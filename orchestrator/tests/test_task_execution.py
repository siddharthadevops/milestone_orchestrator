"""Physical task ownership, including REAL owner-death / surviving-worker races."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

from orchestrator.runners import RunnerError, SubprocessRunner
from orchestrator.task_execution import ExecutionBusy, TaskExecutionLease


WORKER = r'''
import json, os, sys, time
workspace, mode, live = sys.argv[1:]
if live == "live":
    sys.stdin.readline()
else:
    sys.stdin.read()
if mode == "close-fds":
    os.closerange(3, 4096)
if mode == "descendant":
    child = os.fork()
    if child == 0:
        os.closerange(3, 4096)
        with open(os.path.join(workspace, "descendant.pid"), "w") as handle:
            handle.write(str(os.getpid()))
    else:
        with open(os.path.join(workspace, "worker.pid"), "w") as handle:
            handle.write(str(os.getpid()))
elif mode != "descendant":
    with open(os.path.join(workspace, "worker.pid"), "w") as handle:
        handle.write(str(os.getpid()))
while True:
    with open(os.path.join(workspace, "heartbeat"), "a") as handle:
        handle.write(str(os.getpid()) + "\n")
    if mode == "fix":
        with open(os.path.join(workspace, "standalone.py"), "a") as handle:
            handle.write("# surviving fix\n")
    time.sleep(0.02)
'''


OWNER = r'''
import os, signal, sys
from orchestrator.runners import ActiveCallControl, SubprocessRunner
from orchestrator.task_execution import TaskExecutionLease
task_dir, workspace, mode, transport, worker = sys.argv[1:]
with TaskExecutionLease(task_dir) as lease:
    if mode == "spawn-gap":
        lease.record_worker = lambda _pid: os.kill(os.getpid(), signal.SIGKILL)
    runner = SubprocessRunner({}, {}, execution_lease=lease)
    argv = [sys.executable, "-c", worker, workspace, mode, transport]
    if transport == "live":
        runner._call_live_transport(
            "claude", "test prompt", workspace, argv, argv,
            active_control=ActiveCallControl(),
        )
    else:
        runner.commands = {"fake": argv}
        runner.call("fake", "test prompt", workspace)
'''


DEEP_HOST = r'''
import sys, time
from orchestrator import contracts, runners, task_api
from orchestrator.tests.test_reviewed_task_api import ReviewedTaskOrderingTest
from orchestrator.tests.test_driver_mock import finding, ok, report, step
home, identity, worker = sys.argv[1:]
factory_calls = []
class FixRunner(runners.MockRunner):
    def call(self, family, prompt, workspace, **kwargs):
        if runners.prompt_kind(prompt) == contracts.KIND_FIX_FINDINGS:
            actual = runners.SubprocessRunner(
                {"fake": [sys.executable, "-c", worker, workspace, "fix", "template"]},
                {}, execution_lease=self.execution_lease,
            )
            return actual.call("fake", prompt, workspace)
        return super().call(family, prompt, workspace, **kwargs)
def factory(_config, _workspace):
    factory_calls.append(True)
    if len(factory_calls) == 1:
        return runners.MockRunner(ReviewedTaskOrderingTest._script(contracts.KIND_DRAFT_SLICE_NOTE))
    production = ReviewedTaskOrderingTest._script(contracts.KIND_IMPLEMENT)[0]
    review = step(contracts.KIND_REVIEW_ROUND, report(
        contracts.KIND_REVIEW_ROUND, [finding("F1", "fix the demonstrated behavior", severity="P2")]
    ))
    review.pop("expect_family", None)
    classification = step(contracts.KIND_RECLASSIFY, ok(
        contracts.KIND_RECLASSIFY, drift_risk="high", drift_damage="high",
        reason="The demonstrated behavior must be fixed before continuing.",
    ))
    classification.pop("expect_family", None)
    return FixRunner([production, review, classification])
host = task_api.DirectTaskHost(home, runner_factory=factory, poll_interval=0.001)
host.start(host.store.record(identity), ReviewedTaskOrderingTest._config)
while True:
    time.sleep(1)
'''


class TaskExecutionLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.task_dir = os.path.join(self.temporary.name, "task")

    def test_lease_excludes_second_owner_and_can_transfer_between_threads(self):
        import threading

        lease = TaskExecutionLease(self.task_dir).acquire()
        self.addCleanup(lease.close)
        with self.assertRaises(ExecutionBusy):
            TaskExecutionLease(self.task_dir).acquire()
        closer = threading.Thread(target=lease.close)
        closer.start()
        closer.join(timeout=2)
        self.assertFalse(closer.is_alive())
        with TaskExecutionLease(self.task_dir):
            pass

    def test_unknown_dispatch_fails_closed_without_mutating_evidence(self):
        with TaskExecutionLease(self.task_dir) as lease:
            kwargs = {}
            lease.prepare_spawn(kwargs)
            self.assertEqual(len(kwargs["pass_fds"]), 1)
            with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
                lease.prepare_spawn({})
        with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
            TaskExecutionLease(self.task_dir).acquire()
        with open(lease.journal_path) as handle:
            self.assertEqual(json.load(handle)["phase"], "dispatching")

    def test_invalid_journal_fails_closed(self):
        with TaskExecutionLease(self.task_dir) as lease:
            lease._write({"invalid": True})
        with self.assertRaisesRegex(ExecutionBusy, "invalid execution journal"):
            TaskExecutionLease(self.task_dir).acquire()

    def test_group_must_be_positively_quiescent(self):
        with TaskExecutionLease(self.task_dir) as lease:
            lease.prepare_spawn({})
            lease.record_worker(12345)
            lease.finish_spawn(False)
        for observation in (False, None):
            with self.subTest(observation=observation):
                with mock.patch("orchestrator.runners._process_group_quiescent",
                                return_value=observation):
                    with self.assertRaisesRegex(ExecutionBusy, "12345"):
                        TaskExecutionLease(self.task_dir).acquire()
        with mock.patch("orchestrator.runners._process_group_quiescent", return_value=True):
            with TaskExecutionLease(self.task_dir):
                self.assertFalse(os.path.exists(lease.journal_path))

    def test_successful_template_call_clears_dispatch(self):
        with TaskExecutionLease(self.task_dir) as lease:
            runner = SubprocessRunner(
                {"fake": [sys.executable, "-c", "print('ok')"]}, {},
                execution_lease=lease,
            )
            self.assertEqual(runner.call("fake", "prompt", self.temporary.name).text.strip(), "ok")
            self.assertFalse(os.path.exists(lease.journal_path))
            self.assertEqual(runner.call("fake", "second", self.temporary.name).text.strip(), "ok")

    def test_definite_spawn_failure_can_be_retried(self):
        with TaskExecutionLease(self.task_dir) as lease:
            runner = SubprocessRunner(
                {"fake": [os.path.join(self.temporary.name, "does-not-exist")]}, {},
                execution_lease=lease,
            )
            with self.assertRaises(RunnerError):
                runner.call("fake", "prompt", self.temporary.name)
            self.assertFalse(os.path.exists(lease.journal_path))

    def test_opaque_factory_failure_cannot_certify_no_worker_was_spawned(self):
        children = []

        def factory(_context, argv, kwargs):
            children.append(subprocess.Popen(argv, **kwargs))
            raise RuntimeError("factory failed after launch")

        try:
            with TaskExecutionLease(self.task_dir) as lease:
                runner = SubprocessRunner(
                    {}, {}, participant_process_factory=factory,
                    execution_lease=lease,
                )
                with self.assertRaises(RunnerError):
                    runner._call_template(
                        "fake", "prompt", self.temporary.name,
                        [sys.executable, "-c", "import time; time.sleep(30)"],
                        execution_context={"capability": "test"},
                    )
                with open(lease.journal_path) as handle:
                    self.assertEqual(json.load(handle)["phase"], "dispatching")
            with self.assertRaises(ExecutionBusy):
                TaskExecutionLease(self.task_dir).acquire()
        finally:
            for proc in children:
                proc.kill()
                proc.communicate(timeout=3)
        with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
            TaskExecutionLease(self.task_dir).acquire()

    def test_live_transport_clears_dispatch_after_success(self):
        from orchestrator.runners import ActiveCallControl

        worker = "import json,sys; sys.stdin.readline(); print(json.dumps({'type':'result','result':'ok'}),flush=True)"
        argv = [sys.executable, "-c", worker]
        with TaskExecutionLease(self.task_dir) as lease:
            runner = SubprocessRunner({}, {}, execution_lease=lease)
            result = runner._call_live_transport(
                "claude", "prompt", self.temporary.name, argv, argv,
                active_control=ActiveCallControl(),
            )
            self.assertEqual(result.text, "ok")
            self.assertFalse(os.path.exists(lease.journal_path))

    def test_owner_death_preserves_inherited_lock_for_template_worker(self):
        self._owner_death("template", "inherit")

    def test_owner_death_preserves_inherited_lock_for_live_worker(self):
        self._owner_death("live", "inherit")

    def test_journal_protects_worker_that_closed_inherited_descriptors(self):
        self._owner_death("template", "close-fds")

    def test_journal_protects_descendant_after_owner_and_worker_leader_die(self):
        self._owner_death("template", "descendant")

    def test_owner_death_in_spawn_identity_gap_fails_closed(self):
        self._owner_death("template", "spawn-gap")

    def _wait_until(self, predicate, description, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("timed out waiting for " + description)

    def _owner_death(self, transport, mode):
        """Kill only the real owner, demonstrate surviving writes, reject reuse."""
        workspace = self.temporary.name
        env = dict(os.environ)
        env.pop("ORCH_REAL_LLM", None)
        repo = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        env["PYTHONPATH"] = repo + os.pathsep + env.get("PYTHONPATH", "")
        owner = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(OWNER), self.task_dir,
             workspace, mode, transport, textwrap.dedent(WORKER)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, env=env, start_new_session=True,
        )
        worker_pid = None
        try:
            pid_path = os.path.join(workspace, "worker.pid")
            journal_path = os.path.join(self.task_dir, "execution.json")

            def ready():
                try:
                    with open(pid_path) as handle:
                        int(handle.read())
                    with open(journal_path) as handle:
                        phase = "dispatching" if mode == "spawn-gap" else "worker"
                        return json.load(handle).get("phase") == phase
                except (OSError, ValueError):
                    return False

            self._wait_until(ready, "worker and durable identity")
            with open(pid_path) as handle:
                worker_pid = int(handle.read())
            if mode == "descendant":
                child_path = os.path.join(workspace, "descendant.pid")
                self._wait_until(lambda: os.path.exists(child_path), "worker descendant")
            if owner.poll() is None:
                owner.kill()
            owner.wait(timeout=3)
            self.assertEqual(owner.returncode, -signal.SIGKILL)
            if mode == "descendant":
                os.kill(worker_pid, signal.SIGKILL)
                # Ensure the leader has released its inherited descriptor so
                # the journal, not an accidentally still-held flock, protects.
                time.sleep(0.1)
            heartbeat = os.path.join(workspace, "heartbeat")
            before = os.path.getsize(heartbeat)
            self._wait_until(lambda: os.path.getsize(heartbeat) > before,
                             "surviving worker writes after owner exit")
            if mode == "inherit":
                with mock.patch("orchestrator.runners._process_group_quiescent",
                                side_effect=AssertionError("inherited flock must exclude first")):
                    with self.assertRaises(ExecutionBusy):
                        TaskExecutionLease(self.task_dir).acquire()
            else:
                with self.assertRaises(ExecutionBusy):
                    TaskExecutionLease(self.task_dir).acquire()
            self.assertTrue(os.path.exists(journal_path))
            os.killpg(worker_pid, signal.SIGKILL)

            if mode == "spawn-gap":
                from orchestrator.runners import _process_group_quiescent
                self._wait_until(lambda: _process_group_quiescent(worker_pid) is True,
                                 "worker death after identity gap")
                with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
                    TaskExecutionLease(self.task_dir).acquire()
                return

            def recoverable():
                try:
                    with TaskExecutionLease(self.task_dir):
                        return True
                except ExecutionBusy:
                    return False

            self._wait_until(recoverable, "whole worker group quiescence")
            self.assertFalse(os.path.exists(journal_path))
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=3)
            if worker_pid is None:
                try:
                    with open(os.path.join(workspace, "worker.pid")) as handle:
                        worker_pid = int(handle.read())
                except (OSError, ValueError):
                    pass
            if worker_pid is not None:
                try:
                    os.killpg(worker_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            owner.stderr.close()


class HostExecutionCrashTests(unittest.TestCase):
    from orchestrator.tests.test_task_api import TaskApiTest as _ApiFixture
    setUp = _ApiFixture.setUp
    directory = _ApiFixture.directory
    start_server = _ApiFixture.start_server
    request = _ApiFixture.request
    order = _ApiFixture.order
    _wait_until = TaskExecutionLeaseTests._wait_until

    def _release_legacy_pause(self, host, path, task_id):
        # These fixtures never spawned a worker. Supply that positive evidence
        # only during teardown, after checking that unknown markers fail closed.
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"completed": True}, handle)
        self._wait_until(lambda: not host.is_active(task_id), "legacy pause controller cleanup")

    def _admit(self, executor):
        from orchestrator import service
        from orchestrator.tests.test_reviewed_task_api import ReviewedTaskOrderingTest

        order = self.order(executor, work_area={
            "workspace_path": self.primary, "primary": self.primary, "additional": [],
        })
        if executor == "reviewed_task":
            order["configuration"] = {"task_kind": "draft_slice_note"}
        with mock.patch.object(service, "_direct_task_config", return_value=ReviewedTaskOrderingTest._config()):
            status, response = self.request("POST", "/api/tasks", order)
        self.assertEqual(status, 201, response)
        return response["task"]

    def test_legacy_agent_inflight_marker_blocks_resume_without_new_lock(self):
        self._legacy_marker_rejected("agent_call")

    def test_legacy_reviewed_inflight_marker_blocks_resume_without_new_lock(self):
        self._legacy_marker_rejected("reviewed_task")

    def test_legacy_pending_child_call_blocks_even_when_current_call_completed(self):
        self._legacy_marker_rejected("reviewed_task", pending=True)

    def test_malformed_legacy_agent_marker_does_not_break_restart_or_enable_resume(self):
        from orchestrator import task_api
        from orchestrator.tests.test_reviewed_task_api import ReviewedTaskOrderingTest

        record = self._admit("agent_call")
        path = task_api._marker_path(self.home, record["id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(["malformed legacy marker"], handle)
        host = task_api.DirectTaskHost(self.home, poll_interval=0.001)
        self.addCleanup(self._release_legacy_pause, host, path, record["id"])
        host.adopt_open_tasks(lambda _record: ReviewedTaskOrderingTest._config)
        self.assertEqual(host.store.lifecycle(record["id"])["status"], "pausing")
        lifecycle = host.lifecycle(record["id"])
        self.assertFalse(lifecycle["can_resume"])
        self.assertIn("malformed", lifecycle["blocked_reason"])
        self.assertTrue(host.is_active(record["id"]))

    def test_legacy_completion_requires_true_boolean_not_truthy_text(self):
        from orchestrator import task_api
        from orchestrator.tests.test_reviewed_task_api import ReviewedTaskOrderingTest

        record = self._admit("reviewed_task")
        path = os.path.join(task_api.reviewed_state_directory(
            self.home, record["id"]), "current.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"completed": "false"}, handle)
        host = task_api.DirectTaskHost(self.home, poll_interval=0.001)
        self.addCleanup(self._release_legacy_pause, host, path, record["id"])
        host.adopt_open_tasks(lambda _record: ReviewedTaskOrderingTest._config)
        lifecycle = host.lifecycle(record["id"])
        self.assertFalse(lifecycle["can_resume"])
        self.assertIn("predates worker tracking", lifecycle["blocked_reason"])

    def test_missing_paused_workspace_does_not_break_other_workspace_ownership(self):
        from orchestrator import task_api
        from orchestrator.tests.test_reviewed_task_api import ReviewedTaskOrderingTest

        record = self._admit("agent_call")
        host = task_api.DirectTaskHost(self.home)
        host.adopt_open_tasks(lambda _record: ReviewedTaskOrderingTest._config)
        moved = self.primary + "-temporarily-moved"
        os.rename(self.primary, moved)
        try:
            self.assertFalse(host.owns_workspace(self.outside))
            self.assertTrue(host.owns_workspace(self.primary))
            self.assertFalse(host.owns_workspace_except(self.outside, record["id"]))
        finally:
            os.rename(moved, self.primary)

    def test_legacy_terminal_failure_with_unknown_worker_still_reserves_workspace(self):
        from orchestrator import task_api

        record = self._admit("agent_call")
        host = task_api.DirectTaskHost(self.home)
        path = task_api._marker_path(self.home, record["id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"call_id": "old-orphan", "completed": False}, handle)
        terminal = host.store.record_result(record["id"], host._deep_failure(
            "old backend closed the task after a restart"))
        self.assertTrue(host.owns_workspace(self.primary))
        self.assertFalse(host.owns_workspace(self.outside))
        self.assertEqual(host.store.record(record["id"]), terminal)
        self.assertFalse(host.lifecycle(record["id"])["can_resume"])

    def _legacy_marker_rejected(self, executor, pending=False):
        from orchestrator import task_api
        from orchestrator.tests.test_reviewed_task_api import ReviewedTaskOrderingTest

        record = self._admit(executor)
        task_id = record["id"]
        path = (task_api._marker_path(self.home, task_id)
                if executor == "agent_call" else os.path.join(
                    task_api.reviewed_state_directory(self.home, task_id), "current.json"))
        marker = {"task_id": task_id, "call_id": "old-untracked-call", "completed": pending}
        if pending:
            marker["pending_calls"] = [{"call_id": "old-pending-call", "completed": False}]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(marker, handle)
        runner_factory = mock.Mock(side_effect=AssertionError("legacy worker must not be retried"))
        host = task_api.DirectTaskHost(self.home, runner_factory=runner_factory, poll_interval=0.001)
        self.addCleanup(self._release_legacy_pause, host, path, task_id)
        host.adopt_open_tasks(lambda _record: ReviewedTaskOrderingTest._config)
        paused = host.store.lifecycle(task_id)
        self.assertEqual(paused["status"], "pausing")
        lock_path = os.path.join(self.home, "task-runtime", task_id, "execution.lock")
        for _retry in range(2):
            lifecycle = host.lifecycle(task_id)
            self.assertFalse(lifecycle["can_resume"])
            self.assertIn("predates worker tracking", lifecycle["blocked_reason"])
            with self.assertRaises(task_api.TaskControlConflict):
                host.resume(task_id, ReviewedTaskOrderingTest._config, paused["revision"])
            with self.assertRaisesRegex(ExecutionBusy, "predates worker tracking"):
                host._lease(task_id)
            self.assertFalse(os.path.exists(lock_path), "a refused probe must not manufacture tracking evidence")
            self.assertEqual(host.store.lifecycle(task_id), paused)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), marker)
        runner_factory.assert_not_called()

    def test_cancel_active_deep_child_cancels_parent_instead_of_pausing_it(self):
        import threading
        from orchestrator import contracts, runners, task_api
        from orchestrator.tests.test_reviewed_task_api import ReviewedTaskOrderingTest

        record = self._admit("deep_task")
        task_id = record["id"]
        entered, release = threading.Event(), threading.Event()
        implementation = ReviewedTaskOrderingTest._script(contracts.KIND_IMPLEMENT)
        write_implementation = implementation[0]["side_effect"]

        def hold(workspace):
            entered.set()
            if not release.wait(10):
                raise AssertionError("test did not release cancelled child")
            write_implementation(workspace)

        implementation[0]["side_effect"] = hold
        pending = [
            runners.MockRunner(ReviewedTaskOrderingTest._script(contracts.KIND_DRAFT_SLICE_NOTE)),
            runners.MockRunner(implementation[:1]),
        ]
        host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: pending.pop(0),
            poll_interval=0.001,
        )
        host.start(record, ReviewedTaskOrderingTest._config)
        try:
            self.assertTrue(entered.wait(10), "implementation child did not start")
            child = host.store.related(task_id, "implementation", "a")
            self.assertTrue(host.stop(child["id"], "cancel through the child"))
            self.assertEqual(host.store.stop_reason(task_id), "cancel through the child")
            release.set()

            def settled():
                return (not host.is_active(task_id) and not host.is_active(child["id"])
                        and host.store.record(task_id)["result"] is not None)

            self._wait_until(settled, "cancelled task family settlement")
            for identity in (task_id, child["id"]):
                result = host.store.record(identity)["result"]
                self.assertEqual(result["status"], "failure")
                self.assertIn("cancel through the child", result["reason"])
                self.assertFalse(host.lifecycle(identity)["can_resume"])
            self.assertEqual(len(host.store.records()), 3)
            self.assertEqual(pending, [])
        finally:
            release.set()
            deadline = time.monotonic() + 5
            while host.is_active(task_id) and time.monotonic() < deadline:
                time.sleep(0.02)

    def test_deep_host_restart_cannot_restore_or_repeat_surviving_child_fix(self):
        from orchestrator import service, task_api
        from orchestrator.tests.test_reviewed_task_api import ReviewedTaskOrderingTest

        config_resolver = ReviewedTaskOrderingTest._config
        order = self.order("deep_task", work_area={
            "workspace_path": self.primary, "primary": self.primary, "additional": [],
        })
        with mock.patch.object(service, "_direct_task_config", return_value=config_resolver()):
            status, response = self.request("POST", "/api/tasks", order)
        self.assertEqual(status, 201, response)
        task_id = response["task"]["id"]
        env = dict(os.environ)
        env.pop("ORCH_REAL_LLM", None)
        repo = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        env["PYTHONPATH"] = repo + os.pathsep + env.get("PYTHONPATH", "")
        owner = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(DEEP_HOST), self.home,
             task_id, textwrap.dedent(WORKER)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, env=env, start_new_session=True,
        )
        worker_pid = None
        try:
            pid_path = os.path.join(self.primary, "worker.pid")
            store = task_api.StandaloneTaskStore(self.home)

            def fix_started():
                try:
                    with open(pid_path) as handle:
                        if int(handle.read()) > 0:
                            return True
                except (OSError, ValueError):
                    pass
                lifecycle = store.lifecycle(task_id)
                if lifecycle["status"] == "paused":
                    self.fail("deep host paused before real fix: %s" % lifecycle)
                return False

            self._wait_until(fix_started, "real deep child fix", timeout=15)
            with open(pid_path) as handle:
                worker_pid = int(handle.read())
            child = store.related(task_id, "implementation", "a")
            child_id = child["id"]
            journal = os.path.join(self.home, "task-runtime", child_id, "execution.json")

            def recorded():
                with open(journal) as handle:
                    return json.load(handle).get("pgid") == worker_pid

            self._wait_until(recorded, "child worker durable identity")
            owner.kill()
            owner.wait(timeout=3)
            state_path = task_api.reviewed_state_path(self.home, child_id)
            with open(state_path, "rb") as handle:
                state_before = handle.read()
            work_file = os.path.join(self.primary, "standalone.py")
            work_size = os.path.getsize(work_file)
            restarted = task_api.DirectTaskHost(
                self.home,
                runner_factory=mock.Mock(side_effect=RunnerError("test stops after safe resumption")),
                poll_interval=0.001,
            )
            restarted.adopt_open_tasks(lambda _record: config_resolver)
            paused = store.lifecycle(task_id)
            self.assertEqual(paused["status"], "pausing")
            self.assertEqual(store.lifecycle(child_id)["status"], "pausing")
            self.assertFalse(restarted.lifecycle(task_id)["can_resume"])
            self.assertIsNotNone(restarted.lifecycle(task_id)["blocked_reason"])
            with self.assertRaises(task_api.TaskControlConflict):
                restarted.resume(task_id, config_resolver, paused["revision"])
            restarted.runner_factory.assert_not_called()
            self.assertTrue(restarted.is_active(task_id))
            self.assertTrue(restarted.is_active(child_id))
            with open(state_path, "rb") as handle:
                self.assertEqual(handle.read(), state_before)
            self._wait_until(lambda: os.path.getsize(work_file) > work_size,
                             "fix continues writing without being restored")
            self.assertEqual(len(store.records()), 3)
            self.assertEqual(store.related(task_id, "implementation", "a")["id"], child_id)

            os.killpg(worker_pid, signal.SIGKILL)
            self._wait_until(lambda: restarted.lifecycle(task_id)["can_resume"],
                             "safe host resumption after worker quiescence")
            paused = store.lifecycle(task_id)
            restarted.resume(task_id, config_resolver, paused["revision"])
            self._wait_until(lambda: not restarted.is_active(task_id)
                             and store.lifecycle(task_id)["status"] == "paused",
                             "same task family settles test continuation")
            self.assertEqual(restarted.runner_factory.call_count, 1)
            self.assertEqual(len(store.records()), 3)
            self.assertEqual(store.related(task_id, "implementation", "a")["id"], child_id)
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=3)
            if worker_pid is None:
                try:
                    with open(os.path.join(self.primary, "worker.pid")) as handle:
                        worker_pid = int(handle.read())
                except (OSError, ValueError):
                    pass
            if worker_pid is not None:
                try:
                    os.killpg(worker_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            owner.stderr.close()


if __name__ == "__main__":
    unittest.main()
