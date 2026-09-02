"""Slice 10 conformance for standalone reviewed complete verification."""

import copy
import os
import threading
import unittest
from unittest import mock

from orchestrator import contracts, gitops, runners, service, task_api, tasks
from orchestrator import driver as drv
from orchestrator import state as st
from orchestrator.tests import test_task_api as _task_api_tests
from orchestrator.tests import test_reviewed_task_api as _reviewed_tests
from orchestrator.tests.test_driver_mock import (
    fix_ok,
    make_config,
    report,
    step,
    triaged,
    write_file,
)


NoopHost = _task_api_tests.NoopHost
COMMAND = "python3 -m unittest"


class ReviewedCompleteVerificationTest(unittest.TestCase):
    setUp = _task_api_tests.TaskApiTest.setUp
    directory = _task_api_tests.TaskApiTest.directory
    start_server = _task_api_tests.TaskApiTest.start_server
    request = _task_api_tests.TaskApiTest.request
    order = _task_api_tests.TaskApiTest.order
    wait_record = _task_api_tests.TaskApiTest.wait_record
    _git = staticmethod(_reviewed_tests.ReviewedTaskOrderingTest._git)
    _repo = _reviewed_tests.ReviewedTaskOrderingTest._repo
    _standalone_step = staticmethod(
        _reviewed_tests.ReviewedTaskOrderingTest._standalone_step
    )
    _adopt_reviewed = _reviewed_tests.ReviewedTaskOrderingTest._adopt_reviewed

    @staticmethod
    def _config(command=COMMAND):
        return make_config(
            docs_dir="docs",
            verification=[] if command is None else [command],
        )

    def _baseline(self, name):
        workspace = self._repo(name)
        write_file("app.txt", "baseline\n")(workspace)
        self._git(workspace, "add", "app.txt")
        self._git(workspace, "commit", "-q", "-m", "baseline")
        return (
            workspace,
            self._git(workspace, "rev-parse", "HEAD"),
            self._git(workspace, "rev-parse", "HEAD^{tree}"),
        )

    def _order(self, workspace, **configuration):
        order = self.order("reviewed_task", work_area={
            "workspace_path": workspace,
            "primary": workspace,
            "additional": [],
        })
        order["configuration"] = {
            "task_kind": tasks.REVIEWED_COMPLETE_VERIFICATION,
            **configuration,
        }
        return order

    @staticmethod
    def _checkpoint(status, command=COMMAND):
        commands = [] if status == "no_suite" else [command]
        result = {
            "status": status,
            "kind": contracts.KIND_SUITE_CHECKPOINT,
            "commands": commands,
            "results": [],
        }
        if status in ("passed", "failed"):
            result["results"] = [{
                "command": command,
                "exit_code": 0 if status == "passed" else 1,
                "evidence": "complete suite %s" % status,
            }]
        if status == "blocked":
            result["blocked_reason"] = "suite cannot run"
            return result
        result["authority"] = {
            "source": "operator_config" if commands else "repository",
            "evidence": [] if commands else [{
                "path": "app.txt",
                "basis": "No complete suite is declared.",
            }],
        }
        if status == "failed":
            result["failure_account"] = {
                "command": command,
                "exit_code": 1,
                "diagnostics": "one focused failure",
                "affected_tests": ["test_example"],
            }
        return result

    @staticmethod
    def _call(response, side_effect=None):
        return step(
            contracts.KIND_SUITE_CHECKPOINT,
            response,
            side_effect=side_effect,
        )

    def _admit(self, workspace, config):
        host = NoopHost()
        self.start_server(host)
        with mock.patch.object(
            service, "_direct_task_config", return_value=config
        ):
            status, body = self.request(
                "POST", "/api/tasks", self._order(workspace)
            )
        self.assertEqual(status, 201, body)
        record = body["task"]
        task_api.ensure_reviewed_state(self.home, record, config)
        return record

    def _run(self, workspace, config, script):
        runner = runners.MockRunner(script)
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: runner,
            poll_interval=0.001,
        )
        self.start_server(host)
        with mock.patch.object(
            service, "_direct_task_config", return_value=config
        ):
            status, body = self.request(
                "POST", "/api/tasks", self._order(workspace)
            )
            self.assertEqual(status, 201, body)
            terminal = self.wait_record(body["task"]["id"])
        return terminal, runner

    def test_contract_admits_only_agent_call_complete_verification(self):
        resolved = tasks.resolve_configuration(
            "reviewed_task",
            {"task_kind": tasks.REVIEWED_COMPLETE_VERIFICATION},
        )
        self.assertEqual(resolved["producer"], {
            "task_executor": "agent_call",
            "configuration": {"role": "implement"},
        })
        self.assertIn("impl_reclassify_from", resolved)
        self.assertNotIn("doc_reclassify_from", resolved)
        self.assertNotIn("implementation_size_control", resolved)
        for configuration, code in (
            ({"task_kind": tasks.REVIEWED_COMPLETE_VERIFICATION,
              "producer": {"task_executor": "brainstorming"}},
             tasks.INVALID_TASK_REQUEST),
            ({"task_kind": tasks.REVIEWED_COMPLETE_VERIFICATION,
              "implementation_size_control": {}},
             tasks.INVALID_TASK_REQUEST),
            ({"task_kind": tasks.REVIEWED_COMPLETE_VERIFICATION,
              "doc_reclassify_from": "P2"}, tasks.INVALID_TASK_REQUEST),
            ({"task_kind": tasks.REVIEWED_COMPLETE_VERIFICATION,
              "producer": {"task_executor": "missing"}},
             tasks.UNKNOWN_TASK_EXECUTOR),
        ):
            with self.assertRaises(tasks.TaskRequestError) as caught:
                tasks.resolve_configuration("reviewed_task", configuration)
            self.assertEqual(caught.exception.code, code)

    def test_unchanged_pass_and_no_suite_each_own_seal_and_gate(self):
        for status in ("passed", "no_suite"):
            with self.subTest(status=status):
                workspace, base, _tree = self._baseline("green-" + status)
                before = len(task_api.StandaloneTaskStore(self.home).records())
                certified_trees = []
                terminal, runner = self._run(
                    workspace,
                    self._config(None if status == "no_suite" else COMMAND),
                    [self._call(
                        self._checkpoint(status),
                        side_effect=lambda root: certified_trees.append(
                            self._git(root, "rev-parse", "HEAD^{tree}")
                        ),
                    )],
                )
                native = terminal["result"]["native_result"]
                self.assertEqual(native["production_result"]["status"], status)
                self.assertEqual(
                    [kind for _family, kind, _prompt in runner.calls],
                    [contracts.KIND_SUITE_CHECKPOINT],
                )
                self.assertAlmostEqual(terminal["result"]["duration_s"], 0.01)
                self.assertEqual(self._git(workspace, "rev-parse", "HEAD^"), base)
                self.assertEqual(
                    self._git(workspace, "rev-parse", "HEAD^{tree}"),
                    certified_trees[0],
                )
                lifecycle = st.load(task_api.reviewed_state_path(
                    self.home, terminal["id"]
                ))
                unit = next(item for item in lifecycle["units"]
                            if item.get("reviewed_task_kind"))
                self.assertEqual(unit["seals"][-1]["reviews"], [])
                self.assertTrue(unit["seals"][-1]["verification_event_seq"] >= 0)
                self.assertEqual(
                    len(task_api.StandaloneTaskStore(self.home).records()),
                    before + 1,
                )

    def test_failed_suite_repairs_reviews_changes_and_reverifies_current_bytes(self):
        workspace, _base, _tree = self._baseline("repair")
        config = self._config()
        record = self._admit(workspace, config)
        runner = runners.MockRunner([
            self._call(self._checkpoint("failed")),
        ])
        subject = drv.Driver(
            task_api.reviewed_state_path(self.home, record["id"]),
            runner=runner,
            model_profiles_home=self.home,
        )
        self._standalone_step(subject)  # task-owned empty WIP
        self._standalone_step(subject)  # failed checkpoint
        unit = subject._unit_by_key(subject.state["reviewed_task"]["unit"])
        queued = copy.deepcopy(unit["fix_queue"][0])
        runner.script.extend([
            step(
                contracts.KIND_FIX_FINDINGS,
                fix_ok([
                    triaged(
                        queued["id"], "fixed", queued["summary"],
                        severity=queued["severity"],
                    )
                ], files_changed=["app.txt"]),
                side_effect=write_file("app.txt", "repaired\n"),
            ),
            step(contracts.KIND_DELTA_REVIEW,
                 report(contracts.KIND_DELTA_REVIEW)),
            step(contracts.KIND_REVIEW_ROUND,
                 report(contracts.KIND_REVIEW_ROUND)),
            step(contracts.KIND_REVIEW_ROUND,
                 report(contracts.KIND_REVIEW_ROUND)),
        ])
        terminal = self._adopt_reviewed(record, runner)
        lifecycle = st.load(task_api.reviewed_state_path(
            self.home, record["id"]
        ))
        unit = next(item for item in lifecycle["units"]
                    if item.get("reviewed_task_kind"))
        verification = [event for event in lifecycle["events"]
                        if event.get("type") == "verification"]
        self.assertEqual([event["status"] for event in verification],
                         ["failed", "passed", "passed"])
        self.assertTrue(verification[1]["fixer_certified"])
        self.assertEqual(verification[2]["reused_from_seq"],
                         verification[1]["seq"])
        reviews = [round_["id"] for round_ in unit["rounds"]
                   if round_["kind"] == contracts.KIND_REVIEW_ROUND]
        self.assertEqual(unit["seals"][-1]["reviews"], reviews)
        self.assertEqual(len(reviews), 2)
        self.assertAlmostEqual(terminal["result"]["duration_s"],
                               len(runner.calls) * 0.01)
        self.assertTrue(
            terminal["result"]["native_result"]["production_result"]
            ["fixer_certified"]
        )
        self.assertFalse(any(event["type"].startswith("implementation_size_")
                             for event in lifecycle["events"]))

    def test_blocked_stop_restart_and_gate_crashes_keep_one_honest_result(self):
        blocked_ws, _base, _tree = self._baseline("blocked")
        blocked, _runner = self._run(
            blocked_ws, self._config(),
            [self._call(self._checkpoint("blocked"))],
        )
        self.assertEqual(blocked["result"]["status"], "failure")
        self.assertIsNone(blocked["result"]["native_result"])

        stop_ws, _base, _tree = self._baseline("stop")
        entered, release = threading.Event(), threading.Event()
        scripted = runners.MockRunner([
            self._call(self._checkpoint("passed"))
        ])

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
        with mock.patch.object(
            service, "_direct_task_config", return_value=self._config()
        ):
            status, body = self.request(
                "POST", "/api/tasks", self._order(stop_ws)
            )
            self.assertEqual(status, 201, body)
            self.assertTrue(entered.wait(2))
            stopped = self.request(
                "POST", "/api/tasks/%s/stop" % body["task"]["id"], {}
            )
            self.assertEqual(stopped[0], 200)
            release.set()
            stopped_record = self.wait_record(body["task"]["id"])
        self.assertEqual(stopped_record["result"]["status"], "failure")
        self.assertIsNone(stopped_record["result"]["native_result"])

        crash_ws, _base, _tree = self._baseline("gate-crash")
        record = self._admit(crash_ws, self._config())
        runner = runners.MockRunner([
            self._call(self._checkpoint("passed"))
        ])
        subject = drv.Driver(
            task_api.reviewed_state_path(self.home, record["id"]),
            runner=runner,
            model_profiles_home=self.home,
        )
        self._standalone_step(subject)
        real_gate = gitops.finalize_gate

        def gate_then_crash(workspace, message):
            real_gate(workspace, message)
            raise RuntimeError("crash after gate")

        with mock.patch.object(
            gitops, "finalize_gate", side_effect=gate_then_crash
        ), self.assertRaisesRegex(RuntimeError, "crash after gate"):
            self._standalone_step(subject)
        self.assertIsNone(
            task_api.StandaloneTaskStore(self.home).record(record["id"])[
                "result"
            ]
        )
        recovered = self._adopt_reviewed(record, runners.MockRunner([]))
        self.assertEqual(recovered["id"], record["id"])
        self.assertEqual(recovered["result"]["status"], "success")
        self.assertEqual(len(runner.calls), 1)

    def test_gate_rejects_post_verification_edits(self):
        workspace, _base, _tree = self._baseline("post-verification-edit")
        record = self._admit(workspace, self._config())
        certified_trees = []
        runner = runners.MockRunner([
            self._call(
                self._checkpoint("passed"),
                side_effect=lambda root: certified_trees.append(
                    self._git(root, "rev-parse", "HEAD^{tree}")
                ),
            ),
        ])
        subject = drv.Driver(
            task_api.reviewed_state_path(self.home, record["id"]),
            runner=runner,
            model_profiles_home=self.home,
        )
        self._standalone_step(subject)  # task-owned empty WIP
        real_gate = gitops.finalize_gate

        def edit_then_gate(root, message):
            write_file("app.txt", "changed after verification\n")(root)
            return real_gate(root, message)

        with mock.patch.object(
            gitops, "finalize_gate", side_effect=edit_then_gate
        ):
            self._standalone_step(subject)

        unit = subject._unit_by_key(subject.state["reviewed_task"]["unit"])
        self.assertEqual(unit["status"], st.U_PRE_SEAL_VERIFY)
        self.assertFalse(unit.get("gate_commit"))
        self.assertNotIn("pending_gate_unit", subject.state)
        self.assertEqual(len(runner.calls), 1)
        self.assertFalse(any(
            event.get("type") == "gate_commit"
            and event.get("unit") == st.unit_key(unit)
            for event in subject.state["events"]
        ))
        self.assertIsNone(
            task_api.StandaloneTaskStore(self.home).record(record["id"])[
                "result"
            ]
        )

        runner.script.append(self._call(
            self._checkpoint("passed"),
            side_effect=lambda root: certified_trees.append(
                self._git(root, "rev-parse", "HEAD^{tree}")
            ),
        ))
        terminal = self._adopt_reviewed(record, runner)
        self.assertEqual(terminal["result"]["status"], "success")
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(
            self._git(workspace, "rev-parse", "HEAD^{tree}"),
            certified_trees[-1],
        )

    def test_slice_ten_leaves_milestone_cadence_and_old_records_unchanged(self):
        self.assertEqual(drv.FULL_VERIFICATION_SLICE_INTERVAL, 4)
        catalogue = tasks.task_executor_catalogue()
        self.assertEqual(
            [entry["id"] for entry in catalogue],
            ["agent_call", "brainstorming", "reviewed_task", "deep_task"],
        )
        self.assertNotIn("verification_task", [entry["id"] for entry in catalogue])
        self.assertEqual(
            set(catalogue[3]["configuration_schema"]),
            {"documentation", "implementation"},
        )
        old = tasks.validate_order(self.order("agent_call"))
        old["task_executor"] = "worker"
        self.assertEqual(
            tasks.projected_task_record({
                "id": "old",
                "order": old,
                "resolved_staffing": {},
                "result": None,
            })["order"]["task_executor"],
            "agent_call",
        )


if __name__ == "__main__":
    unittest.main()
