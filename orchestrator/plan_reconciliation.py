"""Observe one accepted canonical-plan range and open its wipe account.

The two plans come only from committed Git objects.  This module records the
facts needed by the later repair slice; it never changes Git, unit history, or
event history itself.
"""

from __future__ import annotations

import copy

from orchestrator import canonical_plan, gitops
from orchestrator import state as st


class PlanReconciliationError(canonical_plan.CanonicalPlanError):
    """The declared accepted range cannot be observed safely."""


def _full_declared_revision(workspace, revision, label):
    if (
        not isinstance(revision, str)
        or len(revision) != 40
        or any(character not in "0123456789abcdef" for character in revision)
    ):
        raise PlanReconciliationError("%s must be a full revision" % label)
    try:
        resolved = gitops.commit_full_sha(workspace, revision)
    except gitops.GitError as exc:
        raise PlanReconciliationError(
            "%s cannot be resolved: %s" % (label, exc)
        ) from exc
    if resolved != revision:
        raise PlanReconciliationError("%s is not an exact commit" % label)
    return resolved


def _resolved_gate(workspace, revision, label):
    if not isinstance(revision, str) or not revision:
        raise PlanReconciliationError("%s is missing" % label)
    try:
        return gitops.commit_full_sha(workspace, revision)
    except gitops.GitError as exc:
        raise PlanReconciliationError(
            "%s cannot be resolved: %s" % (label, exc)
        ) from exc


def _committed_plan(workspace, revision, path, anchored_document=None):
    if gitops.show_file_mode(workspace, revision, path) not in (
        "100644", "100755"
    ):
        raise PlanReconciliationError(
            "canonical-plan revision does not contain a regular skeleton"
        )
    document = gitops.show_file(workspace, revision, path)
    if document is None:
        raise PlanReconciliationError(
            "canonical-plan revision cannot resolve its skeleton"
        )
    validated = canonical_plan.validate_canonical_plan(
        document,
        document if anchored_document is None else anchored_document,
    )
    return document, validated


def _unit_boundaries(state, workspace):
    boundaries = []
    by_key = {}
    for unit in state.get("units") or []:
        key = st.unit_key(unit)
        gate = unit.get("gate_commit")
        boundary = {
            "unit": key,
            "kind": unit.get("kind"),
            "slice_id": unit.get("slice_id"),
            "part": unit.get("part"),
            "status": unit.get("status"),
            "gate_commit": gate,
            "gate_revision": (
                None if gate is None else _resolved_gate(
                    workspace, gate, "%s gate_commit" % key
                )
            ),
            "closed_record": copy.deepcopy(unit.get("closed_record")),
            "implementation_cut": copy.deepcopy(
                unit.get("implementation_cut")
            ),
        }
        boundaries.append(boundary)
        by_key[key] = boundary
    return boundaries, by_key


def _completed_checkpoint_anchors(state, by_key):
    events = state.get("events") or []
    barriers = st.reconciliation_invalidation_barriers(state)
    later_closures = set()
    completed = []
    for event in reversed(events):
        if not st.event_survives_reconciliation_barrier(
            state, event, barriers
        ):
            continue
        unit_key = event.get("unit")
        if event.get("type") == "slice_closed":
            later_closures.add(unit_key)
            continue
        if (
            event.get("type") != "verification"
            or unit_key not in later_closures
            or event.get("cadence") not in (
                "four_slice_checkpoint", "milestone_final"
            )
            or event.get("status") not in ("passed", "no_suite")
            or event.get("ok") is not True
            or event.get("stable") is not True
        ):
            continue
        unit = by_key.get(unit_key)
        if unit is None or unit["gate_revision"] is None:
            raise PlanReconciliationError(
                "completed checkpoint %r has no unit gate" % unit_key
            )
        completed.append(
            {
                "event_seq": event.get("seq"),
                "unit": unit_key,
                "slice_id": unit.get("slice_id"),
                "cadence": event.get("cadence"),
                "gate_revision": unit["gate_revision"],
            }
        )
    completed.reverse()
    return completed


def _candidate_index(old_plan, accepted_plan, started_ids):
    started_positions = [
        index
        for index, slice_plan in enumerate(old_plan)
        if slice_plan["id"] in started_ids
    ]
    if not started_positions:
        return None, ()
    frontier = max(started_positions)
    accepted_ids = [slice_plan["id"] for slice_plan in accepted_plan]
    accepted_id_set = set(accepted_ids)

    deleted = [
        index
        for index, slice_plan in enumerate(old_plan)
        if slice_plan["id"] in started_ids
        and slice_plan["id"] not in accepted_id_set
    ]
    positional = next(
        (
            index
            for index in range(frontier + 1)
            if index >= len(accepted_ids)
            or old_plan[index]["id"] != accepted_ids[index]
        ),
        None,
    )
    candidates = list(deleted)
    if positional is not None:
        candidates.append(positional)
    if not candidates:
        return None, ()

    candidate = min(candidates)
    triggers = []
    if candidate in deleted:
        triggers.append("started_deletion")
    if positional == candidate:
        triggers.append("historical_positional_divergence")
    return candidate, tuple(triggers)


def _last_gate_by_slice(unit_boundaries):
    gates = {}
    for boundary in unit_boundaries:
        if (
            boundary["kind"] == st.UNIT_SLICE_IMPL
            and boundary["gate_revision"] is not None
        ):
            gates[boundary["slice_id"]] = boundary["gate_revision"]
    return gates


def _milestone_start_revision(state, workspace):
    for event in state.get("events") or []:
        if event.get("type") == "gate_commit" and event.get("unit") == st.UNIT_SKELETON:
            return _resolved_gate(
                workspace,
                event.get("sha"),
                "initial skeleton gate_commit",
            )
    raise PlanReconciliationError("initial skeleton gate_commit is missing")


def _wipe_base(
    old_plan,
    accepted_plan,
    candidate,
    slice_gates,
    milestone_start_revision,
):
    if candidate == 0:
        return milestone_start_revision
    preceding_id = old_plan[candidate - 1]["id"]
    accepted_ids = [slice_plan["id"] for slice_plan in accepted_plan]
    if (
        candidate > len(accepted_ids)
        or accepted_ids[candidate - 1] != preceding_id
    ):
        raise PlanReconciliationError(
            "the wipe prefix has no surviving preceding slice"
        )
    try:
        return slice_gates[preceding_id]
    except KeyError as exc:
        raise PlanReconciliationError(
            "preceding slice %s has no final implementation gate"
            % preceding_id
        ) from exc


def observe_accepted_range(
    state,
    source_base_revision,
    accepted_revision,
    source=None,
):
    """Observe A..B and either return ``no_wipe`` or persist one open record.

    ``source`` is opaque structural metadata identifying the call/session that
    produced the range.  It is copied into the record, never interpreted.
    """
    milestone = state.get("milestone")
    workspace = state.get("workspace")
    if not isinstance(milestone, dict) or not isinstance(workspace, str):
        raise PlanReconciliationError(
            "run state has no milestone workspace boundary"
        )
    if milestone.get(canonical_plan.RECONCILIATION_KEY) is not None:
        raise PlanReconciliationError(
            "an accepted-range reconciliation is already open"
        )

    source_base_revision = _full_declared_revision(
        workspace, source_base_revision, "source_base_revision"
    )
    accepted_revision = _full_declared_revision(
        workspace, accepted_revision, "accepted_revision"
    )
    try:
        if not gitops.is_ancestor(
            workspace, source_base_revision, accepted_revision
        ):
            raise PlanReconciliationError(
                "accepted revision is not descended from its source base"
            )
        if gitops.head_full_sha(workspace) != accepted_revision:
            raise PlanReconciliationError(
                "HEAD must equal accepted_revision during plan observation"
            )
    except gitops.GitError as exc:
        raise PlanReconciliationError(
            "accepted range cannot be inspected: %s" % exc
        ) from exc
    branch = gitops.head_symbolic_ref(workspace)

    anchor = milestone.get(canonical_plan.ANCHOR_KEY)
    if not isinstance(anchor, dict) or set(anchor) != {"path", "revision"}:
        raise PlanReconciliationError("canonical-plan anchor is invalid")
    path = anchor.get("path")
    if not isinstance(path, str) or not path:
        raise PlanReconciliationError("canonical-plan anchor path is invalid")

    old_document, old = _committed_plan(
        workspace, source_base_revision, path
    )
    _accepted_document, accepted = _committed_plan(
        workspace, accepted_revision, path, anchored_document=old_document
    )
    old_plan = old["slices"]
    accepted_plan = accepted["slices"]

    base_result = {
        "source": copy.deepcopy(source),
        "source_base_revision": source_base_revision,
        "accepted_revision": accepted_revision,
        "old_plan": copy.deepcopy(old_plan),
        "accepted_plan": copy.deepcopy(accepted_plan),
    }
    if old["block"] == accepted["block"]:
        return dict(base_result, status="no_wipe")
    if anchor.get("revision") != accepted_revision:
        raise PlanReconciliationError(
            "changed canonical plan is not anchored at accepted_revision"
        )

    unit_boundaries, by_key = _unit_boundaries(state, workspace)
    started_ids = {
        boundary["slice_id"]
        for boundary in unit_boundaries
        if boundary["slice_id"] is not None
    }
    candidate, triggers = _candidate_index(
        old_plan, accepted_plan, started_ids
    )

    if candidate is None:
        return dict(base_result, status="no_wipe")

    skeleton = by_key.get(st.UNIT_SKELETON)
    if skeleton is None or skeleton["gate_revision"] is None:
        raise PlanReconciliationError(
            "milestone-start skeleton gate is missing"
        )
    milestone_start_revision = _milestone_start_revision(state, workspace)
    checkpoint_anchors = _completed_checkpoint_anchors(state, by_key)
    slice_gates = _last_gate_by_slice(unit_boundaries)
    wipe_boundary = _wipe_base(
        old_plan,
        accepted_plan,
        candidate,
        slice_gates,
        milestone_start_revision,
    )

    suffix_ids = {
        slice_plan["id"] for slice_plan in old_plan[candidate:]
    }
    invalidated_units = [
        boundary["unit"]
        for boundary in unit_boundaries
        if boundary["slice_id"] in suffix_ids
    ]
    invalidated_slice_ids = [
        slice_plan["id"]
        for slice_plan in old_plan[candidate:]
        if slice_plan["id"] in started_ids
    ]
    invalidated_slice_set = set(invalidated_slice_ids)
    requeue_slice_ids = [
        slice_plan["id"]
        for slice_plan in accepted_plan
        if slice_plan["id"] in invalidated_slice_set
    ]
    checkpoint_invalidations = [
        copy.deepcopy(checkpoint)
        for checkpoint in checkpoint_anchors
        if checkpoint["slice_id"] in invalidated_slice_set
    ]

    opening_account = {
        "wipe_boundary": wipe_boundary,
        "boundary_old_plan_index": candidate,
        "boundary_slice_id": old_plan[candidate]["id"],
        "triggers": list(triggers),
        "invalidated_units": invalidated_units,
        "invalidated_slice_ids": invalidated_slice_ids,
        "requeue_slice_ids": requeue_slice_ids,
        "checkpoint_invalidations": checkpoint_invalidations,
    }
    record = {
        "status": "open",
        "source": copy.deepcopy(source),
        "source_base_revision": source_base_revision,
        "accepted_revision": accepted_revision,
        "branch": branch,
        "skeleton_path": path,
        "original_old_plan": copy.deepcopy(old_plan),
        "accepted_plan": copy.deepcopy(accepted_plan),
        "original_run_boundaries": {
            "milestone_status": milestone.get("status"),
            "milestone_start_revision": milestone_start_revision,
            "units": copy.deepcopy(unit_boundaries),
            "checkpoint_anchors": copy.deepcopy(checkpoint_anchors),
        },
        "wipe_boundary": wipe_boundary,
        "opening_account": opening_account,
    }
    milestone[canonical_plan.RECONCILIATION_KEY] = record
    return {"status": "opened", "reconciliation": copy.deepcopy(record)}


def _final_account(record, final_plan):
    """Recompute one account only from Slice 10's frozen original facts."""
    old_plan = record.get("original_old_plan")
    original = record.get("original_run_boundaries")
    if (
        not isinstance(old_plan, list)
        or not isinstance(final_plan, list)
        or not isinstance(original, dict)
        or not isinstance(original.get("units"), list)
        or not isinstance(original.get("checkpoint_anchors"), list)
    ):
        raise PlanReconciliationError(
            "reconciliation original boundaries are invalid"
        )
    unit_boundaries = original["units"]
    started_ids = {
        boundary.get("slice_id")
        for boundary in unit_boundaries
        if isinstance(boundary, dict) and boundary.get("slice_id") is not None
    }
    candidate, triggers = _candidate_index(
        old_plan, final_plan, started_ids
    )
    empty = {
        "wipe_boundary": None,
        "boundary_old_plan_index": None,
        "boundary_slice_id": None,
        "triggers": [],
        "invalidated_units": [],
        "invalidated_slice_ids": [],
        "requeue_slice_ids": [],
        "checkpoint_invalidations": [],
        "invalidated_gate_revisions": [],
        "invalidated_revisions": [],
    }
    if candidate is None:
        return empty

    milestone_start = original.get("milestone_start_revision")
    if not isinstance(milestone_start, str) or not milestone_start:
        raise PlanReconciliationError(
            "reconciliation milestone-start revision is missing"
        )
    slice_gates = _last_gate_by_slice(unit_boundaries)
    wipe_boundary = _wipe_base(
        old_plan,
        final_plan,
        candidate,
        slice_gates,
        milestone_start,
    )
    suffix_ids = {
        slice_plan["id"] for slice_plan in old_plan[candidate:]
    }
    invalidated_units = [
        boundary["unit"]
        for boundary in unit_boundaries
        if boundary.get("slice_id") in suffix_ids
    ]
    invalidated_slice_ids = [
        slice_plan["id"]
        for slice_plan in old_plan[candidate:]
        if slice_plan["id"] in started_ids
    ]
    invalidated_slice_set = set(invalidated_slice_ids)
    requeue_slice_ids = [
        slice_plan["id"]
        for slice_plan in final_plan
        if slice_plan["id"] in invalidated_slice_set
    ]
    checkpoint_invalidations = [
        copy.deepcopy(checkpoint)
        for checkpoint in original["checkpoint_anchors"]
        if checkpoint.get("slice_id") in invalidated_slice_set
    ]
    invalidated_gate_revisions = []
    for boundary in unit_boundaries:
        if boundary.get("unit") not in invalidated_units:
            continue
        revision = boundary.get("gate_revision")
        if revision is not None and revision not in invalidated_gate_revisions:
            invalidated_gate_revisions.append(revision)
    return {
        "wipe_boundary": wipe_boundary,
        "boundary_old_plan_index": candidate,
        "boundary_slice_id": old_plan[candidate]["id"],
        "triggers": list(triggers),
        "invalidated_units": invalidated_units,
        "invalidated_slice_ids": invalidated_slice_ids,
        "requeue_slice_ids": requeue_slice_ids,
        "checkpoint_invalidations": checkpoint_invalidations,
        "invalidated_gate_revisions": invalidated_gate_revisions,
        "invalidated_revisions": [],
    }


def validate_dispatch_state(state):
    """Read-only admission checks for the sole merge-repair dispatch."""
    milestone = state.get("milestone")
    workspace = state.get("workspace")
    record = (
        milestone.get(canonical_plan.RECONCILIATION_KEY)
        if isinstance(milestone, dict) else None
    )
    if (
        not isinstance(workspace, str)
        or not isinstance(record, dict)
        or record.get("status") != "open"
    ):
        raise PlanReconciliationError("no open reconciliation is available")
    accepted = _full_declared_revision(
        workspace, record.get("accepted_revision"), "accepted_revision"
    )
    source_base = _full_declared_revision(
        workspace,
        record.get("source_base_revision"),
        "source_base_revision",
    )
    branch = record.get("branch")
    path = record.get("skeleton_path")
    anchor = milestone.get(canonical_plan.ANCHOR_KEY)
    original = record.get("original_run_boundaries")
    if (
        not isinstance(branch, str)
        or not branch
        or not isinstance(path, str)
        or not path
        or anchor != {"path": path, "revision": accepted}
        or not isinstance(original, dict)
    ):
        raise PlanReconciliationError(
            "open reconciliation authority is incomplete"
        )
    milestone_start = _full_declared_revision(
        workspace,
        original.get("milestone_start_revision"),
        "milestone_start_revision",
    )
    wipe_boundary = _full_declared_revision(
        workspace, record.get("wipe_boundary"), "wipe_boundary"
    )
    try:
        if gitops.head_full_sha(workspace) != accepted:
            raise PlanReconciliationError(
                "merge repair must dispatch from accepted_revision"
            )
        if gitops.head_symbolic_ref(workspace) != branch:
            raise PlanReconciliationError(
                "merge repair must dispatch from the recorded branch"
            )
        if not gitops.repository_clean(workspace):
            raise PlanReconciliationError(
                "merge repair requires a clean accepted revision"
            )
        if not gitops.linear_interval(workspace, milestone_start, accepted):
            raise PlanReconciliationError(
                "accepted run-owned history is not linear"
            )
        if not gitops.is_ancestor(workspace, source_base, accepted):
            raise PlanReconciliationError(
                "accepted revision is not descended from its source base"
            )
        if not gitops.is_ancestor(workspace, wipe_boundary, accepted):
            raise PlanReconciliationError(
                "opening wipe boundary is not an accepted ancestor"
            )
    except gitops.GitError as exc:
        raise PlanReconciliationError(
            "merge-repair dispatch state cannot be read: %s" % exc
        ) from exc
    source_document, _source = _committed_plan(
        workspace, source_base, path
    )
    _accepted_document, accepted_plan = _committed_plan(
        workspace, accepted, path, anchored_document=source_document
    )
    if accepted_plan["slices"] != record.get("accepted_plan"):
        raise PlanReconciliationError(
            "accepted plan no longer matches the frozen reconciliation"
        )
    return copy.deepcopy(record)


def validate_final_state(state, record):
    """Read-only finite postconditions and final-account recomputation."""
    workspace = state.get("workspace")
    if not isinstance(workspace, str) or not isinstance(record, dict):
        raise PlanReconciliationError("final reconciliation state is invalid")
    accepted = _full_declared_revision(
        workspace, record.get("accepted_revision"), "accepted_revision"
    )
    original = record.get("original_run_boundaries")
    if not isinstance(original, dict):
        raise PlanReconciliationError(
            "reconciliation original boundaries are missing"
        )
    milestone_start = _full_declared_revision(
        workspace,
        original.get("milestone_start_revision"),
        "milestone_start_revision",
    )
    try:
        final_head = gitops.head_full_sha(workspace)
        if final_head == accepted:
            raise PlanReconciliationError(
                "merge repair produced no final commit"
            )
        if gitops.head_symbolic_ref(workspace) != record.get("branch"):
            raise PlanReconciliationError(
                "merge repair changed the recorded branch"
            )
        if not gitops.repository_clean(workspace):
            raise PlanReconciliationError(
                "merge repair left the repository dirty"
            )
        if not gitops.linear_interval(workspace, milestone_start, final_head):
            raise PlanReconciliationError(
                "final run-owned history is not linear"
            )
    except gitops.GitError as exc:
        raise PlanReconciliationError(
            "merge-repair final state cannot be read: %s" % exc
        ) from exc

    path = record.get("skeleton_path")
    accepted_document = gitops.show_file(workspace, accepted, path)
    if accepted_document is None:
        raise PlanReconciliationError(
            "accepted revision cannot supply the final plan anchor"
        )
    final_document, final = _committed_plan(
        workspace,
        final_head,
        path,
        anchored_document=accepted_document,
    )
    account = _final_account(record, final["slices"])
    try:
        boundary = account["wipe_boundary"]
        if boundary is None:
            if not gitops.is_ancestor(workspace, accepted, final_head):
                raise PlanReconciliationError(
                    "no-wipe final history does not retain accepted_revision"
                )
        else:
            boundary = _full_declared_revision(
                workspace, boundary, "final wipe_boundary"
            )
            if not gitops.is_ancestor(workspace, boundary, accepted):
                raise PlanReconciliationError(
                    "final wipe boundary is not in the accepted history"
                )
            if not gitops.is_ancestor(workspace, boundary, final_head):
                raise PlanReconciliationError(
                    "final wipe boundary is not an ancestor of final HEAD"
                )
            invalidated = gitops.commits_between(
                workspace, boundary, accepted
            )
            for revision in invalidated:
                if gitops.is_ancestor(workspace, revision, final_head):
                    raise PlanReconciliationError(
                        "invalidated revision remains in final HEAD ancestry"
                    )
            account["invalidated_revisions"] = invalidated
    except gitops.GitError as exc:
        raise PlanReconciliationError(
            "merge-repair ancestry cannot be checked: %s" % exc
        ) from exc
    return {
        "final_head": final_head,
        "final_document": final_document,
        "final_plan": copy.deepcopy(final["slices"]),
        "projection": copy.deepcopy(final["projection"]),
        "final_account": account,
    }
