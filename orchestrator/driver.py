"""Deterministic orchestrator driver.

The control loop the canon used to delegate to an LLM orchestrator, now
hardcoded: read state -> decide the single legal next action -> execute it
(usually one full-permission CLI worker call) -> append immutable records ->
save -> repeat. Content judgment stays with the LLM workers; sequencing,
bookkeeping, and gate enforcement live here, in tested code.

Usage:
  python3 -m orchestrator.driver init --goal "..." --workspace DIR [--config F]
  python3 -m orchestrator.driver status [--json]
  python3 -m orchestrator.driver next
  python3 -m orchestrator.driver step
  python3 -m orchestrator.driver run [--max-steps N]
  python3 -m orchestrator.driver serve [--port 8765]
"""

import argparse
import contextlib
import copy
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX: flock degrades to the
    fcntl = None     # staleness check in step(); documented in the README

from . import contracts, errclass, gitops, interpreter, kvstore, ledgers
from . import projects, prompts, runners, verifiers, workareas
from . import state as st

DEFAULT_CONFIG = {
    "families_order": ["codex", "claude"],
    "fix_family": None,  # default: first family in families_order
    "commands": {
        "codex": [
            "codex",
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "-m",
            "{model}",
            "-c",
            "model_reasoning_effort={effort}",
            "--output-last-message",
            "{output_file}",
        ],
        "claude": [
            "claude",
            "-p",
            "--model",
            "{model}",
            "--effort",
            "{effort}",
            "--permission-mode",
            "bypassPermissions",
        ],
    },
    # Family-level model/effort used when an act does not override them.
    # {model}/{effort} placeholders in the command template are filled per
    # call; templates without placeholders (codex: its model lives in its
    # own CLI config) ignore overrides.
    # Verified against the installed CLIs (2026-07-09): claude accepts
    # explicit ids (claude-fable-5 / claude-opus-4-8 / claude-sonnet-5)
    # and efforts low|medium|high|xhigh|max; codex models come from its
    # live catalog (gpt-5.6-sol / gpt-5.6-terra / gpt-5.6-luna) with
    # reasoning efforts low|medium|high|xhigh|max set via
    # `-c model_reasoning_effort=...` (bare value: failed TOML parse
    # falls back to the literal string, per codex --help).
    # claude workers run with background workflows force-disabled
    # (runners.WORKFLOW_DISABLED_ENV): the async workflow model is
    # incompatible with the one-shot call contract.
    "model_defaults": {
        "claude": {"model": "claude-opus-4-8", "effort": "max"},
        "codex": {"model": "gpt-5.6-sol", "effort": "xhigh"},
    },
    # No timeouts by default: worker calls run as long as the work needs
    # (an implement call may legitimately run hours of test suites). A
    # fixed cap killed a real 15-minute-plus implement mid-flight; a hung
    # CLI is the operator's Stop button (a liveness mechanism — e.g.
    # periodic workspace-diff progress checks — is future work). Operators
    # can still set per-family caps here when a run warrants them.
    "timeouts": {},
    "verification": [],
    # Unlimited by default, same philosophy as worker timeouts: a real
    # suite may take 15+ minutes and a gate that kills it converts honest
    # work into failures. Set a number (seconds) to cap it per run.
    "verification_timeout": None,
    "max_rounds_per_family": 12,
    "max_seal_attempts": 8,
    "max_verify_fix_attempts": 4,
    "seal_concurrent": False,
    # First seal attempt runs a single half (the last reviewer's redundant
    # re-review is dropped); any finding reopens to the full double seal.
    # Off for pure-state/CLI runs; the service forces it on. See
    # _seal_families for why a1 is the only byte-identical, empirically-quiet
    # case. Parallelization is decided by half count, not this flag: >1 half
    # runs concurrently (when seal_concurrent), a lone a1 half runs directly.
    "single_seal_first_attempt": False,
    # Gate commits + the reviewed-point index discipline (see gitops.py).
    # Off by default for pure-state CLI runs; the demo config and the
    # service panel (service.create_run forces it on unless the operator
    # explicitly disables it) enable it.
    "git": {"enabled": False},
    # Per-act family policy: a family name ("codex"/"claude"), "self"
    # (same family as the act's origin), or "opposite". Delta review is not
    # independently configurable: it always uses the fixer's family and that
    # family's Review profile.
    # Acts may also be objects: {"agent": "claude", "model": "sonnet",
    # "effort": "high"} — who leads drafting ("drafter": skeleton + slice
    # notes), implementation ("implementer") and fixes ("fixer"), and with
    # which model/effort. `review_codex` / `review_claude` tune each fixed
    # review family independently without changing family rotation; they
    # apply to whole-artifact rounds, delta reviews, and seal halves. Absent drafter /
    # implementer fall back to fix_family (legacy behavior). The operator
    # can hot-edit all of this mid-run via acts.json; the driver re-reads it
    # before every act resolution.
    "acts": {
        "fixer": "codex",
        # Once one fix chain has produced enough dirty delta reviews,
        # use a deliberately stronger, independently configurable fixer.
        # Frozen pre-feature configs fall back to this exact profile too;
        # acts.json can still replace it mid-run.
        "convergence_fixer": {
            "agent": "codex",
            "model": "gpt-5.6-sol",
            "effort": "max",
        },
        "consultation": "opposite",
        # Who RATES findings for debt deferral: "opposite" (the
        # pre-reform doctrine) or a fixed family (operator
        # 2026-07-09: an 8-minute opposite-family rating of a
        # 4-minute review's findings is upside down; a fixed fast
        # rater is still a fresh stateless look).
        "reclassifier": "opposite",
    },
    # The fixer AFTER this many dirty delta reviews in the same active fix
    # chain uses convergence_fixer. The count is derived from append-only
    # history, so stopping/resuming a run cannot reset the escalation.
    "convergence_fixer_after_deltas": 10,
    # A delta stops being meaningfully incremental after enough cumulative
    # fixes.  After this many fixes in one episode, amend the pending diff
    # without fabricating a clean delta result and return exactly where a
    # real clean delta would return.  In review rounds this preserves the
    # active family, which then reviews the whole amended commit again.
    "delta_full_review_after_fixes": 5,
    # Fixer+delta iterations allowed per fix episode before failing. A
    # deliberate resume grants a fresh budget (state.resume_run resets the
    # counter), so this is a soft ceiling, not a dead end.
    "max_fix_loops": 20,
    # Back-edge budget (reform decision 13): how many times a downstream
    # builder may reopen an upstream unit for repair before the driver
    # stops for the operator (the same gap bouncing = a real stall, not
    # convergence). Amnesty on resume, like the other convergence caps.
    "max_gap_repairs": 3,
    # Rated DOC-debt deferral. Eligible doc findings (P3 in legacy, P2/P3 in
    # a reform profile), whether raised in rounds or seals, are rated
    # independently. Findings below the threshold become tracked debt; only
    # retained findings enter a fix cycle. Implementation and delta findings
    # always enter the normal fix/reject flow. A refused verdict or failed
    # rating retains that finding for the fixer.
    "p3_reclassify_debt": True,
    # Deferral threshold over the reclassifier's drift-risk rating
    # (low|medium|high|xhigh): an eligible finding defers at/below this.
    # The worker only RATES; this config makes the decision — set per
    # project by the operator's cost-of-being-wrong: storage/contract
    # work (Life/Spanner) -> "low"; UI shell work (chat components) ->
    # "medium". high/xhigh are never sensible thresholds.
    "p3_defer_max_risk": "low",
    # Reform runs: a goal LONGER than this (chars) is not inlined into
    # the skeleton-phase prompts — it rides as the generated goal.md
    # ledger and the prompt orders a full read. Short goals (the common
    # panel-typed case) stay inline: zero indirection. Instructions must
    # dominate a prompt, and a FILE survives the worker's own context
    # compaction where inline prose does not.
    "goal_inline_max": 8000,
    # Infra-failure handling (errclass): short in-place retries for
    # network/busy before a typed failure, and the opposite-family LLM
    # classifier fallback for noisy failure output. The service guard
    # auto-resumes typed failures at their resume_at; login/unknown
    # always wait for the operator.
    "infra_retry_backoff_s": [10, 30],
    "error_classifier": True,
    # Where the milestone's documents live inside the workspace: worker
    # artifacts (skeleton.md, slices/) and driver-generated ledgers
    # (README.md record, review-log.md, adjudications.md, closures/).
    # {slug} resolves from the run name at init. The parent directory
    # gains a machine-maintained milestone index (README.md marker
    # block). Set to "docs" for the legacy flat layout.
    "docs_dir": "implementation/milestones/{slug}",
    # Extra directory names excluded from workspace snapshots, on top of
    # runners.SNAPSHOT_EXCLUDE_DIRS (runtime dirs + common Python tool
    # caches). Add tool caches your verification suite writes so read-only
    # seal halves that run it are not falsely invalidated. With git
    # enabled the same names are also git-ignored in the workspace repo
    # (gitops.ignore_lines), so cache writes never enter micro-review
    # diffs or gate commits.
    "snapshot_exclude_dirs": [],
}


def merge_config(config, override):
    """Merge a user override into a config dict, in place: one level deep —
    dict values update key-wise, everything else replaces. The single
    source of truth for config merge semantics; both the CLI (load_config)
    and the service panel (service.create_run) go through here, so the two
    entry points can never drift."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def load_config(path=None):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            user = json.load(fh)
        merge_config(cfg, user)
    return cfg


# ---------------------------------------------------------------------------
# Actions


class Action(object):
    def __init__(self, type_, **params):
        self.type = type_
        self.params = params

    def __repr__(self):
        if self.params:
            inner = ", ".join("%s=%r" % kv for kv in sorted(self.params.items()))
            return "%s(%s)" % (self.type, inner)
        return self.type


A_DRAFT = "draft"
A_VERIFY = "verify"
A_REVIEW_ROUND = "review_round"
A_FIX = "fix_findings"
A_DELTA_REVIEW = "delta_review"
A_SEAL_ATTEMPT = "seal_attempt"
A_DONE = "done"
A_FAILED = "failed"


def decide(state):
    """Pure decision function: the single legal next action for a state."""
    if state["failure"] is not None or state["milestone"]["status"] == st.M_FAILED:
        return Action(A_FAILED, reason=(state["failure"] or {}).get("reason"))
    if state["milestone"]["status"] == st.M_CLOSED:
        return Action(A_DONE)
    unit = st.current_unit(state)
    if unit is None:
        return Action(A_DONE)  # run() closes the milestone
    status = unit["status"]
    if status == st.U_PENDING:
        return Action(A_DRAFT, unit=st.unit_key(unit))
    if status in (st.U_PRE_REVIEW_VERIFY, st.U_PRE_SEAL_VERIFY):
        return Action(A_VERIFY, unit=st.unit_key(unit), stage=status)
    if status == st.U_ROUNDS:
        # The stage interpreter chooses the review-rounds loop from the
        # run's governing profile. Phase 2 interprets only
        # family_until_clean — the canonical flow, and the answer for every
        # profile-less run — so this branch is byte-identical to the
        # pre-reform driver for those runs; other loop kinds are rejected
        # loudly until their phase lands.
        loop = interpreter.rounds_loop(state)
        if loop != interpreter.FAMILY_UNTIL_CLEAN:
            raise st.IllegalTransition(
                "rounds loop %r is not interpreted yet (later phase)" % loop
            )
        family = st.current_family(state, unit)
        return Action(A_REVIEW_ROUND, unit=st.unit_key(unit), family=family)
    if status == st.U_FIXING:
        return Action(A_FIX, unit=st.unit_key(unit))
    if status == st.U_DELTA_REVIEW:
        return Action(A_DELTA_REVIEW, unit=st.unit_key(unit))
    if status == st.U_SEALING:
        return Action(A_SEAL_ATTEMPT, unit=st.unit_key(unit))
    raise st.IllegalTransition("no action for unit status %r" % status)


# ---------------------------------------------------------------------------
# Driver


class ConcurrentRunError(RuntimeError):
    """Another driver invocation is active on the same state (the advisory
    lock is held) or advanced it on disk since this driver loaded it. Raised
    BEFORE any side-effectful worker call is made."""


class _SealHalfFailure(RuntimeError):
    """Internal: a seal half failed (runner/protocol error or a blocked
    worker). Deliberately mutates no state so it is safe to raise from
    concurrent seal worker threads; the caller decides how to record it.
    Carries the raw output texts so the MAIN thread can classify the
    failure type (the classifier must never run inside half threads)."""

    def __init__(self, message, raw_texts=None, family=None,
                 protocol_raw_paths=None, protocol_label=None):
        RuntimeError.__init__(self, message)
        self.raw_texts = list(raw_texts or [])
        self.family = family
        # Set only for a protocol (double contract violation) failure:
        # the saved raw paths + label the MAIN thread turns into the
        # fatal worker_malformed event (never appended from half threads).
        self.protocol_raw_paths = list(protocol_raw_paths or [])
        self.protocol_label = protocol_label


class _StandingLawError(RuntimeError):
    """Internal: a project-bound run's standing law (the policy store or
    the work-area meta family) could not be read or validated for a worker
    call. Routed into a recorded run failure — never a silent skip (a run
    proceeding without its standing safeguards is the incident this
    machinery exists to prevent), never a worker repair (the fault is the
    operator's store, not the worker's output)."""


class _GapRouteError(RuntimeError):
    """A gap report named a target that is not routable from the reporting
    unit's position (the §8 target vocabulary is closed). Surfaces as an
    operator-gated run failure — the worker misused the gap contract."""


class Driver(object):
    def __init__(self, state_path, runner=None):
        self.state_path = state_path
        self.state = st.load(state_path)
        # The governing profile's dials merge over the run config here
        # (spec §5). Profile-less runs and the dial-less `legacy` profile
        # get the raw config unchanged, so they stay bit-identical; a
        # `strict`/`light` run reads its own thresholds through the same
        # self.config every existing read-site already uses.
        self.config = interpreter.effective_config(self.state)
        # Fail loudly at startup if an embedded profile snapshot is
        # inconsistent (content hash vs recorded profile_ref hash). No-op
        # for profile-less runs and ref-only labels.
        interpreter.verify_embedded(self.state)
        self.workspace = self.state["workspace"]
        self.runner = runner or runners.SubprocessRunner(
            self.config["commands"], self.config.get("timeouts", {})
        )
        if gitops.enabled(self.config):
            try:
                gitops.ensure_repo(
                    self.workspace,
                    extra_ignore_dirs=self.config.get("snapshot_exclude_dirs"),
                )
            except gitops.GitError as exc:
                # A driver that cannot keep its gate ledger must not run.
                # Idempotent across operator retries: an already-recorded
                # failure is not overwritten and the ledger gains no
                # duplicate run_failed events.
                if self.state["failure"] is None:
                    st.fail_run(self.state, "git unavailable: %s" % exc)
                    self._save()
        self._consume_stale_marker()

    # -- helpers ----------------------------------------------------------

    def _save(self):
        st.save(self.state_path, self.state)

    def _snapshot(self):
        """(mode, entries) content snapshot for tamper checks.

        With git enabled the tamper universe is what the repository can
        see (tracked + untracked non-ignored): a report-only reviewer
        that runs the project's build/tests is not invalidated by
        .gitignore'd artifact churn (_build, deps, caches). If git cannot
        list, the raw walk is used and the mode says so — _snapshot_diff
        refuses to compare universes of different modes, so a mid-call
        git breakage (e.g. a worker damaging .git) yields one honest
        invalidation instead of a bogus everything-changed file list."""
        paths = None
        mode = "walk"
        if gitops.enabled(self.config):
            try:
                paths = gitops.snapshot_paths(self.workspace)
                mode = "git"
            except gitops.GitError:
                paths = None
        entries = runners.snapshot_workspace(
            self.workspace,
            extra_exclude=self.config.get("snapshot_exclude_dirs"),
            paths=paths,
        )
        return mode, entries

    @staticmethod
    def _snapshot_diff(before, after):
        """Changed paths between two _snapshot() results; a mode mismatch
        is itself evidence (the git universe appeared/vanished mid-call)."""
        before_mode, before_entries = before
        after_mode, after_entries = after
        if before_mode != after_mode:
            return [
                "(tamper universe changed mid-call: %s -> %s snapshot)"
                % (before_mode, after_mode)
            ]
        return runners.snapshot_changes(before_entries, after_entries)

    @contextlib.contextmanager
    def _exclusive(self):
        """Advisory inter-process lock on <state>.lock for one step. Two
        concurrent invocations on the same state would each run
        side-effectful worker calls; without this, the divergence would be
        detected only afterwards, at save time, as HistoryRewriteError."""
        if fcntl is None:
            yield
            return
        lock_path = self.state_path + ".lock"
        os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
        fh = open(lock_path, "a+")
        try:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ConcurrentRunError(
                    "another orchestrator invocation is active on %s "
                    "(advisory lock %s is held)" % (self.state_path, lock_path)
                )
            yield
        finally:
            fh.close()  # closing the descriptor releases the flock

    def _assert_not_stale(self):
        """Refuse to act on in-memory state that another invocation has
        advanced on disk — before any worker call, not after it."""
        if not os.path.exists(self.state_path):
            return
        disk = st.load(self.state_path)
        if disk.get("events") != self.state.get("events"):
            raise ConcurrentRunError(
                "state file %s changed on disk since this driver loaded it "
                "(another invocation ran); start a new driver to continue"
                % self.state_path
            )

    def _fix_family(self):
        return self.config.get("fix_family") or self.config["families_order"][0]

    def _opposite(self, family):
        for fam in self.config["families_order"]:
            if fam != family:
                return fam
        return family

    def _opposite_cmd(self, family):
        return self.config["commands"].get(self._opposite(family), [])

    def _runtime_dir(self):
        # All runtime bookkeeping lives beside the state file: for a
        # per-milestone run that is <milestone>/.run/, for a legacy run
        # <workspace>/.orchestrator/. Deriving from the state path keeps
        # both layouts working with identical code.
        return os.path.dirname(self.state_path)

    def _raw_dir(self):
        path = os.path.join(self._runtime_dir(), "raw")
        os.makedirs(path, exist_ok=True)
        return path

    def _save_raw(self, name, text):
        path = os.path.join(self._raw_dir(), name + ".txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text or "")
        return os.path.relpath(path, self.workspace)

    def _unit_desc(self, unit):
        if unit["kind"] == st.UNIT_SKELETON:
            return "the milestone skeleton"
        title = ""
        for sl in self.state["milestone"]["slices"]:
            if sl["id"] == unit["slice_id"]:
                title = sl["title"]
                break  # ids are unique (contract) and first match wins,
                       # consistent with _slice_info
        if unit["kind"] == st.UNIT_SLICE_DOC:
            return "the slice %d note (%s)" % (unit["slice_id"], title)
        return "the slice %d implementation (%s)" % (unit["slice_id"], title)

    def _artifact(self, unit):
        return unit["artifact"] or "(workspace)"

    def _verification_commands(self, unit):
        """Gate commands for a unit: explicit config verification wins;
        a fixer-supplied suite correction can replace a stale explicit
        gate; otherwise the suite command the implementer discovered —
        applied to implementation units only (doc artifacts cannot break
        a test suite, and a discovered suite may cost many minutes per
        run)."""
        configured = self.config.get("verification") or []
        corrected = self._corrected_suite_command()
        if corrected:
            return [corrected]
        if configured:
            return list(configured)
        discovered = self.state.get("suite_command")
        if discovered and unit["kind"] == st.UNIT_SLICE_IMPL:
            return [discovered]
        return []

    def _corrected_suite_command(self):
        """A fix_findings output with suite_command is allowed to correct
        a wrong verification gate. Without this, stale explicit config keeps
        winning and the same suite-command finding is reborn."""
        discovered = self.state.get("suite_command")
        configured = self.config.get("verification") or []
        if (
            not discovered
            or len(configured) != 1
            or configured == [discovered]
        ):
            return None
        for unit in self.state.get("units", []):
            for round_info in unit.get("rounds", []):
                if round_info.get("kind") != contracts.KIND_FIX_FINDINGS:
                    continue
                result = round_info.get("result") or {}
                if result.get("suite_command") != discovered:
                    continue
                if any(
                    f.get("disposition") == "fixed"
                    for f in result.get("findings", [])
                ):
                    return discovered
        return None

    def _verified_suite(self, unit):
        """The gate command string reviewers may rely on, or None. Unit
        status flow guarantees rounds/sealing are only reachable through
        a passing verification gate, so a non-empty command here means
        the gate genuinely ran it green."""
        cmds = self._verification_commands(unit)
        return " && ".join(cmds) if cmds else None

    def _governing(self, unit):
        """The sealed document the unit's artifact answers to (the
        reviewer's explicit standard): the skeleton for a slice note, the
        slice note for an implementation, nothing for the skeleton."""
        if unit["kind"] == st.UNIT_SLICE_DOC:
            return self._skeleton_artifact()
        if unit["kind"] == st.UNIT_SLICE_IMPL:
            return self._slice_note_artifact(unit["slice_id"])
        return None

    def _save_protocol_raws(self, raw_name, exc):
        """Persist the raw texts of a protocol-violating call (original and
        repair retry) so the operator can inspect what the model actually
        said; state.failure keeps only the truncated error strings.
        Returns the saved workspace-relative paths."""
        paths = []
        for i, text in enumerate(getattr(exc, "raw_texts", []) or [], 1):
            paths.append(
                self._save_raw("%s-protoerr%d" % (raw_name, i), text)
            )
        return paths

    def _worker_event_unit(self):
        """Owning unit for worker incidents recorded outside unit records."""
        unit = st.current_unit(self.state)
        return st.unit_key(unit) if unit is not None else None

    def _record_fatal_malformed(self, raw_name, kind, family, exc,
                                raw_paths):
        """The RED chip: ANY failed LLM call — a double contract
        violation, a crashed/timed-out/non-zero CLI, quota — lands in
        the incident trail (operator decision 2026-07-09). The event
        carries whatever raw texts were captured (both attempts for a
        protocol failure; often none for a spawn failure — the error
        text still tells). A worker that honestly returns `blocked` is
        NOT an LLM failure and records nothing here."""
        raw_paths = list(raw_paths or [])
        st.append_event(
            self.state,
            "worker_malformed",
            unit=self._worker_event_unit(),
            label=raw_name,
            kind=kind,
            family=family,
            fatal=True,
            error=str(exc)[:300],
            duration_s=None,
            raw_path=(raw_paths or [None])[0],
            raw_path2=(raw_paths[1] if len(raw_paths or []) > 1 else None),
        )

    def _emit_seal_protocol_event(self, exc):
        """Main-thread emission of a seal half's fatal double violation
        (the half thread saved the raws and stashed their paths on the
        exception; events never leave half threads)."""
        if not getattr(exc, "protocol_label", None):
            return  # a blocked worker / standing-law fault: not an LLM failure
        paths = getattr(exc, "protocol_raw_paths", None) or []
        st.append_event(
            self.state,
            "worker_malformed",
            unit=self._worker_event_unit(),
            label=exc.protocol_label,
            kind=contracts.KIND_SEAL_HALF,
            family=exc.family,
            fatal=True,
            error=str(exc)[:300],
            duration_s=None,
            raw_path=paths[0] if paths else None,
            raw_path2=paths[1] if len(paths) > 1 else None,
        )

    def _consume_stale_marker(self):
        """A driver that died mid-call (Stop, crash, SIGKILL) leaves its
        in-flight marker behind. On startup, use it to repair what the
        death may have dirtied — without ever destroying legitimate work:

        - killed EDIT call with zero completed fixes in the episode, or a
          killed call in a clean-tree phase (rounds/sealing): the
          pre-call worktree was exactly HEAD, so restore_clean is safe;
        - killed fixer mid-loop (legitimate prior fix work is mixed with
          the partial dead work): no destructive action — the next fixer
          gets a KILLED NOTICE instead (killed_fix_notice flag).
        """
        path = self._busy_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                marker = json.load(fh)
        except (OSError, ValueError):
            return
        try:
            os.unlink(path)
        except OSError:
            pass
        if not gitops.enabled(self.config):
            return
        kind = marker.get("kind")
        unit = st.current_unit(self.state)
        if unit is None or kind in (None, "verification"):
            return
        try:
            dirty = bool(gitops.worktree_diff(self.workspace).strip())
        except gitops.GitError:
            return
        status = unit["status"]
        clean_tree_phase = status in (
            st.U_ROUNDS, st.U_SEALING, st.U_PRE_SEAL_VERIFY,
            st.U_PRE_REVIEW_VERIFY,
        )
        fresh_episode_fix = (
            kind == contracts.KIND_FIX_FINDINGS
            and status == st.U_FIXING
            and not unit.get("fix_loop_rounds")
        )
        if dirty and (clean_tree_phase or fresh_episode_fix):
            try:
                gitops.restore_clean(self.workspace)
            except gitops.GitError:
                return
            st.append_event(
                self.state,
                "unclean_stop_restored",
                unit=st.unit_key(unit),
                killed_call=marker.get("label"),
                kind=kind,
            )
            self._save()
            return
        if kind == contracts.KIND_FIX_FINDINGS and status in (
            st.U_FIXING, st.U_DELTA_REVIEW
        ):
            unit["killed_fix_notice"] = marker.get("label") or True
            st.append_event(
                self.state,
                "unclean_stop_noticed",
                unit=st.unit_key(unit),
                killed_call=marker.get("label"),
            )
            self._save()

    def _amendments_path(self):
        return os.path.join(self._runtime_dir(), "amendments.json")

    def _amendments(self):
        """Operator amendments, re-read before every worker call so a note
        added mid-run binds the very next call. The file is operator-owned
        (the panel appends to it; the driver only reads) — deliberately
        OUTSIDE the append-only ledger so hot edits cannot collide with
        the driver's lock. The ledger still gets an `amendment_seen`
        event the first time each id shows up, so every round can be
        judged against what its workers actually knew."""
        try:
            with open(self._amendments_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            amendments = [
                a
                for a in (data.get("amendments") or [])
                if isinstance(a, dict) and str(a.get("text") or "").strip()
            ]
        except (OSError, ValueError):
            return []
        if amendments:
            seen = {
                e.get("amendment_id")
                for e in self.state["events"]
                if e.get("type") == "amendment_seen"
            }
            for a in amendments:
                aid = str(a.get("id") or "")
                if aid and aid not in seen:
                    st.append_event(
                        self.state,
                        "amendment_seen",
                        amendment_id=aid,
                        text=str(a.get("text"))[:300],
                    )
        return amendments

    def _read_standing_law(self, worker_kind, unit_kind):
        """LIVE read of the project's standing law for one worker call:
        (in-scope enabled policies, reuse-source roles or None), through
        the sealed Slice 3 selection and Slice 2 meta seams. Any fault is
        a _StandingLawError: unlike amendments.json (a lock-free hot-edit
        file whose tolerant read returns nothing on a mid-write race), the
        policy store is a CAS-disciplined KV validated on write — malformed
        content there is corruption, and silently proceeding WITHOUT
        standing law is the one behavior this surface must never exhibit."""
        block = self.state["project"]
        directory, project = block["directory"], block["project"]
        store_dir = os.path.join(directory, project)
        if not os.path.isdir(store_dir):
            # Opening a client would silently recreate an EMPTY store and
            # run the call with no law at all; refuse before that.
            raise _StandingLawError(
                "project %r has no readable store under %s (removed after "
                "init?); repair the store and resume" % (project, directory)
            )
        store_file = os.path.join(store_dir, kvstore.STORE_FILENAME)
        if not os.path.isfile(store_file):
            # The project directory alone is not evidence of standing law:
            # LocalKVClient would treat a missing file as an empty store.
            raise _StandingLawError(
                "project %r has no readable KV file at %s (removed after "
                "init?); repair the store and resume" % (project, store_file)
            )
        try:
            selected = projects.PolicyStore(directory, project).in_scope(
                worker_kind, unit_kind
            )
        except OSError as exc:
            raise _StandingLawError(
                "policy store of project %r is unreadable while selecting "
                "safeguards for (%s, %s): %s; repair the store and resume"
                % (project, worker_kind, unit_kind, exc)
            )
        if not selected.ok:
            raise _StandingLawError(
                "policy store of project %r failed while selecting "
                "safeguards for (%s, %s): %s; repair the store and resume"
                % (project, worker_kind, unit_kind, selected.reason)
            )
        work_area = block["work_area"]
        try:
            record = workareas.WorkAreaStore(directory, project).read_meta(
                work_area
            )
        except (OSError, RuntimeError) as exc:
            raise _StandingLawError(
                "work_area_meta:%s of project %r is unreadable: %s; repair "
                "the store and resume" % (work_area, project, exc)
            )
        if not record["exists?"]:
            # The meta family is optional by Slice 2's design: the map
            # renders without roles.
            return selected.value, None
        try:
            meta = workareas._meta_value(record["value"])
        except ValueError as exc:
            raise _StandingLawError(
                "work_area_meta:%s of project %r is malformed (%s); repair "
                "the store and resume" % (work_area, project, exc)
            )
        return selected.value, meta["reuse_sources"]

    def _record_safeguards_seen(self, policies):
        """`project_safeguard_seen`, mirroring `amendment_seen`: appended
        the first time each (policy id, version) pair enters a prompt of
        this run, with the same 300-character text clip; a version bump
        re-records under the new version (the frozen ledger shape). Runs
        BEFORE the worker call, so a call that later fails still leaves
        what its worker was shown in the persisted ledger."""
        seen = {
            (e.get("policy_id"), e.get("version"))
            for e in self.state["events"]
            if e.get("type") == "project_safeguard_seen"
        }
        for policy in policies:
            key = (policy["id"], policy["version"])
            if key in seen:
                continue
            seen.add(key)
            st.append_event(
                self.state,
                "project_safeguard_seen",
                policy_id=policy["id"],
                version=policy["version"],
                text=str(policy["prompt"])[:300],
            )

    def _project_prompt_inputs(self, unit, kind):
        """Standing project law for one worker call of a project-bound
        run: (project_context, extensions, roots) — the PROJECT CONTEXT
        builder input, the compiled in-scope contract extensions, and the
        grant universe. (None, None, None) for a project-less run, whose
        builders and validation then behave byte-identically to today.

        Selection and meta are read live per call through this method;
        callers choose the cadence (every ordinary call; ONCE per seal
        attempt, so both halves share one snapshot — one judgment
        surface). Roots and handles come from the state project block
        recorded at init, never a live resolve: the map always describes
        exactly the universe containment enforces, and a mid-run store
        edit to the work-area record changes neither. Selection, meta,
        and compile faults fail the run, loudly, consuming no worker call
        (Slice 4's non-repairable error split, reused); the same call
        that renders an obligation supplies its compiled extension to
        enforcement — never one without the other."""
        block = self.state.get("project")
        if block is None:
            return None, None, None
        try:
            policies, reuse_sources = self._read_standing_law(
                kind, unit["kind"]
            )
            extensions = verifiers.compile_extensions(policies)
        except (_StandingLawError, verifiers.VerifierError) as exc:
            st.fail_run(
                self.state,
                "project standing law unavailable for the %s call: %s"
                % (kind, exc),
                unit=unit,
            )
            self._save()
            raise StopStep(str(exc))
        self._record_safeguards_seen(policies)
        roots = [block["primary"]["path"]] + [
            root["path"] for root in block["additional"]
        ]
        project_context = {
            "project": block["project"],
            "work_area": block["work_area"],
            "primary": block["primary"],
            "additional": block["additional"],
            "reuse_sources": reuse_sources,
            "safeguards": policies,
        }
        return project_context, extensions, roots

    def _busy_path(self):
        return os.path.join(self._runtime_dir(), "current.json")

    def _mark_busy(self, label, kind, family, model=None, effort=None):
        """Cosmetic in-flight marker for the panel (NOT part of the state
        ledger): what call is executing right now and since when. Written
        atomically; concurrent seal halves may interleave markers
        (last-write-wins), which is acceptable for a progress display."""
        try:
            os.makedirs(os.path.dirname(self._busy_path()), exist_ok=True)
            tmp = self._busy_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(
                    {"label": label, "kind": kind, "family": family,
                     "model": model, "effort": effort,
                     "started_at": time.time()},
                    fh,
                )
            os.replace(tmp, self._busy_path())
        except OSError:
            pass  # never let the progress display break a run

    def _clear_busy(self):
        try:
            os.unlink(self._busy_path())
        except OSError:
            pass

    def _call(self, family, prompt, kind, raw_name, model=None, effort=None,
              extensions=None, roots=None, validate_opts=None):
        """Validated worker call; on protocol/runner failure, fail the run
        with the explanation recorded, then re-raise as StopStep.

        extensions/roots: the in-scope compiled project contract
        extensions and the run's grant universe (_project_prompt_inputs).
        Absent, validation is exactly the base kind contract.
        validate_opts: extra validation kwargs (require_plain,
        battery_questions) threaded into runners.call_worker."""
        dm, de = self._family_defaults(family)
        model = model or dm
        effort = effort or de
        retries = self.config.get("infra_retry_backoff_s")
        if retries is None:
            retries = [10, 30]
        attempt = 0
        while True:
            self._mark_busy(
                raw_name, kind, family, model=model, effort=effort
            )
            try:
                output, result = runners.call_worker(
                    self.runner, family, prompt, kind, self.workspace,
                    model=model, effort=effort,
                    extensions=extensions, roots=roots,
                    validate_opts=validate_opts,
                )
            except verifiers.VerifierError as exc:
                # Slice 4's non-repairable family (the operator's policy or
                # the environment, e.g. a missing reuse-source directory —
                # never the worker): a recorded run failure the operator
                # repairs and resumes; no repair retry is burned.
                self._clear_busy()
                st.fail_run(
                    self.state,
                    "%s call: project standing-law fault (never the "
                    "worker's): %s" % (kind, exc),
                    unit=st.current_unit(self.state),
                )
                self._save()
                raise StopStep(str(exc))
            except (runners.RunnerError, runners.WorkerProtocolError) as exc:
                self._clear_busy()
                proto_paths = self._save_protocol_raws(raw_name, exc)
                etype, resume_at, evidence = self._classify_failure(
                    family, exc, raw_name=raw_name
                )
                if etype in ("network", "busy") and attempt < len(retries):
                    # Short in-place retries BEFORE failing: transient
                    # blips should not cost a run failure + resume cycle.
                    st.append_event(
                        self.state, "infra_retry", kind=kind, family=family,
                        failure_type=etype, attempt=attempt + 1,
                        wait_s=retries[attempt],
                    )
                    self._save()
                    time.sleep(retries[attempt])
                    attempt += 1
                    continue
                # The call is now definitively FAILING the run: the red
                # incident chip (an in-place-absorbed infra blip above
                # records only its infra_retry event, no chip).
                self._record_fatal_malformed(
                    raw_name, kind, family, exc, proto_paths
                )
                resume_at = errclass.normalize_resume_at(resume_at)
                if etype in errclass.AUTO_RESUMABLE and not resume_at:
                    fallback_min = (
                        30 if etype == "quota"
                        else errclass.TRANSIENT_BACKOFF_MIN
                    )
                    resume_at = errclass.parse_resume_at(
                        "in %d minutes" % fallback_min
                    )
                st.fail_run(
                    self.state,
                    "%s call failed: %s" % (kind, exc),
                    unit=st.current_unit(self.state),
                    type_=etype,
                    resume_at=resume_at,
                    evidence=evidence,
                )
                self._save()
                raise StopStep(str(exc))
            break
        self._clear_busy()
        raw_path = self._save_raw(raw_name, result.text)
        self._record_repair(raw_name, kind, family, result)
        return output, result, raw_path

    def _record_repair(self, raw_name, kind, family, result):
        """Permanent trace of a repaired first strike: a worker whose first
        output violated the contract and whose single repair retry then
        validated used to be invisible (no event, no raw, its duration
        unrecorded — the panel's '7 min' call that took 20). The malformed
        text lands in raw/ and a worker_malformed event carries the error,
        the wasted duration, and the raw path — the panel surfaces it as a
        chip; prompt/contract tuning needs these strikes visible."""
        rep = getattr(result, "repair", None)
        if not rep:
            return
        raw_path = self._save_raw("%s-malformed" % raw_name, rep["raw_text"])
        st.append_event(
            self.state,
            "worker_malformed",
            unit=self._worker_event_unit(),
            label=raw_name,
            kind=kind,
            family=family,
            error=str(rep["error"])[:300],
            duration_s=rep["duration_s"],
            raw_path=raw_path,
        )

    def _classify_failure(self, family, exc, raw_name=None):
        """Type a failed worker call: deterministic patterns over the raw
        outputs (and the exception text), opposite-family LLM classifier
        as a non-blocking fallback (config error_classifier).

        When the LLM stage runs, its prompt+response (or the error, if the
        classifier call itself failed) are persisted as a
        <raw_name>-classify-<family>.txt artifact so an "unknown" verdict is
        auditable after the fact."""
        texts = list(getattr(exc, "raw_texts", []) or [])
        texts.append(str(exc))
        if isinstance(exc, runners.RunnerError) and "timed out" in str(exc):
            return "timeout", None, "runner timeout"
        return errclass.classify_failure(
            texts,
            runner=self.runner,
            opposite_family=self._opposite(family),
            workspace=self.workspace,
            use_llm=bool(self.config.get("error_classifier", True)),
            on_llm_raw=self._classify_raw_saver(raw_name),
        )

    def _classify_raw_saver(self, raw_name):
        """A best-effort sink that persists the failure classifier's I/O.
        Returns None when there is no raw_name to key the artifact on."""
        if not raw_name:
            return None

        def _save(classifier_family, prompt, raw):
            self._save_raw(
                "%s-classify-%s" % (raw_name, classifier_family),
                "CLASSIFIER PROMPT\n=================\n%s\n\n"
                "CLASSIFIER RESPONSE\n===================\n%s\n"
                % (prompt, raw if raw is not None else "(no response)"),
            )

        return _save

    def _builders_desc(self):
        """One line naming the run's REAL downstream builders (resolved
        acts, family defaults filled in) for the drift-risk rater: 'who
        builds on this artifact' is a fact of the run, not a hypothetical
        junior — a fable-5-at-max implementer reads an ambiguity very
        differently than the rater's imagined worst case."""
        parts = []
        for act, label in (("drafter", "slice docs drafted by"),
                           ("implementer", "implementation built by")):
            fam, model, effort = self._act_profile(act)
            dm, de = self._family_defaults(fam)
            parts.append("%s %s (%s, %s effort)"
                         % (label, fam, model or dm, effort or de))
        return "; ".join(parts)

    def _enforce_sealed_artifacts(self, raw_name):
        """SEALED units' doc artifacts are read-only for every edit-kind
        call (found live 2026-07-10: a fixer materially REWROTE the
        sealed slice-02 note to legalize behaviors the sealed version
        forbade, then self-declared the note in its expected files — 50
        rounds of review judged a moving target). After every edit-kind
        call, each sealed unit's artifact must byte-match the run's
        NEWEST gate commit (not HEAD: the amend discipline folds
        tampering into the wip commit, so HEAD can already be tainted;
        and not each unit's OWN gate: sealed docs carry legal post-seal
        drift — pre-guard-era `prevention` edits reviewed and folded
        into later gates, and repair reseals — so the last gate, a
        double-sealed checkpoint of the WHOLE tree, is the one canonical
        baseline; baselining on the own gate fired three false restores
        on 2026-07-10, each regressing a legally amended note). A
        mismatch is restored from that gate, the illegal bytes land in
        raw/ for forensics, and a sealed_artifact_restored event records
        the violation. Runs without git have no canonical source and
        skip (their sealed docs are protected by the prompt rule only).
        A unit under legitimate repair is not SEALED while it is being
        repaired, so its own repair episode is naturally exempt."""
        if not gitops.enabled(self.config):
            return []
        last_gate = gitops.newest_commit(
            self.workspace,
            [u.get("gate_commit") for u in self.state["units"]],
        )
        restored = []
        for u in self.state["units"]:
            if u["status"] != st.U_SEALED:
                continue
            gate, art = u.get("gate_commit"), u.get("artifact")
            if not gate or not art:
                continue
            canonical = gitops.show_file(
                self.workspace, last_gate or gate, art
            )
            if canonical is None:
                # The artifact is unreadable at the newest gate (e.g. a
                # foreign-history edge): fall back to the unit's own gate.
                canonical = gitops.show_file(self.workspace, gate, art)
            if canonical is None:
                continue  # unreadable gate/path: nothing to enforce against
            path = os.path.join(self.workspace, art)
            try:
                with open(path, "rb") as fh:
                    current = fh.read()
            except OSError:
                current = None  # deleted: also a violation
            if current == canonical:
                continue
            safe = st.unit_key(u).replace("/", "_")
            raw = self._save_raw(
                "%s-sealed-violation-%s" % (raw_name, safe),
                (current if current is not None else b"(file deleted)")
                .decode("utf-8", "replace"),
            )
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(canonical)
            st.append_event(
                self.state, "sealed_artifact_restored",
                unit=st.unit_key(u), artifact=art, during=raw_name,
                raw_path=raw,
            )
            restored.append(art)
        return restored

    def _maybe_update_slices(self, unit, output):
        """A fix call on the skeleton unit may report an updated slice plan
        (it has edit permissions on the skeleton document); keep the
        structural plan in sync with it. Validated by contracts already."""
        slices = output.get("slices")
        if unit["kind"] != st.UNIT_SKELETON or not slices:
            return
        if slices != self.state["milestone"]["slices"]:
            self.state["milestone"]["slices"] = [dict(sl) for sl in slices]
            st.append_event(
                self.state,
                "slices_updated",
                unit=st.unit_key(unit),
                slices=self.state["milestone"]["slices"],
            )

    def _check_worker_blocked(self, unit, output, kind):
        # type_="worker_blocked": a blocked worker is an OPERATOR-gated
        # stop (like goal_gap/gap_stall), not an unclassified transient —
        # left untyped it defaults to "unknown" and the service guard
        # emergency-resumes it every 15 minutes forever, re-running the
        # worker against the very decision it stopped to ask for. Found
        # live (2026-07-10, LPC rich-content): blocked findings that
        # needed a sealed-note repair were auto-resumed 16 minutes later.
        if output["status"] == "blocked":
            st.fail_run(
                self.state,
                "%s worker blocked: %s" % (kind, output.get("blocked_reason")),
                unit=unit, type_="worker_blocked",
            )
            self._save()
            raise StopStep(output.get("blocked_reason"))
        blocked = contracts.blocking_findings(output)
        if blocked:
            st.fail_run(
                self.state,
                "%s reported blocked findings needing the operator: %s"
                % (kind, "; ".join(f["summary"] for f in blocked)),
                unit=unit, type_="worker_blocked",
            )
            self._save()
            raise StopStep("blocked findings")

    # -- action executors --------------------------------------------------

    def step(self):
        """Execute exactly one action. Returns (action, note).

        Worker calls have at-least-once semantics: records are saved only
        after the handler completes, so a crash mid-handler re-executes the
        same call on resume (see README, "Operational semantics")."""
        action = decide(self.state)
        if action.type in (A_DONE, A_FAILED):
            return action, None
        handler = {
            A_DRAFT: self._do_draft,
            A_VERIFY: self._do_verify,
            A_REVIEW_ROUND: self._do_review_round,
            A_FIX: self._do_fix,
            A_DELTA_REVIEW: self._do_delta_review,
            A_SEAL_ATTEMPT: self._do_seal_attempt,
        }[action.type]
        with self._exclusive():
            self._assert_not_stale()
            try:
                note = handler()
            except StopStep as exc:
                return action, "run failed: %s" % exc
            self._save()
            return action, note

    def run(self, max_steps=1000):
        steps = 0
        while steps < max_steps:
            action = decide(self.state)
            if action.type == A_DONE:
                if st.current_unit(self.state) is None:
                    with self._exclusive():
                        self._assert_not_stale()
                        st.maybe_close_milestone(self.state)
                        self._save()
                return 0
            if action.type == A_FAILED:
                return 2
            self.step()
            steps += 1
        return 3

    def _goal_for(self, unit):
        """The GOAL block a unit's prompts carry.

        Reform runs, skeleton phase: the skeleton consumes the operator's
        goal — but a LARGE goal (config goal_inline_max) rides as the
        generated goal.md ledger with an ordered full read instead of
        inline text: instructions must dominate a prompt (a 60K goal
        drowns the altitude rules and the output contract), and a file
        survives the worker's own context compaction where inline prose
        does not — the worker can re-read ground truth at any point.

        Reform runs, later units: they consume the SEALED SKELETON
        (spec §2's chain of consumption) — operator planning prose stops
        riding every downstream call, and downstream workers judge scope
        against the sealed boundary rather than a raw brainstorm's
        non-binding sketches; goal.md stays one read away.

        Legacy and profile-less runs keep the full goal inline
        everywhere (bit-identical)."""
        if not interpreter.reform_active(self.state):
            return self.state["goal"]
        if unit["kind"] == st.UNIT_SKELETON:
            limit = self.config.get("goal_inline_max")
            if not isinstance(limit, int) or limit <= 0:
                limit = 8000
            if len(self.state["goal"]) <= limit:
                return self.state["goal"]
            self._ensure_goal_ledger()
            return (
                "the operator's goal document is preserved VERBATIM at "
                "%s (generated snapshot, frozen at launch — the live "
                "original may drift; this file is the mandate). Read it "
                "IN FULL before working: every requirement in it binds "
                "exactly as if it were printed here."
                % ledgers.goal_path(self.state)
            )
        self._ensure_goal_ledger()
        return (
            "the sealed skeleton at %s is the operative restatement of "
            "the goal — the milestone boundary; judge scope against IT. "
            "The operator's full original goal text is preserved at %s "
            "(generated snapshot); read it only to trace intent the "
            "skeleton does not settle."
            % (ledgers.skeleton_path(self.state),
               ledgers.goal_path(self.state))
        )

    def _ensure_goal_ledger(self):
        """Idempotent write of the goal.md snapshot ledger, for prompts
        that reference it before the first gate regeneration lands it
        (the skeleton draft of a large goal precedes every gate). Always
        called on the main thread during prompt assembly — before any
        report-call tamper snapshot, so the write is never attributed to
        a reviewer."""
        rel = ledgers.goal_path(self.state)
        path = os.path.join(self.workspace, rel)
        content = ledgers.render_goal(self.state)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() == content:
                    return
        except OSError:
            pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def _do_draft(self):
        unit = st.current_unit(self.state)
        act = (
            "implementer" if unit["kind"] == st.UNIT_SLICE_IMPL else "drafter"
        )
        family, model, effort = self._act_profile(act)
        goal = self._goal_for(unit)
        amendments = self._amendments()
        kind = {
            st.UNIT_SKELETON: contracts.KIND_DRAFT_SKELETON,
            st.UNIT_SLICE_DOC: contracts.KIND_DRAFT_SLICE_NOTE,
            st.UNIT_SLICE_IMPL: contracts.KIND_IMPLEMENT,
        }[unit["kind"]]
        project_context, extensions, roots = self._project_prompt_inputs(
            unit, kind
        )
        # Reform profiles hand builders the gap exit (stop-report-repair-
        # resume); legacy/profile-less builders never see it. A profile
        # asking for the lay+hard-table register gets the two-register
        # document instruction (spec §6); others keep the dense register.
        # Doc drafts under a reform profile additionally answer the
        # structured question battery (spec §4) — prompted, mirrored in
        # the contract JSON, and machine-checked for presence.
        gap_enabled = interpreter.gap_semantics(self.state)
        two_register = interpreter.doc_register(self.state) == "lay+hard-table"
        battery = interpreter.battery_questions(self.state, unit["kind"])
        if unit["kind"] == st.UNIT_SKELETON:
            prompt = prompts.build_draft_skeleton(
                family, self.workspace, goal, amendments=amendments,
                artifact_path=ledgers.skeleton_path(self.state),
                project_context=project_context, gap_enabled=gap_enabled,
                two_register=two_register, battery=battery,
            )
        elif unit["kind"] == st.UNIT_SLICE_DOC:
            sl = self._slice_info(unit["slice_id"])
            prompt = prompts.build_draft_slice_note(
                family, self.workspace, goal, sl, self._skeleton_artifact(),
                amendments=amendments,
                note_path=ledgers.slice_note_path(
                    self.state, unit["slice_id"]
                ),
                project_context=project_context, gap_enabled=gap_enabled,
                two_register=two_register, battery=battery,
            )
        else:
            sl = self._slice_info(unit["slice_id"])
            prompt = prompts.build_implement(
                family,
                self.workspace,
                goal,
                sl,
                self._slice_note_artifact(unit["slice_id"]),
                self._verification_commands(unit),
                amendments=amendments,
                project_context=project_context, gap_enabled=gap_enabled,
            )
        output, result, raw_path = self._call(
            family, prompt, kind, "%s-draft" % st.unit_key(unit),
            model=model, effort=effort, extensions=extensions, roots=roots,
            validate_opts=(
                {"battery_questions": battery} if battery else None
            ),
        )
        if output.get("status") == "gap":
            # The builder met a build-changing hole/conflict and stopped
            # (reform §3). Route it upstream (repair) or to the operator
            # (goal). The unit finished NOTHING and stays pending; it
            # re-drafts after the repair reseals.
            return self._handle_gap(unit, output, result.duration_s)
        self._enforce_sealed_artifacts("%s-draft" % st.unit_key(unit))
        self._check_worker_blocked(unit, output, kind)
        st.record_draft(self.state, unit, kind, output, raw_path,
                        family=family, duration=result.duration_s,
                        model=model, effort=effort)
        if kind == contracts.KIND_IMPLEMENT and output.get("suite_command"):
            st.set_discovered_suite(self.state, output["suite_command"])
        if unit["kind"] == st.UNIT_SKELETON:
            self.state["milestone"]["slices"] = output["slices"]
        if gitops.enabled(self.config):
            try:
                sha = gitops.commit_wip(
                    self.workspace, "wip: %s" % st.unit_key(unit)
                )
            except gitops.GitError as exc:
                st.fail_run(self.state, "wip commit failed: %s" % exc, unit=unit)
                self._save()
                raise StopStep(str(exc))
            st.append_event(
                self.state, "wip_commit", unit=st.unit_key(unit), sha=sha
            )
        st.transition_unit(
            self.state, unit, st.U_PRE_REVIEW_VERIFY, reason="drafted"
        )
        return "drafted %s" % (unit["artifact"] or "(implementation)")

    # -- gap routing (reform §3: stop-report-repair-resume) -----------------

    def _find_unit(self, kind, slice_id):
        for u in self.state["units"]:
            if u["kind"] == kind and u["slice_id"] == slice_id:
                return u
        return None

    _SLICE_DOC_RE = re.compile(r"^slice_doc-0*(\d+)$")

    def _route_gap_target(self, unit, target):
        """Resolve a gap's `target` to ('operator', None) for the goal, or
        ('unit', <sealed upstream unit>) for an upstream doc. Raises
        _GapRouteError on a target that is not routable from `unit`."""
        if target == "goal":
            if unit["kind"] == st.UNIT_SLICE_IMPL:
                raise _GapRouteError(
                    "an implement gap must target its slice_doc or the "
                    "skeleton, not the goal"
                )
            return ("operator", None)
        up = None
        if target == "skeleton":
            up = self._find_unit(st.UNIT_SKELETON, None)
        else:
            m = self._SLICE_DOC_RE.match(target or "")
            if m:
                up = self._find_unit(st.UNIT_SLICE_DOC, int(m.group(1)))
        if up is None:
            raise _GapRouteError(
                "gap target %r does not name a known upstream unit" % target
            )
        if up is unit or up["status"] != st.U_SEALED:
            raise _GapRouteError(
                "gap target %r is not a SEALED upstream unit (is %s)"
                % (target, up["status"])
            )
        return ("unit", up)

    def _gap_targets_unit(self, gap, upstream):
        target = gap.get("target")
        if target == "skeleton":
            return upstream["kind"] == st.UNIT_SKELETON
        m = self._SLICE_DOC_RE.match(target or "")
        return bool(
            m and upstream["kind"] == st.UNIT_SLICE_DOC
            and int(m.group(1)) == upstream["slice_id"]
        )

    def _gap_to_finding(self, gap, i):
        """A gap becomes a P1 repair finding for the upstream fixer. Its
        proposal, when present, is carried as CONTEXT and marked as a
        proposal — the fixer verifies it against the sources, never adopts
        it on trust (reform decision 6)."""
        summary = "REPAIR (downstream gap): %s. Forced decision: %s." % (
            gap.get("missing_or_conflict", ""), gap.get("forced_decision", "")
        )
        if gap.get("proposal"):
            summary += (
                " Proposal (a PROPOSAL — verify independently against the "
                "sources, do not adopt on trust): %s" % gap["proposal"]
            )
        finding = {"id": "GAP%d" % (i + 1), "severity": "P1",
                   "summary": summary}
        if gap.get("plain"):
            finding["plain"] = gap["plain"]
        if gap.get("example"):
            finding["example"] = gap["example"]
        return finding

    def _handle_gap(self, unit, output, duration_s=None):
        gaps = output.get("gaps", [])
        st.append_event(
            self.state, "gap_reported", unit=st.unit_key(unit),
            duration_s=duration_s,
            count=len(gaps),
            gaps=[{k: g.get(k) for k in ("target", "forced_decision", "plain")}
                  for g in gaps],
        )
        # Route the MOST UPSTREAM implicated target first (goal < skeleton <
        # slice_doc); repairing it and re-drafting re-surfaces anything
        # still open, so convergence needs no cross-target bookkeeping.
        def _rank(t):
            return {"goal": 0, "skeleton": 1}.get(t, 2)
        try:
            routed = sorted(
                (
                    (_rank(g.get("target")), g,
                     self._route_gap_target(unit, g.get("target")))
                    for g in gaps
                ),
                key=lambda r: r[0],
            )
        except _GapRouteError as exc:
            st.fail_run(self.state, "gap routing failed: %s" % exc, unit=unit,
                        type_="gap_route")
            self._save()
            raise StopStep(str(exc))
        _, primary, (route_kind, target_unit) = routed[0]
        if route_kind == "operator":
            return self._route_goal_gap(unit, primary)
        return self._reopen_and_repair(unit, target_unit, gaps, primary)

    def _route_goal_gap(self, unit, primary):
        """A gap targeting the goal routes to the OPERATOR — the goal is
        operator-authored and only its author repairs it. The operator
        resolves by amending the goal (the existing amendment mechanism
        binds from the next call) and resuming; the fresh draft then sees
        the amendment. Operator-gated failure: not auto- or emergency-
        resumed (re-drafting would just re-report the same gap)."""
        st.append_event(
            self.state, "goal_gap_reported", unit=st.unit_key(unit),
            forced_decision=str(primary.get("forced_decision", ""))[:400],
            plain=str(primary.get("plain", ""))[:400],
            example=str(primary.get("example", ""))[:400],
        )
        st.fail_run(
            self.state,
            "goal gap: %s — resolve by amending the goal, then resume "
            "(the goal is operator-authored; only its author repairs it)"
            % primary.get("forced_decision", ""),
            unit=unit, type_="goal_gap",
        )
        self._save()
        raise StopStep("goal gap reported to the operator")

    def _reopen_and_repair(self, unit, target_unit, gaps, primary):
        cap = int(self.config.get("max_gap_repairs", 3))
        n = int(unit.get("gap_repairs", 0)) + 1
        unit["gap_repairs"] = n
        if n > cap:
            st.fail_run(
                self.state,
                "gap-repair cap (%d) exceeded on %s: the same gap keeps "
                "reopening upstream — a stall, not convergence; operator "
                "review needed" % (cap, st.unit_key(unit)),
                unit=unit, type_="gap_stall",
            )
            self._save()
            raise StopStep("gap-repair cap exceeded")
        target_key = st.unit_key(target_unit)
        repair_findings = [
            self._gap_to_finding(g, i)
            for i, g in enumerate(gaps) if self._gap_targets_unit(g, target_unit)
        ]
        st.reopen_for_repair(
            self.state, target_unit, primary,
            reason="downstream %s reported a gap" % st.unit_key(unit),
            reported_by=st.unit_key(unit),
        )
        st.enter_fix_episode(
            self.state, target_unit, repair_findings, "repair", None,
            "%s-gap-repair" % target_key, st.U_PRE_SEAL_VERIFY,
        )
        return (
            "gap on %s -> reopened %s for repair (%d repair finding(s)); it "
            "reseals, then %s re-drafts"
            % (st.unit_key(unit), target_key, len(repair_findings),
               st.unit_key(unit))
        )

    def _slice_info(self, slice_id):
        for sl in self.state["milestone"]["slices"]:
            if sl["id"] == slice_id:
                return sl
        raise st.IllegalTransition("unknown slice id %r" % slice_id)

    def _skeleton_artifact(self):
        for u in self.state["units"]:
            if u["kind"] == st.UNIT_SKELETON:
                return u["artifact"] or ledgers.skeleton_path(self.state)
        return ledgers.skeleton_path(self.state)

    def _slice_note_artifact(self, slice_id):
        for u in self.state["units"]:
            if u["kind"] == st.UNIT_SLICE_DOC and u["slice_id"] == slice_id:
                return u["artifact"] or ledgers.slice_note_path(
                    self.state, slice_id
                )
        return ledgers.slice_note_path(self.state, slice_id)


    # -- review/fix separation machinery ------------------------------------

    def _registry(self):
        return st.adjudicated_rejections(self.state)

    def _debt(self, unit):
        return list(st.active_debt(self.state, unit))

    def _acts_overlay(self):
        """Operator-editable mid-run act assignments (acts.json beside the
        state file) — same lock-free pattern as amendments: the panel
        writes, the driver only reads, re-read before every act resolution
        so a change binds the next call."""
        path = os.path.join(self._runtime_dir(), "acts.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _act_profile(self, act, origin_family=None, default_family=None):
        """(family, model, effort) for an act. Policy forms: a family
        name, "self"/"opposite" (relative to origin), or an object
        {"agent": ..., "model": ..., "effort": ...}. Hot overlay wins
        over config; an absent policy falls back to default_family (or
        fix_family). model/effort None mean family defaults."""
        acts = dict(self.config.get("acts") or {})
        for key, val in self._acts_overlay().items():
            if val:
                acts[key] = val
        policy = acts.get(act)
        model = effort = None
        if isinstance(policy, dict):
            model = (policy.get("model") or "").strip() or None
            effort = (policy.get("effort") or "").strip() or None
            policy = (
                policy.get("agent") or policy.get("family") or ""
            ).strip() or None
        if not policy:
            return (default_family or self._fix_family()), model, effort
        families = self.config["families_order"]
        if policy == "self":
            fam = origin_family or families[0]
        elif policy == "opposite":
            fam = self._opposite(origin_family or families[0])
        else:
            fam = policy
        return fam, model, effort

    def _family_defaults(self, family):
        d = (self.config.get("model_defaults") or {}).get(family) or {}
        return d.get("model"), d.get("effort")

    def _review_profile(self, family):
        """Effective model/effort for a fixed review family.

        Review leadership remains family-rotated: an accidental/manual
        `agent` field on the act cannot turn the Codex half into Claude or
        vice versa. Only model and effort are operator-tunable.
        """
        _ignored_family, model, effort = self._act_profile(
            "review_%s" % family,
            origin_family=family,
            default_family=family,
        )
        default_model, default_effort = self._family_defaults(family)
        return model or default_model, effort or default_effort

    def _delta_review_profile(self, fixer_family):
        """Use the fixer's family and that family's Review profile.

        Older frozen configs may still contain a `delta_review` act. It is
        deliberately ignored: the delta judge has no independent family or
        model dial, so it cannot drift away from the fixer it is checking.
        """
        family = fixer_family or self._fix_family()
        model, effort = self._review_profile(family)
        return family, model, effort

    def _convergence_fixer_profile(self, origin_family=None):
        """Effective profile for a fix chain that is failing to converge.

        Runs freeze config at creation time, so old live runs do not contain
        this act. They still receive the current Sol/max default. A hot
        acts.json entry is detected explicitly and then resolved through the
        ordinary policy machinery, preserving its normal precedence.
        """
        configured = (self.config.get("acts") or {}).get(
            "convergence_fixer"
        )
        hot = self._acts_overlay().get("convergence_fixer")
        if configured or hot:
            return self._act_profile(
                "convergence_fixer",
                origin_family=origin_family,
                default_family="codex",
            )
        fallback = DEFAULT_CONFIG["acts"]["convergence_fixer"]
        return (
            fallback["agent"], fallback["model"], fallback["effort"]
        )

    def _resolve_act(self, act, origin_family):
        """Family-only view of _act_profile (legacy call sites/tests)."""
        fam, _m, _e = self._act_profile(
            act, origin_family,
            default_family="codex" if act == "fixer" else None,
        )
        return fam

    def _validate_contests(self, unit, output, kind):
        """Structural check: a finding's contests.rejection_id must exist in
        the milestone registry. A bad reference is a protocol violation and
        fails the run with the explanation."""
        known = st.registry_ids(self.state)
        for f in output.get("findings", []):
            contests = f.get("contests")
            if contests and contests.get("rejection_id") not in known:
                st.fail_run(
                    self.state,
                    "%s finding %s contests unknown adjudication %r "
                    "(known: %s)"
                    % (kind, f.get("id"), contests.get("rejection_id"),
                       sorted(known) or "none"),
                    unit=unit,
                )
                self._save()
                raise StopStep("bad contests reference")

    def _validate_adjudication_refs(self, unit, output):
        known = st.registry_ids(self.state)
        for f in output.get("findings", []):
            if f.get("disposition") == "rejected_adjudicated":
                ref = f.get("adjudication_ref")
                if ref not in known:
                    st.fail_run(
                        self.state,
                        "fixer marked %s rejected_adjudicated with unknown "
                        "registry ref %r (known: %s)"
                        % (f.get("id"), ref, sorted(known) or "none"),
                        unit=unit,
                    )
                    self._save()
                    raise StopStep("bad adjudication reference")

    def _validate_contested_dispositions(self, unit, output):
        """A queued finding carrying `contests` re-opened that adjudication
        with structurally validated new evidence; the fixer must weigh it
        on the merits — fix, or reject with a FRESH consultation (the
        prompt contract: a CONTESTS finding "re-opens that adjudication").
        Disposing it rejected_adjudicated — killing the new evidence by
        pointer, typically citing the very adjudication under contest — is
        a protocol violation, enforced structurally, not by prompt text."""
        contested = {
            f["id"]: (f.get("contests") or {}).get("rejection_id")
            for f in (unit.get("fix_queue") or [])
            if f.get("contests")
        }
        for f in output.get("findings", []):
            if (f.get("disposition") == "rejected_adjudicated"
                    and f.get("id") in contested):
                st.fail_run(
                    self.state,
                    "fixer disposed finding %s as rejected_adjudicated "
                    "(ref %r), but that finding CONTESTS adjudication %r "
                    "with new evidence: a contested adjudication is "
                    "re-opened and must be fixed or rejected with a fresh "
                    "consultation, never killed by pointer"
                    % (f.get("id"), f.get("adjudication_ref"),
                       contested[f.get("id")]),
                    unit=unit,
                )
                self._save()
                raise StopStep("contested finding killed by pointer")

    def _report_call(self, unit, family, prompt, kind, raw_name,
                     extensions=None, roots=None, validate_opts=None,
                     model=None, effort=None):
        """Run a report-only call with mechanical no-edit enforcement.

        Returns (output, result, raw_path, changed): when the reviewer
        modified the workspace, changed is the non-empty list of paths
        that differ and the output must be discarded by the caller."""
        before = self._snapshot()
        output, result, raw_path = self._call(
            family, prompt, kind, raw_name, model=model, effort=effort,
            extensions=extensions, roots=roots, validate_opts=validate_opts,
        )
        changed = self._snapshot_diff(before, self._snapshot())
        return output, result, raw_path, changed

    def _restore_or_fail(self, unit, why):
        if not gitops.enabled(self.config):
            # With git disabled there was never a wip commit: HEAD — if the
            # workspace even is a repository, e.g. a user's own project —
            # predates everything this run produced, so reset/clean would
            # destroy the un-committed draft, every prior fix, and the
            # user's own uncommitted work, then keep judging the gutted
            # tree. Restoration is impossible; stop with the facts.
            st.fail_run(
                self.state,
                "%s, and git is disabled for this run so the workspace "
                "cannot be mechanically restored; operator inspection "
                "required" % why,
                unit=unit,
            )
            self._save()
            raise StopStep(why)
        try:
            gitops.restore_clean(self.workspace)
        except gitops.GitError as exc:
            st.fail_run(
                self.state,
                "%s and the workspace could not be restored: %s" % (why, exc),
                unit=unit,
            )
            self._save()
            raise StopStep(str(exc))

    def _do_fix(self):
        unit = st.current_unit(self.state)
        source = unit.get("fix_source") or {}
        max_loops = self.config.get("max_fix_loops", 6)
        if unit.get("fix_loop_rounds", 0) >= max_loops:
            st.fail_run(
                self.state,
                "fix episode on %s did not converge after %d fixer+delta "
                "loops (source: %s)"
                % (st.unit_key(unit), max_loops, source.get("type")),
                unit=unit,
            )
            self._save()
            raise StopStep("fix loop cap")
        dirty_delta_rounds = st.active_fix_dirty_delta_rounds(
            self.state, unit
        )
        dirty_deltas = len(dirty_delta_rounds)
        try:
            convergence_after = int(self.config.get(
                "convergence_fixer_after_deltas",
                DEFAULT_CONFIG["convergence_fixer_after_deltas"],
            ))
        except (TypeError, ValueError):
            convergence_after = DEFAULT_CONFIG[
                "convergence_fixer_after_deltas"
            ]
        convergence_after = max(0, convergence_after)
        convergence = dirty_deltas >= convergence_after
        if convergence:
            family, fix_model, fix_effort = (
                self._convergence_fixer_profile(source.get("family"))
            )
        else:
            family, fix_model, fix_effort = self._act_profile(
                "fixer", source.get("family"), default_family="codex"
            )
        consultation_family = self._resolve_act("consultation", family)
        project_context, extensions, roots = self._project_prompt_inputs(
            unit, contracts.KIND_FIX_FINDINGS
        )
        prompt = prompts.build_fix_findings(
            family,
            self.workspace,
            self._goal_for(unit),
            self._unit_desc(unit),
            unit.get("fix_queue") or [],
            self._registry(),
            consultation_family,
            self.config["commands"].get(consultation_family, []),
            verification_output=(
                unit.get("last_verification_output")
                if source.get("type") == "verification"
                else None
            ),
            unit_kind=unit["kind"],
            amendments=self._amendments(),
            phantom_retry=bool(unit.get("phantom_retried")),
            killed_notice=bool(unit.pop("killed_fix_notice", None)),
            project_context=project_context,
            debt=self._debt(unit),
            repair_artifact=(
                unit.get("artifact")
                if source.get("type") == "repair" else None
            ),
            convergence=(
                {
                    "dirty_deltas": dirty_deltas,
                    "rounds": dirty_delta_rounds[-5:],
                }
                if convergence
                else None
            ),
        )
        n_fix = 1 + len(
            [r for r in unit["rounds"] if r["kind"] == contracts.KIND_FIX_FINDINGS]
        )
        output, result, raw_path = self._call(
            family,
            prompt,
            contracts.KIND_FIX_FINDINGS,
            "%s-fix%d" % (st.unit_key(unit), n_fix),
            model=fix_model,
            effort=fix_effort,
            extensions=extensions,
            roots=roots,
        )
        self._enforce_sealed_artifacts("%s-fix%d" % (st.unit_key(unit), n_fix))
        self._check_worker_blocked(unit, output, contracts.KIND_FIX_FINDINGS)
        try:
            contracts.validate_fix_coverage(output, unit.get("fix_queue") or [])
        except contracts.ContractError as exc:
            st.fail_run(self.state, str(exc), unit=unit)
            self._save()
            raise StopStep(str(exc))
        self._validate_adjudication_refs(unit, output)
        self._validate_contested_dispositions(unit, output)
        if (
            isinstance(output.get("suite_command"), str)
            and output["suite_command"].strip()
            and (
                source.get("type") == "verification"
                or not self.state.get("suite_command")
            )
        ):
            # A verification fixer may CORRECT a wrong command; any fixer
            # may ARM a run that has none yet (live case: a reviewer
            # flagged the vacuous gate, the fixer supplied `mix test` —
            # dropping it on the floor forced a re-flag loop).
            if st.set_discovered_suite(self.state, output["suite_command"]):
                # Arming the suite IS a real fix even with zero file
                # edits: exempt THIS fix round's 'fixed' dispositions
                # from the phantom check. One-shot by construction —
                # adoption only fires when it actually changes state.
                unit["suite_armed_by_fix"] = True
        st.record_round(
            self.state,
            unit,
            family,
            contracts.KIND_FIX_FINDINGS,
            output,
            raw_path=raw_path,
            duration=result.duration_s,
            # `queued` preserves what the fixer was actually asked to triage
            # — including any contests links — in the immutable history;
            # state.adjudicated_rejections() derives overturned
            # adjudications (a contested finding conceded as 'fixed') from
            # it. model/effort record which experiment produced this fix.
            meta={
                "source_round_id": source.get("source_round_id"),
                "queued": copy.deepcopy(unit.get("fix_queue") or []),
                **(
                    {"model": fix_model, "effort": fix_effort}
                    if (fix_model or fix_effort)
                    else {}
                ),
                **(
                    {"convergence_dirty_deltas": dirty_deltas}
                    if convergence
                    else {}
                ),
            },
        )
        self._maybe_update_slices(unit, output)
        unit["fix_loop_rounds"] = unit.get("fix_loop_rounds", 0) + 1
        if gitops.enabled(self.config):
            st.transition_unit(
                self.state, unit, st.U_DELTA_REVIEW, reason="fix applied"
            )
            return "fix call done (%d finding(s) triaged); delta review next" % len(
                output.get("findings", [])
            )
        # Without git there is no delta to review or amend: return directly.
        target = source.get("return_to") or st.U_PRE_REVIEW_VERIFY
        st.transition_unit(self.state, unit, target, reason="fix applied (no git)")
        return "fix call done; continuing (git disabled)"

    def _phantom_edit_claims(self, unit):
        """Edit claims made by the unit's LAST fix call: any 'fixed'
        disposition, any prevention edit, or a non-empty files_changed
        (entries under .orchestrator/ are ignored — consultation
        transcripts are bookkeeping, excluded from diffs by design).
        Cross-checked against an empty worktree delta in _do_delta_review."""
        last_fix = None
        for r in reversed(unit["rounds"]):
            if r["kind"] == contracts.KIND_FIX_FINDINGS:
                last_fix = r["result"]
                break
        if last_fix is None:
            return []
        armed_now = unit.pop("suite_armed_by_fix", None)
        claims = []
        changed = []
        for p in last_fix.get("files_changed") or []:
            norm = os.path.normpath(str(p))
            # Runtime-bookkeeping paths (either layout) are not real edits.
            if any(seg in (".orchestrator", ".run")
                   for seg in norm.split(os.sep)):
                continue
            changed.append(p)
        if changed:
            claims.append("files_changed=%s" % (changed,))
        for f in last_fix.get("findings", []):
            if f.get("disposition") == "fixed":
                if armed_now:
                    # This fix ARMED the run's suite command — a real
                    # state-level fix; its 'fixed' verdicts are earned
                    # even without file edits.
                    continue
                claims.append("finding %s disposed 'fixed'" % f.get("id"))
            if f.get("prevention"):
                claims.append(
                    "finding %s claims a prevention edit in %s"
                    % (f.get("id"),
                       (f.get("prevention") or {}).get("documented_in"))
                )
        return claims

    def _do_delta_review(self):
        unit = st.current_unit(self.state)
        source = unit.get("fix_source") or {}
        return_to = source.get("return_to") or st.U_PRE_REVIEW_VERIFY
        try:
            delta = gitops.worktree_diff(self.workspace)
        except gitops.GitError as exc:
            st.fail_run(self.state, "git diff failed: %s" % exc, unit=unit)
            self._save()
            raise StopStep(str(exc))
        if not delta.strip():
            # An all-rejections episode leaves no delta: nothing to amend.
            # But the fixer's claims must agree with that: a 'fixed'
            # disposition, a non-empty files_changed, or a prevention edit
            # with an EMPTY worktree delta means the fixer reported work it
            # never did — a phantom fix would close the finding unfixed,
            # and a phantom prevention pointer would enter the adjudication
            # registry and suppress re-detection in every later review
            # prompt ("Settled findings stay settled" is a structural rule,
            # so the prevention edit must structurally exist).
            claims = self._phantom_edit_claims(unit)
            if claims:
                if not unit.get("phantom_retried"):
                    # First offense: the phantom round stays on the record
                    # (invalid evidence) but does not kill the run —
                    # re-run the fixer once with the same queue, exactly
                    # like the JSON repair retry. A second phantom is a
                    # typed failure whose resume restores to FIXING.
                    unit["phantom_retried"] = True
                    st.append_event(
                        self.state,
                        "phantom_fix_retry",
                        unit=st.unit_key(unit),
                        claims="; ".join(claims)[:300],
                    )
                    st.transition_unit(
                        self.state, unit, st.U_FIXING,
                        reason="phantom fix (claims with empty delta); "
                               "retrying fixer",
                    )
                    self._save()
                    return "phantom fix discarded; retrying fixer once"
                st.fail_run(
                    self.state,
                    "fixer on %s claimed edits but the worktree delta is "
                    "empty (nothing was actually changed), twice in a row: "
                    "%s" % (st.unit_key(unit), "; ".join(claims)),
                    unit=unit,
                    type_="phantom_fix",
                )
                self._save()
                raise StopStep("fixer claimed edits with an empty delta")
            unit.pop("phantom_retried", None)
            unit["fix_queue"] = []
            unit["fix_source"] = None
            if return_to in (st.U_PRE_REVIEW_VERIFY, st.U_PRE_SEAL_VERIFY):
                # Zero edits since the gate last proved this tree green:
                # let _do_verify reuse that result instead of re-running
                # a potentially long suite for a bit-identical tree.
                unit["skip_next_verify"] = True
            st.transition_unit(
                self.state, unit, return_to, reason="no delta (fix episode green)"
            )
            return "no pending delta; episode closed"
        try:
            checkpoint_after = int(self.config.get(
                "delta_full_review_after_fixes",
                DEFAULT_CONFIG["delta_full_review_after_fixes"],
            ))
        except (TypeError, ValueError):
            checkpoint_after = DEFAULT_CONFIG[
                "delta_full_review_after_fixes"
            ]
        checkpoint_after = max(0, checkpoint_after)
        dirty_deltas = st.active_fix_dirty_deltas(self.state, unit)
        # One fix is currently pending plus one already-applied fix for every
        # accepted dirty delta in this episode.  Deriving this from immutable
        # history makes Stop/Start and Resume unable to restart the budget;
        # phantom attempts do not count because they produced no dirty delta.
        fix_number = 1 + dirty_deltas
        if (return_to == st.U_ROUNDS
                and checkpoint_after
                and fix_number >= checkpoint_after):
            # The fifth fix has already incorporated the previous delta's
            # known findings.  At this point another diff-only review would
            # inspect a large cumulative patch with less context than the
            # active full reviewer.  Checkpoint the WIP and follow the exact
            # clean-delta return edge; family_index is deliberately untouched.
            try:
                sha = gitops.amend(self.workspace)
            except gitops.GitError as exc:
                st.fail_run(
                    self.state, "delta checkpoint amend failed: %s" % exc,
                    unit=unit,
                )
                self._save()
                raise StopStep(str(exc))
            st.append_event(
                self.state, "amended", unit=st.unit_key(unit), sha=sha
            )
            st.append_event(
                self.state,
                "delta_checkpoint",
                unit=st.unit_key(unit),
                sha=sha,
                fixes=fix_number,
                dirty_deltas=dirty_deltas,
                return_to=return_to,
                review_family=st.current_family(self.state, unit),
            )
            unit["fix_queue"] = []
            unit["fix_source"] = None
            unit.pop("phantom_retried", None)
            st.transition_unit(
                self.state,
                unit,
                return_to,
                reason="delta checkpoint after %d fixes; full review resumes"
                % fix_number,
            )
            return (
                "delta checkpoint after %d fixes; amended (%s); continuing"
                % (fix_number, sha)
            )
        fixer_family = None
        for r in reversed(unit["rounds"]):
            if r["kind"] == contracts.KIND_FIX_FINDINGS:
                fixer_family = r["family"]
                break
        family, delta_model, delta_effort = self._delta_review_profile(
            fixer_family
        )
        project_context, extensions, roots = self._project_prompt_inputs(
            unit, contracts.KIND_DELTA_REVIEW
        )
        prompt = prompts.build_delta_review(
            family,
            self.workspace,
            self._goal_for(unit),
            self._unit_desc(unit),
            delta,
            self._registry(),
            unit_kind=unit["kind"],
            governing=self._governing(unit),
            amendments=self._amendments(),
            project_context=project_context,
            debt=self._debt(unit),
        )
        n_delta = 1 + len(
            [r for r in unit["rounds"] if r["kind"] == contracts.KIND_DELTA_REVIEW]
        )
        output, result, raw_path, changed = self._report_call(
            unit,
            family,
            prompt,
            contracts.KIND_DELTA_REVIEW,
            "%s-delta%d" % (st.unit_key(unit), n_delta),
            extensions=extensions,
            roots=roots,
            # Reform runs hard-require plain/example on every finding;
            # the delta prompt itself is NOT battery-aware (diff-scoped).
            validate_opts=(
                {"require_plain": True}
                if interpreter.reform_active(self.state) else None
            ),
            model=delta_model,
            effort=delta_effort,
        )
        if changed:
            # The pending fix delta and the tampering are now entangled;
            # restoring would destroy the fixer's work. Stop with the facts.
            st.fail_run(
                self.state,
                "delta reviewer (%s) modified the workspace (%s) during a "
                "report-only call; its edits are entangled with the pending "
                "fix delta — operator inspection required"
                % (family, runners.format_changes(changed)),
                unit=unit,
            )
            self._save()
            raise StopStep("delta reviewer tampered")
        self._check_worker_blocked(unit, output, contracts.KIND_DELTA_REVIEW)
        self._validate_contests(unit, output, contracts.KIND_DELTA_REVIEW)
        st.record_round(
            self.state,
            unit,
            family,
            contracts.KIND_DELTA_REVIEW,
            output,
            raw_path=raw_path,
            duration=result.duration_s,
            meta={"model": delta_model, "effort": delta_effort},
        )
        if contracts.findings_clean(output):
            try:
                sha = gitops.amend(self.workspace)
            except gitops.GitError as exc:
                st.fail_run(self.state, "amend failed: %s" % exc, unit=unit)
                self._save()
                raise StopStep(str(exc))
            st.append_event(
                self.state, "amended", unit=st.unit_key(unit), sha=sha
            )
            unit["fix_queue"] = []
            unit["fix_source"] = None
            st.transition_unit(
                self.state, unit, return_to, reason="delta green; amended"
            )
            unit.pop("phantom_retried", None)
            return "delta review clean; amended (%s)" % sha
        # Dirty delta: its findings become the new fix queue (same episode).
        unit["fix_queue"] = [
            {
                "id": f["id"],
                "severity": f["severity"],
                "summary": f["summary"],
                "contests": f.get("contests"),
            }
            for f in output["findings"]
        ]
        source["type"] = "delta"
        source["family"] = family
        source["source_round_id"] = st.family_rounds(unit, family)[-1]["id"]
        unit["fix_source"] = source
        st.transition_unit(
            self.state, unit, st.U_FIXING, reason="delta findings queued"
        )
        return "delta review: %d finding(s); back to the fixer" % len(
            output["findings"]
        )

    def _do_verify(self):
        unit = st.current_unit(self.state)
        stage = unit["status"]
        stage_key = (
            "pre_review" if stage == st.U_PRE_REVIEW_VERIFY else "pre_seal"
        )
        commands = self._verification_commands(unit)
        if unit.pop("skip_next_verify", None) and commands:
            # The fix episode that routed here closed with an EMPTY delta
            # (all findings rejected, zero edits): the tree is bit-
            # identical to the one the last gate proved green, so a
            # 15-minute suite re-run would buy nothing. The reuse is
            # recorded, never silent.
            st.append_event(
                self.state,
                "verification",
                unit=st.unit_key(unit),
                stage=stage,
                ok=True,
                commands=list(commands),
                reused=True,
                output_tail="(reused: empty-delta fix episode, tree "
                            "unchanged since the last green gate)",
            )
            ok = True
        else:
            unit.pop("skip_next_verify", None)
            self._mark_busy(
                "verification (%s)" % stage_key, "verification", None
            )
            try:
                ok, output = run_verification(
                    commands, self.workspace,
                    self.config.get("verification_timeout"),
                )
            finally:
                self._clear_busy()
            st.append_event(
                self.state,
                "verification",
                unit=st.unit_key(unit),
                stage=stage,
                ok=ok,
                commands=list(commands),
                vacuous=(not commands) or None,
                output_tail=(output or "")[-2000:],
            )
        if ok:
            # The cap bounds consecutive fix attempts for the CURRENT
            # failing stage; a pass closes the episode.
            unit["verify_fix_attempts"][stage_key] = 0
            if stage == st.U_PRE_REVIEW_VERIFY:
                st.transition_unit(self.state, unit, st.U_ROUNDS, reason="verified")
            else:
                if not st.can_open_seal(self.state, unit):
                    st.fail_run(
                        self.state,
                        "pre-seal verification passed but not every family has "
                        "a recorded clean round; state is inconsistent",
                        unit=unit,
                    )
                    self._save()
                    raise StopStep("seal gate violation")
                st.transition_unit(self.state, unit, st.U_SEALING, reason="verified")
            return "verification ok (%d command(s))" % len(commands)
        unit["verify_fix_attempts"][stage_key] += 1
        if unit["verify_fix_attempts"][stage_key] > self.config["max_verify_fix_attempts"]:
            st.fail_run(
                self.state,
                "%s verification still failing after %d fix attempts; last "
                "output tail: %s"
                % (
                    stage_key.replace("_", "-"),
                    self.config["max_verify_fix_attempts"],
                    (output or "")[-1500:],
                ),
                unit=unit,
            )
            self._save()
            raise StopStep("verification fix attempts exhausted")
        unit["last_verification_output"] = (output or "")[-4000:]
        # The synthetic episode id must stay unique for the unit's whole
        # life: verify_fix_attempts resets whenever the stage passes, but a
        # stage can be RE-ENTERED later (every dirty seal attempt returns
        # to pre-seal verification), and a colliding id would mint two
        # adjudication registry entries with the same id if V1 is rejected
        # in both episodes. A dedicated never-reset sequence numbers the
        # episodes instead (setdefault: field absent in pre-existing
        # states).
        seq = unit.setdefault(
            "verify_episode_seq", {"pre_review": 0, "pre_seal": 0}
        )
        seq[stage_key] += 1
        n_episode = seq[stage_key]
        st.enter_fix_episode(
            self.state,
            unit,
            [
                {
                    "id": "V1",
                    "severity": "P1",
                    "summary": "the verification suite failed (see the "
                    "verification output in this prompt)",
                }
            ],
            "verification",
            None,
            "%s-verify-%s-%d" % (st.unit_key(unit), stage_key, n_episode),
            stage,
        )
        return "verification failed; findings queued for the fixer"

    def _partition_defer_candidates(self, unit, items):
        """Rate candidates independently and split debt from fix work.

        `items` is a list of (finding, raising_family). Returns
        (debt_entries, retained_items). A refused/failed rating retains only
        that finding for the fixer; one serious finding can never drag other,
        independently deferred findings into the fix queue. A tampering
        reclassifier voids every rating and retains the whole input.
        """
        before = self._snapshot()
        debt = []
        retained = []
        levels = contracts.DRIFT_RISK_LEVELS
        threshold = str(self.config.get("p3_defer_max_risk") or "low")
        if threshold not in levels:
            threshold = "low"
        self._mark_busy(
            "%s-reclassify (%d finding(s))" % (st.unit_key(unit), len(items)),
            contracts.KIND_RECLASSIFY, None,
        )
        try:
            acts_merged = dict(self.config.get("acts") or {})
            for k, v in self._acts_overlay().items():
                if v:
                    acts_merged[k] = v
            raw_policy = acts_merged.get("reclassifier")
            if isinstance(raw_policy, dict):
                raw_policy = (raw_policy.get("agent")
                              or raw_policy.get("family") or "").strip()
            explicit = bool(raw_policy) and raw_policy not in ("opposite",)
            for finding, raising_family in items:
                opp, rater_model, rater_effort = self._act_profile(
                    "reclassifier", origin_family=raising_family,
                    default_family=self._opposite(raising_family),
                )
                defer_ok, reason = False, "reclassification unavailable"
                risk = None
                damage = None
                duration_s = None
                if opp == raising_family and not explicit:
                    # No independent opposite family (single-family config):
                    # cross-family verification is impossible, so the finding
                    # is never deferred — it takes the normal fix path. An
                    # EXPLICIT fixed/self policy is the operator choosing a
                    # same-family rater on purpose — allowed (a fresh
                    # stateless call is still a second look).
                    reason = "no independent reclassifier (single family)"
                else:
                    # Finding ids are arbitrary reviewer strings; sanitize
                    # the raw-filename component so an id with a path
                    # separator cannot make _save_raw raise.
                    safe_id = "".join(
                        c if (c.isalnum() or c in "_.-") else "_"
                        for c in str(finding.get("id", ""))
                    )[:64] or "f"
                    pc, _rx, _rr = self._project_prompt_inputs(
                        unit, contracts.KIND_RECLASSIFY
                    )
                    # Reform runs: the rater judges for the run's REAL
                    # builders and knows their stop-report-repair exit —
                    # the reform's bargain (tolerate more in docs BECAUSE
                    # the builder can come back), encoded in the judge.
                    # Legacy/profile-less prompts stay byte-identical.
                    builder_desc = None
                    gap_backstop = interpreter.gap_semantics(self.state)
                    if gap_backstop:
                        builder_desc = self._builders_desc()
                    prompt = prompts.build_reclassify(
                        opp, self.workspace, finding, self._artifact(unit),
                        unit_kind=unit["kind"], amendments=self._amendments(),
                        project_context=pc,
                        builder_desc=builder_desc, gap_backstop=gap_backstop,
                        two_axis=gap_backstop,
                    )
                    raw_name = "%s-reclassify-%s-%s" % (
                        st.unit_key(unit), raising_family, safe_id)
                    try:
                        dm, de = self._family_defaults(opp)
                        output, result = runners.call_worker(
                            self.runner, opp, prompt,
                            contracts.KIND_RECLASSIFY,
                            self.workspace,
                            model=rater_model or dm,
                            effort=rater_effort or de,
                            validate_opts=(
                                {"require_drift_damage": True}
                                if gap_backstop else None
                            ),
                        )
                        self._save_raw(raw_name, result.text)
                        duration_s = result.duration_s
                        self._record_repair(
                            raw_name, contracts.KIND_RECLASSIFY, opp, result
                        )
                        if output.get("status") == "ok":
                            # The worker only RATES; the deterministic
                            # decision is this comparison against the
                            # run's threshold. Reform runs rate TWO axes
                            # and the decision gates on DAMAGE (operator,
                            # 2026-07-09: probability and damage decide
                            # differently — a self-revealing cheap defect
                            # defers even at high probability; a
                            # destructive one is fixed however unlikely).
                            # Legacy keeps the single-axis risk gate.
                            risk = output.get("drift_risk")
                            damage = output.get("drift_damage")
                            reason = str(output.get("reason") or "")[:300]
                            gate = damage if gap_backstop else risk
                            defer_ok = (
                                gate in levels
                                and levels.index(gate)
                                <= levels.index(threshold)
                            )
                        else:
                            reason = "reclassifier blocked"
                    except (runners.RunnerError,
                            runners.WorkerProtocolError) as exc:
                        self._record_fatal_malformed(
                            raw_name, contracts.KIND_RECLASSIFY, opp, exc,
                            self._save_protocol_raws(raw_name, exc),
                        )
                        reason = ("reclassify call failed: %s" % exc)[:300]
                st.append_event(
                    self.state, "reclassify_recorded",
                    unit=st.unit_key(unit),
                    finding_id="%s-%s" % (raising_family, finding.get("id")),
                    reclassifier=opp, drift_risk=risk,
                    drift_damage=damage, threshold=threshold,
                    defer_ok=defer_ok, reason=reason,
                    duration_s=duration_s,
                )
                if defer_ok:
                    debt.append({
                        "id": "%s-%s" % (raising_family, finding["id"]),
                        "severity": finding.get("severity", "P3"),
                        "summary": finding.get("summary", ""),
                        "raised_by": raising_family,
                        "cleared_by": opp,
                        "drift_risk": risk,
                        "drift_damage": damage,
                        "reason": reason,
                    })
                else:
                    retained.append((finding, raising_family))
        finally:
            self._clear_busy()
        if self._snapshot_diff(before, self._snapshot()):
            # A reclassifier edited the workspace: void any deferral (the
            # reclassify_recorded events above no longer stand) and restore.
            st.append_event(
                self.state, "reclassify_voided", unit=st.unit_key(unit),
                reason="reclassifier modified the workspace; deferral voided",
            )
            self._restore_or_fail(
                unit, "reclassifier modified the workspace")
            return [], list(items)
        return debt, retained

    def _do_review_round(self):
        unit = st.current_unit(self.state)
        family = st.current_family(self.state, unit)
        if family is None:
            raise st.IllegalTransition("rounds status with no family left")
        done = len(
            [
                r
                # Count from the amnesty marker (moved at each resume), not
                # from all history: resume grants a fresh review budget.
                for r in unit["rounds"][unit.get("rounds_amnesty") or 0:]
                if r["family"] == family
                and r["kind"] == contracts.KIND_REVIEW_ROUND
            ]
        )
        if done >= self.config["max_rounds_per_family"]:
            st.fail_run(
                self.state,
                "family %s reached max_rounds_per_family=%d on %s without a "
                "clean round"
                % (family, self.config["max_rounds_per_family"], st.unit_key(unit)),
                unit=unit,
            )
            self._save()
            raise StopStep("round cap")
        project_context, extensions, roots = self._project_prompt_inputs(
            unit, contracts.KIND_REVIEW_ROUND
        )
        # Reform runs: reviewers of doc units check the question battery
        # (presence and substance, never prose — spec §4) and every
        # finding hard-requires its plain/example lay mirror.
        reform = interpreter.reform_active(self.state)
        review_model, review_effort = self._review_profile(family)
        prompt = prompts.build_review_round(
            family,
            self.workspace,
            self._goal_for(unit),
            self._unit_desc(unit),
            self._artifact(unit),
            self._registry(),
            unit_kind=unit["kind"],
            governing=self._governing(unit),
            amendments=self._amendments(),
            verified_suite=self._verified_suite(unit),
            project_context=project_context,
            battery=interpreter.battery_questions(self.state, unit["kind"]),
            debt=self._debt(unit),
        )
        # Raw/label numbering counts ALL history (like fix/delta and the
        # ledger round ids): the amnesty-relative `done` must never make a
        # new raw file reuse — and overwrite — a historical round's name.
        label_no = 1 + len(
            [
                r
                for r in st.family_rounds(unit, family)
                if r["kind"] == contracts.KIND_REVIEW_ROUND
            ]
        )
        output, result, raw_path, changed = self._report_call(
            unit,
            family,
            prompt,
            contracts.KIND_REVIEW_ROUND,
            "%s-%s-r%d" % (st.unit_key(unit), family, label_no),
            extensions=extensions,
            roots=roots,
            validate_opts={"require_plain": True} if reform else None,
            model=review_model,
            effort=review_effort,
        )
        if changed:
            # Rounds run on a clean worktree (everything is amended), so a
            # tampering reviewer is fully revertible: restore, discard the
            # output, record the incident as an invalidated round (it
            # counts toward the family's cap), retry next step.
            self._restore_or_fail(
                unit, "review round reviewer (%s) tampered" % family
            )
            st.record_round(
                self.state,
                unit,
                family,
                contracts.KIND_REVIEW_ROUND,
                {"status": "ok", "kind": contracts.KIND_REVIEW_ROUND,
                 "findings": []},
                raw_path=raw_path,
                duration=result.duration_s,
                meta={
                    "invalidated": "reviewer modified the workspace "
                    "(%s); output discarded, workspace restored"
                    % runners.format_changes(changed),
                    "model": review_model,
                    "effort": review_effort,
                },
            )
            return "%s round INVALID (reviewer edited); restored and retrying" % family
        self._check_worker_blocked(unit, output, contracts.KIND_REVIEW_ROUND)
        self._validate_contests(unit, output, contracts.KIND_REVIEW_ROUND)
        findings = output.get("findings", [])
        # Debt deferral: DOC phase only. The profile chooses the deferrable
        # severity scope (interpreter.doc_defer_scope): legacy/profile-less
        # runs rate P3; reform runs rate P2/P3. P0/P1 always fix. Candidates
        # are rated independently: one serious finding must not drag cheap,
        # accepted debt into the fix queue with it.
        defer_scope = interpreter.doc_defer_scope(self.state)
        deferred = []
        fix_findings = list(findings)
        if (findings
                and self.config.get("p3_reclassify_debt")
                and unit["kind"] in (st.UNIT_SKELETON, st.UNIT_SLICE_DOC)):
            candidates = [
                (f, family) for f in findings
                if f.get("severity") in defer_scope
            ]
            if candidates:
                deferred, retained = self._partition_defer_candidates(
                    unit, candidates)
                retained_ids = {f.get("id") for f, _family in retained}
                fix_findings = [
                    f for f in findings
                    if (f.get("severity") not in defer_scope
                        or f.get("id") in retained_ids)
                ]
        round_meta = {"model": review_model, "effort": review_effort}
        if deferred and not fix_findings:
            round_meta["deferred_clean"] = True
        rec = st.record_round(
            self.state, unit, family, contracts.KIND_REVIEW_ROUND, output,
            raw_path=raw_path, duration=result.duration_s,
            meta=round_meta,
        )
        if deferred:
            st.record_debt(self.state, unit, deferred, "round", rec["id"])
        if not findings:
            st.advance_family_if_clean(self.state, unit, output)
            return "%s round: clean" % family
        if not fix_findings:
            st.advance_family_deferred(self.state, unit)
            return ("%s round: %d finding(s) deferred as debt (verified by %s)"
                    % (family, len(deferred), self._opposite(family)))
        st.enter_fix_episode(
            self.state,
            unit,
            [
                {
                    "id": f["id"],
                    "severity": f["severity"],
                    "summary": f["summary"],
                    "contests": f.get("contests"),
                }
                for f in fix_findings
            ],
            "round",
            family,
            rec["id"],
            st.U_ROUNDS,
        )
        return ("%s round: %d finding(s) queued for the fixer; %d deferred"
                % (family, len(fix_findings), len(deferred)))

    def _seal_families(self, unit, attempt_no):
        """Families that run a seal half this attempt.

        On the FIRST attempt the frozen candidate is byte-identical to what
        every family just reviewed clean — a1 opens only after every family's
        review round is clean and a read-only pre-seal verify. So the last
        reviewer (families_order[-1], whose round immediately preceded the
        seal) is re-reviewing the exact bytes it just blessed; empirically its
        a1 half never fires while the first family's fresh pass still catches
        real defects. single_seal_first_attempt therefore drops that last
        half on a1 only. Any finding reopens the unit and a2+ runs the full
        double seal, because the artifact has by then changed. Never reduces
        below one family (single-family configs keep their only sealer)."""
        families = self.config["families_order"]
        if (attempt_no == 1
                and self.config.get("single_seal_first_attempt")
                and len(families) > 1):
            return families[:-1]
        return families

    def _do_seal_attempt(self):
        unit = st.current_unit(self.state)
        # The cap counts from the amnesty marker (moved at each resume);
        # attempt numbering below stays global over the full history.
        seals_done = len(unit["seals"]) - (unit.get("seals_amnesty") or 0)
        if seals_done >= self.config["max_seal_attempts"]:
            st.fail_run(
                self.state,
                "max_seal_attempts=%d reached on %s"
                % (self.config["max_seal_attempts"], st.unit_key(unit)),
                unit=unit,
            )
            self._save()
            raise StopStep("seal cap")
        attempt_no = len(unit["seals"]) + 1
        all_families = self.config["families_order"]
        # Reform seal PREDICATE (spec §5): the review rounds already carry
        # every family's whole-artifact judgment. If each family's most
        # recent review is clean on the CURRENT bytes (no fix changed them
        # after it), the dedicated seal-half re-reads would re-read bytes
        # the family already blessed — redundant. Seal directly and cite
        # the satisfying reviews; zero seal calls. When a family's look is
        # stale (a later fix changed the bytes) the predicate returns None
        # and we fall through to the proven double-seal halves, which give
        # exactly that family its fresh look. Legacy and profile-less runs
        # never take this path (bit-identical).
        stale_only = None
        if interpreter.seal_predicate(self.state):
            cite = st.seal_predicate_reviews(unit, all_families)
            if cite is not None:
                st.record_seal_attempt(self.state, unit, {}, True)
                st.append_event(
                    self.state, "seal_satisfied", unit=st.unit_key(unit),
                    attempt=attempt_no, reviews=cite,
                )
                st.transition_unit(
                    self.state, unit, st.U_SEALED,
                    reason="seal predicate satisfied (%s)" % ", ".join(cite),
                )
                self._after_seal(unit)
                return (
                    "%s sealed by predicate — every family's review is "
                    "clean on the current bytes (%s); no seal calls"
                    % (st.unit_key(unit), ", ".join(cite))
                )
            # Predicate not satisfied: only the STALE families owe a
            # fresh look (spec §5 — refined fallback, 2026-07-09); a
            # family clean on the current bytes stands on its cited
            # review instead of re-reading bytes it just blessed. After
            # a fix+amend every family is stale, so a post-fix reseal
            # degrades to the full double automatically.
            stale_only = st.stale_seal_families(unit, all_families)
        if stale_only is not None:
            families, fresh_cites = stale_only
            if fresh_cites:
                st.append_event(
                    self.state, "seal_stale_only",
                    unit=st.unit_key(unit), attempt=attempt_no,
                    ran=list(families), standing=fresh_cites,
                )
        else:
            families = self._seal_families(unit, attempt_no)
            if families != all_families:
                st.append_event(
                    self.state, "seal_single_first_attempt",
                    unit=st.unit_key(unit), attempt=attempt_no,
                    ran=list(families),
                    skipped=[f for f in all_families if f not in families],
                )
        goal = self._goal_for(unit)
        desc = self._unit_desc(unit)
        artifact = self._artifact(unit)
        registry = self._registry()
        debt = self._debt(unit)
        review_profiles = {
            family: self._review_profile(family) for family in families
        }
        halves = {}
        invalidated = None
        tamper_family = None  # sequential mode can attribute the tampering
        amendments = self._amendments()  # once, before any half thread
        verified_suite = self._verified_suite(unit)
        # A seal attempt is ONE judgment surface: selection/compile/meta
        # run once here, in the main thread (fail-closed before any half
        # runs; the seen ledger gains at most one event per pair), and
        # both halves share the snapshot — an edit between sequential
        # halves binds the next call after the attempt, never the second
        # half. Same once-before-half-threads pattern as amendments.
        project_context, project_extensions, project_roots = (
            self._project_prompt_inputs(unit, contracts.KIND_SEAL_HALF)
        )
        # Reform gates for the halves, computed once on the main thread
        # (same once-before-half-threads pattern as amendments): doc-unit
        # sealers check the question battery, and every finding
        # hard-requires its plain/example lay mirror.
        seal_battery = interpreter.battery_questions(
            self.state, unit["kind"]
        )
        seal_validate_opts = (
            {"require_plain": True}
            if interpreter.reform_active(self.state) else None
        )

        def run_half_pure(family):
            """One seal half, mutating NO shared state (thread-safe): any
            failure raises _SealHalfFailure; raw outputs go to per-family
            files only."""
            prompt = prompts.build_seal_half(
                family, self.workspace, goal, desc, artifact, registry,
                unit_kind=unit["kind"], governing=self._governing(unit),
                amendments=amendments, verified_suite=verified_suite,
                project_context=project_context, battery=seal_battery,
                debt=debt,
            )
            raw_name = "%s-seal-a%d-%s" % (st.unit_key(unit), attempt_no, family)
            try:
                review_model, review_effort = review_profiles[family]
                output, result = runners.call_worker(
                    self.runner,
                    family,
                    prompt,
                    contracts.KIND_SEAL_HALF,
                    self.workspace,
                    model=review_model,
                    effort=review_effort,
                    extensions=project_extensions,
                    roots=project_roots,
                    validate_opts=seal_validate_opts,
                )
            except verifiers.VerifierError as exc:
                # Slice 4's non-repairable family (operator/environment,
                # never the worker); no state mutation here — the caller
                # records the failure.
                raise _SealHalfFailure(
                    "%s call: project standing-law fault (never the "
                    "worker's): %s" % (contracts.KIND_SEAL_HALF, exc),
                    family=family,
                )
            except (runners.RunnerError, runners.WorkerProtocolError) as exc:
                proto_paths = self._save_protocol_raws(raw_name, exc)
                raise _SealHalfFailure(
                    "%s call failed: %s" % (contracts.KIND_SEAL_HALF, exc),
                    raw_texts=list(getattr(exc, "raw_texts", []) or [])
                    + [str(exc)],
                    family=family,
                    protocol_raw_paths=proto_paths,
                    protocol_label=raw_name,
                )
            raw_path = self._save_raw(raw_name, result.text)
            if output["status"] == "blocked":
                raise _SealHalfFailure(
                    "%s worker blocked: %s"
                    % (contracts.KIND_SEAL_HALF, output.get("blocked_reason"))
                )
            half = {
                "result": output,
                "raw_path": raw_path,
                "duration_s": result.duration_s,
                "workspace_modified": False,
                "model": review_profiles[family][0],
                "effort": review_profiles[family][1],
            }
            rep = getattr(result, "repair", None)
            if rep:
                # Thread-safe part only: write the per-family raw file
                # (distinct names, no race) and stash the strike; the
                # main thread emits the worker_malformed event after the
                # halves join (events must never be appended from half
                # threads).
                half["repair"] = {
                    "label": raw_name,
                    "error": str(rep["error"])[:300],
                    "duration_s": rep["duration_s"],
                    "raw_path": self._save_raw(
                        "%s-malformed" % raw_name, rep["raw_text"]
                    ),
                }
            return half

        def fail_attempt(reason, raw_texts=None, failed_family=None):
            # Runs on the main thread (sequential path directly; concurrent
            # path only after every half has joined), so _save_raw here never
            # races the seal worker threads.
            etype, resume_at, evidence = "unknown", None, None
            if raw_texts:
                etype, resume_at, evidence = errclass.classify_failure(
                    raw_texts,
                    runner=self.runner,
                    opposite_family=self._opposite(
                        failed_family or families[0]
                    ),
                    workspace=self.workspace,
                    use_llm=bool(self.config.get("error_classifier", True)),
                    on_llm_raw=self._classify_raw_saver(
                        "%s-seal-a%d-classify"
                        % (st.unit_key(unit), attempt_no)
                    ),
                )
                resume_at = errclass.normalize_resume_at(resume_at)
                if etype in errclass.AUTO_RESUMABLE and not resume_at:
                    fallback_min = (
                        30 if etype == "quota"
                        else errclass.TRANSIENT_BACKOFF_MIN
                    )
                    resume_at = errclass.parse_resume_at(
                        "in %d minutes" % fallback_min
                    )
            st.fail_run(self.state, reason, unit=unit, type_=etype,
                        resume_at=resume_at, evidence=evidence)
            self._save()
            raise StopStep(reason)

        if len(families) > 1 and self.config.get("seal_concurrent"):
            # Parallelize only when there is more than one half to run: a lone
            # a1 half has nothing to parallelize and takes the direct path.
            before = self._snapshot()
            errors = {}
            error_excs = []
            error_raws = []

            def worker(fam):
                # Worker threads never touch driver state: mutating and
                # saving shared state from here would race (duplicate
                # run_failed events, clashing event seqs, overwritten
                # failure reasons). Everything is reported back to the
                # main thread instead — including unexpected crashes,
                # which must never let the attempt pass on fewer halves.
                try:
                    halves[fam] = run_half_pure(fam)
                except _SealHalfFailure as exc:
                    errors[fam] = str(exc)
                    error_excs.append(exc)
                    error_raws.extend(exc.raw_texts)
                except Exception as exc:  # a dead thread must fail the run
                    errors[fam] = "seal half crashed: %r" % (exc,)

            threads = [
                threading.Thread(target=worker, args=(fam,)) for fam in families
            ]
            self._mark_busy(
                "%s-seal-a%d (%s)"
                % (st.unit_key(unit), attempt_no, "+".join(families)),
                contracts.KIND_SEAL_HALF,
                None,
            )
            try:
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            finally:
                self._clear_busy()
            if errors:
                for e in error_excs:
                    self._emit_seal_protocol_event(e)
                fail_attempt(
                    "concurrent seal attempt failed: "
                    + "; ".join(
                        "%s: %s" % (fam, errors[fam]) for fam in sorted(errors)
                    ),
                    raw_texts=error_raws,
                    failed_family=sorted(errors)[0],
                )
            changed = self._snapshot_diff(before, self._snapshot())
            if changed:
                for fam in halves:
                    halves[fam]["workspace_modified"] = True
                invalidated = (
                    "workspace changed during concurrent seal attempt (%s); "
                    "cannot attribute; attempt invalid"
                    % runners.format_changes(changed)
                )
        else:
            snap = self._snapshot()
            for fam in families:
                self._mark_busy(
                    "%s-seal-a%d-%s" % (st.unit_key(unit), attempt_no, fam),
                    contracts.KIND_SEAL_HALF,
                    fam,
                    model=review_profiles[fam][0],
                    effort=review_profiles[fam][1],
                )
                try:
                    halves[fam] = run_half_pure(fam)
                except _SealHalfFailure as exc:
                    self._emit_seal_protocol_event(exc)
                    fail_attempt(str(exc), raw_texts=exc.raw_texts,
                                 failed_family=exc.family)
                finally:
                    self._clear_busy()
                new_snap = self._snapshot()
                changed = self._snapshot_diff(snap, new_snap)
                if changed:
                    halves[fam]["workspace_modified"] = True
                    invalidated = (
                        "seal half %s modified the workspace (%s); its "
                        "output is invalid and the attempt does not count "
                        "as evidence"
                        % (fam, runners.format_changes(changed))
                    )
                    tamper_family = fam
                    snap = new_snap

        if set(halves) != set(families):
            # Defense in depth: a seal attempt must never be judged on
            # fewer halves than configured families.
            fail_attempt(
                "seal attempt %d lost half(s) for: %s"
                % (attempt_no, ", ".join(sorted(set(families) - set(halves))))
            )
        for fam in families:
            # Main-thread emission of any half's repaired first strike
            # (stashed thread-safely in run_half_pure); popped so the
            # seal record itself stays exactly its historical shape.
            rep = halves[fam].pop("repair", None)
            if rep:
                st.append_event(
                    self.state, "worker_malformed",
                    unit=st.unit_key(unit),
                    label=rep["label"], kind=contracts.KIND_SEAL_HALF,
                    family=fam, error=rep["error"],
                    duration_s=rep["duration_s"], raw_path=rep["raw_path"],
                )
        clean = all(
            contracts.findings_clean(halves[fam]["result"]) for fam in families
        )
        # Debt at seal is DOC-only, exactly like review-round debt. An
        # implementation finding always reopens the normal fixer flow: code
        # is either repaired or the finding is explicitly rejected, never
        # parked as debt at the final gate.
        seal_findings = [
            (f, fam)
            for fam in families
            for f in halves[fam]["result"].get("findings", [])
        ]
        defer_scope = (
            interpreter.doc_defer_scope(self.state)
            if unit["kind"] in (st.UNIT_SKELETON, st.UNIT_SLICE_DOC)
            else ()
        )
        deferred = []
        fix_seal_findings = list(seal_findings)
        if (defer_scope and not clean and invalidated is None
                and self.config.get("p3_reclassify_debt")):
            candidates = [
                (f, fam) for f, fam in seal_findings
                if f.get("severity") in defer_scope
            ]
            if candidates:
                deferred, retained = self._partition_defer_candidates(
                    unit, candidates)
                retained_ids = {
                    (fam, f.get("id")) for f, fam in retained
                }
                fix_seal_findings = [
                    (f, fam) for f, fam in seal_findings
                    if (f.get("severity") not in defer_scope
                        or (fam, f.get("id")) in retained_ids)
                ]
        passed = (clean or not fix_seal_findings) and invalidated is None
        st.record_seal_attempt(self.state, unit, halves, passed, invalidated)
        if deferred:
            st.record_debt(
                self.state, unit, deferred, "seal",
                "%s-seal-a%d" % (st.unit_key(unit), attempt_no))
        if passed:
            seal_kind = "single seal" if len(families) == 1 else "double seal"
            st.transition_unit(
                self.state, unit, st.U_SEALED,
                reason=("%s clean" % seal_kind if not deferred
                        else "%s: %d finding(s) deferred as debt"
                        % (seal_kind, len(deferred))))
            self._after_seal(unit)
            return "seal attempt %d PASSED (%s); %s sealed" % (
                attempt_no,
                "clean" if not deferred
                else "%d finding(s) deferred as debt" % len(deferred),
                st.unit_key(unit))
        if invalidated is not None:
            # Seals run on a clean worktree (everything amended), so a
            # tampering half is fully revertible: restore the sealed
            # candidate commit and retry a full attempt (one attempt spent).
            self._restore_or_fail(unit, "seal half tampered")
            return "seal attempt %d INVALID: %s (workspace restored)" % (
                attempt_no,
                invalidated,
            )
        for fam in families:
            self._validate_contests(
                unit, halves[fam]["result"], contracts.KIND_SEAL_HALF
            )
        merged = [
            {
                "id": "%s-%s" % (fam, f["id"]),
                "severity": f["severity"],
                "summary": "[%s seal half] %s" % (fam, f["summary"]),
                "contests": f.get("contests"),
            }
            for f, fam in fix_seal_findings
        ]
        st.enter_fix_episode(
            self.state,
            unit,
            merged,
            "seal",
            None,
            "%s-seal-a%d" % (st.unit_key(unit), attempt_no),
            st.U_PRE_SEAL_VERIFY,
        )
        return ("seal attempt %d: %d finding(s) queued for the fixer; "
                "%d deferred" % (attempt_no, len(merged), len(deferred)))

    def _after_seal(self, unit):
        if unit["kind"] == st.UNIT_SLICE_IMPL:
            st.close_slice(self.state, unit)
        self._gate_commit(unit)
        nxt = st.ensure_next_unit(self.state)
        if nxt is None and st.maybe_close_milestone(self.state):
            self._final_commit()

    def _gate_message(self, unit):
        if unit["kind"] == st.UNIT_SKELETON:
            return "Seal milestone skeleton"
        if unit["kind"] == st.UNIT_SLICE_DOC:
            return "Seal slice %02d note" % unit["slice_id"]
        return "Seal slice %02d implementation and close" % unit["slice_id"]

    def _gate_commit(self, unit):
        """The canon's commit-the-sealed-unit rule, executed by code: the
        generated ledgers are folded in and the unit's amended wip commit
        is finalized under the canonical gate message."""
        if not gitops.enabled(self.config):
            return
        try:
            ledgers.generate(self.state, self.workspace)
            sha = gitops.finalize_gate(self.workspace, self._gate_message(unit))
        except (gitops.GitError, ledgers.LedgerError, OSError) as exc:
            # A hostile/malformed index file must become a RECORDED run
            # failure — an unhandled crash here would discard the sealed
            # transition still in memory and livelock re-burning seals.
            st.fail_run(self.state, "gate commit failed: %s" % exc, unit=unit)
            self._save()
            raise StopStep(str(exc))
        unit["gate_commit"] = sha
        st.append_event(
            self.state,
            "gate_commit",
            unit=st.unit_key(unit),
            sha=sha,
            message=self._gate_message(unit),
        )

    def _final_commit(self):
        if not gitops.enabled(self.config):
            return
        try:
            ledgers.generate(self.state, self.workspace)
            sha = gitops.commit_plain(self.workspace, "Close milestone")
        except (gitops.GitError, ledgers.LedgerError, OSError) as exc:
            st.fail_run(self.state, "close commit failed: %s" % exc)
            self._save()
            raise StopStep(str(exc))
        if sha:
            st.append_event(self.state, "gate_commit", unit=None, sha=sha,
                            message="Close milestone")


class StopStep(RuntimeError):
    """Raised by executors after fail_run() has recorded the explanation."""


def run_verification(commands, workspace, timeout):
    """Run every verification command; returns (all_ok, combined_output).

    Commands may be worker-discovered strings (suite_command), so they run
    with the same stop semantics as workers: own session, tracked so the
    driver's SIGTERM handler SIGKILLs the whole group (a TERM-trapping or
    hung suite must not survive the Stop button), stdin closed and CI=1
    set so watch-mode/interactive runners run once and exit. Execution
    assumes the operator already trusts workers with full permissions;
    sandboxed-worker configs must set explicit config verification
    instead of relying on discovery."""
    if not commands:
        return True, "(no verification configured)"
    env = dict(os.environ)
    env.setdefault("CI", "1")
    chunks = []
    for cmd in commands:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            start_new_session=True,
        )
        runners._track_worker(proc)
        try:
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                runners._kill_group(proc)
                proc.communicate()
                chunks.append("$ %s\nTIMEOUT after %ss" % (cmd, timeout))
                return False, "\n".join(chunks)
        finally:
            runners._untrack_worker(proc)
        chunks.append(
            "$ %s\nexit=%d\n%s%s" % (cmd, proc.returncode, out, err)
        )
        if proc.returncode != 0:
            return False, "\n".join(chunks)
    return True, "\n".join(chunks)


# ---------------------------------------------------------------------------
# CLI


def default_state_path(workspace, docs_dir=None):
    """Where a run's state (and its sibling runtime: raw/, amendments.json,
    acts.json, current.json) lives.

    New milestones (a per-milestone docs_dir like
    implementation/milestones/<slug>) keep their runtime INSIDE the
    milestone directory, in a gitignored `.run/` subdir — so each milestone
    is self-contained and a new run never collides with a closed one.
    Legacy flat-`docs` runs keep the historical workspace-root
    `.orchestrator/` location. Runtime is always the state file's own
    directory, so both layouts work with the same driver code."""
    if docs_dir and os.path.normpath(docs_dir) not in ("", ".", "docs"):
        return os.path.join(workspace, docs_dir, ".run", "state.json")
    return os.path.join(workspace, ".orchestrator", "state.json")


# Init-specific project refusal causes. Causes raised out of Slice 2's
# validation/read seams reuse the workareas vocabulary verbatim
# (invalid_project, invalid_name, unknown_work_area, malformed_work_area,
# work_area_not_ready); an invalid defaults object reuses
# projects.INVALID_DEFAULTS. Only the causes no store seam owns are minted
# here.
WORKSPACE_MISMATCH = "workspace_mismatch"
MISSING_PRIMARY_PATH = "missing_primary_path"

_BINDING_REQUIRED_KEYS = ("directory", "project", "work_area")


class ProjectResolutionError(RuntimeError):
    """A project binding handed to init_run could not be resolved. Raised
    BEFORE anything is created — no state file, no directory, no KV write —
    so a refused init leaves nothing to resume or clean up. `cause` carries
    one machine-readable reason (Slice 2's validation/read vocabulary,
    projects.INVALID_DEFAULTS, or the init-specific WORKSPACE_MISMATCH /
    MISSING_PRIMARY_PATH) so the service launcher can map project refusals
    to 400-class API errors without string-matching. Deliberately distinct
    from FileExistsError (state already exists — also unchanged)."""

    def __init__(self, cause, message):
        RuntimeError.__init__(self, message)
        self.cause = cause


def _resolve_project_binding(binding, workspace, config_override):
    """Resolve a (project, work_area) binding through Slice 2's sealed
    READY-gated seam (WorkAreaStore.resolve), READ-ONLY: a successful
    resolution writes no KV entry and creates no directory (the store is
    not even opened until the pure validations pass and its project
    directory is known to exist). Returns (workspace, project_block,
    effective_config):

    - workspace: the resolved work area's primary.path — the repo the
      driver owns and executes in. A caller-supplied workspace must equal
      it EXACTLY (no symlink-resolving or normalizing comparison is
      attempted: ambiguity refuses);
    - project_block: {directory, project, work_area, primary, additional}
      — the state seam Slices 6 and 8 consume, roots verbatim in Slice 2's
      public {path, device} shape;
    - effective_config: DEFAULT_CONFIG <- binding defaults <-
      config_override, each applied with merge_config (the single merge
      source): launch intent wins over standing project defaults, which
      win over built-ins.
    """
    if not isinstance(binding, dict):
        raise ValueError("project binding must be a dict")
    unknown = sorted(set(binding) - set(_BINDING_REQUIRED_KEYS) - {"defaults"})
    if unknown:
        raise ValueError("project binding has unknown keys: %s" % unknown)
    missing = [k for k in _BINDING_REQUIRED_KEYS if k not in binding]
    if missing:
        raise ValueError("project binding is missing keys: %s" % missing)
    directory = binding["directory"]
    if not isinstance(directory, str) or not directory.strip():
        raise ValueError(
            "project binding directory must be a non-empty string"
        )
    directory = os.path.abspath(directory)

    try:
        project = workareas.validate_project_slug(binding["project"])
        work_area = workareas.validate_name(binding["work_area"])
    except workareas.WorkAreaValidationError as exc:
        raise ProjectResolutionError(
            exc.reason, "invalid project binding: %s" % exc.reason
        ) from exc

    # Defaults are validated before any store access so every refusal —
    # this one included — creates nothing (opening the KV would
    # materialize the project directory and its lock file).
    defaults = None
    if "defaults" in binding:
        try:
            if not isinstance(binding["defaults"], dict):
                raise ValueError("defaults must be a JSON object")
            defaults = kvstore.canonical_json_value(binding["defaults"])
        except ValueError as exc:
            raise ProjectResolutionError(
                projects.INVALID_DEFAULTS,
                "project defaults must be a JSON-plain object: %s" % exc,
            ) from exc

    if not os.path.isdir(os.path.join(directory, project)):
        raise ProjectResolutionError(
            workareas.UNKNOWN,
            "project %r has no work-area store under %s"
            % (project, directory),
        )
    resolved = workareas.WorkAreaStore(directory, project).resolve(work_area)
    if not resolved.ok:
        raise ProjectResolutionError(
            resolved.reason,
            "cannot resolve work area %r of project %r: %s"
            % (work_area, project, resolved.reason),
        )
    primary = resolved.value["primary"]
    additional = resolved.value["additional"]

    if workspace is None:
        workspace = primary["path"]
    elif workspace != primary["path"]:
        raise ProjectResolutionError(
            WORKSPACE_MISMATCH,
            "supplied workspace %r is not work area %r's primary.path %r; "
            "a project-bound run executes in the primary root (omit the "
            "workspace to derive it)" % (workspace, work_area,
                                         primary["path"]),
        )
    if not os.path.isdir(primary["path"]):
        raise ProjectResolutionError(
            MISSING_PRIMARY_PATH,
            "work area %r's primary.path %r is not an existing directory; "
            "init never fabricates the executed repo"
            % (work_area, primary["path"]),
        )

    config = load_config(None)
    if defaults is not None:
        merge_config(config, defaults)
    if config_override:
        merge_config(config, config_override)
    project_block = {
        "directory": directory,
        "project": project,
        "work_area": work_area,
        "primary": primary,
        "additional": additional,
    }
    return workspace, project_block, config


def init_run(goal, workspace=None, config=None, state_path=None, name=None,
             project=None, config_override=None):
    """Create a new run state. `config` is a merged config dict (see
    load_config) or None for defaults. Returns the state path.
    Raises FileExistsError instead of overwriting an existing state; the
    claim is atomic (st.save_new, exclusive hard link), so two concurrent
    inits of the same workspace cannot both win — no exists() TOCTOU.

    `project` (optional) binds the run to a (project, work_area) pair:
    {"directory": <service-level store dir>, "project": <slug>,
    "work_area": <name>} plus optional "defaults" (the project record's
    standing config conventions). Resolution happens once, here, read-only
    (see _resolve_project_binding): the run's workspace IS the work area's
    primary.path — which must already exist; a bound init never creates
    the executed repo — the resolved block lands in the state document,
    and the ledger records exactly one project_resolved event. A binding
    that cannot be resolved raises ProjectResolutionError and creates
    nothing. Because project defaults must merge BENEATH per-launch
    intent, a bound init takes the launch's own override separately, as
    `config_override`, never pre-merged into `config`. Without a binding,
    behavior is byte-identical to the pre-project seam."""
    if project is not None:
        if config is not None:
            raise ValueError(
                "project-bound init orders project defaults beneath the "
                "launch's own intent; pass the launch override as "
                "config_override, not a pre-merged config"
            )
        if config_override is not None and not isinstance(
            config_override, dict
        ):
            raise ValueError("config_override must be a dict")
        workspace, project_block, config = _resolve_project_binding(
            project, workspace, config_override
        )
    else:
        if config_override is not None:
            raise ValueError(
                "config_override applies only to project-bound init; "
                "merge launch overrides into config instead"
            )
        if workspace is None:
            raise ValueError(
                "workspace is required without a project binding"
            )
        project_block = None
        workspace = os.path.abspath(workspace)
        os.makedirs(workspace, exist_ok=True)
        if config is None:
            config = load_config(None)
    template = (config or {}).get("docs_dir") or "docs"
    slug = None
    if "{slug}" in template:
        # New milestones never write into a previous milestone's sealed
        # directory: uniquify the slug until the resolved dir is free.
        base = st.slugify(name)
        slug = base
        k = 1
        while os.path.exists(
            os.path.join(
                workspace,
                os.path.normpath(
                    template.replace("{slug}", slug)
                ).strip("/"),
            )
        ):
            k += 1
            slug = "%s-%d" % (base, k)
    else:
        fixed = os.path.normpath(template).strip("/")
        if fixed != "docs" and os.path.exists(
            os.path.join(workspace, fixed)
        ):
            raise FileExistsError(
                "docs_dir %r already exists in the workspace — a fixed "
                "docs_dir cannot host two milestones; use a {slug} "
                "template or remove/rename the directory" % fixed
            )
    state = st.new_state(goal, workspace, config, name=name, slug=slug,
                         project=project_block)
    st.append_event(state, "initialized", goal=goal)
    if project_block is not None:
        # Frozen ledger shape: payload exactly {project, work_area}, once
        # per run, at init (project-concept.md:254, fixture I10).
        # Exactly-once needs no guard of its own: this is the only append
        # site, save_new's exclusive claim makes init itself exactly-once,
        # and nothing re-resolves after init.
        st.append_event(
            state,
            "project_resolved",
            project=project_block["project"],
            work_area=project_block["work_area"],
        )
    path = state_path or default_state_path(workspace, state.get("docs_dir"))
    st.save_new(path, state)
    return path


def cmd_init(args):
    try:
        path = init_run(
            args.goal,
            args.workspace,
            config=load_config(args.config),
            state_path=args.state,
            name=(
                args.name
                or os.path.basename(
                    os.path.abspath(args.workspace).rstrip("/")
                )
                or "run"
            ),
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("initialized: %s" % path)
    return 0


def resolve_workspace_state(workspace):
    """Locate a run's state file given only the workspace root.

    Prefers the legacy <ws>/.orchestrator/state.json; otherwise finds a
    per-milestone <ws>/<...>/.run/state.json. Raises SystemExit(2) when
    there is no run, or more than one (the operator must then pass --state
    to disambiguate, since one repo can now host several milestones)."""
    workspace = os.path.abspath(workspace)
    legacy = default_state_path(workspace)
    if os.path.isfile(legacy):
        return legacy
    prune = (runners.SNAPSHOT_EXCLUDE_DIRS - {".run"}) | {
        "node_modules", "deps", "_build", "target", "vendor", "build"
    }
    found = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in prune]
        if os.path.basename(root) == ".run" and "state.json" in files:
            found.append(os.path.join(root, "state.json"))
            dirs[:] = []  # do not descend below a runtime dir
    if len(found) == 1:
        return found[0]
    if not found:
        print("error: no run state found under %s (pass --state PATH)"
              % workspace, file=sys.stderr)
    else:
        print("error: %d runs under %s; pass --state PATH to pick one:\n  %s"
              % (len(found), workspace, "\n  ".join(sorted(found))),
              file=sys.stderr)
    raise SystemExit(2)


def _state_path(args):
    if args.state:
        return args.state
    if args.workspace:
        return resolve_workspace_state(args.workspace)
    print(
        "error: pass --state PATH or --workspace DIR to locate the state file",
        file=sys.stderr,
    )
    raise SystemExit(2)


def cmd_status(args):
    state = st.load(_state_path(args))
    summ = st.summary(state)
    if args.json:
        print(json.dumps(summ, indent=2, ensure_ascii=False))
        return 0
    print("goal:      %s" % summ["goal"])
    print("workspace: %s" % summ["workspace"])
    print("milestone: %s" % summ["milestone_status"])
    if summ["failure"]:
        print("FAILED:    %s" % summ["failure"]["reason"])
    for unit in summ["units"]:
        seals = ", ".join(
            "a%d:%s" % (s["attempt"], "pass" if s["passed"] else ("inval" if s["invalidated"] else "fail"))
            for s in unit["seals"]
        )
        print(
            "  %-16s %-18s rounds=%-3d seals=[%s]"
            % (unit["unit"], unit["status"], len(unit["rounds"]), seals)
        )
    nxt = decide(state)
    print("next:      %r" % nxt)
    return 0


def cmd_resume(args):
    path = _state_path(args)
    state = st.load(path)
    try:
        restored = st.resume_run(state)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    st.save(path, state)
    for unit, status in restored.items():
        print("resumed %s -> %s" % (unit, status))
    print("run resumed; relaunch with `run` (or the panel's Start)")
    return 0


def cmd_next(args):
    state = st.load(_state_path(args))
    print(repr(decide(state)))
    return 0


def _install_stop_forwarding():
    """Make SIGTERM (service Stop button, plain `kill`) reach in-flight
    worker CLIs before the driver dies. Workers run in their OWN sessions
    (so timeout kills cannot take the driver down with them), which also
    means a SIGTERM to the driver's group would otherwise orphan a
    full-permission codex/claude process that keeps editing the workspace
    for up to its whole timeout. CLI entry points only; signal handlers can
    only be installed from the main thread."""
    if threading.current_thread() is not threading.main_thread():
        return  # pragma: no cover - embedded use; CLI always hits main thread

    def handler(signum, frame):
        runners.kill_active_worker_groups()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTERM)  # die with the real signal status

    try:
        signal.signal(signal.SIGTERM, handler)
    except ValueError:  # pragma: no cover - non-main thread race
        pass


def cmd_step(args):
    _install_stop_forwarding()
    driver = Driver(_state_path(args))
    try:
        action, note = driver.step()
    except ConcurrentRunError as exc:
        print("CONCURRENT RUN REFUSED: %s" % exc, file=sys.stderr)
        return 2
    print("%r -> %s" % (action, note))
    if action.type == A_FAILED:
        return 2
    return 0


def cmd_run(args):
    _install_stop_forwarding()
    driver = Driver(_state_path(args))
    try:
        code = driver.run(max_steps=args.max_steps)
    except ConcurrentRunError as exc:
        print("CONCURRENT RUN REFUSED: %s" % exc, file=sys.stderr)
        return 2
    summ = st.summary(driver.state)
    if code == 0:
        print("milestone %s" % summ["milestone_status"])
    elif code == 2:
        print("RUN FAILED: %s" % (summ["failure"] or {}).get("reason"))
    else:
        print("stopped after --max-steps")
    return code


def cmd_serve(args):
    from . import webapp

    return webapp.serve(_state_path(args), args.port)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create a new run state")
    p_init.add_argument("--goal", required=True)
    p_init.add_argument("--name", default=None,
                        help="milestone name (slug feeds docs_dir)")
    p_init.add_argument("--workspace", required=True)
    p_init.add_argument("--config", default=None)
    p_init.add_argument("--state", default=None)
    p_init.set_defaults(func=cmd_init)

    for name, func in (
        ("status", cmd_status),
        ("resume", cmd_resume),
        ("next", cmd_next),
        ("step", cmd_step),
        ("run", cmd_run),
        ("serve", cmd_serve),
    ):
        p = sub.add_parser(name)
        p.add_argument("--state", default=None)
        p.add_argument("--workspace", default=None)
        if name == "status":
            p.add_argument("--json", action="store_true")
        if name == "run":
            p.add_argument("--max-steps", type=int, default=1000)
        if name == "serve":
            p.add_argument("--port", type=int, default=8765)
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
