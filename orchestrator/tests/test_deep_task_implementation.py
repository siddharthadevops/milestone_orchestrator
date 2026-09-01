"""Slice 7 focused proof for sequential deep implementation delivery."""

import copy
import json
import time
import unittest
from pathlib import Path
from unittest import mock

from orchestrator import contracts, runners, service, task_api, tasks
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
            parent = self._wait_terminal(body["task"]["id"])
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

    def test_unreadable_documentation_artifact_fails_parent_without_implementation(self):
        workspace = self._repo("deep-unreadable-documentation")
        script = reviewed_tests.ReviewedTaskOrderingTest._script(
            contracts.KIND_DRAFT_SLICE_NOTE
        )
        script[0]["response"]["artifact"] = "docs/missing-slice.md"
        parent, store, _used = self._execute(
            workspace, [], documentation_script=script
        )
        documentation = store.related(parent["id"], "documentation", None)
        self.assertEqual(documentation["result"]["status"], "success")
        self.assertEqual(parent["result"]["status"], "failure")
        self.assertIn("artifact is unavailable", parent["result"]["reason"])
        self.assertIsNone(store.related(parent["id"], "implementation", "a"))
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


if __name__ == "__main__":
    unittest.main()
