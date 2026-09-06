"""Slice 7 focused proof for sequential deep implementation delivery."""

import copy
from concurrent import futures
import json
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from orchestrator import brainstorming, brainstorming_lifecycle
from orchestrator import brainstorming_milestone, brainstorming_tasks, contracts
from orchestrator import driver as drv
from orchestrator import registry, runners
from orchestrator import service, task_api, tasks
from orchestrator import state as st
from orchestrator.tests import test_deep_task_documentation as deep_tests
from orchestrator.tests import test_reviewed_task_api as reviewed_tests
from orchestrator.tests import test_task_api as api_tests
from orchestrator.tests.test_driver_mock import append_file, finding, fix_ok, triaged
from orchestrator.tests.test_p3_debt import reclassify


class _PausingImplementationStore(deep_tests._PausingResultStore):
    """Pause only part a's gate-backed public result write."""

    def _before_result(self, task_id):
        relation = (self.record(task_id).get("parent") or {})
        if relation.get("phase") != "implementation" \
                or relation.get("part") != "a":
            return False
        return super()._before_result(task_id)


class DeepTaskImplementationTest(unittest.TestCase):
    setUp = api_tests.TaskApiTest.setUp
    directory = api_tests.TaskApiTest.directory
    start_server = api_tests.TaskApiTest.start_server
    request = api_tests.TaskApiTest.request
    order = api_tests.TaskApiTest.order
    _sleeper = api_tests.TaskApiTest._sleeper
    _manual_brainstorming = api_tests.TaskApiTest._manual_brainstorming
    _waiting_manual_brainstorming = (
        api_tests.TaskApiTest._waiting_manual_brainstorming
    )
    _git = staticmethod(reviewed_tests.ReviewedTaskOrderingTest._git)
    _repo = reviewed_tests.ReviewedTaskOrderingTest._repo

    def _wait_terminal(self, task_id):
        deadline = time.time() + 15
        store = task_api.StandaloneTaskStore(self.home)
        while time.time() < deadline:
            record = store.record(task_id)
            if record["result"] is not None:
                return record
            time.sleep(0.01)
        self.fail("deep task %s did not become terminal" % task_id)

    def _wait_paused(self, task_id):
        deadline = time.time() + 15
        store = task_api.StandaloneTaskStore(self.home)
        while time.time() < deadline:
            record = store.record(task_id)
            self.assertIsNone(record["result"])
            if store.lifecycle(task_id)["status"] == "paused":
                return record
            time.sleep(0.01)
        self.fail("deep task %s did not become paused" % task_id)

    def _wait_related(self, parent_id, phase, part, terminal=None):
        deadline = time.time() + 5
        store = task_api.StandaloneTaskStore(self.home)
        while time.time() < deadline:
            child = store.related(parent_id, phase, part)
            if child is not None and (
                terminal is None or (child["result"] is not None) == terminal
            ):
                return child
            time.sleep(0.01)
        self.fail("%s/%s child did not reach expected state" % (phase, part))

    @staticmethod
    def _stored_success(native_result, duration_s=1.0):
        return {
            "status": "success",
            "duration_s": duration_s,
            "token_usage": None,
            "token_usage_partial": True,
            "cost": None,
            "cost_partial": True,
            "native_result": native_result,
        }

    def _deep_order(self, workspace, configuration=None, references=None):
        order = self.order("deep_task", work_area={
            "workspace_path": workspace,
            "primary": workspace,
            "additional": [],
        })
        if configuration is not None:
            order["configuration"] = configuration
        if references is not None:
            order["request"]["reference_documents"] = list(references)
        return order

    def _execute(
        self,
        workspace,
        implementations,
        store=None,
        before_wait=None,
        documentation_script=None,
        expect_paused=False,
        **order_options,
    ):
        owned_runners = [runners.MockRunner(
            documentation_script
            or reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_DRAFT_SLICE_NOTE
            )
        )]
        owned_runners.extend(
            implementation if isinstance(implementation, runners.MockRunner)
            else runners.MockRunner(
                reviewed_tests.ReviewedTaskOrderingTest._script(
                    contracts.KIND_IMPLEMENT,
                    marker=implementation[0],
                    cut=implementation[1],
                )
            )
            for implementation in implementations
        )
        pending = list(owned_runners)
        store = store or task_api.StandaloneTaskStore(self.home)
        host = task_api.DirectTaskHost(
            self.home,
            store=store,
            runner_factory=lambda _config, _workspace: pending.pop(0),
            poll_interval=0.001,
        )
        self._last_execution_host = host
        self.start_server(host)
        with mock.patch.object(
            service,
            "_direct_task_config",
            return_value=reviewed_tests.ReviewedTaskOrderingTest._config(),
        ):
            status, body = self.request(
                "POST", "/api/tasks",
                self._deep_order(workspace, **order_options),
            )
            self.assertEqual(status, 201, body)
            if before_wait is not None:
                before_wait(body["task"]["id"], store)
            parent = (self._wait_paused if expect_paused else self._wait_terminal)(
                body["task"]["id"]
            )
        self.assertEqual(pending, [])
        return parent, store, owned_runners

    def test_documentation_gate_admits_one_public_part_a_with_frozen_authority(self):
        workspace = self._repo("deep-implementation-authority")
        reference = Path(workspace) / "operator-note.md"
        reference.write_text("operator authority\n", encoding="utf-8")
        self._git(workspace, "add", reference.name)
        self._git(workspace, "commit", "-q", "-m", "Reference authority")
        store = deep_tests._PausingResultStore(self.home)
        documentation_script = (
            reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_DRAFT_SLICE_NOTE
            )
        )
        documentation_script[0]["response"]["artifact"] = "reviewed-note.md"
        documentation_script[0]["side_effect"] = reviewed_tests.write_file(
            "reviewed-note.md", "# Reviewed slice outside output directory\n"
        )
        queued = [
            runners.MockRunner(documentation_script),
            runners.MockRunner(reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_IMPLEMENT
            )),
        ]
        host = task_api.DirectTaskHost(
            self.home,
            store=store,
            runner_factory=lambda _config, _workspace: queued.pop(0),
            poll_interval=0.001,
        )
        self.start_server(host)
        configuration = {
            "documentation": {"max_fix_loops": 3},
            "implementation": {"max_fix_loops": 7},
        }
        with mock.patch.object(
            service, "_direct_task_config",
            return_value=reviewed_tests.ReviewedTaskOrderingTest._config(),
        ):
            order = self._deep_order(
                workspace, configuration, [reference.name]
            )
            order["request"]["output_directory"] = "docs"
            status, body = self.request(
                "POST", "/api/tasks", order,
            )
            self.assertEqual(status, 201, body)
            parent_id = body["task"]["id"]
            self.assertTrue(store.write_entered.wait(5))
            self.assertIsNone(
                store.related(parent_id, "implementation", "a")
            )
            store.allow_write.set()
            parent = self._wait_terminal(parent_id)

        documentation = store.related(parent_id, "documentation", None)
        implementation = store.related(parent_id, "implementation", "a")
        self.assertEqual(parent["result"]["status"], "success")
        self.assertEqual(implementation["order"]["task_executor"], "reviewed_task")
        self.assertEqual(implementation["parent"], {
            "task_id": parent_id, "phase": "implementation", "part": "a",
        })
        expected_configuration = copy.deepcopy(
            parent["order"]["configuration"]["implementation"]
        )
        expected_configuration["task_kind"] = contracts.KIND_IMPLEMENT
        self.assertEqual(
            implementation["order"]["configuration"], expected_configuration
        )
        expected_reference = str(
            (Path(workspace) / documentation["result"]["native_result"]
             ["production_result"]["artifact"]).resolve()
        )
        expected_request = copy.deepcopy(parent["order"]["request"])
        expected_request["reference_documents"].append(expected_reference)
        self.assertEqual(implementation["order"]["request"], expected_request)
        self.assertEqual(
            implementation["order"]["staffing_session"],
            parent["order"]["staffing_session"],
        )
        fake = copy.deepcopy(documentation)
        fake["result"]["native_result"]["production_result"]["artifact"] = (
            str(Path(self.outside) / "unreadable.md")
        )
        with self.assertRaisesRegex(tasks.TaskRequestError, "stay inside"):
            host._deep_documentation_reference(parent, fake)

    def test_waiting_session_keeps_milestone_reviewed_and_deep_owners_open(self):
        workspace = self._repo("deep-waiting-brainstorming")
        session_id, waiting, create = (
            reviewed_tests.ReviewedTaskOrderingTest._waiting_rethink_session(
                self, workspace, "deep-reviewed-wait.md"
            )
        )
        pending = [
            runners.MockRunner(reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_DRAFT_SLICE_NOTE
            )),
            runners.MockRunner([
                reviewed_tests.ReviewedTaskOrderingTest._rethink_step(
                    contracts.KIND_IMPLEMENT
                )
            ]),
        ]
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: pending.pop(0),
            poll_interval=0.001,
        )
        self.start_server(host)
        with mock.patch.object(
            service,
            "_direct_task_config",
            return_value=reviewed_tests.ReviewedTaskOrderingTest._config(),
        ), mock.patch.object(
            brainstorming_milestone,
            "create_session",
            side_effect=create,
        ), mock.patch.object(
            brainstorming_milestone, "terminal_handoff", return_value=None
        ):
            status, body = self.request(
                "POST", "/api/tasks", self._deep_order(workspace)
            )
            self.assertEqual(status, 201, body)
            parent_id = body["task"]["id"]
            documentation = self._wait_related(
                parent_id, "documentation", None, terminal=True
            )
            implementation = self._wait_related(
                parent_id, "implementation", "a", terminal=False
            )
            deadline = time.time() + 3
            while time.time() < deadline and host.running_session_id(
                implementation["id"]
            ) != session_id:
                time.sleep(0.01)

            store = task_api.StandaloneTaskStore(self.home)
            self.assertEqual(documentation["result"]["status"], "success")
            self.assertIsNone(store.record(parent_id)["result"])
            self.assertIsNone(store.record(implementation["id"])["result"])
            lifecycle = st.load(task_api.reviewed_state_path(
                self.home, implementation["id"]
            ))
            selected = next(
                unit for unit in lifecycle["units"]
                if st.unit_key(unit) == lifecycle["reviewed_task"]["unit"]
            )
            self.assertEqual(
                selected["brainstorming_wait"]["session_id"], session_id
            )
            self.assertIsNone(lifecycle["failure"])

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
            self.assertIsNone(store.record(parent_id)["result"])
            self.assertIsNone(store.record(implementation["id"])["result"])

            self.request("POST", "/api/tasks/%s/stop" % parent_id, {})
            self.assertEqual(self._wait_terminal(parent_id)["result"]["status"],
                             "failure")
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

    def test_brainstorming_producer_wait_continues_under_deep_owner(self):
        workspace = self._repo("deep-brainstorming-producer-wait")
        session_id, waiting, start = (
            reviewed_tests.ReviewedTaskOrderingTest
            ._waiting_producer_session(
                self, workspace, "deep-brainstorming-producer-wait.md"
            )
        )
        pending = [
            runners.MockRunner(reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_DRAFT_SLICE_NOTE
            )),
            runners.MockRunner([]),
        ]
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: pending.pop(0),
            poll_interval=0.001,
        )
        self.start_server(host)
        configuration = {
            "implementation": {
                "producer": {"task_executor": "brainstorming"}
            }
        }
        with mock.patch.object(
            service,
            "_direct_task_config",
            return_value=reviewed_tests.ReviewedTaskOrderingTest._config(),
        ), mock.patch.object(
            brainstorming_tasks, "start_task", side_effect=start
        ), mock.patch.object(
            brainstorming_tasks, "finish_task", return_value=None
        ):
            status, body = self.request(
                "POST",
                "/api/tasks",
                self._deep_order(workspace, configuration=configuration),
            )
            self.assertEqual(status, 201, body)
            parent_id = body["task"]["id"]
            implementation = self._wait_related(
                parent_id, "implementation", "a", terminal=False
            )
            deadline = time.time() + 3
            while time.time() < deadline and host.running_session_id(
                implementation["id"]
            ) != session_id:
                time.sleep(0.01)
            self.assertEqual(
                host.running_session_id(implementation["id"]), session_id
            )

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
            store = task_api.StandaloneTaskStore(self.home)
            self.assertIsNone(store.record(parent_id)["result"])
            self.assertIsNone(store.record(implementation["id"])["result"])

            self.request("POST", "/api/tasks/%s/stop" % parent_id, {})
            self.assertEqual(self._wait_terminal(parent_id)["result"]["status"],
                             "failure")

    def test_unreadable_documentation_artifact_pauses_parent_without_implementation(self):
        workspace = self._repo("deep-unreadable-documentation")
        script = reviewed_tests.ReviewedTaskOrderingTest._script(
            contracts.KIND_DRAFT_SLICE_NOTE
        )
        script[0]["response"]["artifact"] = "docs/missing-slice.md"
        parent, store, _used = self._execute(
            workspace, [], documentation_script=script, expect_paused=True
        )
        documentation = store.related(parent["id"], "documentation", None)
        self.assertEqual(documentation["result"]["status"], "success")
        self.assertIsNone(parent["result"])
        paused = store.lifecycle(parent["id"])
        self.assertEqual(paused["status"], "paused")
        self.assertIn("artifact is unavailable", paused["reason"])
        self.assertIsNone(store.related(parent["id"], "implementation", "a"))
        self.assertEqual(self.request(
            "POST", "/api/tasks/%s/stop" % parent["id"], {}
        )[0], 200)
        parent = self._wait_terminal(parent["id"])
        for field in (
            "duration_s", "token_usage", "token_usage_partial",
            "cost", "cost_partial",
        ):
            self.assertEqual(
                parent["result"][field], documentation["result"][field]
            )

    def test_cut_chain_gates_a_b_c_and_mounts_exact_remaining_scope(self):
        workspace = self._repo("deep-cut-chain")
        cut_a = {
            "cut_scope": "Complete the storage seam.",
            "remaining_scope": "Wire the host and focused tests.",
        }
        cut_b = {
            "cut_scope": "Wire the host.",
            "remaining_scope": "Add the focused tests only.",
        }
        part_c_script = reviewed_tests.ReviewedTaskOrderingTest._script(
            contracts.KIND_IMPLEMENT, marker="part-c"
        )
        part_c_script = [
            part_c_script[0],
            reviewed_tests.step(
                contracts.KIND_REVIEW_ROUND,
                reviewed_tests.report(contracts.KIND_REVIEW_ROUND, [
                    finding(
                        "SCOPE-1", "the focused proof is incomplete",
                        severity="P1",
                    )
                ]),
            ),
            reclassify(False, "claude"),
            reviewed_tests.step(
                contracts.KIND_FIX_FINDINGS,
                fix_ok([
                    triaged(
                        "SCOPE-1", "fixed", "the focused proof is incomplete",
                        severity="P1",
                    )
                ], files_changed=["standalone.py"]),
                side_effect=append_file(
                    "standalone.py", "# focused proof\n"
                ),
            ),
            reviewed_tests.step(
                contracts.KIND_DELTA_REVIEW,
                reviewed_tests.report(contracts.KIND_DELTA_REVIEW),
            ),
            reviewed_tests.step(
                contracts.KIND_REVIEW_ROUND,
                reviewed_tests.report(contracts.KIND_REVIEW_ROUND),
            ),
            reviewed_tests.step(
                contracts.KIND_REVIEW_ROUND,
                reviewed_tests.report(contracts.KIND_REVIEW_ROUND),
            ),
            part_c_script[-1],
        ]
        for call in part_c_script:
            call.pop("expect_family", None)
        pausing = _PausingImplementationStore(self.home)

        def before_wait(parent_id, store):
            self.assertTrue(store.write_entered.wait(5))
            part_a = store.related(parent_id, "implementation", "a")
            lifecycle = st.load(task_api.reviewed_state_path(
                self.home, part_a["id"]
            ))
            selected = next(
                unit for unit in lifecycle["units"]
                if st.unit_key(unit) == lifecycle["reviewed_task"]["unit"]
            )
            self.assertTrue(selected["gate_commit"])
            self.assertIsNone(part_a["result"])
            self.assertIsNone(store.related(parent_id, "implementation", "b"))
            store.allow_write.set()

        parent, store, used = self._execute(workspace, [
            ("part-a", cut_a),
            ("part-b", cut_b),
            runners.MockRunner(part_c_script),
        ], store=pausing, before_wait=before_wait)
        children = [
            store.related(parent["id"], "implementation", part)
            for part in ("a", "b", "c")
        ]
        self.assertTrue(all(child is not None for child in children))
        self.assertIsNone(store.related(parent["id"], "implementation", "d"))
        self.assertEqual(
            [child["parent"]["part"] for child in children],
            ["a", "b", "c"],
        )
        self.assertEqual(
            children[0]["result"]["native_result"]["production_result"]
            ["implementation_cut"], cut_a,
        )
        self.assertEqual(
            children[1]["result"]["native_result"]["production_result"]
            ["implementation_cut"], cut_b,
        )
        expected_scopes = {
            "b": cut_a["remaining_scope"],
            "c": cut_b["remaining_scope"],
        }
        for child, part in zip(children, ("a", "b", "c")):
            lifecycle = st.load(task_api.reviewed_state_path(
                self.home, child["id"]
            ))
            if part == "a":
                self.assertNotIn(
                    "implementation_scope", lifecycle["reviewed_task"]
                )
                continue
            self.assertEqual(lifecycle["reviewed_task"]["implementation_scope"], {
                "part": part,
                "scope": expected_scopes[part],
                "delegated_remaining": None,
                "source_unit": children[ord(part) - ord("b")]["id"],
            })

        part_a_calls = used[1].calls
        production_prompt = next(
            prompt for _family, kind, prompt in part_a_calls
            if kind == contracts.KIND_IMPLEMENT
        )
        self.assertNotIn("SEQUENTIAL IMPLEMENTATION PART", production_prompt)
        for _family, kind, prompt in part_a_calls:
            if kind == contracts.KIND_REVIEW_ROUND:
                self.assertIn("SEQUENTIAL IMPLEMENTATION PART — a", prompt)
                self.assertIn(json.dumps(cut_a["cut_scope"]), prompt)

        part_c_calls = [
            (kind, prompt) for _family, kind, prompt in used[3].calls
            if kind in (
                contracts.KIND_IMPLEMENT,
                contracts.KIND_REVIEW_ROUND,
                contracts.KIND_FIX_FINDINGS,
                contracts.KIND_DELTA_REVIEW,
            )
        ]
        observed_kinds = {kind for kind, _prompt in part_c_calls}
        self.assertTrue({
            contracts.KIND_FIX_FINDINGS, contracts.KIND_DELTA_REVIEW,
        }.issubset(observed_kinds), (observed_kinds, children[2]["result"]))
        for _kind, prompt in part_c_calls:
            self.assertIn("SEQUENTIAL IMPLEMENTATION PART — c", prompt)
            self.assertIn(json.dumps(cut_b["remaining_scope"]), prompt)
        self.assertEqual(parent["result"]["status"], "success")

    def test_final_uncut_part_completes_parent_with_child_owned_results_and_single_count_totals(self):
        workspace = self._repo("deep-final-aggregate")
        cut_a = {"cut_scope": "part a", "remaining_scope": "part b and c"}
        cut_b = {"cut_scope": "part b", "remaining_scope": "part c"}
        parent, store, _used = self._execute(
            workspace, [
                ("part-a", cut_a), ("part-b", cut_b), ("part-c", None),
            ]
        )
        documentation = store.related(parent["id"], "documentation", None)
        implementations = [
            store.related(parent["id"], "implementation", part)
            for part in ("a", "b", "c")
        ]
        child_results = [documentation["result"]] + [
            child["result"] for child in implementations
        ]
        self.assertEqual(
            parent["result"],
            task_api.DirectTaskHost._deep_result("success", child_results),
        )
        self.assertIsNone(parent["result"]["native_result"])
        gates = [
            child["result"]["native_result"]["gate_commit"]
            for child in [documentation] + implementations
        ]
        self.assertEqual(len(set(gates)), 4)
        self.assertEqual(self._git(workspace, "rev-parse", "--short", "HEAD"),
                         gates[-1])
        known = []
        for index in (1, 2):
            known.append({
                "duration_s": float(index),
                "token_usage": {
                    "input_tokens": index,
                    "cached_input_tokens": 0,
                    "output_tokens": index,
                    "reasoning_output_tokens": 0,
                    "total_tokens": index * 2,
                },
                "token_usage_partial": index == 2,
                "cost": {"api_usd": index / 10, "real_usd": 0.0},
                "cost_partial": False,
            })
        aggregate = task_api.DirectTaskHost._deep_result("success", known)
        self.assertEqual(aggregate["duration_s"], 3.0)
        self.assertEqual(aggregate["token_usage"]["total_tokens"], 6)
        self.assertTrue(aggregate["token_usage_partial"])
        self.assertAlmostEqual(aggregate["cost"]["api_usd"], 0.3)
        self.assertFalse(aggregate["cost_partial"])

    def test_failure_pauses_and_stop_settles_all_child_accounting_without_successors(self):
        cut = {"cut_scope": "part a", "remaining_scope": "part b"}
        failed_parent, failed_store, _used = self._execute(
            self._repo("deep-child-failure"), [
                ("part-a", cut), runners.MockRunner([]),
            ], expect_paused=True,
        )
        failed_children = [
            failed_store.related(
                failed_parent["id"], "documentation", None
            ),
            failed_store.related(
                failed_parent["id"], "implementation", "a"
            ),
            failed_store.related(
                failed_parent["id"], "implementation", "b"
            ),
        ]
        self.assertIsNone(failed_parent["result"])
        self.assertIsNone(failed_children[-1]["result"])
        self.assertEqual(failed_store.lifecycle(failed_parent["id"])["status"], "paused")
        self.assertEqual(failed_store.lifecycle(failed_children[-1]["id"])["status"], "paused")
        cancellation_runner = runners.MockRunner([])
        self._last_execution_host.runner_factory = lambda *_args: cancellation_runner
        self.assertIsNone(
            failed_store.related(
                failed_parent["id"], "implementation", "c"
            )
        )
        self.assertEqual(self.request(
            "POST", "/api/tasks/%s/stop" % failed_parent["id"], {}
        )[0], 200)
        failed_parent = self._wait_terminal(failed_parent["id"])
        failed_children = [failed_store.record(child["id"]) for child in failed_children]
        self.assertEqual(failed_parent["result"]["status"], "failure")
        self.assertEqual(failed_children[-1]["result"]["status"], "failure")
        self.assertEqual(cancellation_runner.calls, [])
        self.assertEqual(
            failed_parent["result"],
            task_api.DirectTaskHost._deep_result(
                "failure",
                [child["result"] for child in failed_children],
                failed_children[-1]["result"]["reason"],
            ),
        )

        workspace = self._repo("deep-implementation-stop")
        late = deep_tests._LateResultRunner(
            reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_IMPLEMENT
            )
        )
        pending = [
            runners.MockRunner(
                reviewed_tests.ReviewedTaskOrderingTest._script(
                    contracts.KIND_DRAFT_SLICE_NOTE
                )
            ),
            late,
        ]
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: pending.pop(0),
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
            self.assertTrue(late.entered.wait(5))
            active = self._wait_related(
                parent_id, "implementation", "a", terminal=False
            )
            status, stopped = self.request(
                "POST", "/api/tasks/%s/stop" % parent_id, {}
            )
            self.assertEqual((status, stopped["state"]), (200, "stopping"))
            self.assertTrue(host.owns_workspace(workspace))
            self.assertIsNone(
                task_api.StandaloneTaskStore(self.home).record(parent_id)[
                    "result"
                ]
            )
            self.assertIsNone(
                task_api.StandaloneTaskStore(self.home).record(active["id"])[
                    "result"
                ]
            )
            late.release.set()
            stopped_parent = self._wait_terminal(parent_id)
            stopped_child = self._wait_related(
                parent_id, "implementation", "a", terminal=True
            )

        stopped_store = task_api.StandaloneTaskStore(self.home)
        documentation = stopped_store.related(
            parent_id, "documentation", None
        )
        self.assertEqual(stopped_child["result"]["status"], "failure")
        self.assertEqual(stopped_parent["result"]["status"], "failure")
        self.assertEqual(
            stopped_parent["result"]["reason"],
            stopped_child["result"]["reason"],
        )
        self.assertEqual(
            stopped_parent["result"],
            task_api.DirectTaskHost._deep_result(
                "failure",
                [documentation["result"], stopped_child["result"]],
                stopped_child["result"]["reason"],
            ),
        )
        self.assertIsNone(
            stopped_store.related(parent_id, "implementation", "b")
        )
        self.assertEqual(len(late.calls), 1)
        self.assertFalse(host.owns_workspace(workspace))

    def test_accepted_stop_survives_host_recovery_and_settles_active_part(self):
        workspace = self._repo("deep-durable-stop")
        store = task_api.StandaloneTaskStore(self.home)
        parent = store.admit(
            tasks.validate_order(self._deep_order(workspace)), {}, workspace
        )
        artifact = Path(workspace) / "docs" / "slice-01.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("# Reviewed slice\n", encoding="utf-8")
        self._git(workspace, "add", "docs/slice-01.md")
        self._git(workspace, "commit", "-q", "-m", "Documentation gate")
        with registry.locked(self.home):
            documentation = store.admit_related_locked(
                parent["id"], "documentation", None,
                task_api.DirectTaskHost._deep_child_order(parent), {}, workspace,
            )
        documentation = store.record_result(
            documentation["id"], self._stored_success({
                "production_result": {"artifact": "docs/slice-01.md"},
                "review_evidence": {"reviews": ["documentation"]},
                "gate_commit": self._git(workspace, "rev-parse", "HEAD"),
            })
        )
        with registry.locked(self.home):
            implementation = store.admit_related_locked(
                parent["id"], "implementation", "a",
                task_api.DirectTaskHost._deep_implementation_order(
                    parent, str(artifact.resolve())
                ),
                {}, workspace,
            )

        session_id, waiting, create = (
            reviewed_tests.ReviewedTaskOrderingTest._waiting_rethink_session(
                self, workspace, "deep-durable-stop.md"
            )
        )
        session_usage, session_cost = (
            reviewed_tests.ReviewedTaskOrderingTest
            ._record_brainstorming_activity(self, session_id)
        )
        path = task_api.ensure_reviewed_state(
            self.home,
            implementation,
            reviewed_tests.ReviewedTaskOrderingTest._config(),
        )
        subject = drv.Driver(
            path,
            runner=runners.MockRunner([
                reviewed_tests.ReviewedTaskOrderingTest._rethink_step(
                    contracts.KIND_IMPLEMENT
                )
            ]),
            model_profiles_home=self.home,
        )
        with mock.patch.object(
            brainstorming_milestone, "create_session", side_effect=create
        ), mock.patch.object(
            brainstorming_milestone, "terminal_handoff", return_value=None
        ):
            reviewed_tests.ReviewedTaskOrderingTest._standalone_step(subject)

        previous_host = task_api.DirectTaskHost(self.home, store=store)
        with previous_host._lock:
            previous_host._active[parent["id"]] = workspace
        reason = "stopped before host recovery"
        self.assertTrue(previous_host.stop(parent["id"], reason))
        self.assertEqual(
            task_api.StandaloneTaskStore(self.home).stop_reason(parent["id"]),
            reason,
        )
        with mock.patch.object(
            brainstorming_lifecycle,
            "_launch_lifecycle_process",
        ) as launched:
            status, refused = self.request(
                "POST",
                "/api/brainstorming/sessions/%s/continue" % session_id,
                {"waiting_revision": waiting.revision},
            )
        self.assertEqual(
            (status, refused["error"]),
            (409, brainstorming_lifecycle.CONTINUATION_CONFLICT),
        )
        launched.assert_not_called()

        settlement_runner = runners.MockRunner([])
        recovered_host = task_api.DirectTaskHost(
            self.home,
            store=task_api.StandaloneTaskStore(self.home),
            runner_factory=lambda *_args: settlement_runner,
            poll_interval=0.001,
        )
        outcome = recovered_host.adopt_open_tasks(
            lambda _record: reviewed_tests.ReviewedTaskOrderingTest._config
        )
        stopped_parent = self._wait_terminal(parent["id"])
        stopped_child = store.record(implementation["id"])

        self.assertIn(parent["id"], outcome["adopted"])
        self.assertEqual(stopped_child["result"]["status"], "failure")
        self.assertEqual(stopped_child["result"]["reason"], reason)
        self.assertEqual(stopped_child["result"]["token_usage"], session_usage)
        self.assertEqual(stopped_child["result"]["cost"], session_cost)
        self.assertEqual(stopped_parent["result"]["status"], "failure")
        self.assertEqual(stopped_parent["result"]["reason"], reason)
        self.assertEqual(stopped_parent["result"]["token_usage"], session_usage)
        self.assertEqual(stopped_parent["result"]["cost"], session_cost)
        self.assertEqual(
            stopped_parent["result"],
            task_api.DirectTaskHost._deep_result(
                "failure",
                [documentation["result"], stopped_child["result"]],
                reason,
            ),
        )
        self.assertIsNone(
            store.related(parent["id"], "implementation", "b")
        )
        self.assertEqual(store.stop_reason(parent["id"]), reason)
        self.assertNotIn("stop_reason", store.record(parent["id"]))
        self.assertEqual(settlement_runner.calls, [])
        terminal_session = brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        ).read(session_id)
        self.assertEqual(terminal_session.state["status"], "failure")
        child_lifecycle = st.load(task_api.reviewed_state_path(
            self.home, implementation["id"]
        ))
        child_unit = next(
            item for item in st.summary(child_lifecycle)["units"]
            if item["unit"] == child_lifecycle["reviewed_task"]["unit"]
        )
        self.assertEqual(
            next(
                item for item in child_unit["brainstormings"]
                if item["session_id"] == session_id
            )["outcome"],
            "failed",
        )
        status, refused = self.request(
            "POST",
            "/api/brainstorming/sessions/%s/rounds" % session_id,
            {"maximum": 2},
        )
        self.assertEqual(
            (status, refused["error"]),
            (409, brainstorming_lifecycle.CONTINUATION_CONFLICT),
        )
        status, refused = self.request(
            "POST",
            "/api/brainstorming/sessions/%s/continue" % session_id,
            {"waiting_revision": waiting.revision},
        )
        self.assertEqual(
            (status, refused["error"]),
            (409, brainstorming_lifecycle.CONTINUATION_CONFLICT),
        )

    def test_part_admission_crash_windows_and_races_reuse_exact_child(self):
        cut = {
            "cut_scope": "gate-backed part a",
            "remaining_scope": "recover exactly part b",
        }
        for window in ("before", "after"):
            with self.subTest(window=window):
                workspace = self._repo("deep-part-recovery-%s" % window)
                store = task_api.StandaloneTaskStore(self.home)
                parent = store.admit(
                    tasks.validate_order(self._deep_order(workspace)),
                    {},
                    workspace,
                )
                artifact = Path(workspace) / "docs" / "slice-01.md"
                artifact.parent.mkdir(parents=True)
                artifact.write_text("# Reviewed slice\n", encoding="utf-8")
                self._git(workspace, "add", "docs/slice-01.md")
                self._git(workspace, "commit", "-q", "-m", "Documentation gate")
                with registry.locked(self.home):
                    documentation = store.admit_related_locked(
                        parent["id"],
                        "documentation",
                        None,
                        task_api.DirectTaskHost._deep_child_order(parent),
                        {},
                        workspace,
                    )
                store.record_result(documentation["id"], self._stored_success({
                    "production_result": {"artifact": "docs/slice-01.md"},
                    "review_evidence": {"reviews": ["documentation"]},
                    "gate_commit": self._git(
                        workspace, "rev-parse", "--short", "HEAD"
                    ),
                }))

                part_a_path = Path(workspace) / "part-a.py"
                part_a_path.write_text("PART = 'a'\n", encoding="utf-8")
                self._git(workspace, "add", part_a_path.name)
                self._git(workspace, "commit", "-q", "-m", "Part a gate")
                implementation_order = (
                    task_api.DirectTaskHost._deep_implementation_order(
                        parent, str(artifact.resolve())
                    )
                )
                with registry.locked(self.home):
                    predecessor = store.admit_related_locked(
                        parent["id"],
                        "implementation",
                        "a",
                        implementation_order,
                        {},
                        workspace,
                    )
                store.record_result(predecessor["id"], self._stored_success({
                    "production_result": {
                        "files_changed": [part_a_path.name],
                        "implementation_cut": cut,
                    },
                    "review_evidence": {"reviews": ["part-a"]},
                    "gate_commit": self._git(
                        workspace, "rev-parse", "--short", "HEAD"
                    ),
                }, duration_s=2.0))

                with self.assertRaisesRegex(
                    service.ApiError, "retained by its open parent"
                ):
                    service.delete_task(
                        self.home,
                        {"admin": True},
                        predecessor["id"],
                        api_tests.NoopHost(),
                    )

                real_cas = store._store.cas

                def crash_cas(key, expected_revision, value):
                    if window == "after":
                        real_cas(key, expected_revision, value)
                    raise RuntimeError("%s implementation admission" % window)

                with mock.patch.object(
                    store._store, "cas", side_effect=crash_cas
                ), registry.locked(self.home), self.assertRaisesRegex(
                    RuntimeError, "%s implementation admission" % window
                ):
                    store.admit_related_locked(
                        parent["id"],
                        "implementation",
                        "b",
                        implementation_order,
                        {},
                        workspace,
                    )
                first = store.related(
                    parent["id"], "implementation", "b"
                )
                self.assertEqual(first is None, window == "before")

                barrier = threading.Barrier(4)

                def recover_relation():
                    barrier.wait()
                    with registry.locked(self.home):
                        return store.admit_related_locked(
                            parent["id"],
                            "implementation",
                            "b",
                            implementation_order,
                            {},
                            workspace,
                        )

                with futures.ThreadPoolExecutor(4) as pool:
                    recovered = [
                        pool.submit(recover_relation) for _ in range(4)
                    ]
                    recovered = [future.result() for future in recovered]
                child_id = recovered[0]["id"]
                self.assertEqual(
                    {record["id"] for record in recovered}, {child_id}
                )

                host = task_api.DirectTaskHost(self.home, store=store)
                entered = threading.Event()
                release = threading.Event()
                starts = []

                def hold_run(task_id, _resolver):
                    try:
                        # State construction now belongs to the leased run,
                        # so retain that portion when holding dispatch here.
                        task_api.ensure_reviewed_state(
                            self.home, store.record(task_id), _resolver(),
                            implementation_scope=host._deep_implementation_scope(
                                store.record(task_id)
                            ),
                        )
                        starts.append(task_id)
                        entered.set()
                        release.wait(5)
                    finally:
                        with host._lock:
                            host._active.pop(task_id, None)
                            lease = host._leases.pop(task_id, None)
                            if lease is not None:
                                lease.close()

                start_barrier = threading.Barrier(4)

                def recover_lifecycle():
                    start_barrier.wait()
                    return host.start(
                        recovered[0],
                        reviewed_tests.ReviewedTaskOrderingTest._config,
                        parent_task_id=parent["id"],
                    )

                with mock.patch.object(host, "_run", side_effect=hold_run):
                    with futures.ThreadPoolExecutor(4) as pool:
                        attempts = [
                            pool.submit(recover_lifecycle) for _ in range(4)
                        ]
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
                lifecycle = st.load(
                    task_api.reviewed_state_path(self.home, child_id)
                )
                self.assertEqual(lifecycle["reviewed_task"]["implementation_scope"], {
                    "part": "b",
                    "scope": cut["remaining_scope"],
                    "delegated_remaining": None,
                    "source_unit": predecessor["id"],
                })
                self.assertEqual(
                    sum(
                        event["type"] == "reviewed_policy_frozen"
                        for event in lifecycle["events"]
                    ),
                    1,
                )

                runner = runners.MockRunner(
                    reviewed_tests.ReviewedTaskOrderingTest._script(
                        contracts.KIND_IMPLEMENT, marker="recovered-part-b"
                    )
                )
                recovered_host = task_api.DirectTaskHost(
                    self.home,
                    store=store,
                    runner_factory=lambda _config, _workspace: runner,
                    poll_interval=0.001,
                )
                outcome = recovered_host.adopt_open_tasks(
                    lambda _record: (
                        reviewed_tests.ReviewedTaskOrderingTest._config
                    )
                )
                self.assertEqual(outcome["adopted"], [])
                paused = store.lifecycle(parent["id"])
                self.assertEqual(paused["status"], "paused")
                self.assertIsNone(store.record(child_id)["result"])
                recovered_host.resume(
                    parent["id"], reviewed_tests.ReviewedTaskOrderingTest._config,
                    paused["revision"],
                )
                terminal = self._wait_terminal(parent["id"])
                self.assertEqual(terminal["result"]["status"], "success")
                self.assertEqual(
                    store.related(parent["id"], "implementation", "b")["id"],
                    child_id,
                )
                self.assertIsNone(
                    store.related(parent["id"], "implementation", "c")
                )
                self.assertEqual(runner.script, [])

    def test_brainstorming_implementation_finishes_without_size_continuation(self):
        workspace = self._repo("deep-brainstorming-implementation")
        implementation_script = (
            reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_IMPLEMENT
            )[1:]
        )
        implementation_script[-1]["response"]["authority"]["evidence"][0][
            "path"
        ] = "brainstorming-implementation.txt"
        implementation_runner = runners.MockRunner(implementation_script)
        pending = [
            runners.MockRunner(
                reviewed_tests.ReviewedTaskOrderingTest._script(
                    contracts.KIND_DRAFT_SLICE_NOTE
                )
            ),
            implementation_runner,
        ]
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: pending.pop(0),
            poll_interval=0.001,
        )
        self.start_server(host)
        session_id = "deep-brainstorming-implementation"

        def finish(state, task_id, *_args, **_kwargs):
            record = tasks.task_record(state, task_id)
            source = record["order"]["request"]["context"]["session_charge"][
                "repository"
            ]["pre_session_commit"]
            relative = "brainstorming-implementation.txt"
            reviewed_tests.write_file(
                relative, "Brainstorming implementation\n"
            )(workspace)
            self._git(workspace, "add", relative)
            self._git(
                workspace, "commit", "-q", "-m", "Brainstorming delivery"
            )
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
                    "accepted_revision": self._git(
                        workspace, "rev-parse", "HEAD"
                    ),
                },
            })

        configuration = {
            "implementation": {
                "producer": {"task_executor": "brainstorming"}
            }
        }
        with mock.patch.object(
            service,
            "_direct_task_config",
            return_value=reviewed_tests.ReviewedTaskOrderingTest._config(),
        ), mock.patch.object(
            brainstorming_tasks, "resolve_staffing", return_value={
                "dispatch_authority": "static", "participants": []
            }
        ), mock.patch.object(
            brainstorming_tasks,
            "start_task",
            return_value={"id": session_id},
        ), mock.patch.object(
            brainstorming_tasks, "finish_task", side_effect=finish
        ):
            status, body = self.request(
                "POST",
                "/api/tasks",
                self._deep_order(workspace, configuration=configuration),
            )
            self.assertEqual(status, 201, body)
            parent = self._wait_terminal(body["task"]["id"])

        store = task_api.StandaloneTaskStore(self.home)
        child = store.related(parent["id"], "implementation", "a")
        self.assertEqual(parent["result"]["status"], "success")
        self.assertEqual(child["result"]["status"], "success")
        self.assertEqual(
            child["order"]["configuration"]["producer"]["task_executor"],
            "brainstorming",
        )
        self.assertNotIn(
            "implementation_size_control", child["order"]["configuration"]
        )
        self.assertNotIn(
            "implementation_cut",
            child["result"]["native_result"]["production_result"],
        )
        self.assertIsNone(
            store.related(parent["id"], "implementation", "b")
        )
        lifecycle = st.load(
            task_api.reviewed_state_path(self.home, child["id"])
        )
        self.assertFalse(any(
            event["type"].startswith("implementation_size_")
            for event in lifecycle["events"]
        ))
        self.assertEqual(len(implementation_runner.calls), 3)
        self.assertEqual(pending, [])


if __name__ == "__main__":
    unittest.main()
