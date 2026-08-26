"""Focused compatibility proof for the milestone's Worker task cutover."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import brainstorming_milestone as adapter
from orchestrator import canonical_plan
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import gitops
from orchestrator import profiles
from orchestrator import prompt_router
from orchestrator import prompts
from orchestrator import runners
from orchestrator import state as st
from orchestrator import tasks
from orchestrator import verifiers
from orchestrator.tests.test_driver_mock import (
    finding,
    fix_ok as legacy_fix_ok,
    ok,
    report as legacy_report,
    triaged,
)


def report_finding(fid="F1"):
    return {
        "id": fid,
        "severity": "P1",
        "summary": "One design choice is unresolved.",
        "validity": {
            "permitted_baseline": "the design makes the choice explicit",
            "actual_outcome": "the choice is not settled",
            "incremental_harm": "the current judgment cannot finish",
            "exceeds_baseline": True,
        },
        "plain": "The reviewer cannot judge the work until one choice is made.",
        "example": "A reviewer checks one behavior but two outcomes are allowed.",
        "contests": None,
    }


def failure_gap():
    return {
        "classification": "fits_remodel",
        "missing_or_conflict": "the design choice remains unresolved",
        "where": "implementation/milestones/example/skeleton.md:1",
        "forced_decision": "state which behavior the implementation must use",
        "proposal": None,
        "plain": "The implementation cannot finish without one design choice.",
        "example": "A builder must choose A or B but neither is selected.",
    }


def _judgment_questions():
    return [
        {"id": "environment_fit", "answer": "Checked."},
        {"id": "human_scale", "answer": "Checked."},
    ]


def fix_ok(*args, **kwargs):
    value = legacy_fix_ok(*args, **kwargs)
    value["questions"] = _judgment_questions()
    return value


def report(kind, findings=()):
    value = legacy_report(kind, findings)
    value["questions"] = _judgment_questions()
    return value


def _usage(amount=3):
    return {
        "input_tokens": amount,
        "cached_input_tokens": 0,
        "output_tokens": amount,
        "reasoning_output_tokens": 0,
        "total_tokens": amount * 2,
    }


def _rethink(kind, source=None, result_mode="proposal"):
    value = {
        "status": "need_rethink",
        "kind": kind,
        "finding": copy.deepcopy(source or {"id": "BUILD", "summary": "choice"}),
        "target_path": "proposals/rethink.md",
    }
    if kind in _AUTHOR_QUESTION_IDS:
        value["questions"] = _author_questions(kind)
        return value
    value.update({
        "request": "Resolve the one bounded design question.",
        "max_rounds": 20,
        "result_mode": result_mode,
    })
    if kind in contracts.RETHINK_CONTINUATION_KINDS:
        value["failure_gap"] = failure_gap()
    value["questions"] = _judgment_questions()
    return value


_AUTHOR_QUESTION_IDS = {
    contracts.KIND_DRAFT_SKELETON: (
        "due_diligence_count",
        "machinery_trust",
        "environment_fit",
        "human_scale",
    ),
    contracts.KIND_DRAFT_SLICE_NOTE: (
        "due_diligence_count",
        "machinery_trust",
        "environment_fit",
        "human_scale",
    ),
    contracts.KIND_IMPLEMENT: (
        "machinery_trust",
        "environment_fit",
        "human_scale",
    ),
}


def _author_questions(kind):
    return [
        {"id": question_id, "answer": "Checked the bounded fixture."}
        for question_id in _AUTHOR_QUESTION_IDS[kind]
    ]


def _author_ok(kind, **extra):
    return ok(kind, questions=_author_questions(kind), **extra)


def _worker_plan():
    return {
        "slices": [{
            "id": 1,
            "title": "Worker",
            "intent": "Exercise the retained worker-task behavior.",
            "producer_task_executor": {
                "draft_slice_note": "agent_call",
                "implement": "agent_call",
            },
        }],
    }


def _worker_skeleton():
    return (
        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
        % json.dumps(_worker_plan())
    )


def _created(session_id):
    return {
        "id": session_id,
        "state": {
            "completed_turns": [],
            "rounds_used": 0,
            "recovery_baseline_revision": "baseline-%s" % session_id,
            "accepted_target_revision": None,
        },
    }


def _handoff(session_id, outcome="success", work_duration_s=None):
    result = {
        "outcome": outcome,
        "target_ref": "/retained/target.md",
        "transcript_ref": "/retained/chat.md",
        "rounds_used": 1,
    }
    if outcome == "failure":
        result["reason"] = "No agreement was reached."
    value = {
        "session_id": session_id,
        "result": result,
        "accepted_target_revision": (
            "accepted-%s" % session_id if outcome == "success" else None
        ),
    }
    if outcome == "success":
        value["retained_target"] = {
            "exists": True,
            "encoding": "utf-8",
            "content": "accepted proposal",
        }
    if work_duration_s is not None:
        value["work_duration_s"] = work_duration_s
    return value


class WorkerTaskCutoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="worker-tasks-")
        self.addCleanup(self.tmp.cleanup)

    def _path(self, label, unit_kind=st.UNIT_SLICE_IMPL, status=st.U_PENDING):
        workspace = os.path.join(self.tmp.name, label)
        os.makedirs(os.path.join(workspace, "docs"))
        os.makedirs(os.path.join(workspace, "proposals"))
        config = copy.deepcopy(drv.DEFAULT_CONFIG)
        config.update({
            "docs_dir": "docs",
            "git": {"enabled": False},
            "verification": [],
            "guarantee_calibration": {"enabled": False},
            "p3_reclassify_debt": False,
            "error_classifier": False,
            "infra_retry_backoff_s": [],
        })
        state = st.new_state("Build the Worker task cutover.", workspace, config)
        state["milestone"]["slices"] = copy.deepcopy(_worker_plan()["slices"])
        skeleton = st._new_unit(st.UNIT_SKELETON, None)
        skeleton.update({"status": st.U_SEALED, "artifact": "docs/skeleton.md"})
        note = st._new_unit(st.UNIT_SLICE_DOC, 1)
        note.update({"status": st.U_SEALED, "artifact": "docs/note.md"})
        implementation = st._new_unit(st.UNIT_SLICE_IMPL, 1)
        implementation["status"] = status
        if unit_kind == st.UNIT_SKELETON:
            skeleton.update({"status": status, "artifact": None})
            state["milestone"]["slices"] = []
            state["units"] = [skeleton]
        elif unit_kind == st.UNIT_SLICE_DOC:
            note.update({"status": status, "artifact": None})
            state["units"] = [skeleton, note, implementation]
        else:
            state["units"] = [skeleton, note, implementation]
        if status in (st.U_FIXING, st.U_DELTA_REVIEW):
            queued = finding("F1", "repair the bounded defect", severity="P1")
            implementation["fix_queue"] = [queued]
            implementation["fix_source"] = {
                "type": "round",
                "origin_type": "round",
                "family": "claude",
                "source_round_id": "slice_impl-01-claude-r1",
                "return_to": st.U_ROUNDS,
            }
        for relative, text in (
            ("docs/skeleton.md", _worker_skeleton()),
            ("docs/note.md", "# Note\n"),
        ):
            with open(os.path.join(workspace, relative), "w", encoding="utf-8") as fh:
                fh.write(text)
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        gitops.ensure_repo(workspace)
        if unit_kind != st.UNIT_SKELETON:
            canonical_plan.establish_current_plan(state, "docs/skeleton.md")
        path = drv.default_state_path(workspace)
        st.save(path, state)
        with open(
            os.path.join(os.path.dirname(path), "amendments.json"),
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump({"amendments": []}, handle)
        return path

    @staticmethod
    def _task(state, index=-1):
        return tasks.task_records(state)[index]

    def test_worker_adapter_preserves_request_native_result_and_accounting(self):
        path = self._path("adapter", st.UNIT_SKELETON)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        task = driver._admit_worker_task(
            unit, contracts.KIND_DRAFT_SKELETON, "complete prompt", "codex"
        )
        native = _author_ok(
            contracts.KIND_DRAFT_SKELETON,
            artifact="docs/skeleton.md",
        )
        os.makedirs(
            os.path.dirname(driver._amendments_path()), exist_ok=True
        )
        with open(
            driver._amendments_path(), "w", encoding="utf-8"
        ) as handle:
            handle.write(
                '{"amendments":[{"id":"A-direct","text":'
                '"Do not inject this into a direct execution."}]}'
            )
        seen = []
        returned = tasks.execute_worker(task, lambda request: seen.append(request) or native)
        self.assertIs(returned, native)
        self.assertEqual(seen, [task["order"]["request"]])
        result = runners.RunnerResult("{}", 0, 2.0, token_usage=_usage())
        result.task_id = task["id"]
        result.cost = {"api_usd": 0.2, "real_usd": 0.1}
        st.record_draft(
            driver.state,
            unit,
            contracts.KIND_DRAFT_SKELETON,
            native,
            duration=2.0,
            token_usage=_usage(),
            cost=result.cost,
            task_id=task["id"],
        )
        driver._terminalize_worker_task(unit, native, result=result)
        terminal = self._task(driver.state)
        self.assertEqual(terminal["result"]["native_result"], native)
        self.assertEqual(terminal["result"]["duration_s"], 2.0)
        self.assertEqual(st.summary(driver.state)["work_duration_s"], 2.0)

    def test_worker_episode_authority_is_complete_or_fails_closed(self):
        path = self._path("authority-completeness", st.UNIT_SKELETON)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        st.append_event(
            driver.state,
            "brainstorming_design_amendment_adopted",
            amendment_id="B-live",
            text="# Accepted decision\nKeep the bounded behavior.",
            authority="brainstorming_design",
        )
        os.makedirs(
            os.path.dirname(driver._amendments_path()), exist_ok=True
        )
        with open(
            driver._amendments_path(), "w", encoding="utf-8"
        ) as handle:
            handle.write('{"amendments":[]}')
        complete_amendments = driver._amendments_snapshot(
            record_seen=False
        )
        complete = prompts.worker_episode_authority_block(
            complete_amendments, None
        )
        self.assertIn("MUTABLE OPERATOR AMENDMENTS: COMPLETE", complete)
        self.assertIn("omitted here is revoked", complete)
        self.assertIn("CURRENT MUTABLE OPERATOR AMENDMENTS: none", complete)
        self.assertIn("[B-live]", complete)
        self.assertIn("Keep the bounded behavior.", complete)
        self.assertIn("COMPLETE AND REPLACING", complete)

        with open(
            driver._amendments_path(), "w", encoding="utf-8"
        ) as handle:
            handle.write('{"amendments":')
        with self.assertRaises(prompt_router.PromptRouterError):
            driver._amendments_snapshot(record_seen=False)

    def test_amendment_authority_is_derived_from_durable_source(self):
        path = self._path("authority-source", st.UNIT_SKELETON)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        st.append_event(
            driver.state,
            "redoc_wave_migrated_to_design_update",
            amendment_id="B-migrated",
            text="Keep the migrated design decision bounded.",
            authority="historical_design_update",
        )
        os.makedirs(
            os.path.dirname(driver._amendments_path()), exist_ok=True
        )
        with open(
            driver._amendments_path(), "w", encoding="utf-8"
        ) as handle:
            handle.write(
                '{"amendments":[{"id":"A-current","text":'
                '"Apply current operator law.","authority":'
                '"brainstorming_design"}]}'
            )

        amendments = driver._amendments_snapshot(record_seen=False)
        by_id = {item["id"]: item for item in amendments}
        self.assertNotIn("authority", by_id["A-current"])
        self.assertEqual(
            by_id["B-migrated"]["authority"], "brainstorming_design"
        )
        rendered = prompts.worker_episode_authority_block(
            amendments, None
        )
        self.assertLess(
            rendered.index("OPERATOR AMENDMENTS"),
            rendered.index("ACCEPTED BRAINSTORMING DESIGN AMENDMENTS"),
        )
        self.assertLess(
            rendered.index("[A-current]"),
            rendered.index("ACCEPTED BRAINSTORMING DESIGN AMENDMENTS"),
        )
        self.assertGreater(
            rendered.index("[B-migrated]"),
            rendered.index("ACCEPTED BRAINSTORMING DESIGN AMENDMENTS"),
        )

    def test_standing_law_failure_prevents_recovery_dispatch(self):
        path = self._path("standing-law-stop", st.UNIT_SKELETON)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        frozen_prompt = (
            "KIND: draft_skeleton\nFAMILY: codex\nWORKSPACE: %s\n"
            "immutable admitted prompt" % driver.workspace
        )
        task = driver._admit_worker_task(
            unit,
            contracts.KIND_DRAFT_SKELETON,
            frozen_prompt,
            "codex",
        )
        driver._save()
        recovered = drv.Driver(path, runner=runners.MockRunner([]))

        with (
            mock.patch.object(
                recovered,
                "_project_prompt_inputs",
                side_effect=drv.StopStep("standing law unavailable"),
            ),
            mock.patch.object(recovered, "_call") as worker_call,
            self.assertRaisesRegex(drv.StopStep, "standing law unavailable"),
        ):
            recovered._do_draft()

        worker_call.assert_not_called()
        current = tasks.task_record(recovered.state, task["id"])
        self.assertIsNone(current["result"])
        self.assertEqual(
            current["order"]["request"]["request"],
            frozen_prompt,
        )

    def test_recovery_safeguard_snapshot_governs_prompt_and_repair(self):
        path = self._path("episode-repair", st.UNIT_SKELETON)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        frozen_prompt = (
            "KIND: draft_skeleton\nFAMILY: codex\nWORKSPACE: %s\n"
            "immutable admitted prompt" % driver.workspace
        )
        task = driver._admit_worker_task(
            unit,
            contracts.KIND_DRAFT_SKELETON,
            frozen_prompt,
            "codex",
        )
        policy = {
            "id": "episode-guard",
            "version": 2,
            "enabled": True,
            "scope": {
                "kinds": [contracts.KIND_DRAFT_SKELETON],
                "unit_kinds": [st.UNIT_SKELETON],
            },
            "prompt": "Record the live episode check.",
            "contract": {
                "field": "episode_audit",
                "required": True,
                "entry": {"note": {"type": "string"}},
                "checks": [{"kind": "non_empty", "field": "note"}],
            },
        }
        extension = verifiers.compile_policy(policy)
        context = {
            "project": "orchestrators",
            "work_area": "implementation",
            "primary": {"path": driver.workspace},
            "additional": [],
            "reuse_sources": None,
            "safeguards": [policy],
        }
        incomplete = _author_ok(
            contracts.KIND_DRAFT_SKELETON,
            artifact="docs/skeleton.md",
        )
        repaired = copy.deepcopy(incomplete)
        repaired["episode_audit"] = [{"note": "checked live law"}]

        def write_changed_skeleton(workspace):
            with open(
                os.path.join(workspace, "docs/skeleton.md"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(_worker_skeleton() + "\nChecked safeguard.\n")

        runner = runners.MockRunner([
            {
                "expect_kind": contracts.KIND_DRAFT_SKELETON,
                "response": incomplete,
                "side_effect": write_changed_skeleton,
            },
            {
                "expect_kind": contracts.KIND_DRAFT_SKELETON,
                "response": repaired,
            },
        ])
        recovered = drv.Driver(path, runner=runner)
        with mock.patch.object(
            recovered,
            "_project_prompt_inputs",
            return_value=(context, [extension], [driver.workspace]),
        ) as live_inputs:
            recovered._do_draft()

        # Admission plus both physical attempts read current policy.  The
        # repair is a freshly routed charge, not a suffix on a frozen prompt.
        self.assertEqual(live_inputs.call_count, 3)
        self.assertEqual(len(runner.calls), 2)
        for call in runner.calls:
            self.assertIn("SAFEGUARD episode-guard v2", call[2])
        self.assertIn("CONTRACT CORRECTION", runner.calls[1][2])
        self.assertEqual(
            tasks.task_record(recovered.state, task["id"])["result"]["status"],
            "success",
        )
        self.assertEqual(
            tasks.task_record(recovered.state, task["id"])["order"]
            ["request"]["request"],
            frozen_prompt,
        )

    def test_default_milestone_worker_cutover_preserves_all_six_kinds(self):
        fixed = fix_ok([triaged("F1", "fixed", severity="P1")])
        cases = (
            (contracts.KIND_DRAFT_SKELETON, st.UNIT_SKELETON, st.U_PENDING,
             _author_ok(contracts.KIND_DRAFT_SKELETON,
                        artifact="docs/skeleton.md")),
            (contracts.KIND_DRAFT_SLICE_NOTE, st.UNIT_SLICE_DOC, st.U_PENDING,
             _author_ok(contracts.KIND_DRAFT_SLICE_NOTE,
                        artifact="docs/note.md")),
            (contracts.KIND_IMPLEMENT, st.UNIT_SLICE_IMPL, st.U_PENDING,
             _author_ok(contracts.KIND_IMPLEMENT, files_changed=[])),
            (contracts.KIND_FIX_FINDINGS, st.UNIT_SLICE_IMPL, st.U_FIXING, fixed),
            (contracts.KIND_REVIEW_ROUND, st.UNIT_SLICE_IMPL, st.U_ROUNDS,
             report(contracts.KIND_REVIEW_ROUND)),
            (contracts.KIND_DELTA_REVIEW, st.UNIT_SLICE_IMPL, st.U_DELTA_REVIEW,
             report(contracts.KIND_DELTA_REVIEW)),
        )
        # The process step each milestone order records: its own seat for
        # the three production kinds, the fixer's for a fix, and `review`
        # for both report-only kinds.
        roles = {
            contracts.KIND_DRAFT_SKELETON: "plan",
            contracts.KIND_DRAFT_SLICE_NOTE: "draft",
            contracts.KIND_IMPLEMENT: "implement",
            contracts.KIND_FIX_FINDINGS: "fix",
            contracts.KIND_REVIEW_ROUND: "review",
            contracts.KIND_DELTA_REVIEW: "review",
        }
        for number, (kind, unit_kind, status, response) in enumerate(cases):
            with self.subTest(kind=kind):
                path = self._path("kind-%d" % number, unit_kind, status)
                scripted = {"expect_kind": kind, "response": response}
                if kind in _AUTHOR_QUESTION_IDS:
                    def author_edit(workspace, author_kind=kind):
                        if author_kind == contracts.KIND_DRAFT_SKELETON:
                            relative = "docs/skeleton.md"
                            body = _worker_skeleton() + "\nUpdated by author.\n"
                        elif author_kind == contracts.KIND_DRAFT_SLICE_NOTE:
                            relative = "docs/note.md"
                            body = "# Note\n\nUpdated by author.\n"
                        else:
                            relative = "implementation.py"
                            body = "implemented = True\n"
                        with open(
                            os.path.join(workspace, relative),
                            "w",
                            encoding="utf-8",
                        ) as handle:
                            handle.write(body)

                    scripted["side_effect"] = author_edit
                runner = runners.MockRunner([scripted])
                with mock.patch.object(drv.gitops, "worktree_diff", return_value="delta"), \
                        mock.patch.object(drv.gitops, "amend", return_value="abc123"):
                    drv.Driver(path, runner=runner).step()
                state = st.load(path)
                task = self._task(state)
                self.assertEqual(len(tasks.task_records(state)), 1)
                self.assertEqual(task["order"]["task_executor"], "agent_call")
                self.assertEqual(
                    task["order"]["configuration"], {"role": roles[kind]}
                )
                # These runs bind no session; the order records the absence
                # as the deliberate value it is.
                self.assertEqual(
                    tasks.order_staffing_session(task["order"]), (True, None)
                )
                self.assertEqual(task["order"]["request"]["context"]["task_kind"], kind)
                self.assertEqual(task["result"]["status"], "success")
                self.assertEqual(task["result"]["native_result"], response)
                links = [
                    record.get("task_id")
                    for unit in state["units"]
                    for record in ([unit.get("draft")] + unit.get("rounds", []))
                    if record
                ]
                self.assertEqual(links, [task["id"]])

    def test_worker_order_destination_is_admitted_once_and_forwarded_unchanged(self):
        path = self._path("destination", st.UNIT_SKELETON)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        task = driver._admit_worker_task(
            unit,
            contracts.KIND_DRAFT_SKELETON,
            "prompt",
            "codex",
            output_directory="planned/output",
        )
        canonical = os.path.realpath(os.path.join(driver.workspace, "planned/output"))
        seen = []
        tasks.execute_worker(task, lambda request: seen.append(request["output_directory"]))
        self.assertEqual(seen, [canonical])
        self.assertEqual(task["order"]["request"]["output_directory"], canonical)

        omitted_path = self._path("destination-omitted", st.UNIT_SKELETON)
        omitted_driver = drv.Driver(omitted_path, runner=runners.MockRunner([]))
        omitted = omitted_driver._admit_worker_task(
            st.current_unit(omitted_driver.state),
            contracts.KIND_DRAFT_SKELETON,
            "prompt",
            "codex",
        )
        self.assertNotIn("output_directory", omitted["order"]["request"])

        outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(driver.workspace, "linked-outside"))
        for index, destination in enumerate((outside, "linked-outside/child")):
            invalid_path = self._path("destination-invalid-%d" % index,
                                      st.UNIT_SKELETON)
            invalid_driver = drv.Driver(invalid_path, runner=runners.MockRunner([]))
            if index:
                os.symlink(outside, os.path.join(invalid_driver.workspace,
                                                 "linked-outside"))
            with self.assertRaises(tasks.TaskRequestError):
                invalid_driver._admit_worker_task(
                    st.current_unit(invalid_driver.state),
                    contracts.KIND_DRAFT_SKELETON,
                    "prompt",
                    "codex",
                    output_directory=destination,
                )
            self.assertEqual(tasks.task_records(invalid_driver.state), [])

    def test_profileless_worker_uses_default_changed_after_admission(self):
        path = self._path("staffing", st.UNIT_SKELETON)

        def write_changed_skeleton(workspace):
            with open(
                os.path.join(workspace, "docs/skeleton.md"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(_worker_skeleton() + "\nUpdated by author.\n")

        runner = runners.MockRunner([
            {"expect_kind": contracts.KIND_DRAFT_SKELETON,
             "response": "not json",
             "side_effect": write_changed_skeleton},
            {"expect_kind": contracts.KIND_DRAFT_SKELETON,
             "response": _author_ok(contracts.KIND_DRAFT_SKELETON,
                                    artifact="docs/skeleton.md")},
        ])
        driver = drv.Driver(path, runner=runner)
        unit = st.current_unit(driver.state)
        driver.config["model_defaults"]["codex"] = {
            "model": "model-a", "effort": "low"
        }
        resolver = driver._structural_dispatch("codex")
        task = driver._admit_worker_task(
            unit,
            contracts.KIND_DRAFT_SKELETON,
            "KIND: draft_skeleton\n",
            "codex",
            dispatch_resolver=resolver,
        )
        frozen = copy.deepcopy(task["resolved_staffing"])
        driver.config["model_defaults"]["codex"] = {
            "model": "model-b", "effort": "high"
        }
        output, result, _raw = tasks.execute_worker(
            task,
            lambda request: driver._call(
                "codex",
                request["request"],
                contracts.KIND_DRAFT_SKELETON,
                "staffing",
                dispatch_resolver=resolver,
                task_id=task["id"],
                prepare_call=driver._author_prepare_call(
                    unit,
                    contracts.KIND_DRAFT_SKELETON,
                    "document",
                    "staffing",
                ),
                episode_unit=unit,
            ),
        )
        self.assertEqual(frozen["agent_call"]["model"], "model-a")
        self.assertEqual(task["resolved_staffing"], frozen)
        self.assertEqual([call["model"] for call in runner.call_meta],
                         ["model-b", "model-b"])
        self.assertEqual(result.resolved_model, "model-b")
        self.assertEqual(output["artifact"], "docs/skeleton.md")

    def test_worker_note_keeps_nondefault_artifact_declaration(self):
        path = self._path("note-path", st.UNIT_SLICE_DOC)
        declared = "design/slices/one.md"
        response = _author_ok(
            contracts.KIND_DRAFT_SLICE_NOTE, artifact=declared
        )
        runner = runners.MockRunner([
            {"expect_kind": contracts.KIND_DRAFT_SLICE_NOTE, "response": response}
        ])
        drv.Driver(path, runner=runner).step()
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        note = next(u for u in driver.state["units"] if u["kind"] == st.UNIT_SLICE_DOC)
        task = self._task(driver.state)
        self.assertEqual(note["artifact"], declared)
        self.assertEqual(driver._artifact(note), declared)
        self.assertEqual(driver._slice_note_artifact(1), declared)
        self.assertEqual(task["result"]["native_result"], response)

    def test_continuable_worker_abandonments_fail_and_reentry_succeeds_new_task(self):
        def paused(label):
            path = self._path(label)
            runner = runners.MockRunner([{
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": _rethink(contracts.KIND_IMPLEMENT),
            }])
            with mock.patch.object(adapter, "create_session",
                                   return_value=_created(label)):
                drv.Driver(path, runner=runner).step()
            return path

        cases = (
            ("missing", lifecycle.PublicLifecycleError(404, lifecycle.UNKNOWN_SESSION), None),
            ("operational", adapter.OperationalTerminalError("lost"), None),
            ("no-agreement", None, _handoff("no-agreement", "failure")),
        )
        for label, error, handoff in cases:
            path = paused(label)
            effect = error if error is not None else [handoff]
            with mock.patch.object(adapter, "terminal_handoff", side_effect=effect):
                drv.Driver(path, runner=runners.MockRunner([])).step()
            self.assertEqual(self._task(st.load(path))["result"]["status"], "failure")

        waiting = paused("recoverable")
        with mock.patch.object(adapter, "terminal_handoff", return_value=None):
            drv.Driver(waiting, runner=runners.MockRunner([])).step()
        waiting_state = st.load(waiting)
        self.assertEqual(
            self._task(waiting_state)["result"]["status"], "failure"
        )
        self.assertIn("brainstorming_wait", st.current_unit(waiting_state))

        retry = self._path("attachment")
        runner = runners.MockRunner([
            {"expect_kind": contracts.KIND_IMPLEMENT,
             "response": _rethink(contracts.KIND_IMPLEMENT)},
            {"expect_kind": contracts.KIND_IMPLEMENT,
             "response": _author_ok(
                 contracts.KIND_IMPLEMENT, files_changed=[]
             )},
        ])
        with mock.patch.object(adapter, "create_session",
                               side_effect=adapter.AdapterError("unavailable")):
            drv.Driver(retry, runner=runner).step()
        failed = st.load(retry)
        predecessor = copy.deepcopy(self._task(failed))
        st.resume_run(failed)
        st.save(retry, failed)
        drv.Driver(retry, runner=runner).step()
        records = tasks.task_records(st.load(retry))
        self.assertEqual(records[0], predecessor)
        self.assertNotEqual(records[0]["id"], records[1]["id"])

    def test_fresh_stabilization_refreshes_authority(self):
        path = self._path("cutoff-recovery")
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        task = driver._admit_worker_task(
            unit,
            contracts.KIND_IMPLEMENT,
            "frozen pre-cutoff prompt",
            "codex",
            author_coordinates=driver._author_coordinates(
                unit, contracts.KIND_IMPLEMENT
            ),
        )
        unit["implementation_stabilization"] = {
            "implementation_size": {
                "episode_id": "focused-cutoff",
                "task_id": task["id"],
            },
        }
        driver._save()
        os.makedirs(
            os.path.dirname(driver._amendments_path()), exist_ok=True
        )
        with open(
            driver._amendments_path(), "w", encoding="utf-8"
        ) as handle:
            handle.write(
                '{"amendments":[{"id":"A-stabilize","text":'
                '"Apply current stabilization authority."}]}'
            )
        seen = []

        def reached(_family, _prompt, *_args, **kwargs):
            recovery = driver._combined_author_recovery(
                kwargs.get("author_recovery"),
                driver._implementation_stabilizer_context(),
            )
            prepare_call = kwargs["prepare_author"](recovery, None)
            prepared = prepare_call(None)
            seen.append(prepared.prompt)
            prepared.complete()
            raise RuntimeError("recovery prompt reached")

        with mock.patch.object(
            driver, "_call_implementation", side_effect=reached
        ):
            with self.assertRaisesRegex(RuntimeError, "recovery prompt reached"):
                driver._do_draft()

        self.assertEqual(
            tasks.task_record(driver.state, task["id"])["order"]["request"]
            ["request"],
            "frozen pre-cutoff prompt",
        )
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith("KIND: implement\n"))
        self.assertNotIn("frozen pre-cutoff prompt", seen[0])
        self.assertIn("FORCED CONTROLLED-CUTOFF RECOVERY", seen[0])
        self.assertIn("[A-stabilize]", seen[0])

    def test_immediate_cutoff_stabilization_takes_a_new_episode_snapshot(self):
        path = self._path("immediate-stabilization")
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        control = mock.Mock()
        control.model_confirmation_at = None
        marker = {
            "episode_id": "cutoff-episode",
            "soft_lines": 10,
            "hard_lines": 20,
            "steer_attempted": False,
            "steer_delivered": False,
            "steer_confirmed": False,
            "steer_lines": None,
            "hard_crossed_lines": 21,
            "grace_kind": "unconfirmed",
            "interrupt_lines": 21,
            "last_lines": 21,
        }
        interrupted = runners.ControlledInterruptionResult(
            "partial", 1, 1.0, "size cutoff"
        )
        completed = runners.RunnerResult("{}", 0, 1.0)
        refreshes = []
        preparations = []
        prepared_callbacks = []

        def refresh(prompt):
            refreshes.append(prompt)
            return prompt + "\nFRESH AUTHORITY", ["new-extension"], ["root"]

        def prepare_author(recovery, meter):
            callback = object()
            preparations.append((recovery, meter))
            prepared_callbacks.append(callback)
            return callback

        with (
            mock.patch.object(
                driver,
                "_implementation_size_control",
                return_value=(control, marker),
            ),
            mock.patch.object(
                driver, "_implementation_line_count", return_value=21
            ),
            mock.patch.object(driver, "_matching_busy_call", return_value={}),
            mock.patch.object(
                driver,
                "_call",
                side_effect=[
                    (None, interrupted, "raw/interrupted.txt"),
                    (
                        {"status": "ok", "kind": contracts.KIND_IMPLEMENT,
                         "files_changed": []},
                        completed,
                        "raw/stabilized.txt",
                    ),
                ],
            ) as worker_call,
        ):
            output, _result, _raw, _size, stabilized = (
                driver._call_implementation(
                    "codex",
                    "initial episode prompt",
                    "slice_impl-01-draft",
                    "gpt-5",
                    "high",
                    ["old-extension"],
                    ["root"],
                    None,
                    True,
                    "base-tree",
                    task_id="task-1",
                    episode_refresher=refresh,
                    prepare_author=prepare_author,
                    author_recovery="RESUMED AUTHOR EPISODE",
                )
            )

        self.assertTrue(stabilized)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(len(refreshes), 1)
        self.assertEqual(refreshes[0], "initial episode prompt")
        self.assertEqual(len(preparations), 2)
        self.assertEqual(preparations[0][0], "RESUMED AUTHOR EPISODE")
        self.assertIs(preparations[0][1], marker)
        self.assertIn("RESUMED AUTHOR EPISODE", preparations[1][0])
        self.assertIn("FORCED CONTROLLED-CUTOFF RECOVERY", preparations[1][0])
        self.assertIsNone(preparations[1][1])
        self.assertEqual(worker_call.call_count, 2)
        second = worker_call.call_args_list[1]
        self.assertIs(second.kwargs["prepare_call"], prepared_callbacks[1])
        self.assertEqual(second.kwargs["extensions"], ["new-extension"])

    def test_recovery_refreshes_authority_without_rewriting_order(self):
        path = self._path("frozen-recovery", st.UNIT_SKELETON)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        task = driver._admit_worker_task(
            st.current_unit(driver.state),
            contracts.KIND_DRAFT_SKELETON,
            "frozen admitted prompt",
            "codex",
        )
        amendments_path = driver._amendments_path()
        os.makedirs(os.path.dirname(amendments_path), exist_ok=True)
        with open(amendments_path, "w", encoding="utf-8") as handle:
            handle.write(
                '{"amendments":[{"id":"A-after","text":'
                '"Added after admission."}]}'
            )

        def write_changed_skeleton(workspace):
            with open(
                os.path.join(workspace, "docs/skeleton.md"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(_worker_skeleton() + "\nRecovered author edit.\n")

        runner = runners.MockRunner([{
            "expect_kind": contracts.KIND_DRAFT_SKELETON,
            "response": _author_ok(
                contracts.KIND_DRAFT_SKELETON,
                artifact="docs/skeleton.md",
            ),
            "side_effect": write_changed_skeleton,
        }])
        recovered = drv.Driver(path, runner=runner)
        recovered._do_draft()

        self.assertEqual(len(runner.calls), 1)
        physical_prompt = runner.calls[0][2]
        self.assertTrue(physical_prompt.startswith("KIND: draft_skeleton\n"))
        self.assertNotIn("frozen admitted prompt", physical_prompt)
        self.assertIn("RESUMED AUTHOR EPISODE", physical_prompt)
        self.assertIn("[A-after] Added after admission.", physical_prompt)
        self.assertEqual(
            tasks.task_record(recovered.state, task["id"])["order"]["request"]
            ["request"],
            "frozen admitted prompt",
        )
        self.assertTrue([
            event for event in recovered.state["events"]
            if event.get("type") == "amendment_seen"
            and event.get("amendment_id") == "A-after"
        ])

    def test_implementation_recovery_dispatches_live_authority_block(self):
        path = self._path("implementation-authority-recovery")
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        task = driver._admit_worker_task(
            st.current_unit(driver.state),
            contracts.KIND_IMPLEMENT,
            "frozen implementation prompt",
            "codex",
            author_coordinates=driver._author_coordinates(
                st.current_unit(driver.state), contracts.KIND_IMPLEMENT
            ),
        )
        os.makedirs(
            os.path.dirname(driver._amendments_path()), exist_ok=True
        )
        with open(
            driver._amendments_path(), "w", encoding="utf-8"
        ) as handle:
            handle.write(
                '{"amendments":[{"id":"A-implementation","text":'
                '"Apply to implementation recovery."}]}'
            )
        runner = runners.MockRunner([{
            "expect_kind": contracts.KIND_IMPLEMENT,
            "response": _author_ok(
                contracts.KIND_IMPLEMENT, files_changed=[]
            ),
        }])
        driver.runner = runner
        driver._do_draft()

        self.assertEqual(len(runner.calls), 1)
        physical_prompt = runner.calls[0][2]
        self.assertTrue(physical_prompt.startswith("KIND: implement\n"))
        self.assertNotIn("frozen implementation prompt", physical_prompt)
        self.assertIn("RESUMED AUTHOR EPISODE", physical_prompt)
        self.assertIn("[A-implementation]", physical_prompt)
        self.assertEqual(
            tasks.task_record(driver.state, task["id"])["order"]["request"]
            ["request"],
            "frozen implementation prompt",
        )

    def test_recovery_keeps_validation_aligned_with_frozen_strategy_prompt(self):
        cases = (
            ("legacy-to-strict", "legacy", "strict", None),
            (
                "strict-to-legacy",
                "strict",
                "legacy",
                {
                    "battery_questions": list(
                        contracts.BATTERY_QUESTIONS_SLICE_NOTE
                    ),
                    "require_failure_gap": True,
                },
            ),
        )
        for label, admitted_name, current_name, frozen_opts in cases:
            with self.subTest(label=label):
                path = self._path(label, st.UNIT_SLICE_DOC)
                state = st.load(path)
                admitted_profile = copy.deepcopy(
                    profiles.SEEDS[admitted_name]["profile"]
                )
                admitted_ref = {
                    "name": admitted_name,
                    "version": 1,
                    "hash": profiles.semantic_hash(admitted_profile),
                }
                state["config"]["profile"] = admitted_profile
                state["config"]["profile_ref"] = admitted_ref
                st.save(path, state)

                driver = drv.Driver(path, runner=runners.MockRunner([]))
                task = driver._admit_worker_task(
                    st.current_unit(driver.state),
                    contracts.KIND_DRAFT_SLICE_NOTE,
                    "frozen strategy-specific prompt",
                    "codex",
                    validate_opts=frozen_opts,
                    author_coordinates=driver._author_coordinates(
                        st.current_unit(driver.state),
                        contracts.KIND_DRAFT_SLICE_NOTE,
                    ),
                )
                current_profile = copy.deepcopy(
                    profiles.SEEDS[current_name]["profile"]
                )
                current_ref = {
                    "name": current_name,
                    "version": 1,
                    "hash": profiles.semantic_hash(current_profile),
                }
                st.append_event(
                    driver.state,
                    "profile_changed",
                    **{
                        "from": admitted_ref,
                        "to": current_ref,
                        "profile": current_profile,
                    },
                )
                driver._save()

                runner = runners.MockRunner([{
                    "expect_kind": contracts.KIND_DRAFT_SLICE_NOTE,
                    "response": _author_ok(
                        contracts.KIND_DRAFT_SLICE_NOTE,
                        artifact="docs/note.md",
                    ),
                }])
                recovered = drv.Driver(path, runner=runner)
                recovered._do_draft()

                expected = copy.deepcopy(frozen_opts)
                self.assertEqual(len(runner.calls), 1)
                physical_prompt = runner.calls[0][2]
                self.assertTrue(physical_prompt.startswith(
                    "KIND: draft_slice_note\n"
                ))
                self.assertNotIn(
                    "frozen strategy-specific prompt", physical_prompt
                )
                self.assertIn("RESUMED AUTHOR EPISODE", physical_prompt)
                self.assertEqual(
                    task["order"]["request"]["context"]["worker_validation"],
                    expected or {},
                )
                self.assertEqual(
                    tasks.task_record(
                        recovered.state, task["id"]
                    )["result"]["status"],
                    "success",
                )

    def test_review_result_routing_uses_admitted_strategy(self):
        path = self._path(
            "review-result-strategy", st.UNIT_SLICE_DOC, st.U_ROUNDS
        )
        state = st.load(path)
        admitted_profile = copy.deepcopy(profiles.SEEDS["strict"]["profile"])
        admitted_ref = {
            "name": "strict",
            "version": 1,
            "hash": profiles.semantic_hash(admitted_profile),
        }
        state["config"]["profile"] = admitted_profile
        state["config"]["profile_ref"] = admitted_ref
        st.save(path, state)

        admitted = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(admitted.state)
        unit["review_evidence_fingerprint"] = (
            admitted._review_evidence_fingerprint(unit)
        )
        task = admitted._admit_worker_task(
            unit,
            contracts.KIND_REVIEW_ROUND,
            "KIND: review_round\nFAMILY: codex\nWORKSPACE: %s\n"
            "frozen strict review" % admitted.workspace,
            "codex",
            validate_opts={"require_plain": True},
        )
        legacy_profile = copy.deepcopy(profiles.SEEDS["legacy"]["profile"])
        st.append_event(
            admitted.state,
            "profile_changed",
            **{
                "from": admitted_ref,
                "to": {
                    "name": "legacy",
                    "version": 1,
                    "hash": profiles.semantic_hash(legacy_profile),
                },
                "profile": legacy_profile,
            },
        )
        admitted._save()

        raised = finding(
            "F-strategy", "a deferrable design issue", severity="P2"
        )
        runner = runners.MockRunner([{
            "expect_kind": contracts.KIND_REVIEW_ROUND,
            "response": report(contracts.KIND_REVIEW_ROUND, [raised]),
        }])
        recovered = drv.Driver(path, runner=runner)
        with mock.patch.object(
            recovered,
            "_partition_defer_candidates",
            return_value=([], [(raised, "codex")]),
        ) as partition:
            recovered._do_review_round()

        partition.assert_called_once()
        self.assertEqual(
            partition.call_args.kwargs["defer_threshold"], "low"
        )
        self.assertTrue(partition.call_args.kwargs["gap_backstop"])
        self.assertEqual(
            task["order"]["request"]["context"]["worker_result_policy"],
            {
                "defer_scope": ["P2", "P3"],
                "p3_reclassify_debt": True,
                "p3_defer_max_risk": "low",
                "gap_backstop": True,
            },
        )

    def test_delta_recovery_refreshes_authority_without_rewriting_order(self):
        path = self._path("delta-frozen-recovery", status=st.U_DELTA_REVIEW)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        task = driver._admit_worker_task(
            st.current_unit(driver.state),
            contracts.KIND_DELTA_REVIEW,
            "frozen delta-review prompt",
            "codex",
        )
        self.assertEqual(
            task["order"]["request"]["context"]["worker_result_policy"],
            driver._worker_result_policy(st.current_unit(driver.state)),
        )
        amendments_path = driver._amendments_path()
        os.makedirs(os.path.dirname(amendments_path), exist_ok=True)
        with open(amendments_path, "w", encoding="utf-8") as handle:
            handle.write(
                '{"amendments":[{"id":"A-after","text":'
                '"Added after delta-review admission."}]}'
            )
        recovered = drv.Driver(path, runner=runners.MockRunner([]))
        seen = []

        def reached(_family, prompt, *_args, **_kwargs):
            seen.append(prompt)
            raise RuntimeError("delta dispatch reached")

        with (
            mock.patch.object(
                drv.gitops, "worktree_diff", return_value="pending delta"
            ),
            mock.patch.object(recovered, "_call", side_effect=reached),
            self.assertRaisesRegex(RuntimeError, "delta dispatch reached"),
        ):
            recovered._do_delta_review()

        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith("frozen delta-review prompt\n\n"))
        self.assertIn("WORKER EPISODE AUTHORITY REFRESH", seen[0])
        self.assertIn("[A-after] Added after delta-review admission.", seen[0])
        self.assertEqual(
            tasks.task_record(recovered.state, task["id"])["order"]["request"]
            ["request"],
            "frozen delta-review prompt",
        )
        self.assertTrue([
            event for event in recovered.state["events"]
            if event.get("type") == "amendment_seen"
            and event.get("amendment_id") == "A-after"
        ])

    def test_empty_delta_after_admission_fails_task_before_closing_episode(self):
        path = self._path("delta-vanished", status=st.U_DELTA_REVIEW)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        task = driver._admit_worker_task(
            unit,
            contracts.KIND_DELTA_REVIEW,
            "frozen delta-review prompt",
            "codex",
        )

        with mock.patch.object(drv.gitops, "worktree_diff", return_value=""):
            outcome = driver._do_delta_review()

        terminal = tasks.task_record(driver.state, task["id"])
        self.assertEqual(outcome, "no pending delta; episode closed")
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertIsNone(terminal["result"]["native_result"])
        self.assertIn("no pending delta remained", terminal["result"]["reason"])
        self.assertNotIn("active_task", unit)
        self.assertEqual(unit["status"], st.U_ROUNDS)

    def test_provisional_empty_delta_rollback_closes_review_before_fixer(self):
        path = self._path("provisional-delta-vanished", status=st.U_DELTA_REVIEW)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        original_queue = copy.deepcopy(unit["fix_queue"])
        original_source = copy.deepcopy(unit["fix_source"])
        unit["design_correction"] = {
            "phase": "proposed",
            "baseline": {
                "refs": "refs-before",
                "sym": "sym-before",
                "head": "head-before",
                "tree": "tree-before",
                "index_tree": "index-before",
            },
            "original_fix_queue": original_queue,
            "original_fix_source": original_source,
            "original_fix_loop_rounds": 0,
        }
        review = driver._admit_worker_task(
            unit,
            contracts.KIND_DELTA_REVIEW,
            "frozen provisional delta-review prompt",
            "codex",
        )

        with (
            mock.patch.object(
                driver, "_design_correction_integrity_error", return_value=None
            ),
            mock.patch.object(
                driver,
                "_design_correction_review_context",
                side_effect=lambda correction: correction,
            ),
            mock.patch.object(drv.gitops, "worktree_diff", return_value=""),
            mock.patch.object(drv.gitops, "restore_to_snapshot"),
            mock.patch.object(drv.gitops, "restore_index_tree"),
        ):
            outcome = driver._do_delta_review()

        failed_review = tasks.task_record(driver.state, review["id"])
        self.assertEqual(
            outcome, "design correction rejected; fixer retries without exception"
        )
        self.assertEqual(failed_review["result"]["status"], "failure")
        self.assertIsNone(failed_review["result"]["native_result"])
        self.assertIn(
            "proposed correction left no delta to ratify",
            failed_review["result"]["reason"],
        )
        self.assertNotIn("active_task", unit)
        self.assertEqual(unit["status"], st.U_FIXING)

        successor = driver._admit_worker_task(
            unit,
            contracts.KIND_FIX_FINDINGS,
            "retry without the rejected correction",
            "codex",
        )
        self.assertNotEqual(successor["id"], review["id"])

    def test_same_task_fixer_recovery_dispatches_killed_call_notice(self):
        path = self._path("fixer-killed-notice", status=st.U_FIXING)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        task = driver._admit_worker_task(
            unit,
            contracts.KIND_FIX_FINDINGS,
            "frozen fixer prompt",
            "codex",
        )
        unit["killed_fix_notice"] = "slice_impl-01-fix1"
        driver._save()
        recovered = drv.Driver(path, runner=runners.MockRunner([]))
        seen = []

        def reached(_family, prompt, *_args, **_kwargs):
            seen.append(prompt)
            raise RuntimeError("dispatch reached")

        with (
            mock.patch.object(
                recovered,
                "_judgment_prepare_call",
                wraps=recovered._judgment_prepare_call,
            ) as prepare_call,
            mock.patch.object(recovered, "_call", side_effect=reached),
            self.assertRaisesRegex(RuntimeError, "dispatch reached"),
        ):
            recovered._do_fix()

        self.assertEqual(len(seen), 1)
        self.assertIn("KILLED-CALL NOTICE", seen[0])
        self.assertIn("frozen fixer prompt", seen[0])
        self.assertIn("WORKER EPISODE AUTHORITY REFRESH", seen[0])
        self.assertEqual(
            prepare_call.call_args.kwargs["context"]["fixer_recovery_state"],
            "pending_partial_delta",
        )
        self.assertEqual(
            tasks.task_record(recovered.state, task["id"])["order"]["request"]
            ["request"],
            "frozen fixer prompt",
        )
        self.assertTrue(st.current_unit(recovered.state)["killed_fix_notice"])

    def test_worker_task_recovery_and_legacy_exclusions(self):
        path = self._path("recovery", st.UNIT_SKELETON)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        task = driver._admit_worker_task(
            unit, contracts.KIND_DRAFT_SKELETON, "original", "codex"
        )
        driver._mark_busy("legacy", contracts.KIND_DRAFT_SKELETON, "codex")
        recovered = drv.Driver(path, runner=runners.MockRunner([]))
        same = recovered._admit_worker_task(
            st.current_unit(recovered.state), contracts.KIND_DRAFT_SKELETON,
            "changed on retry", "codex",
        )
        self.assertEqual(same["id"], task["id"])
        st.append_event(recovered.state, "worker_unaccepted", task_id=task["id"],
                        duration_s=2.0, token_usage=_usage(), cost=None)
        for event_type in ("brainstorming_work_recorded", "reclassify_recorded",
                           "seal_half"):
            st.append_event(recovered.state, event_type, duration_s=9.0,
                            token_usage=_usage(9), cost=None)
        envelope = tasks.worker_result(recovered.state, task["id"], {"done": True})
        self.assertEqual(envelope["duration_s"], 2.0)
        self.assertTrue(envelope["cost_partial"])
        interrupted = [e for e in recovered.state["events"]
                       if e["type"] == "worker_interrupted"]
        self.assertTrue(interrupted)
        self.assertNotIn("task_id", interrupted[-1])
