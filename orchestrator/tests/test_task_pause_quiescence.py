"""Owned independent discussions must become quiet before a task is paused."""

import copy
from contextlib import contextmanager
import os
import threading
import unittest
from unittest import mock

from orchestrator import brainstorming, brainstorming_lifecycle
from orchestrator import brainstorming_milestone, brainstorming_tasks
from orchestrator import contracts, registry, runners, service, task_api
from orchestrator import brainstorming_coordination as coordination
from orchestrator import driver as drv
from orchestrator.tests import test_reviewed_task_api as reviewed_tests
from orchestrator.tests import test_task_recovery as recovery_tests


class TaskPauseQuiescenceTest(unittest.TestCase):
    # Reuse the disposable real-Git/HTTP fixtures, not their test methods.
    setUp = recovery_tests.TaskRecoveryTest.setUp
    directory = recovery_tests.TaskRecoveryTest.directory
    start_server = recovery_tests.TaskRecoveryTest.start_server
    request = recovery_tests.TaskRecoveryTest.request
    order = recovery_tests.TaskRecoveryTest.order
    _git = staticmethod(recovery_tests.TaskRecoveryTest._git)
    _config = staticmethod(recovery_tests.TaskRecoveryTest._config)
    _sleeper = recovery_tests.TaskRecoveryTest._sleeper
    _manual_brainstorming = recovery_tests.TaskRecoveryTest._manual_brainstorming
    _waiting_manual_brainstorming = recovery_tests.TaskRecoveryTest._waiting_manual_brainstorming
    _waiting_rethink_session = recovery_tests.TaskRecoveryTest._waiting_rethink_session
    _waiting_producer_session = reviewed_tests.ReviewedTaskOrderingTest._waiting_producer_session
    _record_brainstorming_activity = reviewed_tests.ReviewedTaskOrderingTest._record_brainstorming_activity
    _admit = recovery_tests.TaskRecoveryTest._admit
    _wait = recovery_tests.TaskRecoveryTest._wait
    _paused = recovery_tests.TaskRecoveryTest._paused
    _terminal = recovery_tests.TaskRecoveryTest._terminal
    _state = recovery_tests.TaskRecoveryTest._state
    _unit = staticmethod(recovery_tests.TaskRecoveryTest._unit)

    def _host(self):
        runner = runners.MockRunner([])
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda *_args: runner,
            poll_interval=0.001,
        )
        host.test_runner = runner

        def finish_test_controls():
            with host._lock:
                active = list(host._active)
            for task_id in active:
                if host.is_active(task_id):
                    host.stop(task_id, "test cleanup cancellation")
            self._wait(lambda: not any(host.is_active(task_id) for task_id in active),
                       "test control threads did not stop")

        self.addCleanup(finish_test_controls)
        return host

    def _owned_session(self, executor="reviewed_task", unattached=False):
        session_id, waiting, attach = self._waiting_rethink_session(
            self.primary, "quiescence-%s.md" % executor
        )
        owner = self._admit(executor, "implement")
        host = self._host()
        child = owner
        if executor == "deep_task":
            child, stopped = host._admit_deep_child(
                owner["id"], "documentation", None,
                host._deep_child_order(owner), self.primary,
            )
            self.assertIsNone(stopped)
        path = task_api.ensure_reviewed_state(self.home, child, self._config())
        subject = drv.Driver(
            path,
            runner=runners.MockRunner([
                reviewed_tests.ReviewedTaskOrderingTest._rethink_step(
                    child["order"]["configuration"]["task_kind"]
                )
            ]),
            model_profiles_home=self.home,
        )
        if unattached:
            # Creation durably records its caller before the reviewed state
            # saves the attachment/event. Do not rewrite append-only history.
            attach(subject.state, self._config(),
                   subject.state["reviewed_task"]["unit"], {}, [], {})
        else:
            with mock.patch.object(
                brainstorming_milestone, "create_session", side_effect=attach
            ), mock.patch.object(
                brainstorming_milestone, "terminal_handoff", return_value=None
            ):
                reviewed_tests.ReviewedTaskOrderingTest._standalone_step(subject)
        process = self._start_waiting_session(session_id, waiting)
        return owner, child, session_id, process

    def _start_waiting_session(self, session_id, waiting):
        sessions = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        )
        sessions.continue_waiting(session_id, waiting.revision)
        process = self._sleeper()
        with mock.patch.object(
            brainstorming_lifecycle, "_launch_lifecycle_process",
            return_value=brainstorming_lifecycle.GatedLaunch(
                process, lambda: None, process.terminate
            ),
        ):
            started = brainstorming_lifecycle.start_session(
                self.home, session_id, lambda _record: None
            )
        self.assertEqual(started["process"], "running")
        self.assertIsNone(process.poll())
        return process

    def _owned_unattached_producer(self):
        session_id, waiting, create = self._waiting_producer_session(
            self.primary, "unattached-producer.md"
        )
        order = self.order("reviewed_task", work_area={
            "workspace_path": self.primary, "primary": self.primary,
            "additional": [],
        })
        order["configuration"] = {
            "task_kind": contracts.KIND_IMPLEMENT,
            "producer": {"task_executor": "brainstorming"},
        }
        with mock.patch.object(service, "_direct_task_config", return_value=self._config()):
            status, body = self.request("POST", "/api/tasks", order)
        self.assertEqual(status, 201, body)
        owner = body["task"]
        path = task_api.ensure_reviewed_state(self.home, owner, self._config())
        subject = drv.Driver(path, runner=runners.MockRunner([]),
                             model_profiles_home=self.home)
        unit = self._unit(subject.state)
        inner, _planned = subject._admit_brainstorming_production(
            unit, contracts.KIND_IMPLEMENT
        )
        create(subject.state, inner["id"], subject.config, self.home)
        self.assertEqual(
            brainstorming_lifecycle._record_by_id(self.home, session_id)["caller"],
            brainstorming_tasks._task_caller(inner, inner["id"]),
        )
        self.assertNotIn("brainstorming_wait", self._unit(self._state(owner["id"])))
        return owner, session_id, self._start_waiting_session(session_id, waiting)

    def _assert_session_stopped(self, session_id, process):
        projection = brainstorming_lifecycle.inspect_session(
            self.home, session_id, lambda _record: None
        )
        self.assertEqual(projection["process"], "stopped")
        self.assertIsNotNone(process.poll())
        return projection

    @contextmanager
    def _adoption_controls_only(self, host):
        with mock.patch.object(
            drv, "Driver", side_effect=AssertionError(
                "restart pause must not construct a Driver or restore Git"
            )
        ) as driver, mock.patch.object(
            host, "runner_factory", side_effect=AssertionError(
                "restart pause must not dispatch a provider"
            )
        ) as runner:
            yield
        driver.assert_not_called()
        runner.assert_not_called()

    def _adopt(self, host):
        outcome = host.adopt_open_tasks(lambda _record: self._config)
        self.assertEqual(outcome["closed"], [])
        self.assertEqual(len(outcome["adopted"]), len(set(outcome["adopted"])))
        return outcome

    def test_review_inspection_failure_stops_live_discussion_before_paused(self):
        owner, _child, session_id, process = self._owned_session()
        host = self._host()
        before = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        ).read(session_id)
        stop = brainstorming_lifecycle.stop_session
        observed = []

        def stop_owned(*args, **kwargs):
            observed.append(host.store.lifecycle(owner["id"])["status"])
            return stop(*args, **kwargs)

        with mock.patch.object(
            brainstorming_milestone, "terminal_handoff",
            side_effect=OSError("terminal handoff inspection failed"),
        ), mock.patch.object(
            brainstorming_lifecycle, "stop_session", side_effect=stop_owned
        ):
            host.start(owner, self._config)
            paused = self._paused(host, owner["id"])
        self.assertTrue(observed, "failure did not stop the owned discussion")
        self.assertEqual(set(observed), {"pausing"})
        self._assert_session_stopped(session_id, process)
        self.assertEqual(paused["source"], "error")
        self.assertIn("inspection failed", paused["reason"])
        self.assertEqual(brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        ).read(session_id), before)
        self.assertEqual(host.test_runner.calls, [])

    def test_failure_with_unsuccessful_discussion_stop_remains_pausing(self):
        owner, _child, session_id, process = self._owned_session()
        host = self._host()
        attempted = threading.Event()

        def cannot_stop(*_args, **_kwargs):
            attempted.set()
            raise brainstorming_lifecycle.PublicLifecycleError(
                409, brainstorming_lifecycle.STOP_INCOMPLETE
            )

        with mock.patch.object(
            brainstorming_milestone, "terminal_handoff",
            side_effect=OSError("terminal handoff inspection failed"),
        ), mock.patch.object(
            brainstorming_lifecycle, "stop_session", side_effect=cannot_stop
        ), mock.patch.object(
            threading.Thread, "start", autospec=True,
            side_effect=threading.Thread.start,
        ) as starts:
            host.start(owner, self._config)
            self.assertTrue(attempted.wait(5), "error path skipped discussion Stop")
            lifecycle = host.lifecycle(owner["id"])
            self.assertEqual(lifecycle["status"], "pausing")
            self.assertFalse(lifecycle["can_resume"])
            self.assertTrue(host.is_active(owner["id"]))
            self.assertIsNone(process.poll())
            self.assertIsNone(host.store.record(owner["id"])["result"])
            with self.assertRaises(task_api.TaskControlConflict):
                host.resume(owner["id"], self._config, lifecycle["revision"])
            stable = host.store.lifecycle(owner["id"])
            threads_started = starts.call_count
            with self._adoption_controls_only(host):
                self._adopt(host)
            self.assertEqual(host.store.lifecycle(owner["id"]), stable)
            self.assertEqual(starts.call_count, threads_started)
        self._paused(host, owner["id"])
        self._assert_session_stopped(session_id, process)
        self.assertEqual(host.test_runner.calls, [])

    def _restart_quiescence(self, executor, already_paused=False, unattached=False):
        owner, child, session_id, process = self._owned_session(
            executor, unattached=unattached
        )
        host = self._host()
        family_ids = list(dict.fromkeys([owner["id"], child["id"]]))
        if already_paused:
            with registry.locked(self.home):
                for task_id in family_ids:
                    host.store.pause_locked(task_id, "legacy incomplete pause")
        before = copy.deepcopy(self._state(child["id"]))
        stop = brainstorming_lifecycle.stop_session
        observations = []

        def stop_owned(*args, **kwargs):
            observations.append([
                host.store.lifecycle(task_id)["status"] for task_id in family_ids
            ])
            return stop(*args, **kwargs)

        with mock.patch.object(
            brainstorming_lifecycle, "stop_session", side_effect=stop_owned
        ), self._adoption_controls_only(host):
            self._adopt(host)
            for task_id in family_ids:
                self._paused(host, task_id)
        self.assertTrue(observations, "restart adopted a live discussion as paused")
        for observation in observations:
            self.assertEqual(observation, ["pausing"] * len(family_ids))
        self._assert_session_stopped(session_id, process)
        self.assertEqual(self._state(child["id"]), before)
        stable = {task_id: host.store.lifecycle(task_id) for task_id in family_ids}
        with self._adoption_controls_only(host):
            self._adopt(host)
        self.assertEqual(
            {task_id: host.store.lifecycle(task_id) for task_id in family_ids}, stable
        )

    def test_restart_quiesces_reviewed_discussion_before_marking_paused(self):
        self._restart_quiescence("reviewed_task")

    def test_restart_quiesces_deep_child_discussion_before_pausing_family(self):
        self._restart_quiescence("deep_task")

    def test_restart_repairs_legacy_paused_owner_with_live_discussion(self):
        self._restart_quiescence("reviewed_task", already_paused=True)

    def test_restart_quiesces_session_created_before_reviewed_attachment_save(self):
        self._restart_quiescence("reviewed_task", unattached=True)

    def test_restart_quiesces_producer_session_created_before_attachment_save(self):
        owner, session_id, process = self._owned_unattached_producer()
        host = self._host()
        before = copy.deepcopy(self._state(owner["id"]))
        with self._adoption_controls_only(host):
            self._adopt(host)
            self._paused(host, owner["id"])
        self._assert_session_stopped(session_id, process)
        self.assertEqual(self._state(owner["id"]), before)
        self.assertIsNone(host.store.record(owner["id"])["result"])

    def test_failure_quiesces_producer_session_created_before_attachment_save(self):
        owner, session_id, process = self._owned_unattached_producer()
        host = self._host()
        stop = brainstorming_lifecycle.stop_session
        observations = []

        def stop_owned(*args, **kwargs):
            observations.append(host.store.lifecycle(owner["id"])["status"])
            return stop(*args, **kwargs)

        with mock.patch.object(
            brainstorming_tasks, "start_task",
            side_effect=OSError("producer session inspection failed"),
        ), mock.patch.object(
            brainstorming_lifecycle, "stop_session", side_effect=stop_owned
        ):
            host.start(owner, self._config)
            paused = self._paused(host, owner["id"])
        self.assertTrue(observations)
        self.assertEqual(set(observations), {"pausing"})
        self._assert_session_stopped(session_id, process)
        self.assertEqual(paused["source"], "error")
        self.assertIn("producer session inspection failed", paused["reason"])
        self.assertEqual(host.test_runner.calls, [])

    def test_restart_failed_stop_keeps_entire_deep_family_pausing(self):
        owner, child, session_id, process = self._owned_session("deep_task")
        host = self._host()
        family_ids = (owner["id"], child["id"])
        before = copy.deepcopy(self._state(child["id"]))
        with self._adoption_controls_only(host):
            with mock.patch.object(
                brainstorming_lifecycle, "stop_session",
                side_effect=brainstorming_lifecycle.PublicLifecycleError(
                    409, brainstorming_lifecycle.STOP_INCOMPLETE
                ),
            ) as stop, mock.patch.object(
                threading.Thread, "start", autospec=True,
                side_effect=threading.Thread.start,
            ) as starts:
                self._adopt(host)
                self._wait(lambda: stop.called, "restart did not stop its discussion")
                stable = {task_id: host.store.lifecycle(task_id) for task_id in family_ids}
                for task_id in family_ids:
                    lifecycle = host.lifecycle(task_id)
                    self.assertEqual(lifecycle["status"], "pausing")
                    self.assertFalse(lifecycle["can_resume"])
                    self.assertIsNone(host.store.record(task_id)["result"])
                    with self.assertRaises(task_api.TaskControlConflict):
                        host.resume(task_id, self._config, lifecycle["revision"])
                self.assertIsNone(process.poll())
                threads_started = starts.call_count
                self._adopt(host)
                self.assertEqual(
                    {task_id: host.store.lifecycle(task_id) for task_id in family_ids}, stable
                )
                self.assertEqual(starts.call_count, threads_started)
            # The original control thread completes automatically once Stop
            # can prove quiescence; no Resume or another adoption is needed.
            for task_id in family_ids:
                self._paused(host, task_id)
        self._assert_session_stopped(session_id, process)
        self.assertEqual(self._state(child["id"]), before)

    def test_stopped_session_with_unquiet_turn_attempt_blocks_pause_until_quiet(self):
        self._stopped_session_with_unquiet_turn_attempt()

    def test_cancel_adoption_waits_for_turn_quiescence_and_keeps_accounting(self):
        self._stopped_session_with_unquiet_turn_attempt(cancel=True)

    def _stopped_session_with_unquiet_turn_attempt(self, cancel=False):
        owner, child, session_id, process = self._owned_session("deep_task")
        host = self._host()
        sessions = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        )
        snapshot = sessions.read(session_id)
        usage, cost = self._record_brainstorming_activity(session_id)
        target = os.path.join(self.primary, "docs", "quiescence-deep_task.md")
        with coordination._open_target_parent(target) as (
            _descriptor, _name, parent_identity
        ):
            pass
        attempt = sessions.begin_turn_attempt(session_id, {
            "token": "worker-survived-discussion-coordinator",
            "participant_id": "lead",
            "completed_turn_count": len(snapshot.state["completed_turns"]),
            "target_revision": snapshot.state["accepted_target_revision"],
            "quiescent": False,
            "target_parent": parent_identity,
        })
        self.addCleanup(sessions.mark_turn_attempt_quiescent, session_id, attempt["token"])
        process.terminate()
        process.wait(timeout=5)
        brainstorming_lifecycle.reap_children(self.home)
        self._assert_session_stopped(session_id, process)
        stopped_once = threading.Event()
        real_stop = brainstorming_lifecycle.stop_session

        def observe_stop(*args, **kwargs):
            projection = real_stop(*args, **kwargs)
            stopped_once.set()
            return projection

        with mock.patch.object(brainstorming_lifecycle, "stop_session", side_effect=observe_stop):
            with self._adoption_controls_only(host):
                self._adopt(host)
                self.assertTrue(stopped_once.wait(5))
                for task_id in (owner["id"], child["id"]):
                    lifecycle = host.lifecycle(task_id)
                    self.assertEqual(lifecycle["status"], "pausing")
                    self.assertFalse(lifecycle["can_resume"])
                    with self.assertRaises(task_api.TaskControlConflict):
                        host.resume(task_id, self._config, lifecycle["revision"])
            self.assertFalse(sessions.read_turn_attempt(session_id)["quiescent"])
            if cancel:
                cancel_checked_quiescence = threading.Event()
                check_quiet = host._discussion_quiescent

                def observe_cancel_check(identity):
                    quiet = check_quiet(identity)
                    if not quiet and host.store.stop_reason(owner["id"]) is not None:
                        cancel_checked_quiescence.set()
                    return quiet

                with mock.patch.object(
                    host, "_discussion_quiescent", side_effect=observe_cancel_check
                ):
                    self.assertTrue(host.stop(owner["id"], "cancel recovered family"))
                    self.assertTrue(cancel_checked_quiescence.wait(5),
                                    "Cancel skipped surviving discussion-worker quiescence")
                    for task_id in (owner["id"], child["id"]):
                        self.assertIsNone(host.store.record(task_id)["result"])
                    self.assertTrue(host.owns_workspace(self.primary))
                    self.assertFalse(sessions.read_turn_attempt(session_id)["quiescent"])
            sessions.mark_turn_attempt_quiescent(session_id, attempt["token"])
            for task_id in (owner["id"], child["id"]):
                if cancel:
                    terminal = self._terminal(host, task_id)
                    self.assertEqual(terminal["result"]["status"], "failure")
                    self.assertEqual(terminal["result"]["reason"], "cancel recovered family")
                    self.assertEqual(terminal["result"]["token_usage"], usage)
                    self.assertEqual(terminal["result"]["cost"], cost)
                else:
                    self._paused(host, task_id)
        self.assertTrue(sessions.read_turn_attempt(session_id)["quiescent"])

    def test_cancel_winning_failure_pause_settles_discussion_and_keeps_accounting(self):
        owner, _child, session_id, process = self._owned_session()
        usage, cost = self._record_brainstorming_activity(session_id)
        host = self._host()
        stop = brainstorming_lifecycle.stop_session
        reason = "cancel accepted while failure pause was stopping discussion"
        accepted = threading.Event()

        def cancel_during_pause(*args, **kwargs):
            with registry.locked(self.home):
                host.store.record_stop_locked(owner["id"], reason)
            accepted.set()
            return stop(*args, **kwargs)

        with mock.patch.object(
            brainstorming_milestone, "terminal_handoff",
            side_effect=OSError("terminal handoff inspection failed"),
        ), mock.patch.object(
            brainstorming_lifecycle, "stop_session", side_effect=cancel_during_pause
        ):
            host.start(owner, self._config)
            self.assertTrue(accepted.wait(5), "failure skipped its pause boundary")
            terminal = self._terminal(host, owner["id"])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], reason)
        self.assertEqual(terminal["result"]["token_usage"], usage)
        self.assertEqual(terminal["result"]["cost"], cost)
        self.assertGreaterEqual(terminal["result"]["duration_s"], 7.0)
        self.assertEqual(self._assert_session_stopped(session_id, process)["state"]["status"], "failure")
        ledger = [event for event in self._state(owner["id"])["events"]
                  if event.get("type") == "brainstorming_work_recorded"
                  and event.get("session_id") == session_id]
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["duration_s"], 7.0)
        before = copy.deepcopy(terminal)
        with self._adoption_controls_only(host):
            self._adopt(host)
        self.assertEqual(host.store.record(owner["id"]), before)
        self.assertEqual(host.test_runner.calls, [])


if __name__ == "__main__":
    unittest.main()
