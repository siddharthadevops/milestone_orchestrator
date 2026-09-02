"""Focused proof for prospective sibling milestone verification cadence."""

import os
import subprocess
import tempfile
import unittest

from orchestrator import driver as drv, state as st, tasks
from orchestrator.tests import test_driver_mock as base


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

    def test_parts_count_once_and_open_or_failed_verification_blocks(self):
        subject = self._fixture(split=4)
        subject._prepare_milestone_verification()
        record = self._verification_records(subject)[0]
        context = subject._milestone_verification_context(record)
        self.assertEqual(context["completed_slice_ids"], [1, 2, 3, 4, 5])
        unit = subject._milestone_verification_unit(record)
        st.fail_run(subject.state, "suite blocked", unit=unit)
        subject._prepare_milestone_verification()
        self.assertEqual(tasks.task_record(subject.state, record["id"])[
            "result"]["status"], "failure")
        st.resume_run(subject.state)
        subject._save()
        subject = drv.Driver(self.path, runner=base.runners.MockRunner([]))
        subject._prepare_milestone_verification()
        self.assertIsNotNone(subject.state["failure"])
        self.assertEqual(len(self._verification_records(subject)), 1)

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
