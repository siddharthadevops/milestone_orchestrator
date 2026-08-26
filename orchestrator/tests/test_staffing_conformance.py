"""Closing cross-surface proof for the Staffing Router milestone.

The focused suites remain the detailed authority for their own seams.  This
matrix composes their representative cases, adds the one creation/dispatch
boundary Slice 10 owns, and keeps the runtime inventory closed without
copying those fixtures into another test harness.
"""

import ast
import copy
import os
import pathlib
import types
import unittest
from unittest import mock

from orchestrator import brainstorming
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import service
from orchestrator import staffing
from orchestrator import task_api
from orchestrator.tests import test_staffing_api as api_cases
from orchestrator.tests import test_staffing_brainstorming_cutover as brainstorming_cases
from orchestrator.tests import test_staffing_driver_cutover as driver_cases
from orchestrator.tests import test_staffing_sessions as session_cases
from orchestrator.tests import test_staffing_standalone_cutover as standalone_cases


class StaffingConformanceTest(driver_cases.StaffingCutoverTestCase):
    """Five composition cells over the router's reachable consumers."""

    def _assert_existing_cases(self, *cases):
        """Run named lower-level authorities as one conformance cell."""
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

    @staticmethod
    def _answer(resolution):
        answer = resolution.answer
        return answer["agent"], answer["model"], answer["effort"]

    def _physical_implement_call(self, subject, answer, round_number, label):
        marker = {}
        subject.runner = runners.MockRunner([{
            "expect_kind": contracts.KIND_IMPLEMENT,
            "expect_family": answer[0],
            "response": driver_cases.ok(
                contracts.KIND_IMPLEMENT, files_changed=[]
            ),
            "side_effect": lambda _workspace: marker.update(
                subject._read_busy()
            ),
        }])
        subject._call(
            answer[0],
            "KIND: implement\nFAMILY: %s\nWORKSPACE: %s\n\n%s"
            % (answer[0], subject.workspace, label),
            contracts.KIND_IMPLEMENT,
            label,
            dispatch_resolver=subject._dispatch_for_role(
                "implement", round=round_number
            ),
        )
        self.assertEqual(
            (marker["family"], marker["model"], marker["effort"]),
            answer,
        )
        return marker

    def test_step_up_marker_and_live_edits_cross_the_dispatch_boundary(self):
        document = staffing.default_document_seed()
        document["name"] = "conformance-live"
        document["assignment"]["implement"] = {"1": 1}
        document["tuning"]["medium"]["1"]["implement"] = [1, 1]
        document["tuning"]["low"]["1"]["implement"] = [2, 1]
        document["rules"] = [{
            "type": "step_up", "role": "implement", "min_round": 2,
        }]
        path = self.bound_to(document, name="conformance-live")
        subject = self.driver_for(path)
        session = self.session_of(path)

        base = self._answer(staffing.resolve(
            self.home, session, "implement", round=1
        ))
        stepped = self._answer(staffing.resolve(
            self.home, session, "implement", round=2
        ))
        self.assertNotEqual(stepped, base)
        markers = [
            self._physical_implement_call(subject, base, 1, "base-rung"),
            self._physical_implement_call(subject, stepped, 2, "step-up"),
        ]

        staffing.edit_session(self.home, session, {"rigor": "low"})
        low = self._answer(staffing.resolve(
            self.home, session, "implement", round=1
        ))
        self.assertNotEqual(low, stepped)
        markers.append(
            self._physical_implement_call(subject, low, 1, "rigor-edit")
        )

        moved = staffing.load(self.home, document["name"])
        moved["assignment"]["implement"] = {"1": 2}
        staffing.save(self.home, moved)
        replaced = self._answer(staffing.resolve(
            self.home, session, "implement", round=1
        ))
        self.assertNotEqual(replaced, low)
        markers.append(self._physical_implement_call(
            subject, replaced, 1, "document-replacement"
        ))
        self.assertEqual(
            [(m["family"], m["model"], m["effort"]) for m in markers],
            [base, stepped, low, replaced],
        )

        self._assert_existing_cases(
            (
                session_cases.StaffingResolutionTest,
                "test_step_up_fires_from_its_round_and_saturates",
            ),
            (
                api_cases.StaffingSessionRoutes,
                "test_session_access_and_authorized_override_authors",
            ),
            (
                api_cases.StaffingResolveRoute,
                "test_session_and_document_edits_reach_the_next_resolution",
            ),
            (
                brainstorming_cases.BrainstormingCutoverTest,
                "test_a_completed_edit_reaches_the_next_call",
            ),
            (
                standalone_cases.DirectCallStaffingTest,
                "test_direct_agent_call_resolves_live_and_ignores_snapshot",
            ),
            (
                standalone_cases.GitAlignmentStaffingTest,
                "test_git_sync_resolves_live_after_ownership_checks",
            ),
        )

    def _create_split_brainstorming_session(self):
        workspace = os.path.join(self.tmp.name, "split-brainstorming")
        os.makedirs(workspace)
        staffing.ensure_documents(self.home)
        session = staffing.create_session(self.home, {
            "work_area": {"workspace_path": workspace},
            "families": list(brainstorming_cases.CONFIG["families_order"]),
            "document": staffing.DEFAULT_DOCUMENT_NAME,
            "rigor": "medium",
        })["id"]
        document = staffing.load(self.home, staffing.DEFAULT_DOCUMENT_NAME)
        document["assignment"]["brainstorm"] = {"1": 1, "2": 1}
        document["roles"]["brainstorm"] = {"distinct_families": True}
        staffing.save(self.home, document)

        target = os.path.join(workspace, "decision.md")
        pathlib.Path(target).write_bytes(b"initial target")
        body = {
            "request": {
                "workspace_path": workspace,
                "target_path": target,
                "request": "Choose the bounded compatible result.",
                "context": {"brief": "One decision."},
                "max_rounds": 1,
            },
            "participants": brainstorming_cases.llm_roster(),
            "closure_policy": "unanimity",
        }
        launch = lifecycle.GatedLaunch(
            process=types.SimpleNamespace(pid=999999, poll=lambda: None),
            release=mock.Mock(),
            abort=mock.Mock(),
        )
        family_read = staffing.session_seat_families
        with mock.patch.object(
            lifecycle, "_projected_seat_staffing", return_value={}
        ), mock.patch.object(
            staffing, "resolve",
            side_effect=AssertionError("creation performed a dispatch read"),
        ), mock.patch.object(
            staffing, "session_seat_families", wraps=family_read
        ) as read, mock.patch.object(lifecycle, "_track_child"):
            created = lifecycle.create_resolved_session(
                self.home,
                body,
                "milestone:conformance",
                {
                    "workspace_path": workspace,
                    "project": None,
                    "work_area": None,
                    "primary": None,
                    "additional": [],
                },
                copy.deepcopy(brainstorming_cases.CONFIG),
                launcher=lambda _home, _session_id: launch,
                owned_target_path=target,
                staffing_selection={"session": session},
            )
        read.assert_called_once()
        launch.release.assert_called_once_with()

        store = brainstorming.SessionStore(lifecycle.state_directory(self.home))
        record = lifecycle._record_by_id(self.home, created["id"])
        participants = store.read(created["id"]).state["run_config"][
            "participants"
        ]
        self.assertEqual(
            [seat["model_family"] for seat in participants],
            ["codex", "codex"],
        )

        subject = lifecycle._participant_execution(
            store,
            record,
            None,
            staffing_binding=lifecycle._record_staffing_binding(
                self.home, record, session
            ),
        )
        started = []
        for executor in subject.executors.values():
            executor.runner = brainstorming_cases._NoProviderRunner(started)
        with self.assertRaises(staffing.StaffingConditionError) as refused:
            coordination.BrainstormingCoordinator(
                store, subject
            ).run_next_turn(created["id"], record["execution_context"])
        self.assertEqual(
            refused.exception.code,
            staffing.DISTINCT_FAMILIES_UNSATISFIABLE,
        )
        self.assertEqual(started, [])
        self.assertEqual(
            (store.read_activity(created["id"]) or {}).get("events", []), []
        )

    def test_fallback_and_condition_placement_conforms_across_consumers(self):
        self._create_split_brainstorming_session()
        self._assert_existing_cases(
            (
                driver_cases.StoppingConditions,
                "test_the_marker_carries_the_fallback_note",
            ),
            (
                brainstorming_cases.BrainstormingCutoverTest,
                "test_activity_records_what_ran_and_the_default_fallback",
            ),
            (
                standalone_cases.DirectFallbackAndMarkerTest,
                "test_direct_fallback_conditions_and_marker_posture",
            ),
            (
                standalone_cases.GitAlignmentStaffingTest,
                "test_git_sync_resolves_live_after_ownership_checks",
            ),
            (
                api_cases.StaffingSessionRoutes,
                "test_session_create_read_and_live_condition_projection",
            ),
            (
                driver_cases.TheCycleReadAnswersWithoutDispatching,
                "test_a_split_it_cannot_honour_is_described_not_refused",
            ),
            (
                driver_cases.TheCycleReadAnswersWithoutDispatching,
                "test_no_family_available_leaves_no_answer_to_give",
            ),
            (
                session_cases.StaffingResolutionTest,
                "test_the_two_surfaced_conditions",
            ),
        )

    def test_resume_derivation_defaults_and_moves_on(self):
        self._assert_existing_cases(
            (
                driver_cases.RunBinding,
                "test_resume_derives_a_session_and_carries_nothing_else",
            ),
            (
                driver_cases.RunBinding,
                "test_an_unknown_profile_name_or_no_selection_gives_default",
            ),
            (
                driver_cases.RunBinding,
                "test_a_session_that_cannot_be_created_never_blocks_resume",
            ),
        )

    @staticmethod
    def _resolve_sites(module):
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        stack = []
        sites = []

        class Visitor(ast.NodeVisitor):
            def visit_ClassDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def visit_FunctionDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def visit_Call(self, node):
                target = node.func
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "resolve"
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "staffing"
                ):
                    sites.append(".".join(stack))
                self.generic_visit(node)

        Visitor().visit(tree)
        return sites

    def test_reachable_consumer_inventory_has_no_parallel_staffing_path(self):
        self.assertEqual({
            "driver": self._resolve_sites(drv),
            "brainstorming": self._resolve_sites(lifecycle),
            "direct": self._resolve_sites(task_api),
            "service": self._resolve_sites(service),
        }, {
            "driver": [
                "resolve_current_review_model.answer",
                "Driver._builders_desc",
                "Driver._staffing_resolution",
            ],
            "brainstorming": ["_SeatStaffing.__call__"],
            "direct": ["_dispatch"],
            "service": ["resolve_staffing_request", "sync_project_git"],
        })
        self._assert_existing_cases(
            (
                driver_cases.DriverCallsAskTheRouter,
                "test_every_driver_call_asks_the_router",
            ),
            (
                driver_cases.RetiredDispatchInputs,
                "test_profiles_acts_and_config_decide_nothing",
            ),
            (
                brainstorming_cases.BrainstormingCutoverTest,
                "test_every_automatic_seat_asks_the_router_for_its_own_index",
            ),
            (
                brainstorming_cases.BrainstormingCutoverTest,
                "test_the_classifier_seat_is_classify_one_and_only_when_called",
            ),
            (
                brainstorming_cases.BrainstormingCutoverTest,
                "test_slice_material_reaches_agent_call_and_brainstorming_production",
            ),
            (
                brainstorming_cases.BrainstormingCutoverTest,
                "test_retired_selectors_decide_nothing_for_a_router_session",
            ),
            (
                standalone_cases.DirectCallStaffingTest,
                "test_direct_agent_call_resolves_live_and_ignores_snapshot",
            ),
            (
                standalone_cases.GitAlignmentStaffingTest,
                "test_git_sync_resolves_live_after_ownership_checks",
            ),
        )


if __name__ == "__main__":
    unittest.main()
