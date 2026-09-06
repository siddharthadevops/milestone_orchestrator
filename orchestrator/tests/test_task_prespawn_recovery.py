"""Native pre-spawn rejection is recoverable; opaque launch failure is not."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest

from orchestrator.runners import ActiveCallControl, RunnerError, SubprocessRunner
from orchestrator.task_execution import ExecutionBusy, TaskExecutionLease


class TaskPrespawnRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = self.temporary.name
        self.task_dir = os.path.join(self.workspace, "task")

    def _call(self, runner, transport, argv, **kwargs):
        if transport == "live":
            return runner._call_live_transport(
                "claude", "prompt", self.workspace, argv, argv,
                active_control=ActiveCallControl(), **kwargs,
            )
        return runner._call_template(
            "fake", "prompt", self.workspace, argv, **kwargs,
        )

    @staticmethod
    def _successful_argv(transport):
        if transport == "live":
            script = (
                "import json,sys; sys.stdin.readline(); "
                "print(json.dumps({'type':'result','result':'ok'}),flush=True)"
            )
        else:
            script = "print('ok')"
        return [sys.executable, "-c", script]

    def _rejected_then_repaired(self, transport, invalid):
        argv = self._successful_argv(transport)
        options = {}
        if invalid == "argv":
            argv.append("embedded\x00nul")
        elif invalid == "env":
            options["env"] = {"INVALID=KEY": "value"}
        elif invalid == "cwd":
            options["cwd"] = self.workspace + "\x00invalid"
        with TaskExecutionLease(self.task_dir) as lease:
            runner = SubprocessRunner({}, {}, execution_lease=lease, **options)
            # Exercise actual CPython Popen validation, not a mocked error.
            with self.assertRaises(RunnerError) as raised:
                self._call(runner, transport, argv)
            self.assertIsInstance(raised.exception.__cause__, ValueError)
            self.assertIs(raised.exception.worker_quiescent, True)
            self.assertIs(raised.exception.provider_dispatch_started, False)
            self.assertFalse(os.path.exists(lease.journal_path))
        # A new owner can acquire the same physical task and run the repaired
        # configuration; no hand-written deletion of durable evidence needed.
        with TaskExecutionLease(self.task_dir) as lease:
            runner = SubprocessRunner({}, {}, execution_lease=lease)
            result = self._call(runner, transport, self._successful_argv(transport))
            self.assertEqual(result.text.strip(), "ok")
            self.assertFalse(os.path.exists(lease.journal_path))

    def test_template_argv_validation_error_allows_recovery(self):
        self._rejected_then_repaired("template", "argv")

    def test_live_argv_validation_error_allows_recovery(self):
        self._rejected_then_repaired("live", "argv")

    def test_template_environment_validation_error_allows_recovery(self):
        self._rejected_then_repaired("template", "env")

    def test_live_environment_validation_error_allows_recovery(self):
        self._rejected_then_repaired("live", "env")

    def test_template_cwd_validation_error_allows_recovery(self):
        self._rejected_then_repaired("template", "cwd")

    def test_live_cwd_validation_error_allows_recovery(self):
        self._rejected_then_repaired("live", "cwd")

    def _opaque_factory_value_error(self, transport):
        children = []

        def factory(_context, argv, kwargs):
            children.append(subprocess.Popen(argv, **kwargs))
            # An opaque adapter can raise the same exception as Popen's
            # validation after successfully starting a real worker.
            raise ValueError("adapter rejected its post-launch configuration")

        try:
            with TaskExecutionLease(self.task_dir) as lease:
                runner = SubprocessRunner(
                    {}, {}, execution_lease=lease,
                    participant_process_factory=factory,
                )
                with self.assertRaises(RunnerError) as raised:
                    self._call(
                        runner, transport,
                        [sys.executable, "-c", "import time; time.sleep(30)"],
                        execution_context={"capability": "test"},
                    )
                self.assertIsNone(children[0].poll())
                self.assertFalse(getattr(raised.exception, "worker_quiescent", False))
                self.assertIsNot(
                    getattr(raised.exception, "provider_dispatch_started", None), False,
                )
                with open(lease.journal_path, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["phase"], "dispatching")
            with self.assertRaises(ExecutionBusy):
                TaskExecutionLease(self.task_dir).acquire()
        finally:
            for proc in children:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate(timeout=3)
        # Missing identity remains ambiguous even after this test's external
        # cleanup; a production host must not pretend it observed that cleanup.
        with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
            TaskExecutionLease(self.task_dir).acquire()

    def test_template_opaque_value_error_retains_live_worker_fence(self):
        self._opaque_factory_value_error("template")

    def test_live_opaque_value_error_retains_live_worker_fence(self):
        self._opaque_factory_value_error("live")


if __name__ == "__main__":
    unittest.main()
