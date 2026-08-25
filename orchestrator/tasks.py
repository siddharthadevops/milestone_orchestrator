"""Task contracts, built-in TaskExecutors, and durable task records.

Dispatch and executor lifecycle remain in their integration layers.
"""

from __future__ import annotations

import json
import math
import os
import uuid

from orchestrator import brainstorming, contracts, kvstore, prompt_sets
from orchestrator import staffing
from orchestrator import state as st


UNKNOWN_TASK_EXECUTOR = "unknown_task_executor"
INVALID_TASK_REQUEST = "invalid_task_request"
TASK_UNAVAILABLE = "task_unavailable"
TASK_SELECTION_FROZEN = "task_selection_frozen"
TASK_UPDATE_BUSY = "task_update_busy"

PRODUCER_TASK_KINDS = (
    contracts.KIND_DRAFT_SLICE_NOTE,
    contracts.KIND_IMPLEMENT,
)

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
        # The process step the one call performs, and the only thing an
        # orderer chooses about its staffing: the seat is always the role's
        # first and the round always its first, so no caller can reach into
        # a cycle the router keeps no history of.
        "configuration_schema": {
            "role": {
                "type": "choice",
                "choices": list(staffing.ROLES),
                "default": "implement",
            },
        },
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
        "configuration_schema": {
            "max_rounds": {
                "type": "integer",
                # The floor every Brainstorming runs with, whatever a planner
                # or caller wrote: a lower value is raised to it at
                # resolution (operator, 2026-08-19 — a six-round slice
                # discussion failed a run at "irreducible gap").
                "minimum": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
                "default": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
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


def resolve_configuration(task_executor, configuration=_MISSING):
    """Validate one executor configuration and apply catalogue defaults."""
    try:
        return _resolve_configuration(task_executor, configuration)
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def _validate_producer_selection(value, context, stored=False):
    _exact_keys(value, ("task_executor",), ("configuration",), context)
    task_executor = value["task_executor"]
    if stored:
        task_executor = stored_task_executor(task_executor)
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
    """Read one recorded prospective choice without freezing defaults.

    Both callers project an already-stored `slice_producer_updated` event, so a
    retired id reads under its current name.  The write body has its own
    validator and keeps refusing it.
    """
    try:
        return _validate_producer_selection(value, context, stored=True)
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def validate_producer_map(value, context="producer_task_executor"):
    """Read a partial/raw producer map; omissions retain agent-call defaults."""
    try:
        _exact_keys(value, (), PRODUCER_TASK_KINDS, context)
        checked = {}
        for task_kind in PRODUCER_TASK_KINDS:
            if task_kind in value:
                checked[task_kind] = _validate_producer_selection(
                    value[task_kind],
                    "%s.%s" % (context, task_kind),
                    stored=True,
                )
        return _json_copy(checked, context)
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def effective_slice_producers(slice_plan):
    """Project both effective choices without rewriting the stored slice plan."""
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


def slice_material(slice_plan):
    """The material one slice currently proposes, or ``None``.

    A read, never a default: an omitted material is not "no material" the
    router must be told about, it is simply nothing to send, and the
    session's own default then stands.
    """
    if not isinstance(slice_plan, dict):
        raise TaskRequestError(
            INVALID_TASK_REQUEST, "slice plan must be an object"
        )
    material = slice_plan.get("material")
    if material is None:
        return None
    if not isinstance(material, str):
        raise TaskRequestError(
            INVALID_TASK_REQUEST, "slice material must be a string"
        )
    return material


def effective_slice_plan(slices):
    """Return a detached plan whose every slice exposes both effective choices."""
    checked = _json_copy(slices, "slice plan")
    contracts.validate_slices(checked, "slice plan")
    for slice_plan in checked:
        slice_plan["producer_task_executor"] = effective_slice_producers(
            slice_plan
        )
    return checked


def operator_producer_overrides(state):
    """Project current-plan operator choices from append-only history."""
    events = state.get("events", [])
    latest_plan_update = max(
        (
            index
            for index, event in enumerate(events)
            if isinstance(event, dict) and event.get("type") == "slices_updated"
        ),
        default=-1,
    )
    overrides = {}
    for index, event in enumerate(events):
        if index <= latest_plan_update:
            continue
        if not isinstance(event, dict) or event.get("type") != (
            "slice_producer_updated"
        ):
            continue
        slice_id = event.get("slice_id")
        task_kind = event.get("task_kind")
        if type(slice_id) is not int or task_kind not in PRODUCER_TASK_KINDS:
            raise TaskRequestError(
                INVALID_TASK_REQUEST,
                "slice producer event %d has invalid identity" % index,
            )
        overrides[(slice_id, task_kind)] = validate_producer_selection(
            event.get("selection"),
            "slice producer event %d.selection" % index,
        )
    return [
        {
            "slice_id": slice_id,
            "task_kind": task_kind,
            "selection": _json_copy(selection, "operator producer override"),
        }
        for (slice_id, task_kind), selection in sorted(overrides.items())
    ]


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
        # The production task owns this value from admission onward.  Write
        # the absence too, so a later slice edit cannot be mistaken for
        # context an older admitted order omitted.
        "staffing_material": slice_material(slice_plan),
    }
    if "configuration" in selection:
        order["configuration"] = _json_copy(
            selection["configuration"], "producer configuration"
        )
    return order


def validate_producer_override(value):
    """Validate the closed slice-producer write body."""
    try:
        _exact_keys(
            value,
            ("task_kind", "task_executor"),
            ("configuration",),
            "producer override",
        )
        task_kind = value["task_kind"]
        if task_kind not in PRODUCER_TASK_KINDS:
            raise ContractError(
                "task_kind must be one of %s" % (list(PRODUCER_TASK_KINDS),)
            )
        selection = _validate_producer_selection(
            {
                key: value[key]
                for key in ("task_executor", "configuration")
                if key in value
            },
            "producer override",
        )
        return {"task_kind": task_kind, **selection}
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def _producer_selection_frozen(state, slice_id, task_kind):
    unit_kind = {
        contracts.KIND_DRAFT_SLICE_NOTE: st.UNIT_SLICE_DOC,
        contracts.KIND_IMPLEMENT: st.UNIT_SLICE_IMPL,
    }[task_kind]
    for unit in state.get("units", []):
        if (
            unit.get("kind") != unit_kind
            or unit.get("slice_id") != slice_id
        ):
            continue
        draft = unit.get("draft")
        if isinstance(draft, dict) and draft.get("kind") == task_kind:
            return True
        reference = unit.get("active_task")
        if not isinstance(reference, dict) or reference.get("kind") != task_kind:
            continue
        record = task_record(state, reference.get("id"))
        result = record.get("result")
        if result is None or result.get("status") == "success":
            return True
    return False


def update_slice_producer(state, slice_id, value):
    """Change one still-prospective selection in loaded milestone state."""
    checked = validate_producer_override(value)
    if type(slice_id) is not int:
        raise TaskRequestError(INVALID_TASK_REQUEST, "slice id must be an integer")
    slices = (state.get("milestone") or {}).get("slices")
    if not isinstance(slices, list):
        raise TaskRequestError(INVALID_TASK_REQUEST, "slice plan is unavailable")
    slice_plan = next(
        (candidate for candidate in slices if candidate.get("id") == slice_id),
        None,
    )
    if slice_plan is None:
        raise TaskRequestError(
            INVALID_TASK_REQUEST, "unknown slice id %r" % slice_id
        )
    task_kind = checked["task_kind"]
    if _producer_selection_frozen(state, slice_id, task_kind):
        raise TaskRequestError(
            TASK_SELECTION_FROZEN,
            "%s producer selection is already frozen" % task_kind,
        )

    raw = slice_plan.get("producer_task_executor", _MISSING)
    if raw is _MISSING:
        producer_map = {}
    else:
        # Check the stored map, then carry its own bytes forward: a retired id
        # recorded on the sibling kind keeps reading as its current name and is
        # not rewritten by an override of the other kind.
        validate_producer_map(raw)
        producer_map = _json_copy(raw, "producer_task_executor")
    selection = {
        key: checked[key]
        for key in ("task_executor", "configuration")
        if key in checked
    }
    producer_map[task_kind] = selection
    slice_plan["producer_task_executor"] = producer_map
    st.append_event(
        state,
        "slice_producer_updated",
        slice_id=slice_id,
        task_kind=task_kind,
        selection=_json_copy(selection, "producer selection"),
    )
    return effective_slice_producers(slice_plan)


def validate_material_override(value):
    """Validate the closed slice-material write body.

    Exactly `{"material": <string>}` or `{"material": null}`: a string
    replaces the slice's proposal, ``None`` withdraws it. Nothing is checked
    against the document's live catalogue — a name it does not carry is the
    router's business and already degrades there, so a renamed material can
    never refuse a write.
    """
    try:
        _exact_keys(value, ("material",), (), "material override")
        material = value["material"]
        if material is not None and not isinstance(material, str):
            raise ContractError(
                "material must be a string, or null to clear it"
            )
        return {"material": material}
    except (ContractError, TypeError, ValueError) as exc:
        _request_error(exc)


def update_slice_material(state, slice_id, value):
    """Change one slice's still-prospective material in loaded state.

    Prospective, and prospective ONLY: unlike a producer choice, this write
    is never frozen by an admitted task, because it does not decide which
    executor runs the work. Each production task took the material in force
    when it was admitted and keeps it; this write governs the next one.
    """
    checked = validate_material_override(value)
    if type(slice_id) is not int:
        raise TaskRequestError(
            INVALID_TASK_REQUEST, "slice id must be an integer"
        )
    slices = (state.get("milestone") or {}).get("slices")
    if not isinstance(slices, list):
        raise TaskRequestError(INVALID_TASK_REQUEST, "slice plan is unavailable")
    slice_plan = next(
        (candidate for candidate in slices if candidate.get("id") == slice_id),
        None,
    )
    if slice_plan is None:
        raise TaskRequestError(
            INVALID_TASK_REQUEST, "unknown slice id %r" % slice_id
        )
    material = checked["material"]
    if material is None:
        # Clearing REMOVES the key. A plan that never carried one and a plan
        # whose proposal was withdrawn read the same way, so no reader has to
        # learn a second spelling for "no material".
        slice_plan.pop("material", None)
    else:
        slice_plan["material"] = material
    st.append_event(
        state,
        "slice_material_updated",
        slice_id=slice_id,
        material=material,
    )
    return slice_material(slice_plan)


def operator_material_overrides(state):
    """Project current-plan explicit material writes from append-only history.

    The same cutoff the producer projection uses: a later authorized complete
    slice plan replaces the proposals wholesale, so writes made before it no
    longer describe the plan a reviewer is reading.
    """
    events = state.get("events", [])
    latest_plan_update = max(
        (
            index
            for index, event in enumerate(events)
            if isinstance(event, dict) and event.get("type") == "slices_updated"
        ),
        default=-1,
    )
    overrides = {}
    for index, event in enumerate(events):
        if index <= latest_plan_update:
            continue
        if not isinstance(event, dict) or event.get("type") != (
            "slice_material_updated"
        ):
            continue
        slice_id = event.get("slice_id")
        material = event.get("material")
        if type(slice_id) is not int or (
            material is not None and not isinstance(material, str)
        ):
            raise TaskRequestError(
                INVALID_TASK_REQUEST,
                "slice material event %d has invalid identity" % index,
            )
        overrides[slice_id] = material
    return [
        {"slice_id": slice_id, "material": material}
        for slice_id, material in sorted(overrides.items())
    ]


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


def _order_staffing_material(value):
    """One production order's frozen optional router material."""
    if value is None:
        return None
    # Reuse the plan boundary's one definition of a storable material.  This
    # remains shape validation, never catalogue-membership validation.
    try:
        contracts._require_material(value, "task order")
    except contracts.ContractError as exc:
        raise ContractError(str(exc)) from exc
    return value


def validate_order(order):
    """Validate a closed order and return its resolved, detached value."""
    try:
        _exact_keys(
            order,
            ("task_executor", "request"),
            ("configuration", "staffing_session", "staffing_material"),
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
            "staffing_session": _order_staffing_session(
                order.get("staffing_session")
            ),
        }
        if "staffing_material" in order:
            checked["staffing_material"] = _order_staffing_material(
                order["staffing_material"]
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


def order_staffing_material(order):
    """The frozen production material on one stored order, if any.

    Older and non-production orders carry no key and therefore ask the router
    for no request material.  New production orders write the key even when
    its value is ``None``, fixing that absence at their admission boundary.
    """
    if not isinstance(order, dict) or "staffing_material" not in order:
        return None
    return order["staffing_material"]


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
