"""Slice 5 conformance for standalone reviewed-task ordering."""

import copy
import os
import subprocess
import threading
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import runners, service, task_api, tasks
from orchestrator import state as st
from orchestrator.tests import test_task_api as _task_api_tests
from orchestrator.tests.test_brainstorming_slice_production import (
    suite_checkpoint_response,
)
from orchestrator.tests.test_driver_mock import (
    canonical_skeleton_document,
    make_config,
    ok,
    report,
    step,
    write_file,
)


NoopHost = _task_api_tests.NoopHost


class ReviewedTaskOrderingTest(unittest.TestCase):
    # Reuse the generic HTTP harness without inheriting its test cases.
    setUp = _task_api_tests.TaskApiTest.setUp
    directory = _task_api_tests.TaskApiTest.directory
    start_server = _task_api_tests.TaskApiTest.start_server
    request = _task_api_tests.TaskApiTest.request
    order = _task_api_tests.TaskApiTest.order
    project = _task_api_tests.TaskApiTest.project
    wait_record = _task_api_tests.TaskApiTest.wait_record
    _age_stored_record = staticmethod(
        _task_api_tests.TaskApiTest._age_stored_record
    )

    @staticmethod
    def _git(workspace, *args):
        return subprocess.run(
            ("git",) + args,
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _repo(self, name):
        workspace = self.directory(name)
        self._git(workspace, "init", "-q")
        self._git(workspace, "config", "user.name", "Reviewed Task Test")
        self._git(
            workspace,
            "config",
            "user.email",
            "reviewed-task@example.invalid",
        )
        return workspace

    @staticmethod
    def _config():
        return make_config(docs_dir="docs")

    def _reviewed_order(self, workspace, kind):
        order = self.order(
            "reviewed_task",
            work_area={
                "workspace_path": workspace,
                "primary": workspace,
                "additional": [],
            },
        )
        order["configuration"] = {"task_kind": kind}
        return order

    @staticmethod
    def _script(kind, marker="", cut=None):
        if kind == contracts.KIND_DRAFT_SKELETON:
            production = step(
                kind,
                ok(kind, artifact="docs/skeleton.md"),
                side_effect=write_file(
                    "docs/skeleton.md",
                    canonical_skeleton_document() + "\n" + marker,
                ),
            )
        elif kind == contracts.KIND_DRAFT_SLICE_NOTE:
            production = step(
                kind,
                ok(kind, artifact="docs/slice-01.md"),
                side_effect=write_file(
                    "docs/slice-01.md", "# Standalone slice\n" + marker
                ),
            )
        else:
            extra = {"files_changed": ["standalone.py"]}
            if cut is not None:
                extra["implementation_cut"] = cut
            production = step(
                kind,
                ok(kind, **extra),
                side_effect=write_file(
                    "standalone.py", "VALUE = %r\n" % (marker or "done")
                ),
            )
        script = [
            production,
            step(contracts.KIND_REVIEW_ROUND,
                 report(contracts.KIND_REVIEW_ROUND)),
            step(contracts.KIND_REVIEW_ROUND,
                 report(contracts.KIND_REVIEW_ROUND)),
        ]
        if kind == contracts.KIND_IMPLEMENT:
            checkpoint = suite_checkpoint_response("no_suite", [])
            checkpoint["authority"]["evidence"][0]["path"] = "standalone.py"
            script.append(step(
                contracts.KIND_SUITE_CHECKPOINT,
                checkpoint,
            ))
        for call in script:
            call.pop("expect_family", None)
        return script

    def _run_reviewed(
        self, workspace, kind, marker="", cut=None, script=None,
        references=None,
    ):
        runner = runners.MockRunner(
            script or self._script(kind, marker=marker, cut=cut)
        )
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: runner,
            poll_interval=0.001,
        )
        self.start_server(host)
        with mock.patch.object(
            service, "_direct_task_config", return_value=self._config()
        ):
            order = self._reviewed_order(workspace, kind)
            if references is not None:
                order["request"]["reference_documents"] = list(references)
            status, body = self.request(
                "POST", "/api/tasks", order
            )
            self.assertEqual(status, 201, body)
            terminal = self.wait_record(body["task"]["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        return terminal, runner, host

    def test_catalogue_api_and_panel_publish_the_same_reviewed_configuration(self):
        status, body = self.request("GET", "/api/task-executors")
        self.assertEqual(status, 200)
        self.assertEqual(
            [entry["id"] for entry in body["task_executors"]],
            ["agent_call", "brainstorming", "reviewed_task"],
        )
        reviewed = body["task_executors"][2]
        self.assertEqual(
            reviewed["configuration_schema"]["task_kind"]["choices"],
            list(tasks.REVIEWED_TASK_KINDS),
        )
        with open(
            os.path.join(os.path.dirname(service.__file__), "static", "panel.html"),
            encoding="utf-8",
        ) as handle:
            panel = handle.read()
        self.assertIn("renderTaskConfigurationSchema", panel)
        self.assertNotIn('taskExecutor === "reviewed_task"', panel)

    def test_untouched_api_and_panel_orders_inherit_bound_project_reviewed_defaults(self):
        workspace = self._repo("defaults")
        self.project("defaults", workspace)
        defaults = {
            "git": {"enabled": True},
            "impl_reclassify_from": "P2",
            "max_rounds_per_family": 7,
            "max_fix_loops": 8,
            "delta_full_review_after_fixes": 2,
            "implementation_size_control": {
                "soft_lines": 111,
                "hard_lines": 222,
                "unconfirmed_grace_s": 9,
                "confirmed_grace_s": 19,
            },
        }
        service.update_project(self.home, "defaults", {"defaults": defaults})
        order = self.order(
            "reviewed_task",
            work_area={"project": "defaults", "work_area": "main"},
        )
        order["configuration"] = {"task_kind": "implement"}
        status, body = self.request("POST", "/api/tasks", order)
        self.assertEqual(status, 201, body)
        resolved = body["task"]["order"]["configuration"]
        self.assertEqual(resolved["producer"]["task_executor"], "agent_call")
        self.assertEqual(resolved["review_breadth"], "double")
        self.assertFalse(resolved["same_family_second_look"])
        for name in (
            "impl_reclassify_from", "max_rounds_per_family", "max_fix_loops",
            "delta_full_review_after_fixes", "implementation_size_control",
        ):
            self.assertEqual(resolved[name], defaults[name])

    def test_invalid_policy_access_paths_git_and_busy_tree_refuse_before_admission(self):
        workspace = self._repo("refusals")
        base = self._reviewed_order(workspace, "implement")
        invalid = []
        for configuration, code in (
            ({"task_kind": "implement", "producer": {
                "task_executor": "missing"}}, tasks.UNKNOWN_TASK_EXECUTOR),
            ({"task_kind": "implement",
              "implementation_size_control": None}, tasks.INVALID_TASK_REQUEST),
            ({"task_kind": "implement", "producer": {
                "task_executor": "brainstorming"},
              "implementation_size_control": {
                  "soft_lines": 1, "hard_lines": 2,
                  "unconfirmed_grace_s": 1, "confirmed_grace_s": 1,
              }}, tasks.INVALID_TASK_REQUEST),
        ):
            order = copy.deepcopy(base)
            order["configuration"] = configuration
            invalid.append((order, code))
        outside = copy.deepcopy(base)
        outside["request"]["reference_documents"] = [
            os.path.join(self.outside, "secret.md")
        ]
        invalid.append((outside, tasks.INVALID_TASK_REQUEST))
        for order, expected in invalid:
            before = len(task_api.StandaloneTaskStore(self.home).records())
            status, body = self.request("POST", "/api/tasks", order)
            self.assertEqual((status, body["error"]), (400, expected))
            self.assertEqual(
                len(task_api.StandaloneTaskStore(self.home).records()), before
            )

        disabled = self._repo("disabled")
        self.project("disabled", disabled)
        service.update_project(self.home, "disabled", {
            "defaults": {"git": {"enabled": 0}}
        })
        order = self.order("reviewed_task", work_area={
            "project": "disabled", "work_area": "main"
        })
        order["configuration"] = {"task_kind": "draft_skeleton"}
        status, body = self.request("POST", "/api/tasks", order)
        self.assertEqual((status, body["error"]),
                         (400, tasks.INVALID_TASK_REQUEST))

        nonrepo = self.directory("nonrepo")
        status, body = self.request(
            "POST", "/api/tasks", self._reviewed_order(
                nonrepo, "draft_skeleton"
            )
        )
        self.assertEqual((status, body["error"]),
                         (400, service.PRIMARY_NOT_REPO_ROOT))
        busy = NoopHost()
        busy.owns_workspace = lambda _workspace: True
        self.start_server(busy)
        status, body = self.request("POST", "/api/tasks", base)
        self.assertEqual((status, body["error"]),
                         (409, service.WORK_AREA_BUSY))
        self.assertEqual(busy.started, [])

    def test_every_agent_call_job_reaches_reviewed_result(self):
        kinds = ("draft_skeleton", "draft_slice_note", "implement")
        before = len(task_api.StandaloneTaskStore(self.home).records())
        for index, kind in enumerate(kinds):
            with self.subTest(kind=kind):
                terminal, _runner, _host = self._run_reviewed(
                    self._repo("kind-%d" % index), kind
                )
                native = terminal["result"]["native_result"]
                self.assertEqual(
                    set(native),
                    {"production_result", "review_evidence", "gate_commit"},
                )
                self.assertTrue(native["gate_commit"])
        records = task_api.StandaloneTaskStore(self.home).records()
        self.assertEqual(len(records), before + len(kinds))
        self.assertTrue(all(
            record["order"]["task_executor"] == "reviewed_task"
            for record in records[before:]
        ))

    def test_reference_documents_remain_ordered_untyped_material(self):
        workspace = self._repo("references")
        references = ["docs/skeleton.md", "docs/slice-01.md", "docs/extra.md"]
        terminal, _runner, _host = self._run_reviewed(
            workspace, "implement", references=references
        )

        self.assertEqual(
            terminal["order"]["request"]["reference_documents"], references
        )
        path = task_api.reviewed_state_path(self.home, terminal["id"])
        lifecycle = st.load(path)
        authority = lifecycle["reviewed_task"]["authority_path"]
        sealed = lifecycle["units"][:2]
        self.assertEqual([unit["artifact"] for unit in sealed],
                         [authority, authority])
        with open(authority, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("no positional roles", text)
        self.assertEqual(
            [text.index("- %s" % reference) for reference in references],
            sorted(text.index("- %s" % reference) for reference in references),
        )

    def test_successive_orders_on_one_work_area_have_disjoint_evidence_and_accounting(self):
        workspace = self._repo("successive")
        first, first_runner, _host = self._run_reviewed(
            workspace, "draft_skeleton", marker="first"
        )
        first_gate = first["result"]["native_result"]["gate_commit"]
        status, body = self.request(
            "DELETE", "/api/tasks/%s" % first["id"]
        )
        self.assertEqual(status, 200, body)
        second, second_runner, _host = self._run_reviewed(
            workspace, "draft_skeleton", marker="second"
        )
        self.assertNotEqual(
            first_gate, second["result"]["native_result"]["gate_commit"]
        )
        self.assertEqual(second["result"]["duration_s"],
                         len(second_runner.calls) * 0.01)
        self.assertEqual(len(first_runner.calls), len(second_runner.calls))
        lifecycle = st.load(task_api.reviewed_state_path(self.home, second["id"]))
        self.assertEqual(tasks.task_records(lifecycle), [])

    def test_agent_call_implementation_cut_returns_without_successor(self):
        cut = {
            "cut_scope": "complete standalone core",
            "remaining_scope": "wire the later caller",
        }
        terminal, _runner, _host = self._run_reviewed(
            self._repo("cut"), "implement", cut=cut
        )
        self.assertEqual(
            terminal["result"]["native_result"]["production_result"]
            ["implementation_cut"],
            cut,
        )
        lifecycle = st.load(task_api.reviewed_state_path(self.home, terminal["id"]))
        self.assertFalse(any(unit.get("part") == "b"
                             for unit in lifecycle["units"]))
        self.assertEqual(
            [row["id"] for row in task_api.StandaloneTaskStore(self.home).records()],
            [terminal["id"]],
        )

    def test_standalone_suite_checkpoint_restores_edits_before_retry(self):
        workspace = self._repo("suite-read-only")
        script = self._script("implement")
        script[-1]["side_effect"] = write_file(
            "standalone.py", "VALUE = 'checkpoint edit'\n"
        )
        checkpoint = suite_checkpoint_response("no_suite", [])
        checkpoint["authority"]["evidence"][0]["path"] = "standalone.py"
        retry = step(contracts.KIND_SUITE_CHECKPOINT, checkpoint)
        retry.pop("expect_family", None)
        script.append(retry)

        terminal, runner, _host = self._run_reviewed(
            workspace, "implement", script=script
        )
        with open(
            os.path.join(workspace, "standalone.py"), encoding="utf-8"
        ) as handle:
            self.assertEqual(handle.read(), "VALUE = 'done'\n")
        lifecycle = st.load(task_api.reviewed_state_path(self.home, terminal["id"]))
        verifications = [
            event for event in lifecycle["events"]
            if event["type"] == "verification"
        ]
        self.assertEqual(
            [event["status"] for event in verifications[-2:]],
            ["invalidated", "no_suite"],
        )
        self.assertEqual(
            sum(kind == contracts.KIND_SUITE_CHECKPOINT
                for _family, kind, _prompt in runner.calls),
            2,
        )

    def test_stop_fails_without_success_and_releases_the_work_area(self):
        workspace = self._repo("stop")
        entered = threading.Event()
        release = threading.Event()
        scripted = runners.MockRunner(self._script("draft_skeleton"))

        class BlockingRunner:
            def call(_self, *args, **kwargs):
                entered.set()
                release.wait(5)
                return scripted.call(*args, **kwargs)

        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: BlockingRunner(),
            poll_interval=0.001,
        )
        self.start_server(host)
        with mock.patch.object(service, "_direct_task_config",
                               return_value=self._config()):
            body = self.request(
                "POST", "/api/tasks",
                self._reviewed_order(workspace, "draft_skeleton"),
            )[1]
            task_id = body["task"]["id"]
            self.assertTrue(entered.wait(2))
            status, stopped = self.request(
                "POST", "/api/tasks/%s/stop" % task_id, {}
            )
            self.assertEqual((status, stopped["state"]), (200, "stopping"))
            release.set()
            terminal = self.wait_record(task_id)
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertIsNone(terminal["result"]["native_result"])
        self.assertFalse(host.owns_workspace(workspace))

    def test_existing_direct_tasks_and_old_records_keep_their_recovery_law(self):
        workspace = self.directory("legacy-worker")
        store = task_api.StandaloneTaskStore(self.home)
        record = store.admit(
            tasks.validate_order(self.order(work_area={
                "workspace_path": workspace,
                "primary": workspace,
                "additional": [],
            })),
            {"worker": {"agent": "codex", "model": None, "effort": None}},
            workspace,
        )
        aged = copy.deepcopy(record)
        aged["order"]["task_executor"] = "worker"
        aged["order"].pop("staffing_session", None)
        self._age_stored_record(store, aged)

        class LegacyRunner:
            def call(self, *_args, **_kwargs):
                return runners.RunnerResult("legacy result", 0, 0.1)

        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: LegacyRunner(),
        )
        host.start(aged, lambda: self._config())
        terminal = self.wait_record(aged["id"])
        self.assertEqual(terminal["result"]["native_result"], "legacy result")
        self.assertEqual(terminal["order"]["task_executor"], "worker")
        self.assertNotIn("staffing_session", terminal["order"])


if __name__ == "__main__":
    unittest.main()
