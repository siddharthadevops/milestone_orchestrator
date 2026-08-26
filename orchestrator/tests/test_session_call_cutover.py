"""Focused proof for routed milestone Brainstorming seat calls."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from orchestrator import brainstorming, brainstorming_coordination
from orchestrator import brainstorming_execution
from orchestrator import brainstorming_milestone
from orchestrator import brainstorming_tasks
from orchestrator import canonical_plan
from orchestrator import contracts, prompt_authority, prompt_router, prompt_sets
from orchestrator import driver, ledgers, runners, session_calls
from orchestrator import session_repository, state, tasks


RETHINK_FINDING = json.dumps(
    {"id": "F1", "summary": "One bounded contradiction."},
    sort_keys=True,
)


def repository_context(workspace):
    return {
        "state_path": os.path.join(workspace, "state.json"),
        "skeleton_path": "docs/skeleton.md",
        "pre_session_commit": "0" * 40,
    }


def turn_values(workspace, role):
    return {
        "workspace": workspace,
        "chat_path": "%s/chat.md" % workspace,
        "reference_documents": "  - docs/skeleton.md",
        "participant_id": role,
        "role": role,
        "round": "1",
        "target_path": "docs/decision.md",
        "target_authority": "accepted revision abc",
        "target_state": "present",
    }


def question_answers(bound):
    return [
        {"id": question_id, "answer": "Checked the current session context."}
        for question_id in bound.question_ids
    ]


class RecordingExecutor:
    model_family = "codex"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    @staticmethod
    def supports_continuation():
        return True

    @staticmethod
    def wait_for_quiescence(_result):
        return True

    def start(self, prompt, workspace_path, execution_context):
        self.calls.append(prompt)
        result = runners.RunnerResult(self.replies.pop(0), 0, 0.01)
        result.session_ref = "session-1"
        result.worker_quiescent = True
        return result

    def continue_session(
        self, session_ref, prompt, workspace_path, execution_context
    ):
        self.calls.append(prompt)
        result = runners.RunnerResult(self.replies.pop(0), 0, 0.01)
        result.session_ref = session_ref
        result.worker_quiescent = True
        return result


class SessionCallCutoverTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orch-session-call-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = self.temp.name

    def prepare(self, job, role, lead, artifact_type=None, **changes):
        values = turn_values(self.workspace, role)
        if job == "rethink":
            values["rethink_finding"] = RETHINK_FINDING
        options = {
            "job": job,
            "material": (
                "code" if job == "implement@slice_impl" else "document"
            ),
            "role": role,
            "lead": lead,
            "artifact_type": artifact_type,
            "values": values,
            "operator_amendments": [],
        }
        options.update(changes)
        return session_calls.prepare(self.workspace, **options)

    def write_set(self, name, documents):
        root = Path(prompt_sets.prompt_set_dir(self.workspace, name))
        for member, document in documents.items():
            path = root / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding="utf-8")

    def test_session_charge_matrix_mounts_exact_seat_law(self):
        cases = (
            ("draft_slice_note@slice_doc", "initial_position", True, None),
            ("draft_slice_note@slice_doc", "contrary_position", False, None),
            ("implement@slice_impl", "initial_position", True, None),
            ("rethink", "initial_position", True, "document"),
            ("rethink", "common_sense", False, "implementation"),
        )
        for job, role, lead, artifact_type in cases:
            with self.subTest(job=job, role=role):
                prepared = self.prepare(
                    job, role, lead, artifact_type=artifact_type
                )
                expected_kind = (
                    "questioner_turn"
                    if role == "common_sense" else "discussion_turn"
                )
                self.assertEqual(prepared.bound.prompt["kind"], expected_kind)
                reply = {
                    "kind": expected_kind,
                    "markdown": "One bounded intervention.",
                    "questions": question_answers(prepared.bound),
                }
                if expected_kind == "discussion_turn":
                    reply["ready"] = True
                self.assertEqual(prepared.validate(copy.deepcopy(reply)), reply)

        with self.assertRaises(prompt_router.PromptRouterError):
            self.prepare(
                "review_round@slice_impl", "initial_position", True
            )

    def test_milestone_session_admission_is_closed(self):
        amendments = Path(self.workspace) / "amendments.json"
        amendments.write_text('{"amendments":[]}', encoding="utf-8")
        charge = {
            "job": "implement@slice_impl",
            "material": "code",
            "prompt_set": "default",
            "values": {},
            "amendments_path": str(amendments),
            "accepted_amendments": [],
            "repository": repository_context(self.workspace),
        }
        request = {
            "work_area": {
                "workspace_path": self.workspace,
                "primary": self.workspace,
                "additional": [],
            },
            "request": "Implement the admitted slice.",
            "context": {
                "task_kind": "implement",
                "session_charge": charge,
            },
            "reference_documents": ["docs/slice.md"],
        }
        plan = {
            "id": 1,
            "title": "One",
            "intent": "Exercise one admitted producer.",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "brainstorming"},
            },
        }
        order = tasks.producer_order(plan, "implement", request)
        state = {"tasks": []}
        resolved = {
            "dispatch_authority": "static",
            "participants": [],
        }
        with mock.patch.object(
            brainstorming_tasks, "resolve_staffing", return_value=resolved
        ):
            record = brainstorming_tasks.admit_task(
                state, order, {}, self.workspace
            )
        self.assertEqual(
            record["order"]["request"]["context"]["session_charge"],
            charge,
        )

        mismatched = copy.deepcopy(order)
        mismatched["request"]["context"]["task_kind"] = "draft_slice_note"
        with (
            mock.patch.object(
                brainstorming_tasks, "resolve_staffing",
                return_value=resolved,
            ),
            self.assertRaises(tasks.TaskRequestError),
        ):
            brainstorming_tasks.admit_task(
                {"tasks": []}, mismatched, {}, self.workspace
            )

        wrong_material = copy.deepcopy(order)
        wrong_material["request"]["context"]["session_charge"][
            "material"
        ] = "document"
        with (
            mock.patch.object(
                brainstorming_tasks, "resolve_staffing",
                return_value=resolved,
            ),
            self.assertRaises(tasks.TaskRequestError),
        ):
            brainstorming_tasks.admit_task(
                {"tasks": []}, wrong_material, {}, self.workspace
            )

        for job in (
            "review_round@slice_impl", "fix_findings@slice_impl",
            "reclassify@doc", "suite_checkpoint@workspace",
            "guarantee_calibration",
        ):
            invalid = dict(charge, job=job)
            with self.subTest(job=job), self.assertRaises(
                prompt_router.PromptRouterError
            ):
                session_calls.validate_charge(invalid)

    def test_driver_admits_the_planned_producer_charge(self):
        repository = os.path.join(self.workspace, "repo")
        home = os.path.join(self.workspace, "home")
        os.makedirs(repository)
        os.makedirs(home)
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repository, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repository, check=True,
        )
        Path(repository, "README").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=repository, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "seed"], cwd=repository, check=True
        )
        config = driver.load_config(None)
        driver.merge_config(config, {
            "git": {"enabled": True}, "docs_dir": "milestone",
        })
        state_path = driver.init_run(
            "Build one slice.", repository, config=config,
            model_profiles_home=home,
        )
        document = state.load(state_path)
        skeleton_path = ledgers.skeleton_path(document)
        note_path = ledgers.slice_note_path(document, 1)
        plan = {"slices": [{
            "id": 1,
            "title": "One",
            "intent": "Build the admitted implementation.",
            "producer_task_executor": {
                "draft_slice_note": "agent_call",
                "implement": "brainstorming",
            },
        }]}
        for relative, content in (
            (
                skeleton_path,
                "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                % json.dumps(plan),
            ),
            (note_path, "# Slice 01\n"),
        ):
            path = Path(repository, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(
            ["git", "add", skeleton_path, note_path],
            cwd=repository, check=True,
        )
        subprocess.run(
            ["git", "commit", "-qm", "reviewed design"],
            cwd=repository, check=True,
        )
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        document["milestone"]["slices"] = [{
            "id": 1,
            "title": "One",
            "intent": "Build the admitted implementation.",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "brainstorming"},
            },
        }]
        document["milestone"]["canonical_plan_anchor"] = {
            "path": skeleton_path, "revision": revision,
        }
        skeleton = document["units"][0]
        skeleton.update({"status": state.U_SEALED, "artifact": skeleton_path})
        note = state._new_unit(state.UNIT_SLICE_DOC, 1)
        note.update({"status": state.U_SEALED, "artifact": note_path})
        implementation = state._new_unit(state.UNIT_SLICE_IMPL, 1)
        document["units"] = [skeleton, note, implementation]
        state.save(state_path, document)

        resolved = {
            "dispatch_authority": "static", "participants": [],
        }
        subject = driver.Driver(
            state_path, runner=runners.MockRunner([]),
            model_profiles_home=home,
        )
        with (
            mock.patch.object(
                brainstorming_tasks, "resolve_staffing",
                return_value=resolved,
            ),
            mock.patch.object(
                brainstorming_tasks, "start_task",
                return_value={"id": "session-1"},
            ),
        ):
            subject.step()

        current = state.current_unit(subject.state)
        record = tasks.task_record(
            subject.state, current["active_task"]["id"]
        )
        charge = record["order"]["request"]["context"]["session_charge"]
        self.assertEqual(charge["job"], "implement@slice_impl")
        self.assertEqual(charge["material"], "code")
        self.assertEqual(
            charge["prompt_set"], subject.state[state.PROMPT_SET_KEY]
        )
        self.assertEqual(
            charge["repository"]["state_path"], os.path.abspath(state_path)
        )
        self.assertEqual(
            charge["repository"]["skeleton_path"], skeleton_path
        )
        self.assertEqual(
            charge["repository"]["pre_session_commit"],
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
        )
        self.assertEqual(current["brainstorming_wait"]["session_id"], "session-1")

        updated_plan = copy.deepcopy(plan)
        updated_plan["slices"].append({
            "id": 2,
            "title": "Two",
            "intent": "Continue after the session plan edit.",
            "producer_task_executor": {
                "draft_slice_note": "agent_call",
                "implement": "agent_call",
            },
        })
        Path(repository, skeleton_path).write_text(
            "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
            % json.dumps(updated_plan),
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", skeleton_path], cwd=repository, check=True
        )
        subprocess.run(
            ["git", "commit", "-qm", "session plan edit"],
            cwd=repository,
            check=True,
        )
        new_revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        refreshed = state.load(state_path)
        canonical_plan.establish_current_plan(refreshed, skeleton_path)
        state.save(state_path, refreshed)

        def finish_reloaded_wait(unit, _wait):
            unit.pop("brainstorming_wait", None)
            unit.pop("active_task", None)
            return "finished reloaded wait"

        with (
            mock.patch.object(
                subject,
                "_apply_profile_swap",
                return_value=True,
            ),
            mock.patch.object(
                subject,
                "_do_brainstorming_production_wait",
                side_effect=finish_reloaded_wait,
            ),
        ):
            subject.step()

        persisted = state.load(state_path)
        self.assertEqual(
            persisted["milestone"][canonical_plan.ANCHOR_KEY]["revision"],
            new_revision,
        )
        self.assertEqual(
            [item["id"] for item in persisted["milestone"]["slices"]],
            [1, 2],
        )

    def test_session_questions_and_envelopes_are_bound(self):
        lead = self.prepare(
            "draft_slice_note@slice_doc", "initial_position", True
        )
        contrary = self.prepare(
            "draft_slice_note@slice_doc", "contrary_position", False
        )
        rethink = self.prepare(
            "rethink", "initial_position", True, artifact_type="document"
        )
        dante = self.prepare(
            "rethink", "common_sense", False,
            artifact_type="document",
        )
        self.assertGreater(len(lead.bound.question_ids), len(contrary.bound.question_ids))
        self.assertEqual(
            set(rethink.bound.question_ids),
            {"turn_environment_fit", "turn_human_scale"},
        )
        self.assertIn("request_focus", dante.bound.question_ids)
        invalid = {
            "kind": "questioner_turn",
            "markdown": "Any remaining question?",
            "ready": True,
            "questions": question_answers(dante.bound),
        }
        with self.assertRaises(contracts.ContractError):
            dante.validate(invalid)

    def test_session_project_extension_joins_the_bound_envelope(self):
        policy = {
            "id": "seat-proof",
            "version": 1,
            "enabled": True,
            "scope": {
                "kinds": ["implement"],
                "unit_kinds": ["slice_impl"],
            },
            "prompt": "Record the seat evidence.",
            "contract": {
                "field": "seat_evidence",
                "required": True,
                "entry": {"finding": {"type": "string"}},
                "checks": [{"kind": "non_empty", "field": "finding"}],
            },
        }
        project_context = {
            "project": "orchestrator",
            "work_area": "implementation",
            "primary": {"path": self.workspace},
            "additional": [],
            "reuse_sources": [],
            "safeguards": [policy],
        }
        prepared = self.prepare(
            "implement@slice_impl",
            "initial_position",
            True,
            project_context=project_context,
        )
        reply = {
            "kind": "discussion_turn",
            "markdown": "Implemented the bounded change.",
            "questions": question_answers(prepared.bound),
        }
        with self.assertRaises(contracts.ContractError):
            prepared.validate(copy.deepcopy(reply))
        reply["seat_evidence"] = [{"finding": "Used the existing router."}]
        self.assertEqual(prepared.validate(copy.deepcopy(reply)), reply)

    def test_rethink_origin_has_one_unframed_identity(self):
        finding = {"id": "F1", "summary": "One bounded contradiction."}
        checked = brainstorming_milestone.validate_origin_signal(
            {
                "status": "need_rethink",
                "kind": "implement",
                "finding": finding,
                "target_path": "docs/skeleton.md",
                "questions": [],
            },
            "implement",
        )
        self.assertEqual(checked, {
            "finding": finding,
            "target_path": "docs/skeleton.md",
        })
        for retired in (
            "request", "result_mode", "max_rounds", "failure_gap"
        ):
            self.assertNotIn(retired, checked)

        charge = {
            "job": "rethink",
            "material": "document",
            "prompt_set": "default",
            "values": {"rethink_finding": RETHINK_FINDING},
            "amendments_path": str(Path(self.workspace) / "amendments.json"),
            "accepted_amendments": [],
            "artifact_type": "document",
            "repository": repository_context(self.workspace),
        }
        session_calls.validate_charge(charge)
        missing_finding = copy.deepcopy(charge)
        missing_finding["values"] = {}
        with self.assertRaises(prompt_router.PromptRouterError):
            session_calls.validate_charge(missing_finding)

        prepared = self.prepare(
            "rethink", "initial_position", True,
            artifact_type="document",
        )
        mounted = [
            declaration
            for unit in prepared.bound.prompt["instructions"]
            for declaration in unit["variables"]
            if declaration.get("name") == "rethink_finding"
        ]
        self.assertEqual(len(mounted), 1)

    def test_rethink_payload_mount_is_exact_for_every_seat(self):
        base = prompt_sets.default_seed().documents
        cases = (
            ("brainstorming/discussion_turn.json", "initial_position", True),
            ("brainstorming/discussion_turn.json", "contrary_position", False),
            ("brainstorming/questioner_turn.json", "common_sense", False),
        )
        for member, role, lead in cases:
            for mutation in ("missing", "duplicate"):
                with self.subTest(role=role, mutation=mutation):
                    documents = copy.deepcopy(base)
                    parts = documents[member]["instructions"]["parts"]
                    index = next(
                        index for index, part in enumerate(parts)
                        if part.get("ref") == "rethink_charge"
                    )
                    if mutation == "missing":
                        parts.pop(index)
                    else:
                        parts.insert(index, {"ref": "rethink_charge"})
                    self.write_set("invalid-rethink-mount", documents)
                    prepared = self.prepare(
                        "rethink", role, lead,
                        artifact_type="document",
                        prompt_set="invalid-rethink-mount",
                    )
                    declarations = session_calls._mounted_variable_declarations(
                        prepared.bound.prompt
                    )
                    self.assertEqual(declarations["rethink_finding"], 1)
                    self.assertEqual(
                        session_calls._mounted_variable_substitutions(
                            prepared.bound.prompt, "rethink_finding"
                        ),
                        1,
                    )
                    self.assertIsNotNone(prepared.prompt_set_fallback)

    def test_rethink_artifact_type_follows_the_target(self):
        subject = object.__new__(driver.Driver)
        subject._design_document_paths = lambda: [
            "implementation/milestones/demo/skeleton.md"
        ]
        unit = {"kind": state.UNIT_SLICE_IMPL}
        for target in (
            "implementation/milestones/demo/skeleton.md",
            "README.md",
            "docs/architecture.rst",
        ):
            with self.subTest(target=target):
                self.assertEqual(
                    subject._rethink_artifact_type(unit, target), "document"
                )
        self.assertEqual(
            subject._rethink_artifact_type(unit, "orchestrator/driver.py"),
            "implementation",
        )

    def test_session_correction_reloads_prompt_and_authority(self):
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        first_line = "First stored session wording."
        second_line = "Second stored session wording."
        documents["brainstorming/discussion_turn.json"]["instructions"][
            "parts"
        ][1]["text"].append(first_line)
        self.write_set("live", documents)
        first = self.prepare(
            "rethink",
            "initial_position",
            True,
            artifact_type="document",
            prompt_set="live",
        )
        documents["brainstorming/discussion_turn.json"]["instructions"][
            "parts"
        ][1]["text"][-1] = second_line
        self.write_set("live", documents)
        second = self.prepare(
            "rethink",
            "initial_position",
            True,
            artifact_type="document",
            prompt_set="live",
            correction="The first envelope omitted a required answer.",
            operator_amendments=[{"id": "A1", "text": "Current law."}],
        )
        expected_values = turn_values(self.workspace, "initial_position")
        expected_values.update({
            "rethink_finding": RETHINK_FINDING,
            "operator_amendments": prompt_authority.current_amendments(
                [{"id": "A1", "text": "Current law."}]
            ),
            "contract_correction": (
                "The first envelope omitted a required answer."
            ),
        })
        self.assertNotEqual(first.prompt, second.prompt)
        self.assertNotEqual(first.bound.prompt, second.bound.prompt)
        self.assertEqual(
            second.prompt,
            prompt_router.render(second.bound.prompt, expected_values),
        )
        self.assertEqual(second.prompt_set_fallback, None)

    def test_prepare_turn_reads_mutable_authority_now(self):
        amendments = Path(self.workspace) / "amendments.json"
        amendments.write_text('{"amendments":[]}', encoding="utf-8")
        state = {
            "request": {
                "workspace_path": self.workspace,
                "target_path": "docs/decision.md",
                "context": {
                    "references": ["docs/skeleton.md"],
                    "source_payload": {
                        "session_charge": {
                            "job": "rethink",
                            "material": "document",
                            "prompt_set": "default",
                            "values": {
                                "rethink_finding": RETHINK_FINDING,
                            },
                            "amendments_path": str(amendments),
                            "accepted_amendments": [],
                            "artifact_type": "document",
                            "repository": repository_context(self.workspace),
                        }
                    },
                },
            },
            "transcript_ref": "%s/chat.md" % self.workspace,
            "accepted_target_revision": "accepted",
            "recovery_baseline_revision": "baseline",
        }
        participant = {
            "id": "initial-position", "role": "initial_position"
        }
        target = {"exists": True}
        boundary = {
            "accept_reply": True,
            "committed": False,
            "plan_changed": False,
            "revision": "1" * 40,
            "anchor": None,
        }
        with (
            mock.patch.object(
                session_repository,
                "live_target_authority",
                return_value=("repository HEAD live", "present", {}),
            ),
            mock.patch.object(
                session_repository,
                "begin_attempt",
                return_value=types.SimpleNamespace(),
            ),
            mock.patch.object(
                session_repository,
                "complete_attempt",
                return_value=boundary,
            ),
        ):
            first = session_calls.prepare_turn(
                self.workspace, state, participant, 1, target
            )
            amendments.write_text(
                json.dumps({
                    "amendments": [{"id": "A1", "text": "New law."}]
                }),
                encoding="utf-8",
            )
            second = session_calls.prepare_turn(
                self.workspace, state, participant, 1, target
            )
        self.assertNotEqual(first.prompt, second.prompt)
        expected_values = {
            "workspace": self.workspace,
            "chat_path": "%s/chat.md" % self.workspace,
            "reference_documents": "  - docs/skeleton.md",
            "participant_id": "initial-position",
            "role": "initial_position",
            "round": "1",
            "target_path": "docs/decision.md",
            "target_authority": "repository HEAD live",
            "target_state": "present",
            "rethink_finding": RETHINK_FINDING,
            "operator_amendments": prompt_authority.current_amendments(
                [{"id": "A1", "text": "New law."}]
            ),
        }
        self.assertEqual(
            second.prompt,
            prompt_router.render(second.bound.prompt, expected_values),
        )

    def test_prepared_exchange_refreshes_its_correction_package(self):
        store = brainstorming.SessionStore(self.workspace)
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
            "executor_ref": "contrary-executor",
            "model_family": "claude",
        }
        participants = [participant, contrary]
        request = {
            "workspace_path": self.workspace,
            "target_path": "docs/decision.md",
            "request": "Resolve one issue.",
            "context": {"brief": "Resolve one issue."},
            "max_rounds": 1,
        }
        created = store.create(
            "prepared", request,
            brainstorming.resolve_run_config(
                participants, "unanimity", participants
            ),
            participants,
        )
        store.transition("prepared", created.revision, "running")
        executor = RecordingExecutor([
            "malformed",
            json.dumps({"kind": "discussion_turn", "markdown": "valid"}),
        ])
        subject = brainstorming_execution.ParticipantExecution(
            store, {"lead-executor": executor}
        )
        errors = []

        def prepare(error):
            errors.append(error)

            def validate(value):
                if value.get("kind") != "discussion_turn" \
                        or not value.get("markdown"):
                    raise contracts.ContractError("invalid turn")
                return value

            return types.SimpleNamespace(
                prompt="first-package" if error is None else "second-package",
                validate=validate,
                prompt_set_fallback=None,
            )

        reply, _result = subject.exchange_prepared_quiescent(
            "prepared", "lead", prepare, {}
        )
        self.assertEqual(reply["markdown"], "valid")
        self.assertEqual(executor.calls, ["first-package", "second-package"])
        self.assertEqual(errors[0], None)
        self.assertIsInstance(errors[1], str)

    def test_coordinator_uses_the_routed_turn_boundary(self):
        root = os.path.join(self.workspace, "coordinated")
        os.makedirs(os.path.join(root, "docs"))
        Path(root, "docs", "decision.md").write_text(
            "initial\n", encoding="utf-8"
        )
        amendments = Path(root, "amendments.json")
        amendments.write_text('{"amendments":[]}', encoding="utf-8")
        charge = {
            "job": "rethink",
            "material": "document",
            "prompt_set": "default",
            "values": {"rethink_finding": RETHINK_FINDING},
            "amendments_path": str(amendments),
            "accepted_amendments": [],
            "artifact_type": "document",
            "repository": repository_context(root),
        }
        lead = {
            "id": "lead", "role": "initial_position", "delivery": "llm",
            "executor_ref": "lead-executor", "model_family": "codex",
        }
        contrary = {
            "id": "contrary", "role": "contrary_position",
            "delivery": "llm", "executor_ref": "contrary-executor",
            "model_family": "claude",
        }
        participants = [lead, contrary]
        request = {
            "workspace_path": root,
            "target_path": "docs/decision.md",
            "request": "Resolve one issue.",
            "context": {
                "brief": "Resolve one issue.",
                "source_payload": {"session_charge": charge},
            },
            "max_rounds": 1,
        }
        store = brainstorming.SessionStore(os.path.join(root, "state"))
        created = store.create(
            "routed",
            request,
            brainstorming.resolve_run_config(
                participants, "unanimity", participants
            ),
            participants,
        )
        store.transition("routed", created.revision, "running")
        reply = {
            "kind": "discussion_turn",
            "markdown": "The focused issue is resolved.",
            "questions": [
                {
                    "id": "turn_environment_fit",
                    "answer": "Checked the surrounding standard.",
                },
                {
                    "id": "turn_human_scale",
                    "answer": "Kept the intervention at request scale.",
                },
            ],
        }
        executor = RecordingExecutor([json.dumps(reply)])
        participant_execution = brainstorming_execution.ParticipantExecution(
            store, {
                "lead-executor": executor,
                "contrary-executor": RecordingExecutor([]),
            }
        )
        subject = brainstorming_coordination.BrainstormingCoordinator(
            store,
            participant_execution,
            turn_preparer=lambda current, participant, round_number,
                                 target, correction: session_calls.prepare_turn(
                                     self.workspace,
                                     current,
                                     participant,
                                     round_number,
                                     target,
                                     correction,
                                 ),
        )
        boundary = {
            "accept_reply": True,
            "committed": False,
            "plan_changed": False,
            "revision": "1" * 40,
            "anchor": None,
        }
        with (
            mock.patch.object(
                brainstorming_coordination,
                "build_turn_prompt",
                side_effect=AssertionError("legacy turn builder reached"),
            ),
            mock.patch.object(
                session_repository,
                "live_target_authority",
                return_value=("repository HEAD live", "present", {}),
            ),
            mock.patch.object(
                session_repository,
                "begin_attempt",
                return_value=types.SimpleNamespace(),
            ),
            mock.patch.object(
                session_repository,
                "complete_attempt",
                return_value=boundary,
            ),
        ):
            completed = subject.run_next_turn("routed", {})

        self.assertEqual(len(completed.state["completed_turns"]), 1)
        self.assertEqual(len(executor.calls), 1)


if __name__ == "__main__":
    unittest.main()
