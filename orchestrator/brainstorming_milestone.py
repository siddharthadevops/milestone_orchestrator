"""Milestone adapter for the independent Brainstorming lifecycle."""

from __future__ import annotations

import base64
import copy
import hashlib
import os
import tempfile

from orchestrator import brainstorming, brainstorming_coordination
from orchestrator import brainstorming_lifecycle
from orchestrator import contracts, registry, session_calls, session_repository


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
    if kind not in contracts.RETHINK_KINDS or not isinstance(signal, dict):
        raise AdapterError("the origin cannot open a rethink session")
    if signal.get("status") != "need_rethink" or signal.get("kind") != kind:
        raise AdapterError("the rethink signal does not match its origin")
    finding = signal.get("finding")
    if not isinstance(finding, dict) or not finding:
        raise AdapterError("a rethink requires one source finding")
    if kind in contracts.REPORT_KINDS:
        contracts.validate_report_finding(
            finding,
            "milestone need_rethink.finding",
            require_plain=True,
        )
    target = signal.get("target_path")
    if (
        not isinstance(target, str)
        or not target.strip()
        or os.path.isabs(target)
        or "\x00" in target
        or os.path.normpath(target) != target
        or target in (".", "..")
        or target.startswith(".." + os.sep)
    ):
        raise AdapterError(
            "a rethink target must be normalized and workspace-relative"
        )
    checked = {
        "finding": copy.deepcopy(finding),
        "target_path": target,
    }
    if kind == contracts.KIND_FIX_FINDINGS:
        wanted = finding.get("id")
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
        checked["finding"] = copy.deepcopy(matches[0])
    return checked


def _owned_work_areas_root(state, active_home=None):
    """Place standalone Brainstorming task targets outside the workspace."""
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
        candidates.append(os.path.join(
            parent,
            ".impl-roadmap-brainstorming-work-areas-%s" % digest,
        ))
    for root in candidates:
        if not _path_overlap(root, workspace):
            return root
    raise AdapterError(
        "no Brainstorming-owned work area can be placed outside the workspace"
    )


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


def _launch_repository_session(
    state,
    config,
    unit_key,
    body,
    staffing_selection=None,
    active_home=None,
):
    """Launch a milestone session directly in the granted project repo."""
    context = execution_context(state)
    if context["project"] is not None:
        body["project"] = context["project"]
        body["work_area"] = context["work_area"]
    caller = "milestone:%s:%s" % (
        state.get("name") or "run", unit_key
    )
    kwargs = {}
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


def create_session(
    state,
    config,
    unit_key,
    signal,
    references,
    session_charge,
    authority_context=None,
    lead_profile=None,
    counterpart_profile=None,
    staffing_selection=None,
    active_home=None,
):
    """Translate one valid signal into the existing standalone lifecycle."""
    participants = _participants(lead_profile, counterpart_profile)
    checked_charge = session_calls.validate_charge(session_charge)
    if checked_charge["job"] != "rethink":
        raise AdapterError("an attached rethink requires the rethink charge")
    validate_target(state, signal, references)
    context_references = list(references)
    if signal["target_path"] not in context_references:
        context_references.append(signal["target_path"])
    source_payload = {
        "finding": copy.deepcopy(signal["finding"]),
        "session_charge": checked_charge,
    }
    accepted = [
        copy.deepcopy(item)
        for item in (authority_context or {}).get("amendments") or []
        if isinstance(item, dict)
        and item.get("authority") == "brainstorming_design"
    ]
    body = {
        "request": {
            "workspace_path": state["workspace"],
            "target_path": signal["target_path"],
            "request": (
                "Resolve the focused contradiction in the supplied finding. "
                "Edit the target and any other repository files the resolution "
                "requires."
            ),
            "context": {
                "brief": (
                    "A milestone worker reported one focused contradiction. "
                    "The finding below is the complete rethink charge."
                ),
                "references": context_references,
                "amendments": accepted,
                "source_payload": source_payload,
            },
            "max_rounds": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
        },
        "participants": participants,
        "closure_policy": "unanimity",
    }
    return _launch_repository_session(
        state,
        config,
        unit_key,
        body,
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
    repository_backed = session_repository.context_from_state(
        session_state
    ) is not None
    handoff = {
        "session_id": session_id,
        "result": copy.deepcopy(session_state["result"]),
        "work_duration_s": projected.get("work_duration_s"),
        "work_token_usage": projected.get("work_token_usage"),
        "work_token_usage_partial": projected.get(
            "work_token_usage_partial", False
        ),
        "work_cost": projected.get("work_cost"),
        "work_cost_partial": projected.get("work_cost_partial", False),
    }
    if repository_backed:
        if session_state["status"] == "success":
            handoff.update(session_repository.sealed_range(session_state))
        return handoff
    handoff["accepted_target_revision"] = session_state[
        "accepted_target_revision"
    ]
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
