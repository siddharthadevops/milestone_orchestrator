"""Focused proof for Git-anchored Brainstorming readiness and delivery."""

import copy
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import (
    brainstorming,
    brainstorming_coordination,
    brainstorming_milestone,
    canonical_plan,
)
from orchestrator import brainstorming_tasks, driver, tasks
from orchestrator import session_repository, state


def git(workspace, *args):
    return subprocess.run(
        ["git", *args], cwd=workspace, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


class RepositorySealTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orch-repo-seal-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = os.path.join(self.temp.name, "repo")
        os.makedirs(self.workspace)
        git(self.workspace, "init", "-q")
        git(self.workspace, "config", "user.email", "test@example.com")
        git(self.workspace, "config", "user.name", "Test")
        Path(self.workspace, "target.md").write_text(
            "initial\n", encoding="utf-8"
        )
        canonical = (
            "# Skeleton\n\n## Canonical slice plan\n```json\n"
            '{"slices":[{"id":1,"title":"One","intent":"Build one.",'
            '"producer_task_executor":{"draft_slice_note":"agent_call",'
            '"implement":"agent_call"}}]}\n```\n'
        )
        Path(self.workspace, "skeleton.md").write_text(
            canonical, encoding="utf-8"
        )
        Path(self.workspace, "docs").mkdir()
        Path(self.workspace, "docs", "skeleton.md").write_text(
            canonical, encoding="utf-8"
        )
        git(self.workspace, "add", "target.md", "skeleton.md", "docs/skeleton.md")
        git(self.workspace, "commit", "-qm", "baseline")
        self.base = git(self.workspace, "rev-parse", "HEAD")
        self.amendments = os.path.join(self.temp.name, "amendments.json")
        Path(self.amendments).write_text(
            '{"amendments":[]}', encoding="utf-8"
        )
        self.store = brainstorming.SessionStore(
            os.path.join(self.temp.name, "state")
        )
        self.participants = [
            {
                "id": "lead", "role": "initial_position",
                "delivery": "llm", "executor_ref": "lead-executor",
                "model_family": "codex",
            },
            {
                "id": "contrary", "role": "contrary_position",
                "delivery": "llm", "executor_ref": "contrary-executor",
                "model_family": "codex",
            },
            {
                "id": "dante", "role": "common_sense",
                "delivery": "external", "external_ref": "narrator",
            },
        ]

    def request(self, max_rounds=2):
        return {
            "workspace_path": self.workspace,
            "target_path": "target.md",
            "request": "Resolve the focused issue.",
            "context": {
                "brief": "Resolve the focused issue.",
                "source_payload": {
                    "session_charge": {
                        "job": "implement@slice_impl",
                        "prompt_set": "default",
                        "values": {},
                        "amendments_path": self.amendments,
                        "accepted_amendments": [],
                        "repository": {
                            "state_path": os.path.join(
                                self.workspace, "state.json"
                            ),
                            "skeleton_path": "skeleton.md",
                            "pre_session_commit": self.base,
                        }
                    }
                },
            },
            "max_rounds": max_rounds,
        }

    def running(self, max_rounds=2, closure_policy="unanimity"):
        created = self.store.create(
            "session",
            self.request(max_rounds),
            brainstorming.resolve_run_config(
                self.participants, closure_policy, self.participants
            ),
            self.participants,
        )
        running = self.store.transition(
            "session", created.revision, "running"
        )
        return self.store.initialize_repository_coordination(
            "session", running.revision, self.base
        )

    def append(self, snapshot, participant, revision, ready):
        return self.store.record_repository_turn(
            "session",
            snapshot.revision,
            participant,
            "%s turn" % participant,
            revision,
            ready,
        )

    def test_problem_only_origin_preserves_exact_text(self):
        problem = "  The governing design contradicts persistence.  "
        checked = brainstorming_milestone.validate_origin_signal(
            {"status": "need_rethink", "problem": problem},
            "implement",
        )
        self.assertEqual(checked, {"problem": problem})
        for retired in ("kind", "finding", "target_path"):
            with self.subTest(retired=retired), self.assertRaises(
                brainstorming_milestone.AdapterError
            ):
                brainstorming_milestone.validate_origin_signal(
                    {
                        "status": "need_rethink",
                        "problem": problem,
                        retired: "retired",
                    },
                    "implement",
                )

    def test_rethink_craft_follows_origin_unit_kind(self):
        subject = object.__new__(driver.Driver)
        self.assertEqual(
            subject._rethink_artifact_type({"kind": state.UNIT_SKELETON}),
            "document",
        )
        self.assertEqual(
            subject._rethink_artifact_type({"kind": state.UNIT_SLICE_DOC}),
            "document",
        )
        self.assertEqual(
            subject._rethink_artifact_type({"kind": state.UNIT_SLICE_IMPL}),
            "implementation",
        )

    def test_milestone_adapter_launches_target_free_exact_problem(self):
        problem = "The design requires persistence without database access."
        charge = {
            "job": "rethink",
            "prompt_set": "default",
            "values": {"rethink_problem": problem},
            "amendments_path": self.amendments,
            "accepted_amendments": [],
            "artifact_type": "implementation",
            "repository": {
                "state_path": os.path.join(self.workspace, "state.json"),
                "skeleton_path": "skeleton.md",
                "pre_session_commit": self.base,
            },
        }
        with mock.patch.object(
            brainstorming_milestone,
            "_launch_repository_session",
            return_value={"id": "session"},
        ) as launch:
            created = brainstorming_milestone.create_session(
                {"workspace": self.workspace},
                {},
                "slice_impl-01",
                {"problem": problem},
                ["skeleton.md", "target.md"],
                charge,
            )
        self.assertEqual(created, {"id": "session"})
        body = launch.call_args.args[3]
        request = body["request"]
        self.assertNotIn("target_path", request)
        self.assertNotIn("deliver_chat", request)
        self.assertEqual(
            set(request["context"]["source_payload"]), {"session_charge"}
        )
        self.assertEqual(
            request["context"]["source_payload"]["session_charge"]
            ["values"]["rethink_problem"],
            problem,
        )
        self.assertTrue(request["request"].endswith(problem))

    def test_repository_initialization_writes_no_target_snapshot(self):
        with mock.patch.object(
            self.store,
            "_write_target_revision",
            side_effect=AssertionError("target snapshot was written"),
        ):
            snapshot = self.running()
        self.assertEqual(
            snapshot.state["recovery_baseline_revision"], self.base
        )
        self.assertIsNone(snapshot.state["accepted_target_revision"])

    def test_repository_seal_waits_for_questioner_and_is_atomic(self):
        snapshot = self.running()
        snapshot = self.append(snapshot, "lead", self.base, True)
        snapshot = self.append(snapshot, "contrary", self.base, True)
        self.assertEqual(snapshot.state["status"], "running")
        self.assertEqual(snapshot.state["rounds_used"], 0)

        snapshot = self.append(snapshot, "dante", self.base, False)
        self.assertEqual(snapshot.state["status"], "running")
        self.assertEqual(snapshot.state["rounds_used"], 1)

        snapshot = self.append(snapshot, "lead", self.base, True)
        snapshot = self.append(snapshot, "contrary", self.base, True)
        sealed = self.append(snapshot, "dante", self.base, True)

        self.assertEqual(sealed.state["status"], "success")
        self.assertEqual(sealed.state["rounds_used"], 2)
        self.assertEqual(
            [item["status"] for item in sealed.state["history"]],
            ["created", "running", "success"],
        )
        self.assertEqual(sealed.state["transcript_events"], [])

    def test_pre_version_repository_session_keeps_legacy_agreement(self):
        config = brainstorming.resolve_run_config(
            self.participants, "unanimity", self.participants
        )
        config.pop("agreement_version")
        created = brainstorming.new_session_state(
            self.request(), config,
            os.path.join(self.temp.name, "legacy", "chat.md"),
        )
        running = brainstorming.transition_session(created, "running")
        current = brainstorming.initialize_repository_coordination_state(
            running, self.base
        )
        current = brainstorming.repository_completed_turn_successor(
            current, "lead", "lead turn", self.base, True
        )
        current = brainstorming.repository_completed_turn_successor(
            current, "contrary", "contrary turn", self.base, True
        )
        terminal = brainstorming.repository_completed_turn_successor(
            current, "dante", "dante question", self.base, False
        )

        self.assertEqual(terminal["status"], "success")
        self.assertNotIn("agreement_version", terminal["run_config"])
        self.assertEqual(
            [item["id"] for item in brainstorming.closure_voters(config)],
            ["lead", "contrary"],
        )

    def test_new_revision_invalidates_every_prior_readiness(self):
        snapshot = self.running()
        snapshot = self.append(snapshot, "lead", self.base, True)
        Path(self.workspace, "target.md").write_text(
            "changed\n", encoding="utf-8"
        )
        git(self.workspace, "add", "target.md")
        git(self.workspace, "commit", "-qm", "new turn")
        changed = git(self.workspace, "rev-parse", "HEAD")
        snapshot = self.store.advance_repository_revision(
            "session", snapshot.revision, changed
        )
        self.assertEqual(len(snapshot.state["completed_turns"]), 1)
        self.assertFalse(brainstorming.repository_positions_ready(snapshot.state))

        snapshot = self.append(snapshot, "contrary", changed, True)
        snapshot = self.append(snapshot, "dante", changed, False)
        self.assertEqual(snapshot.state["status"], "running")

        snapshot = self.append(snapshot, "lead", changed, True)
        snapshot = self.append(snapshot, "contrary", changed, True)
        sealed = self.append(snapshot, "dante", changed, True)
        self.assertEqual(sealed.state["status"], "success")
        self.assertEqual(sealed.state["accepted_target_revision"], changed)

    def test_ready_false_withdraws_same_revision_readiness(self):
        snapshot = self.running()
        snapshot = self.append(snapshot, "lead", self.base, True)
        snapshot = self.append(snapshot, "contrary", self.base, False)
        snapshot = self.append(snapshot, "dante", self.base, False)
        snapshot = self.append(snapshot, "lead", self.base, False)
        snapshot = self.append(snapshot, "contrary", self.base, True)
        snapshot = self.append(snapshot, "dante", self.base, False)
        self.assertEqual(snapshot.state["status"], "waiting")
        self.assertFalse(brainstorming.repository_positions_ready(snapshot.state))

    def test_final_unready_pass_waits_open(self):
        snapshot = self.running(max_rounds=1)
        snapshot = self.append(snapshot, "lead", self.base, False)
        snapshot = self.append(snapshot, "contrary", self.base, True)
        waiting = self.append(snapshot, "dante", self.base, False)
        self.assertEqual(waiting.state["status"], "waiting")
        self.assertEqual(waiting.state["transcript_events"], [])
        self.assertNotIn("result", waiting.state)

    def test_add_rounds_racing_repository_turn_preserves_completed_work(self):
        self.running(max_rounds=2)

        class Execution:
            def exchange_prepared_quiescent(_execution, *args, **kwargs):
                result = mock.Mock(
                    repository_turn={"revision": self.base}
                )
                return (
                    {"markdown": "completed lead turn", "ready": False},
                    result,
                )

        coordinator = brainstorming_coordination.BrainstormingCoordinator(
            self.store,
            Execution(),
            turn_preparer=lambda *args: None,
        )
        record_repository_turn = self.store.record_repository_turn
        raced = False

        def accept_after_extension(*args, **kwargs):
            nonlocal raced
            if not raced:
                raced = True
                self.store.extend_rounds("session", 3)
            return record_repository_turn(*args, **kwargs)

        with mock.patch.object(
            self.store,
            "record_repository_turn",
            side_effect=accept_after_extension,
        ):
            accepted = coordinator.run_next_turn("session", {})

        self.assertTrue(raced)
        self.assertEqual(accepted.state["status"], "running")
        self.assertEqual(brainstorming.effective_max_rounds(accepted.state), 3)
        self.assertEqual(
            accepted.state["completed_turns"],
            [
                {
                    "participant_id": "lead",
                    "round": 1,
                    "markdown": "completed lead turn",
                    "target_revision": self.base,
                    "ready": False,
                }
            ],
        )
        self.assertIsNone(self.store.read_turn_attempt("session"))
        self.assertNotIn("failure_origin", accepted.state)

    def test_add_rounds_racing_read_only_recovery_preserves_session(self):
        self.running(max_rounds=2)

        class Execution:
            def exchange_prepared_quiescent(_execution, *args, **kwargs):
                error = session_repository.ReadOnlyTurnInvalidated(
                    "read-only repository mutation restored"
                )
                error.repository_turn = {"revision": self.base}
                raise error

        coordinator = brainstorming_coordination.BrainstormingCoordinator(
            self.store,
            Execution(),
            turn_preparer=lambda *args: None,
        )
        advance_repository_revision = self.store.advance_repository_revision
        raced = False

        def recover_after_extension(*args, **kwargs):
            nonlocal raced
            if not raced:
                raced = True
                self.store.extend_rounds("session", 3)
            return advance_repository_revision(*args, **kwargs)

        with mock.patch.object(
            self.store,
            "advance_repository_revision",
            side_effect=recover_after_extension,
        ):
            recovered = coordinator.run_next_turn("session", {})

        self.assertTrue(raced)
        self.assertEqual(recovered.state["status"], "running")
        self.assertEqual(
            brainstorming.effective_max_rounds(recovered.state), 3
        )
        self.assertEqual(recovered.state["accepted_target_revision"], self.base)
        self.assertEqual(recovered.state["completed_turns"], [])
        self.assertIsNone(self.store.read_turn_attempt("session"))
        self.assertNotIn("failure_origin", recovered.state)

    def test_repository_readiness_honors_majority_policy(self):
        snapshot = self.running(closure_policy="majority")
        snapshot = self.append(snapshot, "lead", self.base, True)
        snapshot = self.append(snapshot, "contrary", self.base, False)
        sealed = self.append(snapshot, "dante", self.base, True)

        self.assertEqual(sealed.state["status"], "success")

    def test_majority_cannot_close_over_an_unready_initial_position(self):
        snapshot = self.running(max_rounds=1, closure_policy="majority")
        snapshot = self.append(snapshot, "lead", self.base, False)
        snapshot = self.append(snapshot, "contrary", self.base, True)
        failed = self.append(snapshot, "dante", self.base, True)

        self.assertEqual(failed.state["status"], "waiting")

    def test_terminal_handoff_is_exact_repository_range(self):
        snapshot = self.running()
        snapshot = self.append(snapshot, "lead", self.base, True)
        snapshot = self.append(snapshot, "contrary", self.base, True)
        sealed = self.append(snapshot, "dante", self.base, True)
        projection = {
            "state": copy.deepcopy(sealed.state),
            "work_duration_s": 0.3,
        }
        with mock.patch.object(
            brainstorming_milestone,
            "inspect_session",
            return_value=projection,
        ):
            handoff = brainstorming_milestone.terminal_handoff(
                {"workspace": self.workspace}, "session"
            )
        self.assertEqual(handoff["source_base_revision"], self.base)
        self.assertEqual(handoff["accepted_revision"], self.base)
        self.assertNotIn("accepted_target_revision", handoff)
        self.assertNotIn("retained_target", handoff)

    def test_repository_producer_finishes_without_effect(self):
        snapshot = self.running()
        snapshot = self.append(snapshot, "lead", self.base, True)
        snapshot = self.append(snapshot, "contrary", self.base, True)
        sealed = self.append(snapshot, "dante", self.base, True)
        charge = sealed.state["request"]["context"]["source_payload"][
            "session_charge"
        ]
        request = {
            "work_area": {
                "workspace_path": self.workspace,
                "primary": self.workspace,
                "additional": [],
            },
            "request": "Implement the admitted slice.",
            "context": {
                "task_kind": "implement",
                "author_coordinates": {"slice_note_path": "target.md"},
                "session_charge": charge,
            },
            "reference_documents": ["target.md"],
        }
        plan = {
            "id": 1,
            "title": "One",
            "intent": "Build one bounded slice.",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "brainstorming"},
            },
        }
        task_state = {"tasks": []}
        record = brainstorming_tasks.admit_task(
            task_state,
            tasks.producer_order(plan, "implement", request),
            driver.load_config(None),
            self.workspace,
            staffing_selection={"session": None},
        )
        projection = {
            "state": copy.deepcopy(sealed.state),
            "work_duration_s": 0.3,
            "work_token_usage": None,
            "work_token_usage_partial": True,
            "work_cost": None,
            "work_cost_partial": True,
        }
        effect = mock.Mock(side_effect=AssertionError("effect call reached"))
        with mock.patch.object(
            brainstorming_tasks.lifecycle,
            "inspect_session",
            return_value=projection,
        ):
            completed = brainstorming_tasks.finish_task(
                task_state,
                record["id"],
                self.temp.name,
                "session",
                effect,
            )
        self.assertEqual(completed["result"]["status"], "success")
        self.assertEqual(
            completed["result"]["native_result"]["source_base_revision"],
            self.base,
        )
        effect.assert_not_called()

    def test_repository_note_handoff_uses_planned_path_at_b(self):
        record = {
            "order": {
                "task_executor": "brainstorming",
                "request": {
                    "work_area": {
                        "workspace_path": self.workspace,
                        "primary": self.workspace,
                        "additional": [],
                    },
                    "request": "Draft the planned note.",
                    "context": {
                        "planned_slice_note_path": "target.md",
                        "session_charge": {"repository": {}},
                    },
                    "reference_documents": [],
                },
            },
            "result": {
                "status": "success",
                "native_result": {"accepted_revision": self.base},
            },
        }
        unit = {}
        self.assertEqual(
            brainstorming_tasks.record_slice_note_handoff(
                unit, record, "target.md"
            ),
            "target.md",
        )
        self.assertEqual(unit["artifact"], "target.md")

    def test_repository_rethink_reenters_fresh_without_application(self):
        state_path = driver.init_run(
            "Resolve one focused issue.",
            self.workspace,
            config=driver.load_config(None),
        )
        document = state.load(state_path)
        canonical_plan.establish_current_plan(document, "docs/skeleton.md")
        unit = state.current_unit(document)
        unit["implementation_attempt_snapshot"] = {"tree": "stale"}
        unit["brainstorming_wait"] = {
            "session_id": "session",
            "signal": {
                "status": "need_rethink",
                "problem": "The governing design contradicts persistence.",
            },
            "origin": {
                "unit": state.unit_key(unit),
                "kind": "implement",
                "family": "codex",
            },
        }
        state.save(state_path, document)
        subject = driver.Driver(state_path)
        handoff = {
            "session_id": "session",
            "result": {
                "outcome": "success",
                "transcript_ref": "chat.md",
                "rounds_used": 1,
            },
            "source_base_revision": self.base,
            "accepted_revision": self.base,
        }
        with mock.patch.object(
            brainstorming_milestone,
            "terminal_handoff",
            return_value=handoff,
        ):
            message = subject._do_brainstorming_wait()
        current = state.current_unit(subject.state)
        self.assertNotIn("brainstorming_wait", current)
        self.assertNotIn("brainstorming_resume", current)
        self.assertNotIn("implementation_attempt_snapshot", current)
        self.assertIn("will run fresh", message)
        event = next(
            item for item in subject.state["events"]
            if item.get("type") == "brainstorming_rethink_sealed"
        )
        self.assertEqual(event["source_base_revision"], self.base)
        self.assertEqual(event["accepted_revision"], self.base)
        self.assertNotIn("target_path", event)


if __name__ == "__main__":
    unittest.main()
