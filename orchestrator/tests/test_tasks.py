"""Focused tests for the generic task contracts and catalogue."""

import copy
from concurrent import futures
import json
import math
import os
import tempfile
import threading
import unittest
from unittest import mock

from orchestrator import brainstorming, contracts
from orchestrator import driver as drv
from orchestrator import profiles, runners, staffing
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


def task_order(task_executor="agent_call", **request_changes):
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
            ["agent_call", "brainstorming", "reviewed_task", "deep_task"],
        )
        producer_catalogue = tasks.producer_task_executor_catalogue()
        self.assertEqual(
            [entry["id"] for entry in producer_catalogue],
            ["agent_call", "brainstorming"],
        )
        producer_catalogue[0]["description"] = "changed"
        self.assertNotEqual(
            tasks.producer_task_executor_catalogue()[0]["description"],
            "changed",
        )
        fields = {
            "id",
            "name",
            "description",
            "operating_mode",
            "usage_examples",
            "available_agent_configurations",
            "configuration_schema",
            "execution_bindings",
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

        self.assertEqual(
            {
                entry["id"]: entry["execution_bindings"]
                for entry in catalogue
            },
            {
                "agent_call": {
                    "staffing": True,
                    "strategy_profile": False,
                    "prompt_set": False,
                },
                "brainstorming": {
                    "staffing": True,
                    "strategy_profile": False,
                    "prompt_set": True,
                },
                "reviewed_task": {
                    "staffing": True,
                    "strategy_profile": True,
                    "prompt_set": True,
                },
                "deep_task": {
                    "staffing": True,
                    "strategy_profile": True,
                    "prompt_set": True,
                },
            },
        )
        catalogue[0]["execution_bindings"]["staffing"] = False
        self.assertTrue(
            tasks.task_executor_catalogue()[0]["execution_bindings"][
                "staffing"
            ]
        )
        for entry in tasks.task_executor_catalogue():
            for binding, supported in entry["execution_bindings"].items():
                self.assertEqual(
                    tasks.task_executor_supports_binding(
                        entry["id"], binding
                    ),
                    supported,
                )

        # The one thing an orderer chooses about an agent call's staffing:
        # the process step it performs, from the router's own closed
        # vocabulary and defaulting to implementation work. No seat and no
        # round: those are the consumer facts the router keeps no history
        # of, and nothing here exposes them.
        self.assertEqual(
            catalogue[0]["configuration_schema"],
            {
                "role": {
                    "type": "choice",
                    "choices": [
                        "plan", "draft", "implement", "fix", "classify",
                        "review", "brainstorm", "consult", "sync",
                    ],
                    "default": "implement",
                },
            },
        )
        self.assertEqual(
            catalogue[0]["configuration_schema"]["role"]["choices"],
            list(staffing.ROLES),
        )
        self.assertEqual(catalogue[0]["name"], "Agent call")
        # The retired spelling survives only in stored bytes, never in the
        # catalogue an operator, a product, or a planner reads.
        for entry in catalogue:
            text = json.dumps(entry, sort_keys=True).lower()
            self.assertNotIn("worker", text)
        self.assertEqual(
            catalogue[1]["configuration_schema"],
            {
                "max_rounds": {
                    "type": "integer",
                    "minimum": 20,
                    "default": 20,
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
            20,
        )

        reviewed = catalogue[2]["configuration_schema"]
        producer = reviewed["producer"]
        self.assertEqual(producer["type"], "task_executor")
        self.assertEqual(
            [choice["value"] for choice in producer["choices"]],
            ["agent_call", "brainstorming"],
        )
        self.assertEqual(
            producer["choices"][0]["configuration_schema_by"]["schemas"],
            {
                kind: {
                    "role": {
                        "type": "choice",
                        "choices": [role],
                        "optional": True,
                        "default": "",
                    },
                }
                for kind, role in (
                    ("draft_skeleton", "plan"),
                    ("draft_slice_note", "draft"),
                    ("implement", "implement"),
                    ("complete_verification", "implement"),
                )
            },
        )
        self.assertEqual(
            producer["choices"][1]["configuration_schema"],
            tasks.task_executor_catalogue()[1]["configuration_schema"],
        )
        self.assertEqual(
            reviewed["doc_reclassify_from"]["applicable_when"],
            {"task_kind": ["draft_skeleton", "draft_slice_note"]},
        )
        self.assertEqual(
            reviewed["impl_reclassify_from"]["applicable_when"],
            {"task_kind": ["implement", "complete_verification"]},
        )
        size = reviewed["implementation_size_control"]
        self.assertEqual(size["type"], "object")
        self.assertEqual(
            size["applicable_when"],
            {
                "task_kind": ["implement"],
                "producer.task_executor": [None, "agent_call"],
            },
        )
        self.assertEqual(
            set(size["properties"]),
            {
                "soft_lines", "hard_lines", "unconfirmed_grace_s",
                "confirmed_grace_s",
            },
        )
        self.assertNotIn('"type": "json"', json.dumps(reviewed))

    def test_configuration_schema_and_resolution(self):
        self.assertEqual(
            tasks.resolve_configuration("agent_call"), {"role": "implement"}
        )
        self.assertEqual(
            tasks.resolve_configuration("agent_call", {}),
            {"role": "implement"},
        )
        for role in staffing.ROLES:
            self.assertEqual(
                tasks.resolve_configuration("agent_call", {"role": role}),
                {"role": role},
            )
        self.assertEqual(
            tasks.resolve_configuration("brainstorming"),
            {"max_rounds": 20, "closure_policy": "unanimity"},
        )
        self.assertEqual(
            tasks.resolve_configuration(
                "brainstorming", {"max_rounds": 24}
            ),
            {"max_rounds": 24, "closure_policy": "unanimity"},
        )
        self.assertEqual(
            tasks.resolve_configuration(
                "brainstorming", {"closure_policy": "majority"}
            ),
            {"max_rounds": 20, "closure_policy": "majority"},
        )

        invalid = [
            ("agent_call", {"max_rounds": 1}),
            ("agent_call", {"role": "reviewer"}),
            ("agent_call", {"role": None}),
            ("agent_call", {"role": "implement", "index": 2}),
            ("agent_call", None),
            ("brainstorming", {"max_rounds": True}),
            ("brainstorming", {"max_rounds": 1.0}),
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

        reviewed = tasks.resolve_configuration(
            "reviewed_task", {"task_kind": "implement"}
        )
        self.assertEqual(reviewed["task_kind"], "implement")
        self.assertEqual(
            reviewed["producer"]["task_executor"], "agent_call"
        )
        self.assertEqual(reviewed["review_breadth"], "double")
        self.assertIn("implementation_size_control", reviewed)
        inherited = tasks.resolve_configuration(
            "reviewed_task",
            {"task_kind": "implement"},
            reviewed_defaults={
                "max_fix_loops": 7,
                "implementation_size_control": {
                    "soft_lines": 40,
                    "hard_lines": 60,
                    "unconfirmed_grace_s": 9,
                    "confirmed_grace_s": 15,
                },
            },
        )
        self.assertEqual(inherited["max_fix_loops"], 7)
        self.assertEqual(
            inherited["implementation_size_control"]["soft_lines"], 40
        )
        for configuration, code in (
            ({}, tasks.INVALID_TASK_REQUEST),
            ({"task_kind": "draft_skeleton", "producer": {
                "task_executor": "brainstorming",
            }}, tasks.INVALID_TASK_REQUEST),
            ({"task_kind": "implement", "producer": {
                "task_executor": "reviewed_task",
            }}, tasks.INVALID_TASK_REQUEST),
            ({"task_kind": "implement", "producer": {
                "task_executor": "missing",
            }}, tasks.UNKNOWN_TASK_EXECUTOR),
            ({"task_kind": "implement", "producer": {
                "task_executor": "brainstorming",
            }, "implementation_size_control": {}}, tasks.INVALID_TASK_REQUEST),
        ):
            with self.subTest(configuration=configuration):
                self.assert_request_error(
                    code,
                    tasks.resolve_configuration,
                    "reviewed_task",
                    configuration,
                )

        definition = tasks._TASK_EXECUTOR_BY_ID["brainstorming"][
            "configuration_schema"
        ]["max_rounds"]
        with mock.patch.dict(definition, {"default": 27}):
            self.assertEqual(
                tasks.task_executor_catalogue()[1]["configuration_schema"]
                ["max_rounds"]["default"],
                27,
            )
            self.assertEqual(
                tasks.resolve_configuration("brainstorming")["max_rounds"],
                27,
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
            {"task_executor": "agent_call", "request": task_request()}
        )
        self.assertEqual(order["configuration"], {"role": "implement"})
        self.assertEqual(order["request"], task_request())
        # Every order this validator admits carries the owner's staffing
        # context, and an omitted one is an explicit null: absence of the
        # key is reserved for records admitted before the cutover.
        self.assertIsNone(order["staffing_session"])
        self.assertEqual(tasks.order_staffing_session(order), (True, None))
        named = tasks.validate_order({
            "task_executor": "agent_call",
            "request": task_request(),
            "configuration": {"role": "consult"},
            "staffing_session": "stf-abc",
        })
        self.assertEqual(named["staffing_session"], "stf-abc")
        self.assertEqual(named["configuration"], {"role": "consult"})
        self.assertEqual(
            tasks.order_staffing_session(named), (True, "stf-abc")
        )
        # A pre-cutover record has no such key at all, and reads as one.
        self.assertEqual(
            tasks.order_staffing_session(
                {"task_executor": "worker", "request": task_request()}
            ),
            (False, None),
        )
        for refused in ("", "   ", 7, False, []):
            with self.subTest(staffing_session=refused):
                self.assert_request_error(
                    tasks.INVALID_TASK_REQUEST,
                    tasks.validate_order,
                    {
                        "task_executor": "agent_call",
                        "request": task_request(),
                        "staffing_session": refused,
                    },
                )
        brainstorming_order = tasks.validate_order(
            {
                "task_executor": "brainstorming",
                "request": task_request(),
                "configuration": {"max_rounds": 3},  # below the floor
            }
        )
        self.assertEqual(
            brainstorming_order["configuration"],
            {"max_rounds": 20, "closure_policy": "unanimity"},  # raised
        )
        self.assertEqual(brainstorming_order["prompt_set"], "default")
        selected_prompt_set = tasks.validate_order({
            "task_executor": "brainstorming",
            "request": task_request(),
            "prompt_set": "operator",
        })
        self.assertEqual(selected_prompt_set["prompt_set"], "operator")
        for invalid_prompt_set in ("", "bad/name", None, 7):
            with self.subTest(prompt_set=invalid_prompt_set):
                self.assert_request_error(
                    tasks.INVALID_TASK_REQUEST,
                    tasks.validate_order,
                    {
                        "task_executor": "brainstorming",
                        "request": task_request(),
                        "prompt_set": invalid_prompt_set,
                    },
                )
        self.assert_request_error(
            tasks.INVALID_TASK_REQUEST,
            tasks.validate_order,
            {
                "task_executor": "agent_call",
                "request": task_request(),
                "prompt_set": "operator",
            },
        )
        production_order = tasks.producer_order(
            {"id": 1, "title": "one", "material": "analysis"},
            contracts.KIND_IMPLEMENT,
            task_request(context={}),
        )
        admitted_production_order = tasks.validate_order(production_order)
        self.assertNotIn("staffing_material", admitted_production_order)
        self.assert_request_error(
            tasks.INVALID_TASK_REQUEST,
            tasks.validate_order,
            {**production_order, "staffing_material": "analysis"},
        )
        self.assertEqual(admitted_production_order["request"]["context"], {})

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
            {"task_executor": "agent_call"},
            {"request": task_request()},
            {
                "task_executor": "agent_call",
                "request": task_request(),
                "extra": True,
            },
            {"task_executor": 1, "request": task_request()},
            {"task_executor": "agent_call", "request": []},
            {
                "task_executor": "agent_call",
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

    def test_reviewed_and_deep_orders_retain_optional_prompt_and_strategy(self):
        content = copy.deepcopy(profiles.SEEDS["light"]["profile"])
        snapshot = {
            "ref": {
                "name": "light",
                "version": 1,
                "hash": profiles.semantic_hash(content),
            },
            "profile": content,
        }
        reviewed = tasks.validate_order({
            "task_executor": "reviewed_task",
            "configuration": {"task_kind": "draft_skeleton"},
            "request": task_request(),
            "prompt_set": "operator",
            "strategy_profile": snapshot,
        })
        deep = tasks.validate_order({
            "task_executor": "deep_task",
            "request": task_request(),
            "prompt_set": "operator",
            "strategy_profile": snapshot,
        })
        for order in (reviewed, deep):
            self.assertEqual(order["prompt_set"], "operator")
            self.assertEqual(order["strategy_profile"], snapshot)

        # Internal milestone and pre-cutover orders that carry neither field
        # remain profileless and do not acquire a prompt binding here.
        plain = tasks.validate_order({
            "task_executor": "reviewed_task",
            "configuration": {"task_kind": "draft_skeleton"},
            "request": task_request(),
        })
        self.assertNotIn("prompt_set", plain)
        self.assertNotIn("strategy_profile", plain)
        plain_deep = tasks.validate_order({
            "task_executor": "deep_task",
            "request": task_request(),
        })
        self.assertNotIn("prompt_set", plain_deep)
        self.assertNotIn("strategy_profile", plain_deep)
        plain_child = tasks.deep_documentation_order({"order": plain_deep})
        self.assertNotIn("prompt_set", plain_child)
        self.assertNotIn("strategy_profile", plain_child)

        parent = {"order": deep}
        for child in (
            tasks.deep_documentation_order(parent),
            tasks.deep_implementation_order(parent, "docs/note.md"),
        ):
            self.assertEqual(child["prompt_set"], "operator")
            self.assertEqual(child["strategy_profile"], snapshot)
            self.assertEqual(
                tasks.validate_order(child)["strategy_profile"], snapshot
            )

        damaged = copy.deepcopy(snapshot)
        damaged["ref"]["hash"] = "0" * 64
        for task_executor, configuration in (
            ("reviewed_task", {"task_kind": "draft_skeleton"}),
            ("deep_task", {}),
        ):
            with self.subTest(task_executor=task_executor):
                self.assert_request_error(
                    tasks.INVALID_TASK_REQUEST,
                    tasks.validate_order,
                    {
                        "task_executor": task_executor,
                        "configuration": configuration,
                        "request": task_request(),
                        "strategy_profile": damaged,
                    },
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

            for executor in ("agent_call", "brainstorming"):
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

    def test_worker_task_id_survives_marker_and_recovery_records(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as workspace:
            state_path = persisted_state(workspace)
            task = tasks.admit_persisted_task(
                state_path, task_order(), {"seat": "worker"}, workspace
            )
            driver = drv.Driver(
                state_path, runner=runners.MockRunner([])
            )
            self.assertTrue(driver._mark_busy(
                "slice_doc-01-draft",
                contracts.KIND_DRAFT_SLICE_NOTE,
                "codex",
                task_id=task["id"],
            ))
            with open(driver._busy_path(), "r", encoding="utf-8") as handle:
                marker = json.load(handle)
            self.assertEqual(marker["task_id"], task["id"])

            self.assertTrue(driver._mark_busy(
                "slice_doc-01-reclassify-codex-F1",
                contracts.KIND_RECLASSIFY,
                "claude",
                nested=True,
            ))
            with open(driver._busy_path(), "r", encoding="utf-8") as handle:
                reclassify = json.load(handle)
            self.assertNotIn("task_id", reclassify)
            self.assertEqual(
                reclassify["pending_calls"][0]["task_id"], task["id"]
            )
            driver._clear_busy()
            self.assertTrue(driver._mark_busy(
                "slice_doc-01-draft",
                contracts.KIND_DRAFT_SLICE_NOTE,
                "codex",
                task_id=task["id"],
            ))

            classifier = {
                "family": "claude",
                "model": "classifier-model",
                "effort": "high",
                "status": "ok",
                "failure_type": "unknown",
                "error": None,
                "duration_s": 2.0,
                "token_usage": token_usage(),
                "token_usage_partial": False,
                "cost_payloads": [],
                "prompt_path": "raw/classifier.txt",
            }
            driver._classify_call_starter(
                "slice_doc-01-draft", task["id"]
            )(classifier)
            with open(driver._busy_path(), "r", encoding="utf-8") as handle:
                nested = json.load(handle)
            self.assertEqual(nested["task_id"], task["id"])
            self.assertEqual(
                nested["pending_calls"][0]["task_id"], task["id"]
            )
            driver._classify_call_recorder(
                "slice_doc-01-draft", task["id"]
            )(classifier)
            self.assertEqual(
                driver.state["events"][-1]["task_id"], task["id"]
            )

            recovered = drv.Driver(
                state_path, runner=runners.MockRunner([])
            )
            interrupted = [
                event for event in recovered.state["events"]
                if event["type"] == "worker_interrupted"
            ]
            self.assertEqual(len(interrupted), 2)
            self.assertEqual(
                {event["task_id"] for event in interrupted}, {task["id"]}
            )
            self.assertEqual(len(tasks.task_records(recovered.state)), 1)

            seen = {}

            def dispatched(*_args, **_kwargs):
                with open(
                    recovered._busy_path(), "r", encoding="utf-8"
                ) as handle:
                    seen.update(json.load(handle))
                return {}, runners.RunnerResult(
                    "{}", 0, 1.0, token_usage=token_usage()
                )

            with mock.patch.object(
                runners, "call_worker", side_effect=dispatched
            ), mock.patch.object(
                recovered, "_save_raw", return_value="raw/result.json"
            ):
                _output, result, _raw_path = recovered._call(
                    "codex",
                    "KIND: draft_slice_note\n",
                    contracts.KIND_DRAFT_SLICE_NOTE,
                    "slice_doc-01-draft",
                    task_id=task["id"],
                )
            self.assertEqual(seen["task_id"], task["id"])
            self.assertEqual(result.task_id, task["id"])
            recovered._clear_busy()

    def test_classifier_and_cutoff_keep_known_task_id_without_marker(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as workspace:
            state_path = persisted_state(workspace)
            task = tasks.admit_persisted_task(
                state_path, task_order(), {"seat": "worker"}, workspace
            )
            driver = drv.Driver(
                state_path, runner=runners.MockRunner([])
            )
            raw_name = "slice_impl-01-draft"
            self.assertTrue(driver._mark_busy(
                raw_name,
                contracts.KIND_IMPLEMENT,
                "codex",
                task_id=task["id"],
            ))
            classifier = {
                "family": "claude",
                "model": "classifier-model",
                "effort": "high",
                "status": "ok",
                "failure_type": "unknown",
                "error": None,
                "duration_s": 2.0,
                "token_usage": token_usage(),
                "token_usage_partial": False,
                "cost_payloads": [],
                "prompt_path": "raw/classifier.txt",
            }

            def classify(_exc, **kwargs):
                kwargs["on_llm_start"](classifier)
                driver._clear_busy()
                kwargs["on_llm_call"](classifier)
                return "unknown", None, "test classification"

            with mock.patch.object(
                drv.errclass,
                "classify_worker_failure",
                side_effect=classify,
            ):
                driver._classify_failure(
                    "codex", runners.RunnerError("mystery"), raw_name
                )

            self.assertEqual(
                driver.state["events"][-1]["task_id"], task["id"]
            )

            implementation = st._new_unit(st.UNIT_SLICE_IMPL, 1)

            with mock.patch.object(
                drv.gitops, "enabled", return_value=True
            ), mock.patch.object(
                drv.gitops, "reviewable_line_count", return_value=0
            ), mock.patch.object(
                driver, "_matching_busy_call", return_value={}
            ):
                control, marker = driver._implementation_size_control(
                    "base-tree", task_id=task["id"], unit=implementation
                )
                marker["interrupt_lines"] = 1600
                control._bind(lambda _text: True, lambda _reason: True)
                self.assertTrue(control.interrupt("hard size limit"))
                control._close()
            durable = implementation[
                "implementation_stabilization"
            ]["implementation_size"]
            self.assertEqual(durable["task_id"], task["id"])

            driver._ensure_implementation_stabilization_events(
                implementation, durable
            )
            interrupted = [
                event for event in driver.state["events"]
                if event["type"] == "implementation_size_interrupted"
            ]
            self.assertEqual(len(interrupted), 1)
            self.assertEqual(interrupted[0]["task_id"], task["id"])

    def test_worker_task_id_survives_marker_loss_fallback(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as workspace:
            state_path = persisted_state(workspace)
            task = tasks.admit_persisted_task(
                state_path, task_order(), {"seat": "worker"}, workspace
            )
            driver = drv.Driver(
                state_path, runner=runners.MockRunner([])
            )
            usage = token_usage()

            def dispatched(*_args, **_kwargs):
                driver._clear_busy()
                return {}, runners.RunnerResult(
                    "{}", 0, 7.0, token_usage=usage
                )

            with mock.patch.object(
                runners, "call_worker", side_effect=dispatched
            ), self.assertRaises(drv.StopStep):
                driver._call(
                    "codex",
                    "KIND: draft_slice_note\n",
                    contracts.KIND_DRAFT_SLICE_NOTE,
                    "slice_doc-01-draft",
                    task_id=task["id"],
                )

            persisted = st.load(state_path)
            fallback = [
                event for event in persisted["events"]
                if event["type"] == "worker_unaccepted"
            ]
            self.assertEqual(len(fallback), 1)
            self.assertEqual(fallback[0]["task_id"], task["id"])
            self.assertEqual(fallback[0]["duration_s"], 7.0)
            self.assertEqual(fallback[0]["token_usage"], usage)
            accounting = tasks.task_accounting(persisted, task["id"])
            self.assertEqual(accounting["duration_s"], 7.0)
            self.assertEqual(accounting["token_usage"], usage)

    def test_task_accounting_reuses_existing_homes_once(self):
        def usage(amount):
            return {
                "input_tokens": amount,
                "cached_input_tokens": 0,
                "output_tokens": amount,
                "reasoning_output_tokens": 0,
                "total_tokens": amount * 2,
            }

        def cost(amount):
            return {
                "api_usd": amount / 100.0,
                "real_usd": amount / 200.0,
            }

        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as workspace:
            state = st.new_state(
                "Exercise task accounting.",
                workspace,
                {"families_order": ["codex", "claude"]},
            )
            task = tasks.admit_task(
                state, task_order(), {"seat": "worker"}, workspace
            )
            task_id = task["id"]
            unit = state["units"][0]

            event_amounts = (
                ("brainstorming_origin_recorded", 1),
                ("brainstorming_origin_recorded", 2),
                ("worker_malformed", 3),
                ("implementation_size_interrupted", 5),
                ("worker_interrupted", 6),
                ("worker_unaccepted", 7),
                ("error_classifier_call", 8),
                ("gap_reported", 9),
            )
            for event_type, amount in event_amounts:
                st.append_event(
                    state,
                    event_type,
                    unit=st.unit_key(unit),
                    task_id=task_id,
                    fatal=(event_type == "worker_malformed"),
                    duration_s=float(amount),
                    token_usage=usage(amount),
                    token_usage_partial=False,
                    cost=cost(amount),
                    cost_partial=False,
                )
            st.append_event(
                state,
                "worker_malformed",
                unit=st.unit_key(unit),
                task_id=task_id,
                fatal=True,
                duration_s=4.0,
                token_usage=None,
                token_usage_partial=True,
                cost=None,
                cost_partial=True,
            )
            st.record_draft(
                state,
                unit,
                contracts.KIND_DRAFT_SKELETON,
                {"artifact": "skeleton.md", "slices": []},
                duration=10.0,
                token_usage=usage(10),
                cost=cost(10),
                task_id=task_id,
            )
            round_task = tasks.admit_task(
                state, task_order(), {"seat": "worker"}, workspace
            )
            unit["status"] = st.U_ROUNDS
            st.record_round(
                state,
                unit,
                "codex",
                contracts.KIND_REVIEW_ROUND,
                {"findings": []},
                duration=11.0,
                token_usage=usage(11),
                cost=cost(11),
                task_id=round_task["id"],
            )

            before = st.summary(state)
            subtotal = tasks.task_accounting(state, task_id)
            self.assertEqual(subtotal["duration_s"], 55.0)
            self.assertEqual(subtotal["token_usage"], usage(51))
            self.assertTrue(subtotal["token_usage_partial"])
            self.assertAlmostEqual(subtotal["cost"]["api_usd"], 0.51)
            self.assertAlmostEqual(subtotal["cost"]["real_usd"], 0.255)
            self.assertTrue(subtotal["cost_partial"])
            self.assertEqual(
                tasks.task_accounting(state, round_task["id"]),
                {
                    "duration_s": 11.0,
                    "token_usage": usage(11),
                    "token_usage_partial": False,
                    "cost": cost(11),
                    "cost_partial": False,
                },
            )

            tasks.record_task_result(
                state,
                task_id,
                {
                    "status": "success",
                    **subtotal,
                    "native_result": {"artifact": "skeleton.md"},
                },
            )
            after = st.summary(state)
            for field in (
                "work_duration_s",
                "work_token_usage",
                "work_token_usage_partial",
                "work_cost",
                "work_cost_partial",
            ):
                self.assertEqual(after[field], before[field])

    def test_pending_cutoff_marks_only_its_task_accounting_partial(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as workspace:
            state = st.new_state(
                "Project pending cutoff evidence.",
                workspace,
                {"families_order": ["codex", "claude"]},
            )
            pending_task = tasks.admit_task(
                state, task_order(), {"seat": "worker"}, workspace
            )
            other_task = tasks.admit_task(
                state, task_order(), {"seat": "worker"}, workspace
            )
            unit = state["units"][0]
            complete = {
                "duration_s": 3.0,
                "token_usage": token_usage(),
                "token_usage_partial": False,
                "cost": {"api_usd": 0.2, "real_usd": 0.1},
                "cost_partial": False,
            }
            for task in (pending_task, other_task):
                st.append_event(
                    state,
                    "worker_unaccepted",
                    unit=st.unit_key(unit),
                    task_id=task["id"],
                    **copy.deepcopy(complete),
                )
            unit["implementation_stabilization"] = {
                "implementation_size": {
                    "episode_id": "pending-cutoff",
                    "task_id": pending_task["id"],
                },
            }

            pending = tasks.task_accounting(state, pending_task["id"])
            self.assertEqual(pending["duration_s"], 3.0)
            self.assertEqual(pending["token_usage"], token_usage())
            self.assertEqual(pending["cost"], complete["cost"])
            self.assertTrue(pending["token_usage_partial"])
            self.assertTrue(pending["cost_partial"])

            other = tasks.task_accounting(state, other_task["id"])
            self.assertFalse(other["token_usage_partial"])
            self.assertFalse(other["cost_partial"])

            st.append_event(
                state,
                "implementation_size_interrupted",
                unit=st.unit_key(unit),
                episode_id="pending-cutoff",
                task_id=pending_task["id"],
                **copy.deepcopy(complete),
            )
            resolved = tasks.task_accounting(state, pending_task["id"])
            self.assertFalse(resolved["token_usage_partial"])
            self.assertFalse(resolved["cost_partial"])

    def test_legacy_and_non_task_activity_stay_unattributed(self):
        with tempfile.TemporaryDirectory(prefix="orch-tasks-") as workspace:
            state = st.new_state(
                "Keep legacy activity separate.",
                workspace,
                {"families_order": ["codex", "claude"]},
            )
            task = tasks.admit_task(
                state, task_order(), {"seat": "worker"}, workspace
            )
            unit = state["units"][0]
            accounting = {
                "duration_s": 3.0,
                "token_usage": token_usage(),
                "token_usage_partial": False,
                "cost": {"api_usd": 0.2, "real_usd": 0.0},
                "cost_partial": False,
            }
            st.append_event(
                state,
                "worker_malformed",
                unit=st.unit_key(unit),
                label="reused-label",
                fatal=True,
                **copy.deepcopy(accounting),
            )
            st.append_event(
                state,
                "brainstorming_work_recorded",
                unit=st.unit_key(unit),
                **copy.deepcopy(accounting),
            )
            st.append_event(
                state,
                "reclassify_recorded",
                unit=st.unit_key(unit),
                **copy.deepcopy(accounting),
            )
            unit["seals"].append({
                "halves": {"codex": copy.deepcopy(accounting)}
            })

            work, _unassigned = st._work_durations(state)
            self.assertEqual(work[st.unit_key(unit)], 12.0)
            self.assertEqual(
                tasks.task_accounting(state, task["id"]),
                {
                    "duration_s": 0.0,
                    "token_usage": None,
                    "token_usage_partial": True,
                    "cost": None,
                    "cost_partial": True,
                },
            )
            for record in state["events"] + [unit["seals"][0]["halves"]["codex"]]:
                self.assertNotIn("task_id", record)

            old_state = st.new_state(
                "Old run.", workspace, {"families_order": ["codex"]}
            )
            old_bytes = copy.deepcopy(old_state)
            self.assertEqual(tasks.task_records(old_state), [])
            self.assertEqual(old_state, old_bytes)


if __name__ == "__main__":
    unittest.main()
