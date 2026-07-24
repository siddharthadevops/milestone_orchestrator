"""Product-neutral brainstorming session contracts and durable state.

This module owns accepted configuration, lifecycle state, durable participant
session references, and the accepted ordered-discussion projection. Ballots,
transcripts, service routes, and product adapters belong to later slices.
"""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import re
from dataclasses import dataclass

from orchestrator import contracts, kvstore


STATUSES = ("created", "running", "success", "failure")
TERMINAL_STATUSES = ("success", "failure")
CLOSURE_POLICIES = ("unanimity", "majority_with_lead_tiebreak")
ROLES = ("lead", "interlocutor")

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
    """Validate crash-surviving control state for one exclusive turn."""
    _exact_keys(
        turn_attempt,
        (
            "token",
            "participant_id",
            "completed_turn_count",
            "target_revision",
            "quiescent",
        ),
        ("target_parent",),
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


def validate_result(result, terminal_status, target_path):
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
    _text(result["transcript_ref"], "result.transcript_ref")
    rounds_used = result["rounds_used"]
    if type(rounds_used) is not int or rounds_used < 0:
        raise ContractError("result.rounds_used must be a non-negative integer")
    if outcome == "failure":
        _text(result["reason"], "result.reason")
    return _json_copy(result, "result")


def _validate_history(history, target_path):
    if not isinstance(history, list) or not history:
        raise ContractError("state.history must be a non-empty list")
    previous = None
    for index, record in enumerate(history):
        ctx = "state.history[%d]" % index
        _object(record, ctx)
        status = record.get("status")
        if status not in STATUSES:
            raise ContractError("%s.status is invalid" % ctx)
        required = ("status", "result") if status in TERMINAL_STATUSES else ("status",)
        _exact_keys(record, required, (), ctx)
        if index == 0:
            if record != {"status": "created"}:
                raise ContractError("state.history must begin with created")
        elif status not in _ALLOWED_TRANSITIONS[previous]:
            raise IllegalTransition("%s -> %s is not legal" % (previous, status))
        if status in TERMINAL_STATUSES:
            validate_result(record["result"], status, target_path)
        previous = status
    return previous


def validate_session_state(state):
    """Validate and return a detached complete session-state copy."""
    _object(state, "state")
    status = state.get("status")
    if status not in STATUSES:
        raise ContractError("state.status is invalid")
    required = {"request", "run_config", "status", "history"}
    if status in TERMINAL_STATUSES:
        required.add("result")
    _exact_keys(
        state,
        required,
        ("participant_sessions",) + _COORDINATION_FIELDS,
        "state",
    )
    request = validate_request(state["request"])
    run_config = validate_run_config(state["run_config"])
    if "participant_sessions" in state:
        participant_sessions = validate_participant_sessions(
            state["participant_sessions"], run_config
        )
        if status == "created" and participant_sessions:
            raise ContractError(
                "created sessions cannot have participant session references"
            )
    _validate_coordination(state, request, run_config, status)
    last_status = _validate_history(state["history"], request["target_path"])
    if last_status != status:
        raise ContractError("state.status must match the last history record")
    if status in TERMINAL_STATUSES:
        result = validate_result(state["result"], status, request["target_path"])
        if not _same_json_value(result, state["history"][-1]["result"]):
            raise ContractError("state.result must match terminal history")
    return _json_copy(state, "state")


def new_session_state(request, run_config):
    """Construct a valid, non-running session without performing I/O."""
    return {
        "request": validate_request(request),
        "run_config": validate_run_config(run_config),
        "status": "created",
        "history": [{"status": "created"}],
        "participant_sessions": {},
    }


def transition_session(state, new_status, result=None):
    """Return one legal whole-state successor without mutating ``state``."""
    current = validate_session_state(state)
    old_status = current["status"]
    if new_status not in _ALLOWED_TRANSITIONS[old_status]:
        raise IllegalTransition("%s -> %s is not legal" % (old_status, new_status))
    if new_status in TERMINAL_STATUSES:
        checked_result = validate_result(
            result, new_status, current["request"]["target_path"]
        )
    elif result is not None:
        raise ContractError("nonterminal transitions cannot carry a result")
    else:
        checked_result = None

    successor = copy.deepcopy(current)
    successor["status"] = new_status
    record = {"status": new_status}
    if checked_result is not None:
        successor["result"] = checked_result
        record["result"] = copy.deepcopy(checked_result)
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
    expected = transition_session(old, appended["status"], appended.get("result"))
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
    for field in ("request", "run_config", "status", "history", "result"):
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

    @property
    def path(self):
        return self._store.client.path

    @staticmethod
    def _snapshot(record):
        if not record["exists?"]:
            return None
        return SessionSnapshot(
            revision=record["revision"],
            state=validate_session_state(record["value"]),
        )

    def read(self, session_id):
        return self._snapshot(self._store.read(_session_key(session_id)))

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
        """Persist worker admission before invoking the scheduled participant."""
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
        expected = participants[len(turns) % len(participants)]
        if (
            checked["participant_id"] != expected["id"]
            or checked["completed_turn_count"] != len(turns)
            or checked["target_revision"]
            != projection["accepted_target_revision"]
        ):
            raise HistoryRewriteError(
                "turn attempt does not match durable accepted progress"
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
        self, session_id, expected_revision, candidate, assertion
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
            latest = self._snapshot(result.record)
            if latest is None:
                raise SessionNotFound(session_id)
            raise RevisionConflict(latest)
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
        state = new_session_state(request, resolved_config)
        result = self._store.cas(_session_key(session_id), None, state)
        if not result.ok:
            raise SessionAlreadyExists("session already exists")
        return self._snapshot(result.record)

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
            latest = self._snapshot(result.record)
            if latest is None:
                raise SessionNotFound(session_id)
            raise RevisionConflict(latest)
        return self._snapshot(result.record)

    def transition(self, session_id, expected_revision, new_status, result=None):
        current = self.read(session_id)
        if current is None:
            raise SessionNotFound(session_id)
        if current.revision != expected_revision:
            raise RevisionConflict(current)
        successor = transition_session(current.state, new_status, result)
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
            session_id, expected_revision, candidate, assertion
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
            latest = self._snapshot(result.record)
            if latest is None:
                raise SessionNotFound(session_id)
            raise RevisionConflict(latest)
        return self._snapshot(result.record)
