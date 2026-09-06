"""Physical outcomes wait for quiescence before any post-call repository work."""

import json
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from orchestrator import registry, runners, task_api
from orchestrator.task_execution import TaskExecutionLease


class TaskResultQuiescenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = os.path.join(self.temporary.name, "home")
        self.workspace = os.path.join(self.temporary.name, "workspace")
        os.makedirs(self.workspace)
        self.store = task_api.StandaloneTaskStore(self.home)
        self.record = self.store.admit({
            "task_executor": "agent_call",
            "request": {
                "work_area": {"workspace_path": self.workspace,
                              "primary": self.workspace, "additional": []},
                "request": "Verify the physical outcome boundary.",
                "context": {}, "reference_documents": [],
            },
        }, {}, self.workspace)

    def _wait_for_outcome(self, transport, fail=False, cancel=False):
        pending = threading.Event()
        release = threading.Event()
        delivered = threading.Event()
        pending_calls, completions, values, errors = [], [], [], []
        task_id = self.record["id"]
        invocations_path = os.path.join(self.workspace, "invocations")

        def on_pending():
            pending_calls.append(True)
            with registry.locked(self.home):
                self.store.pause_locked(
                    task_id, "Physical cleanup is still unconfirmed",
                    source="error", pending=True,
                )
                if cancel:
                    self.store.record_stop_locked(task_id, "Cancel while stopping")
            pending.set()

        def complete():
            # This is the callback where repository reconciliation/restore
            # happens. It must not run while the physical journal survives.
            completions.append(os.path.exists(lease.journal_path))
            return {"accept_reply": True}

        payload = json.dumps({"status": "ok", "kind": "draft_slice_note",
                              "retained": "the original physical answer"})
        script = (
            "import json,sys\n"
            "with open(sys.argv[1], 'a') as handle: handle.write('one\\n')\n"
        )
        if transport == "live":
            script += "sys.stdin.readline()\n"
            script += "print(json.dumps(%r), flush=True)\n" % {
                "type": "result", "is_error": fail,
                "result": "native failure sentinel" if fail else payload,
            }
        elif not fail:
            script += "print(%r, flush=True)\n" % payload
        if fail:
            script += "sys.stderr.write('native failure sentinel\\n'); sys.exit(7)\n"
        argv = [sys.executable, "-c", script, invocations_path]
        lease = TaskExecutionLease(
            os.path.join(self.home, "task-runtime", task_id),
            on_pending=on_pending, poll_interval=0.005,
        )
        native = runners.SubprocessRunner({}, {}, execution_lease=lease)

        def physical_call(_family, prompt, workspace, **_kwargs):
            if transport == "live":
                return native._call_live_transport(
                    "claude", prompt, workspace, argv, argv,
                    active_control=runners.ActiveCallControl(),
                )
            return native._call_template("fake", prompt, workspace, argv)

        prepared = SimpleNamespace(
            prompt="test prompt", validate=lambda output: output,
            complete=complete,
        )

        def run():
            try:
                values.append(runners.call_worker(
                    SimpleNamespace(call=physical_call), "fake", "prompt",
                    "draft_slice_note", self.workspace,
                    prepare_call=lambda _error: prepared, single_attempt=True,
                ))
            except BaseException as exc:
                errors.append(exc)
            finally:
                delivered.set()

        with mock.patch.object(
            runners, "_wait_for_process_group_quiescence", return_value=False,
        ), mock.patch.object(
            runners, "_process_group_quiescent",
            side_effect=lambda _pgid: True if release.is_set() else None,
        ), lease:
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            try:
                self.assertTrue(pending.wait(5), "cleanup did not report pending")
                self.assertFalse(delivered.wait(0.05), "outcome escaped the barrier")
                self.assertEqual(completions, [])
                self.assertEqual(values, [])
                self.assertEqual(errors, [])
                self.assertTrue(os.path.exists(lease.journal_path))
                self.assertEqual(self.store.lifecycle(task_id)["status"], "pausing")
                if cancel:
                    self.assertEqual(self.store.stop_reason(task_id), "Cancel while stopping")
                # The physical command has already run once. Neither waiting
                # nor a durable Cancel authorizes a second provider attempt.
                with open(invocations_path, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), "one\n")
            finally:
                release.set()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), "cleanup did not release the outcome")
            self.assertTrue(delivered.is_set())
            self.assertFalse(os.path.exists(lease.journal_path))
            self.assertEqual(pending_calls, [True])
            self.assertEqual(completions, [False])
            with open(invocations_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "one\n")
            if fail:
                self.assertEqual(values, [])
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], runners.RunnerError)
                self.assertIn("native failure sentinel", str(errors[0]))
            else:
                self.assertEqual(errors, [])
                self.assertEqual(len(values), 1)
                output, result = values[0]
                self.assertEqual(output["retained"], "the original physical answer")
                self.assertEqual(result.text, payload + ("\n" if transport == "template" else ""))

    def test_template_success_waits_before_completion_callback(self):
        self._wait_for_outcome("template")

    def test_live_success_waits_before_completion_callback(self):
        self._wait_for_outcome("live")

    def test_template_error_waits_and_preserves_the_original_failure(self):
        self._wait_for_outcome("template", fail=True)

    def test_live_error_waits_and_preserves_the_original_failure(self):
        self._wait_for_outcome("live", fail=True)

    def test_template_durable_cancel_cannot_bypass_physical_quiescence(self):
        self._wait_for_outcome("template", cancel=True)

    def test_live_durable_cancel_cannot_bypass_physical_quiescence(self):
        self._wait_for_outcome("live", cancel=True)


if __name__ == "__main__":
    unittest.main()
