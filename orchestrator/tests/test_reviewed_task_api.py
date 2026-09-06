"""Slice 5 conformance for standalone reviewed-task ordering."""

import copy
import os
import subprocess
import threading
import time
import unittest
from unittest import mock

from orchestrator import brainstorming, brainstorming_lifecycle
from orchestrator import brainstorming_milestone, brainstorming_tasks
from orchestrator import canonical_plan, contracts, gitops
from orchestrator import driver as drv
from orchestrator import registry, runners, service, task_api, tasks
from orchestrator import state as st
from orchestrator.tests import test_task_api as _task_api_tests
from orchestrator.tests.test_brainstorming_slice_production import (
    suite_checkpoint_response,
)
from orchestrator.tests.test_driver_mock import (
    canonical_skeleton_document,
    init_state,
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
    _sleeper = _task_api_tests.TaskApiTest._sleeper
    _manual_brainstorming = _task_api_tests.TaskApiTest._manual_brainstorming
    _waiting_manual_brainstorming = (
        _task_api_tests.TaskApiTest._waiting_manual_brainstorming
    )
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

    def _run_brainstorming_reviewed(self, workspace, kind):
        script = self._script(kind)[1:]
        if kind == contracts.KIND_IMPLEMENT:
            script[-1]["response"]["authority"]["evidence"][0]["path"] = (
                "brainstorming-implementation.txt"
            )
        runner = runners.MockRunner(script)
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: runner,
            poll_interval=0.001,
        )
        self.start_server(host)
        session_id = "reviewed-brainstorming-%s" % kind

        def finish(state, task_id, *_args, **_kwargs):
            record = tasks.task_record(state, task_id)
            source = record["order"]["request"]["context"]["session_charge"][
                "repository"
            ]["pre_session_commit"]
            relative = (
                "docs/slice-01.md"
                if kind == contracts.KIND_DRAFT_SLICE_NOTE
                else "brainstorming-implementation.txt"
            )
            write_file(relative, "Brainstorming production\n")(workspace)
            self._git(workspace, "add", relative)
            self._git(workspace, "commit", "-q", "-m", "Brainstorming delivery")
            accepted = self._git(workspace, "rev-parse", "HEAD")
            return tasks.record_task_result(state, task_id, {
                "status": "success",
                "duration_s": 2.0,
                "token_usage": None,
                "token_usage_partial": True,
                "cost": None,
                "cost_partial": True,
                "native_result": {
                    "outcome": "success",
                    "rounds_used": 1,
                    "source_base_revision": source,
                    "accepted_revision": accepted,
                },
            })

        order = self._reviewed_order(workspace, kind)
        order["configuration"]["producer"] = {
            "task_executor": "brainstorming"
        }
        with mock.patch.object(
            service, "_direct_task_config", return_value=self._config()
        ), mock.patch.object(
            brainstorming_tasks, "resolve_staffing", return_value={
                "dispatch_authority": "static", "participants": []
            }
        ), mock.patch.object(
            brainstorming_tasks, "start_task", return_value={"id": session_id}
        ), mock.patch.object(
            brainstorming_tasks, "finish_task", side_effect=finish
        ):
            status, body = self.request("POST", "/api/tasks", order)
            self.assertEqual(status, 201, body)
            terminal = self.wait_record(body["task"]["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        return terminal, runner

    @staticmethod
    def _rethink_step(kind):
        call = step(kind, {
            "status": "need_rethink",
            "problem": "Resolve the standalone governing contradiction.",
        })
        call.pop("expect_family", None)
        return call

    @staticmethod
    def _rethink_session(session_id):
        def create(_state, _config, _unit, _signal, _references, charge,
                   **_kwargs):
            return {
                "id": session_id,
                "state": {"request": {"context": {"source_payload": {
                    "session_charge": copy.deepcopy(charge)
                }}}},
            }
        return create

    def _waiting_rethink_session(self, workspace, name):
        primary = self.primary
        self.primary = workspace
        try:
            session_id, waiting = self._waiting_manual_brainstorming(name)
        finally:
            self.primary = primary
        projection = brainstorming_lifecycle.inspect_session(
            self.home, session_id, lambda _record: None
        )

        def create(state, _config, unit_key, _signal, _references, charge,
                   **_kwargs):
            caller = "milestone:%s:%s" % (
                state.get("name") or "run", unit_key
            )
            with brainstorming_lifecycle._locked_registry(self.home):
                document = brainstorming_lifecycle._load_registry(self.home)
                record = brainstorming_lifecycle._find_record(
                    document, session_id
                )
                record["caller"] = caller
                brainstorming_lifecycle._save_registry(self.home, document)
            created = copy.deepcopy(projection)
            created["caller"] = caller
            created["state"]["request"]["context"] = {
                "source_payload": {"session_charge": copy.deepcopy(charge)}
            }
            return created

        return session_id, waiting, create

    def _waiting_producer_session(self, workspace, name):
        primary = self.primary
        self.primary = workspace
        try:
            session_id, waiting = self._waiting_manual_brainstorming(name)
        finally:
            self.primary = primary

        def start(state, task_id, _config, _home,
                  staffing_selection=None, **_kwargs):
            task = tasks.task_record(state, task_id)
            with brainstorming_lifecycle._locked_registry(self.home):
                document = brainstorming_lifecycle._load_registry(self.home)
                record = brainstorming_lifecycle._find_record(
                    document, session_id
                )
                record["caller"] = brainstorming_tasks._task_caller(
                    task, task_id
                )
                record["execution_context"] = (
                    brainstorming_tasks._execution_context(
                        task["order"]["request"]
                    )
                )
                record["staffing_session"] = (
                    staffing_selection or {}
                ).get("session")
                brainstorming_lifecycle._save_registry(self.home, document)
            return brainstorming_lifecycle.inspect_session(
                self.home, session_id, lambda _record: None
            )

        return session_id, waiting, start

    def _record_brainstorming_activity(self, session_id):
        usage = {
            "input_tokens": 30,
            "cached_input_tokens": 5,
            "output_tokens": 12,
            "reasoning_output_tokens": 4,
            "total_tokens": 42,
        }
        cost = {"api_usd": 0.7, "real_usd": 0.2}
        store = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        )
        store.append_activity(session_id, {
            "id": "activity-before-owner-stop",
            "action_id": "turn-before-owner-stop",
            "provider_attempt": 1,
            "at": "2026-09-05T12:00:00+0200",
            "started_at": 1.0,
            "duration_s": 7.0,
            "kind": "discussion_turn",
            "stage": "discussion",
            "round": 1,
            "participant_id": "lead",
            "model_family": "codex",
            "model": "gpt-5.6-sol",
            "effort": "xhigh",
            "status": "completed",
            "token_usage": usage,
            "cost": cost,
        })
        return usage, cost

    def _admit_open_reviewed(self, workspace, kind):
        host = NoopHost()
        self.start_server(host)
        with mock.patch.object(
            service, "_direct_task_config", return_value=self._config()
        ):
            status, body = self.request(
                "POST", "/api/tasks", self._reviewed_order(workspace, kind)
            )
        self.assertEqual(status, 201, body)
        record = body["task"]
        self.assertEqual(host.started, [record["id"]])
        task_api.ensure_reviewed_state(self.home, record, self._config())
        return record

    def _adopt_reviewed(self, record, runner):
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: runner,
            poll_interval=0.001,
        )
        outcome = host.adopt_open_tasks(
            lambda _record: lambda: (_ for _ in ()).throw(
                AssertionError("durable reviewed state must be reused")
            )
        )
        terminal = self.wait_record(record["id"])
        self.assertEqual(outcome["adopted"], [record["id"]])
        self.assertEqual(terminal["id"], record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        return terminal

    @staticmethod
    def _standalone_step(subject):
        unit_key = subject.state["reviewed_task"]["unit"]
        with subject._exclusive():
            subject._assert_not_stale()
            unit = subject._unit_by_key(unit_key)
            action = subject.reviewed_work.next_action(unit)
            try:
                subject.reviewed_work.execute(
                    action,
                    call_preparation=drv.StandaloneReviewedWorkCallPreparation(
                        subject
                    ),
                )
                subject._save()
            finally:
                subject._clear_busy()
        return action

    def test_catalogue_api_and_panel_publish_the_same_reviewed_configuration(self):
        status, body = self.request("GET", "/api/task-executors")
        self.assertEqual(status, 200)
        self.assertEqual(
            [entry["id"] for entry in body["task_executors"]],
            ["agent_call", "brainstorming", "reviewed_task", "deep_task"],
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
                status, detail = self.request(
                    "GET", "/api/tasks/%s" % terminal["id"]
                )
                self.assertEqual(status, 200, detail)
                reviewed_view = detail["reviewed_task"]
                self.assertEqual(reviewed_view["task_kind"], kind)
                self.assertEqual(reviewed_view["status"], "success")
                unit = reviewed_view["activity"]["unit"]
                self.assertEqual(unit["source_task_id"], terminal["id"])
                self.assertEqual(unit["status"], "sealed")
                self.assertTrue(unit["drafts"])
                self.assertTrue(unit["rounds"])
        records = task_api.StandaloneTaskStore(self.home).records()
        self.assertEqual(len(records), before + len(kinds))
        self.assertTrue(all(
            record["order"]["task_executor"] == "reviewed_task"
            for record in records[before:]
        ))
        status, sidebar = self.request(
            "GET", "/api/tasks?scope=direct&limit=10"
        )
        self.assertEqual(status, 200, sidebar)
        self.assertEqual(
            {row["record"]["id"] for row in sidebar["rows"]},
            {record["id"] for record in records[before:]},
        )

    def test_brainstorming_jobs_reach_the_same_result_without_size_control(self):
        for index, kind in enumerate(("draft_slice_note", "implement")):
            with self.subTest(kind=kind):
                terminal, runner = self._run_brainstorming_reviewed(
                    self._repo("brainstorming-%d" % index), kind
                )
                native = terminal["result"]["native_result"]
                self.assertTrue(native["gate_commit"])
                resolved = terminal["order"]["configuration"]
                self.assertEqual(
                    resolved["producer"]["task_executor"], "brainstorming"
                )
                self.assertNotIn("implementation_size_control", resolved)
                lifecycle = st.load(task_api.reviewed_state_path(
                    self.home, terminal["id"]
                ))
                self.assertFalse(any(
                    event["type"].startswith("implementation_size_")
                    for event in lifecycle["events"]
                ))
                expected_calls = 3 if kind == "implement" else 2
                self.assertEqual(len(runner.calls), expected_calls)

    def test_brainstorming_producer_wait_continues_same_reviewed_session(self):
        workspace = self._repo("brainstorming-producer-continue")
        session_id, waiting, start = self._waiting_producer_session(
            workspace, "brainstorming-producer-continue.md"
        )
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: runners.MockRunner([]),
            poll_interval=0.001,
        )
        self.start_server(host)
        order = self._reviewed_order(workspace, "implement")
        order["configuration"]["producer"] = {
            "task_executor": "brainstorming"
        }
        with mock.patch.object(
            service, "_direct_task_config", return_value=self._config()
        ), mock.patch.object(
            brainstorming_tasks, "start_task", side_effect=start
        ), mock.patch.object(
            brainstorming_tasks, "finish_task", return_value=None
        ):
            status, body = self.request("POST", "/api/tasks", order)
            self.assertEqual(status, 201, body)
            task_id = body["task"]["id"]
            deadline = time.time() + 3
            while time.time() < deadline \
                    and host.running_session_id(task_id) != session_id:
                time.sleep(0.01)
            self.assertEqual(host.running_session_id(task_id), session_id)

            lifecycle = st.load(task_api.reviewed_state_path(
                self.home, task_id
            ))
            unit = next(
                item for item in lifecycle["units"]
                if st.unit_key(item) == lifecycle["reviewed_task"]["unit"]
            )
            inner_id = unit["brainstorming_wait"]["origin"]["task_id"]
            self.assertIsNone(tasks.task_record(lifecycle, inner_id)["result"])

            continued_process = self._sleeper()
            with mock.patch.object(
                brainstorming_lifecycle,
                "_launch_lifecycle_process",
                return_value=brainstorming_lifecycle.GatedLaunch(
                    continued_process,
                    lambda: None,
                    continued_process.terminate,
                ),
            ) as launched:
                status, continued = self.request(
                    "POST",
                    "/api/brainstorming/sessions/%s/continue" % session_id,
                    {"waiting_revision": waiting.revision},
                )
            self.assertEqual(status, 200, continued)
            self.assertEqual(continued["session"]["id"], session_id)
            self.assertEqual(
                continued["session"]["state"]["status"], "running"
            )
            launched.assert_called_once()
            self.assertIsNone(
                task_api.StandaloneTaskStore(self.home).record(task_id)[
                    "result"
                ]
            )

            self.request("POST", "/api/tasks/%s/stop" % task_id, {})
            self.assertEqual(self.wait_record(task_id)["result"]["status"],
                             "failure")

    def test_brainstorming_wait_does_not_exhaust_reviewed_step_budget(self):
        workspace = self.directory("long-brainstorming-wait")
        unit = {"brainstorming_wait": {"session_id": "same-session"}}
        subject = mock.MagicMock()
        subject.state = {
            "reviewed_task": {"unit": "slice-01"},
            "failure": None,
        }
        subject._unit_by_key.return_value = unit
        subject.reviewed_work.recover_pending_gate.return_value = None
        subject.reviewed_work.next_action.return_value.type = (
            drv.A_BRAINSTORM_WAIT
        )
        subject.reviewed_work.result.return_value = None
        store = mock.Mock()
        store.stop_reason.return_value = None
        host = task_api.DirectTaskHost(
            self.home, store=store, runner_factory=lambda *_args: None
        )
        success = {"status": "success", "native_result": None}
        polls = 0

        def operator_eventually_continues(_interval):
            nonlocal polls
            polls += 1
            # A human wait must outlive the execution-step safeguard.  The
            # same discussion then reaches a real terminal outcome.
            if polls == 10001:
                unit.pop("brainstorming_wait")
                subject.reviewed_work.result.return_value = success

        with mock.patch.object(
            task_api.st, "load", return_value={"config": {}}
        ), mock.patch.object(
            task_api.driver, "Driver", return_value=subject
        ), mock.patch.object(
            task_api.time, "sleep", side_effect=operator_eventually_continues
        ), mock.patch.object(
            host, "_reviewed_failure", return_value={"status": "failure"}
        ), mock.patch.object(host, "_publish_reviewed_terminal") as publish:
            host._run_reviewed({
                "id": "reviewed-owner",
                "order": {"request": {"work_area": {
                    "workspace_path": workspace,
                }}},
            })

        self.assertEqual(polls, 10001)
        publish.assert_called_once_with(
            "reviewed-owner", subject, unit, success
        )

    def test_reviewed_execution_step_guard_still_stops_nonprogressing_work(self):
        workspace = self.directory("nonprogressing-reviewed-work")
        unit = {}
        subject = mock.MagicMock()
        subject.state = {
            "reviewed_task": {"unit": "slice-01"},
            "failure": None,
        }
        subject._unit_by_key.return_value = unit
        subject.reviewed_work.recover_pending_gate.return_value = None
        subject.reviewed_work.next_action.return_value.type = drv.A_DRAFT
        subject.reviewed_work.result.return_value = None
        store = mock.Mock()
        store.stop_reason.return_value = None
        host = task_api.DirectTaskHost(
            self.home, store=store, runner_factory=lambda *_args: None
        )
        with mock.patch.object(
            task_api.st, "load", return_value={"config": {}}
        ), mock.patch.object(
            task_api.driver, "Driver", return_value=subject
        ), mock.patch.object(
            host, "_reviewed_failure",
            side_effect=lambda _subject, _unit, reason: {
                "status": "failure", "reason": reason,
            },
        ), mock.patch.object(host, "_publish_reviewed_terminal") as publish:
            host._run_reviewed({
                "id": "reviewed-owner",
                "order": {"request": {"work_area": {
                    "workspace_path": workspace,
                }}},
            })

        self.assertEqual(subject.reviewed_work.execute.call_count, 10000)
        publish.assert_called_once()
        failure = publish.call_args.args[-1]
        self.assertEqual(failure["status"], "failure")
        self.assertIn("exceeded its lifecycle step bound", failure["reason"])

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

    def test_stop_during_attached_rethink_stops_session_and_fails_outer_task(self):
        workspace = self._repo("stop-rethink")
        session_id, waiting, create = self._waiting_rethink_session(
            workspace, "standalone-rethink-stop.md"
        )
        session_usage, session_cost = self._record_brainstorming_activity(
            session_id
        )
        runner = runners.MockRunner([self._rethink_step("implement")])
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: runner,
            poll_interval=0.01,
        )
        self.start_server(host)
        with mock.patch.object(
            service, "_direct_task_config", return_value=self._config()
        ), mock.patch.object(
            brainstorming_milestone,
            "create_session",
            side_effect=create,
        ), mock.patch.object(
            brainstorming_milestone, "terminal_handoff", return_value=None
        ):
            status, body = self.request(
                "POST", "/api/tasks",
                self._reviewed_order(workspace, "implement"),
            )
            self.assertEqual(status, 201, body)
            task_id = body["task"]["id"]
            deadline = time.time() + 3
            while time.time() < deadline \
                    and host.running_session_id(task_id) != session_id:
                time.sleep(0.01)
            self.assertEqual(host.running_session_id(task_id), session_id)
            continued_process = self._sleeper()
            with mock.patch.object(
                brainstorming_lifecycle,
                "_launch_lifecycle_process",
                return_value=brainstorming_lifecycle.GatedLaunch(
                    continued_process,
                    lambda: None,
                    continued_process.terminate,
                ),
            ):
                status, continued = self.request(
                    "POST",
                    "/api/brainstorming/sessions/%s/continue" % session_id,
                    {"waiting_revision": waiting.revision},
                )
            self.assertEqual(status, 200, continued)
            self.assertEqual(
                continued["session"]["state"]["status"], "running"
            )
            self.assertIsNone(
                task_api.StandaloneTaskStore(self.home).record(task_id)[
                    "result"
                ]
            )
            status, stopped = self.request(
                "POST", "/api/tasks/%s/stop" % task_id, {}
            )
            self.assertEqual((status, stopped["state"]), (200, "stopping"))
            terminal = self.wait_record(task_id)
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertAlmostEqual(
            terminal["result"]["duration_s"], 7.0 + len(runner.calls) * 0.01
        )
        self.assertEqual(terminal["result"]["token_usage"], session_usage)
        self.assertEqual(terminal["result"]["cost"], session_cost)
        lifecycle = st.load(task_api.reviewed_state_path(
            self.home, task_id
        ))
        recorded = [
            event for event in lifecycle["events"]
            if event.get("type") == "brainstorming_work_recorded"
            and event.get("session_id") == session_id
        ]
        self.assertEqual(len(recorded), 1)
        reviewed_unit = next(
            unit for unit in st.summary(lifecycle)["units"]
            if unit["unit"] == lifecycle["reviewed_task"]["unit"]
        )
        discussion = next(
            item for item in reviewed_unit["brainstormings"]
            if item["session_id"] == session_id
        )
        self.assertEqual(discussion["outcome"], "failed")
        terminal_session = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        ).read(session_id)
        self.assertEqual(terminal_session.state["status"], "failure")
        status, refused = self.request(
            "POST",
            "/api/brainstorming/sessions/%s/continue" % session_id,
            {"waiting_revision": waiting.revision},
        )
        self.assertEqual(
            (status, refused["error"]),
            (409, brainstorming_lifecycle.CONTINUATION_CONFLICT),
        )
        self.assertFalse(host.owns_workspace(workspace))

    def test_stop_recovers_session_created_before_attachment_save(self):
        workspace = self._repo("stop-before-attachment-save")
        session_id, waiting, bind_caller = self._waiting_rethink_session(
            workspace, "stop-before-attachment-save.md"
        )
        owner = self._admit_open_reviewed(workspace, "implement")
        path = task_api.reviewed_state_path(self.home, owner["id"])
        lifecycle = st.load(path)
        unit_key = lifecycle["reviewed_task"]["unit"]
        unit = next(
            item for item in lifecycle["units"]
            if st.unit_key(item) == unit_key
        )
        self.assertNotIn("brainstorming_wait", unit)
        bind_caller(lifecycle, self._config(), unit_key, {}, [], {})

        store = task_api.StandaloneTaskStore(self.home)
        reason = "stopped before attachment persisted"
        with registry.locked(self.home):
            store.record_stop_locked(owner["id"], reason)
        session_store = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        )
        before = session_store.read(session_id)
        for suffix, payload in (
            ("rounds", {"maximum": 4}),
            ("continue", {"waiting_revision": waiting.revision}),
        ):
            status, refused = self.request(
                "POST",
                "/api/brainstorming/sessions/%s/%s"
                % (session_id, suffix),
                payload,
            )
            self.assertEqual(
                (status, refused["error"]),
                (409, brainstorming_lifecycle.CONTINUATION_CONFLICT),
            )
            self.assertEqual(session_store.read(session_id), before)

        recovered_host = task_api.DirectTaskHost(
            self.home,
            store=task_api.StandaloneTaskStore(self.home),
            runner_factory=lambda *_args: runners.MockRunner([]),
            poll_interval=0.001,
        )
        outcome = recovered_host.adopt_open_tasks(
            lambda _record: self._config
        )
        terminal = self.wait_record(owner["id"])
        self.assertEqual(outcome["adopted"], [owner["id"]])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], reason)
        self.assertEqual(
            session_store.read(session_id).state["status"], "failure"
        )

    def test_stop_recovers_terminal_session_created_before_attachment_save(self):
        workspace = self._repo("terminal-before-attachment-save")
        session_id, _waiting, bind_caller = self._waiting_rethink_session(
            workspace, "terminal-before-attachment-save.md"
        )
        owner = self._admit_open_reviewed(workspace, "implement")
        path = task_api.reviewed_state_path(self.home, owner["id"])
        lifecycle = st.load(path)
        unit_key = lifecycle["reviewed_task"]["unit"]
        unit = next(
            item for item in lifecycle["units"]
            if st.unit_key(item) == unit_key
        )
        self.assertNotIn("brainstorming_wait", unit)
        bind_caller(lifecycle, self._config(), unit_key, {}, [], {})
        session_usage, session_cost = self._record_brainstorming_activity(
            session_id
        )
        terminal_session = brainstorming_lifecycle.abandon_session(
            self.home,
            session_id,
            lambda _record: None,
            "session terminalized before attachment persisted",
        )
        self.assertEqual(terminal_session["state"]["status"], "failure")

        store = task_api.StandaloneTaskStore(self.home)
        reason = "stopped after unattached session terminalized"
        with registry.locked(self.home):
            store.record_stop_locked(owner["id"], reason)
        recovered_host = task_api.DirectTaskHost(
            self.home,
            store=task_api.StandaloneTaskStore(self.home),
            runner_factory=lambda *_args: runners.MockRunner([]),
            poll_interval=0.001,
        )
        outcome = recovered_host.adopt_open_tasks(
            lambda _record: self._config
        )
        terminal = self.wait_record(owner["id"])

        self.assertEqual(outcome["adopted"], [owner["id"]])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], reason)
        self.assertEqual(terminal["result"]["duration_s"], 7.0)
        self.assertEqual(terminal["result"]["token_usage"], session_usage)
        self.assertEqual(terminal["result"]["cost"], session_cost)
        lifecycle = st.load(path)
        recorded = [
            event for event in lifecycle["events"]
            if event.get("type") == "brainstorming_work_recorded"
            and event.get("session_id") == session_id
        ]
        self.assertEqual(len(recorded), 1)
        reviewed_unit = next(
            item for item in st.summary(lifecycle)["units"]
            if item["unit"] == lifecycle["reviewed_task"]["unit"]
        )
        discussion = next(
            item for item in reviewed_unit["brainstormings"]
            if item["session_id"] == session_id
        )
        self.assertEqual(discussion["outcome"], "failed")
        self.assertEqual(discussion["duration_s"], 7.0)
        self.assertEqual(discussion["token_usage"], session_usage)
        self.assertEqual(discussion["cost"], session_cost)

    def test_stop_racing_reviewed_failure_settles_session_first(self):
        workspace = self._repo("stop-racing-reviewed-failure")
        owner = self._admit_open_reviewed(workspace, "implement")
        path = task_api.reviewed_state_path(self.home, owner["id"])
        session_id, _waiting, create = self._waiting_rethink_session(
            workspace, "stop-racing-reviewed-failure.md"
        )
        subject = drv.Driver(
            path,
            runner=runners.MockRunner([self._rethink_step("implement")]),
            model_profiles_home=self.home,
        )
        with mock.patch.object(
            brainstorming_milestone, "create_session", side_effect=create
        ), mock.patch.object(
            brainstorming_milestone, "terminal_handoff", return_value=None
        ):
            self._standalone_step(subject)

        host = task_api.DirectTaskHost(
            self.home,
            store=task_api.StandaloneTaskStore(self.home),
            runner_factory=lambda *_args: runners.MockRunner([]),
            poll_interval=0.001,
        )
        result_fence_entered = threading.Event()
        release_result_fence = threading.Event()
        record_terminal = host._record_reviewed_terminal

        def delayed_record(*args, **kwargs):
            result_fence_entered.set()
            self.assertTrue(release_result_fence.wait(5))
            return record_terminal(*args, **kwargs)

        reason = "stopped during failure publication"
        with mock.patch.object(
            host, "_record_reviewed_terminal", side_effect=delayed_record
        ), mock.patch.object(
            brainstorming_milestone,
            "terminal_handoff",
            side_effect=OSError("inspection failed"),
        ):
            outcome = host.adopt_open_tasks(lambda _record: self._config)
            self.assertTrue(result_fence_entered.wait(5))
            self.assertTrue(host.stop(owner["id"], reason))
            release_result_fence.set()
            terminal = self.wait_record(owner["id"])

        self.assertEqual(outcome["adopted"], [owner["id"]])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], reason)
        session = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        ).read(session_id)
        self.assertEqual(session.state["status"], "failure")
        self.assertFalse(host.owns_workspace(workspace))

    def test_unreadable_stopped_reviewed_owner_refuses_continuation_controls(self):
        workspace = self._repo("unreadable-stopped-rethink-owner")
        session_id, waiting, _create = self._waiting_rethink_session(
            workspace, "unreadable-stopped-rethink-owner.md"
        )
        owner = self._admit_open_reviewed(workspace, "implement")
        path = task_api.reviewed_state_path(self.home, owner["id"])
        lifecycle = st.load(path)
        unit_key = lifecycle["reviewed_task"]["unit"]
        unit = next(
            item for item in lifecycle["units"]
            if st.unit_key(item) == unit_key
        )
        unit["brainstorming_wait"] = {"session_id": session_id}
        st.save(path, lifecycle)
        with brainstorming_lifecycle._locked_registry(self.home):
            document = brainstorming_lifecycle._load_registry(self.home)
            session = brainstorming_lifecycle._find_record(
                document, session_id
            )
            session["caller"] = "milestone:%s:%s" % (
                lifecycle["name"], unit_key
            )
            brainstorming_lifecycle._save_registry(self.home, document)

        store = task_api.StandaloneTaskStore(self.home)
        with registry.locked(self.home):
            store.record_stop_locked(owner["id"], "stopped by operator")
        session_store = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        )
        before = session_store.read(session_id)
        real_load = st.load

        def unreadable(candidate):
            if os.path.abspath(candidate) == os.path.abspath(path):
                raise OSError("reviewed owner state is unreadable")
            return real_load(candidate)

        with mock.patch.object(st, "load", side_effect=unreadable), \
                mock.patch.object(
                    brainstorming_lifecycle,
                    "_launch_lifecycle_process",
                    side_effect=AssertionError("must not launch"),
                ):
            for suffix, payload in (
                ("continue", {"waiting_revision": waiting.revision}),
                ("rounds", {"maximum": 4}),
            ):
                status, refused = self.request(
                    "POST",
                    "/api/brainstorming/sessions/%s/%s"
                    % (session_id, suffix),
                    payload,
                )
                self.assertEqual(
                    (status, refused["error"]),
                    (503, brainstorming_lifecycle.UNAVAILABLE),
                )
                self.assertEqual(session_store.read(session_id), before)

    def test_discarded_attached_session_does_not_wedge_reviewed_stop(self):
        workspace = self._repo("discarded-rethink-stop")
        store = task_api.StandaloneTaskStore(self.home)
        record = store.admit(
            tasks.validate_order(self._reviewed_order(workspace, "implement")),
            {},
            workspace,
        )
        session_id, _waiting, create = self._waiting_rethink_session(
            workspace, "discarded-rethink-stop.md"
        )
        path = task_api.ensure_reviewed_state(
            self.home, record, self._config()
        )
        subject = drv.Driver(
            path,
            runner=runners.MockRunner([self._rethink_step("implement")]),
            model_profiles_home=self.home,
        )
        with mock.patch.object(
            brainstorming_milestone, "create_session", side_effect=create
        ), mock.patch.object(
            brainstorming_milestone, "terminal_handoff", return_value=None
        ):
            self._standalone_step(subject)

        brainstorming_lifecycle.delete_session(
            self.home, session_id, lambda _record: None, purge=True
        )
        reason = "stopped after discussion discard"
        with registry.locked(self.home):
            store.record_stop_locked(record["id"], reason)
        recovered_host = task_api.DirectTaskHost(
            self.home,
            store=task_api.StandaloneTaskStore(self.home),
            runner_factory=lambda *_args: runners.MockRunner([]),
            poll_interval=0.001,
        )
        outcome = recovered_host.adopt_open_tasks(
            lambda _record: self._config
        )
        terminal = self.wait_record(record["id"])
        self.assertEqual(outcome["adopted"], [record["id"]])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], reason)
        lifecycle = st.load(path)
        reviewed_unit = next(
            item for item in st.summary(lifecycle)["units"]
            if item["unit"] == lifecycle["reviewed_task"]["unit"]
        )
        discussion = next(
            item for item in reviewed_unit["brainstormings"]
            if item["session_id"] == session_id
        )
        self.assertEqual(discussion["outcome"], "detached")

    def test_retained_target_free_session_does_not_wedge_reviewed_stop(self):
        workspace = self._repo("retained-target-free-rethink-stop")
        record = self._admit_open_reviewed(workspace, "implement")
        path = task_api.reviewed_state_path(self.home, record["id"])
        lifecycle = st.load(path)
        unit_key = lifecycle["reviewed_task"]["unit"]
        unit = next(
            item for item in lifecycle["units"]
            if st.unit_key(item) == unit_key
        )
        session_id = "retained-target-free-rethink"
        problem = "Resolve a retained repository contradiction."
        participants = [
            {
                "id": "lead",
                "role": "initial_position",
                "delivery": "llm",
                "executor_ref": "lead-executor",
                "model_family": "codex",
            },
            {
                "id": "critic",
                "role": "contrary_position",
                "delivery": "llm",
                "executor_ref": "critic-executor",
                "model_family": "codex",
            },
        ]
        request = {
            "workspace_path": workspace,
            "request": problem,
            "context": {
                "brief": "Retained target-free recovery fixture.",
                "source_payload": {"session_charge": {
                    "job": "rethink",
                    "prompt_set": "default",
                    "values": {"rethink_problem": problem},
                    "amendments_path": os.path.join(
                        workspace, "amendments.json"
                    ),
                    "accepted_amendments": [],
                    "artifact_type": "implementation",
                    "repository": {
                        "state_path": path,
                        "skeleton_path": "docs/skeleton.md",
                        "pre_session_commit": "a" * 40,
                    },
                }},
            },
            "max_rounds": 1,
        }
        session_store = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        )
        retained = session_store.create(
            session_id,
            request,
            brainstorming.resolve_run_config(
                participants, "unanimity", participants
            ),
            participants,
        )
        self.assertNotIn("target_path", retained.state["request"])
        unit["brainstorming_wait"] = {
            "session_id": session_id,
            "origin": {"kind": "implement"},
        }
        st.append_event(
            lifecycle,
            "brainstorming_wait_started",
            unit=unit_key,
            kind="implement",
            session_id=session_id,
        )
        st.save(path, lifecycle)

        reason = "stopped after target-free session discard"
        store = task_api.StandaloneTaskStore(self.home)
        with registry.locked(self.home):
            store.record_stop_locked(record["id"], reason)
        recovered_host = task_api.DirectTaskHost(
            self.home,
            store=task_api.StandaloneTaskStore(self.home),
            runner_factory=lambda *_args: runners.MockRunner([]),
            poll_interval=0.001,
        )
        outcome = recovered_host.adopt_open_tasks(
            lambda _record: self._config
        )
        terminal = self.wait_record(record["id"])

        self.assertEqual(outcome["adopted"], [record["id"]])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(terminal["result"]["reason"], reason)
        retained = session_store.read(session_id)
        self.assertIsNotNone(retained)
        self.assertNotIn("target_path", retained.state["request"])
        lifecycle = st.load(path)
        detached = [
            event for event in lifecycle["events"]
            if event.get("type") == "brainstorming_missing_detached"
            and event.get("session_id") == session_id
        ]
        self.assertEqual(len(detached), 1)

    def test_rethink_crash_adopts_same_id_and_resumes_without_reconciliation(self):
        workspace = self._repo("rethink-restart")
        record = self._admit_open_reviewed(workspace, "implement")
        path = task_api.reviewed_state_path(self.home, record["id"])
        first_runner = runners.MockRunner([self._rethink_step("implement")])
        subject = drv.Driver(path, runner=first_runner,
                             model_profiles_home=self.home)
        session_id = "standalone-rethink-restart"
        with mock.patch.object(
            brainstorming_milestone,
            "create_session",
            side_effect=self._rethink_session(session_id),
        ), mock.patch.object(
            drv.brainstorming,
            "coordination_projection",
            return_value={"recovery_baseline_revision": "baseline"},
        ):
            self._standalone_step(subject)

        lifecycle = st.load(path)
        unit = next(
            item for item in lifecycle["units"]
            if st.unit_key(item) == lifecycle["reviewed_task"]["unit"]
        )
        self.assertEqual(unit["brainstorming_wait"]["session_id"], session_id)
        self.assertIsNone(
            task_api.StandaloneTaskStore(self.home).record(record["id"])[
                "result"
            ]
        )

        runner = runners.MockRunner(self._script("implement"))
        revision = self._git(workspace, "rev-parse", "HEAD")
        handoff = {
            "session_id": session_id,
            "result": {"outcome": "success"},
            "source_base_revision": revision,
            "accepted_revision": revision,
            "work_duration_s": None,
        }
        with mock.patch.object(
            brainstorming_milestone, "terminal_handoff", return_value=handoff
        ):
            terminal = self._adopt_reviewed(record, runner)
        recovered = st.load(path)
        self.assertNotIn(
            canonical_plan.RECONCILIATION_KEY, recovered["milestone"]
        )
        self.assertTrue(any(
            event["type"] == "brainstorming_rethink_sealed"
            for event in recovered["events"]
        ))
        self.assertAlmostEqual(
            terminal["result"]["duration_s"],
            (len(first_runner.calls) + len(runner.calls)) * 0.01,
        )

    def test_same_id_recovers_production_wip_review_and_gate_crashes(self):
        # A provider result lost before its draft record may repeat; the outer
        # identity and the pre-call implementation baseline must not.
        workspace = self._repo("crash-production")
        record = self._admit_open_reviewed(workspace, "implement")
        path = task_api.reviewed_state_path(self.home, record["id"])
        first = runners.MockRunner([self._script("implement")[0]])
        subject = drv.Driver(path, runner=first, model_profiles_home=self.home)
        with mock.patch.object(
            st, "record_draft", side_effect=RuntimeError("production crash")
        ), self.assertRaisesRegex(RuntimeError, "production crash"):
            self._standalone_step(subject)
        second = runners.MockRunner(self._script("implement"))
        self._adopt_reviewed(record, second)
        self.assertEqual(
            sum(kind == "implement" for _family, kind, _prompt
                in first.calls + second.calls),
            2,
        )

        # A landed WIP is adopted from its durable parent/tree/message intent.
        workspace = self._repo("crash-wip")
        record = self._admit_open_reviewed(workspace, "implement")
        path = task_api.reviewed_state_path(self.home, record["id"])
        runner = runners.MockRunner(self._script("implement"))
        subject = drv.Driver(path, runner=runner, model_profiles_home=self.home)
        real_wip = gitops.commit_wip

        def wip_then_crash(workspace_path, message):
            real_wip(workspace_path, message)
            raise RuntimeError("WIP crash")

        with mock.patch.object(
            gitops, "commit_wip", side_effect=wip_then_crash
        ), self.assertRaisesRegex(RuntimeError, "WIP crash"):
            self._standalone_step(subject)
        self._adopt_reviewed(record, runner)
        self.assertEqual(
            sum(kind == "implement" for _family, kind, _prompt in runner.calls),
            1,
        )

        # A review response lost before its round record may repeat in place.
        workspace = self._repo("crash-review")
        record = self._admit_open_reviewed(workspace, "draft_skeleton")
        path = task_api.reviewed_state_path(self.home, record["id"])
        script = self._script("draft_skeleton")
        script.insert(3, copy.deepcopy(script[2]))
        runner = runners.MockRunner(script)
        subject = drv.Driver(path, runner=runner, model_profiles_home=self.home)
        self._standalone_step(subject)
        unit_key = subject.state["reviewed_task"]["unit"]
        while subject.reviewed_work.next_action(
            subject._unit_by_key(unit_key)
        ).type != drv.A_REVIEW_ROUND:
            self._standalone_step(subject)
        with mock.patch.object(
            st, "record_round", side_effect=RuntimeError("review crash")
        ), self.assertRaisesRegex(RuntimeError, "review crash"):
            self._standalone_step(subject)
        self._adopt_reviewed(record, runner)
        self.assertEqual(
            sum(kind == "review_round" for _family, kind, _prompt
                in runner.calls),
            3,
        )

        # A landed gate is adopted before the outer task exposes success.
        workspace = self._repo("crash-gate")
        record = self._admit_open_reviewed(workspace, "draft_skeleton")
        path = task_api.reviewed_state_path(self.home, record["id"])
        runner = runners.MockRunner(self._script("draft_skeleton"))
        subject = drv.Driver(path, runner=runner, model_profiles_home=self.home)
        unit_key = subject.state["reviewed_task"]["unit"]
        while subject._unit_by_key(unit_key)["status"] != st.U_PRE_SEAL_VERIFY:
            self._standalone_step(subject)
        real_gate = gitops.finalize_gate

        def gate_then_crash(workspace_path, message):
            real_gate(workspace_path, message)
            raise RuntimeError("gate crash")

        with mock.patch.object(
            gitops, "finalize_gate", side_effect=gate_then_crash
        ), self.assertRaisesRegex(RuntimeError, "gate crash"):
            self._standalone_step(subject)
        self.assertIsNone(
            task_api.StandaloneTaskStore(self.home).record(record["id"])[
                "result"
            ]
        )
        terminal = self._adopt_reviewed(record, runners.MockRunner([]))
        self.assertEqual(
            terminal["result"]["native_result"]["gate_commit"],
            self._git(workspace, "rev-parse", "--short", "HEAD"),
        )

    def test_shared_pending_gate_recovery_rejects_downtime_edits_for_both_callers(self):
        for standalone in (False, True):
            caller = "standalone" if standalone else "milestone"
            with self.subTest(caller=caller):
                workspace = self._repo("pending-gate-%s" % caller)
                if standalone:
                    record = self._admit_open_reviewed(
                        workspace, "draft_skeleton"
                    )
                    path = task_api.reviewed_state_path(
                        self.home, record["id"]
                    )
                else:
                    record = None
                    path = init_state(workspace, self._config())

                first_runner = runners.MockRunner(
                    self._script("draft_skeleton")
                )
                subject = drv.Driver(
                    path, runner=first_runner, model_profiles_home=self.home
                )
                unit_key = (
                    subject.state["reviewed_task"]["unit"]
                    if standalone else "skeleton"
                )

                def advance(current):
                    if standalone:
                        return self._standalone_step(current)
                    return current.step()[0]

                while subject._unit_by_key(unit_key)["status"] \
                        != st.U_PRE_SEAL_VERIFY:
                    advance(subject)
                old_reviews = [
                    round_["id"]
                    for round_ in subject._unit_by_key(unit_key)["rounds"]
                    if round_["kind"] == contracts.KIND_REVIEW_ROUND
                ]
                self.assertEqual(len(old_reviews), 2)

                with mock.patch.object(
                    gitops,
                    "finalize_gate",
                    side_effect=RuntimeError("gate unavailable"),
                ), self.assertRaisesRegex(RuntimeError, "gate unavailable"):
                    advance(subject)

                pending = st.load(path)
                pending_unit = next(
                    unit for unit in pending["units"]
                    if st.unit_key(unit) == unit_key
                )
                self.assertEqual(pending["pending_gate_unit"], unit_key)
                self.assertTrue(pending["pending_gate_fingerprint"])
                self.assertEqual(pending_unit["status"], st.U_SEALED)
                self.assertFalse(pending_unit.get("gate_commit"))
                if standalone:
                    self.assertIsNone(
                        task_api.StandaloneTaskStore(self.home).record(
                            record["id"]
                        )["result"]
                    )

                marker = "Downtime edit for %s caller." % caller
                write_file(
                    "docs/skeleton.md",
                    canonical_skeleton_document() + "\n" + marker + "\n",
                )(workspace)
                recovery_runner = runners.MockRunner(
                    self._script("draft_skeleton")[1:]
                )

                if standalone:
                    terminal = self._adopt_reviewed(record, recovery_runner)
                    lifecycle = st.load(path)
                    self.assertEqual(
                        terminal["result"]["native_result"]["gate_commit"],
                        next(
                            unit["gate_commit"]
                            for unit in lifecycle["units"]
                            if st.unit_key(unit) == unit_key
                        ),
                    )
                else:
                    recovered = drv.Driver(
                        path,
                        runner=recovery_runner,
                        model_profiles_home=self.home,
                    )
                    rewound = recovered._unit_by_key(unit_key)
                    self.assertEqual(rewound["status"], st.U_PRE_REVIEW_VERIFY)
                    self.assertFalse(rewound.get("gate_commit"))
                    self.assertNotIn("pending_gate_unit", recovered.state)
                    for _ in range(20):
                        unit = recovered._unit_by_key(unit_key)
                        if unit["status"] == st.U_SEALED \
                                and unit.get("gate_commit"):
                            break
                        recovered.step()
                    else:
                        self.fail("milestone caller did not regain its gate")
                    lifecycle = st.load(path)

                unit = next(
                    candidate for candidate in lifecycle["units"]
                    if st.unit_key(candidate) == unit_key
                )
                fresh_reviews = [
                    round_["id"]
                    for round_ in unit["rounds"]
                    if round_["kind"] == contracts.KIND_REVIEW_ROUND
                    and round_["id"] not in old_reviews
                ]
                self.assertEqual(len(fresh_reviews), 2)
                self.assertEqual(unit["seals"][-1]["reviews"], fresh_reviews)
                self.assertEqual(unit["review_cycle_start"], len(old_reviews))
                self.assertTrue(any(
                    event["type"] == "review_cycle_restarted"
                    and "pending" in event["reason"]
                    for event in lifecycle["events"]
                ))
                self.assertEqual(recovery_runner.script, [])
                self.assertIn(
                    marker,
                    self._git(workspace, "show", "HEAD:docs/skeleton.md"),
                )
                self.assertEqual(self._git(workspace, "status", "--short"), "")

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
