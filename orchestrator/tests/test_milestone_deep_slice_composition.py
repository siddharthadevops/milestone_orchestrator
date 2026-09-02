"""Focused prospective milestone deep-slice composition proof."""

import copy
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from orchestrator import brainstorming_milestone, brainstorming_tasks
from orchestrator import canonical_plan, contracts
from orchestrator import driver as drv, gitops
from orchestrator import runners, state as st, tasks
from orchestrator.tests import test_driver_mock as base
from orchestrator.tests.test_worker_tasks import _created, _rethink


class MilestoneDeepSliceCompositionTest(base.DriverTestCase):
    def _fixture(
        self, workspace, activated=True, implementation_producer="agent_call"
    ):
        config = base.make_config(verification=[base.VERIFY_CMD])
        path = base.init_state(workspace, config)
        gitops.ensure_repo(workspace)
        state = st.load(path)
        state["milestone"][st.SKELETON_COMPOSITION_KEY] = (
            st.SKELETON_COMPOSITION_VERSION
        )
        state["milestone"][st.DEEP_SLICE_COMPOSITION_KEY] = (
            st.DEEP_SLICE_COMPOSITION_VERSION
        )
        if not activated:
            state["milestone"].pop(st.DEEP_SLICE_COMPOSITION_KEY)
        skeleton_path = Path(workspace, "docs/skeleton.md")
        skeleton_path.parent.mkdir(parents=True, exist_ok=True)
        skeleton_document = base.canonical_skeleton_document().replace(
            '"implement":"agent_call"',
            '"implement":"%s"' % implementation_producer,
        )
        skeleton_path.write_text(skeleton_document, encoding="utf-8")
        subprocess.run(
            ["git", "add", "-A"], cwd=workspace, check=True
        )
        subprocess.run(
            ["git", "commit", "-qm", "reviewed skeleton gate"],
            cwd=workspace,
            check=True,
        )
        revision = gitops.head_full_sha(workspace)
        skeleton = state["units"][0]
        skeleton.update({
            "status": st.U_SEALED,
            "artifact": "docs/skeleton.md",
            "gate_commit": revision[:12],
        })
        st.append_event(
            state, "gate_commit", unit=st.UNIT_SKELETON,
            sha=revision[:12], message="reviewed skeleton gate",
        )
        canonical_plan.establish_current_plan(state, "docs/skeleton.md")
        st.ensure_due_unit(state)
        st.save(path, state)
        return path

    @staticmethod
    def _clean_reviews():
        return [
            base.step(
                contracts.KIND_REVIEW_ROUND,
                base.report(contracts.KIND_REVIEW_ROUND),
                family="codex",
            ),
            base.step(
                contracts.KIND_REVIEW_ROUND,
                base.report(contracts.KIND_REVIEW_ROUND),
                family="claude",
            ),
        ]

    @classmethod
    def _documentation_steps(cls):
        return [
            base.step(
                contracts.KIND_DRAFT_SLICE_NOTE,
                base.ok(
                    contracts.KIND_DRAFT_SLICE_NOTE,
                    artifact="docs/slice-01.md",
                ),
                family="codex",
                side_effect=base.write_file(
                    "docs/slice-01.md", "# Reviewed slice 01\n"
                ),
            ),
            *cls._clean_reviews(),
        ]

    def test_slice_delivery_gates_documentation_and_parts(self):
        with tempfile.TemporaryDirectory(prefix="milestone-deep-") as workspace:
            path = self._fixture(workspace)
            cut = {
                "cut_scope": "Complete part a.",
                "remaining_scope": "Complete part b.",
            }

            def write_document(root):
                state = st.load(path)
                parent, child = tasks.task_records(state)
                self.assertEqual(parent["order"]["task_executor"], "deep_task")
                self.assertEqual(child["parent"], {
                    "task_id": parent["id"],
                    "phase": "documentation",
                    "part": None,
                })
                self.assertIsNone(parent["result"])
                base.write_file(
                    "docs/slice-01.md", "# Reviewed slice 01\n"
                )(root)

            script = [
                base.step(
                    contracts.KIND_DRAFT_SLICE_NOTE,
                    base.ok(
                        contracts.KIND_DRAFT_SLICE_NOTE,
                        artifact="docs/slice-01.md",
                    ),
                    family="codex",
                    side_effect=write_document,
                ),
                *self._clean_reviews(),
                base.step(
                    contracts.KIND_IMPLEMENT,
                    base.ok(
                        contracts.KIND_IMPLEMENT,
                        files_changed=["part_a.py"],
                        implementation_cut=cut,
                    ),
                    family="codex",
                    side_effect=base.write_file("part_a.py", "PART = 'a'\n"),
                ),
                *self._clean_reviews(),
                base.step(
                    contracts.KIND_IMPLEMENT,
                    base.ok(
                        contracts.KIND_IMPLEMENT,
                        files_changed=["part_b.py"],
                    ),
                    family="codex",
                    side_effect=base.write_file("part_b.py", "PART = 'b'\n"),
                ),
                *self._clean_reviews(),
                base.suite_checkpoint_step(base.VERIFY_CMD),
            ]
            runner = runners.MockRunner(script)
            subject = drv.Driver(path, runner=runner)
            _action, note = subject.step()
            status = subprocess.run(
                ["git", "status", "--short"], cwd=workspace, check=True,
                capture_output=True, text=True,
            ).stdout
            self.assertIsNone(
                subject.state.get("failure"), "%s\n%s" % (note, status)
            )
            subject = drv.Driver(path, runner=runner)
            _actions, terminal = self.drive(subject)

            self.assertEqual(
                terminal.type, drv.A_DONE, subject.state.get("failure")
            )
            records = tasks.task_records(subject.state)
            self.assertEqual(len(records), 4)
            parent = records[0]
            documentation = tasks.related_task(
                subject.state, parent["id"], "documentation", None
            )
            parts = [
                tasks.related_task(
                    subject.state, parent["id"], "implementation", part
                )
                for part in ("a", "b")
            ]
            self.assertTrue(all(record["result"] for record in records))
            self.assertEqual(
                parent["result"],
                tasks.deep_task_result(
                    "success", [documentation["result"]]
                    + [part["result"] for part in parts]
                ),
            )
            self.assertIsNone(parent["result"]["native_result"])
            gates = [
                child["result"]["native_result"]["gate_commit"]
                for child in [documentation] + parts
            ]
            self.assertEqual(len(set(gates)), 3)
            self.assertEqual(
                parts[0]["result"]["native_result"]["production_result"]
                ["implementation_cut"],
                cut,
            )
            self.assertEqual(runner.script, [])

    def test_pre_activation_run_keeps_direct_slice_law(self):
        with tempfile.TemporaryDirectory(prefix="milestone-direct-") as workspace:
            path = self._fixture(workspace, activated=False)
            runner = runners.MockRunner([
                base.step(
                    contracts.KIND_DRAFT_SLICE_NOTE,
                    base.ok(
                        contracts.KIND_DRAFT_SLICE_NOTE,
                        artifact="docs/slice-01.md",
                    ),
                    family="codex",
                    side_effect=base.write_file(
                        "docs/slice-01.md", "# Direct slice 01\n"
                    ),
                )
            ])
            subject = drv.Driver(path, runner=runner)
            subject.step()

            self.assertNotIn(
                st.DEEP_SLICE_COMPOSITION_KEY, subject.state["milestone"]
            )
            self.assertEqual(tasks.task_records(subject.state), [])
            self.assertNotIn(
                "reviewed_task_id", st.current_unit(subject.state)
            )

    def test_brainstorming_production_counts_in_child_and_parent(self):
        with tempfile.TemporaryDirectory(
            prefix="milestone-brainstorm-"
        ) as workspace:
            path = self._fixture(
                workspace, implementation_producer="brainstorming"
            )
            usage = {
                "input_tokens": 80,
                "cached_input_tokens": 20,
                "output_tokens": 30,
                "reasoning_output_tokens": 10,
                "total_tokens": 110,
            }
            cost = {"api_usd": 1.25, "real_usd": 0.75}
            session_id = "milestone-brainstorming-implementation"

            def finish(state, task_id, *_args, **_kwargs):
                record = tasks.task_record(state, task_id)
                source = record["order"]["request"]["context"][
                    "session_charge"
                ]["repository"]["pre_session_commit"]
                base.write_file(
                    "brainstorming.py", "DELIVERED = True\n"
                )(workspace)
                subprocess.run(
                    ["git", "add", "brainstorming.py"],
                    cwd=workspace,
                    check=True,
                )
                subprocess.run(
                    ["git", "commit", "-qm", "Brainstorming delivery"],
                    cwd=workspace,
                    check=True,
                )
                return tasks.record_task_result(state, task_id, {
                    "status": "success",
                    "duration_s": 2.0,
                    "token_usage": usage,
                    "token_usage_partial": False,
                    "cost": cost,
                    "cost_partial": False,
                    "native_result": {
                        "outcome": "success",
                        "rounds_used": 1,
                        "source_base_revision": source,
                        "accepted_revision": gitops.head_full_sha(workspace),
                    },
                })

            runner = runners.MockRunner([
                base.step(
                    contracts.KIND_DRAFT_SLICE_NOTE,
                    base.ok(
                        contracts.KIND_DRAFT_SLICE_NOTE,
                        artifact="docs/slice-01.md",
                    ),
                    family="codex",
                    side_effect=base.write_file(
                        "docs/slice-01.md", "# Reviewed slice 01\n"
                    ),
                ),
                *self._clean_reviews(),
                *self._clean_reviews(),
                base.suite_checkpoint_step(base.VERIFY_CMD),
            ])
            subject = drv.Driver(path, runner=runner)
            with mock.patch.object(
                brainstorming_tasks,
                "resolve_staffing",
                return_value={
                    "dispatch_authority": "static", "participants": []
                },
            ), mock.patch.object(
                brainstorming_tasks,
                "start_task",
                return_value={"id": session_id},
            ), mock.patch.object(
                brainstorming_tasks, "finish_task", side_effect=finish
            ):
                _actions, terminal = self.drive(subject)

            self.assertEqual(terminal.type, drv.A_DONE)
            parent = next(
                record for record in tasks.task_records(subject.state)
                if record["order"]["task_executor"] == "deep_task"
            )
            implementation = tasks.related_task(
                subject.state, parent["id"], "implementation", "a"
            )
            self.assertAlmostEqual(
                implementation["result"]["duration_s"], 2.02
            )
            self.assertEqual(implementation["result"]["token_usage"], usage)
            self.assertEqual(implementation["result"]["cost"], cost)
            children = [
                record["result"] for record in tasks.task_records(subject.state)
                if (record.get("parent") or {}).get("task_id") == parent["id"]
            ]
            self.assertEqual(
                parent["result"], tasks.deep_task_result("success", children)
            )
            self.assertEqual(parent["result"]["token_usage"], usage)
            self.assertEqual(parent["result"]["cost"], cost)
            run = st.summary(subject.state)
            self.assertEqual(run["work_token_usage"], usage)
            self.assertEqual(run["work_cost"], cost)
            self.assertEqual(runner.script, [])

    def test_surviving_rethink_resumes_same_child_and_phase_without_redocumentation(self):
        scenarios = (
            ("production", st.U_PENDING, contracts.KIND_IMPLEMENT),
            ("review", st.U_ROUNDS, contracts.KIND_REVIEW_ROUND),
            ("fix", st.U_FIXING, contracts.KIND_FIX_FINDINGS),
        )
        for label, expected_status, phase_kind in scenarios:
            with self.subTest(phase=label), tempfile.TemporaryDirectory(
                prefix="milestone-rethink-%s-" % label
            ) as workspace:
                path = self._fixture(workspace)
                script = self._documentation_steps()
                if label == "production":
                    script.extend([
                        base.step(
                            contracts.KIND_IMPLEMENT,
                            _rethink(contracts.KIND_IMPLEMENT),
                            family="codex",
                        ),
                        base.step(
                            contracts.KIND_IMPLEMENT,
                            base.ok(
                                contracts.KIND_IMPLEMENT,
                                files_changed=["implementation.py"],
                            ),
                            family="codex",
                            side_effect=base.write_file(
                                "implementation.py", "VALUE = 1\n"
                            ),
                        ),
                    ])
                elif label == "review":
                    script.extend([
                        base.step(
                            contracts.KIND_IMPLEMENT,
                            base.ok(
                                contracts.KIND_IMPLEMENT,
                                files_changed=["implementation.py"],
                            ),
                            family="codex",
                            side_effect=base.write_file(
                                "implementation.py", "VALUE = 1\n"
                            ),
                        ),
                        base.step(
                            contracts.KIND_REVIEW_ROUND,
                            _rethink(contracts.KIND_REVIEW_ROUND),
                            family="codex",
                        ),
                        base.step(
                            contracts.KIND_REVIEW_ROUND,
                            base.report(contracts.KIND_REVIEW_ROUND),
                            family="codex",
                        ),
                    ])
                else:
                    finding = base.finding(
                        "F1", "The implementation needs one correction.",
                        severity="P0",
                    )
                    script.extend([
                        base.step(
                            contracts.KIND_IMPLEMENT,
                            base.ok(
                                contracts.KIND_IMPLEMENT,
                                files_changed=["implementation.py"],
                            ),
                            family="codex",
                            side_effect=base.write_file(
                                "implementation.py", "VALUE = 1\n"
                            ),
                        ),
                        base.step(
                            contracts.KIND_REVIEW_ROUND,
                            base.report(
                                contracts.KIND_REVIEW_ROUND, [finding]
                            ),
                            family="codex",
                        ),
                        base.step(
                            contracts.KIND_FIX_FINDINGS,
                            _rethink(contracts.KIND_FIX_FINDINGS),
                            family="codex",
                        ),
                        base.step(
                            contracts.KIND_FIX_FINDINGS,
                            base.fix_ok([
                                base.triaged(
                                    "F1", "fixed",
                                    "The implementation needs one correction.",
                                    severity="P0",
                                )
                            ], files_changed=["implementation.py"]),
                            family="codex",
                            side_effect=base.append_file(
                                "implementation.py", "FIXED = True\n"
                            ),
                        ),
                    ])
                runner = runners.MockRunner(script)
                subject = drv.Driver(path, runner=runner)
                session_id = "surviving-%s" % label
                with mock.patch.object(
                    brainstorming_milestone,
                    "create_session",
                    side_effect=lambda *_args, **_kwargs: _created(
                        session_id, path, workspace
                    ),
                ):
                    self.step_until(
                        subject,
                        lambda state: any(
                            unit.get("brainstorming_wait")
                            for unit in state["units"]
                        ),
                    )

                unit = st.current_unit(subject.state)
                self.assertEqual(unit["status"], expected_status)
                parent = self._open_parent(subject.state)
                child = tasks.related_task(
                    subject.state, parent["id"], "implementation", "a"
                )
                documentation = tasks.related_task(
                    subject.state, parent["id"], "documentation", None
                )
                frozen_parent_order = copy.deepcopy(parent["order"])
                frozen_child_order = copy.deepcopy(child["order"])
                revision = gitops.head_full_sha(workspace)
                with mock.patch.object(
                    brainstorming_milestone,
                    "terminal_handoff",
                    return_value={
                        "session_id": session_id,
                        "result": {"outcome": "success"},
                        "source_base_revision": revision,
                        "accepted_revision": revision,
                    },
                ):
                    subject.step()

                continued = st.current_unit(subject.state)
                self.assertEqual(continued["status"], expected_status)
                self.assertEqual(continued["reviewed_task_id"], child["id"])
                self.assertNotIn("brainstorming_wait", continued)
                subject.step()

                same_parent = tasks.task_record(subject.state, parent["id"])
                same_child = tasks.task_record(subject.state, child["id"])
                self.assertEqual(same_parent["order"], frozen_parent_order)
                self.assertEqual(same_child["order"], frozen_child_order)
                self.assertIsNone(same_parent["result"])
                self.assertIsNone(same_child["result"])
                self.assertEqual(
                    tasks.related_task(
                        subject.state, parent["id"], "documentation", None
                    )["id"],
                    documentation["id"],
                )
                self.assertEqual(
                    sum(
                        kind == contracts.KIND_DRAFT_SLICE_NOTE
                        for _family, kind, _prompt in runner.calls
                    ),
                    1,
                )
                self.assertEqual(runner.calls[-1][1], phase_kind)
                self.assertEqual(runner.script, [])

    @staticmethod
    def _open_parent(state):
        return next(
            record for record in tasks.task_records(state)
            if record["order"]["task_executor"] == "deep_task"
            and record["result"] is None
        )

    def test_rethink_continuation_preserves_order_and_counts_physical_calls_once(self):
        with tempfile.TemporaryDirectory(
            prefix="milestone-rethink-accounting-"
        ) as workspace:
            path = self._fixture(workspace)
            runner = runners.MockRunner([
                *self._documentation_steps(),
                base.step(
                    contracts.KIND_IMPLEMENT,
                    _rethink(contracts.KIND_IMPLEMENT),
                    family="codex",
                ),
                base.step(
                    contracts.KIND_IMPLEMENT,
                    base.ok(
                        contracts.KIND_IMPLEMENT,
                        files_changed=["implementation.py"],
                    ),
                    family="codex",
                    side_effect=base.write_file(
                        "implementation.py", "VALUE = 1\n"
                    ),
                ),
                *self._clean_reviews(),
                base.suite_checkpoint_step(base.VERIFY_CMD),
            ])
            subject = drv.Driver(path, runner=runner)
            session_id = "accounted-survivor"
            with mock.patch.object(
                brainstorming_milestone,
                "create_session",
                side_effect=lambda *_args, **_kwargs: _created(
                    session_id, path, workspace
                ),
            ):
                self.step_until(
                    subject,
                    lambda state: any(
                        unit.get("brainstorming_wait")
                        for unit in state["units"]
                    ),
                )
            parent = self._open_parent(subject.state)
            implementation = tasks.related_task(
                subject.state, parent["id"], "implementation", "a"
            )
            frozen_order = copy.deepcopy(implementation["order"])
            source_base = gitops.head_full_sha(workspace)
            Path(workspace, "accepted.txt").write_text(
                "accepted rethink authority\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", "accepted.txt"], cwd=workspace, check=True
            )
            subprocess.run(
                ["git", "commit", "-qm", "accepted rethink state"],
                cwd=workspace,
                check=True,
            )
            accepted = gitops.head_full_sha(workspace)
            with mock.patch.object(
                brainstorming_milestone,
                "terminal_handoff",
                return_value={
                    "session_id": session_id,
                    "result": {"outcome": "success"},
                    "source_base_revision": source_base,
                    "accepted_revision": accepted,
                    "work_duration_s": 2.0,
                    "work_token_usage": None,
                    "work_token_usage_partial": True,
                    "work_cost": None,
                    "work_cost_partial": True,
                },
            ):
                subject.step()
            _actions, terminal = self.drive(subject)

            self.assertEqual(terminal.type, drv.A_DONE)
            parent = tasks.task_record(subject.state, parent["id"])
            implementation = tasks.task_record(
                subject.state, implementation["id"]
            )
            documentation = tasks.related_task(
                subject.state, parent["id"], "documentation", None
            )
            self.assertEqual(implementation["order"], frozen_order)
            self.assertAlmostEqual(
                implementation["result"]["duration_s"], 2.04
            )
            self.assertAlmostEqual(
                parent["result"]["duration_s"],
                documentation["result"]["duration_s"]
                + implementation["result"]["duration_s"],
            )
            work = [
                event for event in subject.state["events"]
                if event.get("type") == "brainstorming_work_recorded"
            ]
            self.assertEqual(len(work), 1)
            self.assertEqual(work[0]["task_id"], implementation["id"])
            self.assertAlmostEqual(st.summary(subject.state)["work_duration_s"], 2.08)
            self.assertEqual(
                sum(
                    kind == contracts.KIND_IMPLEMENT
                    for _family, kind, _prompt in runner.calls
                ),
                2,
            )
            self.assertEqual(len(runner.calls), 8)
            self.assertTrue(Path(workspace, "accepted.txt").is_file())
            self.assertEqual(runner.script, [])

    def test_rollback_supersession_fails_open_tree_and_starts_new_documentation_first_deep_task(self):
        with tempfile.TemporaryDirectory(
            prefix="milestone-rethink-rollback-"
        ) as workspace:
            path = self._fixture(workspace)
            cut = {
                "cut_scope": "Complete part a.",
                "remaining_scope": "Complete part b.",
            }
            repair = {}

            def repair_from_boundary(root):
                subprocess.run(
                    ["git", "reset", "--hard", repair["wipe_boundary"]],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )
                Path(root, "docs/skeleton.md").write_text(
                    repair["accepted_document"], encoding="utf-8"
                )
                Path(root, "repair.txt").write_text(
                    "reconciled ancestry\n", encoding="utf-8"
                )
                subprocess.run(["git", "add", "-A"], cwd=root, check=True)
                subprocess.run(
                    ["git", "commit", "-qm", "reconciled slice ancestry"],
                    cwd=root,
                    check=True,
                )

            runner = runners.MockRunner([
                *self._documentation_steps(),
                base.step(
                    contracts.KIND_IMPLEMENT,
                    base.ok(
                        contracts.KIND_IMPLEMENT,
                        files_changed=["part_a.py"],
                        implementation_cut=cut,
                    ),
                    family="codex",
                    side_effect=base.write_file("part_a.py", "PART = 'a'\n"),
                ),
                *self._clean_reviews(),
                base.step(
                    contracts.KIND_IMPLEMENT,
                    _rethink(contracts.KIND_IMPLEMENT),
                    family="codex",
                ),
                base.step(
                    contracts.KIND_MERGE_REPAIR,
                    base.ok(
                        contracts.KIND_MERGE_REPAIR,
                        files_changed=["docs/skeleton.md", "repair.txt"],
                    ),
                    side_effect=repair_from_boundary,
                ),
                base.step(
                    contracts.KIND_DRAFT_SLICE_NOTE,
                    base.ok(
                        contracts.KIND_DRAFT_SLICE_NOTE,
                        artifact="docs/slice-02.md",
                    ),
                    family="codex",
                    side_effect=base.write_file(
                        "docs/slice-02.md", "# Reconciled slice 02\n"
                    ),
                ),
            ])
            subject = drv.Driver(path, runner=runner)
            session_id = "rollback-origin"
            with mock.patch.object(
                brainstorming_milestone,
                "create_session",
                side_effect=lambda *_args, **_kwargs: _created(
                    session_id, path, workspace
                ),
            ):
                self.step_until(
                    subject,
                    lambda state: any(
                        unit.get("brainstorming_wait")
                        for unit in state["units"]
                    ),
                )

            old_parent = self._open_parent(subject.state)
            old_documentation = tasks.related_task(
                subject.state, old_parent["id"], "documentation", None
            )
            old_part_a = tasks.related_task(
                subject.state, old_parent["id"], "implementation", "a"
            )
            old_part_b = tasks.related_task(
                subject.state, old_parent["id"], "implementation", "b"
            )
            source_base = gitops.head_full_sha(workspace)
            skeleton_path = Path(workspace, "docs/skeleton.md")
            accepted_intent = "Establish the reconciled prerequisite."
            accepted_document = (
                "# Calculator milestone\n\n"
                "Goal: CLI calculator with tests.\n\n"
                "## Canonical slice plan\n```json\n%s\n```\n"
                % json.dumps({"slices": [
                    {
                        "id": 2,
                        "title": "Reconciled prerequisite",
                        "intent": accepted_intent,
                        "producer_task_executor": {
                            "draft_slice_note": "agent_call",
                            "implement": "agent_call",
                        },
                    },
                    {
                        "id": 1,
                        "title": "Calculator core",
                        "intent": (
                            "Build the bounded calculator CLI and its tests."
                        ),
                        "producer_task_executor": {
                            "draft_slice_note": "agent_call",
                            "implement": "agent_call",
                        },
                    },
                ]}, separators=(",", ":"))
            )
            skeleton_path.write_text(accepted_document, encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "accepted reconciled design"],
                cwd=workspace,
                check=True,
            )
            accepted = gitops.head_full_sha(workspace)
            canonical_plan.establish_current_plan(
                subject.state, "docs/skeleton.md"
            )
            subject._save()
            with mock.patch.object(
                brainstorming_milestone,
                "terminal_handoff",
                return_value={
                    "session_id": session_id,
                    "result": {"outcome": "success"},
                    "source_base_revision": source_base,
                    "accepted_revision": accepted,
                },
            ):
                action, _note = subject.step()
            self.assertEqual(action.type, drv.A_RECONCILIATION)
            record = subject.state["milestone"][
                canonical_plan.RECONCILIATION_KEY
            ]
            repair.update({
                "wipe_boundary": record["wipe_boundary"],
                "accepted_document": accepted_document,
            })

            with mock.patch.object(
                subject, "_staff", return_value=("codex", None, None)
            ), mock.patch.object(
                subject,
                "_dispatch_for_role",
                return_value=lambda: ("codex", None, None),
            ):
                action, _note = subject.step()
            self.assertEqual(action.type, drv.A_RECONCILIATION)
            old_results = {
                record["id"]: copy.deepcopy(record["result"])
                for record in tasks.task_records(subject.state)
            }
            self.assertEqual(
                old_results[old_parent["id"]]["status"], "failure"
            )
            self.assertEqual(
                old_results[old_part_b["id"]]["status"], "failure"
            )
            self.assertIn(
                "superseded", old_results[old_part_b["id"]]["reason"]
            )
            self.assertEqual(
                old_results[old_documentation["id"]]["status"], "success"
            )
            self.assertEqual(old_results[old_part_a["id"]]["status"], "success")
            current = st.current_unit(subject.state)
            self.assertEqual(st.unit_key(current), "slice_doc-02")
            self.assertEqual(current["status"], st.U_PENDING)
            self.assertNotIn("reviewed_task_id", current)

            subject.step()
            records = tasks.task_records(subject.state)
            new_parent = next(
                record for record in reversed(records)
                if record["order"]["task_executor"] == "deep_task"
            )
            self.assertNotEqual(new_parent["id"], old_parent["id"])
            self.assertEqual(
                new_parent["order"]["request"]["request"], accepted_intent
            )
            new_documentation = tasks.related_task(
                subject.state, new_parent["id"], "documentation", None
            )
            self.assertIsNotNone(new_documentation)
            self.assertIsNone(tasks.related_task(
                subject.state, new_parent["id"], "implementation", "a"
            ))
            for task_id, result in old_results.items():
                self.assertEqual(
                    tasks.task_record(subject.state, task_id)["result"], result
                )
            self.assertEqual(runner.script, [])

    def test_rollback_discards_superseded_cut_authority_before_new_deep_parts(self):
        with tempfile.TemporaryDirectory(
            prefix="milestone-rethink-cut-authority-"
        ) as workspace:
            path = self._fixture(workspace)
            subject = drv.Driver(path, runner=runners.MockRunner([]))
            documentation = st.current_unit(subject.state)
            documentation["status"] = st.U_SEALED
            implementation = st.ensure_next_unit(subject.state)
            old_cut = st.record_implementation_cut(
                subject.state,
                implementation,
                "Complete obsolete part a.",
                "Complete obsolete part b.",
            )
            self.assertIn(
                (st.UNIT_SLICE_IMPL, 1, "b"),
                st.planned_execution_units(subject.state),
            )

            subject._requeue_reconciled_deep_slices(
                {
                    "wipe_boundary": "rollback-base",
                    "requeue_slice_ids": [1],
                },
                "accepted-rethink",
            )

            self.assertNotIn("implementation_cut", implementation)
            self.assertEqual(
                implementation["superseded_implementation_cuts"],
                [{
                    "cut": old_cut,
                    "accepted_revision": "accepted-rethink",
                }],
            )
            self.assertNotIn(
                (st.UNIT_SLICE_IMPL, 1, "b"),
                st.planned_execution_units(subject.state),
            )

            new_cut = st.record_implementation_cut(
                subject.state,
                implementation,
                "Complete reconciled part a.",
                "Complete reconciled part b with new scope.",
            )
            self.assertNotEqual(new_cut, old_cut)
            self.assertEqual(
                st.implementation_scope(subject.state, implementation),
                {
                    "part": "a",
                    "scope": "Complete reconciled part a.",
                    "delegated_remaining": (
                        "Complete reconciled part b with new scope."
                    ),
                    "source_unit": "slice_impl-01",
                },
            )
            self.assertIn(
                (st.UNIT_SLICE_IMPL, 1, "b"),
                st.planned_execution_units(subject.state),
            )
