"""Slice 6 focused proof for deep documentation and child authority."""

from pathlib import Path
import threading
import time
import unittest
from unittest import mock

from orchestrator import contracts, runners, service, task_api, tasks
from orchestrator.tests import test_reviewed_task_api as reviewed_tests
from orchestrator.tests import test_task_api as api_tests


class _PausingResultStore(task_api.StandaloneTaskStore):
    """Expose the first host-thread terminal write before it reaches storage."""

    def __init__(self, home):
        super().__init__(home)
        self.write_entered = threading.Event()
        self.allow_write = threading.Event()
        self.competing_write = threading.Event()
        self.competing_write_finished = threading.Event()
        self.paused_task_id = None
        self._paused_thread = None
        self._pause_lock = threading.Lock()

    def _before_result(self, task_id):
        current = threading.get_ident()
        pause = False
        compete = False
        with self._pause_lock:
            if (
                self.paused_task_id is None
                and threading.current_thread().name.startswith("task-")
            ):
                self.paused_task_id = task_id
                self._paused_thread = current
                pause = True
            elif (
                task_id == self.paused_task_id
                and current != self._paused_thread
                and not self.allow_write.is_set()
            ):
                compete = True
        if pause:
            self.write_entered.set()
            if not self.allow_write.wait(5):
                raise AssertionError("timed out holding terminal task write")
        if compete:
            self.competing_write.set()
        return compete

    def record_result(self, task_id, result):
        compete = self._before_result(task_id)
        try:
            return super().record_result(task_id, result)
        finally:
            if compete:
                self.competing_write_finished.set()

    def record_result_locked(self, task_id, result):
        self._before_result(task_id)
        return super().record_result_locked(task_id, result)


class DeepTaskDocumentationTest(unittest.TestCase):
    setUp = api_tests.TaskApiTest.setUp
    directory = api_tests.TaskApiTest.directory
    start_server = api_tests.TaskApiTest.start_server
    request = api_tests.TaskApiTest.request
    order = api_tests.TaskApiTest.order
    wait_record = api_tests.TaskApiTest.wait_record
    _git = staticmethod(reviewed_tests.ReviewedTaskOrderingTest._git)
    _repo = reviewed_tests.ReviewedTaskOrderingTest._repo

    def _deep_order(self, workspace, configuration=None):
        order = self.order("deep_task", work_area={
            "workspace_path": workspace,
            "primary": workspace,
            "additional": [],
        })
        if configuration is not None:
            order["configuration"] = configuration
        return order

    def _wait_child(self, parent_id, terminal=None):
        store = task_api.StandaloneTaskStore(self.home)
        deadline = time.time() + 5
        while time.time() < deadline:
            child = store.related(parent_id, "documentation", None)
            if child is not None and (
                terminal is None
                or (child["result"] is not None) == terminal
            ):
                return child
            time.sleep(0.01)
        self.fail("documentation child did not reach expected state")

    def test_catalogue_api_and_panel_publish_independent_deep_policies(self):
        catalogue = tasks.task_executor_catalogue()
        self.assertEqual(
            [entry["id"] for entry in catalogue],
            ["agent_call", "brainstorming", "reviewed_task", "deep_task"],
        )
        schema = catalogue[-1]["configuration_schema"]
        self.assertEqual(set(schema), {"documentation", "implementation"})
        self.assertNotIn("task_kind", schema["documentation"]["properties"])
        self.assertNotIn(
            "implementation_size_control",
            schema["documentation"]["properties"],
        )
        self.assertIn(
            "implementation_size_control",
            schema["implementation"]["properties"],
        )
        resolved = tasks.resolve_deep_task_configuration(
            {
                "documentation": {"max_fix_loops": 3},
                "implementation": {
                    "producer": {"task_executor": "brainstorming"}
                },
            },
            defaults={"max_rounds_per_family": 7},
        )
        self.assertEqual(resolved["documentation"]["max_fix_loops"], 3)
        self.assertEqual(resolved["implementation"]["max_rounds_per_family"], 7)
        self.assertNotIn(
            "implementation_size_control", resolved["implementation"]
        )
        status, body = self.request("GET", "/api/task-executors")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["task_executors"], catalogue)
        panel = Path(__file__).resolve().parents[1] / "static" / "panel.html"
        task_ui = panel.read_text(encoding="utf-8").split(
            "/* ---- standalone task ordering", 1
        )[1].split("/* ---- new brainstorming:", 1)[0]
        self.assertNotIn('"deep_task"', task_ui)

    def test_one_public_documentation_child_owns_gate_and_parent_stays_open(self):
        workspace = self._repo("deep")
        runner = runners.MockRunner(
            reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_DRAFT_SLICE_NOTE
            )
        )
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: runner,
            poll_interval=0.001,
        )
        self.start_server(host)
        configuration = {
            "documentation": {"max_fix_loops": 4},
            "implementation": {"max_fix_loops": 9},
        }
        with mock.patch.object(
            service,
            "_direct_task_config",
            return_value=reviewed_tests.ReviewedTaskOrderingTest._config(),
        ):
            status, body = self.request(
                "POST", "/api/tasks", self._deep_order(workspace, configuration)
            )
            self.assertEqual(status, 201, body)
            parent = body["task"]
            child = self._wait_child(parent["id"], terminal=True)

        self.assertEqual(child["order"]["task_executor"], "reviewed_task")
        self.assertEqual(
            child["parent"],
            {"task_id": parent["id"], "phase": "documentation", "part": None},
        )
        self.assertEqual(child["order"]["request"], parent["order"]["request"])
        self.assertEqual(child["order"]["staffing_session"], None)
        child_config = child["order"]["configuration"]
        self.assertEqual(child_config["task_kind"], "draft_slice_note")
        self.assertEqual(child_config["max_fix_loops"], 4)
        self.assertEqual(child["result"]["status"], "success")
        self.assertTrue(child["result"]["native_result"]["gate_commit"])
        parent = task_api.StandaloneTaskStore(self.home).record(parent["id"])
        self.assertIsNone(parent["result"])
        self.assertEqual(parent["order"]["configuration"]["implementation"]
                         ["max_fix_loops"], 9)
        self.assertEqual(len(task_api.StandaloneTaskStore(self.home).records()), 2)

        status, body = self.request("DELETE", "/api/tasks/%s" % child["id"])
        self.assertEqual(status, 409, body)
        status, body = self.request("POST", "/api/tasks/%s/stop" % parent["id"])
        self.assertEqual((status, body["state"]), (200, "stopping"))
        terminal = self.wait_record(parent["id"])
        self.assertEqual(terminal["result"]["status"], "failure")
        for field in (
            "duration_s", "token_usage", "token_usage_partial",
            "cost", "cost_partial",
        ):
            self.assertEqual(terminal["result"][field], child["result"][field])

    def test_parent_stop_cannot_replace_a_settling_child_result(self):
        workspace = self._repo("deep-stop-settlement")
        runner = runners.MockRunner(
            reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_DRAFT_SLICE_NOTE
            )
        )
        store = _PausingResultStore(self.home)
        host = task_api.DirectTaskHost(
            self.home,
            store=store,
            runner_factory=lambda _config, _workspace: runner,
            poll_interval=0.001,
        )
        self.start_server(host)
        with mock.patch.object(
            service,
            "_direct_task_config",
            return_value=reviewed_tests.ReviewedTaskOrderingTest._config(),
        ):
            status, body = self.request(
                "POST", "/api/tasks", self._deep_order(workspace)
            )
            self.assertEqual(status, 201, body)
            parent_id = body["task"]["id"]
            self.assertTrue(store.write_entered.wait(5))

            stopped = []
            stop_thread = threading.Thread(
                target=lambda: stopped.append(
                    host.stop(parent_id, "stop during child settlement")
                ),
                daemon=True,
            )
            stop_thread.start()
            competing = store.competing_write.wait(0.1)
            if competing:
                self.assertTrue(store.competing_write_finished.wait(5))
            store.allow_write.set()
            stop_thread.join(5)
            self.assertFalse(stop_thread.is_alive())

            parent = self.wait_record(parent_id)
            child = store.record(store.paused_task_id)

        self.assertEqual(stopped, [True])
        self.assertFalse(competing)
        self.assertEqual(parent["result"]["status"], "failure")
        self.assertEqual(
            parent["result"]["reason"], "stop during child settlement"
        )
        self.assertGreater(child["result"]["duration_s"], 0.0)
        for field in (
            "duration_s", "token_usage", "token_usage_partial",
            "cost", "cost_partial",
        ):
            self.assertEqual(parent["result"][field], child["result"][field])


if __name__ == "__main__":
    unittest.main()
