"""Focused first-plan composition proof for Slice 8."""

import copy
import tempfile
from pathlib import Path
from unittest import mock

from orchestrator import canonical_plan, contracts, driver as drv
from orchestrator import gitops, ledgers, registry, runners, service
from orchestrator import state as st, tasks
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

    def test_classification_charge_belongs_to_the_outer_task(self):
        with tempfile.TemporaryDirectory(
            prefix="skeleton-classification-"
        ) as workspace:
            base.git_init_workspace(workspace)
            path = drv.init_run(
                base.GOAL,
                workspace=workspace,
                config=base.make_config(p3_reclassify_debt=True),
            )
            document = base.canonical_skeleton_document()
            runner = runners.MockRunner([
                base.step(
                    contracts.KIND_DRAFT_SKELETON,
                    base.ok(
                        contracts.KIND_DRAFT_SKELETON,
                        artifact="docs/skeleton.md",
                    ),
                    family="codex",
                    side_effect=base.write_file("docs/skeleton.md", document),
                ),
                base.step(
                    contracts.KIND_REVIEW_ROUND,
                    base.report(contracts.KIND_REVIEW_ROUND, [base.finding(
                        "P3-1", "bounded wording debt"
                    )]),
                    family="codex",
                ),
                base.step(
                    contracts.KIND_RECLASSIFY,
                    base.ok(
                        contracts.KIND_RECLASSIFY,
                        drift_risk="low",
                        drift_damage="low",
                        reason="bounded wording only",
                    ),
                    family="claude",
                ),
                base.step(
                    contracts.KIND_REVIEW_ROUND,
                    base.report(contracts.KIND_REVIEW_ROUND),
                    family="claude",
                ),
            ])
            subject = drv.Driver(path, runner=runner)
            unit = subject._find_unit(st.UNIT_SKELETON, None)
            self._until(subject, lambda: unit["status"] == st.U_SEALED)
            record = tasks.task_records(subject.state)[0]
            rating = next(
                event for event in subject.state["events"]
                if event["type"] == "reclassify_recorded"
            )
            self.assertEqual(rating["task_id"], record["id"])
            self.assertEqual(record["result"]["duration_s"], 0.04)
            self.assertEqual(
                tasks.task_accounting(subject.state, record["id"]),
                {key: record["result"][key]
                 for key in tasks.task_accounting(subject.state, record["id"])},
            )

    def test_terminal_failure_resume_uses_disjoint_successor(self):
        with tempfile.TemporaryDirectory(prefix="skeleton-failure-") as workspace:
            path = self._activated(workspace)
            document = base.canonical_skeleton_document()
            runner = runners.MockRunner([
                base.step(
                    contracts.KIND_DRAFT_SKELETON,
                    base.ok(
                        contracts.KIND_DRAFT_SKELETON,
                        artifact="docs/skeleton.md",
                    ),
                    family="codex",
                    side_effect=base.write_file("docs/skeleton.md", document),
                ),
                base.step(
                    contracts.KIND_REVIEW_ROUND,
                    base.report(contracts.KIND_REVIEW_ROUND, [base.finding(
                        "F1", "first attempt finding", severity="P1"
                    )]),
                    family="codex",
                ),
                base.step(
                    contracts.KIND_FIX_FINDINGS,
                    base.fix_ok([base.triaged(
                        "F1",
                        "rejected_adjudicated",
                        "first attempt finding",
                        severity="P1",
                        adjudication_ref="ghost/F9",
                    )]),
                    family="codex",
                ),
                base.step(
                    contracts.KIND_DRAFT_SKELETON,
                    base.ok(
                        contracts.KIND_DRAFT_SKELETON,
                        artifact="docs/skeleton.md",
                    ),
                    family="codex",
                    side_effect=base.write_file("docs/skeleton.md", document),
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
            ])
            subject = drv.Driver(path, runner=runner)
            for _ in range(10):
                subject.step()
                if subject.state.get("failure") is not None:
                    break
            unit = subject._find_unit(st.UNIT_SKELETON, None)
            failed = tasks.task_record(
                subject.state, unit["reviewed_task_id"]
            )
            failed_id = failed["id"]
            old_review = unit["rounds"][0]["id"]
            self.assertEqual(failed["result"]["status"], "failure")
            self.assertEqual(failed["result"]["duration_s"], 0.03)
            self.assertEqual(subject.state["milestone"]["status"], st.M_FAILED)
            self.assertNotIn(
                canonical_plan.ANCHOR_KEY, subject.state["milestone"]
            )

            st.resume_run(subject.state)
            st.save(path, subject.state)
            resumed = drv.Driver(path, runner=runner)
            resumed.step()
            successor_unit = resumed._find_unit(st.UNIT_SKELETON, None)
            successor_id = successor_unit["reviewed_task_id"]
            self.assertNotEqual(successor_id, failed_id)
            self.assertEqual(tasks.task_record(resumed.state, failed_id), failed)
            self.assertNotIn(
                canonical_plan.ANCHOR_KEY, resumed.state["milestone"]
            )
            self._until(
                resumed, lambda: successor_unit["status"] == st.U_SEALED
            )
            successor = tasks.task_record(resumed.state, successor_id)
            cited = successor["result"]["native_result"]["review_evidence"][
                "reviews"
            ]
            self.assertNotIn(old_review, cited)
            self.assertEqual(successor["result"]["duration_s"], 0.03)
            self.assertEqual(
                tasks.task_accounting(resumed.state, successor_id),
                {key: successor["result"][key]
                 for key in tasks.task_accounting(resumed.state, successor_id)},
            )
            self.assertAlmostEqual(
                st.summary(resumed.state)["work_duration_s"], 0.06
            )

    def test_repeated_phantom_fix_resume_uses_disjoint_successor(self):
        with tempfile.TemporaryDirectory(
            prefix="skeleton-phantom-fix-"
        ) as workspace:
            path = self._activated(workspace)
            claimed_fix = base.step(
                contracts.KIND_FIX_FINDINGS,
                base.fix_ok(
                    [base.triaged(
                        "F1", "fixed", "first attempt finding", severity="P1"
                    )],
                    files_changed=["docs/skeleton.md"],
                ),
                family="codex",
            )
            runner = runners.MockRunner([
                base.skeleton_script()[0],
                base.step(
                    contracts.KIND_REVIEW_ROUND,
                    base.report(contracts.KIND_REVIEW_ROUND, [base.finding(
                        "F1", "first attempt finding", severity="P1"
                    )]),
                    family="codex",
                ),
                claimed_fix,
                copy.deepcopy(claimed_fix),
                base.skeleton_script()[0],
            ])
            subject = drv.Driver(path, runner=runner)
            self.step_until(
                subject, lambda state: state["failure"] is not None,
                max_steps=12,
            )

            unit = subject._find_unit(st.UNIT_SKELETON, None)
            failed_id = unit["reviewed_task_id"]
            failed = copy.deepcopy(tasks.task_record(subject.state, failed_id))
            self.assertEqual(subject.state["failure"]["type"], "phantom_fix")
            self.assertEqual(failed["result"]["status"], "failure")
            self.assertEqual(failed["result"]["duration_s"], 0.04)

            st.resume_run(subject.state)
            st.save(path, subject.state)
            resumed = drv.Driver(path, runner=runner)
            resumed.step()

            successor_unit = resumed._find_unit(st.UNIT_SKELETON, None)
            successor_id = successor_unit["reviewed_task_id"]
            self.assertNotEqual(successor_id, failed_id)
            self.assertEqual(tasks.task_record(resumed.state, failed_id), failed)
            self.assertEqual(
                tasks.task_accounting(resumed.state, failed_id)["duration_s"],
                0.04,
            )
            self.assertEqual(
                tasks.task_accounting(resumed.state, successor_id)["duration_s"],
                0.01,
            )

    def test_recoverable_stop_resume_reuses_the_open_task(self):
        with tempfile.TemporaryDirectory(
            prefix="skeleton-resume-"
        ) as workspace:
            path = self._activated(workspace)
            subject = drv.Driver(
                path,
                runner=runners.MockRunner([
                    base.skeleton_script()[0],
                    base.step(
                        contracts.KIND_REVIEW_ROUND,
                        {
                            "status": "blocked",
                            "kind": contracts.KIND_REVIEW_ROUND,
                            "blocked_reason": "operator input needed",
                        },
                        family="codex",
                    ),
                ]),
            )
            subject.step()
            subject.step()
            subject.step()

            unit = subject._find_unit(st.UNIT_SKELETON, None)
            task_id = unit["reviewed_task_id"]
            self.assertEqual(
                subject.state["failure"]["type"], "worker_blocked"
            )
            self.assertIsNone(
                tasks.task_record(subject.state, task_id)["result"]
            )

            st.resume_run(subject.state)
            st.save(path, subject.state)
            resumed = drv.Driver(
                path,
                runner=runners.MockRunner([
                    base.step(
                        contracts.KIND_REVIEW_ROUND,
                        base.report(contracts.KIND_REVIEW_ROUND),
                        family="codex",
                    )
                ]),
            )
            resumed.step()

            unit = resumed._find_unit(st.UNIT_SKELETON, None)
            self.assertIsNone(resumed.state["failure"])
            self.assertEqual(unit["reviewed_task_id"], task_id)
            self.assertIsNone(
                tasks.task_record(resumed.state, task_id)["result"]
            )
            self.assertEqual(len(tasks.task_records(resumed.state)), 1)

    def test_admission_and_gate_crash_windows_reuse_one_task(self):
        with tempfile.TemporaryDirectory(
            prefix="skeleton-admission-crash-"
        ) as workspace:
            path, subject, runner, _final = self._fixture(workspace)
            with mock.patch.object(
                subject.reviewed_work,
                "execute",
                side_effect=RuntimeError("crash after admission"),
            ), self.assertRaisesRegex(RuntimeError, "after admission"):
                subject.step()
            admitted = st.load(path)
            task_id = admitted["units"][0]["reviewed_task_id"]
            self.assertIsNone(tasks.task_record(admitted, task_id)["result"])

            restarted = drv.Driver(path, runner=runner)
            restarted.step()
            self.assertEqual(
                restarted.state["units"][0]["reviewed_task_id"], task_id
            )
            self.assertEqual(len(tasks.task_records(restarted.state)), 1)

        for mode in ("gate_error", "landed_then_crash"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(
                prefix="skeleton-gate-crash-"
            ) as workspace:
                path, subject, runner, _final = self._fixture(workspace)
                unit = subject._find_unit(st.UNIT_SKELETON, None)
                self._until(
                    subject, lambda: unit["status"] == st.U_PRE_SEAL_VERIFY
                )
                task_id = unit["reviewed_task_id"]
                real_finalize = gitops.finalize_gate

                if mode == "gate_error":
                    with mock.patch.object(
                        gitops,
                        "finalize_gate",
                        side_effect=gitops.GitError("temporary gate failure"),
                    ):
                        subject.step()
                    failed = st.load(path)
                    self.assertIsNone(
                        tasks.task_record(failed, task_id)["result"]
                    )
                    st.resume_run(failed)
                    st.save(path, failed)
                else:
                    def land_then_crash(root, message):
                        real_finalize(root, message)
                        raise RuntimeError("crash after gate")

                    with mock.patch.object(
                        gitops, "finalize_gate", side_effect=land_then_crash
                    ), self.assertRaisesRegex(RuntimeError, "after gate"):
                        subject.step()

                recovered = drv.Driver(path, runner=runner)
                with mock.patch.object(
                    recovered, "_do_draft", return_value="next unit ready"
                ):
                    recovered.step()
                record = tasks.task_record(recovered.state, task_id)
                self.assertEqual(record["result"]["status"], "success")
                self.assertIn(
                    canonical_plan.ANCHOR_KEY, recovered.state["milestone"]
                )
                self.assertEqual(len(tasks.task_records(recovered.state)), 1)
                gates = [
                    message for _sha, message in base.git_subjects(workspace)
                    if message == "Complete review of milestone skeleton"
                ]
                self.assertEqual(len(gates), 1)

    def test_result_and_anchor_crash_windows_converge_without_rework(self):
        for mode in ("before_anchor", "after_anchor_projection"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(
                prefix="skeleton-anchor-crash-"
            ) as workspace:
                path, subject, runner, _final = self._fixture(workspace)
                unit = subject._find_unit(st.UNIT_SKELETON, None)
                self._until(
                    subject, lambda: unit["status"] == st.U_PRE_SEAL_VERIFY
                )
                task_id = unit["reviewed_task_id"]

                if mode == "before_anchor":
                    patcher = mock.patch.object(
                        canonical_plan,
                        "establish_current_plan",
                        side_effect=RuntimeError("crash before anchor"),
                    )
                else:
                    real_ensure = st.ensure_due_unit

                    def crash_after_projection(state):
                        if canonical_plan.ANCHOR_KEY in state["milestone"]:
                            raise RuntimeError("crash after anchor projection")
                        return real_ensure(state)

                    patcher = mock.patch.object(
                        st, "ensure_due_unit", side_effect=crash_after_projection
                    )
                with patcher, self.assertRaisesRegex(RuntimeError, "crash"):
                    subject.step()

                interrupted = st.load(path)
                self.assertEqual(
                    tasks.task_record(interrupted, task_id)["result"]["status"],
                    "success",
                )
                self.assertNotIn(
                    canonical_plan.ANCHOR_KEY, interrupted["milestone"]
                )
                recovered = drv.Driver(path, runner=runner)
                with mock.patch.object(
                    recovered, "_do_draft", return_value="next unit ready"
                ):
                    recovered.step()
                self.assertEqual(len(tasks.task_records(recovered.state)), 1)
                self.assertEqual(len(runner.script), 0)
                self.assertEqual(
                    sum(event["type"] == "canonical_plan_established"
                        for event in recovered.state["events"]),
                    1,
                )

    def test_task_stop_refuses_while_run_stop_remains_the_control(self):
        with tempfile.TemporaryDirectory(prefix="skeleton-control-") as workspace, \
                tempfile.TemporaryDirectory(prefix="skeleton-home-") as home:
            path, subject, _runner, _final = self._fixture(workspace)
            subject.step()
            task_id = subject.state["units"][0]["reviewed_task_id"]
            entry = registry.new_entry(
                "run-1", "run", workspace, path
            )
            entry["pid"] = 4242
            registry.add(home, entry)
            who = {"admin": True}
            self.assertEqual(
                [row["id"] for row in service.visible_run_tasks(
                    home, who, "run-1"
                )],
                [task_id],
            )
            host = mock.Mock()
            with self.assertRaises(service.ApiError) as refused:
                service.stop_task(home, who, task_id, host)
            self.assertEqual(refused.exception.status, 409)
            self.assertEqual(
                str(refused.exception),
                "milestone tasks are stopped through their run",
            )
            host.stop.assert_not_called()

            with mock.patch.object(
                service, "reap_exited_drivers"
            ), mock.patch.object(
                service, "driver_alive", return_value=True
            ), mock.patch.object(
                service.os, "killpg"
            ) as killpg, mock.patch.object(
                service, "_wait_driver_exit", return_value=True
            ), mock.patch.object(service, "_clear_pid"):
                stopped = service.stop_run(home, "run-1")
            self.assertEqual(stopped["pid"], 4242)
            self.assertTrue(stopped["stopped"])
            killpg.assert_called_once()

    def test_reconciliation_and_final_close_stay_milestone_owned(self):
        with tempfile.TemporaryDirectory(
            prefix="skeleton-reconciliation-"
        ) as workspace:
            _path, subject, _runner, final = self._fixture(workspace)
            unit = subject._find_unit(st.UNIT_SKELETON, None)
            self._until(subject, lambda: unit["status"] == st.U_SEALED)
            task_count = len(tasks.task_records(subject.state))
            source_base = subject.state["milestone"][
                canonical_plan.ANCHOR_KEY
            ]["revision"]
            changed = final.replace('"id":1', '"id":2').replace(
                "Reviewed final plan", "Reconciled plan"
            )
            Path(workspace, "docs/skeleton.md").write_text(
                changed, encoding="utf-8"
            )
            gitops.commit_plain(workspace, "accepted plan change")
            accepted = gitops.head_full_sha(workspace)
            subject.state["milestone"][canonical_plan.ANCHOR_KEY][
                "revision"
            ] = accepted
            source = st.current_unit(subject.state)
            self.assertTrue(subject._observe_accepted_plan_range(
                source_base,
                accepted,
                {"unit": st.unit_key(source), "kind": "review_round"},
            ))
            self.assertEqual(drv.decide(subject.state).type, drv.A_RECONCILIATION)
            self.assertEqual(len(tasks.task_records(subject.state)), task_count)

        with tempfile.TemporaryDirectory(
            prefix="skeleton-final-close-"
        ) as workspace:
            _path, subject, _runner, _final = self._fixture(workspace)
            skeleton = subject._find_unit(st.UNIT_SKELETON, None)
            self._until(subject, lambda: skeleton["status"] == st.U_SEALED)
            skeleton_task = tasks.task_records(subject.state)[0]
            document = st.current_unit(subject.state)
            document["status"] = st.U_SEALED
            implementation = st.ensure_due_unit(subject.state)
            implementation["status"] = st.U_SEALED
            st.close_slice(subject.state, implementation)
            with mock.patch.object(
                ledgers, "generate"
            ), mock.patch.object(
                gitops, "commit_plain", return_value="close-sha"
            ) as commit:
                subject._advance_milestone_after_gate(implementation)
            commit.assert_called_once_with(workspace, "Close milestone")
            self.assertEqual(
                subject.state["milestone"]["status"], st.M_CLOSED
            )
            self.assertEqual(len(tasks.task_records(subject.state)), 1)
            self.assertNotEqual(
                skeleton_task["result"]["native_result"]["gate_commit"],
                "close-sha",
            )
            closing = [
                event for event in subject.state["events"]
                if event.get("message") == "Close milestone"
            ]
            self.assertEqual([event.get("unit") for event in closing], [None])

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
