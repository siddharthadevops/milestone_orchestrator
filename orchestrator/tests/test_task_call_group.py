"""Concurrent members share physical ownership, never each other's outcome fence."""

import json
import os
import signal
import subprocess
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from orchestrator import runners
from orchestrator.task_execution import ExecutionBusy, TaskExecutionLease
from orchestrator.tests import test_task_execution as execution_fixture


GROUP_OWNER = r'''
import os, signal, sys, threading
from orchestrator.runners import ActiveCallControl, SubprocessRunner
from orchestrator.task_execution import TaskExecutionLease
from orchestrator.tests.test_task_execution import WORKER
task_dir, workspace, mode, transport = sys.argv[1:]
with TaskExecutionLease(task_dir) as lease:
    def run(index, ready):
        directory = os.path.join(workspace, str(index))
        member = lease.member()
        record = member.record_worker
        def recorded(pid):
            if mode == "spawn-gap" and index == 1:
                os.kill(os.getpid(), signal.SIGKILL)
            record(pid)
            with open(os.path.join(directory, "recorded"), "w") as handle:
                handle.write(str(pid))
            ready.set()
        member.record_worker = recorded
        runner = SubprocessRunner({}, {}, execution_lease=member)
        worker_mode = "close-fds" if mode == "spawn-gap" else mode
        argv = [sys.executable, "-c", WORKER, directory, worker_mode, transport]
        if transport == "live":
            runner._call_live_transport(
                "claude", "prompt", directory, argv, argv,
                active_control=ActiveCallControl(),
            )
        else:
            runner._call_template("fake", "prompt", directory, argv)
    threads = []
    for index in range(2):
        ready = threading.Event()
        thread = threading.Thread(target=run, args=(index, ready))
        threads.append(thread)
        thread.start()
        if not ready.wait(5):
            raise RuntimeError("worker identity was not recorded")
    for thread in threads:
        thread.join()
'''


class TaskCallGroupLeaseTests(unittest.TestCase):
    setUp = execution_fixture.TaskExecutionLeaseTests.setUp
    _wait_until = execution_fixture.TaskExecutionLeaseTests._wait_until

    def _call(self, member, transport, workspace, name, fail=False, complete=None):
        payload = json.dumps({"status": "ok", "kind": "draft_slice_note",
                              "retained": name})
        script = "import json,sys\n"
        script += "with open(sys.argv[1], 'a') as handle: handle.write(%r)\n" % (name + "\n")
        if transport == "live":
            script += "sys.stdin.readline()\n"
            script += "print(json.dumps(%r), flush=True)\n" % {
                "type": "result", "is_error": fail,
                "result": "original failure " + name if fail else payload,
            }
        elif not fail:
            script += "print(%r, flush=True)\n" % payload
        if fail:
            script += "sys.stderr.write(%r); sys.exit(7)\n" % ("original failure " + name)
        argv = [sys.executable, "-c", script, os.path.join(workspace, "invocations")]
        native = runners.SubprocessRunner({}, {}, execution_lease=member)

        def physical_call(_family, prompt, directory, **_kwargs):
            if transport == "live":
                return native._call_live_transport(
                    "claude", prompt, directory, argv, argv,
                    active_control=runners.ActiveCallControl(),
                )
            return native._call_template("fake", prompt, directory, argv)

        prepared = SimpleNamespace(prompt="prompt", validate=lambda value: value,
                                   complete=complete)
        return runners.call_worker(
            SimpleNamespace(call=physical_call), "fake", "prompt",
            "draft_slice_note", workspace, prepare_call=lambda _error: prepared,
            single_attempt=True,
        )

    def test_member_completion_keeps_other_dispatch_evidence(self):
        for transport in ("template", "live"):
            with self.subTest(transport=transport):
                directory = os.path.join(self.temporary.name, transport)
                with TaskExecutionLease(directory) as lease:
                    unknown, completed = lease.member(), lease.member()
                    unknown.prepare_spawn({})
                    output, _result = self._call(completed, transport, directory, "completed")
                    self.assertEqual(output["retained"], "completed")
                    with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
                        lease.ensure_quiescent()
                with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
                    TaskExecutionLease(directory).acquire()

    def test_member_outcome_waits_for_own_quiescence(self):
        for transport in ("template", "live"):
            for fail in (False, True):
                with self.subTest(transport=transport, fail=fail):
                    self._independent_outcomes(transport, fail)

    def _independent_outcomes(self, transport, fail):
        pending, release = threading.Event(), threading.Event()
        delivered = {name: threading.Event() for name in ("held", "quiet")}
        values, errors, completions, held_pids = {}, {}, [], set()
        directory = os.path.join(self.temporary.name, transport + str(fail))
        lease = TaskExecutionLease(directory, poll_interval=0.005)
        real_observe = runners._process_group_quiescent

        def observe(pgid):
            if pgid in held_pids and not release.is_set():
                pending.set()
                return None
            return real_observe(pgid)

        def run(name, member):
            try:
                values[name] = self._call(
                    member, transport, directory, name, fail=fail and name == "held",
                    complete=lambda: completions.append(name),
                )
            except BaseException as exc:
                errors[name] = exc
            finally:
                delivered[name].set()

        with lease, mock.patch.object(
            runners, "_wait_for_process_group_quiescence", side_effect=observe,
        ), mock.patch.object(runners, "_process_group_quiescent", side_effect=observe):
            held, quiet = lease.member(), lease.member()
            record = held.record_worker

            def record_held(pid):
                held_pids.add(pid)
                record(pid)

            held.record_worker = record_held
            threads = [threading.Thread(target=run, args=(name, member), daemon=True)
                       for name, member in (("held", held), ("quiet", quiet))]
            try:
                for thread in threads:
                    thread.start()
                self.assertTrue(pending.wait(5), "member never reached quiescence fence")
                self.assertTrue(delivered["quiet"].wait(5), "sibling could not deliver independently")
                self.assertFalse(delivered["held"].wait(0.05))
                self.assertEqual(completions, ["quiet"])
                self.assertEqual(values["quiet"][0]["retained"], "quiet")
                self.assertEqual(errors, {})
                with self.assertRaises(ExecutionBusy):
                    lease.ensure_quiescent()
            finally:
                release.set()
                for thread in threads:
                    thread.join(timeout=5)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(completions, ["quiet", "held"])
            if fail:
                self.assertIsInstance(errors["held"], runners.RunnerError)
                self.assertIn("original failure held", str(errors["held"]))
            else:
                self.assertEqual(errors, {})
                self.assertEqual(values["held"][0]["retained"], "held")
            lease.ensure_quiescent()
            with open(os.path.join(directory, "invocations")) as handle:
                self.assertCountEqual(handle.read().splitlines(), ["held", "quiet"])

    def test_group_quiescence_survives_owner_death(self):
        for transport in ("template", "live"):
            for mode in ("inherit", "close-fds", "descendant", "spawn-gap"):
                with self.subTest(transport=transport, mode=mode):
                    self._owner_death(transport, mode)

    def _owner_death(self, transport, mode):
        directory = os.path.join(self.temporary.name, transport, mode)
        task_dir = os.path.join(directory, "task")
        workspaces = [os.path.join(directory, str(index)) for index in range(2)]
        for workspace in workspaces:
            os.makedirs(workspace)
        env = dict(os.environ)
        env.pop("ORCH_REAL_LLM", None)
        repo = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        env["PYTHONPATH"] = repo + os.pathsep + env.get("PYTHONPATH", "")
        owner = subprocess.Popen(
            [sys.executable, "-c", GROUP_OWNER, task_dir, directory, mode, transport],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, env=env, start_new_session=True,
        )
        pids = []
        try:
            for workspace in workspaces:
                path = os.path.join(workspace, "worker.pid")
                self._wait_until(lambda: os.path.exists(path) and os.path.getsize(path),
                                 "concurrent worker start")
                with open(path) as handle:
                    pids.append(int(handle.read()))
                marker = "descendant.pid" if mode == "descendant" else "recorded"
                if mode != "spawn-gap":
                    self._wait_until(lambda: os.path.exists(os.path.join(workspace, marker)),
                                     "worker evidence")
            if mode == "spawn-gap":
                self._wait_until(lambda: owner.poll() is not None, "death during dispatch")
            else:
                owner.kill()
            owner.wait(timeout=3)
            self.assertEqual(owner.returncode, -signal.SIGKILL)
            if mode == "descendant":
                for pid in pids:
                    os.kill(pid, signal.SIGKILL)
            for workspace in workspaces:
                heartbeat = os.path.join(workspace, "heartbeat")
                before = os.path.getsize(heartbeat)
                self._wait_until(lambda: os.path.getsize(heartbeat) > before,
                                 "surviving group writes")
            with self.assertRaises(ExecutionBusy):
                TaskExecutionLease(task_dir).acquire()
            os.killpg(pids[0], signal.SIGKILL)
            self._wait_until(lambda: runners._process_group_quiescent(pids[0]) is True,
                             "first member quiescence")
            with self.assertRaises(ExecutionBusy):
                TaskExecutionLease(task_dir).acquire()
            self.assertIs(runners._process_group_quiescent(pids[1]), False)
            os.killpg(pids[1], signal.SIGKILL)
            self._wait_until(lambda: runners._process_group_quiescent(pids[1]) is True,
                             "second member quiescence")
            if mode == "spawn-gap":
                with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
                    TaskExecutionLease(task_dir).acquire()
            else:
                with TaskExecutionLease(task_dir):
                    pass
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=3)
            for workspace in workspaces:
                try:
                    with open(os.path.join(workspace, "worker.pid")) as handle:
                        os.killpg(int(handle.read()), signal.SIGKILL)
                except (OSError, ValueError):
                    pass
            owner.stderr.close()


if __name__ == "__main__":
    unittest.main()
