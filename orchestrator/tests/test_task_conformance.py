"""Cross-surface compatibility and cardinality proof for TaskExecutors.

The detailed lifecycle branches remain owned by their focused test modules.
This matrix composes selected cases so the final slice detects drift between
those seams without copying their fixtures or creating a test-only runtime.
"""

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import canonical_plan
from orchestrator import driver as drv
from orchestrator import gitops
from orchestrator import runners
from orchestrator import state as st
from orchestrator import task_api
from orchestrator import tasks
from orchestrator.tests import test_brainstorming_slice_production as production_cases
from orchestrator.tests import test_brainstorming_tasks as brainstorming_cases
from orchestrator.tests import test_deep_task_documentation as deep_documentation_cases
from orchestrator.tests import test_deep_task_implementation as deep_implementation_cases
from orchestrator.tests import test_milestone_deep_slice_composition as deep_slice_cases
from orchestrator.tests import test_milestone_skeleton_composition as skeleton_cases
from orchestrator.tests import test_milestone_verification_cadence as cadence_cases
from orchestrator.tests import test_reviewed_call_routing as routing_cases
from orchestrator.tests import test_reviewed_complete_verification as verification_cases
from orchestrator.tests import test_reviewed_policy as policy_cases
from orchestrator.tests import test_task_activity as activity_cases
from orchestrator.tests import test_task_api as api_cases
from orchestrator.tests import test_tasks as task_cases
from orchestrator.tests import test_worker_tasks as worker_cases
from orchestrator.tests.test_driver_mock import ok
from orchestrator.tests.test_driver_mock import git_init_workspace


class TaskConformanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="task-conformance-")
        self.addCleanup(self.tmp.cleanup)

    def _assert_existing_cases(self, *cases):
        """Run the named lower-level authorities as one conformance cell."""
        suite = unittest.TestSuite(case(method) for case, method in cases)
        result = unittest.TestResult()
        suite.run(result)
        problems = result.failures + result.errors
        details = "\n\n".join(
            "%s\n%s" % (test.id(), traceback)
            for test, traceback in problems
        )
        if result.unexpectedSuccesses:
            details += "\nunexpected successes: %s" % [
                test.id() for test in result.unexpectedSuccesses
            ]
        if result.skipped:
            details += "\nskipped: %s" % [
                (test.id(), reason) for test, reason in result.skipped
            ]
        if result.expectedFailures:
            details += "\nexpected failures: %s" % [
                test.id() for test, _traceback in result.expectedFailures
            ]
        self.assertEqual(result.testsRun, len(cases))
        self.assertFalse(
            problems
            or result.unexpectedSuccesses
            or result.skipped
            or result.expectedFailures,
            details,
        )

    def _milestone(self, label, slice_plan, task_kind):
        workspace = os.path.join(self.tmp.name, label)
        os.makedirs(workspace, exist_ok=True)
        git_init_workspace(workspace)
        config = copy.deepcopy(drv.DEFAULT_CONFIG)
        config.update({
            "git": {"enabled": True},
            "verification": [],
            "guarantee_calibration": {"enabled": False},
            "p3_reclassify_debt": False,
            "error_classifier": False,
            "infra_retry_backoff_s": [],
        })
        path = drv.init_run("Prove old task compatibility.", workspace, config=config)
        docs = os.path.join(workspace, "docs")
        os.makedirs(docs, exist_ok=True)
        current_slice = copy.deepcopy(slice_plan)
        current_slice.setdefault("intent", "Exercise the task boundary.")
        current_slice.setdefault("producer_task_executor", {
            "draft_slice_note": "agent_call",
            "implement": "agent_call",
        })
        with open(
            os.path.join(docs, "skeleton.md"), "w", encoding="utf-8"
        ) as handle:
            handle.write(
                "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                % json.dumps({"slices": [current_slice]})
            )
        with open(
            os.path.join(docs, "note.md"), "w", encoding="utf-8"
        ) as handle:
            handle.write("# Note\n")
        gitops.ensure_repo(workspace)

        state = st.load(path)
        for key in (
            st.SKELETON_COMPOSITION_KEY,
            st.DEEP_SLICE_COMPOSITION_KEY,
            st.MILESTONE_VERIFICATION_CADENCE_KEY,
        ):
            state["milestone"].pop(key, None)
        canonical_plan.establish_current_plan(state, "docs/skeleton.md")
        state["units"][0].update({
            "status": st.U_SEALED,
            "artifact": "docs/skeleton.md",
        })
        note = st._new_unit(st.UNIT_SLICE_DOC, 1)
        implementation = st._new_unit(st.UNIT_SLICE_IMPL, 1)
        if task_kind == contracts.KIND_IMPLEMENT:
            note.update({"status": st.U_SEALED, "artifact": "docs/note.md"})
        state["units"].extend([note, implementation])
        st.save(path, state)
        return path

    def test_public_reviewed_and_deep_ordering_conforms(self):
        self._assert_existing_cases(
            (
                task_cases.TaskContractsTest,
                "test_catalogue_has_exact_builtins_and_self_description",
            ),
            (
                api_cases.TaskApiTest,
                "test_reviewed_task_resolves_before_admission_and_reaches_its_gate",
            ),
            (
                deep_documentation_cases.DeepTaskDocumentationTest,
                "test_one_public_documentation_child_owns_gate_before_implementation",
            ),
        )

    def test_milestone_hierarchy_commits_and_totals_conform(self):
        self._assert_existing_cases(
            (
                skeleton_cases.MilestoneSkeletonCompositionTest,
                "test_task_gate_result_anchors_the_same_commit_and_final_table",
            ),
            (
                deep_slice_cases.MilestoneDeepSliceCompositionTest,
                "test_slice_delivery_gates_documentation_and_parts",
            ),
            (
                deep_implementation_cases.DeepTaskImplementationTest,
                "test_final_uncut_part_completes_parent_with_child_owned_results_"
                "and_single_count_totals",
            ),
            (
                verification_cases.ReviewedCompleteVerificationTest,
                "test_unchanged_pass_and_no_suite_each_own_seal_and_gate",
            ),
            (
                cadence_cases.MilestoneVerificationCadenceTest,
                "test_five_completed_deep_tasks_admit_one_sibling_before_slice_six",
            ),
        )

    def test_recovery_rethink_prompt_and_size_boundaries_conform(self):
        self._assert_existing_cases(
            (
                deep_implementation_cases.DeepTaskImplementationTest,
                "test_part_admission_crash_windows_and_races_reuse_exact_child",
            ),
            (
                deep_slice_cases.MilestoneDeepSliceCompositionTest,
                "test_surviving_rethink_resumes_same_child_and_phase_without_"
                "redocumentation",
            ),
            (
                deep_slice_cases.MilestoneDeepSliceCompositionTest,
                "test_rollback_supersession_fails_open_tree_and_starts_new_"
                "documentation_first_deep_task",
            ),
            (
                routing_cases.ReviewedCallRoutingTest,
                "test_offered_matrix_routes_every_reviewed_attempt",
            ),
            (
                routing_cases.ReviewedCallRoutingTest,
                "test_internal_agent_calls_create_evidence_without_child_tasks",
            ),
            (
                policy_cases.ReviewedProducerPolicyTest,
                "test_brainstorming_implementation_refuses_size_control_before_freeze",
            ),
        )

    def test_pre_activation_and_current_cadence_conform(self):
        self._assert_existing_cases(
            (
                skeleton_cases.MilestoneSkeletonCompositionTest,
                "test_pre_activation_run_keeps_direct_skeleton_law",
            ),
            (
                deep_slice_cases.MilestoneDeepSliceCompositionTest,
                "test_pre_activation_run_keeps_direct_slice_law",
            ),
            (
                cadence_cases.MilestoneVerificationCadenceTest,
                "test_activation_replaces_only_new_runs_in_slice_cadence",
            ),
            (
                cadence_cases.MilestoneVerificationCadenceTest,
                "test_final_reuses_only_current_active_five_slice_verification",
            ),
        )

    def test_mixed_producer_paths_remain_independent_without_spillover(self):
        self._assert_existing_cases(
            (
                production_cases.BrainstormingSliceProductionTest,
                "test_brainstorming_note_waits_replaces_path_then_worker_implements",
            ),
            (
                production_cases.BrainstormingSliceProductionTest,
                "test_worker_note_then_target_free_brainstorming_implementation",
            ),
            (
                activity_cases.TaskActivityProjectionTests,
                "test_draft_and_implementation_tasks_render_separately",
            ),
        )

    def test_executor_cardinality_native_results_and_totals_conform(self):
        direct_snapshots = []

        class CardinalityApiCase(api_cases.TaskApiTest):
            def setUp(subject):
                super(CardinalityApiCase, subject).setUp()
                subject.requested_task_ids = []

            def request(subject, method, path, *args, **kwargs):
                response = super(CardinalityApiCase, subject).request(
                    method, path, *args, **kwargs
                )
                if method == "POST" and path == "/api/tasks" and response[0] == 201:
                    subject.requested_task_ids.append(response[1]["task"]["id"])
                return response

            def doCleanups(subject):
                direct_snapshots.append((
                    list(subject.requested_task_ids),
                    task_api.StandaloneTaskStore(subject.home).records(),
                ))
                return super(CardinalityApiCase, subject).doCleanups()

        self._assert_existing_cases(
            (
                CardinalityApiCase,
                "test_direct_worker_preserves_raw_request_result_and_accounting",
            ),
            (
                CardinalityApiCase,
                "test_direct_brainstorming_freezes_and_runs_static_order",
            ),
            (
                worker_cases.WorkerTaskCutoverTest,
                "test_worker_adapter_preserves_request_native_result_and_accounting",
            ),
            (
                production_cases.BrainstormingSliceProductionTest,
                "test_native_failure_preserves_accounting_and_resumes_with_"
                "a_distinct_task",
            ),
            (
                production_cases.BrainstormingSliceProductionTest,
                "test_success_accounting_has_one_existing_run_home",
            ),
            (
                task_cases.DurableTaskRecordsTest,
                "test_task_accounting_reuses_existing_homes_once",
            ),
            (
                task_cases.DurableTaskRecordsTest,
                "test_worker_task_id_survives_marker_and_recovery_records",
            ),
            (
                task_cases.DurableTaskRecordsTest,
                "test_classifier_and_cutoff_keep_known_task_id_without_marker",
            ),
            (
                task_cases.DurableTaskRecordsTest,
                "test_legacy_and_non_task_activity_stay_unattributed",
            ),
            (
                worker_cases.WorkerTaskCutoverTest,
                "test_worker_task_recovery_and_legacy_exclusions",
            ),
            (
                activity_cases.TaskActivityProjectionTests,
                "test_task_projection_does_not_reaggregate_or_infer_staffing",
            ),
        )
        self.assertEqual(len(direct_snapshots), 2)
        for requested_ids, records in direct_snapshots:
            self.assertEqual([record["id"] for record in records], requested_ids)
            self.assertEqual(len(records), len(requested_ids))
            self.assertTrue(all(record["result"] is not None for record in records))

    def test_out_of_root_claim_and_partial_effects_do_not_strengthen_success(self):
        path = self._milestone(
            "effect-worker-success",
            {"id": 1, "title": "effect boundary"},
            contracts.KIND_IMPLEMENT,
        )
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        workspace = driver.workspace
        output = os.path.join(workspace, "output")
        os.makedirs(output)
        outside_claim = os.path.join(workspace, "outside.txt")
        native = {"files_changed": ["outside.txt"]}
        runner = runners.MockRunner([{
            "expect_kind": contracts.KIND_IMPLEMENT,
            "response": ok(contracts.KIND_IMPLEMENT, **native),
        }])
        driver = drv.Driver(path, runner=runner)
        unit = st.current_unit(driver.state)
        admitted = driver._admit_worker_task(
            unit,
            contracts.KIND_IMPLEMENT,
            "KIND: implement\nFAMILY: codex\n\nApply the requested effect.",
            "codex",
            output_directory=output,
            author_coordinates=driver._author_coordinates(
                unit, contracts.KIND_IMPLEMENT
            ),
        )
        drv.Driver(path, runner=runner).step()
        state = st.load(path)
        terminal = tasks.task_records(state)[0]
        self.assertEqual(terminal["id"], admitted["id"])
        self.assertEqual(len(tasks.task_records(state)), 1)
        self.assertEqual(terminal["result"]["status"], "success")
        self.assertEqual(
            terminal["result"]["native_result"],
            ok(contracts.KIND_IMPLEMENT, **native)(runner.calls[0][2]),
        )
        self.assertNotIn("reason", terminal["result"])
        self.assertFalse(os.path.exists(outside_claim))
        self.assertNotIn("output_directory_violation", json.dumps(state))

        home = os.path.join(self.tmp.name, "direct-home")
        partial_path = os.path.join(output, "partial-worker.txt")
        store = task_api.StandaloneTaskStore(home)
        crashed = store.admit(
            task_cases.task_order(
                work_area={
                    "workspace_path": workspace,
                    "primary": workspace,
                    "additional": [],
                },
                reference_documents=[],
                output_directory=output,
            ),
            {"agent_call": {"agent": "codex"}},
            workspace,
        )

        class CrashingRunner:
            def call(_self, *_args, **_kwargs):
                with open(partial_path, "w", encoding="utf-8") as handle:
                    handle.write("survives the failed call\n")
                raise runners.ProviderResponseError(
                    "provider crashed", raw_texts=["partial native evidence"]
                )

        host = task_api.DirectTaskHost(
            home,
            store=store,
            runner_factory=lambda _config, _workspace: CrashingRunner(),
        )
        host._run_worker(crashed, lambda: copy.deepcopy(drv.DEFAULT_CONFIG))
        failed = store.record(crashed["id"])
        self.assertEqual(failed["result"]["status"], "failure")
        self.assertEqual(failed["result"]["native_result"],
                         "partial native evidence")
        self.assertTrue(os.path.isfile(partial_path))
        self.assertEqual(len(store.records()), 1)

        self._assert_existing_cases(
            (
                brainstorming_cases.BrainstormingTaskAdapterTest,
                "test_effect_completion_preserves_native_result_and_"
                "complete_accounting",
            ),
            (
                brainstorming_cases.BrainstormingTaskAdapterTest,
                "test_effect_failure_is_terminal_and_keeps_native_and_partial_effects",
            ),
            (
                production_cases.BrainstormingSliceProductionTest,
                "test_effect_failure_keeps_partial_work_and_implementation_successor",
            ),
        )


if __name__ == "__main__":
    unittest.main()
