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

    def _execute(self, workspace, implementations, **order_options):
        owned_runners = [runners.MockRunner(
            reviewed_tests.ReviewedTaskOrderingTest._script(
                contracts.KIND_DRAFT_SLICE_NOTE
            )
        )]
        owned_runners.extend(
            runners.MockRunner(
                reviewed_tests.ReviewedTaskOrderingTest._script(
                    contracts.KIND_IMPLEMENT, marker=marker, cut=cut
                )
            )
            for marker, cut in implementations
        )
        pending = list(owned_runners)
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
                "POST", "/api/tasks",
                self._deep_order(workspace, **order_options),
            )
            self.assertEqual(status, 201, body)
            parent = self._wait_terminal(body["task"]["id"])
        self.assertEqual(pending, [])
        return parent, task_api.StandaloneTaskStore(self.home), owned_runners

    def test_documentation_gate_admits_one_public_part_a_with_frozen_authority(self):
        workspace = self._repo("deep-implementation-authority")
        reference = Path(workspace) / "operator-note.md"
        reference.write_text("operator authority\n", encoding="utf-8")
        self._git(workspace, "add", reference.name)
        self._git(workspace, "commit", "-q", "-m", "Reference authority")
        store = deep_tests._PausingResultStore(self.home)
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
        parent, store, used = self._execute(workspace, [
            ("part-a", cut_a), ("part-b", cut_b), ("part-c", None),
        ])
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
        expected_scopes = [
            parent["order"]["request"]["request"],
            cut_a["remaining_scope"],
            cut_b["remaining_scope"],
        ]
        cuts = {"a": cut_a, "b": cut_b}
        for child, runner, part, scope in zip(
            children, used[1:], ("a", "b", "c"), expected_scopes
        ):
            lifecycle = st.load(task_api.reviewed_state_path(
                self.home, child["id"]
            ))
            self.assertEqual(lifecycle["reviewed_task"]["implementation_scope"], {
                "part": part,
                "scope": scope,
                "delegated_remaining": None,
                "source_unit": (
                    parent["id"] if part == "a" else
                    children[ord(part) - ord("b")]["id"]
                ),
            })
            for _family, kind, prompt in runner.calls:
                if kind not in (
                    contracts.KIND_IMPLEMENT, contracts.KIND_REVIEW_ROUND
                ):
                    continue
                expected = scope
                if kind == contracts.KIND_REVIEW_ROUND and part in cuts:
                    expected = cuts[part]["cut_scope"]
                self.assertIn(
                    "SEQUENTIAL IMPLEMENTATION PART — %s" % part, prompt
                )
                self.assertIn(json.dumps(expected, ensure_ascii=False), prompt)
        self.assertEqual(parent["result"]["status"], "success")

    def test_final_uncut_part_completes_parent_with_child_owned_results_and_single_count_totals(self):
        workspace = self._repo("deep-final-aggregate")
        parent, store, _used = self._execute(
            workspace, [("only-part", None)]
        )
        documentation = store.related(parent["id"], "documentation", None)
        implementation = store.related(parent["id"], "implementation", "a")
        child_results = [documentation["result"], implementation["result"]]
        self.assertEqual(
            parent["result"],
            task_api.DirectTaskHost._deep_result("success", child_results),
        )
        self.assertIsNone(parent["result"]["native_result"])
        gates = [
            child["result"]["native_result"]["gate_commit"]
            for child in (documentation, implementation)
        ]
        self.assertEqual(len(set(gates)), 2)
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
