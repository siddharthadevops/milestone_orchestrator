"""Product-neutral brainstorming session contracts and durable state.

This module owns accepted configuration, lifecycle state, durable participant
session references, the accepted ordered discussion, and its human transcript.
Service routes and product adapters belong to later slices.
"""

from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import dataclass

from orchestrator import contracts, kvstore

try:
    import fcntl
except ImportError:  # pragma: no cover - the production service is POSIX
    fcntl = None


STATUSES = ("created", "running", "success", "failure")
TERMINAL_STATUSES = ("success", "failure")
CLOSURE_POLICIES = ("unanimity", "majority_with_lead_tiebreak")
ROLES = ("lead", "interlocutor")
TRANSCRIPT_EVENT_KINDS = ("material_interruption", "closure_ballot")
TRANSCRIPT_FORMAT_VERSION = 1

_ALLOWED_TRANSITIONS = {
    "created": ("running", "failure"),
    "running": ("success", "failure"),
    "success": (),
    "failure": (),
}
_SESSION_KEY_PREFIX = "brainstorming/session:"
_TARGET_REVISION_KEY_PREFIX = "brainstorming/target_revision:"
_TURN_ATTEMPT_KEY_PREFIX = "brainstorming/turn_attempt:"
_TARGET_REVISION_ID_PREFIX = "brainstorming-sha256:"
_TARGET_REVISION_ID_RE = re.compile(
    r"^brainstorming-sha256:[0-9a-f]{64}$"
)
_COORDINATION_FIELDS = (
    "completed_turns",
    "rounds_used",
    "accepted_target_revision",
)
_TRANSCRIPT_LOCKS = {}
_TRANSCRIPT_LOCKS_GUARD = threading.Lock()


class ContractError(contracts.ContractError):
    """A request, configuration, state, or result violates its contract."""


class IllegalTransition(RuntimeError):
    """A session lifecycle move is not allowed."""


class HistoryRewriteError(RuntimeError):
    """A durable session update rewrites already committed facts."""


class SessionNotFound(LookupError):
    """No durable session exists for the supplied identifier."""


class SessionAlreadyExists(RuntimeError):
    """Creation attempted to replace an existing durable session."""


class RevisionConflict(RuntimeError):
    """A stale writer attempted to replace a newer durable session."""

    def __init__(self, current):
        super().__init__("session revision is stale")
        self.current = current


@dataclass(frozen=True)
class SessionSnapshot:
    revision: int
    state: dict


def _thread_transcript_lock(path):
    with _TRANSCRIPT_LOCKS_GUARD:
        lock = _TRANSCRIPT_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _TRANSCRIPT_LOCKS[path] = lock
        return lock


@contextlib.contextmanager
def _exclusive_transcript(path):
    """Serialize complete transcript projections across threads and processes."""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    lock_path = path + ".lock"
    with _thread_transcript_lock(lock_path):
        handle = open(lock_path, "a+", encoding="utf-8")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            handle.close()


def _atomic_replace_utf8(path, content):
    """Expose one complete UTF-8 file snapshot using the accepted KV pattern."""
    encoded = content.encode("utf-8")
    try:
        with open(path, "rb") as handle:
            if handle.read() == encoded:
                return
    except FileNotFoundError:
        pass
    fd, temporary = tempfile.mkstemp(
        prefix=".chat-", suffix=".md", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _aliases_transcript_inode(transcript_root, target_path):
    """Return whether a caller path hard-links any transcript artifact."""
    try:
        target_stat = os.stat(target_path)
        session_directories = os.scandir(transcript_root)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return False
    with session_directories:
        for session_directory in session_directories:
            if not session_directory.is_dir(follow_symlinks=False):
                continue
            for name in ("chat.md", "chat.md.lock"):
                try:
                    artifact_stat = os.stat(
                        os.path.join(session_directory.path, name)
                    )
                except (FileNotFoundError, OSError):
                    continue
                if (
                    artifact_stat.st_dev,
                    artifact_stat.st_ino,
                ) == (target_stat.st_dev, target_stat.st_ino):
                    return True
    return False


def _filesystem_ignores_case(path):
    """Detect or conservatively assume case aliases without probe writes."""
    existing = os.path.realpath(os.path.abspath(path))
    while not os.path.lexists(existing):
        parent = os.path.dirname(existing)
        if parent == existing:
            return False
        existing = parent
    while True:
        if os.path.ismount(existing):
            # The mount's parent cannot reveal the mounted filesystem's case
            # behavior. Treat it as uncertain so admission stays read-only.
            return True
        parent = os.path.dirname(existing)
        if parent == existing:
            return False
        name = os.path.basename(existing)
        alias = name.swapcase()
        if alias != name:
            try:
                return os.path.samefile(
                    existing, os.path.join(parent, alias)
                )
            except (FileNotFoundError, OSError):
                return False
        existing = parent


def _existing_ancestor_chain(path):
    """Return existing ancestors with each path's unresolved component tail."""
    existing = os.path.abspath(path)
    tail = ()
    while not os.path.lexists(existing):
        parent, name = os.path.split(existing)
        if parent == existing:
            return ()
        tail = (name,) + tail
        existing = parent
    chain = []
    while True:
        chain.append((existing, tail))
        parent, name = os.path.split(existing)
        if parent == existing:
            return tuple(chain)
        tail = (name,) + tail
        existing = parent


def _tails_overlap_on_filesystem(first, second, filesystem_path):
    """Compare unresolved tails using their shared existing filesystem."""
    ignores_case = _filesystem_ignores_case(filesystem_path)

    def normalized(tail):
        # Canonically equivalent unresolved names may become one path under
        # directory-local filesystem policy. Refuse that ambiguity without
        # probing or modifying the caller's directory.
        tail = tuple(
            unicodedata.normalize("NFC", component) for component in tail
        )
        if ignores_case:
            tail = tuple(component.casefold() for component in tail)
        return tail

    first = normalized(first)
    second = normalized(second)
    shared_length = min(len(first), len(second))
    return first[:shared_length] == second[:shared_length]


def _paths_overlap_from_existing_ancestor(first, second):
    """Resolve aliases before applying one filesystem's name behavior."""
    first_chain = _existing_ancestor_chain(first)
    second_chain = _existing_ancestor_chain(second)
    for first_ancestor, first_tail in first_chain:
        for second_ancestor, second_tail in second_chain:
            try:
                same_ancestor = os.path.samefile(
                    first_ancestor, second_ancestor
                )
            except (FileNotFoundError, OSError):
                same_ancestor = False
            if same_ancestor:
                return _tails_overlap_on_filesystem(
                    first_tail, second_tail, first_ancestor
                )
    return False


def _target_overlaps_state_storage(store_path, target_path):
    """Return whether target names Brainstorming's durable state or lock."""
    target_path = os.path.abspath(target_path)
    for authority_path in (
        os.path.abspath(store_path),
        os.path.abspath(store_path) + ".lock",
    ):
        if os.path.realpath(target_path) == os.path.realpath(authority_path):
            return True
        if _paths_overlap_from_existing_ancestor(
            authority_path, target_path
        ):
            return True
        try:
            if os.path.samefile(target_path, authority_path):
                return True
        except (FileNotFoundError, OSError):
            pass
    return False


def _target_overlaps_transcript_storage(
    transcript_root, target_path, transcript_path=None
):
    """Check transcript authority aliases without creating its directories."""
    transcript_root = os.path.abspath(transcript_root)
    target_path = os.path.abspath(target_path)
    target_real = os.path.realpath(target_path)
    transcript_root_real = os.path.realpath(transcript_root)
    try:
        common = os.path.commonpath((target_real, transcript_root_real))
    except ValueError:
        common = None
    if common in (target_real, transcript_root_real):
        return True
    if _paths_overlap_from_existing_ancestor(
        transcript_root, target_path
    ):
        return True
    if _aliases_transcript_inode(transcript_root, target_path):
        return True
    if transcript_path is None:
        return False
    for authority_path in (
        os.path.abspath(transcript_path),
        os.path.abspath(transcript_path) + ".lock",
    ):
        if os.path.realpath(target_path) == os.path.realpath(authority_path):
            return True
        try:
            if os.path.samefile(target_path, authority_path):
                return True
        except (FileNotFoundError, OSError):
            pass
    return False


def _object(value, ctx):
    if not isinstance(value, dict):
        raise ContractError("%s must be an object" % ctx)
    return value


def _exact_keys(value, required, optional, ctx):
    _object(value, ctx)
    required = set(required)
    allowed = required | set(optional)
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise ContractError("%s is missing %s" % (ctx, missing))
    if extra:
        raise ContractError("%s has unsupported fields %s" % (ctx, extra))


def _text(value, ctx):
    if not isinstance(value, str) or not value.strip():
        raise ContractError("%s must be a non-empty string" % ctx)
    return value


def _json_copy(value, ctx):
    try:
        return kvstore.canonical_json_value(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("%s must be JSON-compatible" % ctx) from exc


def _same_json_value(left, right):
    """Compare JSON values without Python's bool/number coercion."""
    options = {
        "sort_keys": True,
        "separators": (",", ":"),
        "ensure_ascii": False,
        "allow_nan": False,
    }
    return json.dumps(left, **options) == json.dumps(right, **options)


def validate_target_revision_id(revision):
    """Validate one Brainstorming-owned target revision identifier."""
    _text(revision, "target revision")
    if _TARGET_REVISION_ID_RE.fullmatch(revision) is None:
        raise ContractError("target revision is not a Brainstorming revision")
    return revision


def make_target_revision(exists, content, mode):
    """Retain exact target bytes and functional mode under a derived id."""
    if type(exists) is not bool:
        raise ContractError("target revision exists must be a boolean")
    if not isinstance(content, bytes):
        raise ContractError("target revision content must be bytes")
    if not exists and content:
        raise ContractError("an absent target revision cannot carry content")
    if exists:
        if type(mode) is not int or mode < 0 or mode > 0o7777:
            raise ContractError(
                "target revision mode must be POSIX permission bits"
            )
        mode_marker = mode.to_bytes(2, "big")
    else:
        if mode is not None:
            raise ContractError("an absent target revision cannot carry a mode")
        mode_marker = b""
    marker = b"\x01" if exists else b"\x00"
    revision = _TARGET_REVISION_ID_PREFIX + hashlib.sha256(
        marker + mode_marker + content
    ).hexdigest()
    return {
        "revision": revision,
        "exists": exists,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "mode": mode,
    }


def validate_target_revision(target_revision):
    """Validate one exact, recoverable target revision record."""
    _exact_keys(
        target_revision,
        ("revision", "exists", "content_base64", "mode"),
        (),
        "target_revision",
    )
    revision = validate_target_revision_id(target_revision["revision"])
    exists = target_revision["exists"]
    if type(exists) is not bool:
        raise ContractError("target_revision.exists must be a boolean")
    encoded = target_revision["content_base64"]
    if not isinstance(encoded, str):
        raise ContractError("target_revision.content_base64 must be a string")
    try:
        content = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ContractError(
            "target_revision.content_base64 is invalid"
        ) from exc
    mode = target_revision["mode"]
    expected = make_target_revision(exists, content, mode)
    if revision != expected["revision"]:
        raise ContractError("target_revision state does not match its id")
    return expected


def target_revision_content(target_revision):
    """Return the exact existence bit and bytes from a checked revision."""
    checked = validate_target_revision(target_revision)
    return (
        checked["exists"],
        base64.b64decode(checked["content_base64"].encode("ascii")),
    )


def target_revision_mode(target_revision):
    """Return the retained POSIX mode, or ``None`` for an absent target."""
    return validate_target_revision(target_revision)["mode"]


def validate_turn_attempt(turn_attempt):
    """Validate crash-surviving control state for one exclusive worker."""
    _exact_keys(
        turn_attempt,
        (
            "token",
            "participant_id",
            "completed_turn_count",
            "target_revision",
            "quiescent",
        ),
        ("target_parent", "kind"),
        "turn_attempt",
    )
    checked = {
        "token": _text(turn_attempt["token"], "turn_attempt.token"),
        "participant_id": _text(
            turn_attempt["participant_id"], "turn_attempt.participant_id"
        ),
        "completed_turn_count": turn_attempt["completed_turn_count"],
        "target_revision": validate_target_revision_id(
            turn_attempt["target_revision"]
        ),
        "quiescent": turn_attempt["quiescent"],
    }
    if "kind" in turn_attempt:
        if turn_attempt["kind"] not in ("discussion_turn", "closure"):
            raise ContractError(
                "turn_attempt.kind must be discussion_turn or closure"
            )
        checked["kind"] = turn_attempt["kind"]
    if "target_parent" in turn_attempt:
        parent = turn_attempt["target_parent"]
        _exact_keys(
            parent,
            ("path", "device", "inode"),
            (),
            "turn_attempt.target_parent",
        )
        checked["target_parent"] = {
            "path": _text(
                parent["path"], "turn_attempt.target_parent.path"
            ),
            "device": parent["device"],
            "inode": parent["inode"],
        }
        if (
            type(checked["target_parent"]["device"]) is not int
            or checked["target_parent"]["device"] < 0
            or type(checked["target_parent"]["inode"]) is not int
            or checked["target_parent"]["inode"] < 0
        ):
            raise ContractError(
                "turn_attempt.target_parent device and inode must be "
                "non-negative integers"
            )
    if (
        type(checked["completed_turn_count"]) is not int
        or checked["completed_turn_count"] < 0
    ):
        raise ContractError(
            "turn_attempt.completed_turn_count must be a non-negative integer"
        )
    if type(checked["quiescent"]) is not bool:
        raise ContractError("turn_attempt.quiescent must be a boolean")
    return checked


def _validate_participant(participant, ctx):
    _exact_keys(
        participant,
        ("id", "role", "executor_ref", "model_family"),
        (),
        ctx,
    )
    checked = {
        "id": _text(participant["id"], "%s.id" % ctx),
        "role": participant["role"],
        "executor_ref": _text(
            participant["executor_ref"], "%s.executor_ref" % ctx
        ),
        "model_family": _text(
            participant["model_family"], "%s.model_family" % ctx
        ),
    }
    if checked["role"] not in ROLES:
        raise ContractError("%s.role must be one of %s" % (ctx, ROLES))
    return checked


def validate_request(request):
    """Validate and return a detached JSON-compatible request copy."""
    _exact_keys(
        request,
        ("workspace_path", "target_path", "question", "context", "max_rounds"),
        (),
        "request",
    )
    for key in ("workspace_path", "target_path", "question"):
        _text(request[key], "request.%s" % key)
    if type(request["max_rounds"]) is not int or request["max_rounds"] <= 0:
        raise ContractError("request.max_rounds must be a positive integer")

    context = request["context"]
    _exact_keys(
        context, ("brief",), ("references", "source_payload"), "request.context"
    )
    _text(context["brief"], "request.context.brief")
    if "references" in context:
        references = context["references"]
        if not isinstance(references, list):
            raise ContractError("request.context.references must be a list")
        for index, reference in enumerate(references):
            _text(reference, "request.context.references[%d]" % index)
    if "source_payload" in context:
        _json_copy(context["source_payload"], "request.context.source_payload")
    return _json_copy(request, "request")


def validate_run_config(run_config):
    """Validate an already resolved roster and closure selection."""
    _exact_keys(
        run_config,
        ("participants", "closure_policy", "same_family_fallback"),
        (),
        "run_config",
    )
    participants = run_config["participants"]
    if not isinstance(participants, list):
        raise ContractError("run_config.participants must be a list")

    ids = set()
    lead_count = 0
    interlocutor_count = 0
    families = set()
    for index, participant in enumerate(participants):
        ctx = "run_config.participants[%d]" % index
        checked = _validate_participant(participant, ctx)
        participant_id = checked["id"]
        if participant_id in ids:
            raise ContractError("participant ids must be unique")
        ids.add(participant_id)
        role = checked["role"]
        lead_count += role == "lead"
        interlocutor_count += role == "interlocutor"
        families.add(checked["model_family"])

    if lead_count != 1:
        raise ContractError("run_config must contain exactly one lead")
    if interlocutor_count < 1:
        raise ContractError("run_config must contain at least one interlocutor")
    if run_config["closure_policy"] not in CLOSURE_POLICIES:
        raise ContractError(
            "run_config.closure_policy must be one of %s" % (CLOSURE_POLICIES,)
        )
    fallback = run_config["same_family_fallback"]
    if type(fallback) is not bool:
        raise ContractError("run_config.same_family_fallback must be a boolean")
    expected_fallback = len(families) == 1
    if fallback is not expected_fallback:
        raise ContractError(
            "same_family_fallback must record whether the resolved roster "
            "uses only one model family"
        )
    return _json_copy(run_config, "run_config")


def validate_participant_sessions(participant_sessions, run_config):
    """Validate the write-once participant-to-provider-session projection."""
    _object(participant_sessions, "participant_sessions")
    checked_config = validate_run_config(run_config)
    participants = {
        participant["id"]: participant
        for participant in checked_config["participants"]
    }
    unknown = sorted(set(participant_sessions) - set(participants))
    if unknown:
        raise ContractError(
            "participant_sessions has unknown participant ids %s" % unknown
        )

    seen = set()
    for participant_id, session_ref in participant_sessions.items():
        _text(session_ref, "participant_sessions.%s" % participant_id)
        executor_ref = participants[participant_id]["executor_ref"]
        prefix = executor_ref + ":"
        if (
            not session_ref.startswith(prefix)
            or not session_ref[len(prefix):].strip()
        ):
            raise ContractError(
                "participant_sessions.%s must be namespaced by executor_ref"
                % participant_id
            )
        if session_ref in seen:
            raise ContractError(
                "participant session references must be unique"
            )
        seen.add(session_ref)
    return _json_copy(participant_sessions, "participant_sessions")


def make_participant_session_ref(executor_ref, provider_session_ref):
    """Namespace one opaque provider reference by its persisted executor."""
    executor_ref = _text(executor_ref, "executor_ref")
    provider_session_ref = _text(
        provider_session_ref, "provider_session_ref"
    )
    return "%s:%s" % (executor_ref, provider_session_ref)


def provider_session_ref(executor_ref, participant_session_ref):
    """Recover the opaque provider reference after checking its namespace."""
    executor_ref = _text(executor_ref, "executor_ref")
    participant_session_ref = _text(
        participant_session_ref, "participant_session_ref"
    )
    prefix = executor_ref + ":"
    if (
        not participant_session_ref.startswith(prefix)
        or not participant_session_ref[len(prefix):].strip()
    ):
        raise ContractError(
            "participant_session_ref does not match executor_ref"
        )
    return participant_session_ref[len(prefix):]


def coordination_projection(state):
    """Return the accepted ordered-discussion fields, or ``None``."""
    present = {field for field in _COORDINATION_FIELDS if field in state}
    if not present:
        return None
    if present != set(_COORDINATION_FIELDS):
        raise ContractError(
            "accepted coordination fields must be present together"
        )
    return {
        field: copy.deepcopy(state[field]) for field in _COORDINATION_FIELDS
    }


def _validate_coordination(state, request, run_config, status):
    projection = coordination_projection(state)
    if projection is None:
        return None
    if status == "created":
        raise ContractError(
            "created sessions cannot have accepted coordination state"
        )

    turns = projection["completed_turns"]
    if not isinstance(turns, list):
        raise ContractError("state.completed_turns must be a list")
    rounds_used = projection["rounds_used"]
    if type(rounds_used) is not int or rounds_used < 0:
        raise ContractError(
            "state.rounds_used must be a non-negative integer"
        )
    accepted_revision = validate_target_revision_id(
        projection["accepted_target_revision"]
    )
    participants = run_config["participants"]
    turn_limit = request["max_rounds"] * len(participants)
    if len(turns) > turn_limit:
        raise ContractError("completed turns exceed request.max_rounds")

    previous_revision = None
    for index, turn in enumerate(turns):
        ctx = "state.completed_turns[%d]" % index
        _exact_keys(
            turn,
            ("round", "participant_id", "markdown", "target_revision"),
            (),
            ctx,
        )
        participant = participants[index % len(participants)]
        expected_round = index // len(participants) + 1
        if type(turn["round"]) is not int or turn["round"] != expected_round:
            raise ContractError("%s.round does not follow roster order" % ctx)
        if turn["participant_id"] != participant["id"]:
            raise ContractError(
                "%s.participant_id does not follow roster order" % ctx
            )
        _text(turn["markdown"], "%s.markdown" % ctx)
        revision = validate_target_revision_id(turn["target_revision"])
        if (
            previous_revision is not None
            and revision != previous_revision
            and participant["role"] != "lead"
        ):
            raise ContractError(
                "%s changes the target revision outside a lead turn" % ctx
            )
        previous_revision = revision

    expected_rounds = len(turns) // len(participants)
    if rounds_used != expected_rounds:
        raise ContractError(
            "state.rounds_used must count only complete roster passes"
        )
    if rounds_used > request["max_rounds"]:
        raise ContractError("state.rounds_used exceeds request.max_rounds")
    if turns and turns[-1]["target_revision"] != accepted_revision:
        raise ContractError(
            "accepted_target_revision must match the latest completed turn"
        )
    return {
        "completed_turns": _json_copy(turns, "state.completed_turns"),
        "rounds_used": rounds_used,
        "accepted_target_revision": accepted_revision,
    }


def _validate_eligible_participants(eligible_participants):
    eligible = _json_copy(eligible_participants, "eligible_participants")
    if not isinstance(eligible, list) or not eligible:
        raise ContractError("eligible_participants must be a non-empty list")
    roles_by_id = {}
    unique_assignments = []
    for index, participant in enumerate(eligible):
        ctx = "eligible_participants[%d]" % index
        checked = _validate_participant(participant, ctx)
        existing_role = roles_by_id.setdefault(checked["id"], checked["role"])
        if existing_role != checked["role"]:
            raise ContractError(
                "an eligible participant id cannot change roles"
            )
        if any(_same_json_value(checked, item) for item in unique_assignments):
            raise ContractError("eligible participant assignments must be unique")
        unique_assignments.append(checked)
    return eligible


def _cross_family_roster_available(eligible, interlocutor_count):
    leads = [item for item in eligible if item["role"] == "lead"]
    interlocutors = [
        item for item in eligible if item["role"] == "interlocutor"
    ]
    for lead in leads:
        available_ids = {
            item["id"] for item in interlocutors if item["id"] != lead["id"]
        }
        if len(available_ids) < interlocutor_count:
            continue
        if any(
            item["id"] != lead["id"]
            and item["model_family"] != lead["model_family"]
            for item in interlocutors
        ):
            return True
    return False


def resolve_run_config(participants, closure_policy, eligible_participants):
    """Validate chosen assignments against the complete eligible roster."""
    participants = _json_copy(participants, "participants")
    families = {
        participant.get("model_family")
        for participant in participants
        if (
            isinstance(participant, dict)
            and isinstance(participant.get("model_family"), str)
        )
    } if isinstance(participants, list) else set()
    run_config = {
        "participants": participants,
        "closure_policy": closure_policy,
        "same_family_fallback": len(families) == 1,
    }
    checked = validate_run_config(run_config)
    eligible = _validate_eligible_participants(eligible_participants)
    for participant in checked["participants"]:
        if not any(
            _same_json_value(participant, candidate)
            for candidate in eligible
        ):
            raise ContractError(
                "every selected participant must be an eligible assignment"
            )
    if (
        checked["same_family_fallback"]
        and _cross_family_roster_available(
            eligible,
            sum(
                item["role"] == "interlocutor"
                for item in checked["participants"]
            ),
        )
    ):
        raise ContractError(
            "same-family fallback is invalid while a cross-family roster "
            "is eligible"
        )
    return checked


def _transcript_event_boundary(event, participant_count):
    fact = event["fact"]
    if event["kind"] == "material_interruption":
        return fact["after_completed_turns"]
    return fact["after_completed_rounds"] * participant_count


def _validate_transcript_events(events, run_config, coordination):
    if not isinstance(events, list):
        raise ContractError("state.transcript_events must be a list")
    participants = run_config["participants"]
    turns = [] if coordination is None else coordination["completed_turns"]
    previous_boundary = -1
    ballot_rounds = set()
    checked = []
    for index, event in enumerate(events):
        ctx = "state.transcript_events[%d]" % index
        _exact_keys(event, ("kind", "fact"), (), ctx)
        kind = event["kind"]
        if kind not in TRANSCRIPT_EVENT_KINDS:
            raise ContractError("%s.kind is invalid" % ctx)
        if kind == "material_interruption":
            fact = validate_material_interruption(event["fact"])
        else:
            fact = validate_closure_ballot(event["fact"], run_config)
        candidate = {"kind": kind, "fact": fact}
        if any(
            _same_json_value(accepted, candidate)
            for accepted in checked
        ):
            raise ContractError(
                "state.transcript_events cannot repeat an accepted event"
            )
        boundary = _transcript_event_boundary(
            candidate, len(participants)
        )
        if boundary < previous_boundary:
            raise ContractError(
                "state.transcript_events must retain accepted append order"
            )
        if boundary > len(turns):
            raise ContractError(
                "a transcript event cannot precede its accepted discussion"
            )
        if kind == "closure_ballot":
            if coordination is None:
                raise ContractError(
                    "closure ballots require accepted coordination state"
                )
            if fact["after_completed_rounds"] > coordination["rounds_used"]:
                raise ContractError(
                    "closure ballot round exceeds durable completed rounds"
                )
            if (
                not turns
                or turns[boundary - 1]["target_revision"]
                != fact["target_revision"]
            ):
                raise ContractError(
                    "closure ballot target revision does not match its round"
                )
            ballot_round = fact["after_completed_rounds"]
            if ballot_round in ballot_rounds:
                raise ContractError(
                    "only one closure ballot may be accepted per completed round"
                )
            ballot_rounds.add(ballot_round)
        previous_boundary = boundary
        checked.append(candidate)
    return checked


def validate_transcript_ref(transcript_ref):
    """Validate one stable reference to a Brainstorming-owned ``chat.md``."""
    transcript_ref = _text(transcript_ref, "state.transcript_ref")
    if not os.path.isabs(transcript_ref):
        raise ContractError("state.transcript_ref must be an absolute path")
    if os.path.basename(transcript_ref) != "chat.md":
        raise ContractError("state.transcript_ref must end in chat.md")
    return os.path.abspath(transcript_ref)


def validate_material_interruption(interruption):
    """Validate one explicitly classified, human-safe interruption fact."""
    _exact_keys(
        interruption,
        ("after_completed_turns", "plain"),
        (),
        "material_interruption",
    )
    after = interruption["after_completed_turns"]
    if type(after) is not int or after < 0:
        raise ContractError(
            "material_interruption.after_completed_turns must be a "
            "non-negative integer"
        )
    _text(interruption["plain"], "material_interruption.plain")
    return _json_copy(interruption, "material_interruption")


def _validate_closure_votes(votes, run_config):
    checked_config = validate_run_config(run_config)
    participants = checked_config["participants"]
    if not isinstance(votes, list) or len(votes) != len(participants):
        raise ContractError(
            "closure_ballot.votes must contain every participant once"
        )
    checked_votes = []
    for index, (vote, participant) in enumerate(zip(votes, participants)):
        ctx = "closure_ballot.votes[%d]" % index
        _exact_keys(vote, ("participant_id", "vote"), (), ctx)
        if vote["participant_id"] != participant["id"]:
            raise ContractError(
                "closure_ballot.votes must follow the persisted roster"
            )
        if vote["vote"] not in ("accept", "object"):
            raise ContractError("%s.vote must be accept or object" % ctx)
        if participant["role"] == "lead" and vote["vote"] != "accept":
            raise ContractError(
                "the lead closure proposal must be recorded as accept"
            )
        checked_votes.append(
            {"participant_id": vote["participant_id"], "vote": vote["vote"]}
        )
    return checked_config, checked_votes


def _closure_decision(checked_config, checked_votes):
    accepts = sum(vote["vote"] == "accept" for vote in checked_votes)
    objects = len(checked_votes) - accepts
    if checked_config["closure_policy"] == "unanimity":
        return accepts == len(checked_votes)
    if accepts != objects:
        return accepts > objects
    lead_id = next(
        participant["id"]
        for participant in checked_config["participants"]
        if participant["role"] == "lead"
    )
    return next(
        vote["vote"] == "accept"
        for vote in checked_votes
        if vote["participant_id"] == lead_id
    )


def evaluate_closure(run_config, votes):
    """Apply the persisted closure policy to one exact roster ballot."""
    checked_config, checked_votes = _validate_closure_votes(votes, run_config)
    return _closure_decision(checked_config, checked_votes)


def validate_closure_ballot(ballot, run_config):
    """Validate one complete ballot and derive its policy decision."""
    _exact_keys(
        ballot,
        ("after_completed_rounds", "target_revision", "votes", "approved"),
        (),
        "closure_ballot",
    )
    after = ballot["after_completed_rounds"]
    if type(after) is not int or after <= 0:
        raise ContractError(
            "closure_ballot.after_completed_rounds must be a positive integer"
        )
    validate_target_revision_id(ballot["target_revision"])
    if type(ballot["approved"]) is not bool:
        raise ContractError("closure_ballot.approved must be a boolean")
    checked_config, votes = _validate_closure_votes(
        ballot["votes"], run_config
    )
    approved = _closure_decision(checked_config, votes)
    if ballot["approved"] is not approved:
        raise ContractError(
            "closure_ballot.approved must equal the configured policy decision"
        )
    checked = _json_copy(ballot, "closure_ballot")
    checked["votes"] = votes
    checked["approved"] = approved
    return checked


def validate_closing_summary_shape(summary):
    """Validate the participant-authored fields shared by both outcomes."""
    _exact_keys(
        summary,
        (
            "reason",
            "unresolved_objections",
            "affected_parties",
            "damage_altitude",
            "proportionality",
            "escalation_evidence",
        ),
        (),
        "closing_summary",
    )
    for field in (
        "reason",
        "affected_parties",
        "damage_altitude",
        "proportionality",
    ):
        _text(summary[field], "closing_summary.%s" % field)
    objections = summary["unresolved_objections"]
    if not isinstance(objections, list):
        raise ContractError(
            "closing_summary.unresolved_objections must be a list"
        )
    for index, objection in enumerate(objections):
        _text(
            objection,
            "closing_summary.unresolved_objections[%d]" % index,
        )
    evidence = summary["escalation_evidence"]
    if evidence is not None:
        _text(evidence, "closing_summary.escalation_evidence")
    return _json_copy(summary, "closing_summary")


def validate_closing_summary(summary, terminal_status, result):
    """Validate contextual human facts against one terminal outcome."""
    checked = validate_closing_summary_shape(summary)
    if terminal_status == "failure" and checked["reason"] != result["reason"]:
        raise ContractError(
            "closing_summary.reason must equal the failure result reason"
        )
    return checked


def closing_summary_with_ballot_facts(summary, ballot, run_config):
    """Add strict human objection records derived from one accepted ballot."""
    checked = validate_closing_summary_shape(summary)
    checked_ballot = validate_closure_ballot(ballot, run_config)
    labels = _human_labels(run_config)
    objections = list(checked["unresolved_objections"])
    for item in checked_ballot["votes"]:
        if item["vote"] != "object":
            continue
        record = "%s objected to closure." % labels[item["participant_id"]]
        if record not in objections:
            objections.append(record)
    checked["unresolved_objections"] = objections
    return validate_closing_summary_shape(checked)


def validate_result(result, terminal_status, target_path, transcript_ref):
    """Validate the retained representation of a terminal outcome."""
    _object(result, "result")
    outcome = result.get("outcome")
    required = {"outcome", "target_ref", "transcript_ref", "rounds_used"}
    if outcome == "failure":
        required.add("reason")
    _exact_keys(result, required, (), "result")
    if terminal_status not in TERMINAL_STATUSES or outcome != terminal_status:
        raise ContractError("result.outcome must match the terminal status")
    if outcome not in TERMINAL_STATUSES:
        raise ContractError("result.outcome must be success or failure")
    target_ref = _text(result["target_ref"], "result.target_ref")
    if target_ref != target_path:
        raise ContractError("result.target_ref must equal request.target_path")
    checked_transcript_ref = _text(
        result["transcript_ref"], "result.transcript_ref"
    )
    if checked_transcript_ref != transcript_ref:
        raise ContractError(
            "result.transcript_ref must equal state.transcript_ref"
        )
    rounds_used = result["rounds_used"]
    if type(rounds_used) is not int or rounds_used < 0:
        raise ContractError("result.rounds_used must be a non-negative integer")
    if outcome == "failure":
        _text(result["reason"], "result.reason")
    return _json_copy(result, "result")


def _validate_closure_lifecycle(status, request, coordination, events):
    ballots = [
        event["fact"]
        for event in events
        if event["kind"] == "closure_ballot"
    ]
    approved = [ballot for ballot in ballots if ballot["approved"]]
    if status != "success" and approved:
        raise ContractError(
            "an approving closure ballot must become success atomically"
        )
    if status == "success":
        if coordination is None or not ballots:
            raise ContractError(
                "success requires a current approving closure ballot"
            )
        ballot = ballots[-1]
        if (
            len(approved) != 1
            or not ballot["approved"]
            or ballot["after_completed_rounds"]
            != coordination["rounds_used"]
            or ballot["target_revision"]
            != coordination["accepted_target_revision"]
            or events[-1]["kind"] != "closure_ballot"
        ):
            raise ContractError(
                "success requires the current accepted target ballot"
            )
    if (
        status == "running"
        and coordination is not None
        and coordination["rounds_used"] == request["max_rounds"]
        and ballots
    ):
        ballot = ballots[-1]
        if (
            ballot["after_completed_rounds"] == coordination["rounds_used"]
            and ballot["target_revision"]
            == coordination["accepted_target_revision"]
        ):
            raise ContractError(
                "a final non-approving ballot must become failure atomically"
            )


def _current_closure_ballot(events, run_config, coordination):
    if coordination is None:
        return None
    participant_count = len(run_config["participants"])
    turns = coordination["completed_turns"]
    for event in reversed(events):
        if event["kind"] != "closure_ballot":
            continue
        ballot = event["fact"]
        boundary = ballot["after_completed_rounds"] * participant_count
        if (
            ballot["target_revision"]
            == coordination["accepted_target_revision"]
            and all(
                turn["target_revision"] == ballot["target_revision"]
                for turn in turns[boundary:]
            )
        ):
            return ballot
    return None


def _validate_history(history, target_path, transcript_ref):
    if not isinstance(history, list) or not history:
        raise ContractError("state.history must be a non-empty list")
    previous = None
    for index, record in enumerate(history):
        ctx = "state.history[%d]" % index
        _object(record, ctx)
        status = record.get("status")
        if status not in STATUSES:
            raise ContractError("%s.status is invalid" % ctx)
        required = (
            ("status", "result", "closing_summary")
            if status in TERMINAL_STATUSES
            else ("status",)
        )
        _exact_keys(record, required, (), ctx)
        if index == 0:
            if record != {"status": "created"}:
                raise ContractError("state.history must begin with created")
        elif status not in _ALLOWED_TRANSITIONS[previous]:
            raise IllegalTransition("%s -> %s is not legal" % (previous, status))
        if status in TERMINAL_STATUSES:
            result = validate_result(
                record["result"], status, target_path, transcript_ref
            )
            validate_closing_summary(
                record["closing_summary"], status, result
            )
        previous = status
    return previous


def validate_session_state(state):
    """Validate and return a detached complete session-state copy."""
    _object(state, "state")
    status = state.get("status")
    if status not in STATUSES:
        raise ContractError("state.status is invalid")
    required = {
        "request",
        "run_config",
        "status",
        "history",
        "transcript_ref",
        "transcript_events",
        "transcript_format_version",
    }
    if status in TERMINAL_STATUSES:
        required.update(("result", "closing_summary"))
    _exact_keys(
        state,
        required,
        ("participant_sessions",) + _COORDINATION_FIELDS,
        "state",
    )
    request = validate_request(state["request"])
    run_config = validate_run_config(state["run_config"])
    transcript_ref = validate_transcript_ref(state["transcript_ref"])
    if "participant_sessions" in state:
        participant_sessions = validate_participant_sessions(
            state["participant_sessions"], run_config
        )
        if status == "created" and participant_sessions:
            raise ContractError(
                "created sessions cannot have participant session references"
            )
    coordination = _validate_coordination(
        state, request, run_config, status
    )
    transcript_events = _validate_transcript_events(
        state["transcript_events"], run_config, coordination
    )
    _validate_closure_lifecycle(
        status, request, coordination, transcript_events
    )
    if state["transcript_format_version"] not in _TRANSCRIPT_RENDERERS:
        raise ContractError("state.transcript_format_version is unsupported")
    last_status = _validate_history(
        state["history"], request["target_path"], transcript_ref
    )
    if last_status != status:
        raise ContractError("state.status must match the last history record")
    if status in TERMINAL_STATUSES:
        result = validate_result(
            state["result"],
            status,
            request["target_path"],
            transcript_ref,
        )
        if not _same_json_value(result, state["history"][-1]["result"]):
            raise ContractError("state.result must match terminal history")
        summary = validate_closing_summary(
            state["closing_summary"], status, result
        )
        terminal_ballot = _current_closure_ballot(
            transcript_events, run_config, coordination
        )
        if terminal_ballot is not None:
            ballot_summary = closing_summary_with_ballot_facts(
                summary, terminal_ballot, run_config
            )
            if not _same_json_value(summary, ballot_summary):
                raise ContractError(
                    "closing_summary must record every terminal object vote"
                )
        if not _same_json_value(
            summary, state["history"][-1]["closing_summary"]
        ):
            raise ContractError(
                "state.closing_summary must match terminal history"
            )
        durable_rounds = (
            0 if coordination is None else coordination["rounds_used"]
        )
        if result["rounds_used"] != durable_rounds:
            raise ContractError(
                "result.rounds_used must equal durable completed rounds"
            )
    return _json_copy(state, "state")


def new_session_state(request, run_config, transcript_ref):
    """Construct a valid, non-running session without performing I/O."""
    state = {
        "request": validate_request(request),
        "run_config": validate_run_config(run_config),
        "status": "created",
        "history": [{"status": "created"}],
        "participant_sessions": {},
        "transcript_ref": validate_transcript_ref(transcript_ref),
        "transcript_events": [],
        "transcript_format_version": TRANSCRIPT_FORMAT_VERSION,
    }
    return validate_session_state(state)


def transition_session(
    state, new_status, result=None, closing_summary=None
):
    """Return one legal whole-state successor without mutating ``state``."""
    current = validate_session_state(state)
    old_status = current["status"]
    if new_status not in _ALLOWED_TRANSITIONS[old_status]:
        raise IllegalTransition("%s -> %s is not legal" % (old_status, new_status))
    if new_status in TERMINAL_STATUSES:
        checked_result = validate_result(
            result,
            new_status,
            current["request"]["target_path"],
            current["transcript_ref"],
        )
        terminal_ballot = _current_closure_ballot(
            current["transcript_events"],
            current["run_config"],
            coordination_projection(current),
        )
        if terminal_ballot is not None:
            closing_summary = closing_summary_with_ballot_facts(
                closing_summary,
                terminal_ballot,
                current["run_config"],
            )
        checked_summary = validate_closing_summary(
            closing_summary, new_status, checked_result
        )
    elif result is not None:
        raise ContractError("nonterminal transitions cannot carry a result")
    elif closing_summary is not None:
        raise ContractError(
            "nonterminal transitions cannot carry a closing summary"
        )
    else:
        checked_result = None
        checked_summary = None

    successor = copy.deepcopy(current)
    successor["status"] = new_status
    record = {"status": new_status}
    if checked_result is not None:
        successor["result"] = checked_result
        successor["closing_summary"] = checked_summary
        record["result"] = copy.deepcopy(checked_result)
        record["closing_summary"] = copy.deepcopy(checked_summary)
    successor["history"].append(record)
    return validate_session_state(successor)


def assert_session_successor(old_state, new_state):
    """Reject rewrites and accept exactly one legal appended transition."""
    old = validate_session_state(old_state)
    new = validate_session_state(new_state)
    if not _same_json_value(old["request"], new["request"]):
        raise HistoryRewriteError("accepted request is immutable")
    if not _same_json_value(old["run_config"], new["run_config"]):
        raise HistoryRewriteError("resolved run configuration is immutable")
    old_history = old["history"]
    new_history = new["history"]
    if len(new_history) < len(old_history):
        raise HistoryRewriteError("session history shrank")
    if not _same_json_value(new_history[:len(old_history)], old_history):
        raise HistoryRewriteError("completed session history was modified")
    if len(new_history) != len(old_history) + 1:
        raise HistoryRewriteError("an update must append exactly one transition")
    appended = new_history[-1]
    expected = transition_session(
        old,
        appended["status"],
        appended.get("result"),
        appended.get("closing_summary"),
    )
    if not _same_json_value(expected, new):
        raise HistoryRewriteError("state is not the exact next session revision")


def assert_participant_session_successor(
    old_state, new_state, participant_id, session_ref
):
    """Accept exactly one write-once participant-session binding."""
    old = validate_session_state(old_state)
    new = validate_session_state(new_state)
    if old["status"] != "running" or new["status"] != "running":
        raise IllegalTransition(
            "participant sessions can only bind while running"
        )
    for field in (
        "request",
        "run_config",
        "status",
        "history",
        "result",
        "closing_summary",
        "transcript_ref",
        "transcript_events",
        "transcript_format_version",
    ):
        if not _same_json_value(old.get(field), new.get(field)):
            raise HistoryRewriteError(
                "participant binding changed session field %s" % field
            )
    if not _same_json_value(
        coordination_projection(old), coordination_projection(new)
    ):
        raise HistoryRewriteError(
            "participant binding changed accepted coordination state"
        )

    old_sessions = old.get("participant_sessions", {})
    if participant_id in old_sessions:
        raise HistoryRewriteError(
            "participant session reference is already bound"
        )
    expected = copy.deepcopy(old_sessions)
    expected[participant_id] = session_ref
    if not _same_json_value(new.get("participant_sessions", {}), expected):
        raise HistoryRewriteError(
            "participant binding must add exactly one session reference"
        )


def initialize_coordination_state(state, target_revision):
    """Add the empty accepted-discussion projection to a running session."""
    current = validate_session_state(state)
    if current["status"] != "running":
        raise IllegalTransition(
            "accepted coordination can only initialize while running"
        )
    if coordination_projection(current) is not None:
        raise HistoryRewriteError("accepted coordination is already initialized")
    checked_revision = validate_target_revision(target_revision)
    successor = copy.deepcopy(current)
    successor.update(
        {
            "completed_turns": [],
            "rounds_used": 0,
            "accepted_target_revision": checked_revision["revision"],
        }
    )
    return validate_session_state(successor)


def assert_coordination_initialization_successor(old_state, new_state):
    """Accept exactly the first empty coordination projection."""
    old = validate_session_state(old_state)
    new = validate_session_state(new_state)
    if coordination_projection(old) is not None:
        raise HistoryRewriteError("accepted coordination is already initialized")
    revision = new.get("accepted_target_revision")
    expected = copy.deepcopy(old)
    expected.update(
        {
            "completed_turns": [],
            "rounds_used": 0,
            "accepted_target_revision": revision,
        }
    )
    validate_target_revision_id(revision)
    if not _same_json_value(validate_session_state(expected), new):
        raise HistoryRewriteError(
            "coordination initialization changed unrelated session state"
        )


def completed_turn_successor(
    state, participant_id, markdown, target_revision
):
    """Append exactly the next roster turn and complete a pass if applicable."""
    current = validate_session_state(state)
    if current["status"] != "running":
        raise IllegalTransition("completed turns require a running session")
    if coordination_projection(current) is None:
        raise HistoryRewriteError("accepted coordination is not initialized")
    participant_id = _text(participant_id, "participant_id")
    markdown = _text(markdown, "discussion_turn.markdown")
    target_revision = validate_target_revision_id(target_revision)
    participants = current["run_config"]["participants"]
    turn_index = len(current["completed_turns"])
    if turn_index >= current["request"]["max_rounds"] * len(participants):
        raise IllegalTransition("the configured round limit is exhausted")
    participant = participants[turn_index % len(participants)]
    if participant_id != participant["id"]:
        raise HistoryRewriteError(
            "completed turn does not match the next persisted participant"
        )
    if (
        target_revision != current["accepted_target_revision"]
        and participant["role"] != "lead"
    ):
        raise HistoryRewriteError(
            "only a completed lead turn may advance the target revision"
        )

    successor = copy.deepcopy(current)
    round_number = turn_index // len(participants) + 1
    successor["completed_turns"].append(
        {
            "round": round_number,
            "participant_id": participant_id,
            "markdown": markdown,
            "target_revision": target_revision,
        }
    )
    successor["accepted_target_revision"] = target_revision
    if (turn_index + 1) % len(participants) == 0:
        successor["rounds_used"] += 1
    return validate_session_state(successor)


def assert_completed_turn_successor(
    old_state, new_state, participant_id, markdown, target_revision
):
    """Accept one exact append-only ordered-turn successor."""
    old = validate_session_state(old_state)
    new = validate_session_state(new_state)
    expected = completed_turn_successor(
        old, participant_id, markdown, target_revision
    )
    if not _same_json_value(expected, new):
        raise HistoryRewriteError(
            "completed turn is not the exact next coordination revision"
        )


def _closure_ballot_at_current_boundary(state, fact):
    coordination = coordination_projection(state)
    if state["status"] != "running" or coordination is None:
        raise IllegalTransition(
            "closure ballots require accepted running discussion"
        )
    checked_fact = validate_closure_ballot(fact, state["run_config"])
    participant_count = len(state["run_config"]["participants"])
    if (
        len(coordination["completed_turns"])
        != coordination["rounds_used"] * participant_count
        or checked_fact["after_completed_rounds"]
        != coordination["rounds_used"]
        or checked_fact["target_revision"]
        != coordination["accepted_target_revision"]
    ):
        raise HistoryRewriteError(
            "closure ballot must match the current completed round "
            "and accepted target revision"
        )
    if any(
        event["kind"] == "closure_ballot"
        and event["fact"]["after_completed_rounds"]
        == checked_fact["after_completed_rounds"]
        for event in state["transcript_events"]
    ):
        raise HistoryRewriteError(
            "another complete discussion round is required before a new ballot"
        )
    return checked_fact


def transcript_event_successor(state, kind, fact):
    """Append one explicit human event at the current discussion boundary."""
    current = validate_session_state(state)
    if current["status"] in TERMINAL_STATUSES:
        raise IllegalTransition(
            "terminal sessions cannot append transcript events"
        )
    coordination = coordination_projection(current)
    completed_turns = (
        [] if coordination is None else coordination["completed_turns"]
    )
    if kind == "material_interruption":
        checked_fact = validate_material_interruption(fact)
        if checked_fact["after_completed_turns"] != len(completed_turns):
            raise HistoryRewriteError(
                "material interruption must follow current accepted turns"
            )
    elif kind == "closure_ballot":
        checked_fact = _closure_ballot_at_current_boundary(current, fact)
        if checked_fact["approved"]:
            raise IllegalTransition(
                "an approving ballot must become success atomically"
            )
        if coordination["rounds_used"] == current["request"]["max_rounds"]:
            raise IllegalTransition(
                "a final non-approving ballot must become failure atomically"
            )
    else:
        raise ContractError("transcript event kind is invalid")

    successor = copy.deepcopy(current)
    successor["transcript_events"].append(
        {"kind": kind, "fact": checked_fact}
    )
    return validate_session_state(successor)


def terminal_closure_successor(state, ballot, result, closing_summary):
    """Accept one ballot and its derived terminal outcome in one state."""
    current = validate_session_state(state)
    checked_ballot = _closure_ballot_at_current_boundary(current, ballot)
    outcome = "success" if checked_ballot["approved"] else "failure"
    if (
        outcome == "failure"
        and current["rounds_used"] < current["request"]["max_rounds"]
    ):
        raise IllegalTransition(
            "a rejected ballot resumes discussion while rounds remain"
        )
    checked_result = validate_result(
        result,
        outcome,
        current["request"]["target_path"],
        current["transcript_ref"],
    )
    checked_summary = validate_closing_summary(
        closing_summary_with_ballot_facts(
            closing_summary, checked_ballot, current["run_config"]
        ),
        outcome,
        checked_result,
    )

    successor = copy.deepcopy(current)
    successor["transcript_events"].append(
        {"kind": "closure_ballot", "fact": checked_ballot}
    )
    successor["status"] = outcome
    successor["result"] = checked_result
    successor["closing_summary"] = checked_summary
    successor["history"].append(
        {
            "status": outcome,
            "result": copy.deepcopy(checked_result),
            "closing_summary": copy.deepcopy(checked_summary),
        }
    )
    return validate_session_state(successor)


def terminal_interruption_successor(
    state, interruption, result, closing_summary
):
    """Atomically append one interruption and terminal failure.

    Standalone stop cannot publish the human interruption first and the
    failure second: closure could win between those writes.  Compose the two
    already-validated successors into one candidate so the session CAS chooses
    exactly one terminal outcome.
    """
    interrupted = transcript_event_successor(
        state, "material_interruption", interruption
    )
    return transition_session(
        interrupted, "failure", result, closing_summary
    )


def assert_terminal_closure_successor(
    old_state, new_state, ballot, result, closing_summary
):
    """Accept only the exact combined ballot/result/closing successor."""
    old = validate_session_state(old_state)
    new = validate_session_state(new_state)
    expected = terminal_closure_successor(
        old, ballot, result, closing_summary
    )
    if not _same_json_value(expected, new):
        raise HistoryRewriteError(
            "terminal closure is not the exact next session revision"
        )


def assert_terminal_interruption_successor(
    old_state, new_state, interruption, result, closing_summary
):
    """Accept only the exact combined interruption/failure successor."""
    old = validate_session_state(old_state)
    new = validate_session_state(new_state)
    expected = terminal_interruption_successor(
        old, interruption, result, closing_summary
    )
    if not _same_json_value(expected, new):
        raise HistoryRewriteError(
            "terminal interruption is not the exact next session revision"
        )


def assert_transcript_event_successor(old_state, new_state, kind, fact):
    """Accept only the exact next explicit transcript event."""
    old = validate_session_state(old_state)
    new = validate_session_state(new_state)
    expected = transcript_event_successor(old, kind, fact)
    if not _same_json_value(expected, new):
        raise HistoryRewriteError(
            "transcript event is not the exact next session revision"
        )


def _human_labels(run_config):
    labels = {}
    interlocutor = 0
    for participant in run_config["participants"]:
        if participant["role"] == "lead":
            labels[participant["id"]] = "Lead"
        else:
            interlocutor += 1
            labels[participant["id"]] = "Interlocutor %d" % interlocutor
    return labels


def _quoted_markdown(value):
    """Keep supplied Markdown readable without allowing top-level entries."""
    lines = value.splitlines()
    if not lines:
        lines = [""]
    return "\n".join(
        "> " + line if line else ">" for line in lines
    )


def _closure_rule(policy):
    if policy == "unanimity":
        return "Everyone must agree before the session can close."
    return (
        "A majority decides; if the vote is tied exactly, the lead's vote "
        "breaks the tie."
    )


def _entry(title, *parts):
    return "## %s\n\n%s" % (title, "\n\n".join(parts))


def _field(label, value):
    return "**%s**\n\n%s" % (label, value)


def _render_opening(state, labels):
    roster = []
    for participant in state["run_config"]["participants"]:
        label = labels[participant["id"]]
        role = (
            "leads the session"
            if participant["role"] == "lead"
            else "participates as an interlocutor"
        )
        roster.append("- **%s** — %s." % (label, role))
    rounds = state["request"]["max_rounds"]
    return _entry(
        "Opening",
        _field(
            "What is being discussed",
            _quoted_markdown(state["request"]["question"]),
        ),
        _field(
            "Why this discussion is needed",
            _quoted_markdown(state["request"]["context"]["brief"]),
        ),
        _field(
            "Target being worked on",
            _quoted_markdown(state["request"]["target_path"]),
        ),
        _field("Participants", "\n".join(roster)),
        _field(
            "Agreement rule",
            _closure_rule(state["run_config"]["closure_policy"]),
        ),
        _field(
            "Round limit",
            "The discussion may use at most %d round%s."
            % (rounds, "" if rounds == 1 else "s"),
        ),
    )


def _render_turn(turn, labels):
    return _entry(
        "Discussion turn — Round %d — %s"
        % (turn["round"], labels[turn["participant_id"]]),
        _quoted_markdown(turn["markdown"]),
    )


def _render_transcript_event(event, state, labels):
    fact = event["fact"]
    if event["kind"] == "material_interruption":
        return _entry(
            "Material interruption", _quoted_markdown(fact["plain"])
        )

    votes = [
        "- **%s:** `%s`"
        % (labels[vote["participant_id"]], vote["vote"])
        for vote in fact["votes"]
    ]
    decision = (
        "This ballot approved closure."
        if fact["approved"]
        else (
            "This ballot did not approve closure, so discussion could continue."
            if fact["after_completed_rounds"]
            < state["request"]["max_rounds"]
            else (
                "This ballot did not approve closure. No complete discussion "
                "round remained within the configured limit."
            )
        )
    )
    round_number = fact["after_completed_rounds"]
    return _entry(
        "Closure ballot — After round %d" % round_number,
        "The target considered was the target completed after round %d."
        % round_number,
        _field("Votes", "\n".join(votes)),
        _field(
            "Applied agreement rule",
            _closure_rule(state["run_config"]["closure_policy"]),
        ),
        _field("Result", decision),
    )


def _render_closing(state):
    summary = state["closing_summary"]
    result = state["result"]
    agreement = (
        "Agreement was reached."
        if result["outcome"] == "success"
        else "Agreement was not reached."
    )
    disposition = (
        "The target was produced."
        if result["outcome"] == "success"
        else "The target was left unfinished."
    )
    objections = summary["unresolved_objections"]
    if objections:
        objection_lines = []
        for index, objection in enumerate(objections, 1):
            objection_lines.extend(
                ("%d." % index, _quoted_markdown(objection))
            )
        objections_text = "\n\n".join(objection_lines)
    else:
        objections_text = "No unresolved objections were recorded."
    evidence = summary["escalation_evidence"]
    evidence_text = (
        _quoted_markdown(evidence)
        if evidence is not None
        else "No concrete escalation evidence was recorded."
    )
    return _entry(
        "Closing",
        _field("Agreement", agreement),
        _field("Reason", _quoted_markdown(summary["reason"])),
        _field(
            "Target outcome",
            disposition + "\n\n" + _quoted_markdown(result["target_ref"]),
        ),
        _field("Completed rounds", str(result["rounds_used"])),
        _field("Unresolved objections", objections_text),
        _field(
            "Affected parties",
            _quoted_markdown(summary["affected_parties"]),
        ),
        _field(
            "Realistic damage",
            _quoted_markdown(summary["damage_altitude"]),
        ),
        _field(
            "Proportionality",
            _quoted_markdown(summary["proportionality"]),
        ),
        _field("Escalation evidence", evidence_text),
    )


def _render_transcript_v1(checked):
    """Render the immutable first transcript format."""
    labels = _human_labels(checked["run_config"])
    entries = [_render_opening(checked, labels)]
    events = checked["transcript_events"]
    participant_count = len(checked["run_config"]["participants"])
    event_index = 0

    def append_boundary(boundary):
        nonlocal event_index
        while (
            event_index < len(events)
            and _transcript_event_boundary(
                events[event_index], participant_count
            )
            == boundary
        ):
            entries.append(
                _render_transcript_event(
                    events[event_index], checked, labels
                )
            )
            event_index += 1

    append_boundary(0)
    for index, turn in enumerate(checked.get("completed_turns", ()), 1):
        entries.append(_render_turn(turn, labels))
        append_boundary(index)
    if checked["status"] in TERMINAL_STATUSES:
        entries.append(_render_closing(checked))
    return "# Brainstorming session\n\n" + "\n\n".join(entries) + "\n"


_TRANSCRIPT_RENDERERS = {1: _render_transcript_v1}


def render_transcript(state):
    """Render with the format version accepted when the session was created."""
    checked = validate_session_state(state)
    return _TRANSCRIPT_RENDERERS[
        checked["transcript_format_version"]
    ](checked)


def _session_key(session_id):
    return _SESSION_KEY_PREFIX + kvstore.validate_fragment(
        session_id, "session_id"
    )


def _target_revision_key(session_id, revision):
    session_id = kvstore.validate_fragment(session_id, "session_id")
    revision = validate_target_revision_id(revision)
    return "%s%s:%s" % (
        _TARGET_REVISION_KEY_PREFIX,
        session_id,
        revision,
    )


def _turn_attempt_key(session_id):
    return _TURN_ATTEMPT_KEY_PREFIX + kvstore.validate_fragment(
        session_id, "session_id"
    )


class SessionStore:
    """CAS-backed authority for independent brainstorming session records."""

    def __init__(self, directory, filename=kvstore.STORE_FILENAME):
        self._store = kvstore.RevisionEnvelopeStore(
            kvstore.LocalKVClient(directory, filename=filename)
        )
        self._transcript_root = self.path + ".sessions"

    @property
    def path(self):
        return self._store.client.path

    def transcript_ref(self, session_id):
        """Return this session's stable Brainstorming-owned human artifact."""
        session_id = kvstore.validate_fragment(session_id, "session_id")
        directory = hashlib.sha256(
            session_id.encode("utf-8", errors="surrogatepass")
        ).hexdigest()
        return os.path.abspath(
            os.path.join(self._transcript_root, directory, "chat.md")
        )

    @staticmethod
    def _snapshot(record):
        if not record["exists?"]:
            return None
        return SessionSnapshot(
            revision=record["revision"],
            state=validate_session_state(record["value"]),
        )

    def _publish_current(self, session_id):
        """Reconcile ``chat.md`` from the latest winning durable revision."""
        key = _session_key(session_id)
        if not self._store.read(key)["exists?"]:
            return None
        path = self.transcript_ref(session_id)
        with _exclusive_transcript(path):
            snapshot = self._snapshot(self._store.read(key))
            if snapshot is None:
                return None
            if snapshot.state["transcript_ref"] != path:
                raise HistoryRewriteError(
                    "session transcript reference does not match its authority"
                )
            _atomic_replace_utf8(
                path, render_transcript(snapshot.state)
            )
            return snapshot

    def read(self, session_id):
        return self._publish_current(session_id)

    def reconcile_transcript(self, session_id):
        """Repair and return the latest complete transcript projection."""
        return self._publish_current(session_id)

    def _write_target_revision(self, session_id, target_revision):
        checked = validate_target_revision(target_revision)
        key = _target_revision_key(session_id, checked["revision"])
        current = self._store.read(key)
        if current["exists?"]:
            retained = validate_target_revision(current["value"])
            if not _same_json_value(retained, checked):
                raise HistoryRewriteError(
                    "a target revision id cannot identify different state"
                )
            return retained
        result = self._store.cas(key, None, checked)
        if not result.ok:
            retained = validate_target_revision(result.record["value"])
            if not _same_json_value(retained, checked):
                raise HistoryRewriteError(
                    "a target revision id cannot identify different state"
                )
            return retained
        return checked

    def read_target_revision(self, session_id, revision):
        """Read one exact retained revision owned by this session."""
        record = self._store.read(_target_revision_key(session_id, revision))
        if not record["exists?"]:
            raise HistoryRewriteError(
                "accepted target revision content is unavailable"
            )
        checked = validate_target_revision(record["value"])
        if checked["revision"] != revision:
            raise HistoryRewriteError(
                "retained target revision has the wrong identifier"
            )
        return checked

    def read_turn_attempt(self, session_id):
        """Read the exclusive in-flight control record, if one remains."""
        record = self._store.read(_turn_attempt_key(session_id))
        if not record["exists?"]:
            return None
        return validate_turn_attempt(record["value"])

    def begin_turn_attempt(self, session_id, turn_attempt):
        """Persist worker admission before invoking one target-aware control."""
        checked = validate_turn_attempt(turn_attempt)
        if "target_parent" not in checked:
            raise ContractError(
                "new turn attempts require a pinned target_parent"
            )
        if checked["quiescent"]:
            raise ContractError("a new turn attempt cannot start quiescent")
        snapshot = self.read(session_id)
        if snapshot is None:
            raise SessionNotFound(session_id)
        if snapshot.state["status"] != "running":
            raise IllegalTransition("turn attempts require a running session")
        projection = coordination_projection(snapshot.state)
        if projection is None:
            raise HistoryRewriteError(
                "accepted coordination is not initialized"
            )
        turns = projection["completed_turns"]
        participants = snapshot.state["run_config"]["participants"]
        kind = checked.get("kind", "discussion_turn")
        if kind == "discussion_turn":
            expected = participants[len(turns) % len(participants)]
            valid_participant = checked["participant_id"] == expected["id"]
        else:
            valid_participant = any(
                checked["participant_id"] == participant["id"]
                for participant in participants
            )
            if (
                not turns
                or len(turns)
                != projection["rounds_used"] * len(participants)
            ):
                raise HistoryRewriteError(
                    "closure control requires a complete discussion round"
                )
            if any(
                event["kind"] == "closure_ballot"
                and event["fact"]["after_completed_rounds"]
                == projection["rounds_used"]
                for event in snapshot.state["transcript_events"]
            ):
                raise HistoryRewriteError(
                    "closure control requires another complete discussion round"
                )
        if (
            not valid_participant
            or checked["completed_turn_count"] != len(turns)
            or checked["target_revision"]
            != projection["accepted_target_revision"]
        ):
            raise HistoryRewriteError(
                "worker attempt does not match durable accepted progress"
            )
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if current["exists?"]:
            raise HistoryRewriteError("a turn attempt is already active")
        # Coordinators hold the cross-process target lock around this write.
        self._store.put(key, checked)
        return checked

    def mark_turn_attempt_quiescent(self, session_id, token):
        """Durably record that the admitted worker can no longer mutate."""
        token = _text(token, "turn_attempt.token")
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("the active turn attempt is missing")
        attempt = validate_turn_attempt(current["value"])
        if attempt["token"] != token:
            raise HistoryRewriteError("the active turn attempt token changed")
        if attempt["quiescent"]:
            return attempt
        attempt["quiescent"] = True
        result = self._store.cas(key, current["revision"], attempt)
        if not result.ok:
            raise HistoryRewriteError(
                "the active turn attempt changed before quiescence"
            )
        return attempt

    def finish_turn_attempt(self, session_id, token):
        """Clear one reconciled or durably accepted exclusive attempt."""
        token = _text(token, "turn_attempt.token")
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            return
        attempt = validate_turn_attempt(current["value"])
        if attempt["token"] != token:
            raise HistoryRewriteError("the active turn attempt token changed")
        result = self._store.delete(key, expected_revision=current["revision"])
        if not result.ok:
            raise HistoryRewriteError(
                "the active turn attempt changed before completion"
            )

    def _cas_coordination(
        self,
        session_id,
        expected_revision,
        candidate,
        assertion,
        publish=True,
    ):
        if type(expected_revision) is not int or expected_revision <= 0:
            raise ContractError("expected_revision must be a positive integer")
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        candidate = validate_session_state(candidate)
        assertion(current.state, candidate)
        result = self._store.cas(
            _session_key(session_id), expected_revision, candidate
        )
        if not result.ok:
            latest = self._publish_current(session_id)
            if latest is None:
                raise SessionNotFound(session_id)
            raise RevisionConflict(latest)
        if publish:
            return self._publish_current(session_id)
        return self._snapshot(result.record)

    def create(self, session_id, request, run_config, eligible_participants):
        checked_config = validate_run_config(run_config)
        resolved_config = resolve_run_config(
            checked_config["participants"],
            checked_config["closure_policy"],
            eligible_participants,
        )
        if not _same_json_value(checked_config, resolved_config):
            raise ContractError("run_config does not match roster resolution")
        state = new_session_state(
            request, resolved_config, self.transcript_ref(session_id)
        )
        target_path = state["request"]["target_path"]
        if not os.path.isabs(target_path):
            target_path = os.path.join(
                state["request"]["workspace_path"], target_path
            )
        if _target_overlaps_state_storage(self.path, target_path):
            raise ContractError(
                "request.target_path must not overlap Brainstorming's "
                "durable state store or lock"
            )
        if _target_overlaps_transcript_storage(
            self._transcript_root,
            target_path,
            state["transcript_ref"],
        ):
            raise ContractError(
                "request.target_path must not overlap Brainstorming-owned "
                "transcript storage"
            )
        result = self._store.cas(_session_key(session_id), None, state)
        if not result.ok:
            raise SessionAlreadyExists("session already exists")
        return self._publish_current(session_id)

    def discard_unlaunched(self, session_id):
        """Remove only a create-time session that no worker could have used.

        Standalone creation keeps its lifecycle child behind a launch gate
        until the public binding, durable state, and response projection are
        ready.  This narrow compensation seam lets that transaction leave no
        hidden session when a later create step fails.  It deliberately
        refuses any state that already contains participant or coordination
        work.
        """
        key = _session_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            return
        state = validate_session_state(current["value"])
        if (
            state["status"] not in ("created", "running")
            or state.get("participant_sessions")
            or state.get("transcript_events")
            or coordination_projection(state) is not None
            or [item["status"] for item in state["history"]]
            not in (["created"], ["created", "running"])
        ):
            raise HistoryRewriteError(
                "only an unused create-time session may be discarded"
            )

        transcript = self.transcript_ref(session_id)
        with _exclusive_transcript(transcript):
            try:
                os.unlink(transcript)
            except FileNotFoundError:
                pass

            expected_revision = current["revision"]

            def remove(document):
                raw = self._store._raw_from_doc(document, key)
                public = self._store._public_from_raw(raw)
                if (
                    not public["exists?"]
                    or public["revision"] != expected_revision
                ):
                    return False, False
                del document["entries"][key]
                return True, True

            if not self._store.client._mutate(remove):
                self._publish_current(session_id)
                raise HistoryRewriteError(
                    "create-time session changed before compensation"
                )

        directory = os.path.dirname(transcript)
        try:
            os.rmdir(directory)
        except OSError:
            pass

    def save(self, session_id, expected_revision, state):
        if type(expected_revision) is not int or expected_revision <= 0:
            raise ContractError("expected_revision must be a positive integer")
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        candidate = validate_session_state(state)
        assert_session_successor(current.state, candidate)
        result = self._store.cas(
            _session_key(session_id), expected_revision, candidate
        )
        if not result.ok:
            latest = self._publish_current(session_id)
            if latest is None:
                raise SessionNotFound(session_id)
            raise RevisionConflict(latest)
        return self._publish_current(session_id)

    def transition(
        self,
        session_id,
        expected_revision,
        new_status,
        result=None,
        closing_summary=None,
    ):
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        successor = transition_session(
            current.state, new_status, result, closing_summary
        )
        return self.save(session_id, expected_revision, successor)

    def initialize_coordination(
        self, session_id, expected_revision, target_revision
    ):
        """Retain the starting target and atomically expose empty progress."""
        checked_target = self._write_target_revision(
            session_id, target_revision
        )
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        candidate = initialize_coordination_state(
            current.state, checked_target
        )
        return self._cas_coordination(
            session_id,
            expected_revision,
            candidate,
            assert_coordination_initialization_successor,
        )

    def record_completed_turn(
        self,
        session_id,
        expected_revision,
        participant_id,
        markdown,
        target_revision,
        publish=True,
    ):
        """Retain target content and atomically append one accepted turn."""
        checked_target = self._write_target_revision(
            session_id, target_revision
        )
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        candidate = completed_turn_successor(
            current.state,
            participant_id,
            markdown,
            checked_target["revision"],
        )

        def assertion(old, new):
            assert_completed_turn_successor(
                old,
                new,
                participant_id,
                markdown,
                checked_target["revision"],
            )

        return self._cas_coordination(
            session_id,
            expected_revision,
            candidate,
            assertion,
            publish=publish,
        )

    def _record_transcript_event(
        self, session_id, expected_revision, kind, fact
    ):
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        candidate = transcript_event_successor(
            current.state, kind, fact
        )

        def assertion(old, new):
            assert_transcript_event_successor(
                old, new, kind, fact
            )

        return self._cas_coordination(
            session_id, expected_revision, candidate, assertion
        )

    def record_material_interruption(
        self, session_id, expected_revision, interruption
    ):
        """Append one explicitly material, human-safe interruption."""
        return self._record_transcript_event(
            session_id,
            expected_revision,
            "material_interruption",
            interruption,
        )

    def record_closure_ballot(
        self, session_id, expected_revision, ballot
    ):
        """Append one rejected, non-final ballot before discussion resumes."""
        return self._record_transcript_event(
            session_id, expected_revision, "closure_ballot", ballot
        )

    def close_with_ballot(
        self,
        session_id,
        expected_revision,
        ballot,
        result,
        closing_summary,
    ):
        """Atomically accept a ballot and its derived terminal outcome."""
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        candidate = terminal_closure_successor(
            current.state, ballot, result, closing_summary
        )
        if candidate["status"] == "success":
            accepted_target = self.read_target_revision(
                session_id,
                candidate["accepted_target_revision"],
            )
            if not accepted_target["exists"]:
                raise ContractError(
                    "success requires the requested target to exist"
                )

        def assertion(old, new):
            assert_terminal_closure_successor(
                old, new, ballot, result, closing_summary
            )

        return self._cas_coordination(
            session_id,
            expected_revision,
            candidate,
            assertion,
        )

    def close_with_interruption(
        self,
        session_id,
        expected_revision,
        interruption,
        result,
        closing_summary,
    ):
        """Atomically append a material interruption and terminal failure."""
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        candidate = terminal_interruption_successor(
            current.state, interruption, result, closing_summary
        )

        def assertion(old, new):
            assert_terminal_interruption_successor(
                old, new, interruption, result, closing_summary
            )

        return self._cas_coordination(
            session_id,
            expected_revision,
            candidate,
            assertion,
        )

    def bind_participant_session(
        self,
        session_id,
        expected_revision,
        participant_id,
        provider_ref,
    ):
        """CAS-add one participant's durable logical-session reference."""
        if type(expected_revision) is not int or expected_revision <= 0:
            raise ContractError("expected_revision must be a positive integer")
        participant_id = _text(participant_id, "participant_id")
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        if current.state["status"] != "running":
            raise IllegalTransition(
                "participant sessions can only bind while running"
            )

        participant = next(
            (
                item
                for item in current.state["run_config"]["participants"]
                if item["id"] == participant_id
            ),
            None,
        )
        if participant is None:
            raise ContractError(
                "participant_id is not in the persisted roster"
            )
        session_ref = make_participant_session_ref(
            participant["executor_ref"], provider_ref
        )
        candidate = copy.deepcopy(current.state)
        candidate.setdefault("participant_sessions", {})
        if participant_id in candidate["participant_sessions"]:
            raise HistoryRewriteError(
                "participant session reference is already bound"
            )
        candidate["participant_sessions"][participant_id] = session_ref
        validate_session_state(candidate)
        assert_participant_session_successor(
            current.state, candidate, participant_id, session_ref
        )

        result = self._store.cas(
            _session_key(session_id), expected_revision, candidate
        )
        if not result.ok:
            latest = self._publish_current(session_id)
            if latest is None:
                raise SessionNotFound(session_id)
            raise RevisionConflict(latest)
        return self._publish_current(session_id)
