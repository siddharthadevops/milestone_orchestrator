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
from orchestrator import pricing
from orchestrator import prompt_router
from orchestrator import runners
from orchestrator import session_calls
from orchestrator import state
from orchestrator import tasks
from orchestrator.tests.test_driver_mock import (
    init_state,
    make_config,
    prompt_response,
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


def _usage(seed):
    return {
        "input_tokens": seed * 10,
        "cached_input_tokens": seed,
        "output_tokens": seed * 2,
        "reasoning_output_tokens": seed,
        "total_tokens": seed * 12,
    }


def _accounted(step, duration_s, seed):
    value = dict(step)
    value["accounting"] = {
        "duration_s": duration_s,
        "token_usage": _usage(seed),
        "claude_cost_usd": seed / 100.0,
    }
    return value


class _AccountingRunner(runners.MockRunner):
    """MockRunner whose every physical call has distinct known accounting."""

    def __init__(self, script):
        self._accounting = [
            copy.deepcopy(item["accounting"]) for item in script
        ]
        self.physical_calls = []
        super().__init__(script)

    def call(self, family, prompt, workspace, **kwargs):
        result = super().call(family, prompt, workspace, **kwargs)
        accounting = self._accounting.pop(0)
        usage = accounting["token_usage"]
        model = kwargs.get("model")
        if family == "claude":
            cost_payload = {
                "total_cost_usd": accounting["claude_cost_usd"]
            }
        else:
            cost_payload = dict(usage, cache_write_input_tokens=0)
        result.duration_s = accounting["duration_s"]
        result.token_usage = copy.deepcopy(usage)
        result.cost_payloads = [copy.deepcopy(cost_payload)]
        self.physical_calls.append({
            "family": family,
            "model": model,
            "duration_s": accounting["duration_s"],
            "token_usage": copy.deepcopy(usage),
            "cost_payload": copy.deepcopy(cost_payload),
        })
        return result


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

    def _assert_physical_accounting(self, persisted, runner, unit_key):
        unit_view = next(
            item for item in state.summary(persisted)["units"]
            if item["unit"] == unit_key
        )
        expected_usage = runners.add_token_usage(*[
            item["token_usage"] for item in runner.physical_calls
        ])
        expected_cost = None
        cost_partial = False
        billing = persisted["config"].get("billing") or {}
        for item in runner.physical_calls:
            quote = pricing.quote(
                item["family"],
                item["model"],
                item["cost_payload"],
                billing=billing.get(item["family"]),
            )
            if quote.api_usd is None or quote.real_usd is None:
                cost_partial = True
            else:
                if expected_cost is None:
                    expected_cost = {"api_usd": 0.0, "real_usd": 0.0}
                expected_cost["api_usd"] += quote.api_usd
                expected_cost["real_usd"] += quote.real_usd

        self.assertEqual(tasks.task_records(persisted), [])
        self.assertEqual(unit_view["task_ids"], [])
        self.assertAlmostEqual(
            unit_view["work_duration_s"],
            sum(item["duration_s"] for item in runner.physical_calls),
        )
        self.assertEqual(unit_view["work_token_usage"], expected_usage)
        self.assertFalse(unit_view["work_token_usage_partial"])
        if expected_cost is None:
            self.assertIsNone(unit_view["work_cost"])
        else:
            self.assertAlmostEqual(
                unit_view["work_cost"]["api_usd"],
                expected_cost["api_usd"],
            )
            self.assertAlmostEqual(
                unit_view["work_cost"]["real_usd"],
                expected_cost["real_usd"],
            )
        self.assertEqual(unit_view["work_cost_partial"], cost_partial)
        summary = state.summary(persisted)
        self.assertAlmostEqual(
            summary["work_duration_s"], unit_view["work_duration_s"]
        )
        self.assertEqual(
            summary["work_token_usage"], unit_view["work_token_usage"]
        )
        self.assertEqual(summary["work_cost"], unit_view["work_cost"])

    @staticmethod
    def _event(persisted, event_type):
        return next(
            item for item in persisted["events"]
            if item["type"] == event_type
        )

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

    def test_internal_call_evidence_and_totals_survive_without_child_task_ids(self):
        accepted = skeleton_script()[0]
        blocked = prompt_response({
            "status": "blocked",
            "kind": contracts.KIND_DRAFT_SKELETON,
            "blocked_reason": "The operator must choose the public wording.",
        })
        with tempfile.TemporaryDirectory(
            prefix="reviewed-call-blocked-"
        ) as workspace:
            path = init_state(workspace, make_config())
            runner = _AccountingRunner([_accounted({
                "expect_kind": contracts.KIND_DRAFT_SKELETON,
                "response": blocked,
                "side_effect": accepted["side_effect"],
            }, 1.25, 1)])
            driver.Driver(path, runner=runner).step()
            persisted = state.load(path)
            incident = self._event(persisted, "worker_unaccepted")
            self.assertEqual(incident["kind"], contracts.KIND_DRAFT_SKELETON)
            self.assertEqual(incident["unit"], "skeleton")
            self.assertNotIn("task_id", incident)
            self.assertEqual(persisted["failure"]["type"], "worker_blocked")
            self._assert_physical_accounting(
                persisted, runner, "skeleton"
            )

        with tempfile.TemporaryDirectory(
            prefix="reviewed-call-malformed-"
        ) as workspace:
            path = init_state(workspace, make_config())
            runner = _AccountingRunner([
                _accounted({
                    "expect_kind": contracts.KIND_DRAFT_SKELETON,
                    "response": "not json",
                    "side_effect": accepted["side_effect"],
                }, 2.25, 2),
                _accounted({
                    "expect_kind": contracts.KIND_DRAFT_SKELETON,
                    "response": "still not json",
                }, 3.25, 3),
            ])
            driver.Driver(path, runner=runner).step()
            persisted = state.load(path)
            incident = self._event(persisted, "worker_malformed")
            self.assertTrue(incident["fatal"])
            self.assertEqual(incident["unit"], "skeleton")
            self.assertNotIn("task_id", incident)
            self.assertTrue(incident["raw_path"])
            self.assertTrue(incident["raw_path2"])
            self.assertEqual(persisted["failure"]["type"], "worker_protocol")
            self._assert_physical_accounting(
                persisted, runner, "skeleton"
            )

        with tempfile.TemporaryDirectory(
            prefix="reviewed-call-corrected-"
        ) as workspace:
            path = init_state(workspace, make_config())
            runner = _AccountingRunner([
                _accounted({
                    "expect_kind": contracts.KIND_DRAFT_SKELETON,
                    "response": "not json",
                    "side_effect": accepted["side_effect"],
                }, 4.25, 4),
                _accounted({
                    "expect_kind": contracts.KIND_DRAFT_SKELETON,
                    "response": accepted["response"],
                }, 5.25, 5),
            ])
            driver.Driver(path, runner=runner).step()
            persisted = state.load(path)
            unit = persisted["units"][0]
            incident = self._event(persisted, "worker_malformed")
            self.assertFalse(incident.get("fatal", False))
            self.assertTrue(incident["raw_path"])
            self.assertNotIn("task_id", incident)
            self.assertEqual(
                unit["draft"]["result"]["status"], "ok"
            )
            self.assertNotIn("task_id", unit["draft"])
            self._assert_physical_accounting(
                persisted, runner, "skeleton"
            )

        with tempfile.TemporaryDirectory(
            prefix="reviewed-call-reclassified-"
        ) as workspace:
            path = init_state(
                workspace, make_config(p3_reclassify_debt=True)
            )
            finding = report_finding("minor-wording")
            finding["severity"] = "P3"
            runner = _AccountingRunner([
                _accounted(accepted, 6.25, 6),
                _accounted({
                    "expect_kind": contracts.KIND_REVIEW_ROUND,
                    "expect_family": "codex",
                    "response": prompt_response({
                        "status": "ok",
                        "kind": contracts.KIND_REVIEW_ROUND,
                        "findings": [finding],
                    }),
                }, 7.25, 7),
                _accounted({
                    "expect_kind": contracts.KIND_RECLASSIFY,
                    "expect_family": "claude",
                    "response": prompt_response({
                        "status": "ok",
                        "kind": contracts.KIND_RECLASSIFY,
                        "drift_risk": "low",
                        "drift_damage": "low",
                        "reason": "The wording is local and self-revealing.",
                    }),
                }, 8.25, 8),
            ])
            subject = driver.Driver(path, runner=runner)
            for _ in range(20):
                subject.step()
                if any(
                    item["type"] == "reclassify_recorded"
                    for item in subject.state["events"]
                ):
                    break
            else:
                self.fail("reviewed finding was not reclassified")
            persisted = state.load(path)
            incident = self._event(persisted, "reclassify_recorded")
            self.assertEqual(incident["unit"], "skeleton")
            self.assertEqual(incident["finding_id"], "codex-minor-wording")
            self.assertTrue(incident["defer_ok"])
            self.assertNotIn("task_id", incident)
            self.assertNotIn("task_id", persisted["units"][0]["rounds"][0])
            self._assert_physical_accounting(
                persisted, runner, "skeleton"
            )

        with tempfile.TemporaryDirectory(
            prefix="reviewed-call-rethink-origin-"
        ) as workspace:
            path = self._implementation_path(workspace)
            runner = _AccountingRunner([_accounted({
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": _rethink(contracts.KIND_IMPLEMENT),
            }, 9.25, 9)])
            subject = driver.Driver(path, runner=runner)
            created = _created("accounted-origin", path, workspace)
            with mock.patch.object(
                brainstorming_milestone,
                "create_session",
                return_value=created,
            ):
                subject.step()
            persisted = state.load(path)
            origin = self._event(
                persisted, "brainstorming_origin_recorded"
            )
            self.assertEqual(origin["kind"], contracts.KIND_IMPLEMENT)
            self.assertEqual(origin["unit"], "slice_impl-01")
            self.assertTrue(origin["raw_path"])
            self.assertNotIn("task_id", origin)
            implementation = next(
                item for item in persisted["units"]
                if state.unit_key(item) == "slice_impl-01"
            )
            self.assertIsNone(implementation["draft"])
            self.assertEqual(
                implementation["brainstorming_wait"]["signal"]["problem"],
                dict(_rethink(contracts.KIND_IMPLEMENT))["problem"],
            )
            self._assert_physical_accounting(
                persisted, runner, "slice_impl-01"
            )

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
