"""Cancel settles durable evidence without requiring an available workspace."""

import copy
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from orchestrator import brainstorming, brainstorming_lifecycle, brainstorming_milestone
from orchestrator import brainstorming_coordination as coordination
from orchestrator import contracts, gitops, registry, runners, task_api, tasks
from orchestrator import driver as drv
from orchestrator import state as st
from orchestrator.task_execution import ExecutionBusy, TaskExecutionLease
from orchestrator.tests import test_reviewed_task_api as reviewed_tests
from orchestrator.tests import test_task_recovery as recovery_tests


class TaskCancelRecoveryTest(unittest.TestCase):
    setUp = recovery_tests.TaskRecoveryTest.setUp
    directory = recovery_tests.TaskRecoveryTest.directory
    start_server = recovery_tests.TaskRecoveryTest.start_server
    request = recovery_tests.TaskRecoveryTest.request
    order = recovery_tests.TaskRecoveryTest.order
    _config = staticmethod(recovery_tests.TaskRecoveryTest._config)
    _script = staticmethod(recovery_tests.TaskRecoveryTest._script)
    _admit = recovery_tests.TaskRecoveryTest._admit
    _host = recovery_tests.TaskRecoveryTest._host
    _wait = recovery_tests.TaskRecoveryTest._wait
    _paused = recovery_tests.TaskRecoveryTest._paused
    _terminal = recovery_tests.TaskRecoveryTest._terminal
    _state = recovery_tests.TaskRecoveryTest._state
    _unit = staticmethod(recovery_tests.TaskRecoveryTest._unit)
    _fail_call = staticmethod(recovery_tests.TaskRecoveryTest._fail_call)
    _failed_review_script = recovery_tests.TaskRecoveryTest._failed_review_script
    _sleeper = recovery_tests.TaskRecoveryTest._sleeper
    _manual_brainstorming = recovery_tests.TaskRecoveryTest._manual_brainstorming
    _waiting_manual_brainstorming = recovery_tests.TaskRecoveryTest._waiting_manual_brainstorming
    _waiting_rethink_session = recovery_tests.TaskRecoveryTest._waiting_rethink_session
    _record_brainstorming_activity = reviewed_tests.ReviewedTaskOrderingTest._record_brainstorming_activity

    @staticmethod
    def _completed_result(status="success"):
        result = {
            "status": status, "duration_s": 0.375,
            "token_usage": runners.normalize_token_usage({
                "input_tokens": 9, "output_tokens": 4,
            }),
            "token_usage_partial": False,
            "cost": {"api_usd": 0.07, "real_usd": 0.02},
            "cost_partial": False,
            "native_result": "completed evidence before the host died",
        }
        if status == "failure":
            result["reason"] = "completed provider failure"
        return result

    def _completed_marker(self, record, result):
        task_api._write_worker_marker(self.home, record["id"], {
            "task_id": record["id"], "call_id": "completed-before-task-write",
            "family": "codex", "started_at": time.time(), "completed": True,
            "result": result,
        })

    def _unmount_workspace(self):
        retained = self.primary + "-temporarily-unmounted"
        os.rename(self.primary, retained)
        self.addCleanup(lambda: os.rename(retained, self.primary))

    def _assert_accounting(self, actual, expected):
        for name in ("duration_s", "token_usage", "token_usage_partial",
                     "cost", "cost_partial"):
            self.assertEqual(actual[name], expected[name], name)

    def _surviving_lease_worker(self, record):
        """Leave the actual flock held only by a child's inherited descriptor."""
        lease = TaskExecutionLease(os.path.join(
            self.home, "task-runtime", record["id"]
        )).acquire()
        self.addCleanup(lease.close)
        kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "start_new_session": True,
        }
        lease.prepare_spawn(kwargs)
        worker = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1)"],
            **kwargs,
        )

        def cleanup():
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=5)

        self.addCleanup(cleanup)
        lease.record_worker(worker.pid)
        lease.close()
        # This must be real lock contention, not only a simulated journal or
        # the host's presentation flag. The original owner no longer holds FD.
        with self.assertRaisesRegex(ExecutionBusy, "still owned"):
            with TaskExecutionLease(lease.task_dir):
                pass
        return worker

    def test_restart_durable_cancel_waits_for_surviving_lease_then_settles_once(self):
        record = self._admit("agent_call")
        expected = self._completed_result()
        self._completed_marker(record, expected)
        worker = self._surviving_lease_worker(record)
        host = self._host()
        with registry.locked(self.home):
            host.store.record_stop_locked(record["id"], "cancel before owner restart")

        with mock.patch.object(
            host, "runner_factory", side_effect=AssertionError("Cancel cannot call provider")
        ) as provider:
            host.adopt_open_tasks(lambda _record: self._config)
            self._wait(
                lambda: host.is_active(record["id"])
                and host.store.lifecycle(record["id"])["status"] == "pausing",
                "durable Cancel did not retain active pending settlement",
            )
            self.assertIsNone(host.store.record(record["id"])["result"])
            self.assertIsNone(worker.poll())
            self.assertTrue(host.owns_workspace(self.primary))

            worker.communicate(input=b"release", timeout=5)
            # No second Stop, Resume, or adoption is allowed to wake settlement.
            terminal = self._terminal(host, record["id"])
            provider.assert_not_called()

        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], "cancel before owner restart")
        self._assert_accounting(terminal["result"], expected)
        receipts = [event for event in host.store.lifecycle(record["id"])["history"]
                    if event.get("call_id") == "completed-before-task-write"]
        self.assertEqual(len(receipts), 1)
        self.assertFalse(host.owns_workspace(self.primary))

    def test_restart_reviewed_cancel_waits_for_surviving_lease_then_settles_once(self):
        record = self._admit("reviewed_task")
        path = task_api.ensure_reviewed_state(self.home, record, self._config())
        subject = drv.Driver(path, runner=runners.MockRunner([]), model_profiles_home=self.home)
        expected = self._completed_result()
        self.assertTrue(subject._write_busy({
            "call_id": "reviewed-completed-before-owner-restart",
            "family": "codex", "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "completed": True, "unit": subject.state["reviewed_task"]["unit"],
            "label": "reviewed-completed-before-owner-restart",
            **{field: copy.deepcopy(expected[field]) for field in (
                "duration_s", "token_usage", "token_usage_partial", "cost", "cost_partial",
            )},
        }))
        worker = self._surviving_lease_worker(record)
        host = self._host()
        with registry.locked(self.home):
            host.store.record_stop_locked(record["id"], "cancel reviewed before owner restart")

        with mock.patch.object(
            host, "runner_factory", side_effect=AssertionError("Cancel cannot call provider")
        ) as provider:
            host.adopt_open_tasks(lambda _record: self._config)
            self._wait(
                lambda: host.is_active(record["id"])
                and host.store.lifecycle(record["id"])["status"] == "pausing",
                "reviewed Cancel did not retain active pending settlement",
            )
            self.assertIsNone(host.store.record(record["id"])["result"])
            self.assertIsNone(worker.poll())
            self.assertTrue(host.owns_workspace(self.primary))

            worker.communicate(input=b"release", timeout=5)
            # No second Stop, Resume, or adoption is allowed to wake settlement.
            terminal = self._terminal(host, record["id"])
            provider.assert_not_called()

        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], "cancel reviewed before owner restart")
        self._assert_accounting(terminal["result"], expected)
        state = self._state(record["id"])
        self.assertEqual(len([event for event in state["events"]
                              if event["type"] == "worker_interrupted"]), 1)
        self.assertFalse(host.owns_workspace(self.primary))

    def test_restart_cancel_imports_completed_worker_accounting_once(self):
        for status in ("success", "failure"):
            with self.subTest(status=status):
                record = self._admit("agent_call")
                result = self._completed_result(status)
                self._completed_marker(record, result)
                host = self._host()
                with registry.locked(self.home):
                    host.store.record_stop_locked(record["id"], "cancel before host crash")
                host.adopt_open_tasks(lambda _record: self._config)
                terminal = self._terminal(host, record["id"])
                host.adopt_open_tasks(lambda _record: self._config)
                self.assertEqual(terminal, host.store.record(record["id"]))
                self.assertEqual(terminal["result"]["status"], "failure")
                self.assertEqual(terminal["result"]["reason"], "cancel before host crash")
                self._assert_accounting(terminal["result"], result)
                attempts = [event for event in host.store.lifecycle(record["id"])["history"]
                            if "attempt" in event]
                self.assertEqual(len(attempts), 1)
                self.assertEqual(host.test_pending_runners, [])

    def test_cancel_imports_marker_once_without_changing_existing_pause(self):
        record = self._admit("agent_call")
        result = self._completed_result("failure")
        self._completed_marker(record, result)
        host = self._host()
        host.pause(record["id"], "inspect before cancelling")
        paused = host.store.lifecycle(record["id"])
        with registry.locked(self.home):
            self.assertTrue(host._recover_worker_attempt_locked(record["id"]))
            self.assertFalse(host._recover_worker_attempt_locked(record["id"]))
        imported = host.store.lifecycle(record["id"])
        for field in ("status", "revision", "reason", "source"):
            self.assertEqual(imported[field], paused[field])
        self.assertTrue(host.stop(record["id"], "cancel with retained accounting"))
        terminal = self._terminal(host, record["id"])
        self._assert_accounting(terminal["result"], result)

    def test_cancel_unstarted_tasks_without_workspace_or_provider(self):
        records = [self._admit(executor) for executor in (
            "agent_call", "reviewed_task", "deep_task"
        )]
        host = self._host()
        for record in records:
            host.pause(record["id"], "not started")
        self._unmount_workspace()
        with mock.patch.object(host, "runner_factory") as provider:
            for record in records:
                self.assertTrue(host.stop(record["id"], "workspace is gone"))
                terminal = self._terminal(host, record["id"])
                self.assertEqual(terminal["result"]["status"], "failure")
                self.assertEqual(terminal["result"]["reason"], "workspace is gone")
                with host._lease(record["id"]):
                    pass
            provider.assert_not_called()
        self.assertFalse(host.owns_workspace(self.primary))
        self.assertFalse(os.path.exists(self.primary))

    def test_cancel_failed_review_preserves_accounting_without_workspace(self):
        record = self._admit()
        script, _remaining = self._failed_review_script(contracts.KIND_DRAFT_SLICE_NOTE)
        host = self._host(runners.MockRunner(script))
        host.start(record, self._config)
        self._paused(host, record["id"])
        state = self._state(record["id"])
        expected = st.reviewed_work_accounting(state, self._unit(state))
        self._unmount_workspace()
        with mock.patch.object(host, "runner_factory") as provider, mock.patch.object(
            gitops, "ensure_repo", side_effect=AssertionError("Cancel must not reopen Git")
        ), mock.patch.object(
            gitops, "restore_clean", side_effect=AssertionError("Cancel must not restore Git")
        ):
            self.assertTrue(host.stop(record["id"], "cancel missing work area"))
            terminal = self._terminal(host, record["id"])
            provider.assert_not_called()
        self._assert_accounting(terminal["result"], expected)
        self.assertFalse(os.path.exists(self.primary))
        self.assertFalse(host.owns_workspace(self.primary))

    def test_restart_settles_durable_cancel_without_workspace(self):
        records = [self._admit(executor) for executor in (
            "agent_call", "reviewed_task", "deep_task"
        )]
        first = self._host()
        expected = self._completed_result()
        self._completed_marker(records[0], expected)
        task_api.ensure_reviewed_state(self.home, records[1], self._config())
        with registry.locked(self.home):
            for record in records:
                first.store.record_stop_locked(record["id"], "cancel before restart")
        self._unmount_workspace()
        restarted = self._host()
        with mock.patch.object(restarted, "runner_factory") as provider:
            restarted.adopt_open_tasks(lambda _record: self._config)
            terminal = [self._terminal(restarted, record["id"]) for record in records]
            restarted.adopt_open_tasks(lambda _record: self._config)
            provider.assert_not_called()
        self._assert_accounting(terminal[0]["result"], expected)
        for record in terminal:
            self.assertEqual(record["result"]["status"], "failure")
            self.assertEqual(record["result"]["reason"], "cancel before restart")
            self.assertEqual(record, restarted.store.record(record["id"]))
        self.assertFalse(os.path.exists(self.primary))
        self.assertFalse(restarted.owns_workspace(self.primary))

    def test_cancel_deep_family_without_workspace_retains_completed_child(self):
        record = self._admit("deep_task")
        failed_script, _remaining = self._failed_review_script(contracts.KIND_IMPLEMENT)
        host = self._host(
            runners.MockRunner(self._script(contracts.KIND_DRAFT_SLICE_NOTE)),
            runners.MockRunner(failed_script),
        )
        host.start(record, self._config)
        self._paused(host, record["id"])
        documentation = host.store.related(record["id"], "documentation", None)
        implementation = host.store.related(record["id"], "implementation", "a")
        state = self._state(implementation["id"])
        expected = tasks.deep_task_result("failure", [
            documentation["result"], {
                "status": "failure", "reason": "cancel family", "native_result": None,
                **st.reviewed_work_accounting(state, self._unit(state)),
            },
        ], reason="cancel family")
        self._unmount_workspace()
        with mock.patch.object(host, "runner_factory") as provider:
            self.assertTrue(host.stop(implementation["id"], "cancel family"))
            terminal = self._terminal(host, record["id"])
            provider.assert_not_called()
        self.assertEqual(host.store.record(documentation["id"]), documentation)
        self.assertEqual(host.store.record(implementation["id"])["result"]["status"], "failure")
        self._assert_accounting(terminal["result"], expected)
        self.assertEqual(len(host.store.records()), 3)
        self.assertFalse(os.path.exists(self.primary))
        self.assertFalse(host.owns_workspace(self.primary))

    def test_cancel_review_settles_owned_discussion_without_workspace(self):
        session_id, _waiting, attach = self._waiting_rethink_session(
            self.primary, "cancel-missing-workspace.md"
        )
        record = self._admit("reviewed_task", "implement")
        path = task_api.ensure_reviewed_state(self.home, record, self._config())
        subject = drv.Driver(path, runner=runners.MockRunner([
            reviewed_tests.ReviewedTaskOrderingTest._rethink_step(contracts.KIND_IMPLEMENT)
        ]), model_profiles_home=self.home)
        with mock.patch.object(brainstorming_milestone, "create_session", side_effect=attach), \
                mock.patch.object(brainstorming_milestone, "terminal_handoff", return_value=None):
            reviewed_tests.ReviewedTaskOrderingTest._standalone_step(subject)
        usage, cost = self._record_brainstorming_activity(session_id)
        host = self._host()
        host.pause(record["id"], "inspect retained discussion")
        self._unmount_workspace()
        with mock.patch.object(host, "runner_factory") as provider:
            self.assertTrue(host.stop(record["id"], "cancel discussion owner"))
            terminal = self._terminal(host, record["id"])
            provider.assert_not_called()
        projection = brainstorming_lifecycle.inspect_session(
            self.home, session_id, lambda _record: None
        )
        self.assertEqual(projection["state"]["status"], "failure")
        self.assertEqual(projection["process"], "stopped")
        self.assertEqual(terminal["result"]["cost"], cost)
        self.assertEqual(terminal["result"]["token_usage"], usage)
        self.assertEqual(len([event for event in self._state(record["id"])["events"]
                              if event["type"] == "brainstorming_work_recorded"]), 1)
        self.assertFalse(os.path.exists(self.primary))

    def test_cancel_review_imports_stale_marker_without_git_recovery(self):
        record = self._admit()
        path = task_api.ensure_reviewed_state(self.home, record, self._config())
        subject = drv.Driver(path, runner=runners.MockRunner([]), model_profiles_home=self.home)
        result = self._completed_result()
        marker = {"call_id": "completed-before-cancel", "family": "codex",
                  "kind": contracts.KIND_DRAFT_SLICE_NOTE, "completed": True,
                  "unit": subject.state["reviewed_task"]["unit"],
                  "label": "completed-before-cancel",
                  **{name: copy.deepcopy(result[name]) for name in (
                      "duration_s", "token_usage", "token_usage_partial", "cost", "cost_partial",
                  )}}
        self.assertTrue(subject._write_busy(marker))
        host = self._host()
        host.pause(record["id"], "cancel completed reviewed call")
        self._unmount_workspace()
        with mock.patch.object(host, "runner_factory") as provider, mock.patch.object(
            gitops, "worktree_diff", side_effect=AssertionError("Cancel must not inspect Git")
        ):
            self.assertTrue(host.stop(record["id"], "cancel retained call"))
            terminal = self._terminal(host, record["id"])
            provider.assert_not_called()
        self._assert_accounting(terminal["result"], result)
        repeated = drv.Driver(path, cancellation_only=True)
        self.assertEqual(len([event for event in repeated.state["events"]
                              if event["type"] == "worker_interrupted"]), 1)
        self.assertFalse(os.path.exists(self.primary))

    def _deep_owner_with_discardable_discussion(self):
        session_id, waiting, bind_caller = self._waiting_rethink_session(
            self.primary, "discarded-deep-cancel.md"
        )
        owner = self._admit("deep_task")
        host = self._host()
        child, stop_reason = host._admit_deep_child(
            owner["id"], "documentation", None,
            host._deep_child_order(owner), self.primary,
        )
        self.assertIsNone(stop_reason)
        path = task_api.ensure_reviewed_state(self.home, child, self._config())
        with st.exclusive_mutation(path):
            state = st.load(path)
            unit = self._unit(state)
            unit_key = st.unit_key(unit)
            bind_caller(state, self._config(), unit_key, {}, [], {})
            unit["brainstorming_wait"] = {
                "session_id": session_id,
                "origin": {"kind": contracts.KIND_DRAFT_SLICE_NOTE},
            }
            st.append_event(
                state, "brainstorming_wait_started", unit=unit_key,
                kind=contracts.KIND_DRAFT_SLICE_NOTE, session_id=session_id,
            )
            st.save(path, state)
        usage, cost = self._record_brainstorming_activity(session_id)
        return host, owner, child, session_id, waiting, path, usage, cost

    def test_deep_cancel_detaches_discarded_quiet_child_and_preserves_accounting(self):
        host, owner, child, session_id, _waiting, _path, usage, cost = (
            self._deep_owner_with_discardable_discussion()
        )
        brainstorming_lifecycle.delete_session(
            self.home, session_id, lambda _record: None, purge=False,
        )
        with mock.patch.object(host, "runner_factory") as provider:
            self.assertTrue(host.stop(owner["id"], "cancel discarded discussion owner"))
            terminal = self._terminal(host, owner["id"])
            provider.assert_not_called()
        child_result = host.store.record(child["id"])["result"]
        self.assertEqual(child_result["status"], "failure")
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["token_usage"], usage)
        self.assertEqual(terminal["result"]["cost"], cost)
        state = self._state(child["id"])
        self.assertNotIn("brainstorming_wait", self._unit(state))
        for event_type in ("brainstorming_work_recorded", "brainstorming_missing_detached"):
            self.assertEqual(len([
                event for event in state["events"]
                if event["type"] == event_type and event.get("session_id") == session_id
            ]), 1)
        self.assertFalse(host.owns_workspace(self.primary))

    def test_deep_cancel_does_not_detach_discarded_child_with_unquiet_native_attempt(self):
        host, owner, child, session_id, waiting, path, _usage, _cost = (
            self._deep_owner_with_discardable_discussion()
        )
        sessions = brainstorming.SessionStore(brainstorming_lifecycle.state_directory(self.home))
        sessions.continue_waiting(session_id, waiting.revision)
        snapshot = sessions.read(session_id)
        target = os.path.join(self.primary, "docs", "discarded-deep-cancel.md")
        with coordination._open_target_parent(target) as (_descriptor, _name, parent_identity):
            pass
        attempt = sessions.begin_turn_attempt(session_id, {
            "token": "discarded-child-unquiet-attempt",
            "participant_id": "lead",
            "completed_turn_count": len(snapshot.state["completed_turns"]),
            "target_revision": snapshot.state["accepted_target_revision"],
            "quiescent": False, "target_parent": parent_identity,
        })
        # Native Discard currently checks the coordinator, not this retained
        # worker attempt. A missing registry row must not erase that evidence.
        brainstorming_lifecycle.delete_session(
            self.home, session_id, lambda _record: None, purge=False,
        )
        with registry.locked(self.home):
            for record in (owner, child):
                host.store.record_stop_locked(record["id"], "cancel after discard")
        subject = drv.Driver(path, cancellation_only=True)
        unit = self._unit(subject.state)
        self.assertFalse(host._settle_stopped_reviewed(
            child["id"], subject, unit, "cancel after discard",
        ))
        self.assertIsNone(host.store.record(child["id"])["result"])
        self.assertIsNone(host.store.record(owner["id"])["result"])
        self.assertEqual(unit["brainstorming_wait"]["session_id"], session_id)
        self.assertFalse(any(
            event["type"] == "brainstorming_missing_detached"
            for event in subject.state["events"]
        ))
        self.assertEqual(sessions.read_turn_attempt(session_id), attempt)
        sessions.mark_turn_attempt_quiescent(session_id, attempt["token"])
        self.assertTrue(host._settle_stopped_reviewed(
            child["id"], subject, unit, "cancel after discard",
        ))
        self.assertNotIn("brainstorming_wait", unit)


if __name__ == "__main__":
    unittest.main()
