"""Milestone adapter for the independent Brainstorming lifecycle."""

from __future__ import annotations

import base64
import copy
import hashlib
import os
import shutil
import tempfile

from orchestrator import brainstorming, brainstorming_coordination
from orchestrator import brainstorming_lifecycle
from orchestrator import contracts, registry


class AdapterError(RuntimeError):
    """A milestone signal cannot safely enter or consume Brainstorming."""


class OperationalTerminalError(AdapterError):
    """The attached discussion ended because its execution failed."""

    def __init__(self, message, work_duration_s=None, work_token_usage=None,
                 work_token_usage_partial=False, work_cost=None,
                 work_cost_partial=False):
        super().__init__(message)
        self.work_duration_s = work_duration_s
        self.work_token_usage = work_token_usage
        self.work_token_usage_partial = bool(work_token_usage_partial)
        # A failed session still spent money; it crosses this seam with the
        # duration and tokens or it is lost to the run entirely.
        self.work_cost = work_cost
        self.work_cost_partial = bool(work_cost_partial)


DESIGN_AMENDMENT_LENGTH_GUIDANCE = (
    "Keep it concise and preferably under 3,000 characters, but never omit "
    "necessary meaning merely to meet that preference."
)
DESIGN_AMENDMENT_PLACEHOLDER = (
    "Replace this placeholder with one self-contained design amendment that "
    "fulfils the stated request without changing the goal. %s\n"
    % DESIGN_AMENDMENT_LENGTH_GUIDANCE
)
LEGACY_DESIGN_AMENDMENT_PLACEHOLDER = (
    "Replace this placeholder with one concise, self-contained design "
    "amendment that fulfils the stated request without changing the goal.\n"
)
DESIGN_AMENDMENT_PLACEHOLDERS = (
    DESIGN_AMENDMENT_PLACEHOLDER,
    LEGACY_DESIGN_AMENDMENT_PLACEHOLDER,
)

GUARANTEE_CALIBRATION_MAX_ROUNDS = contracts.MILESTONE_BRAINSTORMING_ROUNDS
GUARANTEE_CALIBRATION_REQUEST = (
    "Does this skeleton declare each guarantee at the right level and within "
    "the right observable scope, no stronger or weaker than its authority "
    "requires?"
)
GUARANTEE_CALIBRATION_BRIEF = (
    "Discuss only the guarantee declarations in the milestone skeleton. "
    "For each disputed guarantee, check its authority, affected party, "
    "realistic damage, enforceability, and the normal, transition, recovery, "
    "or failure states it permits. Do not strengthen a guarantee merely as a "
    "precaution. Do not alter the goal restatement, boundary, non-goals, "
    "slice plan, slice table, or unrelated material. The Initial Position "
    "must leave target_path as the complete agreed skeleton, changing it only where the "
    "discussion requires; if the current declarations are sound, retain the "
    "document unchanged."
)


def service_home(state, active_home=None):
    """Use the bound service home, active entrypoint home, or local default."""
    project = state.get("project")
    if isinstance(project, dict):
        directory = project.get("directory")
        if isinstance(directory, str) and directory.strip():
            return os.path.dirname(os.path.abspath(directory))
    if isinstance(active_home, str) and active_home.strip():
        return os.path.abspath(active_home)
    return os.path.abspath(registry.DEFAULT_HOME)


def execution_context(state):
    project = state.get("project")
    if isinstance(project, dict):
        return {
            "workspace_path": state["workspace"],
            "project": project["project"],
            "work_area": project["work_area"],
            "primary": copy.deepcopy(project["primary"]),
            "additional": copy.deepcopy(project["additional"]),
        }
    return {
        "workspace_path": state["workspace"],
        "project": None,
        "work_area": None,
        "primary": None,
        "additional": [],
    }


def _path_overlap(first, second):
    first = os.path.abspath(first)
    second = os.path.abspath(second)
    try:
        common = os.path.commonpath(
            (os.path.realpath(first), os.path.realpath(second))
        )
    except ValueError:
        common = None
    if common in (os.path.realpath(first), os.path.realpath(second)):
        return True
    return brainstorming._paths_overlap_from_existing_ancestor(first, second)


def _candidate_reference(workspace, value):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.startswith(("http://", "https://")):
        return None
    path = value if os.path.isabs(value) else os.path.join(workspace, value)
    return os.path.abspath(path)


def validate_target(state, signal, references):
    """Resolve the requested source artifact inside the milestone checkout."""
    workspace = os.path.abspath(state["workspace"])
    target = os.path.abspath(os.path.join(workspace, signal["target_path"]))
    workspace_real = os.path.realpath(workspace)
    target_real = os.path.realpath(target)
    try:
        if (
            os.path.commonpath((workspace, target)) != workspace
            or os.path.commonpath((workspace_real, target_real))
            != workspace_real
        ):
            raise AdapterError(
                "the Brainstorming proposal target leaves the workspace"
            )
    except ValueError as exc:
        raise AdapterError(
            "the Brainstorming proposal target leaves the workspace"
        ) from exc
    try:
        brainstorming_coordination.capture_materialization_source(target)
    except brainstorming_coordination.CoordinationRejected as exc:
        raise AdapterError(
            "the requested Brainstorming source target is not materializable"
        ) from exc
    return target


def stable_references(state, candidates, target_path):
    """Keep stable, unique present caller references in declared order."""
    workspace = os.path.abspath(state["workspace"])
    references = []
    seen = set()
    for candidate in candidates:
        path = _candidate_reference(workspace, candidate)
        if path is None or not os.path.lexists(path):
            continue
        try:
            rel = os.path.relpath(path, workspace)
        except ValueError:
            rel = path
        value = rel if not rel.startswith(".." + os.sep) else path
        if value not in seen:
            references.append(value)
            seen.add(value)
    return references


def validate_origin_signal(signal, kind, queued_findings=None):
    """Apply caller-state checks that the common schema cannot know."""
    if (
        kind in (
            contracts.KIND_DRAFT_SLICE_NOTE,
            contracts.KIND_IMPLEMENT,
        )
        and "request" not in signal
        and "max_rounds" not in signal
    ):
        signal = copy.deepcopy(signal)
        signal.update({
            "request": (
                "Resolve the focused design contradiction described in the "
                "supplied source finding."
            ),
            "max_rounds": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
        })
    contracts.validate_need_rethink(
        signal,
        kind,
        "milestone need_rethink",
        require_plain=kind in contracts.REPORT_KINDS,
    )
    if kind == contracts.KIND_FIX_FINDINGS:
        wanted = (signal.get("finding") or {}).get("id")
        matches = [
            finding
            for finding in list(queued_findings or [])
            if wanted is not None and finding.get("id") == wanted
        ]
        if len(matches) != 1:
            raise AdapterError(
                "a fixer rethink must name exactly one currently queued finding"
            )
        # The queue's copy is the authoritative text. A fixer echoing the
        # finding may normalize a byte it never meant to contest — one
        # transposed character in the echo killed a run (2026-08-21) —
        # so the id selects and the queue supplies the body.
        checked = copy.deepcopy(signal)
        checked["finding"] = copy.deepcopy(matches[0])
        return checked
    return copy.deepcopy(signal)


def _owned_work_areas_root(state, active_home=None):
    """Keep adapter proposals outside the milestone checkout."""
    workspace = os.path.abspath(state["workspace"])
    candidates = [
        os.path.join(
            os.path.abspath(service_home(state, active_home)),
            "brainstorming-work-areas",
        ),
        os.path.join(
            tempfile.gettempdir(),
            "impl-roadmap-brainstorming-work-areas",
        ),
    ]
    digest = hashlib.sha256(
        workspace.encode("utf-8", errors="surrogatepass")
    ).hexdigest()[:16]
    parent = os.path.dirname(workspace)
    if parent != workspace:
        candidates.append(
            os.path.join(
                parent,
                ".impl-roadmap-brainstorming-work-areas-%s" % digest,
            )
        )
    for root in candidates:
        if not _path_overlap(root, workspace):
            return root
    raise AdapterError(
        "no Brainstorming-owned work area can be placed outside the workspace"
    )


def _materialize_target(state, signal, references, active_home=None):
    """Materialize either a source proposal or a fresh amendment target."""
    source = validate_target(state, signal, references)
    root = _owned_work_areas_root(state, active_home)
    os.makedirs(root, exist_ok=True)
    work_area = tempfile.mkdtemp(prefix="milestone-", dir=root)
    target_parent = os.path.join(work_area, "target")
    os.makedirs(target_parent)
    amendment_mode = (
        signal.get("result_mode")
        == contracts.RETHINK_RESULT_DESIGN_AMENDMENT
    )
    target = os.path.join(
        target_parent,
        "amendment.md" if amendment_mode else os.path.basename(source),
    )
    try:
        if amendment_mode:
            if not os.path.isfile(source) or os.path.islink(source):
                raise AdapterError(
                    "a design amendment requires one existing regular source "
                    "artifact for context"
                )
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(DESIGN_AMENDMENT_PLACEHOLDER)
        else:
            source_revision = (
                brainstorming_coordination.capture_materialization_source(
                    source
                )
            )
            brainstorming_coordination.restore_target(target, source_revision)
    except Exception:
        shutil.rmtree(work_area)
        raise
    return work_area, target


def _participant(participant_id, role, profile, label):
    """Translate one optional act-style profile into a pinned session seat."""
    participant = {"id": participant_id, "role": role, "delivery": "llm"}
    if profile is None:
        return participant
    try:
        brainstorming._exact_keys(
            profile,
            ("agent", "model", "effort"),
            (),
            label,
        )
        participant.update(
            {
                "model_family": brainstorming._text(
                    profile["agent"], "%s.agent" % label
                ),
                "model": brainstorming._text(
                    profile["model"], "%s.model" % label
                ),
                "effort": brainstorming._text(
                    profile["effort"], "%s.effort" % label
                ),
            }
        )
    except (TypeError, ValueError, brainstorming.ContractError) as exc:
        raise AdapterError(
            "%s must contain exactly non-empty agent, model and effort"
            % label
        ) from exc
    return participant


def _narrator(profile):
    participant = {
        "id": "dante",
        "role": "common_sense",
        "delivery": "external",
        "external_provider": "narrator",
    }
    if profile is None:
        return participant
    pinned = _participant("dante", "common_sense", profile, "lead_profile")
    participant.update(
        {
            key: pinned[key]
            for key in ("model_family", "model", "effort")
        }
    )
    return participant


def _participants(lead_profile=None, counterpart_profile=None):
    return [
        _participant(
            "initial-position",
            "initial_position",
            lead_profile,
            "lead_profile",
        ),
        _participant(
            "contrary-position",
            "contrary_position",
            counterpart_profile,
            "counterpart_profile",
        ),
        _narrator(lead_profile),
    ]


def _launch_owned_session(
    state,
    config,
    unit_key,
    work_area,
    target,
    body,
    caller_suffix=None,
    staffing_selection=None,
    active_home=None,
):
    """Launch one session whose isolated target belongs to this adapter."""
    context = execution_context(state)
    if context["project"] is not None:
        body["project"] = context["project"]
        body["work_area"] = context["work_area"]
    caller = "milestone:%s:%s" % (
        state.get("name") or "run",
        unit_key,
    )
    if caller_suffix:
        caller += ":%s" % caller_suffix
    try:
        kwargs = {"owned_target_path": target}
        if staffing_selection is not None:
            kwargs["staffing_selection"] = staffing_selection
        return brainstorming_lifecycle.create_resolved_session(
            service_home(state, active_home),
            body,
            caller,
            context,
            config,
            **kwargs
        )
    except Exception:
        shutil.rmtree(work_area)
        raise


def create_session(
    state,
    config,
    unit_key,
    signal,
    references,
    authority_context=None,
    lead_profile=None,
    counterpart_profile=None,
    staffing_selection=None,
    active_home=None,
):
    """Translate one valid signal into the existing standalone lifecycle."""
    participants = _participants(lead_profile, counterpart_profile)
    work_area, target = _materialize_target(
        state, signal, references, active_home=active_home
    )
    amendment_mode = (
        signal.get("result_mode")
        == contracts.RETHINK_RESULT_DESIGN_AMENDMENT
    )
    context_references = list(references)
    if amendment_mode and signal["target_path"] not in context_references:
        context_references.append(signal["target_path"])
    source_payload = copy.deepcopy(signal["finding"])
    if amendment_mode:
        source_payload = {
            "finding": copy.deepcopy(signal["finding"]),
            "authority_context": copy.deepcopy(authority_context or {}),
        }
        if "failure_gap" in signal:
            source_payload["failure_gap"] = copy.deepcopy(
                signal["failure_gap"]
            )
    body = {
        "request": {
            "workspace_path": state["workspace"],
            "target_path": target,
            "request": signal["request"],
            "context": {
                "brief": (
                    (
                        "A milestone worker paused on one focused, in-goal "
                        "design contradiction. The target is a new concise "
                        "design amendment, not a copy of the source. Replace "
                        "its placeholder with only the agreed amendment. %s "
                        % DESIGN_AMENDMENT_LENGTH_GUIDANCE
                    )
                    if amendment_mode else
                    "A milestone worker paused with one focused design request. "
                    "The source finding below is preserved unchanged."
                ),
                "references": context_references,
                "amendments": copy.deepcopy(
                    (authority_context or {}).get("amendments") or []
                ),
                "source_payload": source_payload,
            },
            "max_rounds": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
        },
        "participants": participants,
        "closure_policy": "unanimity",
    }
    return _launch_owned_session(
        state,
        config,
        unit_key,
        work_area,
        target,
        body,
        staffing_selection=staffing_selection,
        active_home=active_home,
    )


def create_guarantee_calibration_session(
    state,
    config,
    unit_key,
    skeleton_path,
    lead_profile,
    counterpart_profile,
    references=None,
    authority_context=None,
    max_rounds=GUARANTEE_CALIBRATION_MAX_ROUNDS,
    staffing_selection=None,
    active_home=None,
):
    """Open a bounded discussion over an isolated full-skeleton copy."""
    if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) \
            or max_rounds <= 0:
        raise AdapterError("guarantee calibration max_rounds must be positive")
    participants = _participants(lead_profile, counterpart_profile)
    references = list(references or [])
    source = {
        "target_path": skeleton_path,
        "result_mode": contracts.RETHINK_RESULT_PROPOSAL,
    }
    source_path = validate_target(state, source, references)
    if not os.path.isfile(source_path) or os.path.islink(source_path):
        raise AdapterError(
            "guarantee calibration requires one existing regular skeleton"
        )
    work_area, target = _materialize_target(
        state, source, references, active_home=active_home
    )
    context_references = list(references)
    if skeleton_path not in context_references:
        context_references.append(skeleton_path)
    body = {
        "request": {
            "workspace_path": state["workspace"],
            "target_path": target,
            "request": GUARANTEE_CALIBRATION_REQUEST,
            "context": {
                "brief": GUARANTEE_CALIBRATION_BRIEF,
                "references": context_references,
                "amendments": copy.deepcopy(
                    (authority_context or {}).get("amendments") or []
                ),
                "source_payload": {
                    "goal": copy.deepcopy(state.get("goal")),
                    "authority_context": copy.deepcopy(
                        authority_context or {}
                    ),
                },
            },
            "max_rounds": max_rounds,
        },
        "participants": participants,
        "closure_policy": "unanimity",
    }
    return _launch_owned_session(
        state,
        config,
        unit_key,
        work_area,
        target,
        body,
        caller_suffix="guarantee-calibration",
        staffing_selection=staffing_selection,
        active_home=active_home,
    )


def inspect_session(state, session_id, active_home=None):
    return brainstorming_lifecycle.inspect_session(
        service_home(state, active_home), session_id, lambda _record: None
    )


def retained_revision(state, session_id, revision, active_home=None):
    store = brainstorming.SessionStore(
        brainstorming_lifecycle.state_directory(
            service_home(state, active_home)
        )
    )
    return store.read_target_revision(session_id, revision)


def prompt_handoff(state, handoff, active_home=None):
    """Attach exact retained proposal bytes for one worker prompt only."""
    expanded = copy.deepcopy(handoff)
    if "retained_target" in expanded:
        return expanded
    record = retained_revision(
        state,
        expanded["session_id"],
        expanded["accepted_target_revision"],
        active_home=active_home,
    )
    exists, content = brainstorming.target_revision_content(record)
    try:
        rendered = content.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        rendered = base64.b64encode(content).decode("ascii")
        encoding = "base64"
    expanded["retained_target"] = {
        "exists": exists,
        "encoding": encoding,
        "content": rendered,
    }
    return expanded


def terminal_handoff(state, session_id, active_home=None):
    """Return one retained terminal result and its accepted authority."""
    projected = inspect_session(state, session_id, active_home=active_home)
    session_state = projected["state"]
    if session_state["status"] not in brainstorming.TERMINAL_STATUSES:
        return None
    if session_state.get("failure_origin") == "operational":
        raise OperationalTerminalError(
            "the Brainstorming lifecycle ended because execution failed",
            work_duration_s=projected.get("work_duration_s"),
            work_token_usage=projected.get("work_token_usage"),
            work_token_usage_partial=projected.get(
                "work_token_usage_partial", False
            ),
            work_cost=projected.get("work_cost"),
            work_cost_partial=projected.get("work_cost_partial", False),
        )
    handoff = {
        "session_id": session_id,
        "result": copy.deepcopy(session_state["result"]),
        "accepted_target_revision": session_state[
            "accepted_target_revision"
        ],
        "work_duration_s": projected.get("work_duration_s"),
        "work_token_usage": projected.get("work_token_usage"),
        "work_token_usage_partial": projected.get(
            "work_token_usage_partial", False
        ),
        "work_cost": projected.get("work_cost"),
        "work_cost_partial": projected.get("work_cost_partial", False),
    }
    if session_state["status"] == "success":
        revision = handoff["accepted_target_revision"]
        if revision is None:
            raise AdapterError(
                "a successful Brainstorming session has no accepted target"
            )
        retained_revision(
            state, session_id, revision, active_home=active_home
        )
        return prompt_handoff(state, handoff, active_home=active_home)
    return handoff
