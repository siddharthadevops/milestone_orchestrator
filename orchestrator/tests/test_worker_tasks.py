"""Focused compatibility proof for the milestone's Worker task cutover."""

import copy
import os
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import brainstorming_milestone as adapter
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import profiles
from orchestrator import prompts
from orchestrator import runners
from orchestrator import state as st
from orchestrator import tasks
from orchestrator import verifiers
from orchestrator.tests.test_brainstorming_milestone_adapter import (
    failure_gap,
    report_finding,
)
from orchestrator.tests.test_driver_mock import (
    finding,
    fix_ok,
    ok,
    report,
    triaged,
)


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
        "request": "Resolve the one bounded design question.",
        "finding": copy.deepcopy(source or {"id": "BUILD", "summary": "choice"}),
        "target_path": "proposals/rethink.md",
        "max_rounds": 20,
        "result_mode": result_mode,
    }
    if kind in contracts.RETHINK_CONTINUATION_KINDS:
        value["failure_gap"] = failure_gap()
    return value


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
            "git": {"enabled": False},
            "verification": [],
            "guarantee_calibration": {"enabled": False},
            "p3_reclassify_debt": False,
            "error_classifier": False,
            "infra_retry_backoff_s": [],
        })
        state = st.new_state("Build the Worker task cutover.", workspace, config)
        state["milestone"]["slices"] = [{"id": 1, "title": "Worker"}]
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
            ("docs/skeleton.md", "# Skeleton\n"),
            ("docs/note.md", "# Note\n"),
        ):
            with open(os.path.join(workspace, relative), "w", encoding="utf-8") as fh:
                fh.write(text)
        path = drv.default_state_path(workspace)
        st.save(path, state)
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
        native = ok(
            contracts.KIND_DRAFT_SKELETON,
            artifact="docs/skeleton.md",
            slices=[],
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

    def test_worker_episode_authority_complete_empty_and_incomplete(self):
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
        complete_amendments, complete_flag = driver._amendments_snapshot(
            record_seen=False
        )
        self.assertTrue(complete_flag)
        complete = prompts.worker_episode_authority_block(
            complete_amendments, None, complete_flag
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
        incomplete_amendments, incomplete_flag = driver._amendments_snapshot(
            record_seen=False
        )
        self.assertFalse(incomplete_flag)
        incomplete = prompts.worker_episode_authority_block(
            incomplete_amendments, None, incomplete_flag
        )
        self.assertIn("MUTABLE OPERATOR AMENDMENTS: INCOMPLETE", incomplete)
        self.assertIn("This block revokes\nnothing", incomplete)
        self.assertIn("there is no prior-set cache", incomplete)
        self.assertIn("[B-live]", incomplete)

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

        amendments, complete = driver._amendments_snapshot(record_seen=False)

        self.assertTrue(complete)
        by_id = {item["id"]: item for item in amendments}
        self.assertNotIn("authority", by_id["A-current"])
        self.assertEqual(
            by_id["B-migrated"]["authority"], "brainstorming_design"
        )
        rendered = prompts.worker_episode_authority_block(
            amendments, None, complete
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
        incomplete = ok(
            contracts.KIND_DRAFT_SKELETON,
            artifact="docs/skeleton.md",
            slices=[{"id": 1, "title": "Worker"}],
        )
        repaired = copy.deepcopy(incomplete)
        repaired["episode_audit"] = [{"note": "checked live law"}]
        runner = runners.MockRunner([
            {
                "expect_kind": contracts.KIND_DRAFT_SKELETON,
                "response": incomplete,
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

        self.assertEqual(live_inputs.call_count, 1)
        self.assertEqual(len(runner.calls), 2)
        self.assertIn("SAFEGUARD episode-guard v2", runner.calls[0][2])
        self.assertTrue(runner.calls[1][2].startswith(runner.calls[0][2]))
        self.assertEqual(
            tasks.task_record(recovered.state, task["id"])["result"]["status"],
            "success",
        )
        self.assertEqual(
            tasks.task_record(recovered.state, task["id"])["order"]
            ["request"]["request"],
            frozen_prompt,
        )

    def test_validated_resume_carrier_consumes_without_authority_refresh(self):
        path = self._path("validated-carrier", st.UNIT_SLICE_DOC)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        task = driver._admit_worker_task(
            unit,
            contracts.KIND_DRAFT_SLICE_NOTE,
            "immutable admitted prompt",
            "codex",
        )
        native = ok(
            contracts.KIND_DRAFT_SLICE_NOTE,
            artifact="docs/note.md",
        )
        unit["brainstorming_resume"] = {
            "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "output": native,
            "raw_path": "raw/validated-carrier.txt",
            "duration_s": 1,
            "token_usage": _usage(2),
            "token_usage_partial": False,
            "cost": {"api_usd": 0.2, "real_usd": 0.1},
            "cost_partial": False,
            "text": "validated carrier",
            "provider_session_ref": "carrier-session",
            "family": "codex",
            "model": "gpt-5",
            "effort": "high",
            "pre_snapshot": {},
            "task_id": task["id"],
        }
        driver._save()

        with (
            mock.patch.object(
                driver,
                "_worker_episode_authority",
                side_effect=AssertionError(
                    "validated carrier refreshed authority"
                ),
            ),
            mock.patch.object(
                driver,
                "_act_profile",
                side_effect=AssertionError(
                    "validated carrier resolved current staffing"
                ),
            ),
        ):
            driver._do_draft()

        terminal = tasks.task_record(driver.state, task["id"])
        self.assertEqual(terminal["result"]["status"], "success")
        self.assertEqual(terminal["result"]["native_result"], native)
        self.assertNotIn("brainstorming_resume", unit)

    def test_validated_fixer_carrier_consumes_without_profile_resolution(self):
        path = self._path("validated-fixer-carrier", status=st.U_FIXING)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        task = driver._admit_worker_task(
            unit,
            contracts.KIND_FIX_FINDINGS,
            "immutable fixer prompt",
            "codex",
        )
        native = fix_ok([triaged("F1", "fixed", severity="P1")])
        unit["brainstorming_resume"] = {
            "kind": contracts.KIND_FIX_FINDINGS,
            "output": native,
            "raw_path": "raw/validated-fixer-carrier.txt",
            "duration_s": 1,
            "token_usage": _usage(2),
            "token_usage_partial": False,
            "cost": {"api_usd": 0.2, "real_usd": 0.1},
            "cost_partial": False,
            "text": "validated fixer carrier",
            "provider_session_ref": "fixer-carrier-session",
            "family": "codex",
            "model": "gpt-5",
            "effort": "high",
            "pre_snapshot": {},
            "task_id": task["id"],
        }

        with (
            mock.patch.object(
                driver,
                "_worker_episode_authority",
                side_effect=AssertionError("fixer carrier refreshed authority"),
            ),
            mock.patch.object(
                driver,
                "_act_profile",
                side_effect=AssertionError("fixer carrier resolved staffing"),
            ),
            mock.patch.object(
                driver,
                "_resolve_act",
                side_effect=AssertionError("fixer carrier resolved consultation"),
            ),
        ):
            driver._do_fix()

        terminal = tasks.task_record(driver.state, task["id"])
        self.assertEqual(terminal["result"]["status"], "success")
        self.assertEqual(terminal["result"]["native_result"], native)
        self.assertNotIn("brainstorming_resume", unit)

    def test_default_milestone_worker_cutover_preserves_all_six_kinds(self):
        fixed = fix_ok([triaged("F1", "fixed", severity="P1")])
        cases = (
            (contracts.KIND_DRAFT_SKELETON, st.UNIT_SKELETON, st.U_PENDING,
             ok(contracts.KIND_DRAFT_SKELETON,
                artifact="docs/skeleton.md", slices=[{"id": 1, "title": "Worker"}])),
            (contracts.KIND_DRAFT_SLICE_NOTE, st.UNIT_SLICE_DOC, st.U_PENDING,
             ok(contracts.KIND_DRAFT_SLICE_NOTE, artifact="docs/note.md")),
            (contracts.KIND_IMPLEMENT, st.UNIT_SLICE_IMPL, st.U_PENDING,
             ok(contracts.KIND_IMPLEMENT, files_changed=[])),
            (contracts.KIND_FIX_FINDINGS, st.UNIT_SLICE_IMPL, st.U_FIXING, fixed),
            (contracts.KIND_REVIEW_ROUND, st.UNIT_SLICE_IMPL, st.U_ROUNDS,
             report(contracts.KIND_REVIEW_ROUND)),
            (contracts.KIND_DELTA_REVIEW, st.UNIT_SLICE_IMPL, st.U_DELTA_REVIEW,
             report(contracts.KIND_DELTA_REVIEW)),
        )
        for number, (kind, unit_kind, status, response) in enumerate(cases):
            with self.subTest(kind=kind):
                path = self._path("kind-%d" % number, unit_kind, status)
                runner = runners.MockRunner([{"expect_kind": kind, "response": response}])
                with mock.patch.object(drv.gitops, "worktree_diff", return_value="delta"), \
                        mock.patch.object(drv.gitops, "amend", return_value="abc123"):
                    drv.Driver(path, runner=runner).step()
                state = st.load(path)
                task = self._task(state)
                self.assertEqual(len(tasks.task_records(state)), 1)
                self.assertEqual(task["order"]["task_executor"], "worker")
                self.assertEqual(task["order"]["configuration"], {})
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
        runner = runners.MockRunner([
            {"expect_kind": contracts.KIND_DRAFT_SKELETON, "response": "not json"},
            {"expect_kind": contracts.KIND_DRAFT_SKELETON,
             "response": ok(contracts.KIND_DRAFT_SKELETON,
                            artifact="docs/skeleton.md",
                            slices=[{"id": 1, "title": "Worker"}])},
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
            ),
        )
        self.assertEqual(frozen["worker"]["model"], "model-a")
        self.assertEqual(task["resolved_staffing"], frozen)
        self.assertEqual([call["model"] for call in runner.call_meta],
                         ["model-b", "model-b"])
        self.assertEqual(result.resolved_model, "model-b")
        self.assertEqual(output["artifact"], "docs/skeleton.md")

    def test_worker_note_keeps_nondefault_artifact_declaration(self):
        path = self._path("note-path", st.UNIT_SLICE_DOC)
        declared = "design/slices/one.md"
        response = ok(contracts.KIND_DRAFT_SLICE_NOTE, artifact=declared)
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

    def test_continuable_worker_rethink_repeats_and_completes_one_task(self):
        cases = (
            (contracts.KIND_DRAFT_SLICE_NOTE, st.UNIT_SLICE_DOC, st.U_PENDING,
             ok(contracts.KIND_DRAFT_SLICE_NOTE, artifact="docs/note.md")),
            (contracts.KIND_IMPLEMENT, st.UNIT_SLICE_IMPL, st.U_PENDING,
             ok(contracts.KIND_IMPLEMENT, files_changed=[])),
            (contracts.KIND_FIX_FINDINGS, st.UNIT_SLICE_IMPL, st.U_FIXING,
             fix_ok([triaged("F1", "fixed", severity="P1")])),
        )
        for index, (kind, unit_kind, status, completed) in enumerate(cases):
            with self.subTest(kind=kind):
                path = self._path("repeat-%d" % index, unit_kind, status)
                queued = st.current_unit(st.load(path)).get("fix_queue") or []
                signal = _rethink(kind, queued[0] if queued else None)
                runner = runners.MockRunner([
                    {"expect_kind": kind, "response": signal},
                    {"expect_kind": kind, "response": signal},
                    {"expect_kind": kind, "response": completed},
                ])
                with mock.patch.object(
                    adapter, "create_session",
                    side_effect=[_created("discussion-1"), _created("discussion-2")],
                ), mock.patch.object(
                    adapter, "terminal_handoff",
                    side_effect=[_handoff("discussion-1"), _handoff("discussion-2")],
                ):
                    for _ in range(4):
                        drv.Driver(path, runner=runner).step()
                state = st.load(path)
                task = self._task(state)
                origins = [e for e in state["events"]
                           if e["type"] == "brainstorming_origin_recorded"]
                self.assertEqual(len(tasks.task_records(state)), 1)
                self.assertEqual({e.get("task_id") for e in origins}, {task["id"]})
                self.assertEqual(task["result"]["native_result"], completed)

    def test_continuable_worker_abandonments_fail_and_reentry_succeeds_new_task(self):
        def paused(label, mode="proposal"):
            path = self._path(label)
            runner = runners.MockRunner([{
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": _rethink(contracts.KIND_IMPLEMENT, result_mode=mode),
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

        adoption = paused("adoption", "design_amendment")
        with mock.patch.object(adapter, "terminal_handoff",
                               return_value=_handoff("adoption")), \
                mock.patch.object(drv.Driver, "_adopt_brainstorming_design_amendment",
                                  side_effect=adapter.AdapterError("invalid amendment")):
            drv.Driver(adoption, runner=runners.MockRunner([])).step()
        self.assertEqual(self._task(st.load(adoption))["result"]["status"], "failure")

        waiting = paused("recoverable")
        with mock.patch.object(adapter, "terminal_handoff", return_value=None):
            drv.Driver(waiting, runner=runners.MockRunner([])).step()
        self.assertIsNone(self._task(st.load(waiting))["result"])

        retry = self._path("attachment")
        runner = runners.MockRunner([
            {"expect_kind": contracts.KIND_IMPLEMENT,
             "response": _rethink(contracts.KIND_IMPLEMENT)},
            {"expect_kind": contracts.KIND_IMPLEMENT,
             "response": ok(contracts.KIND_IMPLEMENT, files_changed=[])},
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

    def test_continuation_abandonment_preserves_origin_rethink_signal(self):
        cases = (
            (
                "blocked",
                contracts.KIND_IMPLEMENT,
                st.UNIT_SLICE_IMPL,
                st.U_PENDING,
                {
                    "status": "blocked",
                    "kind": contracts.KIND_IMPLEMENT,
                    "blocked_reason": "operator choice required",
                },
            ),
            (
                "gap",
                contracts.KIND_IMPLEMENT,
                st.UNIT_SLICE_IMPL,
                st.U_PENDING,
                {
                    "status": "gap",
                    "kind": contracts.KIND_IMPLEMENT,
                    "gaps": [failure_gap()],
                },
            ),
            (
                "retry",
                contracts.KIND_FIX_FINDINGS,
                st.UNIT_SLICE_IMPL,
                st.U_FIXING,
                {
                    "status": "retry",
                    "kind": contracts.KIND_FIX_FINDINGS,
                    "retry_reason": contracts.RETRY_CONSULTATION_UNAVAILABLE,
                    "notes": "consultation temporarily unavailable",
                },
            ),
        )
        for label, kind, unit_kind, status, abandoned in cases:
            with self.subTest(label=label):
                path = self._path(
                    "continuation-%s" % label, unit_kind, status
                )
                queued = st.current_unit(st.load(path)).get("fix_queue") or []
                signal = _rethink(kind, queued[0] if queued else None)
                runner = runners.MockRunner([
                    {"expect_kind": kind, "response": signal},
                    {"expect_kind": kind, "response": abandoned},
                ])
                with mock.patch.object(
                    adapter, "create_session", return_value=_created(label)
                ), mock.patch.object(
                    adapter,
                    "terminal_handoff",
                    return_value=_handoff(label),
                ):
                    for _ in range(3):
                        drv.Driver(path, runner=runner).step()

                task = self._task(st.load(path))
                self.assertEqual(task["result"]["status"], "failure")
                self.assertEqual(task["result"]["native_result"], signal)
                self.assertNotEqual(
                    task["result"]["native_result"], abandoned
                )

    def test_review_rethink_preserves_failed_origin_and_distinct_successor(self):
        for index, (kind, status) in enumerate((
            (contracts.KIND_REVIEW_ROUND, st.U_ROUNDS),
            (contracts.KIND_DELTA_REVIEW, st.U_DELTA_REVIEW),
        )):
            with self.subTest(kind=kind):
                path = self._path("review-%d" % index, status=status)
                signal = _rethink(kind, report_finding())
                clean = report(kind)
                runner = runners.MockRunner([
                    {"expect_kind": kind, "response": signal},
                    {"expect_kind": kind, "response": clean},
                ])
                with mock.patch.object(adapter, "create_session",
                                       return_value=_created("review")), \
                        mock.patch.object(adapter, "terminal_handoff",
                                          return_value=_handoff("review", work_duration_s=1)), \
                        mock.patch.object(drv.gitops, "worktree_diff", return_value="delta"), \
                        mock.patch.object(drv.gitops, "amend", return_value="abc123"):
                    for _ in range(3):
                        drv.Driver(path, runner=runner).step()
                state = st.load(path)
                records = tasks.task_records(state)
                unit = st.current_unit(state)
                origin_raw = next(e["raw_path"] for e in state["events"]
                                  if e["type"] == "brainstorming_origin_recorded")
                self.assertEqual([r["result"]["status"] for r in records],
                                 ["failure", "success"])
                self.assertEqual(records[0]["result"]["native_result"], signal)
                self.assertNotEqual(origin_raw, unit["rounds"][-1]["raw_path"])
                self.assertNotIn("task_id", next(e for e in state["events"]
                                                 if e["type"] == "brainstorming_work_recorded"))

    def test_review_rethink_crash_cannot_reuse_failed_origin_task(self):
        path = self._path("review-crash", status=st.U_ROUNDS)
        signal = _rethink(contracts.KIND_REVIEW_ROUND, report_finding())
        clean = report(contracts.KIND_REVIEW_ROUND)
        runner = runners.MockRunner([
            {"expect_kind": contracts.KIND_REVIEW_ROUND, "response": signal},
            {"expect_kind": contracts.KIND_REVIEW_ROUND, "response": clean},
        ])
        original_save = drv.Driver._save
        crashed_after_origin_save = []

        def save_then_crash_after_origin(subject):
            original_save(subject)
            if (
                not crashed_after_origin_save
                and any(
                    event["type"] == "brainstorming_origin_recorded"
                    for event in subject.state["events"]
                )
            ):
                crashed_after_origin_save.append(True)
                raise KeyboardInterrupt()

        with mock.patch.object(
            drv.Driver, "_save", new=save_then_crash_after_origin
        ), mock.patch.object(adapter, "create_session") as create_session:
            with self.assertRaises(KeyboardInterrupt):
                drv.Driver(path, runner=runner).step()
        create_session.assert_not_called()
        self.assertEqual(crashed_after_origin_save, [True])

        crashed = st.load(path)
        failed = self._task(crashed)
        self.assertEqual(failed["result"]["status"], "failure")
        self.assertEqual(failed["result"]["native_result"], signal)
        self.assertNotIn("active_task", st.current_unit(crashed))

        drv.Driver(path, runner=runner).step()
        records = tasks.task_records(st.load(path))
        self.assertEqual([record["result"]["status"] for record in records],
                         ["failure", "success"])
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

        def reached(_family, prompt, *_args, **_kwargs):
            seen.append(prompt)
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
        self.assertIn("FORCED CONTROLLED-CUTOFF RECOVERY", seen[0])
        self.assertIn("WORKER EPISODE AUTHORITY REFRESH", seen[0])
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

        def refresh(prompt):
            refreshes.append(prompt)
            return prompt + "\nFRESH AUTHORITY", ["new-extension"], ["root"]

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
                )
            )

        self.assertTrue(stabilized)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(len(refreshes), 1)
        self.assertIn("FORCED CONTROLLED-CUTOFF RECOVERY", refreshes[0])
        self.assertEqual(worker_call.call_count, 2)
        second = worker_call.call_args_list[1]
        self.assertIn("FRESH AUTHORITY", second.args[1])
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
        recovered = drv.Driver(path, runner=runners.MockRunner([]))
        seen = []

        def reached(_family, prompt, *_args, **_kwargs):
            seen.append(prompt)
            raise RuntimeError("dispatch reached")

        with (
            mock.patch.object(recovered, "_call", side_effect=reached),
            self.assertRaisesRegex(RuntimeError, "dispatch reached"),
        ):
            recovered._do_draft()

        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith("frozen admitted prompt\n\n"))
        self.assertIn("WORKER EPISODE AUTHORITY REFRESH", seen[0])
        self.assertIn("MUTABLE OPERATOR AMENDMENTS: COMPLETE", seen[0])
        self.assertIn("[A-after] Added after admission.", seen[0])
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
        seen = []

        def reached(_family, prompt, *_args, **_kwargs):
            seen.append(prompt)
            raise RuntimeError("implementation dispatch reached")

        with mock.patch.object(
            driver, "_call_implementation", side_effect=reached
        ):
            with self.assertRaisesRegex(
                RuntimeError, "implementation dispatch reached"
            ):
                driver._do_draft()

        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith("frozen implementation prompt\n\n"))
        self.assertIn("WORKER EPISODE AUTHORITY REFRESH", seen[0])
        self.assertIn("[A-implementation]", seen[0])
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

                recovered = drv.Driver(path, runner=runners.MockRunner([]))
                seen = []

                def reached(_family, prompt, *_args, **kwargs):
                    seen.append((prompt, kwargs.get("validate_opts")))
                    raise RuntimeError("strategy recovery dispatch reached")

                with mock.patch.object(recovered, "_call", side_effect=reached):
                    with self.assertRaisesRegex(
                        RuntimeError, "strategy recovery dispatch reached"
                    ):
                        recovered._do_draft()

                expected = copy.deepcopy(frozen_opts)
                self.assertEqual(len(seen), 1)
                self.assertTrue(seen[0][0].startswith(
                    "frozen strategy-specific prompt\n\n"
                ))
                self.assertIn(
                    "WORKER EPISODE AUTHORITY REFRESH", seen[0][0]
                )
                self.assertEqual(seen[0][1], expected)
                self.assertEqual(
                    task["order"]["request"]["context"]["worker_validation"],
                    expected or {},
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

    def test_rethink_continuation_keeps_frozen_strategy_and_refreshes_authority(self):
        cases = (
            ("legacy-to-strict", "legacy", "strict"),
            ("strict-to-legacy", "strict", "legacy"),
        )
        for label, admitted_name, current_name in cases:
            with self.subTest(label=label):
                path = self._path(
                    "continuation-%s" % label, st.UNIT_SLICE_DOC
                )
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

                signal = _rethink(contracts.KIND_DRAFT_SLICE_NOTE)
                runner = runners.MockRunner([{
                    "expect_kind": contracts.KIND_DRAFT_SLICE_NOTE,
                    "response": signal,
                }])
                with mock.patch.object(
                    adapter,
                    "create_session",
                    return_value=_created(label),
                ):
                    drv.Driver(path, runner=runner).step()

                changed = st.load(path)
                task = tasks.task_records(changed)[0]
                frozen_prompt = task["order"]["request"]["request"]
                frozen_opts = (
                    task["order"]["request"]["context"][
                        "worker_validation"
                    ] or None
                )
                current_profile = copy.deepcopy(
                    profiles.SEEDS[current_name]["profile"]
                )
                st.append_event(
                    changed,
                    "profile_changed",
                    **{
                        "from": admitted_ref,
                        "to": {
                            "name": current_name,
                            "version": 1,
                            "hash": profiles.semantic_hash(current_profile),
                        },
                        "profile": current_profile,
                    },
                )
                st.save(path, changed)

                continued = drv.Driver(path, runner=runners.MockRunner([]))
                os.makedirs(
                    os.path.dirname(continued._amendments_path()),
                    exist_ok=True,
                )
                with open(
                    continued._amendments_path(), "w", encoding="utf-8"
                ) as handle:
                    handle.write(
                        '{"amendments":[{"id":"A-live","text":'
                        '"Use live continuation authority."}]}'
                    )
                seen = []

                def reached(_family, prompt, *_args, **kwargs):
                    seen.append((prompt, kwargs.get("validate_opts")))
                    raise RuntimeError("continuation dispatch reached")

                with (
                    mock.patch.object(
                        adapter,
                        "terminal_handoff",
                        return_value=_handoff(label),
                    ),
                    mock.patch.object(continued, "_call", side_effect=reached),
                    self.assertRaisesRegex(
                        RuntimeError, "continuation dispatch reached"
                    ),
                ):
                    continued._do_brainstorming_wait()

                self.assertEqual(len(seen), 1)
                prompt, actual_opts = seen[0]
                self.assertEqual(actual_opts, frozen_opts)
                self.assertTrue(
                    prompt.startswith(
                        frozen_prompt.rstrip()
                        + "\n\nWORKER EPISODE AUTHORITY REFRESH\n"
                    )
                )
                self.assertIn("[A-live] Use live continuation authority.", prompt)
                self.assertIn("RETHINK CONTINUATION", prompt)
                self.assertEqual(
                    "BATTERY OUTPUT (mandatory in this run):" in prompt,
                    "BATTERY OUTPUT (mandatory in this run):" in frozen_prompt,
                )

    def test_legacy_rethink_continuation_gets_revoking_authority_block(self):
        path = self._path(
            "legacy-continuation-authority", st.UNIT_SLICE_DOC
        )
        origin_runner = runners.MockRunner([{
            "expect_kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "response": _rethink(contracts.KIND_DRAFT_SLICE_NOTE),
        }])
        origin = drv.Driver(path, runner=origin_runner)
        os.makedirs(
            os.path.dirname(origin._amendments_path()), exist_ok=True
        )
        with open(origin._amendments_path(), "w", encoding="utf-8") as handle:
            handle.write(
                '{"amendments":[{"id":"A-old","text":'
                '"Authority present before the retained wait."}]}'
            )
        with mock.patch.object(
            adapter,
            "create_session",
            return_value=_created("legacy-authority"),
        ):
            origin.step()

        legacy = st.load(path)
        unit = st.current_unit(legacy)
        unit.pop("active_task", None)
        unit["brainstorming_wait"]["origin"].pop("task_id", None)
        st.save(path, legacy)

        resumed = drv.Driver(path, runner=runners.MockRunner([]))
        with open(
            resumed._amendments_path(), "w", encoding="utf-8"
        ) as handle:
            handle.write('{"amendments":[]}')
        policy = {
            "id": "replacement-guard",
            "version": 2,
            "enabled": True,
            "scope": {
                "kinds": [contracts.KIND_DRAFT_SLICE_NOTE],
                "unit_kinds": [st.UNIT_SLICE_DOC],
            },
            "prompt": "Record the replacement safeguard check.",
            "contract": {
                "field": "replacement_ack",
                "required": True,
                "entry": {"note": {"type": "string"}},
                "checks": [{"kind": "non_empty", "field": "note"}],
            },
        }
        context = {
            "project": "orchestrators",
            "work_area": "implementation",
            "primary": {"path": resumed.workspace},
            "additional": [],
            "reuse_sources": None,
            "safeguards": [policy],
        }
        extension = verifiers.compile_policy(policy)
        seen = []

        def reached(_family, prompt, *_args, **kwargs):
            seen.append((prompt, kwargs.get("extensions")))
            raise RuntimeError("legacy continuation dispatch reached")

        with (
            mock.patch.object(
                adapter,
                "terminal_handoff",
                return_value=_handoff("legacy-authority"),
            ),
            mock.patch.object(
                resumed,
                "_project_prompt_inputs",
                return_value=(context, [extension], [resumed.workspace]),
            ),
            mock.patch.object(resumed, "_call", side_effect=reached),
            self.assertRaisesRegex(
                RuntimeError, "legacy continuation dispatch reached"
            ),
        ):
            resumed._do_brainstorming_wait()

        self.assertEqual(len(seen), 1)
        prompt, extensions = seen[0]
        self.assertIn("WORKER EPISODE AUTHORITY REFRESH", prompt)
        self.assertIn("MUTABLE OPERATOR AMENDMENTS: COMPLETE", prompt)
        self.assertIn("CURRENT MUTABLE OPERATOR AMENDMENTS: none.", prompt)
        self.assertNotIn("[A-old]", prompt)
        self.assertIn("PROJECT SAFEGUARDS: COMPLETE AND REPLACING", prompt)
        self.assertIn("SAFEGUARD replacement-guard v2", prompt)
        self.assertEqual(extensions, [extension])

    def test_delta_recovery_refreshes_authority_without_rewriting_order(self):
        path = self._path("delta-frozen-recovery", status=st.U_DELTA_REVIEW)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        task = driver._admit_worker_task(
            st.current_unit(driver.state),
            contracts.KIND_DELTA_REVIEW,
            "frozen delta-review prompt",
            "codex",
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

    def test_authority_loss_rollback_fails_admitted_task_before_retry(self):
        cases = (
            ("fixer-authority-read", st.U_FIXING,
             contracts.KIND_FIX_FINDINGS, True),
            ("delta-authority-integrity", st.U_DELTA_REVIEW,
             contracts.KIND_DELTA_REVIEW, False),
        )
        for label, status, kind, read_failure in cases:
            with self.subTest(label=label):
                path = self._path(label, status=status)
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
                    "brainstorming_authority": {
                        "session_id": "authority-session",
                        "accepted_target_revision": "accepted-authority",
                    },
                }
                abandoned = driver._admit_worker_task(
                    unit,
                    kind,
                    "frozen prompt that depends on provisional authority",
                    "codex",
                )
                origin_signal = None
                if kind == contracts.KIND_FIX_FINDINGS:
                    origin_signal = _rethink(kind, original_queue[0])
                    unit["brainstorming_resume"] = {
                        "kind": kind,
                        "output": fix_ok([
                            triaged("F1", "fixed", severity="P1")
                        ]),
                        "raw_path": "raw/stale-continuation.json",
                        "duration_s": 1,
                        "token_usage": _usage(7),
                        "token_usage_partial": False,
                        "cost": {"api_usd": 0.7, "real_usd": 0.4},
                        "cost_partial": False,
                        "text": "stale completed continuation",
                        "family": "codex",
                        "model": "gpt-5",
                        "effort": "high",
                        "pre_snapshot": {},
                        "origin_rethink_signal": origin_signal,
                        "task_id": abandoned["id"],
                    }

                integrity = None if read_failure else "authority changed"
                review_effect = (
                    RuntimeError("authority read failed")
                    if read_failure else unit["design_correction"]
                )
                with (
                    mock.patch.object(
                        driver,
                        "_design_correction_integrity_error",
                        return_value=integrity,
                    ),
                    mock.patch.object(
                        driver,
                        "_design_correction_review_context",
                        side_effect=(
                            review_effect if read_failure else None
                        ),
                    ),
                    mock.patch.object(drv.gitops, "restore_to_snapshot"),
                    mock.patch.object(drv.gitops, "restore_index_tree"),
                ):
                    if kind == contracts.KIND_FIX_FINDINGS:
                        outcome = driver._do_fix()
                    else:
                        outcome = driver._do_delta_review()

                terminal = tasks.task_record(driver.state, abandoned["id"])
                self.assertEqual(
                    outcome,
                    "design correction rejected; fixer retries without exception",
                )
                self.assertEqual(terminal["result"]["status"], "failure")
                if origin_signal is not None:
                    self.assertEqual(
                        terminal["result"]["native_result"], origin_signal
                    )
                    self.assertEqual(terminal["result"]["duration_s"], 1.0)
                    self.assertEqual(
                        terminal["result"]["token_usage"], _usage(7)
                    )
                    self.assertFalse(
                        terminal["result"]["token_usage_partial"]
                    )
                    self.assertEqual(
                        terminal["result"]["cost"],
                        {"api_usd": 0.7, "real_usd": 0.4},
                    )
                    self.assertFalse(terminal["result"]["cost_partial"])
                    accounting = [
                        event for event in driver.state["events"]
                        if event.get("type") == "worker_unaccepted"
                        and event.get("task_id") == abandoned["id"]
                    ]
                    self.assertEqual(len(accounting), 1)
                    self.assertEqual(accounting[0]["duration_s"], 1)
                    self.assertEqual(
                        st.summary(driver.state)["work_duration_s"], 1.0
                    )
                self.assertIn(
                    "design authority became unusable",
                    terminal["result"]["reason"],
                )
                self.assertNotIn("active_task", unit)
                self.assertNotIn("brainstorming_resume", unit)
                self.assertEqual(unit["status"], st.U_FIXING)

                if kind == contracts.KIND_FIX_FINDINGS:
                    driver.runner = runners.MockRunner([{
                        "expect_kind": contracts.KIND_FIX_FINDINGS,
                        "response": fix_ok([
                            triaged("F1", "fixed", severity="P1")
                        ]),
                    }])
                    driver._do_fix()
                    successor = tasks.task_records(driver.state)[-1]
                    self.assertEqual(successor["result"]["status"], "success")
                else:
                    successor = driver._admit_worker_task(
                        unit,
                        contracts.KIND_FIX_FINDINGS,
                        "retry without provisional authority",
                        "codex",
                    )
                self.assertNotEqual(successor["id"], abandoned["id"])

    def test_empty_delta_discards_completed_delta_review_handoff(self):
        path = self._path("delta-handoff-vanished", status=st.U_DELTA_REVIEW)
        signal = _rethink(contracts.KIND_DELTA_REVIEW, report_finding())
        runner = runners.MockRunner([{
            "expect_kind": contracts.KIND_DELTA_REVIEW,
            "response": signal,
        }])
        with mock.patch.object(
            adapter, "create_session", return_value=_created("delta-handoff")
        ), mock.patch.object(
            adapter,
            "terminal_handoff",
            return_value=_handoff("delta-handoff"),
        ), mock.patch.object(
            drv.gitops, "worktree_diff", return_value="pending delta"
        ):
            drv.Driver(path, runner=runner).step()
            drv.Driver(path, runner=runner).step()

        completed = st.load(path)
        self.assertEqual(
            st.current_unit(completed)["brainstorming_review_handoff"]["kind"],
            contracts.KIND_DELTA_REVIEW,
        )
        with mock.patch.object(drv.gitops, "worktree_diff", return_value=""):
            drv.Driver(path, runner=runner).step()

        closed = st.load(path)
        unit = st.current_unit(closed)
        self.assertNotIn("brainstorming_review_handoff", unit)
        self.assertIsNone(
            drv.Driver(path, runner=runner)._brainstorming_review_handoff(
                unit, contracts.KIND_REVIEW_ROUND
            )
        )

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
            mock.patch.object(recovered, "_call", side_effect=reached),
            self.assertRaisesRegex(RuntimeError, "dispatch reached"),
        ):
            recovered._do_fix()

        self.assertEqual(len(seen), 1)
        self.assertIn("KILLED-CALL NOTICE", seen[0])
        self.assertIn("frozen fixer prompt", seen[0])
        self.assertIn("WORKER EPISODE AUTHORITY REFRESH", seen[0])
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
