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
import math
import os
import re
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass

from orchestrator import contracts, errclass, kvstore, staffing

try:
    import fcntl
except ImportError:  # pragma: no cover - the production service is POSIX
    fcntl = None


STATUSES = ("created", "running", "success", "failure")
TERMINAL_STATUSES = ("success", "failure")
CLOSURE_POLICIES = ("unanimity", "majority")
ROLES = ("initial_position", "contrary_position", "common_sense")
POSITION_ROLES = ("initial_position", "contrary_position")
DELIVERIES = ("llm", "external")
TRANSCRIPT_EVENT_KINDS = (
    "material_interruption",
    "closure_ballot",
    "floor_intervention",
)
TRANSCRIPT_FORMAT_VERSION = 1

# Out-of-turn interventions arrive from outside the roster. Their author ids
# must be label_hex32-shaped (the agent_99 entity contract), so they can never
# collide with the operational roster ids (initial-position, dante, critic-N).
FLOOR_AUTHOR_ID_RE = re.compile(r"^[a-z][a-z0-9]*_[0-9a-f]{32}$")

_ALLOWED_TRANSITIONS = {
    "created": ("running", "failure"),
    "running": ("success", "failure"),
    "success": (),
    "failure": (),
}
_SESSION_KEY_PREFIX = "brainstorming/session:"
_TARGET_REVISION_KEY_PREFIX = "brainstorming/target_revision:"
_TURN_ATTEMPT_KEY_PREFIX = "brainstorming/turn_attempt:"
_EXTERNAL_INTERVENTION_KEY_PREFIX = "brainstorming/external_intervention:"
_ACTIVITY_KEY_PREFIX = "brainstorming/activity:"
_TASK_EFFECT_ATTEMPT_KEY_PREFIX = "brainstorming/task_effect_attempt:"
_TARGET_REVISION_ID_PREFIX = "brainstorming-sha256:"
_TARGET_REVISION_ID_RE = re.compile(
    r"^brainstorming-sha256:[0-9a-f]{64}$"
)
_COORDINATION_FIELDS = (
    "completed_turns",
    "rounds_used",
    "recovery_baseline_revision",
    "accepted_target_revision",
)
_TRANSCRIPT_LOCKS = {}
_TRANSCRIPT_LOCKS_GUARD = threading.Lock()

ACTIVITY_SCHEMA_VERSION = 1
ACTIVITY_STATUSES = ("completed", "failed")
ACTIVITY_FAILURE_TYPES = ("protocol", "execution", "acceptance")
# The router's own token for "an input could not be read, so the default
# document answered". Taken from the resolver rather than restated, so the
# ledger and the marker can never drift apart.
STAFFING_FALLBACK_DEFAULT_DOCUMENT = staffing.STAFFING_FALLBACK_DEFAULT_DOCUMENT


def _cost(value, ctx="cost"):
    """What the call cost, under both readings. See pricing.py."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ContractError("%s must be an object" % ctx)
    checked = {}
    for field in ("api_usd", "real_usd"):
        amount = value.get(field)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ContractError("%s.%s must be a number" % (ctx, field))
        amount = float(amount)
        if not math.isfinite(amount) or amount < 0:
            raise ContractError(
                "%s.%s must be a non-negative finite number" % (ctx, field)
            )
        checked[field] = amount
    if checked["real_usd"] > checked["api_usd"]:
        raise ContractError(
            "%s.real_usd cannot exceed the API-equivalent" % ctx
        )
    return checked


def _token_usage(value, ctx="token_usage"):
    if value is None:
        return None
    _exact_keys(
        value,
        (
            "input_tokens", "cached_input_tokens", "output_tokens",
            "reasoning_output_tokens", "total_tokens",
        ),
        (),
        ctx,
    )
    checked = {}
    for field, count in value.items():
        if type(count) is not int or count < 0:
            raise ContractError(
                "%s.%s must be a non-negative integer" % (ctx, field)
            )
        checked[field] = count
    if checked["cached_input_tokens"] > checked["input_tokens"]:
        raise ContractError("%s.cached_input_tokens exceeds input" % ctx)
    if checked["reasoning_output_tokens"] > checked["output_tokens"]:
        raise ContractError("%s.reasoning_output_tokens exceeds output" % ctx)
    if checked["total_tokens"] != (
        checked["input_tokens"] + checked["output_tokens"]
    ):
        raise ContractError("%s.total_tokens is inconsistent" % ctx)
    return checked
RECOVERABLE_FAILURE_TYPES = errclass.AUTO_RESUMABLE


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


def _model_keys(value, required, optional, ctx):
    """Key check for a MODEL-authored envelope: presence is mandatory,
    surplus is dropped in place (operator rule, 2026-08-11 — see
    contracts._require_keys). Stored records, run configs and API payloads
    keep _exact_keys: a surplus field there is our own typo, and it must
    still fail loudly."""
    _object(value, ctx)
    missing = sorted(set(required) - set(value))
    if missing:
        raise ContractError("%s is missing %s" % (ctx, missing))
    allowed = set(required) | set(optional)
    for key in sorted(set(value) - allowed):
        del value[key]


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


def validate_external_intervention(intervention):
    """Validate one durable request for a response outside worker control."""
    _exact_keys(
        intervention,
        (
            "token",
            "participant_id",
            "action_kind",
            "completed_turn_count",
            "round",
            "target_revision",
            "input",
            "created_at",
            "provider_attempt",
            "provider_quiescent",
            "response",
        ),
        ("closure_context", "dispatch_refused"),
        "external_intervention",
    )
    checked = {
        "token": _text(
            intervention["token"], "external_intervention.token"
        ),
        "participant_id": _text(
            intervention["participant_id"],
            "external_intervention.participant_id",
        ),
        "action_kind": intervention["action_kind"],
        "completed_turn_count": intervention["completed_turn_count"],
        "round": intervention["round"],
        "target_revision": (
            None
            if intervention["target_revision"] is None
            else validate_target_revision_id(
                intervention["target_revision"]
            )
        ),
        "created_at": intervention["created_at"],
        "provider_attempt": intervention["provider_attempt"],
        "provider_quiescent": intervention["provider_quiescent"],
        "response": None,
    }
    if checked["action_kind"] not in ("discussion_turn", "closure_vote"):
        raise ContractError("external_intervention.action_kind is invalid")
    for field in ("completed_turn_count", "provider_attempt"):
        value = checked[field]
        if type(value) is not int or value < 0:
            raise ContractError(
                "external_intervention.%s must be a non-negative integer"
                % field
            )
    if not isinstance(checked["provider_quiescent"], bool):
        raise ContractError(
            "external_intervention.provider_quiescent must be boolean"
        )
    if (
        checked["provider_attempt"] == 0
        and not checked["provider_quiescent"]
    ):
        raise ContractError(
            "an unclaimed external provider must be quiescent"
        )
    dispatch_refused = intervention.get("dispatch_refused", False)
    if type(dispatch_refused) is not bool:
        raise ContractError(
            "external_intervention.dispatch_refused must be a boolean"
        )
    if dispatch_refused and (
        checked["provider_attempt"] == 0
        or not checked["provider_quiescent"]
    ):
        raise ContractError(
            "a refused external dispatch leaves its claimed provider quiescent"
        )
    if "dispatch_refused" in intervention:
        checked["dispatch_refused"] = dispatch_refused
    if type(checked["round"]) is not int or checked["round"] <= 0:
        raise ContractError(
            "external_intervention.round must be a positive integer"
        )
    if (
        isinstance(checked["created_at"], bool)
        or not isinstance(checked["created_at"], (int, float))
        or not math.isfinite(float(checked["created_at"]))
        or float(checked["created_at"]) <= 0
    ):
        raise ContractError(
            "external_intervention.created_at must be a positive finite number"
        )
    checked["created_at"] = float(checked["created_at"])

    supplied = intervention["input"]
    _exact_keys(
        supplied,
        (
            "request",
            "context",
            "workspace_path",
            "target_path",
            "transcript_ref",
        ),
        (),
        "external_intervention.input",
    )
    checked["input"] = {
        "request": _text(
            supplied["request"], "external_intervention.input.request"
        ),
        "context": _json_copy(
            supplied["context"], "external_intervention.input.context"
        ),
        "workspace_path": _text(
            supplied["workspace_path"],
            "external_intervention.input.workspace_path",
        ),
        "target_path": _text(
            supplied["target_path"],
            "external_intervention.input.target_path",
        ),
        "transcript_ref": validate_transcript_ref(
            supplied["transcript_ref"]
        ),
    }

    closure_context = intervention.get("closure_context")
    if checked["action_kind"] == "closure_vote":
        _exact_keys(
            closure_context,
            ("closing_summary", "votes"),
            (),
            "external_intervention.closure_context",
        )
        summary = validate_closing_summary_shape(
            closure_context["closing_summary"]
        )
        votes = closure_context["votes"]
        if not isinstance(votes, list) or not votes:
            raise ContractError(
                "external_intervention.closure_context.votes must be non-empty"
            )
        checked_votes = []
        for index, vote in enumerate(votes):
            ctx = "external_intervention.closure_context.votes[%d]" % index
            _exact_keys(vote, ("participant_id", "vote"), (), ctx)
            participant_id = _text(vote["participant_id"], "%s.participant_id" % ctx)
            if vote["vote"] not in ("accept", "object"):
                raise ContractError("%s.vote must be accept or object" % ctx)
            checked_votes.append(
                {"participant_id": participant_id, "vote": vote["vote"]}
            )
        checked["closure_context"] = {
            "closing_summary": summary,
            "votes": checked_votes,
        }
    elif closure_context is not None:
        raise ContractError(
            "discussion interventions cannot carry closure_context"
        )

    response = intervention["response"]
    if response is not None:
        if not checked["provider_quiescent"]:
            raise ContractError(
                "an answered external intervention must be quiescent"
            )
        _exact_keys(
            response,
            ("received_at", "payload"),
            (),
            "external_intervention.response",
        )
        received_at = response["received_at"]
        if (
            isinstance(received_at, bool)
            or not isinstance(received_at, (int, float))
            or not math.isfinite(float(received_at))
            or float(received_at) <= 0
        ):
            raise ContractError(
                "external_intervention.response.received_at must be positive"
            )
        payload = response["payload"]
        if checked["action_kind"] == "discussion_turn":
            _exact_keys(
                payload,
                ("markdown",),
                (),
                "external_intervention.response.payload",
            )
            payload = {
                "markdown": _text(
                    payload["markdown"],
                    "external_intervention.response.payload.markdown",
                )
            }
        else:
            _exact_keys(
                payload,
                ("vote",),
                (),
                "external_intervention.response.payload",
            )
            if payload["vote"] not in ("accept", "object"):
                raise ContractError(
                    "external_intervention.response.payload.vote is invalid"
                )
            payload = {"vote": payload["vote"]}
        checked["response"] = {
            "received_at": float(received_at),
            "payload": payload,
        }
    return checked


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
        (
            "target_parent",
            "kind",
            "started_at",
            "provider_attempt",
            "target_mutation_corrections",
            "envelope_repair_used",
            "dispatch_refused",
            "retry_pending",
            "operational_retry",
            "target_mutation_failure_pending",
            "action_context",
            "classifier_call",
        ),
        "turn_attempt",
    )
    checked = {
        "token": _text(turn_attempt["token"], "turn_attempt.token"),
        "participant_id": _text(
            turn_attempt["participant_id"], "turn_attempt.participant_id"
        ),
        "completed_turn_count": turn_attempt["completed_turn_count"],
        "target_revision": (
            None
            if turn_attempt["target_revision"] is None
            else validate_target_revision_id(turn_attempt["target_revision"])
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
    started_at = turn_attempt.get("started_at")
    if started_at is not None:
        if (
            isinstance(started_at, bool)
            or not isinstance(started_at, (int, float))
            or not math.isfinite(float(started_at))
            or float(started_at) <= 0
        ):
            raise ContractError(
                "turn_attempt.started_at must be a positive finite number"
            )
        checked["started_at"] = float(started_at)
    provider_attempt = turn_attempt.get("provider_attempt")
    if provider_attempt is not None:
        if type(provider_attempt) is not int or provider_attempt <= 0:
            raise ContractError(
                "turn_attempt.provider_attempt must be a positive integer"
            )
        checked["provider_attempt"] = provider_attempt
    corrections = turn_attempt.get("target_mutation_corrections", 0)
    if type(corrections) is not int or corrections not in (0, 1):
        raise ContractError(
            "turn_attempt.target_mutation_corrections must be 0 or 1"
        )
    retry_pending = turn_attempt.get("retry_pending", False)
    if type(retry_pending) is not bool:
        raise ContractError("turn_attempt.retry_pending must be a boolean")
    if retry_pending and (
        not checked["quiescent"] or corrections != 1
    ):
        raise ContractError(
            "a retry-pending turn attempt must be quiescent with its one "
            "target-mutation correction already used"
        )
    operational_retry = turn_attempt.get("operational_retry")
    if operational_retry is not None:
        _exact_keys(
            operational_retry,
            ("error_type", "resume_at", "evidence", "retry_at"),
            (),
            "turn_attempt.operational_retry",
        )
        error_type = operational_retry["error_type"]
        if error_type not in RECOVERABLE_FAILURE_TYPES:
            raise ContractError(
                "turn_attempt.operational_retry.error_type is not recoverable"
            )
        resume_at = operational_retry["resume_at"]
        if resume_at is not None:
            resume_at = _text(
                resume_at, "turn_attempt.operational_retry.resume_at"
            )
        evidence = operational_retry["evidence"]
        if not isinstance(evidence, str):
            raise ContractError(
                "turn_attempt.operational_retry.evidence must be a string"
            )
        retry_at = operational_retry["retry_at"]
        if (
            isinstance(retry_at, bool)
            or not isinstance(retry_at, (int, float))
            or not math.isfinite(float(retry_at))
            or float(retry_at) <= 0
        ):
            raise ContractError(
                "turn_attempt.operational_retry.retry_at must be a positive "
                "finite number"
            )
        if not checked["quiescent"] or retry_pending:
            raise ContractError(
                "an operational retry must be quiescent and independent of "
                "target-mutation retry"
            )
        checked["operational_retry"] = {
            "error_type": error_type,
            "resume_at": resume_at,
            "evidence": evidence,
            "retry_at": float(retry_at),
        }
    failure_pending = turn_attempt.get(
        "target_mutation_failure_pending", False
    )
    if type(failure_pending) is not bool:
        raise ContractError(
            "turn_attempt.target_mutation_failure_pending must be a boolean"
        )
    if failure_pending and (
        not checked["quiescent"]
        or corrections != 1
        or retry_pending
        or operational_retry is not None
    ):
        raise ContractError(
            "a target-mutation failure must be quiescent, corrected once, "
            "and no longer retryable"
        )
    if "target_mutation_corrections" in turn_attempt:
        checked["target_mutation_corrections"] = corrections
    envelope_repair_used = turn_attempt.get("envelope_repair_used", False)
    if type(envelope_repair_used) is not bool:
        raise ContractError(
            "turn_attempt.envelope_repair_used must be a boolean"
        )
    if "envelope_repair_used" in turn_attempt:
        checked["envelope_repair_used"] = envelope_repair_used
    dispatch_refused = turn_attempt.get("dispatch_refused", False)
    if type(dispatch_refused) is not bool:
        raise ContractError("turn_attempt.dispatch_refused must be a boolean")
    if dispatch_refused and not checked["quiescent"]:
        raise ContractError(
            "a refused dispatch leaves its turn attempt quiescent"
        )
    if "dispatch_refused" in turn_attempt:
        checked["dispatch_refused"] = dispatch_refused
    if "retry_pending" in turn_attempt:
        checked["retry_pending"] = retry_pending
    if "target_mutation_failure_pending" in turn_attempt:
        checked["target_mutation_failure_pending"] = failure_pending
    action_context = turn_attempt.get("action_context")
    if action_context is not None:
        if checked.get("kind", "discussion_turn") != "closure":
            raise ContractError(
                "turn_attempt.action_context is closure-only"
            )
        if not isinstance(action_context, dict):
            raise ContractError(
                "turn_attempt.action_context must be an object"
            )
        checked["action_context"] = _json_copy(
            action_context, "turn_attempt.action_context"
        )
    classifier_call = turn_attempt.get("classifier_call")
    if classifier_call is not None:
        _exact_keys(
            classifier_call,
            ("family", "model", "effort", "started_at"),
            (),
            "turn_attempt.classifier_call",
        )
        started_at = classifier_call["started_at"]
        if (
            isinstance(started_at, bool)
            or not isinstance(started_at, (int, float))
            or not math.isfinite(float(started_at))
            or float(started_at) <= 0
        ):
            raise ContractError(
                "turn_attempt.classifier_call.started_at must be a positive "
                "finite number"
            )
        checked["classifier_call"] = {
            "family": _text(
                classifier_call["family"],
                "turn_attempt.classifier_call.family",
            ),
            "model": classifier_call["model"],
            "effort": classifier_call["effort"],
            "started_at": float(started_at),
        }
        for field in ("model", "effort"):
            value = checked["classifier_call"][field]
            if value is not None:
                checked["classifier_call"][field] = _text(
                    value, "turn_attempt.classifier_call.%s" % field
                )
    return checked


def validate_activity_event(event):
    """Validate one immutable provider call in the operational ledger."""
    _exact_keys(
        event,
        (
            "id",
            "action_id",
            "provider_attempt",
            "at",
            "started_at",
            "duration_s",
            "kind",
            "stage",
            "round",
            "participant_id",
            "model_family",
            "model",
            "effort",
            "status",
        ),
        (
            "failure_type",
            "error",
            "raw_ref",
            "prompt_ref",
            "token_usage",
            "token_usage_partial",
            "cost",
            "cost_partial",
            # Says the staffing behind this call came from the default
            # document because the router could not read the session or the
            # document it names. Optional and additive: an event written
            # before the staffing cutover simply has no such note, and one
            # written on an ordinary answer has none either.
            "staffing_fallback",
            "prompt_set_fallback",
            # Withdrawn model-profile attribution may remain in ledgers
            # written by the superseded runtime. It has no authority, but
            # generic Brainstorming execution and recovery must still read
            # those sessions, so validation accepts and discards it.
            "model_profile",
            "act_override",
        ),
        "activity_event",
    )
    checked = {
        "id": _text(event["id"], "activity_event.id"),
        "action_id": _text(
            event["action_id"], "activity_event.action_id"
        ),
        "provider_attempt": event["provider_attempt"],
        "at": _text(event["at"], "activity_event.at"),
        "started_at": event["started_at"],
        "duration_s": event["duration_s"],
        "kind": event["kind"],
        "stage": event["stage"],
        "round": event["round"],
        "participant_id": _text(
            event["participant_id"], "activity_event.participant_id"
        ),
        "model_family": event["model_family"],
        "model": event["model"],
        "effort": event["effort"],
        "status": event["status"],
    }
    if type(checked["provider_attempt"]) is not int \
            or checked["provider_attempt"] <= 0:
        raise ContractError(
            "activity_event.provider_attempt must be a positive integer"
        )
    for field in ("started_at", "duration_s"):
        value = checked[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ContractError(
                "activity_event.%s must be a non-negative finite number"
                % field
            )
        checked[field] = float(value)
    if checked["started_at"] <= 0:
        raise ContractError(
            "activity_event.started_at must be a positive finite number"
        )
    if checked["kind"] not in (
        "discussion_turn", "closure", "classifier", "production_effect"
    ):
        raise ContractError("activity_event.kind is invalid")
    if checked["stage"] not in (
        "discussion", "proposal", "vote", "classification", "production"
    ):
        raise ContractError("activity_event.stage is invalid")
    if checked["kind"] == "discussion_turn" \
            and checked["stage"] != "discussion":
        raise ContractError(
            "discussion activity must use the discussion stage"
        )
    if checked["kind"] == "closure" \
            and checked["stage"] not in ("proposal", "vote"):
        raise ContractError("closure activity must name its control stage")
    if checked["kind"] == "classifier" \
            and checked["stage"] != "classification":
        raise ContractError(
            "classifier activity must use the classification stage"
        )
    if checked["kind"] == "production_effect" \
            and checked["stage"] != "production":
        raise ContractError(
            "production-effect activity must use the production stage"
        )
    if (
        checked["kind"] != "production_effect"
        or checked["model_family"] is not None
    ):
        checked["model_family"] = _text(
            checked["model_family"], "activity_event.model_family"
        )
    if type(checked["round"]) is not int or checked["round"] <= 0:
        raise ContractError(
            "activity_event.round must be a positive integer"
        )
    for field in ("model", "effort"):
        value = checked[field]
        if value is not None:
            checked[field] = _text(value, "activity_event.%s" % field)
    if checked["status"] not in ACTIVITY_STATUSES:
        raise ContractError("activity_event.status is invalid")
    failure_type = event.get("failure_type")
    error = event.get("error")
    if checked["status"] == "failed":
        if failure_type not in ACTIVITY_FAILURE_TYPES:
            raise ContractError(
                "failed activity requires a valid failure_type"
            )
        checked["failure_type"] = failure_type
        checked["error"] = _text(error, "activity_event.error")
    elif failure_type is not None or error is not None:
        raise ContractError(
            "completed activity cannot carry failure details"
        )
    for field in ("raw_ref", "prompt_ref"):
        value = event.get(field)
        if value is not None:
            checked[field] = _text(value, "activity_event.%s" % field)
    token_usage = _token_usage(
        event.get("token_usage"), "activity_event.token_usage"
    )
    if token_usage is not None:
        checked["token_usage"] = token_usage
    token_usage_partial = event.get("token_usage_partial", False)
    if type(token_usage_partial) is not bool:
        raise ContractError(
            "activity_event.token_usage_partial must be a boolean"
        )
    if token_usage_partial:
        checked["token_usage_partial"] = True
    cost = _cost(event.get("cost"), "activity_event.cost")
    if cost is not None:
        checked["cost"] = cost
    cost_partial = event.get("cost_partial", False)
    if type(cost_partial) is not bool:
        raise ContractError(
            "activity_event.cost_partial must be a boolean"
        )
    if cost_partial:
        checked["cost_partial"] = True
    fallback = event.get("staffing_fallback")
    if fallback is not None:
        if fallback != STAFFING_FALLBACK_DEFAULT_DOCUMENT:
            raise ContractError(
                "activity_event.staffing_fallback must be %r"
                % STAFFING_FALLBACK_DEFAULT_DOCUMENT
            )
        checked["staffing_fallback"] = fallback
    prompt_fallback = event.get("prompt_set_fallback")
    if prompt_fallback is not None:
        if prompt_fallback not in ("stored_default", "in_code_seed"):
            raise ContractError(
                "activity_event.prompt_set_fallback is invalid"
            )
        checked["prompt_set_fallback"] = prompt_fallback
    return checked


def validate_activity_log(activity):
    _exact_keys(
        activity,
        ("schema_version", "events"),
        (),
        "activity",
    )
    if activity["schema_version"] != ACTIVITY_SCHEMA_VERSION:
        raise ContractError("activity.schema_version is unsupported")
    if not isinstance(activity["events"], list):
        raise ContractError("activity.events must be a list")
    events = [validate_activity_event(item) for item in activity["events"]]
    ids = [item["id"] for item in events]
    call_keys = [
        (item["action_id"], item["provider_attempt"]) for item in events
    ]
    if len(ids) != len(set(ids)) or len(call_keys) != len(set(call_keys)):
        raise ContractError("activity events must be unique")
    return {
        "schema_version": ACTIVITY_SCHEMA_VERSION,
        "events": events,
    }


def validate_task_effect_attempt(attempt):
    """Validate the single in-flight production-effect recovery marker."""
    _exact_keys(
        attempt,
        ("task_id", "token", "started_at"),
        (),
        "task_effect_attempt",
    )
    started_at = attempt["started_at"]
    try:
        normalized_started_at = float(started_at)
    except (TypeError, ValueError, OverflowError):
        normalized_started_at = -1.0
    if (
        isinstance(started_at, bool)
        or not isinstance(started_at, (int, float))
        or not math.isfinite(normalized_started_at)
        or normalized_started_at <= 0
    ):
        raise ContractError(
            "task_effect_attempt.started_at must be a positive finite number"
        )
    return {
        "task_id": _text(attempt["task_id"], "task_effect_attempt.task_id"),
        "token": _text(attempt["token"], "task_effect_attempt.token"),
        "started_at": normalized_started_at,
    }


def _validate_participant(participant, ctx):
    _object(participant, ctx)
    delivery = participant.get("delivery")
    if delivery == "llm":
        _exact_keys(
            participant,
            ("id", "role", "delivery", "executor_ref", "model_family"),
            (),
            ctx,
        )
    elif delivery == "external":
        _exact_keys(
            participant,
            ("id", "role", "delivery", "external_ref"),
            (),
            ctx,
        )
    else:
        raise ContractError("%s.delivery must be one of %s" % (ctx, DELIVERIES))
    checked = {
        "id": _text(participant["id"], "%s.id" % ctx),
        "role": participant["role"],
        "delivery": delivery,
    }
    if delivery == "llm":
        checked.update(
            {
                "executor_ref": _text(
                    participant["executor_ref"], "%s.executor_ref" % ctx
                ),
                "model_family": _text(
                    participant["model_family"], "%s.model_family" % ctx
                ),
            }
        )
    else:
        checked["external_ref"] = _text(
            participant["external_ref"], "%s.external_ref" % ctx
        )
    if checked["role"] not in ROLES:
        raise ContractError("%s.role must be one of %s" % (ctx, ROLES))
    if delivery == "external" and checked["role"] == "initial_position":
        raise ContractError(
            "an external participant cannot own the target"
        )
    return checked


def validate_request(request):
    """Validate and return a detached JSON-compatible request copy."""
    _exact_keys(
        request,
        ("workspace_path", "target_path", "request", "context", "max_rounds"),
        ("deliver_chat",),
        "request",
    )
    for key in ("workspace_path", "target_path", "request"):
        _text(request[key], "request.%s" % key)
    if type(request["max_rounds"]) is not int or request["max_rounds"] <= 0:
        raise ContractError("request.max_rounds must be a positive integer")
    if "deliver_chat" in request and type(request["deliver_chat"]) is not bool:
        raise ContractError("request.deliver_chat must be a boolean")

    context = request["context"]
    _exact_keys(
        context,
        ("brief",),
        ("references", "source_payload", "amendments"),
        "request.context",
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
    if "amendments" in context:
        amendments = context["amendments"]
        if not isinstance(amendments, list):
            raise ContractError("request.context.amendments must be a list")
        for index, amendment in enumerate(amendments):
            if not isinstance(amendment, dict):
                raise ContractError(
                    "request.context.amendments[%d] must be an object" % index
                )
            _text(
                amendment.get("text"),
                "request.context.amendments[%d].text" % index,
            )
            if "id" in amendment:
                _text(
                    amendment["id"],
                    "request.context.amendments[%d].id" % index,
                )
    return _json_copy(request, "request")


def delivers_chat(request):
    """Whether this session hands the chat over beside its target document.

    Opt-in, and OFF unless the request says otherwise: the discussion's
    product is the target document, and a session that also drops a
    transcript into the operator's tree is doing something they must have
    asked for. An older stored session carries no key and delivers nothing.
    """
    return bool(isinstance(request, dict) and request.get("deliver_chat"))


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
    initial_count = 0
    contrary_count = 0
    common_sense_count = 0
    families = set()
    for index, participant in enumerate(participants):
        ctx = "run_config.participants[%d]" % index
        checked = _validate_participant(participant, ctx)
        participant_id = checked["id"]
        if participant_id in ids:
            raise ContractError("participant ids must be unique")
        ids.add(participant_id)
        role = checked["role"]
        initial_count += role == "initial_position"
        contrary_count += role == "contrary_position"
        common_sense_count += role == "common_sense"
        if checked["delivery"] == "llm":
            families.add(checked["model_family"])

    if initial_count != 1:
        raise ContractError(
            "run_config must contain exactly one initial position"
        )
    if contrary_count < 1:
        raise ContractError(
            "run_config must contain at least one contrary position"
        )
    if common_sense_count > 1:
        raise ContractError(
            "run_config may contain at most one common-sense participant"
        )
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
        participant = participants[participant_id]
        executor_ref = (
            participant["executor_ref"]
            if participant["delivery"] == "llm"
            else participant["external_ref"]
        )
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
    recovery_baseline = validate_target_revision_id(
        projection["recovery_baseline_revision"]
    )
    accepted_revision = projection["accepted_target_revision"]
    if accepted_revision is not None:
        accepted_revision = validate_target_revision_id(accepted_revision)
    participants = run_config["participants"]
    turn_limit = request["max_rounds"] * len(participants)
    if len(turns) > turn_limit:
        raise ContractError("completed turns exceed request.max_rounds")

    previous_revision = None
    completed_initial_turn = False
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
        revision = turn["target_revision"]
        if revision is not None:
            revision = validate_target_revision_id(revision)
        if participant["role"] == "initial_position":
            if revision is None:
                raise ContractError(
                    "%s completed initial-position turn must accept a target "
                    "revision"
                    % ctx
                )
            completed_initial_turn = True
        elif revision != previous_revision:
            raise ContractError(
                "%s changes the target revision outside the initial "
                "position turn" % ctx
            )
        previous_revision = revision

    expected_rounds = len(turns) // len(participants)
    if rounds_used != expected_rounds:
        raise ContractError(
            "state.rounds_used must count only complete roster passes"
        )
    if rounds_used > request["max_rounds"]:
        raise ContractError("state.rounds_used exceeds request.max_rounds")
    if accepted_revision != previous_revision:
        raise ContractError(
            "accepted_target_revision must match the latest completed turn"
        )
    if completed_initial_turn is not (accepted_revision is not None):
        raise ContractError(
            "accepted_target_revision must exist exactly after completed "
            "initial-position work"
        )
    return {
        "completed_turns": _json_copy(turns, "state.completed_turns"),
        "rounds_used": rounds_used,
        "recovery_baseline_revision": recovery_baseline,
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
    leads = [
        item for item in eligible
        if item["role"] == "initial_position"
        and item["delivery"] == "llm"
    ]
    interlocutors = [
        item for item in eligible
        if item["role"] == "contrary_position"
        and item["delivery"] == "llm"
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
            and participant.get("delivery") == "llm"
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
                item["role"] == "contrary_position"
                and item["delivery"] == "llm"
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
    if event["kind"] in ("material_interruption", "floor_intervention"):
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
        elif kind == "floor_intervention":
            fact = validate_floor_intervention(event["fact"])
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


def validate_floor_intervention(intervention):
    """Validate one out-of-turn intervention by an external actor."""
    _exact_keys(
        intervention,
        ("after_completed_turns", "author_id", "author_name", "plain", "at"),
        (),
        "floor_intervention",
    )
    after = intervention["after_completed_turns"]
    if type(after) is not int or after < 0:
        raise ContractError(
            "floor_intervention.after_completed_turns must be a "
            "non-negative integer"
        )
    author_id = _text(intervention["author_id"], "floor_intervention.author_id")
    if not FLOOR_AUTHOR_ID_RE.match(author_id):
        raise ContractError(
            "floor_intervention.author_id must be label_hex32-shaped"
        )
    _text(intervention["author_name"], "floor_intervention.author_name")
    _text(intervention["plain"], "floor_intervention.plain")
    at = intervention["at"]
    if (
        isinstance(at, bool)
        or not isinstance(at, (int, float))
        or not math.isfinite(float(at))
        or float(at) <= 0
    ):
        raise ContractError(
            "floor_intervention.at must be a positive finite number"
        )
    checked = _json_copy(intervention, "floor_intervention")
    checked["at"] = float(at)
    return checked


def closure_voters(run_config):
    """Return only the positions whose agreement can close a session."""
    checked = validate_run_config(run_config)
    return [
        participant
        for participant in checked["participants"]
        if participant["role"] in POSITION_ROLES
    ]


def _validate_closure_votes(votes, run_config):
    checked_config = validate_run_config(run_config)
    participants = closure_voters(checked_config)
    if not isinstance(votes, list) or len(votes) != len(participants):
        raise ContractError(
            "closure_ballot.votes must contain every position once"
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
        if (
            participant["role"] == "initial_position"
            and vote["vote"] != "accept"
        ):
            raise ContractError(
                "the initial position's closure proposal must be recorded "
                "as accept"
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
    return accepts > objects


def evaluate_closure(run_config, votes):
    """Apply the persisted closure policy to one exact roster ballot."""
    checked_config, checked_votes = _validate_closure_votes(votes, run_config)
    return _closure_decision(checked_config, checked_votes)


def validate_closure_ballot(ballot, run_config):
    """Validate one complete ballot and derive its policy decision."""
    _exact_keys(
        ballot,
        ("after_completed_rounds", "target_revision", "votes", "approved"),
        ("closing_summary",),
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
    if "closing_summary" in ballot:
        checked["closing_summary"] = validate_closing_summary_shape(
            ballot["closing_summary"]
        )
    return checked


CLOSING_SUMMARY_REQUIRED = (
    "reason",
    "unresolved_objections",
    "affected_parties",
    "damage_altitude",
    "proportionality",
    "escalation_evidence",
)

CLOSING_SUMMARY_OPTIONAL = ("open_questions",)


def validate_model_closing_summary(summary):
    """The participant-authored summary as it arrives from the model: its
    surplus is dropped AT THE DOOR (operator rule, 2026-08-11), and what
    passes is then the ordinary stored shape. Every later validation runs
    on a session record we own, where a surplus field is our own bug and
    must still fail loudly."""
    _model_keys(
        summary,
        CLOSING_SUMMARY_REQUIRED,
        CLOSING_SUMMARY_OPTIONAL,
        "closing_summary",
    )
    return validate_closing_summary_shape(summary)


def validate_closing_summary_shape(summary):
    """Validate the participant-authored fields shared by both outcomes."""
    _exact_keys(
        summary,
        CLOSING_SUMMARY_REQUIRED,
        CLOSING_SUMMARY_OPTIONAL,
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
    questions = summary.get("open_questions")
    if questions is not None:
        if not isinstance(questions, list):
            raise ContractError(
                "closing_summary.open_questions must be a list"
            )
        for index, question in enumerate(questions):
            _text(
                question,
                "closing_summary.open_questions[%d]" % index,
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
        optional = (
            ("failure_origin",)
            if status == "failure"
            else ()
        )
        _exact_keys(record, required, optional, ctx)
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
            if (
                "failure_origin" in record
                and record["failure_origin"] != "operational"
            ):
                raise ContractError(
                    "%s.failure_origin must be operational" % ctx
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
        (
            "participant_sessions",
            "failure_origin",
        ) + _COORDINATION_FIELDS,
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
            proposed_summary = terminal_ballot.get(
                "closing_summary", summary
            )
            ballot_summary = closing_summary_with_ballot_facts(
                proposed_summary, terminal_ballot, run_config
            )
            if not _same_json_value(summary, ballot_summary):
                raise ContractError(
                    "closing_summary must match the voted closing account and "
                    "record every terminal object vote"
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
    failure_origin = state.get("failure_origin")
    if failure_origin is not None:
        if status != "failure" or failure_origin != "operational":
            raise ContractError(
                "state.failure_origin is only operational on failure"
            )
        if state["history"][-1].get("failure_origin") != failure_origin:
            raise ContractError(
                "state.failure_origin must match terminal history"
            )
    elif status == "failure" and "failure_origin" in state["history"][-1]:
        raise ContractError(
            "terminal history failure_origin requires the state marker"
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
    state,
    new_status,
    result=None,
    closing_summary=None,
    failure_origin=None,
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
        if failure_origin is not None and (
            new_status != "failure" or failure_origin != "operational"
        ):
            raise ContractError(
                "failure_origin is only operational on failure"
            )
    elif result is not None:
        raise ContractError("nonterminal transitions cannot carry a result")
    elif closing_summary is not None:
        raise ContractError(
            "nonterminal transitions cannot carry a closing summary"
        )
    elif failure_origin is not None:
        raise ContractError(
            "nonterminal transitions cannot carry a failure origin"
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
        if failure_origin is not None:
            successor["failure_origin"] = failure_origin
            record["failure_origin"] = failure_origin
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
        appended.get("failure_origin"),
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
    """Retain recovery state without accepting target work at setup."""
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
            "recovery_baseline_revision": checked_revision["revision"],
            "accepted_target_revision": None,
        }
    )
    return validate_session_state(successor)


def assert_coordination_initialization_successor(old_state, new_state):
    """Accept exactly the first empty coordination projection."""
    old = validate_session_state(old_state)
    new = validate_session_state(new_state)
    if coordination_projection(old) is not None:
        raise HistoryRewriteError("accepted coordination is already initialized")
    baseline = new.get("recovery_baseline_revision")
    expected = copy.deepcopy(old)
    expected.update(
        {
            "completed_turns": [],
            "rounds_used": 0,
            "recovery_baseline_revision": baseline,
            "accepted_target_revision": None,
        }
    )
    validate_target_revision_id(baseline)
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
    if target_revision is not None:
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
        participant["role"] == "initial_position"
        and target_revision is None
    ):
        raise HistoryRewriteError(
            "a completed initial-position turn must accept the target revision"
        )
    if (
        participant["role"] != "initial_position"
        and target_revision != current["accepted_target_revision"]
    ):
        raise HistoryRewriteError(
            "only a completed initial-position turn may advance the target "
            "revision"
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
    elif kind == "floor_intervention":
        checked_fact = validate_floor_intervention(fact)
        if checked_fact["after_completed_turns"] != len(completed_turns):
            raise HistoryRewriteError(
                "floor intervention must follow current accepted turns"
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
    if "closing_summary" not in checked_ballot:
        raise ContractError(
            "a new closure ballot must retain its closing summary"
        )
    proposed_summary = validate_closing_summary_shape(closing_summary)
    if not _same_json_value(
        checked_ballot["closing_summary"], proposed_summary
    ):
        raise ContractError(
            "terminal closing summary must equal the account that was voted"
        )
    checked_summary = validate_closing_summary(
        closing_summary_with_ballot_facts(
            proposed_summary, checked_ballot, current["run_config"]
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
    state,
    interruption,
    result,
    closing_summary,
    failure_origin=None,
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
        interrupted,
        "failure",
        result,
        closing_summary,
        failure_origin=failure_origin,
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
    old_state,
    new_state,
    interruption,
    result,
    closing_summary,
    failure_origin=None,
):
    """Accept only the exact combined interruption/failure successor."""
    old = validate_session_state(old_state)
    new = validate_session_state(new_state)
    expected = terminal_interruption_successor(
        old,
        interruption,
        result,
        closing_summary,
        failure_origin=failure_origin,
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
    contrary = 0
    for participant in run_config["participants"]:
        if participant["role"] == "initial_position":
            labels[participant["id"]] = "Initial Position"
        elif participant["role"] == "common_sense":
            labels[participant["id"]] = "Dante"
        else:
            contrary += 1
            labels[participant["id"]] = (
                "Contrary Position"
                if contrary == 1
                else "Contrary Position %d" % contrary
            )
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
        return "Every position must agree before the session can close."
    return "A strict majority of the positions decides; a tie is a gap."


def _entry(title, *parts):
    return "## %s\n\n%s" % (title, "\n\n".join(parts))


def _field(label, value):
    return "**%s**\n\n%s" % (label, value)


def _render_opening(state, labels):
    roster = []
    for participant in state["run_config"]["participants"]:
        label = labels[participant["id"]]
        if participant["role"] == "initial_position":
            role = "presents the initial position and owns target edits"
        elif participant["role"] == "contrary_position":
            role = "challenges the initial position"
        else:
            role = "asks common-sense anti-drift questions and does not vote"
        roster.append("- **%s** — %s." % (label, role))
    rounds = state["request"]["max_rounds"]
    return _entry(
        "Opening",
        _field(
            "Requested outcome",
            _quoted_markdown(state["request"]["request"]),
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
    if event["kind"] == "floor_intervention":
        # The author id is machine identity; only the name faces humans.
        return _entry(
            "Intervention — %s" % fact["author_name"],
            _quoted_markdown(fact["plain"]),
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
    fields = [
        _field("Votes", "\n".join(votes)),
        _field(
            "Applied agreement rule",
            _closure_rule(state["run_config"]["closure_policy"]),
        ),
        _field("Result", decision),
    ]
    summary = fact.get("closing_summary")
    if summary is not None:
        questions = summary.get("open_questions", [])
        fields[0:0] = [
            _field(
                "Proposed final agreement",
                _quoted_markdown(summary["reason"]),
            ),
            _field(
                "Open questions",
                (
                    "No open questions were recorded."
                    if not questions
                    else "\n\n".join(
                        _quoted_markdown(question)
                        for question in questions
                    )
                ),
            ),
        ]
    return _entry(
        "Closure ballot — After round %d" % round_number,
        "The target considered was the target completed after round %d."
        % round_number,
        *fields,
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
    questions = summary.get("open_questions", [])
    questions_text = (
        "No open questions were recorded."
        if not questions
        else "\n\n".join(
            _quoted_markdown(question) for question in questions
        )
    )
    return _entry(
        "Closing",
        _field("Agreement", agreement),
        _field(
            "Final agreement"
            if result["outcome"] == "success"
            else "Reason",
            _quoted_markdown(summary["reason"]),
        ),
        _field("Open questions", questions_text),
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


def _external_intervention_key(session_id):
    return _EXTERNAL_INTERVENTION_KEY_PREFIX + kvstore.validate_fragment(
        session_id, "session_id"
    )


def _activity_key(session_id):
    return _ACTIVITY_KEY_PREFIX + kvstore.validate_fragment(
        session_id, "session_id"
    )


def _task_effect_attempt_key(session_id):
    return _TASK_EFFECT_ATTEMPT_KEY_PREFIX + kvstore.validate_fragment(
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

    def _session_directory(self, session_id):
        """Return private runtime storage for prompts and provider outputs."""
        session_id = kvstore.validate_fragment(session_id, "session_id")
        directory = hashlib.sha256(
            session_id.encode("utf-8", errors="surrogatepass")
        ).hexdigest()
        return os.path.abspath(os.path.join(self._transcript_root, directory))

    def transcript_ref(self, session_id):
        """Return this session's private, operational chat reference."""
        return os.path.join(self._session_directory(session_id), "chat.md")

    def delivered_transcript_ref(self, session_id, request):
        """Return the final chat artifact placed beside the target."""
        session_id = kvstore.validate_fragment(session_id, "session_id")
        checked = validate_request(request)
        target = checked["target_path"]
        if not os.path.isabs(target):
            target = os.path.join(checked["workspace_path"], target)
        return os.path.join(
            os.path.dirname(os.path.abspath(target)),
            "chat-%s.md" % session_id,
        )

    def prompt_directory(self, session_id):
        """Brainstorming-owned runtime directory for exact LLM prompts."""
        return os.path.join(self._session_directory(session_id), "prompts")

    def output_directory(self, session_id):
        """Brainstorming-owned runtime directory for exact LLM outputs."""
        return os.path.join(self._session_directory(session_id), "outputs")

    def save_activity_output(self, session_id, event_id, text):
        """Persist one immutable provider output and return its safe name."""
        if not isinstance(text, str):
            raise ContractError("activity output must be text")
        safe = "".join(
            char
            if char.isascii() and (char.isalnum() or char in "._-")
            else "_"
            for char in _text(event_id, "activity_event.id")
        ).strip("._-")[:96] or "activity"
        directory = self.output_directory(session_id)
        os.makedirs(directory, exist_ok=True)
        candidate = safe
        counter = 1
        while True:
            name = candidate + ".txt"
            path = os.path.join(directory, name)
            try:
                fd = os.open(
                    path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666
                )
            except FileExistsError:
                candidate = "%s-%d" % (safe, counter)
                counter += 1
                continue
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(text.encode("utf-8"))
            except BaseException:
                try:
                    os.unlink(path)
                except OSError:
                    pass
                raise
            return name

    def read_activity_output(self, session_id, raw_ref):
        """Read one session-owned output without following path fragments."""
        raw_ref = _text(raw_ref, "activity_event.raw_ref")
        if os.path.basename(raw_ref) != raw_ref:
            raise ContractError("activity_event.raw_ref is invalid")
        path = os.path.join(self.output_directory(session_id), raw_ref)
        if os.path.islink(path):
            raise ContractError("activity output must not be a symbolic link")
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()

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
        discarded_underfoot = False
        with _exclusive_transcript(path):
            snapshot = self._snapshot(self._store.read(key))
            if snapshot is None:
                discarded_underfoot = True
                for leftover in (path, path + ".lock"):
                    try:
                        os.unlink(leftover)
                    except OSError:
                        pass
            else:
                if snapshot.state["transcript_ref"] != path:
                    raise HistoryRewriteError(
                        "session transcript reference does not match its "
                        "authority"
                    )
                rendered = render_transcript(snapshot.state)
                _atomic_replace_utf8(path, rendered)
                return snapshot
        if discarded_underfoot:
            try:
                os.rmdir(os.path.dirname(path))
            except OSError:
                pass
        return None

    def _deliver_transcript(self, session_id, state):
        """Place the final chat beside the target, once, at the end.

        This is a PRODUCT artifact, so the discussion ending is what
        delivers it. Reconciling it from the read path instead — as this
        once did — made delivery a side effect of looking at the session:
        the panel polls every two seconds, so an operator who deleted a
        delivered chat watched it come straight back.

        Delivery is the operator's choice and is OFF by default, so the
        gate lives here rather than at the one call site: nothing writes
        the chat into the workspace unless the request asked for it. The
        session's own transcript is unaffected — it is always kept, and
        the panel always shows it.
        """
        if not delivers_chat(state["request"]):
            return None
        delivered = self.delivered_transcript_ref(
            session_id, state["request"]
        )
        os.makedirs(os.path.dirname(delivered), exist_ok=True)
        _atomic_replace_utf8(delivered, render_transcript(state))
        return delivered

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

    def read_external_intervention(self, session_id):
        """Read the one ordered external response request, if present."""
        record = self._store.read(_external_intervention_key(session_id))
        if not record["exists?"]:
            return None
        return validate_external_intervention(record["value"])

    def publish_external_intervention(self, session_id, intervention):
        """Publish an external turn only for the exact durable next action."""
        checked = validate_external_intervention(intervention)
        if (
            checked["provider_attempt"] != 0
            or not checked["provider_quiescent"]
            or checked["response"] is not None
        ):
            raise ContractError(
                "a new external intervention must be unanswered and unclaimed"
            )
        snapshot = self.read(session_id)
        if snapshot is None:
            raise SessionNotFound(session_id)
        if snapshot.state["status"] != "running":
            raise IllegalTransition(
                "external interventions require a running session"
            )
        projection = coordination_projection(snapshot.state)
        if projection is None:
            raise HistoryRewriteError(
                "external intervention requires initialized coordination"
            )
        participants = snapshot.state["run_config"]["participants"]
        participant = next(
            (
                item
                for item in participants
                if item["id"] == checked["participant_id"]
            ),
            None,
        )
        if participant is None or participant["delivery"] != "external":
            raise HistoryRewriteError(
                "external intervention participant is not an external seat"
            )
        turns = projection["completed_turns"]
        if checked["action_kind"] == "discussion_turn":
            expected = participants[len(turns) % len(participants)]
            expected_round = len(turns) // len(participants) + 1
            valid_action = (
                expected["id"] == checked["participant_id"]
                and checked["round"] == expected_round
            )
        else:
            valid_action = (
                bool(turns)
                and len(turns) == projection["rounds_used"] * len(participants)
                and checked["round"] == projection["rounds_used"]
                and not any(
                    event["kind"] == "closure_ballot"
                    and event["fact"]["after_completed_rounds"]
                    == projection["rounds_used"]
                    for event in snapshot.state["transcript_events"]
                )
            )
        request = snapshot.state["request"]
        expected_input = {
            "request": request["request"],
            "context": request["context"],
            "workspace_path": request["workspace_path"],
            "target_path": request["target_path"],
            "transcript_ref": snapshot.state["transcript_ref"],
        }
        if (
            not valid_action
            or checked["completed_turn_count"] != len(turns)
            or checked["target_revision"]
            != projection["accepted_target_revision"]
            or not _same_json_value(checked["input"], expected_input)
        ):
            raise HistoryRewriteError(
                "external intervention does not match durable accepted progress"
            )
        if self.read_turn_attempt(session_id) is not None:
            raise HistoryRewriteError(
                "external intervention cannot overlap a worker attempt"
            )
        key = _external_intervention_key(session_id)
        current = self._store.read(key)
        if current["exists?"]:
            raise HistoryRewriteError(
                "an external intervention is already pending"
            )
        result = self._store.cas(key, current["revision"], checked)
        if not result.ok:
            raise HistoryRewriteError(
                "an external intervention is already pending"
            )
        return validate_external_intervention(result.record["value"])

    def advance_external_intervention(
        self, session_id, consumed_token, intervention
    ):
        """Atomically carry one external closure vote into the next seat."""
        consumed_token = _text(
            consumed_token, "external_intervention.token"
        )
        checked = validate_external_intervention(intervention)
        if (
            checked["action_kind"] != "closure_vote"
            or checked["provider_attempt"] != 0
            or not checked["provider_quiescent"]
            or checked["response"] is not None
        ):
            raise ContractError(
                "the next external closure intervention must be unclaimed"
            )
        key = _external_intervention_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("external intervention is missing")
        prior = validate_external_intervention(current["value"])
        if prior["token"] != consumed_token:
            raise HistoryRewriteError("external intervention token changed")
        if (
            prior["action_kind"] != "closure_vote"
            or prior["response"] is None
            or not prior["provider_quiescent"]
        ):
            raise HistoryRewriteError(
                "only an answered closure intervention can advance"
            )
        self._preserve_external_call_accounting(session_id, prior)
        for field in (
            "action_kind",
            "completed_turn_count",
            "round",
            "target_revision",
            "input",
        ):
            if not _same_json_value(prior[field], checked[field]):
                raise HistoryRewriteError(
                    "advanced external closure changed %s" % field
                )
        if not _same_json_value(
            prior["closure_context"]["closing_summary"],
            checked["closure_context"]["closing_summary"],
        ):
            raise HistoryRewriteError(
                "advanced external closure changed its closing summary"
            )

        snapshot = self.read(session_id)
        if snapshot is None or snapshot.state["status"] != "running":
            raise HistoryRewriteError(
                "external intervention no longer belongs to a running session"
            )
        participants = snapshot.state["run_config"]["participants"]
        positions = {item["id"]: index for index, item in enumerate(participants)}
        old_index = positions.get(prior["participant_id"])
        new_index = positions.get(checked["participant_id"])
        if (
            old_index is None
            or new_index is None
            or new_index <= old_index
            or participants[new_index]["delivery"] != "external"
        ):
            raise HistoryRewriteError(
                "advanced external closure does not select a later external seat"
            )

        def expected_vote_ids(before_index):
            included = {
                item["id"]
                for index, item in enumerate(participants)
                if item["role"] == "initial_position"
                or (
                    item["role"] == "contrary_position"
                    and index < before_index
                )
            }
            return [
                item["id"] for item in participants if item["id"] in included
            ]

        prior_votes = prior["closure_context"]["votes"]
        next_votes = checked["closure_context"]["votes"]
        if (
            [item["participant_id"] for item in prior_votes]
            != expected_vote_ids(old_index)
            or [item["participant_id"] for item in next_votes]
            != expected_vote_ids(new_index)
        ):
            raise HistoryRewriteError(
                "advanced external closure has an invalid vote prefix"
            )
        next_by_id = {
            item["participant_id"]: item["vote"] for item in next_votes
        }
        if any(
            next_by_id.get(item["participant_id"]) != item["vote"]
            for item in prior_votes
        ) or next_by_id.get(prior["participant_id"]) != prior["response"][
            "payload"
        ]["vote"]:
            raise HistoryRewriteError(
                "advanced external closure did not retain the consumed vote"
            )
        if self.read_turn_attempt(session_id) is not None:
            raise HistoryRewriteError(
                "external intervention cannot overlap a worker attempt"
            )
        result = self._store.cas(key, current["revision"], checked)
        if not result.ok:
            raise HistoryRewriteError(
                "external intervention changed before advancing"
            )
        return validate_external_intervention(result.record["value"])

    def claim_external_intervention(self, session_id, token):
        """Record one automatic provider attempt before invoking it."""
        token = _text(token, "external_intervention.token")
        key = _external_intervention_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("external intervention is missing")
        intervention = validate_external_intervention(current["value"])
        if intervention["token"] != token:
            raise HistoryRewriteError("external intervention token changed")
        if intervention["response"] is not None:
            raise HistoryRewriteError("external intervention is already answered")
        if not intervention["provider_quiescent"]:
            raise HistoryRewriteError(
                "the prior external provider attempt is not confirmed finished"
            )
        self._preserve_external_call_accounting(session_id, intervention)
        intervention["provider_attempt"] += 1
        intervention["provider_quiescent"] = False
        # The mark describes the attempt it was written for; this new claim
        # is not refused until its own dispatch says so.
        intervention.pop("dispatch_refused", None)
        result = self._store.cas(key, current["revision"], intervention)
        if not result.ok:
            raise HistoryRewriteError(
                "external intervention changed before provider claim"
            )
        return validate_external_intervention(result.record["value"])

    def mark_external_provider_quiescent(
        self, session_id, token, dispatch_refused=False
    ):
        """Record that one claimed automatic provider can no longer act.

        *dispatch_refused* says this claimed attempt was refused before any
        provider was started — nothing ran, so retiring the attempt owes it
        no call accounting.
        """
        token = _text(token, "external_intervention.token")
        key = _external_intervention_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("external intervention is missing")
        intervention = validate_external_intervention(current["value"])
        if intervention["token"] != token:
            raise HistoryRewriteError("external intervention token changed")
        if intervention["response"] is not None:
            raise HistoryRewriteError("external intervention is already answered")
        if intervention["provider_quiescent"]:
            return intervention
        if dispatch_refused:
            intervention["dispatch_refused"] = True
        self._preserve_external_call_accounting(session_id, intervention)
        intervention["provider_quiescent"] = True
        result = self._store.cas(key, current["revision"], intervention)
        if not result.ok:
            raise HistoryRewriteError(
                "external intervention changed before provider quiescence"
            )
        return validate_external_intervention(result.record["value"])

    def retry_external_provider(self, session_id, token):
        """Start one repair after the prior provider call became quiescent."""
        token = _text(token, "external_intervention.token")
        key = _external_intervention_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("external intervention is missing")
        intervention = validate_external_intervention(current["value"])
        if intervention["token"] != token:
            raise HistoryRewriteError("external intervention token changed")
        if intervention["response"] is not None:
            raise HistoryRewriteError("external intervention is already answered")
        if intervention["provider_quiescent"]:
            raise HistoryRewriteError(
                "external provider repair has no active prior attempt"
            )
        self._preserve_external_call_accounting(session_id, intervention)
        intervention["provider_attempt"] += 1
        # As in `claim_external_intervention`: the repair is its own attempt.
        intervention.pop("dispatch_refused", None)
        result = self._store.cas(key, current["revision"], intervention)
        if not result.ok:
            raise HistoryRewriteError(
                "external intervention changed before provider repair"
            )
        return validate_external_intervention(result.record["value"])

    def _deliver_external_response(
        self, session_id, token, payload, automatic
    ):
        token = _text(token, "external_intervention.token")
        payload = _json_copy(payload, "external intervention response")
        session_key = _session_key(session_id)
        intervention_key = _external_intervention_key(session_id)

        def deliver(document):
            session_raw = self._store._raw_from_doc(document, session_key)
            session_public = self._store._public_from_raw(session_raw)
            if (
                not session_public["exists?"]
                or validate_session_state(session_public["value"])["status"]
                != "running"
            ):
                return (False, "session is no longer running"), False
            raw = self._store._raw_from_doc(document, intervention_key)
            public = self._store._public_from_raw(raw)
            if not public["exists?"]:
                return (False, "external intervention is missing"), False
            intervention = validate_external_intervention(public["value"])
            if intervention["token"] != token:
                return (False, "external intervention token changed"), False
            if intervention["response"] is not None:
                return (False, "external intervention is already answered"), False
            if automatic:
                if (
                    intervention["provider_attempt"] <= 0
                    or intervention["provider_quiescent"]
                ):
                    return (False, "automatic provider is not active"), False
                intervention["provider_quiescent"] = True
            elif not intervention["provider_quiescent"]:
                return (False, "automatic provider is still active"), False
            intervention["response"] = {
                "received_at": time.time(),
                "payload": payload,
            }
            intervention = validate_external_intervention(intervention)
            envelope = {
                "revision": raw["revision"] + 1,
                "value": intervention,
                "deleted?": False,
            }
            native = document["entries"].get(intervention_key)
            self._store.client._set_entry(
                document,
                intervention_key,
                envelope,
                native["rev"] + 1,
            )
            return (True, intervention), True

        accepted, value = self._store.client._mutate(deliver)
        if not accepted:
            raise HistoryRewriteError(value)
        return value

    def submit_external_intervention(self, session_id, token, payload):
        """Accept one external response exactly once while the run is live."""
        return self._deliver_external_response(
            session_id, token, payload, automatic=False
        )

    def complete_external_provider(self, session_id, token, payload):
        """Atomically finish one automatic provider and accept its response."""
        return self._deliver_external_response(
            session_id, token, payload, automatic=True
        )

    def _preserve_external_call_accounting(self, session_id, intervention):
        """Retain token uncertainty before an external attempt is retired."""
        attempt = intervention["provider_attempt"]
        if attempt <= 0:
            return
        if intervention.get("dispatch_refused", False):
            # This claimed attempt was refused before it started: there is
            # no call whose tokens or cost could be uncertain, so there is
            # nothing to preserve and no activity to write for it.
            return
        activity = self.read_activity(session_id)
        if any(
            event["action_id"] == intervention["token"]
            and event["provider_attempt"] == attempt
            for event in ((activity or {}).get("events") or [])
        ):
            return
        response = intervention.get("response")
        action_id = intervention["token"]
        digest = hashlib.sha256(
            ("%s:%d" % (action_id, attempt)).encode("utf-8")
        ).hexdigest()[:20]
        kind = (
            "discussion_turn"
            if intervention["action_kind"] == "discussion_turn"
            else "closure"
        )
        recorded_at = (
            response["received_at"] if response is not None else time.time()
        )
        event = {
            "id": "activity-%s" % digest,
            "action_id": action_id,
            "provider_attempt": attempt,
            "at": time.strftime(
                "%Y-%m-%dT%H:%M:%S%z", time.localtime(recorded_at)
            ),
            "started_at": recorded_at,
            "duration_s": 0.0,
            "kind": kind,
            "stage": "discussion" if kind == "discussion_turn" else "vote",
            "round": intervention["round"],
            "participant_id": intervention["participant_id"],
            "model_family": "external-provider",
            "model": None,
            "effort": None,
            "status": "completed" if response is not None else "failed",
            "token_usage_partial": True,
                    "cost_partial": True,
        }
        if response is None:
            event.update({
                "failure_type": "execution",
                "error": "provider call ended without durable activity",
            })
        self.append_activity(session_id, event)

    def preserve_turn_attempt_accounting(self, session_id, token):
        """Retain token uncertainty before a quiescent worker is retired."""
        token = _text(token, "turn_attempt.token")
        attempt = self.read_turn_attempt(session_id)
        if attempt is None:
            raise HistoryRewriteError("the active turn attempt is missing")
        if attempt["token"] != token:
            raise HistoryRewriteError("the active turn attempt token changed")
        if not attempt["quiescent"]:
            raise HistoryRewriteError(
                "only a quiescent turn attempt can preserve accounting"
            )
        if attempt.get("dispatch_refused", False):
            # This provider attempt was refused before it started: there is
            # no call whose tokens or cost could be uncertain, so there is
            # nothing to preserve and no activity to write for it.
            return
        provider_attempt = attempt.get("provider_attempt", 1)
        activity = self.read_activity(session_id)
        events = (activity or {}).get("events") or []
        snapshot = self.read(session_id)
        if snapshot is None:
            raise SessionNotFound(session_id)
        participants = snapshot.state["run_config"]["participants"]
        participant = next(
            (
                item
                for item in participants
                if item["id"] == attempt["participant_id"]
            ),
            None,
        )
        if participant is None or participant["delivery"] != "llm":
            raise HistoryRewriteError(
                "the active turn attempt participant is unavailable"
            )
        kind = attempt.get("kind", "discussion_turn")
        stage = (
            (attempt.get("action_context") or {}).get("stage")
            if kind == "closure"
            else "discussion"
        )
        completed = attempt["completed_turn_count"]
        round_number = (
            completed // len(participants) + 1
            if kind == "discussion_turn"
            else max(1, completed // len(participants))
        )
        recorded_at = time.time()
        if not any(
            event["action_id"] == token
            and event["provider_attempt"] == provider_attempt
            for event in events
        ):
            started_at = attempt.get("started_at", recorded_at)
            digest = hashlib.sha256(
                ("%s:%d" % (token, provider_attempt)).encode("utf-8")
            ).hexdigest()[:20]
            self.append_activity(
                session_id,
                {
                    "id": "activity-%s" % digest,
                    "action_id": token,
                    "provider_attempt": provider_attempt,
                    "at": time.strftime(
                        "%Y-%m-%dT%H:%M:%S%z", time.localtime(recorded_at)
                    ),
                    "started_at": started_at,
                    "duration_s": max(0.0, recorded_at - started_at),
                    "kind": kind,
                    "stage": stage,
                    "round": round_number,
                    "participant_id": participant["id"],
                    "model_family": participant["model_family"],
                    "model": None,
                    "effort": None,
                    "status": "failed",
                    "failure_type": "execution",
                    "error": "provider call ended without durable activity",
                    "token_usage_partial": True,
                    "cost_partial": True,
                },
            )
        classifier = attempt.get("classifier_call")
        classifier_action = "%s:classifier" % token
        if classifier is not None and not any(
            event["action_id"] == classifier_action
            and event["provider_attempt"] == provider_attempt
            for event in events
        ):
            digest = hashlib.sha256(
                ("%s:%d" % (classifier_action, provider_attempt)).encode(
                    "utf-8"
                )
            ).hexdigest()[:20]
            self.append_activity(
                session_id,
                {
                    "id": "activity-%s" % digest,
                    "action_id": classifier_action,
                    "provider_attempt": provider_attempt,
                    "at": time.strftime(
                        "%Y-%m-%dT%H:%M:%S%z", time.localtime(recorded_at)
                    ),
                    "started_at": classifier["started_at"],
                    "duration_s": max(
                        0.0, recorded_at - classifier["started_at"]
                    ),
                    "kind": "classifier",
                    "stage": "classification",
                    "round": round_number,
                    "participant_id": "recovery-classifier",
                    "model_family": classifier["family"],
                    "model": classifier["model"],
                    "effort": classifier["effort"],
                    "status": "failed",
                    "failure_type": "execution",
                    "error": "classifier call ended without durable activity",
                    "token_usage_partial": True,
                    "cost_partial": True,
                },
            )

    def finish_external_intervention(self, session_id, token):
        """Remove one response only after its turn or vote was consumed."""
        token = _text(token, "external_intervention.token")
        key = _external_intervention_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            return
        intervention = validate_external_intervention(current["value"])
        if intervention["token"] != token:
            raise HistoryRewriteError("external intervention token changed")
        if intervention["response"] is None:
            raise HistoryRewriteError(
                "an unanswered external intervention cannot finish"
            )
        self._preserve_external_call_accounting(session_id, intervention)
        result = self._store.delete(key, expected_revision=current["revision"])
        if not result.ok:
            raise HistoryRewriteError(
                "external intervention changed before completion"
            )

    def read_turn_attempt(self, session_id):
        """Read the exclusive in-flight control record, if one remains."""
        record = self._store.read(_turn_attempt_key(session_id))
        if not record["exists?"]:
            return None
        return validate_turn_attempt(record["value"])

    def begin_turn_attempt(self, session_id, turn_attempt):
        """Persist worker admission before invoking one target-aware control."""
        checked = validate_turn_attempt(turn_attempt)
        checked["started_at"] = time.time()
        checked["provider_attempt"] = 1
        if "target_parent" not in checked:
            raise ContractError(
                "new turn attempts require a pinned target_parent"
            )
        if checked["quiescent"]:
            raise ContractError("a new turn attempt cannot start quiescent")
        if checked.get("envelope_repair_used", False):
            raise ContractError(
                "a new turn attempt cannot start with envelope repair used"
            )
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

    @staticmethod
    def _turn_attempt_action(attempt):
        return {
            "participant_id": attempt["participant_id"],
            "completed_turn_count": attempt["completed_turn_count"],
            "target_revision": attempt["target_revision"],
            "target_parent": attempt.get("target_parent"),
            "kind": attempt.get("kind", "discussion_turn"),
            "action_context": attempt.get("action_context"),
        }

    def restart_turn_attempt(self, session_id, turn_attempt):
        """Retry exactly one corrected pending action under a fresh token."""
        checked = validate_turn_attempt(turn_attempt)
        if checked["quiescent"] or checked.get("retry_pending"):
            raise ContractError(
                "a restarted turn attempt must begin active"
            )
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError(
                "the corrected pending turn attempt is missing"
            )
        prior = validate_turn_attempt(current["value"])
        if (
            not prior.get("retry_pending", False)
            or prior.get("target_mutation_corrections", 0) != 1
            or not _same_json_value(
                self._turn_attempt_action(prior),
                self._turn_attempt_action(checked),
            )
        ):
            raise HistoryRewriteError(
                "the corrected retry does not match the pending worker action"
            )
        checked["target_mutation_corrections"] = 1
        if prior.get("envelope_repair_used", False):
            checked["envelope_repair_used"] = True
        checked["started_at"] = time.time()
        checked["provider_attempt"] = prior.get("provider_attempt", 1) + 1
        checked["retry_pending"] = False
        result = self._store.cas(key, current["revision"], checked)
        if not result.ok:
            raise HistoryRewriteError(
                "the pending worker action changed before its corrected retry"
            )
        return checked

    def schedule_operational_retry(
        self, session_id, token, classification, retry_at
    ):
        """Keep one quiescent action pending after a recoverable call fault."""
        token = _text(token, "turn_attempt.token")
        if not isinstance(classification, dict):
            raise ContractError("operational classification must be an object")
        candidate_retry = {
            "error_type": classification.get("error_type"),
            "resume_at": classification.get("resume_at"),
            "evidence": classification.get("evidence"),
            "retry_at": retry_at,
        }
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("the active turn attempt is missing")
        attempt = validate_turn_attempt(current["value"])
        if attempt["token"] != token:
            raise HistoryRewriteError("the active turn attempt token changed")
        if (
            not attempt["quiescent"]
            or attempt.get("retry_pending", False)
            or attempt.get("target_mutation_failure_pending", False)
            or attempt.get("operational_retry") is not None
        ):
            raise HistoryRewriteError(
                "the turn attempt cannot enter operational retry"
            )
        attempt["operational_retry"] = candidate_retry
        checked = validate_turn_attempt(attempt)
        result = self._store.cas(key, current["revision"], checked)
        if not result.ok:
            raise HistoryRewriteError(
                "the active turn attempt changed before operational retry"
            )
        return checked

    def restart_operational_turn_attempt(self, session_id, turn_attempt):
        """Retry the same logical action after its operational timer."""
        checked = validate_turn_attempt(turn_attempt)
        if checked["quiescent"] or checked.get("retry_pending"):
            raise ContractError(
                "a restarted operational attempt must begin active"
            )
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError(
                "the operationally pending turn attempt is missing"
            )
        prior = validate_turn_attempt(current["value"])
        retry = prior.get("operational_retry")
        if (
            retry is None
            or time.time() < retry["retry_at"]
            or not _same_json_value(
                self._turn_attempt_action(prior),
                self._turn_attempt_action(checked),
            )
        ):
            raise HistoryRewriteError(
                "the operational retry is not due or does not match the "
                "pending worker action"
            )
        checked["token"] = prior["token"]
        if prior.get("target_mutation_corrections", 0):
            checked["target_mutation_corrections"] = prior[
                "target_mutation_corrections"
            ]
        if prior.get("envelope_repair_used", False):
            checked["envelope_repair_used"] = True
        checked["started_at"] = time.time()
        checked["provider_attempt"] = prior.get("provider_attempt", 1) + 1
        result = self._store.cas(key, current["revision"], checked)
        if not result.ok:
            raise HistoryRewriteError(
                "the pending worker action changed before operational retry"
            )
        return checked

    def mark_turn_attempt_quiescent(
        self, session_id, token, dispatch_refused=False
    ):
        """Durably record that the admitted worker can no longer mutate.

        *dispatch_refused* says this attempt's current provider call was
        refused before any provider was started — nothing ran, so retiring
        the attempt owes it no call accounting.
        """
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
        if dispatch_refused:
            attempt["dispatch_refused"] = True
        result = self._store.cas(key, current["revision"], attempt)
        if not result.ok:
            raise HistoryRewriteError(
                "the active turn attempt changed before quiescence"
            )
        return attempt

    def begin_turn_classifier_call(self, session_id, call):
        """Admit one classifier call before its provider can start."""
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("the active turn attempt is missing")
        attempt = validate_turn_attempt(current["value"])
        if attempt.get("classifier_call") is not None:
            raise HistoryRewriteError(
                "a classifier call is already active for this turn"
            )
        candidate = copy.deepcopy(attempt)
        candidate["classifier_call"] = {
            "family": call.get("family"),
            "model": call.get("model"),
            "effort": call.get("effort"),
            "started_at": call.get("started_at"),
        }
        candidate = validate_turn_attempt(candidate)
        result = self._store.cas(key, current["revision"], candidate)
        if not result.ok:
            raise HistoryRewriteError(
                "the active turn attempt changed before classification"
            )
        return candidate

    def finish_turn_classifier_call(self, session_id):
        """Clear a classifier marker only after its activity is durable."""
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("the active turn attempt is missing")
        attempt = validate_turn_attempt(current["value"])
        if attempt.get("classifier_call") is None:
            return attempt
        candidate = copy.deepcopy(attempt)
        candidate.pop("classifier_call", None)
        result = self._store.cas(
            key, current["revision"], validate_turn_attempt(candidate)
        )
        if not result.ok:
            raise HistoryRewriteError(
                "the active turn attempt changed after classification"
            )
        return candidate

    def mark_turn_attempt_target_mutation(self, session_id, token):
        """Spend the action's sole correction, or report a repetition."""
        token = _text(token, "turn_attempt.token")
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("the active turn attempt is missing")
        attempt = validate_turn_attempt(current["value"])
        if attempt["token"] != token:
            raise HistoryRewriteError("the active turn attempt token changed")
        if not attempt["quiescent"]:
            raise HistoryRewriteError(
                "target mutation cannot be classified before quiescence"
            )
        if attempt.get("target_mutation_corrections", 0) == 1:
            if attempt.get("target_mutation_failure_pending", False):
                return True
            attempt["target_mutation_failure_pending"] = True
            result = self._store.cas(key, current["revision"], attempt)
            if not result.ok:
                raise HistoryRewriteError(
                    "the repeated target mutation changed before failure "
                    "was retained"
                )
            return True
        attempt["target_mutation_corrections"] = 1
        attempt["retry_pending"] = True
        result = self._store.cas(key, current["revision"], attempt)
        if not result.ok:
            raise HistoryRewriteError(
                "the active turn attempt changed before correction"
            )
        return False

    def mark_turn_attempt_envelope_repair(self, session_id, token):
        """Spend the pending action's sole discussion-envelope repair."""
        token = _text(token, "turn_attempt.token")
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("the active turn attempt is missing")
        attempt = validate_turn_attempt(current["value"])
        if attempt["token"] != token:
            raise HistoryRewriteError("the active turn attempt token changed")
        if attempt.get("envelope_repair_used", False):
            return False
        attempt["envelope_repair_used"] = True
        attempt["started_at"] = time.time()
        attempt["provider_attempt"] = attempt.get("provider_attempt", 1) + 1
        result = self._store.cas(key, current["revision"], attempt)
        if not result.ok:
            raise HistoryRewriteError(
                "the active turn attempt changed before envelope repair"
            )
        return True

    def preserve_corrected_turn_retry(self, session_id, token):
        """Keep a previously spent correction attached after a crash."""
        token = _text(token, "turn_attempt.token")
        key = _turn_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise HistoryRewriteError("the active turn attempt is missing")
        attempt = validate_turn_attempt(current["value"])
        if attempt["token"] != token:
            raise HistoryRewriteError("the active turn attempt token changed")
        if (
            not attempt["quiescent"]
            or attempt.get("target_mutation_corrections", 0) != 1
        ):
            raise HistoryRewriteError(
                "only a quiescent corrected action can remain pending"
            )
        if attempt.get("retry_pending", False):
            return attempt
        attempt["retry_pending"] = True
        result = self._store.cas(key, current["revision"], attempt)
        if not result.ok:
            raise HistoryRewriteError(
                "the active turn attempt changed before retry preservation"
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
        if attempt["quiescent"]:
            self.preserve_turn_attempt_accounting(session_id, token)
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
        key = _session_key(session_id)
        if candidate["status"] in TERMINAL_STATUSES:
            intervention_key = _external_intervention_key(session_id)

            def accept_terminal(document):
                raw = self._store._raw_from_doc(document, key)
                public = self._store._public_from_raw(raw)
                if (
                    not public["exists?"]
                    or public["revision"] != expected_revision
                ):
                    return (False, public), False
                assertion(validate_session_state(public["value"]), candidate)
                envelope = {
                    "revision": raw["revision"] + 1,
                    "value": candidate,
                    "deleted?": False,
                }
                native = document["entries"].get(key)
                self._store.client._set_entry(
                    document, key, envelope, native["rev"] + 1
                )

                external_raw = self._store._raw_from_doc(
                    document, intervention_key
                )
                external_envelope = {
                    "revision": (
                        1
                        if external_raw is kvstore.ABSENT
                        else external_raw["revision"] + 1
                    ),
                    "value": None,
                    "deleted?": True,
                }
                external_native = document["entries"].get(intervention_key)
                self._store.client._set_entry(
                    document,
                    intervention_key,
                    external_envelope,
                    1
                    if external_native is None
                    else external_native["rev"] + 1,
                )
                return (
                    True,
                    self._store._public_from_raw(envelope),
                ), True

            accepted, record = self._store.client._mutate(accept_terminal)
        else:
            result = self._store.cas(key, expected_revision, candidate)
            accepted, record = result.ok, result.record
        if not accepted:
            latest = self._publish_current(session_id)
            if latest is None:
                raise SessionNotFound(session_id)
            raise RevisionConflict(latest)
        if candidate["status"] in TERMINAL_STATUSES:
            # Every terminal acceptance funnels through here, so this is
            # the one moment the discussion ends — and the only place the
            # product artifact is written.
            self._deliver_transcript(session_id, candidate)
        if publish:
            return self._publish_current(session_id)
        return self._snapshot(record)

    def create(self, session_id, request, run_config, eligible_participants):
        checked_config = validate_run_config(run_config)
        resolved_config = resolve_run_config(
            checked_config["participants"],
            checked_config["closure_policy"],
            eligible_participants,
        )
        if not _same_json_value(checked_config, resolved_config):
            raise ContractError("run_config does not match roster resolution")
        checked_request = validate_request(request)
        target_path = checked_request["target_path"]
        if not os.path.isabs(target_path):
            target_path = os.path.join(
                checked_request["workspace_path"], target_path
            )
        target_path = os.path.abspath(target_path)
        state = new_session_state(
            checked_request, resolved_config, self.transcript_ref(session_id)
        )
        if _target_overlaps_state_storage(self.path, target_path):
            raise ContractError(
                "request.target_path must not overlap Brainstorming's "
                "durable state store or lock"
            )
        delivered = self.delivered_transcript_ref(session_id, checked_request)
        if os.path.realpath(target_path) == os.path.realpath(delivered):
            raise ContractError(
                "request.target_path must not equal its delivered chat path"
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
        activity = {
            "schema_version": ACTIVITY_SCHEMA_VERSION,
            "events": [],
        }
        activity_result = self._store.cas(
            _activity_key(session_id), None, activity
        )
        if not activity_result.ok:
            self._store.delete(
                _session_key(session_id),
                expected_revision=result.record["revision"],
            )
            raise SessionAlreadyExists(
                "session activity already exists"
            )
        return self._publish_current(session_id)

    def read_activity(self, session_id):
        """Read the append-only operational ledger, if this session has one."""
        record = self._store.read(_activity_key(session_id))
        if not record["exists?"]:
            return None
        return validate_activity_log(record["value"])

    def session_ids_for_target(self, target_path):
        """Find retained session authority for one exact private target."""
        target_path = _text(target_path, "target_path")
        if not os.path.isabs(target_path):
            raise ContractError("target_path must be absolute")
        matches = []
        listing = self._store.list_entries(prefix=_SESSION_KEY_PREFIX)
        for item in listing["items"]:
            key = item["key"]
            session_id = key[len(_SESSION_KEY_PREFIX):]
            record = self._store.read(key)
            if not record["exists?"]:
                continue
            # This is a scan over EVERY stored session, most of which belong
            # to other callers and other eras. Match on the raw request path
            # first and validate only a candidate: a record that no longer
            # satisfies the current contract (for instance a session written
            # under an earlier participant-role vocabulary) can never be the
            # retained authority for this private target, and it must not
            # abort the dispatch that merely walked past it. A live crash of
            # this kind killed a milestone driver at its first Brainstorming
            # production start (2026-08-18).
            raw = record["value"]
            request = raw.get("request") if isinstance(raw, dict) else None
            candidate = (
                request.get("target_path") if isinstance(request, dict)
                else None
            )
            if (
                not isinstance(candidate, str)
                or not candidate
                or os.path.abspath(candidate) != target_path
            ):
                continue
            try:
                validate_session_state(raw)
            except ContractError:
                # A matching record that fails the current contract is not
                # a usable authority either; skipping it lets the caller
                # start afresh instead of failing the task on stale bytes.
                continue
            matches.append(session_id)
        return matches

    def read_task_effect_attempt(self, session_id):
        """Read the adapter's one in-flight effect marker, if present."""
        record = self._store.read(_task_effect_attempt_key(session_id))
        if not record["exists?"]:
            return None
        return validate_task_effect_attempt(record["value"])

    def begin_task_effect_attempt(self, session_id, attempt):
        """Durably mark an effect attempt before its callback can run."""
        checked = validate_task_effect_attempt(attempt)
        key = _task_effect_attempt_key(session_id)
        current = self._store.read(key)
        if current["exists?"]:
            raise HistoryRewriteError(
                "a production-effect attempt is already active"
            )
        result = self._store.cas(
            key, current["revision"], checked
        )
        if not result.ok:
            raise HistoryRewriteError(
                "a production-effect attempt is already active"
            )
        return validate_task_effect_attempt(result.record["value"])

    def finish_task_effect_attempt(self, session_id, token):
        """Clear an effect marker only after its activity is durable."""
        token = _text(token, "task_effect_attempt.token")
        key = _task_effect_attempt_key(session_id)
        current = self._store.read(key)
        if not current["exists?"]:
            return
        attempt = validate_task_effect_attempt(current["value"])
        if attempt["token"] != token:
            raise HistoryRewriteError(
                "the production-effect attempt token changed"
            )
        result = self._store.delete(
            key, expected_revision=current["revision"]
        )
        if not result.ok:
            raise HistoryRewriteError(
                "the production-effect attempt changed before completion"
            )

    def append_activity(self, session_id, event):
        """Append one provider call exactly once across crash recovery."""
        checked = validate_activity_event(event)
        key = _activity_key(session_id)
        for _attempt in range(8):
            current = self._store.read(key)
            if not current["exists?"]:
                # Sessions created by an older runtime have no activity key.
                # Create it lazily so they can continue after an upgrade; the
                # ledger then covers every provider call made by this runtime.
                if self.read(session_id) is None:
                    raise SessionNotFound(session_id)
                created = self._store.cas(
                    key,
                    current["revision"],
                    {
                        "schema_version": ACTIVITY_SCHEMA_VERSION,
                        "events": [],
                    },
                )
                if not created.ok:
                    continue
                current = created.record
            activity = validate_activity_log(current["value"])
            for existing in activity["events"]:
                if (
                    existing["id"] == checked["id"]
                    or (
                        existing["action_id"] == checked["action_id"]
                        and existing["provider_attempt"]
                        == checked["provider_attempt"]
                    )
                ):
                    if not _same_json_value(existing, checked):
                        raise HistoryRewriteError(
                            "activity call identity was reused with new facts"
                        )
                    return activity
            successor = copy.deepcopy(activity)
            successor["events"].append(checked)
            result = self._store.cas(
                key, current["revision"], successor
            )
            if result.ok:
                return validate_activity_log(result.record["value"])
        raise HistoryRewriteError(
            "session activity changed too often to append safely"
        )

    def discard_unlaunched(self, session_id, recovery_revision=None):
        """Remove only a create-time session that no worker could have used.

        Standalone creation keeps its lifecycle child behind a launch gate
        until the public binding, durable state, and response projection are
        ready.  This narrow compensation seam lets that transaction leave no
        hidden session when a later create step fails.  It deliberately
        refuses any state that already contains participant or coordination
        work.
        """
        key = _session_key(session_id)
        activity_key = _activity_key(session_id)
        task_effect_attempt_key = _task_effect_attempt_key(session_id)
        intervention_key = _external_intervention_key(session_id)
        supplied_baseline_key = None
        if recovery_revision is not None:
            supplied_baseline_key = _target_revision_key(
                session_id, recovery_revision
            )
        current = self._store.read(key)
        if not current["exists?"]:
            def remove_orphan(document):
                if supplied_baseline_key is not None:
                    document["entries"].pop(supplied_baseline_key, None)
                document["entries"].pop(activity_key, None)
                document["entries"].pop(task_effect_attempt_key, None)
                document["entries"].pop(intervention_key, None)
                return True, True

            self._store.client._mutate(remove_orphan)
            return
        state = validate_session_state(current["value"])
        progress = coordination_projection(state)
        unused_progress = (
            progress is None
            or (
                progress["completed_turns"] == []
                and progress["rounds_used"] == 0
                and progress["accepted_target_revision"] is None
            )
        )
        if (
            state["status"] not in ("created", "running")
            or state.get("participant_sessions")
            or state.get("transcript_events")
            or not unused_progress
            or [item["status"] for item in state["history"]]
            not in (["created"], ["created", "running"])
        ):
            raise HistoryRewriteError(
                "only an unused create-time session may be discarded"
            )

        transcript = state["transcript_ref"]
        with _exclusive_transcript(transcript):
            try:
                os.unlink(transcript)
            except FileNotFoundError:
                pass

            expected_revision = current["revision"]
            baseline_key = (
                supplied_baseline_key
                or (
                    None
                    if progress is None
                    else _target_revision_key(
                        session_id, progress["recovery_baseline_revision"]
                    )
                )
            )

            def remove(document):
                raw = self._store._raw_from_doc(document, key)
                public = self._store._public_from_raw(raw)
                if (
                    not public["exists?"]
                    or public["revision"] != expected_revision
                ):
                    return False, False
                del document["entries"][key]
                document["entries"].pop(activity_key, None)
                document["entries"].pop(task_effect_attempt_key, None)
                document["entries"].pop(intervention_key, None)
                if baseline_key is not None:
                    document["entries"].pop(baseline_key, None)
                return True, True

            if not self._store.client._mutate(remove):
                self._publish_current(session_id)
                raise HistoryRewriteError(
                    "create-time session changed before compensation"
                )

        directory = self._session_directory(session_id)
        try:
            os.rmdir(directory)
        except OSError:
            pass

    def discard_session(self, session_id):
        """Remove one session's private runtime state.

        The service's delete route calls this after its own authorization
        and process-liveness gates. Unlike discard_unlaunched it does not
        care how far the discussion got — the operator has ordered the
        session gone. Its final delivered chat, if one exists beside the
        target, remains a normal product artifact.
        """
        session_id = kvstore.validate_fragment(session_id, "session_id")
        key = _session_key(session_id)
        attempt_key = _turn_attempt_key(session_id)
        intervention_key = _external_intervention_key(session_id)
        activity_key = _activity_key(session_id)
        task_effect_attempt_key = _task_effect_attempt_key(session_id)
        revision_prefix = "%s%s:" % (
            _TARGET_REVISION_KEY_PREFIX, session_id
        )
        transcript = self.transcript_ref(session_id)
        with _exclusive_transcript(transcript):
            try:
                os.unlink(transcript)
            except FileNotFoundError:
                pass

            for runtime_directory in (
                self.prompt_directory(session_id),
                self.output_directory(session_id),
            ):
                if os.path.islink(runtime_directory):
                    try:
                        os.unlink(runtime_directory)
                    except FileNotFoundError:
                        pass
                    runtime_entries = None
                else:
                    try:
                        runtime_entries = os.scandir(runtime_directory)
                    except (FileNotFoundError, NotADirectoryError):
                        runtime_entries = None
                if runtime_entries is not None:
                    with runtime_entries:
                        for entry in runtime_entries:
                            if entry.is_file(follow_symlinks=False) \
                                    or entry.is_symlink():
                                try:
                                    os.unlink(entry.path)
                                except FileNotFoundError:
                                    pass
                    try:
                        os.rmdir(runtime_directory)
                    except OSError:
                        pass

            def remove(document):
                doomed = [
                    stored
                    for stored in document["entries"]
                    if stored == key
                    or stored == attempt_key
                    or stored == intervention_key
                    or stored == activity_key
                    or stored == task_effect_attempt_key
                    or stored.startswith(revision_prefix)
                ]
                for stored in doomed:
                    del document["entries"][stored]
                return True, bool(doomed)

            self._store.client._mutate(remove)
        # Best-effort tidy of the private runtime directory and lock.
        directory = self._session_directory(session_id)
        for leftover in (transcript + ".lock",):
            try:
                os.unlink(leftover)
            except OSError:
                pass
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
        if candidate["status"] in TERMINAL_STATUSES:
            return self._cas_coordination(
                session_id,
                expected_revision,
                candidate,
                assert_session_successor,
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
        """Retain the recovery baseline and expose null accepted progress."""
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
        checked_target = (
            None
            if target_revision is None
            else self._write_target_revision(session_id, target_revision)
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
            None if checked_target is None else checked_target["revision"],
        )

        def assertion(old, new):
            assert_completed_turn_successor(
                old,
                new,
                participant_id,
                markdown,
                None if checked_target is None else checked_target["revision"],
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

    def record_floor_intervention(
        self, session_id, expected_revision, intervention
    ):
        """Append one out-of-turn external intervention."""
        return self._record_transcript_event(
            session_id,
            expected_revision,
            "floor_intervention",
            intervention,
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
        failure_origin=None,
    ):
        """Atomically append a material interruption and terminal failure."""
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        candidate = terminal_interruption_successor(
            current.state,
            interruption,
            result,
            closing_summary,
            failure_origin=failure_origin,
        )

        def assertion(old, new):
            assert_terminal_interruption_successor(
                old,
                new,
                interruption,
                result,
                closing_summary,
                failure_origin=failure_origin,
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
        binding_ref = (
            participant["executor_ref"]
            if participant["delivery"] == "llm"
            else participant["external_ref"]
        )
        session_ref = make_participant_session_ref(binding_ref, provider_ref)
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
