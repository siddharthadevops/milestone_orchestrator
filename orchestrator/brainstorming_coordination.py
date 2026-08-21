"""Ordered turns, target-only accepted revisions, and revision-bound closure."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import threading
import time
import uuid

from orchestrator import brainstorming, runners

try:
    import fcntl
except ImportError:  # pragma: no cover - the production service is POSIX
    fcntl = None


class CoordinationRejected(RuntimeError):
    """A session cannot admit the requested coordination work."""


class RoundLimitReached(CoordinationRejected):
    """No participant turn remains inside the configured round bound."""


class ClosureNotEligible(CoordinationRejected):
    """The accepted discussion is not at a new complete-round boundary."""


class InvalidTargetMutation(CoordinationRejected):
    """A non-owner or incomplete turn changed the target."""


class TargetMutationCorrected(CoordinationRejected):
    """The pending action was recovered and must be attempted once more."""


class TargetMutationFailed(CoordinationRejected):
    """The corrected pending action mutated the target again and failed."""

    def __init__(self, snapshot):
        super().__init__(
            "the corrected pending worker action changed target_path again"
        )
        self.snapshot = snapshot


class TargetRecoveryError(CoordinationRejected):
    """The accepted target revision could not be re-established exactly."""


class OperationalRetryPending(CoordinationRejected):
    """A recoverable provider failure is waiting for its retry time."""

    def __init__(self, retry):
        self.retry = brainstorming._json_copy(
            retry, "operational_retry"
        )
        super().__init__(
            "recoverable participant failure; retry at %s"
            % self.retry["retry_at"]
        )


class ExternalInterventionPending(CoordinationRejected):
    """The ordered flow is waiting for a response outside worker control."""

    def __init__(self, intervention):
        self.intervention = brainstorming.validate_external_intervention(
            intervention
        )
        super().__init__(
            "waiting for external participant %s"
            % self.intervention["participant_id"]
        )


_TARGET_LOCKS = {}
_TARGET_LOCKS_GUARD = threading.Lock()
OPERATIONAL_RETRY_S = 5 * 60


def _thread_lock_for(path):
    with _TARGET_LOCKS_GUARD:
        lock = _TARGET_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _TARGET_LOCKS[path] = lock
        return lock


def _target_lock_path(store_path, target_path):
    identity = os.path.abspath(target_path).encode(
        "utf-8", errors="surrogatepass"
    )
    digest = hashlib.sha256(identity).hexdigest()
    return "%s.brainstorming-target-%s.lock" % (store_path, digest)


def _is_target_lock_path(store_path, candidate_path):
    suffix = ".lock"
    candidates = {
        os.path.abspath(candidate_path),
        os.path.realpath(candidate_path),
    }
    stores = {
        os.path.abspath(store_path),
        os.path.realpath(store_path),
    }
    for store in stores:
        prefix = store + ".brainstorming-target-"
        for candidate in candidates:
            if not candidate.startswith(prefix) or not candidate.endswith(
                suffix
            ):
                continue
            digest = candidate[len(prefix) : -len(suffix)]
            if len(digest) == 64 and all(
                character in "0123456789abcdef" for character in digest
            ):
                return True
    return False


def _reject_store_target_alias(
    store_path, target_path, transcript_path=None
):
    """Keep target recovery independent from Brainstorming's state authority."""
    store_path = os.path.abspath(store_path)
    target_path = os.path.abspath(target_path)
    if _is_target_lock_path(store_path, target_path):
        raise CoordinationRejected(
            "target_path must not use Brainstorming's target coordination "
            "lock namespace"
        )
    if brainstorming._target_overlaps_state_storage(
        store_path, target_path
    ):
        raise CoordinationRejected(
            "target_path must not alias Brainstorming's durable state store "
            "or lock"
        )
    authority_paths = [store_path, store_path + ".lock"]
    if brainstorming._target_overlaps_transcript_storage(
        store_path + ".sessions", target_path, transcript_path
    ):
        raise CoordinationRejected(
            "target_path must not overlap Brainstorming-owned transcript "
            "storage"
        )
    if transcript_path is not None:
        transcript_path = os.path.abspath(transcript_path)
        authority_paths.extend(
            (transcript_path, transcript_path + ".lock")
        )
    for authority_path in authority_paths:
        aliases_authority = (
            os.path.realpath(target_path) == os.path.realpath(authority_path)
        )
        if not aliases_authority:
            try:
                aliases_authority = os.path.samefile(
                    target_path, authority_path
                )
            except (FileNotFoundError, OSError):
                aliases_authority = False
        if aliases_authority:
            label = (
                "transcript or lock"
                if transcript_path is not None
                and authority_path.startswith(transcript_path)
                else "durable state store or lock"
            )
            raise CoordinationRejected(
                "target_path must not alias Brainstorming's %s" % label
            )


@contextlib.contextmanager
def _exclusive_target_turn(
    store_path, target_path, transcript_path=None
):
    """Serialize one target's execution, reconciliation, and state decision."""
    _reject_store_target_alias(
        store_path, target_path, transcript_path
    )
    lock_path = _target_lock_path(store_path, target_path)
    with _thread_lock_for(lock_path):
        handle = open(lock_path, "a+", encoding="utf-8")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            handle.close()


def resolve_target_path(request):
    """Resolve the target exactly as a participant's workspace-relative path."""
    checked = brainstorming.validate_request(request)
    target_path = checked["target_path"]
    if os.path.isabs(target_path):
        return os.path.abspath(target_path)
    return os.path.abspath(
        os.path.join(checked["workspace_path"], target_path)
    )


@contextlib.contextmanager
def _open_target_parent(path, expected=None):
    """Resolve stable parent links once, then pin the resulting directory."""
    path = os.path.abspath(path)
    parent, name = os.path.split(path)
    if not name:
        raise CoordinationRejected(
            "target_path must identify one artifact"
        )
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise CoordinationRejected(
            "target-only recovery requires no-follow directory access"
        )
    resolved_parent = os.path.realpath(parent)
    if expected is not None and resolved_parent != expected["path"]:
        raise CoordinationRejected(
            "target_path parent changed during its acceptance window"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = None
    try:
        descriptor = os.open(os.sep, flags)
        for component in (
            item for item in resolved_parent.split(os.sep) if item
        ):
            next_descriptor = os.open(
                component, flags, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = next_descriptor
        opened = os.fstat(descriptor)
        identity = {
            "path": resolved_parent,
            "device": opened.st_dev,
            "inode": opened.st_ino,
        }
        if expected is not None and identity != expected:
            raise CoordinationRejected(
                "target_path parent changed during its acceptance window"
            )
    except CoordinationRejected:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise CoordinationRejected(
            "target_path has an unavailable or redirected parent"
        ) from exc
    try:
        yield descriptor, name, identity
    finally:
        os.close(descriptor)


def _capture_target_at(
    parent_descriptor, name, *, require_single_link=True
):
    try:
        before = os.stat(
            name, dir_fd=parent_descriptor, follow_symlinks=False
        )
    except FileNotFoundError:
        return brainstorming.make_target_revision(False, b"", None)
    except OSError as exc:
        raise CoordinationRejected(
            "target_path could not be observed exactly"
        ) from exc

    if stat.S_ISLNK(before.st_mode):
        raise CoordinationRejected(
            "target_path must not be a symbolic link"
        )
    if not stat.S_ISREG(before.st_mode):
        raise CoordinationRejected(
            "target_path must identify one regular artifact"
        )
    if require_single_link and before.st_nlink != 1:
        raise CoordinationRejected(
            "target_path must not share a hard-linked artifact"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(
            name, flags, dir_fd=parent_descriptor
        )
        try:
            with os.fdopen(descriptor, "rb") as handle:
                content = handle.read()
                opened = os.fstat(handle.fileno())
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        after = os.stat(
            name, dir_fd=parent_descriptor, follow_symlinks=False
        )
    except CoordinationRejected:
        raise
    except OSError as exc:
        raise CoordinationRejected(
            "target_path could not be read exactly"
        ) from exc

    identity = (before.st_dev, before.st_ino)
    before_mode = stat.S_IMODE(before.st_mode)
    if (
        identity != (opened.st_dev, opened.st_ino)
        or identity != (after.st_dev, after.st_ino)
        or not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or (require_single_link and opened.st_nlink != 1)
        or (require_single_link and after.st_nlink != 1)
        or before.st_size != opened.st_size
        or opened.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before_mode != stat.S_IMODE(opened.st_mode)
        or before_mode != stat.S_IMODE(after.st_mode)
    ):
        raise CoordinationRejected(
            "target_path changed while it was being observed"
        )
    return brainstorming.make_target_revision(True, content, before_mode)


def capture_target(path):
    """Capture exact bytes or absence without following alternate path forms."""
    with _open_target_parent(path) as (parent_descriptor, name, _identity):
        return _capture_target_at(parent_descriptor, name)


def capture_materialization_source(path):
    """Capture source bytes without imposing live-target link custody."""
    with _open_target_parent(path) as (parent_descriptor, name, _identity):
        return _capture_target_at(
            parent_descriptor,
            name,
            require_single_link=False,
        )


def _capture_pinned_target(target):
    path, parent_descriptor, name, parent_identity = target
    with _open_target_parent(path, parent_identity):
        pass
    return _capture_target_at(parent_descriptor, name)


def _remove_directory_contents(descriptor):
    for child in os.listdir(descriptor):
        current = os.stat(
            child, dir_fd=descriptor, follow_symlinks=False
        )
        if stat.S_ISDIR(current.st_mode) and not stat.S_ISLNK(
            current.st_mode
        ):
            os.chmod(
                child,
                stat.S_IMODE(current.st_mode)
                | stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            child_descriptor = os.open(
                child, flags, dir_fd=descriptor
            )
            try:
                _remove_directory_contents(child_descriptor)
            finally:
                os.close(child_descriptor)
            os.rmdir(child, dir_fd=descriptor)
        else:
            os.unlink(child, dir_fd=descriptor)


def _remove_target_entry(parent_descriptor, name):
    current = os.stat(
        name, dir_fd=parent_descriptor, follow_symlinks=False
    )
    if stat.S_ISDIR(current.st_mode) and not stat.S_ISLNK(current.st_mode):
        os.chmod(
            name,
            stat.S_IMODE(current.st_mode)
            | stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        descriptor = os.open(
            name, flags, dir_fd=parent_descriptor
        )
        try:
            _remove_directory_contents(descriptor)
        finally:
            os.close(descriptor)
        os.rmdir(name, dir_fd=parent_descriptor)
    else:
        os.unlink(name, dir_fd=parent_descriptor)


def _write_target_bytes(parent_descriptor, name, content):
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(
        name, flags, 0o600, dir_fd=parent_descriptor
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def _restore_target_at(
    path,
    parent_descriptor,
    name,
    parent_identity,
    target_revision,
):
    checked = brainstorming.validate_target_revision(target_revision)
    exists, content = brainstorming.target_revision_content(checked)
    accepted_mode = brainstorming.target_revision_mode(checked)
    with _open_target_parent(path, parent_identity):
        pass
    try:
        try:
            current = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            current = None
        if not exists:
            if current is not None:
                _remove_target_entry(parent_descriptor, name)
        else:
            direct_write = (
                current is not None
                and stat.S_ISREG(current.st_mode)
                and current.st_nlink == 1
            )
            mode = (
                stat.S_IMODE(current.st_mode)
                if direct_write
                else None
            )
            if current is not None and not direct_write:
                _remove_target_entry(parent_descriptor, name)
            if direct_write:
                try:
                    _write_target_bytes(
                        parent_descriptor, name, content
                    )
                except PermissionError:
                    os.chmod(
                        name,
                        mode | stat.S_IRUSR | stat.S_IWUSR,
                        dir_fd=parent_descriptor,
                        follow_symlinks=False,
                    )
                    _write_target_bytes(
                        parent_descriptor, name, content
                    )
            else:
                _write_target_bytes(
                    parent_descriptor, name, content
                )
            os.chmod(
                name,
                accepted_mode,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        observed = _capture_target_at(parent_descriptor, name)
    except TargetRecoveryError:
        raise
    except CoordinationRejected as exc:
        raise TargetRecoveryError(
            "the target parent is unavailable or redirected; recovery "
            "will not modify another path"
        ) from exc
    except OSError as exc:
        raise TargetRecoveryError(
            "the accepted target revision could not be restored"
        ) from exc

    if observed != checked:
        raise TargetRecoveryError(
            "target_path does not match its accepted revision after recovery"
        )


def restore_target(path, target_revision):
    """Restore only ``path`` to one retained Brainstorming revision."""
    try:
        with _open_target_parent(path) as (
            parent_descriptor,
            name,
            parent_identity,
        ):
            _restore_target_at(
                path,
                parent_descriptor,
                name,
                parent_identity,
                target_revision,
            )
    except TargetRecoveryError:
        raise
    except CoordinationRejected as exc:
        raise TargetRecoveryError(
            "the target parent is unavailable or redirected; recovery "
            "will not modify another path"
        ) from exc


def _execution_context_block(execution_context):
    """Render inherited project roots as role instructions, not new policy."""
    lines = [
        "",
        "Brainstorming role and target boundary (binding):",
        "workspace_path is orientation, not a limit on legitimate reads. "
        "For this Brainstorming session, modify no caller path other than "
        "target_path.",
    ]
    if isinstance(execution_context, dict):
        primary = execution_context.get("primary")
        if isinstance(primary, dict) and isinstance(
            primary.get("path"), str
        ):
            lines.append(
                "- PRIMARY ROOT %s — caller context. It does not constrain "
                "target_path location; do not edit it except when target_path "
                "itself is inside it and your role permits that target edit."
                % primary["path"]
            )
        additional = execution_context.get("additional") or []
        for root in additional:
            if isinstance(root, dict) and isinstance(root.get("path"), str):
                lines.append(
                    "- ADDITIONAL ROOT %s — read-only evidence; never edit it."
                    % root["path"]
                )
    lines.append("")
    return "\n".join(lines)


BRAINSTORMING_COMMON_CHECK = """\
Use judgment proportionate to the decision: identify real affected parties,
realistic harm and reversibility, reuse existing mechanisms, and prefer the
cheapest sufficient result. Escalate only on concrete evidence.
"""


AI_AMENDMENT_INTRO = """\
The project was amended in earlier discussions with the decisions below. They
are prior project decisions, not unquestionable assumptions. If the current
discussion provides solid evidence that one is mistaken, incomplete, or
disproportionate, identify it and propose the necessary correction.
"""


DANTE_SCENE_INTRO = """\
This scene belongs to a contemporary novel built from a real case so that the
conversation remains consistent and believable.

Dante is a human project lead listening to two AI agents discuss a real issue.
He has no position to defend and proposes no solution. His job is to notice
drift and ask the few simple, awkward questions that the agents are skipping:
what the project actually intends, who is really affected, what observable
damage exists, whether ordinary permitted operation already includes the
claimed state, and whether the proposed machinery is proportionate.

He understands the project deeply but speaks plainly. He asks only questions
that could change the decision, never a checklist, speech, ruling, or analysis.
"""


DANTE_AMENDMENT_INTRO = """\
Dante amended the project in earlier discussions with the decisions below.
They reflect the judgment he reached at the time, but he does not need to
defend them. An amendment is neither sacred nor infallible. If the current
discussion gives him a solid reason, Dante may question, revise, or reject it.
"""


DANTE_MANDATORY_LINE = (
    "MANDATORY: DANTE MUST SOUND LIKE A REAL HUMAN ASKING NATURAL, DIRECT "
    "QUESTIONS. HE MUST NOT TAKE A POSITION OR PROPOSE A SOLUTION."
)


def _resolved_target_path(workspace_path, value):
    if os.path.isabs(value):
        return os.path.abspath(value)
    return os.path.abspath(os.path.join(workspace_path, value))


def _prompt_amendments(state):
    """Project the generic prior-decision list into concise prompt text."""
    amendments = state["request"]["context"].get("amendments")
    if not isinstance(amendments, list):
        return []
    projected = []
    for amendment in amendments:
        if not isinstance(amendment, dict):
            continue
        text = amendment.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        item = {"text": text.strip()}
        amendment_id = amendment.get("id")
        if isinstance(amendment_id, str) and amendment_id.strip():
            item["id"] = amendment_id.strip()
        projected.append(item)
    return projected


def _amendments_block(state, introduction):
    amendments = _prompt_amendments(state)
    if not amendments:
        return ""
    lines = [introduction.rstrip(), "", "Project amendments:"]
    for amendment in amendments:
        label = (
            "%s: " % amendment["id"] if amendment.get("id") else ""
        )
        lines.append("- %s%s" % (label, amendment["text"]))
    return "\n".join(lines) + "\n\n"


def _prompt_sources(state):
    request = state["request"]
    workspace = os.path.abspath(request["workspace_path"])
    target = _resolved_target_path(workspace, request["target_path"])
    references = request["context"].get("references", [])
    lines = [
        "Sources:",
        "- Brainstorming chat: %s" % state["transcript_ref"],
        "- Target document: %s" % target,
        "- Working directory: %s" % workspace,
    ]
    if references:
        lines.append("- Goal and reference documents:")
        lines.extend("  - %s" % reference for reference in references)
    return "\n".join(lines)


def _common_prompt_intro(state, action):
    return """\
You are taking part in a live, bounded brainstorming conversation.

The Brainstorming chat is the shared record. Read it from beginning to end,
inspect the target and referenced documents as needed, and {action}.

{sources}

{amendments}{common_check}
""".format(
        sources=_prompt_sources(state),
        amendments=_amendments_block(state, AI_AMENDMENT_INTRO),
        common_check=BRAINSTORMING_COMMON_CHECK.rstrip(),
        action=action,
    )


def build_turn_prompt(
    state,
    participant,
    round_number,
    target_revision,
    execution_context=None,
):
    """Compose the product-neutral view for one persisted participant turn."""
    checked = brainstorming.validate_session_state(state)
    checked_participant = brainstorming._validate_participant(
        participant, "participant"
    )
    if checked_participant["delivery"] != "llm":
        raise brainstorming.ContractError(
            "ordinary turn prompts are only for llm delivery"
        )
    target_revision = brainstorming.validate_target_revision(target_revision)
    target_presence = "present" if target_revision["exists"] else "absent"
    accepted_revision = checked["accepted_target_revision"]
    if accepted_revision is None:
        revision_label = "not yet accepted"
        authority_label = "unaccepted recovery baseline"
    else:
        revision_label = accepted_revision
        authority_label = "accepted revision"
    if checked_participant["role"] == "initial_position":
        ownership = (
            "You are the Initial Position. Present the best current answer to "
            "the request; the request is not evidence that any suggested "
            "direction is right. You may edit only the target document during "
            "this turn. Treat your earlier position as revisable: answer "
            "Dante's questions and the contrary criticism, and change course "
            "when they expose a real defect."
        )
    elif checked_participant["role"] == "contrary_position":
        ownership = (
            "You are the Contrary Position. Do not edit the target document. "
            "Try to disprove the current position. Make every material premise, "
            "causal link, claimed consequence, necessity, and remedy earn its "
            "place with concrete evidence. Do not concede merely because a "
            "claim sounds plausible, but do not invent disagreement after the "
            "issue is resolved. Attack the weakest inferential link: existence "
            "or possibility alone does not prove action, harm, or a guarantee "
            "violation, and operator-configured behavior is ordinary operation "
            "unless governing material says otherwise. Consider Dante's "
            "questions."
        )
    else:
        ownership = (
            "You are the common-sense participant. Do not edit the target "
            "document, take a position, or propose a solution. Ask only the "
            "few anti-drift questions the two positions still need to answer. "
            "Use the same natural language as the Brainstorming request and "
            "discussion; if they are mixed, follow the request."
        )

    return """\
{intro}

Turn:
- participant_id: {participant_id}
- role: {role}
- round: {round_number}
- workspace_path: {workspace_path}
- target_path: {target_path}
- accepted Brainstorming target revision: {accepted_revision}
- current target authority: {authority_label} {target_revision}
- current target state: {target_presence}

{execution_context}
The target on disk matches that Brainstorming authority. The recovery baseline
is not accepted work; only a completed Initial Position turn creates the first
accepted revision. {ownership}

Return exactly one JSON object with kind "discussion_turn" and one non-empty
Markdown field. Do not add target content, votes, results, or control metadata
to that envelope. Keep the intervention concise, preferably under 3,000
characters, but never omit material meaning merely to fit.
""".format(
        intro=_common_prompt_intro(
            checked, "continue naturally with your next turn"
        ).rstrip(),
        participant_id=checked_participant["id"],
        role=checked_participant["role"],
        round_number=round_number,
        workspace_path=checked["request"]["workspace_path"],
        target_path=checked["request"]["target_path"],
        accepted_revision=revision_label,
        authority_label=authority_label,
        target_revision=target_revision["revision"],
        target_presence=target_presence,
        execution_context=_execution_context_block(execution_context),
        ownership=ownership,
    )


def validate_closure_proposal_envelope(envelope):
    """Validate the Initial Position's proposed agreement."""
    brainstorming._model_keys(
        envelope,
        ("kind", "propose", "closing_summary"),
        (),
        "closure_proposal",
    )
    if envelope["kind"] != "closure_proposal":
        raise brainstorming.ContractError(
            "closure_proposal.kind must be closure_proposal"
        )
    if type(envelope["propose"]) is not bool:
        raise brainstorming.ContractError(
            "closure_proposal.propose must be a boolean"
        )
    summary = brainstorming.validate_model_closing_summary(
        envelope["closing_summary"]
    )
    if "open_questions" not in summary:
        raise brainstorming.ContractError(
            "closure_proposal.closing_summary requires open_questions"
        )
    return {
        "kind": "closure_proposal",
        "propose": envelope["propose"],
        "closing_summary": summary,
    }


def validate_closure_vote_envelope(envelope):
    """Validate one Contrary Position vote; extra rationale is dropped, not
    a rejected ballot."""
    brainstorming._model_keys(
        envelope, ("kind", "vote"), (), "closure_vote"
    )
    if envelope["kind"] != "closure_vote":
        raise brainstorming.ContractError(
            "closure_vote.kind must be closure_vote"
        )
    if envelope["vote"] not in ("accept", "object"):
        raise brainstorming.ContractError(
            "closure_vote.vote must be accept or object"
        )
    return brainstorming._json_copy(envelope, "closure_vote")


def _closure_common_prompt(state, target_revision, execution_context=None):
    checked = brainstorming.validate_session_state(state)
    revision = brainstorming.validate_target_revision(target_revision)
    return """\
{intro}

- closure after completed round: {round_number}
- workspace_path: {workspace_path}
- target_path: {target_path}
- accepted Brainstorming target revision: {target_revision}

{execution_context}
The target has been reconciled to that exact accepted revision. Do not edit,
delete, recreate, rename, or replace target_path during closure. Closure control
does not create a target revision or consume a discussion turn.
""".format(
        intro=_common_prompt_intro(
            checked, "use them for this closure decision"
        ).rstrip(),
        round_number=checked["rounds_used"],
        workspace_path=checked["request"]["workspace_path"],
        target_path=checked["request"]["target_path"],
        target_revision=revision["revision"],
        execution_context=_execution_context_block(execution_context),
    )


def build_closure_proposal_prompt(
    state, target_revision, execution_context=None
):
    """Ask the Initial Position whether to propose one exact agreement."""
    return _closure_common_prompt(
        state, target_revision, execution_context
    ) + """\

You are the Initial Position. Decide whether to propose closure against this
exact revision.
Your proposal is your `accept` vote. Supply the complete plain-language closing
account that will be used only if this attempt terminalizes. Its reason must
stand alone as the final agreement: cover the whole accepted outcome, every
material target change or deliberate non-change, and anything intentionally
left open. Do not summarize only the last objection. The coordinator will add a
plain human-labeled record for every later `object` vote so the closing cannot
contradict the accepted ballot. Return exactly one JSON object with:
- kind: "closure_proposal"
- propose: true or false
- closing_summary: exactly reason, unresolved_objections, affected_parties,
  damage_altitude, proportionality, escalation_evidence, and open_questions

The four prose fields are non-empty strings. Use unresolved_objections only for
unresolved objections, otherwise return an empty list. Open_questions is a list
of questions deliberately deferred by agreement, otherwise an empty list.
Escalation_evidence is null or a non-empty string. Add no other fields.
"""


def build_closure_vote_prompt(
    state,
    participant,
    target_revision,
    closing_summary,
    execution_context=None,
):
    """Ask one Contrary Position to vote on the exact proposal."""
    checked_participant = brainstorming._validate_participant(
        participant, "participant"
    )
    if checked_participant["delivery"] != "llm":
        raise brainstorming.ContractError(
            "ordinary closure prompts are only for llm delivery"
        )
    summary = brainstorming.validate_closing_summary_shape(closing_summary)
    return _closure_common_prompt(
        state, target_revision, execution_context
    ) + """\

The Initial Position has proposed this final agreement against the exact target
revision:
{closing_summary}

You are Contrary Position {participant_id}. Accept only if both the target and this
complete final agreement accurately represent the discussion, including what
changed, what deliberately stayed unchanged, and what remains open. Return
exactly one JSON object with kind "closure_vote" and vote equal to "accept" or
"object". Add no rationale or other fields to the control envelope, and do not
edit target_path.
""".format(
        participant_id=checked_participant["id"],
        closing_summary=json.dumps(
            summary, ensure_ascii=False, sort_keys=True, indent=2
        ),
    )


def build_external_narrator_prompt(state, intervention):
    """Render Dante's direct-turn prompt from the external contract."""
    checked = brainstorming.validate_session_state(state)
    pending = brainstorming.validate_external_intervention(intervention)
    expected_input = {
        "request": checked["request"]["request"],
        "context": checked["request"]["context"],
        "workspace_path": checked["request"]["workspace_path"],
        "target_path": checked["request"]["target_path"],
        "transcript_ref": checked["transcript_ref"],
    }
    if not brainstorming._same_json_value(
        pending["input"], expected_input
    ):
        raise brainstorming.ContractError(
            "external intervention input no longer matches the session"
        )
    if pending["action_kind"] == "discussion_turn":
        return """\
{scene}

{sources}

{amendments}Read the Brainstorming chat from beginning to end. Ask Dante's next
few direct anti-drift questions. Use the same natural language as the
Brainstorming request and discussion; if they are mixed, follow the request.
Do not edit files, take a position, propose a solution, summarize the
discussion, or answer your own questions. If no material question remains,
say only the natural equivalent of `No further questions.` in that language.

Return exactly one JSON object with kind "discussion_turn" and a non-empty
"markdown" field with Dante's single spoken intervention in that same
language. Add no other fields. Keep it concise, preferably under 3,000
characters, but never omit a material question merely to fit.

{mandatory}""".format(
            scene=DANTE_SCENE_INTRO.rstrip(),
            sources=_prompt_sources(checked),
            amendments=_amendments_block(
                checked, DANTE_AMENDMENT_INTRO
            ),
            mandatory=DANTE_MANDATORY_LINE,
        )
    raise brainstorming.ContractError("Dante does not vote on closure")


class BrainstormingCoordinator:
    """Coordinate ordered turns and revision-bound closure."""

    def __init__(self, store, participant_execution):
        self.store = store
        self.participant_execution = participant_execution

    @staticmethod
    def _require_running(snapshot):
        if snapshot is None:
            raise brainstorming.SessionNotFound("brainstorming session")
        if snapshot.state["status"] != "running":
            raise CoordinationRejected(
                "ordered turns require a running session"
            )
        return snapshot

    def _authority_record(self, session_id, snapshot):
        revision = snapshot.state["accepted_target_revision"]
        if revision is None:
            revision = snapshot.state["recovery_baseline_revision"]
        return self.store.read_target_revision(
            session_id, revision
        )

    @staticmethod
    def _external_input(state):
        request = state["request"]
        return {
            "request": request["request"],
            "context": request["context"],
            "workspace_path": request["workspace_path"],
            "target_path": request["target_path"],
            "transcript_ref": state["transcript_ref"],
        }

    def _external_intervention(
        self,
        state,
        participant,
        action_kind,
        round_number,
        closure_context=None,
    ):
        intervention = {
            "token": str(uuid.uuid4()),
            "participant_id": participant["id"],
            "action_kind": action_kind,
            "completed_turn_count": len(state["completed_turns"]),
            "round": round_number,
            "target_revision": state["accepted_target_revision"],
            "input": self._external_input(state),
            "created_at": time.time(),
            "provider_attempt": 0,
            "provider_quiescent": True,
            "response": None,
        }
        if closure_context is not None:
            intervention["closure_context"] = closure_context
        return intervention

    def _publish_external(
        self,
        session_id,
        state,
        participant,
        action_kind,
        round_number,
        closure_context=None,
    ):
        intervention = self._external_intervention(
            state,
            participant,
            action_kind,
            round_number,
            closure_context=closure_context,
        )
        return self.store.publish_external_intervention(
            session_id, intervention
        )

    @staticmethod
    def _require_external_match(
        pending,
        state,
        participant,
        action_kind,
        round_number,
        closure_context=None,
    ):
        expected = {
            "participant_id": participant["id"],
            "action_kind": action_kind,
            "completed_turn_count": len(state["completed_turns"]),
            "round": round_number,
            "target_revision": state["accepted_target_revision"],
        }
        if any(pending[key] != value for key, value in expected.items()):
            raise CoordinationRejected(
                "pending external intervention does not match the next action"
            )
        if closure_context is not None and not brainstorming._same_json_value(
            pending.get("closure_context"), closure_context
        ):
            raise CoordinationRejected(
                "pending external closure context changed"
            )

    def _external_response_locked(
        self,
        session_id,
        target,
        state,
        participant,
        action_kind,
        round_number,
        accepted_target,
        closure_context=None,
    ):
        pending = self.store.read_external_intervention(session_id)
        if pending is None:
            pending = self._publish_external(
                session_id,
                state,
                participant,
                action_kind,
                round_number,
                closure_context=closure_context,
            )
        try:
            self._require_external_match(
                pending,
                state,
                participant,
                action_kind,
                round_number,
                closure_context=closure_context,
            )
        except CoordinationRejected:
            if (
                action_kind != "closure_vote"
                or pending["action_kind"] != "closure_vote"
                or pending["response"] is None
                or closure_context is None
            ):
                raise
            following = self._external_intervention(
                state,
                participant,
                action_kind,
                round_number,
                closure_context=closure_context,
            )
            pending = self.store.advance_external_intervention(
                session_id, pending["token"], following
            )
        if pending["response"] is None:
            raise ExternalInterventionPending(pending)
        if _capture_pinned_target(target) != accepted_target:
            _restore_target_at(*target, accepted_target)
        return pending, pending["response"]["payload"]

    def _clear_consumed_external_turn(self, session_id, state):
        pending = self.store.read_external_intervention(session_id)
        if (
            pending is None
            or pending["action_kind"] != "discussion_turn"
            or pending["response"] is None
        ):
            return False
        turns = state["completed_turns"]
        index = pending["completed_turn_count"]
        if index >= len(turns):
            return False
        accepted = turns[index]
        payload = pending["response"]["payload"]
        if (
            index + 1 != len(turns)
            or accepted["participant_id"] != pending["participant_id"]
            or accepted["round"] != pending["round"]
            or accepted["markdown"] != payload["markdown"]
        ):
            raise CoordinationRejected(
                "external intervention conflicts with accepted discussion"
            )
        self.store.finish_external_intervention(
            session_id, pending["token"]
        )
        return True

    @staticmethod
    def _closure_context_captures_external(action_context, pending):
        if (
            not isinstance(action_context, dict)
            or action_context.get("stage") != "vote"
            or pending["action_kind"] != "closure_vote"
            or pending["response"] is None
        ):
            return False
        if not brainstorming._same_json_value(
            action_context.get("closing_summary"),
            pending["closure_context"]["closing_summary"],
        ):
            return False
        votes = action_context.get("votes_by_id")
        if not isinstance(votes, dict):
            return False
        if any(
            votes.get(item["participant_id"]) != item["vote"]
            for item in pending["closure_context"]["votes"]
        ):
            return False
        return votes.get(pending["participant_id"]) == pending["response"][
            "payload"
        ]["vote"]

    def _clear_consumed_external_closure(self, session_id, state):
        pending = self.store.read_external_intervention(session_id)
        if (
            pending is None
            or pending["action_kind"] != "closure_vote"
            or pending["response"] is None
        ):
            return False
        ballot = next(
            (
                event["fact"]
                for event in state["transcript_events"]
                if event["kind"] == "closure_ballot"
                and event["fact"]["after_completed_rounds"]
                == pending["round"]
                and event["fact"]["target_revision"]
                == pending["target_revision"]
            ),
            None,
        )
        if ballot is None:
            return False
        vote = next(
            (
                item["vote"]
                for item in ballot["votes"]
                if item["participant_id"] == pending["participant_id"]
            ),
            None,
        )
        if vote != pending["response"]["payload"]["vote"]:
            raise CoordinationRejected(
                "external closure response conflicts with its accepted ballot"
            )
        self.store.finish_external_intervention(
            session_id, pending["token"]
        )
        return True

    def reconcile_external_intervention(self, session_id):
        """Retire a response only after durable discussion or ballot capture."""
        snapshot = self.store.read(session_id)
        if snapshot is None:
            raise brainstorming.SessionNotFound(session_id)
        if self._clear_consumed_external_turn(session_id, snapshot.state):
            return self.store.read(session_id)
        if self._clear_consumed_external_closure(session_id, snapshot.state):
            return self.store.read(session_id)
        return snapshot

    @staticmethod
    def _attempt_target_parent(attempt):
        if attempt is None:
            return None
        parent = attempt.get("target_parent")
        if parent is None:
            raise TargetRecoveryError(
                "the prior turn attempt has no pinned target parent; "
                "recovery will not follow the current path"
            )
        return parent

    def _reconcile_snapshot(self, session_id, snapshot, target):
        snapshot = self._require_running(snapshot)
        accepted = self._authority_record(session_id, snapshot)
        try:
            observed = _capture_pinned_target(target)
        except CoordinationRejected:
            _restore_target_at(*target, accepted)
            return snapshot
        if observed != accepted:
            _restore_target_at(*target, accepted)
        return snapshot

    def _resolve_prior_attempt(
        self, session_id, snapshot, target, cancel_operational_retry=False
    ):
        attempt = self.store.read_turn_attempt(session_id)
        if attempt is None:
            return self._reconcile_snapshot(session_id, snapshot, target)
        projection = brainstorming.coordination_projection(snapshot.state)
        if projection is None:
            raise CoordinationRejected(
                "an active turn exists without accepted coordination state"
            )
        completed = len(projection["completed_turns"])
        expected = attempt["completed_turn_count"]
        if completed < expected or completed > expected + 1:
            raise CoordinationRejected(
                "active turn control state conflicts with accepted progress"
            )
        if completed == expected and not attempt["quiescent"]:
            raise CoordinationRejected(
                "the prior participant worker's quiescence is unknown"
            )
        if completed == expected and attempt.get(
            "target_mutation_failure_pending", False
        ):
            authority = self._authority_record(session_id, snapshot)
            try:
                _restore_target_at(*target, authority)
            except BaseException as recovery_error:
                raise TargetRecoveryError(
                    "the repeated invalid target mutation could not be "
                    "recovered"
                ) from recovery_error
            failed = self._terminal_target_mutation_failure(
                session_id, attempt["token"]
            )
            raise TargetMutationFailed(failed)
        if completed == expected and attempt.get("operational_retry"):
            retry = attempt["operational_retry"]
            if not cancel_operational_retry and time.time() < retry["retry_at"]:
                raise OperationalRetryPending(retry)
            reconciled = self._reconcile_snapshot(
                session_id, snapshot, target
            )
            if cancel_operational_retry:
                self.store.finish_turn_attempt(
                    session_id, attempt["token"]
                )
            return reconciled
        if completed == expected and attempt.get("retry_pending", False):
            return self._reconcile_snapshot(session_id, snapshot, target)
        if completed == expected:
            authority = self._authority_record(session_id, snapshot)
            try:
                observed = _capture_pinned_target(target)
            except CoordinationRejected:
                observed = None
            if observed != authority:
                repeated = self.store.mark_turn_attempt_target_mutation(
                    session_id, attempt["token"]
                )
                try:
                    _restore_target_at(*target, authority)
                except BaseException as recovery_error:
                    raise TargetRecoveryError(
                        "an incomplete worker's target mutation could not be "
                        "recovered"
                    ) from recovery_error
                if repeated:
                    failed = self._terminal_target_mutation_failure(
                        session_id, attempt["token"]
                    )
                    raise TargetMutationFailed(failed)
                return self._require_running(self.store.read(session_id))
            if attempt.get("target_mutation_corrections", 0) == 1:
                self.store.preserve_corrected_turn_retry(
                    session_id, attempt["token"]
                )
                return snapshot
        reconciled = self._reconcile_snapshot(session_id, snapshot, target)
        self.store.finish_turn_attempt(session_id, attempt["token"])
        return reconciled

    def _prepare_locked(
        self, session_id, target, cancel_operational_retry=False
    ):
        """Initialize target versioning and reconcile while holding its lock."""
        while True:
            snapshot = self._require_running(self.store.read(session_id))
            if brainstorming.coordination_projection(snapshot.state) is not None:
                return self._resolve_prior_attempt(
                    session_id,
                    snapshot,
                    target,
                    cancel_operational_retry=cancel_operational_retry,
                )
            if self.store.read_turn_attempt(session_id) is not None:
                raise CoordinationRejected(
                    "an active turn exists before coordination initialization"
                )
            starting_target = _capture_pinned_target(target)
            try:
                initialized = self.store.initialize_coordination(
                    session_id, snapshot.revision, starting_target
                )
            except brainstorming.RevisionConflict:
                continue
            return self._reconcile_snapshot(
                session_id, initialized, target
            )

    def prepare(self, session_id, cancel_operational_retry=False):
        """Initialize target versioning and reconcile before any turn."""
        snapshot = self._require_running(self.store.read(session_id))
        path = resolve_target_path(snapshot.state["request"])
        try:
            with _exclusive_target_turn(
                self.store.path,
                path,
                self.store.transcript_ref(session_id),
            ):
                attempt = self.store.read_turn_attempt(session_id)
                expected = self._attempt_target_parent(attempt)
                with _open_target_parent(path, expected) as (
                    parent_descriptor,
                    name,
                    parent_identity,
                ):
                    target = (
                        path,
                        parent_descriptor,
                        name,
                        parent_identity,
                    )
                    return self._prepare_locked(
                        session_id,
                        target,
                        cancel_operational_retry=cancel_operational_retry,
                    )
        except TargetMutationFailed as failed:
            return failed.snapshot

    def _recover_latest(self, session_id, target):
        latest = self.store.read(session_id)
        if (
            latest is None
            or brainstorming.coordination_projection(latest.state) is None
        ):
            return
        accepted = self._authority_record(session_id, latest)
        _restore_target_at(*target, accepted)

    def _record_supervision_stop(self, session_id, plain):
        """Append one human-safe reason when supervision stops discussion."""
        while True:
            snapshot = self._require_running(self.store.read(session_id))
            projection = brainstorming.coordination_projection(snapshot.state)
            if projection is None:
                raise CoordinationRejected(
                    "participant supervision has not started"
                )
            try:
                return self.store.record_material_interruption(
                    session_id,
                    snapshot.revision,
                    {
                        "after_completed_turns": len(
                            projection["completed_turns"]
                        ),
                        "plain": plain,
                    },
                )
            except brainstorming.RevisionConflict:
                continue

    def _recover_rejected(self, session_id, target, token, cause):
        target_mutated = isinstance(cause, InvalidTargetMutation)
        if not target_mutated and isinstance(cause, Exception):
            attempt = self.store.read_turn_attempt(session_id)
            if (
                attempt is not None
                and attempt["token"] == token
                and attempt["quiescent"]
            ):
                authority = self._authority_record(
                    session_id,
                    self._require_running(self.store.read(session_id)),
                )
                try:
                    observed = _capture_pinned_target(target)
                except CoordinationRejected:
                    observed = None
                target_mutated = observed != authority
        classification = getattr(
            cause, "brainstorming_failure_classification", None
        )
        if (
            isinstance(classification, dict)
            and classification.get("error_type")
            in brainstorming.RECOVERABLE_FAILURE_TYPES
        ):
            try:
                self._recover_latest(session_id, target)
                retry_at = time.time() + OPERATIONAL_RETRY_S
                pending = self.store.schedule_operational_retry(
                    session_id, token, classification, retry_at
                )
            except BaseException as recovery_error:
                self._record_supervision_stop(
                    session_id,
                    "The discussion stopped because its recoverable worker "
                    "failure could not be scheduled safely.",
                )
                raise TargetRecoveryError(
                    "recoverable participant failure could not be retained"
                ) from recovery_error
            raise OperationalRetryPending(pending["operational_retry"])
        if target_mutated:
            repeated = self.store.mark_turn_attempt_target_mutation(
                session_id, token
            )
            try:
                self._recover_latest(session_id, target)
            except BaseException as recovery_error:
                self._record_supervision_stop(
                    session_id,
                    "The discussion stopped because the target could not be "
                    "restored to the last accepted Brainstorming revision.",
                )
                raise TargetRecoveryError(
                    "invalid target mutation could not be reconciled"
                ) from recovery_error
            if repeated:
                failed = self._terminal_target_mutation_failure(
                    session_id, token
                )
                raise TargetMutationFailed(failed)
            raise TargetMutationCorrected(
                "target_path was recovered; retry the same pending action"
            )
        try:
            self._recover_latest(session_id, target)
            self.store.finish_turn_attempt(session_id, token)
        except BaseException as recovery_error:
            self._record_supervision_stop(
                session_id,
                "The discussion stopped because the target could not be "
                "restored to the last accepted Brainstorming revision.",
            )
            raise TargetRecoveryError(
                "rejected work could not be reconciled to durable state"
            ) from recovery_error
        if cause is not None:
            raise cause

    def _terminal_target_mutation_failure(self, session_id, token):
        reason = (
            "The same pending worker action changed the target again after "
            "its one correction."
        )
        snapshot = self._require_running(self.store.read(session_id))
        projection = brainstorming.coordination_projection(snapshot.state)
        result = self._closure_result(snapshot.state, "failure", reason)
        summary = {
            "reason": reason,
            "unresolved_objections": [
                "The repeated invalid target mutation prevented this worker "
                "action from being accepted."
            ],
            "affected_parties": (
                "The caller and participants waiting for a coherent target "
                "are affected."
            ),
            "damage_altitude": (
                "The bounded discussion failed without promoting the rejected "
                "worker outcome."
            ),
            "proportionality": (
                "Ending after one corrected retry preserves the last accepted "
                "Brainstorming target authority."
            ),
            "escalation_evidence": (
                "The same pending action mutated target_path twice."
            ),
        }
        failed = self.store.close_with_interruption(
            session_id,
            snapshot.revision,
            {
                "after_completed_turns": len(
                    projection["completed_turns"]
                ),
                "plain": reason,
            },
            result,
            summary,
        )
        self.store.finish_turn_attempt(session_id, token)
        return failed

    def _begin_or_retry_attempt(self, session_id, attempt):
        prior = self.store.read_turn_attempt(session_id)
        if prior is not None and prior.get("operational_retry"):
            return self.store.restart_operational_turn_attempt(
                session_id, attempt
            )
        if prior is not None and prior.get("retry_pending", False):
            return self.store.restart_turn_attempt(session_id, attempt)
        return self.store.begin_turn_attempt(session_id, attempt)

    def _before_envelope_repair(
        self, session_id, token, target, accepted_target
    ):
        """Keep one envelope repair attached to the same pending action."""
        self._require_closure_target(target, accepted_target)
        if not self.store.mark_turn_attempt_envelope_repair(session_id, token):
            raise runners.WorkerProtocolError(
                "the pending worker action already used its one "
                "discussion-envelope repair"
            )

    @staticmethod
    def _closure_fingerprint(state):
        """Ignore only write-once provider bindings during one closure attempt."""
        return {
            "status": state["status"],
            "history": state["history"],
            "transcript_events": state["transcript_events"],
            "coordination": brainstorming.coordination_projection(state),
        }

    def _closure_exchange(
        self,
        session_id,
        execution_context,
        target,
        baseline_state,
        participant,
        prompt,
        validator,
        accepted_target,
        action_context,
    ):
        while True:
            try:
                return self._closure_exchange_once(
                    session_id,
                    execution_context,
                    target,
                    baseline_state,
                    participant,
                    prompt,
                    validator,
                    accepted_target,
                    action_context,
                )
            except TargetMutationCorrected:
                continue

    def _closure_exchange_once(
        self,
        session_id,
        execution_context,
        target,
        baseline_state,
        participant,
        prompt,
        validator,
        accepted_target,
        action_context,
    ):
        if participant["delivery"] == "external":
            votes_by_id = action_context.get("votes_by_id") or {}
            closure_context = {
                "closing_summary": action_context["closing_summary"],
                "votes": [
                    {
                        "participant_id": item["id"],
                        "vote": votes_by_id[item["id"]],
                    }
                    for item in baseline_state["run_config"]["participants"]
                    if item["id"] in votes_by_id
                ],
            }
            pending, payload = self._external_response_locked(
                session_id,
                target,
                baseline_state,
                participant,
                "closure_vote",
                baseline_state["rounds_used"],
                accepted_target,
                closure_context=closure_context,
            )
            current = self._require_running(self.store.read(session_id))
            if not brainstorming._same_json_value(
                self._closure_fingerprint(current.state),
                self._closure_fingerprint(baseline_state),
            ):
                raise brainstorming.RevisionConflict(current)
            return {"kind": "closure_vote", "vote": payload["vote"]}
        attempt = {
            "token": str(uuid.uuid4()),
            "participant_id": participant["id"],
            "completed_turn_count": len(baseline_state["completed_turns"]),
            "target_revision": baseline_state["accepted_target_revision"],
            "quiescent": False,
            "target_parent": target[3],
            "kind": "closure",
            "action_context": action_context,
        }
        attempt = self._begin_or_retry_attempt(session_id, attempt)
        exchange = getattr(
            self.participant_execution, "exchange_control_quiescent", None
        )
        if not callable(exchange):
            self._recover_rejected(
                session_id,
                target,
                attempt["token"],
                CoordinationRejected(
                    "participant execution exposes no quiescent control exchange"
                ),
            )
        try:
            envelope, _runner_result = exchange(
                session_id,
                participant["id"],
                prompt,
                execution_context,
                validator,
                before_repair=lambda: self._before_envelope_repair(
                    session_id,
                    attempt["token"],
                    target,
                    accepted_target,
                ),
            )
        except BaseException as exc:
            if getattr(exc, "worker_quiescent", None) is not True:
                self._record_supervision_stop(
                    session_id,
                    "The discussion stopped because closure work could not be "
                    "confirmed as finished.",
                )
                raise
            try:
                # A refusal before the provider started leaves no call to
                # account for; the preservation below then writes nothing.
                self.store.mark_turn_attempt_quiescent(
                    session_id,
                    attempt["token"],
                    dispatch_refused=getattr(
                        exc, "brainstorming_dispatch_refused", False
                    ) is True,
                )
            except BaseException as mark_error:
                self._recover_rejected(
                    session_id, target, attempt["token"], mark_error
                )
            try:
                self.store.preserve_turn_attempt_accounting(
                    session_id, attempt["token"]
                )
            except BaseException:
                self._record_supervision_stop(
                    session_id,
                    "The discussion stopped because participant activity "
                    "could not be preserved.",
                )
                raise
            self._recover_rejected(
                session_id, target, attempt["token"], exc
            )
        try:
            self.store.mark_turn_attempt_quiescent(
                session_id, attempt["token"]
            )
            current = self._require_running(self.store.read(session_id))
            if not brainstorming._same_json_value(
                self._closure_fingerprint(current.state),
                self._closure_fingerprint(baseline_state),
            ):
                raise brainstorming.RevisionConflict(current)
            if (
                _capture_pinned_target(target) != accepted_target
                or _capture_pinned_target(target) != accepted_target
            ):
                raise InvalidTargetMutation(
                    "target_path changed during closure control"
                )
        except BaseException as exc:
            self._recover_rejected(
                session_id, target, attempt["token"], exc
            )
        self.store.finish_turn_attempt(session_id, attempt["token"])
        return envelope

    def run_next_turn(self, session_id, execution_context):
        """Run and atomically accept exactly the next ordered turn."""
        while True:
            claimed = self._require_running(self.store.read(session_id))
            path = resolve_target_path(claimed.state["request"])
            try:
                with _exclusive_target_turn(
                    self.store.path,
                    path,
                    self.store.transcript_ref(session_id),
                ):
                    current = self._require_running(
                        self.store.read(session_id)
                    )
                    if not brainstorming._same_json_value(
                        brainstorming.coordination_projection(claimed.state),
                        brainstorming.coordination_projection(current.state),
                    ):
                        raise brainstorming.RevisionConflict(current)
                    prior_attempt = self.store.read_turn_attempt(session_id)
                    expected = self._attempt_target_parent(prior_attempt)
                    with _open_target_parent(path, expected) as (
                        parent_descriptor,
                        name,
                        parent_identity,
                    ):
                        target = (
                            path,
                            parent_descriptor,
                            name,
                            parent_identity,
                        )
                        return self._run_next_turn_locked(
                            session_id, execution_context, target
                        )
            except TargetMutationCorrected:
                continue
            except TargetMutationFailed as failed:
                return failed.snapshot

    def _run_next_turn_locked(self, session_id, execution_context, target):
        starting = self._prepare_locked(session_id, target)
        state = starting.state
        if (
            self._clear_consumed_external_turn(session_id, state)
            or self._clear_consumed_external_closure(session_id, state)
        ):
            starting = self._require_running(self.store.read(session_id))
            state = starting.state
        participants = state["run_config"]["participants"]
        turn_index = len(state["completed_turns"])
        if turn_index >= state["request"]["max_rounds"] * len(participants):
            raise RoundLimitReached(
                "the configured round limit is exhausted"
            )
        participant = participants[turn_index % len(participants)]
        round_number = turn_index // len(participants) + 1
        accepted_target = self._authority_record(session_id, starting)
        if participant["delivery"] == "external":
            pending, payload = self._external_response_locked(
                session_id,
                target,
                state,
                participant,
                "discussion_turn",
                round_number,
                accepted_target,
            )
            current = self._require_running(self.store.read(session_id))
            if not brainstorming._same_json_value(
                brainstorming.coordination_projection(starting.state),
                brainstorming.coordination_projection(current.state),
            ):
                raise brainstorming.RevisionConflict(current)
            target_record = (
                None
                if state["accepted_target_revision"] is None
                else accepted_target
            )
            accepted = self.store.record_completed_turn(
                session_id,
                current.revision,
                participant["id"],
                payload["markdown"],
                target_record,
                publish=False,
            )
            self._reconcile_snapshot(session_id, accepted, target)
            self.store.finish_external_intervention(
                session_id, pending["token"]
            )
            return self.store.reconcile_transcript(session_id)
        prompt = build_turn_prompt(
            state,
            participant,
            round_number,
            accepted_target,
            execution_context,
        )
        attempt = {
            "token": str(uuid.uuid4()),
            "participant_id": participant["id"],
            "completed_turn_count": turn_index,
            "target_revision": state["accepted_target_revision"],
            "quiescent": False,
            "target_parent": target[3],
        }
        attempt = self._begin_or_retry_attempt(session_id, attempt)

        exchange = getattr(
            self.participant_execution, "exchange_quiescent", None
        )
        if not callable(exchange):
            self._recover_rejected(
                session_id,
                target,
                attempt["token"],
                CoordinationRejected(
                    "participant execution exposes no quiescent exchange"
                ),
            )
        try:
            envelope, _runner_result = exchange(
                session_id,
                participant["id"],
                prompt,
                execution_context,
                before_repair=lambda: self._before_envelope_repair(
                    session_id,
                    attempt["token"],
                    target,
                    accepted_target,
                ),
            )
        except BaseException as exc:
            if getattr(exc, "worker_quiescent", None) is not True:
                # An ordinary provider or evidence-check failure is not proof
                # that its supervised worker can no longer mutate the target.
                # Keep the durable attempt active and refuse every retry.
                self._record_supervision_stop(
                    session_id,
                    "The discussion stopped because the participant's work "
                    "could not be confirmed as finished.",
                )
                raise
            try:
                # A refusal before the provider started leaves no call to
                # account for; the preservation below then writes nothing.
                self.store.mark_turn_attempt_quiescent(
                    session_id,
                    attempt["token"],
                    dispatch_refused=getattr(
                        exc, "brainstorming_dispatch_refused", False
                    ) is True,
                )
            except BaseException as mark_error:
                self._recover_rejected(
                    session_id, target, attempt["token"], mark_error
                )
            try:
                self.store.preserve_turn_attempt_accounting(
                    session_id, attempt["token"]
                )
            except BaseException:
                self._record_supervision_stop(
                    session_id,
                    "The discussion stopped because participant activity "
                    "could not be preserved.",
                )
                raise
            self._recover_rejected(
                session_id, target, attempt["token"], exc
            )
        try:
            self.store.mark_turn_attempt_quiescent(
                session_id, attempt["token"]
            )
        except BaseException as exc:
            self._recover_rejected(
                session_id, target, attempt["token"], exc
            )

        try:
            current = self.store.read(session_id)
            if current is None or current.state["status"] != "running":
                raise CoordinationRejected(
                    "session lifecycle changed during the participant turn"
                )
            if not brainstorming._same_json_value(
                brainstorming.coordination_projection(starting.state),
                brainstorming.coordination_projection(current.state),
            ):
                raise brainstorming.RevisionConflict(current)

            observed_target = _capture_pinned_target(target)
            changed = observed_target != accepted_target
            if participant["role"] != "initial_position" and changed:
                raise InvalidTargetMutation(
                    "a non-owning participant changed target_path"
                )
            target_record = (
                observed_target
                if participant["role"] == "initial_position"
                else (
                    None
                    if state["accepted_target_revision"] is None
                    else accepted_target
                )
            )

            authority_after = (
                accepted_target if target_record is None else target_record
            )
            if _capture_pinned_target(target) != authority_after:
                raise InvalidTargetMutation(
                    "target_path changed outside the completed exchange"
                )
            accepted = self.store.record_completed_turn(
                session_id,
                current.revision,
                participant["id"],
                envelope["markdown"],
                target_record,
                publish=False,
            )
        except BaseException as exc:
            self._recover_rejected(
                session_id, target, attempt["token"], exc
            )

        self._reconcile_snapshot(session_id, accepted, target)
        self.store.finish_turn_attempt(session_id, attempt["token"])
        return self.store.reconcile_transcript(session_id)

    @staticmethod
    def _closure_result(state, outcome, reason=None):
        result = {
            "outcome": outcome,
            "target_ref": state["request"]["target_path"],
            "transcript_ref": state["transcript_ref"],
            "rounds_used": state["rounds_used"],
        }
        if outcome == "failure":
            result["reason"] = brainstorming._text(
                reason, "failure reason"
            )
        return result

    @staticmethod
    def _require_closure_target(target, accepted_target):
        if (
            _capture_pinned_target(target) != accepted_target
            or _capture_pinned_target(target) != accepted_target
        ):
            raise InvalidTargetMutation(
                "target_path changed during closure acceptance"
            )

    def run_closure(self, session_id, execution_context):
        """Collect one revision-bound ballot or continue/fail at the boundary."""
        claimed = self._require_running(self.store.read(session_id))
        path = resolve_target_path(claimed.state["request"])
        try:
            with _exclusive_target_turn(
                self.store.path,
                path,
                self.store.transcript_ref(session_id),
            ):
                current = self._require_running(self.store.read(session_id))
                if current.revision != claimed.revision:
                    raise brainstorming.RevisionConflict(current)
                prior_attempt = self.store.read_turn_attempt(session_id)
                expected = self._attempt_target_parent(prior_attempt)
                with _open_target_parent(path, expected) as (
                    parent_descriptor,
                    name,
                    parent_identity,
                ):
                    target = (
                        path,
                        parent_descriptor,
                        name,
                        parent_identity,
                    )
                    return self._run_closure_locked(
                        session_id, execution_context, target
                    )
        except TargetMutationFailed as failed:
            return failed.snapshot

    def _run_closure_locked(self, session_id, execution_context, target):
        starting = self._prepare_locked(session_id, target)
        state = starting.state
        participants = state["run_config"]["participants"]
        participant_count = len(participants)
        if (
            state["rounds_used"] <= 0
            or len(state["completed_turns"])
            != state["rounds_used"] * participant_count
        ):
            raise ClosureNotEligible(
                "closure requires a complete discussion round"
            )
        if any(
            event["kind"] == "closure_ballot"
            and event["fact"]["after_completed_rounds"]
            == state["rounds_used"]
            for event in state["transcript_events"]
        ):
            raise ClosureNotEligible(
                "another complete discussion round is required before a ballot"
            )

        if state["accepted_target_revision"] is None:
            raise ClosureNotEligible(
                "closure requires completed Initial Position target acceptance"
            )
        accepted_target = self._authority_record(session_id, starting)
        self._require_closure_target(target, accepted_target)
        lead = next(
            participant
            for participant in participants
            if participant["role"] == "initial_position"
        )
        pending = self.store.read_turn_attempt(session_id)
        external_pending = self.store.read_external_intervention(session_id)
        if (
            external_pending is not None
            and external_pending["action_kind"] != "closure_vote"
        ):
            raise CoordinationRejected(
                "a discussion intervention remains at a closure boundary"
            )
        pending_context = (
            pending.get("action_context")
            if pending is not None
            and (
                pending.get("retry_pending", False)
                or pending.get("operational_retry") is not None
            )
            and pending.get("kind", "discussion_turn") == "closure"
            else None
        )
        resume_from_attempt = (
            external_pending is not None
            and pending is not None
            and self._closure_context_captures_external(
                pending_context, external_pending
            )
        )
        if resume_from_attempt:
            action_context = pending_context
        elif external_pending is not None:
            external_context = external_pending["closure_context"]
            action_context = {
                "stage": "vote",
                "closing_summary": external_context["closing_summary"],
                "votes_by_id": {
                    vote["participant_id"]: vote["vote"]
                    for vote in external_context["votes"]
                },
            }
        else:
            action_context = pending_context
        stage = (
            action_context.get("stage")
            if isinstance(action_context, dict)
            else None
        )
        if stage not in (None, "proposal", "vote"):
            raise CoordinationRejected(
                "the pending closure action has an unknown stage"
            )

        if stage == "vote":
            summary = brainstorming.validate_closing_summary_shape(
                action_context.get("closing_summary")
            )
            votes_by_id = action_context.get("votes_by_id")
            if not isinstance(votes_by_id, dict):
                raise CoordinationRejected(
                    "the pending closure vote has no prior vote context"
                )
            votes_by_id = dict(votes_by_id)
            if votes_by_id.get(lead["id"]) != "accept" or any(
                participant_id
                not in {item["id"] for item in participants}
                or vote not in ("accept", "object")
                for participant_id, vote in votes_by_id.items()
            ):
                raise CoordinationRejected(
                    "the pending closure vote context is invalid"
                )
            proposal = {"propose": True, "closing_summary": summary}
        else:
            proposal = self._closure_exchange(
                session_id,
                execution_context,
                target,
                state,
                lead,
                build_closure_proposal_prompt(
                    state, accepted_target, execution_context
                ),
                validate_closure_proposal_envelope,
                accepted_target,
                {"stage": "proposal"},
            )
            summary = proposal["closing_summary"]
            votes_by_id = {lead["id"]: "accept"}

        if proposal["propose"] and not accepted_target["exists"]:
            if state["rounds_used"] < state["request"]["max_rounds"]:
                return self.store.reconcile_transcript(session_id)
            self._require_closure_target(target, accepted_target)
            current = self._require_running(self.store.read(session_id))
            if not brainstorming._same_json_value(
                self._closure_fingerprint(current.state),
                self._closure_fingerprint(state),
            ):
                raise brainstorming.RevisionConflict(current)
            reason = "The requested target was not produced."
            summary = dict(summary, reason=reason)
            result = self._closure_result(
                current.state, "failure", reason
            )
            return self.store.transition(
                session_id,
                current.revision,
                "failure",
                result,
                summary,
            )

        if not proposal["propose"]:
            if state["rounds_used"] < state["request"]["max_rounds"]:
                return self.store.reconcile_transcript(session_id)
            self._require_closure_target(target, accepted_target)
            current = self._require_running(self.store.read(session_id))
            if not brainstorming._same_json_value(
                self._closure_fingerprint(current.state),
                self._closure_fingerprint(state),
            ):
                raise brainstorming.RevisionConflict(current)
            reason = (
                "Irreducible gap: the positions did not agree before the "
                "configured round limit."
            )
            summary = dict(summary, reason=reason)
            result = self._closure_result(current.state, "failure", reason)
            return self.store.transition(
                session_id,
                current.revision,
                "failure",
                result,
                summary,
            )

        pending_participant = (
            (
                pending["participant_id"]
                if resume_from_attempt
                else external_pending["participant_id"]
                if external_pending is not None
                else pending["participant_id"]
            )
            if stage == "vote"
            else None
        )
        reached_pending = pending_participant is None
        for participant in participants:
            if participant["role"] != "contrary_position":
                continue
            if not reached_pending:
                if participant["id"] != pending_participant:
                    continue
                reached_pending = True
            vote = self._closure_exchange(
                session_id,
                execution_context,
                target,
                state,
                participant,
                (
                    None
                    if participant["delivery"] == "external"
                    else build_closure_vote_prompt(
                        state,
                        participant,
                        accepted_target,
                        summary,
                        execution_context,
                    )
                ),
                validate_closure_vote_envelope,
                accepted_target,
                {
                    "stage": "vote",
                    "closing_summary": summary,
                    "votes_by_id": votes_by_id,
                },
            )
            votes_by_id[participant["id"]] = vote["vote"]
        if not reached_pending:
            raise CoordinationRejected(
                "the pending closure voter is not a Contrary Position"
            )

        voters = brainstorming.closure_voters(state["run_config"])
        votes = [
            {
                "participant_id": participant["id"],
                "vote": votes_by_id[participant["id"]],
            }
            for participant in voters
        ]
        ballot = {
            "after_completed_rounds": state["rounds_used"],
            "target_revision": state["accepted_target_revision"],
            "votes": votes,
            "approved": brainstorming.evaluate_closure(
                state["run_config"], votes
            ),
            "closing_summary": summary,
        }
        self._require_closure_target(target, accepted_target)
        current = self._require_running(self.store.read(session_id))
        if not brainstorming._same_json_value(
            self._closure_fingerprint(current.state),
            self._closure_fingerprint(state),
        ):
            raise brainstorming.RevisionConflict(current)

        if (
            not ballot["approved"]
            and state["rounds_used"] < state["request"]["max_rounds"]
        ):
            accepted = self.store.record_closure_ballot(
                session_id, current.revision, ballot
            )
            self._clear_consumed_external_closure(
                session_id, accepted.state
            )
            return self.store.reconcile_transcript(session_id)

        outcome = "success" if ballot["approved"] else "failure"
        if not ballot["approved"]:
            reason = (
                "Irreducible gap: the positions did not agree before the "
                "configured round limit."
            )
            summary = dict(summary, reason=reason)
            ballot["closing_summary"] = summary
        result = self._closure_result(
            current.state,
            outcome,
            summary["reason"] if outcome == "failure" else None,
        )
        return self.store.close_with_ballot(
            session_id,
            current.revision,
            ballot,
            result,
            summary,
        )

    def record_material_interruption(
        self, session_id, expected_revision, plain
    ):
        """Record one supervision outcome already judged material."""
        snapshot = self._require_running(self.store.read(session_id))
        if snapshot.revision != expected_revision:
            raise brainstorming.RevisionConflict(snapshot)
        projection = brainstorming.coordination_projection(snapshot.state)
        if projection is None:
            raise CoordinationRejected(
                "participant supervision has not started"
            )
        return self.store.record_material_interruption(
            session_id,
            expected_revision,
            {
                "after_completed_turns": len(
                    projection["completed_turns"]
                ),
                "plain": plain,
            },
        )
