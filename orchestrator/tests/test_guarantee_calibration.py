"""Driver-level contract tests for the initial guarantee calibration."""

import copy
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming_milestone as adapter
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st
from orchestrator.tests.test_driver_mock import init_state, step, write_file


SKELETON = """# Milestone

## Guarantees

- Delivery is best effort.
"""

CALIBRATED_SKELETON = """# Milestone

## Guarantees

- Delivery is best effort during normal operation.
"""


class GuaranteeCalibrationDriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            prefix="guarantee-calibration-driver-"
        )
        self.addCleanup(self.tmp.cleanup)

    @staticmethod
    def _git(workspace, *args):
        result = subprocess.run(
            ["git", *args],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return result.stdout.strip()

    @staticmethod
    def _config():
        config = drv.load_config(None)
        config.update(
            {
                "docs_dir": "docs",
                "git": {"enabled": True},
                "verification": [],
                "verification_timeout": 60,
                "error_classifier": False,
                "infra_retry_backoff_s": [],
            }
        )
        return config

    def _start(self, config=None):
        workspace = os.path.join(self.tmp.name, "workspace")
        os.makedirs(workspace)
        config = config or self._config()
        state_path = init_state(workspace, config, goal="Ship one feature")
        runner = runners.MockRunner(
            [
                step(
                    contracts.KIND_DRAFT_SKELETON,
                    {
                        "status": "ok",
                        "kind": contracts.KIND_DRAFT_SKELETON,
                        "artifact": "docs/skeleton.md",
                        "slices": [{"id": 1, "title": "First slice"}],
                    },
                    family="claude",
                    side_effect=write_file("docs/skeleton.md", SKELETON),
                )
            ]
        )
        driver = drv.Driver(state_path, runner=runner)
        base_head = self._git(workspace, "rev-parse", "HEAD")
        captured = {}

        def create(
            state,
            effective_config,
            unit_key,
            skeleton_path,
            lead_profile,
            counterpart_profile,
            **kwargs,
        ):
            captured.update(
                {
                    "state": state,
                    "config": effective_config,
                    "unit_key": unit_key,
                    "skeleton_path": skeleton_path,
                    "lead": copy.deepcopy(lead_profile),
                    "counterpart": copy.deepcopy(counterpart_profile),
                    "kwargs": copy.deepcopy(kwargs),
                }
            )
            return {"id": "calibration-1"}

        with mock.patch.object(
            adapter,
            "create_guarantee_calibration_session",
            side_effect=create,
        ):
            action, note = driver.step()
        return workspace, state_path, runner, base_head, captured, action, note

    @staticmethod
    def _success_handoff(content):
        handoff = {
            "session_id": "calibration-1",
            "accepted_target_revision": "revision-2",
            "result": {"outcome": "success"},
        }
        expanded = copy.deepcopy(handoff)
        expanded["retained_target"] = {
            "exists": True,
            "encoding": "utf-8",
            "content": content,
        }
        return handoff, expanded

    def _complete_success(self, state_path, runner, content):
        handoff, expanded = self._success_handoff(content)
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=handoff
        ), mock.patch.object(
            adapter, "prompt_handoff", return_value=expanded
        ):
            driver = drv.Driver(state_path, runner=runner)
            action, note = driver.step()
        return driver, action, note

    def test_new_run_pauses_after_draft_and_pins_both_participants(self):
        (
            workspace,
            state_path,
            runner,
            base_head,
            captured,
            action,
            _note,
        ) = self._start()

        state = st.load(state_path)
        unit = st.current_unit(state)
        self.assertEqual(action.type, drv.A_DRAFT)
        self.assertEqual(drv.decide(state).type, drv.A_BRAINSTORM_WAIT)
        self.assertEqual(unit["status"], st.U_PENDING)
        self.assertIsNotNone(unit["draft"])
        self.assertEqual(unit["guarantee_calibration"]["status"], "running")
        self.assertNotIn("wip_commit", [e["type"] for e in state["events"]])
        self.assertEqual(self._git(workspace, "rev-parse", "HEAD"), base_head)
        self.assertTrue(
            self._git(
                workspace, "status", "--porcelain", "--", "docs/skeleton.md"
            )
        )
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(
            runner.call_meta[0],
            {
                "family": "claude",
                "kind": contracts.KIND_DRAFT_SKELETON,
                "model": "claude-opus-5",
                "effort": "max",
            },
        )
        self.assertEqual(captured["unit_key"], "skeleton")
        self.assertEqual(captured["skeleton_path"], "docs/skeleton.md")
        self.assertEqual(
            captured["lead"],
            {
                "agent": "codex",
                "model": "gpt-5.6-sol",
                "effort": "max",
            },
        )
        self.assertEqual(
            captured["counterpart"],
            {
                "agent": "claude",
                "model": "claude-opus-5",
                "effort": "max",
            },
        )
        self.assertEqual(captured["kwargs"]["max_rounds"], 5)

    def test_explicit_round_override_is_preserved(self):
        config = self._config()
        config["guarantee_calibration"] = {
            "enabled": True,
            "max_rounds": 7,
        }

        *_prefix, captured, _action, _note = self._start(config=config)

        self.assertEqual(captured["kwargs"]["max_rounds"], 7)

    def test_success_without_changes_commits_and_opens_normal_flow(self):
        workspace, state_path, runner, base_head, *_rest = self._start()
        driver, action, _note = self._complete_success(
            state_path, runner, SKELETON
        )

        state = st.load(state_path)
        unit = st.current_unit(state)
        self.assertEqual(action.type, drv.A_BRAINSTORM_WAIT)
        self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(unit["guarantee_calibration"]["status"], "complete")
        self.assertFalse(unit["guarantee_calibration"]["changed"])
        self.assertNotIn("brainstorming_wait", unit)
        self.assertEqual(drv.decide(state).type, drv.A_VERIFY)
        self.assertNotEqual(self._git(workspace, "rev-parse", "HEAD"), base_head)
        self.assertEqual(
            self._git(workspace, "show", "HEAD:docs/skeleton.md"),
            SKELETON.strip(),
        )
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(
            len([e for e in state["events"] if e["type"] == "wip_commit"]),
            1,
        )
        self.assertEqual(driver.state["failure"], None)

    def test_success_with_changes_adopts_target_then_opens_normal_flow(self):
        workspace, state_path, runner, _base_head, *_rest = self._start()
        _driver, action, _note = self._complete_success(
            state_path, runner, CALIBRATED_SKELETON
        )

        state = st.load(state_path)
        unit = st.current_unit(state)
        with open(
            os.path.join(workspace, "docs", "skeleton.md"),
            "r",
            encoding="utf-8",
        ) as handle:
            self.assertEqual(handle.read(), CALIBRATED_SKELETON)
        self.assertEqual(action.type, drv.A_BRAINSTORM_WAIT)
        self.assertTrue(unit["guarantee_calibration"]["changed"])
        self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(drv.decide(state).type, drv.A_VERIFY)
        self.assertEqual(
            self._git(workspace, "show", "HEAD:docs/skeleton.md"),
            CALIBRATED_SKELETON.strip(),
        )
        self.assertEqual(len(runner.calls), 1)

    def test_failed_discussion_stops_without_committing_or_continuing(self):
        workspace, state_path, runner, base_head, *_rest = self._start()
        handoff = {
            "session_id": "calibration-1",
            "accepted_target_revision": None,
            "result": {"outcome": "failure"},
        }
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=handoff
        ), mock.patch.object(
            adapter,
            "prompt_handoff",
            side_effect=AssertionError("failure must not be adopted"),
        ):
            driver = drv.Driver(state_path, runner=runner)
            action, _note = driver.step()

        state = st.load(state_path)
        unit = st.current_unit(state)
        self.assertEqual(action.type, drv.A_BRAINSTORM_WAIT)
        self.assertEqual(drv.decide(state).type, drv.A_FAILED)
        self.assertEqual(unit["status"], st.U_FAILED)
        self.assertEqual(unit["guarantee_calibration"]["status"], "failed")
        self.assertNotIn("brainstorming_wait", unit)
        self.assertEqual(self._git(workspace, "rev-parse", "HEAD"), base_head)
        self.assertNotIn("wip_commit", [e["type"] for e in state["events"]])
        self.assertEqual(len(runner.calls), 1)

    def test_historical_config_without_key_does_not_insert_the_stage(self):
        config = self._config()
        config.pop("guarantee_calibration")
        workspace = os.path.join(self.tmp.name, "workspace")
        os.makedirs(workspace)
        state_path = init_state(workspace, config, goal="Ship one feature")
        runner = runners.MockRunner(
            [
                step(
                    contracts.KIND_DRAFT_SKELETON,
                    {
                        "status": "ok",
                        "kind": contracts.KIND_DRAFT_SKELETON,
                        "artifact": "docs/skeleton.md",
                        "slices": [{"id": 1, "title": "First slice"}],
                    },
                    family="claude",
                    side_effect=write_file("docs/skeleton.md", SKELETON),
                )
            ]
        )

        with mock.patch.object(
            adapter,
            "create_guarantee_calibration_session",
            side_effect=AssertionError("historical run inserted calibration"),
        ):
            driver = drv.Driver(state_path, runner=runner)
            base_head = self._git(workspace, "rev-parse", "HEAD")
            action, _note = driver.step()

        state = st.load(state_path)
        unit = st.current_unit(state)
        self.assertEqual(action.type, drv.A_DRAFT)
        self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertNotIn("guarantee_calibration", unit)
        self.assertNotIn("brainstorming_wait", unit)
        self.assertEqual(drv.decide(state).type, drv.A_VERIFY)
        self.assertNotEqual(self._git(workspace, "rev-parse", "HEAD"), base_head)
        self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
