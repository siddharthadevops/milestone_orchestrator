"""Focused tests for the generic task contracts and catalogue."""

import copy
from concurrent import futures
import math
import os
import tempfile
import threading
import unittest
from unittest import mock

from orchestrator import brainstorming
from orchestrator import state as st
from orchestrator import tasks


def task_request(**changes):
    value = {
        "work_area": {
            "workspace_path": "/workspace",
            "primary": "/workspace",
            "additional": ["/reference"],
        },
        "request": "Produce the requested content.",
        "context": {"nested": [1, True, None]},
        "reference_documents": ["docs/a.md", "../reference/b.md"],
    }
    value.update(changes)
    return value


def token_usage(**changes):
    value = {
        "input_tokens": 10,
        "cached_input_tokens": 2,
        "output_tokens": 5,
        "reasoning_output_tokens": 1,
        "total_tokens": 15,
    }
    value.update(changes)
    return value


def task_result(**changes):
    value = {
        "status": "success",
        "duration_s": 2,
        "token_usage": token_usage(),
        "token_usage_partial": False,
        "cost": {"api_usd": 0.2, "real_usd": 0.1},
        "cost_partial": False,
        "native_result": {"files_changed": ["a.py"]},
    }
    value.update(changes)
    return value


def task_order(task_executor="worker", **request_changes):
    return {
        "task_executor": task_executor,
        "request": task_request(**request_changes),
    }


def persisted_state(workspace):
    path = os.path.join(workspace, "state.json")
    state = st.new_state(
        "Exercise durable tasks.",
        workspace,
        {"families_order": ["codex", "claude"]},
    )
    st.save_new(path, state)
    return path


class TaskContractsTest(unittest.TestCase):
    def assert_request_error(self, code, function, *args):
        with self.assertRaises(tasks.TaskRequestError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)

    def test_catalogue_has_exact_builtins_and_self_description(self):
        catalogue = tasks.task_executor_catalogue()
        self.assertIsInstance(catalogue, list)
        self.assertEqual(
            [entry["id"] for entry in catalogue],
            ["worker", "brainstorming"],
        )
        fields = {
            "id",
            "name",
            "description",
            "operating_mode",
            "usage_examples",
            "available_agent_configurations",
            "configuration_schema",
        }
        for entry in catalogue:
            self.assertEqual(set(entry), fields)
            for field in ("name", "description", "operating_mode"):
                self.assertIsInstance(entry[field], str)
                self.assertTrue(entry[field].strip())
            self.assertTrue(entry["usage_examples"])
            for example in entry["usage_examples"]:
                self.assertIsInstance(example, str)
                self.assertLess(len(example.split()), 10)
            self.assertIsInstance(
                entry["available_agent_configurations"], str
            )
            self.assertTrue(entry["available_agent_configurations"].strip())

        self.assertEqual(catalogue[0]["configuration_schema"], {})
        self.assertEqual(
            catalogue[1]["configuration_schema"],
            {
                "max_rounds": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 10,
                },
                "closure_policy": {
                    "type": "choice",
                    "choices": ["unanimity", "majority"],
                    "default": "unanimity",
                },
            },
        )
        self.assertEqual(
            catalogue[1]["configuration_schema"]["closure_policy"][
                "choices"
            ],
            list(brainstorming.CLOSURE_POLICIES),
        )
        catalogue[1]["configuration_schema"]["max_rounds"]["default"] = 99
        self.assertEqual(
            tasks.task_executor_catalogue()[1]["configuration_schema"]
            ["max_rounds"]["default"],
            10,
        )

    def test_configuration_schema_and_resolution(self):
        self.assertEqual(tasks.resolve_configuration("worker"), {})
        self.assertEqual(tasks.resolve_configuration("worker", {}), {})
        self.assertEqual(
            tasks.resolve_configuration("brainstorming"),
            {"max_rounds": 10, "closure_policy": "unanimity"},
        )
        self.assertEqual(
            tasks.resolve_configuration(
                "brainstorming", {"max_rounds": 4}
            ),
            {"max_rounds": 4, "closure_policy": "unanimity"},
        )
        self.assertEqual(
            tasks.resolve_configuration(
                "brainstorming", {"closure_policy": "majority"}
            ),
            {"max_rounds": 10, "closure_policy": "majority"},
        )

        invalid = [
            ("worker", {"max_rounds": 1}),
            ("worker", None),
            ("brainstorming", {"max_rounds": True}),
            ("brainstorming", {"max_rounds": 1.0}),
            ("brainstorming", {"max_rounds": 0}),
            ("brainstorming", {"max_rounds": -1}),
            ("brainstorming", {"closure_policy": "consensus"}),
            ("brainstorming", {"agent": "codex"}),
            ("brainstorming", []),
        ]
        for executor, configuration in invalid:
            with self.subTest(executor=executor, configuration=configuration):
                self.assert_request_error(
                    tasks.INVALID_TASK_REQUEST,
                    tasks.resolve_configuration,
                    executor,
                    configuration,
                )
        self.assert_request_error(
            tasks.UNKNOWN_TASK_EXECUTOR,
            tasks.resolve_configuration,
            "other",
        )
        self.assert_request_error(
            tasks.INVALID_TASK_REQUEST,
            tasks.resolve_configuration,
            1,
        )

        definition = tasks._TASK_EXECUTOR_BY_ID["brainstorming"][
            "configuration_schema"
        ]["max_rounds"]
        with mock.patch.dict(definition, {"default": 17}):
            self.assertEqual(
                tasks.task_executor_catalogue()[1]["configuration_schema"]
                ["max_rounds"]["default"],
                17,
            )
            self.assertEqual(
                tasks.resolve_configuration("brainstorming")["max_rounds"],
                17,
            )

    def test_request_and_order_contracts(self):
        source = task_request(output_directory="../requested-output")
        checked = tasks.validate_request(source)
        self.assertEqual(checked, source)
        self.assertIsNot(checked, source)
        self.assertIsNot(checked["context"], source["context"])
        source["context"]["nested"].append("later")
        self.assertNotIn("later", checked["context"]["nested"])
        self.assertEqual(
            checked["reference_documents"],
            ["docs/a.md", "../reference/b.md"],
        )
        for context in (None, "brief", [1, False], 0):
            with self.subTest(context=context):
                self.assertEqual(
                    tasks.validate_request(task_request(context=context))[
                        "context"
                    ],
                    context,
                )
        self.assertEqual(
            tasks.validate_request(task_request(reference_documents=[]))[
                "reference_documents"
            ],
            [],
        )

        order = tasks.validate_order(
            {"task_executor": "worker", "request": task_request()}
        )
        self.assertEqual(order["configuration"], {})
        self.assertEqual(order["request"], task_request())
        brainstorming_order = tasks.validate_order(
            {
                "task_executor": "brainstorming",
                "request": task_request(),
                "configuration": {"max_rounds": 3},
            }
        )
        self.assertEqual(
            brainstorming_order["configuration"],
            {"max_rounds": 3, "closure_policy": "unanimity"},
        )

        invalid_requests = []
        for missing in (
            "work_area",
            "request",
            "context",
            "reference_documents",
        ):
            value = task_request()
            del value[missing]
            invalid_requests.append(value)
        for extra in ("target_path", "artifacts", "domain_kind"):
            invalid_requests.append(task_request(**{extra: "not allowed"}))
        invalid_requests.extend(
            [
                task_request(work_area={}),
                task_request(work_area=[]),
                task_request(work_area={1: "not JSON"}),
                task_request(request="  "),
                task_request(request=1),
                task_request(context={"bad": {1, 2}}),
                task_request(context=math.nan),
                task_request(reference_documents="docs/a.md"),
                task_request(reference_documents=[""]),
                task_request(reference_documents=[1]),
                task_request(output_directory=""),
                task_request(output_directory=1),
                {**task_request(), 1: "not a field name"},
            ]
        )
        for value in invalid_requests:
            with self.subTest(request=value):
                self.assert_request_error(
                    tasks.INVALID_TASK_REQUEST, tasks.validate_request, value
                )

        invalid_orders = [
            {},
            {"task_executor": "worker"},
            {"request": task_request()},
            {
                "task_executor": "worker",
                "request": task_request(),
                "extra": True,
            },
            {"task_executor": 1, "request": task_request()},
            {"task_executor": "worker", "request": []},
            {
                "task_executor": "worker",
                "request": task_request(),
                "configuration": None,
            },
        ]
        for value in invalid_orders:
            with self.subTest(order=value):
                self.assert_request_error(
                    tasks.INVALID_TASK_REQUEST, tasks.validate_order, value
                )
        self.assert_request_error(
            tasks.UNKNOWN_TASK_EXECUTOR,
            tasks.validate_order,
            {"task_executor": "other", "request": task_request()},
        )

    def test_result_contract_and_native_opacity(self):
        success_source = task_result(
            native_result={
                "files_changed": ["a.py"],
                "nested": {"answer": [True, None, 3.5]},
            }
        )
        success = tasks.validate_result(success_source)
        self.assertEqual(success, success_source)
        self.assertEqual(success["duration_s"], 2.0)
        success_source["native_result"]["nested"]["answer"].append("later")
        self.assertNotIn(
            "later", success["native_result"]["nested"]["answer"]
        )

        failure = tasks.validate_result(
            task_result(
                status="failure",
                reason="The session could not finish.",
                token_usage=None,
                token_usage_partial=True,
                cost=None,
                cost_partial=True,
                native_result={
                    "session": {"id": "brainstorming-1"},
                    "transcript": ["position", "objection"],
                },
            )
        )
        self.assertEqual(failure["status"], "failure")
        self.assertIsNone(failure["token_usage"])
        self.assertEqual(
            failure["native_result"]["transcript"],
            ["position", "objection"],
        )
        known_partial = tasks.validate_result(
            task_result(token_usage_partial=True, cost_partial=True)
        )
        self.assertIsNotNone(known_partial["token_usage"])

        invalid = [
            task_result(extra=True),
            task_result(status="pending"),
            task_result(reason="success cannot explain failure"),
            task_result(status="failure"),
            task_result(status="failure", reason=""),
            task_result(duration_s=True),
            task_result(duration_s=-1),
            task_result(duration_s=math.inf),
            task_result(duration_s=10**400),
            task_result(duration_s="2"),
            task_result(token_usage=None),
            task_result(token_usage_partial=1),
            task_result(token_usage=token_usage(total_tokens=14)),
            task_result(token_usage=token_usage(cached_input_tokens=11)),
            task_result(token_usage=token_usage(reasoning_output_tokens=6)),
            task_result(token_usage=token_usage(input_tokens=True)),
            task_result(token_usage=token_usage(extra=0)),
            task_result(cost=None),
            task_result(cost_partial=1),
            task_result(cost={"api_usd": 0.1}),
            task_result(cost={"api_usd": 0.1, "real_usd": 0.2}),
            task_result(cost={"api_usd": 2**53, "real_usd": 2**53 + 1}),
            task_result(cost={"api_usd": 10**400, "real_usd": 0}),
            task_result(cost={"api_usd": math.nan, "real_usd": 0.0}),
            task_result(cost={"api_usd": True, "real_usd": 0.0}),
            task_result(
                cost={"api_usd": 0.1, "real_usd": 0.0, "extra": 0.0}
            ),
            task_result(native_result={"not": {"json"}}),
            task_result(native_result=math.nan),
            {**task_result(), 1: "not a field name"},
        ]
        for field in (
            "status",
            "duration_s",
            "token_usage",
            "token_usage_partial",
            "cost",
            "cost_partial",
            "native_result",
        ):
            missing = task_result()
            del missing[field]
            invalid.append(missing)
        malformed_usage = task_result()
        del malformed_usage["token_usage"]["total_tokens"]
        invalid.append(malformed_usage)
        for value in invalid:
            with self.subTest(result=value):
                with self.assertRaises(tasks.ContractError):
                    tasks.validate_result(copy.deepcopy(value))


class DurableTaskRecordsTest(unittest.TestCase):
    def assert_request_error(self, function, *args):
        with self.assertRaises(tasks.TaskRequestError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, tasks.INVALID_TASK_REQUEST)

    def test_admission_freezes_one_task_and_terminal_result(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as workspace:
            state_path = persisted_state(workspace)
            outside = os.path.join(os.path.dirname(workspace), "outside")
            self.assert_request_error(
                tasks.admit_persisted_task,
                state_path,
                task_order(output_directory=outside),
                {"seat": "worker"},
                workspace,
            )
            self.assertNotIn("tasks", st.load(state_path))
            with mock.patch.object(tasks.st, "save", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    tasks.admit_persisted_task(
                        state_path,
                        task_order(),
                        {"seat": "worker"},
                        workspace,
                    )
            self.assertEqual(tasks.task_records(st.load(state_path)), [])

            source_order = task_order(output_directory="planned/missing")
            source_staffing = {"seat": {"family": "codex", "ordinal": 1}}
            first = tasks.admit_persisted_task(
                state_path, source_order, source_staffing, workspace
            )
            second = tasks.admit_persisted_task(
                state_path, source_order, source_staffing, workspace
            )
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(first["result"], None)
            self.assertEqual(
                first["order"]["request"]["output_directory"],
                os.path.realpath(os.path.join(workspace, "planned/missing")),
            )
            self.assertFalse(os.path.exists(os.path.join(workspace, "planned")))

            source_order["request"]["context"]["nested"].append("later")
            source_staffing["seat"]["family"] = "claude"
            first["order"]["request"]["request"] = "mutated return"
            durable = st.load(state_path)
            stored = tasks.task_record(durable, first["id"])
            self.assertNotIn(
                "later", stored["order"]["request"]["context"]["nested"]
            )
            self.assertEqual(
                stored["resolved_staffing"],
                {"seat": {"family": "codex", "ordinal": 1}},
            )

            source_result = task_result(native_result={"answer": [1]})
            terminal = tasks.record_persisted_task_result(
                state_path, first["id"], source_result
            )
            source_result["native_result"]["answer"].append(2)
            terminal["result"]["native_result"]["answer"].append(3)
            winner = tasks.task_record(st.load(state_path), first["id"])
            self.assertEqual(winner["result"]["native_result"], {"answer": [1]})
            for replacement in (
                task_result(native_result={"answer": [4]}),
                task_result(
                    status="failure",
                    reason="later failure",
                    native_result={"finding": "F1"},
                ),
            ):
                with self.assertRaises(tasks.TaskRecordError):
                    tasks.record_persisted_task_result(
                        state_path, first["id"], replacement
                    )
            self.assertEqual(
                tasks.task_record(st.load(state_path), first["id"]), winner
            )

            failure = tasks.admit_persisted_task(
                state_path, task_order(), {"seat": "worker"}, workspace
            )
            tasks.record_persisted_task_result(
                state_path,
                failure["id"],
                task_result(
                    status="failure",
                    reason="provider unavailable",
                    token_usage=None,
                    token_usage_partial=True,
                    cost=None,
                    cost_partial=True,
                    native_result={"request": "preserved"},
                ),
            )
            self.assertEqual(
                tasks.task_record(st.load(state_path), failure["id"])["result"]
                ["reason"],
                "provider unavailable",
            )

            rewritten = st.load(state_path)
            rewritten["tasks"][0]["resolved_staffing"] = {"seat": "changed"}
            with self.assertRaises(st.HistoryRewriteError):
                st.save(state_path, rewritten)
            rewritten = st.load(state_path)
            rewritten["tasks"][0]["result"]["duration_s"] = 99
            with self.assertRaises(st.HistoryRewriteError):
                st.save(state_path, rewritten)

            typed_rewrites = (
                (
                    lambda record: record["order"]["request"]["context"][
                        "nested"
                    ].__setitem__(0, 1.0),
                    "order",
                ),
                (
                    lambda record: record["resolved_staffing"]["seat"].__setitem__(
                        "ordinal", True
                    ),
                    "staffing",
                ),
                (
                    lambda record: record["result"]["native_result"].__setitem__(
                        "answer", [True]
                    ),
                    "terminal result",
                ),
            )
            for rewrite, field in typed_rewrites:
                with self.subTest(json_distinct_rewrite=field):
                    rewritten = st.load(state_path)
                    rewrite(rewritten["tasks"][0])
                    with self.assertRaises(st.HistoryRewriteError):
                        st.save(state_path, rewritten)
                    self.assertEqual(
                        tasks.task_record(st.load(state_path), first["id"]), winner
                    )

    @unittest.skipIf(st.fcntl is None, "fcntl unavailable on this platform")
    def test_concurrent_task_mutations_preserve_accepted_history(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as workspace:
            state_path = persisted_state(workspace)

            def together(*operations):
                barrier = threading.Barrier(len(operations))

                def run(operation):
                    barrier.wait()
                    return operation()

                with futures.ThreadPoolExecutor(len(operations)) as pool:
                    return [pool.submit(run, operation) for operation in operations]

            admitted = together(
                lambda: tasks.admit_persisted_task(
                    state_path, task_order(), {"seat": "first"}, workspace
                ),
                lambda: tasks.admit_persisted_task(
                    state_path, task_order(), {"seat": "second"}, workspace
                ),
            )
            first, second = [future.result() for future in admitted]
            self.assertEqual(
                {record["id"] for record in tasks.task_records(st.load(state_path))},
                {first["id"], second["id"]},
            )

            mixed = together(
                lambda: tasks.admit_persisted_task(
                    state_path, task_order(), {"seat": "third"}, workspace
                ),
                lambda: tasks.record_persisted_task_result(
                    state_path, first["id"], task_result(native_result="done")
                ),
            )
            third, terminal = [future.result() for future in mixed]
            current = st.load(state_path)
            self.assertEqual(tasks.task_record(current, first["id"]), terminal)
            self.assertEqual(tasks.task_record(current, third["id"]), third)

            contenders = together(
                lambda: tasks.record_persisted_task_result(
                    state_path, second["id"], task_result(native_result="A")
                ),
                lambda: tasks.record_persisted_task_result(
                    state_path, second["id"], task_result(native_result="B")
                ),
            )
            outcomes = []
            for future in contenders:
                try:
                    outcomes.append(future.result()["result"]["native_result"])
                except tasks.TaskRecordError:
                    outcomes.append("refused")
            self.assertEqual(outcomes.count("refused"), 1)
            winner = tasks.task_record(st.load(state_path), second["id"])
            self.assertIn(winner["result"]["native_result"], ("A", "B"))
            with self.assertRaises(tasks.TaskRecordError):
                tasks.record_persisted_task_result(
                    state_path, second["id"], task_result(native_result="later")
                )
            self.assertEqual(
                tasks.task_record(st.load(state_path), second["id"]), winner
            )

    def test_output_directory_admission_for_both_executors(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as root:
            primary = os.path.join(root, "primary")
            additional = os.path.join(root, "additional")
            outside = os.path.join(root, "outside")
            os.makedirs(os.path.join(primary, "inside"))
            os.makedirs(additional)
            os.makedirs(outside)
            os.symlink(outside, os.path.join(primary, "linked-outside"))

            for executor in ("worker", "brainstorming"):
                with self.subTest(executor=executor):
                    state = st.new_state("goal", primary, {})
                    omitted = tasks.admit_task(
                        state,
                        task_order(executor),
                        {"executor": executor},
                        primary,
                    )
                    self.assertNotIn(
                        "output_directory", omitted["order"]["request"]
                    )
                    relative = tasks.admit_task(
                        state,
                        task_order(executor, output_directory="missing/leaf"),
                        {"executor": executor},
                        primary,
                    )
                    absolute = tasks.admit_task(
                        state,
                        task_order(
                            executor,
                            output_directory=os.path.join(primary, "inside"),
                        ),
                        {"executor": executor},
                        primary,
                    )
                    self.assertEqual(
                        relative["order"]["request"]["output_directory"],
                        os.path.realpath(os.path.join(primary, "missing/leaf")),
                    )
                    self.assertEqual(
                        absolute["order"]["request"]["output_directory"],
                        os.path.realpath(os.path.join(primary, "inside")),
                    )
                    self.assertFalse(os.path.exists(os.path.join(primary, "missing")))

                    before = len(tasks.task_records(state))
                    for invalid in (
                        os.path.join(primary, "..", "outside"),
                        additional,
                        os.path.join(primary, "linked-outside", "child"),
                    ):
                        with self.subTest(executor=executor, invalid=invalid):
                            self.assert_request_error(
                                tasks.admit_task,
                                state,
                                task_order(executor, output_directory=invalid),
                                {"executor": executor},
                                primary,
                            )
                            self.assertEqual(len(tasks.task_records(state)), before)

    def test_output_directory_derived_path_boundary(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as root:
            output = os.path.realpath(os.path.join(root, "output"))
            outside = os.path.realpath(os.path.join(root, "outside"))
            os.makedirs(output)
            os.makedirs(outside)
            os.symlink(outside, os.path.join(output, "linked-outside"))
            child = tasks.resolve_derived_path(output, "nested/missing.txt")
            self.assertEqual(
                child, os.path.realpath(os.path.join(output, "nested/missing.txt"))
            )
            self.assertFalse(os.path.exists(os.path.join(output, "nested")))
            self.assertEqual(
                tasks.resolve_derived_path(output, os.path.join(output, "file")),
                os.path.realpath(os.path.join(output, "file")),
            )
            for invalid in (
                "../outside/file",
                os.path.join(outside, "file"),
                "linked-outside/file",
            ):
                with self.subTest(invalid=invalid):
                    self.assert_request_error(
                        tasks.resolve_derived_path, output, invalid
                    )

    def test_post_admission_symlink_cannot_redirect_derived_path(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as root:
            primary = os.path.join(root, "primary")
            outside = os.path.join(root, "outside")
            os.makedirs(primary)
            os.makedirs(outside)
            state = st.new_state("goal", primary, {})
            admitted = tasks.admit_task(
                state,
                task_order(output_directory="planned"),
                {"executor": "worker"},
                primary,
            )["order"]["request"]["output_directory"]

            os.symlink(outside, admitted)

            self.assert_request_error(
                tasks.resolve_derived_path, admitted, "effect.txt"
            )


if __name__ == "__main__":
    unittest.main()
