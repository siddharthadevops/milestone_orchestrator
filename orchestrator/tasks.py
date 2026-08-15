"""Pure contracts and the built-in TaskExecutor catalogue.

This module defines task vocabulary only.  Admission, persistence, staffing,
dispatch, and effect validation belong to later integration layers.
"""

from __future__ import annotations

import math

from orchestrator import brainstorming, contracts, kvstore


UNKNOWN_TASK_EXECUTOR = "unknown_task_executor"
INVALID_TASK_REQUEST = "invalid_task_request"

_MISSING = object()
_RESULT_STATUSES = ("success", "failure")
_COST_FIELDS = ("api_usd", "real_usd")

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
