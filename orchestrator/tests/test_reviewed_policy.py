"""Order-local producer policy for the reviewed-work boundary."""

import tempfile
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st
from orchestrator import tasks
from orchestrator.tests.test_driver_mock import init_state, make_config


def _units(path, producer_task_executor=None):
    state = st.load(path)
    state["milestone"]["slices"] = [{
        "id": 1,
        "title": "Policy",
        "intent": "Exercise one reviewed-work order.",
        "producer_task_executor": producer_task_executor or {
            "draft_slice_note": {"task_executor": "agent_call"},
            "implement": {"task_executor": "agent_call"},
        },
    }]
    document = st.ensure_next_unit(state)
    implementation = st.ensure_next_unit(state)
    st.save(path, state)
    return document, implementation


def _unit(subject, kind):
    return next(
        unit for unit in subject.state["units"] if unit["kind"] == kind
    )


class ReviewedProducerPolicyTest(unittest.TestCase):
    def test_runtime_establishes_plan_before_freezing_producer(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-runtime-") as ws:
            path = init_state(ws, make_config())
            _units(path)
            state = st.load(path)
            state["units"][0]["status"] = st.U_SEALED
            st.save(path, state)
            subject = drv.Driver(path, runner=runners.MockRunner([]))

            observed = {}

            def establish_plan(unit, kind):
                observed["policy_before_plan"] = unit.get("reviewed_policy")
                subject.state["milestone"]["slices"][0][
                    "producer_task_executor"
                ]["draft_slice_note"] = {
                    "task_executor": "brainstorming",
                    "configuration": {"closure_policy": "majority"},
                }
                return False

            def dispatch(unit, call_preparation):
                observed["policy"] = st.load(path)["units"][1][
                    "reviewed_policy"
                ]
                return "selected producer dispatched"

            with mock.patch.object(
                subject.milestone_reviewed_calls,
                "ensure_author_plan",
                side_effect=establish_plan,
            ) as plan_preparation, mock.patch.object(
                subject, "_do_draft", side_effect=dispatch
            ) as production:
                action, note = subject.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertEqual(note, "selected producer dispatched")
            self.assertIsNone(observed["policy_before_plan"])
            self.assertEqual(
                observed["policy"]["producer"],
                {
                    "task_executor": "brainstorming",
                    "configuration": {
                        "max_rounds": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
                        "closure_policy": "majority",
                    },
                },
            )
            plan_preparation.assert_called_once()
            production.assert_called_once()

    def test_default_and_non_default_producers_are_frozen_per_order(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-policy-") as ws:
            path = init_state(ws, make_config())
            _units(path)
            subject = drv.Driver(path, runner=runners.MockRunner([]))
            document = _unit(subject, st.UNIT_SLICE_DOC)
            implementation = _unit(subject, st.UNIT_SLICE_IMPL)

            selected = subject.reviewed_work.configure(document, {
                "review_breadth": "single",
                "max_rounds_per_family": 3,
                "p3_reclassify_debt": True,
                "producer": {
                    "task_executor": "brainstorming",
                    "configuration": {
                        "max_rounds": 99,
                        "closure_policy": "majority",
                    },
                },
            })
            defaulted = subject.reviewed_work.configure(implementation, {})

            self.assertEqual(selected["producer"]["task_executor"], "brainstorming")
            self.assertEqual(selected["review_breadth"], "single")
            self.assertEqual(selected["max_rounds_per_family"], 3)
            self.assertEqual(
                defaulted["producer"], {
                    "task_executor": "agent_call",
                    "configuration": {"role": "implement"},
                }
            )
            self.assertEqual(defaulted["review_breadth"], "double")
            self.assertEqual(defaulted["max_rounds_per_family"], 6)
            self.assertIn("implementation_size_control", defaulted)
            self.assertEqual(subject._review_families(document), ["codex"])
            self.assertEqual(
                subject._review_families(implementation), ["codex", "claude"]
            )
            self.assertFalse(
                subject._worker_result_policy(document)["p3_reclassify_debt"]
            )
            frozen = st.load(path)
            by_kind = {unit["kind"]: unit for unit in frozen["units"]}
            self.assertEqual(
                by_kind[st.UNIT_SLICE_DOC]["reviewed_policy"], selected
            )
            self.assertEqual(
                by_kind[st.UNIT_SLICE_IMPL]["reviewed_policy"], defaulted
            )
            self.assertEqual(
                frozen["milestone"]["slices"][0]
                ["producer_task_executor"]["implement"]["task_executor"],
                "agent_call",
            )
            self.assertEqual(
                [
                    event["unit"] for event in frozen["events"]
                    if event["type"] == "reviewed_policy_frozen"
                ],
                ["slice_doc-01", "slice_impl-01"],
            )

    def test_omitted_producer_freezes_plan_choice_across_restart(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-default-") as ws:
            path = init_state(ws, make_config())
            _units(path, {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {
                    "task_executor": "brainstorming",
                    "configuration": {"closure_policy": "majority"},
                },
            })
            subject = drv.Driver(path, runner=runners.MockRunner([]))
            implementation = _unit(subject, st.UNIT_SLICE_IMPL)

            frozen = subject.reviewed_work.configure(implementation, {
                "review_breadth": "single",
                "same_family_second_look": True,
                "p3_reclassify_debt": True,
                "max_fix_loops": 2,
                "implementation_size_control": {
                    "soft_lines": 40,
                    "hard_lines": 60,
                    "unconfirmed_grace_s": 3,
                    "confirmed_grace_s": 7,
                },
            })

            self.assertEqual(
                frozen["producer"],
                {
                    "task_executor": "brainstorming",
                    "configuration": {
                        "max_rounds": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
                        "closure_policy": "majority",
                    },
                },
            )
            self.assertTrue(subject._brainstorming_producer_selected(
                implementation, contracts.KIND_IMPLEMENT
            ))

            changed = st.load(path)
            changed["milestone"]["slices"][0][
                "producer_task_executor"
            ]["implement"] = {"task_executor": "agent_call"}
            st.save(path, changed)

            recovered = drv.Driver(path, runner=runners.MockRunner([]))
            implementation = _unit(recovered, st.UNIT_SLICE_IMPL)
            self.assertEqual(
                recovered.reviewed_work.configure(implementation, {}), frozen
            )
            self.assertTrue(recovered._brainstorming_producer_selected(
                implementation, contracts.KIND_IMPLEMENT
            ))
            self.assertEqual(recovered._review_families(implementation), ["codex"])
            self.assertEqual(recovered._reviewed_limit(
                implementation, "max_fix_loops"
            ), 2)
            result_policy = recovered._worker_result_policy(implementation)
            self.assertTrue(result_policy["p3_reclassify_debt"])
            self.assertTrue(result_policy["same_family_second_look"])
            self.assertIsNone(
                recovered._implementation_size_settings(implementation)
            )

    def test_restart_uses_the_frozen_producer_not_the_slice_plan(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-restart-") as ws:
            path = init_state(ws, make_config())
            _units(path)
            subject = drv.Driver(path, runner=runners.MockRunner([]))
            document = _unit(subject, st.UNIT_SLICE_DOC)
            policy = {
                "producer": {
                    "task_executor": "brainstorming",
                    "configuration": {"closure_policy": "majority"},
                },
            }
            frozen = subject.reviewed_work.configure(document, policy)
            self.assertEqual(
                frozen["producer"]["configuration"],
                {
                    "max_rounds": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
                    "closure_policy": "majority",
                },
            )

            recovered = drv.Driver(path, runner=runners.MockRunner([]))
            document = _unit(recovered, st.UNIT_SLICE_DOC)
            self.assertTrue(recovered._brainstorming_producer_selected(
                document, contracts.KIND_DRAFT_SLICE_NOTE
            ))
            with mock.patch.object(
                recovered,
                "_start_brainstorming_production",
                return_value="selected Brainstorming",
            ) as start:
                result = recovered._do_draft(
                    unit=document,
                    call_preparation=drv.ReviewedWorkCallPreparation(recovered),
                )
            self.assertEqual(result, "selected Brainstorming")
            start.assert_called_once_with(
                document, contracts.KIND_DRAFT_SLICE_NOTE
            )
            self.assertEqual(
                recovered.reviewed_work.configure(document, policy), frozen
            )
            with self.assertRaises(tasks.TaskRequestError) as changed:
                recovered.reviewed_work.configure(document, {
                    "producer": {"task_executor": "agent_call"},
                })
            self.assertEqual(changed.exception.code, tasks.INVALID_TASK_REQUEST)
            self.assertEqual(
                sum(
                    event["type"] == "reviewed_policy_frozen"
                    for event in st.load(path)["events"]
                ),
                1,
            )

    def test_reconciliation_rebuild_freezes_the_repaired_plan_producer(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-rebuild-") as ws:
            path = init_state(ws, make_config())
            _units(path)
            subject = drv.Driver(path, runner=runners.MockRunner([]))
            implementation = _unit(subject, st.UNIT_SLICE_IMPL)
            subject.reviewed_work.configure(implementation, {})

            state = st.load(path)
            state["units"][0]["status"] = st.U_SEALED
            state["units"][1]["status"] = st.U_SEALED
            implementation = state["units"][2]
            implementation["status"] = st.U_SEALED
            st.save(path, state)

            repaired = st.load(path)
            repaired["milestone"]["slices"][0][
                "producer_task_executor"
            ]["implement"] = {"task_executor": "brainstorming"}
            implementation = repaired["units"][2]
            st.requeue_implementation_after_reconciliation(
                repaired, implementation, "accepted-repair"
            )
            self.assertNotIn("reviewed_policy", implementation)
            st.save(path, repaired)

            rebuilt = drv.Driver(path, runner=runners.MockRunner([]))
            observed = {}

            def dispatch(unit, call_preparation):
                observed["producer"] = unit["reviewed_policy"]["producer"]
                return "repaired producer dispatched"

            with mock.patch.object(
                rebuilt.milestone_reviewed_calls,
                "ensure_author_plan",
                return_value=False,
            ), mock.patch.object(
                rebuilt, "_do_draft", side_effect=dispatch
            ) as production:
                action, note = rebuilt.step()

            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertEqual(note, "repaired producer dispatched")
            self.assertEqual(
                observed["producer"]["task_executor"], "brainstorming"
            )
            self.assertEqual(
                [
                    event["task_executor"]
                    for event in st.load(path)["events"]
                    if event["type"] == "reviewed_policy_frozen"
                ],
                ["agent_call", "brainstorming"],
            )
            production.assert_called_once()

    def test_selected_agent_call_keeps_the_semantic_job_role(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-agent-") as ws:
            path = init_state(ws, make_config())
            _units(path)
            subject = drv.Driver(path, runner=runners.MockRunner([]))
            implementation = _unit(subject, st.UNIT_SLICE_IMPL)
            subject.reviewed_work.configure(implementation, {
                "producer": {
                    "task_executor": "agent_call",
                    "configuration": {"role": "implement"},
                },
            })

            record = subject._admit_worker_task(
                implementation,
                contracts.KIND_IMPLEMENT,
                "implement the selected production",
                "codex",
            )

            self.assertEqual(record["order"]["task_executor"], "agent_call")
            self.assertEqual(
                record["order"]["configuration"], {"role": "implement"}
            )
            self.assertEqual(
                record["order"]["request"]["context"]["task_kind"],
                contracts.KIND_IMPLEMENT,
            )
            self.assertEqual(subject.runner.calls, [])

    def test_production_choice_never_selects_a_judgment_call(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-judgment-") as ws:
            path = init_state(ws, make_config())
            _units(path)
            subject = drv.Driver(path, runner=runners.MockRunner([]))
            document = _unit(subject, st.UNIT_SLICE_DOC)
            subject.reviewed_work.configure(document, {
                "producer": {"task_executor": "brainstorming"},
            })
            self.assertTrue(subject._brainstorming_producer_selected(
                document, contracts.KIND_DRAFT_SLICE_NOTE
            ))

            record = subject._admit_worker_task(
                document,
                contracts.KIND_REVIEW_ROUND,
                "review the selected production",
                "codex",
            )

            self.assertEqual(record["order"]["task_executor"], "agent_call")
            self.assertEqual(
                record["order"]["configuration"], {"role": "review"}
            )
            self.assertEqual(subject.runner.calls, [])

    def test_invalid_policy_fails_before_any_physical_call(self):
        cases = (
            (
                st.UNIT_SLICE_DOC,
                {"producer": {"task_executor": "missing"}},
                tasks.UNKNOWN_TASK_EXECUTOR,
            ),
            (
                st.UNIT_SKELETON,
                {"producer": {"task_executor": "brainstorming"}},
                tasks.INVALID_TASK_REQUEST,
            ),
            (
                st.UNIT_SLICE_IMPL,
                {
                    "producer": {
                        "task_executor": "agent_call",
                        "configuration": {"role": "review"},
                    },
                },
                tasks.INVALID_TASK_REQUEST,
            ),
            (
                st.UNIT_SLICE_DOC,
                {"review_breadth": "double", "same_family_second_look": True},
                tasks.INVALID_TASK_REQUEST,
            ),
            (
                st.UNIT_SLICE_DOC,
                {"max_fix_loops": -1},
                tasks.INVALID_TASK_REQUEST,
            ),
            (
                st.UNIT_SLICE_IMPL,
                {"implementation_size_control": {
                    "soft_lines": 10, "hard_lines": 10,
                }},
                tasks.INVALID_TASK_REQUEST,
            ),
        )
        for index, (kind, policy, code) in enumerate(cases):
            with self.subTest(kind=kind, code=code), tempfile.TemporaryDirectory(
                prefix="orch-reviewed-invalid-%d-" % index
            ) as ws:
                path = init_state(ws, make_config())
                _units(path)
                subject = drv.Driver(path, runner=runners.MockRunner([]))
                before = st.load(path)
                with self.assertRaises(tasks.TaskRequestError) as refused:
                    subject.reviewed_work.configure(
                        _unit(subject, kind), policy
                    )
                self.assertEqual(refused.exception.code, code)
                self.assertEqual(st.load(path), before)
                self.assertEqual(subject.runner.calls, [])


if __name__ == "__main__":
    unittest.main()
