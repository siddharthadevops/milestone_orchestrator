"""Driver wiring for controlled implementation-size cuts.

The Git line counter and provider transports have their own unit tests.  This
module exercises the seam between them: a live control result must become one
immutable implementation part, and no continuation may open before that
part's ordinary gate has completed.
"""

import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from orchestrator import brainstorming_milestone
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import gitops
from orchestrator import prompts
from orchestrator import runners
from orchestrator import state as st
from orchestrator.tests.test_driver_mock import (
    git_init_workspace,
    make_config,
    ok,
)


class _PromptReached(RuntimeError):
    pass


class LiveControlRunner(runners.MockRunner):
    """Small deterministic transport that exercises ActiveCallControl.

    ``normal`` finishes below the soft boundary, ``steer`` waits until the
    observer delivers its soft request, and ``hard`` keeps growing until the
    observer interrupts it.  A hard run's second call is the stabilizer.
    """

    def __init__(self, mode, response, recovery_response=None,
                 recovery_lines=4):
        super().__init__([])
        self.mode = mode
        self.response = response
        self.recovery_response = recovery_response
        self.recovery_lines = recovery_lines
        self.steer_seen = threading.Event()
        self.interrupt_seen = threading.Event()

    @staticmethod
    def _wait_for(predicate, message):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        raise AssertionError(message)

    @staticmethod
    def _write_lines(workspace, count):
        with open(os.path.join(workspace, "implementation.py"), "w",
                  encoding="utf-8") as handle:
            handle.writelines("value_%d = %d\n" % (i, i) for i in range(count))

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None, active_control=None):
        kind = runners.prompt_kind(prompt)
        self.calls.append((family, kind, prompt))
        self.call_meta.append({
            "family": family,
            "kind": kind,
            "model": model,
            "effort": effort,
        })

        if active_control is None:
            if self.recovery_response is None:
                raise AssertionError("unexpected uncontrolled worker call")
            return runners.RunnerResult(
                json.dumps(self.recovery_response), 0, 0.02
            )

        active_control._bind(
            lambda _text: (self.steer_seen.set() or True),
            lambda _reason: (self.interrupt_seen.set() or True),
        )
        try:
            if "FORCED CONTROLLED-CUTOFF RECOVERY" in prompt:
                if self.recovery_response is None:
                    raise AssertionError("unexpected cutoff recovery")
                self._write_lines(workspace, self.recovery_lines)
                return runners.RunnerResult(
                    json.dumps(self.recovery_response), 0, 0.02
                )
            if self.mode == "normal":
                self._write_lines(workspace, 2)
            elif self.mode == "preserve":
                self._wait_for(
                    lambda: bool(active_control.steers),
                    "preserved oversized work did not receive its soft steer",
                )
                self._wait_for(
                    lambda: active_control.interrupted,
                    "preserved oversized work was not interrupted",
                )
                result = runners.ControlledInterruptionResult(
                    "partial worker output",
                    -9,
                    0.03,
                    active_control.interrupt_reason,
                )
                result.steers = active_control.steers
                return result
            else:
                self._write_lines(
                    workspace, 8 if self.mode == "jump" else 3
                )
                self._wait_for(
                    lambda: bool(active_control.steers),
                    "soft size steer was not delivered",
                )
                if self.mode == "hard":
                    self._write_lines(workspace, 8)
                    self._wait_for(
                        lambda: active_control.interrupted,
                        "hard size interruption was not delivered",
                    )
                    result = runners.ControlledInterruptionResult(
                        "partial worker output",
                        -9,
                        0.03,
                        active_control.interrupt_reason,
                    )
                    result.steers = active_control.steers
                    return result
            result = runners.RunnerResult(json.dumps(self.response), 0, 0.02)
            result.steers = active_control.steers
            return result
        finally:
            active_control._close()


class ContinuationControlProbeRunner(runners.MockRunner):
    """Accept a Brainstorming continuation only when live control survives."""

    def __init__(self, response, require_steer=False):
        super().__init__([])
        self.response = response
        self.require_steer = require_steer
        self.controlled_calls = 0

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None, active_control=None):
        if active_control is None:
            raise AssertionError(
                "implementation continuation lost its size control"
            )
        self.controlled_calls += 1
        active_control._bind(lambda _text: True, lambda _reason: True)
        if self.require_steer:
            LiveControlRunner._wait_for(
                lambda: bool(active_control.steers),
                "Brainstorming continuation did not receive its soft steer",
            )
        active_control._close()
        self.calls.append((family, runners.prompt_kind(prompt), prompt))
        return runners.RunnerResult(json.dumps(self.response), 0, 0.02)


class InfraRetryControlRunner(object):
    def __init__(self):
        self.controls = []

    def call(self, _family, _prompt, _workspace, model=None, effort=None,
             active_control=None):
        del model, effort
        self.controls.append((active_control, active_control.closed))
        active_control._close()
        if len(self.controls) == 1:
            raise runners.RunnerError("temporary network failure")
        return runners.RunnerResult(
            json.dumps(ok(contracts.KIND_IMPLEMENT, files_changed=[])),
            0,
            0.02,
        )


class StagedCrashRunner(object):
    """Leave an oversized staged candidate, then fail before any draft."""

    def __init__(self):
        self.calls = 0

    def call(self, _family, _prompt, workspace, model=None, effort=None,
             active_control=None):
        del model, effort
        self.calls += 1
        active_control._bind(lambda _text: True, lambda _reason: True)
        try:
            LiveControlRunner._write_lines(workspace, 8)
            gitops._run(workspace, "add", "implementation.py")
        finally:
            active_control._close()
        raise runners.RunnerError("provider failed after staging its work")


class DriverImplementationSizeTest(unittest.TestCase):
    def _ready_driver(self, workspace, runner, size_control=None,
                      git_enabled=True):
        config = make_config(
            git={"enabled": git_enabled},
            implementation_size_control=(
                size_control
                or {"soft_lines": 1000, "hard_lines": 1500,
                    "poll_interval_s": 0.005}
            ),
        )
        if git_enabled:
            git_init_workspace(workspace)
        os.makedirs(os.path.join(workspace, "docs"), exist_ok=True)
        with open(os.path.join(workspace, "docs", "skeleton.md"), "w",
                  encoding="utf-8") as handle:
            handle.write("# Skeleton\n")
        with open(os.path.join(workspace, "docs", "slice-01.md"), "w",
                  encoding="utf-8") as handle:
            handle.write("# Slice 01\n")

        state = st.new_state("Build the feature", workspace, config)
        state["milestone"]["slices"] = [{"id": 1, "title": "Feature"}]
        skeleton = st.current_unit(state)
        skeleton["artifact"] = "docs/skeleton.md"
        skeleton["status"] = st.U_SEALED
        note = st.ensure_next_unit(state)
        note["artifact"] = "docs/slice-01.md"
        note["status"] = st.U_SEALED
        implementation = st.ensure_next_unit(state)
        path = drv.default_state_path(workspace)
        st.save(path, state)

        driver = drv.Driver(path, runner=runner)
        implementation = st.current_unit(driver.state)
        if git_enabled:
            implementation["baseline_verification"] = {
                "commands": driver._verification_commands(implementation),
                "candidate_fingerprint": (
                    driver._verification_candidate_fingerprint()
                ),
            }
            driver._save()
        return path, driver, implementation

    @staticmethod
    def _cut_response(cut="coherent core", remaining="remaining wiring"):
        return ok(
            contracts.KIND_IMPLEMENT,
            files_changed=["implementation.py"],
            implementation_cut={
                "cut_scope": cut,
                "remaining_scope": remaining,
            },
        )

    @staticmethod
    def _brainstorming_handoff():
        return {
            "session_id": "brainstorming-size-control",
            "accepted_target_revision": 1,
            "result": {"outcome": "success"},
            "retained_target": {
                "exists": True,
                "encoding": "utf-8",
                "content": "Continue the bounded implementation.",
            },
        }

    @staticmethod
    def _attach_brainstorming_wait(unit, base_tree, handoff):
        unit["brainstorming_wait"] = {
            "session_id": handoff["session_id"],
            "signal": {
                "status": "need_rethink",
                "kind": contracts.KIND_IMPLEMENT,
                "question": "Which bounded implementation should proceed?",
                "finding": {
                    "id": "F1",
                    "summary": "the implementation choice needs agreement",
                },
                "target_path": "docs/slice-01.md",
                "max_rounds": 2,
                "result_mode": contracts.RETHINK_RESULT_PROPOSAL,
            },
            "references": ["docs/slice-01.md"],
            "origin": {
                "unit": st.unit_key(unit),
                "kind": contracts.KIND_IMPLEMENT,
                "family": "codex",
                "model": "gpt-5.6-sol",
                "effort": "max",
                "raw_path": "raw/origin.txt",
                "raw_name": "slice_impl-01-draft",
                "provider_session_ref": "codex-thread-7",
                "duration_s": 0.02,
                "pre_snapshot": {
                    "tree": base_tree,
                    "implementation_cut_authorized": False,
                },
            },
        }

    def test_normal_implementation_finishes_without_creating_a_part(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-normal-") as ws:
            runner = LiveControlRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
            )
            path, driver, _unit = self._ready_driver(ws, runner)

            action, note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertIn("drafted", note)
            unit = st.current_unit(st.load(path))
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertNotIn("implementation_cut", unit)
            self.assertNotIn("implementation_attempt_snapshot", unit)
            self.assertFalse(any(
                event["type"] in {
                    "implementation_size_steer",
                    "implementation_size_interrupted",
                    "implementation_size_overflow",
                    "implementation_size_recovery_interrupted",
                }
                for event in driver.state["events"]
            ))

    def test_failed_wip_commit_is_retried_before_reviews_open(self):
        with tempfile.TemporaryDirectory(prefix="orch-wip-retry-") as ws:
            runner = LiveControlRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
            )
            path, driver, _unit = self._ready_driver(ws, runner)

            with mock.patch.object(
                gitops,
                "commit_wip",
                side_effect=gitops.GitError("simulated WIP commit failure"),
            ):
                action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            failed = st.load(path)
            failed_unit = st.current_unit(failed)
            self.assertIsNotNone(failed["failure"])
            self.assertIsNotNone(failed_unit["draft"])
            self.assertIsNotNone(failed_unit.get("pending_wip"))
            self.assertFalse(any(
                event.get("type") == "wip_commit"
                for event in failed["events"]
            ))

            st.resume_run(failed)
            st.save(path, failed)
            real_commit = gitops.commit_wip
            recovered = drv.Driver(path, runner=runner)
            with mock.patch.object(
                gitops, "commit_wip", wraps=real_commit
            ) as retried:
                resumed_action, _resumed_note = recovered.step()

            self.assertEqual(resumed_action.type, drv.A_DRAFT)
            retried.assert_called_once_with(ws, "wip: slice_impl-01")
            state = st.load(path)
            unit = st.current_unit(state)
            self.assertIsNone(state["failure"])
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertNotIn("pending_wip", unit)
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(len([
                event for event in state["events"]
                if event.get("type") == "wip_commit"
                and event.get("unit") == "slice_impl-01"
            ]), 1)
            subjects = gitops._run(
                ws, "log", "--format=%s"
            ).stdout.splitlines()
            self.assertEqual(subjects.count("wip: slice_impl-01"), 1)

    def test_failed_wip_intent_preparation_is_retried_before_review(self):
        with tempfile.TemporaryDirectory(prefix="orch-wip-prepare-") as ws:
            runner = LiveControlRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
            )
            path, driver, _unit = self._ready_driver(ws, runner)

            with mock.patch.object(
                gitops,
                "snapshot_worktree_tree",
                side_effect=gitops.GitError("temporary tree failure"),
            ):
                action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            failed = st.load(path)
            failed_unit = st.current_unit(failed)
            self.assertIsNotNone(failed_unit["draft"])
            self.assertNotIn("pending_wip", failed_unit)
            self.assertIn("implementation_attempt_snapshot", failed_unit)

            st.resume_run(failed)
            st.save(path, failed)
            recovered = drv.Driver(path, runner=runner)
            resumed_action, _resumed_note = recovered.step()

            self.assertEqual(resumed_action.type, drv.A_DRAFT)
            state = st.load(path)
            unit = st.current_unit(state)
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertNotIn("pending_wip", unit)
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(len([
                event for event in state["events"]
                if event.get("type") == "wip_commit"
                and event.get("unit") == "slice_impl-01"
            ]), 1)

    def test_resume_adopts_landed_pending_wip_without_second_commit(self):
        with tempfile.TemporaryDirectory(prefix="orch-wip-adopt-") as ws:
            runner = LiveControlRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
            )
            path, driver, _unit = self._ready_driver(ws, runner)
            real_commit = gitops.commit_wip
            landed = []

            def commit_then_crash(workspace, message):
                landed.append(real_commit(workspace, message))
                raise RuntimeError("simulated crash after WIP commit")

            with mock.patch.object(
                gitops, "commit_wip", side_effect=commit_then_crash
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "simulated crash after WIP commit"
                ):
                    driver.step()

            persisted = st.load(path)
            persisted_unit = st.current_unit(persisted)
            self.assertIsNone(persisted["failure"])
            self.assertIsNotNone(persisted_unit["draft"])
            self.assertIsNotNone(persisted_unit.get("pending_wip"))
            self.assertFalse(any(
                event.get("type") == "wip_commit"
                for event in persisted["events"]
            ))
            self.assertEqual(
                gitops.head_sha(ws), landed[0]
            )

            recovered = drv.Driver(path, runner=runner)
            with mock.patch.object(gitops, "commit_wip") as duplicate_commit:
                resumed_action, _resumed_note = recovered.step()

            self.assertEqual(resumed_action.type, drv.A_DRAFT)
            duplicate_commit.assert_not_called()
            state = st.load(path)
            unit = st.current_unit(state)
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertNotIn("pending_wip", unit)
            self.assertEqual(len(runner.calls), 1)
            wips = [
                event for event in state["events"]
                if event.get("type") == "wip_commit"
                and event.get("unit") == "slice_impl-01"
            ]
            self.assertEqual(len(wips), 1)
            self.assertEqual(wips[0]["sha"], landed[0])
            subjects = gitops._run(
                ws, "log", "--format=%s"
            ).stdout.splitlines()
            self.assertEqual(subjects.count("wip: slice_impl-01"), 1)

    def test_infrastructure_retry_renews_the_live_controller(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-retry-") as ws:
            _path, driver, _unit = self._ready_driver(
                ws, runners.MockRunner([]), git_enabled=False
            )
            runner = InfraRetryControlRunner()
            driver.runner = runner
            driver.config["infra_retry_backoff_s"] = [0]

            with mock.patch.object(
                driver,
                "_classify_failure",
                return_value=("network", None, None),
            ), mock.patch.object(time, "sleep"):
                output, _result, _raw = driver._call(
                    "codex",
                    "KIND: implement\n",
                    contracts.KIND_IMPLEMENT,
                    "controlled-infra-retry",
                    active_control=runners.ActiveCallControl(),
                )

            self.assertEqual(output["status"], "ok")
            self.assertEqual([closed for _control, closed in runner.controls],
                             [False, False])
            self.assertIsNot(runner.controls[0][0], runner.controls[1][0])

    def test_missing_fixed_git_baseline_stops_before_worker_call(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-no-base-") as ws:
            runner = runners.MockRunner([])
            _path, driver, _unit = self._ready_driver(ws, runner)

            with self.assertRaisesRegex(
                drv.StopStep, "size control unavailable"
            ):
                driver._call_implementation(
                    "codex",
                    "KIND: implement\n",
                    "missing-size-baseline",
                    "gpt-5.6-sol",
                    "max",
                    [],
                    [],
                    None,
                    True,
                    None,
                )

            self.assertEqual(runner.calls, [])
            self.assertEqual(driver.state["failure"]["type"], "orchestrator")

    def test_resume_keeps_pre_crash_tree_for_staged_oversized_work(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-staged-resume-") as ws:
            crashed_runner = StagedCrashRunner()
            path, driver, _unit = self._ready_driver(
                ws,
                crashed_runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.05},
            )
            original_tree = gitops.snapshot_index_tree(ws)

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            failed = st.load(path)
            self.assertIsNotNone(failed["failure"])
            self.assertIsNone(st.current_unit(failed)["draft"])
            self.assertEqual(
                st.current_unit(failed)["implementation_attempt_snapshot"][
                    "tree"
                ],
                original_tree,
            )
            contaminated_tree = gitops.snapshot_index_tree(ws)
            self.assertNotEqual(contaminated_tree, original_tree)
            self.assertEqual(
                gitops.reviewable_line_count(ws, original_tree), 8
            )

            st.resume_run(failed)
            st.save(path, failed)
            resumed_runner = LiveControlRunner(
                "preserve",
                ok(contracts.KIND_IMPLEMENT, files_changed=[]),
                recovery_response=self._cut_response(
                    "stabilized staged work", "remaining wiring"
                ),
                recovery_lines=4,
            )
            resumed = drv.Driver(path, runner=resumed_runner)
            for _ in range(6):
                current = st.current_unit(resumed.state)
                if resumed.state.get("failure") or current.get("draft"):
                    break
                resumed.step()

            recovered = st.load(path)
            self.assertIsNone(recovered["failure"])
            implementation = st.current_unit(recovered)
            self.assertEqual(
                implementation["status"], st.U_PRE_REVIEW_VERIFY
            )
            self.assertEqual(len(resumed_runner.calls), 2)
            self.assertIn(
                "FORCED CONTROLLED-CUTOFF RECOVERY",
                resumed_runner.calls[1][2],
            )
            self.assertEqual(
                implementation["implementation_cut"]["cut_scope"],
                "stabilized staged work",
            )
            interrupted = [
                event for event in recovered["events"]
                if event.get("type") == "implementation_size_interrupted"
            ]
            self.assertTrue(interrupted)
            self.assertGreaterEqual(interrupted[-1]["lines"], 8)

    def test_delivered_soft_steer_authorizes_part_a_cut(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-steer-") as ws:
            runner = LiveControlRunner("steer", self._cut_response())
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 50,
                 "poll_interval_s": 0.005},
            )

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            unit = st.current_unit(st.load(path))
            self.assertEqual(st.display_unit_key(unit), "slice_impl-01-a")
            self.assertEqual(unit["implementation_cut"]["part"], "a")
            self.assertGreaterEqual(unit["implementation_cut"]["steer_lines"], 2)
            self.assertTrue(any(
                event["type"] == "implementation_size_steer"
                and event["delivered"] is True
                for event in driver.state["events"]
            ))
            subject = gitops._run(ws, "log", "-1", "--format=%s").stdout.strip()
            self.assertEqual(subject, "wip: slice_impl-01-a")

    def test_spontaneous_cut_without_a_live_steer_fails_the_run(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-reject-") as ws:
            runner = LiveControlRunner("normal", self._cut_response())
            path, driver, _unit = self._ready_driver(ws, runner)

            action, note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertIn("unauthorized implementation cut", note)
            state = st.load(path)
            self.assertEqual(state["milestone"]["status"], st.M_FAILED)
            self.assertEqual(state["failure"]["type"], "worker_protocol")
            self.assertIn("without a delivered live size steer",
                          state["failure"]["reason"])

    def test_rethink_resume_cannot_invent_a_cut_without_origin_authority(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-rethink-no-") as ws:
            _path, driver, _unit = self._ready_driver(
                ws, runners.MockRunner([]), git_enabled=False
            )
            output = self._cut_response()
            result = runners.RunnerResult(json.dumps(output), 0, 0.02)
            result.origin_family = "codex"
            result.origin_model = "gpt-5.6-sol"
            result.origin_effort = "max"
            result.origin_pre_snapshot = {
                "implementation_cut_authorized": False,
            }

            with mock.patch.object(
                driver, "_baseline_verification_current", return_value=True
            ), mock.patch.object(
                driver,
                "_take_brainstorming_resume",
                return_value=(output, result, "raw/resumed.txt"),
            ):
                with self.assertRaisesRegex(
                    drv.StopStep, "unauthorized implementation cut"
                ):
                    driver._do_draft()

            self.assertEqual(driver.state["milestone"]["status"], st.M_FAILED)
            self.assertEqual(
                driver.state["failure"]["type"], "worker_protocol"
            )

    def test_rethink_resume_preserves_origin_cut_authority(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-rethink-yes-") as ws:
            _path, driver, unit = self._ready_driver(
                ws, runners.MockRunner([]), git_enabled=False
            )
            output = self._cut_response()
            result = runners.RunnerResult(json.dumps(output), 0, 0.02)
            result.origin_family = "codex"
            result.origin_model = "gpt-5.6-sol"
            result.origin_effort = "max"
            result.origin_pre_snapshot = {
                "implementation_cut_authorized": True,
            }

            with mock.patch.object(
                driver, "_baseline_verification_current", return_value=True
            ), mock.patch.object(
                driver,
                "_take_brainstorming_resume",
                return_value=(output, result, "raw/resumed.txt"),
            ), mock.patch.object(
                driver, "_finish_draft", return_value="drafted"
            ):
                self.assertEqual(driver._do_draft(), "drafted")

            self.assertEqual(st.display_unit_key(unit), "slice_impl-01-a")
            self.assertEqual(
                unit["implementation_cut"]["cut_scope"], "coherent core"
            )
            self.assertEqual(
                unit["implementation_cut"]["remaining_scope"],
                "remaining wiring",
            )
            self.assertIsNotNone(unit["draft"])

    def test_hard_interruption_runs_stabilizer_and_records_metrics(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-hard-") as ws:
            runner = LiveControlRunner(
                "hard",
                self._cut_response(),
                recovery_response=self._cut_response(
                    "stabilized core", "remaining wiring"
                ),
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.005},
            )

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertEqual(len(runner.calls), 2)
            self.assertIn("FORCED CONTROLLED-CUTOFF RECOVERY",
                          runner.calls[1][2])
            state = st.load(path)
            unit = st.current_unit(state)
            cut = unit["implementation_cut"]
            self.assertGreaterEqual(cut["steer_lines"], 2)
            self.assertGreaterEqual(cut["interrupt_lines"], 6)
            events = {event["type"]: event for event in state["events"]}
            self.assertTrue(events["implementation_size_steer"]["delivered"])
            self.assertGreaterEqual(
                events["implementation_size_interrupted"]["lines"], 6
            )
            self.assertIn("controlled size cutoff",
                          events["implementation_size_interrupted"]["reason"])

    def test_hard_jump_before_next_poll_forces_stabilization(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-jump-") as ws:
            runner = LiveControlRunner(
                "jump",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
                recovery_response=self._cut_response(
                    "stabilized jump", "remaining wiring"
                ),
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.05},
            )

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertEqual(
                len(runner.calls), 2,
                "an over-hard result must be stabilized even when the "
                "worker exits before the monitor's next poll",
            )
            self.assertIn("FORCED CONTROLLED-CUTOFF RECOVERY",
                          runner.calls[1][2])
            unit = st.current_unit(st.load(path))
            self.assertEqual(st.display_unit_key(unit), "slice_impl-01-a")
            self.assertEqual(
                unit["implementation_cut"]["cut_scope"], "stabilized jump"
            )

    def test_oversized_stabilizer_fails_before_review_opens(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-bad-recovery-") as ws:
            runner = LiveControlRunner(
                "jump",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
                recovery_response=self._cut_response(
                    "still oversized", "remaining wiring"
                ),
                recovery_lines=8,
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.05},
            )

            action, note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertIn("cutoff recovery failed", note)
            state = st.load(path)
            unit = st.current_unit(state)
            self.assertEqual(state["milestone"]["status"], st.M_FAILED)
            self.assertEqual(state["failure"]["type"], "worker_protocol")
            self.assertEqual(unit["status"], st.U_FAILED)
            self.assertIsNone(unit["draft"])
            self.assertFalse(any(
                event["type"] == "wip_commit" for event in state["events"]
            ))
            self.assertEqual(len(runner.calls), 2)

    def test_brainstorming_implementation_continuation_keeps_size_control(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-brainstorm-") as ws:
            runner = ContinuationControlProbeRunner(
                ok(contracts.KIND_IMPLEMENT, files_changed=[])
            )
            _path, driver, unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.005},
            )
            base_tree = gitops.snapshot_index_tree(ws)
            handoff = self._brainstorming_handoff()
            self._attach_brainstorming_wait(unit, base_tree, handoff)
            driver._save()

            with mock.patch.object(
                brainstorming_milestone,
                "terminal_handoff",
                return_value=handoff,
            ), mock.patch.object(
                brainstorming_milestone,
                "prompt_handoff",
                return_value=handoff,
            ):
                note = driver._do_brainstorming_wait()

            self.assertEqual(runner.controlled_calls, 1)
            self.assertIn("origin conversation continued", note)
            self.assertIn("brainstorming_resume", unit)

    def test_brainstorming_soft_steer_cut_keeps_authority_and_metrics_on_resume(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="orch-size-brain-cut-") as ws:
            runner = ContinuationControlProbeRunner(
                self._cut_response("agreed cut", "remaining wiring"),
                require_steer=True,
            )
            path, driver, unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.005},
            )
            base_tree = gitops.snapshot_index_tree(ws)
            handoff = self._brainstorming_handoff()
            self._attach_brainstorming_wait(unit, base_tree, handoff)

            with mock.patch.object(
                brainstorming_milestone,
                "terminal_handoff",
                return_value=handoff,
            ), mock.patch.object(
                brainstorming_milestone,
                "prompt_handoff",
                return_value=handoff,
            ), mock.patch.object(
                gitops, "reviewable_line_count", return_value=3
            ):
                wait_action, _wait_note = driver.step()

            self.assertEqual(wait_action.type, drv.A_BRAINSTORM_WAIT)

            resume_pre = unit["brainstorming_resume"]["pre_snapshot"]
            self.assertTrue(resume_pre["implementation_cut_authorized"])
            self.assertFalse(resume_pre["implementation_stabilized"])
            self.assertTrue(
                resume_pre["implementation_size"]["steer_delivered"]
            )
            self.assertEqual(
                resume_pre["implementation_size"]["steer_lines"], 3
            )

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            state = st.load(path)
            unit = st.current_unit(state)
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertEqual(st.display_unit_key(unit), "slice_impl-01-a")
            self.assertEqual(
                unit["implementation_cut"]["cut_scope"], "agreed cut"
            )
            self.assertEqual(unit["implementation_cut"]["steer_lines"], 3)

    def test_part_scope_is_wired_to_every_implementation_prompt(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-scope-") as ws:
            _path, driver, first = self._ready_driver(
                ws, runners.MockRunner([]), git_enabled=False
            )
            st.record_implementation_cut(
                driver.state, first, "coherent core", "remaining wiring"
            )
            first["status"] = st.U_SEALED
            continuation = st.ensure_next_unit(driver.state)
            expected = st.implementation_scope(driver.state, continuation)

            with mock.patch.object(
                prompts, "build_implement", wraps=prompts.build_implement
            ) as builder, mock.patch.object(
                driver, "_baseline_verification_current", return_value=True
            ), mock.patch.object(
                driver, "_call_implementation", side_effect=_PromptReached
            ):
                with self.assertRaises(_PromptReached):
                    driver._do_draft()
                self.assertEqual(
                    builder.call_args.kwargs["implementation_scope"], expected
                )

            continuation["status"] = st.U_ROUNDS
            continuation["family_index"] = 0
            with mock.patch.object(
                driver, "_review_evidence_inputs",
                return_value=("fingerprint", None, [], [], []),
            ), mock.patch.object(
                prompts, "build_review_round",
                wraps=prompts.build_review_round,
            ) as builder, mock.patch.object(
                driver, "_report_call", side_effect=_PromptReached
            ):
                with self.assertRaises(_PromptReached):
                    driver._do_review_round()
                self.assertEqual(
                    builder.call_args.kwargs["implementation_scope"], expected
                )

            continuation["status"] = st.U_FIXING
            continuation["fix_queue"] = [{
                "id": "F1",
                "severity": "P2",
                "summary": "fix the bounded defect",
            }]
            continuation["fix_source"] = {
                "type": "round",
                "family": "claude",
                "source_round_id": "slice_impl-01-b-claude-r1",
                "return_to": st.U_ROUNDS,
            }
            with mock.patch.object(
                prompts, "build_fix_findings",
                wraps=prompts.build_fix_findings,
            ) as builder, mock.patch.object(
                driver, "_call", side_effect=_PromptReached
            ):
                with self.assertRaises(_PromptReached):
                    driver._do_fix()
                self.assertEqual(
                    builder.call_args.kwargs["implementation_scope"], expected
                )

            continuation["status"] = st.U_DELTA_REVIEW
            with mock.patch.object(
                gitops, "worktree_diff", return_value="one bounded delta"
            ), mock.patch.object(
                prompts, "build_delta_review",
                wraps=prompts.build_delta_review,
            ) as builder, mock.patch.object(
                driver, "_report_call", side_effect=_PromptReached
            ):
                with self.assertRaises(_PromptReached):
                    driver._do_delta_review()
                self.assertEqual(
                    builder.call_args.kwargs["implementation_scope"], expected
                )

    def test_continuation_opens_only_after_predecessor_gate(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-gate-") as ws:
            _path, driver, first = self._ready_driver(
                ws, runners.MockRunner([]), git_enabled=False
            )
            st.record_implementation_cut(
                driver.state, first, "coherent core", "remaining wiring"
            )
            first["status"] = st.U_SEALED
            gate_observations = []

            def gate(unit):
                gate_observations.append(
                    any(candidate.get("part") == "b"
                        for candidate in driver.state["units"])
                )
                unit["gate_commit"] = "gate-a"

            with mock.patch.object(driver, "_gate_commit", side_effect=gate):
                driver._after_seal(first)

            self.assertEqual(gate_observations, [False])
            continuation = st.current_unit(driver.state)
            self.assertEqual(st.unit_key(continuation), "slice_impl-01-b")
            self.assertEqual(continuation["status"], st.U_PENDING)
            self.assertEqual(continuation["rounds"], [])
            self.assertEqual(first["gate_commit"], "gate-a")

    def test_failed_part_a_gate_is_retried_before_part_b_can_open(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-gate-resume-") as ws:
            path, driver, first = self._ready_driver(
                ws, runners.MockRunner([])
            )
            st.record_implementation_cut(
                driver.state, first, "coherent core", "remaining wiring"
            )
            first["status"] = st.U_SEALED
            gitops.commit_wip(ws, "wip: slice_impl-01-a")
            driver._save()

            with mock.patch.object(
                gitops,
                "finalize_gate",
                side_effect=gitops.GitError("simulated gate failure"),
            ):
                with self.assertRaises(drv.StopStep):
                    driver._after_seal(first)

            failed = st.load(path)
            failed_first = failed["units"][-1]
            self.assertEqual(failed_first["status"], st.U_SEALED)
            self.assertIsNone(failed_first["gate_commit"])
            self.assertFalse(any(
                unit.get("part") == "b" for unit in failed["units"]
            ))

            st.resume_run(failed)
            st.save(path, failed)
            self.assertFalse(any(
                unit.get("part") == "b" for unit in st.load(path)["units"]
            ))

            real_finalize = gitops.finalize_gate
            b_present_when_gate_retried = []

            def successful_retry(workspace, message):
                b_present_when_gate_retried.append(any(
                    unit.get("part") == "b"
                    for unit in st.load(path)["units"]
                ))
                return real_finalize(workspace, message)

            with mock.patch.object(
                gitops, "finalize_gate", side_effect=successful_retry
            ):
                recovered = drv.Driver(path, runner=runners.MockRunner([]))

            self.assertEqual(
                b_present_when_gate_retried,
                [False],
                "part b must not exist before the recovered gate succeeds",
            )
            recovered_first = next(
                unit for unit in recovered.state["units"]
                if unit["kind"] == st.UNIT_SLICE_IMPL
                and unit.get("part") is None
            )
            self.assertIsNotNone(recovered_first["gate_commit"])

    def test_failed_last_gate_recovery_closes_with_a_final_commit(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-last-gate-") as ws:
            path, driver, last = self._ready_driver(
                ws, runners.MockRunner([])
            )
            last["status"] = st.U_SEALED
            gitops.commit_wip(ws, "wip: slice_impl-01")
            driver._save()

            with mock.patch.object(
                gitops,
                "finalize_gate",
                side_effect=gitops.GitError("simulated final gate failure"),
            ):
                with self.assertRaises(drv.StopStep):
                    driver._after_seal(last)

            failed = st.load(path)
            self.assertEqual(failed["units"][-1]["status"], st.U_SEALED)
            self.assertIsNone(failed["units"][-1]["gate_commit"])
            st.resume_run(failed)
            st.save(path, failed)

            real_finalize = gitops.finalize_gate
            real_final = gitops.commit_plain
            with mock.patch.object(
                gitops, "finalize_gate", wraps=real_finalize
            ) as retried_gate, mock.patch.object(
                gitops, "commit_plain", wraps=real_final
            ) as final_commit:
                recovered = drv.Driver(path, runner=runners.MockRunner([]))
                recovered.run(max_steps=1)

            self.assertEqual(retried_gate.call_count, 1)
            final_commit.assert_called_once_with(ws, "Close milestone")
            closed = st.load(path)
            self.assertEqual(closed["milestone"]["status"], st.M_CLOSED)
            self.assertIsNotNone(closed["units"][-1]["gate_commit"])

    def test_failed_final_commit_stays_pending_and_resume_retries_it(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-final-resume-") as ws:
            path, driver, last = self._ready_driver(
                ws, runners.MockRunner([])
            )
            last["status"] = st.U_SEALED
            gitops.commit_wip(ws, "wip: slice_impl-01")
            driver._save()

            with mock.patch.object(
                gitops,
                "commit_plain",
                side_effect=gitops.GitError("simulated close commit failure"),
            ):
                with self.assertRaises(drv.StopStep):
                    driver._after_seal(last)

            failed = st.load(path)
            self.assertTrue(failed["pending_final_commit"])
            self.assertIsNotNone(failed["failure"])
            self.assertIsNotNone(failed["units"][-1]["gate_commit"])

            st.resume_run(failed)
            st.save(path, failed)
            real_final = gitops.commit_plain
            with mock.patch.object(
                gitops, "commit_plain", wraps=real_final
            ) as retried_final:
                drv.Driver(path, runner=runners.MockRunner([]))

            retried_final.assert_called_once_with(ws, "Close milestone")
            closed = st.load(path)
            self.assertEqual(closed["milestone"]["status"], st.M_CLOSED)
            self.assertIsNone(closed["failure"])
            self.assertNotIn("pending_final_commit", closed)
            final_events = [
                event for event in closed["events"]
                if event.get("type") == "gate_commit"
                and event.get("unit") is None
                and event.get("message") == "Close milestone"
            ]
            self.assertEqual(len(final_events), 1)

    def test_pending_gate_does_not_duplicate_a_redoc_wave_gate(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-wave-gate-") as ws:
            path, driver, _implementation = self._ready_driver(
                ws, runners.MockRunner([])
            )
            skeleton, note = driver.state["units"][:2]
            old_gate = gitops.head_sha(ws)
            skeleton["gate_commit"] = old_gate
            note["status"] = st.U_REPAIRING
            note["under_repair"] = True
            driver.state["redoc_wave"] = {
                "anchor": st.unit_key(skeleton),
                "docs": [st.unit_key(note)],
                "reporter": "slice_impl-01",
            }
            st.append_event(
                driver.state,
                "gate_commit",
                unit=st.unit_key(skeleton),
                sha=old_gate,
                message="old skeleton gate",
            )
            st.append_event(
                driver.state,
                "unit_transition",
                unit=st.unit_key(skeleton),
                from_status=st.U_SEALING,
                to_status=st.U_SEALED,
                reason="redoc anchor resealed",
            )
            gitops.commit_wip(ws, "wip: skeleton redocumentation")
            driver._save()

            with mock.patch.object(
                gitops,
                "finalize_gate",
                side_effect=gitops.GitError("simulated wave gate failure"),
            ):
                with self.assertRaises(drv.StopStep):
                    driver._after_seal(skeleton)

            failed = st.load(path)
            self.assertEqual(failed["pending_gate_unit"], "skeleton")
            self.assertIsNotNone(failed["redoc_wave"])
            self.assertEqual(failed["units"][1]["status"], st.U_SEALED)
            st.resume_run(failed)
            st.save(path, failed)

            real_finalize = gitops.finalize_gate
            with mock.patch.object(
                gitops, "finalize_gate", wraps=real_finalize
            ) as retried_gate:
                drv.Driver(path, runner=runners.MockRunner([]))

            self.assertEqual(retried_gate.call_count, 1)
            recovered = st.load(path)
            self.assertNotIn("pending_gate_unit", recovered)
            self.assertIsNone(recovered["redoc_wave"])
            self.assertEqual(
                recovered["units"][1]["gate_commit"],
                recovered["units"][0]["gate_commit"],
            )
            wave_closes = [
                event for event in recovered["events"]
                if event.get("type") == "redoc_wave_closed"
            ]
            self.assertEqual(len(wave_closes), 1)
            skeleton_gates = [
                event for event in recovered["events"]
                if event.get("type") == "gate_commit"
                and event.get("unit") == "skeleton"
            ]
            self.assertEqual(len(skeleton_gates), 2)  # old gate + one retry


if __name__ == "__main__":
    unittest.main()
