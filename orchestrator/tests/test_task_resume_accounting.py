"""A failed lifecycle write cannot discard or repeat a completed direct call."""

import copy
import time
import unittest
from unittest import mock

from orchestrator import registry, runners, task_api
from orchestrator.tests import test_task_recovery as recovery_tests


class TaskResumeAccountingTest(unittest.TestCase):
    setUp = recovery_tests.TaskRecoveryTest.setUp
    directory = recovery_tests.TaskRecoveryTest.directory
    start_server = recovery_tests.TaskRecoveryTest.start_server
    request = recovery_tests.TaskRecoveryTest.request
    order = recovery_tests.TaskRecoveryTest.order
    _config = staticmethod(recovery_tests.TaskRecoveryTest._config)
    _admit = recovery_tests.TaskRecoveryTest._admit
    _host = recovery_tests.TaskRecoveryTest._host
    _wait = recovery_tests.TaskRecoveryTest._wait
    _paused = recovery_tests.TaskRecoveryTest._paused
    _terminal = recovery_tests.TaskRecoveryTest._terminal

    class Worker:
        def __init__(self, fail_first=False):
            self.calls = 0
            self.fail_first = fail_first

        def call(self, *_args, **_kwargs):
            self.calls += 1
            if self.fail_first and self.calls == 1:
                failure = runners.ProviderResponseError(
                    "provider refused completed attempt", token_usage={
                        "input_tokens": 9, "output_tokens": 4,
                    },
                )
                failure.duration_s = 0.375
                failure.cost_payloads = [{"total_cost_usd": 0.07}]
                raise failure
            return runners.RunnerResult(
                "completed physical call %s" % self.calls, 0, 0.375,
                token_usage={"input_tokens": 9, "output_tokens": 4},
                cost_payloads=[{"total_cost_usd": 0.07}],
            )

    def _unpublished_success(self):
        record = self._admit("agent_call")
        runner = self.Worker()
        # A second runner is available so a duplicate would really execute,
        # rather than merely fail because this fixture exhausted its queue.
        host = self._host(runner, runner, runner)
        with mock.patch.object(
            host.store, "record_result_locked",
            side_effect=OSError("injected task-result persistence failure"),
        ):
            host.start(record, self._config)
            paused = self._paused(host, record["id"])
        marker = task_api.read_worker_marker(self.home, record["id"])
        self.assertIs(marker["completed"], True)
        self.assertEqual(marker["result"]["status"], "success")
        self.assertEqual(marker["result"]["cost"]["api_usd"], 0.07)
        self.assertFalse(marker["result"]["cost_partial"])
        self.assertEqual(runner.calls, 1)
        return record, runner, host, paused, marker

    def _assert_retained_once(self, host, record, marker):
        receipts = [
            event for event in host.store.lifecycle(record["id"])["history"]
            if event.get("call_id") == marker["call_id"]
            and "attempt" in event
        ]
        self.assertEqual(len(receipts), 1, receipts)
        self.assertEqual(receipts[0]["attempt"], marker["result"])

    def _assert_accounting(self, actual, expected):
        for field in ("duration_s", "token_usage", "token_usage_partial",
                      "cost", "cost_partial"):
            self.assertEqual(actual[field], expected[field], field)

    def _legacy_completed_marker(self, record):
        # HEAD before Pause/Resume wrote these top-level accounting fields,
        # but no result, status, or native answer, even after a successful call.
        marker = {
            "task_id": record["id"],
            "call_id": "legacy-completed-%s" % record["id"],
            "family": "claude", "model": "claude-fable-5", "effort": "max",
            "started_at": time.time(), "completed": True,
            "duration_s": 0.375,
            "token_usage": runners.normalize_token_usage({
                "input_tokens": 9, "output_tokens": 4,
            }),
            "token_usage_partial": False,
            "cost": {"api_usd": 0.07, "real_usd": 0.0},
            "cost_partial": False,
        }
        task_api._write_worker_marker(self.home, record["id"], marker)
        return marker

    def _assert_legacy_retained_once(self, host, record, marker):
        lifecycle = host.store.lifecycle(record["id"])
        # A control transition can reference this call without charging it.
        # Only events containing an attempt are accounting receipts.
        receipts = [event for event in lifecycle["history"]
                    if event.get("call_id") == marker["call_id"]
                    and "attempt" in event]
        self.assertEqual(len(receipts), 1, receipts)
        attempt = receipts[0]["attempt"]
        self.assertEqual(attempt["status"], "failure")
        self.assertIn("outcome was not retained", attempt["reason"])
        self.assertIsNone(attempt["native_result"])
        self._assert_accounting(attempt, marker)
        self.assertNotIn("completed_result", lifecycle)

    def test_resume_publishes_completed_success_without_repeating_call(self):
        record, runner, host, paused, marker = self._unpublished_success()

        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])

        self.assertEqual(runner.calls, 1)
        self.assertEqual(terminal["result"], marker["result"])
        self._assert_retained_once(host, record, marker)
        with self.assertRaises(task_api.TaskControlConflict):
            host.resume(record["id"], self._config, paused["revision"])
        self.assertEqual(host.store.record(record["id"]), terminal)
        self.assertEqual(runner.calls, 1)

    def test_resume_imports_failed_call_when_initial_attempt_write_failed(self):
        record = self._admit("agent_call")
        runner = self.Worker(fail_first=True)
        host = self._host(runner, runner)
        pause = host.store.pause_locked

        def reject_attempt_write(*args, **kwargs):
            if kwargs.get("attempt") is not None:
                raise OSError("injected attempt-receipt persistence failure")
            return pause(*args, **kwargs)

        with mock.patch.object(
            host.store, "pause_locked", side_effect=reject_attempt_write
        ):
            host.start(record, self._config)
            paused = self._paused(host, record["id"])
        marker = copy.deepcopy(task_api.read_worker_marker(self.home, record["id"]))
        self.assertIs(marker["completed"], True)
        self.assertEqual(marker["result"]["status"], "failure")

        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])

        self.assertEqual(runner.calls, 2)
        self.assertEqual(terminal["result"]["status"], "success")
        self.assertEqual(terminal["result"]["native_result"], "completed physical call 2")
        self.assertEqual(terminal["result"]["duration_s"], 0.75)
        self.assertEqual(terminal["result"]["token_usage"]["input_tokens"], 18)
        self.assertEqual(terminal["result"]["token_usage"]["output_tokens"], 8)
        self.assertAlmostEqual(terminal["result"]["cost"]["api_usd"], 0.14)
        self.assertFalse(terminal["result"]["cost_partial"])
        self._assert_retained_once(host, record, marker)

    def test_failed_resume_start_cannot_duplicate_import_on_next_resume(self):
        record, runner, host, paused, marker = self._unpublished_success()

        with mock.patch.object(
            host, "start", side_effect=OSError("injected launch failure")
        ):
            with self.assertRaisesRegex(OSError, "injected launch failure"):
                host.resume(record["id"], self._config, paused["revision"])
        paused_again = self._paused(host, record["id"])
        self.assertEqual(runner.calls, 1)
        host.resume(record["id"], self._config, paused_again["revision"])
        terminal = self._terminal(host, record["id"])

        self.assertEqual(runner.calls, 1)
        self.assertEqual(terminal["result"], marker["result"])
        self._assert_retained_once(host, record, marker)

    def test_cancel_after_second_publication_failure_charges_one_physical_call(self):
        record, runner, host, paused, marker = self._unpublished_success()

        with mock.patch.object(
            host.store, "record_result_locked",
            side_effect=OSError("injected second publication failure"),
        ):
            host.resume(record["id"], self._config, paused["revision"])
            paused_again = self._paused(host, record["id"])
        self.assertTrue(host.stop(record["id"], "cancel after inspecting retained result"))
        terminal = self._terminal(host, record["id"])

        self.assertEqual(runner.calls, 1)
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], "cancel after inspecting retained result")
        self._assert_accounting(terminal["result"], marker["result"])
        self._assert_retained_once(host, record, marker)
        with self.assertRaises(task_api.TaskControlConflict):
            host.resume(record["id"], self._config, paused_again["revision"])

    def test_adopt_legacy_marker_keeps_charge_without_inventing_success(self):
        record = self._admit("agent_call")
        marker = self._legacy_completed_marker(record)
        host = self._host()

        host.adopt_open_tasks(lambda _record: self._config)
        paused = self._paused(host, record["id"])
        host.adopt_open_tasks(lambda _record: self._config)

        self.assertEqual(host.store.lifecycle(record["id"]), paused)
        self.assertIsNone(host.store.record(record["id"])["result"])
        self._assert_accounting(paused["accounting"], marker)
        self._assert_legacy_retained_once(host, record, marker)
        self.assertEqual(host.test_pending_runners, [])

    def test_resume_legacy_marker_charges_old_and_new_call_once(self):
        record = self._admit("agent_call")
        marker = self._legacy_completed_marker(record)
        runner = self.Worker()
        host = self._host(runner)
        host.pause(record["id"], "review old completed call before retrying")
        paused = self._paused(host, record["id"])

        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])
        host.adopt_open_tasks(lambda _record: self._config)

        self.assertEqual(runner.calls, 1)
        self.assertEqual(terminal["result"]["status"], "success")
        self.assertEqual(terminal["result"]["native_result"], "completed physical call 1")
        self.assertEqual(terminal["result"]["duration_s"], 0.75)
        self.assertEqual(terminal["result"]["token_usage"]["input_tokens"], 18)
        self.assertEqual(terminal["result"]["token_usage"]["output_tokens"], 8)
        self.assertAlmostEqual(terminal["result"]["cost"]["api_usd"], 0.14)
        self.assertFalse(terminal["result"]["cost_partial"])
        self._assert_legacy_retained_once(host, record, marker)
        with self.assertRaises(task_api.TaskControlConflict):
            host.resume(record["id"], self._config, paused["revision"])
        self.assertEqual(host.store.record(record["id"]), terminal)

    def test_legacy_adopt_failed_resume_adopt_cancel_deduplicates_call_id(self):
        record = self._admit("agent_call")
        marker = self._legacy_completed_marker(record)
        host = self._host()
        host.adopt_open_tasks(lambda _record: self._config)
        paused = self._paused(host, record["id"])

        with mock.patch.object(
            host, "start", side_effect=OSError("injected launch failure")
        ):
            with self.assertRaisesRegex(OSError, "injected launch failure"):
                host.resume(record["id"], self._config, paused["revision"])
        self._paused(host, record["id"])
        host.adopt_open_tasks(lambda _record: self._config)
        self.assertTrue(host.stop(record["id"], "cancel retained legacy call"))
        terminal = self._terminal(host, record["id"])
        host.adopt_open_tasks(lambda _record: self._config)

        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], "cancel retained legacy call")
        self._assert_accounting(terminal["result"], marker)
        self._assert_legacy_retained_once(host, record, marker)
        self.assertEqual(host.store.record(record["id"]), terminal)
        self.assertEqual(host.test_pending_runners, [])

    def test_cancel_legacy_marker_without_prior_adoption_keeps_accounting(self):
        record = self._admit("agent_call")
        marker = self._legacy_completed_marker(record)
        host = self._host()

        self.assertTrue(host.stop(record["id"], "cancel without adopting first"))
        terminal = self._terminal(host, record["id"])

        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], "cancel without adopting first")
        self._assert_accounting(terminal["result"], marker)
        self._assert_legacy_retained_once(host, record, marker)
        self.assertEqual(host.test_pending_runners, [])

    def test_malformed_new_result_is_not_reinterpreted_as_legacy(self):
        record = self._admit("agent_call")
        marker = self._legacy_completed_marker(record)
        marker["result"] = None
        task_api._write_worker_marker(self.home, record["id"], marker)
        host = self._host()
        before = host.store.lifecycle(record["id"])

        with registry.locked(self.home):
            self.assertFalse(host._recover_worker_attempt_locked(record["id"]))

        self.assertEqual(host.store.lifecycle(record["id"]), before)


if __name__ == "__main__":
    unittest.main()
