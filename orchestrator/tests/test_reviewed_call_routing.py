"""Focused integration proof for reviewed-call routing and continuity."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming_milestone
from orchestrator import canonical_plan
from orchestrator import contracts
from orchestrator import driver
from orchestrator import plan_reconciliation
from orchestrator import prompt_router
from orchestrator import runners
from orchestrator import session_calls
from orchestrator import state
from orchestrator import tasks
from orchestrator.tests.test_driver_mock import (
    init_state,
    make_config,
    skeleton_script,
)
from orchestrator.tests.test_session_call_cutover import (
    RETHINK_PROBLEM,
    turn_values,
)
from orchestrator.tests.test_worker_tasks import (
    _author_ok,
    _created,
    _rethink,
    _worker_plan,
    _worker_skeleton,
    report_finding,
)


def _plan(slice_id):
    return {
        "slices": [{
            "id": slice_id,
            "title": "Reviewed %d" % slice_id,
            "intent": "Exercise reviewed call ownership.",
            "producer_task_executor": {
                "draft_slice_note": "agent_call",
                "implement": "agent_call",
            },
        }],
    }


def _skeleton(plan):
    return (
        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
        % json.dumps(plan, separators=(",", ":"))
    )


class ReviewedCallRoutingTest(unittest.TestCase):
    def _preparation_driver(self, workspace):
        os.makedirs(os.path.join(workspace, "docs"), exist_ok=True)
        path = init_state(
            workspace,
            make_config(git={"enabled": False}, docs_dir="docs"),
        )
        document = state.load(path)
        document["milestone"]["slices"] = copy.deepcopy(
            _worker_plan()["slices"]
        )
        skeleton = document["units"][0]
        skeleton.update({
            "status": state.U_SEALED,
            "artifact": "docs/skeleton.md",
        })
        note = state._new_unit(state.UNIT_SLICE_DOC, 1)
        note.update({
            "status": state.U_SEALED,
            "artifact": "docs/note.md",
        })
        implementation = state._new_unit(state.UNIT_SLICE_IMPL, 1)
        implementation["artifact"] = None
        document["units"] = [skeleton, note, implementation]
        for relative, body in (
            ("docs/skeleton.md", _worker_skeleton()),
            ("docs/note.md", "# Note\n"),
        ):
            with open(
                os.path.join(workspace, relative), "w", encoding="utf-8"
            ) as handle:
                handle.write(body)
        state.save(path, document)
        return driver.Driver(path), skeleton, note, implementation

    def _implementation_path(self, workspace):
        os.makedirs(os.path.join(workspace, "docs"), exist_ok=True)
        path = init_state(workspace, make_config(docs_dir="docs"))
        subprocess.run(
            ["git", "config", "user.email", "tests@example.invalid"],
            cwd=workspace, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Tests"],
            cwd=workspace, check=True,
        )
        for relative, body in (
            ("docs/skeleton.md", _worker_skeleton()),
            ("docs/note.md", "# Note\n"),
        ):
            with open(
                os.path.join(workspace, relative), "w", encoding="utf-8"
            ) as handle:
                handle.write(body)
        subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "reviewed fixture"],
            cwd=workspace, check=True,
        )
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        document = state.load(path)
        document["milestone"]["slices"] = copy.deepcopy(
            _worker_plan()["slices"]
        )
        skeleton = document["units"][0]
        skeleton.update({
            "status": state.U_SEALED,
            "artifact": "docs/skeleton.md",
            "gate_commit": revision[:12],
        })
        note = state._new_unit(state.UNIT_SLICE_DOC, 1)
        note.update({
            "status": state.U_SEALED,
            "artifact": "docs/note.md",
        })
        implementation = state._new_unit(state.UNIT_SLICE_IMPL, 1)
        document["units"] = [skeleton, note, implementation]
        state.append_event(
            document,
            "gate_commit",
            unit=state.UNIT_SKELETON,
            sha=revision,
        )
        canonical_plan.establish_current_plan(document, "docs/skeleton.md")
        state.save(path, document)
        return path

    def test_offered_matrix_routes_every_reviewed_attempt(self):
        with tempfile.TemporaryDirectory(
            prefix="reviewed-route-matrix-"
        ) as workspace:
            subject, skeleton, note, implementation = (
                self._preparation_driver(workspace)
            )
            calls = driver.ReviewedWorkCallPreparation(subject)
            original = prompt_router.resolve
            with mock.patch.object(
                prompt_router, "resolve", wraps=original
            ) as resolve:
                for unit, kind in (
                    (skeleton, contracts.KIND_DRAFT_SKELETON),
                    (note, contracts.KIND_DRAFT_SLICE_NOTE),
                    (implementation, contracts.KIND_IMPLEMENT),
                ):
                    calls.author(unit, kind, "author")(None)
                for unit in (skeleton, note, implementation):
                    for kind in (
                        contracts.KIND_REVIEW_ROUND,
                        contracts.KIND_FIX_FINDINGS,
                        contracts.KIND_DELTA_REVIEW,
                    ):
                        calls.judgment(
                            unit,
                            kind,
                            "judgment",
                            context=(
                                {"delta_base_revision": "base"}
                                if kind == contracts.KIND_DELTA_REVIEW
                                else {}
                            ),
                            queued_findings=(
                                [report_finding()]
                                if kind == contracts.KIND_FIX_FINDINGS
                                else None
                            ),
                        )(None)
                calls.judgment(
                    note,
                    contracts.KIND_RECLASSIFY,
                    "reclassify",
                    context={"finding": report_finding()},
                )(None)

                for job, artifact_type in (
                    ("draft_slice_note@slice_doc", None),
                    ("implement@slice_impl", None),
                    ("rethink", "document"),
                    ("rethink", "implementation"),
                ):
                    values = turn_values(workspace, "initial_position")
                    if job == "rethink":
                        for field in (
                            "target_path", "target_authority", "target_state"
                        ):
                            values.pop(field)
                        values.update({
                            "rethink_problem": RETHINK_PROBLEM,
                            "repository_authority": "Git commit %s" % (
                                "0" * 40
                            ),
                        })
                    session_calls.prepare(
                        workspace,
                        job=job,
                        material=(
                            "code"
                            if job == "implement@slice_impl"
                            or artifact_type == "implementation"
                            else "document"
                        ),
                        role="initial_position",
                        lead=True,
                        artifact_type=artifact_type,
                        values=values,
                        operator_amendments=[],
                    )

            observed = [
                (
                    item.kwargs["job"],
                    item.kwargs["executor"],
                    item.kwargs.get("artifact_type"),
                )
                for item in resolve.call_args_list
            ]
            expected_agent = {
                ("draft_skeleton@skeleton", "agent_call", None),
                ("draft_slice_note@slice_doc", "agent_call", None),
                ("implement@slice_impl", "agent_call", None),
                ("reclassify@doc", "agent_call", None),
            } | {
                ("%s@%s" % (kind, target), "agent_call", None)
                for target in ("skeleton", "slice_doc", "slice_impl")
                for kind in (
                    contracts.KIND_REVIEW_ROUND,
                    contracts.KIND_FIX_FINDINGS,
                    contracts.KIND_DELTA_REVIEW,
                )
            }
            expected_sessions = {
                ("draft_slice_note@slice_doc", "brainstorming", None),
                ("implement@slice_impl", "brainstorming", None),
                ("rethink", "brainstorming", "document"),
                ("rethink", "brainstorming", "implementation"),
            }
            self.assertEqual(set(observed), expected_agent | expected_sessions)
            self.assertEqual(len(observed), len(expected_agent | expected_sessions))

    def test_internal_agent_calls_create_evidence_without_child_tasks(self):
        with tempfile.TemporaryDirectory(
            prefix="reviewed-call-evidence-"
        ) as workspace:
            path = init_state(workspace, make_config())
            runner = runners.MockRunner(skeleton_script())
            subject = driver.Driver(path, runner=runner)
            for _ in range(100):
                if subject._unit_by_key("skeleton")["status"] == state.U_SEALED:
                    break
                subject.step()
            else:
                self.fail("reviewed skeleton did not seal")

            persisted = state.load(path)
            unit = persisted["units"][0]
            evidence = [unit["draft"]] + list(unit["rounds"])
            view = state.summary(persisted)
            self.assertEqual(tasks.task_records(persisted), [])
            self.assertTrue(evidence)
            self.assertTrue(all("task_id" not in item for item in evidence))
            self.assertEqual(view["units"][0]["task_ids"], [])
            self.assertAlmostEqual(
                view["units"][0]["work_duration_s"],
                sum(item["duration_s"] for item in evidence),
            )
            self.assertIsNone(view["units"][0]["work_token_usage"])
            self.assertTrue(view["units"][0]["work_token_usage_partial"])
            self.assertIsNone(view["units"][0]["work_cost"])
            self.assertTrue(view["units"][0]["work_cost_partial"])

    def test_rethink_success_reenters_surviving_origins_and_does_not_reenter_a_reconciled_out_origin(self):
        with tempfile.TemporaryDirectory(
            prefix="reviewed-rethink-survives-"
        ) as workspace:
            path = self._implementation_path(workspace)
            runner = runners.MockRunner([
                {"expect_kind": contracts.KIND_IMPLEMENT,
                 "response": _rethink(contracts.KIND_IMPLEMENT)},
                {"expect_kind": contracts.KIND_IMPLEMENT,
                 "response": _author_ok(
                     contracts.KIND_IMPLEMENT, files_changed=[]
                 )},
            ])
            subject = driver.Driver(path, runner=runner)
            created = _created("survives", path, workspace)
            with mock.patch.object(
                brainstorming_milestone,
                "create_session",
                return_value=created,
            ):
                subject.step()
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=workspace, check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            with mock.patch.object(
                brainstorming_milestone,
                "terminal_handoff",
                return_value={
                    "session_id": "survives",
                    "result": {"outcome": "success"},
                    "source_base_revision": revision,
                    "accepted_revision": revision,
                },
            ):
                subject.step()
            subject.step()
            survived = state.load(path)
            unit = next(
                item for item in survived["units"]
                if state.unit_key(item) == "slice_impl-01"
            )
            self.assertEqual(
                [kind for _family, kind, _prompt in runner.calls],
                [contracts.KIND_IMPLEMENT, contracts.KIND_IMPLEMENT],
            )
            self.assertIsNotNone(unit["draft"])
            self.assertNotIn("brainstorming_wait", unit)
            self.assertEqual(tasks.task_records(survived), [])

        with tempfile.TemporaryDirectory(
            prefix="reviewed-rethink-removed-"
        ) as workspace:
            path = self._implementation_path(workspace)
            runner = runners.MockRunner([{
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": _rethink(contracts.KIND_IMPLEMENT),
            }])
            subject = driver.Driver(path, runner=runner)
            created = _created("removed", path, workspace)
            with mock.patch.object(
                brainstorming_milestone,
                "create_session",
                return_value=created,
            ):
                subject.step()
            source_base = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=workspace, check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            with open(
                os.path.join(workspace, "docs/skeleton.md"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(_skeleton(_plan(2)))
            subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "accepted replacement plan"],
                cwd=workspace, check=True,
            )
            accepted = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=workspace, check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            canonical_plan.establish_current_plan(
                subject.state, "docs/skeleton.md"
            )
            subject._save()
            with mock.patch.object(
                brainstorming_milestone,
                "terminal_handoff",
                return_value={
                    "session_id": "removed",
                    "result": {"outcome": "success"},
                    "source_base_revision": source_base,
                    "accepted_revision": accepted,
                },
            ):
                action, _note = subject.step()
            self.assertEqual(action.type, driver.A_RECONCILIATION)
            record = copy.deepcopy(
                subject.state["milestone"][canonical_plan.RECONCILIATION_KEY]
            )
            subject._close_reconciliation(record, {
                "final_head": accepted,
                "final_plan": copy.deepcopy(record["accepted_plan"]),
                "projection": copy.deepcopy(
                    subject.state["milestone"]["slices"]
                ),
                "final_account": plan_reconciliation._final_account(
                    record, record["accepted_plan"]
                ),
            })
            next_action = driver.decide(subject.state)
            self.assertNotEqual(
                next_action.params.get("unit"), "slice_impl-01"
            )
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(tasks.task_records(subject.state), [])

    def test_rethink_failure_fails_origin_without_reopening(self):
        with tempfile.TemporaryDirectory(
            prefix="reviewed-rethink-failure-"
        ) as workspace:
            path = self._implementation_path(workspace)
            runner = runners.MockRunner([{
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": _rethink(contracts.KIND_IMPLEMENT),
            }])
            subject = driver.Driver(path, runner=runner)
            created = _created("failed", path, workspace)
            with mock.patch.object(
                brainstorming_milestone,
                "create_session",
                return_value=created,
            ):
                subject.step()
            with mock.patch.object(
                brainstorming_milestone,
                "terminal_handoff",
                return_value={
                    "session_id": "failed",
                    "result": {
                        "outcome": "failure",
                        "reason": "No agreement was reached.",
                    },
                },
            ):
                subject.step()
            failed = state.load(path)
            self.assertIsNotNone(failed["failure"])
            self.assertEqual(driver.decide(failed).type, driver.A_FAILED)
            self.assertEqual(tasks.task_records(failed), [])
            subject.step()
            self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
