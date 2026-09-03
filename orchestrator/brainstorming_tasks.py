"""Thin TaskExecutor adapter for the independent Brainstorming lifecycle."""

from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import json
import math
import os
import secrets
import shutil
import time

from orchestrator import brainstorming
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import brainstorming_milestone as milestone
from orchestrator import gitops
from orchestrator import kvstore
from orchestrator import prompt_sets
from orchestrator import prompt_router
from orchestrator import session_calls
from orchestrator import session_repository
from orchestrator import state as st
from orchestrator import tasks


_PROFILE_AUTHORITY = "current_profile"
_STATIC_AUTHORITY = "static"
_REPOSITORY_REVIEW_MODE = "repository_review"
# A Brainstorming ordered outside a milestone has no profile to consult, so
# until the staffing router lets the caller choose, every seat runs at the
# top effort (operator, 2026-08-19): a direct discussion is ordered because
# the question is hard, not to save tokens.
DIRECT_BRAINSTORMING_EFFORT = "max"
_TASK_CALLER_PREFIX = "task:"
_RECOVERED_EFFECT_ERROR = (
    "production effect ended without durable completion evidence"
)
_RECOVERED_EFFECT_PARTICIPANT = "task-effect-recovery"
_PRODUCTION_COMPLETION_KIND = "production_completion"


class AdapterError(RuntimeError):
    """An admitted task cannot safely cross the Brainstorming boundary."""


def _task_record(state, task_id):
    record = tasks.task_record(state, task_id)
    order = record.get("order") or {}
    if order.get("task_executor") != "brainstorming":
        raise AdapterError("Brainstorming execution requires a Brainstorming task")
    if record.get("result") is not None:
        raise AdapterError("a terminal Brainstorming task cannot execute")
    return record


def _workspace(request):
    work_area = request.get("work_area") or {}
    primary = work_area.get("primary")
    primary_path = primary.get("path") if isinstance(primary, dict) else primary
    workspace = work_area.get("workspace_path") or primary_path
    if (
        not isinstance(workspace, str)
        or not workspace.strip()
        or not os.path.isabs(workspace)
        or not os.path.isdir(workspace)
    ):
        raise AdapterError("the task work area has no existing absolute workspace")
    if primary_path is not None and (
        not isinstance(primary_path, str)
        or os.path.realpath(primary_path) != os.path.realpath(workspace)
    ):
        raise AdapterError("the task work area does not match its primary workspace")
    return os.path.abspath(workspace)


def _structured_context(request):
    """Return only the reserved, object-shaped task context metadata."""
    context = request.get("context")
    return context if isinstance(context, dict) else {}


def _execution_context(request):
    """Translate the frozen work area to the lifecycle's resolved context."""
    work_area = copy.deepcopy(request["work_area"])
    workspace = _workspace(request)
    primary = work_area.get("primary")
    if isinstance(primary, str):
        primary = {"path": primary}
    additional = []
    for root in work_area.get("additional") or []:
        additional.append({"path": root} if isinstance(root, str) else root)
    project = work_area.get("project")
    area = work_area.get("work_area")
    if (project is None) != (area is None):
        raise AdapterError("project and work_area authority must be supplied together")
    return {
        "workspace_path": workspace,
        "project": project,
        "work_area": area,
        "primary": primary,
        "additional": additional,
    }


def standalone_staffing(session=None):
    """The selection a directly ordered Brainstorming task carries.

    *session* is the id the order inherited from its owner, or ``None``
    when the order deliberately named none: the discussion then resolves
    every automatic call on the `default` document at `medium` with the
    host's configured families, which is the same answer an unbound run
    gives the discussions it owns. Either way this IS a selection; absence
    is reserved for a caller with no document store to resolve against at
    all, which is what a pre-cutover static record keeps.
    """
    return {"session": session}


def resolve_staffing(config, workspace, staffing_selection=None):
    """Resolve the order's staffing authority before durable admission.

    A task carrying a staffing selection is ROUTER-BACKED: it records no
    seat pins at all, because every one of its calls resolves through that
    selection immediately before it is made. The selection may name no
    session — a standalone order, or an owner run that holds none — and the
    default document answers for it.

    Only a caller with no staffing document store to read — a `Driver`
    built without a catalogue home — freezes an explicit static binding
    here, which is also the shape a pre-cutover record holds and keeps.
    """
    if staffing_selection is not None:
        participants = milestone._participants()
        authority = _PROFILE_AUTHORITY
    else:
        try:
            participants = lifecycle.resolve_static_participants(
                config,
                milestone._participants(),
                "unanimity",
                workspace,
            )
        except lifecycle.PublicLifecycleError as exc:
            code = (
                tasks.TASK_UNAVAILABLE
                if exc.code == lifecycle.UNAVAILABLE
                else tasks.INVALID_TASK_REQUEST
            )
            raise tasks.TaskRequestError(
                code, "static Brainstorming staffing is unavailable"
            ) from exc
        participants = [
            dict(seat, effort=DIRECT_BRAINSTORMING_EFFORT)
            if seat.get("delivery") == "llm" or seat.get("effort") is not None
            else seat
            for seat in participants
        ]
        authority = _STATIC_AUTHORITY
    return brainstorming._json_copy(
        {"dispatch_authority": authority, "participants": participants},
        "Brainstorming resolved staffing",
    )


def admit_task(
    state,
    order,
    config,
    primary_workspace,
    staffing_selection=None,
):
    """Resolve Brainstorming staffing before the common durable admission."""
    checked = tasks._canonical_output_directory(
        tasks.validate_order(order), primary_workspace
    )
    if checked["task_executor"] != "brainstorming":
        raise tasks.TaskRequestError(
            tasks.INVALID_TASK_REQUEST,
            "the Brainstorming adapter requires task_executor brainstorming",
        )
    context = _structured_context(checked["request"])
    charge = context.get("session_charge")
    if charge is not None:
        checked_charge = session_calls.validate_charge(charge)
        checked["prompt_set"] = checked_charge["prompt_set"]
        task_kind = context.get("task_kind")
        expected_job = {
            "draft_slice_note": "draft_slice_note@slice_doc",
            "implement": "implement@slice_impl",
        }.get(task_kind)
        if checked_charge["job"] != expected_job:
            raise tasks.TaskRequestError(
                tasks.INVALID_TASK_REQUEST,
                "Brainstorming producer charge does not match its task kind",
            )
    elif staffing_selection is not None:
        # Prospective cutover marker: an admitted-but-not-yet-started task must
        # not change execution semantics merely because the service restarted.
        checked["brainstorming_mode"] = _REPOSITORY_REVIEW_MODE
    staffing = resolve_staffing(
        config, os.path.realpath(primary_workspace), staffing_selection
    )
    return tasks.admit_task(
        state, checked, staffing, primary_workspace=primary_workspace
    )


def _frozen_participants(record):
    staffing = record.get("resolved_staffing")
    try:
        brainstorming._exact_keys(
            staffing,
            ("dispatch_authority", "participants"),
            (),
            "Brainstorming resolved staffing",
        )
        if staffing["dispatch_authority"] != _STATIC_AUTHORITY:
            raise brainstorming.ContractError(
                "static launch requires static staffing authority"
            )
        participants = staffing["participants"]
        checked = lifecycle.validate_create_body({
            "request": {
                "workspace_path": "/workspace",
                "target_path": "/private/agreement.md",
                "request": "Validate frozen task seats.",
                "context": {"brief": "Validate frozen task seats."},
                "max_rounds": 1,
            },
            "participants": participants,
            "closure_policy": "unanimity",
        })["participants"]
        for participant in checked:
            for field in ("model_family", "model", "effort"):
                brainstorming._text(
                    participant.get(field), "frozen participant.%s" % field
                )
        return checked
    except (TypeError, ValueError, brainstorming.ContractError) as exc:
        raise AdapterError("the task has no complete static staffing binding") from exc


def _private_target_paths(workspace, home, task_id):
    root = milestone._owned_work_areas_root(
        {"workspace": workspace}, active_home=home
    )
    try:
        fragment = kvstore.validate_fragment(task_id, "task_id")
    except ValueError as exc:
        raise AdapterError("the task id cannot own a private target") from exc
    work_area = os.path.join(root, "task-%s" % fragment)
    target_parent = os.path.join(work_area, "private")
    return work_area, target_parent, os.path.join(target_parent, "agreement.md")


def _task_lifecycle_lock(workspace, home, task_id):
    """Return a lock distinct from Brainstorming's transcript lock."""
    work_area, _target_parent, _target = _private_target_paths(
        workspace, home, task_id
    )
    return work_area + "-lifecycle"


def _private_target(workspace, home, task_id):
    work_area, target_parent, target = _private_target_paths(
        workspace, home, task_id
    )
    os.makedirs(os.path.dirname(work_area), exist_ok=True)
    os.makedirs(target_parent, exist_ok=True)
    return work_area, target


def _repository_target(request):
    context = _structured_context(request)
    target = (
        context.get("planned_slice_note_path")
        or (context.get("author_coordinates") or {}).get("slice_note_path")
    )
    try:
        return milestone._candidate_reference(_workspace(request), target)
    except (KeyError, TypeError):
        return None


def _direct_repository_charge(record, repository):
    """Bind an ordinary panel task to the shared Git review lifecycle."""
    return {
        "job": prompt_router.STANDALONE_REPOSITORY_SESSION_JOB,
        "prompt_set": record["order"].get(
            "prompt_set", prompt_sets.DEFAULT_SET_NAME
        ),
        "values": {},
        "repository": copy.deepcopy(repository),
    }


def _creation_body(
    record, participants, target, workspace, direct_repository=None
):
    order = record["order"]
    request = order["request"]
    configuration = order["configuration"]
    task_context = copy.deepcopy(request["context"])
    structured_context = (
        task_context if isinstance(task_context, dict) else {}
    )
    session_charge = structured_context.get("session_charge")
    if direct_repository is not None:
        # A direct task's repository authority is minted by this adapter.
        # Same-named caller context remains background and cannot replace it.
        session_charge = _direct_repository_charge(record, direct_repository)
    elif session_charge is not None:
        session_charge = session_calls.read_charge(session_charge)
        task_context["session_charge"] = session_charge
    repository_backed = "repository" in (session_charge or {})
    prompt_set = (
        session_charge["prompt_set"]
        if repository_backed else
        order.get("prompt_set", prompt_sets.DEFAULT_SET_NAME)
    )
    brief = (
        "Work directly in the shared project repository. Initial Position "
        "implements the requested task there; the other seats inspect it "
        "without editing. Git is the delivery record."
        if repository_backed else
        "Discuss the target-free task and write the complete agreed "
        "production approach to the private target. During discussion, do "
        "not treat that private target as a requested task effect. The lead "
        "applies every requested effect only after agreement."
    )
    return {
        "create_target_parents": bool(repository_backed and target is not None),
        "request": {
            "workspace_path": workspace,
            **({"target_path": target} if target is not None else {}),
            "request": request["request"],
            "context": {
                "brief": (
                    brief
                    + "\n\nCaller-supplied task context (binding background):\n"
                    + json.dumps(
                        task_context,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                ),
                "references": list(request["reference_documents"]),
                "source_payload": {
                    "task_context": copy.deepcopy(task_context),
                    "work_area": copy.deepcopy(request["work_area"]),
                    **(
                        {"session_charge": copy.deepcopy(session_charge)}
                        if session_charge is not None else {}
                    ),
                    **(
                        {"output_directory": request["output_directory"]}
                        if "output_directory" in request else {}
                    ),
                },
            },
            "max_rounds": configuration["max_rounds"],
        },
        "participants": copy.deepcopy(participants),
        "closure_policy": configuration["closure_policy"],
        "prompt_set": prompt_set,
    }


def _zero_accounting():
    return {
        "duration_s": 0.0,
        "token_usage": {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": 0,
        },
        "token_usage_partial": False,
        "cost": {"api_usd": 0.0, "real_usd": 0.0},
        "cost_partial": False,
    }


def _fail_before_session(state, task_id, reason):
    result = {
        "status": "failure",
        "reason": reason,
        **_zero_accounting(),
        "native_result": None,
    }
    return tasks.record_task_result(state, task_id, result)


def _fail_from_projection(state, task_id, projection, reason):
    session_state = projection.get("state") or {}
    result = {
        "status": "failure",
        "reason": reason,
        **_projection_accounting(projection),
        "native_result": copy.deepcopy(session_state.get("result")),
    }
    return tasks.record_task_result(state, task_id, result)


def _authorize_caller(caller):
    def authorize(record):
        if record.get("caller") != caller:
            raise AdapterError("session/task mismatch")
    return authorize


def _task_caller(record, task_id):
    authority = (record.get("resolved_staffing") or {}).get(
        "dispatch_authority"
    )
    return _caller_for_authority(authority, task_id)


def _caller_for_authority(authority, task_id):
    if authority == _PROFILE_AUTHORITY:
        return lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX + task_id
    if authority == _STATIC_AUTHORITY:
        return _TASK_CALLER_PREFIX + task_id
    raise AdapterError("the task has no recognized staffing authority")


def _owned_projection(home, caller, target_path):
    rows = lifecycle.list_sessions(
        home, lambda record: record.get("caller") == caller
    )
    if len(rows) > 1:
        raise AdapterError("one Brainstorming task owns multiple sessions")
    if not rows:
        return None
    session_id = rows[0]["id"]
    try:
        projection = lifecycle.inspect_session(
            home, session_id, _authorize_caller(caller)
        )
    except lifecycle.PublicLifecycleError as exc:
        if exc.code != lifecycle.UNKNOWN_SESSION:
            raise
        return (
            session_id,
            _retained_projection(home, session_id, caller, target_path),
            False,
        )
    return session_id, projection, True


def _retained_projection(home, session_id, caller, target_path):
    """Project evidence retained after the service record was forgotten."""
    store = brainstorming.SessionStore(lifecycle.state_directory(home))
    snapshot = store.read(session_id)
    if snapshot is None:
        return None
    if not brainstorming.repository_session(snapshot.state):
        retained_target = os.path.abspath(
            snapshot.state["request"]["target_path"]
        )
        if retained_target != target_path:
            raise AdapterError("retained Brainstorming session/task mismatch")
    record = {
        "id": session_id,
        "caller": caller,
        "pid": None,
        "created_at": "1970-01-01T00:00:01+0000",
    }
    projection = {
        "id": session_id,
        "caller": caller,
        "process": "stopped",
        "revision": snapshot.revision,
        "state": snapshot.state,
    }
    projection.update(
        lifecycle._activity_projection(store, record, snapshot.state)
    )
    if store.read_task_effect_attempt(session_id) is not None:
        projection["work_token_usage_partial"] = True
        projection["work_cost_partial"] = True
    return projection


def _retained_owned_projection(home, caller, target_path):
    store = brainstorming.SessionStore(lifecycle.state_directory(home))
    session_ids = store.session_ids_for_target(target_path)
    if len(session_ids) > 1:
        raise AdapterError("one Brainstorming task owns multiple sessions")
    if not session_ids:
        return None
    session_id = session_ids[0]
    return session_id, _retained_projection(
        home, session_id, caller, target_path
    )


def _fail_lost_session(state, task_id, projection=None):
    reason = "Brainstorming session was deleted before task completion."
    if projection is not None:
        return _fail_from_projection(state, task_id, projection, reason)
    return tasks.record_task_result(state, task_id, {
        "status": "failure",
        "reason": reason,
        "duration_s": 0.0,
        "token_usage": None,
        "token_usage_partial": True,
        "cost": None,
        "cost_partial": True,
        "native_result": None,
    })


def _resume_projection(
    state,
    task_id,
    home,
    session_id,
    caller,
    projection,
    staffing_selection,
    authority_failure_reason=None,
):
    if (
        projection["state"]["status"] in brainstorming.TERMINAL_STATUSES
        or projection.get("process") == "running"
    ):
        return projection
    if authority_failure_reason is not None:
        _fail_from_projection(
            state, task_id, projection, authority_failure_reason
        )
        return None
    try:
        return lifecycle.start_session(
            home,
            session_id,
            _authorize_caller(caller),
            resolve_staffing_session=(
                (lambda _record: staffing_selection.get("session"))
                if staffing_selection is not None else None
            ),
        )
    except lifecycle.PublicLifecycleError as exc:
        if exc.code == lifecycle.STOP_INCOMPLETE:
            raise
        _fail_from_projection(
            state,
            task_id,
            projection,
            "Brainstorming session start failed: %s" % exc.code,
        )
        return None


def _start_task_exclusive(
    state,
    task_id,
    config,
    home,
    staffing_selection=None,
    launcher=None,
    session_id=None,
    pre_session_failure_reason=None,
):
    """Launch, or resume, the one session owned by an open task."""
    record = _task_record(state, task_id)
    staffing = record["resolved_staffing"]
    authority = staffing.get("dispatch_authority")
    authority_failure_reason = None
    if authority == _PROFILE_AUTHORITY:
        if staffing_selection is None:
            # An attached task admitted before this cutover carries no
            # session of its own. Its owner supplies one at every launch;
            # with none supplied there is nothing to resolve through, and
            # the task says so exactly as it did for the profile it used to
            # need.
            authority_failure_reason = (
                "Brainstorming session admission failed: the owner's "
                "staffing session is unavailable"
            )
    elif authority == _STATIC_AUTHORITY:
        # An ambient owner session may appear after admission. The durable
        # task authority still selects the static frozen binding.
        staffing_selection = None
    else:
        raise AdapterError("the task has no recognized staffing authority")
    caller = _task_caller(record, task_id)
    request = record["order"]["request"]
    context = _execution_context(request)
    workspace = context["workspace_path"]
    direct_repository_mode = (
        record["order"].get("brainstorming_mode")
        == _REPOSITORY_REVIEW_MODE
    )
    attached_repository = (
        not direct_repository_mode
        and "repository" in (
            _structured_context(request).get("session_charge") or {}
        )
    )
    work_area, _target_parent, private_target = _private_target_paths(
        workspace, home, task_id
    )
    if session_id is not None:
        try:
            projection = lifecycle.inspect_session(
                home, session_id, _authorize_caller(caller)
            )
        except lifecycle.PublicLifecycleError as exc:
            if exc.code != lifecycle.UNKNOWN_SESSION:
                raise
            retained = _retained_projection(
                home, session_id, caller, private_target
            )
            _fail_lost_session(state, task_id, retained)
            return None
        return _resume_projection(
            state,
            task_id,
            home,
            session_id,
            caller,
            projection,
            staffing_selection,
            authority_failure_reason,
        )

    # Both historical private-target sessions and current repository sessions
    # are owned by this caller identity.  Looking them up before selecting a
    # creation mode lets an in-flight pre-cutover task finish as admitted.
    owned = _owned_projection(home, caller, private_target)
    if owned is not None:
        recovered_id, projection, registered = owned
        if not registered:
            _fail_lost_session(state, task_id, projection)
            return None
        return _resume_projection(
            state,
            task_id,
            home,
            recovered_id,
            caller,
            projection,
            staffing_selection,
            authority_failure_reason,
        )

    retained = _retained_owned_projection(home, caller, private_target)
    if retained is not None:
        _session_id, projection = retained
        _fail_lost_session(state, task_id, projection)
        return None

    if not attached_repository and os.path.lexists(work_area):
        _fail_lost_session(state, task_id)
        return None

    if authority_failure_reason is not None:
        _fail_before_session(state, task_id, authority_failure_reason)
        return None
    if pre_session_failure_reason is not None:
        _fail_before_session(state, task_id, pre_session_failure_reason)
        return None

    created_work_area = None
    try:
        participants = (
            milestone._participants()
            if staffing_selection is not None
            else _frozen_participants(record)
        )
        direct_repository = None
        legacy_private = not attached_repository and not direct_repository_mode
        if attached_repository:
            target = _repository_target(request)
            if target is None:
                raise AdapterError(
                    "repository-backed task has no primary repository target"
                )
        elif legacy_private:
            created_work_area, target = _private_target(
                workspace, home, task_id
            )
        else:
            # The marker makes loss of the registry record fail closed instead
            # of silently creating a second repository-writing discussion.
            os.makedirs(os.path.dirname(work_area), exist_ok=True)
            os.makedirs(work_area)
            created_work_area = work_area
            target = None
            direct_repository = (
                session_repository.checkpoint_standalone_task_context(
                    workspace,
                    "Prepare Brainstorming task %s" % task_id,
                )
            )
        body = _creation_body(
            record,
            participants,
            target,
            workspace,
            direct_repository=direct_repository,
        )
        if context["project"] is not None:
            body["project"] = context["project"]
            body["work_area"] = context["work_area"]
        kwargs = (
            {"owned_target_path": target} if legacy_private else {}
        )
        if launcher is not None:
            kwargs["launcher"] = launcher
        if staffing_selection is not None:
            kwargs["staffing_selection"] = staffing_selection
        else:
            kwargs["static_binding"] = True
        return lifecycle.create_resolved_session(
            home, body, caller, context, config, **kwargs
        )
    except (
        AdapterError,
        lifecycle.PublicLifecycleError,
        session_repository.SessionRepositoryError,
        gitops.GitError,
        tasks.TaskRequestError,
        OSError,
    ) as exc:
        code = getattr(exc, "code", lifecycle.UNAVAILABLE)
        if code == lifecycle.TARGET_IN_USE:
            owned = _owned_projection(home, caller, private_target)
            if owned is not None:
                recovered_id, projection, registered = owned
                if not registered:
                    _fail_lost_session(state, task_id, projection)
                    return None
                return _resume_projection(
                    state,
                    task_id,
                    home,
                    recovered_id,
                    caller,
                    projection,
                    staffing_selection,
                )
        if created_work_area is not None and code != lifecycle.TARGET_IN_USE:
            shutil.rmtree(created_work_area, ignore_errors=True)
        _fail_before_session(
            state,
            task_id,
            "Brainstorming session admission failed: %s" % code,
        )
        return None


def start_task(
    state,
    task_id,
    config,
    home,
    staffing_selection=None,
    launcher=None,
    session_id=None,
    pre_session_failure_reason=None,
):
    """Launch or resume under the task's one lifecycle serialization lock."""
    record = _task_record(state, task_id)
    workspace = _workspace(record["order"]["request"])
    with contextlib.ExitStack() as stack:
        try:
            lock = _task_lifecycle_lock(workspace, home, task_id)
            stack.enter_context(brainstorming._exclusive_transcript(lock))
        except OSError as exc:
            # Lock-store availability is operational, not evidence that this
            # task or its possibly-running owned session became terminal.
            raise lifecycle.PublicLifecycleError(
                503, lifecycle.UNAVAILABLE
            ) from exc
        return _start_task_exclusive(
            state,
            task_id,
            config,
            home,
            staffing_selection=staffing_selection,
            launcher=launcher,
            session_id=session_id,
            pre_session_failure_reason=pre_session_failure_reason,
        )


def start_persisted_task(
    state_path,
    task_id,
    config,
    home,
    staffing_selection=None,
    launcher=None,
    session_id=None,
):
    """Serialize a public restart with the owning durable task record."""
    with st.exclusive_mutation(state_path):
        state = st.load(state_path)
        projection = start_task(
            state,
            task_id,
            config,
            home,
            staffing_selection=staffing_selection,
            launcher=launcher,
            session_id=session_id,
        )
        record = tasks.task_record(state, task_id)
        if record["result"] is not None:
            st.save(state_path, state)
        return projection, record


def _projection_accounting(projection):
    duration = projection.get("work_duration_s")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        duration = 0.0
    token_usage = projection.get("work_token_usage")
    cost = projection.get("work_cost")
    return {
        "duration_s": float(duration),
        "token_usage": copy.deepcopy(token_usage),
        "token_usage_partial": bool(
            projection.get("work_token_usage_partial", False)
            or token_usage is None
        ),
        "cost": copy.deepcopy(cost),
        "cost_partial": bool(
            projection.get("work_cost_partial", False) or cost is None
        ),
    }


def validate_effect_result(value):
    """Validate one non-participant effect operation and its aggregate evidence.

    Physical participant calls retain the lifecycle's staffed per-call activity;
    this adapter-private callback only reports whether their agreed effects landed.
    """
    try:
        brainstorming._exact_keys(
            value,
            (
                "completed",
                "duration_s",
                "token_usage",
                "token_usage_partial",
                "cost",
                "cost_partial",
            ),
            ("reason", "activity_recorded"),
            "production effect result",
        )
        if type(value["completed"]) is not bool:
            raise brainstorming.ContractError(
                "production effect result.completed must be boolean"
            )
        if value["completed"] and "reason" in value:
            raise brainstorming.ContractError(
                "completed production effects cannot carry a reason"
            )
        reason = value.get("reason")
        if not value["completed"]:
            reason = brainstorming._text(reason, "production effect result.reason")
        checked = tasks.validate_result({
            "status": "success" if value["completed"] else "failure",
            **({"reason": reason} if not value["completed"] else {}),
            "duration_s": value["duration_s"],
            "token_usage": value["token_usage"],
            "token_usage_partial": value["token_usage_partial"],
            "cost": value["cost"],
            "cost_partial": value["cost_partial"],
            "native_result": None,
        })
        activity_recorded = value.get("activity_recorded", False)
        if type(activity_recorded) is not bool:
            raise brainstorming.ContractError(
                "production effect result.activity_recorded must be boolean"
            )
        return {
            "completed": value["completed"],
            **({"reason": reason} if not value["completed"] else {}),
            **(
                {"activity_recorded": True}
                if activity_recorded else {}
            ),
            **{
                key: checked[key]
                for key in (
                    "duration_s",
                    "token_usage",
                    "token_usage_partial",
                    "cost",
                    "cost_partial",
                )
            },
        }
    except (TypeError, ValueError, brainstorming.ContractError, tasks.ContractError) as exc:
        raise AdapterError("production effect completion is invalid") from exc


def validate_production_completion(value):
    """Validate the lead's small post-agreement control response."""
    brainstorming._model_keys(
        value,
        ("kind", "completed"),
        ("reason",),
        "production completion",
    )
    if value["kind"] != _PRODUCTION_COMPLETION_KIND:
        raise brainstorming.ContractError(
            "production completion.kind must be %s"
            % _PRODUCTION_COMPLETION_KIND
        )
    if type(value["completed"]) is not bool:
        raise brainstorming.ContractError(
            "production completion.completed must be boolean"
        )
    reason = value.get("reason")
    if value["completed"]:
        value.pop("reason", None)
    else:
        value["reason"] = brainstorming._text(
            reason, "production completion.reason"
        )
    return brainstorming._json_copy(value, "production completion")


def _production_prompt(effect_request):
    request = effect_request.get("request")
    agreement = effect_request.get("agreement")
    if not isinstance(request, dict) or not isinstance(agreement, dict):
        raise AdapterError("production effect handoff is incomplete")
    return (
        "Apply the accepted Brainstorming agreement now. Work directly in "
        "the inherited writable workspace and complete every effect named "
        "by the caller request. The private agreement itself is not a task "
        "effect. Do not merely explain or restate the work.\n\n"
        "CALLER REQUEST (JSON):\n%s\n\n"
        "ACCEPTED AGREEMENT (JSON):\n%s\n\n"
        "This is an internal Brainstorming completion exchange. Any response "
        "contract embedded in the caller request does not govern this reply. "
        "After applying the effects, return only JSON: "
        '{"kind":"production_completion","completed":true}. If an effect '
        "did not complete, return only "
        '{"kind":"production_completion","completed":false,'
        '"reason":"specific cause"}.'
        % (
            json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True),
            json.dumps(agreement, ensure_ascii=False, indent=2, sort_keys=True),
        )
    )


def _production_call_accounting(store, session_id, token, started_at):
    action_id = "task-production-effect:%s:lead" % token
    activity = store.read_activity(session_id) or {"events": []}
    events = [
        event for event in activity["events"]
        if event.get("action_id") == action_id
    ]
    duration = sum(float(event.get("duration_s") or 0.0) for event in events)
    token_usage = None
    cost = None
    for event in events:
        token_usage = st._add_token_usage(token_usage, event.get("token_usage"))
        cost = st._add_cost(cost, event.get("cost"))
    if not events:
        duration = max(0.0, time.time() - started_at)
    return events, {
        "duration_s": duration,
        "token_usage": token_usage,
        "token_usage_partial": bool(
            not events
            or any(
                event.get("token_usage") is None
                or event.get("token_usage_partial", False)
                for event in events
            )
        ),
        "cost": cost,
        "cost_partial": bool(
            not events
            or any(
                event.get("cost") is None
                or event.get("cost_partial", False)
                for event in events
            )
        ),
    }


def apply_agreed_effects(
    home,
    session_id,
    task_id,
    effect_request,
    dispatch_authority,
    staffing_selection=None,
    participant_process_factory=None,
):
    """Run the agreed production work through the task session's lead."""
    store = brainstorming.SessionStore(lifecycle.state_directory(home))
    attempt = store.read_task_effect_attempt(session_id)
    if attempt is None or attempt["task_id"] != task_id:
        raise AdapterError("production-effect session/task mismatch")
    started_at = time.time()
    completion = None
    failure = None
    try:
        staffing_kwargs = {}
        if staffing_selection is not None:
            staffing_kwargs["staffing_session"] = staffing_selection.get(
                "session"
            )
        completion, _result = lifecycle.apply_production_effect(
            home,
            session_id,
            _authorize_caller(
                _caller_for_authority(dispatch_authority, task_id)
            ),
            _production_prompt(effect_request),
            validate_production_completion,
            participant_process_factory=participant_process_factory,
            **staffing_kwargs
        )
    except Exception as exc:
        if (
            dispatch_authority == _PROFILE_AUTHORITY
            and staffing_selection is None
            and isinstance(exc, lifecycle.PublicLifecycleError)
            and exc.code == lifecycle.UNAVAILABLE
        ):
            failure = "the owner's staffing session is unavailable"
        else:
            failure = str(exc).strip() or type(exc).__name__
    events, accounting = _production_call_accounting(
        store, session_id, attempt["token"], started_at
    )
    staffed = bool(events) and all(
        event.get("model_family") is not None
        and event.get("model") is not None
        and event.get("effort") is not None
        for event in events
    )
    if failure is not None:
        completed = False
        reason = "production lead failed: %s" % failure[:3900]
    elif not staffed:
        completed = False
        reason = "production lead left no staffed physical-call evidence"
    else:
        completed = completion["completed"]
        reason = completion.get("reason")
    return {
        "completed": completed,
        **({"reason": reason} if not completed else {}),
        **accounting,
        **({"activity_recorded": True} if events else {}),
    }


def _known_effect_accounting(value):
    if not isinstance(value, dict):
        return _unknown_effect("production effect completion is invalid")
    duration = value.get("duration_s")
    try:
        normalized_duration = float(duration)
    except (TypeError, ValueError, OverflowError):
        normalized_duration = -1.0
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(normalized_duration)
        or normalized_duration < 0
    ):
        duration = 0.0
    else:
        duration = normalized_duration
    try:
        token_usage = tasks._token_usage(value.get("token_usage"))
    except (TypeError, ValueError, OverflowError, tasks.ContractError):
        token_usage = None
    token_partial = value.get("token_usage_partial")
    if type(token_partial) is not bool:
        token_partial = True
    token_partial = bool(token_partial or token_usage is None)
    try:
        cost = tasks._cost(value.get("cost"))
    except (TypeError, ValueError, OverflowError, tasks.ContractError):
        cost = None
    cost_partial = value.get("cost_partial")
    if type(cost_partial) is not bool:
        cost_partial = True
    cost_partial = bool(cost_partial or cost is None)
    reason = value.get("reason") if value.get("completed") is False else None
    if not isinstance(reason, str) or not reason.strip():
        reason = "production effect completion is invalid"
    return {
        "completed": False,
        "reason": reason,
        "duration_s": duration,
        "token_usage": token_usage,
        "token_usage_partial": token_partial,
        "cost": cost,
        "cost_partial": cost_partial,
    }


def _unknown_effect(reason):
    return {
        "completed": False,
        "reason": reason,
        "duration_s": 0.0,
        "token_usage": None,
        "token_usage_partial": True,
        "cost": None,
        "cost_partial": True,
    }


def _exception_effect(exc, started_at):
    detail = str(exc).strip() or type(exc).__name__
    effect = _unknown_effect("production effect failed: %s" % detail[:3960])
    effect["duration_s"] = max(0.0, time.time() - started_at)
    return effect


def _effect_action_id(token):
    return "task-production-effect:%s" % token


def _effect_activity_event(
    effect,
    attempt,
    projection,
    failure_type,
    participant_id="production-lead",
):
    action_id = _effect_action_id(attempt["token"])
    digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:20]
    native_result = ((projection.get("state") or {}).get("result") or {})
    rounds = native_result.get("rounds_used", 1)
    if type(rounds) is not int or rounds <= 0:
        rounds = 1
    event = {
        "id": "activity-%s" % digest,
        "action_id": action_id,
        "provider_attempt": 1,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "started_at": attempt["started_at"],
        "duration_s": effect["duration_s"],
        "kind": "production_effect",
        "stage": "production",
        "round": rounds,
        "participant_id": participant_id,
        "model_family": None,
        "model": None,
        "effort": None,
        "status": "completed" if effect["completed"] else "failed",
    }
    if effect["token_usage"] is not None:
        event["token_usage"] = copy.deepcopy(effect["token_usage"])
    if effect["token_usage_partial"]:
        event["token_usage_partial"] = True
    if effect["cost"] is not None:
        event["cost"] = copy.deepcopy(effect["cost"])
    if effect["cost_partial"]:
        event["cost_partial"] = True
    if not effect["completed"]:
        event.update({
            "failure_type": failure_type,
            "error": effect["reason"],
        })
    return brainstorming.validate_activity_event(event)


def _effect_event(events, token):
    action_id = _effect_action_id(token)
    return next(
        (event for event in events if event.get("action_id") == action_id),
        None,
    )


def _recover_effect_attempt(store, session_id, task_id, projection):
    attempt = store.read_task_effect_attempt(session_id)
    if attempt is None:
        return None
    if attempt["task_id"] != task_id:
        raise AdapterError("production-effect session/task mismatch")
    activity = store.read_activity(session_id) or {"events": []}
    if _effect_event(activity["events"], attempt["token"]) is not None:
        store.finish_task_effect_attempt(session_id, attempt["token"])
        return None
    recovered = _unknown_effect(_RECOVERED_EFFECT_ERROR)
    store.append_activity(
        session_id,
        _effect_activity_event(
            recovered,
            attempt,
            projection,
            "execution",
            participant_id=_RECOVERED_EFFECT_PARTICIPANT,
        ),
    )
    store.finish_task_effect_attempt(session_id, attempt["token"])
    return recovered


def _terminal_effect_from_projection(projection):
    terminal = [
        event
        for event in projection.get("activity") or []
        if event.get("kind") == "production_effect"
        and event.get("participant_id") == "production-lead"
    ]
    if not terminal:
        return None
    event = terminal[-1]
    completed = event["status"] == "completed"
    return {
        "completed": completed,
        **({"reason": event.get("error") or "production effects failed"}
           if not completed else {}),
    }


def _begin_effect_attempt(store, session_id, task_id):
    return store.begin_task_effect_attempt(session_id, {
        "task_id": task_id,
        "token": secrets.token_hex(16),
        "started_at": time.time(),
    })


def _merge_accounting(first, second):
    return {
        "duration_s": first["duration_s"] + second["duration_s"],
        "token_usage": st._add_token_usage(
            first["token_usage"], second["token_usage"]
        ),
        "token_usage_partial": bool(
            first["token_usage_partial"] or second["token_usage_partial"]
        ),
        "cost": st._add_cost(first["cost"], second["cost"]),
        "cost_partial": bool(first["cost_partial"] or second["cost_partial"]),
    }


def _retained_agreement(home, session_id, session_state):
    revision = session_state.get("accepted_target_revision")
    if not isinstance(revision, str) or not revision:
        raise AdapterError("a successful Brainstorming session has no agreement")
    store = brainstorming.SessionStore(lifecycle.state_directory(home))
    retained = store.read_target_revision(session_id, revision)
    exists, content = brainstorming.target_revision_content(retained)
    if not exists:
        raise AdapterError("a successful Brainstorming agreement is absent")
    try:
        rendered = content.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        rendered = base64.b64encode(content).decode("ascii")
        encoding = "base64"
    return {"exists": True, "encoding": encoding, "content": rendered}


def _finish_task_exclusive(
    state,
    task_id,
    home,
    session_id,
    apply_effects,
    effect_store,
):
    """Finish one task while holding its adapter lifecycle lock."""
    record = _task_record(state, task_id)
    caller = _task_caller(record, task_id)
    request = record["order"]["request"]
    workspace = _workspace(request)
    _work_area, _target_parent, private_target = _private_target_paths(
        workspace, home, task_id
    )
    try:
        projection = lifecycle.inspect_session(
            home, session_id, _authorize_caller(caller)
        )
    except lifecycle.PublicLifecycleError as exc:
        if exc.code != lifecycle.UNKNOWN_SESSION:
            raise
        retained = _retained_projection(
            home, session_id, caller, private_target
        )
        return _fail_lost_session(state, task_id, retained)
    session_state = projection["state"]
    repository_backed = session_repository.context_from_state(
        session_state
    ) is not None
    if session_state["status"] not in brainstorming.TERMINAL_STATUSES:
        return None
    native_result = copy.deepcopy(session_state["result"])
    if repository_backed:
        native_result["session_id"] = session_id
    accounting = _projection_accounting(projection)
    if session_state["status"] == "failure":
        reason = native_result.get("reason") or "Brainstorming did not agree."
        return tasks.record_task_result(state, task_id, {
            "status": "failure",
            "reason": reason,
            **accounting,
            "native_result": native_result,
        })
    if repository_backed:
        try:
            native_result.update(
                session_repository.sealed_range(session_state)
            )
        except (
            session_repository.SessionRepositoryError,
            gitops.GitError,
        ) as exc:
            return tasks.record_task_result(state, task_id, {
                "status": "failure",
                "reason": (
                    "Brainstorming repository delivery is unavailable: %s"
                    % exc
                ),
                **accounting,
                "native_result": native_result,
            })
        return tasks.record_task_result(state, task_id, {
            "status": "success",
            **accounting,
            "native_result": native_result,
        })
    store = effect_store
    recovered = _recover_effect_attempt(
        store, session_id, task_id, projection
    )
    if recovered is not None:
        accounting = _merge_accounting(accounting, recovered)
    prior_effect = _terminal_effect_from_projection(projection)
    if prior_effect is not None:
        result = {
            "status": "success" if prior_effect["completed"] else "failure",
            **accounting,
            "native_result": native_result,
        }
        if not prior_effect["completed"]:
            result["reason"] = prior_effect["reason"]
        return tasks.record_task_result(state, task_id, result)
    if not callable(apply_effects):
        raise AdapterError("Brainstorming production requires an effect callback")
    agreement = _retained_agreement(home, session_id, session_state)
    attempt = _begin_effect_attempt(store, session_id, task_id)
    try:
        supplied_effect = apply_effects({
            "request": copy.deepcopy(record["order"]["request"]),
            "agreement": agreement,
        })
    except Exception as exc:
        effect = _exception_effect(exc, attempt["started_at"])
        failure_type = "execution"
    else:
        try:
            effect = validate_effect_result(supplied_effect)
            failure_type = "execution"
        except AdapterError:
            effect = _known_effect_accounting(supplied_effect)
            failure_type = "protocol"
    event_effect = effect
    if effect.get("activity_recorded"):
        event_effect = {
            "completed": effect["completed"],
            **({"reason": effect["reason"]} if not effect["completed"] else {}),
            **_zero_accounting(),
        }
    store.append_activity(
        session_id,
        _effect_activity_event(
            event_effect, attempt, projection, failure_type
        ),
    )
    store.finish_task_effect_attempt(session_id, attempt["token"])
    accounting = _merge_accounting(accounting, effect)
    result = {
        "status": "success" if effect["completed"] else "failure",
        **accounting,
        "native_result": native_result,
    }
    if not effect["completed"]:
        result["reason"] = effect["reason"]
    return tasks.record_task_result(state, task_id, result)


def finish_task(
    state,
    task_id,
    home,
    session_id,
    apply_effects=None,
    effect_store=None,
):
    """Terminalize reviewed repository work; preserve legacy target effects."""
    record = _task_record(state, task_id)
    workspace = _workspace(record["order"]["request"])
    durable_store = brainstorming.SessionStore(lifecycle.state_directory(home))
    store = effect_store or durable_store
    lock = _task_lifecycle_lock(workspace, home, task_id)
    with brainstorming._exclusive_transcript(lock):
        return _finish_task_exclusive(
            state,
            task_id,
            home,
            session_id,
            apply_effects,
            store,
        )


def prepare_slice_note_request(request, planned_path):
    """Name the current run-layout path without adding an artifact result."""
    checked = tasks.validate_request(request)
    if not isinstance(planned_path, str) or not planned_path.strip():
        raise tasks.TaskRequestError(
            tasks.INVALID_TASK_REQUEST, "planned slice-note path is required"
        )
    workspace = _workspace(checked)
    absolute = os.path.realpath(
        planned_path
        if os.path.isabs(planned_path)
        else os.path.join(workspace, planned_path)
    )
    if not kvstore.path_is_inside_roots(absolute, [workspace]):
        raise tasks.TaskRequestError(
            tasks.INVALID_TASK_REQUEST,
            "planned slice-note path must stay inside the primary workspace",
        )
    if "output_directory" in checked:
        output_root = checked["output_directory"]
        output_root = os.path.realpath(
            output_root
            if os.path.isabs(output_root)
            else os.path.join(workspace, output_root)
        )
        tasks.resolve_derived_path(output_root, absolute)
    repository_backed = "repository" in (
        _structured_context(checked).get("session_charge") or {}
    )
    if not repository_backed:
        checked["request"] = (
            checked["request"].rstrip()
            + "\n\nRequired effect: create the slice note at %s." % planned_path
        )
    return tasks.validate_request(checked)


def record_slice_note_handoff(unit, record, planned_path):
    """Record a planned note that exists in the sealed repository revision."""
    result = record.get("result") if isinstance(record, dict) else None
    request = ((record.get("order") or {}).get("request") or {})
    native = result.get("native_result") if isinstance(result, dict) else None
    accepted = (
        native.get("accepted_revision") if isinstance(native, dict) else None
    )
    context = _structured_context(request)
    repository_backed = "repository" in (
        context.get("session_charge") or {}
    )
    if repository_backed:
        valid_delivery = (
            context.get("planned_slice_note_path")
            == planned_path
            and isinstance(accepted, str)
            and gitops.show_file_mode(
                _workspace(request), accepted, planned_path
            ) in ("100644", "100755")
        )
    else:
        valid_delivery = request.get("request", "").rstrip().endswith(
            "Required effect: create the slice note at %s." % planned_path
        )
    if (
        (record.get("order") or {}).get("task_executor") != "brainstorming"
        or not isinstance(result, dict)
        or result.get("status") != "success"
        or not valid_delivery
    ):
        raise AdapterError("slice-note handoff requires its successful current task")
    unit["artifact"] = planned_path
    return planned_path
