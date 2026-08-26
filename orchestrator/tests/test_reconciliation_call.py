import copy
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import canonical_plan, contracts, driver, gitops
from orchestrator import plan_reconciliation, tasks
from orchestrator import runners
from orchestrator import state as st
from orchestrator import staffing


def _slice(slice_id):
    return {
        "id": slice_id,
        "title": "Slice %d" % slice_id,
        "intent": "Deliver slice %d." % slice_id,
        "producer_task_executor": {
            "draft_slice_note": "agent_call",
            "implement": "agent_call",
        },
    }


def _document(ids):
    return (
        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
        % json.dumps(
            {"slices": [_slice(value) for value in ids]},
            separators=(",", ":"),
        )
    )


class ReconciliationCallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="merge-repair-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = self.temp.name
        self.path = "docs/skeleton.md"
        self._git("init", "-q")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "Tests")
        self._write(".gitignore", "\n".join(gitops.ignore_lines()) + "\n")
        self._write(self.path, _document((1, 2, 3)))
        self.milestone_start = self._commit("milestone start")
        self._write("slice-1.txt", "done\n")
        self.slice_1_gate = self._commit("slice 1 gate")
        self._write("slice-2.txt", "done\n")
        self.slice_2_gate = self._commit("slice 2 gate")
        self.source_base = self.slice_2_gate
        self._git("config", "--local", gitops.BASELINE_MARK, "true")

        config = driver.load_config(None)
        driver.merge_config(config, {
            "git": {"enabled": True},
            "error_classifier": True,
            "infra_retry_backoff_s": [0, 0],
        })
        self.model_home = tempfile.TemporaryDirectory(
            prefix="merge-repair-models-"
        )
        self.addCleanup(self.model_home.cleanup)
        staffing.ensure_documents(self.model_home.name, config=config)
        state = st.new_state("goal", self.workspace, config)
        state["milestone"]["slices"] = copy.deepcopy(
            canonical_plan.validate_canonical_plan(
                _document((1, 2, 3))
            )["projection"]
        )
        state["units"] = [
            self._unit(st.UNIT_SKELETON, None, self.milestone_start),
            self._unit(st.UNIT_SLICE_DOC, 1, self.slice_1_gate),
            self._unit(st.UNIT_SLICE_IMPL, 1, self.slice_1_gate),
            self._unit(st.UNIT_SLICE_DOC, 2, self.slice_2_gate),
            self._unit(st.UNIT_SLICE_IMPL, 2, self.slice_2_gate),
            self._unit(st.UNIT_SLICE_DOC, 3, self.slice_2_gate),
            self._unit(st.UNIT_SLICE_IMPL, 3, self.slice_2_gate),
        ]
        st.append_event(
            state,
            "gate_commit",
            unit=st.UNIT_SKELETON,
            sha=self.milestone_start,
        )
        st.append_event(
            state,
            "verification",
            unit="slice_impl-02",
            status="passed",
            cadence="four_slice_checkpoint",
            ok=True,
            stable=True,
        )
        st.append_event(
            state, "slice_closed", unit="slice_impl-02", slice_id=2
        )

        self._write(self.path, _document((1, 3)))
        self.accepted = self._commit("accepted structural plan")
        state["milestone"][canonical_plan.ANCHOR_KEY] = {
            "path": self.path,
            "revision": self.accepted,
        }
        result = plan_reconciliation.observe_accepted_range(
            state,
            self.source_base,
            self.accepted,
            source={
                "executor": "agent_call",
                "job": "review_round@slice_impl",
                "material": "code",
                # Exercise the ordinary deleted-owner case. Slice 3 must
                # still become due after the source owner disappears.
                "unit": "slice_impl-02",
                "physical_attempt": 1,
            },
        )
        self.assertEqual(result["status"], "opened")
        self.state_path = driver.default_state_path(self.workspace)
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(
            os.path.join(os.path.dirname(self.state_path), "amendments.json"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write('{"amendments":[]}')
        st.save(self.state_path, state)

    def _git(self, *args):
        return subprocess.run(
            ("git",) + args,
            cwd=self.workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _write(self, relative, content):
        path = os.path.join(self.workspace, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def _commit(self, message):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD")

    @staticmethod
    def _unit(kind, slice_id, gate, status=st.U_SEALED):
        unit = st._new_unit(kind, slice_id)
        unit["status"] = status
        unit["gate_commit"] = None if gate is None else gate[:12]
        if kind == st.UNIT_SLICE_IMPL and status == st.U_SEALED:
            unit["closed_record"] = {"slice_id": slice_id}
        if kind == st.UNIT_SKELETON:
            unit["artifact"] = "docs/skeleton.md"
        return unit

    def _repair_from_boundary(self, ids=(1, 3), observe_handoff=None):
        def effect(_workspace):
            if observe_handoff is not None:
                persisted = st.load(self.state_path)
                record = persisted["milestone"][
                    canonical_plan.RECONCILIATION_KEY
                ]
                observe_handoff.append(copy.deepcopy(record.get("handoff")))
            self._git("reset", "--hard", self.slice_1_gate)
            self._write(self.path, _document(ids))
            self._write("repair.txt", "repaired\n")
            self._commit("LLM structural repair")

        return effect

    def _response(self, status="ok"):
        result = {
            "status": status,
            "kind": "merge_repair",
            "files_changed": [self.path, "repair.txt"],
            "questions": [
                {
                    "id": "guarantee_fit",
                    "answer": "The accepted reconciliation contract governs.",
                },
                {
                    "id": "cheapest_sufficient",
                    "answer": "One bounded repair call is the simplest option.",
                },
                {
                    "id": "rare_failure_posture",
                    "answer": "A failed repair stops for operator action.",
                },
            ],
        }
        if status == "blocked":
            result["blocked_reason"] = "The required repair cannot complete."
        return result

    def test_success_marks_before_dispatch_and_closes_one_account(self):
        seen = []
        state = st.load(self.state_path)
        retained = next(
            unit for unit in state["units"]
            if st.unit_key(unit) == "slice_impl-03"
        )
        retained["preserved_candidate"] = {
            "ref": "refs/orchestrator/stale-before-repair"
        }
        deleted_before_repair = next(
            unit for unit in state["units"]
            if st.unit_key(unit) == "slice_impl-02"
        )
        deleted_before_repair["preserved_candidate"] = {
            "ref": "refs/orchestrator/deleted-before-repair"
        }
        os.unlink(self.state_path)
        st.save_new(self.state_path, state)
        subject = driver.Driver(
            self.state_path,
            model_profiles_home=self.model_home.name,
            runner=runners.MockRunner([{
                "expect_kind": "merge_repair",
                "side_effect": self._repair_from_boundary(
                    observe_handoff=seen
                ),
                "response": self._response(),
            }]),
        )

        action, note = subject.step()

        self.assertEqual(action.type, driver.A_RECONCILIATION)
        self.assertIn("reconciled", note)
        self.assertEqual(len(subject.runner.calls), 1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["kind"], "merge_repair")
        self.assertNotIn(
            canonical_plan.RECONCILIATION_KEY,
            subject.state["milestone"],
        )
        final_head = gitops.head_full_sha(self.workspace)
        self.assertEqual(
            subject.state["milestone"][canonical_plan.ANCHOR_KEY],
            {"path": self.path, "revision": final_head},
        )
        closed = next(
            event for event in reversed(subject.state["events"])
            if event.get("type")
            == "accepted_range_reconciliation_closed"
        )
        self.assertEqual(closed["final_head"], final_head)
        self.assertEqual(closed["accepted_revision"], self.accepted)
        self.assertEqual(closed["final_account"]["requeue_slice_ids"], [3])
        self.assertTrue(closed["final_account"]["invalidated_revisions"])
        source_retired = next(
            event for event in subject.state["events"]
            if event.get("type") == "reconciliation_source_retired"
        )
        self.assertFalse(source_retired["owner_survives"])
        current = st.current_unit(subject.state)
        self.assertEqual(st.unit_key(current), "slice_impl-03")
        self.assertEqual(current["status"], st.U_PENDING)
        self.assertIsNone(current["gate_commit"])
        self.assertIsNone(current["closed_record"])
        self.assertNotIn("preserved_candidate", current)
        deleted = next(
            unit for unit in subject.state["units"]
            if st.unit_key(unit) == "slice_impl-02"
        )
        self.assertIsNone(deleted["closed_record"])
        self.assertNotIn("preserved_candidate", deleted)
        self.assertEqual(self._git("status", "--porcelain"), "")

    def test_run_continues_after_success_instead_of_returning_frozen(self):
        subject = driver.Driver(
            self.state_path,
            model_profiles_home=self.model_home.name,
            runner=runners.MockRunner([{
                "expect_kind": "merge_repair",
                "side_effect": self._repair_from_boundary(),
                "response": self._response(),
            }]),
        )

        self.assertEqual(subject.run(max_steps=1), 3)
        self.assertNotEqual(driver.decide(subject.state).type, driver.A_RECONCILIATION)

    def test_blocked_leaves_the_llm_worktree_and_fails_once(self):
        def leave_dirty(_workspace):
            self._write("llm-left.txt", "unfinished\n")

        subject = driver.Driver(
            self.state_path,
            model_profiles_home=self.model_home.name,
            runner=runners.MockRunner([{
                "expect_kind": "merge_repair",
                "side_effect": leave_dirty,
                "response": self._response("blocked"),
            }]),
        )

        action, note = subject.step()

        self.assertEqual(action.type, driver.A_RECONCILIATION)
        self.assertIn("run failed", note)
        self.assertEqual(len(subject.runner.calls), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.workspace, "llm-left.txt")))
        self.assertEqual(subject.state["failure"]["type"], "worker_blocked")
        self.assertIsNotNone(
            subject.state["milestone"][
                canonical_plan.RECONCILIATION_KEY
            ]["handoff"]
        )

    def test_invalid_reply_has_no_correction_classifier_or_retry(self):
        subject = driver.Driver(
            self.state_path,
            model_profiles_home=self.model_home.name,
            runner=runners.MockRunner([{
                "expect_kind": "merge_repair",
                "response": {"bad": True},
            }]),
        )

        with mock.patch.object(
            subject,
            "_classify_failure",
            side_effect=AssertionError("classifier must not run"),
        ):
            action, _note = subject.step()

        self.assertEqual(action.type, driver.A_RECONCILIATION)
        self.assertEqual(len(subject.runner.calls), 1)
        self.assertEqual(subject.state["failure"]["type"], "worker_protocol")

    def test_marked_reconciliation_never_dispatches_again(self):
        state = st.load(self.state_path)
        state["milestone"][canonical_plan.RECONCILIATION_KEY]["handoff"] = {
            "kind": "merge_repair",
            "at": "already",
        }
        st.save(self.state_path, state)
        with mock.patch.object(
            driver.Driver,
            "_pre_clean_pending_gap",
            side_effect=AssertionError("gap cleanup must remain frozen"),
        ), mock.patch.object(
            driver.Driver,
            "_consume_pending_gap",
            side_effect=AssertionError("gap routing must remain frozen"),
        ), mock.patch.object(
            driver.Driver,
            "_migrate_active_redoc_wave",
            side_effect=AssertionError("redoc migration must remain frozen"),
        ):
            subject = driver.Driver(
                self.state_path,
                model_profiles_home=self.model_home.name,
                runner=runners.MockRunner([]),
            )

        action, note = subject.step()

        self.assertEqual(action.type, driver.A_RECONCILIATION)
        self.assertIn("already dispatched", note)
        self.assertEqual(subject.runner.calls, [])

    def test_restart_does_not_materialize_the_provisional_plan(self):
        state = st.load(self.state_path)
        state["milestone"]["slices"] = (
            canonical_plan.validate_canonical_plan(
                _document((1, 9, 3))
            )["projection"]
        )
        deleted = next(
            unit for unit in state["units"]
            if st.unit_key(unit) == "slice_impl-02"
        )
        deleted["preserved_candidate"] = {
            "ref": "refs/orchestrator/parked-before-repair"
        }
        opened_before = sum(
            event.get("type") == "unit_opened" for event in state["events"]
        )
        os.unlink(self.state_path)
        st.save_new(self.state_path, state)

        subject = driver.Driver(
            self.state_path,
            model_profiles_home=self.model_home.name,
            runner=runners.MockRunner([]),
        )

        self.assertEqual(
            sum(
                event.get("type") == "unit_opened"
                for event in subject.state["events"]
            ),
            opened_before,
        )
        self.assertFalse(any(
            st.unit_key(unit) == "slice_doc-09"
            for unit in subject.state["units"]
        ))
        self.assertIsNone(subject.state["failure"])
        persisted_deleted = next(
            unit for unit in subject.state["units"]
            if st.unit_key(unit) == "slice_impl-02"
        )
        self.assertIn("preserved_candidate", persisted_deleted)

    def test_final_plan_can_replace_opening_wipe_with_no_wipe(self):
        record = copy.deepcopy(
            st.load(self.state_path)["milestone"][
                canonical_plan.RECONCILIATION_KEY
            ]
        )
        self._write(self.path, _document((1, 2, 3)))
        self._write("repair.txt", "accepted child\n")
        final_head = self._commit("LLM no-wipe final plan")

        result = plan_reconciliation.validate_final_state(
            st.load(self.state_path), record
        )

        self.assertEqual(result["final_head"], final_head)
        self.assertIsNone(result["final_account"]["wipe_boundary"])
        self.assertEqual(result["final_account"]["invalidated_units"], [])
        self.assertEqual(result["final_account"]["invalidated_revisions"], [])

    def test_later_reconciliation_does_not_resurrect_old_checkpoint(self):
        subject = driver.Driver(
            self.state_path,
            model_profiles_home=self.model_home.name,
            runner=runners.MockRunner([{
                "expect_kind": "merge_repair",
                "side_effect": self._repair_from_boundary(),
                "response": self._response(),
            }]),
        )
        subject.step()
        rebuilt = st.current_unit(subject.state)
        rebuilt["status"] = st.U_SEALED
        rebuilt["gate_commit"] = gitops.head_full_sha(self.workspace)[:12]
        rebuilt["closed_record"] = {"slice_id": 3}
        new_checkpoint = st.append_event(
            subject.state,
            "verification",
            unit="slice_impl-03",
            status="passed",
            cadence="four_slice_checkpoint",
            ok=True,
            stable=True,
        )
        st.append_event(
            subject.state,
            "slice_closed",
            unit="slice_impl-03",
            slice_id=3,
        )
        later_base = gitops.head_full_sha(self.workspace)
        self._write(self.path, _document((1,)))
        later_accepted = self._commit("later accepted plan")
        subject.state["milestone"][canonical_plan.ANCHOR_KEY] = {
            "path": self.path,
            "revision": later_accepted,
        }

        later = plan_reconciliation.observe_accepted_range(
            subject.state,
            later_base,
            later_accepted,
            source={
                "executor": "agent_call",
                "job": "review_round@slice_impl",
                "material": "code",
                "unit": "slice_impl-03",
            },
        )["reconciliation"]

        checkpoints = later["opening_account"]["checkpoint_invalidations"]
        self.assertEqual(
            [checkpoint["event_seq"] for checkpoint in checkpoints],
            [new_checkpoint["seq"]],
        )

    def test_surviving_source_task_is_retired_and_owner_runs_fresh(self):
        subject = driver.Driver(
            self.state_path,
            model_profiles_home=self.model_home.name,
            runner=runners.MockRunner([{
                "expect_kind": "merge_repair",
                "side_effect": self._repair_from_boundary(),
                "response": self._response(),
            }]),
        )
        source = next(
            unit for unit in subject.state["units"]
            if st.unit_key(unit) == "slice_impl-03"
        )
        source["status"] = st.U_ROUNDS
        source["closed_record"] = None
        record = subject.state["milestone"][
            canonical_plan.RECONCILIATION_KEY
        ]
        record["source"]["unit"] = st.unit_key(source)
        task = subject._admit_worker_task(
            source,
            contracts.KIND_REVIEW_ROUND,
            "Review the current implementation.",
            "codex",
        )
        record = subject.state["milestone"][
            canonical_plan.RECONCILIATION_KEY
        ]
        record["source"]["task_id"] = task["id"]
        st.append_event(
            subject.state,
            "worker_paused_for_plan_reconciliation",
            unit=st.unit_key(source),
            task_id=task["id"],
            kind=contracts.KIND_REVIEW_ROUND,
            family="codex",
            duration_s=2.0,
            token_usage=None,
            token_usage_partial=True,
            cost=None,
            cost_partial=True,
        )
        subject._save()

        subject.step()

        terminal = tasks.task_record(subject.state, task["id"])["result"]
        self.assertEqual(terminal["status"], "failure")
        self.assertEqual(terminal["duration_s"], 2.0)
        self.assertEqual(
            terminal["native_result"]["status"],
            "superseded_by_reconciliation",
        )
        rebuilt = next(
            unit for unit in subject.state["units"]
            if st.unit_key(unit) == "slice_impl-03"
        )
        self.assertEqual(rebuilt["status"], st.U_PENDING)
        self.assertNotIn("active_task", rebuilt)


if __name__ == "__main__":
    unittest.main()
