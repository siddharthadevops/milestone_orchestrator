"""Gate-backed result and recovery coverage for reviewed work."""

import tempfile
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import gitops
from orchestrator import runners
from orchestrator import state as st
from orchestrator import tasks
from orchestrator.tests.test_driver_mock import (
    append_file,
    doc_script,
    git_subjects,
    init_state,
    make_config,
    ok,
    report,
    skeleton_script,
    step,
    write_file,
)


class ReviewedResultContractTest(unittest.TestCase):
    def _boundary_step(self, subject):
        lifecycle = subject.reviewed_work
        selected = subject._unit_by_key("skeleton")
        action = lifecycle.next_action(selected)
        with subject._exclusive():
            subject._assert_not_stale()
            try:
                outcome = lifecycle.execute(action)
                subject._save()
                return action, outcome
            finally:
                subject._clear_busy()

    def _drive_boundary(self, workspace, git_enabled=True):
        config = make_config(git={"enabled": git_enabled})
        path = init_state(workspace, config)
        runner = runners.MockRunner([
            skeleton_script()[0],
            step(
                contracts.KIND_REVIEW_ROUND,
                report(contracts.KIND_REVIEW_ROUND),
                family="codex",
            ),
            step(
                contracts.KIND_REVIEW_ROUND,
                report(contracts.KIND_REVIEW_ROUND),
                family="claude",
            ),
        ])
        subject = drv.Driver(path, runner=runner)
        result = None
        for _ in range(100):
            selected = subject._unit_by_key("skeleton")
            if selected["status"] == st.U_SEALED:
                return path, subject, runner, result
            self.assertIsNone(subject.reviewed_work.result(selected))
            _action, (_note, _sealed, _context, result) = (
                self._boundary_step(subject)
            )
        self.fail("reviewed boundary did not seal")

    @staticmethod
    def _implementation_script(cut):
        return [
            step(
                contracts.KIND_IMPLEMENT,
                ok(
                    contracts.KIND_IMPLEMENT,
                    files_changed=["calculator.py"],
                    implementation_cut=cut,
                ),
                family="codex",
                side_effect=write_file(
                    "calculator.py", "def add(a, b):\n    return a + b\n"
                ),
            ),
            step(
                contracts.KIND_REVIEW_ROUND,
                report(contracts.KIND_REVIEW_ROUND),
                family="codex",
            ),
            step(
                contracts.KIND_REVIEW_ROUND,
                report(contracts.KIND_REVIEW_ROUND),
                family="claude",
            ),
        ]

    def _implementation_ready_to_seal(self, workspace, cut):
        path = init_state(workspace, make_config())
        runner = runners.MockRunner(
            skeleton_script() + doc_script() + self._implementation_script(cut)
        )
        subject = drv.Driver(path, runner=runner)
        for _ in range(150):
            implementations = [
                unit for unit in subject.state["units"]
                if unit["kind"] == st.UNIT_SLICE_IMPL
            ]
            if (
                implementations
                and implementations[0]["status"] == st.U_PRE_SEAL_VERIFY
            ):
                return path, subject, runner, implementations[0]
            subject.step()
        self.fail("implementation did not reach sealing")

    def test_success_requires_current_seal_and_gate(self):
        with tempfile.TemporaryDirectory(prefix="orch-result-success-") as ws:
            _path, subject, _runner, result = self._drive_boundary(ws)
            unit = subject._unit_by_key("skeleton")
            self.assertIsNotNone(result)
            self.assertEqual(result, subject.reviewed_work.result(unit))
            self.assertEqual(result["status"], "success")

        with tempfile.TemporaryDirectory(prefix="orch-result-no-git-") as ws:
            _path, subject, _runner, result = self._drive_boundary(
                ws, git_enabled=False
            )
            self.assertIsNone(result)
            self.assertIsNone(
                subject.reviewed_work.result(
                    subject._unit_by_key("skeleton")
                )
            )

        with tempfile.TemporaryDirectory(prefix="orch-result-gate-fail-") as ws:
            path = init_state(ws, make_config())
            subject = drv.Driver(
                path, runner=runners.MockRunner(skeleton_script())
            )
            while (
                subject._unit_by_key("skeleton")["status"]
                != st.U_PRE_SEAL_VERIFY
            ):
                self._boundary_step(subject)
            with mock.patch.object(
                gitops,
                "finalize_gate",
                side_effect=gitops.GitError("simulated gate failure"),
            ):
                with self.assertRaises(drv.StopStep):
                    self._boundary_step(subject)
            self.assertIsNone(
                subject.reviewed_work.result(
                    subject._unit_by_key("skeleton")
                )
            )

    def test_native_result_preserves_producer_citations_cut_and_gate(self):
        cut = {
            "cut_scope": "complete arithmetic core",
            "remaining_scope": "wire the command interface",
        }
        with tempfile.TemporaryDirectory(prefix="orch-result-native-") as ws:
            _path, subject, _runner, unit = (
                self._implementation_ready_to_seal(ws, cut)
            )
            subject.step()
            result = subject.reviewed_work.result(unit)
            native = result["native_result"]
            self.assertEqual(
                set(native),
                {"production_result", "review_evidence", "gate_commit"},
            )
            self.assertEqual(
                native["production_result"]["implementation_cut"], cut
            )
            self.assertEqual(native["gate_commit"], unit["gate_commit"])
            self.assertEqual(native["review_evidence"], {
                "seal_attempt": unit["seals"][-1]["attempt"],
                "reviews": unit["seals"][-1]["reviews"],
                "verification_event_seq": unit["seals"][-1].get(
                    "verification_event_seq"
                ),
            })
            self.assertEqual(result, tasks.validate_result(result))

    def test_result_totals_match_origin_evidence_once(self):
        with tempfile.TemporaryDirectory(prefix="orch-result-account-") as ws:
            _path, subject, runner, result = self._drive_boundary(ws)
            unit = subject._unit_by_key("skeleton")
            accounting = st.reviewed_work_accounting(subject.state, unit)
            for field, expected in accounting.items():
                self.assertEqual(result[field], expected)
            self.assertAlmostEqual(
                result["duration_s"], len(runner.calls) * 0.01
            )
            self.assertEqual(tasks.task_records(subject.state), [])

    def test_recovery_keeps_wip_amend_and_final_review_history(self):
        with tempfile.TemporaryDirectory(prefix="orch-result-wip-") as ws:
            path = init_state(ws, make_config())
            runner = runners.MockRunner(skeleton_script())
            subject = drv.Driver(path, runner=runner)
            real_commit = gitops.commit_wip
            landed = []

            def commit_then_crash(workspace, message):
                landed.append(real_commit(workspace, message))
                raise RuntimeError("crash after WIP")

            with mock.patch.object(
                gitops, "commit_wip", side_effect=commit_then_crash
            ):
                with self.assertRaisesRegex(RuntimeError, "crash after WIP"):
                    subject.step()

            subject = drv.Driver(path, runner=runner)
            subject.step()
            while not any(
                event.get("type") == "amended"
                for event in subject.state["events"]
            ):
                subject.step()
            subject = drv.Driver(path, runner=runner)
            while subject._unit_by_key("skeleton")["status"] != st.U_SEALED:
                subject.step()

            unit = subject._unit_by_key("skeleton")
            result = subject.reviewed_work.result(unit)
            cited = set(result["native_result"]["review_evidence"]["reviews"])
            dirty = {
                round_["id"] for round_ in unit["rounds"]
                if round_["result"].get("findings")
            }
            self.assertTrue(landed)
            self.assertEqual(
                sum(
                    event.get("type") == "wip_commit"
                    and event.get("unit") == "skeleton"
                    for event in subject.state["events"]
                ),
                1,
            )
            self.assertTrue(any(
                event.get("type") == "amended"
                for event in subject.state["events"]
            ))
            self.assertTrue(cited)
            self.assertTrue(cited.isdisjoint(dirty))
            self.assertEqual(
                sum(kind == contracts.KIND_DRAFT_SKELETON
                    for _family, kind, _prompt in runner.calls),
                1,
            )

    def test_gate_crash_recovers_before_result_and_successor(self):
        cut = {
            "cut_scope": "complete arithmetic core",
            "remaining_scope": "wire the command interface",
        }
        with tempfile.TemporaryDirectory(prefix="orch-result-gate-crash-") as ws:
            path, subject, runner, unit = self._implementation_ready_to_seal(
                ws, cut
            )
            gate_message = subject._gate_message(unit)
            real_finalize = gitops.finalize_gate
            landed = []

            def finalize_then_crash(workspace, message):
                landed.append(real_finalize(workspace, message))
                raise RuntimeError("crash after gate")

            with mock.patch.object(
                gitops, "finalize_gate", side_effect=finalize_then_crash
            ):
                with self.assertRaisesRegex(RuntimeError, "crash after gate"):
                    subject.step()

            self.assertIsNone(subject.reviewed_work.result(unit))
            self.assertFalse(any(
                candidate.get("part") == "b"
                for candidate in subject.state["units"]
            ))
            observed_successor = []
            real_landed = gitops.landed_gate_sha

            def observe_recovery(workspace, message):
                observed_successor.append(any(
                    candidate.get("part") == "b"
                    for candidate in st.load(path)["units"]
                ))
                return real_landed(workspace, message)

            with mock.patch.object(
                gitops, "landed_gate_sha", side_effect=observe_recovery
            ), mock.patch.object(
                gitops,
                "finalize_gate",
                side_effect=AssertionError("gate must be adopted"),
            ):
                recovered = drv.Driver(path, runner=runners.MockRunner([]))

            recovered_unit = next(
                candidate for candidate in recovered.state["units"]
                if candidate["kind"] == st.UNIT_SLICE_IMPL
                and candidate.get("part") is None
            )
            result = recovered.reviewed_work.result(recovered_unit)
            self.assertEqual(observed_successor, [False])
            self.assertEqual(result["native_result"]["gate_commit"], landed[0])
            self.assertTrue(any(
                candidate.get("part") == "b"
                for candidate in recovered.state["units"]
            ))
            self.assertEqual(
                [sha for sha, subject_ in git_subjects(ws)
                 if subject_ == gate_message],
                landed,
            )
            self.assertEqual(
                sum(kind == contracts.KIND_IMPLEMENT
                    for _family, kind, _prompt in runner.calls),
                1,
            )

    def test_preserved_fixer_gate_wip_is_adopted_after_crash(self):
        with tempfile.TemporaryDirectory(
            prefix="orch-result-preserved-gate-"
        ) as ws:
            script = skeleton_script()

            def commit_fix(workspace):
                append_file(
                    "docs/skeleton.md",
                    "\n## Non-goals\n\nNo scientific functions.\n",
                )(workspace)
                gitops.commit_wip(workspace, "fixer-owned repair")

            next(
                item for item in script
                if item.get("expect_kind") == contracts.KIND_FIX_FINDINGS
            )["side_effect"] = commit_fix
            path = init_state(ws, make_config())
            subject = drv.Driver(path, runner=runners.MockRunner(script))
            unit = subject._unit_by_key("skeleton")
            while unit["status"] != st.U_PRE_SEAL_VERIFY:
                self._boundary_step(subject)

            self.assertTrue(any(
                event.get("type") == "fixer_commits_preserved"
                and event.get("unit") == "skeleton"
                for event in subject.state["events"]
            ))
            real_commit = gitops.commit_wip

            def gate_wip_then_crash(workspace, message):
                real_commit(workspace, message)
                raise RuntimeError("crash after temporary gate WIP")

            with mock.patch.object(
                gitops, "commit_wip", side_effect=gate_wip_then_crash
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "crash after temporary gate WIP"
                ):
                    self._boundary_step(subject)

            recovered = drv.Driver(path, runner=runners.MockRunner([]))
            recovered_unit = recovered._unit_by_key("skeleton")
            self.assertIsNotNone(recovered.reviewed_work.result(recovered_unit))
            subjects = [message for _sha, message in git_subjects(ws)]
            self.assertIn("fixer-owned repair", subjects)
            self.assertNotIn("wip: gate skeleton", subjects)
            self.assertEqual(
                subjects.count("Complete review of milestone skeleton"), 1
            )

    def test_slice_five_publishes_reviewed_task(self):
        self.assertEqual(
            [entry["id"] for entry in tasks.task_executor_catalogue()],
            ["agent_call", "brainstorming", "reviewed_task", "deep_task"],
        )


if __name__ == "__main__":
    unittest.main()
