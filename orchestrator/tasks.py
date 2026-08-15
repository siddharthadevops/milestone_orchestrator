"""Task contracts, built-in TaskExecutors, and durable task records.

Dispatch and executor lifecycle remain in their integration layers.
"""

from __future__ import annotations

import math
import os
import uuid

from orchestrator import brainstorming, contracts, kvstore
from orchestrator import state as st


UNKNOWN_TASK_EXECUTOR = "unknown_task_executor"
INVALID_TASK_REQUEST = "invalid_task_request"

_MISSING = object()
_RESULT_STATUSES = ("success", "failure")
_COST_FIELDS = ("api_usd", "real_usd")
_WORKER_ACCOUNTING_EVENTS = frozenset({
    "brainstorming_origin_recorded",
    "error_classifier_call",
    "gap_reported",
    "implementation_size_interrupted",
    "worker_interrupted",
    "worker_malformed",
    "worker_unaccepted",
})

_TASK_EXECUTORS = (
    {
        "id": "worker",
        "name": "Worker",
        "description": "Runs one contracted Worker call for focused work.",
        "operating_mode": "One contracted Worker call.",
        "usage_examples": [
            "drafting documents",
            "programming small chunks of code",
        ],
        "available_agent_configurations": (
            "One Worker seat; agent, model, and effort resolve from the "
            "current profile or call-time defaults."
        ),
        "configuration_schema": {},
    },
    {
        "id": "brainstorming",
        "name": "Brainstorming",
        "description": (
            "Runs a bounded discussion whose lead applies the agreed work."
        ),
        "operating_mode": "A led multi-seat discussion.",
        "usage_examples": [
            "elaborating strategies",
            "resolving contested designs",
        ],
        "available_agent_configurations": (
            "Initial Position, Contrary Position, and Dante seats; agent, "
            "model, and effort resolve from profiles or Brainstorming."
        ),
        "configuration_schema": {
            "max_rounds": {
                "type": "integer",
                "minimum": 1,
                "default": 10,
            },
            "closure_policy": {
                "type": "choice",
                "choices": list(brainstorming.CLOSURE_POLICIES),
                "default": "unanimity",
            },
        },
    },
)
_TASK_EXECUTOR_BY_ID = {
    entry["id"]: entry for entry in _TASK_EXECUTORS
}


class ContractError(contracts.ContractError):
    """A generic task value does not satisfy its closed contract."""


class TaskRequestError(ContractError):
    """A task request or order refused with its public classification."""

    def __init__(self, code, detail):
        ContractError.__init__(self, detail)
        self.code = code


class TaskRecordError(ContractError):
    """A durable task transition is invalid."""


def _exact_keys(value, required, optional, context):
    if not isinstance(value, dict):
        raise ContractError("%s must be an object" % context)
    if any(not isinstance(key, str) for key in value):
        raise ContractError("%s keys must be strings" % context)
    required = set(required)
    allowed = required | set(optional)
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise ContractError("%s is missing %s" % (context, missing))
    if extra:
        raise ContractError(
            "%s has unsupported fields %s" % (context, extra)
        )


def _text(value, context):
    if not isinstance(value, str) or not value.strip():
        raise ContractError("%s must be a non-empty string" % context)
    return value


def _json_copy(value, context):
    try:
        return kvstore.canonical_json_value(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("%s must be JSON-plain" % context) from exc


def _request_error(exc):
    if isinstance(exc, TaskRequestError):
        raise exc
    raise TaskRequestError(INVALID_TASK_REQUEST, str(exc)) from exc


def task_executor_catalogue():
    """Return the ordered, detached built-in TaskExecutor catalogue."""
    return _json_copy(list(_TASK_EXECUTORS), "TaskExecutor catalogue")


def _validate_request(request):
    _exact_keys(
        request,
        ("work_area", "request", "context", "reference_documents"),
        ("output_directory",),
        "task request",
    )
    work_area = request["work_area"]
    if not isinstance(work_area, dict) or not work_area:
        raise ContractError("task request.work_area must be a non-empty object")
    checked = {
        "work_area": _json_copy(work_area, "task request.work_area"),
        "request": _text(request["request"], "task request.request"),
        "context": _json_copy(request["context"], "task request.context"),
    }
    references = request["reference_documents"]
    if not isinstance(references, list):
        raise ContractError(
            "task request.reference_documents must be a list"
        )
    checked["reference_documents"] = [
        _text(reference, "task request.reference_documents[%d]" % index)
        for index, reference in enumerate(references)
    ]
    if "output_directory" in request:
        checked["output_directory"] = _text(
            request["output_directory"], "task request.output_directory"
        )
    return _json_copy(checked, "task request")


def validate_request(request):
    """Validate and detach one common TaskExecutor request."""
    try:
        return _validate_request(request)
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def _resolve_configuration(task_executor, configuration):
    if not isinstance(task_executor, str):
        raise ContractError("task_executor must be a string")
    entry = _TASK_EXECUTOR_BY_ID.get(task_executor)
    if entry is None:
        raise TaskRequestError(
            UNKNOWN_TASK_EXECUTOR,
            "unknown TaskExecutor %r" % task_executor,
        )
    if configuration is _MISSING:
        configuration = {}
    if not isinstance(configuration, dict):
        raise ContractError("configuration must be an object")

    schema = entry["configuration_schema"]
    _exact_keys(configuration, (), schema, "configuration")
    checked = {}
    for name, definition in schema.items():
        value = configuration.get(name, definition["default"])
        if definition["type"] == "integer":
            if type(value) is not int or value < definition["minimum"]:
                raise ContractError(
                    "configuration.%s must be an integer of at least %d"
                    % (name, definition["minimum"])
                )
        elif definition["type"] == "choice":
            if value not in definition["choices"]:
                raise ContractError(
                    "configuration.%s must be one of %s"
                    % (name, definition["choices"])
                )
        else:  # pragma: no cover - the built-in catalogue is closed
            raise ContractError(
                "configuration schema for %s has an unsupported type" % name
            )
        checked[name] = value
    return _json_copy(checked, "configuration")


def resolve_configuration(task_executor, configuration=_MISSING):
    """Validate one executor configuration and apply catalogue defaults."""
    try:
        return _resolve_configuration(task_executor, configuration)
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def validate_order(order):
    """Validate a closed order and return its resolved, detached value."""
    try:
        _exact_keys(
            order,
            ("task_executor", "request"),
            ("configuration",),
            "task order",
        )
        task_executor = order["task_executor"]
        if not isinstance(task_executor, str):
            raise ContractError("task order.task_executor must be a string")
        if task_executor not in _TASK_EXECUTOR_BY_ID:
            raise TaskRequestError(
                UNKNOWN_TASK_EXECUTOR,
                "unknown TaskExecutor %r" % task_executor,
            )
        checked = {
            "task_executor": task_executor,
            "request": _validate_request(order["request"]),
            "configuration": _resolve_configuration(
                task_executor,
                order.get("configuration", _MISSING),
            ),
        }
        return _json_copy(checked, "task order")
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def _canonical_output_directory(order, primary_workspace):
    request = order["request"]
    if "output_directory" not in request:
        return order
    if not isinstance(primary_workspace, str) or not primary_workspace.strip():
        raise TaskRequestError(
            INVALID_TASK_REQUEST,
            "a supplied output_directory requires a resolved primary workspace",
        )
    if not os.path.isabs(primary_workspace):
        raise TaskRequestError(
            INVALID_TASK_REQUEST,
            "the resolved primary workspace must be absolute",
        )
    root = os.path.realpath(primary_workspace)
    supplied = request["output_directory"]
    candidate = (
        supplied
        if os.path.isabs(supplied)
        else os.path.join(root, supplied)
    )
    canonical = os.path.realpath(candidate)
    if not kvstore.path_is_inside_roots(canonical, [root]):
        raise TaskRequestError(
            INVALID_TASK_REQUEST,
            "task request.output_directory must stay inside the primary workspace",
        )
    checked = _json_copy(order, "task order")
    checked["request"]["output_directory"] = canonical
    return checked


def resolve_derived_path(output_directory, path):
    """Canonicalize one task-owned path beneath an admitted destination."""
    try:
        root = _text(output_directory, "output_directory")
        if not os.path.isabs(root):
            raise ContractError("output_directory must be canonical and absolute")
        if os.path.normpath(root) != root:
            raise ContractError("output_directory must be canonical and absolute")
        if os.path.realpath(root) != root:
            raise ContractError(
                "output_directory no longer resolves to its admitted path"
            )
        candidate = _text(path, "derived path")
        canonical = os.path.realpath(
            candidate if os.path.isabs(candidate) else os.path.join(root, candidate)
        )
        try:
            inside = os.path.commonpath([root, canonical]) == root
        except ValueError:
            inside = False
        if not inside:
            raise ContractError("derived path must stay inside output_directory")
        return canonical
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def task_records(state):
    """Return detached durable task history; pre-task state reads as empty."""
    records = state.get("tasks", [])
    if not isinstance(records, list):
        raise TaskRecordError("task history must be a list")
    return _json_copy(records, "task history")


def task_record(state, task_id):
    """Return one detached task record, or raise for an unknown identity."""
    if not isinstance(task_id, str) or not task_id:
        raise TaskRecordError("task id must be a non-empty string")
    for record in task_records(state):
        if record.get("id") == task_id:
            return record
    raise TaskRecordError("unknown task %r" % task_id)


def execute_worker(record, dispatch):
    """Pass one admitted common request through the Worker unchanged.

    Prompt construction, dispatch policy, and native-result validation remain
    with the milestone caller.  This adapter deliberately has no staffing or
    destination fallback: both authorities were settled before it is entered.
    """
    if not isinstance(record, dict):
        raise TaskRecordError("Worker execution requires a task record")
    order = record.get("order")
    if not isinstance(order, dict) or order.get("task_executor") != "worker":
        raise TaskRecordError("Worker execution requires a Worker task")
    if record.get("result") is not None:
        raise TaskRecordError("a terminal Worker task cannot execute")
    if not callable(dispatch):
        raise TaskRecordError("Worker execution requires a dispatch callback")
    request = _json_copy(order.get("request"), "Worker task request")
    return dispatch(request)


def admit_task(state, order, resolved_staffing, primary_workspace=None):
    """Validate and append one frozen scheduling decision to loaded state."""
    checked_order = _canonical_output_directory(
        validate_order(order), primary_workspace
    )
    try:
        staffing = _json_copy(resolved_staffing, "resolved staffing")
    except ContractError as exc:
        _request_error(exc)
    existing = task_records(state)
    known_ids = {record.get("id") for record in existing}
    task_id = str(uuid.uuid4())
    while task_id in known_ids:  # pragma: no cover - UUID collision guard
        task_id = str(uuid.uuid4())
    record = {
        "id": task_id,
        "order": checked_order,
        "resolved_staffing": staffing,
        "result": None,
    }
    state.setdefault("tasks", []).append(_json_copy(record, "task record"))
    return _json_copy(record, "task record")


def record_task_result(state, task_id, result):
    """Perform the task record's sole legal mutation: null to terminal."""
    checked_result = validate_result(result)
    if not isinstance(task_id, str) or not task_id:
        raise TaskRecordError("task id must be a non-empty string")
    records = state.get("tasks", [])
    if not isinstance(records, list):
        raise TaskRecordError("task history must be a list")
    for record in records:
        if record.get("id") != task_id:
            continue
        if record.get("result") is not None:
            raise TaskRecordError("task %s is already terminal" % task_id)
        record["result"] = _json_copy(checked_result, "task result")
        return _json_copy(record, "task record")
    raise TaskRecordError("unknown task %r" % task_id)


def _persisted_transition(state_path, transition):
    with st.exclusive_mutation(state_path, wait=True):
        state = st.load(state_path)
        value = transition(state)
        st.save(state_path, state)
    return value


def admit_persisted_task(
    state_path, order, resolved_staffing, primary_workspace=None
):
    """Serialized persistent form of :func:`admit_task`."""
    return _persisted_transition(
        state_path,
        lambda state: admit_task(
            state, order, resolved_staffing, primary_workspace
        ),
    )


def record_persisted_task_result(state_path, task_id, result):
    """Serialized persistent form of :func:`record_task_result`."""
    return _persisted_transition(
        state_path,
        lambda state: record_task_result(state, task_id, result),
    )


def task_accounting(state, task_id):
    """Project one Worker's linked accounting without creating a ledger."""
    task_record(state, task_id)
    duration_s = 0.0
    token_usage = None
    token_usage_partial = False
    cost = None
    cost_partial = False
    linked = False

    def account(record, missing_is_partial=False):
        nonlocal duration_s, token_usage, token_usage_partial
        nonlocal cost, cost_partial, linked
        if record.get("task_id") != task_id:
            return
        linked = True
        duration = st._completed_duration(record.get("duration_s"))
        duration_s += duration
        normalized_usage = st._normalized_token_usage(
            record.get("token_usage")
        )
        normalized_cost = st._normalized_cost(record.get("cost"))
        token_usage = st._add_token_usage(token_usage, normalized_usage)
        cost = st._add_cost(cost, normalized_cost)
        token_usage_partial = bool(
            token_usage_partial
            or record.get("token_usage_partial", False)
            or (duration > 0 and normalized_usage is None)
            or (missing_is_partial and normalized_usage is None)
        )
        cost_partial = bool(
            cost_partial
            or record.get("cost_partial", False)
            or (duration > 0 and normalized_cost is None)
            or (
                record.get("cost") is not None
                and normalized_cost is None
            )
            or (missing_is_partial and normalized_cost is None)
        )

    for unit in state.get("units") or []:
        unit_key = st.unit_key(unit)
        stabilization = (
            (unit.get("implementation_stabilization") or {}).get(
                "implementation_size"
            )
        )
        if (
            isinstance(stabilization, dict)
            and stabilization.get("task_id") == task_id
        ):
            episode_id = stabilization.get("episode_id")
            has_interrupt_accounting = bool(
                episode_id
                and any(
                    event.get("type")
                    == "implementation_size_interrupted"
                    and event.get("unit") == unit_key
                    and event.get("episode_id") == episode_id
                    and event.get("task_id") == task_id
                    for event in state.get("events") or []
                )
            )
            if not has_interrupt_accounting:
                token_usage_partial = True
                cost_partial = True
        for draft in st._draft_history(state, unit):
            account(draft, missing_is_partial=True)
        for round_ in unit.get("rounds") or []:
            account(round_, missing_is_partial=True)

    for event in state.get("events") or []:
        if event.get("type") not in _WORKER_ACCOUNTING_EVENTS:
            continue
        if (
            event.get("type") == "worker_malformed"
            and event.get("duration_s") is None
            and event.get("token_usage") is None
            and not event.get("fatal")
        ):
            continue
        account(event)

    return {
        "duration_s": duration_s,
        "token_usage": token_usage,
        "token_usage_partial": bool(
            token_usage_partial or not linked or token_usage is None
        ),
        "cost": cost,
        "cost_partial": bool(cost_partial or not linked or cost is None),
    }


def worker_result(state, task_id, native_result, status="success", reason=None):
    """Build a terminal Worker envelope from its existing linked evidence."""
    accounting = task_accounting(state, task_id)
    result = {
        "status": status,
        **accounting,
        "native_result": native_result,
    }
    if status == "failure":
        result["reason"] = reason
    elif reason is not None:
        raise ContractError("a successful Worker task cannot carry a reason")
    return validate_result(result)


def _token_usage(value):
    if value is None:
        return None
    try:
        return brainstorming._token_usage(value, "task result.token_usage")
    except brainstorming.ContractError as exc:
        raise ContractError(str(exc)) from exc


def _cost(value):
    if value is None:
        return None
    _exact_keys(value, _COST_FIELDS, (), "task result.cost")
    try:
        checked = brainstorming._cost(value, "task result.cost")
    except brainstorming.ContractError as exc:
        raise ContractError(str(exc)) from exc
    except OverflowError as exc:
        raise ContractError(
            "task result.cost amounts must be non-negative finite numbers"
        ) from exc
    # Brainstorming normalizes each amount to float.  Compare the validated
    # source numbers too so that normalization cannot erase a real-over-API
    # difference above binary64's exact-integer range.
    if value["real_usd"] > value["api_usd"]:
        raise ContractError(
            "task result.cost.real_usd cannot exceed the API-equivalent"
        )
    return checked


def validate_result(result):
    """Validate and detach one executor-opaque terminal task result."""
    _exact_keys(
        result,
        (
            "status",
            "duration_s",
            "token_usage",
            "token_usage_partial",
            "cost",
            "cost_partial",
            "native_result",
        ),
        ("reason",),
        "task result",
    )
    status = result["status"]
    if status not in _RESULT_STATUSES or not isinstance(status, str):
        raise ContractError(
            "task result.status must be one of %s" % (_RESULT_STATUSES,)
        )
    if status == "failure":
        if "reason" not in result:
            raise ContractError("failure task result requires reason")
        reason = _text(result["reason"], "task result.reason")
    elif "reason" in result:
        raise ContractError("success task result cannot carry reason")

    duration = result["duration_s"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ContractError(
            "task result.duration_s must be a non-negative finite number"
        )
    try:
        normalized_duration = float(duration)
    except OverflowError as exc:
        raise ContractError(
            "task result.duration_s must be a non-negative finite number"
        ) from exc
    if not math.isfinite(normalized_duration) or normalized_duration < 0:
        raise ContractError(
            "task result.duration_s must be a non-negative finite number"
        )
    token_usage = _token_usage(result["token_usage"])
    cost = _cost(result["cost"])
    token_partial = result["token_usage_partial"]
    cost_partial = result["cost_partial"]
    if type(token_partial) is not bool:
        raise ContractError("task result.token_usage_partial must be boolean")
    if type(cost_partial) is not bool:
        raise ContractError("task result.cost_partial must be boolean")
    if token_usage is None and not token_partial:
        raise ContractError("null token_usage must be partial")
    if cost is None and not cost_partial:
        raise ContractError("null cost must be partial")

    checked = {
        "status": status,
        "duration_s": normalized_duration,
        "token_usage": token_usage,
        "token_usage_partial": token_partial,
        "cost": cost,
        "cost_partial": cost_partial,
        "native_result": _json_copy(
            result["native_result"], "task result.native_result"
        ),
    }
    if status == "failure":
        checked["reason"] = reason
    return _json_copy(checked, "task result")
