"""Task contracts, built-in TaskExecutors, and durable task records.

Dispatch and executor lifecycle remain in their integration layers.
"""

from __future__ import annotations

import copy
import json
import math
import os
import uuid

from orchestrator import brainstorming, contracts, kvstore, profiles, prompt_sets
from orchestrator import staffing
from orchestrator import state as st


UNKNOWN_TASK_EXECUTOR = "unknown_task_executor"
INVALID_TASK_REQUEST = "invalid_task_request"
TASK_UNAVAILABLE = "task_unavailable"

PRODUCER_TASK_KINDS = (
    contracts.KIND_DRAFT_SLICE_NOTE,
    contracts.KIND_IMPLEMENT,
)
_PRODUCER_TASK_EXECUTOR_IDS = ("agent_call", "brainstorming")
REVIEWED_COMPLETE_VERIFICATION = "complete_verification"

_REVIEWED_PRODUCTION_ROLES = {
    contracts.KIND_DRAFT_SKELETON: "plan",
    contracts.KIND_DRAFT_SLICE_NOTE: "draft",
    contracts.KIND_IMPLEMENT: "implement",
    REVIEWED_COMPLETE_VERIFICATION: "implement",
}

_REVIEW_BREADTHS = ("single", "double")
REVIEWED_TASK_KINDS = tuple(_REVIEWED_PRODUCTION_ROLES)
_REVIEWED_POLICY_DEFAULTS = {
    "review_breadth": "double",
    "same_family_second_look": False,
    "max_rounds_per_family": 12,
    "max_fix_loops": 20,
    "delta_full_review_after_fixes": 5,
    "doc_reclassify_from": "P2",
    "impl_reclassify_from": "P1",
    "p3_reclassify_debt": True,
    "p3_defer_max_risk": "low",
    "implementation_size_control": {
        "soft_lines": 500,
        "hard_lines": 750,
        "unconfirmed_grace_s": 180,
        "confirmed_grace_s": 600,
    },
}

_AGENT_CALL_CONFIGURATION_SCHEMA = {
    "role": {
        "type": "choice",
        "choices": list(staffing.ROLES),
        "default": "implement",
    },
}

_BRAINSTORMING_CONFIGURATION_SCHEMA = {
    "max_rounds": {
        "type": "integer",
        # The floor every Brainstorming runs with, whatever a planner
        # or caller wrote: a lower value is raised to it at resolution
        # (operator, 2026-08-19 — a six-round slice discussion failed a
        # run at "irreducible gap").
        "minimum": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
        "default": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
    },
    "closure_policy": {
        "type": "choice",
        "choices": list(brainstorming.CLOSURE_POLICIES),
        "default": "unanimity",
    },
}

_REVIEWED_AGENT_CONFIGURATION_BY_KIND = {
    task_kind: {
        "role": {
            "type": "choice",
            "choices": [role],
            "optional": True,
            "default": "",
        },
    }
    for task_kind, role in _REVIEWED_PRODUCTION_ROLES.items()
}

_MISSING = object()
_RESULT_STATUSES = ("success", "failure")
_COST_FIELDS = ("api_usd", "real_usd")
_WORKER_ACCOUNTING_EVENTS = frozenset({
    "brainstorming_origin_recorded",
    "brainstorming_work_recorded",
    "error_classifier_call",
    "gap_reported",
    "implementation_size_interrupted",
    "reclassify_recorded",
    "worker_interrupted",
    "worker_malformed",
    "worker_paused_for_plan_reconciliation",
    "worker_unaccepted",
})

_TASK_EXECUTORS = (
    {
        "id": "agent_call",
        "name": "Agent call",
        "description": "Runs one contracted agent call for focused work.",
        "operating_mode": "One contracted agent call.",
        "usage_examples": [
            "drafting documents",
            "programming small chunks of code",
        ],
        "available_agent_configurations": (
            "One agent-call seat; agent, model, and effort resolve from the "
            "staffing session that owns the order, at the role below."
        ),
        "execution_bindings": {
            "staffing": True,
            "strategy_profile": False,
            "prompt_set": False,
        },
        # The process step the one call performs, and the only thing an
        # orderer chooses about its staffing: the seat is always the role's
        # first and the round always its first, so no caller can reach into
        # a cycle the router keeps no history of.
        "configuration_schema": _AGENT_CALL_CONFIGURATION_SCHEMA,
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
            "model, and effort resolve from the staffing session that owns "
            "the order, at each seat's roster position."
        ),
        "execution_bindings": {
            "staffing": True,
            "strategy_profile": False,
            "prompt_set": True,
        },
        "configuration_schema": _BRAINSTORMING_CONFIGURATION_SCHEMA,
    },
    {
        "id": "reviewed_task",
        "name": "Reviewed task",
        "description": (
            "Produces, reviews, corrects, seals, and gate-commits one result."
        ),
        "operating_mode": "One production through its complete review cycle.",
        "usage_examples": [
            "reviewing a planning document",
            "implementing one bounded change with review",
        ],
        "available_agent_configurations": (
            "The producer and review seats resolve from the staffing session "
            "that owns the order."
        ),
        "execution_bindings": {
            "staffing": True,
            "strategy_profile": True,
            "prompt_set": True,
        },
        "configuration_schema": {
            "task_kind": {
                "type": "choice",
                "choices": list(REVIEWED_TASK_KINDS),
                "default": contracts.KIND_DRAFT_SKELETON,
            },
            "producer": {
                "type": "task_executor",
                "optional": True,
                "default": "",
                "choices": [
                    {
                        "value": "agent_call",
                        "label": "Agent call",
                        "applicable_when": {
                            "task_kind": list(REVIEWED_TASK_KINDS),
                        },
                        "configuration_schema_by": {
                            "path": "task_kind",
                            "schemas": _REVIEWED_AGENT_CONFIGURATION_BY_KIND,
                        },
                    },
                    {
                        "value": "brainstorming",
                        "label": "Brainstorming",
                        "applicable_when": {
                            "task_kind": list(PRODUCER_TASK_KINDS),
                        },
                        "configuration_schema": (
                            _BRAINSTORMING_CONFIGURATION_SCHEMA
                        ),
                    },
                ],
            },
            "review_breadth": {
                "type": "choice", "choices": list(_REVIEW_BREADTHS),
                "optional": True, "default": "",
            },
            "same_family_second_look": {
                "type": "boolean", "optional": True, "default": "",
                "applicable_when": {"review_breadth": ["single"]},
            },
            "doc_reclassify_from": {
                "type": "choice",
                "choices": list(contracts.RECLASSIFY_FROM_LEVELS),
                "optional": True, "default": "",
                "applicable_when": {
                    "task_kind": [
                        contracts.KIND_DRAFT_SKELETON,
                        contracts.KIND_DRAFT_SLICE_NOTE,
                    ],
                },
            },
            "impl_reclassify_from": {
                "type": "choice",
                "choices": list(contracts.RECLASSIFY_FROM_LEVELS),
                "optional": True, "default": "",
                "applicable_when": {
                    "task_kind": [
                        contracts.KIND_IMPLEMENT,
                        REVIEWED_COMPLETE_VERIFICATION,
                    ],
                },
            },
            "p3_reclassify_debt": {
                "type": "boolean", "optional": True, "default": "",
            },
            "p3_defer_max_risk": {
                "type": "choice", "choices": list(contracts.DRIFT_RISK_LEVELS),
                "optional": True, "default": "",
            },
            "max_rounds_per_family": {
                "type": "integer", "minimum": 0,
                "optional": True, "default": "",
            },
            "max_fix_loops": {
                "type": "integer", "minimum": 0,
                "optional": True, "default": "",
            },
            "delta_full_review_after_fixes": {
                "type": "integer", "minimum": 0,
                "optional": True, "default": "",
            },
            "implementation_size_control": {
                "type": "object",
                "optional": True,
                "applicable_when": {
                    "task_kind": [contracts.KIND_IMPLEMENT],
                    "producer.task_executor": [None, "agent_call"],
                },
                "description": (
                    "Optional thresholds for an agent-call implementation; "
                    "blank values inherit the effective work-area defaults."
                ),
                "properties": {
                    "soft_lines": {
                        "type": "integer", "minimum": 1,
                        "optional": True, "default": "",
                    },
                    "hard_lines": {
                        "type": "integer", "minimum": 1,
                        "greater_than": "soft_lines",
                        "optional": True, "default": "",
                    },
                    "unconfirmed_grace_s": {
                        "type": "number", "exclusive_minimum": 0,
                        "optional": True, "default": "",
                    },
                    "confirmed_grace_s": {
                        "type": "number", "exclusive_minimum": 0,
                        "optional": True, "default": "",
                    },
                },
                "constraints": [
                    "hard_lines must exceed the effective soft_lines value",
                ],
            },
        },
    },
)


def _deep_policy_configuration_schema(task_kind, prefix):
    """Reuse the reviewed-task policy form for one fixed deep child job."""
    schema = copy.deepcopy(_TASK_EXECUTORS[-1]["configuration_schema"])
    schema.pop("task_kind")
    floor = (
        "impl_reclassify_from"
        if task_kind == contracts.KIND_IMPLEMENT
        else "doc_reclassify_from"
    )
    schema.pop(
        "doc_reclassify_from"
        if floor == "impl_reclassify_from"
        else "impl_reclassify_from"
    )
    schema[floor].pop("applicable_when", None)
    if task_kind != contracts.KIND_IMPLEMENT:
        schema.pop("implementation_size_control")

    producer = schema["producer"]
    for choice in producer["choices"]:
        choice.pop("applicable_when", None)
        if choice["value"] == "agent_call":
            choice.pop("configuration_schema_by", None)
            choice["configuration_schema"] = copy.deepcopy(
                _REVIEWED_AGENT_CONFIGURATION_BY_KIND[task_kind]
            )
    schema["same_family_second_look"]["applicable_when"] = {
        prefix + "review_breadth": ["single"]
    }
    if task_kind == contracts.KIND_IMPLEMENT:
        schema["implementation_size_control"]["applicable_when"] = {
            prefix + "producer.task_executor": [None, "agent_call"]
        }
    return schema


_TASK_EXECUTORS += (
    {
        "id": "deep_task",
        "name": "Deep task",
        "description": (
            "Delivers one reviewed documentation child before reviewed "
            "implementation parts."
        ),
        "operating_mode": "A documentation-first sequence of reviewed tasks.",
        "usage_examples": [
            "delivering one coherent slice",
            "reviewing documentation before implementation",
        ],
        "available_agent_configurations": (
            "Documentation and implementation producers and reviewers resolve "
            "from the staffing session that owns the order."
        ),
        "execution_bindings": {
            "staffing": True,
            "strategy_profile": True,
            "prompt_set": True,
        },
        "configuration_schema": {
            "documentation": {
                "type": "object",
                "optional": True,
                "description": "Reviewed policy for the slice note.",
                "properties": _deep_policy_configuration_schema(
                    contracts.KIND_DRAFT_SLICE_NOTE, "documentation."
                ),
            },
            "implementation": {
                "type": "object",
                "optional": True,
                "description": "Reviewed policy frozen for implementation.",
                "properties": _deep_policy_configuration_schema(
                    contracts.KIND_IMPLEMENT, "implementation."
                ),
            },
        },
    },
)
_TASK_EXECUTOR_BY_ID = {
    entry["id"]: entry for entry in _TASK_EXECUTORS
}
# One retired spelling per renamed executor.  Durable orders, durable producer
# maps, stored producer events, and plans an agent echoes back keep the bytes
# they were written with; reading names them under the current id.  The
# catalogue itself never gains the retired key, so a new write still meets the
# ordinary unknown-executor refusal.
_RETIRED_TASK_EXECUTORS = {"worker": "agent_call"}


def stored_task_executor(value):
    """Read a stored or agent-returned executor id under its current name."""
    if isinstance(value, str):
        return _RETIRED_TASK_EXECUTORS.get(value, value)
    return value


def projected_task_record(record):
    """Read one durable task record under the current executor name.

    Applied where a record is projected outward rather than inside
    `task_records`: the standalone store loads through that reader before
    saving, so normalizing there would rewrite durable bytes the rename
    forbids touching.
    """
    order = record.get("order") if isinstance(record, dict) else None
    if not isinstance(order, dict):
        return record
    stored = order.get("task_executor")
    current = stored_task_executor(stored)
    if current == stored:
        return record
    return dict(record, order=dict(order, task_executor=current))


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


def _path_text(value, context):
    value = _text(value, context)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractError(
            "%s contains an invalid path character" % context
        ) from exc
    if "\x00" in value:
        raise ContractError("%s contains an invalid path character" % context)
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


def task_executor_supports_binding(task_executor, binding):
    """Whether the executor catalogue declares one execution binding."""
    entry = _TASK_EXECUTOR_BY_ID.get(task_executor)
    return bool(
        entry is not None
        and (entry.get("execution_bindings") or {}).get(binding) is True
    )


def producer_task_executor_catalogue():
    """Return only executors offered for slice production planning."""
    return _json_copy(
        [
            entry for entry in _TASK_EXECUTORS
            if entry["id"] in _PRODUCER_TASK_EXECUTOR_IDS
        ],
        "producer TaskExecutor catalogue",
    )


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
        _path_text(reference, "task request.reference_documents[%d]" % index)
        for index, reference in enumerate(references)
    ]
    if "output_directory" in request:
        checked["output_directory"] = _path_text(
            request["output_directory"], "task request.output_directory"
        )
    checked = _json_copy(checked, "task request")
    try:
        json.dumps(
            checked, ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractError("task request must contain only UTF-8 text") from exc
    return checked


def validate_request(request):
    """Validate and detach one common TaskExecutor request."""
    try:
        return _validate_request(request)
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def _resolve_configuration(
    task_executor, configuration, reviewed_defaults=None
):
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
    if task_executor == "reviewed_task":
        return resolve_reviewed_task_configuration(
            configuration, defaults=reviewed_defaults
        )
    if task_executor == "deep_task":
        return resolve_deep_task_configuration(
            configuration, defaults=reviewed_defaults
        )

    schema = entry["configuration_schema"]
    _exact_keys(configuration, (), schema, "configuration")
    checked = {}
    for name, definition in schema.items():
        value = configuration.get(name, definition["default"])
        if definition["type"] == "integer":
            if type(value) is not int:
                raise ContractError(
                    "configuration.%s must be an integer" % name
                )
            # `minimum` is a floor, not a refusal: a planner or caller who
            # wrote less gets the floor, visibly, in the resolved value.
            value = max(value, definition["minimum"])
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


def resolve_configuration(
    task_executor, configuration=_MISSING, reviewed_defaults=None
):
    """Validate one executor configuration and apply catalogue defaults."""
    try:
        return _resolve_configuration(
            task_executor, configuration, reviewed_defaults=reviewed_defaults
        )
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def _validate_producer_selection(
    value, context, stored=False, allowed_executors=None
):
    _exact_keys(value, ("task_executor",), ("configuration",), context)
    task_executor = value["task_executor"]
    if stored:
        task_executor = stored_task_executor(task_executor)
    if (
        allowed_executors is not None
        and task_executor not in allowed_executors
        and task_executor in _TASK_EXECUTOR_BY_ID
    ):
        raise ContractError(
            "TaskExecutor %r is not offered for reviewed production"
            % task_executor
        )
    configuration = value.get("configuration", _MISSING)
    # Resolve only as a validation probe.  Prospective state preserves an
    # omitted configuration; catalogue defaults freeze when a task is admitted.
    _resolve_configuration(task_executor, configuration)
    checked = {"task_executor": task_executor}
    if configuration is not _MISSING:
        checked["configuration"] = _json_copy(
            configuration, "%s.configuration" % context
        )
    return _json_copy(checked, context)


def validate_producer_selection(value, context="producer selection"):
    """Read one stored plan choice without freezing catalogue defaults."""
    try:
        return _validate_producer_selection(value, context, stored=True)
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def resolve_reviewed_producer(task_kind, value=_MISSING):
    """Freeze one reviewed production's catalogue-backed producer.

    The semantic job decides the agent-call role.  Producer configuration
    may tune an offered executor, but it cannot turn production into a
    review, fix, or another process step.
    """
    try:
        role = _REVIEWED_PRODUCTION_ROLES.get(task_kind)
        if role is None:
            raise ContractError(
                "reviewed production task_kind must be one of %s"
                % (list(_REVIEWED_PRODUCTION_ROLES),)
            )
        if value is _MISSING:
            value = {"task_executor": "agent_call"}
        allowed = (
            _PRODUCER_TASK_EXECUTOR_IDS
            if task_kind in PRODUCER_TASK_KINDS else ("agent_call",)
        )
        checked = _validate_producer_selection(
            value, "reviewed policy.producer", allowed_executors=allowed
        )
        task_executor = checked["task_executor"]
        supplied = checked.get("configuration") or {}
        if (
            task_executor == "agent_call"
            and "role" in supplied
            and supplied["role"] != role
        ):
            raise ContractError(
                "reviewed policy.producer.configuration.role cannot change "
                "the %s semantic job" % task_kind
            )
        configuration = _resolve_configuration(
            task_executor, checked.get("configuration", _MISSING)
        )
        if task_executor == "agent_call":
            configuration["role"] = role
        return _json_copy(
            {
                "task_executor": task_executor,
                "configuration": configuration,
            },
            "reviewed policy.producer",
        )
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def _reviewed_non_negative_int(value, context):
    if type(value) is not int or value < 0:
        raise ContractError("%s must be a non-negative integer" % context)
    return value


def _reviewed_size_control(value, defaults):
    context = "reviewed policy.implementation_size_control"
    if not isinstance(value, dict):
        raise ContractError("%s must be an object" % context)
    _exact_keys(
        value,
        (),
        (
            "soft_lines", "hard_lines", "unconfirmed_grace_s",
            "confirmed_grace_s",
        ),
        context,
    )
    source = dict(defaults or {})
    source.update(value)
    soft = source.get("soft_lines")
    hard = source.get("hard_lines")
    if type(soft) is not int or soft <= 0:
        raise ContractError("%s.soft_lines must be a positive integer" % context)
    if type(hard) is not int or hard <= soft:
        raise ContractError(
            "%s.hard_lines must be an integer greater than soft_lines"
            % context
        )
    checked = {"soft_lines": soft, "hard_lines": hard}
    for name in ("unconfirmed_grace_s", "confirmed_grace_s"):
        grace = source.get(name)
        if (
            isinstance(grace, bool)
            or not isinstance(grace, (int, float))
            or not math.isfinite(grace)
            or grace <= 0
        ):
            raise ContractError("%s.%s must be positive and finite" % (context, name))
        checked[name] = grace
    return checked


def resolve_reviewed_policy(
    task_kind, value=None, default_producer=_MISSING, defaults=None
):
    """Resolve every order-local reviewed-work choice to durable values."""
    try:
        if value is None:
            value = {}
        phase_floor = (
            "impl_reclassify_from"
            if task_kind in (
                contracts.KIND_IMPLEMENT,
                REVIEWED_COMPLETE_VERIFICATION,
            )
            else "doc_reclassify_from"
        )
        allowed = (
            "producer", "review_breadth", "same_family_second_look",
            phase_floor, "p3_reclassify_debt", "p3_defer_max_risk",
            "max_rounds_per_family", "max_fix_loops",
            "delta_full_review_after_fixes",
        )
        if task_kind == contracts.KIND_IMPLEMENT:
            allowed += ("implementation_size_control",)
        _exact_keys(value, (), allowed, "reviewed policy")
        size_defaults = dict(
            _REVIEWED_POLICY_DEFAULTS["implementation_size_control"]
        )
        supplied_defaults = defaults or {}
        if isinstance(supplied_defaults.get("implementation_size_control"), dict):
            size_defaults.update(
                supplied_defaults["implementation_size_control"]
            )
        effective = dict(_REVIEWED_POLICY_DEFAULTS)
        effective.update(supplied_defaults)
        effective.update(value)
        breadth = effective["review_breadth"]
        if breadth not in _REVIEW_BREADTHS:
            raise ContractError(
                "reviewed policy.review_breadth must be one of %s"
                % (list(_REVIEW_BREADTHS),)
            )
        second_look = effective["same_family_second_look"]
        if type(second_look) is not bool:
            raise ContractError(
                "reviewed policy.same_family_second_look must be a boolean"
            )
        if second_look and breadth != "single":
            raise ContractError(
                "same_family_second_look requires single review breadth"
            )
        floor = effective[phase_floor]
        if floor not in contracts.RECLASSIFY_FROM_LEVELS:
            raise ContractError(
                "reviewed policy.%s must be one of %s"
                % (phase_floor, list(contracts.RECLASSIFY_FROM_LEVELS))
            )
        reclassify = effective["p3_reclassify_debt"]
        if type(reclassify) is not bool:
            raise ContractError(
                "reviewed policy.p3_reclassify_debt must be a boolean"
            )
        risk = effective["p3_defer_max_risk"]
        if risk not in contracts.DRIFT_RISK_LEVELS:
            raise ContractError(
                "reviewed policy.p3_defer_max_risk must be one of %s"
                % (list(contracts.DRIFT_RISK_LEVELS),)
            )
        producer = resolve_reviewed_producer(
            task_kind, value.get("producer", default_producer)
        )
        size_control_applicable = (
            task_kind == contracts.KIND_IMPLEMENT
            and producer["task_executor"] == "agent_call"
        )
        if (
            "implementation_size_control" in value
            and not size_control_applicable
        ):
            raise ContractError(
                "reviewed policy.implementation_size_control requires an "
                "agent_call implementation producer"
            )
        checked = {
            "producer": producer,
            "review_breadth": breadth,
            "same_family_second_look": second_look,
            phase_floor: floor,
            "p3_reclassify_debt": reclassify,
            "p3_defer_max_risk": risk,
        }
        for name in (
            "max_rounds_per_family", "max_fix_loops",
            "delta_full_review_after_fixes",
        ):
            checked[name] = _reviewed_non_negative_int(
                effective[name], "reviewed policy.%s" % name
            )
        if size_control_applicable:
            checked["implementation_size_control"] = _reviewed_size_control(
                value.get("implementation_size_control", {}),
                size_defaults,
            )
        return _json_copy(checked, "reviewed policy")
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def reviewed_policy_defaults(task_kind, config):
    """Project one work area's effective reviewed defaults."""
    config = config if isinstance(config, dict) else {}
    floor = (
        "impl_reclassify_from"
        if task_kind in (
            contracts.KIND_IMPLEMENT,
            REVIEWED_COMPLETE_VERIFICATION,
        )
        else "doc_reclassify_from"
    )
    defaults = {
        "review_breadth": "double",
        "same_family_second_look": False,
        floor: config.get(floor, _REVIEWED_POLICY_DEFAULTS[floor]),
        "p3_reclassify_debt": config.get(
            "p3_reclassify_debt", _REVIEWED_POLICY_DEFAULTS["p3_reclassify_debt"]
        ),
        "p3_defer_max_risk": config.get(
            "p3_defer_max_risk", _REVIEWED_POLICY_DEFAULTS["p3_defer_max_risk"]
        ),
    }
    for name in (
        "max_rounds_per_family", "max_fix_loops",
        "delta_full_review_after_fixes",
    ):
        defaults[name] = config.get(name, _REVIEWED_POLICY_DEFAULTS[name])
    if task_kind == contracts.KIND_IMPLEMENT:
        control = config.get("implementation_size_control")
        defaults["implementation_size_control"] = (
            dict(control) if isinstance(control, dict) else None
        )
    return defaults


def resolve_reviewed_task_configuration(value, defaults=None):
    """Resolve a public reviewed-task configuration before admission."""
    try:
        _exact_keys(
            value,
            ("task_kind",),
            (
                "producer", "review_breadth", "same_family_second_look",
                "doc_reclassify_from", "impl_reclassify_from",
                "p3_reclassify_debt", "p3_defer_max_risk",
                "max_rounds_per_family", "max_fix_loops",
                "delta_full_review_after_fixes",
                "implementation_size_control",
            ),
            "configuration",
        )
        task_kind = value["task_kind"]
        if task_kind not in REVIEWED_TASK_KINDS:
            raise ContractError(
                "configuration.task_kind must be one of %s"
                % (list(REVIEWED_TASK_KINDS),)
            )
        policy = dict(value)
        policy.pop("task_kind")
        resolved = resolve_reviewed_policy(
            task_kind, policy, defaults=(
                reviewed_policy_defaults(task_kind, defaults)
                if defaults is not None else None
            )
        )
        return _json_copy(
            {"task_kind": task_kind, **resolved},
            "reviewed-task configuration",
        )
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def resolve_deep_task_configuration(value, defaults=None):
    """Freeze both fixed-job reviewed policies on one deep order."""
    try:
        _exact_keys(
            value, (), ("documentation", "implementation"), "configuration"
        )
        resolved = {}
        for name, task_kind in (
            ("documentation", contracts.KIND_DRAFT_SLICE_NOTE),
            ("implementation", contracts.KIND_IMPLEMENT),
        ):
            supplied = value.get(name, {})
            if not isinstance(supplied, dict):
                raise ContractError("configuration.%s must be an object" % name)
            resolved[name] = resolve_reviewed_policy(
                task_kind,
                supplied,
                defaults=(
                    reviewed_policy_defaults(task_kind, defaults)
                    if defaults is not None else None
                ),
            )
        return _json_copy(resolved, "deep-task configuration")
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def producer_order_from_selection(selection, request):
    """Build an order from the trusted producer frozen on reviewed work."""
    return {
        "task_executor": selection["task_executor"],
        "configuration": _json_copy(
            selection["configuration"], "producer configuration"
        ),
        "request": _json_copy(request, "task request"),
    }


def validate_producer_map(value, context="producer_task_executor"):
    """Read a generic producer map without mutating its stored shape."""
    try:
        _exact_keys(value, (), PRODUCER_TASK_KINDS, context)
        checked = {}
        for task_kind in PRODUCER_TASK_KINDS:
            if task_kind in value:
                checked[task_kind] = _validate_producer_selection(
                    value[task_kind],
                    "%s.%s" % (context, task_kind),
                    stored=True,
                    allowed_executors=_PRODUCER_TASK_EXECUTOR_IDS,
                )
        return _json_copy(checked, context)
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def effective_slice_producers(slice_plan):
    """Resolve generic task orders; canonical milestone plans are complete."""
    if not isinstance(slice_plan, dict):
        raise TaskRequestError(INVALID_TASK_REQUEST, "slice plan must be an object")
    raw = slice_plan.get("producer_task_executor", _MISSING)
    checked = {} if raw is _MISSING else validate_producer_map(raw)
    return {
        task_kind: _json_copy(
            checked.get(task_kind, {"task_executor": "agent_call"}),
            "effective producer selection",
        )
        for task_kind in PRODUCER_TASK_KINDS
    }


def effective_slice_plan(slices):
    """Return a detached plan whose every slice exposes both effective choices."""
    checked = _json_copy(slices, "slice plan")
    contracts.validate_slices(checked, "slice plan", legacy_material=True)
    for slice_plan in checked:
        # Compatibility readers admit historical per-slice material, but it
        # is no longer part of the operative plan or any routing decision.
        slice_plan.pop("material", None)
        slice_plan["producer_task_executor"] = effective_slice_producers(
            slice_plan
        )
    return checked


def producer_order(slice_plan, task_kind, request):
    """Build one prospective production order from the current slice choice."""
    if task_kind not in PRODUCER_TASK_KINDS:
        raise TaskRequestError(
            INVALID_TASK_REQUEST,
            "task_kind must be one of %s" % (list(PRODUCER_TASK_KINDS),),
        )
    selection = effective_slice_producers(slice_plan)[task_kind]
    order = {
        "task_executor": selection["task_executor"],
        "request": _json_copy(request, "task request"),
    }
    if "configuration" in selection:
        order["configuration"] = _json_copy(
            selection["configuration"], "producer configuration"
        )
    return order


def _order_staffing_session(value):
    """The owner's inherited staffing context on one order.

    A session id, or ``None`` for the default document — a deliberate
    choice either way, which is why the key is written on EVERY order this
    validator admits. Its ABSENCE means something else entirely and is
    reserved for records admitted before the cutover: those keep the
    dispatch authority already frozen on them, and nothing rewrites them.

    Nothing further is checked here. Whether the id names a session this
    caller may reach is the admitting route's question, asked against the
    session store itself; a shape rule invented here would be a second
    vocabulary for the same refusal.
    """
    if value is None:
        return None
    return _text(value, "task order.staffing_session")


def _strategy_profile(value):
    """Validate one service-resolved, retained strategy snapshot."""
    if not isinstance(value, dict) or set(value) != {"ref", "profile"}:
        raise ContractError(
            "task order.strategy_profile must contain ref and profile"
        )
    try:
        profiles.verify_retained(value["ref"], value["profile"])
    except profiles.ProfileError as exc:
        raise ContractError(
            "task order.strategy_profile is invalid"
        ) from exc
    return _json_copy(value, "task order.strategy_profile")


def validate_order(order, reviewed_defaults=None):
    """Validate a closed order and return its resolved, detached value."""
    try:
        _exact_keys(
            order,
            ("task_executor", "request"),
            (
                "configuration", "staffing_session", "prompt_set",
                "brainstorming_mode", "strategy_profile",
            ),
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
        if (
            "staffing_session" in order
            and not task_executor_supports_binding(task_executor, "staffing")
        ):
            raise ContractError(
                "task order.staffing_session is unavailable for this "
                "TaskExecutor"
            )
        if (
            "prompt_set" in order
            and not task_executor_supports_binding(task_executor, "prompt_set")
        ):
            raise ContractError(
                "task order.prompt_set is unavailable for this TaskExecutor"
            )
        if (
            "strategy_profile" in order
            and not task_executor_supports_binding(
                task_executor, "strategy_profile"
            )
        ):
            raise ContractError(
                "task order.strategy_profile is unavailable for this "
                "TaskExecutor"
            )
        if "brainstorming_mode" in order and (
            task_executor != "brainstorming"
            or order["brainstorming_mode"] != "repository_review"
        ):
            raise ContractError(
                "task order.brainstorming_mode must be repository_review "
                "for Brainstorming"
            )
        checked = {
            "task_executor": task_executor,
            "request": _validate_request(order["request"]),
            "configuration": _resolve_configuration(
                task_executor,
                order.get("configuration", _MISSING),
                reviewed_defaults=reviewed_defaults,
            ),
            "staffing_session": _order_staffing_session(
                order.get("staffing_session")
            ),
        }
        if task_executor == "brainstorming" or "prompt_set" in order:
            try:
                checked["prompt_set"] = prompt_sets.validate_name(
                    order.get("prompt_set", prompt_sets.DEFAULT_SET_NAME)
                )
            except prompt_sets.PromptSetError as exc:
                raise ContractError("task order.prompt_set is invalid") from exc
            if "brainstorming_mode" in order:
                checked["brainstorming_mode"] = order["brainstorming_mode"]
        if "strategy_profile" in order:
            checked["strategy_profile"] = _strategy_profile(
                order["strategy_profile"]
            )
        return _json_copy(checked, "task order")
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def order_staffing_session(order):
    """(supplied, session) for one stored order.

    *supplied* says whether the order carries the field AT ALL, which is
    the whole of standalone compatibility: a record admitted before the
    cutover has no such key and keeps running its frozen snapshot, while a
    record that carries an explicit ``None`` deliberately chose the default
    document and resolves live like any other.
    """
    if not isinstance(order, dict) or "staffing_session" not in order:
        return False, None
    return True, order["staffing_session"]


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
    records = state.get("tasks", [])
    if not isinstance(records, list):
        raise TaskRecordError("task history must be a list")
    for record in records:
        if record.get("id") == task_id:
            return _json_copy(record, "task record")
    raise TaskRecordError("unknown task %r" % task_id)


def related_task(state, parent_task_id, phase, part):
    """Return the one child admitted for a deep parent phase and part."""
    relation = {
        "task_id": parent_task_id,
        "phase": phase,
        "part": part,
    }
    found = [
        record for record in state.get("tasks", [])
        if record.get("parent") == relation
    ]
    if len(found) > 1:
        raise TaskRecordError(
            "duplicate related task for %s/%s/%s"
            % (parent_task_id, phase, part)
        )
    return (
        _json_copy(found[0], "task record") if found else None
    )


def admit_related_task(
    state,
    parent_task_id,
    phase,
    part,
    order,
    resolved_staffing,
    primary_workspace=None,
):
    """Admit or reuse one canonical deep child in a loaded task history."""
    existing = related_task(state, parent_task_id, phase, part)
    if existing is not None:
        return existing
    parent = task_record(state, parent_task_id)
    if parent["result"] is not None:
        raise TaskRecordError(
            "terminal task %s cannot admit a child" % parent_task_id
        )
    return admit_task(
        state,
        order,
        resolved_staffing,
        primary_workspace=primary_workspace,
        parent={
            "task_id": parent_task_id,
            "phase": phase,
            "part": part,
        },
    )


def deep_documentation_order(record):
    """Build the reviewed documentation child from one frozen deep order."""
    configuration = copy.deepcopy(
        record["order"]["configuration"]["documentation"]
    )
    configuration["task_kind"] = contracts.KIND_DRAFT_SLICE_NOTE
    order = {
        "task_executor": "reviewed_task",
        "configuration": configuration,
        "request": copy.deepcopy(record["order"]["request"]),
        "staffing_session": record["order"].get("staffing_session"),
    }
    for name in ("prompt_set", "strategy_profile"):
        if name in record["order"]:
            order[name] = copy.deepcopy(record["order"][name])
    return order


def deep_implementation_order(record, documentation_reference):
    """Build a reviewed implementation child from one frozen deep order."""
    configuration = copy.deepcopy(
        record["order"]["configuration"]["implementation"]
    )
    configuration["task_kind"] = contracts.KIND_IMPLEMENT
    request = copy.deepcopy(record["order"]["request"])
    request["reference_documents"].append(documentation_reference)
    order = {
        "task_executor": "reviewed_task",
        "configuration": configuration,
        "request": request,
        "staffing_session": record["order"].get("staffing_session"),
    }
    for name in ("prompt_set", "strategy_profile"):
        if name in record["order"]:
            order[name] = copy.deepcopy(record["order"][name])
    return order


def deep_task_result(status, child_results, reason=None):
    """Aggregate child envelopes without creating another physical charge."""
    duration = 0.0
    usage = None
    cost = None
    usage_partial = not child_results
    cost_partial = not child_results
    for result in child_results:
        duration += result["duration_s"]
        usage = st._add_token_usage(usage, result["token_usage"])
        cost = st._add_cost(cost, result["cost"])
        usage_partial = bool(
            usage_partial
            or result["token_usage_partial"]
            or result["token_usage"] is None
        )
        cost_partial = bool(
            cost_partial
            or result["cost_partial"]
            or result["cost"] is None
        )
    terminal = {
        "status": status,
        "duration_s": duration,
        "token_usage": usage,
        "token_usage_partial": bool(usage_partial or usage is None),
        "cost": cost,
        "cost_partial": bool(cost_partial or cost is None),
        "native_result": None,
    }
    if status == "failure":
        terminal["reason"] = str(reason or "Deep task failed")
    return validate_result(terminal)


def execute_worker(record, dispatch):
    """Pass one admitted common request through the Worker unchanged.

    Prompt construction, dispatch policy, and native-result validation remain
    with the milestone caller.  This adapter deliberately has no staffing or
    destination fallback: both authorities were settled before it is entered.
    """
    if not isinstance(record, dict):
        raise TaskRecordError("Worker execution requires a task record")
    order = record.get("order")
    if not isinstance(order, dict) or stored_task_executor(
        order.get("task_executor")
    ) != "agent_call":
        raise TaskRecordError("Worker execution requires an agent-call task")
    if record.get("result") is not None:
        raise TaskRecordError("a terminal Worker task cannot execute")
    if not callable(dispatch):
        raise TaskRecordError("Worker execution requires a dispatch callback")
    request = _json_copy(order.get("request"), "Worker task request")
    return dispatch(request)


def admit_task(
    state, order, resolved_staffing, primary_workspace=None, parent=None
):
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
    if parent is not None:
        record["parent"] = _json_copy(parent, "task parent relation")
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


def worker_result(
    state,
    task_id,
    native_result,
    status="success",
    reason=None,
    prompt_set_fallback=None,
):
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
    if prompt_set_fallback is not None:
        result["prompt_set_fallback"] = prompt_set_fallback
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
        ("reason", "prompt_set_fallback"),
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
    fallback = result.get("prompt_set_fallback")
    if fallback is not None:
        if fallback not in prompt_sets.PROMPT_SET_FALLBACKS:
            raise ContractError("task result.prompt_set_fallback is invalid")
        checked["prompt_set_fallback"] = fallback
    if status == "failure":
        checked["reason"] = reason
    return _json_copy(checked, "task result")
