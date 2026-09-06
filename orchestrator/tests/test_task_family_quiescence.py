"""A terminal receipt is not proof that its physical task family is quiet."""

import copy
import os
import threading
import unittest
from unittest import mock

from orchestrator import brainstorming, brainstorming_lifecycle
from orchestrator import brainstorming_coordination as coordination
from orchestrator import contracts, gitops, registry, runners, task_api
from orchestrator import driver as drv
from orchestrator import state as st
from orchestrator.task_execution import ExecutionBusy, TaskExecutionLease
from orchestrator.tests import test_task_pause_quiescence as pause_tests
from orchestrator.tests import test_task_recovery as recovery_tests


class TaskFamilyQuiescenceTest(unittest.TestCase):
    setUp = recovery_tests.TaskRecoveryTest.setUp
    directory = recovery_tests.TaskRecoveryTest.directory
    start_server = recovery_tests.TaskRecoveryTest.start_server
    request = recovery_tests.TaskRecoveryTest.request
    order = recovery_tests.TaskRecoveryTest.order
    _sleeper = recovery_tests.TaskRecoveryTest._sleeper
    _git = staticmethod(recovery_tests.TaskRecoveryTest._git)
    _script = staticmethod(recovery_tests.TaskRecoveryTest._script)
    _config = staticmethod(recovery_tests.TaskRecoveryTest._config)
    _admit = recovery_tests.TaskRecoveryTest._admit
    _wait = recovery_tests.TaskRecoveryTest._wait
    _paused = recovery_tests.TaskRecoveryTest._paused
    _terminal = recovery_tests.TaskRecoveryTest._terminal
    _manual_brainstorming = recovery_tests.TaskRecoveryTest._manual_brainstorming
    _waiting_manual_brainstorming = recovery_tests.TaskRecoveryTest._waiting_manual_brainstorming
    _waiting_rethink_session = recovery_tests.TaskRecoveryTest._waiting_rethink_session
    _start_waiting_session = pause_tests.TaskPauseQuiescenceTest._start_waiting_session
    _record_brainstorming_activity = pause_tests.TaskPauseQuiescenceTest._record_brainstorming_activity

    def _terminal_documentation(self):
        parent = self._admit("deep_task")
        production = runners.MockRunner(self._script(contracts.KIND_DRAFT_SLICE_NOTE))
        host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: production,
            poll_interval=0.005,
        )
        child, reason = host._admit_deep_child(
            parent["id"], "documentation", None,
            host._deep_child_order(parent), self.primary,
        )
        self.assertIsNone(reason)
        host.start(child, self._config)
        child = self._terminal(host, child["id"])
        self.assertEqual(child["result"]["status"], "success", child)
        return host, parent, child

    def _surviving_journal(self, task_id):
        process = self._sleeper()
        task_dir = os.path.join(self.home, "task-runtime", task_id)
        with TaskExecutionLease(task_dir) as lease:
            lease.prepare_spawn({})
            lease.record_worker(process.pid)
            lease.finish_spawn(False)
        return process

    @staticmethod
    def _finish_process(process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)

    def _wait_host_inactive(self, host):
        self._wait(
            lambda: all(not host.is_active(record["id"])
                        for record in host.store.records()),
            "test host did not release its task family before fixture cleanup",
        )

    def _finish_discussion_fixture(self, host, session_id, process):
        sessions = brainstorming.SessionStore(brainstorming_lifecycle.state_directory(self.home))
        attempt = sessions.read_turn_attempt(session_id)
        if attempt is not None and not attempt["quiescent"]:
            sessions.mark_turn_attempt_quiescent(session_id, attempt["token"])
        self._finish_process(process)
        brainstorming_lifecycle.reap_children(self.home)
        self._wait_host_inactive(host)

    def _terminal_documentation_with_discussion(self, history_only=True, running=True):
        # Create the durable native session before admitting its eventual task
        # owner, using the established no-provider discussion fixture.
        session_id, waiting, bind_caller = self._waiting_rethink_session(
            self.primary, "terminal-child-discussion.md"
        )
        if history_only:
            host, parent, child = self._terminal_documentation()
        else:
            # A legacy Cancel could terminalize the public child while its
            # pending unit retained a discussion attachment. Prepare that
            # attachment before the first terminal receipt; never mutate an
            # already-sealed successful unit to manufacture this history.
            parent = self._admit("deep_task")
            host = task_api.DirectTaskHost(self.home, poll_interval=0.005)
            child, stopped = host._admit_deep_child(
                parent["id"], "documentation", None,
                host._deep_child_order(parent), self.primary,
            )
            self.assertIsNone(stopped)
            task_api.ensure_reviewed_state(self.home, child, self._config())
        path = task_api.reviewed_state_path(self.home, child["id"])
        with st.exclusive_mutation(path):
            state = st.load(path)
            unit = next(candidate for candidate in state["units"]
                        if st.unit_key(candidate) == state["reviewed_task"]["unit"])
            unit_key = st.unit_key(unit)
            bind_caller(state, self._config(), unit_key, {}, [], {})
            st.append_event(state, "brainstorming_wait_started", unit=unit_key,
                            kind=contracts.KIND_DRAFT_SLICE_NOTE, session_id=session_id)
            if history_only:
                unit.pop("brainstorming_wait", None)
                st.append_event(state, "brainstorming_rethink_sealed", unit=unit_key,
                                session_id=session_id)
            else:
                unit["brainstorming_wait"] = {
                    "session_id": session_id,
                    "origin": {"kind": contracts.KIND_DRAFT_SLICE_NOTE},
                }
            st.save(path, state)
        if not history_only:
            reason = "legacy Cancel retained its discussion attachment"
            with registry.locked(self.home):
                host.store.record_stop_locked(child["id"], reason)
                child = host.store.record_result_locked(child["id"], {
                    "status": "failure", "reason": reason, "native_result": None,
                    **st.reviewed_work_accounting(state, unit),
                })
        process = self._start_waiting_session(session_id, waiting)
        self.addCleanup(self._finish_discussion_fixture, host, session_id, process)
        sessions = brainstorming.SessionStore(brainstorming_lifecycle.state_directory(self.home))
        self._record_brainstorming_activity(session_id)
        snapshot = sessions.read(session_id)
        target = os.path.join(self.primary, "docs", "terminal-child-discussion.md")
        with coordination._open_target_parent(target) as (_descriptor, _name, parent_identity):
            pass
        attempt = sessions.begin_turn_attempt(session_id, {
            "token": "terminal-child-surviving-discussion-turn",
            "participant_id": "lead",
            "completed_turn_count": len(snapshot.state["completed_turns"]),
            "target_revision": snapshot.state["accepted_target_revision"],
            "quiescent": False,
            "target_parent": parent_identity,
        })
        if not running:
            self._finish_process(process)
            brainstorming_lifecycle.reap_children(self.home)
        # No worker journal is responsible for any of the fences below.
        self.assertTrue(host._workers_quiescent(host._family(parent["id"])))
        self.assertIn(session_id, host._pause_discussion_ids(child))
        self.assertEqual(host.store.record(child["id"]), child)
        return host, parent, child, session_id, process, sessions, attempt

    def test_resume_checks_terminal_child_historical_discussion_and_turn_attempt(self):
        host, parent, child, identity, process, sessions, attempt = (
            self._terminal_documentation_with_discussion(history_only=True)
        )
        path = task_api.reviewed_state_path(self.home, child["id"])
        child_state = st.load(path)
        self.assertFalse(any(unit.get("brainstorming_wait") for unit in child_state["units"]))
        native_state = sessions.read(identity).state
        with registry.locked(self.home):
            host.store.pause_locked(parent["id"], "operator pause")
        revision = host.store.lifecycle(parent["id"])["revision"]
        try:
            with mock.patch.object(host, "start") as start, mock.patch.object(
                st, "resume_run"
            ) as restore_git:
                self.assertIsNone(process.poll())
                self.assertFalse(host.lifecycle(parent["id"])["can_resume"])
                with self.assertRaises(task_api.TaskControlConflict):
                    host.resume(parent["id"], self._config, revision)
                stopped = brainstorming_lifecycle.stop_session(self.home, identity, lambda _record: True)
                self.assertEqual(stopped["process"], "stopped")
                self.assertFalse(sessions.read_turn_attempt(identity)["quiescent"])
                self.assertFalse(host.lifecycle(parent["id"])["can_resume"])
                with self.assertRaises(task_api.TaskControlConflict):
                    host.resume(parent["id"], self._config, revision)
                self.assertTrue(host.owns_workspace(self.primary))
                start.assert_not_called()
                restore_git.assert_not_called()
                sessions.mark_turn_attempt_quiescent(identity, attempt["token"])
                self.assertTrue(host.lifecycle(parent["id"])["can_resume"])
                host.resume(parent["id"], self._config, revision)
                start.assert_called_once()
            self.assertEqual(host.store.record(child["id"]), child)
            self.assertEqual(st.load(path), child_state)
            self.assertEqual(sessions.read(identity).state, native_state)
        finally:
            self._finish_discussion_fixture(host, identity, process)

    def test_terminal_child_legacy_detach_requires_missing_session_and_quiet_attempt(self):
        host, parent, child, identity, process, sessions, attempt = (
            self._terminal_documentation_with_discussion(history_only=False, running=False)
        )
        path = task_api.reviewed_state_path(self.home, child["id"])
        with st.exclusive_mutation(path):
            state = st.load(path)
            st.append_event(state, "brainstorming_missing_detached",
                            unit=state["reviewed_task"]["unit"], session_id=identity)
            st.save(path, state)
        child_state = st.load(path)
        native_state = sessions.read(identity).state
        with registry.locked(self.home):
            host.store.pause_locked(parent["id"], "operator pause")
        revision = host.store.lifecycle(parent["id"])["revision"]
        try:
            with mock.patch.object(host, "start") as start:
                # A detach event alone cannot erase a still-registered owner.
                self.assertIn(identity, host._pause_discussion_ids(child))
                self.assertFalse(host.lifecycle(parent["id"])["can_resume"])
                with self.assertRaises(task_api.TaskControlConflict):
                    host.resume(parent["id"], self._config, revision)
                deleted = brainstorming_lifecycle.delete_session(
                    self.home, identity, lambda _record: True, purge=False
                )
                self.assertEqual(deleted, {"deleted": identity, "purged": False})
                # Retained worker evidence survives removal from the panel.
                self.assertFalse(sessions.read_turn_attempt(identity)["quiescent"])
                self.assertIn(identity, host._pause_discussion_ids(child))
                self.assertFalse(host.lifecycle(parent["id"])["can_resume"])
                with self.assertRaises(task_api.TaskControlConflict):
                    host.resume(parent["id"], self._config, revision)
                start.assert_not_called()
                sessions.mark_turn_attempt_quiescent(identity, attempt["token"])
                self.assertNotIn(identity, host._pause_discussion_ids(child))
                self.assertTrue(host.lifecycle(parent["id"])["can_resume"])
                host.resume(parent["id"], self._config, revision)
                start.assert_called_once()
            self.assertEqual(host.store.record(child["id"]), child)
            self.assertEqual(st.load(path), child_state)
            self.assertEqual(sessions.read(identity).state, native_state)
        finally:
            self._finish_discussion_fixture(host, identity, process)

    def test_deep_successor_stops_terminal_child_discussion_before_resume(self):
        host, parent, child, identity, process, sessions, attempt = (
            self._terminal_documentation_with_discussion(history_only=True)
        )
        path = task_api.reviewed_state_path(self.home, child["id"])
        child_state = st.load(path)
        native_state = sessions.read(identity).state
        implementation = runners.MockRunner(self._script(contracts.KIND_IMPLEMENT))
        factory = mock.Mock(return_value=implementation)
        host.runner_factory = factory
        stopped = threading.Event()
        real_stop = brainstorming_lifecycle.stop_session

        def stop_native(*args, **kwargs):
            result = real_stop(*args, **kwargs)
            if args[1] == identity:
                stopped.set()
            return result

        try:
            with mock.patch.object(brainstorming_lifecycle, "stop_session", side_effect=stop_native), \
                    mock.patch.object(brainstorming_lifecycle, "abandon_session", side_effect=AssertionError(
                        "a terminal child's discussion must only be quiesced"
                    )) as abandon, \
                    mock.patch.object(host, "_deep_documentation_reference",
                                      wraps=host._deep_documentation_reference) as reference:
                host.start(parent, self._config)
                self.assertTrue(stopped.wait(5), "successor did not stop the terminal child's discussion")
                self.assertIsNotNone(process.poll())
                self.assertEqual(host.store.lifecycle(parent["id"])["status"], "pausing")
                self.assertFalse(sessions.read_turn_attempt(identity)["quiescent"])
                self.assertIsNone(host.store.related(parent["id"], "implementation", "a"))
                self.assertFalse(host.lifecycle(parent["id"])["can_resume"])
                self.assertTrue(host.owns_workspace(self.primary))
                factory.assert_not_called()
                reference.assert_not_called()
                sessions.mark_turn_attempt_quiescent(identity, attempt["token"])
                paused = self._paused(host, parent["id"])
                factory.assert_not_called()
                reference.assert_not_called()
                abandon.assert_not_called()
            host.resume(parent["id"], self._config, paused["revision"])
            terminal = self._terminal(host, parent["id"])
            successor = host.store.related(parent["id"], "implementation", "a")
            self.assertEqual(terminal["result"], host._deep_result(
                "success", [child["result"], successor["result"]]
            ))
            self.assertEqual(host.store.record(child["id"]), child)
            self.assertEqual(st.load(path), child_state)
            self.assertEqual(sessions.read(identity).state, native_state)
            factory.assert_called_once()
        finally:
            self._finish_discussion_fixture(host, identity, process)

    def test_cancel_waits_for_terminal_child_historical_discussion_without_recharging(self):
        host, parent, child, identity, process, sessions, attempt = (
            self._terminal_documentation_with_discussion(history_only=True, running=False)
        )
        path = task_api.reviewed_state_path(self.home, child["id"])
        child_state = st.load(path)
        native_state = sessions.read(identity).state
        reason = "cancel family with a terminal child's surviving discussion"
        cancel_checked = threading.Event()
        inspect_discussion = host._discussion_quiescent

        def check_after_cancel(session_id):
            quiet = inspect_discussion(session_id)
            if session_id == identity and not quiet and host.store.stop_reason(parent["id"]) == reason:
                cancel_checked.set()
            return quiet

        try:
            with mock.patch.object(host, "_discussion_quiescent", side_effect=check_after_cancel), \
                    mock.patch.object(brainstorming_lifecycle, "abandon_session", side_effect=AssertionError(
                        "a terminal child's discussion must only be quiesced"
                    )) as abandon, \
                    mock.patch.object(drv, "Driver", side_effect=AssertionError(
                        "Cancel must not reopen a terminal child"
                    )) as reopen_child, \
                    mock.patch.object(host, "runner_factory", side_effect=AssertionError(
                        "Cancel must not dispatch a provider"
                    )) as factory:
                self.assertTrue(host.stop(parent["id"], reason))
                self.assertTrue(cancel_checked.wait(5), "Cancel skipped the terminal child's discussion")
                self.assertIsNone(host.store.record(parent["id"])["result"])
                self.assertFalse(sessions.read_turn_attempt(identity)["quiescent"])
                self.assertTrue(host.owns_workspace(self.primary))
                self.assertFalse(host.lifecycle(parent["id"])["can_resume"])
                self.assertEqual(host.store.record(child["id"]), child)
                sessions.mark_turn_attempt_quiescent(identity, attempt["token"])
                terminal = self._terminal(host, parent["id"])
                # Native activity has nonzero accounting, but the terminal
                # child's immutable receipt is the only parent charge.
                self.assertEqual(terminal["result"], host._deep_result("failure", [child["result"]], reason))
                abandon.assert_not_called()
                reopen_child.assert_not_called()
                factory.assert_not_called()
            self.assertEqual(host.store.record(child["id"]), child)
            self.assertEqual(st.load(path), child_state)
            self.assertEqual(sessions.read(identity).state, native_state)
            self.assertFalse(host.owns_workspace(self.primary))
        finally:
            self._finish_discussion_fixture(host, identity, process)

    def test_owned_lease_cannot_close_during_its_quiescence_inspection(self):
        record = self._admit("agent_call")
        host = task_api.DirectTaskHost(self.home, poll_interval=0.005)
        lease = host._lease(record["id"]).acquire()
        with host._lock:
            host._leases[record["id"]] = lease
        inspecting, release = threading.Event(), threading.Event()
        closing, closed = threading.Event(), threading.Event()
        errors = []
        inspect_lease = lease.ensure_quiescent

        def hold_inspection():
            inspecting.set()
            if not release.wait(5):
                raise AssertionError("test did not release lease inspection")
            inspect_lease()

        def inspect():
            try:
                host._ensure_workers_quiescent([record])
            except Exception as exc:
                errors.append(exc)

        def close_reservation():
            try:
                closing.set()
                with host._lock:
                    host._leases.pop(record["id"]).close()
                closed.set()
            except Exception as exc:
                errors.append(exc)

        inspector = threading.Thread(target=inspect)
        closer = threading.Thread(target=close_reservation)
        try:
            with mock.patch.object(lease, "ensure_quiescent", side_effect=hold_inspection):
                inspector.start()
                self.assertTrue(inspecting.wait(5), "lease inspection did not start")
                # This directly proves the descriptor's owner lock is held;
                # the competing closer below also exercises the real path.
                acquired = host._lock.acquire(blocking=False)
                if acquired:
                    host._lock.release()
                self.assertFalse(acquired, "inspection released the descriptor's owner lock")
                closer.start()
                self.assertTrue(closing.wait(5), "reservation cleanup did not start")
                self.assertFalse(closed.wait(0.05), "reservation closed during inspection")
                release.set()
                inspector.join(timeout=5)
                closer.join(timeout=5)
                self.assertFalse(inspector.is_alive())
                self.assertFalse(closer.is_alive())
                self.assertTrue(closed.is_set())
                self.assertEqual(errors, [])
        finally:
            release.set()
            for thread in (inspector, closer):
                if thread.ident is not None:
                    thread.join(timeout=5)
            with host._lock:
                retained = host._leases.pop(record["id"], None)
                if retained is not None:
                    retained.close()
            self.assertFalse(inspector.is_alive())
            self.assertFalse(closer.is_alive())

    def test_resume_checks_terminal_child_before_any_control_or_git_mutation(self):
        host, parent, child = self._terminal_documentation()
        child_before = copy.deepcopy(child)
        with registry.locked(self.home):
            host.store.pause_locked(parent["id"], "operator pause")
        revision = host.store.lifecycle(parent["id"])["revision"]
        process = self._surviving_journal(child["id"])
        head = self._git(self.primary, "rev-parse", "HEAD")
        try:
            self.assertTrue(host.owns_workspace(self.primary))
            projection = host.lifecycle(parent["id"])
            self.assertFalse(projection["can_resume"], projection)
            self.assertIsNotNone(projection["blocked_reason"])
            with mock.patch.object(host, "start") as start, mock.patch.object(
                st, "resume_run"
            ) as recover_git:
                with self.assertRaises(task_api.TaskControlConflict):
                    host.resume(parent["id"], self._config, revision)
                start.assert_not_called()
                recover_git.assert_not_called()
            self.assertEqual(host.store.lifecycle(parent["id"])["revision"], revision)
            self.assertEqual(host.store.record(child["id"]), child_before)
            self.assertEqual(self._git(self.primary, "rev-parse", "HEAD"), head)
        finally:
            self._finish_process(process)
            self._wait_host_inactive(host)
        self._wait(lambda: host.lifecycle(parent["id"])["can_resume"],
                   "terminal child's finished group still blocked Resume")
        with mock.patch.object(host, "start") as start:
            host.resume(parent["id"], self._config, revision)
            start.assert_called_once()
        self.assertEqual(host.store.record(child["id"]), child_before)

    def test_deep_successor_waits_for_terminal_child_group_and_explicit_resume(self):
        host, parent, child = self._terminal_documentation()
        child_before = copy.deepcopy(child)
        process = self._surviving_journal(child["id"])
        implementation = runners.MockRunner(self._script(contracts.KIND_IMPLEMENT))
        factory = mock.Mock(return_value=implementation)
        host.runner_factory = factory
        reference = host._deep_documentation_reference
        try:
            with mock.patch.object(
                host, "_deep_documentation_reference", wraps=reference
            ) as derive_reference:
                host.start(parent, self._config)
                control = self._wait(
                    lambda: (value if (value := host.store.lifecycle(parent["id"]))[
                        "status"] != "running" else None),
                    "deep owner did not stop at surviving predecessor",
                )
                self.assertEqual(control["status"], "pausing", control)
                self.assertIsNone(host.store.related(parent["id"], "implementation", "a"))
                factory.assert_not_called()
                derive_reference.assert_not_called()
                self.assertTrue(host.owns_workspace(self.primary))
                self.assertFalse(host.lifecycle(parent["id"])["can_resume"])
                self.assertEqual(host.store.record(child["id"]), child_before)
                self._finish_process(process)
                paused = self._paused(host, parent["id"])
                self.assertEqual(paused["source"], "error")
                factory.assert_not_called()
                derive_reference.assert_not_called()
            host.resume(parent["id"], self._config, paused["revision"])
            result = self._terminal(host, parent["id"])
            self.assertEqual(result["result"]["status"], "success", result)
            factory.assert_called_once()
            self.assertEqual(host.store.record(child["id"]), child_before)
            self.assertEqual(len(host.store.records()), 3)
        finally:
            self._finish_process(process)
            self._wait_host_inactive(host)

    def test_cancel_keeps_terminal_child_reservation_until_group_is_quiet(self):
        host, parent, child = self._terminal_documentation()
        child_before = copy.deepcopy(child)
        process = self._surviving_journal(child["id"])
        factory = mock.Mock(side_effect=AssertionError("Cancel cannot launch a provider"))
        host.runner_factory = factory
        try:
            host.adopt_open_tasks(lambda _record: self._config)
            control = host.store.lifecycle(parent["id"])
            self.assertEqual(control["status"], "pausing", control)
            self.assertTrue(host.stop(parent["id"], "cancel recovered family"))
            self.assertEqual(host.store.stop_reason(parent["id"]), "cancel recovered family")
            self.assertIsNone(host.store.record(parent["id"])["result"])
            self.assertTrue(host.owns_workspace(self.primary))
            self.assertFalse(host.lifecycle(parent["id"])["can_resume"])
            self.assertEqual(host.store.record(child["id"]), child_before)
            factory.assert_not_called()
            self._finish_process(process)
            terminal = self._terminal(host, parent["id"])
            self.assertEqual(terminal["result"]["status"], "failure")
            self.assertEqual(terminal["result"]["reason"], "cancel recovered family")
            self.assertEqual(host.store.record(child["id"]), child_before)
            self.assertFalse(host.owns_workspace(self.primary))
            self.assertEqual(len(host.store.records()), 2)
            factory.assert_not_called()
        finally:
            self._finish_process(process)
            self._wait_host_inactive(host)

    def test_cancel_adopted_family_retries_open_child_settlement_after_worker_exit(self):
        parent = self._admit("deep_task")
        host = task_api.DirectTaskHost(self.home, poll_interval=0.005)
        child, stopped = host._admit_deep_child(
            parent["id"], "documentation", None,
            host._deep_child_order(parent), self.primary,
        )
        self.assertIsNone(stopped)
        path = task_api.ensure_reviewed_state(self.home, child, self._config())
        subject = drv.Driver(path, runner=runners.MockRunner([]), model_profiles_home=self.home)
        accounting = {
            "duration_s": 0.375,
            "token_usage": runners.normalize_token_usage({"input_tokens": 9, "output_tokens": 4}),
            "token_usage_partial": False,
            "cost": {"api_usd": 0.07, "real_usd": 0.02},
            "cost_partial": False,
        }
        self.assertTrue(subject._write_busy({
            "call_id": "completed-open-child-before-host-restart",
            "family": "codex", "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "completed": True, "unit": subject.state["reviewed_task"]["unit"],
            "label": "completed-open-child-before-host-restart", **accounting,
        }))
        before = st.load(path)
        process = self._surviving_journal(child["id"])
        reason = "cancel recovered family while its open child still owns a worker"
        cancel_blocked = threading.Event()
        get_lease = host._lease
        make_driver = drv.Driver

        def observe_lease(task_id):
            lease = get_lease(task_id)
            acquire = lease.acquire

            def observe_acquire():
                try:
                    return acquire()
                except ExecutionBusy:
                    if task_id == child["id"] and host.store.stop_reason(parent["id"]) == reason:
                        cancel_blocked.set()
                    raise

            lease.acquire = observe_acquire
            return lease

        def cancellation_driver(*args, **kwargs):
            self.assertIsNotNone(process.poll(), "Cancel recovered the child before its worker stopped")
            self.assertTrue(kwargs.get("cancellation_only"), "Cancel reopened ordinary child execution")
            return make_driver(*args, **kwargs)

        try:
            with mock.patch.object(host, "_lease", side_effect=observe_lease), \
                    mock.patch.object(drv, "Driver", side_effect=cancellation_driver) as recovery, \
                    mock.patch.object(host, "runner_factory", side_effect=AssertionError(
                        "Cancel must not dispatch a provider"
                    )) as provider, \
                    mock.patch.object(gitops, "worktree_diff", side_effect=AssertionError(
                        "Cancel must not inspect or restore Git"
                    )) as inspect_git:
                host.adopt_open_tasks(lambda _record: self._config)
                for record in (parent, child):
                    self.assertEqual(host.store.lifecycle(record["id"])["status"], "pausing")
                self.assertTrue(host.stop(parent["id"], reason))
                self.assertTrue(cancel_blocked.wait(5), "Cancel skipped its open child's surviving worker")
                self.assertTrue(host.is_active(parent["id"]), "Cancel lost its settlement owner")
                self.assertIsNone(process.poll())
                self.assertTrue(host.owns_workspace(self.primary))
                for record in (parent, child):
                    self.assertIsNone(host.store.record(record["id"])["result"])
                    self.assertFalse(host.lifecycle(record["id"])["can_resume"])
                self.assertEqual(st.load(path), before)
                recovery.assert_not_called()
                provider.assert_not_called()
                inspect_git.assert_not_called()
                self._finish_process(process)
                # No second Stop, adoption, or Resume is allowed to rescue
                # this wait: the same cancellation owner must complete it.
                terminal_child = self._terminal(host, child["id"])
                terminal_parent = self._terminal(host, parent["id"])
                for terminal in (terminal_child, terminal_parent):
                    self.assertEqual(terminal["result"]["status"], "failure")
                    self.assertEqual(terminal["result"]["reason"], reason)
                    for field, value in accounting.items():
                        self.assertEqual(terminal["result"][field], value, field)
                recovery.assert_called_once()
                provider.assert_not_called()
                inspect_git.assert_not_called()
                self.assertEqual(len(host.store.records()), 2)
                self.assertFalse(host.owns_workspace(self.primary))
                self.assertEqual(len([
                    event for event in st.load(path)["events"]
                    if event["type"] == "worker_interrupted"
                ]), 1)
        finally:
            self._finish_process(process)
            self._wait_host_inactive(host)

    def _agent_with_unknown_cleanup(self, manual_pause=False, unknown_observation=False):
        record = self._admit("agent_call")
        process = self._sleeper()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        class RetainedWorker:
            call_count = 0

            def call(inner, *_args, **_kwargs):
                inner.call_count += 1
                inner.execution_lease.prepare_spawn({})
                inner.execution_lease.record_worker(process.pid)
                entered.set()
                if manual_pause:
                    if not release.wait(5):
                        raise AssertionError("test did not release current call")
                inner.execution_lease.finish_spawn(False)
                if manual_pause:
                    return runners.RunnerResult("completed once", 0, 0.25)
                raise runners.RunnerError("worker cleanup could not establish quiescence")

        runner = RetainedWorker()
        factory = mock.Mock(return_value=runner)
        host = task_api.DirectTaskHost(
            self.home, runner_factory=factory, poll_interval=0.005,
        )
        try:
            host.start(record, self._config)
            self.assertTrue(entered.wait(5), "worker did not record its process group")
            if manual_pause:
                host.pause(record["id"], "pause current call")
                release.set()
            control = self._wait(
                lambda: (value if (value := host.store.lifecycle(record["id"]))[
                    "status"] != "running" else None),
                "failed call did not enter its pause boundary",
            )
            self.assertEqual(control["status"], "pausing", control)
            self.assertIsNone(host.store.record(record["id"])["result"])
            self.assertFalse(host.lifecycle(record["id"])["can_resume"])
            self.assertTrue(host.owns_workspace(self.primary))
            host.adopt_open_tasks(lambda _record: self._config)
            self.assertEqual(host.store.lifecycle(record["id"])["status"], "pausing")
            self.assertEqual(runner.call_count, 1)
            factory.assert_called_once()
            if unknown_observation:
                observed_unknown = threading.Event()
                check_group = runners._process_group_quiescent

                def cannot_verify(pgid):
                    if pgid == process.pid:
                        if process.poll() is not None:
                            observed_unknown.set()
                        return None
                    return check_group(pgid)

                with mock.patch.object(
                    runners, "_process_group_quiescent", side_effect=cannot_verify
                ):
                    self._finish_process(process)
                    self.assertTrue(observed_unknown.wait(5),
                                    "settlement did not recheck the uncertain group")
                    self.assertEqual(host.store.lifecycle(record["id"])["status"], "pausing")
                    self.assertFalse(host.lifecycle(record["id"])["can_resume"])
                    self.assertEqual(runner.call_count, 1)
            else:
                self._finish_process(process)
            paused = self._paused(host, record["id"])
            self.assertTrue(host.lifecycle(record["id"])["can_resume"])
            self.assertEqual(runner.call_count, 1, "physical cleanup retried the provider")
            if manual_pause:
                host.resume(record["id"], self._config, paused["revision"])
                terminal = self._terminal(host, record["id"])
                self.assertEqual(terminal["result"]["status"], "success", terminal)
                self.assertEqual(terminal["result"]["native_result"], "completed once")
                self.assertEqual(terminal["result"]["duration_s"], 0.25)
                self.assertEqual(runner.call_count, 1)
                factory.assert_called_once()
            else:
                self.assertEqual(paused["source"], "error")
        finally:
            release.set()
            self._finish_process(process)
            self._wait_host_inactive(host)

    def test_failed_agent_cleanup_stays_pausing_then_settles_without_retry(self):
        self._agent_with_unknown_cleanup()

    def test_success_during_manual_pause_waits_for_group_then_publishes_once(self):
        self._agent_with_unknown_cleanup(manual_pause=True)

    def test_unknown_group_observation_cannot_certify_pause_after_leader_exit(self):
        self._agent_with_unknown_cleanup(unknown_observation=True)


if __name__ == "__main__":
    unittest.main()
