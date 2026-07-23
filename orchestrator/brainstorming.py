"""Product-neutral brainstorming session contracts and durable state.

This module deliberately stops at accepted configuration and lifecycle state.
Participant execution, turns, target revisions, ballots, transcripts, service
routes, and product adapters belong to later slices.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from orchestrator import kvstore


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


class ContractError(ValueError):
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
    _exact_keys(state, required, (), "state")
    request = validate_request(state["request"])
    validate_run_config(state["run_config"])
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


def _session_key(session_id):
    return _SESSION_KEY_PREFIX + kvstore.validate_fragment(
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
