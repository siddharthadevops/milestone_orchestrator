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
import json
import os
import subprocess
import sys
import threading

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX: flock degrades to the
    fcntl = None     # staleness check in step(); documented in the README

from . import contracts, prompts, runners, state as st

DEFAULT_CONFIG = {
    "families_order": ["codex", "claude"],
    "fix_family": None,  # default: first family in families_order
    "commands": {
        "codex": [
            "codex",
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--output-last-message",
            "{output_file}",
        ],
        "claude": [
            "claude",
            "-p",
            "--model",
            "opus",
            "--effort",
            "max",
            "--permission-mode",
            "bypassPermissions",
        ],
    },
    "timeouts": {"codex": 900, "claude": 1800},
    "verification": [],
    "verification_timeout": 600,
    "max_rounds_per_family": 12,
    "max_seal_attempts": 8,
    "max_verify_fix_attempts": 4,
    "seal_concurrent": False,
    # Extra directory names excluded from workspace snapshots, on top of
    # runners.SNAPSHOT_EXCLUDE_DIRS (runtime dirs + common Python tool
    # caches). Add tool caches your verification suite writes so read-only
    # seal halves that run it are not falsely invalidated.
    "snapshot_exclude_dirs": [],
}


def load_config(path=None):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            user = json.load(fh)
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
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
A_FIX_VERIFICATION = "fix_verification"
A_SEAL_ATTEMPT = "seal_attempt"
A_SEAL_FIX = "seal_fix"
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
    if status == st.U_VERIFY_FIX:
        return Action(A_FIX_VERIFICATION, unit=st.unit_key(unit))
    if status == st.U_ROUNDS:
        family = st.current_family(state, unit)
        return Action(A_REVIEW_ROUND, unit=st.unit_key(unit), family=family)
    if status == st.U_SEALING:
        return Action(A_SEAL_ATTEMPT, unit=st.unit_key(unit))
    if status == st.U_SEAL_FIX:
        return Action(A_SEAL_FIX, unit=st.unit_key(unit))
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
    concurrent seal worker threads; the caller decides how to record it."""


class Driver(object):
    def __init__(self, state_path, runner=None):
        self.state_path = state_path
        self.state = st.load(state_path)
        self.config = self.state["config"]
        self.workspace = self.state["workspace"]
        self.runner = runner or runners.SubprocessRunner(
            self.config["commands"], self.config.get("timeouts", {})
        )

    # -- helpers ----------------------------------------------------------

    def _save(self):
        st.save(self.state_path, self.state)

    def _snapshot(self):
        return runners.snapshot_workspace(
            self.workspace,
            extra_exclude=self.config.get("snapshot_exclude_dirs"),
        )

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

    def _raw_dir(self):
        path = os.path.join(self.workspace, ".orchestrator", "raw")
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

    def _save_protocol_raws(self, raw_name, exc):
        """Persist the raw texts of a protocol-violating call (original and
        repair retry) so the operator can inspect what the model actually
        said; state.failure keeps only the truncated error strings."""
        for i, text in enumerate(getattr(exc, "raw_texts", []) or [], 1):
            self._save_raw("%s-protoerr%d" % (raw_name, i), text)

    def _call(self, family, prompt, kind, raw_name):
        """Validated worker call; on protocol/runner failure, fail the run
        with the explanation recorded, then re-raise as StopStep."""
        try:
            output, result = runners.call_worker(
                self.runner, family, prompt, kind, self.workspace
            )
        except (runners.RunnerError, runners.WorkerProtocolError) as exc:
            self._save_protocol_raws(raw_name, exc)
            st.fail_run(self.state, "%s call failed: %s" % (kind, exc),
                        unit=st.current_unit(self.state))
            self._save()
            raise StopStep(str(exc))
        raw_path = self._save_raw(raw_name, result.text)
        return output, result, raw_path

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
            A_FIX_VERIFICATION: self._do_fix_verification,
            A_SEAL_ATTEMPT: self._do_seal_attempt,
            A_SEAL_FIX: self._do_seal_fix,
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
        family = self._fix_family()
        goal = self.state["goal"]
        if unit["kind"] == st.UNIT_SKELETON:
            kind = contracts.KIND_DRAFT_SKELETON
            prompt = prompts.build_draft_skeleton(family, self.workspace, goal)
        elif unit["kind"] == st.UNIT_SLICE_DOC:
            kind = contracts.KIND_DRAFT_SLICE_NOTE
            sl = self._slice_info(unit["slice_id"])
            prompt = prompts.build_draft_slice_note(
                family, self.workspace, goal, sl, self._skeleton_artifact()
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
                self.config["verification"],
            )
        output, _result, raw_path = self._call(
            family, prompt, kind, "%s-draft" % st.unit_key(unit)
        )
        self._check_worker_blocked(unit, output, kind)
        st.record_draft(self.state, unit, kind, output, raw_path)
        if unit["kind"] == st.UNIT_SKELETON:
            self.state["milestone"]["slices"] = output["slices"]
        st.transition_unit(self.state, unit, st.U_PRE_REVIEW_VERIFY, reason="drafted")
        return "drafted %s" % (unit["artifact"] or "(implementation)")

    def _slice_info(self, slice_id):
        for sl in self.state["milestone"]["slices"]:
            if sl["id"] == slice_id:
                return sl
        raise st.IllegalTransition("unknown slice id %r" % slice_id)

    def _skeleton_artifact(self):
        for u in self.state["units"]:
            if u["kind"] == st.UNIT_SKELETON:
                return u["artifact"] or "docs/skeleton.md"
        return "docs/skeleton.md"

    def _slice_note_artifact(self, slice_id):
        for u in self.state["units"]:
            if u["kind"] == st.UNIT_SLICE_DOC and u["slice_id"] == slice_id:
                return u["artifact"] or ("docs/slice-%02d.md" % slice_id)
        return "docs/slice-%02d.md" % slice_id

    def _do_verify(self):
        unit = st.current_unit(self.state)
        stage = unit["status"]
        stage_key = (
            "pre_review" if stage == st.U_PRE_REVIEW_VERIFY else "pre_seal"
        )
        commands = self.config["verification"]
        ok, output = run_verification(
            commands, self.workspace, self.config.get("verification_timeout", 600)
        )
        st.append_event(
            self.state,
            "verification",
            unit=st.unit_key(unit),
            stage=stage,
            ok=ok,
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
        unit["return_to"] = stage_key
        unit["last_verification_output"] = (output or "")[-4000:]
        st.transition_unit(self.state, unit, st.U_VERIFY_FIX, reason="verification failed")
        return "verification failed; scheduling fix call"

    def _do_fix_verification(self):
        unit = st.current_unit(self.state)
        family = self._fix_family()
        prompt = prompts.build_fix_verification(
            family,
            self.workspace,
            self.state["goal"],
            self._unit_desc(unit),
            unit.get("last_verification_output", ""),
            self._opposite(family),
            self._opposite_cmd(family),
        )
        # Monotonic per-unit numbering (stage counters reset on pass, so
        # they would collide across stages).
        n_fix = 1 + len(
            [
                r
                for r in unit["rounds"]
                if r["kind"] == contracts.KIND_FIX_VERIFICATION
            ]
        )
        output, result, raw_path = self._call(
            family,
            prompt,
            contracts.KIND_FIX_VERIFICATION,
            "%s-vfix%d" % (st.unit_key(unit), n_fix),
        )
        self._check_worker_blocked(unit, output, contracts.KIND_FIX_VERIFICATION)
        st.record_round(
            self.state,
            unit,
            family,
            contracts.KIND_FIX_VERIFICATION,
            output,
            raw_path=raw_path,
            duration=result.duration_s,
        )
        self._maybe_update_slices(unit, output)
        target = (
            st.U_PRE_REVIEW_VERIFY
            if unit.get("return_to") == "pre_review"
            else st.U_PRE_SEAL_VERIFY
        )
        st.transition_unit(self.state, unit, target, reason="verification fix applied")
        return "verification fix call done; re-verifying"

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
            self._opposite(family),
            self._opposite_cmd(family),
        )
        output, result, raw_path = self._call(
            family,
            prompt,
            contracts.KIND_REVIEW_ROUND,
            "%s-%s-r%d" % (st.unit_key(unit), family, done + 1),
        )
        self._check_worker_blocked(unit, output, contracts.KIND_REVIEW_ROUND)
        st.record_round(
            self.state,
            unit,
            family,
            contracts.KIND_REVIEW_ROUND,
            output,
            raw_path=raw_path,
            duration=result.duration_s,
        )
        self._maybe_update_slices(unit, output)
        st.advance_family_if_clean(self.state, unit, output)
        n = len(output.get("findings", []))
        return "%s round: %d finding(s)%s" % (
            family,
            n,
            "" if n else " -> clean",
        )

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
        families = self.config["families_order"]
        goal = self.state["goal"]
        desc = self._unit_desc(unit)
        artifact = self._artifact(unit)
        halves = {}
        invalidated = None

        def run_half_pure(family):
            """One seal half, mutating NO shared state (thread-safe): any
            failure raises _SealHalfFailure; raw outputs go to per-family
            files only."""
            prompt = prompts.build_seal_half(
                family, self.workspace, goal, desc, artifact
            )
            raw_name = "%s-seal-a%d-%s" % (st.unit_key(unit), attempt_no, family)
            try:
                output, result = runners.call_worker(
                    self.runner,
                    family,
                    prompt,
                    contracts.KIND_SEAL_HALF,
                    self.workspace,
                )
            except (runners.RunnerError, runners.WorkerProtocolError) as exc:
                self._save_protocol_raws(raw_name, exc)
                raise _SealHalfFailure(
                    "%s call failed: %s" % (contracts.KIND_SEAL_HALF, exc)
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

        def fail_attempt(reason):
            st.fail_run(self.state, reason, unit=unit)
            self._save()
            raise StopStep(reason)

        if self.config.get("seal_concurrent"):
            before = self._snapshot()
            errors = {}

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
                except Exception as exc:  # a dead thread must fail the run
                    errors[fam] = "seal half crashed: %r" % (exc,)

            threads = [
                threading.Thread(target=worker, args=(fam,)) for fam in families
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            if errors:
                fail_attempt(
                    "concurrent seal attempt failed: "
                    + "; ".join(
                        "%s: %s" % (fam, errors[fam]) for fam in sorted(errors)
                    )
                )
            after = self._snapshot()
            if after != before:
                for fam in halves:
                    halves[fam]["workspace_modified"] = True
                invalidated = (
                    "workspace changed during concurrent seal attempt; "
                    "cannot attribute; attempt invalid"
                )
        else:
            snap = self._snapshot()
            for fam in families:
                try:
                    halves[fam] = run_half_pure(fam)
                except _SealHalfFailure as exc:
                    fail_attempt(str(exc))
                new_snap = self._snapshot()
                if new_snap != snap:
                    halves[fam]["workspace_modified"] = True
                    invalidated = (
                        "seal half %s modified the workspace; its output is "
                        "invalid and the attempt does not count as evidence"
                        % fam
                    )
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
        passed = clean and invalidated is None
        st.record_seal_attempt(self.state, unit, halves, passed, invalidated)
        if passed:
            st.transition_unit(self.state, unit, st.U_SEALED, reason="double seal clean")
            self._after_seal(unit)
            return "seal attempt %d PASSED; %s sealed" % (attempt_no, st.unit_key(unit))
        if invalidated is not None:
            # The tampering half's modifications are still on disk: the
            # delta must pass verification again before the next attempt
            # may double-seal it (same gate as the seal-findings path).
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_SEAL_VERIFY,
                reason="seal attempt invalidated; re-verify before retry",
            )
            return "seal attempt %d INVALID: %s" % (attempt_no, invalidated)
        st.transition_unit(self.state, unit, st.U_SEAL_FIX, reason="seal findings")
        total = sum(len(h["result"].get("findings", [])) for h in halves.values())
        return "seal attempt %d: %d finding(s); scheduling seal fix" % (
            attempt_no,
            total,
        )

    def _after_seal(self, unit):
        if unit["kind"] == st.UNIT_SLICE_IMPL:
            st.close_slice(self.state, unit)
        nxt = st.ensure_next_unit(self.state)
        if nxt is None:
            st.maybe_close_milestone(self.state)

    def _do_seal_fix(self):
        unit = st.current_unit(self.state)
        family = self._fix_family()
        last_seal = unit["seals"][-1]
        seal_findings = {
            fam: (h["result"].get("findings", []) if h.get("result") else [])
            for fam, h in last_seal["halves"].items()
        }
        prompt = prompts.build_seal_fix(
            family,
            self.workspace,
            self.state["goal"],
            self._unit_desc(unit),
            self._artifact(unit),
            seal_findings,
            self._opposite(family),
            self._opposite_cmd(family),
        )
        output, result, raw_path = self._call(
            family,
            prompt,
            contracts.KIND_SEAL_FIX,
            "%s-sealfix-a%d" % (st.unit_key(unit), len(unit["seals"])),
        )
        self._check_worker_blocked(unit, output, contracts.KIND_SEAL_FIX)
        st.record_round(
            self.state,
            unit,
            family,
            contracts.KIND_SEAL_FIX,
            output,
            raw_path=raw_path,
            duration=result.duration_s,
        )
        self._maybe_update_slices(unit, output)
        st.transition_unit(
            self.state, unit, st.U_PRE_SEAL_VERIFY, reason="seal findings triaged"
        )
        return "seal fix call done; re-verifying before next attempt"


class StopStep(RuntimeError):
    """Raised by executors after fail_run() has recorded the explanation."""


def run_verification(commands, workspace, timeout):
    """Run every verification command; returns (all_ok, combined_output)."""
    if not commands:
        return True, "(no verification configured)"
    chunks = []
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            chunks.append("$ %s\nTIMEOUT after %ss" % (cmd, timeout))
            return False, "\n".join(chunks)
        chunks.append(
            "$ %s\nexit=%d\n%s%s" % (cmd, proc.returncode, proc.stdout, proc.stderr)
        )
        if proc.returncode != 0:
            return False, "\n".join(chunks)
    return True, "\n".join(chunks)


# ---------------------------------------------------------------------------
# CLI


def default_state_path(workspace):
    return os.path.join(workspace, ".orchestrator", "state.json")


def cmd_init(args):
    workspace = os.path.abspath(args.workspace)
    os.makedirs(workspace, exist_ok=True)
    config = load_config(args.config)
    state = st.new_state(args.goal, workspace, config)
    st.append_event(state, "initialized", goal=args.goal)
    path = args.state or default_state_path(workspace)
    if os.path.exists(path):
        print("refusing to overwrite existing state at %s" % path, file=sys.stderr)
        return 2
    st.save(path, state)
    print("initialized: %s" % path)
    return 0


def _state_path(args):
    if args.state:
        return args.state
    if args.workspace:
        return default_state_path(os.path.abspath(args.workspace))
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


def cmd_next(args):
    state = st.load(_state_path(args))
    print(repr(decide(state)))
    return 0


def cmd_step(args):
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
    p_init.add_argument("--workspace", required=True)
    p_init.add_argument("--config", default=None)
    p_init.add_argument("--state", default=None)
    p_init.set_defaults(func=cmd_init)

    for name, func in (
        ("status", cmd_status),
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
