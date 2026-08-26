import copy
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming_milestone, brainstorming_tasks
from orchestrator import canonical_plan, driver, gitops, plan_reconciliation
from orchestrator import runners
from orchestrator import state as st


def _slice(slice_id, title=None):
    return {
        "id": slice_id,
        "title": title or "Slice %d" % slice_id,
        "intent": "Deliver slice %d" % slice_id,
        "producer_task_executor": {
            "draft_slice_note": "agent_call",
            "implement": "agent_call",
        },
    }


def _document(slices):
    payload = json.dumps(
        {"slices": slices}, separators=(",", ":"), ensure_ascii=False
    )
    return "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n" % payload


class PlanReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="plan-reconcile-")
        self.workspace = self.temp.name
        self._git("init", "-q")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "Tests")
        self.path = "skeleton.md"
        self.old_plan = [_slice(value) for value in (1, 2, 3, 4)]
        self._write(self.path, _document(self.old_plan))
        self.milestone_start = self._commit("milestone start")

        self._write("slice-1.txt", "done\n")
        self.slice_1_gate = self._commit("slice 1 gate")
        self._write("slice-2.txt", "done\n")
        self.slice_2_gate = self._commit("slice 2 gate")
        self.source_base = self.slice_2_gate

        self.state = st.new_state(
            "goal", self.workspace, {"families_order": []}
        )
        self.state["milestone"]["slices"] = [{"id": 99}]
        self.state["units"] = [
            self._unit(st.UNIT_SKELETON, None, self.milestone_start),
            self._unit(st.UNIT_SLICE_DOC, 1, self.slice_1_gate),
            self._unit(st.UNIT_SLICE_IMPL, 1, self.slice_1_gate),
            self._unit(st.UNIT_SLICE_DOC, 2, self.slice_2_gate),
            self._unit(st.UNIT_SLICE_IMPL, 2, self.slice_2_gate),
            self._unit(st.UNIT_SLICE_DOC, 3, None, status=st.U_PENDING),
        ]
        st.append_event(
            self.state,
            "gate_commit",
            unit=st.UNIT_SKELETON,
            sha=self.milestone_start,
        )
        st.append_event(
            self.state,
            "verification",
            unit="slice_impl-01",
            status="passed",
            ok=True,
            stable=True,
            cadence="four_slice_checkpoint",
        )
        st.append_event(self.state, "slice_closed", unit="slice_impl-01")
        st.append_event(
            self.state,
            "verification",
            unit="slice_impl-02",
            status="no_suite",
            ok=True,
            stable=True,
            cadence="four_slice_checkpoint",
        )
        st.append_event(self.state, "slice_closed", unit="slice_impl-02")

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

    def _write(self, relative, content):
        path = os.path.join(self.workspace, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def _commit(self, message):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD")

    def _initialize_run(self, state_path, run_state):
        driver._write_initial_amendments(state_path)
        st.save(state_path, run_state)

    def _unit(self, kind, slice_id, gate, status=st.U_SEALED):
        unit = st._new_unit(kind, slice_id)
        unit["status"] = status
        unit["gate_commit"] = (
            None if gate is None else gate[:12]
        )
        if kind == st.UNIT_SLICE_IMPL and status == st.U_SEALED:
            unit["closed_record"] = {"slice_id": slice_id}
        return unit

    def _accept(self, slices):
        self._write(self.path, _document(slices))
        accepted = self._commit("accepted plan")
        self.state["milestone"][canonical_plan.ANCHOR_KEY] = {
            "path": self.path,
            "revision": accepted,
        }
        return accepted

    def _observe(self, accepted, source=None):
        return plan_reconciliation.observe_accepted_range(
            self.state,
            self.source_base,
            accepted,
            source=source,
        )

    def _accepted_session_driver(self):
        accepted_plan = [_slice(value) for value in (1, 3, 4)]
        accepted = self._accept(accepted_plan)
        config = driver.load_config(None)
        driver.merge_config(config, {
            "git": {"enabled": True},
            "error_classifier": False,
            "infra_retry_backoff_s": [],
        })
        run_state = st.new_state("goal", self.workspace, config)
        run_state["milestone"]["slices"] = copy.deepcopy(
            canonical_plan.validate_canonical_plan(
                _document(accepted_plan), _document(self.old_plan)
            )["projection"]
        )
        run_state["milestone"][canonical_plan.ANCHOR_KEY] = {
            "path": self.path,
            "revision": accepted,
        }
        run_state["units"] = [
            self._unit(st.UNIT_SKELETON, None, self.milestone_start),
            self._unit(st.UNIT_SLICE_DOC, 1, self.slice_1_gate),
            self._unit(st.UNIT_SLICE_IMPL, 1, self.slice_1_gate),
            self._unit(st.UNIT_SLICE_DOC, 2, self.slice_2_gate),
            self._unit(
                st.UNIT_SLICE_IMPL, 2, None, status=st.U_PENDING
            ),
        ]
        st.append_event(
            run_state,
            "gate_commit",
            unit=st.UNIT_SKELETON,
            sha=self.milestone_start,
        )
        state_path = driver.default_state_path(self.workspace)
        self._initialize_run(state_path, run_state)
        subject = driver.Driver(state_path)
        unit = next(
            candidate for candidate in subject.state["units"]
            if st.unit_key(candidate) == "slice_impl-02"
        )
        return subject, unit, accepted

    def test_range_ignores_projection_as_before_authority(self):
        accepted = self._accept([_slice(value) for value in (1, 3, 4)])

        result = self._observe(accepted)

        self.assertEqual(result["status"], "opened")
        record = result["reconciliation"]
        self.assertEqual(
            [item["id"] for item in record["original_old_plan"]],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            [item["id"] for item in record["accepted_plan"]],
            [1, 3, 4],
        )
        self.assertEqual(self.state["milestone"]["slices"], [{"id": 99}])

    def test_forward_only_changes_do_not_open_reconciliation(self):
        accepted_plan = [
            _slice(1, "renamed retained slice"),
            _slice(2),
            _slice(3),
            _slice(5),
        ]
        accepted = self._accept(accepted_plan)
        before = copy.deepcopy(self.state)

        result = self._observe(accepted, source={"kind": "review_round"})

        self.assertEqual(result["status"], "no_wipe")
        self.assertEqual(result["source"], {"kind": "review_round"})
        self.assertEqual(
            [item["id"] for item in result["old_plan"]], [1, 2, 3, 4]
        )
        self.assertEqual(
            [item["id"] for item in result["accepted_plan"]], [1, 2, 3, 5]
        )
        self.assertEqual(self.state, before)

    def test_code_only_session_range_does_not_require_anchor_to_advance(self):
        self.state["milestone"][canonical_plan.ANCHOR_KEY] = {
            "path": self.path,
            "revision": self.milestone_start,
        }
        self._write("implementation.txt", "session delivery\n")
        accepted = self._commit("accepted code-only session")
        before = copy.deepcopy(self.state)

        result = self._observe(
            accepted,
            source={"executor": "brainstorming", "job": "implement"},
        )

        self.assertEqual(result["status"], "no_wipe")
        self.assertNotEqual(self.source_base, accepted)
        self.assertEqual(result["old_plan"], result["accepted_plan"])
        self.assertEqual(self.state, before)

    def test_started_delete_and_reorder_choose_earliest_boundary(self):
        accepted = self._accept([_slice(value) for value in (1, 4, 3)])

        record = self._observe(accepted)["reconciliation"]
        account = record["opening_account"]

        self.assertEqual(account["boundary_old_plan_index"], 1)
        self.assertEqual(account["boundary_slice_id"], 2)
        self.assertEqual(
            account["triggers"],
            ["started_deletion", "historical_positional_divergence"],
        )
        self.assertEqual(account["wipe_boundary"], self.slice_1_gate)
        self.assertEqual(record["wipe_boundary"], self.slice_1_gate)

    def test_opening_account_captures_original_units_requeue_and_checkpoints(self):
        accepted = self._accept([_slice(value) for value in (1, 3, 4)])
        units_before = copy.deepcopy(self.state["units"])
        events_before = copy.deepcopy(self.state["events"])
        head_before = gitops.head_full_sha(self.workspace)
        source = {"kind": "brainstorming", "task_id": "task-10"}

        result = self._observe(accepted, source=source)
        source["task_id"] = "changed-after-call"

        record = result["reconciliation"]
        account = record["opening_account"]
        self.assertEqual(record["source"]["task_id"], "task-10")
        self.assertEqual(record["source_base_revision"], self.source_base)
        self.assertEqual(record["accepted_revision"], accepted)
        self.assertEqual(
            record["original_run_boundaries"]["milestone_start_revision"],
            self.milestone_start,
        )
        self.assertEqual(
            account["invalidated_units"],
            ["slice_doc-02", "slice_impl-02", "slice_doc-03"],
        )
        self.assertEqual(account["invalidated_slice_ids"], [2, 3])
        self.assertEqual(account["requeue_slice_ids"], [3])
        self.assertEqual(
            [item["unit"] for item in account["checkpoint_invalidations"]],
            ["slice_impl-02"],
        )
        self.assertEqual(self.state["units"], units_before)
        self.assertEqual(self.state["events"], events_before)
        self.assertEqual(gitops.head_full_sha(self.workspace), head_before)
        self.assertEqual(self._git("status", "--porcelain"), "")
        self.assertEqual(
            self.state["milestone"][canonical_plan.RECONCILIATION_KEY],
            record,
        )

    def test_first_started_slice_uses_milestone_start_revision(self):
        accepted = self._accept([_slice(value) for value in (2, 3, 4)])

        account = self._observe(accepted)["reconciliation"]["opening_account"]

        self.assertEqual(account["boundary_old_plan_index"], 0)
        self.assertEqual(account["wipe_boundary"], self.milestone_start)

    def test_wipe_stops_before_contract_correction_dispatch(self):
        config = driver.load_config(None)
        driver.merge_config(config, {
            "git": {"enabled": True},
            "error_classifier": False,
            "infra_retry_backoff_s": [],
        })
        run_state = st.new_state("goal", self.workspace, config)
        run_state["milestone"]["slices"] = copy.deepcopy(
            canonical_plan.validate_canonical_plan(
                _document(self.old_plan)
            )["projection"]
        )
        run_state["milestone"][canonical_plan.ANCHOR_KEY] = {
            "path": self.path,
            "revision": self.source_base,
        }
        skeleton = run_state["units"][0]
        skeleton.update({
            "status": st.U_SEALED,
            "artifact": self.path,
            "gate_commit": self.milestone_start[:12],
        })
        st.append_event(
            run_state,
            "gate_commit",
            unit=st.UNIT_SKELETON,
            sha=self.milestone_start,
        )
        st.ensure_due_unit(run_state)
        state_path = driver.default_state_path(self.workspace)
        self._initialize_run(state_path, run_state)

        def append_future_plan(workspace):
            self._write(self.path, _document([
                _slice(value) for value in (1, 2, 3, 4, 5)
            ]))
            self._write("docs/slice-01.md", "# Slice 01\n")

        def reorder_historical_plan(workspace):
            self._write(self.path, _document([
                _slice(value) for value in (2, 1, 3, 4, 5)
            ]))

        subject = driver.Driver(
            state_path,
            runner=runners.MockRunner([
                {
                    "expect_kind": "draft_slice_note",
                    "side_effect": append_future_plan,
                    # The valid forward-only plan survives this invalid reply
                    # and the ordinary one-shot correction may dispatch.
                    "response": {"bad": True},
                },
                {
                    "expect_kind": "draft_slice_note",
                    "side_effect": reorder_historical_plan,
                    # The historical wipe freezes before this reply is parsed.
                    "response": {"still_bad": True},
                },
            ]),
        )

        action, _note = subject.step()

        self.assertEqual(action.type, driver.A_RECONCILIATION)
        self.assertEqual(len(subject.runner.calls), 2)
        self.assertEqual(driver.decide(subject.state).type, driver.A_RECONCILIATION)
        self.assertIsNone(subject.state["failure"])
        current = next(
            unit for unit in subject.state["units"]
            if st.unit_key(unit) == "slice_doc-01"
        )
        self.assertEqual(current["status"], st.U_PENDING)
        self.assertIsNone(current["draft"])
        record = subject.state["milestone"][
            canonical_plan.RECONCILIATION_KEY
        ]
        self.assertEqual(record["source"]["job"], "draft_slice_note@slice_doc")
        self.assertEqual(record["source"]["physical_attempt"], 2)
        self.assertEqual(record["source"]["range_start_attempt"], 1)
        self.assertEqual(record["opening_account"]["boundary_old_plan_index"], 0)
        first_range = next(
            event for event in subject.state["events"]
            if event.get("type") == "canonical_plan_range_accepted"
        )
        self.assertEqual(
            record["source_base_revision"],
            first_range["source_base_revision"],
        )
        self.assertEqual(
            gitops.head_full_sha(self.workspace), record["accepted_revision"]
        )

    def test_initial_plan_establishment_does_not_open_reconciliation(self):
        with tempfile.TemporaryDirectory(prefix="initial-plan-") as workspace:
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=workspace,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Tests"],
                cwd=workspace,
                check=True,
            )
            os.makedirs(os.path.join(workspace, "docs"))
            skeleton_path = os.path.join(workspace, "docs", "skeleton.md")
            with open(skeleton_path, "w", encoding="utf-8") as handle:
                handle.write("# Pending skeleton\n")
            subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "baseline"],
                cwd=workspace,
                check=True,
            )
            config = driver.load_config(None)
            driver.merge_config(config, {
                "git": {"enabled": True},
                "docs_dir": "docs",
                "error_classifier": False,
                "infra_retry_backoff_s": [],
            })
            run_state = st.new_state("goal", workspace, config)
            state_path = driver.default_state_path(workspace)
            self._initialize_run(state_path, run_state)

            def write_initial_plan(_workspace):
                with open(skeleton_path, "w", encoding="utf-8") as handle:
                    handle.write(_document([_slice(1)]))

            subject = driver.Driver(
                state_path,
                runner=runners.MockRunner([{
                    "expect_kind": "draft_skeleton",
                    "side_effect": write_initial_plan,
                    "response": {
                        "status": "ok",
                        "kind": "draft_skeleton",
                        "artifact": "docs/skeleton.md",
                        "questions": [
                            {
                                "id": question_id,
                                "answer": "The bounded check is satisfied.",
                            }
                            for question_id in (
                                "due_diligence_count",
                                "machinery_trust",
                                "environment_fit",
                                "human_scale",
                                "guarantee_fit",
                                "cheapest_sufficient",
                                "rare_failure_posture",
                            )
                        ],
                    },
                }]),
            )

            action, _note = subject.step()

            self.assertEqual(action.type, driver.A_DRAFT)
            self.assertNotIn(
                canonical_plan.RECONCILIATION_KEY,
                subject.state["milestone"],
            )
            self.assertIsNotNone(
                subject.state["milestone"][canonical_plan.ANCHOR_KEY]
            )
            self.assertTrue(any(
                event.get("type") == "canonical_plan_established"
                for event in subject.state["events"]
            ))

    def test_rethink_session_freezes_even_when_b_deletes_its_owner(self):
        subject, unit, accepted = self._accepted_session_driver()
        unit["implementation_attempt_snapshot"] = {"tree": "stale"}
        unit["brainstorming_wait"] = {
            "session_id": "rethink-session",
            "signal": {"finding": {"id": "F1"}},
            "origin": {
                "unit": st.unit_key(unit),
                "kind": "implement",
                "family": "codex",
                "plan_source": {
                    "executor": "brainstorming",
                    "job": "rethink",
                    "material": "code",
                    "unit": st.unit_key(unit),
                    "physical_attempt": "repository_session",
                    "session_id": "rethink-session",
                },
            },
        }
        st.save(subject.state_path, subject.state)
        handoff = {
            "session_id": "rethink-session",
            "result": {"outcome": "success"},
            "source_base_revision": self.source_base,
            "accepted_revision": accepted,
        }

        with mock.patch.object(
            brainstorming_milestone,
            "terminal_handoff",
            return_value=handoff,
        ):
            action, _note = subject.step()

        self.assertEqual(action.type, driver.A_RECONCILIATION)
        frozen = next(
            candidate for candidate in subject.state["units"]
            if st.unit_key(candidate) == "slice_impl-02"
        )
        self.assertIn("brainstorming_wait", frozen)
        self.assertIn("implementation_attempt_snapshot", frozen)
        self.assertFalse(any(
            event.get("type") == "brainstorming_rethink_sealed"
            for event in subject.state["events"]
        ))

    def test_producer_session_freezes_before_recording_draft_or_wip(self):
        subject, unit, accepted = self._accepted_session_driver()
        source = {
            "executor": "brainstorming",
            "job": "implement@slice_impl",
            "material": "code",
            "unit": st.unit_key(unit),
            "physical_attempt": "repository_session",
            "task_id": "producer-task",
            "session_id": "producer-session",
        }
        wait = {
            "session_id": "producer-session",
            "origin": {
                "unit": st.unit_key(unit),
                "kind": "implement",
                "task_executor": "brainstorming",
                "task_id": "producer-task",
                "plan_source": copy.deepcopy(source),
            },
        }
        unit["brainstorming_wait"] = copy.deepcopy(wait)
        unit["active_task"] = {
            "id": "producer-task", "kind": "implement"
        }
        st.save(subject.state_path, subject.state)
        active = {
            "id": "producer-task",
            "order": {"request": {"context": {"session_charge": {
                "job": "implement@slice_impl", "material": "code"
            }}}},
        }
        terminal = {
            "id": "producer-task",
            "result": {
                "status": "success",
                "duration_s": 1.0,
                "native_result": {
                    "source_base_revision": self.source_base,
                    "accepted_revision": accepted,
                },
            },
        }

        with (
            mock.patch.object(
                subject, "_active_brainstorming_task", return_value=active
            ),
            mock.patch.object(
                brainstorming_milestone,
                "service_home",
                return_value=self.workspace,
            ),
            mock.patch.object(
                brainstorming_tasks, "finish_task", return_value=terminal
            ),
            self.assertRaises(driver.PlanReconciliationOpened),
        ):
            subject._do_brainstorming_production_wait(unit, wait)

        self.assertIsNone(unit["draft"])
        self.assertIn("brainstorming_wait", unit)
        self.assertIn("active_task", unit)
        self.assertNotIn("pending_wip", unit)


if __name__ == "__main__":
    unittest.main()
