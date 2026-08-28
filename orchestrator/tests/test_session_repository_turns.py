"""Focused proof for real-repository milestone Brainstorming turns."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming, brainstorming_coordination
from orchestrator import brainstorming_execution, brainstorming_tasks
from orchestrator import brainstorming_lifecycle, brainstorming_milestone
from orchestrator import canonical_plan, driver
from orchestrator import gitops, ledgers, runners, session_calls
from orchestrator import session_repository, state, tasks


PLAN = {
    "slices": [{
        "id": 1,
        "title": "One",
        "intent": "Build one bounded slice.",
        "producer_task_executor": {
            "draft_slice_note": "agent_call",
            "implement": "agent_call",
        },
    }]
}


def git(workspace, *args):
    return subprocess.run(
        ["git", *args], cwd=workspace, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def question_answers(prepared):
    return [
        {"id": question_id, "answer": "Checked against the repository."}
        for question_id in prepared.bound.question_ids
    ]


class CallbackExecutor:
    model_family = "codex"

    def __init__(self, replies, callbacks=None):
        self.replies = list(replies)
        self.callbacks = list(callbacks or [lambda: None] * len(self.replies))
        self.calls = []

    @staticmethod
    def supports_continuation():
        return True

    @staticmethod
    def wait_for_quiescence(_result):
        return True

    def _call(self, prompt, session_ref="session-1"):
        self.calls.append(prompt)
        self.callbacks.pop(0)()
        result = runners.RunnerResult(self.replies.pop(0), 0, 0.01)
        result.session_ref = session_ref
        result.worker_quiescent = True
        return result

    def start(self, prompt, _workspace, _context):
        return self._call(prompt)

    def continue_session(self, session_ref, prompt, _workspace, _context):
        return self._call(prompt, session_ref=session_ref)


class SessionRepositoryTurnsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orch-session-repo-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = os.path.join(self.temp.name, "repo")
        self.home = os.path.join(self.temp.name, "home")
        os.makedirs(self.workspace)
        os.makedirs(self.home)
        git(self.workspace, "init", "-q")
        git(self.workspace, "config", "user.email", "test@example.com")
        git(self.workspace, "config", "user.name", "Test")

        config = driver.load_config(None)
        driver.merge_config(config, {
            "git": {"enabled": True},
            "docs_dir": "milestone",
        })
        self.state_path = driver.init_run(
            "Build one slice.", self.workspace, config=config,
            model_profiles_home=self.home,
        )
        document = state.load(self.state_path)
        self.skeleton_path = ledgers.skeleton_path(document)
        self.target_path = "docs/decision.md"
        skeleton = Path(self.workspace, self.skeleton_path)
        skeleton.parent.mkdir(parents=True, exist_ok=True)
        skeleton.write_text(
            "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
            % json.dumps(PLAN, separators=(",", ":")),
            encoding="utf-8",
        )
        target = Path(self.workspace, self.target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("baseline\n", encoding="utf-8")
        git(self.workspace, "add", "-A")
        git(self.workspace, "commit", "-qm", "reviewed baseline")
        canonical_plan.establish_current_plan(document, self.skeleton_path)
        state.save(self.state_path, document)
        self.amendments = os.path.join(self.temp.name, "amendments.json")
        Path(self.amendments).write_text(
            '{"amendments":[]}', encoding="utf-8"
        )
        self.repository = session_repository.checkpoint_context(
            self.workspace,
            self.state_path,
            self.skeleton_path,
            "Prepare test session",
        )

    def charge(self, job="rethink", role=None):
        del role
        values = {}
        artifact_type = None
        if job == "rethink":
            values["rethink_problem"] = "Resolve the contradiction."
            artifact_type = "document"
        charge = {
            "job": job,
            "prompt_set": "default",
            "values": values,
            "amendments_path": self.amendments,
            "accepted_amendments": [],
            "repository": dict(self.repository),
        }
        if artifact_type is not None:
            charge["artifact_type"] = artifact_type
        return charge

    def session_state(self, charge=None):
        charge = charge or self.charge()
        request = {
            "workspace_path": self.workspace,
            "request": "Resolve one focused contradiction.",
            "context": {
                "brief": "Resolve one focused contradiction.",
                "references": [self.skeleton_path],
                "source_payload": {
                    "session_charge": charge
                },
            },
            "max_rounds": 2,
        }
        if charge["job"] != "rethink":
            request["target_path"] = self.target_path
        return {
            "request": request,
            "transcript_ref": os.path.join(self.temp.name, "chat.md"),
            "accepted_target_revision": None,
            "recovery_baseline_revision": "baseline",
        }

    def begin(self, role):
        return session_repository.begin_attempt(
            self.session_state(), self.charge(), role
        )

    def test_editor_turn_commits_and_empty_turn_does_not(self):
        before = gitops.head_full_sha(self.workspace)
        attempt = self.begin("initial_position")
        Path(self.workspace, self.target_path).write_text(
            "implemented\n", encoding="utf-8"
        )
        first = session_repository.complete_attempt(attempt, "lead", 1)
        after = gitops.head_full_sha(self.workspace)
        self.assertTrue(first["committed"])
        self.assertNotEqual(after, before)
        self.assertEqual(first["revision"], after)

        empty = session_repository.complete_attempt(
            self.begin("initial_position"), "lead", 2
        )
        self.assertFalse(empty["committed"])
        self.assertEqual(gitops.head_full_sha(self.workspace), after)

    def test_editor_turn_ignores_unknown_plan_fields(self):
        attempt = self.begin("initial_position")
        updated = copy.deepcopy(PLAN)
        updated["future_root_field"] = {"opaque": True}
        updated_slice = updated["slices"][0]
        updated_slice["title"] = "One evolved"
        updated_slice["material"] = "historical theme"
        updated_slice["future_slice_field"] = ["opaque"]
        updated_slice["producer_task_executor"]["future_producer"] = (
            "not-an-executor"
        )
        skeleton = Path(self.workspace, self.skeleton_path)
        skeleton.write_text(
            "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
            % json.dumps(updated, separators=(",", ":")),
            encoding="utf-8",
        )

        outcome = session_repository.complete_attempt(attempt, "lead", 1)

        self.assertTrue(outcome["accept_reply"])
        self.assertTrue(outcome["committed"])
        self.assertTrue(outcome["plan_changed"])
        persisted = state.load(self.state_path)
        projected = persisted["milestone"]["slices"][0]
        self.assertEqual(projected["title"], "One evolved")
        self.assertNotIn("material", projected)
        self.assertNotIn("future_slice_field", projected)
        self.assertEqual(
            set(projected["producer_task_executor"]),
            {"draft_slice_note", "implement"},
        )
        self.assertIn('"material":"historical theme"', skeleton.read_text())

    def test_producer_session_uses_the_project_target_without_a_private_copy(self):
        charge = self.charge("implement@slice_impl")
        request = {
            "work_area": {
                "workspace_path": self.workspace,
                "primary": self.workspace,
                "additional": [],
            },
            "request": "Implement the admitted slice.",
            "context": {
                "task_kind": "implement",
                "author_coordinates": {
                    "slice_note_path": self.target_path,
                },
                "session_charge": charge,
            },
            "reference_documents": [self.skeleton_path],
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
        order = tasks.producer_order(plan, "implement", request)
        task_state = {"tasks": []}
        selection = {"session": None}
        record = brainstorming_tasks.admit_task(
            task_state,
            order,
            driver.load_config(None),
            self.workspace,
            staffing_selection=selection,
        )
        with mock.patch.object(
            brainstorming_tasks.lifecycle,
            "create_resolved_session",
            return_value={"id": "session-1"},
        ) as create:
            result = brainstorming_tasks.start_task(
                task_state,
                record["id"],
                driver.load_config(None),
                self.home,
                staffing_selection=selection,
            )
        self.assertEqual(result, {"id": "session-1"})
        body = create.call_args.args[1]
        target = body["request"]["target_path"]
        self.assertEqual(
            os.path.realpath(target),
            os.path.realpath(os.path.join(self.workspace, self.target_path)),
        )
        self.assertNotIn("owned_target_path", create.call_args.kwargs)
        self.assertTrue(body["create_target_parents"])
        self.assertIn(
            "shared project repository", body["request"]["context"]["brief"]
        )

    def test_rethink_session_uses_the_repository_without_a_target(self):
        signal = {"problem": "Resolve the contradiction."}
        milestone_state = state.load(self.state_path)
        with mock.patch.object(
            brainstorming_milestone,
            "_launch_repository_session",
            return_value={"id": "session-1"},
        ) as launch:
            created = brainstorming_milestone.create_session(
                milestone_state,
                driver.load_config(None),
                "slice_impl/01",
                signal,
                [self.target_path, self.skeleton_path],
                self.charge(),
            )
        self.assertEqual(created, {"id": "session-1"})
        body = launch.call_args.args[3]
        self.assertEqual(body["request"]["workspace_path"], self.workspace)
        self.assertNotIn("target_path", body["request"])
        payload = body["request"]["context"]["source_payload"]
        self.assertEqual(set(payload), {"session_charge"})
        self.assertEqual(
            payload["session_charge"]["values"]["rethink_problem"],
            signal["problem"],
        )

    def test_read_only_turn_restores_and_reruns(self):
        before = gitops.head_full_sha(self.workspace)
        attempt = self.begin("contrary_position")
        Path(self.workspace, self.target_path).write_text(
            "forbidden\n", encoding="utf-8"
        )
        git(self.workspace, "add", self.target_path)
        outcome = session_repository.complete_attempt(attempt, "contrary", 1)
        self.assertFalse(outcome["accept_reply"])
        self.assertFalse(outcome["plan_changed"])
        self.assertEqual(gitops.head_full_sha(self.workspace), before)
        self.assertEqual(
            Path(self.workspace, self.target_path).read_text(encoding="utf-8"),
            "baseline\n",
        )
        self.assertEqual(git(self.workspace, "status", "--porcelain"), "")

    def test_read_only_plan_change_preserves_only_the_block(self):
        updated = {
            "slices": PLAN["slices"] + [{
                "id": 2,
                "title": "Two",
                "intent": "Build the next bounded slice.",
                "producer_task_executor": {
                    "draft_slice_note": "agent_call",
                    "implement": "agent_call",
                },
            }]
        }
        attempt = self.begin("common_sense")
        skeleton = Path(self.workspace, self.skeleton_path)
        skeleton.write_text(
            "# Illicit prose\n\n## Canonical slice plan\n```json\n%s\n```\n"
            % json.dumps(updated, separators=(",", ":")),
            encoding="utf-8",
        )
        Path(self.workspace, self.target_path).write_text(
            "also forbidden\n", encoding="utf-8"
        )
        outcome = session_repository.complete_attempt(attempt, "dante", 1)
        self.assertFalse(outcome["accept_reply"])
        self.assertTrue(outcome["plan_changed"])
        self.assertTrue(outcome["committed"])
        content = skeleton.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("# Skeleton\n"))
        self.assertEqual(
            canonical_plan.validate_canonical_plan(content)["projection"][1][
                "id"
            ],
            2,
        )
        self.assertEqual(
            Path(self.workspace, self.target_path).read_text(encoding="utf-8"),
            "baseline\n",
        )
        persisted = state.load(self.state_path)
        self.assertEqual(len(persisted["milestone"]["slices"]), 2)
        self.assertEqual(
            persisted["milestone"][canonical_plan.ANCHOR_KEY]["revision"],
            gitops.head_full_sha(self.workspace),
        )

    def test_invalid_plan_restores_and_fails(self):
        for role in ("initial_position", "contrary_position"):
            with self.subTest(role=role):
                before = gitops.head_full_sha(self.workspace)
                attempt = self.begin(role)
                Path(self.workspace, self.skeleton_path).write_text(
                    "# Skeleton\n\n## Canonical slice plan\n```json\n{bad}\n```\n",
                    encoding="utf-8",
                )
                Path(self.workspace, self.target_path).write_text(
                    "forbidden\n", encoding="utf-8"
                )
                with self.assertRaises(
                    session_repository.SessionRepositoryError
                ):
                    session_repository.complete_attempt(
                        attempt, role, 1
                    )
                self.assertEqual(gitops.head_full_sha(self.workspace), before)
                self.assertEqual(
                    git(self.workspace, "status", "--porcelain"), ""
                )

    def _store(self, participants, charge=None):
        store = brainstorming.SessionStore(
            os.path.join(self.temp.name, "session-state")
        )
        request = self.session_state(charge=charge)["request"]
        created = store.create(
            "repository-session",
            request,
            brainstorming.resolve_run_config(
                participants, "unanimity", participants
            ),
            participants,
        )
        store.transition(
            "repository-session", created.revision, "running"
        )
        return store

    def test_contract_correction_has_a_fresh_repository_snapshot(self):
        participant = {
            "id": "lead",
            "role": "initial_position",
            "delivery": "llm",
            "executor_ref": "lead-executor",
            "model_family": "codex",
        }
        contrary = {
            "id": "contrary",
            "role": "contrary_position",
            "delivery": "llm",
            "executor_ref": "unused-contrary",
            "model_family": "codex",
        }
        store = self._store([participant, contrary])
        valid = session_calls.prepare(
            self.home,
            job="rethink",
            material="document",
            role="initial_position",
            lead=True,
            artifact_type="document",
            values={
                "workspace": self.workspace,
                "chat_path": os.path.join(self.temp.name, "chat.md"),
                "reference_documents": "  - %s" % self.skeleton_path,
                "participant_id": "lead",
                "role": "initial_position",
                "round": "1",
                "repository_authority": "Git commit current",
                "rethink_problem": self.charge()["values"]["rethink_problem"],
            },
            operator_amendments=[],
        )
        reply = {
            "kind": "discussion_turn",
            "markdown": "Completed after correction.",
            "ready": False,
            "questions": question_answers(valid),
        }

        target = Path(self.workspace, self.target_path)
        second_file = Path(self.workspace, "docs", "second-resolution.md")

        def resolved_cross_file_edit():
            target.write_text("second\n", encoding="utf-8")
            second_file.write_text("also resolved\n", encoding="utf-8")

        executor = CallbackExecutor(
            ["malformed", json.dumps(reply)],
            callbacks=[
                lambda: target.write_text("first\n", encoding="utf-8"),
                resolved_cross_file_edit,
            ],
        )
        execution = brainstorming_execution.ParticipantExecution(
            store, {"lead-executor": executor}
        )
        session_snapshot = store.read("repository-session")

        def prepare(correction):
            return session_calls.prepare_turn(
                self.home,
                session_snapshot.state,
                participant,
                1,
                self.repository["pre_session_commit"],
                correction,
            )

        before = self.repository["pre_session_commit"]
        accepted, _result = execution.exchange_prepared_quiescent(
            "repository-session", "lead", prepare, {}
        )
        self.assertEqual(accepted["markdown"], reply["markdown"])
        self.assertEqual(target.read_text(encoding="utf-8"), "second\n")
        self.assertEqual(
            second_file.read_text(encoding="utf-8"), "also resolved\n"
        )
        self.assertEqual(
            int(git(self.workspace, "rev-list", "--count", "%s..HEAD" % before)),
            2,
        )

    def test_coordinator_repeats_a_mutating_read_only_seat(self):
        lead = {
            "id": "lead", "role": "initial_position", "delivery": "llm",
            "executor_ref": "lead-executor", "model_family": "codex",
        }
        contrary = {
            "id": "contrary", "role": "contrary_position",
            "delivery": "llm", "executor_ref": "contrary-executor",
            "model_family": "codex",
        }
        participants = [lead, contrary]
        store = self._store(participants)

        def prepared(role, lead_seat, markdown):
            package = session_calls.prepare(
                self.home,
                job="rethink",
                material="document",
                role=role,
                lead=lead_seat,
                artifact_type="document",
                values={
                    "workspace": self.workspace,
                    "chat_path": os.path.join(self.temp.name, "chat.md"),
                    "reference_documents": "  - %s" % self.skeleton_path,
                    "participant_id": role,
                    "role": role,
                    "round": "1",
                    "repository_authority": "Git commit current",
                    "rethink_problem": self.charge()["values"][
                        "rethink_problem"
                    ],
                },
                operator_amendments=[],
            )
            return json.dumps({
                "kind": "discussion_turn",
                "markdown": markdown,
                "ready": False,
                "questions": question_answers(package),
            })

        target = Path(self.workspace, self.target_path)
        lead_executor = CallbackExecutor([
            prepared("initial_position", True, "Author turn.")
        ])
        contrary_executor = CallbackExecutor(
            [
                prepared("contrary_position", False, "Mutating review."),
                prepared("contrary_position", False, "Clean review."),
            ],
            callbacks=[
                lambda: target.write_text("forbidden\n", encoding="utf-8"),
                lambda: None,
            ],
        )
        execution = brainstorming_execution.ParticipantExecution(
            store,
            {
                "lead-executor": lead_executor,
                "contrary-executor": contrary_executor,
            },
        )
        coordinator = brainstorming_coordination.BrainstormingCoordinator(
            store,
            execution,
            turn_preparer=lambda current, participant, round_number,
                                 target_revision, correction:
                session_calls.prepare_turn(
                    self.home,
                    current,
                    participant,
                    round_number,
                    target_revision,
                    correction,
                ),
        )
        first = coordinator.run_next_turn("repository-session", {})
        self.assertEqual(len(first.state["completed_turns"]), 1)
        invalidated = coordinator.run_next_turn("repository-session", {})
        self.assertEqual(len(invalidated.state["completed_turns"]), 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "baseline\n")
        accepted = coordinator.run_next_turn("repository-session", {})
        self.assertEqual(len(accepted.state["completed_turns"]), 2)
        self.assertEqual(len(contrary_executor.calls), 2)

    def test_plan_only_invalidation_advances_revision_without_a_turn(self):
        lead = {
            "id": "lead", "role": "initial_position", "delivery": "llm",
            "executor_ref": "lead-executor", "model_family": "codex",
        }
        contrary = {
            "id": "contrary", "role": "contrary_position",
            "delivery": "llm", "executor_ref": "contrary-executor",
            "model_family": "codex",
        }
        store = self._store([lead, contrary])

        def reply(role, lead_seat, markdown, ready):
            package = session_calls.prepare(
                self.home,
                job="rethink",
                material="document",
                role=role,
                lead=lead_seat,
                artifact_type="document",
                values={
                    "workspace": self.workspace,
                    "chat_path": os.path.join(self.temp.name, "chat.md"),
                    "reference_documents": "  - %s" % self.skeleton_path,
                    "participant_id": role,
                    "role": role,
                    "round": "1",
                    "repository_authority": "Git commit current",
                    "rethink_problem": self.charge()["values"][
                        "rethink_problem"
                    ],
                },
                operator_amendments=[],
            )
            return json.dumps({
                "kind": "discussion_turn",
                "markdown": markdown,
                "ready": ready,
                "questions": question_answers(package),
            })

        updated = {
            "slices": PLAN["slices"] + [{
                "id": 2,
                "title": "Two",
                "intent": "Build the next bounded slice.",
                "producer_task_executor": {
                    "draft_slice_note": "agent_call",
                    "implement": "agent_call",
                },
            }]
        }

        def change_plan():
            Path(self.workspace, self.skeleton_path).write_text(
                "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                % json.dumps(updated, separators=(",", ":")),
                encoding="utf-8",
            )

        execution = brainstorming_execution.ParticipantExecution(
            store,
            {
                "lead-executor": CallbackExecutor([
                    reply("initial_position", True, "Author ready.", True)
                ]),
                "contrary-executor": CallbackExecutor(
                    [
                        reply("contrary_position", False, "Plan changed.", True),
                        reply("contrary_position", False, "Clean retry.", False),
                    ],
                    callbacks=[change_plan, lambda: None],
                ),
            },
        )
        coordinator = brainstorming_coordination.BrainstormingCoordinator(
            store,
            execution,
            turn_preparer=lambda current, participant, round_number,
                                 target_revision, correction:
                session_calls.prepare_turn(
                    self.home,
                    current,
                    participant,
                    round_number,
                    target_revision,
                    correction,
                ),
        )
        first = coordinator.run_next_turn("repository-session", {})
        first_revision = first.state["accepted_target_revision"]
        invalidated = coordinator.run_next_turn("repository-session", {})

        self.assertEqual(len(invalidated.state["completed_turns"]), 1)
        self.assertNotEqual(
            invalidated.state["accepted_target_revision"], first_revision
        )
        self.assertFalse(
            brainstorming.repository_positions_ready(invalidated.state)
        )
        accepted = coordinator.run_next_turn("repository-session", {})
        self.assertEqual(len(accepted.state["completed_turns"]), 2)
        self.assertEqual(accepted.state["status"], "running")

    def test_coordinator_records_an_external_dante_turn(self):
        lead = {
            "id": "lead", "role": "initial_position", "delivery": "llm",
            "executor_ref": "lead-executor", "model_family": "codex",
        }
        contrary = {
            "id": "contrary", "role": "contrary_position",
            "delivery": "llm", "executor_ref": "contrary-executor",
            "model_family": "codex",
        }
        dante = {
            "id": "dante", "role": "common_sense",
            "delivery": "external", "external_ref": "operator-dante",
        }
        store = self._store([lead, contrary, dante])

        def reply(role, lead_seat, markdown):
            package = session_calls.prepare(
                self.home,
                job="rethink",
                material="document",
                role=role,
                lead=lead_seat,
                artifact_type="document",
                values={
                    "workspace": self.workspace,
                    "chat_path": os.path.join(self.temp.name, "chat.md"),
                    "reference_documents": "  - %s" % self.skeleton_path,
                    "participant_id": role,
                    "role": role,
                    "round": "1",
                    "repository_authority": "Git commit current",
                    "rethink_problem": self.charge()["values"][
                        "rethink_problem"
                    ],
                },
                operator_amendments=[],
            )
            return json.dumps({
                "kind": "discussion_turn",
                "markdown": markdown,
                "ready": False,
                "questions": question_answers(package),
            })

        execution = brainstorming_execution.ParticipantExecution(
            store,
            {
                "lead-executor": CallbackExecutor([
                    reply("initial_position", True, "Author turn.")
                ]),
                "contrary-executor": CallbackExecutor([
                    reply("contrary_position", False, "Review turn.")
                ]),
            },
        )
        coordinator = brainstorming_coordination.BrainstormingCoordinator(
            store,
            execution,
            turn_preparer=lambda current, participant, round_number,
                                 target_revision, correction:
                session_calls.prepare_turn(
                    self.home,
                    current,
                    participant,
                    round_number,
                    target_revision,
                    correction,
                ),
        )
        coordinator.run_next_turn("repository-session", {})
        coordinator.run_next_turn("repository-session", {})
        with self.assertRaises(
            brainstorming_coordination.ExternalInterventionPending
        ):
            coordinator.run_next_turn("repository-session", {})
        pending = store.read_external_intervention("repository-session")
        store.submit_external_intervention(
            "repository-session",
            pending["token"],
            {
                "markdown": "Dante asks the bounded question.",
                "target_revision": gitops.head_full_sha(self.workspace),
            },
        )

        accepted = coordinator.run_next_turn("repository-session", {})

        self.assertEqual(len(accepted.state["completed_turns"]), 3)
        self.assertEqual(
            accepted.state["completed_turns"][-1]["participant_id"],
            "dante",
        )
        self.assertIsNone(
            store.read_external_intervention("repository-session")
        )

    def test_external_plan_only_invalidation_republishes_dante(self):
        lead = {
            "id": "lead", "role": "initial_position", "delivery": "llm",
            "executor_ref": "lead-executor", "model_family": "codex",
        }
        contrary = {
            "id": "contrary", "role": "contrary_position",
            "delivery": "llm", "executor_ref": "contrary-executor",
            "model_family": "codex",
        }
        dante = {
            "id": "dante", "role": "common_sense",
            "delivery": "external", "external_ref": "operator-dante",
        }
        store = self._store([lead, contrary, dante])

        def reply(role, lead_seat, markdown, questioner=False):
            package = session_calls.prepare(
                self.home,
                job="rethink",
                material="document",
                role=role,
                lead=lead_seat,
                artifact_type="document",
                values={
                    "workspace": self.workspace,
                    "chat_path": os.path.join(self.temp.name, "chat.md"),
                    "reference_documents": "  - %s" % self.skeleton_path,
                    "participant_id": role,
                    "role": role,
                    "round": "1",
                    "repository_authority": "Git commit current",
                    "rethink_problem": self.charge()["values"][
                        "rethink_problem"
                    ],
                },
                operator_amendments=[],
            )
            payload = {
                "kind": "questioner_turn" if questioner else "discussion_turn",
                "markdown": markdown,
                "questions": question_answers(package),
            }
            if not questioner:
                payload["ready"] = False
            return json.dumps(payload)

        updated = {
            "slices": PLAN["slices"] + [{
                "id": 2,
                "title": "Two",
                "intent": "Build the next bounded slice.",
                "producer_task_executor": {
                    "draft_slice_note": "agent_call",
                    "implement": "agent_call",
                },
            }]
        }

        def change_plan():
            Path(self.workspace, self.skeleton_path).write_text(
                "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                % json.dumps(updated, separators=(",", ":")),
                encoding="utf-8",
            )

        execution = brainstorming_execution.ParticipantExecution(
            store,
            {
                "lead-executor": CallbackExecutor([
                    reply("initial_position", True, "Author turn.")
                ]),
                "contrary-executor": CallbackExecutor([
                    reply("contrary_position", False, "Contrary turn.")
                ]),
                "operator-dante": CallbackExecutor(
                    [
                        reply("common_sense", False, "Changed plan.", True),
                        reply("common_sense", False, "Clean question.", True),
                    ],
                    callbacks=[change_plan, lambda: None],
                ),
            },
        )
        turn_preparer = lambda current, participant, round_number, \
                target_revision, correction: session_calls.prepare_turn(
                    self.home,
                    current,
                    participant,
                    round_number,
                    target_revision,
                    correction,
                )
        coordinator = brainstorming_coordination.BrainstormingCoordinator(
            store, execution, turn_preparer=turn_preparer
        )
        coordinator.run_next_turn("repository-session", {})
        coordinator.run_next_turn("repository-session", {})
        with self.assertRaises(
            brainstorming_coordination.ExternalInterventionPending
        ) as first_pending:
            coordinator.run_next_turn("repository-session", {})
        first_revision = first_pending.exception.intervention[
            "target_revision"
        ]
        record = {
            "id": "repository-session",
            "runtime": {
                "external_providers": {
                    "operator-dante": {"kind": "narrator"}
                }
            },
        }
        brainstorming_lifecycle._wait_for_external_response(
            store,
            execution,
            record,
            first_pending.exception,
            {},
            turn_preparer,
        )
        advanced = store.read("repository-session")
        self.assertEqual(len(advanced.state["completed_turns"]), 2)
        self.assertNotEqual(
            advanced.state["accepted_target_revision"], first_revision
        )
        self.assertEqual(
            advanced.state["accepted_target_revision"],
            gitops.head_full_sha(self.workspace),
        )
        self.assertIsNone(
            store.read_external_intervention("repository-session")
        )

        with self.assertRaises(
            brainstorming_coordination.ExternalInterventionPending
        ) as second_pending:
            coordinator.run_next_turn("repository-session", {})
        self.assertEqual(
            second_pending.exception.intervention["target_revision"],
            advanced.state["accepted_target_revision"],
        )
        brainstorming_lifecycle._wait_for_external_response(
            store,
            execution,
            record,
            second_pending.exception,
            {},
            turn_preparer,
        )
        accepted = coordinator.run_next_turn("repository-session", {})
        self.assertEqual(len(accepted.state["completed_turns"]), 3)
        self.assertEqual(
            accepted.state["completed_turns"][-1]["target_revision"],
            accepted.state["accepted_target_revision"],
        )

    def test_questioner_uses_the_same_read_only_boundary(self):
        lead = {
            "id": "lead", "role": "initial_position", "delivery": "llm",
            "executor_ref": "unused-lead", "model_family": "codex",
        }
        contrary = {
            "id": "contrary", "role": "contrary_position",
            "delivery": "llm", "executor_ref": "unused-contrary",
            "model_family": "codex",
        }
        dante = {
            "id": "dante", "role": "common_sense", "delivery": "llm",
            "executor_ref": "dante-executor", "model_family": "codex",
        }
        store = self._store([lead, contrary, dante])
        package = session_calls.prepare(
            self.home,
            job="rethink",
            material="document",
            role="common_sense",
            lead=False,
            artifact_type="document",
            values={
                "workspace": self.workspace,
                "chat_path": os.path.join(self.temp.name, "chat.md"),
                "reference_documents": "  - %s" % self.skeleton_path,
                "participant_id": "dante",
                "role": "common_sense",
                "round": "1",
                "repository_authority": "Git commit current",
                "rethink_problem": self.charge()["values"]["rethink_problem"],
            },
            operator_amendments=[],
        )
        reply = json.dumps({
            "kind": "questioner_turn",
            "markdown": "Does the current repository resolve the issue?",
            "questions": question_answers(package),
        })
        target = Path(self.workspace, self.target_path)
        executor = CallbackExecutor(
            [reply],
            callbacks=[
                lambda: target.write_text("forbidden\n", encoding="utf-8")
            ],
        )
        execution = brainstorming_execution.ParticipantExecution(
            store, {"dante-executor": executor}
        )
        snapshot = store.read("repository-session")
        with self.assertRaises(session_repository.ReadOnlyTurnInvalidated):
            execution.exchange_prepared_quiescent(
                "repository-session",
                "dante",
                lambda correction: session_calls.prepare_turn(
                    self.home,
                    snapshot.state,
                    dante,
                    1,
                    self.repository["pre_session_commit"],
                    correction,
                ),
                {},
            )
        self.assertEqual(target.read_text(encoding="utf-8"), "baseline\n")


if __name__ == "__main__":
    unittest.main()
