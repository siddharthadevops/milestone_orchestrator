"""Slice 6 focused proof for deep documentation and child authority."""

import copy
from concurrent import futures
from pathlib import Path
import threading
import time
import unittest
from unittest import mock

from orchestrator import access, contracts, registry, runners, service
from orchestrator import task_api, tasks
from orchestrator import state as st
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
        self.target_task_id = None
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
                and (
                    self.target_task_id is None
                    or self.target_task_id == task_id
                )
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


class _LateResultRunner:
    """Hold one physical result until Stop has been accepted."""

    def __init__(self, script):
        self.inner = runners.MockRunner(script)
        self.entered = threading.Event()
        self.release = threading.Event()

    @property
    def calls(self):
        return self.inner.calls

    def call(self, *args, **kwargs):
        self.entered.set()
        if not self.release.wait(5):
            raise AssertionError("timed out holding late provider result")
        return self.inner.call(*args, **kwargs)


class DeepTaskDocumentationTest(unittest.TestCase):
    setUp = api_tests.TaskApiTest.setUp
    directory = api_tests.TaskApiTest.directory
    start_server = api_tests.TaskApiTest.start_server
    request = api_tests.TaskApiTest.request
    order = api_tests.TaskApiTest.order
    project = api_tests.TaskApiTest.project
    member = staticmethod(api_tests.TaskApiTest.member)
    wait_record = api_tests.TaskApiTest.wait_record
    _age_stored_record = staticmethod(api_tests.TaskApiTest._age_stored_record)
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

    def _admit_parent(self, workspace, configuration=None):
        order = tasks.validate_order(
            self._deep_order(workspace, configuration)
        )
        return task_api.StandaloneTaskStore(self.home).admit(
            order, {}, workspace
        )

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

    def test_one_public_documentation_child_owns_gate_before_implementation(self):
        workspace = self._repo("deep")
        queued = [
            runners.MockRunner(reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_DRAFT_SLICE_NOTE
            )),
            runners.MockRunner(reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_IMPLEMENT
            )),
        ]
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: queued.pop(0),
            poll_interval=0.001,
        )
        self.start_server(host)
        configuration = {
            "documentation": {"max_fix_loops": 4},
            "implementation": {
                "max_fix_loops": 9,
                "implementation_size_control": {
                    "soft_lines": 600,
                    "hard_lines": 900,
                    "unconfirmed_grace_s": 10,
                    "confirmed_grace_s": 20,
                },
            },
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
            parent = self.wait_record(parent["id"])
            child = task_api.StandaloneTaskStore(self.home).related(
                parent["id"], "documentation", None
            )

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
        status, projected = self.request("GET", "/api/tasks/%s" % child["id"])
        self.assertEqual(status, 200, projected)
        self.assertEqual(projected["task"]["parent"], child["parent"])
        self.assertEqual(parent["result"]["status"], "success")
        self.assertEqual(parent["order"]["configuration"]["implementation"]
                         ["max_fix_loops"], 9)
        self.assertIn(
            "implementation_size_control",
            parent["order"]["configuration"]["implementation"],
        )
        self.assertNotIn("implementation_size_control", child_config)
        lifecycle = st.load(task_api.reviewed_state_path(self.home, child["id"]))
        self.assertFalse(any(
            event["type"].startswith("implementation_size_")
            for event in lifecycle["events"]
        ))
        self.assertFalse(Path(
            task_api.reviewed_state_path(self.home, parent["id"])
        ).exists())
        records = task_api.StandaloneTaskStore(self.home).records()
        self.assertEqual(len(records), 3)
        self.assertEqual(
            [record.get("parent", {}).get("phase") for record in records[1:]],
            ["documentation", "implementation"],
        )

    def test_bound_partial_size_defaults_resolve_before_deep_admission(self):
        workspace = self._repo("deep-bound-defaults")
        self.project("deep-defaults", workspace)
        defaults = {
            "git": {"enabled": True},
            "implementation_size_control": {
                "soft_lines": 700,
                "hard_lines": 1000,
                "unconfirmed_grace_s": 11,
                "confirmed_grace_s": 21,
            },
        }
        service.update_project(
            self.home, "deep-defaults", {"defaults": defaults}
        )
        host = api_tests.NoopHost()
        self.start_server(host)
        order = self.order("deep_task", work_area={
            "project": "deep-defaults", "work_area": "main",
        })
        order["configuration"] = {
            "implementation": {
                "implementation_size_control": {"soft_lines": 800}
            }
        }

        status, body = self.request("POST", "/api/tasks", order)
        self.assertEqual(status, 201, body)
        parent = body["task"]
        size = parent["order"]["configuration"]["implementation"][
            "implementation_size_control"
        ]
        self.assertEqual(size, {
            "soft_lines": 800,
            "hard_lines": 1000,
            "unconfirmed_grace_s": 11,
            "confirmed_grace_s": 21,
        })
        self.assertNotIn(
            "implementation_size_control",
            parent["order"]["configuration"]["documentation"],
        )
        self.assertEqual(host.started, [parent["id"]])

    def test_invalid_policy_access_paths_git_and_busy_tree_refuse_before_admission(self):
        workspace = self._repo("deep-refusals")
        host = api_tests.NoopHost()
        self.start_server(host)
        base = self._deep_order(workspace)

        def refuses(order, expected_status, expected_code, headers=None, repo=None):
            before_records = task_api.StandaloneTaskStore(self.home).records()
            before_started = list(host.started)
            before_tree = self._git(repo, "status", "--short") if repo else None
            status, body = self.request(
                "POST", "/api/tasks", order, headers=headers
            )
            self.assertEqual(
                (status, body["error"]),
                (expected_status, expected_code),
                body,
            )
            self.assertEqual(
                task_api.StandaloneTaskStore(self.home).records(), before_records
            )
            self.assertEqual(host.started, before_started)
            if repo:
                self.assertEqual(self._git(repo, "status", "--short"), before_tree)

        invalid = (
            ({"documentation": {"producer": {
                "task_executor": "missing",
            }}}, tasks.UNKNOWN_TASK_EXECUTOR),
            ({"implementation": {"producer": {
                "task_executor": "missing",
            }}}, tasks.UNKNOWN_TASK_EXECUTOR),
            ({"documentation": {"max_fix_loops": -1}},
             tasks.INVALID_TASK_REQUEST),
            ({"documentation": {"implementation_size_control": {}}},
             tasks.INVALID_TASK_REQUEST),
            ({"implementation": {
                "producer": {"task_executor": "brainstorming"},
                "implementation_size_control": {},
            }}, tasks.INVALID_TASK_REQUEST),
        )
        for configuration, code in invalid:
            with self.subTest(configuration=configuration):
                order = copy.deepcopy(base)
                order["configuration"] = configuration
                refuses(order, 400, code, repo=workspace)

        for field, value in (
            ("reference_documents", [str(Path(self.outside) / "secret.md")]),
            ("output_directory", self.outside),
        ):
            with self.subTest(path_field=field):
                order = copy.deepcopy(base)
                order["request"][field] = value
                refuses(order, 400, tasks.INVALID_TASK_REQUEST, repo=workspace)

        private = self._repo("deep-private")
        self.project("deep-private", private)
        private_order = self.order("deep_task", work_area={
            "project": "deep-private", "work_area": "main",
        })
        refuses(private_order, 403, service.FORBIDDEN, self.member(), private)
        refuses(base, 403, service.FORBIDDEN, self.member(), workspace)

        disabled = self._repo("deep-disabled")
        self.project("deep-disabled", disabled)
        service.update_project(self.home, "deep-disabled", {
            "defaults": {"git": {"enabled": False}}
        })
        disabled_order = self.order("deep_task", work_area={
            "project": "deep-disabled", "work_area": "main",
        })
        refuses(
            disabled_order, 400, tasks.INVALID_TASK_REQUEST, repo=disabled
        )

        nonrepo = self.directory("deep-nonrepo")
        refuses(
            self._deep_order(nonrepo), 400, service.PRIMARY_NOT_REPO_ROOT
        )

        host = api_tests.NoopHost()
        host.owns_workspace = lambda _workspace: True
        self.start_server(host)
        refuses(base, 409, service.WORK_AREA_BUSY, repo=workspace)

    def test_related_admission_crash_windows_and_races_reuse_one_child(self):
        for window in ("before", "after"):
            with self.subTest(window=window):
                workspace = self._repo("deep-admission-%s" % window)
                store = task_api.StandaloneTaskStore(self.home)
                parent = self._admit_parent(workspace)
                child_order = task_api.DirectTaskHost._deep_child_order(parent)
                real_cas = store._store.cas

                def crash_cas(key, expected_revision, value):
                    if key == task_api.task_key(parent["id"]):
                        return real_cas(key, expected_revision, value)
                    if window == "after":
                        real_cas(key, expected_revision, value)
                    raise RuntimeError("%s related admission" % window)

                with mock.patch.object(store._store, "cas", side_effect=crash_cas):
                    with registry.locked(self.home), self.assertRaisesRegex(
                        RuntimeError, "%s related admission" % window
                    ):
                        store.admit_related_locked(
                            parent["id"], "documentation", None,
                            child_order, {}, workspace,
                        )
                first = store.related(parent["id"], "documentation", None)
                self.assertEqual(first is None, window == "before")

                barrier = threading.Barrier(4)

                def recover():
                    barrier.wait()
                    with registry.locked(self.home):
                        return store.admit_related_locked(
                            parent["id"], "documentation", None,
                            child_order, {}, workspace,
                        )

                with futures.ThreadPoolExecutor(4) as pool:
                    recovered = [pool.submit(recover) for _ in range(4)]
                    recovered = [future.result() for future in recovered]
                child_id = recovered[0]["id"]
                self.assertEqual({record["id"] for record in recovered}, {child_id})
                related = [
                    record for record in store.records()
                    if record.get("parent") == {
                        "task_id": parent["id"],
                        "phase": "documentation",
                        "part": None,
                    }
                ]
                self.assertEqual([record["id"] for record in related], [child_id])

                host = task_api.DirectTaskHost(
                    self.home,
                    store=store,
                    runner_factory=lambda *_args: self.fail(
                        "concurrent recovery began a provider lifecycle"
                    ),
                )
                entered = threading.Event()
                release = threading.Event()
                starts = []

                def hold_run(task_id, _resolver):
                    try:
                        starts.append(task_id)
                        entered.set()
                        release.wait(5)
                    finally:
                        with host._lock:
                            host._active.pop(task_id, None)

                start_barrier = threading.Barrier(4)

                def start_recovery():
                    start_barrier.wait()
                    return host.start(
                        related[0],
                        reviewed_tests.ReviewedTaskOrderingTest._config,
                        parent_task_id=parent["id"],
                    )

                with mock.patch.object(host, "_run", side_effect=hold_run):
                    with futures.ThreadPoolExecutor(4) as pool:
                        attempts = [pool.submit(start_recovery) for _ in range(4)]
                        attempts = [future.result() for future in attempts]
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(
                        sum(thread is not None for thread in attempts), 1
                    )
                    release.set()
                    for thread in attempts:
                        if thread is not None:
                            thread.join(5)
                self.assertEqual(starts, [child_id])

    def test_stop_parent_fails_active_documentation_child_before_releasing_work_area(self):
        workspace = self._repo("deep-stop-late-return")
        runner = _LateResultRunner(
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
            self.assertTrue(runner.entered.wait(5))
            child = self._wait_child(parent_id, terminal=False)
            status, stopped = self.request(
                "POST", "/api/tasks/%s/stop" % parent_id, {}
            )
            self.assertEqual((status, stopped["state"]), (200, "stopping"))
            self.assertTrue(host.owns_workspace(workspace))
            self.assertIsNone(
                task_api.StandaloneTaskStore(self.home).record(parent_id)["result"]
            )
            runner.release.set()
            parent = self.wait_record(parent_id)
            child = self.wait_record(child["id"])

        self.assertEqual(parent["result"]["status"], "failure")
        self.assertEqual(child["result"]["status"], "failure")
        stop_reason = "stopped by %s" % access.ADMIN_EMAIL
        self.assertEqual(parent["result"]["reason"], stop_reason)
        self.assertEqual(child["result"]["reason"], stop_reason)
        self.assertEqual(len(runner.calls), 1)
        for field in (
            "duration_s", "token_usage", "token_usage_partial",
            "cost", "cost_partial",
        ):
            self.assertEqual(parent["result"][field], child["result"][field])
        self.assertFalse(host.owns_workspace(workspace))
        self.assertIsNone(
            task_api.StandaloneTaskStore(self.home).related(
                parent_id, "implementation", "a"
            )
        )

    def test_restart_after_documentation_reuses_child_and_runs_implementation(self):
        workspace = self._repo("deep-restart")
        store = task_api.StandaloneTaskStore(self.home)
        parent = self._admit_parent(workspace)
        with registry.locked(self.home):
            child = store.admit_related_locked(
                parent["id"], "documentation", None,
                task_api.DirectTaskHost._deep_child_order(parent), {}, workspace,
            )
        artifact = Path(workspace) / "docs" / "slice-01.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("# Reviewed slice\n", encoding="utf-8")
        child_result = {
            "status": "success",
            "duration_s": 3.5,
            "token_usage": {
                "input_tokens": 2, "cached_input_tokens": 0,
                "output_tokens": 1, "reasoning_output_tokens": 0,
                "total_tokens": 3,
            },
            "token_usage_partial": False,
            "cost": {"api_usd": 0.25, "real_usd": 0.1},
            "cost_partial": False,
            "native_result": {
                "production_result": {"artifact": "docs/slice-01.md"},
                "review_evidence": {"reviews": ["kept"]},
                "gate_commit": "kept-on-child",
            },
        }
        store.record_result(child["id"], child_result)
        runner = runners.MockRunner(
            reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_IMPLEMENT
            )
        )
        host = task_api.DirectTaskHost(
            self.home,
            store=store,
            runner_factory=lambda *_args: runner,
            poll_interval=0.001,
        )
        outcome = host.adopt_open_tasks(
            lambda _record: reviewed_tests.ReviewedTaskOrderingTest._config
        )
        self.assertEqual(outcome, {"adopted": [parent["id"]], "closed": []})
        terminal = self.wait_record(parent["id"])
        self.assertEqual(
            store.related(parent["id"], "documentation", None)["id"], child["id"]
        )
        implementation = store.related(parent["id"], "implementation", "a")
        self.assertIsNotNone(implementation)
        self.assertEqual(terminal["result"]["status"], "success")

        self.start_server(host)
        status, projected = self.request("GET", "/api/tasks/%s" % child["id"])
        self.assertEqual(status, 200, projected)
        self.assertEqual(projected["task"]["parent"], child["parent"])
        self.assertEqual(store.record(child["id"])["result"], child_result)
        self.assertNotIn("gate_commit", terminal["result"].get("native_result") or {})

        legacy_workspace = self.directory("deep-legacy-worker")
        legacy = store.admit(
            tasks.validate_order(self.order(work_area={
                "workspace_path": legacy_workspace,
                "primary": legacy_workspace,
                "additional": [],
            })),
            {"worker": {"agent": "codex"}},
            legacy_workspace,
        )
        aged = copy.deepcopy(legacy)
        aged["order"]["task_executor"] = "worker"
        aged["order"].pop("staffing_session", None)
        self._age_stored_record(store, aged)
        status, projected = self.request("GET", "/api/tasks/%s" % aged["id"])
        self.assertEqual(status, 200, projected)
        self.assertEqual(projected["task"]["order"]["task_executor"], "agent_call")
        self.assertNotIn("parent", projected["task"])
        durable = store.record(aged["id"])
        self.assertEqual(durable["order"]["task_executor"], "worker")
        self.assertNotIn("staffing_session", durable["order"])
        self.assertNotIn("parent", durable)

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

    def test_parent_terminal_write_and_stop_choose_one_ordered_outcome(self):
        workspace = self._repo("deep-parent-terminal-fence")
        parent = self._admit_parent(workspace)
        store = _PausingResultStore(self.home)
        store.target_task_id = parent["id"]
        host = task_api.DirectTaskHost(
            self.home,
            store=store,
            runner_factory=lambda _config, _workspace: runners.MockRunner([]),
            poll_interval=0.001,
        )
        host.start(parent, reviewed_tests.ReviewedTaskOrderingTest._config)
        self.assertTrue(store.write_entered.wait(5))
        self.assertEqual(store.paused_task_id, parent["id"])

        stopped = []
        stop_thread = threading.Thread(
            target=lambda: stopped.append(
                host.stop(parent["id"], "late competing stop")
            ),
            daemon=True,
        )
        stop_thread.start()
        time.sleep(0.05)
        self.assertTrue(stop_thread.is_alive())
        store.allow_write.set()
        stop_thread.join(5)
        self.assertFalse(stop_thread.is_alive())

        terminal = self.wait_record(parent["id"])
        child = store.related(parent["id"], "documentation", None)
        self.assertEqual(stopped, [False])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(
            terminal["result"]["reason"], child["result"]["reason"]
        )
        self.assertNotEqual(terminal["result"]["reason"], "late competing stop")
        self.assertFalse(host.owns_workspace(workspace))


if __name__ == "__main__":
    unittest.main()
