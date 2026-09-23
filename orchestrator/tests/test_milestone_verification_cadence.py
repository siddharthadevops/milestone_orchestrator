"""Focused proof for prospective sibling milestone verification cadence."""

import copy
import os
import subprocess
import tempfile
import unittest

from orchestrator import canonical_plan, contracts, gitops
from orchestrator import driver as drv, state as st, tasks
from orchestrator.tests import test_driver_mock as base
from orchestrator.tests.test_suite_checkpoint_call import _document


class MilestoneVerificationCadenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="milestone-verify-")
        self.workspace = self.temp.name
        self._git("init", "-q")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "Tests")
        with open(os.path.join(self.workspace, "app.txt"), "w") as handle:
            handle.write("current\n")
        self._git("add", "app.txt")
        self._git("commit", "-qm", "baseline")
        self.config = base.make_config(verification=[base.VERIFY_CMD])
        self.path = os.path.join(self.workspace, ".git", "orchestrator-state.json")

    def tearDown(self):
        self.temp.cleanup()

    def _git(self, *args):
        return subprocess.run(
            ("git",) + args,
            cwd=self.workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _order(self, executor, configuration):
        return {
            "task_executor": executor,
            "configuration": configuration,
            "staffing_session": None,
            "request": {
                "work_area": {
                    "workspace_path": self.workspace,
                    "primary": self.workspace,
                    "additional": [],
                },
                "request": "Deliver the slice.",
                "context": {},
                "reference_documents": [],
            },
        }

    @staticmethod
    def _success(native=None):
        return tasks.validate_result({
            "status": "success",
            "duration_s": 0,
            "token_usage": None,
            "token_usage_partial": True,
            "cost": None,
            "cost_partial": True,
            "native_result": native or {},
        })

    def _complete_deep(
        self, state, slice_id, unit, existing=False, persist_admission=None
    ):
        parent = tasks.admit_task(
            state,
            self._order(
                "deep_task",
                tasks.resolve_deep_task_configuration({}, self.config),
            ),
            {},
            self.workspace,
        )
        child = tasks.admit_related_task(
            state,
            parent["id"],
            "implementation",
            unit.get("part") or "a",
            self._order(
                "reviewed_task",
                tasks.resolve_reviewed_task_configuration(
                    {"task_kind": "implement"}, self.config
                ),
            ),
            {},
            self.workspace,
        )
        if persist_admission is not None:
            persist_admission()
        child_result = self._success()
        tasks.record_task_result(state, child["id"], child_result)
        tasks.record_task_result(
            state,
            parent["id"],
            tasks.deep_task_result("success", [child_result]),
        )
        unit.update({
            "status": st.U_SEALED,
            "gate_commit": self._git("rev-parse", "--short", "HEAD"),
            "closed_record": {"slice_id": slice_id},
            "reviewed_task_id": child["id"],
        })
        if not existing:
            state["units"].append(unit)
        st.append_event(
            state, "slice_closed", unit=st.unit_key(unit), slice_id=slice_id
        )
        return parent

    def _fixture(self, total=6, completed=5, split=None, activated=True):
        state = st.new_state("goal", self.workspace, self.config)
        state["milestone"][st.SKELETON_COMPOSITION_KEY] = 1
        state["milestone"][st.DEEP_SLICE_COMPOSITION_KEY] = 1
        if activated:
            state["milestone"][st.MILESTONE_VERIFICATION_CADENCE_KEY] = 1
        state["milestone"]["canonical_plan_anchor"] = {
            "path": "skeleton.md",
            "revision": self._git("rev-parse", "HEAD"),
        }
        state["milestone"]["slices"] = [
            {"id": value, "title": "Slice %d" % value, "intent": "work"}
            for value in range(1, total + 1)
        ]
        state["units"][0].update({
            "status": st.U_SEALED,
            "artifact": "skeleton.md",
            "gate_commit": self._git("rev-parse", "--short", "HEAD"),
        })
        for slice_id in range(1, completed + 1):
            note = st._new_unit(st.UNIT_SLICE_DOC, slice_id)
            note.update({"status": st.U_SEALED, "artifact": "slice.md"})
            state["units"].append(note)
            implementation = st._new_unit(st.UNIT_SLICE_IMPL, slice_id)
            if slice_id == split:
                implementation["status"] = st.U_SEALED
                implementation["implementation_cut"] = {
                    "part": "a", "next_part": "b",
                    "cut_scope": "part a", "remaining_scope": "part b",
                }
                state["units"].append(implementation)
                implementation = st._new_unit(
                    st.UNIT_SLICE_IMPL, slice_id, part="b"
                )
            self._complete_deep(state, slice_id, implementation)
        drv._write_initial_amendments(self.path)
        st.save_new(self.path, state)
        return drv.Driver(self.path, runner=base.runners.MockRunner([]))

    def _verification_records(self, subject):
        return subject._milestone_verification_records()

    def _live_checkpoint(self, total=6, completed=5):
        document = _document(range(1, total + 1)) + (
            "\nIntermediate verification may leave unchanged consumers owned by "
            "pending slices NOT VERIFIED. New or unmapped failures block.\n"
        )
        for path, content in (
            ("skeleton.md", document),
            ("slice.md", "# Slice\n"),
            (".gitignore", "\n".join(gitops.ignore_lines()) + "\n"),
        ):
            base.write_file(path, content)(self.workspace)
        self._git("add", "-A")
        self._git("commit", "-qm", "verification authority")
        subject = self._fixture(total=total, completed=completed)
        subject.state["milestone"]["slices"] = canonical_plan.validate_canonical_plan(
            document
        )["projection"]
        subject._prepare_milestone_verification()
        unit = subject._milestone_verification_unit(
            self._verification_records(subject)[-1]
        )
        subject._prepare_complete_verification(unit)
        return subject, unit

    @staticmethod
    def _checkpoint_reply(status="not_verified", owner=6):
        output = {
            "kind": "suite_checkpoint", "status": status,
            "commands": [base.VERIFY_CMD],
            "authority": {"source": "operator_config", "evidence": []},
            "results": [{
                "command": base.VERIFY_CMD,
                "exit_code": 0 if status == "passed" else 1,
                "evidence": "Unchanged old consumer needs the pending migration.",
            }],
        }
        if status == "not_verified":
            output["deferred_failures"] = [{
                "command": base.VERIFY_CMD, "owner_slice_id": owner,
                "authorization": "skeleton.md: intermediate verification exception",
                "evidence": "The unchanged consumer is owned by slice %d; all "
                            "failures come from this removed API." % owner,
            }]
        elif status == "failed":
            output["failure_account"] = {
                "command": base.VERIFY_CMD, "exit_code": 1,
                "diagnostics": "A new current-slice defect remains in app.txt, "
                               "in addition to an authorized future consumer failure.",
                "affected_tests": ["current_slice_regression"],
            }
        return output

    def _run_checkpoint(self, subject, unit, output, side_effect=None):
        subject.runner = base.runners.MockRunner([
            base.step("suite_checkpoint", output, side_effect=side_effect),
        ])
        return subject.reviewed_work.execute(subject.reviewed_work.next_action(unit))

    def test_periodic_not_verified_completes_and_resumes_without_green_proof(self):
        subject, unit = self._live_checkpoint()
        reply = self._checkpoint_reply()
        _note, sealed, _context, result = self._run_checkpoint(
            subject, unit, reply,
            side_effect=base.write_file("snapshot.txt", "normal suite output\n"),
        )
        self.assertIs(sealed, unit)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["native_result"]["production_result"], reply)
        self.assertIsNotNone(subject._current_checkpoint_completion_event(unit))
        self.assertIsNone(subject._current_complete_verification_event(unit))
        event = subject._current_checkpoint_completion_event(unit)
        self.assertFalse(event["ok"])
        self.assertEqual(event["deferred_failures"], reply["deferred_failures"])
        self.assertEqual(unit["fix_queue"], [])
        self.assertEqual(self._git("show", "HEAD:snapshot.txt"), "normal suite output")
        self.assertEqual(self._git("status", "--porcelain"), "")
        # Simulate a crash after the Git gate, before consuming the task result.
        subject._save()
        subject = drv.Driver(self.path, runner=base.runners.MockRunner([]))
        self.assertTrue(subject._prepare_milestone_verification())
        self.assertFalse(subject._prepare_milestone_verification())
        self.assertEqual(len(self._verification_records(subject)), 1)
        self.assertFalse(subject._milestone_final_verification_current())
        self.assertIsNone(subject.state["failure"])

        # The final slice requires its own green proof even after this exception.
        self._complete_deep(
            subject.state, 6, st._new_unit(st.UNIT_SLICE_IMPL, 6),
            persist_admission=subject._save,
        )
        subject._save()
        self.assertTrue(subject._prepare_milestone_verification())
        final_unit = subject._milestone_verification_unit(
            self._verification_records(subject)[-1]
        )
        self.assertIsNone(subject._periodic_checkpoint_context(final_unit))
        self.assertFalse(subject._milestone_final_verification_current())
        subject._prepare_complete_verification(final_unit)
        _note, sealed, _context, result = self._run_checkpoint(
            subject, final_unit, self._checkpoint_reply("passed")
        )
        self.assertIs(sealed, final_unit)
        subject._consume_milestone_verification_result(final_unit, result)
        self.assertTrue(subject._milestone_final_verification_current())

    def test_periodic_gate_rejects_bytes_changed_after_not_verified(self):
        subject, unit = self._live_checkpoint()
        subject.runner = base.runners.MockRunner([
            base.step("suite_checkpoint", self._checkpoint_reply()),
        ])
        subject._do_verify(unit)
        self.assertEqual(unit["status"], st.U_SEALED)
        base.write_file("app.txt", "changed after checkpoint\n")(self.workspace)
        subject._gate_commit(unit)
        self.assertEqual(unit["status"], st.U_PRE_SEAL_VERIFY)
        self.assertIsNone(subject.reviewed_work.result(unit))
        self.assertFalse(unit.get("gate_commit"))

    def test_final_at_multiple_of_five_cannot_defer_failed_suite(self):
        subject, unit = self._live_checkpoint(total=5)
        context = subject._milestone_verification_context(
            self._verification_records(subject)[-1]
        )
        self.assertTrue(context["periodic"])
        self.assertTrue(context["final"])
        self.assertIsNone(subject._periodic_checkpoint_context(unit))
        prepared = subject._routed_suite_checkpoint_prepare_call(
            unit, tasks.REVIEWED_COMPLETE_VERIFICATION, [base.VERIFY_CMD]
        )(None)
        with self.assertRaises(contracts.ContractError):
            prepared.validate(self._checkpoint_reply())
        self._run_checkpoint(subject, unit, self._checkpoint_reply("failed"))
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertFalse(subject._milestone_final_verification_current())

    def test_periodic_mixed_failure_repair_requires_fresh_checkpoint(self):
        subject, unit = self._live_checkpoint()
        self._run_checkpoint(subject, unit, self._checkpoint_reply("failed"))
        queued = unit["fix_queue"][0]
        subject.runner.script.extend([
            base.step("fix_findings", base.fix_ok([
                base.triaged(queued["id"], "fixed", queued["summary"], severity="P1")
            ], files_changed=["app.txt"]),
                side_effect=base.write_file("app.txt", "current defect repaired\n")),
            base.step("delta_review", base.report("delta_review")),
            base.step("review_round", base.report("review_round")),
            base.step("review_round", base.report("review_round")),
            base.step("suite_checkpoint", self._checkpoint_reply()),
        ])
        result = None
        for _ in range(12):
            _note, _sealed, _context, result = subject.reviewed_work.execute(
                subject.reviewed_work.next_action(unit)
            )
            if result is not None:
                break
        self.assertIsNotNone(result)
        self.assertEqual(result["native_result"]["production_result"]["status"],
                         "not_verified")
        events = [e for e in subject.state["events"] if e["type"] == "verification"]
        self.assertEqual([e["status"] for e in events], ["failed", "not_verified"])
        self.assertFalse(any(e.get("fixer_certified") for e in events))
        self.assertEqual(sum(kind == "suite_checkpoint" for _, kind, _ in
                             subject.runner.calls), 2)
        fixer_prompt = next(prompt for _, kind, prompt in subject.runner.calls
                            if kind == "fix_findings")
        self.assertNotIn("Return top-level `blocked` if you cannot leave the suite green",
                         fixer_prompt)
        self.assertEqual(len(unit["seals"][-1]["reviews"]), 2)
        subject._consume_milestone_verification_result(unit, result)
        self.assertFalse(subject._prepare_milestone_verification())

    def test_periodic_rejected_failure_cannot_repeat_past_existing_repair_cap(self):
        subject, unit = self._live_checkpoint()
        unit["reviewed_policy"]["max_fix_loops"] = 1
        self._run_checkpoint(subject, unit, self._checkpoint_reply("failed"))
        queued = unit["fix_queue"][0]
        subject.runner.script.extend([
            base.step("fix_findings", base.fix_ok([
                base.triaged(queued["id"], "rejected", queued["summary"], severity="P1")
            ])),
            base.step("delta_review", base.report("delta_review")),
            base.step("review_round", base.report("review_round")),
            base.step("review_round", base.report("review_round")),
            base.step("suite_checkpoint", self._checkpoint_reply("failed")),
        ])
        # Recording a rejection can itself update the adjudication artifact.
        for _ in range(8):
            subject.reviewed_work.execute(subject.reviewed_work.next_action(unit))
            if unit["status"] == st.U_PRE_SEAL_VERIFY:
                break
        self.assertEqual(unit["status"], st.U_PRE_SEAL_VERIFY)
        self.assertEqual(unit["verify_fix_attempts"]["pre_seal"], 1)
        with self.assertRaisesRegex(drv.StopStep, "periodic suite repair cap"):
            subject.reviewed_work.execute(subject.reviewed_work.next_action(unit))
        self.assertIsNotNone(subject.state["failure"])
        self.assertIsNone(subject.reviewed_work.result(unit))
        self.assertFalse(any(e.get("fixer_certified") for e in subject.state["events"]))

    def _mark_verification_success(self, subject):
        record = self._verification_records(subject)[-1]
        unit = subject._milestone_verification_unit(record)
        event = st.append_event(
            subject.state,
            "verification",
            unit=st.unit_key(unit),
            cadence=tasks.REVIEWED_COMPLETE_VERIFICATION,
            status="passed",
            ok=True,
            stable=True,
            commands=[base.VERIFY_CMD],
            candidate_after=subject._verification_candidate_fingerprint(),
        )
        unit["seals"].append({
            "attempt": 1,
            "reviews": [],
            "verification_event_seq": event["seq"],
        })
        unit["status"] = st.U_SEALED
        st.append_event(subject.state, "seal_satisfied", unit=st.unit_key(unit))
        unit["gate_commit"] = self._git("rev-parse", "HEAD")
        st.append_event(
            subject.state, "gate_commit",
            unit=st.unit_key(unit), sha=unit["gate_commit"],
        )
        result = subject.reviewed_work.result(unit)
        self.assertIsNotNone(result)
        self.assertTrue(subject._consume_milestone_verification_result(
            unit, result
        ))
        subject._save()
        return record

    def test_five_completed_deep_tasks_admit_one_sibling_before_slice_six(self):
        subject = self._fixture()
        self.assertTrue(subject._prepare_milestone_verification())
        records = self._verification_records(subject)
        self.assertEqual(len(records), 1)
        self.assertNotIn("parent", records[0])
        self.assertEqual(
            records[0]["order"]["configuration"]["task_kind"],
            tasks.REVIEWED_COMPLETE_VERIFICATION,
        )
        self.assertEqual(st.current_unit(subject.state)["kind"],
                         st.UNIT_MILESTONE_VERIFICATION)
        self.assertFalse(subject._prepare_milestone_verification())
        self.assertEqual(len(self._verification_records(subject)), 1)
        self.assertFalse(any(
            record["order"]["task_executor"] == "deep_task"
            and record["order"]["request"]["context"].get(
                "milestone_slice_id"
            ) == 6
            for record in tasks.task_records(subject.state)
        ))

    def test_parts_count_once_and_explicit_resume_admits_fresh_verification(self):
        subject = self._fixture(split=4)
        subject._prepare_milestone_verification()
        record = self._verification_records(subject)[0]
        context = subject._milestone_verification_context(record)
        self.assertEqual(context["completed_slice_ids"], [1, 2, 3, 4, 5])
        self.assertFalse(subject._prepare_milestone_verification())
        self.assertEqual(len(self._verification_records(subject)), 1)
        unit = subject._milestone_verification_unit(record)
        unit["status"] = st.U_PRE_SEAL_VERIFY
        st.fail_run(
            subject.state, "suite blocked", unit=unit,
            type_="suite_checkpoint",
        )
        subject._prepare_milestone_verification()
        failed_result = copy.deepcopy(
            tasks.task_record(subject.state, record["id"])["result"]
        )
        self.assertEqual(failed_result["status"], "failure")
        st.resume_run(subject.state)
        subject._save()
        subject = drv.Driver(self.path, runner=base.runners.MockRunner([]))

        self.assertTrue(subject._prepare_milestone_verification())

        records = self._verification_records(subject)
        self.assertIsNone(subject.state["failure"])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["result"], failed_result)
        self.assertEqual(
            subject._milestone_verification_unit(records[0])["status"],
            st.U_FAILED,
        )
        self.assertNotEqual(records[1]["id"], records[0]["id"])
        self.assertIsNone(records[1]["result"])
        self.assertEqual(
            subject._milestone_verification_context(records[1]), context
        )
        self.assertEqual(
            st.unit_key(subject._milestone_verification_unit(records[1])),
            "milestone_verification-2",
        )

    def test_each_terminal_failure_requires_resume_and_restart_never_duplicates(self):
        subject = self._fixture()
        self.assertTrue(subject._prepare_milestone_verification())
        failed_results = []

        for attempt in (1, 2):
            with self.subTest(attempt=attempt):
                records = self._verification_records(subject)
                self.assertEqual(len(records), attempt)
                unit = subject._milestone_verification_unit(records[-1])
                unit["status"] = st.U_PRE_SEAL_VERIFY
                st.fail_run(
                    subject.state, "suite blocked attempt %d" % attempt,
                    unit=unit, type_="suite_checkpoint",
                )
                self.assertTrue(subject._prepare_milestone_verification())
                failed_results.append(copy.deepcopy(
                    self._verification_records(subject)[-1]["result"]
                ))

                self.assertFalse(subject._prepare_milestone_verification())
                subject = drv.Driver(
                    self.path, runner=base.runners.MockRunner([])
                )
                self.assertFalse(subject._prepare_milestone_verification())
                self.assertIsNotNone(subject.state["failure"])
                self.assertEqual(
                    len(self._verification_records(subject)), attempt
                )

                st.resume_run(subject.state)
                subject._save()
                subject = drv.Driver(
                    self.path, runner=base.runners.MockRunner([])
                )
                self.assertTrue(subject._prepare_milestone_verification())
                self.assertIsNone(subject.state["failure"])
                records = self._verification_records(subject)
                self.assertEqual(len(records), attempt + 1)
                self.assertEqual(
                    sum(record["result"] is None for record in records), 1
                )
                for old_record, result in zip(records, failed_results):
                    self.assertEqual(old_record["result"], result)
                    self.assertEqual(
                        subject._milestone_verification_unit(old_record)["status"],
                        st.U_FAILED,
                    )
                self.assertEqual(
                    st.unit_key(subject._milestone_verification_unit(records[-1])),
                    "milestone_verification-%d" % (attempt + 1),
                )

                subject = drv.Driver(
                    self.path, runner=base.runners.MockRunner([])
                )
                self.assertFalse(subject._prepare_milestone_verification())
                self.assertEqual(
                    len(self._verification_records(subject)), attempt + 1
                )
                self.assertEqual(subject.runner.calls, [])

    def test_final_reuses_only_current_active_five_slice_verification(self):
        subject = self._fixture(total=5)
        subject._prepare_milestone_verification()
        self._mark_verification_success(subject)
        self.assertTrue(subject._milestone_final_verification_current())
        self.assertFalse(subject._prepare_milestone_verification())
        with open(os.path.join(self.workspace, "app.txt"), "w") as handle:
            handle.write("changed after proof\n")
        self.assertFalse(subject._milestone_final_verification_current())
        self.assertTrue(subject._prepare_milestone_verification())
        self.assertEqual(len(self._verification_records(subject)), 2)

    def test_crash_and_reconciliation_never_duplicate_or_reuse_superseded_verification(self):
        subject = self._fixture(total=5)
        subject._prepare_milestone_verification()
        first = self._verification_records(subject)[0]
        subject = drv.Driver(self.path, runner=base.runners.MockRunner([]))
        self.assertFalse(subject._prepare_milestone_verification())
        self.assertEqual(len(self._verification_records(subject)), 1)

        unit = next(
            item for item in subject.state["units"]
            if item.get("kind") == st.UNIT_SLICE_IMPL
            and item.get("slice_id") == 5
        )
        st.requeue_implementation_after_reconciliation(
            subject.state, unit, "accepted-revision"
        )
        unit.pop("reviewed_task_id", None)
        subject._save()
        self._complete_deep(
            subject.state, 5, unit, existing=True,
            persist_admission=subject._save,
        )
        subject._save()
        subject._prepare_milestone_verification()
        self.assertEqual(tasks.task_record(subject.state, first["id"])[
            "result"]["status"], "failure")
        self.assertEqual(len(self._verification_records(subject)), 2)
        self.assertEqual(sum(
            record["result"] is None
            for record in self._verification_records(subject)
        ), 1)

    def test_activation_replaces_only_new_runs_in_slice_cadence(self):
        activated = self._fixture(total=1, completed=0)
        unit = st._new_unit(st.UNIT_SLICE_IMPL, 1)
        activated.state["units"].extend((
            st._new_unit(st.UNIT_SLICE_DOC, 1), unit,
        ))
        self.assertIsNone(activated._in_slice_verification_cadence(unit))
        activated.state["milestone"].pop(
            st.MILESTONE_VERIFICATION_CADENCE_KEY
        )
        self.assertEqual(
            activated._in_slice_verification_cadence(unit), "milestone_final"
        )
        self.assertEqual(drv.FULL_VERIFICATION_SLICE_INTERVAL, 4)


if __name__ == "__main__":
    unittest.main()
