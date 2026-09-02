"""Order-local producer policy for the reviewed-work boundary."""

import tempfile
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st
from orchestrator import tasks
from orchestrator.tests.test_driver_mock import (
    append_file,
    finding,
    fix_ok,
    init_state,
    make_config,
    report,
    skeleton_script,
    step,
    triaged,
)


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
    def _step_until(self, subject, predicate, max_steps=60):
        for _ in range(max_steps):
            if predicate(subject.state):
                return
            action, _note = subject.step()
            self.assertNotEqual(action.type, drv.A_DONE)
        self.fail("reviewed policy lifecycle did not reach its expected state")

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
            self.assertNotIn("implementation_size_control", frozen)
            self.assertIsNone(
                recovered._implementation_size_settings(implementation)
            )

    def test_brainstorming_implementation_refuses_size_control_before_freeze(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-no-size-") as ws:
            path = init_state(ws, make_config())
            _units(path, {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "brainstorming"},
            })
            subject = drv.Driver(path, runner=runners.MockRunner([]))
            implementation = _unit(subject, st.UNIT_SLICE_IMPL)
            before = st.load(path)

            with self.assertRaises(tasks.TaskRequestError) as refused:
                subject.reviewed_work.configure(implementation, {
                    "implementation_size_control": {
                        "soft_lines": 40,
                        "hard_lines": 60,
                        "unconfirmed_grace_s": 3,
                        "confirmed_grace_s": 7,
                    },
                })

            self.assertEqual(refused.exception.code, tasks.INVALID_TASK_REQUEST)
            self.assertIn("requires an agent_call", str(refused.exception))
            self.assertEqual(st.load(path), before)
            self.assertEqual(subject.runner.calls, [])

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

    def test_double_family_requires_two_distinct_current_reviews(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-double-") as ws:
            path = init_state(ws, make_config())
            runner = runners.MockRunner([
                skeleton_script()[0],
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ])
            subject = drv.Driver(path, runner=runner)
            unit = subject.state["units"][0]
            subject.reviewed_work.configure(unit, {
                "review_breadth": "double",
            })

            self._step_until(
                subject,
                lambda state: state["units"][0]["status"] == st.U_SEALED,
            )

            sealed = st.load(path)["units"][0]
            cited = sealed["seals"][-1]["reviews"]
            self.assertEqual(cited, [
                "skeleton-codex-r1", "skeleton-claude-r1",
            ])
            cited_rounds = {
                round_["id"]: round_
                for round_ in sealed["rounds"]
                if round_["id"] in cited
            }
            self.assertEqual(
                [cited_rounds[round_id]["family"] for round_id in cited],
                ["codex", "claude"],
            )
            self.assertEqual(
                {
                    cited_rounds[round_id]["evidence_fingerprint"]
                    for round_id in cited
                },
                {sealed["review_evidence_fingerprint"]},
            )
            self.assertEqual(runner.script, [])

        with tempfile.TemporaryDirectory(prefix="orch-reviewed-refusal-") as ws:
            path = init_state(ws, make_config(
                families_order=["codex"],
                commands={"codex": ["fake-codex"]},
            ))
            runner = runners.MockRunner([skeleton_script()[0]])
            subject = drv.Driver(path, runner=runner)
            subject.reviewed_work.configure(subject.state["units"][0], {
                "review_breadth": "double",
            })

            self._step_until(
                subject, lambda state: state["failure"] is not None,
            )

            failed = st.load(path)
            self.assertIn(
                "distinct_families_unsatisfiable",
                failed["failure"]["reason"],
            )
            self.assertEqual(failed["failure"]["unit"], "skeleton")
            self.assertEqual(failed["units"][0]["status"], st.U_FAILED)
            self.assertEqual(
                [call[1] for call in runner.calls], ["draft_skeleton"],
            )
            self.assertEqual(runner.script, [])

    def test_order_caps_survive_resume_without_leaking(self):
        with tempfile.TemporaryDirectory(prefix="orch-reviewed-caps-") as ws:
            path = init_state(ws, make_config(
                max_rounds_per_family=7,
                max_fix_loops=7,
                delta_full_review_after_fixes=7,
            ))
            runner = runners.MockRunner([
                skeleton_script()[0],
                step(
                    "review_round",
                    report("review_round", [finding("F1", "first defect")]),
                    family="codex",
                ),
                step(
                    "fix_findings",
                    fix_ok(
                        [triaged("F1", "fixed", "first defect")],
                        files_changed=["docs/skeleton.md"],
                    ),
                    family="codex",
                    side_effect=append_file("docs/skeleton.md", "\nfix one\n"),
                ),
                step(
                    "delta_review",
                    report("delta_review", [finding("D1", "delta defect")]),
                    family="codex",
                ),
                step(
                    "fix_findings",
                    fix_ok(
                        [triaged("D1", "fixed", "delta defect")],
                        files_changed=["docs/skeleton.md"],
                    ),
                    family="codex",
                    side_effect=append_file("docs/skeleton.md", "\nfix two\n"),
                ),
                step("review_round", report("review_round"), family="codex"),
            ])
            subject = drv.Driver(path, runner=runner)
            selected = subject.reviewed_work.configure(
                subject.state["units"][0],
                {
                    "review_breadth": "single",
                    "max_rounds_per_family": 1,
                    "max_fix_loops": 1,
                    "delta_full_review_after_fixes": 2,
                },
            )

            self._step_until(
                subject,
                lambda state: state["units"][0]["status"] == st.U_ROUNDS,
            )
            seeded = st.load(path)
            st.record_round(
                seeded,
                seeded["units"][0],
                "codex",
                contracts.KIND_REVIEW_ROUND,
                report("review_round"),
                meta={"invalidated": "pre-resume capped review evidence"},
            )
            st.save(path, seeded)
            subject = drv.Driver(path, runner=runner)
            self._step_until(subject, lambda state: state["failure"] is not None)
            first_failure = st.load(path)
            self.assertIn(
                "max_rounds_per_family=1", first_failure["failure"]["reason"]
            )
            self.assertTrue(first_failure["units"][0]["rounds"][0]["invalidated"])
            self.assertEqual(
                [call[1] for call in runner.calls], ["draft_skeleton"]
            )

            st.resume_run(first_failure)
            st.save(path, first_failure)
            subject = drv.Driver(path, runner=runner)
            self.assertEqual(subject.state["units"][0]["reviewed_policy"], selected)
            self._step_until(subject, lambda state: state["failure"] is not None)
            second_failure = st.load(path)
            self.assertIn(
                "did not converge after 1 fixer+delta loops",
                second_failure["failure"]["reason"],
            )

            st.resume_run(second_failure)
            st.save(path, second_failure)
            subject = drv.Driver(path, runner=runner)
            self.assertEqual(subject.state["units"][0]["reviewed_policy"], selected)
            self._step_until(
                subject,
                lambda state: state["units"][0]["status"] == st.U_SEALED,
            )

            completed = st.load(path)
            unit = completed["units"][0]
            checkpoints = [
                event for event in completed["events"]
                if event["type"] == "delta_checkpoint"
            ]
            self.assertEqual(
                [(event["fixes"], event["dirty_deltas"])
                 for event in checkpoints],
                [(2, 1)],
            )
            self.assertEqual(
                [call[1] for call in runner.calls],
                [
                    "draft_skeleton", "review_round", "fix_findings",
                    "delta_review", "fix_findings", "review_round",
                ],
            )
            self.assertEqual(
                len([event for event in completed["events"]
                     if event["type"] == "resumed"]),
                2,
            )
            sibling = subject._unit_by_key("slice_doc-01")
            sibling_policy = subject.reviewed_work.configure(sibling, {})
            self.assertEqual(
                (
                    sibling_policy["max_rounds_per_family"],
                    sibling_policy["max_fix_loops"],
                    sibling_policy["delta_full_review_after_fixes"],
                ),
                (7, 7, 7),
            )
            self.assertEqual(unit["reviewed_policy"], selected)
            self.assertEqual(runner.script, [])

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
