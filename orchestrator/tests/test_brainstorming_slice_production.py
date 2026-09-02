"""Focused integration proof for Brainstorming slice production."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming_tasks as adapter
from orchestrator import canonical_plan
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st
from orchestrator import tasks
from orchestrator.tests.test_driver_mock import (
    prompt_response,
    report as legacy_report,
    step,
    write_file,
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
        "native_result": {"outcome": "success", "rounds_used": 1},
    }


def report(kind, findings=()):
    return legacy_report(kind, findings)


def canonical_skeleton(note_executor, implement_executor, title="Mixed producers"):
    plan = {
        "slices": [{
            "id": 1,
            "title": title,
            "intent": "Exercise one mixed producer slice.",
            "producer_task_executor": {
                "draft_slice_note": note_executor,
                "implement": implement_executor,
            },
        }],
    }
    return (
        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
        % json.dumps(plan, separators=(",", ":"))
    )


def suite_checkpoint_response(status, commands):
    response = {
        "status": status,
        "kind": "suite_checkpoint",
        "commands": list(commands),
        "results": [
            {
                "command": command,
                "exit_code": 0,
                "evidence": "complete suite passed",
            }
            for command in commands
        ],
        "authority": {
            "source": "operator_config" if commands else "repository",
            "evidence": [] if commands else [{
                "path": "docs/skeleton.md",
                "basis": "No complete suite is configured or declared.",
            }],
        },
    }
    return response


class BrainstormingSliceProductionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="brainstorming-production-")
        self.addCleanup(self.tmp.cleanup)
        self.workspace = os.path.join(self.tmp.name, "workspace")
        self._init_git(self.workspace)
        config = copy.deepcopy(drv.DEFAULT_CONFIG)
        config["docs_dir"] = "docs"
        config["git"] = {"enabled": True}
        self.path = drv.init_run("Produce one mixed slice.", self.workspace, config=config)
        # This retained matrix exercises the direct slice-production law that
        # predates reviewed skeletons, deep slices, and sibling verification.
        state = st.load(self.path)
        for key in (
            st.SKELETON_COMPOSITION_KEY,
            st.DEEP_SLICE_COMPOSITION_KEY,
            st.MILESTONE_VERIFICATION_CADENCE_KEY,
        ):
            state["milestone"].pop(key, None)
        st.save(self.path, state)

    @staticmethod
    def _git(workspace, *args):
        return subprocess.run(
            ("git",) + args,
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _init_git(self, workspace):
        os.makedirs(workspace, exist_ok=True)
        self._git(workspace, "init", "-q")
        self._git(workspace, "config", "user.name", "Brainstorming Test")
        self._git(
            workspace,
            "config",
            "user.email",
            "brainstorming@example.invalid",
        )

    def _install_plan(
        self,
        path,
        workspace,
        note_executor,
        implement_executor,
        title="Mixed producers",
    ):
        skeleton_path = "docs/skeleton.md"
        absolute = os.path.join(workspace, skeleton_path)
        os.makedirs(os.path.dirname(absolute), exist_ok=True)
        with open(absolute, "w", encoding="utf-8") as handle:
            handle.write(canonical_skeleton(
                note_executor, implement_executor, title=title
            ))
        self._git(workspace, "add", skeleton_path)
        self._git(workspace, "commit", "-q", "-m", "canonical plan")
        head = self._git(workspace, "rev-parse", "HEAD")

        state = st.load(path)
        canonical_plan.establish_current_plan(state, skeleton_path)
        state["units"][0].update({
            "status": st.U_SEALED,
            "artifact": skeleton_path,
            "gate_commit": head,
        })
        state["units"].extend([
            st._new_unit(st.UNIT_SLICE_DOC, 1),
            st._new_unit(st.UNIT_SLICE_IMPL, 1),
        ])
        st.save(path, state)
        return state

    def planned(self, note_executor, implement_executor):
        return self._install_plan(
            self.path,
            self.workspace,
            note_executor,
            implement_executor,
        )

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

    def finish_success(self, state, task_id, *_args, **_kwargs):
        return self._record_repository_success(state, task_id)

    def _record_repository_success(self, state, task_id, result=None):
        record = tasks.task_record(state, task_id)
        request = record["order"]["request"]
        context = request["context"]
        source = context["session_charge"]["repository"][
            "pre_session_commit"
        ]
        kind = context["task_kind"]
        if kind == contracts.KIND_DRAFT_SLICE_NOTE:
            relative = context["planned_slice_note_path"]
            body = "# Slice 01\n"
        else:
            relative = "brainstorming-implementation.txt"
            body = "implemented in repository session\n"
        absolute = os.path.join(state["workspace"], relative)
        os.makedirs(os.path.dirname(absolute), exist_ok=True)
        with open(absolute, "w", encoding="utf-8") as handle:
            handle.write(body)
        self._git(state["workspace"], "add", relative)
        self._git(
            state["workspace"],
            "commit", "-q", "-m", "Brainstorming repository delivery",
        )
        accepted = self._git(state["workspace"], "rev-parse", "HEAD")
        envelope = copy.deepcopy(result or task_success())
        envelope["native_result"] = {
            **copy.deepcopy(envelope.get("native_result") or {}),
            "source_base_revision": source,
            "accepted_revision": accepted,
        }
        return tasks.record_task_result(state, task_id, envelope)

    def ready_brainstorming_implementation(self, runner=None, verification=None):
        self.planned("agent_call", "brainstorming")
        state = st.load(self.path)
        state["config"]["families_order"] = ["codex"]
        state["config"]["p3_reclassify_debt"] = False
        if verification is not None:
            state["config"]["verification"] = list(verification)
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
        self._git(self.workspace, "add", note["artifact"])
        self._git(
            self.workspace, "commit", "-q", "-m", "reviewed slice note"
        )
        note["gate_commit"] = self._git(
            self.workspace, "rev-parse", "HEAD"
        )
        st.save(self.path, state)
        subject = drv.Driver(
            self.path,
            runner=runner if runner is not None else runners.MockRunner([]),
        )
        subject.reviewed_work.configure(
            st.current_unit(subject.state), {"review_breadth": "single"}
        )
        return subject

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
            return self._record_repository_success(
                state, current_task_id, result=result
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
        worker = prompt_response({
            "status": "ok", "kind": contracts.KIND_IMPLEMENT,
            "files_changed": ["worker-implementation.txt"],
        })
        subject = drv.Driver(self.path, runner=runners.MockRunner([{
            "response": worker,
            "side_effect": write_file(
                "worker-implementation.txt", "implemented by agent call\n"
            ),
        }]))
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
        doc = st.current_unit(subject.state)
        self.assertNotEqual(doc["artifact"], predecessor)
        self.assertEqual(doc["draft"]["task_id"], first_id)

        doc["status"] = st.U_SEALED
        subject._save()
        subject.step()
        impl = st.current_unit(subject.state)
        records = tasks.task_records(subject.state)
        self.assertEqual([row["order"]["task_executor"] for row in records],
                         ["brainstorming"])
        self.assertNotIn("task_id", impl["draft"])

    def test_worker_note_then_target_free_brainstorming_implementation(self):
        self.planned("agent_call", "brainstorming")
        note = prompt_response({
            "status": "ok", "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "artifact": "docs/custom-note.md",
        })
        subject = drv.Driver(self.path, runner=runners.MockRunner([{
            "response": note,
            "side_effect": write_file("docs/custom-note.md", "# Custom note\n"),
        }]))
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
        impl = st.current_unit(subject.state)
        self.assertEqual(impl["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual([row["order"]["task_executor"] for row in tasks.task_records(subject.state)],
                         ["brainstorming"])

    def test_brainstorming_implementation_never_activates_size_control(self):
        subject = self.ready_brainstorming_implementation()
        implementation = st.current_unit(subject.state)
        with self.assertRaises(tasks.TaskRequestError):
            subject.reviewed_work.configure(implementation, {
                "implementation_size_control": {
                    "soft_lines": 2,
                    "hard_lines": 4,
                    "unconfirmed_grace_s": 3,
                    "confirmed_grace_s": 7,
                },
            })

        with mock.patch.object(
            adapter, "resolve_staffing", side_effect=self.staffing
        ), mock.patch.object(
            adapter, "start_task", return_value={"id": "session-size"}
        ):
            subject.step()

        implementation = st.current_unit(subject.state)
        task_id = implementation["active_task"]["id"]
        record = tasks.task_record(subject.state, task_id)
        values = record["order"]["request"]["context"]["session_charge"][
            "values"
        ]
        self.assertIsNone(
            subject._implementation_size_settings(implementation)
        )
        self.assertNotIn("soft_lines", values)
        self.assertNotIn("hard_lines", values)
        self.assertNotIn("implementation_attempt_snapshot", implementation)
        self.assertNotIn(
            "implementation_size", implementation["brainstorming_wait"]
        )

        write_file(
            "oversized.py", "one\ntwo\nthree\nfour\nfive\n"
        )(self.workspace)
        self._git(self.workspace, "add", "oversized.py")
        with mock.patch.object(
            adapter, "finish_task", side_effect=self.finish_success
        ):
            subject.step()

        implementation = st.current_unit(subject.state)
        self.assertEqual(implementation["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertNotIn("implementation_cut", implementation)
        self.assertNotIn("implementation_stabilization", implementation)
        self.assertFalse(any(
            event["type"].startswith("implementation_size_")
            for event in subject.state["events"]
        ))

    def test_brainstorming_implementation_reads_later_skeleton_assignment(self):
        self.planned("agent_call", "brainstorming")
        note = prompt_response({
            "status": "ok", "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "artifact": "docs/older-note.md",
        })
        subject = drv.Driver(
            self.path, runner=runners.MockRunner([{
                "response": note,
                "side_effect": write_file("docs/older-note.md", "# Older note\n"),
            }])
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
        self.assertEqual(
            request["reference_documents"],
            ["docs/older-note.md", "docs/skeleton.md"],
        )

    def test_brainstorming_remodel_successor_uses_durable_assignment(self):
        self.planned("agent_call", "brainstorming")
        note = prompt_response({
            "status": "ok", "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "artifact": "docs/resealed-note.md",
        })
        subject = drv.Driver(
            self.path, runner=runners.MockRunner([{
                "response": note,
                "side_effect": write_file(
                    "docs/resealed-note.md", "# Resealed note\n"
                ),
            }])
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
        self.assertEqual(successor["order"]["task_executor"], "brainstorming")
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
                self._init_git(workspace)
                config = copy.deepcopy(drv.DEFAULT_CONFIG)
                config["git"] = {"enabled": True}
                path = drv.init_run(
                    "Keep ancillary work on Worker.", workspace,
                    config=config,
                )
                self._install_plan(
                    path,
                    workspace,
                    "brainstorming",
                    "brainstorming",
                    title="Brainstorming producers",
                )
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

    def test_configured_suite_runs_one_final_llm_checkpoint(self):
        command = "python3 -m unittest discover -s tests -t ."
        runner = runners.MockRunner([
            step(
                contracts.KIND_REVIEW_ROUND,
                report(contracts.KIND_REVIEW_ROUND),
                family="codex",
            ),
            step(
                "suite_checkpoint",
                suite_checkpoint_response("passed", [command]),
            ),
        ])
        subject = self.ready_brainstorming_implementation(
            runner, verification=[command]
        )
        task_id = self.complete_brainstorming_implementation(subject)
        self.drive_until_closed(subject)

        implementation = subject.state["units"][-1]
        reviews = [
            round_info for round_info in implementation["rounds"]
            if round_info["kind"] == contracts.KIND_REVIEW_ROUND
        ]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(
            reviews[0]["evidence_fingerprint"],
            implementation["review_evidence_fingerprint"],
        )
        verifications = [
            event for event in subject.state["events"]
            if event.get("type") == "verification"
        ]
        self.assertEqual(len(verifications), 1)
        self.assertEqual(verifications[0]["status"], "passed")
        self.assertEqual(verifications[0]["commands"], [command])
        self.assertTrue(verifications[0]["stable"])
        self.assertEqual(verifications[0]["cadence"], "milestone_final")
        records = tasks.task_records(subject.state)
        self.assertEqual(records[0]["id"], task_id)
        self.assertEqual(records[0]["order"]["task_executor"], "brainstorming")
        self.assertEqual(
            [call[1] for call in runner.calls],
            [contracts.KIND_REVIEW_ROUND, "suite_checkpoint"],
        )
        self.assertFalse(runner.script)

    def test_no_suite_seals_with_one_final_llm_checkpoint(self):
        runner = runners.MockRunner([
            step(
                contracts.KIND_REVIEW_ROUND,
                report(contracts.KIND_REVIEW_ROUND),
                family="codex",
            ),
            step(
                "suite_checkpoint",
                suite_checkpoint_response("no_suite", []),
            ),
        ])
        subject = self.ready_brainstorming_implementation(
            runner, verification=[]
        )
        self.complete_brainstorming_implementation(subject)
        self.drive_until_closed(subject)

        verifications = [
            event for event in subject.state["events"]
            if event.get("type") == "verification"
        ]
        self.assertEqual(len(verifications), 1)
        self.assertEqual(verifications[0]["status"], "no_suite")
        self.assertEqual(verifications[0]["commands"], [])
        self.assertTrue(verifications[0]["stable"])
        self.assertEqual(verifications[0]["cadence"], "milestone_final")
        self.assertEqual(subject.state["milestone"]["status"], st.M_CLOSED)
        self.assertEqual(
            [call[1] for call in runner.calls],
            [contracts.KIND_REVIEW_ROUND, "suite_checkpoint"],
        )
        self.assertFalse(runner.script)

    def test_brainstorming_note_carries_the_routed_repository_charge(self):
        self.planned("brainstorming", "agent_call")
        subject = drv.Driver(self.path, runner=runners.MockRunner([]))
        unit = st.current_unit(subject.state)
        request, planned = subject._brainstorming_production_request(
            unit, contracts.KIND_DRAFT_SLICE_NOTE
        )
        context = request["context"]
        charge = context["session_charge"]
        self.assertEqual(charge["job"], "draft_slice_note@slice_doc")
        self.assertNotIn("material", charge)
        self.assertEqual(charge["values"]["slice_id"], "1")
        self.assertEqual(charge["values"]["slice_note_path"], planned)
        self.assertEqual(context["planned_slice_note_path"], planned)
        self.assertEqual(
            charge["repository"]["pre_session_commit"],
            self._git(self.workspace, "rev-parse", "HEAD"),
        )
        self.assertEqual(
            charge["repository"]["skeleton_path"], "docs/skeleton.md"
        )
        self.assertEqual(request["reference_documents"], ["docs/skeleton.md"])


if __name__ == "__main__":
    unittest.main()
