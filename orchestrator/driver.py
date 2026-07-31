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
import base64
import contextlib
import copy
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX: flock degrades to the
    fcntl = None     # staleness check in step(); documented in the README

from . import brainstorming, brainstorming_milestone
from . import contracts, errclass, gitops, interpreter, kvstore, ledgers
from . import projects, prompts, runners, verifiers, workareas
from . import state as st

IMPLEMENTATION_SIZE_ACK = "IMPLEMENTATION_SIZE_CUTOFF_ACK"

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
    # Verified against the installed CLIs (2026-07-09, claude ids
    # re-verified 2026-07-26): claude accepts explicit ids
    # (claude-fable-5 / claude-opus-5 / claude-sonnet-5)
    # and efforts low|medium|high|xhigh|max; codex models come from its
    # live catalog (gpt-5.6-sol / gpt-5.6-terra / gpt-5.6-luna) with
    # reasoning efforts low|medium|high|xhigh|max set via
    # `-c model_reasoning_effort=...` (bare value: failed TOML parse
    # falls back to the literal string, per codex --help).
    # claude workers run with background workflows force-disabled
    # (runners.WORKFLOW_DISABLED_ENV): the async workflow model is
    # incompatible with the one-shot call contract.
    "model_defaults": {
        "claude": {"model": "claude-opus-5", "effort": "max"},
        "codex": {"model": "gpt-5.6-sol", "effort": "max"},
    },
    # No hard wall-clock timeout: worker calls run as long as the work needs
    # (an implement call may legitimately run hours of test suites). A fixed
    # cap killed a real 15-minute-plus implement mid-flight. Instead a
    # LIVENESS watchdog (below) kills only a FROZEN worker. Operators can
    # still set per-family hard caps here when a run warrants them.
    "timeouts": {},
    # Liveness watchdog: a worker whose whole process TREE burns less than
    # worker_stall_min_cpu_s of CPU across a full worker_stall_window_s
    # window is frozen (dead CLI spawn, or a provider-side hang with no
    # bytes flowing) and gets SIGKILLed + typed `stalled` (recoverable,
    # auto-resumed; a fresh call re-issues the work). Measured live: a hung
    # codex burned 0.03s over 5h (~0.001s/window); a WORKING worker — even a
    # report-only review that mostly waits on the LLM — burns ~7-75s/window
    # (streaming keeps CPU flowing). 1s/15min sits ~1000x above frozen and
    # ~7x below the lightest real work. Set the window to 0 to disable.
    "worker_stall_window_s": 900,
    "worker_stall_min_cpu_s": 1.0,
    # Keep implementation commits reviewable.  The live worker is first
    # asked to acknowledge and close one coherent functional cut. Crossing
    # the hard boundary starts a 3-minute grace, extended to 10 minutes by a
    # real model acknowledgement; expiry hands the work to a stabilizer.
    # Git is the sole meter.  Markdown/text and runtime bookkeeping are
    # excluded by gitops.reviewable_line_count().
    "implementation_size_control": {
        "soft_lines": 1000,
        "hard_lines": 1500,
        "poll_interval_s": 2,
        "unconfirmed_grace_s": 180,
        "confirmed_grace_s": 600,
    },
    "verification": [],
    # Unlimited by default, same philosophy as worker timeouts: a real
    # suite may take 15+ minutes and a gate that kills it converts honest
    # work into failures. Set a number (seconds) to cap it per run.
    "verification_timeout": None,
    "max_rounds_per_family": 12,
    # Compatibility name: this now bounds only a baseline suite that keeps
    # mutating bytes. Final-suite convergence belongs to one fixer call.
    "max_verify_fix_attempts": 4,
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
    # "effort": "high"} — who leads SKELETON content work ("skeletoner":
    # its draft, re-drafts, AND fixes — only skeleton reviews stay on the
    # review families), slice-note drafting ("drafter"), implementation
    # ("implementer") and fixes ("fixer"), and with which model/effort.
    # `review_codex` / `review_claude` tune each fixed review family
    # independently without changing family rotation; they apply to
    # whole-artifact rounds and delta reviews. Absent
    # drafter / implementer fall back to fix_family (legacy behavior). The
    # operator can hot-edit all of this mid-run via acts.json; the driver
    # re-reads it before every act resolution.
    "acts": {
        "fixer": "codex",
        # The normal implementation owner also presents the Initial Position in every
        # milestone-owned Brainstorming session.  Pinning the profile here
        # avoids silently dropping from max effort to the family default.
        "implementer": {
            "agent": "codex",
            "model": "gpt-5.6-sol",
            "effort": "max",
        },
        # The second voice is independent configuration, not inferred from
        # family rotation. Same-family fallbacks remain valid when that is all
        # the runtime can provide.
        "brainstorming_counterpart": {
            "agent": "claude",
            "model": "claude-opus-5",
            "effort": "max",
        },
        # The skeleton is drafted, re-drafted, and fixed by one chosen
        # model — skeleton work is high-leverage planning, so it defaults
        # to claude-opus-5 at max effort. Reviews of the skeleton are
        # unaffected (they use review_codex/review_claude).
        "skeletoner": {
            "agent": "claude",
            "model": "claude-opus-5",
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
    # New runs calibrate the skeleton's declared guarantees once, before its
    # ordinary review cycle. Persisted runs created before this key existed
    # continue without inserting a new stage into their chronology.
    "guarantee_calibration": {
        "enabled": True,
        "max_rounds": 5,
    },
    # A delta stops being meaningfully incremental after enough cumulative
    # fixes.  After this many fixes in one episode born from a review round
    # or a seal, amend the pending diff without fabricating a clean delta
    # result and return exactly where a real clean delta would return: a
    # review episode re-reviews the whole amended commit, a seal episode
    # re-runs the suite and opens a fresh full seal.
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
    # caches). Add tool caches your verification suite writes so report-only
    # reviewers are not falsely invalidated. With git
    # enabled the same names are also git-ignored in the workspace repo
    # (gitops.ignore_lines), so cache writes never enter micro-review
    # diffs or gate commits.
    "snapshot_exclude_dirs": [],
}

RETIRED_CONFIG_KEYS = frozenset({
    "max_seal_attempts",
    "seal_concurrent",
    "single_seal_first_attempt",
})
RETIRED_SEAL_WORKER_KIND = "seal_half"


def merge_config(config, override):
    """Merge a user override into a config dict, in place: one level deep —
    dict values update key-wise, everything else replaces. The single
    source of truth for config merge semantics; both the CLI (load_config)
    and the service panel (service.create_run) go through here, so the two
    entry points can never drift."""
    for key, value in override.items():
        if key in RETIRED_CONFIG_KEYS:
            continue
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
A_BRAINSTORM_WAIT = "brainstorming_wait"
A_DONE = "done"
A_FAILED = "failed"

BRAINSTORMING_POLL_INTERVAL_S = 1.0


def decide(state):
    """Pure decision function: the single legal next action for a state."""
    if state["failure"] is not None or state["milestone"]["status"] == st.M_FAILED:
        return Action(A_FAILED, reason=(state["failure"] or {}).get("reason"))
    if state["milestone"]["status"] == st.M_CLOSED:
        return Action(A_DONE)
    unit = st.current_unit(state)
    if unit is None:
        return Action(A_DONE)  # run() closes the milestone
    if unit.get("brainstorming_wait"):
        return Action(A_BRAINSTORM_WAIT, unit=st.unit_key(unit))
    status = unit["status"]
    if status == st.U_PENDING:
        if (
            unit["kind"] == st.UNIT_SLICE_IMPL
            and unit.get("draft") is None
            and unit.get("baseline_verification") is None
        ):
            return Action(
                A_VERIFY, unit=st.unit_key(unit), stage="baseline"
            )
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


class _StandingLawError(RuntimeError):
    """Internal: a project-bound run's standing law (the policy store or
    the work-area meta family) could not be read or validated for a worker
    call. Routed into a recorded run failure — never a silent skip (a run
    proceeding without its standing safeguards is the incident this
    machinery exists to prevent), never a worker repair (the fault is the
    operator's store, not the worker's output)."""


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
            self.config["commands"], self.config.get("timeouts", {}),
            stall_window_s=self.config.get("worker_stall_window_s"),
            stall_min_cpu_s=self.config.get("worker_stall_min_cpu_s"),
            prompt_recorder=self._record_llm_prompt,
        )
        # Before repo validation: if a pending gap's cleanup never ran (a crash
        # between recording the gap and cleaning up), worker junk such as a
        # nested repo could make ensure_repo reject the workspace and deadlock
        # every resume — ensure_repo would record a failure, and
        # _consume_pending_gap skips under failure, so the junk is never
        # removed. Best-effort restore the recorded snapshot first.
        self._pre_clean_pending_gap()
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
        self._consume_pending_gap()
        self._migrate_active_redoc_wave()
        # A crash between a seal and its _after_seal ensure_next_unit can
        # leave the DUE planned unit without a record; with a mid-table
        # remodel insert, navigation would fall through to a later
        # pre-created record. Materialize it before any navigation — under
        # the run lock with fresh state (a concurrent invocation may be
        # mid-step; mutating beside it would surface as HistoryRewriteError
        # instead of a clean refusal). On contention, skip: the lock holder
        # materializes it.
        if self.state.get("failure") is None:
            try:
                with self._exclusive():
                    self.state = st.load(self.state_path)
                    if self.state.get("failure") is None:
                        closure_recovered = self._consume_pending_closure()
                        materialized = st.ensure_due_unit(self.state) is not None
                        try:
                            # A parked implementation must remain assigned to
                            # a planned slice across operator resume as well as
                            # across the redoc close that first detected the
                            # problem.  Otherwise clearing the failure could
                            # let navigation reach DONE with work still held
                            # only by its durable parking ref.
                            self._guard_unplanned_preserved_candidates()
                        except StopStep:
                            pass  # the guard persisted the typed failure
                        else:
                            closed_now = False
                            final_committed = False
                            if (
                                st.current_unit(self.state) is None
                                and self.state.get("failure") is None
                            ):
                                was_closed = (
                                    self.state["milestone"]["status"]
                                    == st.M_CLOSED
                                )
                                if st.maybe_close_milestone(self.state):
                                    closed_now = not was_closed
                                    if (
                                        closed_now
                                        or self.state.get(
                                            "pending_final_commit"
                                        )
                                    ):
                                        self._final_commit()
                                        final_committed = True
                            if (
                                materialized
                                or closure_recovered
                                or closed_now
                                or final_committed
                            ):
                                self._save()
            except ConcurrentRunError:
                pass
            except StopStep:
                pass  # closure/final-commit recovery persisted its failure

    # -- helpers ----------------------------------------------------------

    def _save(self):
        st.save(self.state_path, self.state)

    # -- operator control (safe pause) -------------------------------------
    # control.json lives NEXT to state.json and is written by the service
    # while the driver runs — it must never ride state.json itself, whose
    # single writer is the driver. The driver only READS it (at step
    # boundaries) and clears the one-shot flag after honoring it, so the
    # two processes never contend on the same file for writes.

    def _control_path(self):
        return os.path.join(os.path.dirname(self.state_path), "control.json")

    def _control(self):
        try:
            with open(self._control_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _clear_stop_after_seal(self):
        ctl = self._control()
        if not ctl.get("stop_after_seal"):
            return
        ctl.pop("stop_after_seal", None)
        tmp = self._control_path() + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(ctl, fh)
            os.replace(tmp, self._control_path())
        except OSError:
            # Worst case the stale flag pauses the run once more at the
            # next seal — an extra safe stop, never lost work.
            pass

    def _sealed_keys(self):
        return {
            st.unit_key(u) for u in self.state["units"]
            if u["status"] == st.U_SEALED
        }

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

    def _candidate_fingerprint(self, snapshot=None):
        """Stable digest of every candidate byte visible to tamper checks."""
        mode, entries = snapshot if snapshot is not None else self._snapshot()
        payload = json.dumps(
            [mode, sorted(entries.items())],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "snapshot-sha256:%s" % hashlib.sha256(payload).hexdigest()

    def _verification_candidate_fingerprint(self, snapshot=None):
        """Digest the bytes a full suite is expected to certify.

        Gate-generated ledgers are deterministic projections written only
        after the final suite.  They have never been covered by that suite;
        excluding them makes the proof honest and lets a documentation
        closure serve as the following implementation's baseline.
        """
        mode, entries = snapshot if snapshot is not None else self._snapshot()
        generated = set(ledgers.generated_paths(self.state))
        index = ledgers.index_path(self.state)
        # The canonical parent index is mixed ownership: only its marker
        # block is generated, while prose around it belongs to the repo.
        # Hash that prose instead of dropping the whole file.
        if index:
            generated.discard(index)
        closure_root = ledgers.closures_dir(self.state).rstrip("/")
        filtered = {
            path: value
            for path, value in entries.items()
            if path not in generated
            and path != closure_root
        }
        if index and index in filtered:
            filtered[index] = self._verification_index_descriptor(
                index, filtered[index]
            )
        payload = json.dumps(
            [mode, sorted(filtered.items())],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "verification-sha256:%s" % hashlib.sha256(payload).hexdigest()

    def _verification_index_descriptor(self, relpath, snapshot_value):
        """Hash operator-owned bytes around the generated index block.

        If the file is not a regular UTF-8 index with one valid marker pair,
        retain the snapshot's whole-file descriptor. That is conservative:
        malformed or not-yet-managed indexes never gain proof reuse.
        """
        path = os.path.join(self.workspace, relpath)
        if os.path.islink(path) or not os.path.isfile(path):
            return snapshot_value
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            current = "file %s" % hashlib.sha256(raw).hexdigest()
            if current != snapshot_value:
                return snapshot_value
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return snapshot_value
        if (
            text.count(ledgers.INDEX_START) != 1
            or text.count(ledgers.INDEX_END) != 1
            or text.index(ledgers.INDEX_END)
            < text.index(ledgers.INDEX_START)
        ):
            return snapshot_value
        before, rest = text.split(ledgers.INDEX_START, 1)
        _generated, after = rest.split(ledgers.INDEX_END, 1)
        operator_bytes = json.dumps(
            [before, after], ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        return "index-operator-sha256:%s" % hashlib.sha256(
            operator_bytes
        ).hexdigest()

    def _matching_final_verification(self, commands, fingerprint):
        """Return an actual stable final-suite event for these exact inputs."""
        commands = list(commands)
        for event in reversed(self.state.get("events") or []):
            if (
                event.get("type") == "verification"
                and event.get("boundary") == "final"
                and event.get("ok") is True
                and event.get("stable") is True
                and not event.get("vacuous")
                and not event.get("reused")
                and event.get("commands") == commands
                and event.get("candidate_after") == fingerprint
            ):
                return event
        return None

    def _matching_fixer_verification(self, commands, fingerprint):
        """Return a fixer's full-suite success for these exact inputs."""
        commands = list(commands)
        for event in reversed(self.state.get("events") or []):
            if (
                event.get("type") == "verification"
                and event.get("boundary") == "final"
                and event.get("ok") is True
                and event.get("stable") is True
                and event.get("fixer_certified") is True
                and not event.get("vacuous")
                and event.get("commands") == commands
                and event.get("candidate_after") == fingerprint
            ):
                return event
        return None

    def _baseline_verification_current(self, unit):
        marker = unit.get("baseline_verification")
        if not isinstance(marker, dict):
            return False
        return (
            marker.get("commands") == self._verification_commands(unit)
            and marker.get("candidate_fingerprint")
            == self._verification_candidate_fingerprint()
        )

    def _review_evidence_inputs(self, unit):
        """Return the exact bytes and hot rules a full reviewer would see.

        Reading is side-effect free: if the evidence differs from the bound
        cycle, no ``*_seen`` event may imply that a reviewer saw it before the
        family-zero restart actually runs.
        """
        snapshot = self._snapshot()
        project_context, extensions, roots = self._project_prompt_inputs(
            unit, contracts.KIND_REVIEW_ROUND, record_seen=False
        )
        amendments = self._amendments(record_seen=False)
        payload = json.dumps(
            {
                "candidate": self._candidate_fingerprint(snapshot),
                "amendments": amendments,
                "project_context": project_context,
                "implementation_scope": self._implementation_scope(unit),
                # Bind approvals to the exact execution plan, including
                # command boundaries. Joining with ``&&`` is only a prompt
                # rendering: separate list items run in separate shells and
                # therefore are not equivalent to one joined command.
                "suite_commands": self._verification_commands(unit),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fingerprint = "review-evidence-sha256:%s" % hashlib.sha256(
            payload
        ).hexdigest()
        return fingerprint, project_context, extensions, roots, amendments

    def _review_evidence_fingerprint(self, unit):
        return self._review_evidence_inputs(unit)[0]

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

    def _prompt_dir(self):
        path = os.path.join(self._runtime_dir(), "prompts")
        os.makedirs(path, exist_ok=True)
        return path

    def _record_llm_prompt(self, family, prompt):
        """Persist one exact physical worker prompt outside the Git ledger."""
        label = None
        try:
            with open(self._busy_path(), "r", encoding="utf-8") as handle:
                current = json.load(handle)
            if isinstance(current, dict):
                label = current.get("label")
        except (OSError, ValueError, TypeError):
            pass
        return runners.save_prompt_trace(
            self._prompt_dir(), family, prompt, label=label
        )

    def _save_raw(self, name, text):
        path = os.path.join(self._raw_dir(), name + ".txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text or "")
        return os.path.relpath(path, self.workspace)

    def _save_raw_noclobber(self, name, text):
        """Like _save_raw but never overwrites an existing file, appending
        -2, -3 ... instead. Used for malformed-strike artifacts: a seal
        attempt that failed leaves no seal record, so a manual resume runs
        the SAME attempt number and would otherwise overwrite the earlier
        attempt's strike raw — leaving a live ledger event pointing at
        replaced bytes. Distinct per-family names keep concurrent halves
        from racing; this guards only the across-resume reuse."""
        raw_dir = self._raw_dir()
        candidate = name
        n = 1
        while os.path.exists(os.path.join(raw_dir, candidate + ".txt")):
            n += 1
            candidate = "%s-%d" % (name, n)
        return self._save_raw(candidate, text)

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
        part = st.implementation_part(unit)
        token = "%d%s" % (
            unit["slice_id"], "-%s" % part if part else ""
        )
        return "the slice %s implementation (%s)" % (token, title)

    def _implementation_scope(self, unit):
        return st.implementation_scope(self.state, unit)

    def _implementation_size_control(self, base_tree):
        """Live Git budget monitor for one implementation call.

        The observer never mutates Git. It asks once for a coherent cut at the
        soft boundary. A hard stop follows when the worker remains beyond the
        hard boundary after that request; accepting that stop durably records
        stabilization. Stabilizers never use this monitor: once recovery
        starts, they must close coherently without another size interruption.
        """
        if not base_tree or not gitops.enabled(self.config):
            return None, None
        configured = self.config.get("implementation_size_control")
        if configured is None:
            configured = DEFAULT_CONFIG["implementation_size_control"]
        if not isinstance(configured, dict):
            return None, None
        try:
            soft = int(configured.get("soft_lines", 1000))
            hard = int(configured.get("hard_lines", 1500))
            poll = float(configured.get("poll_interval_s", 2))
            unconfirmed_grace = float(
                configured.get("unconfirmed_grace_s", 180)
            )
            confirmed_grace = float(
                configured.get("confirmed_grace_s", 600)
            )
        except (TypeError, ValueError):
            return None, None
        if (
            soft <= 0 or hard <= soft
            or not all(math.isfinite(value) and value > 0 for value in (
                poll, unconfirmed_grace, confirmed_grace
            ))
        ):
            return None, None
        marker = {
            "episode_id": uuid.uuid4().hex,
            "soft_lines": soft,
            "hard_lines": hard,
            "unconfirmed_grace_s": unconfirmed_grace,
            "confirmed_grace_s": confirmed_grace,
            "steer_attempted": False,
            "steer_delivered": False,
            "steer_confirmed": False,
            "steer_lines": None,
            "hard_crossed_lines": None,
            "grace_kind": None,
            "interrupt_lines": None,
            "last_lines": 0,
        }
        steer_text = (
            "CONTROLLED SIZE CUTOFF: before any further tool call or edit, "
            "send one standalone commentary line containing exactly "
            "%s. Then stop expanding the slice and bring the "
            "current changes to one coherent, functional and reviewable cut; "
            "run only focused checks needed for that cut. Do not implement "
            "the remaining obligations in this turn. If obligations remain, "
            "return implementation_cut with concise non-empty cut_scope and "
            "remaining_scope. If the complete original slice is already "
            "finished, omit implementation_cut and return the normal result."
            % IMPLEMENTATION_SIZE_ACK
        )

        def observe(control):
            call_steered = False
            hard_crossed_at = None
            grace_deadline = None
            while not control.closed:
                if hard_crossed_at is not None:
                    confirmed_at = control.model_confirmation_at
                    if confirmed_at is not None \
                            and marker["grace_kind"] != "confirmed":
                        # The exact model-authored token is stronger delivery
                        # evidence than a missing/timed-out steer RPC reply.
                        marker["steer_delivered"] = True
                        marker["steer_confirmed"] = True
                        marker["grace_kind"] = "confirmed"
                        grace_deadline = confirmed_at + confirmed_grace
                    now = time.monotonic()
                    if now >= grace_deadline:
                        marker["interrupt_lines"] = marker["last_lines"]
                        accepted = control.interrupt(
                            "implementation exceeded the controlled size "
                            "cutoff and did not close within %g seconds "
                            "(%s model confirmation)"
                            % (
                                marker[
                                    "confirmed_grace_s"
                                    if marker["grace_kind"] == "confirmed"
                                    else "unconfirmed_grace_s"
                                ],
                                "with" if marker["grace_kind"] == "confirmed"
                                else "without",
                            )
                        )
                        if accepted:
                            return
                        # Write-ahead persistence or transport delivery may
                        # fail transiently. Keep watching and retry instead of
                        # silently leaving an oversized live worker unbounded.
                        if control.wait_closed(poll):
                            return
                        continue
                    if control.wait_closed(
                        min(poll, max(0.001, grace_deadline - now))
                    ):
                        return
                    continue
                try:
                    lines = gitops.reviewable_line_count(
                        self.workspace,
                        base_tree,
                        bookkeeping_dir=self._runtime_dir(),
                    )
                except gitops.GitError:
                    # A checkout race while files are being replaced is not a
                    # reason to kill useful work.  The next poll tries again.
                    if control.wait_closed(poll):
                        return
                    continue
                observed_at = time.monotonic()
                marker["last_lines"] = lines
                if not call_steered and lines >= soft:
                    call_steered = True
                    marker["steer_attempted"] = True
                    marker["steer_lines"] = lines
                    control.expect_model_confirmation(
                        IMPLEMENTATION_SIZE_ACK
                    )
                    delivered = bool(control.steer(steer_text))
                    marker["steer_delivered"] = bool(
                        marker["steer_delivered"] or delivered
                    )
                confirmed_at = control.model_confirmation_at
                if confirmed_at is not None:
                    # Codex may consume the steer and answer it after the
                    # app-server RPC acknowledgement has timed out.
                    marker["steer_delivered"] = True
                    marker["steer_confirmed"] = True
                if call_steered and lines > hard:
                    hard_crossed_at = observed_at
                    marker["hard_crossed_lines"] = lines
                    if confirmed_at is not None:
                        marker["grace_kind"] = "confirmed"
                        grace_deadline = (
                            hard_crossed_at + confirmed_grace
                            if confirmed_at <= hard_crossed_at
                            else confirmed_at + confirmed_grace
                        )
                    else:
                        marker["grace_kind"] = "unconfirmed"
                        grace_deadline = hard_crossed_at + unconfirmed_grace
                if control.wait_closed(poll):
                    return

        return runners.ActiveCallControl(
            observer=observe,
            on_interrupt=lambda reason: (
                self._persist_implementation_stabilization(
                    marker, interrupt_reason=reason
                )
            ),
            on_interrupt_rejected=lambda _reason: (
                self._clear_rejected_implementation_stabilization(marker)
            ),
        ), marker

    def _persist_implementation_stabilization(
        self, marker, interrupt_reason=None
    ):
        """Durably cross the cutoff boundary before exposing interruption."""
        unit = st.current_unit(self.state)
        created = unit.get("implementation_stabilization") is None
        if created:
            durable_marker = copy.deepcopy(marker)
            if interrupt_reason:
                durable_marker["interrupt_reason"] = interrupt_reason
            unit["implementation_stabilization"] = {
                "implementation_size": durable_marker,
            }
        try:
            self._save()
        except Exception:
            if created:
                unit.pop("implementation_stabilization", None)
            raise

    def _clear_rejected_implementation_stabilization(self, marker):
        """Clear this episode's write-ahead marker after transport refusal."""
        unit = st.current_unit(self.state)
        pending = unit.get("implementation_stabilization")
        durable = (
            pending.get("implementation_size")
            if isinstance(pending, dict) else None
        )
        if not isinstance(durable, dict) or durable.get("episode_id") \
                != marker.get("episode_id"):
            return
        removed = unit.pop("implementation_stabilization")
        try:
            self._save()
        except Exception:
            unit["implementation_stabilization"] = removed
            raise

    def _ensure_implementation_stabilization_events(self, unit, marker):
        """Repair a crash gap between an accepted stop and runner return."""
        unit_key = st.unit_key(unit)
        episode_id = marker.get("episode_id")

        def already_recorded(event_type, fields):
            candidates = (
                event for event in self.state.get("events", [])
                if event.get("unit") == unit_key
                and event.get("type") == event_type
            )
            if episode_id:
                return any(
                    event.get("episode_id") == episode_id
                    for event in candidates
                )
            # Legacy markers cannot name their episode. Match only an
            # untagged event with the same observable cutoff evidence.
            return any(
                event.get("episode_id") is None
                and all(event.get(key) == value
                        for key, value in fields.items())
                for event in candidates
            )

        steer_fields = {
            "lines": marker.get("steer_lines"),
            "delivered": marker.get("steer_delivered"),
            "confirmed": marker.get("steer_confirmed"),
            "grace_kind": marker.get("grace_kind"),
            "soft_lines": marker.get("soft_lines"),
            "hard_lines": marker.get("hard_lines"),
        }
        interrupt_fields = {
            "lines": marker.get("interrupt_lines"),
            "reason": (
                marker.get("interrupt_reason")
                or "implementation size cutoff accepted before restart"
            ),
            "confirmed": marker.get("steer_confirmed"),
            "grace_kind": marker.get("grace_kind"),
            "hard_crossed_lines": marker.get("hard_crossed_lines"),
        }
        added = False
        if (
            marker.get("steer_attempted")
            and not already_recorded(
                "implementation_size_steer", steer_fields
            )
        ):
            st.append_event(
                self.state,
                "implementation_size_steer",
                unit=unit_key,
                episode_id=episode_id,
                **steer_fields,
            )
            added = True
        if (
            marker.get("interrupt_lines") is not None
            and not already_recorded(
                "implementation_size_interrupted", interrupt_fields
            )
        ):
            st.append_event(
                self.state,
                "implementation_size_interrupted",
                unit=unit_key,
                episode_id=episode_id,
                duration_s=None,
                raw_path=None,
                **interrupt_fields,
            )
            added = True
        if added:
            self._save()

    @staticmethod
    def _implementation_stabilizer_prompt(prompt, marker):
        del marker
        return (
            prompt.replace(prompts.IMPLEMENTATION_SIZE_GUIDANCE, "")
            + "\n\nFORCED CONTROLLED-CUTOFF RECOVERY\n"
            "A previous implementer was stopped after continuing beyond the "
            "size limit. Its uncommitted workspace changes are intentionally "
            "present. Inspect and preserve sound work. Close the work already "
            "in progress as one coherent, functional delivery and run focused "
            "checks only. Do not continue into the full remaining slice, but "
            "also do not compress, rewrite, discard, or reimplement sound work "
            "merely to meet a line count. No further size cutoff applies to "
            "this stabilization. If the "
            "original slice still has obligations, return implementation_cut "
            "with concise non-empty cut_scope and remaining_scope; otherwise "
            "omit it. Return the ordinary implement envelope.\n"
        )

    def _implementation_line_count(self, base_tree):
        for attempt in range(3):
            try:
                return gitops.reviewable_line_count(
                    self.workspace,
                    base_tree,
                    bookkeeping_dir=self._runtime_dir(),
                )
            except gitops.GitError:
                if attempt < 2:
                    time.sleep(0.05)
        return None

    def _fail_implementation_size(self, lines, hard, reason):
        detail = (
            "%s; the current implementation delta is %s reviewable Git "
            "lines and must be at most %d"
            % (reason, "unknown" if lines is None else lines, hard)
        )
        st.fail_run(
            self.state,
            detail,
            unit=st.current_unit(self.state),
            type_="worker_protocol",
        )
        self._save()
        raise StopStep("implementation size cutoff recovery failed")

    def _call_implementation(
        self, family, prompt, raw_name, model, effort, extensions, roots,
        validate_opts, start_session, base_tree, session_ref=None,
        stabilizing=False,
    ):
        if stabilizing:
            output, result, raw_path = self._call(
                family,
                prompt,
                contracts.KIND_IMPLEMENT,
                raw_name,
                model=model,
                effort=effort,
                extensions=extensions,
                roots=roots,
                validate_opts=validate_opts,
                start_session=start_session,
                session_ref=session_ref,
                active_control=None,
                repeat_protocol=True,
            )
            return output, result, raw_path, None, True
        control, marker = self._implementation_size_control(base_tree)
        if marker is None and gitops.enabled(self.config):
            st.fail_run(
                self.state,
                "implementation size control is unavailable: the fixed Git "
                "baseline is missing or implementation_size_control is "
                "invalid",
                unit=st.current_unit(self.state),
                type_="orchestrator",
            )
            self._save()
            raise StopStep("implementation size control unavailable")
        output, result, raw_path = self._call(
            family,
            prompt,
            contracts.KIND_IMPLEMENT,
            raw_name,
            model=model,
            effort=effort,
            extensions=extensions,
            roots=roots,
            validate_opts=validate_opts,
            start_session=start_session,
            session_ref=session_ref,
            active_control=control,
        )
        if marker is None:
            return output, result, raw_path, None, False
        # The exact ACK may arrive immediately before provider completion;
        # consolidate it even if closing the control woke the observer before
        # its next polling iteration.
        if control.model_confirmation_at is not None:
            marker["steer_delivered"] = True
            marker["steer_confirmed"] = True
        if marker.get("steer_attempted"):
            st.append_event(
                self.state,
                "implementation_size_steer",
                unit=st.unit_key(st.current_unit(self.state)),
                episode_id=marker.get("episode_id"),
                lines=marker.get("steer_lines"),
                delivered=marker.get("steer_delivered"),
                confirmed=marker.get("steer_confirmed"),
                grace_kind=marker.get("grace_kind"),
                soft_lines=marker.get("soft_lines"),
                hard_lines=marker.get("hard_lines"),
            )
        interrupted = isinstance(result, runners.ControlledInterruptionResult)
        final_lines = self._implementation_line_count(base_tree)
        if final_lines is not None:
            marker["last_lines"] = final_lines
        if (
            not interrupted
            and output is not None
            and output.get("status") == "ok"
            and not control.interrupted
            and marker.get("interrupt_lines") is not None
            and final_lines is not None
            and final_lines > marker["hard_lines"]
        ):
            self._fail_implementation_size(
                final_lines,
                marker["hard_lines"],
                "the controlled cutoff could not be accepted before the "
                "worker completed",
            )
        if (
            not interrupted
            and output is not None
            and output.get("status") == "ok"
            and final_lines is None
        ):
            self._fail_implementation_size(
                None,
                marker["hard_lines"],
                "the final implementation size could not be measured",
            )
        if not interrupted:
            # The monitor controls a call while it is live. If a valid worker
            # delivery jumps over the hard boundary between the last poll and
            # process completion, there is nothing left to interrupt: accept
            # that ordinary envelope and send it into the normal review flow.
            # Keep the oversize observation as telemetry; never re-run a
            # completed implementer merely to manufacture a cutoff.
            if (
                output is not None
                and output.get("status") == "ok"
                and final_lines is not None
                and final_lines > marker["hard_lines"]
                and marker.get("hard_crossed_lines") is None
            ):
                st.append_event(
                    self.state,
                    "implementation_size_overflow",
                    unit=st.unit_key(st.current_unit(self.state)),
                    lines=final_lines,
                    hard_lines=marker["hard_lines"],
                    completed=True,
                )
            return output, result, raw_path, marker, False
        st.append_event(
            self.state,
            "implementation_size_interrupted",
            unit=st.unit_key(st.current_unit(self.state)),
            episode_id=marker.get("episode_id"),
            lines=marker.get("interrupt_lines"),
            reason=result.interrupt_reason,
            duration_s=result.duration_s,
            raw_path=raw_path,
            confirmed=marker.get("steer_confirmed"),
            grace_kind=marker.get("grace_kind"),
            hard_crossed_lines=marker.get("hard_crossed_lines"),
        )
        recovery_prompt = self._implementation_stabilizer_prompt(
            prompt, marker
        )
        # Crossing into stabilization is a durable process boundary.  Save it
        # before the fresh worker starts so a provider failure or driver crash
        # cannot send Resume back through the ordinary size-monitored draft.
        # The marker stays until a valid implementation delivery is recorded.
        self._persist_implementation_stabilization(marker)
        output, result, raw_path = self._call(
            family,
            recovery_prompt,
            contracts.KIND_IMPLEMENT,
            raw_name + "-stabilize",
            model=model,
            effort=effort,
            extensions=extensions,
            roots=roots,
            validate_opts=validate_opts,
            # An interrupted continuation cannot safely reuse its provider
            # turn.  The stabilizer is deliberately a fresh conversation.
            start_session=True,
            # Recovery owns the delivery boundary now.  It is neither
            # size-monitored nor failed for an oversized coherent result.
            active_control=None,
            repeat_protocol=True,
        )
        return output, result, raw_path, marker, True

    def _artifact(self, unit):
        return unit["artifact"] or "(workspace)"

    def _verification_commands(self, unit):
        """Gate commands for a unit: explicit config verification wins;
        a fixer-supplied suite correction can replace a stale explicit
        gate; otherwise use the suite command an implementer discovered.

        Documentation does not run a pre-review suite, but its single final
        boundary deliberately uses the known full suite: that catches the
        rare executable/configuration document without taxing every review
        cycle.  Before the first implementer discovers a zero-config suite,
        the early documentation boundaries are necessarily vacuous.
        """
        configured = self.config.get("verification") or []
        corrected = self._corrected_suite_command()
        if corrected:
            return [corrected]
        if configured:
            return list(configured)
        discovered = self.state.get("suite_command")
        if discovered:
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
            or not configured
            or configured == [discovered]
        ):
            return None
        for unit in self.state.get("units", []):
            for round_info in unit.get("rounds", []):
                if round_info.get("kind") != contracts.KIND_FIX_FINDINGS:
                    continue
                result = round_info.get("result") or {}
                reported = result.get("suite_command")
                if (
                    not isinstance(reported, str)
                    or reported.strip() != discovered
                ):
                    continue
                if any(
                    f.get("disposition") == "fixed"
                    for f in result.get("findings", [])
                ):
                    return discovered
        return None

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
                self._save_raw_noclobber(
                    "%s-protoerr%d" % (raw_name, i), text
                )
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

    def _parked_candidate_ref(self, unit):
        digest = hashlib.sha256(
            (os.path.abspath(self.state_path) + "\0" + st.unit_key(unit))
            .encode("utf-8", "surrogatepass")
        ).hexdigest()[:24]
        return "refs/orchestrator/parked/%s" % digest

    def _record_amendments_seen(self, amendments):
        if not amendments:
            return
        seen = {
            e.get("amendment_id")
            for e in self.state["events"]
            if e.get("type") == "amendment_seen"
        }
        for amendment in amendments:
            aid = str(amendment.get("id") or "")
            if aid and aid not in seen:
                seen.add(aid)
                st.append_event(
                    self.state,
                    "amendment_seen",
                    amendment_id=aid,
                    text=str(amendment.get("text"))[:300],
                )

    def _amendments(self, record_seen=True):
        """Return operator amendments plus accepted design clarifications.

        The panel-owned file remains read-only to the driver. Brainstorming
        amendments live in the append-only run ledger with narrower authority:
        they clarify sealed design but never amend the operator's goal.
        """
        operator = []
        try:
            with open(self._amendments_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            operator = [
                a
                for a in (data.get("amendments") or [])
                if isinstance(a, dict) and str(a.get("text") or "").strip()
            ]
        except (OSError, ValueError):
            pass
        if record_seen:
            self._record_amendments_seen(operator)
        design = [
            {
                "id": event.get("amendment_id"),
                "text": event.get("text"),
                "at": event.get("at"),
                "authority": event.get("authority") or "brainstorming_design",
                "session_id": event.get("session_id"),
                "accepted_target_revision": event.get(
                    "accepted_target_revision"
                ),
            }
            for event in self.state.get("events", [])
            if event.get("type") in (
                "brainstorming_design_amendment_adopted",
                "redoc_wave_migrated_to_design_update",
            )
            and str(event.get("text") or "").strip()
        ]
        return operator + design

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

    def _project_prompt_inputs(self, unit, kind, record_seen=True):
        """Standing project law for one worker call of a project-bound
        run: (project_context, extensions, roots) — the PROJECT CONTEXT
        builder input, the compiled in-scope contract extensions, and the
        grant universe. (None, None, None) for a project-less run, whose
        builders and validation then behave byte-identically to today.

        Selection and meta are read live for every worker call through this
        method. Roots and handles come from the state project block
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
        if record_seen:
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
        atomically so panel readers never observe a partial record."""
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
              extensions=None, roots=None, validate_opts=None,
              start_session=False, session_ref=None, active_control=None,
              repeat_protocol=False):
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
            physical_started = time.time()
            try:
                call_control = (
                    active_control
                    if attempt == 0 or active_control is None
                    else active_control.renew()
                )
                output, result = runners.call_worker(
                    self.runner, family, prompt, kind, self.workspace,
                    model=model, effort=effort,
                    extensions=extensions, roots=roots,
                    validate_opts=validate_opts,
                    start_session=start_session, session_ref=session_ref,
                    active_control=call_control,
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
                if call_control is not None and call_control.interrupted:
                    # The transport accepted the hard stop. A late transport
                    # or parsing error cannot turn that boundary back into an
                    # initial-draft retry or a run failure: hand the accepted
                    # interruption to the ordinary stabilizer path.
                    st.append_event(
                        self.state,
                        "worker_malformed",
                        unit=self._worker_event_unit(),
                        label=raw_name,
                        kind=kind,
                        family=family,
                        fatal=False,
                        controlled_interruption=True,
                        error=str(exc)[:300],
                        duration_s=None,
                        raw_path=(proto_paths or [None])[0],
                        raw_path2=(
                            proto_paths[1]
                            if len(proto_paths) > 1 else None
                        ),
                    )
                    self._save()
                    raw_texts = list(
                        getattr(exc, "raw_texts", []) or []
                    )
                    result = runners.ControlledInterruptionResult(
                        raw_texts[-1] if raw_texts else "",
                        1,
                        time.time() - physical_started,
                        call_control.interrupt_reason,
                    )
                    break
                if (
                    repeat_protocol
                    and isinstance(exc, runners.WorkerProtocolError)
                ):
                    # A cutoff stabilizer owns an already-interrupted delivery.
                    # A malformed handoff cannot safely open review, but it is
                    # also not a reason to abandon the preserved work. Record
                    # the strike and retry in a fresh provider session until a
                    # valid ordinary implementation envelope is delivered.
                    st.append_event(
                        self.state,
                        "worker_malformed",
                        unit=self._worker_event_unit(),
                        label=raw_name,
                        kind=kind,
                        family=family,
                        fatal=False,
                        stabilizer_retry=True,
                        error=str(exc)[:300],
                        duration_s=None,
                        raw_path=(proto_paths or [None])[0],
                        raw_path2=(
                            proto_paths[1] if len(proto_paths) > 1 else None
                        ),
                    )
                    self._save()
                    # A repeated stabilization is a new worker, not another
                    # continuation of the session that already failed twice.
                    if session_ref is not None:
                        session_ref = None
                        start_session = True
                    continue
                etype, resume_at, evidence = self._classify_failure(
                    family, exc, raw_name=raw_name
                )
                if etype in ("network", "busy") and attempt < len(retries):
                    # Short in-place retries BEFORE failing: transient
                    # blips should not cost a run failure + resume cycle.
                    incident = {
                        "unit": self._worker_event_unit(),
                        "label": raw_name,
                        "kind": kind,
                        "family": family,
                        "fatal": False,
                        "infra_retry": True,
                        "error": str(exc)[:300],
                        "duration_s": None,
                        "raw_path": (proto_paths or [None])[0],
                        "raw_path2": (
                            proto_paths[1]
                            if len(proto_paths) > 1 else None
                        ),
                    }
                    if repeat_protocol:
                        incident["stabilizer_retry"] = True
                    st.append_event(
                        self.state, "worker_malformed", **incident
                    )
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
                # incident chip. An absorbed infrastructure blip above gets a
                # non-fatal incident even when the provider exposed no raw
                # bytes, so every retry remains visible and truthful.
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
        if isinstance(result, runners.ControlledInterruptionResult):
            raw_text = getattr(result, "transport_text", None)
            if not isinstance(raw_text, str) or not raw_text:
                raw_text = result.text
            raw_path = self._save_raw_noclobber(
                raw_name + "-controlled-interruption", raw_text
            )
            self._record_repair(raw_name, kind, family, result)
            result.raw_path = raw_path
            return None, result, raw_path
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
        # BOTH channels, never `or`: a repair retry that itself needed
        # delimiter recovery produced two distinct strikes, and reporting
        # only the first would hide the second.
        for attr in ("repair", "recovered"):
            rep = getattr(result, attr, None)
            if not rep:
                continue
            raw_path = self._save_raw_noclobber(
                "%s-malformed%s"
                % (raw_name, "" if attr == "repair" else "-tail"),
                rep["raw_text"],
            )
            st.append_event(
                self.state,
                "worker_malformed",
                unit=self._worker_event_unit(),
                label=raw_name,
                kind=kind,
                family=family,
                error=str(rep["error"])[:300],
                # A delimiter recovery costs no retry, so it wasted no
                # time — it still reports as malformed because the output
                # WAS, and the model dropping its brace must stay visible.
                duration_s=rep.get("duration_s"),
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
        opposite = self._opposite(family)
        cls_model, cls_effort = self._family_defaults(opposite)
        return errclass.classify_worker_failure(
            exc,
            runner=self.runner,
            opposite_family=opposite,
            workspace=self.workspace,
            use_llm=bool(self.config.get("error_classifier", True)),
            on_llm_raw=self._classify_raw_saver(raw_name),
            classifier_model=cls_model,
            classifier_effort=cls_effort,
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

    def _enforce_sealed_artifacts(self, raw_name, editable_sealed=None):
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
        deterministically sealed checkpoint of the WHOLE tree, is the canonical
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
        editable_sealed = set(editable_sealed or ())
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
            if art in editable_sealed:
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

    @staticmethod
    def _safe_design_path(value):
        if not isinstance(value, str) or not value.strip():
            return None
        value = os.path.normpath(value.strip())
        if os.path.isabs(value) or value in (".", "..") \
                or value.startswith(".." + os.sep):
            return None
        return value

    def _design_correction_offer(self, unit):
        """One-shot semantic exception for a normal implementation fixer."""
        if (
            unit.get("kind") != st.UNIT_SLICE_IMPL
            or unit.get("under_repair")
            or unit.get("design_correction")
            or unit.get("design_correction_attempted")
            or self.state.get("redoc_wave")
            or not interpreter.gap_semantics(self.state)
            or not gitops.enabled(self.config)
        ):
            return None
        note = self._find_unit(st.UNIT_SLICE_DOC, unit.get("slice_id"))
        if note is None or note.get("status") != st.U_SEALED \
                or not note.get("gate_commit"):
            return None
        return {
            "mode": "offer",
            "artifact": note.get("artifact")
            or self._slice_note_artifact(unit["slice_id"]),
            "note_unit": st.unit_key(note),
            "authority_gate": note["gate_commit"],
        }

    def _design_correction_context(self, unit):
        correction = unit.get("design_correction") or {}
        if correction.get("phase") == "proposed":
            return {"mode": "active", **correction}
        return self._design_correction_offer(unit)

    def _workspace_bytes(self, relpath):
        try:
            with open(os.path.join(self.workspace, relpath), "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def _start_design_correction(
        self, unit, declaration, files_changed, offer,
        pre_refs, pre_sym, pre_head, pre_tree, pre_worktree_tree, pre_stash,
        brainstorming_handoff=None,
    ):
        """Validate the mechanical envelope; semantic judgment is next."""
        baseline = {
            "refs": pre_refs,
            "sym": pre_sym,
            "head": pre_head,
            "tree": pre_worktree_tree,
            "index_tree": pre_tree,
            "stash": pre_stash,
        }
        candidate = {
            "phase": "proposed",
            "baseline": baseline,
            "original_fix_queue": copy.deepcopy(unit.get("fix_queue") or []),
            "original_fix_source": copy.deepcopy(unit.get("fix_source")),
            "original_fix_loop_rounds": int(unit.get("fix_loop_rounds") or 0),
        }
        if offer is None or offer.get("mode") != "offer":
            return candidate, "the one-shot correction envelope is not open"
        if any(value is None for value in (
            pre_refs, pre_sym, pre_head, pre_tree, pre_worktree_tree,
        )):
            return candidate, "the normal pre-fix Git snapshot is unavailable"
        artifact = self._safe_design_path(declaration.get("artifact"))
        authority = self._safe_design_path(declaration.get("authority_artifact"))
        brainstorming_authority = declaration.get("brainstorming_authority")
        expected = self._safe_design_path(offer.get("artifact"))
        if artifact != expected:
            return candidate, "only the implementation's own slice note is editable"
        changed = {
            self._safe_design_path(path) for path in (files_changed or [])
        }
        if artifact not in changed:
            return candidate, "the corrected note is absent from files_changed"
        note_before = gitops.show_file(self.workspace, pre_head, artifact)
        note_after = self._workspace_bytes(artifact)
        if note_before is None or note_after is None or note_before == note_after:
            return candidate, "the proposed correction did not change its note"

        if brainstorming_authority is not None:
            handoff = brainstorming_handoff or {}
            expected_authority = {
                "session_id": handoff.get("session_id"),
                "accepted_target_revision": handoff.get(
                    "accepted_target_revision"
                ),
            }
            if not brainstorming._same_json_value(
                brainstorming_authority, expected_authority
            ):
                return candidate, (
                    "Brainstorming authority does not match the recorded handoff"
                )
            try:
                authority_record = brainstorming_milestone.retained_revision(
                    self.state,
                    brainstorming_authority["session_id"],
                    brainstorming_authority["accepted_target_revision"],
                )
                checked_record = brainstorming.validate_target_revision(
                    authority_record
                )
                authority_exists, authority_before = (
                    brainstorming.target_revision_content(checked_record)
                )
            except Exception:
                authority_exists, authority_before = False, None
            if not authority_exists or authority_before is None:
                return candidate, (
                    "the recorded Brainstorming authority has no proposal content"
                )
            authority = (handoff.get("result") or {}).get("target_ref")
            candidate["brainstorming_authority"] = copy.deepcopy(
                brainstorming_authority
            )
        else:
            if authority is None or authority == artifact:
                return candidate, (
                    "authority must be one different pre-existing artifact"
                )
            authority_gate = offer.get("authority_gate")
            authority_before = gitops.show_file(
                self.workspace, authority_gate, authority
            )
            if authority_before is None:
                return candidate, (
                    "the cited authority did not predate the sealed note"
                )
            if (
                gitops.show_file(self.workspace, pre_head, authority)
                != authority_before
                or self._workspace_bytes(authority) != authority_before
            ):
                return candidate, (
                    "the cited authority is not unchanged and pre-existing"
                )
        candidate.update({
            "artifact": artifact,
            "note_unit": offer["note_unit"],
            "authority_artifact": authority,
            "authority_sha256": hashlib.sha256(authority_before).hexdigest(),
            "original_note_sha256": hashlib.sha256(note_before).hexdigest(),
            "contradiction": declaration["contradiction"],
            "resolution": declaration["resolution"],
        })
        unit["design_correction"] = candidate
        unit["design_correction_attempted"] = True
        st.append_event(
            self.state,
            "design_correction_proposed",
            unit=st.unit_key(unit),
            artifact=artifact,
            authority_artifact=authority,
        )
        return candidate, None

    def _design_correction_integrity_error(self, correction):
        brainstorming_authority = (correction or {}).get(
            "brainstorming_authority"
        )
        if brainstorming_authority is not None:
            try:
                authority_record = brainstorming_milestone.retained_revision(
                    self.state,
                    brainstorming_authority["session_id"],
                    brainstorming_authority["accepted_target_revision"],
                )
                exists, content = brainstorming.target_revision_content(
                    authority_record
                )
            except Exception:
                exists, content = False, None
            if (
                not exists
                or content is None
                or hashlib.sha256(content).hexdigest()
                != (correction or {}).get("authority_sha256")
            ):
                return (
                    "the retained Brainstorming authority changed or became "
                    "unavailable while the correction was provisional"
                )
            return None
        authority = self._safe_design_path(
            (correction or {}).get("authority_artifact")
        )
        content = self._workspace_bytes(authority) if authority else None
        if content is None or hashlib.sha256(content).hexdigest() != (
            correction or {}
        ).get("authority_sha256"):
            return "the cited authority changed while the correction was provisional"
        return None

    def _design_correction_review_context(self, correction):
        """Expose retained Brainstorming authority only to the review prompt."""
        context = copy.deepcopy(correction)
        authority = context.get("brainstorming_authority")
        if authority is None:
            return context
        record = brainstorming_milestone.retained_revision(
            self.state,
            authority["session_id"],
            authority["accepted_target_revision"],
        )
        exists, content = brainstorming.target_revision_content(record)
        if not exists:
            raise brainstorming_milestone.AdapterError(
                "the retained Brainstorming authority is absent"
            )
        try:
            context["retained_authority_content"] = content.decode("utf-8")
            context["retained_authority_encoding"] = "utf-8"
        except UnicodeDecodeError:
            context["retained_authority_content"] = base64.b64encode(
                content
            ).decode("ascii")
            context["retained_authority_encoding"] = "base64"
        return context

    def _rollback_design_correction(self, unit, reason, correction=None):
        """Discard the provisional fixer delta and retry without authority."""
        correction = correction or unit.get("design_correction") or {}
        baseline = correction.get("baseline") or {}
        try:
            gitops.restore_to_snapshot(
                self.workspace,
                baseline["refs"],
                baseline["sym"],
                baseline["head"],
                baseline["tree"],
                stash=baseline.get("stash"),
            )
            gitops.restore_index_tree(
                self.workspace, baseline.get("index_tree") or baseline["tree"]
            )
        except (KeyError, TypeError, gitops.GitError) as exc:
            st.fail_run(
                self.state,
                "design correction rollback failed: %s" % exc,
                unit=unit,
                type_="gap_cleanup",
            )
            self._save()
            raise StopStep("design correction rollback failed")
        unit["design_correction"] = None
        unit["design_correction_attempted"] = True
        unit["fix_queue"] = copy.deepcopy(
            correction.get("original_fix_queue") or []
        )
        unit["fix_source"] = copy.deepcopy(
            correction.get("original_fix_source")
        )
        unit["fix_loop_rounds"] = int(
            correction.get("original_fix_loop_rounds") or 0
        )
        if unit.get("status") != st.U_FIXING:
            st.transition_unit(
                self.state, unit, st.U_FIXING,
                reason="design correction rejected; retry without exception",
            )
        st.append_event(
            self.state,
            "design_correction_rolled_back",
            unit=st.unit_key(unit),
            reason=str(reason or "")[:300],
        )
        return "design correction rejected; fixer retries without exception"

    @staticmethod
    def _design_correction_gap(correction, decision, reason):
        return {
            "classification": (
                contracts.CLASSIFY_NEEDS_OPERATOR
                if decision == "needs_operator"
                else contracts.CLASSIFY_FITS_REMODEL
            ),
            "missing_or_conflict": correction.get("contradiction"),
            "where": correction.get("artifact"),
            "forced_decision": reason,
            "plain": correction.get("contradiction"),
            "example": correction.get("resolution"),
            "proposal": correction.get("resolution"),
        }

    def _ratify_design_correction(self, unit, correction, verdict, return_to):
        note = self._unit_by_key(correction.get("note_unit"))
        content = self._workspace_bytes(correction.get("artifact"))
        if note is None or content is None:
            st.fail_run(
                self.state, "ratified design correction lost its note", unit=unit
            )
            self._save()
            raise StopStep("ratified correction note missing")
        if hashlib.sha256(content).hexdigest() == correction.get(
            "original_note_sha256"
        ):
            return self._rollback_design_correction(
                unit,
                "the correction reviewer ratified an unchanged governing note",
                correction,
            )
        try:
            note_sha, sha = gitops.ratify_note_correction(
                self.workspace,
                correction["artifact"],
                note["gate_commit"],
                "Ratify slice %02d note correction" % unit["slice_id"],
            )
        except gitops.GitError as exc:
            st.fail_run(self.state, "ratification failed: %s" % exc, unit=unit)
            self._save()
            raise StopStep(str(exc))
        correction["phase"] = "ratified"
        correction["approved_sha256"] = hashlib.sha256(content).hexdigest()
        correction["ratified_commit"] = note_sha
        correction["verdict_reason"] = verdict.get("reason")
        for key in (
            "baseline", "original_fix_queue", "original_fix_source",
            "original_fix_loop_rounds",
        ):
            correction.pop(key, None)
        note["gate_commit"] = note_sha
        st.append_event(self.state, "amended", unit=st.unit_key(unit), sha=sha)
        st.append_event(
            self.state,
            "design_correction_ratified",
            unit=st.unit_key(unit),
            artifact=correction.get("artifact"),
            sha=sha,
            note_sha=note_sha,
            reason=str(verdict.get("reason") or "")[:300],
        )
        unit["fix_queue"] = []
        unit["fix_source"] = None
        unit.pop("phantom_retried", None)
        st.restart_reviews_after_candidate_change(
            self.state, unit, "ratified design correction changed bytes"
        )
        return_to = st.U_PRE_REVIEW_VERIFY
        st.transition_unit(
            self.state, unit, return_to,
            reason="own-note correction independently ratified",
        )
        return "design correction ratified; amended (%s)" % sha

    def _maybe_update_slices(self, unit, output):
        """Keep a legitimately edited skeleton table aligned with state."""
        slices = output.get("slices")
        if not slices or (
            unit["kind"] != st.UNIT_SKELETON
            and not unit.get("design_update")
        ):
            return
        if unit["kind"] != st.UNIT_SKELETON:
            before = list(self.state["milestone"]["slices"])
            old_ids = [item["id"] for item in before]
            new_ids = [item["id"] for item in slices]
            if [value for value in new_ids if value in old_ids] != old_ids:
                reason = (
                    "a lightweight design update may insert future slices, "
                    "but may not remove, renumber, or reorder existing ones"
                )
                st.fail_run(self.state, reason, unit=unit)
                self._save()
                raise StopStep(reason)
            added_ids = [value for value in new_ids if value not in old_ids]
            if len(added_ids) > 1:
                reason = (
                    "a lightweight design update may insert at most one "
                    "bounded future slice"
                )
                st.fail_run(self.state, reason, unit=unit)
                self._save()
                raise StopStep(reason)
            current_id = unit.get("slice_id")
            if current_id in new_ids:
                current_index = new_ids.index(current_id)
                additions_before_current = [
                    value for value in new_ids[:current_index]
                    if value not in old_ids
                ]
                if additions_before_current:
                    reason = (
                        "a lightweight design update may not insert work "
                        "before the slice currently being completed"
                    )
                    st.fail_run(self.state, reason, unit=unit)
                    self._save()
                    raise StopStep(reason)
        if slices != self.state["milestone"]["slices"]:
            self.state["milestone"]["slices"] = [dict(sl) for sl in slices]
            st.append_event(
                self.state,
                "slices_updated",
                unit=st.unit_key(unit),
                slices=self.state["milestone"]["slices"],
            )

    def _brainstorming_references(self, unit, signal):
        return brainstorming_milestone.stable_references(
            self.state,
            [
                ledgers.goal_path(self.state),
                self._skeleton_artifact(),
                self._governing(unit),
                unit.get("artifact"),
            ],
            signal["target_path"],
        )

    @staticmethod
    def _rethink_requests_design_amendment(signal):
        return (
            signal.get("result_mode")
            == contracts.RETHINK_RESULT_DESIGN_AMENDMENT
        )

    def _adopt_brainstorming_design_amendment(
        self, unit, wait, handoff
    ):
        """Persist one accepted, bounded amendment in the append-only ledger."""
        for event in self.state.get("events", []):
            if (
                event.get("type")
                == "brainstorming_design_amendment_adopted"
                and event.get("session_id") == handoff.get("session_id")
                and event.get("accepted_target_revision")
                == handoff.get("accepted_target_revision")
            ):
                return event
        retained = handoff.get("retained_target") or {}
        content = retained.get("content")
        if (
            retained.get("exists") is not True
            or retained.get("encoding") != "utf-8"
            or not isinstance(content, str)
        ):
            raise brainstorming_milestone.AdapterError(
                "an accepted design amendment must be one UTF-8 text artifact"
            )
        text = content
        if (
            not text.strip()
            or any(
                placeholder.strip() in text
                for placeholder in (
                    brainstorming_milestone.DESIGN_AMENDMENT_PLACEHOLDERS
                )
            )
        ):
            raise brainstorming_milestone.AdapterError(
                "the accepted design amendment still contains only its "
                "placeholder"
            )
        if "\x00" in text:
            raise brainstorming_milestone.AdapterError(
                "the accepted design amendment must be UTF-8 text without "
                "NUL bytes"
            )
        number = 1 + sum(
            event.get("type") == "brainstorming_design_amendment_adopted"
            for event in self.state.get("events", [])
        )
        source = wait["signal"].get("finding") or {}
        event = st.append_event(
            self.state,
            "brainstorming_design_amendment_adopted",
            unit=st.unit_key(unit),
            amendment_id="B%d" % number,
            text=text,
            session_id=handoff["session_id"],
            accepted_target_revision=handoff["accepted_target_revision"],
            source_finding_id=source.get("id"),
            target_path=wait["signal"].get("target_path"),
        )
        if unit.get("rounds"):
            st.restart_reviews_after_candidate_change(
                self.state, unit, "accepted Brainstorming design amendment"
            )
        return event

    def _design_document_paths(self):
        """Existing worker-authored design documents, in plan order."""
        paths = []
        by_key = {
            (candidate["kind"], candidate["slice_id"]): candidate
            for candidate in self.state.get("units") or []
        }
        for kind, slice_id in st.planned_units(self.state):
            if kind not in (st.UNIT_SKELETON, st.UNIT_SLICE_DOC):
                continue
            candidate = by_key.get((kind, slice_id))
            path = (candidate or {}).get("artifact")
            if not path:
                path = (
                    ledgers.skeleton_path(self.state)
                    if kind == st.UNIT_SKELETON
                    else ledgers.slice_note_path(self.state, slice_id)
                )
            if os.path.isfile(os.path.join(self.workspace, path)):
                paths.append(path)
        return paths

    def _activate_design_update(self, unit, handoff, amendment_event):
        """Authorize ordinary reviewable document edits after agreement."""
        previous = unit.get("design_update") or {}
        editable_paths = list(previous.get("editable_paths") or [])
        for path in self._design_document_paths():
            if path not in editable_paths:
                editable_paths.append(path)
        update = {
            "session_id": handoff["session_id"],
            "accepted_target_revision": handoff[
                "accepted_target_revision"
            ],
            "amendment_id": amendment_event.get("amendment_id"),
            "amendment": amendment_event.get("text"),
            "editable_paths": editable_paths,
        }
        if previous.get("changed_paths"):
            update["changed_paths"] = list(previous["changed_paths"])
        unit["design_update"] = update
        st.append_event(
            self.state,
            "brainstorming_design_update_authorized",
            unit=st.unit_key(unit),
            session_id=update["session_id"],
            accepted_target_revision=update["accepted_target_revision"],
            editable_paths=list(update["editable_paths"]),
        )
        return update

    @staticmethod
    def _editable_design_paths(unit):
        update = unit.get("design_update") or {}
        return list(update.get("editable_paths") or [])

    @staticmethod
    def _design_review_paths(unit):
        update = unit.get("design_update") or {}
        return list(update.get("changed_paths") or [])

    def _record_design_changes(self, unit, changed_paths):
        update = unit.get("design_update") or {}
        allowed = set(update.get("editable_paths") or [])
        changed = [path for path in changed_paths if path in allowed]
        if not changed:
            return
        merged = list(update.get("changed_paths") or [])
        for path in changed:
            if path not in merged:
                merged.append(path)
        update["changed_paths"] = merged
        unit["design_update"] = update

    def _design_amendment_finding_id(self, result):
        handoff = getattr(result, "brainstorming_handoff", None) or {}
        for event in reversed(self.state.get("events", [])):
            if (
                event.get("type")
                == "brainstorming_design_amendment_adopted"
                and event.get("session_id") == handoff.get("session_id")
                and event.get("accepted_target_revision")
                == handoff.get("accepted_target_revision")
            ):
                return event.get("source_finding_id")
        return None

    def _start_rethink(
        self,
        unit,
        kind,
        family,
        model,
        effort,
        signal,
        result,
        raw_path,
        raw_name,
        pre_snapshot=None,
    ):
        """Attach one non-completing worker signal to an independent session."""
        st.append_event(
            self.state,
            "brainstorming_origin_recorded",
            unit=st.unit_key(unit),
            kind=kind,
            family=family,
            model=model,
            effort=effort,
            raw_path=raw_path,
            duration_s=result.duration_s,
        )
        # The paid origin call is complete before session creation begins.
        # Persist its time now so a crash in the independent-session handoff
        # cannot erase the call and make a later at-least-once retry hide it.
        self._save()
        try:
            checked = brainstorming_milestone.validate_origin_signal(
                signal,
                kind,
                queued_findings=unit.get("fix_queue") or [],
            )
            if kind in contracts.REPORT_KINDS:
                self._validate_contests(
                    unit,
                    {"findings": [copy.deepcopy(checked["finding"])]},
                    kind,
                )
            provider_ref = getattr(result, "session_ref", None)
            if (
                kind in contracts.RETHINK_CONTINUATION_KINDS
                and (
                    not isinstance(provider_ref, str)
                    or not provider_ref.strip()
                )
            ):
                raise brainstorming_milestone.AdapterError(
                    "the origin provider exposed no explicit session reference"
                )
            references = self._brainstorming_references(unit, checked)
            authority_context = {
                "amendments": self._amendments(record_seen=False),
            }
            if self._rethink_requests_design_amendment(checked):
                project_context, _extensions, _roots = (
                    self._project_prompt_inputs(
                        unit, kind, record_seen=False
                    )
                )
                authority_context.update({
                    "goal": self.state.get("goal"),
                    "project_context": project_context,
                })
            lead_profile, counterpart_profile = (
                self._brainstorming_profiles()
            )
            created = brainstorming_milestone.create_session(
                self.state,
                self.config,
                st.unit_key(unit),
                checked,
                references,
                authority_context=authority_context,
                lead_profile=lead_profile,
                counterpart_profile=counterpart_profile,
            )
            progress = brainstorming.coordination_projection(created["state"])
            if (
                progress is None
                or progress["accepted_target_revision"] is not None
                or not progress["recovery_baseline_revision"]
            ):
                raise brainstorming_milestone.AdapterError(
                    "Brainstorming creation did not expose an unaccepted "
                    "recovery baseline"
                )
        except StopStep:
            raise
        except Exception as exc:
            st.fail_run(
                self.state,
                "need_rethink could not create its independent session: %s"
                % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming session creation failed")

        unit["brainstorming_wait"] = {
            "session_id": created["id"],
            "signal": copy.deepcopy(checked),
            "references": list(references),
            "origin": {
                "unit": st.unit_key(unit),
                "kind": kind,
                "family": family,
                "model": model,
                "effort": effort,
                "provider_session_ref": provider_ref,
                "raw_path": raw_path,
                "raw_name": raw_name,
                "duration_s": result.duration_s,
                "pre_snapshot": copy.deepcopy(pre_snapshot),
            },
        }
        st.append_event(
            self.state,
            "brainstorming_wait_started",
            unit=st.unit_key(unit),
            kind=kind,
            family=family,
            session_id=created["id"],
            target_path=checked["target_path"],
        )
        # The independent process is already live. Persist its attachment
        # before returning to the outer step so a later crash cannot leave a
        # successfully launched session invisible to its milestone.
        self._save()
        return "started Brainstorming session %s" % created["id"]

    @staticmethod
    def _resume_result(record):
        result = runners.RunnerResult(
            record.get("text", ""),
            0,
            record.get("duration_s", 0),
        )
        result.session_ref = record.get("provider_session_ref")
        result.brainstorming_handoff = copy.deepcopy(record.get("handoff"))
        result.origin_family = record.get("family")
        result.origin_model = record.get("model")
        result.origin_effort = record.get("effort")
        result.origin_pre_snapshot = copy.deepcopy(record.get("pre_snapshot"))
        return result

    def _take_brainstorming_resume(self, unit, kind):
        record = unit.get("brainstorming_resume")
        if not record:
            return None
        if record.get("kind") != kind:
            raise st.IllegalTransition(
                "Brainstorming continuation kind does not match current action"
            )
        unit.pop("brainstorming_resume", None)
        return (
            copy.deepcopy(record["output"]),
            self._resume_result(record),
            record["raw_path"],
        )

    def _brainstorming_review_handoff(self, unit, kind):
        record = unit.get("brainstorming_review_handoff")
        if not record:
            return None
        if (
            record.get("kind") == contracts.KIND_REVIEW_ROUND
            and kind == contracts.KIND_DELTA_REVIEW
        ):
            # A whole-artifact review handoff may need to wait while
            # verification/fixer/delta work converges. It belongs only in
            # the eventual family-zero full review, never in a diff review.
            return None
        if record.get("kind") != kind:
            raise st.IllegalTransition(
                "Brainstorming review handoff kind does not match current action"
            )
        handoff = brainstorming_milestone.prompt_handoff(
            self.state, record["handoff"]
        )
        handoff["source_finding"] = copy.deepcopy(
            record["source_finding"]
        )
        return handoff

    @staticmethod
    def _consume_brainstorming_review_handoff(unit, kind):
        record = unit.get("brainstorming_review_handoff")
        if not record or record.get("kind") != kind:
            raise st.IllegalTransition(
                "Brainstorming review handoff kind does not match consumption"
            )
        reserved = record.get("reserved_handoff")
        if reserved is None:
            unit.pop("brainstorming_review_handoff", None)
        else:
            unit["brainstorming_review_handoff"] = copy.deepcopy(reserved)

    def _fixer_gap_enabled(self, unit):
        """One shared eligibility gate for advertised and routed fixer gaps."""
        return (
            self._legacy_gap_enabled()
            and gitops.enabled(self.config)
            and not unit.get("under_repair")
            and unit["kind"] != st.UNIT_SKELETON
        )

    @staticmethod
    def _rethink_finding_for_fix(finding):
        return copy.deepcopy(finding)

    def _route_rethink_report_failure(self, unit, wait):
        kind = wait["origin"]["kind"]
        old_source = copy.deepcopy(unit.get("fix_source") or {})
        source_type = {
            contracts.KIND_REVIEW_ROUND: "round",
            contracts.KIND_DELTA_REVIEW: "delta",
        }[kind]
        return_to = {
            contracts.KIND_REVIEW_ROUND: st.U_ROUNDS,
            contracts.KIND_DELTA_REVIEW: (
                old_source.get("return_to") or st.U_PRE_REVIEW_VERIFY
            ),
        }[kind]
        st.enter_fix_episode(
            self.state,
            unit,
            [self._rethink_finding_for_fix(wait["signal"]["finding"])],
            source_type,
            wait["origin"]["family"],
            "brainstorming:%s" % wait["session_id"],
            return_to,
        )
        if kind == contracts.KIND_DELTA_REVIEW and old_source:
            unit["fix_source"]["origin_type"] = old_source.get(
                "origin_type", old_source.get("type", "delta")
            )

    def _restart_from_retired_seal_rethink(self, unit, reason):
        """Migrate an in-flight pre-derived-seal discussion to reviews."""
        st.restart_reviews_after_candidate_change(self.state, unit, reason)
        if unit["status"] in (st.U_SEALING, st.U_PRE_SEAL_VERIFY):
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason="retired seal discussion migrated to ordinary reviews",
            )
            return
        if unit["status"] not in (
            st.U_PRE_REVIEW_VERIFY,
            st.U_FIXING,
            st.U_DELTA_REVIEW,
        ):
            raise st.IllegalTransition(
                "retired seal discussion cannot migrate from status %s"
                % unit["status"]
            )

    def _migrate_retired_seal_review_handoff(self, unit):
        record = unit.get("brainstorming_review_handoff") or {}
        if record.get("kind") != RETIRED_SEAL_WORKER_KIND:
            return False
        record["kind"] = contracts.KIND_REVIEW_ROUND
        self._restart_from_retired_seal_rethink(
            unit, "persisted retired seal Brainstorming handoff migrated"
        )
        st.append_event(
            self.state,
            "brainstorming_review_handoff_migrated",
            unit=st.unit_key(unit),
            from_kind=RETIRED_SEAL_WORKER_KIND,
            to_kind=contracts.KIND_REVIEW_ROUND,
        )
        return True

    def _guarantee_calibration_config(self):
        value = self.config.get("guarantee_calibration")
        if not isinstance(value, dict) or value.get("enabled") is not True:
            return None
        rounds = value.get(
            "max_rounds",
            5,
        )
        if isinstance(rounds, bool) or not isinstance(rounds, int) \
                or rounds <= 0:
            rounds = 5
        return {"max_rounds": rounds}

    def _start_guarantee_calibration(self, unit):
        """Hold a drafted skeleton for one focused guarantee discussion."""
        settings = self._guarantee_calibration_config()
        if settings is None:
            return self._finish_draft(unit, "drafted")
        skeleton_path = unit.get("artifact") or self._skeleton_artifact()
        lead_profile, counterpart_profile = self._brainstorming_profiles()
        project_context, _extensions, _roots = self._project_prompt_inputs(
            unit, contracts.KIND_DRAFT_SKELETON, record_seen=False
        )
        references = brainstorming_milestone.stable_references(
            self.state,
            [skeleton_path, ledgers.goal_path(self.state)],
            skeleton_path,
        )
        try:
            created = (
                brainstorming_milestone.create_guarantee_calibration_session(
                    self.state,
                    self.config,
                    st.unit_key(unit),
                    skeleton_path,
                    lead_profile,
                    counterpart_profile,
                    references=references,
                    authority_context={
                        "amendments": self._amendments(record_seen=False),
                        "project_context": project_context,
                    },
                    max_rounds=settings["max_rounds"],
                )
            )
        except Exception as exc:
            unit["guarantee_calibration"] = {
                "status": "failed",
                "reason": str(exc)[:500],
            }
            st.fail_run(
                self.state,
                "guarantee calibration could not start: %s" % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("guarantee calibration creation failed")
        unit["guarantee_calibration"] = {
            "status": "running",
            "session_id": created["id"],
        }
        unit["brainstorming_wait"] = {
            "session_id": created["id"],
            "signal": None,
            "references": list(references),
            "origin": {
                "unit": st.unit_key(unit),
                "kind": "guarantee_calibration",
                "family": lead_profile["agent"],
                "model": lead_profile["model"],
                "effort": lead_profile["effort"],
                "raw_name": "%s-guarantee-calibration"
                % st.unit_key(unit),
            },
        }
        st.append_event(
            self.state,
            "brainstorming_wait_started",
            unit=st.unit_key(unit),
            kind="guarantee_calibration",
            family=lead_profile["agent"],
            session_id=created["id"],
            target_path=skeleton_path,
        )
        return "skeleton drafted; guarantee calibration started"

    def _complete_guarantee_calibration(self, unit, wait, handoff):
        expanded = brainstorming_milestone.prompt_handoff(
            self.state, handoff
        )
        retained = expanded.get("retained_target") or {}
        content = retained.get("content")
        if (
            retained.get("exists") is not True
            or retained.get("encoding") != "utf-8"
            or not isinstance(content, str)
            or not content.strip()
            or "\x00" in content
        ):
            raise brainstorming_milestone.AdapterError(
                "guarantee calibration did not retain one complete UTF-8 "
                "skeleton"
            )
        relpath = unit.get("artifact") or self._skeleton_artifact()
        path = os.path.join(self.workspace, relpath)
        with open(path, "r", encoding="utf-8") as handle:
            before = handle.read()
        changed = before != content
        if changed:
            tmp = path + ".guarantee-calibration.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(tmp, path)
        unit.pop("brainstorming_wait", None)
        unit["guarantee_calibration"] = {
            "status": "complete",
            "session_id": handoff["session_id"],
            "accepted_target_revision": handoff[
                "accepted_target_revision"
            ],
            "changed": changed,
        }
        st.append_event(
            self.state,
            "guarantee_calibration_completed",
            unit=st.unit_key(unit),
            session_id=handoff["session_id"],
            accepted_target_revision=handoff[
                "accepted_target_revision"
            ],
            changed=changed,
        )
        return self._finish_draft(unit, "guarantees calibrated")

    def _finish_draft(self, unit, reason):
        if gitops.enabled(self.config):
            try:
                pending = unit.get("pending_wip")
                if pending is None:
                    pending = {
                        "parent": gitops.head_full_sha(self.workspace),
                        "tree": gitops.snapshot_worktree_tree(self.workspace),
                        "message": "wip: %s" % st.display_unit_key(unit),
                        "reason": reason,
                    }
                    unit["pending_wip"] = pending
                    self._save()
                return self._complete_pending_wip(unit)
            except gitops.GitError as exc:
                st.fail_run(
                    self.state, "wip commit failed: %s" % exc, unit=unit
                )
                self._save()
                raise StopStep(str(exc))
        st.transition_unit(
            self.state, unit, st.U_PRE_REVIEW_VERIFY, reason=reason
        )
        unit.pop("implementation_attempt_snapshot", None)
        return "drafted %s" % (unit["artifact"] or "(implementation)")

    def _complete_pending_wip(self, unit):
        """Create or adopt exactly one durable WIP before reviews open."""
        pending = unit.get("pending_wip")
        if not isinstance(pending, dict):
            raise st.IllegalTransition("pending WIP metadata is missing")
        parent = pending.get("parent")
        tree = pending.get("tree")
        message = pending.get("message")
        reason = pending.get("reason") or "drafted"
        try:
            head = gitops.head_full_sha(self.workspace)
            if head == parent:
                if gitops.snapshot_worktree_tree(self.workspace) != tree:
                    raise gitops.GitError(
                        "the pending WIP candidate changed before recovery"
                    )
                sha = gitops.commit_wip(self.workspace, message)
            elif gitops.head_matches_wip(
                self.workspace, parent, tree, message
            ):
                sha = gitops.head_sha(self.workspace)
            else:
                raise gitops.GitError(
                    "HEAD no longer matches the pending WIP parent or its "
                    "already-created commit"
                )
        except gitops.GitError as exc:
            st.fail_run(
                self.state,
                "wip commit failed: %s" % exc,
                unit=unit,
                type_="wip_recovery",
            )
            self._save()
            raise StopStep(str(exc))
        st.append_event(
            self.state, "wip_commit", unit=st.unit_key(unit), sha=sha
        )
        unit.pop("pending_wip", None)
        unit.pop("implementation_attempt_snapshot", None)
        st.transition_unit(
            self.state, unit, st.U_PRE_REVIEW_VERIFY, reason=reason
        )
        return "drafted %s" % (unit["artifact"] or "(implementation)")

    def _record_brainstorming_work(self, unit, session_id, duration_s):
        """Attach one independent session's consumed LLM work exactly once."""
        if duration_s is None:
            return
        if any(
            event.get("type") == "brainstorming_work_recorded"
            and event.get("session_id") == session_id
            for event in self.state.get("events", [])
        ):
            return
        st.append_event(
            self.state,
            "brainstorming_work_recorded",
            unit=st.unit_key(unit),
            session_id=session_id,
            duration_s=duration_s,
        )

    def _do_brainstorming_wait(self):
        unit = st.current_unit(self.state)
        wait = copy.deepcopy(unit.get("brainstorming_wait") or {})
        session_id = wait.get("session_id")
        if not session_id:
            raise st.IllegalTransition(
                "brainstorming wait action has no recorded session"
            )
        if (wait.get("origin") or {}).get("unit") != st.unit_key(unit):
            raise st.IllegalTransition(
                "brainstorming wait origin does not match its attached unit"
            )
        try:
            handoff = brainstorming_milestone.terminal_handoff(
                self.state, session_id
            )
        except brainstorming_milestone.OperationalTerminalError as exc:
            # The terminal session remains retained evidence, but it must no
            # longer monopolize the unit's next action. Operator resume now
            # retries the unchanged originating milestone call.
            self._record_brainstorming_work(
                unit, session_id, exc.work_duration_s
            )
            unit.pop("brainstorming_wait", None)
            if (wait.get("origin") or {}).get("kind") \
                    == "guarantee_calibration":
                unit["guarantee_calibration"] = {
                    "status": "failed",
                    "session_id": session_id,
                    "reason": str(exc)[:500],
                }
            st.append_event(
                self.state,
                "brainstorming_operational_detached",
                unit=st.unit_key(unit),
                kind=(wait.get("origin") or {}).get("kind"),
                session_id=session_id,
            )
            st.fail_run(
                self.state,
                "recorded Brainstorming session ended operationally: %s" % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming execution failed")
        except Exception as exc:
            st.fail_run(
                self.state,
                "recorded Brainstorming session could not be inspected: %s"
                % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming inspection failed")
        if handoff is None:
            return "waiting for Brainstorming session %s" % session_id

        self._record_brainstorming_work(
            unit, session_id, handoff.get("work_duration_s")
        )

        origin = wait["origin"]
        kind = origin["kind"]
        if kind == "guarantee_calibration":
            if handoff["result"]["outcome"] == "failure":
                unit.pop("brainstorming_wait", None)
                unit["guarantee_calibration"] = {
                    "status": "failed",
                    "session_id": session_id,
                    "reason": "the participants did not agree",
                }
                st.append_event(
                    self.state,
                    "guarantee_calibration_failed",
                    unit=st.unit_key(unit),
                    session_id=session_id,
                )
                st.fail_run(
                    self.state,
                    "guarantee calibration ended without agreement",
                    unit=unit,
                    type_="guarantee_calibration",
                )
                self._save()
                raise StopStep("guarantee calibration did not agree")
            try:
                return self._complete_guarantee_calibration(
                    unit, wait, handoff
                )
            except Exception as exc:
                unit.pop("brainstorming_wait", None)
                unit["guarantee_calibration"] = {
                    "status": "failed",
                    "session_id": session_id,
                    "reason": str(exc)[:500],
                }
                st.append_event(
                    self.state,
                    "guarantee_calibration_failed",
                    unit=st.unit_key(unit),
                    session_id=session_id,
                )
                st.fail_run(
                    self.state,
                    "accepted guarantee calibration could not be applied: "
                    "%s" % exc,
                    unit=unit,
                    type_="brainstorming_operational",
                )
                self._save()
                raise StopStep("guarantee calibration adoption failed")
        if handoff["result"]["outcome"] == "failure":
            if self._modern_design_updates():
                unit.pop("brainstorming_wait", None)
                st.append_event(
                    self.state,
                    "brainstorming_failure_routed",
                    unit=st.unit_key(unit),
                    kind=kind,
                    session_id=session_id,
                )
                st.fail_run(
                    self.state,
                    "focused design discussion ended without agreement; "
                    "the original work and candidate are preserved",
                    unit=unit,
                    type_="brainstorming_no_agreement",
                )
                self._save()
                raise StopStep("Brainstorming ended without agreement")
            if (
                kind == contracts.KIND_FIX_FINDINGS
                and not self._fixer_gap_enabled(unit)
            ):
                # A discussion failure cannot broaden the ordinary fixer-gap
                # route. Preserve the fix episode and stop before any unwind.
                unit.pop("brainstorming_wait", None)
                st.fail_run(
                    self.state,
                    "Brainstorming failed for a fixer outside the supported "
                    "gap envelope; the existing fix episode is preserved for "
                    "operator intervention",
                    unit=unit,
                    type_="worker_blocked",
                )
                self._save()
                raise StopStep(
                    "Brainstorming fixer failure outside gap envelope"
                )
            unit.pop("brainstorming_wait", None)
            st.append_event(
                self.state,
                "brainstorming_failure_routed",
                unit=st.unit_key(unit),
                kind=kind,
                session_id=session_id,
            )
            if kind in contracts.RETHINK_CONTINUATION_KINDS:
                failure_gap = wait["signal"].get("failure_gap")
                if not isinstance(failure_gap, dict):
                    st.fail_run(
                        self.state,
                        "a historical Brainstorming continuation has no "
                        "failure_gap for its no-agreement route",
                        unit=unit,
                        type_="worker_protocol",
                    )
                    self._save()
                    raise StopStep("missing legacy failure gap")
                pre = origin.get("pre_snapshot") or {}
                return self._handle_gap(
                    unit,
                    {"gaps": [copy.deepcopy(failure_gap)]},
                    None,
                    pre_tree=pre.get("tree"),
                    pre_head=pre.get("head"),
                    pre_sym=pre.get("sym"),
                    pre_refs=pre.get("refs"),
                    pre_stash=pre.get("stash"),
                    pre_worktree_tree=pre.get("worktree_tree"),
                    from_fixer=kind == contracts.KIND_FIX_FINDINGS,
                )
            if kind == RETIRED_SEAL_WORKER_KIND:
                self._restart_from_retired_seal_rethink(
                    unit, "retired seal Brainstorming failed"
                )
                st.enter_fix_episode(
                    self.state,
                    unit,
                    [self._rethink_finding_for_fix(
                        wait["signal"]["finding"]
                    )],
                    "round",
                    origin.get("family"),
                    "brainstorming:%s" % session_id,
                    st.U_ROUNDS,
                )
                return (
                    "Brainstorming failed; retired seal finding queued and "
                    "ordinary reviews restarted"
                )
            self._route_rethink_report_failure(unit, wait)
            return "Brainstorming failed; source finding queued for fixing"

        if kind in contracts.RETHINK_CONTINUATION_KINDS:
            amendment_mode = self._rethink_requests_design_amendment(
                wait["signal"]
            )
            if amendment_mode:
                try:
                    amendment_event = self._adopt_brainstorming_design_amendment(
                        unit, wait, handoff
                    )
                    if self._modern_design_updates():
                        self._activate_design_update(
                            unit, handoff, amendment_event
                        )
                except brainstorming_milestone.AdapterError as exc:
                    unit.pop("brainstorming_wait", None)
                    st.fail_run(
                        self.state,
                        "accepted Brainstorming amendment could not be "
                        "adopted: %s" % exc,
                        unit=unit,
                        type_="brainstorming_operational",
                    )
                    self._save()
                    raise StopStep("Brainstorming amendment adoption failed")
            family = origin["family"]
            design_context = (
                self._design_correction_context(unit)
                if (
                    kind == contracts.KIND_FIX_FINDINGS
                    and (not self._modern_design_updates()
                         or unit.get("design_correction"))
                )
                else None
            )
            amendments = self._amendments()
            battery = (
                interpreter.battery_questions(self.state, unit["kind"])
                if kind == contracts.KIND_DRAFT_SLICE_NOTE
                else None
            )
            verification_repair = (
                kind == contracts.KIND_FIX_FINDINGS
                and (unit.get("fix_source") or {}).get("type")
                == "verification"
            )
            verification_commands = (
                self._verification_commands(unit)
                if verification_repair else None
            )
            project_context, extensions, roots = (
                self._project_prompt_inputs(unit, kind)
            )
            prompt = prompts.build_rethink_continuation(
                kind,
                family,
                self.workspace,
                brainstorming_milestone.prompt_handoff(
                    self.state, handoff
                ),
                allow_design_correction=bool(
                    design_context
                    and design_context.get("mode") == "offer"
                ),
                amendments=amendments,
                project_context=project_context,
                battery=battery,
                accepted_design_amendment=amendment_mode,
                editable_design_paths=(
                    self._editable_design_paths(unit)
                    if amendment_mode and self._modern_design_updates()
                    else None
                ),
                verification_repair=verification_repair,
                verification_commands=verification_commands,
                verification_signal=(
                    wait.get("signal", {}).get("finding")
                    if verification_repair else None
                ),
                unit_kind=unit["kind"],
                gap_enabled=(
                    self._fixer_gap_enabled(unit)
                    if verification_repair else False
                ),
            )
            durable_stabilization_size = None
            if kind == contracts.KIND_IMPLEMENT:
                durable_stabilization = unit.get(
                    "implementation_stabilization"
                )
                if durable_stabilization is not None:
                    durable_stabilization_size = (
                        copy.deepcopy(durable_stabilization.get(
                            "implementation_size"
                        ))
                        if isinstance(durable_stabilization, dict)
                        and isinstance(durable_stabilization.get(
                            "implementation_size"
                        ), dict)
                        else None
                    )
                    if durable_stabilization_size is None:
                        st.fail_run(
                            self.state,
                            "implementation stabilization metadata is "
                            "incomplete",
                            unit=unit,
                            type_="orchestrator",
                        )
                        self._save()
                        raise StopStep(
                            "implementation stabilization metadata incomplete"
                        )
                    self._ensure_implementation_stabilization_events(
                        unit, durable_stabilization_size
                    )
                    # The unit marker is current process truth. Brainstorming's
                    # origin snapshot is retained history and may predate a
                    # cutoff or a crash; it cannot reopen the size-monitored
                    # draft or drop the stabilizer's closing instruction.
                    prompt = self._implementation_stabilizer_prompt(
                        prompt, durable_stabilization_size
                    )
            raw_name = "%s-rethink-return" % origin["raw_name"]
            design_before = (
                self._snapshot() if unit.get("design_update") else None
            )
            validate_opts = {
                **(
                    {"allow_design_correction": True}
                    if design_context
                    and design_context.get("mode") == "offer"
                    else {}
                ),
                **(
                    {"battery_questions": battery}
                    if battery else {}
                ),
                **(
                    {"require_failure_gap": True}
                    if self._legacy_failure_gap_required(unit, kind)
                    else {}
                ),
                **(
                    {"verification_repair": True}
                    if verification_repair else {}
                ),
            } or None
            implementation_size = None
            implementation_stabilized = False
            if kind == contracts.KIND_IMPLEMENT:
                origin_pre_snapshot = origin.get("pre_snapshot") or {}
                fresh_stabilizer_session = bool(
                    durable_stabilization_size is not None
                    and not origin_pre_snapshot.get(
                        "implementation_stabilized"
                    )
                )
                (
                    output,
                    result,
                    raw_path,
                    implementation_size,
                    implementation_stabilized,
                ) = self._call_implementation(
                    family,
                    prompt,
                    raw_name,
                    origin.get("model"),
                    origin.get("effort"),
                    extensions,
                    roots,
                    validate_opts,
                    fresh_stabilizer_session,
                    (
                        unit.get("implementation_attempt_snapshot") or {}
                    ).get("tree")
                    or origin_pre_snapshot.get("tree"),
                    session_ref=(
                        None if fresh_stabilizer_session
                        else origin["provider_session_ref"]
                    ),
                    stabilizing=bool(
                        durable_stabilization_size is not None
                        or origin_pre_snapshot.get(
                            "implementation_stabilized"
                        )
                    ),
                )
                if durable_stabilization_size is not None:
                    implementation_size = durable_stabilization_size
                    implementation_stabilized = True
            else:
                output, result, raw_path = self._call(
                    family,
                    prompt,
                    kind,
                    raw_name,
                    model=origin.get("model"),
                    effort=origin.get("effort"),
                    extensions=extensions,
                    roots=roots,
                    validate_opts=validate_opts,
                    session_ref=origin["provider_session_ref"],
                )
            continued_pre_snapshot = copy.deepcopy(
                origin.get("pre_snapshot") or {}
            )
            if kind == contracts.KIND_IMPLEMENT:
                if (
                    implementation_size
                    and (
                        implementation_size.get("steer_delivered")
                        or implementation_size.get("interrupt_lines")
                    )
                ) or "implementation_size" not in continued_pre_snapshot:
                    continued_pre_snapshot["implementation_size"] = (
                        copy.deepcopy(implementation_size)
                    )
                continued_pre_snapshot["implementation_stabilized"] = bool(
                    continued_pre_snapshot.get("implementation_stabilized")
                    or implementation_stabilized
                )
            if design_before is not None:
                self._record_design_changes(
                    unit,
                    self._snapshot_diff(design_before, self._snapshot()),
                )
            unit.pop("brainstorming_wait", None)
            if output.get("status") == "need_rethink":
                return self._start_rethink(
                    unit,
                    kind,
                    family,
                    origin.get("model"),
                    origin.get("effort"),
                    output,
                    result,
                    raw_path,
                    raw_name,
                    pre_snapshot=continued_pre_snapshot,
                )
            unit["brainstorming_resume"] = {
                "kind": kind,
                "output": copy.deepcopy(output),
                "raw_path": raw_path,
                "duration_s": result.duration_s,
                "text": result.text,
                "provider_session_ref": (
                    getattr(result, "session_ref", None)
                    or origin["provider_session_ref"]
                ),
                "handoff": copy.deepcopy(handoff),
                "family": family,
                "model": origin.get("model"),
                "effort": origin.get("effort"),
                "pre_snapshot": continued_pre_snapshot,
            }
            st.append_event(
                self.state,
                "brainstorming_builder_continued",
                unit=st.unit_key(unit),
                kind=kind,
                session_id=session_id,
                accepted_target_revision=handoff[
                    "accepted_target_revision"
                ],
            )
            return "Brainstorming succeeded; origin conversation continued"

        unit.pop("brainstorming_wait", None)
        origin_kind = kind
        if kind == RETIRED_SEAL_WORKER_KIND:
            self._restart_from_retired_seal_rethink(
                unit, "retired seal Brainstorming succeeded"
            )
            kind = contracts.KIND_REVIEW_ROUND
        review_handoff = {
            "kind": kind,
            "handoff": copy.deepcopy(handoff),
            "source_finding": copy.deepcopy(wait["signal"]["finding"]),
        }
        pending = unit.get("brainstorming_review_handoff")
        if pending is not None:
            if (
                kind == contracts.KIND_DELTA_REVIEW
                and pending.get("kind") == contracts.KIND_REVIEW_ROUND
            ):
                review_handoff["reserved_handoff"] = copy.deepcopy(pending)
            else:
                raise st.IllegalTransition(
                    "Brainstorming review handoff would replace pending context"
                )
        unit["brainstorming_review_handoff"] = review_handoff
        st.append_event(
            self.state,
            "brainstorming_review_restarted",
            unit=st.unit_key(unit),
            kind=kind,
            origin_kind=origin_kind,
            session_id=session_id,
            accepted_target_revision=handoff["accepted_target_revision"],
        )
        return "Brainstorming succeeded; fresh reviewer call required"

    def _check_worker_blocked(self, unit, output, kind):
        if output["status"] == "retry":
            # A fixer could not complete its mandatory opposite-family
            # consultation. This is neither a finding disposition nor an
            # operator decision: fail through the established `unknown`
            # lane so the service guard restores failed_from=U_FIXING and
            # retries the same queue after its 15-minute emergency interval.
            # Preserve any partial delta for the next fixer to inspect, just
            # like a killed fixer call; sealed-doc tampering was already
            # restored by _enforce_sealed_artifacts before this check.
            unit["killed_fix_notice"] = "consultation unavailable"
            detail = str(output.get("notes") or "").strip()
            reason = (
                "%s consultation unavailable; transient retry requested"
                % kind
            )
            if detail:
                reason += ": %s" % detail[:500]
            st.fail_run(
                self.state,
                reason,
                unit=unit,
                type_="unknown",
                evidence="worker reported consultation_unavailable",
            )
            self._save()
            raise StopStep("consultation unavailable")
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
            A_BRAINSTORM_WAIT: self._do_brainstorming_wait,
        }[action.type]
        waiting_session = (
            self._brainstorming_wait_session()
            if action.type == A_BRAINSTORM_WAIT else None
        )
        with self._exclusive():
            self._assert_not_stale()
            try:
                note = handler()
            except StopStep as exc:
                return action, "run failed: %s" % exc
            if (
                action.type == A_BRAINSTORM_WAIT
                and self._brainstorming_wait_session() == waiting_session
            ):
                return action, note
            self._save()
            return action, note

    def _brainstorming_wait_session(self):
        unit = st.current_unit(self.state)
        if unit is None:
            return None
        return (unit.get("brainstorming_wait") or {}).get("session_id")

    def run(self, max_steps=1000):
        steps = 0
        while True:
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
            if steps >= max_steps and action.type != A_BRAINSTORM_WAIT:
                return 3
            sealed_before = self._sealed_keys()
            waiting_session = (
                self._brainstorming_wait_session()
                if action.type == A_BRAINSTORM_WAIT else None
            )
            self.step()
            if (
                action.type == A_BRAINSTORM_WAIT
                and self._brainstorming_wait_session() == waiting_session
            ):
                time.sleep(BRAINSTORMING_POLL_INTERVAL_S)
                continue
            steps += 1
            newly_sealed = self._sealed_keys() - sealed_before
            if newly_sealed and self._control().get("stop_after_seal"):
                # Operator-ordered safe pause: a seal is the one point
                # where worktree == HEAD == reviewed (the seal predicate),
                # so stopping here leaves the repo committed and clean for
                # an out-of-band build. One-shot: the flag clears on
                # honoring; a plain start resumes exactly where paused.
                with self._exclusive():
                    self._assert_not_stale()
                    st.append_event(
                        self.state, "paused_after_seal",
                        units=sorted(newly_sealed),
                        note="operator-ordered safe pause at a sealed "
                             "point (worktree == HEAD == reviewed)",
                    )
                    self._save()
                self._clear_stop_after_seal()
                return 4
        return 3

    def _goal_for(self, unit):
        """The GOAL block a unit's prompts carry.

        Reform runs preserve the operator's goal as generated goal.md before
        the skeleton call. The skeleton consumes the goal inline when small;
        a LARGE goal (config goal_inline_max) rides as that ledger with an
        ordered full read instead of
        inline text: instructions must dominate a prompt (a 60K goal
        drowns the altitude rules and the output contract), and a file
        survives the worker's own context compaction where inline prose
        does not — the worker can re-read ground truth at any point.

        Reform runs, later units consume the current reviewed skeleton
        (spec §2's chain of consumption) — operator planning prose stops
        riding every downstream call, and downstream workers judge scope
        against that reviewed boundary rather than a raw brainstorm's
        non-binding sketches; goal.md stays one read away.

        Legacy and profile-less runs keep the full goal inline
        everywhere (bit-identical)."""
        if not interpreter.reform_active(self.state):
            return self.state["goal"]
        if unit["kind"] == st.UNIT_SKELETON:
            self._ensure_goal_ledger()
            limit = self.config.get("goal_inline_max")
            if not isinstance(limit, int) or limit <= 0:
                limit = 8000
            if len(self.state["goal"]) <= limit:
                return self.state["goal"]
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
            "the current reviewed skeleton at %s is the operative "
            "restatement of "
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

    def _resume_preserved_candidate(self, unit):
        """Replay a parked implementation only when its slice is due again."""
        marker = unit.get("preserved_candidate") or {}
        tree = marker.get("tree")
        refname = marker.get("ref")
        base = marker.get("base")
        if not (tree and refname and base) or not gitops.enabled(self.config):
            st.fail_run(
                self.state,
                "preserved candidate metadata is incomplete; refusing to "
                "rebuild or discard it",
                unit=unit,
                type_="candidate_replay",
            )
            self._save()
            raise StopStep("preserved candidate metadata incomplete")
        resume_base = marker.get("resume_base")
        merged_tree = marker.get("merged_tree")
        if resume_base is None or merged_tree is None:
            if gitops.parked_candidate_tree(self.workspace, refname) != tree:
                st.fail_run(
                    self.state,
                    "parked candidate ref is missing or changed; refusing to "
                    "rebuild or discard the saved implementation",
                    unit=unit,
                    type_="candidate_replay",
                )
                self._save()
                raise StopStep("parked candidate ref unavailable")
            resume_base = gitops.head_full_sha(self.workspace)
            try:
                merged_tree, conflicts = gitops.merge_candidate_tree(
                    self.workspace, base, resume_base, tree
                )
            except gitops.GitError as exc:
                st.fail_run(
                    self.state,
                    "could not prepare preserved candidate replay: %s" % exc,
                    unit=unit,
                    type_="candidate_replay",
                )
                self._save()
                raise StopStep(str(exc))
            if conflicts:
                marker["conflicts"] = conflicts
                st.fail_run(
                    self.state,
                    "preserved candidate overlaps repaired or newly inserted "
                    "work at %s; the candidate remains parked for explicit "
                    "resolution" % ", ".join(conflicts[:20]),
                    unit=unit,
                    type_="candidate_replay",
                )
                self._save()
                raise StopStep("preserved candidate replay conflicts")
            marker["resume_base"] = resume_base
            marker["merged_tree"] = merged_tree
            st.append_event(
                self.state,
                "candidate_replay_prepared",
                unit=st.unit_key(unit),
                base=resume_base,
                merged_tree=merged_tree,
            )
            return "preserved candidate replay prepared"
        try:
            sha = gitops.restore_parked_candidate(
                self.workspace,
                resume_base,
                merged_tree,
                "wip: %s (preserved after design repair)" % st.unit_key(unit),
            )
            gitops.delete_parked_candidate(self.workspace, refname)
        except gitops.GitError as exc:
            st.fail_run(
                self.state,
                "could not restore preserved candidate: %s" % exc,
                unit=unit,
                type_="candidate_replay",
            )
            self._save()
            raise StopStep(str(exc))
        unit.pop("preserved_candidate", None)
        st.append_event(
            self.state,
            "candidate_replayed_after_redoc",
            unit=st.unit_key(unit),
            sha=sha,
            tree=merged_tree,
        )
        return None

    def _do_draft(self):
        unit = st.current_unit(self.state)
        if unit.get("preserved_candidate"):
            prepared = self._resume_preserved_candidate(unit)
            if prepared is not None:
                return prepared
        if unit.get("draft") is not None:
            if unit.get("pending_wip"):
                return self._complete_pending_wip(unit)
            if (
                unit["kind"] == st.UNIT_SLICE_IMPL
                and unit.get("implementation_attempt_snapshot")
                and gitops.enabled(self.config)
            ):
                # The WIP-intent snapshot itself may have failed before its
                # marker was saved.  New size-controlled implementations
                # retain their attempt baseline, so retry WIP preparation;
                # never fall through to the historical no-marker shortcut.
                return self._finish_draft(
                    unit, "recovered implementation draft"
                )
            if (
                unit["kind"] == st.UNIT_SKELETON
                and self._guarantee_calibration_config() is not None
                and (unit.get("guarantee_calibration") or {}).get("status")
                != "complete"
            ):
                return self._start_guarantee_calibration(unit)
            # Defensive compatibility for a persisted post-draft unit whose
            # status was left pending by an older/crashed driver. The work is
            # already present; never call the implementer twice or livelock
            # trying to establish a pre-work baseline after the fact.
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason="recovered pending unit with recorded draft",
            )
            return "recorded draft recovered; review cycle opened"
        if (
            unit["kind"] == st.UNIT_SLICE_IMPL
            and not unit.get("implementation_attempt_snapshot")
            and not self._baseline_verification_current(unit)
        ):
            # The baseline action and the implementer call are separate
            # durable steps. Re-check immediately before spending the worker
            # call so an operator edit between them cannot ride an obsolete
            # green proof.
            unit.pop("baseline_verification", None)
            return "implementation baseline changed; verification required"
        # Skeleton drafts (and re-drafts on remodel) run the `skeletoner`
        # act — one operator-chosen model for all skeleton content work,
        # default claude-opus-5/max; slice docs keep `drafter`, impl keeps
        # `implementer`. Only skeleton REVIEWS stay on the review families.
        if unit["kind"] == st.UNIT_SKELETON:
            act = "skeletoner"
            family, model, effort = self._skeletoner_profile()
        else:
            act = "implementer" if unit["kind"] == st.UNIT_SLICE_IMPL \
                else "drafter"
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
        gap_enabled = self._legacy_gap_enabled()
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
                editable_design_paths=self._editable_design_paths(unit),
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
                # Any implement whose governing note predates the skeleton's
                # latest reseal must READ that remodel — the gap REPORTER
                # (durable has_gap_remodel flag, resume-proof) and equally a
                # PRODUCER slice the remodel assigned work to whose own note
                # sealed before it. Otherwise the builder follows the stale
                # note, omits the assignment, and the reporter gaps again.
                # Reform-gated (gap_enabled): the block speaks the gap-exit
                # vocabulary, which legacy builders do not have.
                skeleton_path=self._skeleton_artifact(),
                remodeled=(gap_enabled
                           and (bool(unit.get("has_gap_remodel"))
                                or self._note_predates_skeleton(
                                    unit["slice_id"]))),
                editable_design_paths=self._editable_design_paths(unit),
                implementation_scope=self._implementation_scope(unit),
            )
        # The reviewed baseline as it stands BEFORE the builder runs: the local
        # ref map, HEAD's branch identity and commit tip, and the index tree
        # (== HEAD, or an adopted repo's staged pre-run edits). If the builder
        # gaps, these handles restore exactly this — undoing its scratch work
        # even if it staged, committed, switched or deleted branches — without
        # reverting the baseline.
        pre_refs = pre_sym = pre_head = pre_tree = pre_stash = None
        if gitops.enabled(self.config):
            try:
                pre_refs = gitops.snapshot_refs(self.workspace)
                pre_sym = gitops.head_symbolic_ref(self.workspace)
                pre_head = gitops.head_full_sha(self.workspace)
                pre_tree = gitops.snapshot_index_tree(self.workspace)
                pre_stash = gitops.snapshot_stash(self.workspace)
            except gitops.GitError:
                pre_refs = pre_sym = pre_head = pre_tree = pre_stash = None
        implementation_attempt = unit.get("implementation_attempt_snapshot")
        if kind == contracts.KIND_IMPLEMENT and gitops.enabled(self.config):
            # One implementation attempt may span provider failure, Resume,
            # Brainstorming, contract repair and cutoff recovery.  Freeze its
            # original Git baseline before the first worker call; never let
            # staged scratch from a dead worker become the next call's zero.
            if not implementation_attempt:
                queued = unit.get("brainstorming_resume") or {}
                queued_pre = queued.get("pre_snapshot") or {}
                source = queued_pre if queued_pre.get("tree") else {
                    "refs": pre_refs,
                    "sym": pre_sym,
                    "head": pre_head,
                    "tree": pre_tree,
                    "stash": pre_stash,
                }
                if (
                    source.get("refs") is not None
                    and source.get("sym") is not None
                    and source.get("head") is not None
                    and source.get("tree") is not None
                ):
                    implementation_attempt = {
                        key: copy.deepcopy(source.get(key))
                        for key in ("refs", "sym", "head", "tree", "stash")
                    }
                    unit["implementation_attempt_snapshot"] = (
                        implementation_attempt
                    )
                    st.append_event(
                        self.state,
                        "implementation_size_baseline_recorded",
                        unit=st.unit_key(unit),
                        tree=implementation_attempt["tree"],
                    )
                    self._save()
            if implementation_attempt:
                pre_refs = copy.deepcopy(implementation_attempt.get("refs"))
                pre_sym = implementation_attempt.get("sym")
                pre_head = implementation_attempt.get("head")
                pre_tree = implementation_attempt.get("tree")
                pre_stash = copy.deepcopy(implementation_attempt.get("stash"))
        raw_name = "%s-draft" % st.unit_key(unit)
        stabilization = (
            unit.get("implementation_stabilization")
            if kind == contracts.KIND_IMPLEMENT else None
        )
        stabilization_size = (
            copy.deepcopy(stabilization.get("implementation_size"))
            if isinstance(stabilization, dict)
            and isinstance(stabilization.get("implementation_size"), dict)
            else None
        )
        if stabilization is not None and stabilization_size is None:
            st.fail_run(
                self.state,
                "implementation stabilization metadata is incomplete",
                unit=unit,
                type_="orchestrator",
            )
            self._save()
            raise StopStep("implementation stabilization metadata incomplete")
        if stabilization_size is not None:
            self._ensure_implementation_stabilization_events(
                unit, stabilization_size
            )
            prompt = self._implementation_stabilizer_prompt(
                prompt, stabilization_size
            )
            raw_name += "-stabilize"
        resumed = self._take_brainstorming_resume(unit, kind)
        implementation_size = None
        implementation_stabilized = False
        design_before = None
        if resumed is not None:
            output, result, raw_path = resumed
            family = result.origin_family or family
            model = result.origin_model or model
            effort = result.origin_effort or effort
            original_pre = result.origin_pre_snapshot or {}
            pre_refs = original_pre.get("refs")
            pre_sym = original_pre.get("sym")
            pre_head = original_pre.get("head")
            pre_tree = original_pre.get("tree")
            pre_stash = original_pre.get("stash")
            implementation_size = copy.deepcopy(
                original_pre.get("implementation_size")
            )
            implementation_stabilized = bool(
                original_pre.get("implementation_stabilized")
            )
        else:
            if unit.get("design_update"):
                design_before = self._snapshot()
            validate_opts = {
                **(
                    {"battery_questions": battery}
                    if battery else {}
                ),
                **(
                    {"require_failure_gap": True}
                    if self._legacy_failure_gap_required(unit, kind)
                    else {}
                ),
            } or None
            start_session = kind in contracts.RETHINK_CONTINUATION_KINDS
            if kind == contracts.KIND_IMPLEMENT:
                (
                    output,
                    result,
                    raw_path,
                    implementation_size,
                    implementation_stabilized,
                ) = self._call_implementation(
                    family,
                    prompt,
                    raw_name,
                    model,
                    effort,
                    extensions,
                    roots,
                    validate_opts,
                    start_session,
                    (implementation_attempt or {}).get("tree") or pre_tree,
                    stabilizing=stabilization_size is not None,
                )
                if stabilization_size is not None:
                    implementation_size = stabilization_size
            else:
                output, result, raw_path = self._call(
                    family, prompt, kind, raw_name,
                    model=model, effort=effort, extensions=extensions,
                    roots=roots, validate_opts=validate_opts,
                    start_session=start_session,
                )
        if design_before is not None:
            self._record_design_changes(
                unit,
                self._snapshot_diff(design_before, self._snapshot()),
            )
        if output.get("status") == "need_rethink":
            self._enforce_sealed_artifacts(
                raw_name,
                editable_sealed=self._editable_design_paths(unit),
            )
            return self._start_rethink(
                unit,
                kind,
                family,
                model,
                effort,
                output,
                result,
                raw_path,
                raw_name,
                pre_snapshot={
                    "refs": pre_refs,
                    "sym": pre_sym,
                    "head": pre_head,
                    "tree": pre_tree,
                    "stash": pre_stash,
                    "implementation_size": copy.deepcopy(
                        implementation_size
                    ),
                    "implementation_stabilized": bool(
                        implementation_stabilized
                    ),
                },
            )
        if output.get("status") == "gap":
            # The builder met a build-changing hole/conflict and stopped
            # (reform §3). Route it upstream (repair) or to the operator
            # (goal). The unit finished NOTHING and stays pending; it
            # re-drafts after the repair reseals.
            return self._handle_gap(unit, output, result.duration_s,
                                    pre_tree=pre_tree, pre_head=pre_head,
                                    pre_sym=pre_sym, pre_refs=pre_refs,
                                    pre_stash=pre_stash)
        self._enforce_sealed_artifacts(
            raw_name,
            editable_sealed=self._editable_design_paths(unit),
        )
        self._check_worker_blocked(unit, output, kind)
        implementation_cut = output.get("implementation_cut")
        if implementation_cut is not None:
            st.record_implementation_cut(
                self.state,
                unit,
                implementation_cut["cut_scope"],
                implementation_cut["remaining_scope"],
                steer_lines=(implementation_size or {}).get("steer_lines"),
                interrupt_lines=(implementation_size or {}).get(
                    "interrupt_lines"
                ),
            )
        if kind == contracts.KIND_IMPLEMENT:
            unit.pop("implementation_stabilization", None)
        st.record_draft(self.state, unit, kind, output, raw_path,
                        family=family, duration=result.duration_s,
                        model=model, effort=effort)
        if kind == contracts.KIND_IMPLEMENT and output.get("suite_command"):
            st.set_discovered_suite(self.state, output["suite_command"])
        if unit["kind"] == st.UNIT_SKELETON:
            self.state["milestone"]["slices"] = output["slices"]
        elif output.get("slices"):
            self._maybe_update_slices(unit, output)
        if (
            unit["kind"] == st.UNIT_SKELETON
            and self._guarantee_calibration_config() is not None
        ):
            unit["guarantee_calibration"] = {"status": "pending"}
            return self._start_guarantee_calibration(unit)
        return self._finish_draft(unit, "drafted")

    # -- gap routing (reform §3: stop-report-repair-resume) -----------------

    def _find_unit(self, kind, slice_id):
        for u in self.state["units"]:
            if u["kind"] == kind and u["slice_id"] == slice_id:
                return u
        return None

    def _last_sealed_seq(self, unit_key):
        """Event seq of the unit's LAST transition to sealed, or -1. The
        ledger seq is the run's total order — unlike second-resolution
        timestamps, it cannot tie (same-second seals) or run backwards
        (DST rollback)."""
        last = -1
        for e in self.state["events"]:
            if e.get("type") == "unit_transition" \
                    and e.get("to_status") == st.U_SEALED \
                    and e.get("unit") == unit_key:
                last = e.get("seq", -1)
        return last

    @staticmethod
    def _last_seal_at(unit):
        for rec in reversed((unit or {}).get("seals") or []):
            if rec.get("passed"):
                return rec.get("at") or ""
        return ""

    def _note_predates_skeleton(self, slice_id):
        """True when the governing slice note sealed BEFORE the skeleton's
        latest reseal — i.e. a remodel happened after the note was written.
        The implementer must then read the CURRENT skeleton: a remodel may
        assign this slice work its (stale) note never mentions, and only
        the gap REPORTER carries has_gap_remodel — a PRODUCER slice whose
        note sealed pre-remodel would otherwise build from the stale note
        and force the reporter to gap again. Ordered by ledger seq (total,
        clock-proof); operator hand-seals may lack transition events, so
        the second-resolution seal timestamps remain as fallback."""
        skeleton = self._find_unit(st.UNIT_SKELETON, None)
        note = self._find_unit(st.UNIT_SLICE_DOC, slice_id)
        sk_seq = self._last_sealed_seq(st.UNIT_SKELETON)
        note_seq = self._last_sealed_seq(st.unit_key(note)) if note else -1
        if sk_seq >= 0 and note_seq >= 0:
            return sk_seq > note_seq
        sk_at, note_at = self._last_seal_at(skeleton), self._last_seal_at(note)
        return bool(sk_at and note_at and sk_at > note_at)

    def _gap_to_finding(self, gap, i, reporter_key):
        """A fits_remodel gap becomes a P1 repair OBJECTIVE for the skeleton
        fixer — a documentary target ("the design under-specifies X; update it
        so a NOT-YET-BUILT step produces X before the reporter needs it"),
        never orchestration vocabulary. Steps run in the slice TABLE's row
        order and the reporter re-drafts after the remodel, so the producer
        may be the reporter itself or any unbuilt step placed before it —
        including a NEW slice inserted in the table (current_unit follows
        table order, so an inserted step genuinely runs first). A sealed
        step is not rerun and its historical episode is not reopened, but it
        does not permanently own the files or code it introduced: the
        reporting or newly inserted slice may modify them when the revised
        skeleton assigns that work. Its proposal, when present, is carried
        as CONTEXT and marked as a proposal — the fixer verifies it against
        the sources, never adopts it on trust (reform decision 6)."""
        summary = (
            "REMODEL OBJECTIVE (a step downstream cannot proceed): %s. "
            "Update the skeleton design so this is resolved: specify which "
            "NOT-YET-BUILT step produces/records what is missing within its "
            "own scope — %s itself (the step that reported this and will "
            "re-draft against the remodel), or a step placed BEFORE it in "
            "the slice table (steps run in table order; a new slice inserted "
            "there runs first). Do not rerun or assign new work to an "
            "already-sealed step; instead assign the correction to one of "
            "those unbuilt steps. That implementing step may modify code "
            "first introduced by a sealed step when the revised scope "
            "requires it; historical seals stay closed. "
            "Resolve: %s."
        ) % (
            gap.get("missing_or_conflict", ""), reporter_key,
            gap.get("forced_decision", "")
        )
        if gap.get("proposal"):
            summary += (
                " Proposal (a PROPOSAL — verify independently against the "
                "sources, do not adopt on trust): %s" % gap["proposal"]
            )
        finding = {"id": "GAP%d" % (i + 1), "severity": "P1",
                   "summary": summary,
                   "validity": {
                       "permitted_baseline": (
                           "the goal is represented by a coherent skeleton "
                           "that assigns every required implementation"
                       ),
                       "actual_outcome": gap.get("missing_or_conflict", ""),
                       "incremental_harm": (
                           "the reporting step cannot implement the goal "
                           "until the design assigns the missing work"
                       ),
                       "exceeds_baseline": True,
                   }}
        if gap.get("plain"):
            finding["plain"] = gap["plain"]
        if gap.get("example"):
            finding["example"] = gap["example"]
        return finding

    def _handle_gap(self, unit, output, duration_s=None, pre_tree=None,
                    pre_head=None, pre_sym=None, pre_refs=None, pre_stash=None,
                    pre_worktree_tree=None, from_fixer=False):
        gaps = output.get("gaps", [])
        st.append_event(
            self.state, "gap_reported", unit=st.unit_key(unit),
            duration_s=duration_s,
            count=len(gaps),
            from_fixer=from_fixer,
            gaps=[{k: g.get(k)
                   for k in ("classification", "forced_decision", "plain")}
                  for g in gaps],
        )
        # Persist the validated gap BEFORE any cleanup or routing. From the
        # moment the worker returns a gap, a crash must RE-ROUTE it on restart,
        # never let the reporter silently re-draft: a divergent re-draft would
        # bury the design hole — drift through the back door, exactly what the
        # gap exit exists to prevent. The pre-call baseline snapshot rides along
        # so recovery can still clean the worktree deterministically.
        self.state["pending_gap"] = {
            "reporter": st.unit_key(unit),
            "gaps": gaps,
            "pre_tree": pre_tree,
            "pre_head": pre_head,
            "pre_sym": pre_sym,
            "pre_refs": pre_refs,
            "pre_stash": pre_stash,
            "pre_worktree_tree": pre_worktree_tree,
            # A FIXER gap is mid-episode, not a "finished nothing" builder:
            # its reporter already committed a draft wip and may hold prior
            # fix work, so the builder scratch-cleanup (restore to the
            # pre-CALL snapshot) misfires. _route_pending_gap branches on this.
            "from_fixer": from_fixer,
        }
        self._save()
        return self._route_pending_gap()

    def _park_fixer_candidate(self, unit, baseline, tree, refname):
        """Pause a built slice for redoc without erasing its implementation."""
        prior = unit["status"]
        unit["preserved_candidate"] = {
            "base": baseline,
            "tree": tree,
            "ref": refname,
        }
        unit["fix_queue"] = []
        unit["fix_source"] = None
        unit.pop("phantom_retried", None)
        unit.pop("baseline_verification", None)
        unit.pop("baseline_unstable_runs", None)
        unit.pop("brainstorming_resume", None)
        unit["fix_loop_rounds"] = 0
        unit["verify_fix_attempts"] = {"pre_review": 0, "pre_seal": 0}
        unit["rounds_amnesty"] = len(unit.get("rounds") or [])
        st.restart_reviews_after_candidate_change(
            self.state, unit, "candidate parked for sealed-design repair"
        )
        # Like reset_for_redraft, this is an intentional backward process
        # edge outside transition_unit. Unlike it, draft/artifact stay intact:
        # _do_draft's recovery branch reopens reviews without another builder.
        unit["status"] = st.U_PENDING
        st.append_event(
            self.state,
            "candidate_parked_for_redoc",
            unit=st.unit_key(unit),
            from_status=prior,
            base=baseline,
            tree=tree,
            ref=refname,
        )

    def _route_pending_gap(self):
        """Clean the worktree and route the recorded gap. Both the fresh path
        and the restart path come here, so it is rerunnable after a crash at
        any point: cleanup restores the recorded pre-call snapshot, and the
        fits_remodel reopen reuses an already-made repair commit and skips an
        already-applied reopen. Clears `pending_gap` once the gap reaches a
        durable terminal (an operator-gated failure, or the reopen applied)."""
        pending = self.state.get("pending_gap")
        if not pending:
            return "no pending gap"
        unit = self._unit_by_key(pending["reporter"])
        if unit is None:
            self.state["pending_gap"] = None
            self._save()
            return "pending gap has no reporter; cleared"
        gaps = pending["gaps"]
        # A BUILDER gap FINISHES NOTHING (contract: no artifact, no file
        # changes). A builder that touched the repo before deciding to gap
        # leaves that behind; left in place a later commit (the repair commit
        # below, or — after the operator amends and resumes — the next
        # successful draft's `git add -A`) would adopt it, and a junk commit
        # the builder made itself would become the repair commit's parent. Undo
        # it all now, BEFORE routing, back to the pre-call snapshot. A FIXER gap
        # is different: its pre-call worktree is the valuable slice candidate.
        # Its dedicated branch below restores that exact tree (discarding only
        # the gapping call's scratch), then either keeps it in place for an
        # operator goal decision or parks it outside the redoc checkout.
        if not pending.get("from_fixer") and gitops.enabled(self.config):
            pre_tree = pending.get("pre_tree")
            pre_head = pending.get("pre_head")
            pre_sym = pending.get("pre_sym")
            pre_refs = pending.get("pre_refs")
            pre_stash = pending.get("pre_stash")
            if (pre_tree is None or pre_head is None or pre_sym is None
                    or pre_refs is None):
                # No pre-call snapshot (rare: the pre-draft git reads failed).
                # Committed or staged-only junk, a branch switch, or a deleted
                # branch is unrecoverable without it, so never route the gap
                # over a repo we cannot restore. (pre_sym == "" is a valid
                # DETACHED snapshot, not a missing one — only None means
                # missing.)
                st.fail_run(
                    self.state,
                    "cannot clean the repo after a gap from %s: the pre-draft "
                    "baseline snapshot is missing, so a builder's scratch work "
                    "cannot be safely discarded — operator inspection required"
                    % st.unit_key(unit),
                    unit=unit, type_="gap_cleanup",
                )
                self._save()
                raise StopStep("gap cleanup: no baseline snapshot")

            def _stash_shas():
                return [e[0] for e in gitops.snapshot_stash(self.workspace)]

            stash_want = ([e[0] for e in pre_stash]
                          if pre_stash is not None else None)

            def _diverges():
                return (
                    gitops.snapshot_refs(self.workspace) != pre_refs
                    or gitops.head_symbolic_ref(self.workspace) != pre_sym
                    or gitops.head_full_sha(self.workspace) != pre_head
                    or gitops.snapshot_index_tree(self.workspace) != pre_tree
                    or gitops.has_builder_edits(self.workspace)
                    or (stash_want is not None
                        and _stash_shas() != stash_want)
                )
            try:
                if _diverges():
                    gitops.restore_to_snapshot(
                        self.workspace, pre_refs, pre_sym, pre_head, pre_tree,
                        stash=pre_stash,
                    )
                    st.append_event(
                        self.state, "gap_edits_discarded",
                        unit=st.unit_key(unit),
                    )
                # Prove the repo is actually back to the snapshot; if anything
                # resisted cleanup (e.g. a stubborn nested repo), FAIL rather
                # than commit over it.
                if _diverges():
                    raise gitops.GitError(
                        "repo still diverges from the baseline after restore"
                    )
            except gitops.GitError as exc:
                st.fail_run(
                    self.state,
                    "could not clean the repo after a gap from %s (%s): the "
                    "builder's scratch work cannot be safely discarded — "
                    "operator inspection required"
                    % (st.unit_key(unit), exc),
                    unit=unit, type_="gap_cleanup",
                )
                self._save()
                raise StopStep("gap cleanup failed")
        if not pending.get("from_fixer"):
            # Cleanup proved that this builder attempt has been abandoned.
            # A later re-draft must establish a fresh size baseline.
            unit.pop("implementation_attempt_snapshot", None)
            unit.pop("implementation_stabilization", None)
        operator_gaps = [
            g for g in gaps
            if g.get("classification") == contracts.CLASSIFY_NEEDS_OPERATOR
        ]
        if (
            not operator_gaps
            and self._modern_design_updates()
            and not gitops.enabled(self.config)
        ):
            # Only an already-running historical worker can still return this
            # retired result. Without Git there is no exact pre-call snapshot,
            # so retrying could adopt its abandoned scratch. Stop safely; never
            # fall through to the old re-documentation route.
            self.state["pending_gap"] = None
            st.fail_run(
                self.state,
                "cannot retry the retired in-goal gap from %s without an "
                "exact Git snapshot; inspect the preserved workspace and "
                "resume explicitly"
                % pending.get("reporter"),
                unit=unit,
                type_="gap_cleanup",
            )
            self._save()
            raise StopStep("retired gap has no restorable snapshot")
        if (
            not pending.get("from_fixer")
            and not operator_gaps
            and self._modern_design_updates()
        ):
            if int(unit.get("retired_gap_retries") or 0) >= 1:
                self.state["pending_gap"] = None
                st.fail_run(
                    self.state,
                    "%s repeated the retired in-goal gap route; use "
                    "need_rethink for the same design contradiction"
                    % pending.get("reporter"),
                    unit=unit,
                    type_="worker_protocol",
                )
                self._save()
                raise StopStep("retired in-goal gap route repeated")
            unit["retired_gap_retries"] = int(
                unit.get("retired_gap_retries") or 0
            ) + 1
            self.state["pending_gap"] = None
            st.append_event(
                self.state,
                "legacy_gap_retried_as_rethink",
                unit=st.unit_key(unit),
                from_fixer=False,
            )
            self._save()
            return (
                "retired in-goal gap cleared; the same draft retries with "
                "the rethink contract"
            )
        # A fixer gap is taken AFTER the slice already has a candidate. Restore
        # the exact PRE-FIXER worktree tree: this discards only the gapping
        # call's scratch while retaining the implementation and any earlier
        # accepted/pending fixes. A goal gap stops on those bytes. An in-goal
        # remodel parks the tree behind a durable ref, resets only the checkout
        # used by the documentation wave, and later replays the candidate over
        # the repaired/possibly-expanded history.
        if pending.get("from_fixer"):
            if gitops.enabled(self.config):
                pre_refs = pending.get("pre_refs")
                pre_sym = pending.get("pre_sym")
                pre_head = pending.get("pre_head")
                pre_tree = pending.get("pre_tree")
                candidate_tree = pending.get("pre_worktree_tree")
                baseline = gitops.newest_commit(
                    self.workspace,
                    [u.get("gate_commit") for u in self.state["units"]
                     if u.get("gate_commit")],
                )
                if (baseline is None or pre_refs is None or pre_sym is None
                        or pre_head is None or pre_tree is None
                        or candidate_tree is None):
                    self.state["pending_gap"] = None
                    st.fail_run(
                        self.state,
                        "cannot preserve fixer-gap reporter %s: missing its "
                        "exact pre-call candidate or sealed base — operator "
                        "inspection required" % st.unit_key(unit),
                        unit=unit, type_="gap_cleanup",
                    )
                    self._save()
                    raise StopStep("fixer-gap preservation: no baseline")
                try:
                    gitops.restore_to_snapshot(
                        self.workspace, pre_refs, pre_sym, pre_head,
                        candidate_tree,
                        stash=pending.get("pre_stash"),
                    )
                    if (
                        gitops.snapshot_worktree_tree(self.workspace)
                        != candidate_tree
                    ):
                        raise gitops.GitError(
                            "pre-fixer candidate tree did not restore exactly"
                        )
                except gitops.GitError as exc:
                    st.fail_run(
                        self.state,
                        "could not restore fixer-gap reporter %s before "
                        "routing (%s): candidate preserved for operator "
                        "inspection" % (st.unit_key(unit), exc),
                        unit=unit, type_="gap_cleanup",
                    )
                    self._save()
                    raise StopStep(str(exc))
                st.append_event(
                    self.state, "gap_edits_discarded", unit=st.unit_key(unit),
                    scope="gapping fixer scratch only",
                )
                if not operator_gaps and self._modern_design_updates():
                    if int(unit.get("retired_gap_retries") or 0) >= 1:
                        self.state["pending_gap"] = None
                        st.fail_run(
                            self.state,
                            "%s repeated the retired in-goal gap route; use "
                            "need_rethink for the same design contradiction"
                            % pending.get("reporter"),
                            unit=unit,
                            type_="worker_protocol",
                        )
                        self._save()
                        raise StopStep("retired fixer gap route repeated")
                    unit["retired_gap_retries"] = int(
                        unit.get("retired_gap_retries") or 0
                    ) + 1
                    self.state["pending_gap"] = None
                    st.append_event(
                        self.state,
                        "legacy_gap_retried_as_rethink",
                        unit=st.unit_key(unit),
                        from_fixer=True,
                    )
                    self._save()
                    return (
                        "retired fixer gap cleared; the same fix retries with "
                        "the rethink contract"
                    )
                if operator_gaps:
                    return self._route_goal_gap(unit, operator_gaps[0])
                refname = self._parked_candidate_ref(unit)
                try:
                    gitops.park_candidate_tree(
                        self.workspace, refname, candidate_tree
                    )
                    gitops.reset_hard(self.workspace, baseline)
                except gitops.GitError as exc:
                    st.fail_run(
                        self.state,
                        "could not park fixer-gap reporter %s for design "
                        "repair (%s) — operator inspection required"
                        % (st.unit_key(unit), exc),
                        unit=unit, type_="gap_cleanup",
                    )
                    self._save()
                    raise StopStep(str(exc))
                self._park_fixer_candidate(
                    unit, baseline, candidate_tree, refname
                )
        # The worker classified; the machine routes. needs_operator OUTRANKS
        # fits_remodel: a goal-level issue must reach the operator even if it
        # arrived alongside in-goal remodels. Everything else (all
        # fits_remodel) reopens the skeleton — the design authority — toward
        # the gaps as an objective; the design is remodelled and the pointer
        # continues, never touching the operator.
        if operator_gaps:
            return self._route_goal_gap(unit, operator_gaps[0])
        skeleton = self._find_unit(st.UNIT_SKELETON, None)
        if skeleton is None or skeleton is unit \
                or skeleton["status"] != st.U_SEALED:
            # A fits_remodel needs a sealed skeleton to remodel; a skeleton
            # builder cannot remodel itself. That is a routing impossibility,
            # not an operator decision — fail loudly rather than loop.
            self.state["pending_gap"] = None
            st.fail_run(
                self.state,
                "fits_remodel gap from %s has no sealed skeleton to remodel"
                % st.unit_key(unit),
                unit=unit, type_="gap_route",
            )
            self._save()
            raise StopStep("fits_remodel gap with no sealed skeleton")
        return self._reopen_and_repair(unit, skeleton, gaps, gaps[0])

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
        # Escalated: the operator-gated failure is now the durable record, so
        # the pending-gap intent is discharged.
        self.state["pending_gap"] = None
        self._save()
        raise StopStep("goal gap reported to the operator")

    def _commit_repair_wip(self, message):
        """Open the fresh repair commit atomically: snapshot the repo state
        immediately before committing, and on ANY GitError roll back to it —
        a commit hook that dirties the tree then fails, or a commit that lands
        but whose sha lookup fails, must not leave partial state the resumed
        run would fold in. Re-raises for the caller to fail the run."""
        snap = (
            gitops.snapshot_refs(self.workspace),
            gitops.head_symbolic_ref(self.workspace),
            gitops.head_full_sha(self.workspace),
            gitops.snapshot_index_tree(self.workspace),
        )
        try:
            return gitops.commit_wip(self.workspace, message)
        except gitops.GitError:
            try:
                gitops.restore_to_snapshot(self.workspace, *snap)
            except gitops.GitError:
                pass  # best effort; the caller fails the run regardless
            raise

    def _unit_by_key(self, key):
        for u in self.state["units"]:
            if st.unit_key(u) == key:
                return u
        return None

    def _reopen_and_repair(self, unit, target_unit, gaps, primary):
        target_key = st.unit_key(target_unit)
        reporter_key = st.unit_key(unit)
        # Idempotent restart: if the reopen already applied before a crash, the
        # pending-gap intent just needs discharging.
        if target_unit.get("under_repair"):
            self.state["pending_gap"] = None
            self._save()
            return "gap repair already applied; intent cleared"
        cap = int(self.config.get("max_gap_repairs", 3))
        n = int(unit.get("gap_repairs", 0)) + 1
        if n > cap:
            unit["gap_repairs"] = n
            self.state["pending_gap"] = None  # terminal failure; discharge it
            st.fail_run(
                self.state,
                "design remodel not converging after %d attempts on %s: the "
                "skeleton keeps being reopened for the same objective without "
                "clearing it — the objective may be malformed or the "
                "downstream builder keeps re-reporting; needs a look"
                % (cap, st.unit_key(unit)),
                unit=unit, type_="gap_stall",
            )
            self._save()
            raise StopStep("gap-repair cap exceeded")
        # Every fits_remodel gap routes to the skeleton (the design
        # authority), so all reported gaps become objectives for it, each
        # pinned to the reporting unit's own scope.
        repair_findings = [self._gap_to_finding(g, i, reporter_key)
                           for i, g in enumerate(gaps)]
        # The reopened design unit's own commit is buried under every unit
        # sealed since (HEAD is the latest sealed unit's commit); its repair
        # amends HEAD, so a fresh commit it owns keeps that amend from
        # rewriting a later sealed unit's commit. Always open a FRESH commit:
        # the whole gap transaction is durable (pending_gap was persisted
        # before routing), and on a crash-retry _route_pending_gap's cleanup
        # already reset the branch to the recorded pre-call HEAD — undoing any
        # stray repair commit a prior attempt made — so nothing is reused and
        # nothing stacks. (Reusing by commit shape could grab an unrelated
        # same-named commit and let the amend rewrite it.)
        sha = None
        if gitops.enabled(self.config):
            try:
                sha = self._commit_repair_wip("wip-repair: %s" % target_key)
            except gitops.GitError as exc:
                st.fail_run(
                    self.state,
                    "repair reopen commit failed: %s" % exc, unit=target_unit,
                )
                self._save()
                raise StopStep(str(exc))
        unit["gap_repairs"] = n
        # A DURABLE record that this slice's design was remodelled, distinct
        # from gap_repairs (a convergence cap the operator's resume resets to
        # 0): the re-draft's REMODEL ASSIGNMENT block gates on this, so a
        # post-resume draft still reads the remodelled skeleton instead of
        # silently following its stale sealed note.
        unit["has_gap_remodel"] = True
        # RE-DOCUMENTATION WAVE: the remodel reopens the WHOLE documentation
        # set — the skeleton (anchor) plus every sealed slice note. Whatever
        # the gap NAMED only orients the objective; it never bounds the edit
        # scope: the re-documenter has free rein under the GOAL to leave the
        # documentation coherent and continuable (restricting the set to the
        # named docs could leave an unnamed note incoherent and re-loop).
        # The notes wait in U_REPAIRING while the anchor's episode runs (its
        # fixer may edit them; the sealed-artifact guard only polices SEALED
        # units) and reseal via close_redoc_wave when the anchor's wave seal
        # passes. Docs reopen BEFORE the anchor so a crash mid-loop resumes
        # through the normal path (anchor still sealed -> re-route re-runs;
        # already-repairing docs are skipped).
        wave_docs = []
        for u in self.state["units"]:
            if u["kind"] != st.UNIT_SLICE_DOC:
                continue
            if u is target_unit or u is unit:
                continue
            if u.get("under_repair"):
                wave_docs.append(st.unit_key(u))  # resume: already reopened
                continue
            if u["status"] != st.U_SEALED:
                continue
            st.reopen_for_repair(
                self.state, u, primary,
                reason="re-documentation wave (gap from %s)" % reporter_key,
                reported_by=reporter_key,
            )
            wave_docs.append(st.unit_key(u))
        st.reopen_for_repair(
            self.state, target_unit, primary,
            reason="downstream %s reported a gap" % reporter_key,
            reported_by=reporter_key,
        )
        self.state["redoc_wave"] = {
            "anchor": target_key,
            "docs": wave_docs,
            "reporter": reporter_key,
        }
        if sha is not None:
            st.append_event(
                self.state, "wip_commit", unit=target_key, sha=sha
            )
        st.enter_fix_episode(
            self.state, target_unit, repair_findings, "repair", None,
            "%s-gap-repair" % target_key, st.U_PRE_SEAL_VERIFY,
        )
        # The reopen is applied and durable: discharge the intent.
        self.state["pending_gap"] = None
        self._save()
        return (
            "gap on %s -> re-documentation wave: reopened %s + %d slice "
            "note(s) (%d repair finding(s)); the set reseals, then %s %s"
            % (reporter_key, target_key, len(wave_docs),
               len(repair_findings), reporter_key,
               ("resumes its preserved candidate"
                if unit.get("preserved_candidate") else "re-drafts"))
        )

    def _pre_clean_pending_gap(self):
        """Best-effort worktree restore for a persisted-but-unrouted gap, run
        BEFORE repo validation so worker junk (e.g. a nested repo) cannot make
        ensure_repo reject the workspace and deadlock every resume. Silent on
        any error — a genuinely broken repo surfaces through ensure_repo, and
        _route_pending_gap re-verifies the cleanup before routing anyway.

        A FIXER gap runs this too (it must — its worker may have left a nested
        repo that would deadlock ensure_repo on every resume). For that branch
        the restore uses the exact pre-call WORKTREE tree, not merely its index,
        so accumulated legitimate fixes survive while gapping-call scratch is
        removed."""
        pending = self.state.get("pending_gap")
        if not pending or not gitops.enabled(self.config):
            return
        pre_refs = pending.get("pre_refs")
        pre_sym = pending.get("pre_sym")
        pre_head = pending.get("pre_head")
        pre_tree = pending.get("pre_tree")
        restore_tree = (
            pending.get("pre_worktree_tree")
            if pending.get("from_fixer") else pre_tree
        )
        pre_stash = pending.get("pre_stash")
        if pre_refs is None or pre_sym is None or pre_head is None \
                or restore_tree is None:
            return
        # Under the run lock, so it cannot race a concurrent invocation's
        # recovery; skips on contention (the lock holder restores) and on any
        # git error (a genuinely broken repo surfaces through ensure_repo).
        try:
            with self._exclusive():
                gitops.restore_to_snapshot(
                    self.workspace, pre_refs, pre_sym, pre_head, restore_tree,
                    stash=pre_stash,
                )
        except (ConcurrentRunError, gitops.GitError):
            pass

    def _consume_pending_gap(self):
        """A driver that died mid gap transaction (the validated gap recorded,
        not yet fully routed) re-routes it on startup, so the gap is never lost
        to a re-draft of the reporter. Idempotent: no intent is a no-op, an
        already-applied reopen just discharges the intent. Skipped while the
        run is failed — resume clears the failure first, then this runs.

        Runs UNDER the exclusive run lock, reloading fresh state so a second
        concurrent invocation cannot restore refs while this one is opening the
        repair commit; on lock contention it simply skips — the invocation that
        holds the lock does the (idempotent) recovery."""
        if not self.state.get("pending_gap") or self.state.get("failure"):
            return
        try:
            with self._exclusive():
                self.state = st.load(self.state_path)
                if not self.state.get("pending_gap") \
                        or self.state.get("failure"):
                    return
                self._route_pending_gap()
        except ConcurrentRunError:
            return
        except StopStep:
            pass  # a routing failure recorded a run failure; leave it be

    def _migrate_active_redoc_wave(self):
        """Retire an in-flight historical redocumentation wave.

        The current anchor keeps its ordinary fix/review position. Co-opened
        notes return to their prior terminal state, while every existing design
        document remains editable through one normal ``design_update`` owned by
        the anchor. Any active Brainstorming attachment and any parked
        implementation candidate are left untouched. The anchor's eventual
        ordinary gate binds the actually changed design paths.
        """
        if not self.state.get("redoc_wave"):
            return
        try:
            with self._exclusive():
                self.state = st.load(self.state_path)
                wave = self.state.get("redoc_wave")
                if not wave:
                    return
                anchor = self._unit_by_key(wave.get("anchor"))
                if anchor is None:
                    return
                anchor_sealed = anchor.get("status") == st.U_SEALED
                by_key = {
                    st.unit_key(unit): unit
                    for unit in self.state.get("units") or []
                }
                docs = [
                    by_key.get(key) for key in wave.get("docs") or []
                ]
                if any(
                    doc is None
                    or doc.get("status") not in (st.U_REPAIRING, st.U_SEALED)
                    for doc in docs
                ):
                    return

                editable_paths = self._design_document_paths()
                changed_paths = []
                candidates = [anchor] + [doc for doc in docs if doc is not None]
                for candidate in candidates:
                    artifact = candidate.get("artifact")
                    if not artifact or artifact not in editable_paths:
                        continue
                    changed = True
                    if gitops.enabled(self.config) and candidate.get("gate_commit"):
                        baseline = gitops.show_file(
                            self.workspace,
                            candidate["gate_commit"],
                            artifact,
                        )
                        changed = baseline != self._workspace_bytes(artifact)
                    if changed and artifact not in changed_paths:
                        changed_paths.append(artifact)

                for doc in docs:
                    if doc["status"] == st.U_REPAIRING:
                        st.transition_unit(
                            self.state,
                            doc,
                            st.U_SEALED,
                            reason=(
                                "historical redocumentation retired; changes "
                                "moved to the anchor's ordinary review"
                            ),
                        )

                trigger = next(
                    (
                        event for event in reversed(self.state.get("events") or [])
                        if event.get("type") == "reopened_for_repair"
                        and event.get("unit") == st.unit_key(anchor)
                    ),
                    {},
                )
                subject = (
                    trigger.get("plain")
                    or trigger.get("forced_decision")
                    or "the reported in-goal design contradiction"
                )
                text = (
                    "Apply the smallest coherent in-goal design update needed "
                    "for: %s. Preserve completed implementation and review the "
                    "changed design with the current unit's ordinary cycle."
                    % subject
                )
                amendment_id = "legacy-redoc-%d" % (
                    1
                    + sum(
                        event.get("type")
                        == "redoc_wave_migrated_to_design_update"
                        for event in self.state.get("events") or []
                    )
                )
                previous = anchor.get("design_update") or {}
                merged_editable = list(previous.get("editable_paths") or [])
                for path in editable_paths:
                    if path not in merged_editable:
                        merged_editable.append(path)
                merged_changed = list(previous.get("changed_paths") or [])
                for path in changed_paths:
                    if path not in merged_changed:
                        merged_changed.append(path)
                if not anchor_sealed:
                    anchor["design_update"] = {
                        **previous,
                        "amendment_id": amendment_id,
                        "amendment": text,
                        "editable_paths": merged_editable,
                        "changed_paths": merged_changed,
                    }
                anchor.pop("under_repair", None)
                self.state["redoc_wave"] = None
                st.append_event(
                    self.state,
                    (
                        "redoc_wave_retired_after_review"
                        if anchor_sealed
                        else "redoc_wave_migrated_to_design_update"
                    ),
                    unit=st.unit_key(anchor),
                    reporter=wave.get("reporter"),
                    amendment_id=amendment_id,
                    text=text,
                    authority="historical_design_update",
                    editable_paths=merged_editable,
                    changed_paths=merged_changed,
                )
                if anchor_sealed:
                    # The anchor's ordinary reviews already covered these
                    # bytes. Recover its post-review gate only when the crash
                    # occurred before that gate; never manufacture per-note
                    # review/seal records.
                    anchor_key = st.unit_key(anchor)
                    sealed_seq = gate_seq = -1
                    for event in self.state.get("events") or []:
                        if event.get("unit") != anchor_key:
                            continue
                        if (
                            event.get("type") == "unit_transition"
                            and event.get("to_status") == st.U_SEALED
                        ):
                            sealed_seq = event.get("seq", -1)
                        elif event.get("type") == "gate_commit":
                            gate_seq = event.get("seq", -1)
                    if gitops.enabled(self.config) and gate_seq < sealed_seq:
                        self.state["retired_redoc_docs_pending_gate"] = {
                            "anchor": anchor_key,
                            "docs": [st.unit_key(doc) for doc in docs],
                        }
                        self._gate_commit(anchor)
                    gate_sha = anchor.get("gate_commit")
                    if gate_sha:
                        for doc in docs:
                            doc["gate_commit"] = gate_sha
                    self._guard_unplanned_preserved_candidates()
                self._save()
        except ConcurrentRunError:
            return
        except StopStep:
            pass  # gate recovery recorded the failure and remains resumable

    def _slice_info(self, slice_id):
        for sl in self.state["milestone"]["slices"]:
            if sl["id"] == slice_id:
                return sl
        raise st.IllegalTransition("unknown slice id %r" % slice_id)

    def _guard_unplanned_preserved_candidates(self):
        """Never let a redoc row deletion silently destroy parked work."""
        planned = set(st.planned_units(self.state))
        for unit in self.state.get("units", []):
            marker = unit.get("preserved_candidate")
            if not marker or (unit["kind"], unit["slice_id"]) in planned:
                continue
            st.append_event(
                self.state,
                "preserved_candidate_lost_plan_assignment",
                unit=st.unit_key(unit),
                tree=marker.get("tree"),
                ref=marker.get("ref"),
            )
            st.fail_run(
                self.state,
                "repaired skeleton removed %s while its implementation "
                "candidate is parked at %s; refusing to discard or silently "
                "orphan that work" % (st.unit_key(unit), marker.get("ref")),
                unit=unit,
                type_="candidate_replay",
            )
            self._save()
            raise StopStep("preserved candidate lost its slice assignment")

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

    def _skeletoner_profile(self, origin_family=None):
        """(family, model, effort) for the `skeletoner` act, with the
        skeleton's OWN defaults re-asserted.

        The skeleton's declared defaults live in
        DEFAULT_CONFIG["acts"]["skeletoner"] (claude / claude-opus-5 / max),
        but merge_config replaces a whole act entry on a partial override —
        so a panel that customizes only the model drops the agent and
        effort. Left to the generic fallback, a model-only override would
        silently resolve to the codex fix-family (breaking: the codex CLI
        cannot run a claude model) and to claude's family effort instead of
        the skeleton's max. Re-assert the skeleton's family and effort here.
        The model stays None so _call fills it from the RESOLVED family's
        defaults — correct whichever family wins, whereas the skeleton's
        default model belongs only to its default family.
        """
        defaults = DEFAULT_CONFIG["acts"]["skeletoner"]
        family, model, effort = self._act_profile(
            "skeletoner", origin_family,
            default_family=defaults.get("agent"),
        )
        return family, model, effort or defaults.get("effort")

    def _family_defaults(self, family):
        d = (self.config.get("model_defaults") or {}).get(family) or {}
        return d.get("model"), d.get("effort")

    def _brainstorming_profiles(self):
        """Pin milestone discussions to their two configured voices."""
        family, model, effort = self._act_profile("implementer")
        default_model, default_effort = self._family_defaults(family)
        lead = {
            "agent": family,
            "model": model or default_model,
            "effort": effort or default_effort,
        }

        defaults = DEFAULT_CONFIG["acts"]["brainstorming_counterpart"]
        family, model, effort = self._act_profile(
            "brainstorming_counterpart",
            origin_family=lead["agent"],
            default_family=defaults["agent"],
        )
        default_model, default_effort = self._family_defaults(family)
        counterpart = {
            "agent": family,
            "model": (
                model
                or (defaults["model"] if family == defaults["agent"] else None)
                or default_model
            ),
            "effort": (
                effort
                or (defaults["effort"] if family == defaults["agent"] else None)
                or default_effort
            ),
        }
        return lead, counterpart

    def _modern_design_updates(self):
        # Compatibility must never restore retired redocumentation machinery.
        # Persisted runs with a missing or false historical flag use the same
        # lightweight rethink/design-update path as newly created runs.
        return True

    def _legacy_gap_enabled(self):
        return (
            interpreter.gap_semantics(self.state)
            and not self._modern_design_updates()
        )

    def _legacy_failure_gap_required(self, unit, kind):
        if (
            not self._legacy_gap_enabled()
            or kind not in contracts.RETHINK_CONTINUATION_KINDS
        ):
            return False
        return (
            kind != contracts.KIND_FIX_FINDINGS
            or self._fixer_gap_enabled(unit)
        )

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
        verification_repair = source.get("type") == "verification"
        verification_commands = (
            self._verification_commands(unit) if verification_repair else None
        )
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
        if unit["kind"] == st.UNIT_SKELETON:
            # The skeleton is drafted, fixed, and re-drafted by ONE
            # operator-chosen model (the `skeletoner` act, default
            # claude-opus-5/max); only its reviews stay on the review
            # families. So a skeleton fix runs `skeletoner`, not `fixer`.
            family, fix_model, fix_effort = self._skeletoner_profile(
                source.get("family")
            )
        else:
            family, fix_model, fix_effort = self._act_profile(
                "fixer", source.get("family"), default_family="codex"
            )
        consultation_family = self._resolve_act("consultation", family)
        project_context, extensions, roots = self._project_prompt_inputs(
            unit, contracts.KIND_FIX_FINDINGS
        )
        # New runs amend design through need_rethink and the ordinary review
        # cycle. Keep the old one-note envelope only for an already-persisted
        # correction episode.
        design_context = (
            self._design_correction_context(unit)
            if (not self._modern_design_updates()
                or unit.get("design_correction"))
            else None
        )
        legacy_design_process = (
            not self._modern_design_updates()
            or bool(unit.get("under_repair"))
            or design_context is not None
        )
        if (
            design_context
            and design_context.get("mode") == "active"
            and design_context.get("brainstorming_authority") is not None
        ):
            correction_error = self._design_correction_integrity_error(
                design_context
            )
            if correction_error:
                return self._rollback_design_correction(
                    unit, correction_error, design_context
                )
            try:
                design_context = self._design_correction_review_context(
                    design_context
                )
            except Exception as exc:
                return self._rollback_design_correction(
                    unit,
                    "the retained Brainstorming authority could not be read: "
                    "%s" % exc,
                    design_context,
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
            unit_kind=unit["kind"],
            amendments=self._amendments(),
            phantom_retry=bool(unit.get("phantom_retried")),
            killed_notice=bool(unit.pop("killed_fix_notice", None)),
            project_context=project_context,
            debt=self._debt(unit),
            repair_artifact=(
                # The editability declaration follows the unit's repair
                # CYCLE (under_repair: reopen -> ... -> reseal), not the
                # queue's source type: a delta-loop fix round inside a
                # repair re-queues with source "delta_review", and keying
                # off the source dropped the line there — the fixer then
                # refused to edit its own under-repair artifact.
                unit.get("artifact")
                if (source.get("type") == "repair"
                    or unit.get("under_repair"))
                else None
            ),
            repair_wave_docs=self._wave_doc_paths(unit),
            # The fixer earns the gap exit under the same reform gate as the
            # builders — but SCOPED to its primary case: a NORMAL slice fixer
            # (a doc/impl being built) that meets a queued finding unfixable in
            # scope because the sealed set contradicts itself. Excluded, keeping
            # the existing `blocked`->operator path:
            #  - git OFF: the candidate cannot be parked/replayed safely
            #    (production is git on; this only affects pure-CLI/test runs).
            #  - an UNDER_REPAIR reporter (a wave's co-reopened note): it is
            #    already inside a repair episode; a nested remodel is out of
            #    scope, and its worktree is the repair wip, not a slice draft.
            #  - the SKELETON: it cannot remodel itself.
            gap_enabled=(
                self._fixer_gap_enabled(unit)
            ),
            legacy_design_process=legacy_design_process,
            design_correction=design_context,
            editable_design_paths=self._editable_design_paths(unit),
            verification_repair=verification_repair,
            verification_commands=verification_commands,
            implementation_scope=self._implementation_scope(unit),
        )
        n_fix = 1 + len(
            [r for r in unit["rounds"] if r["kind"] == contracts.KIND_FIX_FINDINGS]
        )
        # Pre-call snapshot, exactly as the builder captures before its draft:
        # if the fixer GAPS (a queued finding is valid but unfixable in scope —
        # the sealed doc set contradicts itself), the gap FINISHES NOTHING and
        # the worktree-tree handle preserves the candidate, including earlier
        # pending fixes, while excluding scratch written by the gapping call.
        # The wave runs from the sealed base; the candidate is replayed later.
        pre_refs = pre_sym = pre_head = pre_tree = pre_worktree_tree = None
        pre_stash = None
        if gitops.enabled(self.config):
            try:
                pre_refs = gitops.snapshot_refs(self.workspace)
                pre_sym = gitops.head_symbolic_ref(self.workspace)
                pre_head = gitops.head_full_sha(self.workspace)
                pre_tree = gitops.snapshot_index_tree(self.workspace)
                # A persisted worker from an older driver may still return the
                # retired gap result even though current prompts never offer
                # it. Always retain the exact candidate so recovery cannot
                # discard fixes accumulated in earlier rounds.
                pre_worktree_tree = gitops.snapshot_worktree_tree(
                    self.workspace
                )
                pre_stash = gitops.snapshot_stash(self.workspace)
            except gitops.GitError:
                pre_refs = pre_sym = pre_head = pre_tree = None
                pre_worktree_tree = pre_stash = None
        raw_name = "%s-fix%d" % (st.unit_key(unit), n_fix)
        fix_workspace_before = self._snapshot()
        resumed = self._take_brainstorming_resume(
            unit, contracts.KIND_FIX_FINDINGS
        )
        if resumed is not None:
            output, result, raw_path = resumed
            family = result.origin_family or family
            fix_model = result.origin_model or fix_model
            fix_effort = result.origin_effort or fix_effort
            original_pre = result.origin_pre_snapshot or {}
            pre_refs = original_pre.get("refs")
            pre_sym = original_pre.get("sym")
            pre_head = original_pre.get("head")
            pre_tree = original_pre.get("tree")
            pre_worktree_tree = original_pre.get("worktree_tree")
            pre_stash = original_pre.get("stash")
        else:
            output, result, raw_path = self._call(
                family,
                prompt,
                contracts.KIND_FIX_FINDINGS,
                raw_name,
                model=fix_model,
                effort=fix_effort,
                extensions=extensions,
                roots=roots,
                validate_opts=(
                    {
                        **(
                            {"allow_design_correction": True}
                            if design_context
                            and design_context.get("mode") == "offer"
                            else {}
                        ),
                        **(
                            {"require_failure_gap": True}
                            if self._legacy_failure_gap_required(
                                unit, contracts.KIND_FIX_FINDINGS
                            )
                            else {}
                        ),
                        **(
                            {"verification_repair": True}
                            if verification_repair else {}
                        ),
                    } or None
                ),
                start_session=True,
            )
        # The sealed-artifact guard runs on EVERY outcome (gap or not, in
        # envelope or not) BEFORE any branch returns: a fixer that tampered with
        # a sealed doc and then gapped must still be caught and restored — the
        # gap must never be a side door around tamper detection.
        declaration = output.get("design_correction")
        active_correction = unit.get("design_correction") or {}
        editable_note = None
        if active_correction.get("phase") == "proposed":
            editable_note = active_correction.get("artifact")
        elif declaration is not None and design_context:
            editable_note = design_context.get("artifact")
        editable_documents = self._editable_design_paths(unit)
        if editable_note:
            editable_documents.append(editable_note)
        restored = self._enforce_sealed_artifacts(
            raw_name,
            editable_sealed=editable_documents,
        )
        fix_workspace_changed = self._snapshot_diff(
            fix_workspace_before, self._snapshot()
        )
        folded_commits = None
        self._record_design_changes(unit, fix_workspace_changed)
        if output.get("status") == "need_rethink":
            if restored:
                st.fail_run(
                    self.state,
                    "fixer requested Brainstorming after modifying sealed "
                    "artifacts: %s" % ", ".join(restored),
                    unit=unit,
                    type_="worker_blocked",
                )
                self._save()
                raise StopStep("rethink requester modified sealed artifacts")
            return self._start_rethink(
                unit,
                contracts.KIND_FIX_FINDINGS,
                family,
                fix_model,
                fix_effort,
                output,
                result,
                raw_path,
                raw_name,
                pre_snapshot={
                    "refs": pre_refs,
                    "sym": pre_sym,
                    "head": pre_head,
                    "tree": pre_tree,
                    "worktree_tree": pre_worktree_tree,
                    "stash": pre_stash,
                },
            )
        if output.get("status") == "gap":
            # The fixer met an insoluble-in-scope contradiction: a queued
            # finding is valid, but the only repair rewrites a sealed doc this
            # call may not touch. Rather than dead-end at `blocked` (operator),
            # it classifies the contradiction and the machine routes it exactly
            # like a builder gap — fits_remodel reopens the whole doc set as a
            # re-documentation wave (full dosage: re-document -> delta ->
            # reseal), needs_operator stops for the operator. The fix episode
            # finishes NOTHING; its sound findings are re-surfaced and re-fixed
            # after the design is made coherent.
            #
            # In-goal fixer gaps are retired in favor of need_rethink. A
            # persisted needs_operator gap remains recoverable so an old
            # in-flight call cannot lose a genuine operator decision.
            has_operator_gap = any(
                gap.get("classification")
                == contracts.CLASSIFY_NEEDS_OPERATOR
                for gap in output.get("gaps") or []
            )
            recoverable_retired_gap = (
                self._modern_design_updates() and gitops.enabled(self.config)
            )
            if (
                not self._fixer_gap_enabled(unit)
                and not has_operator_gap
                and not recoverable_retired_gap
            ):
                st.fail_run(
                    self.state,
                    "%s returned a contradiction gap outside the supported "
                    "envelope (needs a reform profile, git on, a normal slice, "
                    "not under repair) — resolve as an operator-reopened repair"
                    % contracts.KIND_FIX_FINDINGS,
                    unit=unit, type_="worker_blocked",
                )
                self._save()
                raise StopStep("fixer gap outside supported envelope")
            if active_correction.get("phase") == "proposed":
                baseline = active_correction.get("baseline") or {}
                self._rollback_design_correction(
                    unit, "fixer chose the normal gap exit",
                    active_correction,
                )
                pre_refs = baseline.get("refs")
                pre_sym = baseline.get("sym")
                pre_head = baseline.get("head")
                pre_tree = baseline.get("index_tree")
                pre_worktree_tree = baseline.get("tree")
                pre_stash = baseline.get("stash")
            return self._handle_gap(unit, output, result.duration_s,
                                    pre_tree=pre_tree, pre_head=pre_head,
                                    pre_sym=pre_sym, pre_refs=pre_refs,
                                    pre_stash=pre_stash,
                                    pre_worktree_tree=pre_worktree_tree,
                                    from_fixer=True)
        if (
            gitops.enabled(self.config)
            and pre_refs is not None
            and pre_sym is not None
            and pre_head is not None
            and pre_tree is not None
        ):
            try:
                folded_commits = gitops.fold_worker_commits_to_delta(
                    self.workspace,
                    pre_refs,
                    pre_sym,
                    pre_head,
                    pre_tree,
                    pre_stash,
                )
            except gitops.GitError as exc:
                reason = "fixer left an unsupported git mutation: %s" % exc
                st.fail_run(
                    self.state, reason, unit=unit,
                    type_="worker_git_mutation",
                )
                self._save()
                raise StopStep(reason)
            if folded_commits:
                st.append_event(
                    self.state,
                    "fixer_commits_folded",
                    unit=st.unit_key(unit),
                    baseline_head=folded_commits["baseline_head"],
                    worker_head=folded_commits["worker_head"],
                    commit_count=folded_commits["commit_count"],
                )
        self._check_worker_blocked(unit, output, contracts.KIND_FIX_FINDINGS)
        if verification_repair:
            if output.get("findings") != []:
                reason = (
                    "verification repair must return an empty findings list; "
                    "its ok status certifies the live full suite"
                )
                st.fail_run(
                    self.state, reason, unit=unit, type_="worker_protocol"
                )
                self._save()
                raise StopStep(reason)
        else:
            try:
                contracts.validate_fix_coverage(
                    output, unit.get("fix_queue") or []
                )
            except contracts.ContractError as exc:
                st.fail_run(self.state, str(exc), unit=unit)
                self._save()
                raise StopStep(str(exc))
            self._validate_adjudication_refs(unit, output)
            self._validate_contested_dispositions(unit, output)
        if active_correction.get("phase") == "proposed":
            correction_error = self._design_correction_integrity_error(
                active_correction
            )
            if restored:
                correction_error = (
                    "the provisional correction touched other sealed "
                    "artifacts: %s" % ", ".join(restored)
                )
            if correction_error:
                return self._rollback_design_correction(
                    unit, correction_error, active_correction
                )
        elif declaration is not None:
            candidate, correction_error = self._start_design_correction(
                unit,
                declaration,
                output.get("files_changed") or [],
                design_context,
                pre_refs,
                pre_sym,
                pre_head,
                pre_tree,
                pre_worktree_tree,
                pre_stash,
                brainstorming_handoff=getattr(
                    result, "brainstorming_handoff", None
                ),
            )
            if restored:
                correction_error = (
                    "the correction touched other sealed artifacts: %s"
                    % ", ".join(restored)
                )
            if correction_error:
                unit["design_correction_attempted"] = True
                return self._rollback_design_correction(
                    unit, correction_error, candidate
                )
        suite_corrected = False
        if (
            isinstance(output.get("suite_command"), str)
            and output["suite_command"].strip()
        ):
            # A queued finding may expose a missing OR narrowed suite from a
            # verification failure or review round. Correcting that run
            # state is a real fix even with zero file edits. The command is
            # part of review evidence, so changed commands invalidate prior
            # approvals and execute at the final boundary.
            command = output["suite_command"].strip()
            effective_before = self._verification_commands(unit)
            suite_state_changed = st.set_discovered_suite(
                self.state, output["suite_command"], replace=True
            )
            suite_corrected = bool(
                unit.get("suite_verification_pending")
                or (
                    bool(self.config.get("verification") or [])
                    and effective_before != [command]
                )
                # With no explicit verification, changing stored state is
                # the correction.  A documentation unit intentionally has
                # no effective gate, so merely repeating the already stored
                # command must not earn state-fix credit.
                or (
                    not bool(self.config.get("verification") or [])
                    and suite_state_changed
                )
            )
            if suite_corrected:
                unit["suite_verification_pending"] = True
        design_amendment_finding_id = self._design_amendment_finding_id(
            result
        )
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
                **({"suite_corrected": True} if suite_corrected else {}),
                **(
                    {
                        "design_amendment_finding_id":
                        design_amendment_finding_id,
                    }
                    if design_amendment_finding_id else {}
                ),
            },
        )
        if verification_repair:
            # The fixer owns the complete suite in this episode. Its `ok`
            # certifies the final workspace bytes; bind that assertion to the
            # exact candidate and commands so any later edit invalidates it.
            certified_fingerprint = self._verification_candidate_fingerprint()
            st.append_event(
                self.state,
                "verification",
                unit=st.unit_key(unit),
                stage="fixer",
                boundary="final",
                ok=True,
                commands=list(verification_commands or []),
                candidate_before=certified_fingerprint,
                candidate_after=certified_fingerprint,
                stable=True,
                vacuous=not bool(verification_commands),
                fixer_certified=True,
                raw_path=raw_path,
                output_tail="(fixer reported the configured full suite green)",
            )
            unit.pop("last_verification_output", None)
            unit.pop("suite_verification_pending", None)
            unit.pop("suite_armed_by_fix", None)
            unit["verify_fix_attempts"]["pre_seal"] = 0
        self._maybe_update_slices(unit, output)
        unit["fix_loop_rounds"] = unit.get("fix_loop_rounds", 0) + 1
        if (
            verification_repair
            and not fix_workspace_changed
            and not folded_commits
        ):
            target = source.get("return_to") or st.U_PRE_SEAL_VERIFY
            if (
                target == st.U_PRE_SEAL_VERIFY
                and st.seal_predicate_reviews(
                    unit,
                    self.config["families_order"],
                    current_fingerprint=self._review_evidence_fingerprint(unit),
                ) is None
            ):
                target = st.U_PRE_REVIEW_VERIFY
            unit["fix_queue"] = []
            unit["fix_source"] = None
            unit.pop("phantom_retried", None)
            st.transition_unit(
                self.state,
                unit,
                target,
                reason="full suite certified by fixer; no candidate delta",
            )
            return "full suite green; continuing without re-verification"
        if gitops.enabled(self.config):
            st.transition_unit(
                self.state, unit, st.U_DELTA_REVIEW, reason="fix applied"
            )
            return "fix call done (%d finding(s) triaged); delta review next" % len(
                output.get("findings", [])
            )
        # Without git there is no delta to review or amend: return directly.
        target = source.get("return_to") or st.U_PRE_REVIEW_VERIFY
        if fix_workspace_changed:
            st.restart_reviews_after_candidate_change(
                self.state, unit, "git-disabled fixer changed bytes"
            )
            target = st.U_PRE_REVIEW_VERIFY
        elif suite_corrected and target == st.U_ROUNDS:
            target = st.U_PRE_REVIEW_VERIFY
        elif (target == st.U_PRE_SEAL_VERIFY
              and st.seal_predicate_reviews(
                  unit,
                  self.config["families_order"],
                  current_fingerprint=self._review_evidence_fingerprint(unit),
              ) is None):
            target = st.U_PRE_REVIEW_VERIFY
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
                last_fix = r
                break
        if last_fix is None:
            return []
        result = last_fix["result"]
        design_amendment_finding_id = last_fix.get(
            "design_amendment_finding_id"
        )
        suite_corrected = bool(
            last_fix.get("suite_corrected")
            # Resume compatibility for a state saved by the earlier
            # suite-arming implementation between fix and delta review.
            or unit.pop("suite_armed_by_fix", None)
        )
        suite_finding_id = result.get("suite_command_finding_id")
        if suite_corrected and not suite_finding_id:
            # Old states predate the explicit binding.  Their arming fix was
            # safe only in the historical single-fixed-finding shape.
            fixed_ids = [
                finding.get("id") for finding in result.get("findings", [])
                if finding.get("disposition") == "fixed"
            ]
            if len(fixed_ids) == 1:
                suite_finding_id = fixed_ids[0]
        claims = []
        changed = []
        for p in result.get("files_changed") or []:
            norm = os.path.normpath(str(p))
            # Runtime-bookkeeping paths (either layout) are not real edits.
            if any(seg in (".orchestrator", ".run")
                   for seg in norm.split(os.sep)):
                continue
            changed.append(p)
        if changed:
            claims.append("files_changed=%s" % (changed,))
        for f in result.get("findings", []):
            if f.get("disposition") == "fixed":
                if not (
                    suite_corrected and f.get("id") == suite_finding_id
                    or design_amendment_finding_id
                    and f.get("id") == design_amendment_finding_id
                ):
                    # Only the explicitly bound finding earns state-fix
                    # credit; unrelated fixed claims still require real edits.
                    claims.append(
                        "finding %s disposed 'fixed'" % f.get("id")
                    )
            if f.get("prevention"):
                claims.append(
                    "finding %s claims a prevention edit in %s"
                    % (f.get("id"),
                       (f.get("prevention") or {}).get("documented_in"))
                )
        return claims

    def _do_delta_review(self):
        unit = st.current_unit(self.state)
        self._migrate_retired_seal_review_handoff(unit)
        correction = unit.get("design_correction") or {}
        provisional = (
            correction if correction.get("phase") == "proposed" else None
        )
        review_correction = provisional
        if provisional:
            correction_error = self._design_correction_integrity_error(
                provisional
            )
            if correction_error:
                return self._rollback_design_correction(
                    unit, correction_error, provisional
                )
            try:
                review_correction = self._design_correction_review_context(
                    provisional
                )
            except Exception as exc:
                return self._rollback_design_correction(
                    unit,
                    "the retained Brainstorming authority could not be read: "
                    "%s" % exc,
                    provisional,
                )
        source = unit.get("fix_source") or {}
        # The delta convergence checkpoint (delta_full_review_after_fixes)
        # escalates a review finding's fix loop to a full re-review after N
        # fixes. It is keyed off the episode's origin, not return_to, because
        # a pending suite re-verification may rewrite the latter.
        origin_type = st.active_fix_origin_type(self.state, unit)
        checkpoint_source = origin_type == "round"
        return_to = source.get("return_to") or st.U_PRE_REVIEW_VERIFY
        suite_verification_pending = bool(
            unit.get("suite_verification_pending")
            or unit.get("suite_armed_by_fix")
        )
        if suite_verification_pending and return_to == st.U_ROUNDS:
            return_to = st.U_PRE_REVIEW_VERIFY
        try:
            delta = gitops.worktree_diff(self.workspace)
        except gitops.GitError as exc:
            st.fail_run(self.state, "git diff failed: %s" % exc, unit=unit)
            self._save()
            raise StopStep(str(exc))
        if not delta.strip():
            if provisional:
                return self._rollback_design_correction(
                    unit,
                    "the proposed correction left no delta to ratify",
                    provisional,
                )
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
            if (return_to == st.U_PRE_SEAL_VERIFY
                    and st.seal_predicate_reviews(
                        unit,
                        self.config["families_order"],
                        current_fingerprint=(
                            self._review_evidence_fingerprint(unit)
                        ),
                    ) is None):
                return_to = st.U_PRE_REVIEW_VERIFY
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
        if (not provisional
                and checkpoint_source
                and checkpoint_after
                and fix_number >= checkpoint_after):
            # The fifth fix has already incorporated the previous delta's
            # known findings.  At this point another diff-only review would
            # inspect a large cumulative patch with less context than a full
            # re-review.  Checkpoint the WIP and follow the exact clean-delta
            # return edge. The accepted candidate changed, so every prior
            # whole-artifact approval is stale and review restarts at family
            # zero after verification.
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
            st.restart_reviews_after_candidate_change(
                self.state, unit, "delta checkpoint changed bytes"
            )
            return_to = st.U_PRE_REVIEW_VERIFY
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
            self._registry(),
            unit_kind=unit["kind"],
            governing=self._governing(unit),
            amendments=self._amendments(),
            project_context=project_context,
            debt=self._debt(unit),
            wave_docs=self._wave_doc_paths(unit),
            gap_enabled=self._legacy_gap_enabled(),
            design_correction=review_correction,
            editable_design_paths=self._design_review_paths(unit),
            implementation_scope=self._implementation_scope(unit),
        )
        rethink_handoff = self._brainstorming_review_handoff(
            unit, contracts.KIND_DELTA_REVIEW
        )
        if rethink_handoff is not None:
            prompt = prompts.attach_rethink_review_handoff(
                prompt, rethink_handoff
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
            validate_opts={
                **(
                    {"require_plain": True}
                    if interpreter.reform_active(self.state) else {}
                ),
                **(
                    {"require_design_correction_verdict": True}
                    if provisional else {}
                ),
            } or None,
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
        if rethink_handoff is not None:
            self._consume_brainstorming_review_handoff(
                unit, contracts.KIND_DELTA_REVIEW
            )
        if output.get("status") == "need_rethink":
            return self._start_rethink(
                unit,
                contracts.KIND_DELTA_REVIEW,
                family,
                delta_model,
                delta_effort,
                output,
                result,
                raw_path,
                "%s-delta%d" % (st.unit_key(unit), n_delta),
            )
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
        if provisional:
            verdict = output["design_correction_verdict"]
            decision = verdict["decision"]
            if decision == "ratify":
                correction_error = self._design_correction_integrity_error(
                    provisional
                )
                if correction_error:
                    return self._rollback_design_correction(
                        unit, correction_error, provisional
                    )
                return self._ratify_design_correction(
                    unit, provisional, verdict, return_to
                )
            if decision in ("remodel", "needs_operator"):
                baseline = provisional.get("baseline") or {}
                gap = self._design_correction_gap(
                    provisional, decision, verdict.get("reason")
                )
                self._rollback_design_correction(
                    unit, verdict.get("reason"), provisional
                )
                if decision == "needs_operator":
                    return self._route_goal_gap(unit, gap)
                if self._modern_design_updates():
                    st.append_event(
                        self.state,
                        "legacy_remodel_retried_as_rethink",
                        unit=st.unit_key(unit),
                        reason=str(verdict.get("reason") or "")[:300],
                    )
                    return (
                        "retired remodel verdict cleared; the same fixer "
                        "retries with the rethink contract"
                    )
                return self._handle_gap(
                    unit,
                    {"gaps": [gap]},
                    result.duration_s,
                    pre_tree=baseline.get("index_tree"),
                    pre_head=baseline.get("head"),
                    pre_sym=baseline.get("sym"),
                    pre_refs=baseline.get("refs"),
                    pre_stash=baseline.get("stash"),
                    pre_worktree_tree=baseline.get("tree"),
                    from_fixer=True,
                )
            # retry intentionally falls through to the existing dirty-delta
            # path below; the contract requires actionable findings.
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
            st.restart_reviews_after_candidate_change(
                self.state, unit, "accepted delta changed bytes"
            )
            return_to = st.U_PRE_REVIEW_VERIFY
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
                "validity": copy.deepcopy(f["validity"]),
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

    def _complete_seal_from_reviews(self, unit, verification_event=None):
        """Seal deterministically from current whole-artifact reviews."""
        families = self.config["families_order"]
        current_fingerprint = self._review_evidence_fingerprint(unit)
        cite = st.seal_predicate_reviews(
            unit, families, current_fingerprint=current_fingerprint
        )
        if cite is None:
            st.restart_reviews_after_candidate_change(
                self.state,
                unit,
                "seal boundary did not match cited review bytes",
            )
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason="seal evidence stale; ordinary reviews restarted",
            )
            return "%s review cycle restarted before seal" % st.unit_key(unit)
        if unit["status"] == st.U_PRE_SEAL_VERIFY:
            st.transition_unit(
                self.state, unit, st.U_SEALING,
                reason="verification passed; review predicate satisfied",
            )
        st.record_seal_attempt(
            self.state,
            unit,
            {},
            True,
            reviews=list(cite),
            verification_event_seq=(
                verification_event.get("seq")
                if verification_event is not None else None
            ),
        )
        seal_event = {"unit": st.unit_key(unit), "reviews": list(cite)}
        if verification_event is not None:
            seal_event["verification_event_seq"] = verification_event["seq"]
        st.append_event(self.state, "seal_satisfied", **seal_event)
        st.transition_unit(
            self.state,
            unit,
            st.U_SEALED,
            reason="all reviewers effectively clean on current bytes",
        )
        self._after_seal(unit)
        return "%s sealed from reviews %s" % (
            st.unit_key(unit), ", ".join(cite)
        )

    def _do_verify(self):
        unit = st.current_unit(self.state)
        stage = unit["status"]
        if self._migrate_retired_seal_review_handoff(unit):
            return "retired seal discussion migrated to ordinary reviews"

        baseline = (
            stage == st.U_PENDING
            and unit["kind"] == st.UNIT_SLICE_IMPL
            and unit.get("draft") is None
        )
        if stage == st.U_PRE_REVIEW_VERIFY:
            # Compatibility waypoint retained for existing states and the
            # many fix/review back-edges. Full suites are boundary checks,
            # not a tax between review cycles: reviews use focused checks,
            # and the complete suite runs once at the final boundary.
            unit.pop("skip_next_verify", None)
            st.append_event(
                self.state,
                "verification_deferred",
                unit=st.unit_key(unit),
                stage=stage,
                boundary="final",
                reason="full suite runs only after all reviewers are clean",
            )
            st.transition_unit(
                self.state,
                unit,
                st.U_ROUNDS,
                reason="full verification deferred to final boundary",
            )
            return "full verification deferred; review cycle opened"
        if not baseline and stage != st.U_PRE_SEAL_VERIFY:
            raise st.IllegalTransition(
                "verification cannot run from status %s" % stage
            )

        # Compatibility with states persisted by the retired generic
        # gate-reuse shortcut. Only a fixer that explicitly owned the full
        # suite may now certify this boundary without another execution.
        unit.pop("skip_next_verify", None)

        if stage == st.U_PRE_SEAL_VERIFY:
            current_fingerprint = self._review_evidence_fingerprint(unit)
            if st.seal_predicate_reviews(
                unit,
                self.config["families_order"],
                current_fingerprint=current_fingerprint,
            ) is None:
                st.restart_reviews_after_candidate_change(
                    self.state,
                    unit,
                    "pre-seal evidence missing or bound to different bytes",
                )
                st.transition_unit(
                    self.state,
                    unit,
                    st.U_PRE_REVIEW_VERIFY,
                    reason="pre-seal evidence stale; reviews restarted",
                )
                return "pre-seal evidence stale; review cycle restarted"

        commands = self._verification_commands(unit)
        verification_before = self._snapshot()
        candidate_before = self._verification_candidate_fingerprint(
            verification_before
        )
        if baseline:
            reusable = self._matching_final_verification(
                commands, candidate_before
            )
            if reusable is not None:
                event = st.append_event(
                    self.state,
                    "verification",
                    unit=st.unit_key(unit),
                    stage="baseline",
                    boundary="baseline",
                    ok=True,
                    commands=list(commands),
                    candidate_before=candidate_before,
                    candidate_after=candidate_before,
                    stable=True,
                    reused=True,
                    reused_from_seq=reusable["seq"],
                    output_tail=(
                        "(reused: exact bytes and commands passed at final "
                        "verification event %d)" % reusable["seq"]
                    ),
                )
                unit["baseline_verification"] = {
                    "event_seq": event["seq"],
                    "candidate_fingerprint": candidate_before,
                    "commands": list(commands),
                }
                unit.pop("baseline_unstable_runs", None)
                return "implementation baseline reused from final verification"
        else:
            reusable = self._matching_fixer_verification(
                commands, candidate_before
            )
            if reusable is not None:
                event = st.append_event(
                    self.state,
                    "verification",
                    unit=st.unit_key(unit),
                    stage=stage,
                    boundary="final",
                    ok=True,
                    commands=list(commands),
                    candidate_before=candidate_before,
                    candidate_after=candidate_before,
                    stable=True,
                    reused=True,
                    reused_from_seq=reusable["seq"],
                    fixer_certified=True,
                    output_tail=(
                        "(reused: fixer certified these exact bytes and "
                        "commands at event %d)" % reusable["seq"]
                    ),
                )
                unit.pop("suite_verification_pending", None)
                unit.pop("suite_armed_by_fix", None)
                unit["verify_fix_attempts"]["pre_seal"] = 0
                closed = self._complete_seal_from_reviews(
                    unit, verification_event=event
                )
                return "fixer suite result reused; %s" % closed

        verification_changed = []
        boundary = "baseline" if baseline else "final"
        self._mark_busy(
            "verification (%s)" % boundary, "verification", None
        )
        try:
            ok, output = run_verification(
                commands,
                self.workspace,
                self.config.get("verification_timeout"),
            )
        finally:
            self._clear_busy()
        verification_after = self._snapshot()
        verification_changed = self._snapshot_diff(
            verification_before, verification_after
        )
        candidate_after = self._verification_candidate_fingerprint(
            verification_after
        )
        verification_event = st.append_event(
            self.state,
            "verification",
            unit=st.unit_key(unit),
            stage="baseline" if baseline else stage,
            boundary=boundary,
            ok=ok,
            commands=list(commands),
            candidate_before=candidate_before,
            candidate_after=candidate_after,
            stable=not bool(verification_changed),
            vacuous=(not commands) or None,
            output_tail=(output or "")[-2000:],
        )

        if baseline:
            if ok and not verification_changed:
                unit["baseline_verification"] = {
                    "event_seq": verification_event["seq"],
                    "candidate_fingerprint": candidate_after,
                    "commands": list(commands),
                }
                unit.pop("baseline_unstable_runs", None)
                return "implementation baseline verified (%d command(s))" % len(
                    commands
                )
            if ok:
                attempts = int(unit.get("baseline_unstable_runs") or 0) + 1
                unit["baseline_unstable_runs"] = attempts
                if attempts <= self.config["max_verify_fix_attempts"]:
                    return (
                        "baseline verification changed candidate bytes; "
                        "repeating on the resulting tree"
                    )
                reason = (
                    "baseline verification kept changing candidate bytes "
                    "after %d attempts: %s"
                    % (
                        attempts,
                        runners.format_changes(verification_changed),
                    )
                )
            else:
                reason = (
                    "implementation baseline verification failed before any "
                    "slice bytes were produced; last output tail: %s"
                    % (output or "")[-1500:]
                )
            unit["last_verification_output"] = (output or "")[-4000:]
            st.fail_run(
                self.state,
                reason,
                unit=unit,
                type_="baseline_verification",
            )
            self._save()
            raise StopStep("implementation baseline verification failed")

        if verification_changed:
            st.restart_reviews_after_candidate_change(
                self.state,
                unit,
                "verification changed candidate bytes: %s"
                % runners.format_changes(verification_changed),
            )
        if ok:
            # A mechanical pass closes any pending suite-repair episode.
            unit.pop("suite_verification_pending", None)
            unit.pop("suite_armed_by_fix", None)
            unit["verify_fix_attempts"]["pre_seal"] = 0
            if verification_changed and stage == st.U_PRE_SEAL_VERIFY:
                st.transition_unit(
                    self.state,
                    unit,
                    st.U_PRE_REVIEW_VERIFY,
                    reason=("verification changed candidate bytes; "
                            "review approvals invalidated"),
                )
                return (
                    "verification ok but changed candidate bytes; "
                    "review cycle restarted"
                )
            sealed = self._complete_seal_from_reviews(
                unit, verification_event=verification_event
            )
            return "verification ok (%d command(s)); %s" % (
                len(commands), sealed
            )
        unit["verify_fix_attempts"]["pre_seal"] += 1
        unit.pop("last_verification_output", None)
        # Keep a unique source signal solely for durable episode identity and
        # the optional rethink handoff. The fixer receives no parsed failure
        # or output tail; it diagnoses the live suite itself.
        seq = unit.setdefault(
            "verify_episode_seq", {"pre_review": 0, "pre_seal": 0}
        )
        seq.setdefault("pre_seal", 0)
        seq["pre_seal"] += 1
        n_episode = seq["pre_seal"]
        st.enter_fix_episode(
            self.state,
            unit,
            [
                {
                    "id": "V1",
                    "severity": "P1",
                    "summary": "the configured full verification suite is "
                    "not green",
                    "validity": {
                        "permitted_baseline": (
                            "the configured verification suite passes"
                        ),
                        "actual_outcome": (
                            "the configured verification suite failed"
                        ),
                        "incremental_harm": (
                            "the candidate cannot demonstrate its required "
                            "verification gate"
                        ),
                        "exceeds_baseline": True,
                    },
                }
            ],
            "verification",
            None,
            "%s-verify-pre_seal-%d" % (st.unit_key(unit), n_episode),
            (st.U_PRE_REVIEW_VERIFY
             if verification_changed else stage),
        )
        return "verification failed; full-suite repair queued"

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
        (
            evidence_fingerprint,
            project_context,
            extensions,
            roots,
            amendments,
        ) = self._review_evidence_inputs(unit)
        bound_fingerprint = unit.get("review_evidence_fingerprint")
        if bound_fingerprint is None:
            unit["review_evidence_fingerprint"] = evidence_fingerprint
        elif bound_fingerprint != evidence_fingerprint:
            st.restart_reviews_after_candidate_change(
                self.state,
                unit,
                "candidate bytes or governing context changed between "
                "reviewer calls",
            )
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason=("review evidence changed; prior approvals "
                        "invalidated"),
            )
            return "review evidence changed; cycle restarted"
        self._record_amendments_seen(amendments)
        if project_context is not None:
            self._record_safeguards_seen(project_context["safeguards"])
        family = st.current_family(self.state, unit)
        if family is None:
            raise st.IllegalTransition("rounds status with no family left")
        # Two independent boundaries grant a fresh budget.  Resume amnesty
        # deliberately forgives rounds from before an operator retry; a new
        # review cycle forgives rounds over obsolete candidate bytes.  Count
        # only rounds after whichever boundary is newer.
        budget_start = max(
            int(unit.get("rounds_amnesty") or 0),
            int(unit.get("review_cycle_start") or 0),
        )
        done = len(
            [
                r
                for r in unit["rounds"][budget_start:]
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
            amendments=amendments,
            project_context=project_context,
            battery=interpreter.battery_questions(self.state, unit["kind"]),
            debt=self._debt(unit),
            gap_enabled=self._legacy_gap_enabled(),
            wave_docs=self._wave_doc_paths(unit),
            editable_design_paths=self._design_review_paths(unit),
            implementation_scope=self._implementation_scope(unit),
        )
        rethink_handoff = self._brainstorming_review_handoff(
            unit, contracts.KIND_REVIEW_ROUND
        )
        if rethink_handoff is not None:
            prompt = prompts.attach_rethink_review_handoff(
                prompt, rethink_handoff
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
                    "evidence_fingerprint": evidence_fingerprint,
                },
            )
            return "%s round INVALID (reviewer edited); restored and retrying" % family
        if rethink_handoff is not None:
            self._consume_brainstorming_review_handoff(
                unit, contracts.KIND_REVIEW_ROUND
            )
        if output.get("status") == "need_rethink":
            return self._start_rethink(
                unit,
                contracts.KIND_REVIEW_ROUND,
                family,
                review_model,
                review_effort,
                output,
                result,
                raw_path,
                "%s-%s-r%d" % (st.unit_key(unit), family, label_no),
            )
        self._check_worker_blocked(unit, output, contracts.KIND_REVIEW_ROUND)
        self._validate_contests(unit, output, contracts.KIND_REVIEW_ROUND)
        findings = output.get("findings", [])
        # Debt deferral: the profile/phase chooses the deferrable severity
        # scope (interpreter.defer_scope_for): the DOC phase rates P3
        # (legacy) or P2/P3 (reform); the IMPL phase rates P3 only (a code
        # P2 always fixes). P0/P1 always fix. Candidates are rated
        # independently: one serious finding must not drag cheap, accepted
        # debt into the fix queue with it.
        defer_scope = interpreter.defer_scope_for(self.state, unit["kind"])
        deferred = []
        fix_findings = list(findings)
        if (findings
                and self.config.get("p3_reclassify_debt")
                and defer_scope):
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
        round_meta = {
            "model": review_model,
            "effort": review_effort,
            "evidence_fingerprint": evidence_fingerprint,
        }
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
                    "validity": copy.deepcopy(f["validity"]),
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

    def _do_seal_attempt(self):
        """Close a recovered sealing state without launching seal reviewers."""
        unit = st.current_unit(self.state)
        if self._migrate_retired_seal_review_handoff(unit):
            return "retired seal discussion migrated to ordinary reviews"
        current_fingerprint = self._review_evidence_fingerprint(unit)
        cite = st.seal_predicate_reviews(
            unit,
            self.config["families_order"],
            current_fingerprint=current_fingerprint,
        )
        if cite is None:
            st.restart_reviews_after_candidate_change(
                self.state,
                unit,
                "persisted sealing state lacked current review evidence",
            )
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason="seal recovery restarted ordinary reviews",
            )
            return "seal recovery: review cycle restarted"
        return self._complete_seal_from_reviews(unit)

    def _wave_doc_paths(self, unit):
        """Artifact paths of the slice notes co-reopened with `unit` by an
        active re-documentation wave — None unless `unit` is the wave's
        anchor. Feeds the fixer, delta reviewer, and full reviewers the same
        whole-set declaration."""
        wave = self.state.get("redoc_wave")
        if not wave or wave.get("anchor") != st.unit_key(unit):
            return None
        by_key = {st.unit_key(u): u for u in self.state["units"]}
        paths = []
        for key in wave.get("docs") or []:
            u = by_key.get(key)
            if u is not None and u.get("artifact"):
                paths.append(u["artifact"])
        return paths

    def _retire_reviewed_redoc_wave(self, anchor):
        """Close a historical reviewed wave without synthetic approvals."""
        wave = self.state.get("redoc_wave") or {}
        if wave.get("anchor") != st.unit_key(anchor):
            return []
        by_key = {
            st.unit_key(candidate): candidate
            for candidate in self.state.get("units") or []
        }
        docs = [
            by_key[key] for key in wave.get("docs") or []
            if key in by_key
        ]
        for doc in docs:
            if doc.get("status") == st.U_REPAIRING:
                st.transition_unit(
                    self.state,
                    doc,
                    st.U_SEALED,
                    reason="historical redocumentation retired after review",
                )
            doc.pop("under_repair", None)
        if gitops.enabled(self.config):
            self.state["retired_redoc_docs_pending_gate"] = {
                "anchor": st.unit_key(anchor),
                "docs": [st.unit_key(doc) for doc in docs],
            }
        self.state["redoc_wave"] = None
        st.append_event(
            self.state,
            "redoc_wave_retired_after_review",
            unit=st.unit_key(anchor),
            reporter=wave.get("reporter"),
            docs=[st.unit_key(doc) for doc in docs],
            authority="historical_review_evidence",
        )
        return docs

    def _after_seal(self, unit):
        if unit["kind"] == st.UNIT_SLICE_IMPL:
            st.close_slice(self.state, unit)
        # A driver upgraded while a historical wave was still alive may reach
        # this boundary without restarting. Retire it using the reviews that
        # just completed; never synthesize approvals for the co-opened notes.
        is_anchor = bool(
            (self.state.get("redoc_wave") or {}).get("anchor")
            == st.unit_key(unit)
        )
        if is_anchor:
            self._retire_reviewed_redoc_wave(unit)
        self._gate_commit(unit)
        if unit.get("design_update"):
            unit.pop("design_update", None)
        if is_anchor:
            self._guard_unplanned_preserved_candidates()
        nxt = st.ensure_next_unit(self.state)
        if nxt is None and st.maybe_close_milestone(self.state):
            self._final_commit()

    def _gate_message(self, unit):
        if unit["kind"] == st.UNIT_SKELETON:
            return "Complete review of milestone skeleton"
        if unit["kind"] == st.UNIT_SLICE_DOC:
            return "Complete review of slice %02d note" % unit["slice_id"]
        return "Complete review of slice %s implementation" % st.slice_token(
            unit
        )

    def _consume_pending_closure(self):
        """Finish a reviewed unit's missing Git gate before opening another.

        The explicit marker is written before Git is touched.  This avoids
        guessing from old/synthetic sealed units that legitimately have no
        gate metadata, while ensuring a failed gate is retried before the
        next implementation part can be materialized.
        """
        if not gitops.enabled(self.config):
            return False
        pending = self.state.get("pending_gate_unit")
        if not pending:
            return False
        unit = self._unit_by_key(pending)
        if unit is None or unit.get("status") != st.U_SEALED:
            st.fail_run(
                self.state,
                "cannot recover the pending gate for %s" % pending,
                unit=unit,
                type_="gate_recovery",
            )
            self._save()
            raise StopStep("pending gate unit is unavailable")
        self._gate_commit(unit)
        unit.pop("design_update", None)
        return True

    def _gate_commit(self, unit):
        """The canon's commit-the-sealed-unit rule, executed by code: the
        generated ledgers are folded in and the unit's amended wip commit
        is finalized under the canonical gate message."""
        if not gitops.enabled(self.config):
            return
        self.state["pending_gate_unit"] = st.unit_key(unit)
        self._save()
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
        self.state.pop("pending_gate_unit", None)
        design_paths = set(self._design_review_paths(unit))
        if design_paths:
            for candidate in self.state.get("units") or []:
                if candidate.get("artifact") in design_paths:
                    candidate["gate_commit"] = sha
        correction = unit.get("design_correction") or {}
        if correction.get("phase") == "ratified":
            note = self._unit_by_key(correction.get("note_unit"))
            if note is not None:
                note["gate_commit"] = sha
        retired = self.state.get("retired_redoc_docs_pending_gate") or {}
        if retired.get("anchor") == st.unit_key(unit):
            for key in retired.get("docs") or []:
                note = self._unit_by_key(key)
                if note is not None:
                    note["gate_commit"] = sha
            self.state.pop("retired_redoc_docs_pending_gate", None)
        st.append_event(
            self.state,
            "gate_commit",
            unit=st.unit_key(unit),
            sha=sha,
            message=self._gate_message(unit),
        )

    def _final_commit(self):
        if not gitops.enabled(self.config):
            self.state.pop("pending_final_commit", None)
            return
        # Persist intent before touching Git. A crash or commit failure can
        # then resume this idempotent close instead of leaving a closed
        # milestone whose final ledger commit was never attempted again.
        self.state["pending_final_commit"] = True
        self._save()
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
        self.state.pop("pending_final_commit", None)


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
    elif code == 4:
        print("paused after seal (operator-ordered safe stop); "
              "start again to resume")
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
