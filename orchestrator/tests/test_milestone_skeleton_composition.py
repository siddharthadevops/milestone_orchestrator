"""Focused first-plan composition proof for Slice 8."""

import copy
import tempfile
from pathlib import Path

from orchestrator import canonical_plan, contracts, driver as drv
from orchestrator import gitops, runners, state as st, tasks
from orchestrator.tests import test_driver_mock as base


class MilestoneSkeletonCompositionTest(base.DriverTestCase):
    def _activated(self, workspace):
        base.git_init_workspace(workspace)
        path = drv.init_run(
            base.GOAL, workspace=workspace, config=base.make_config()
        )
        state = st.load(path)
        self.assertEqual(
            state["milestone"][st.SKELETON_COMPOSITION_KEY],
            st.SKELETON_COMPOSITION_VERSION,
        )
        return path

    def _fixture(self, workspace):
        path = self._activated(workspace)
        producer = base.canonical_skeleton_document().replace(
            "Calculator core", "Producer plan"
        )
        final = producer.replace("Producer plan", "Reviewed final plan")

        def first_effect(root):
            state = st.load(path)
            unit = state["units"][0]
            records = tasks.task_records(state)
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(unit["reviewed_task_id"], record["id"])
            self.assertIsNone(record["result"])
            self.assertEqual(
                record["order"]["task_executor"], "reviewed_task"
            )
            configuration = copy.deepcopy(
                record["order"]["configuration"]
            )
            self.assertEqual(
                configuration.pop("task_kind"),
                contracts.KIND_DRAFT_SKELETON,
            )
            self.assertEqual(configuration, unit["reviewed_policy"])
            self.assertEqual(
                record["order"]["request"]["work_area"],
                {
                    "workspace_path": root,
                    "primary": root,
                    "additional": [],
                },
            )
            self.assertNotIn(canonical_plan.ANCHOR_KEY, state["milestone"])
            self.assertEqual(state["milestone"]["slices"], [])
            base.write_file("docs/skeleton.md", producer)(root)

        script = [
            base.step(
                contracts.KIND_DRAFT_SKELETON,
                base.ok(
                    contracts.KIND_DRAFT_SKELETON,
                    artifact="docs/skeleton.md",
                ),
                family="codex",
                side_effect=first_effect,
            ),
            base.step(
                contracts.KIND_REVIEW_ROUND,
                base.report(
                    contracts.KIND_REVIEW_ROUND,
                    [base.finding(
                        "PLAN-1", "Use the reviewed plan title", severity="P1"
                    )],
                ),
                family="codex",
            ),
            base.step(
                contracts.KIND_FIX_FINDINGS,
                base.fix_ok(
                    [
                        base.triaged(
                            "PLAN-1", "fixed", "Use the reviewed plan title",
                            severity="P1",
                        )
                    ],
                    files_changed=["docs/skeleton.md"],
                ),
                family="codex",
                side_effect=base.write_file("docs/skeleton.md", final),
            ),
            base.step(
                contracts.KIND_DELTA_REVIEW,
                base.report(contracts.KIND_DELTA_REVIEW),
                family="codex",
            ),
            base.step(
                contracts.KIND_REVIEW_ROUND,
                base.report(contracts.KIND_REVIEW_ROUND),
                family="codex",
            ),
            base.step(
                contracts.KIND_REVIEW_ROUND,
                base.report(contracts.KIND_REVIEW_ROUND),
                family="claude",
            ),
        ]
        runner = runners.MockRunner(script)
        return path, drv.Driver(path, runner=runner), runner, final

    def _until(self, subject, predicate, limit=40):
        for _ in range(limit):
            if predicate():
                return
            action, note = subject.step()
            self.assertNotEqual(action.type, drv.A_FAILED, note)
        self.fail("composition fixture did not reach its boundary")

    def test_one_reviewed_skeleton_task_is_durable_before_any_call(self):
        with tempfile.TemporaryDirectory(prefix="skeleton-task-") as workspace:
            _path, subject, runner, _final = self._fixture(workspace)
            subject.step()
            self.assertEqual(len(runner.calls), 1)
            unit = subject._find_unit(st.UNIT_SKELETON, None)
            record = tasks.task_record(
                subject.state, unit["reviewed_task_id"]
            )
            self.assertEqual(unit["draft"]["task_id"], record["id"])
            self.assertIsNone(record["result"])
            self.assertEqual(len(tasks.task_records(subject.state)), 1)

    def test_draft_reviews_and_fix_do_not_anchor_or_open_slices(self):
        with tempfile.TemporaryDirectory(
            prefix="skeleton-candidate-"
        ) as workspace:
            _path, subject, runner, final = self._fixture(workspace)
            unit = subject._find_unit(st.UNIT_SKELETON, None)
            self._until(subject, lambda: len(runner.calls) == 3)
            self.assertEqual(
                Path(workspace, "docs/skeleton.md").read_text(encoding="utf-8"),
                final,
            )
            self.assertNotIn(
                canonical_plan.ANCHOR_KEY, subject.state["milestone"]
            )
            self.assertEqual(subject.state["milestone"]["slices"], [])
            self.assertEqual(subject.state["units"], [unit])
            record = tasks.task_record(
                subject.state, unit["reviewed_task_id"]
            )
            self.assertIsNone(record["result"])

            self._until(
                subject,
                lambda: unit["status"] == st.U_PRE_SEAL_VERIFY,
            )
            self.assertNotIn(
                canonical_plan.ANCHOR_KEY, subject.state["milestone"]
            )
            self.assertEqual(subject.state["milestone"]["slices"], [])

    def test_task_gate_result_anchors_the_same_commit_and_final_table(self):
        with tempfile.TemporaryDirectory(prefix="skeleton-gate-") as workspace:
            _path, subject, _runner, _final = self._fixture(workspace)
            unit = subject._find_unit(st.UNIT_SKELETON, None)
            self._until(subject, lambda: unit["status"] == st.U_SEALED)

            record = tasks.task_record(
                subject.state, unit["reviewed_task_id"]
            )
            result = record["result"]
            self.assertEqual(result["status"], "success")
            native = result["native_result"]
            self.assertEqual(
                set(native),
                {"production_result", "review_evidence", "gate_commit"},
            )
            revision = gitops.commit_full_sha(
                workspace, native["gate_commit"]
            )
            anchor = subject.state["milestone"][canonical_plan.ANCHOR_KEY]
            self.assertEqual(anchor["revision"], revision)
            self.assertEqual(
                subject.state["milestone"]["slices"][0]["title"],
                "Reviewed final plan",
            )
            established = [
                event
                for event in subject.state["events"]
                if event["type"] == "canonical_plan_established"
            ]
            self.assertEqual(
                [event["accepted_revision"] for event in established],
                [revision],
            )
            accounting = tasks.task_accounting(subject.state, record["id"])
            self.assertEqual(
                {name: result[name] for name in accounting}, accounting
            )
            self.assertEqual(
                len(tasks.task_records(subject.state)), 1
            )
            self.assertEqual(
                st.current_unit(subject.state)["kind"], st.UNIT_SLICE_DOC
            )
            self.assertFalse(
                any(
                    "canonical plan after" in message.lower()
                    for _sha, message in base.git_subjects(workspace)
                )
            )

    def test_terminal_producer_failure_resume_refuses_without_a_plan(self):
        with tempfile.TemporaryDirectory(prefix="skeleton-failure-") as workspace:
            path = self._activated(workspace)
            runner = runners.MockRunner([
                base.step(
                    contracts.KIND_DRAFT_SKELETON,
                    "not a protocol result",
                    family="codex",
                ),
                base.step(
                    contracts.KIND_DRAFT_SKELETON,
                    "still not a protocol result",
                    family="codex",
                ),
            ])
            subject = drv.Driver(path, runner=runner)
            action, _note = subject.step()
            self.assertEqual(action.type, drv.A_DRAFT)
            unit = subject._find_unit(st.UNIT_SKELETON, None)
            record = tasks.task_record(
                subject.state, unit["reviewed_task_id"]
            )
            task_id = record["id"]
            self.assertEqual(record["result"]["status"], "failure")
            self.assertEqual(subject.state["milestone"]["status"], st.M_FAILED)
            self.assertNotIn(
                canonical_plan.ANCHOR_KEY, subject.state["milestone"]
            )
            self.assertEqual(subject.state["milestone"]["slices"], [])

            st.resume_run(subject.state)
            st.save(path, subject.state)
            resumed_runner = runners.MockRunner([])
            resumed = drv.Driver(path, runner=resumed_runner)
            action, note = resumed.step()

            self.assertEqual(action.type, drv.A_FAILED)
            self.assertIn("distinct retry attempt", note)
            self.assertEqual(resumed_runner.calls, [])
            self.assertEqual(
                tasks.task_record(resumed.state, task_id), record
            )
            self.assertEqual(
                resumed.state["milestone"]["status"], st.M_FAILED
            )
            self.assertEqual(
                resumed._find_unit(st.UNIT_SKELETON, None)["status"],
                st.U_FAILED,
            )
            self.assertNotIn(
                canonical_plan.ANCHOR_KEY, resumed.state["milestone"]
            )
            self.assertEqual(resumed.state["milestone"]["slices"], [])
            self.assertNotIn(
                "Close milestone",
                [message for _sha, message in base.git_subjects(workspace)],
            )

    def test_missing_git_gate_fails_before_the_first_call(self):
        with tempfile.TemporaryDirectory(prefix="skeleton-no-git-") as workspace:
            base.git_init_workspace(workspace)
            path = drv.init_run(
                base.GOAL,
                workspace=workspace,
                config=base.make_config(git={"enabled": False}),
            )
            runner = runners.MockRunner([])
            subject = drv.Driver(path, runner=runner)
            action, _note = subject.step()
            self.assertEqual(action.type, drv.A_FAILED)
            self.assertEqual(runner.calls, [])
            record = tasks.task_records(subject.state)[0]
            self.assertEqual(record["result"]["status"], "failure")
            self.assertNotIn(
                canonical_plan.ANCHOR_KEY, subject.state["milestone"]
            )

    def test_pre_activation_run_keeps_direct_skeleton_law(self):
        with tempfile.TemporaryDirectory(prefix="skeleton-legacy-") as workspace:
            path = base.init_state(workspace, base.make_config())
            subject = drv.Driver(
                path, runner=runners.MockRunner([base.skeleton_script()[0]])
            )
            subject.step()
            self.assertNotIn(
                st.SKELETON_COMPOSITION_KEY, subject.state["milestone"]
            )
            self.assertEqual(tasks.task_records(subject.state), [])
            self.assertIn(
                canonical_plan.ANCHOR_KEY, subject.state["milestone"]
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
