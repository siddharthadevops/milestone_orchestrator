"""Focused integration proof for Brainstorming slice production."""

import copy
import os
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from orchestrator import brainstorming as bs
from orchestrator import brainstorming_execution as execution
from orchestrator import brainstorming_tasks as adapter
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import gitops
from orchestrator import profiles
from orchestrator import prompts
from orchestrator import runners
from orchestrator import state as st
from orchestrator import tasks
from orchestrator.tests.test_driver_mock import (
    finding,
    fix_ok,
    report,
    step,
    triaged,
)


def usage(n):
    return {
        "input_tokens": n, "cached_input_tokens": 0,
        "output_tokens": n, "reasoning_output_tokens": 0,
        "total_tokens": n * 2,
    }


def task_success(n=2):
    return {
        "status": "success", "duration_s": float(n),
        "token_usage": usage(n), "token_usage_partial": False,
        "cost": {"api_usd": n / 10.0, "real_usd": 0.0},
        "cost_partial": False,
        "native_result": {
            "outcome": "success", "target_ref": "private/agreement.md",
            "transcript_ref": "private/chat.md", "rounds_used": 1,
        },
    }


class EvidenceStore:
    def __init__(self, participant, fresh=False):
        self.events = []
        self.attempt = {"task_id": "task-1", "token": "effect-1", "started_at": 1.0}
        self.snapshot = types.SimpleNamespace(state={
            "status": "success",
            "result": {"outcome": "success", "rounds_used": 1},
            "request": {"workspace_path": "/workspace"},
            "run_config": {"participants": [participant]},
            "participant_sessions": {} if fresh else {participant["id"]: "lead:thread-1"},
        })

    def read(self, _session_id):
        return self.snapshot

    def read_turn_attempt(self, _session_id):
        return None

    def read_external_intervention(self, _session_id):
        return None

    def read_task_effect_attempt(self, _session_id):
        return self.attempt

    def read_activity(self, _session_id):
        return {"schema_version": 1, "events": copy.deepcopy(self.events)}

    def save_activity_output(self, _session_id, event_id, _raw):
        return event_id + ".txt"

    def append_activity(self, _session_id, event):
        self.events.append(bs.validate_activity_event(event))


class BrainstormingSliceProductionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="brainstorming-production-")
        self.addCleanup(self.tmp.cleanup)
        self.workspace = os.path.join(self.tmp.name, "workspace")
        config = copy.deepcopy(drv.DEFAULT_CONFIG)
        config["docs_dir"] = "docs"
        self.path = drv.init_run("Produce one mixed slice.", self.workspace, config=config)
        os.makedirs(os.path.join(self.workspace, "docs"), exist_ok=True)
        with open(os.path.join(self.workspace, "docs", "skeleton.md"), "w", encoding="utf-8") as handle:
            handle.write("# Skeleton\n")

    def planned(self, note_executor, implement_executor):
        state = st.load(self.path)
        state["milestone"]["slices"] = [{
            "id": 1,
            "title": "Mixed producers",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": note_executor},
                "implement": {"task_executor": implement_executor},
            },
        }]
        state["units"][0].update({"status": st.U_SEALED, "artifact": "docs/skeleton.md"})
        state["units"].extend([
            st._new_unit(st.UNIT_SLICE_DOC, 1),
            st._new_unit(st.UNIT_SLICE_IMPL, 1),
        ])
        st.save(self.path, state)

    @staticmethod
    def staffing(*_args, **_kwargs):
        return {
            "dispatch_authority": "static",
            "participants": [{
                "id": "initial-position", "role": "initial_position",
                "delivery": "llm", "executor_ref": "codex-primary",
                "model_family": "codex", "model": "lead-pin", "effort": "high",
            }],
        }

    def finish_success(self, state, task_id, _home, _session, _callback, **_kwargs):
        return tasks.record_task_result(state, task_id, task_success())

    def guarded_production(self, name):
        workspace = os.path.join(self.tmp.name, name)
        os.makedirs(workspace)
        subprocess.run(
            ["git", "init", "-q"], cwd=workspace, check=True,
            capture_output=True, text=True,
        )
        config = copy.deepcopy(drv.DEFAULT_CONFIG)
        config["docs_dir"] = "docs"
        config["git"] = {"enabled": True}
        path = drv.init_run(
            "Produce one guarded slice.", workspace, config=config
        )
        os.makedirs(os.path.join(workspace, "docs"), exist_ok=True)
        skeleton_path = os.path.join(workspace, "docs", "skeleton.md")
        with open(skeleton_path, "w", encoding="utf-8") as handle:
            handle.write("# Sealed skeleton\n")
        state = st.load(path)
        state["milestone"]["slices"] = [{
            "id": 1,
            "title": "Guarded producer",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "brainstorming"},
                "implement": {"task_executor": "agent_call"},
            },
        }]
        state["units"][0].update({
            "status": st.U_SEALED,
            "artifact": "docs/skeleton.md",
        })
        state["units"].extend([
            st._new_unit(st.UNIT_SLICE_DOC, 1),
            st._new_unit(st.UNIT_SLICE_IMPL, 1),
        ])
        st.save(path, state)

        subject = drv.Driver(path, runner=runners.MockRunner([]))
        subject.state["units"][0]["gate_commit"] = gitops.head_sha(workspace)
        subject._save()
        with mock.patch.object(
            adapter, "resolve_staffing", side_effect=self.staffing
        ), mock.patch.object(
            adapter, "start_task", return_value={"id": "failed-session"}
        ):
            subject.step()
        return subject, workspace, skeleton_path

    def ready_brainstorming_implementation(self, runner=None):
        self.planned("agent_call", "brainstorming")
        state = st.load(self.path)
        state["config"]["families_order"] = ["codex"]
        state["config"]["p3_reclassify_debt"] = False
        note = state["units"][1]
        note.update({
            "status": st.U_SEALED,
            "artifact": "docs/slice-01.md",
        })
        with open(
            os.path.join(self.workspace, note["artifact"]),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("# Slice 01\n")
        st.save(self.path, state)
        return drv.Driver(
            self.path,
            runner=runner if runner is not None else runners.MockRunner([]),
        )

    def complete_brainstorming_implementation(self, subject, result=None):
        result = copy.deepcopy(result or task_success())
        with mock.patch.object(
            adapter, "resolve_staffing", side_effect=self.staffing
        ), mock.patch.object(
            adapter, "start_task", return_value={"id": "session-impl"}
        ):
            subject.step()
        task_id = st.current_unit(subject.state)["active_task"]["id"]

        def finish(state, current_task_id, *_args, **_kwargs):
            return tasks.record_task_result(
                state, current_task_id, copy.deepcopy(result)
            )

        with mock.patch.object(adapter, "finish_task", side_effect=finish):
            subject.step()
        return task_id

    def drive_until_closed(self, subject, max_steps=30):
        for _index in range(max_steps):
            if subject.state["milestone"]["status"] == st.M_CLOSED:
                return
            subject.step()
        self.fail("milestone did not close within %d steps" % max_steps)

    def test_brainstorming_note_waits_replaces_path_then_worker_implements(self):
        self.planned("brainstorming", "agent_call")
        worker = {
            "status": "ok", "kind": contracts.KIND_IMPLEMENT,
            "files_changed": [], "suite_command": "python3 -m unittest focused",
        }
        subject = drv.Driver(self.path, runner=runners.MockRunner([{"response": worker}]))
        with mock.patch.object(adapter, "resolve_staffing", side_effect=self.staffing), \
                mock.patch.object(adapter, "start_task", return_value={"id": "session-note"}):
            subject.step()
        doc = st.current_unit(subject.state)
        predecessor = "docs/old-note.md"
        doc["artifact"] = predecessor
        first_id = doc["active_task"]["id"]
        with mock.patch.object(adapter, "finish_task", return_value=None):
            subject.step()
        self.assertEqual(len(tasks.task_records(subject.state)), 1)
        with mock.patch.object(adapter, "finish_task", side_effect=self.finish_success):
            subject.step()
        self.assertNotEqual(doc["artifact"], predecessor)
        self.assertEqual(doc["draft"]["task_id"], first_id)

        doc["status"] = st.U_SEALED
        subject._save()
        subject.step()
        impl = st.current_unit(subject.state)
        records = tasks.task_records(subject.state)
        self.assertEqual([row["order"]["task_executor"] for row in records],
                         ["brainstorming", "agent_call"])
        self.assertNotEqual(impl["draft"]["task_id"], first_id)

    def test_worker_note_then_target_free_brainstorming_implementation(self):
        self.planned("agent_call", "brainstorming")
        note = {
            "status": "ok", "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "artifact": "docs/custom-note.md",
        }
        subject = drv.Driver(self.path, runner=runners.MockRunner([{"response": note}]))
        subject.step()
        doc = st.current_unit(subject.state)
        self.assertEqual(doc["artifact"], "docs/custom-note.md")
        doc["status"] = st.U_SEALED
        subject._save()
        with mock.patch.object(adapter, "resolve_staffing", side_effect=self.staffing), \
                mock.patch.object(adapter, "start_task", return_value={"id": "session-impl"}):
            subject.step()
        impl = st.current_unit(subject.state)
        record = tasks.task_record(subject.state, impl["active_task"]["id"])
        request = record["order"]["request"]
        self.assertNotIn("target_path", request)
        self.assertIn("docs/custom-note.md", request["request"])
        with mock.patch.object(adapter, "finish_task", side_effect=self.finish_success):
            subject.step()
        self.assertEqual(impl["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual([row["order"]["task_executor"] for row in tasks.task_records(subject.state)],
                         ["agent_call", "brainstorming"])

    def test_brainstorming_implementation_reads_later_skeleton_assignment(self):
        self.planned("agent_call", "brainstorming")
        note = {
            "status": "ok", "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "artifact": "docs/older-note.md",
        }
        subject = drv.Driver(
            self.path, runner=runners.MockRunner([{"response": note}])
        )
        subject.step()
        doc = st.current_unit(subject.state)
        doc["status"] = st.U_SEALED
        st.append_event(
            subject.state,
            "unit_transition",
            unit=st.unit_key(doc),
            to_status=st.U_SEALED,
        )
        st.append_event(
            subject.state,
            "unit_transition",
            unit=st.UNIT_SKELETON,
            to_status=st.U_SEALED,
        )
        subject._save()

        with mock.patch.object(
            adapter, "resolve_staffing", side_effect=self.staffing
        ), mock.patch.object(
            adapter, "start_task", return_value={"id": "session-remodeled"}
        ):
            subject.step()

        impl = st.current_unit(subject.state)
        record = tasks.task_record(subject.state, impl["active_task"]["id"])
        request = record["order"]["request"]
        self.assertIn("UPDATED DESIGN ASSIGNMENT", request["request"])
        self.assertEqual(
            request["reference_documents"],
            ["docs/older-note.md", "docs/skeleton.md"],
        )

    def test_brainstorming_remodel_successor_uses_durable_assignment(self):
        self.planned("agent_call", "brainstorming")
        note = {
            "status": "ok", "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "artifact": "docs/resealed-note.md",
        }
        subject = drv.Driver(
            self.path, runner=runners.MockRunner([{"response": note}])
        )
        subject.step()
        doc = st.current_unit(subject.state)
        doc["status"] = st.U_SEALED
        st.append_event(
            subject.state,
            "unit_transition",
            unit=st.UNIT_SKELETON,
            to_status=st.U_SEALED,
        )
        st.append_event(
            subject.state,
            "unit_transition",
            unit=st.unit_key(doc),
            to_status=st.U_SEALED,
        )
        implementation = subject.state["units"][-1]
        implementation["has_gap_remodel"] = True
        subject._save()

        self.assertFalse(subject._note_predates_skeleton(1))
        with mock.patch.object(
            adapter, "resolve_staffing", side_effect=self.staffing
        ), mock.patch.object(
            adapter, "start_task", return_value={"id": "session-successor"}
        ):
            subject.step()

        record = tasks.task_record(
            subject.state, implementation["active_task"]["id"]
        )
        request = record["order"]["request"]
        self.assertIn("UPDATED DESIGN ASSIGNMENT", request["request"])
        self.assertEqual(
            request["reference_documents"],
            ["docs/resealed-note.md", "docs/skeleton.md"],
        )

    def test_native_failure_preserves_accounting_and_resumes_with_a_distinct_task(self):
        self.planned("brainstorming", "agent_call")
        subject = drv.Driver(self.path, runner=runners.MockRunner([]))
        with mock.patch.object(adapter, "resolve_staffing", side_effect=self.staffing), \
                mock.patch.object(adapter, "start_task", return_value={"id": "failed-session"}):
            subject.step()
        doc = st.current_unit(subject.state)
        failed_id = doc["active_task"]["id"]
        native = {
            "outcome": "failure",
            "reason": "No bounded agreement was reached.",
            "target_ref": "private/agreement.md",
            "transcript_ref": "private/chat.md",
            "rounds_used": 1,
        }

        def fail(state, task_id, *_args, **_kwargs):
            result = task_success()
            result.update({
                "status": "failure",
                "reason": "No bounded agreement was reached.",
                "native_result": native,
            })
            return tasks.record_task_result(state, task_id, result)

        with mock.patch.object(adapter, "finish_task", side_effect=fail):
            subject.step()
        failed = tasks.task_record(subject.state, failed_id)
        self.assertIsNone(doc["draft"])
        self.assertEqual(failed["result"]["native_result"], native)
        summary = st.summary(subject.state)
        self.assertEqual(summary["work_duration_s"], 2.0)
        self.assertEqual(summary["work_token_usage"], usage(2))
        self.assertFalse(summary["work_token_usage_partial"])
        self.assertEqual(
            summary["work_cost"],
            {"api_usd": 0.2, "real_usd": 0.0},
        )
        self.assertFalse(summary["work_cost_partial"])
        work = [
            event for event in subject.state["events"]
            if event.get("type") == "brainstorming_work_recorded"
        ]
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["task_id"], failed_id)
        st.resume_run(subject.state)
        subject._save()
        with mock.patch.object(adapter, "resolve_staffing", side_effect=self.staffing), \
                mock.patch.object(adapter, "start_task", return_value={"id": "successor-session"}):
            subject.step()
        successor = st.current_unit(subject.state)["active_task"]["id"]
        self.assertNotEqual(successor, failed_id)
        self.assertEqual(tasks.task_record(subject.state, failed_id), failed)

    def test_effect_failure_keeps_partial_work_and_implementation_successor(self):
        subject = self.ready_brainstorming_implementation()
        plan = subject.state["milestone"]["slices"][0]
        plan["producer_task_executor"]["implement"]["configuration"] = {
            "max_rounds": 3,
        }
        subject._save()
        with mock.patch.object(
            adapter, "resolve_staffing", side_effect=self.staffing
        ), mock.patch.object(
            adapter, "start_task", return_value={"id": "failed-impl-session"}
        ):
            subject.step()
        impl = st.current_unit(subject.state)
        failed_id = impl["active_task"]["id"]
        partial_path = os.path.join(self.workspace, "partial-effect.txt")
        native = copy.deepcopy(task_success()["native_result"])

        def fail_effect(state, task_id, *_args, **_kwargs):
            with open(partial_path, "w", encoding="utf-8") as handle:
                handle.write("survives terminal failure\n")
            return tasks.record_task_result(state, task_id, {
                "status": "failure",
                "reason": "production effects were incomplete",
                "duration_s": 3.0,
                "token_usage": usage(2),
                "token_usage_partial": True,
                "cost": {"api_usd": 0.2, "real_usd": 0.0},
                "cost_partial": True,
                "native_result": native,
            })

        with mock.patch.object(adapter, "finish_task", side_effect=fail_effect):
            subject.step()
        predecessor = copy.deepcopy(tasks.task_record(subject.state, failed_id))
        self.assertIsNone(impl["draft"])
        self.assertTrue(os.path.isfile(partial_path))
        self.assertEqual(predecessor["result"]["native_result"], native)
        summary = st.summary(subject.state)
        self.assertEqual(summary["work_duration_s"], 3.0)
        self.assertEqual(summary["work_token_usage"], usage(2))
        self.assertTrue(summary["work_token_usage_partial"])
        self.assertEqual(
            summary["work_cost"], {"api_usd": 0.2, "real_usd": 0.0}
        )
        self.assertTrue(summary["work_cost_partial"])
        work = [
            event for event in subject.state["events"]
            if event.get("type") == "brainstorming_work_recorded"
        ]
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["task_id"], failed_id)

        plan["producer_task_executor"]["implement"]["configuration"] = {
            "max_rounds": 7,
        }
        st.resume_run(subject.state)
        subject._save()
        with mock.patch.object(
            adapter, "resolve_staffing", side_effect=self.staffing
        ), mock.patch.object(
            adapter, "start_task", return_value={"id": "successor-session"}
        ):
            subject.step()
        successor_id = st.current_unit(subject.state)["active_task"]["id"]
        successor = tasks.task_record(subject.state, successor_id)
        self.assertNotEqual(successor_id, failed_id)
        self.assertEqual(successor["order"]["configuration"]["max_rounds"], 7)
        self.assertEqual(tasks.task_record(subject.state, failed_id), predecessor)
        self.assertEqual(st.summary(subject.state)["work_duration_s"], 3.0)

    def test_success_accounting_has_one_existing_run_home(self):
        subject = self.ready_brainstorming_implementation()
        task_id = self.complete_brainstorming_implementation(
            subject, task_success(5)
        )
        impl = st.current_unit(subject.state)
        task = tasks.task_record(subject.state, task_id)
        self.assertEqual(impl["draft"]["task_id"], task_id)
        self.assertEqual(impl["draft"]["duration_s"], 5.0)
        self.assertEqual(task["result"]["duration_s"], 5.0)
        self.assertFalse([
            event for event in subject.state["events"]
            if event.get("type") == "brainstorming_work_recorded"
        ])
        summary = st.summary(subject.state)
        self.assertEqual(summary["work_duration_s"], 5.0)
        self.assertEqual(summary["work_token_usage"], usage(5))
        self.assertFalse(summary["work_token_usage_partial"])
        self.assertEqual(
            summary["work_cost"], {"api_usd": 0.5, "real_usd": 0.0}
        )
        self.assertFalse(summary["work_cost_partial"])

    def test_terminal_failure_restores_sealed_artifact_before_stopping(self):
        subject, workspace, skeleton_path = self.guarded_production(
            "guarded-terminal-workspace"
        )
        doc = st.current_unit(subject.state)
        failed_id = doc["active_task"]["id"]

        def fail_after_tamper(state, task_id, *_args, **_kwargs):
            with open(skeleton_path, "w", encoding="utf-8") as handle:
                handle.write("# Rewritten by failed producer\n")
            result = task_success()
            result.update({"status": "failure", "reason": "effect refused"})
            return tasks.record_task_result(state, task_id, result)

        with mock.patch.object(
            adapter, "finish_task", side_effect=fail_after_tamper
        ):
            subject.step()

        with open(skeleton_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "# Sealed skeleton\n")
        restored = [
            event for event in subject.state["events"]
            if event.get("type") == "sealed_artifact_restored"
        ]
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["artifact"], "docs/skeleton.md")
        with open(
            os.path.join(workspace, restored[0]["raw_path"]),
            encoding="utf-8",
        ) as handle:
            self.assertIn("Rewritten by failed producer", handle.read())
        self.assertIsNotNone(subject.state["failure"])
        self.assertEqual(
            tasks.task_record(subject.state, failed_id)["result"]["reason"],
            "effect refused",
        )

    def test_operational_effect_failure_restores_sealed_artifact(self):
        subject, workspace, skeleton_path = self.guarded_production(
            "guarded-operational-workspace"
        )
        task_id = st.current_unit(subject.state)["active_task"]["id"]

        def raise_after_tamper(*_args, **_kwargs):
            with open(skeleton_path, "w", encoding="utf-8") as handle:
                handle.write("# Rewritten before operational failure\n")
            raise OSError("effect evidence unavailable")

        with mock.patch.object(
            adapter, "finish_task", side_effect=raise_after_tamper
        ):
            subject.step()

        with open(skeleton_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "# Sealed skeleton\n")
        restored = [
            event for event in subject.state["events"]
            if event.get("type") == "sealed_artifact_restored"
        ]
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["artifact"], "docs/skeleton.md")
        with open(
            os.path.join(workspace, restored[0]["raw_path"]),
            encoding="utf-8",
        ) as handle:
            self.assertIn("operational failure", handle.read())
        self.assertIsNotNone(subject.state["failure"])
        self.assertIsNone(tasks.task_record(subject.state, task_id)["result"])

    def test_pre_session_io_failure_terminalizes_admitted_task(self):
        self.planned("brainstorming", "agent_call")
        subject = drv.Driver(self.path, runner=runners.MockRunner([]))
        home = os.path.join(self.tmp.name, "pre-session-home")
        with mock.patch.object(
            adapter, "resolve_staffing", side_effect=self.staffing
        ), mock.patch.object(
            adapter, "_frozen_participants", return_value=[]
        ), mock.patch.object(
            adapter, "_private_target", side_effect=OSError("read-only store")
        ), mock.patch.object(
            drv.brainstorming_milestone, "service_home", return_value=home
        ):
            subject.step()

        task = tasks.task_records(subject.state)[0]
        self.assertEqual(task["result"]["status"], "failure")
        self.assertEqual(
            task["result"]["reason"],
            "Brainstorming session admission failed: brainstorming_unavailable",
        )
        self.assertFalse(task["result"]["token_usage_partial"])
        self.assertFalse(task["result"]["cost_partial"])
        self.assertIsNone(st.current_unit(subject.state).get("active_task"))
        self.assertIsNotNone(subject.state["failure"])

    def test_lifecycle_lock_io_failure_keeps_admitted_task_recoverable(self):
        self.planned("brainstorming", "agent_call")
        subject = drv.Driver(self.path, runner=runners.MockRunner([]))
        refused_lock = mock.MagicMock()
        refused_lock.__enter__.side_effect = OSError("read-only lock store")

        with mock.patch.object(
            adapter, "resolve_staffing", side_effect=self.staffing
        ), mock.patch.object(
            adapter.brainstorming,
            "_exclusive_transcript",
            return_value=refused_lock,
        ):
            subject.step()

        task = tasks.task_records(subject.state)[0]
        self.assertIsNone(task["result"])
        self.assertEqual(
            st.current_unit(subject.state)["active_task"]["id"], task["id"]
        )
        self.assertIsNotNone(subject.state["failure"])

    def test_production_completion_ignores_incidental_untyped_json(self):
        completion, closers = runners._extract_contract_output(
            'fixture {"completed":false,"reason":"effect refused"}\n'
            '{"kind":"production_completion","completed":true}',
            adapter.validate_production_completion,
        )
        self.assertEqual(
            completion,
            {"kind": "production_completion", "completed": True},
        )
        self.assertIsNone(closers)

    def test_production_calls_record_current_or_static_lead_staffing(self):
        participant = {
            "id": "initial-position", "role": "initial_position",
            "delivery": "llm", "executor_ref": "lead",
            "model_family": "codex",
        }
        cases = (
            (False, "codex", "static-model", "high", None),
            (True, "claude", "current-model", "max",
             lambda _round: {"agent": "claude", "model": "current-model",
                             "effort": "max"}),
        )
        for fresh, family, model, effort, resolver in cases:
            with self.subTest(fresh=fresh):
                store = EvidenceStore(participant, fresh=fresh)
                runner = runners.MockRunner([{
                    "expect_family": family,
                    "response": {
                        "kind": "production_completion",
                        "completed": True,
                    },
                }])
                runner.supports_session_continuation = lambda _family: True
                binding = execution.RunnerParticipantExecutor(
                    "codex", runner, model=model, effort=effort,
                    current_resolver=resolver, fresh_each_call=fresh,
                )
                binding.wait_for_quiescence = lambda _result: True
                subject = execution.ParticipantExecution(store, {"lead": binding})
                subject.production_effect("session", "apply", {},
                                          adapter.validate_production_completion)
                event = store.events[-1]
                self.assertEqual((event["model_family"], event["model"], event["effort"]),
                                 (family, model, effort))
                self.assertEqual(event["kind"], "production_effect")

    def test_empty_suite_handoff_is_unknown_and_armed_evidence_stays_out_of_review(self):
        empty = prompts.build_review_round(
            "codex", self.workspace, "goal", "implementation", "(workspace)", [],
            unit_kind=st.UNIT_SLICE_IMPL, verification_commands=[],
        )
        armed = prompts.build_review_round(
            "codex", self.workspace, "goal", "implementation", "(workspace)", [],
            unit_kind=st.UNIT_SLICE_IMPL,
            verification_commands=["python3 -m unittest discover -s tests"],
        )
        self.assertIn("empty list is unknown", empty)
        self.assertIn("missing command as a finding", empty)
        self.assertNotIn("python3 -m unittest discover -s tests", armed)
        self.assertNotIn("Judge whether these commands", armed)

        self.planned("agent_call", "agent_call")
        worker = {
            "status": "ok", "kind": contracts.KIND_IMPLEMENT,
            "files_changed": [],
        }
        worker_subject = drv.Driver(
            self.path,
            runner=runners.MockRunner([{"response": worker}]),
        )
        worker_subject.state["units"][1]["status"] = st.U_SEALED
        worker_subject._save()
        worker_subject.step()
        worker_unit = st.current_unit(worker_subject.state)
        self.assertIsNone(
            worker_subject._review_verification_commands(worker_unit)
        )

        brainstorming_path = drv.init_run(
            "Produce one Brainstorming slice.", self.workspace + "-brainstorming",
            config=copy.deepcopy(drv.DEFAULT_CONFIG),
        )
        state = st.load(brainstorming_path)
        state["milestone"]["slices"] = [{
            "id": 1,
            "title": "Brainstorming implementation",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "brainstorming"},
            },
        }]
        state["units"].extend([
            st._new_unit(st.UNIT_SLICE_DOC, 1),
            st._new_unit(st.UNIT_SLICE_IMPL, 1),
        ])
        impl = state["units"][-1]
        order = tasks.producer_order(
            state["milestone"]["slices"][0],
            contracts.KIND_IMPLEMENT,
            {
                "work_area": {"workspace_path": self.workspace + "-brainstorming"},
                "request": "Implement the slice.",
                "context": {},
                "reference_documents": [],
            },
        )
        task = tasks.admit_task(
            state,
            order,
            {"dispatch_authority": "static", "participants": [{
                "id": "initial-position", "role": "initial_position",
                "delivery": "llm", "executor_ref": "codex-primary",
                "model_family": "codex", "model": "lead-pin",
                "effort": "high",
            }]},
            self.workspace + "-brainstorming",
        )
        st.save(brainstorming_path, state)
        tasks.record_task_result(state, task["id"], task_success())
        impl["draft"] = {
            "kind": contracts.KIND_IMPLEMENT,
            "task_id": task["id"],
            "result": {"status": "ok", "kind": contracts.KIND_IMPLEMENT,
                       "files_changed": []},
        }
        st.save(brainstorming_path, state)
        subject = drv.Driver(brainstorming_path, runner=runners.MockRunner([]))
        unit = subject.state["units"][-1]
        self.assertEqual(subject._review_verification_commands(unit), [])
        before = subject._review_evidence_fingerprint(unit)
        st.set_discovered_suite(
            subject.state, "python3 -m unittest discover -s tests"
        )
        after = subject._review_evidence_fingerprint(unit)
        self.assertNotEqual(before, after)

    def test_ancillary_task_kinds_remain_worker_owned(self):
        kinds = (
            contracts.KIND_DRAFT_SKELETON,
            contracts.KIND_REVIEW_ROUND,
            contracts.KIND_DELTA_REVIEW,
            contracts.KIND_FIX_FINDINGS,
        )
        admitted = []
        for kind in kinds:
            with self.subTest(kind=kind):
                workspace = os.path.join(self.tmp.name, "ancillary-" + kind)
                path = drv.init_run(
                    "Keep ancillary work on Worker.", workspace,
                    config=copy.deepcopy(drv.DEFAULT_CONFIG),
                )
                state = st.load(path)
                state["milestone"]["slices"] = [{
                    "id": 1,
                    "title": "Brainstorming producers",
                    "producer_task_executor": {
                        "draft_slice_note": {
                            "task_executor": "brainstorming"
                        },
                        "implement": {"task_executor": "brainstorming"},
                    },
                }]
                st.save(path, state)
                subject = drv.Driver(path, runner=runners.MockRunner([]))
                unit = st.current_unit(subject.state)
                record = subject._admit_worker_task(
                    unit, kind, "perform %s" % kind, "codex"
                )
                admitted.append(record["order"]["task_executor"])
                self.assertEqual(record["order"]["task_executor"], "agent_call")
                self.assertEqual(
                    tasks.effective_slice_producers(
                        subject.state["milestone"]["slices"][0]
                    ),
                    {
                        "draft_slice_note": {
                            "task_executor": "brainstorming"
                        },
                        "implement": {"task_executor": "brainstorming"},
                    },
                )
        self.assertEqual(admitted, ["agent_call"] * len(kinds))

    def test_empty_suite_finding_arms_and_runs_the_final_checkpoint_once(self):
        command = "python3 -m unittest discover -s tests -t ."
        summary = "official suite command is missing"
        runner = runners.MockRunner([
            step(
                contracts.KIND_REVIEW_ROUND,
                report(
                    contracts.KIND_REVIEW_ROUND,
                    [finding("F1", summary, severity="P1")],
                ),
                family="codex",
            ),
            step(
                contracts.KIND_FIX_FINDINGS,
                dict(
                    fix_ok([
                        triaged("F1", "fixed", summary, severity="P1")
                    ]),
                    suite_command=command,
                    suite_command_finding_id="F1",
                ),
                family="codex",
            ),
            step(
                contracts.KIND_REVIEW_ROUND,
                report(contracts.KIND_REVIEW_ROUND),
                family="codex",
            ),
        ])
        subject = self.ready_brainstorming_implementation(runner)
        task_id = self.complete_brainstorming_implementation(subject)
        with mock.patch.object(
            drv, "run_verification", return_value=(True, "suite passed")
        ) as verify:
            self.drive_until_closed(subject)

        verify.assert_called_once_with(
            [command], self.workspace, subject.config.get("verification_timeout")
        )
        self.assertEqual(subject.state["suite_command"], command)
        implementation = subject.state["units"][-1]
        reviews = [
            round_info for round_info in implementation["rounds"]
            if round_info["kind"] == contracts.KIND_REVIEW_ROUND
        ]
        self.assertEqual(len(reviews), 2)
        self.assertNotEqual(
            reviews[0]["evidence_fingerprint"],
            reviews[1]["evidence_fingerprint"],
        )
        self.assertEqual(
            reviews[1]["evidence_fingerprint"],
            implementation["review_evidence_fingerprint"],
        )
        verifications = [
            event for event in subject.state["events"]
            if event.get("type") == "verification"
        ]
        self.assertEqual(len(verifications), 1)
        self.assertEqual(verifications[0]["commands"], [command])
        self.assertFalse(verifications[0].get("vacuous"))
        self.assertEqual(verifications[0]["cadence"], "milestone_final")
        records = tasks.task_records(subject.state)
        self.assertEqual(records[0]["id"], task_id)
        self.assertEqual(records[0]["order"]["task_executor"], "brainstorming")
        self.assertEqual(
            [record["order"]["task_executor"] for record in records[1:]],
            ["agent_call", "agent_call", "agent_call"],
        )
        self.assertIn("empty list is unknown", runner.calls[0][2])
        self.assertFalse(runner.script)

    def test_confirmed_no_suite_seals_with_one_vacuous_final_checkpoint(self):
        runner = runners.MockRunner([
            step(
                contracts.KIND_REVIEW_ROUND,
                report(contracts.KIND_REVIEW_ROUND),
                family="codex",
            ),
        ])
        subject = self.ready_brainstorming_implementation(runner)
        self.complete_brainstorming_implementation(subject)
        with mock.patch.object(
            drv, "run_verification", return_value=(True, "")
        ) as verify:
            self.drive_until_closed(subject)

        verify.assert_called_once_with(
            [], self.workspace, subject.config.get("verification_timeout")
        )
        self.assertIsNone(subject.state["suite_command"])
        verifications = [
            event for event in subject.state["events"]
            if event.get("type") == "verification"
        ]
        self.assertEqual(len(verifications), 1)
        self.assertEqual(verifications[0]["commands"], [])
        self.assertTrue(verifications[0]["vacuous"])
        self.assertEqual(verifications[0]["cadence"], "milestone_final")
        self.assertEqual(subject.state["milestone"]["status"], st.M_CLOSED)
        self.assertIn("empty list is unknown", runner.calls[0][2])
        self.assertFalse(runner.script)

    def test_delta_review_does_not_rejudge_suite_handoff(self):
        prompt = prompts.build_delta_review(
            "codex", self.workspace, "goal", "implementation", [],
            unit_kind=st.UNIT_SLICE_IMPL,
        )
        self.assertNotIn("Scheduled full-suite commands", prompt)
        self.assertNotIn("empty list is unknown", prompt)

    def test_brainstorming_note_inherits_document_obligations(self):
        self.planned("brainstorming", "agent_call")
        subject = drv.Driver(self.path, runner=runners.MockRunner([]))
        subject.state["config"]["profile"] = copy.deepcopy(
            profiles.SEEDS["light"]["profile"]
        )
        unit = st.current_unit(subject.state)
        request, _planned = subject._brainstorming_production_request(
            unit, contracts.KIND_DRAFT_SLICE_NOTE
        )
        prompt = request["request"]
        compact = " ".join(prompt.split())
        self.assertIn("TWO-REGISTER DOCUMENT", prompt)
        self.assertIn("PINNED-FACTS TABLE", prompt)
        self.assertIn("QUESTION BATTERY", prompt)
        for question in contracts.BATTERY_QUESTIONS_SLICE_NOTE:
            self.assertIn("- %s:" % question, prompt)
        self.assertIn("SLICE NOTE CONTENT", prompt)
        self.assertIn("as observable contracts, not implementation detail", prompt)
        self.assertIn("strict (serialized or", prompt)
        self.assertIn("record the reason in the slice note", compact)
        self.assertIn("ALTITUDE (documentation discipline)", prompt)
        self.assertIn("Include one short `Reuse Posture` section", prompt)


if __name__ == "__main__":
    unittest.main()
