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
                 recovery_lines=4, recovery_script=None,
                 interrupt_error=None, confirm_delay_s=None):
        super().__init__([])
        self.mode = mode
        self.response = response
        self.recovery_response = recovery_response
        self.recovery_lines = recovery_lines
        self.recovery_script = list(recovery_script or [])
        self.interrupt_error = interrupt_error
        self.confirm_delay_s = confirm_delay_s
        self.controls = []
        self.stabilization_seen_before_error = False
        self.steer_at = None
        self.confirmed_at = None
        self.interrupt_at = None
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
        self.controls.append(active_control)

        if active_control is None:
            response = (
                self.recovery_script.pop(0)
                if self.recovery_script else self.recovery_response
            )
            if response is None:
                raise AssertionError("unexpected uncontrolled worker call")
            if isinstance(response, BaseException):
                raise response
            self._write_lines(workspace, self.recovery_lines)
            text = json.dumps(response) if isinstance(response, dict) \
                else response
            return runners.RunnerResult(text, 0, 0.02)

        def receive_steer(_text):
            self.steer_at = time.monotonic()
            self.steer_seen.set()
            if self.confirm_delay_s == 0:
                if active_control.observe_model_message(
                    drv.IMPLEMENTATION_SIZE_ACK
                ):
                    self.confirmed_at = active_control.model_confirmation_at
            return True

        def receive_interrupt(_reason):
            self.interrupt_at = time.monotonic()
            self.interrupt_seen.set()
            return True

        active_control._bind(receive_steer, receive_interrupt)
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
                if self.mode in (
                    "hard", "error_after_interrupt", "crash_after_interrupt",
                    "complete_after_failed_interrupt",
                    "complete_after_accepted_interrupt",
                ):
                    self._write_lines(workspace, 8)
                    if self.confirm_delay_s not in (None, 0):
                        time.sleep(self.confirm_delay_s)
                        if active_control.observe_model_message(
                            drv.IMPLEMENTATION_SIZE_ACK
                        ):
                            self.confirmed_at = (
                                active_control.model_confirmation_at
                            )
                    if self.mode == "complete_after_failed_interrupt":
                        self._wait_for(
                            lambda: bool(active_control.error),
                            "cutoff persistence failure was not observed",
                        )
                        result = runners.RunnerResult(
                            json.dumps(self.response), 0, 0.02
                        )
                        result.steers = active_control.steers
                        return result
                    self._wait_for(
                        lambda: active_control.interrupted,
                        "hard size interruption was not delivered",
                    )
                    if self.mode == "complete_after_accepted_interrupt":
                        result = runners.RunnerResult(
                            json.dumps(self.response), 0, 0.02
                        )
                        result.steers = active_control.steers
                        return result
                    if self.mode == "crash_after_interrupt":
                        raise _PromptReached(
                            "crash after interrupt delivery"
                        )
                    if self.mode == "error_after_interrupt":
                        persisted = st.load(drv.default_state_path(workspace))
                        self.stabilization_seen_before_error = bool(
                            st.current_unit(persisted).get(
                                "implementation_stabilization"
                            )
                        )
                        raise self.interrupt_error
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


class PersistedEventProbeRunner(LiveControlRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events_at_stabilizer_entry = []

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None, active_control=None):
        if active_control is None:
            persisted = st.load(drv.default_state_path(workspace))
            self.events_at_stabilizer_entry = [
                event for event in persisted["events"]
                if event.get("unit") == "slice_impl-01"
                and event.get("type") in {
                    "implementation_size_steer",
                    "implementation_size_interrupted",
                }
            ]
        return super().call(
            family,
            prompt,
            workspace,
            model=model,
            effort=effort,
            timeout_override=timeout_override,
            active_control=active_control,
        )


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
    def __init__(self, raw_texts=None):
        self.controls = []
        self.raw_texts = list(raw_texts or [])

    def call(self, _family, _prompt, _workspace, model=None, effort=None,
             active_control=None):
        del model, effort
        self.controls.append((
            active_control,
            active_control.closed if active_control is not None else None,
        ))
        if active_control is not None:
            active_control._close()
        if len(self.controls) == 1:
            error = runners.RunnerError("temporary network failure")
            error.raw_texts = list(self.raw_texts)
            raise error
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


class InterruptedRepairRunner(object):
    def __init__(self):
        self.calls = 0

    def call(self, _family, _prompt, _workspace, model=None, effort=None):
        del model, effort
        self.calls += 1
        if self.calls == 1:
            return runners.RunnerResult(
                "", 0, 0.01, transport_text="malformed draft transport"
            )
        return runners.ControlledInterruptionResult(
            "partial repair output", -9, 0.02, "controlled size cutoff",
            transport_text="full interrupted repair transport",
        )


class TimedOutSteerConfirmedRunner(runners.MockRunner):
    """The steer RPC times out, then the model proves it received the text."""

    def __init__(self, response):
        super().__init__([])
        self.response = response
        self.controls = []

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None, active_control=None):
        del timeout_override
        self.calls.append((family, runners.prompt_kind(prompt), prompt))
        self.call_meta.append({
            "family": family,
            "kind": runners.prompt_kind(prompt),
            "model": model,
            "effort": effort,
        })
        self.controls.append(active_control)
        confirmed = threading.Event()

        def steer_timeout(_text):
            def confirm_later():
                time.sleep(0.005)
                active_control.observe_model_message(
                    drv.IMPLEMENTATION_SIZE_ACK
                )
                confirmed.set()

            threading.Thread(target=confirm_later, daemon=True).start()
            return False

        active_control._bind(steer_timeout, lambda _reason: True)
        try:
            LiveControlRunner._write_lines(workspace, 3)
            self.assert_confirmation(confirmed)
            return runners.RunnerResult(
                json.dumps(self.response), 0, 0.02
            )
        finally:
            active_control._close()

    @staticmethod
    def assert_confirmation(confirmed):
        if not confirmed.wait(1):
            raise AssertionError("model confirmation was not observed")


class RepairAckCutRunner(runners.MockRunner):
    """Only the renewed contract-repair call emits the exact model ACK."""

    def __init__(self, response):
        super().__init__([])
        self.response = response
        self.controls = []
        self.physical_calls = 0

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None, active_control=None):
        del timeout_override
        self.physical_calls += 1
        current_call = self.physical_calls
        self.calls.append((family, runners.prompt_kind(prompt), prompt))
        self.call_meta.append({
            "family": family,
            "kind": runners.prompt_kind(prompt),
            "model": model,
            "effort": effort,
        })
        self.controls.append(active_control)
        steer_seen = threading.Event()
        confirmed = threading.Event()

        def steer_timeout(_text):
            steer_seen.set()
            if current_call == 2:
                active_control.observe_model_message(
                    drv.IMPLEMENTATION_SIZE_ACK
                )
                confirmed.set()
            return False

        active_control._bind(steer_timeout, lambda _reason: True)
        try:
            LiveControlRunner._write_lines(workspace, 3)
            if not steer_seen.wait(1):
                raise AssertionError("size steer was not attempted")
            if current_call == 1:
                return runners.RunnerResult("not json", 0, 0.01)
            if not confirmed.wait(1):
                raise AssertionError("repair ACK was not observed")
            return runners.RunnerResult(
                json.dumps(self.response), 0, 0.02
            )
        finally:
            active_control._close()


class ProactiveRepairCutRunner(runners.MockRunner):
    """Repair a malformed sub-threshold draft with a proactive cut."""

    def __init__(self, response):
        super().__init__([])
        self.response = response
        self.controls = []

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None, active_control=None):
        del timeout_override
        self.calls.append((family, runners.prompt_kind(prompt), prompt))
        self.call_meta.append({
            "family": family,
            "kind": runners.prompt_kind(prompt),
            "model": model,
            "effort": effort,
        })
        self.controls.append(active_control)
        active_control._bind(lambda _text: True, lambda _reason: True)
        try:
            LiveControlRunner._write_lines(workspace, 2)
            if len(self.calls) == 1:
                return runners.RunnerResult("not json", 0, 0.01)
            return runners.RunnerResult(
                json.dumps(self.response), 0, 0.02
            )
        finally:
            active_control._close()


class DriverImplementationSizeTest(unittest.TestCase):
    def _ready_driver(self, workspace, runner, size_control=None,
                      git_enabled=True):
        effective_size_control = {
            "soft_lines": 1000,
            "hard_lines": 1500,
            "poll_interval_s": 0.005,
            "unconfirmed_grace_s": 0.03,
            "confirmed_grace_s": 0.08,
        }
        effective_size_control.update(size_control or {})
        config = make_config(
            git={"enabled": git_enabled},
            implementation_size_control=effective_size_control,
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
        return path, driver, implementation

    def test_rejected_valid_delivery_keeps_its_usage(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-rejected-") as ws:
            path, driver, _unit = self._ready_driver(
                ws, runners.MockRunner([])
            )
            usage = {
                "input_tokens": 10, "cached_input_tokens": 2,
                "output_tokens": 3, "reasoning_output_tokens": 1,
                "total_tokens": 13,
            }
            result = runners.RunnerResult(
                "{}", 0, 2.0, token_usage=usage
            )

            with self.assertRaises(drv.StopStep):
                driver._fail_implementation_size(
                    None, 1500, "measurement failed",
                    family="codex", result=result,
                )

            state = st.load(path)
            rejected = [
                event for event in state["events"]
                if event["type"] == "worker_unaccepted"
            ]
            self.assertEqual(rejected[0]["token_usage"], usage)
            self.assertEqual(st.summary(state)["work_token_usage"], usage)

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
                "request": "Choose the bounded implementation to continue.",
                "finding": {
                    "id": "F1",
                    "summary": "the implementation choice needs agreement",
                },
                "target_path": "docs/slice-01.md",
                "max_rounds": 10,
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
            runner = InfraRetryControlRunner(["captured network diagnostic"])
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
            incidents = [
                event for event in driver.state["events"]
                if event.get("type") == "worker_malformed"
                and event.get("label") == "controlled-infra-retry"
            ]
            self.assertEqual(len(incidents), 1)
            self.assertFalse(incidents[0]["fatal"])
            self.assertTrue(incidents[0]["infra_retry"])
            self.assertNotIn("stabilizer_retry", incidents[0])
            self.assertTrue(os.path.exists(os.path.join(
                ws, incidents[0]["raw_path"]
            )))

    def test_absorbed_stabilizer_infra_retry_keeps_raw_evidence(self):
        with tempfile.TemporaryDirectory(prefix="orch-stable-infra-retry-") \
                as ws:
            _path, driver, _unit = self._ready_driver(
                ws, runners.MockRunner([]), git_enabled=False
            )
            runner = InfraRetryControlRunner([
                "stabilizer network diagnostic one",
                "stabilizer network diagnostic two",
            ])
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
                    "stabilizer-infra-retry",
                    repeat_protocol=True,
                )

            self.assertEqual(output["status"], "ok")
            incidents = [
                event for event in driver.state["events"]
                if event.get("type") == "worker_malformed"
                and event.get("label") == "stabilizer-infra-retry"
            ]
            self.assertEqual(len(incidents), 1)
            self.assertFalse(incidents[0]["fatal"])
            self.assertTrue(incidents[0]["infra_retry"])
            self.assertTrue(incidents[0]["stabilizer_retry"])
            for key in ("raw_path", "raw_path2"):
                self.assertTrue(os.path.exists(os.path.join(
                    ws, incidents[0][key]
                )))

    def test_absorbed_infrastructure_retry_records_error_without_raw(self):
        with tempfile.TemporaryDirectory(prefix="orch-infra-no-raw-") as ws:
            _path, driver, _unit = self._ready_driver(
                ws, runners.MockRunner([]), git_enabled=False
            )
            driver.runner = InfraRetryControlRunner()
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
                    "infra-no-raw",
                    active_control=runners.ActiveCallControl(),
                )

            self.assertEqual(output["status"], "ok")
            incidents = [
                event for event in driver.state["events"]
                if event.get("type") == "worker_malformed"
                and event.get("label") == "infra-no-raw"
            ]
            self.assertEqual(len(incidents), 1)
            self.assertTrue(incidents[0]["infra_retry"])
            self.assertIn("temporary network failure", incidents[0]["error"])
            self.assertIsNone(incidents[0]["raw_path"])
            self.assertIsNone(incidents[0]["raw_path2"])

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

    def test_failed_cutoff_persistence_does_not_send_interrupt(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-persist-fail-") \
                as ws:
            _path, driver, unit = self._ready_driver(
                ws, runners.MockRunner([])
            )
            marker = {
                "soft_lines": 2,
                "hard_lines": 6,
                "steer_lines": 3,
                "interrupt_lines": 8,
            }
            sent = []
            control = runners.ActiveCallControl(
                on_interrupt=lambda _reason: (
                    driver._persist_implementation_stabilization(marker)
                )
            )
            control._bind(
                lambda _text: True,
                lambda _reason: (sent.append(True) or True),
            )

            with mock.patch.object(
                driver, "_save", side_effect=OSError("state write failed")
            ):
                self.assertFalse(control.interrupt("hard size limit"))

            self.assertEqual(sent, [])
            self.assertFalse(control.interrupted)
            self.assertNotIn("implementation_stabilization", unit)
            control._close()

    def test_rejected_cutoff_transport_resumes_as_an_ordinary_draft(self):
        def return_false(_reason):
            return False

        def raise_error(_reason):
            raise OSError("interrupt transport rejected")

        for label, reject in (
            ("false", return_false),
            ("exception", raise_error),
        ):
            with self.subTest(transport=label), tempfile.TemporaryDirectory(
                prefix="orch-size-rejected-%s-" % label
            ) as ws:
                path, driver, _unit = self._ready_driver(
                    ws, runners.MockRunner([])
                )
                base_tree = gitops.snapshot_index_tree(ws)
                control, _marker = driver._implementation_size_control(
                    base_tree
                )
                control._bind(lambda _text: True, reject)

                self.assertFalse(control.interrupt("hard size limit"))
                control._close()
                persisted = st.load(path)
                self.assertNotIn(
                    "implementation_stabilization",
                    st.current_unit(persisted),
                )

                resumed_runner = LiveControlRunner(
                    "normal",
                    ok(contracts.KIND_IMPLEMENT,
                       files_changed=["implementation.py"]),
                )
                resumed = drv.Driver(path, runner=resumed_runner)
                resumed.step()

                self.assertIsNotNone(resumed_runner.controls[0])
                self.assertNotIn(
                    "FORCED CONTROLLED-CUTOFF RECOVERY",
                    resumed_runner.calls[0][2],
                )

    def test_cutoff_monitor_retries_after_transient_state_write_failure(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-save-retry-") as ws:
            runner = LiveControlRunner(
                "hard",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
                recovery_response=self._cut_response(
                    "coherent retry recovery", "remaining wiring"
                ),
                recovery_lines=8,
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.005},
            )
            real_save = driver._save
            failures = []

            def fail_first_cutoff_save():
                if (
                    not failures
                    and st.current_unit(driver.state).get(
                        "implementation_stabilization"
                    )
                ):
                    failures.append("state write failed")
                    raise OSError("state write failed")
                return real_save()

            with mock.patch.object(
                driver, "_save", side_effect=fail_first_cutoff_save
            ):
                action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertEqual(failures, ["state write failed"])
            self.assertTrue(runner.interrupt_seen.is_set())
            self.assertIsNotNone(runner.controls[0].interrupt_reason)
            recovered = st.load(path)
            unit = st.current_unit(recovered)
            self.assertIsNone(recovered["failure"])
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertNotIn("implementation_stabilization", unit)
            self.assertEqual(len([
                event for event in recovered["events"]
                if event.get("type") == "implementation_size_interrupted"
            ]), 1)

    def test_unpersisted_cutoff_cannot_open_oversized_review(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-save-block-") as ws:
            runner = LiveControlRunner(
                "complete_after_failed_interrupt",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.005},
            )
            real_save = driver._save

            def reject_cutoff_save():
                if st.current_unit(driver.state).get(
                    "implementation_stabilization"
                ):
                    raise OSError("state write remains unavailable")
                return real_save()

            with mock.patch.object(
                driver, "_save", side_effect=reject_cutoff_save
            ):
                action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            blocked = st.load(path)
            unit = st.current_unit(blocked)
            self.assertIsNotNone(blocked["failure"])
            self.assertEqual(blocked["failure"]["type"], "worker_protocol")
            self.assertIsNone(unit["draft"])
            self.assertNotEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertFalse(runner.controls[0].interrupted)

    def test_completed_ok_wins_after_accepted_interrupt(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-stop-race-") as ws:
            runner = LiveControlRunner(
                "complete_after_accepted_interrupt",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.005},
            )

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            completed = st.load(path)
            unit = st.current_unit(completed)
            self.assertIsNone(completed["failure"])
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertIsNotNone(unit["draft"])
            self.assertNotIn("implementation_stabilization", unit)
            self.assertTrue(runner.controls[0].interrupted)
            self.assertEqual(len(runner.calls), 1)
            self.assertFalse(any(
                event.get("type") == "implementation_size_interrupted"
                for event in completed["events"]
            ))

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

    def test_delivered_soft_steer_records_metrics_on_part_a_cut(self):
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

    def test_proactive_cut_without_a_live_steer_opens_part_a(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-proactive-") as ws:
            runner = LiveControlRunner("normal", self._cut_response())
            path, driver, _unit = self._ready_driver(ws, runner)

            action, note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertIn("drafted", note)
            state = st.load(path)
            self.assertIsNone(state["failure"])
            unit = st.current_unit(state)
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertEqual(st.display_unit_key(unit), "slice_impl-01-a")
            self.assertEqual(unit["implementation_cut"]["part"], "a")
            self.assertNotIn("steer_lines", unit["implementation_cut"])
            self.assertFalse(any(
                event["type"] == "implementation_size_steer"
                for event in state["events"]
            ))
            subject = gitops._run(
                ws, "log", "-1", "--format=%s"
            ).stdout.strip()
            self.assertEqual(subject, "wip: slice_impl-01-a")

    def test_rethink_resume_may_return_a_proactive_cut(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-rethink-") as ws:
            _path, driver, unit = self._ready_driver(
                ws, runners.MockRunner([]), git_enabled=False
            )
            output = self._cut_response()
            result = runners.RunnerResult(json.dumps(output), 0, 0.02)
            result.origin_family = "codex"
            result.origin_model = "gpt-5.6-sol"
            result.origin_effort = "max"
            result.origin_pre_snapshot = {}

            with mock.patch.object(
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

    def test_contract_repair_may_return_a_proactive_cut(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-repair-") as ws:
            runner = ProactiveRepairCutRunner(self._cut_response())
            path, driver, _unit = self._ready_driver(ws, runner)

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            state = st.load(path)
            self.assertIsNone(state["failure"])
            unit = st.current_unit(state)
            self.assertEqual(st.display_unit_key(unit), "slice_impl-01-a")
            self.assertEqual(
                unit["implementation_cut"]["cut_scope"], "coherent core"
            )
            self.assertEqual(len(runner.calls), 2)
            self.assertTrue(all(control is not None
                                for control in runner.controls))
            self.assertFalse(any(
                event["type"] == "implementation_size_steer"
                for event in state["events"]
            ))

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
            self.assertFalse(
                events["implementation_size_steer"]["confirmed"]
            )
            self.assertEqual(
                events["implementation_size_steer"]["grace_kind"],
                "unconfirmed",
            )
            self.assertGreaterEqual(
                runner.interrupt_at - runner.steer_at, 0.02
            )
            self.assertGreaterEqual(
                events["implementation_size_interrupted"]["lines"], 6
            )
            self.assertIn("controlled size cutoff",
                          events["implementation_size_interrupted"]["reason"])

    def test_real_model_ack_uses_confirmed_grace_and_is_armed_before_send(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-confirmed-") as ws:
            runner = LiveControlRunner(
                "hard",
                self._cut_response(),
                recovery_response=self._cut_response(
                    "confirmed coherent work", "remaining wiring"
                ),
                confirm_delay_s=0,
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {
                    "soft_lines": 2, "hard_lines": 6,
                    "poll_interval_s": 0.002,
                    "unconfirmed_grace_s": 0.02,
                    "confirmed_grace_s": 0.08,
                },
            )

            driver.step()

            event = next(
                event for event in st.load(path)["events"]
                if event["type"] == "implementation_size_steer"
            )
            self.assertTrue(event["delivered"])
            self.assertTrue(event["confirmed"])
            self.assertEqual(event["grace_kind"], "confirmed")
            self.assertIsNotNone(runner.confirmed_at)
            self.assertGreaterEqual(
                runner.interrupt_at - runner.steer_at, 0.065
            )
            self.assertTrue(any(
                drv.IMPLEMENTATION_SIZE_ACK in steer
                for steer in runner.controls[0].steers
            ))

    def test_ack_during_unconfirmed_grace_extends_from_confirmation(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-late-confirm-") \
                as ws:
            runner = LiveControlRunner(
                "hard",
                self._cut_response(),
                recovery_response=self._cut_response(
                    "late confirmed work", "remaining wiring"
                ),
                confirm_delay_s=0.03,
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {
                    "soft_lines": 2, "hard_lines": 6,
                    "poll_interval_s": 0.002,
                    "unconfirmed_grace_s": 0.06,
                    "confirmed_grace_s": 0.07,
                },
            )

            driver.step()

            event = next(
                event for event in st.load(path)["events"]
                if event["type"] == "implementation_size_steer"
            )
            self.assertTrue(event["confirmed"])
            self.assertEqual(event["grace_kind"], "confirmed")
            self.assertGreaterEqual(
                runner.interrupt_at - runner.confirmed_at, 0.06
            )

    def test_late_ack_records_cut_after_codex_steer_rpc_timeout(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-ack-timeout-") \
                as ws:
            runner = TimedOutSteerConfirmedRunner(self._cut_response())
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.002},
            )

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            state = st.load(path)
            self.assertIsNone(state["failure"])
            unit = st.current_unit(state)
            self.assertEqual(
                unit["implementation_cut"]["cut_scope"], "coherent core"
            )
            event = next(
                event for event in state["events"]
                if event["type"] == "implementation_size_steer"
            )
            self.assertTrue(event["confirmed"])
            self.assertTrue(event["delivered"])
            self.assertEqual(
                runner.controls[0].steers, [],
                "the timed-out RPC itself did not report delivery",
            )

    def test_repair_ack_is_visible_to_original_control_and_cut(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-repair-ack-") as ws:
            runner = RepairAckCutRunner(self._cut_response())
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.002},
            )

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            state = st.load(path)
            self.assertIsNone(state["failure"])
            unit = st.current_unit(state)
            self.assertEqual(
                unit["implementation_cut"]["cut_scope"], "coherent core"
            )
            self.assertIsNot(runner.controls[0], runner.controls[1])
            self.assertIsNotNone(runner.controls[0].model_confirmation_at)
            self.assertEqual(
                runner.controls[0].model_confirmation_at,
                runner.controls[1].model_confirmation_at,
            )
            event = next(
                event for event in state["events"]
                if event["type"] == "implementation_size_steer"
            )
            self.assertTrue(event["confirmed"])
            self.assertTrue(event["delivered"])

    def test_controlled_repair_persists_first_malformed_output(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-repair-cut-") as ws:
            runner = InterruptedRepairRunner()
            _path, driver, _unit = self._ready_driver(
                ws, runner, git_enabled=False
            )

            output, result, controlled_raw_path = driver._call(
                "codex",
                "KIND: implement\nFAMILY: codex\nWORKSPACE: %s\n" % ws,
                contracts.KIND_IMPLEMENT,
                "slice_impl-01-draft",
            )

            self.assertIsNone(output)
            self.assertIsInstance(
                result, runners.ControlledInterruptionResult
            )
            strikes = [
                event for event in driver.state["events"]
                if event.get("type") == "worker_malformed"
            ]
            self.assertEqual(len(strikes), 1)
            raw_path = os.path.join(ws, strikes[0]["raw_path"])
            with open(raw_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "malformed draft transport")
            with open(os.path.join(ws, controlled_raw_path),
                      encoding="utf-8") as handle:
                self.assertEqual(
                    handle.read(), "full interrupted repair transport"
                )

    def test_error_after_accepted_interrupt_enters_stabilizer_without_retry(
        self,
    ):
        errors = (
            runners.RunnerError("connection reset after accepted interrupt"),
            runners.WorkerProtocolError(
                "malformed output after accepted interrupt",
                raw_texts=["bad output one", "bad output two"],
            ),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    tempfile.TemporaryDirectory(
                        prefix="orch-size-interrupt-error-"
                    ) as ws:
                runner = LiveControlRunner(
                    "error_after_interrupt",
                    ok(contracts.KIND_IMPLEMENT,
                       files_changed=["implementation.py"]),
                    recovery_response=self._cut_response(
                        "stable after transport error", "remaining wiring"
                    ),
                    recovery_lines=8,
                    interrupt_error=error,
                )
                path, driver, _unit = self._ready_driver(
                    ws,
                    runner,
                    {"soft_lines": 2, "hard_lines": 6,
                     "poll_interval_s": 0.005},
                )
                driver.config["infra_retry_backoff_s"] = [0]

                action, _note = driver.step()

                self.assertEqual(action.type, drv.A_DRAFT)
                state = st.load(path)
                unit = st.current_unit(state)
                self.assertTrue(runner.stabilization_seen_before_error)
                self.assertIsNone(state["failure"])
                self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
                self.assertNotIn("implementation_stabilization", unit)
                self.assertEqual(len(runner.calls), 2)
                self.assertIsNotNone(runner.controls[0])
                self.assertIsNone(runner.controls[1])
                self.assertIn(
                    "FORCED CONTROLLED-CUTOFF RECOVERY",
                    runner.calls[1][2],
                )
                self.assertFalse(any(
                    event.get("type") in ("infra_retry", "run_failed")
                    for event in state["events"]
                ))
                incidents = [
                    event for event in state["events"]
                    if event.get("type") == "worker_malformed"
                    and event.get("controlled_interruption")
                ]
                self.assertEqual(len(incidents), 1)
                self.assertIn(str(error), incidents[0]["error"])
                if getattr(error, "raw_texts", None):
                    self.assertIsNotNone(incidents[0]["raw_path"])
                else:
                    self.assertIsNone(incidents[0]["raw_path"])
                    self.assertIsNone(incidents[0]["raw_path2"])

    def test_hard_jump_that_finishes_during_grace_is_accepted(self):
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
            self.assertEqual(len(runner.calls), 1)
            unit = st.current_unit(st.load(path))
            self.assertEqual(st.display_unit_key(unit), "slice_impl-01")
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)

    def test_valid_completion_between_polls_is_reviewed_without_stabilizer(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="orch-size-fast-finish-") as ws:
            runner = LiveControlRunner(
                "steer",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.05},
            )

            # The live observer saw the soft-sized delta and delivered its
            # steer. The worker then completed with a valid envelope before
            # another poll could observe the final over-hard size.
            with mock.patch.object(
                driver, "_implementation_line_count", return_value=8
            ):
                action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertEqual(len(runner.calls), 1)
            state = st.load(path)
            unit = st.current_unit(state)
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertNotIn("implementation_stabilization", unit)
            overflow = [
                event for event in state["events"]
                if event.get("type") == "implementation_size_overflow"
            ]
            self.assertEqual(len(overflow), 1)
            self.assertTrue(overflow[0]["completed"])

    def test_stabilizer_can_close_an_oversized_coherent_delivery(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-bad-recovery-") as ws:
            runner = LiveControlRunner(
                "hard",
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

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            state = st.load(path)
            unit = st.current_unit(state)
            self.assertIsNone(state["failure"])
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertIsNotNone(unit["draft"])
            self.assertTrue(any(
                event["type"] == "wip_commit" for event in state["events"]
            ))
            self.assertEqual(len(runner.calls), 2)
            self.assertIsNotNone(runner.controls[0])
            self.assertIsNone(runner.controls[1])
            self.assertIn(
                "No further size cutoff applies to this stabilization",
                runner.calls[1][2],
            )
            self.assertNotIn("reduce the current reviewable Git delta",
                             runner.calls[1][2])
            self.assertNotIn("below approximately 750", runner.calls[1][2])
            self.assertNotIn("Do not compress, omit, distort",
                             runner.calls[1][2])
            self.assertNotIn("Observed reviewable Git lines",
                             runner.calls[1][2])

    def test_malformed_stabilizer_retries_fresh_until_valid(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-retry-recovery-") \
                as ws:
            runner = LiveControlRunner(
                "hard",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
                recovery_lines=8,
                recovery_script=[
                    "",
                    "still not json",
                    "not json in the next fresh stabilizer",
                    "still malformed in its repair",
                    self._cut_response(
                        "coherent preserved work", "remaining wiring"
                    ),
                ],
            )
            path, driver, _unit = self._ready_driver(
                ws,
                runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.05},
            )

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            state = st.load(path)
            unit = st.current_unit(state)
            self.assertIsNone(state["failure"])
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertEqual(
                unit["implementation_cut"]["cut_scope"],
                "coherent preserved work",
            )
            self.assertEqual(len(runner.calls), 6)
            self.assertTrue(all(control is None
                                for control in runner.controls[1:]))
            self.assertEqual(
                [kind for kind, _family, _session in runner.session_calls],
                ["start", "start", "continue", "start", "continue",
                 "start"],
            )
            strikes = [
                event for event in state["events"]
                if event.get("type") == "worker_malformed"
                and event.get("label") == "slice_impl-01-draft-stabilize"
            ]
            self.assertEqual(len(strikes), 2)
            self.assertTrue(all(not strike["fatal"] for strike in strikes))
            raw_paths = [
                strike[key] for strike in strikes
                for key in ("raw_path", "raw_path2")
            ]
            self.assertEqual(len(set(raw_paths)), 4)
            self.assertTrue(all(os.path.exists(os.path.join(ws, path))
                                for path in raw_paths))

    def test_failed_stabilizer_resume_returns_to_uncontrolled_stabilization(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="orch-size-failed-recovery-") \
                as ws:
            failed_runner = LiveControlRunner(
                "hard",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
                recovery_lines=8,
                recovery_script=[runners.RunnerError("provider failed")],
            )
            path, driver, _unit = self._ready_driver(
                ws,
                failed_runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.05},
            )

            action, _note = driver.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            failed = st.load(path)
            unit = st.current_unit(failed)
            self.assertIsNotNone(failed["failure"])
            self.assertIsNone(unit["draft"])
            marker = unit["implementation_stabilization"]
            self.assertGreater(
                marker["implementation_size"]["last_lines"], 6
            )
            self.assertIsNotNone(failed_runner.controls[0])
            self.assertIsNone(failed_runner.controls[1])

            st.resume_run(failed)
            st.save(path, failed)
            resumed_runner = LiveControlRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT, files_changed=[]),
                recovery_response=self._cut_response(
                    "resumed coherent work", "remaining wiring"
                ),
                recovery_lines=8,
            )
            resumed = drv.Driver(path, runner=resumed_runner)

            resumed_action, _resumed_note = resumed.step()

            self.assertEqual(resumed_action.type, drv.A_DRAFT)
            recovered = st.load(path)
            unit = st.current_unit(recovered)
            self.assertIsNone(recovered["failure"])
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertNotIn("implementation_stabilization", unit)
            self.assertEqual(resumed_runner.controls, [None])
            self.assertEqual(len(resumed_runner.calls), 1)
            self.assertIn(
                "FORCED CONTROLLED-CUTOFF RECOVERY",
                resumed_runner.calls[0][2],
            )
            self.assertEqual(
                unit["implementation_cut"]["cut_scope"],
                "resumed coherent work",
            )

    def test_crash_before_stabilizer_output_keeps_stabilization_mode(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-crash-recovery-") \
                as ws:
            crashed_runner = LiveControlRunner(
                "hard",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
                recovery_lines=8,
                recovery_script=[_PromptReached("simulated driver crash")],
            )
            path, driver, _unit = self._ready_driver(
                ws,
                crashed_runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.05},
            )

            with self.assertRaisesRegex(_PromptReached, "driver crash"):
                driver.step()

            persisted = st.load(path)
            self.assertIsNone(persisted["failure"])
            persisted_unit = st.current_unit(persisted)
            self.assertIn("implementation_stabilization", persisted_unit)
            events = {
                event["type"]: event for event in persisted["events"]
                if event["type"] in {
                    "implementation_size_steer",
                    "implementation_size_interrupted",
                }
            }
            self.assertEqual(set(events), {
                "implementation_size_steer",
                "implementation_size_interrupted",
            })
            durable_size = persisted_unit[
                "implementation_stabilization"
            ]["implementation_size"]
            self.assertEqual(
                durable_size["steer_lines"],
                events["implementation_size_steer"]["lines"],
            )
            self.assertEqual(
                durable_size["interrupt_lines"],
                events["implementation_size_interrupted"]["lines"],
            )
            self.assertEqual(
                durable_size["grace_kind"],
                events["implementation_size_interrupted"]["grace_kind"],
            )

            resumed_runner = LiveControlRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT, files_changed=[]),
                recovery_response=self._cut_response(
                    "post-crash coherent work", "remaining wiring"
                ),
                recovery_lines=8,
            )
            resumed = drv.Driver(path, runner=resumed_runner)

            resumed.step()

            recovered = st.load(path)
            unit = st.current_unit(recovered)
            self.assertIsNone(recovered["failure"])
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertNotIn("implementation_stabilization", unit)
            self.assertEqual(resumed_runner.controls, [None])
            self.assertEqual(len(resumed_runner.calls), 1)
            self.assertIn(
                "FORCED CONTROLLED-CUTOFF RECOVERY",
                resumed_runner.calls[0][2],
            )

    def test_resume_repairs_events_after_crash_on_interrupt_delivery(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-stop-crash-") as ws:
            crashed_runner = LiveControlRunner(
                "crash_after_interrupt",
                ok(contracts.KIND_IMPLEMENT,
                   files_changed=["implementation.py"]),
            )
            path, driver, _unit = self._ready_driver(
                ws,
                crashed_runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.005},
            )
            old_episode = "older-cutoff-episode"
            st.append_event(
                driver.state,
                "implementation_size_steer",
                unit="slice_impl-01",
                episode_id=old_episode,
                lines=3,
                delivered=True,
            )
            st.append_event(
                driver.state,
                "implementation_size_interrupted",
                unit="slice_impl-01",
                episode_id=old_episode,
                lines=7,
                reason="older accepted cutoff",
            )
            driver._save()

            with self.assertRaisesRegex(
                _PromptReached, "crash after interrupt delivery"
            ):
                driver.step()

            interrupted = st.load(path)
            marker = st.current_unit(interrupted)[
                "implementation_stabilization"
            ]["implementation_size"]
            self.assertEqual(
                marker["interrupt_reason"],
                crashed_runner.controls[0].interrupt_reason,
            )
            self.assertNotEqual(marker["episode_id"], old_episode)
            pre_resume_events = [
                event for event in interrupted["events"]
                if event.get("type") in {
                    "implementation_size_steer",
                    "implementation_size_interrupted",
                }
            ]
            self.assertEqual(len(pre_resume_events), 2)
            self.assertEqual(
                {event.get("episode_id") for event in pre_resume_events},
                {old_episode},
            )

            resumed_runner = PersistedEventProbeRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT, files_changed=[]),
                recovery_response=self._cut_response(
                    "post-stop coherent work", "remaining wiring"
                ),
                recovery_lines=8,
            )
            resumed = drv.Driver(path, runner=resumed_runner)

            resumed.step()

            current_at_entry = [
                event
                for event in resumed_runner.events_at_stabilizer_entry
                if event.get("episode_id") == marker["episode_id"]
            ]
            self.assertEqual(len(current_at_entry), 2)
            self.assertEqual(
                {event["type"] for event in current_at_entry},
                {
                    "implementation_size_steer",
                    "implementation_size_interrupted",
                },
            )
            recovered = st.load(path)
            size_events = [
                event for event in recovered["events"]
                if event.get("unit") == "slice_impl-01"
                and event.get("type") in {
                    "implementation_size_steer",
                    "implementation_size_interrupted",
                }
            ]
            self.assertEqual(len(size_events), 4)
            self.assertEqual(
                len([event for event in size_events
                     if event.get("episode_id") == old_episode]),
                2,
            )
            current_events = [
                event for event in size_events
                if event.get("episode_id") == marker["episode_id"]
            ]
            self.assertEqual(len(current_events), 2)
            by_type = {event["type"]: event for event in current_events}
            self.assertTrue(
                by_type["implementation_size_interrupted"][
                    "token_usage_partial"
                ]
            )
            self.assertEqual(
                by_type["implementation_size_interrupted"]["reason"],
                marker["interrupt_reason"],
            )
            self.assertEqual(resumed_runner.controls, [None])

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

    def test_brainstorming_continuation_uses_durable_stabilizer_after_crash(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="orch-size-brain-stable-") \
                as ws:
            crashed_runner = LiveControlRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT, files_changed=[]),
                recovery_lines=8,
                recovery_script=[_PromptReached("continuation crash")],
            )
            path, driver, unit = self._ready_driver(
                ws,
                crashed_runner,
                {"soft_lines": 2, "hard_lines": 6,
                 "poll_interval_s": 0.005},
            )
            base_tree = gitops.snapshot_index_tree(ws)
            handoff = self._brainstorming_handoff()
            self._attach_brainstorming_wait(unit, base_tree, handoff)
            origin_pre = unit["brainstorming_wait"]["origin"]["pre_snapshot"]
            origin_pre["implementation_stabilized"] = False
            durable_size = {
                "soft_lines": 2,
                "hard_lines": 6,
                "steer_delivered": True,
                "steer_lines": 3,
                "interrupt_lines": 8,
                "last_lines": 8,
            }
            unit["implementation_stabilization"] = {
                "implementation_size": durable_size,
            }
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
                with self.assertRaisesRegex(_PromptReached, "continuation"):
                    driver._do_brainstorming_wait()

            self.assertEqual(
                crashed_runner.session_calls,
                [("start", "codex", "mock-session-1")],
            )

            persisted = st.load(path)
            persisted_unit = st.current_unit(persisted)
            self.assertIn("brainstorming_wait", persisted_unit)
            self.assertEqual(
                persisted_unit["implementation_stabilization"]
                ["implementation_size"],
                durable_size,
            )

            runner = LiveControlRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT, files_changed=[]),
                recovery_response=self._cut_response(
                    "continued coherent work", "remaining wiring"
                ),
                recovery_lines=8,
            )
            resumed = drv.Driver(path, runner=runner)
            unit = st.current_unit(resumed.state)
            with mock.patch.object(
                brainstorming_milestone,
                "terminal_handoff",
                return_value=handoff,
            ), mock.patch.object(
                brainstorming_milestone,
                "prompt_handoff",
                return_value=handoff,
            ):
                note = resumed._do_brainstorming_wait()

            self.assertIn("origin conversation continued", note)
            self.assertEqual(runner.controls, [None])
            self.assertIn(
                "FORCED CONTROLLED-CUTOFF RECOVERY", runner.calls[0][2]
            )
            self.assertEqual(
                runner.session_calls,
                [("start", "codex", "mock-session-1")],
            )
            self.assertNotIn(
                prompts.IMPLEMENTATION_SIZE_GUIDANCE, runner.calls[0][2]
            )
            resumed_pre = unit["brainstorming_resume"]["pre_snapshot"]
            self.assertTrue(resumed_pre["implementation_stabilized"])
            self.assertEqual(
                resumed_pre["implementation_size"], durable_size
            )

    def test_brainstorming_rethink_from_stabilizer_continues_its_session(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-brain-resume-") \
                as ws:
            runner = LiveControlRunner(
                "normal",
                ok(contracts.KIND_IMPLEMENT, files_changed=[]),
                recovery_response=self._cut_response(
                    "continued stabilizer work", "remaining wiring"
                ),
                recovery_lines=8,
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
            origin_pre = unit["brainstorming_wait"]["origin"]["pre_snapshot"]
            origin_pre["implementation_stabilized"] = True
            durable_size = {
                "soft_lines": 2,
                "hard_lines": 6,
                "steer_delivered": True,
                "steer_lines": 3,
                "interrupt_lines": 8,
                "last_lines": 8,
            }
            unit["implementation_stabilization"] = {
                "implementation_size": durable_size,
            }
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

            self.assertIn("origin conversation continued", note)
            self.assertEqual(
                runner.session_calls,
                [("continue", "codex", "codex-thread-7")],
            )
            self.assertIn(
                "FORCED CONTROLLED-CUTOFF RECOVERY", runner.calls[0][2]
            )
            self.assertEqual(
                unit["brainstorming_resume"]["provider_session_ref"],
                "codex-thread-7",
            )

    def test_brainstorming_soft_steer_cut_keeps_metrics_on_resume(
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
            self.assertNotIn("implementation_cut_authorized", resume_pre)
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

    def test_pending_gate_retires_redoc_wave_without_synthetic_seal(self):
        with tempfile.TemporaryDirectory(prefix="orch-size-wave-gate-") as ws:
            path, driver, _implementation = self._ready_driver(
                ws, runners.MockRunner([])
            )
            skeleton, note = driver.state["units"][:2]
            note_seals = list(note["seals"])
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
            self.assertIsNone(failed["redoc_wave"])
            self.assertEqual(failed["units"][1]["status"], st.U_SEALED)
            self.assertEqual(failed["units"][1]["seals"], note_seals)
            self.assertEqual(
                failed["retired_redoc_docs_pending_gate"]["docs"],
                ["slice_doc-01"],
            )
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
            self.assertEqual(len(wave_closes), 0)
            self.assertNotIn("retired_redoc_docs_pending_gate", recovered)
            skeleton_gates = [
                event for event in recovered["events"]
                if event.get("type") == "gate_commit"
                and event.get("unit") == "skeleton"
            ]
            self.assertEqual(len(skeleton_gates), 2)  # old gate + one retry


if __name__ == "__main__":
    unittest.main()
