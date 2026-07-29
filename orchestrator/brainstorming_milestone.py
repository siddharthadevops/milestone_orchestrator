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


DESIGN_AMENDMENT_PLACEHOLDER = (
    "Replace this placeholder with one concise, self-contained design "
    "amendment that resolves the stated question without changing the goal.\n"
)

GUARANTEE_CALIBRATION_MAX_ROUNDS = 5
GUARANTEE_CALIBRATION_QUESTION = (
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
    "slice plan, slice table, or unrelated material. The lead must leave "
    "target_path as the complete agreed skeleton, changing it only where the "
    "discussion requires; if the current declarations are sound, retain the "
    "document unchanged."
)


def service_home(state):
    """Use the bound service home, or the ordinary default for local runs."""
    project = state.get("project")
    if isinstance(project, dict):
        directory = project.get("directory")
        if isinstance(directory, str) and directory.strip():
            return os.path.dirname(os.path.abspath(directory))
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
    contracts.validate_need_rethink(
        signal,
        kind,
        "milestone need_rethink",
        require_plain=kind in contracts.REPORT_KINDS,
    )
    if kind == contracts.KIND_FIX_FINDINGS:
        matches = [
            finding
            for finding in list(queued_findings or [])
            if brainstorming._same_json_value(finding, signal["finding"])
        ]
        if len(matches) != 1:
            raise AdapterError(
                "a fixer rethink must name exactly one currently queued finding"
            )
    return copy.deepcopy(signal)


def _owned_work_areas_root(state):
    """Keep adapter proposals outside the milestone checkout."""
    workspace = os.path.abspath(state["workspace"])
    candidates = [
        os.path.join(
            os.path.abspath(service_home(state)),
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


def _materialize_target(state, signal, references):
    """Materialize either a source proposal or a fresh amendment target."""
    source = validate_target(state, signal, references)
    root = _owned_work_areas_root(state)
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
    participant = {"id": participant_id, "role": role}
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


def _participants(lead_profile=None, counterpart_profile=None):
    return [
        _participant("lead", "lead", lead_profile, "lead_profile"),
        _participant(
            "interlocutor",
            "interlocutor",
            counterpart_profile,
            "counterpart_profile",
        ),
    ]


def _launch_owned_session(
    state,
    config,
    unit_key,
    work_area,
    target,
    body,
    caller_suffix=None,
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
        return brainstorming_lifecycle.create_resolved_session(
            service_home(state),
            body,
            caller,
            context,
            config,
            owned_target_path=target,
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
):
    """Translate one valid signal into the existing standalone lifecycle."""
    participants = _participants(lead_profile, counterpart_profile)
    work_area, target = _materialize_target(state, signal, references)
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
            "question": signal["question"],
            "context": {
                "brief": (
                    (
                        "A milestone worker paused on one focused, in-goal "
                        "design contradiction. The target is a new concise "
                        "design amendment, not a copy of the source. Replace "
                        "its placeholder with only the agreed amendment. "
                    )
                    if amendment_mode else
                    "A milestone worker paused on one focused design question. "
                    "The source finding below is preserved unchanged."
                ),
                "references": context_references,
                "source_payload": source_payload,
            },
            "max_rounds": signal["max_rounds"],
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
    work_area, target = _materialize_target(state, source, references)
    context_references = list(references)
    if skeleton_path not in context_references:
        context_references.append(skeleton_path)
    body = {
        "request": {
            "workspace_path": state["workspace"],
            "target_path": target,
            "question": GUARANTEE_CALIBRATION_QUESTION,
            "context": {
                "brief": GUARANTEE_CALIBRATION_BRIEF,
                "references": context_references,
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
    )


def inspect_session(state, session_id):
    return brainstorming_lifecycle.inspect_session(
        service_home(state), session_id, lambda _record: None
    )


def retained_revision(state, session_id, revision):
    store = brainstorming.SessionStore(
        brainstorming_lifecycle.state_directory(service_home(state))
    )
    return store.read_target_revision(session_id, revision)


def prompt_handoff(state, handoff):
    """Attach exact retained proposal bytes for one worker prompt only."""
    expanded = copy.deepcopy(handoff)
    if "retained_target" in expanded:
        return expanded
    record = retained_revision(
        state,
        expanded["session_id"],
        expanded["accepted_target_revision"],
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


def terminal_handoff(state, session_id):
    """Return one retained terminal result and its lead-accepted authority."""
    projected = inspect_session(state, session_id)
    session_state = projected["state"]
    if session_state["status"] not in brainstorming.TERMINAL_STATUSES:
        if projected["process"] != "running":
            raise OperationalTerminalError(
                "the Brainstorming lifecycle stopped before a terminal result"
            )
        return None
    if session_state.get("failure_origin") == "operational":
        raise OperationalTerminalError(
            "the Brainstorming lifecycle ended because execution failed"
        )
    handoff = {
        "session_id": session_id,
        "result": copy.deepcopy(session_state["result"]),
        "accepted_target_revision": session_state[
            "accepted_target_revision"
        ],
    }
    if session_state["status"] == "success":
        revision = handoff["accepted_target_revision"]
        if revision is None:
            raise AdapterError(
                "a successful Brainstorming session has no lead-accepted target"
            )
        retained_revision(state, session_id, revision)
        return prompt_handoff(state, handoff)
    return handoff
