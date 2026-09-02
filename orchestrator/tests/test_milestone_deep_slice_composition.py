"""Focused prospective milestone deep-slice composition proof."""

import subprocess
import tempfile
from pathlib import Path

from orchestrator import canonical_plan, contracts, driver as drv, gitops
from orchestrator import runners, state as st, tasks
from orchestrator.tests import test_driver_mock as base


class MilestoneDeepSliceCompositionTest(base.DriverTestCase):
    def _fixture(self, workspace, activated=True):
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
        skeleton_path.write_text(
            base.canonical_skeleton_document(), encoding="utf-8"
        )
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
