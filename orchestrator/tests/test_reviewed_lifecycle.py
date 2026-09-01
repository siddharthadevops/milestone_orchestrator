"""Parity coverage for the reusable reviewed-work lifecycle boundary."""

import json
import os
import tempfile
import unittest

from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st
from orchestrator.tests.test_driver_mock import (
    GATE_MSG_SKELETON,
    git_subjects,
    init_state,
    make_config,
    prompt_response,
    skeleton_script,
    step,
)


def _round_evidence(unit):
    return [
        (
            round_["id"],
            round_["kind"],
            round_["family"],
            round_["result"].get("status"),
            tuple(
                finding["id"]
                for finding in round_["result"].get("findings") or []
            ),
        )
        for round_ in unit["rounds"]
    ]


def _seal_evidence(unit):
    return [
        (
            seal["attempt"],
            seal["passed"],
            seal["invalidated"],
            tuple(seal["reviews"]),
            seal.get("verification_event_seq"),
        )
        for seal in unit["seals"]
    ]


def _event_evidence_through_gate(state):
    evidence = []
    for event in state["events"]:
        if event["type"] == "canonical_plan_established":
            continue
        evidence.append(tuple(
            event.get(key)
            for key in (
                "type", "unit", "round", "kind", "findings", "status",
                "reason", "message", "reviews",
            )
        ))
        if event["type"] == "gate_commit" and event.get("unit") == "skeleton":
            break
    return evidence


class DefaultReviewedLifecycleParityTest(unittest.TestCase):
    def _drive_milestone_entry(self, path, runner):
        subject = drv.Driver(path, runner=runner)
        actions = []
        for _ in range(100):
            skeleton = subject._unit_by_key("skeleton")
            if skeleton["status"] == st.U_SEALED:
                return subject, actions
            action, _note = subject.step()
            actions.append(action.type)
        self.fail("milestone entry did not seal the selected production")

    def _drive_boundary(self, path, runner):
        subject = drv.Driver(path, runner=runner)
        lifecycle = subject.reviewed_work
        selected = subject._unit_by_key("skeleton")
        actions = []
        for _ in range(100):
            if selected["status"] == st.U_SEALED:
                return subject, actions
            action = lifecycle.next_action(selected)
            with subject._exclusive():
                subject._assert_not_stale()
                try:
                    _note, _sealed, _context, _result = lifecycle.execute(
                        action
                    )
                    subject._save()
                finally:
                    subject._clear_busy()
            actions.append(action.type)
        self.fail("reviewed-work boundary did not seal the selected production")

    def test_default_boundary_matches_milestone_lifecycle_golden(self):
        with tempfile.TemporaryDirectory(
            prefix="orch-reviewed-entry-"
        ) as entry_ws:
            entry_path = init_state(entry_ws, make_config())
            entry_runner = runners.MockRunner(skeleton_script())
            entry, entry_actions = self._drive_milestone_entry(
                entry_path, entry_runner
            )

            with tempfile.TemporaryDirectory(
                prefix="orch-reviewed-boundary-"
            ) as boundary_ws:
                boundary_path = init_state(boundary_ws, make_config())
                boundary_runner = runners.MockRunner(skeleton_script())
                boundary, boundary_actions = self._drive_boundary(
                    boundary_path, boundary_runner
                )

                entry_state = st.load(entry_path)
                boundary_state = st.load(boundary_path)
                entry_unit = entry._unit_by_key("skeleton")
                boundary_unit = boundary._unit_by_key("skeleton")

                self.assertEqual(boundary_actions, entry_actions)
                self.assertEqual(
                    [
                        (family, kind)
                        for family, kind, _prompt in boundary_runner.calls
                    ],
                    [
                        (family, kind)
                        for family, kind, _prompt in entry_runner.calls
                    ],
                )
                self.assertEqual(boundary_runner.script, [])
                self.assertEqual(entry_runner.script, [])
                self.assertEqual(
                    _round_evidence(boundary_unit),
                    _round_evidence(entry_unit),
                )
                self.assertEqual(
                    _seal_evidence(boundary_unit),
                    _seal_evidence(entry_unit),
                )
                self.assertEqual(
                    _event_evidence_through_gate(boundary_state),
                    _event_evidence_through_gate(entry_state),
                )
                self.assertNotIn(
                    "canonical_plan_anchor", boundary_state["milestone"]
                )
                self.assertIn(
                    "canonical_plan_anchor", entry_state["milestone"]
                )
                self.assertIsNone(boundary_state["failure"])
                self.assertEqual(boundary_unit["status"], st.U_SEALED)
                self.assertEqual(len(boundary_state["units"]), 1)
                self.assertFalse(any(
                    event["type"] == "unit_opened"
                    for event in boundary_state["events"]
                ))
                self.assertGreater(len(entry_state["units"]), 1)

                gate_by_subject = dict(
                    (subject, sha) for sha, subject in git_subjects(boundary_ws)
                )
                self.assertEqual(
                    boundary_unit["gate_commit"],
                    gate_by_subject[GATE_MSG_SKELETON],
                )

    def test_boundary_matches_failure_and_stop_outcomes(self):
        blocked_review = step(
            "review_round",
            prompt_response({
                "status": "blocked",
                "kind": "review_round",
                "blocked_reason": "operator input needed",
            }),
            family="codex",
        )

        failure_states = []
        for boundary_only in (False, True):
            with self.subTest(outcome="failure", boundary_only=boundary_only):
                with tempfile.TemporaryDirectory(
                    prefix="orch-reviewed-failure-"
                ) as workspace:
                    path = init_state(workspace, make_config())
                    subject = drv.Driver(
                        path,
                        runner=runners.MockRunner([
                            skeleton_script()[0], blocked_review,
                        ]),
                    )
                    for _ in range(3):
                        selected = subject._unit_by_key("skeleton")
                        action = (
                            subject.reviewed_work.next_action(selected)
                            if boundary_only else None
                        )
                        if boundary_only:
                            with subject._exclusive():
                                subject._assert_not_stale()
                                try:
                                    subject.reviewed_work.execute(action)
                                    subject._save()
                                except drv.StopStep:
                                    pass
                                finally:
                                    subject._clear_busy()
                        else:
                            subject.step()
                    failed = st.load(path)
                    self.assertEqual(
                        failed["failure"]["type"], "worker_blocked"
                    )
                    failure_states.append(failed)

        self.assertEqual(
            failure_states[0]["failure"]["reason"],
            failure_states[1]["failure"]["reason"],
        )
        failure_units = [state["units"][0] for state in failure_states]
        self.assertEqual(failure_units[0]["status"], failure_units[1]["status"])
        self.assertEqual(
            _round_evidence(failure_units[0]),
            _round_evidence(failure_units[1]),
        )

        with tempfile.TemporaryDirectory(
            prefix="orch-reviewed-stop-"
        ) as workspace:
            path = init_state(workspace, make_config())
            control_path = os.path.join(os.path.dirname(path), "control.json")
            with open(control_path, "w", encoding="utf-8") as handle:
                json.dump({"stop_after_seal": True}, handle)
            runner = runners.MockRunner(skeleton_script())
            subject = drv.Driver(path, runner=runner)

            self.assertEqual(subject.run(), 4)
            stopped = st.load(path)
            self.assertEqual(
                subject._unit_by_key("skeleton")["status"], st.U_SEALED
            )
            self.assertEqual(runner.script, [])
            self.assertEqual(
                [
                    event["units"]
                    for event in stopped["events"]
                    if event["type"] == "paused_after_seal"
                ],
                [["skeleton"]],
            )

    def test_boundary_executes_the_supplied_non_current_production(self):
        with tempfile.TemporaryDirectory(
            prefix="orch-reviewed-selected-"
        ) as workspace:
            path = init_state(workspace, make_config())
            state = st.load(path)
            state["milestone"]["slices"] = [{
                "id": 1,
                "title": "Selected production",
                "intent": "Exercise the supplied reviewed-work unit.",
                "producer_task_executor": {
                    "draft_slice_note": "agent_call",
                    "implement": "agent_call",
                },
            }]
            current = state["units"][0]
            st.transition_unit(
                state,
                current,
                st.U_PRE_REVIEW_VERIFY,
                reason="fixture leaves milestone-current production eligible",
            )
            selected = st.ensure_next_unit(state)
            st.transition_unit(
                state,
                selected,
                st.U_PRE_REVIEW_VERIFY,
                reason="fixture selects a non-current production",
            )
            st.save(path, state)

            subject = drv.Driver(path, runner=runners.MockRunner([]))
            lifecycle = subject.reviewed_work
            selected = subject._unit_by_key("slice_doc-01")
            action = lifecycle.next_action(selected)

            with subject._exclusive():
                subject._assert_not_stale()
                lifecycle.execute(action)
                subject._save()
                subject._clear_busy()

            self.assertEqual(action.type, drv.A_VERIFY)
            self.assertEqual(selected["status"], st.U_ROUNDS)
            self.assertEqual(
                subject._unit_by_key("skeleton")["status"],
                st.U_PRE_REVIEW_VERIFY,
            )


if __name__ == "__main__":
    unittest.main()
