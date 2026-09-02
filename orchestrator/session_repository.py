"""Real-repository completion boundary for milestone Brainstorming seats."""

from __future__ import annotations

import collections
import copy
import os

from . import canonical_plan, gitops
from . import state as st


class SessionRepositoryError(RuntimeError):
    """A milestone session repository boundary cannot continue."""

    call_boundary_failure = True


class ResumableRepositoryTurnError(SessionRepositoryError):
    """A rejected turn was restored and can resume with updated runtime."""


class ReadOnlyTurnInvalidated(SessionRepositoryError):
    """A read-only physical call changed governed repository state."""


RepositoryAttempt = collections.namedtuple(
    "RepositoryAttempt", ("context", "snapshot", "role")
)


def _relative_path(value, label):
    if (
        not isinstance(value, str)
        or not value.strip()
        or os.path.isabs(value)
        or os.path.normpath(value) != value
        or value in (".", "..")
        or value.startswith(".." + os.sep)
    ):
        raise SessionRepositoryError("%s must be workspace-relative" % label)
    return value


def validate_context(value):
    if not isinstance(value, dict):
        raise SessionRepositoryError(
            "milestone session repository context is invalid"
        )
    standalone = value.get("mode") == "standalone_reviewed"
    expected = (
        {"state_path", "pre_session_commit", "mode"}
        if standalone else
        {"state_path", "skeleton_path", "pre_session_commit"}
    )
    if set(value) != expected:
        raise SessionRepositoryError(
            "milestone session repository context is invalid"
        )
    state_path = value["state_path"]
    if not isinstance(state_path, str) or not os.path.isabs(state_path):
        raise SessionRepositoryError(
            "milestone session state_path must be absolute"
        )
    revision = value["pre_session_commit"]
    if (
        not isinstance(revision, str)
        or len(revision) != 40
        or any(character not in "0123456789abcdef" for character in revision)
    ):
        raise SessionRepositoryError(
            "milestone session pre_session_commit must be a full revision"
        )
    checked = {
        "state_path": state_path,
        "pre_session_commit": revision,
    }
    if standalone:
        checked["mode"] = "standalone_reviewed"
    else:
        checked["skeleton_path"] = _relative_path(
            value["skeleton_path"], "skeleton_path"
        )
    return checked


def checkpoint_context(
    workspace, state_path, skeleton_path, message, *, standalone_reviewed=False
):
    """Commit the shared workspace and return one durable session base."""
    if not isinstance(workspace, str) or not os.path.isabs(workspace):
        raise SessionRepositoryError("session workspace must be absolute")
    if not isinstance(state_path, str):
        raise SessionRepositoryError("session state_path must be text")
    gitops.commit_plain(workspace, message)
    context = {
        "state_path": os.path.abspath(state_path),
        "pre_session_commit": gitops.head_full_sha(workspace),
    }
    if standalone_reviewed:
        context["mode"] = "standalone_reviewed"
    else:
        context["skeleton_path"] = _relative_path(
            skeleton_path, "skeleton_path"
        )
    return validate_context(context)


def context_from_charge(charge):
    if not isinstance(charge, dict) or "repository" not in charge:
        raise SessionRepositoryError(
            "milestone session charge has no repository boundary"
        )
    return validate_context(charge["repository"])


def context_from_state(state):
    try:
        charge = state["request"]["context"]["source_payload"][
            "session_charge"
        ]
    except (KeyError, TypeError):
        return None
    if "repository" not in charge:
        return None
    return context_from_charge(charge)


def sealed_range(session_state):
    """Return the committed A..B delivery of one successful repository seal."""
    context = context_from_state(session_state)
    if context is None:
        raise SessionRepositoryError(
            "session has no repository delivery boundary"
        )
    if session_state.get("status") != "success":
        raise SessionRepositoryError(
            "repository delivery requires a successful session"
        )
    accepted = session_state.get("accepted_target_revision")
    if (
        not isinstance(accepted, str)
        or len(accepted) != 40
        or any(character not in "0123456789abcdef" for character in accepted)
    ):
        raise SessionRepositoryError(
            "repository seal has no accepted full revision"
        )
    workspace = session_state["request"]["workspace_path"]
    if gitops.head_full_sha(workspace) != accepted:
        raise SessionRepositoryError(
            "repository HEAD no longer equals the sealed revision"
        )
    return {
        "source_base_revision": context["pre_session_commit"],
        "accepted_revision": accepted,
    }


def begin_attempt(session_state, charge, role):
    """Capture one proportional boundary immediately before seat dispatch."""
    context = context_from_charge(charge)
    workspace = session_state["request"]["workspace_path"]
    milestone_state = st.load(context["state_path"])
    if milestone_state.get("workspace") != workspace:
        raise SessionRepositoryError(
            "session and milestone repository workspaces do not match"
        )
    if context.get("mode") == "standalone_reviewed":
        if not milestone_state.get("reviewed_task"):
            raise SessionRepositoryError(
                "standalone reviewed repository context has no reviewed task"
            )
        return RepositoryAttempt(
            context,
            {
                "workspace": workspace,
                "anchor": None,
                "repository": canonical_plan._repository_snapshot(workspace),
            },
            role,
        )
    try:
        snapshot = canonical_plan.begin_author_call(
            milestone_state, context["skeleton_path"]
        )
    except (canonical_plan.CanonicalPlanError, gitops.GitError) as exc:
        raise SessionRepositoryError(
            "session repository attempt could not start: %s" % exc
        ) from exc
    return RepositoryAttempt(context, snapshot, role)


def complete_attempt(attempt, participant_id, round_number):
    """Complete one physical call and persist any changed plan projection."""
    context = attempt.context
    try:
        with st.exclusive_mutation(context["state_path"], wait=True):
            milestone_state = st.load(context["state_path"])
            if context.get("mode") == "standalone_reviewed":
                if not milestone_state.get("reviewed_task"):
                    raise SessionRepositoryError(
                        "standalone reviewed repository context lost its task"
                    )
                workspace = milestone_state["workspace"]
                repository = attempt.snapshot["repository"]
                if attempt.role == "initial_position":
                    if (
                        gitops.head_symbolic_ref(workspace)
                        != repository["sym"]
                        or gitops.head_full_sha(workspace)
                        != repository["head"]
                    ):
                        canonical_plan._reject_author_call(
                            attempt.snapshot,
                            SessionRepositoryError(
                                "an editing seat changed HEAD before driver commit"
                            ),
                        )
                    try:
                        committed = gitops.commit_plain(
                            workspace,
                            "Brainstorming round %s — %s"
                            % (round_number, participant_id),
                        ) is not None
                    except gitops.GitError as exc:
                        canonical_plan._reject_author_call(
                            attempt.snapshot, exc
                        )
                    return {
                        "accept_reply": True,
                        "committed": committed,
                        "plan_changed": False,
                        "revision": gitops.head_full_sha(workspace),
                        "anchor": None,
                    }
                unchanged = canonical_plan._repository_matches_snapshot(
                    attempt.snapshot
                )
                if not unchanged:
                    canonical_plan.restore_author_call(attempt.snapshot)
                return {
                    "accept_reply": unchanged,
                    "committed": False,
                    "plan_changed": False,
                    "revision": repository["head"],
                    "anchor": None,
                }
            current_anchor = milestone_state["milestone"].get(
                canonical_plan.ANCHOR_KEY
            )
            if current_anchor != attempt.snapshot["anchor"]:
                raise SessionRepositoryError(
                    "canonical-plan authority changed during a seat attempt"
                )
            message = "Brainstorming round %s — %s" % (
                round_number, participant_id
            )
            if attempt.role == "initial_position":
                outcome = canonical_plan.complete_repository_editor_call(
                    milestone_state, attempt.snapshot, message=message
                )
            else:
                outcome = canonical_plan.complete_repository_read_only_call(
                    milestone_state, attempt.snapshot, message=message
                )
            st.save(context["state_path"], milestone_state)
            return copy.deepcopy(outcome)
    except SessionRepositoryError:
        raise
    except canonical_plan.CanonicalPlanRejectedRestored as exc:
        raise ResumableRepositoryTurnError(
            "session repository attempt was rejected and restored: %s" % exc
        ) from exc
    except (canonical_plan.CanonicalPlanError, gitops.GitError, OSError) as exc:
        raise SessionRepositoryError(
            "session repository attempt failed: %s" % exc
        ) from exc


def live_target_authority(session_state, charge):
    context = context_from_charge(charge)
    workspace = session_state["request"]["workspace_path"]
    target = session_state["request"]["target_path"]
    target_path = target if os.path.isabs(target) else os.path.join(
        workspace, target
    )
    return (
        "repository HEAD %s" % gitops.head_full_sha(workspace),
        "present" if os.path.isfile(target_path) else "absent",
        context,
    )
