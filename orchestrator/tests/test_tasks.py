"""Focused tests for the generic task contracts and catalogue."""

import copy
import math
import unittest
from unittest import mock

from orchestrator import brainstorming
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


if __name__ == "__main__":
    unittest.main()
