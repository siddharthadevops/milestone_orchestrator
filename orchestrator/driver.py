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
import signal
import subprocess
import sys
import threading
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX: flock degrades to the
    fcntl = None     # staleness check in step(); documented in the README

from . import contracts, errclass, gitops, ledgers, prompts, runners
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
    # Verified against the installed CLIs (2026-07-05): claude accepts
    # explicit ids (claude-fable-5 / claude-opus-4-8 / claude-sonnet-5)
    # and efforts low|medium|high|xhigh|max; codex models come from its
    # live catalog (gpt-5.5 / gpt-5.4 / gpt-5.3-codex-spark /
    # gpt-5.4-mini) with reasoning efforts low|medium|high|xhigh set via
    # `-c model_reasoning_effort=...` (bare value: failed TOML parse
    # falls back to the literal string, per codex --help).
    # claude workers run with background workflows force-disabled
    # (runners.WORKFLOW_DISABLED_ENV): the async workflow model is
    # incompatible with the one-shot call contract.
    "model_defaults": {
        "claude": {"model": "claude-opus-4-8", "effort": "max"},
        "codex": {"model": "gpt-5.5", "effort": "xhigh"},
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
    # (same family as the act's origin: the reviewer whose findings are
    # being fixed, or the fixer whose delta is being reviewed), or
    # "opposite". This release pins the cheap acts to codex for speed.
    # Acts may also be objects: {"agent": "claude", "model": "sonnet",
    # "effort": "high"} — who leads drafting ("drafter": skeleton + slice
    # notes), implementation ("implementer") and fixes ("fixer"), and with
    # which model/effort. Absent drafter/implementer fall back to
    # fix_family (legacy behavior). The operator can hot-edit all of this
    # mid-run via <workspace>/.orchestrator/acts.json (driver re-reads it
    # before every act resolution; reviews/seals stay family-rotated).
    "acts": {"fixer": "codex", "delta_review": "codex",
             "consultation": "opposite"},
    # Fixer+delta iterations allowed per fix episode before failing.
    "max_fix_loops": 6,
    # P3 debt deferral (off by default). When on, a review round (DOC phase
    # only) or a seal (both phases) whose findings are ALL P3 gets an
    # opposite-family reclassification per finding; if every one is verified
    # safe to defer, the P3s are recorded as tracked debt and the unit
    # advances/seals instead of firing a fix cycle. Any P0-P2 present, any
    # delta review, and impl-phase rounds are unaffected (findings fixed
    # normally). A refused verdict or a failed reclassify call sends the
    # findings to the normal fix flow (safe default).
    "p3_reclassify_debt": False,
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

    def __init__(self, message, raw_texts=None, family=None):
        RuntimeError.__init__(self, message)
        self.raw_texts = list(raw_texts or [])
        self.family = family


class Driver(object):
    def __init__(self, state_path, runner=None):
        self.state_path = state_path
        self.state = st.load(state_path)
        self.config = self.state["config"]
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
        said; state.failure keeps only the truncated error strings."""
        for i, text in enumerate(getattr(exc, "raw_texts", []) or [], 1):
            self._save_raw("%s-protoerr%d" % (raw_name, i), text)

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

    def _busy_path(self):
        return os.path.join(self._runtime_dir(), "current.json")

    def _mark_busy(self, label, kind, family):
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

    def _call(self, family, prompt, kind, raw_name, model=None, effort=None):
        """Validated worker call; on protocol/runner failure, fail the run
        with the explanation recorded, then re-raise as StopStep."""
        dm, de = self._family_defaults(family)
        model = model or dm
        effort = effort or de
        retries = self.config.get("infra_retry_backoff_s")
        if retries is None:
            retries = [10, 30]
        attempt = 0
        while True:
            self._mark_busy(raw_name, kind, family)
            try:
                output, result = runners.call_worker(
                    self.runner, family, prompt, kind, self.workspace,
                    model=model, effort=effort,
                )
            except (runners.RunnerError, runners.WorkerProtocolError) as exc:
                self._clear_busy()
                self._save_protocol_raws(raw_name, exc)
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
        return output, result, raw_path

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
        if output["status"] == "blocked":
            st.fail_run(
                self.state,
                "%s worker blocked: %s" % (kind, output.get("blocked_reason")),
                unit=unit,
            )
            self._save()
            raise StopStep(output.get("blocked_reason"))
        blocked = contracts.blocking_findings(output)
        if blocked:
            st.fail_run(
                self.state,
                "%s reported blocked findings needing the operator: %s"
                % (kind, "; ".join(f["summary"] for f in blocked)),
                unit=unit,
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

    def _do_draft(self):
        unit = st.current_unit(self.state)
        act = (
            "implementer" if unit["kind"] == st.UNIT_SLICE_IMPL else "drafter"
        )
        family, model, effort = self._act_profile(act)
        goal = self.state["goal"]
        amendments = self._amendments()
        if unit["kind"] == st.UNIT_SKELETON:
            kind = contracts.KIND_DRAFT_SKELETON
            prompt = prompts.build_draft_skeleton(
                family, self.workspace, goal, amendments=amendments,
                artifact_path=ledgers.skeleton_path(self.state),
            )
        elif unit["kind"] == st.UNIT_SLICE_DOC:
            kind = contracts.KIND_DRAFT_SLICE_NOTE
            sl = self._slice_info(unit["slice_id"])
            prompt = prompts.build_draft_slice_note(
                family, self.workspace, goal, sl, self._skeleton_artifact(),
                amendments=amendments,
                note_path=ledgers.slice_note_path(
                    self.state, unit["slice_id"]
                ),
            )
        else:
            kind = contracts.KIND_IMPLEMENT
            sl = self._slice_info(unit["slice_id"])
            prompt = prompts.build_implement(
                family,
                self.workspace,
                goal,
                sl,
                self._slice_note_artifact(unit["slice_id"]),
                self._verification_commands(unit),
                amendments=amendments,
            )
        output, result, raw_path = self._call(
            family, prompt, kind, "%s-draft" % st.unit_key(unit),
            model=model, effort=effort,
        )
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

    def _report_call(self, unit, family, prompt, kind, raw_name):
        """Run a report-only call with mechanical no-edit enforcement.

        Returns (output, result, raw_path, changed): when the reviewer
        modified the workspace, changed is the non-empty list of paths
        that differ and the output must be discarded by the caller."""
        before = self._snapshot()
        output, result, raw_path = self._call(family, prompt, kind, raw_name)
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
        family, fix_model, fix_effort = self._act_profile(
            "fixer", source.get("family"), default_family="codex"
        )
        consultation_family = self._resolve_act("consultation", family)
        prompt = prompts.build_fix_findings(
            family,
            self.workspace,
            self.state["goal"],
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
        )
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
        fixer_family = None
        for r in reversed(unit["rounds"]):
            if r["kind"] == contracts.KIND_FIX_FINDINGS:
                fixer_family = r["family"]
                break
        family = self._resolve_act("delta_review", fixer_family)
        prompt = prompts.build_delta_review(
            family,
            self.workspace,
            self.state["goal"],
            self._unit_desc(unit),
            delta,
            self._registry(),
            unit_kind=unit["kind"],
            governing=self._governing(unit),
            amendments=self._amendments(),
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

    def _reclassify_p3_batch(self, unit, items):
        """Opposite-family second opinion on deferring lone P3s as debt.

        `items` is a list of (finding, raising_family). Returns
        (all_deferrable, debt_entries). Safe by construction: a refused
        verdict, a blocked/failed reclassify call, or a reclassifier that
        edits the workspace all make the batch non-deferrable (and a
        tampering reclassifier is reverted), so the caller takes the normal
        fix path."""
        before = self._snapshot()
        debt = []
        all_ok = True
        self._mark_busy(
            "%s-reclassify (%d P3)" % (st.unit_key(unit), len(items)),
            contracts.KIND_RECLASSIFY, None,
        )
        try:
            for finding, raising_family in items:
                opp = self._opposite(raising_family)
                defer_ok, reason = False, "reclassification unavailable"
                if opp == raising_family:
                    # No independent opposite family (single-family config):
                    # cross-family verification is impossible, so a P3 is
                    # never deferred — it takes the normal fix path.
                    reason = "no independent reclassifier (single family)"
                else:
                    # Finding ids are arbitrary reviewer strings; sanitize
                    # the raw-filename component so an id with a path
                    # separator cannot make _save_raw raise.
                    safe_id = "".join(
                        c if (c.isalnum() or c in "_.-") else "_"
                        for c in str(finding.get("id", ""))
                    )[:64] or "f"
                    prompt = prompts.build_reclassify(
                        opp, self.workspace, finding, self._artifact(unit),
                        unit_kind=unit["kind"], amendments=self._amendments(),
                    )
                    raw_name = "%s-reclassify-%s-%s" % (
                        st.unit_key(unit), raising_family, safe_id)
                    try:
                        dm, de = self._family_defaults(opp)
                        output, result = runners.call_worker(
                            self.runner, opp, prompt,
                            contracts.KIND_RECLASSIFY,
                            self.workspace, model=dm, effort=de,
                        )
                        self._save_raw(raw_name, result.text)
                        if output.get("status") == "ok":
                            defer_ok = bool(output.get("defer_ok"))
                            reason = str(output.get("reason") or "")[:300]
                        else:
                            reason = "reclassifier blocked"
                    except (runners.RunnerError,
                            runners.WorkerProtocolError) as exc:
                        self._save_protocol_raws(raw_name, exc)
                        reason = ("reclassify call failed: %s" % exc)[:300]
                st.append_event(
                    self.state, "reclassify_recorded",
                    unit=st.unit_key(unit),
                    finding_id="%s-%s" % (raising_family, finding.get("id")),
                    reclassifier=opp, defer_ok=defer_ok, reason=reason,
                )
                if defer_ok:
                    debt.append({
                        "id": "%s-%s" % (raising_family, finding["id"]),
                        "severity": "P3",
                        "summary": finding.get("summary", ""),
                        "raised_by": raising_family,
                        "cleared_by": opp,
                        "reason": reason,
                    })
                else:
                    all_ok = False
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
            return False, []
        return all_ok, debt

    def _do_review_round(self):
        unit = st.current_unit(self.state)
        family = st.current_family(self.state, unit)
        if family is None:
            raise st.IllegalTransition("rounds status with no family left")
        done = len(
            [
                r
                for r in st.family_rounds(unit, family)
                if r["kind"] == contracts.KIND_REVIEW_ROUND
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
        prompt = prompts.build_review_round(
            family,
            self.workspace,
            self.state["goal"],
            self._unit_desc(unit),
            self._artifact(unit),
            self._registry(),
            unit_kind=unit["kind"],
            governing=self._governing(unit),
            amendments=self._amendments(),
            verified_suite=self._verified_suite(unit),
        )
        output, result, raw_path, changed = self._report_call(
            unit,
            family,
            prompt,
            contracts.KIND_REVIEW_ROUND,
            "%s-%s-r%d" % (st.unit_key(unit), family, done + 1),
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
                meta={"invalidated": "reviewer modified the workspace "
                      "(%s); output discarded, workspace restored"
                      % runners.format_changes(changed)},
            )
            return "%s round INVALID (reviewer edited); restored and retrying" % family
        self._check_worker_blocked(unit, output, contracts.KIND_REVIEW_ROUND)
        self._validate_contests(unit, output, contracts.KIND_REVIEW_ROUND)
        findings = output.get("findings", [])
        # P3-debt deferral: DOC phase only, and only a round that is ALL P3
        # (any P0-P2 fires a normal fix and the P3s ride along). Each P3
        # gets an opposite-family reclassification; only if every one is
        # verified safe do we defer them as debt and advance.
        deferred = None
        if (findings
                and self.config.get("p3_reclassify_debt")
                and unit["kind"] in (st.UNIT_SKELETON, st.UNIT_SLICE_DOC)
                and contracts.all_p3(findings)):
            all_ok, debt = self._reclassify_p3_batch(
                unit, [(f, family) for f in findings])
            if all_ok:
                deferred = debt
        rec = st.record_round(
            self.state, unit, family, contracts.KIND_REVIEW_ROUND, output,
            raw_path=raw_path, duration=result.duration_s,
            meta={"deferred_clean": True} if deferred else None,
        )
        if not findings:
            st.advance_family_if_clean(self.state, unit, output)
            return "%s round: clean" % family
        if deferred is not None:
            st.record_debt(self.state, unit, deferred, "round", rec["id"])
            st.advance_family_deferred(self.state, unit)
            return ("%s round: %d P3 deferred as debt (verified by %s)"
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
                for f in findings
            ],
            "round",
            family,
            rec["id"],
            st.U_ROUNDS,
        )
        return "%s round: %d finding(s); queued for the fixer" % (
            family, len(findings))

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
        if len(unit["seals"]) >= self.config["max_seal_attempts"]:
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
        families = self._seal_families(unit, attempt_no)
        if families != all_families:
            st.append_event(
                self.state, "seal_single_first_attempt",
                unit=st.unit_key(unit), attempt=attempt_no,
                ran=list(families),
                skipped=[f for f in all_families if f not in families],
            )
        goal = self.state["goal"]
        desc = self._unit_desc(unit)
        artifact = self._artifact(unit)
        registry = self._registry()
        halves = {}
        invalidated = None
        tamper_family = None  # sequential mode can attribute the tampering
        amendments = self._amendments()  # once, before any half thread
        verified_suite = self._verified_suite(unit)

        def run_half_pure(family):
            """One seal half, mutating NO shared state (thread-safe): any
            failure raises _SealHalfFailure; raw outputs go to per-family
            files only."""
            prompt = prompts.build_seal_half(
                family, self.workspace, goal, desc, artifact, registry,
                unit_kind=unit["kind"], governing=self._governing(unit),
                amendments=amendments, verified_suite=verified_suite,
            )
            raw_name = "%s-seal-a%d-%s" % (st.unit_key(unit), attempt_no, family)
            try:
                dm, de = self._family_defaults(family)
                output, result = runners.call_worker(
                    self.runner,
                    family,
                    prompt,
                    contracts.KIND_SEAL_HALF,
                    self.workspace,
                    model=dm,
                    effort=de,
                )
            except (runners.RunnerError, runners.WorkerProtocolError) as exc:
                self._save_protocol_raws(raw_name, exc)
                raise _SealHalfFailure(
                    "%s call failed: %s" % (contracts.KIND_SEAL_HALF, exc),
                    raw_texts=list(getattr(exc, "raw_texts", []) or [])
                    + [str(exc)],
                    family=family,
                )
            raw_path = self._save_raw(raw_name, result.text)
            if output["status"] == "blocked":
                raise _SealHalfFailure(
                    "%s worker blocked: %s"
                    % (contracts.KIND_SEAL_HALF, output.get("blocked_reason"))
                )
            return {
                "result": output,
                "raw_path": raw_path,
                "duration_s": result.duration_s,
                "workspace_modified": False,
            }

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
                )
                try:
                    halves[fam] = run_half_pure(fam)
                except _SealHalfFailure as exc:
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
        clean = all(
            contracts.findings_clean(halves[fam]["result"]) for fam in families
        )
        # P3-debt deferral at the seal (both phases): if the seal is not
        # clean but its findings are ALL P3, each gets an opposite-family
        # reclassification; if every one is verified safe the P3s become
        # tracked debt and the seal PASSES rather than reopening the unit
        # (double-seal re-runs are the most expensive churn).
        deferred = None
        if (not clean and invalidated is None
                and self.config.get("p3_reclassify_debt")):
            seal_findings = [
                (f, fam)
                for fam in families
                for f in halves[fam]["result"].get("findings", [])
            ]
            if contracts.all_p3([f for f, _ in seal_findings]):
                all_ok, debt = self._reclassify_p3_batch(unit, seal_findings)
                if all_ok:
                    deferred = debt
        passed = (clean or deferred is not None) and invalidated is None
        st.record_seal_attempt(self.state, unit, halves, passed, invalidated)
        if passed:
            if deferred:
                st.record_debt(
                    self.state, unit, deferred, "seal",
                    "%s-seal-a%d" % (st.unit_key(unit), attempt_no))
            seal_kind = "single seal" if len(families) == 1 else "double seal"
            st.transition_unit(
                self.state, unit, st.U_SEALED,
                reason=("%s clean" % seal_kind if not deferred
                        else "%s: %d P3 deferred as debt"
                        % (seal_kind, len(deferred))))
            self._after_seal(unit)
            return "seal attempt %d PASSED (%s); %s sealed" % (
                attempt_no,
                "clean" if not deferred
                else "%d P3 deferred as debt" % len(deferred),
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
        merged = []
        for fam in families:
            for f in halves[fam]["result"].get("findings", []):
                merged.append(
                    {
                        "id": "%s-%s" % (fam, f["id"]),
                        "severity": f["severity"],
                        "summary": "[%s seal half] %s" % (fam, f["summary"]),
                        "contests": f.get("contests"),
                    }
                )
        st.enter_fix_episode(
            self.state,
            unit,
            merged,
            "seal",
            None,
            "%s-seal-a%d" % (st.unit_key(unit), attempt_no),
            st.U_PRE_SEAL_VERIFY,
        )
        return "seal attempt %d: %d finding(s); queued for the fixer" % (
            attempt_no,
            len(merged),
        )

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


def init_run(goal, workspace, config=None, state_path=None, name=None):
    """Create a new run state. `config` is a merged config dict (see
    load_config) or None for defaults. Returns the state path.
    Raises FileExistsError instead of overwriting an existing state; the
    claim is atomic (st.save_new, exclusive hard link), so two concurrent
    inits of the same workspace cannot both win — no exists() TOCTOU."""
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
    state = st.new_state(goal, workspace, config, name=name, slug=slug)
    st.append_event(state, "initialized", goal=goal)
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
