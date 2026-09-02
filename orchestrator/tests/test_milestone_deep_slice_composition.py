"""Focused prospective milestone deep-slice composition proof."""

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from orchestrator import brainstorming_tasks, canonical_plan, contracts
from orchestrator import driver as drv, gitops
from orchestrator import runners, state as st, tasks
from orchestrator.tests import test_driver_mock as base


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
