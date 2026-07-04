"""End-to-end test: the calculator scenario with REAL subprocesses.

Builds the same config as examples/calculator/run_demo.sh (worker commands
run python3 on examples/calculator/fake_llm.py; verification is
"python3 run_checks.py"), then drives the flow exclusively through the CLI
entrypoints (`python3 -m orchestrator.driver init/run/status --json`) with
cwd at the repo root, exactly like an operator would.

The scenario exercises: a deliberate div bug (forces the fix_verification
path), a mid-flow review finding, and an impl seal attempt 1 failure with a
claude-half finding (forces seal_fix + attempt 2). The run happens once in
setUpClass; each test asserts one aspect of the outcome.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from orchestrator import state as st

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FAKE_LLM = os.path.join(
    REPO, "orchestrator", "examples", "calculator", "fake_llm.py"
)
GOAL = "Build a small CLI calculator (add/sub/mul/div) with unit tests"


class TestCalculatorE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="orch-e2e-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.work = os.path.join(cls.tmp.name, "work")
        os.makedirs(cls.work)

        # Same shape as examples/calculator/run_demo.sh's generated config.
        config = {
            "commands": {
                "codex": ["python3", FAKE_LLM, "--workspace", "{workspace}"],
                "claude": ["python3", FAKE_LLM, "--workspace", "{workspace}"],
            },
            "timeouts": {"codex": 60, "claude": 60},
            "verification": ["python3 run_checks.py"],
            "max_rounds_per_family": 6,
            "max_seal_attempts": 4,
        }
        cfg_path = os.path.join(cls.tmp.name, "demo-config.json")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)

        cls.p_init = cls._cli(
            "init", "--goal", GOAL, "--workspace", cls.work,
            "--config", cfg_path,
        )
        cls.p_run = cls._cli("run", "--workspace", cls.work)
        cls.p_status = cls._cli("status", "--workspace", cls.work, "--json")
        try:
            cls.parsed_summary = json.loads(cls.p_status.stdout)
        except ValueError:
            cls.parsed_summary = None

    @classmethod
    def _cli(cls, *args):
        return subprocess.run(
            [sys.executable, "-m", "orchestrator.driver"] + list(args),
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=300,
        )

    # -- helpers ------------------------------------------------------------

    def summary(self):
        self.assertEqual(
            self.p_status.returncode, 0,
            "status failed: %s" % self.p_status.stderr,
        )
        self.assertIsNotNone(
            self.parsed_summary,
            "status --json did not print valid JSON:\n%s" % self.p_status.stdout,
        )
        return self.parsed_summary

    def unit(self, key):
        for u in self.summary()["units"]:
            if u["unit"] == key:
                return u
        self.fail("unit %s not in status summary" % key)

    def _diag(self, proc):
        return "exit=%d\nstdout:\n%s\nstderr:\n%s" % (
            proc.returncode, proc.stdout, proc.stderr,
        )

    # -- tests --------------------------------------------------------------

    def test_cli_exit_codes_and_output(self):
        self.assertEqual(self.p_init.returncode, 0, self._diag(self.p_init))
        self.assertIn("initialized:", self.p_init.stdout)
        self.assertEqual(self.p_run.returncode, 0, self._diag(self.p_run))
        self.assertIn("milestone closed", self.p_run.stdout)
        self.assertEqual(self.p_status.returncode, 0,
                         self._diag(self.p_status))

    def test_milestone_closed_and_all_units_sealed(self):
        summ = self.summary()
        self.assertEqual(summ["milestone_status"], "closed")
        self.assertIsNone(summ["failure"])
        self.assertIsNone(summ["current_unit"])
        self.assertIsNone(summ["current_unit_status"])
        self.assertEqual(
            [(u["unit"], u["status"]) for u in summ["units"]],
            [
                ("skeleton", "sealed"),
                ("slice_doc-01", "sealed"),
                ("slice_impl-01", "sealed"),
            ],
        )
        self.assertEqual(
            summ["slices"], [{"id": 1, "title": "Calculator core"}]
        )

    def test_div_bug_was_fixed_in_workspace(self):
        calc_path = os.path.join(self.work, "calculator.py")
        self.assertTrue(os.path.exists(calc_path))
        with open(calc_path, "r", encoding="utf-8") as fh:
            calc = fh.read()
        self.assertIn("return a / b", calc)
        self.assertNotIn("BUG: should divide", calc)
        # The codex impl review round also added the module docstring.
        self.assertTrue(calc.startswith('"""Tiny CLI calculator'))
        # The seal_fix wrote the README the claude seal half demanded.
        self.assertTrue(os.path.exists(os.path.join(self.work, "README.md")))

    def test_impl_unit_seal_a1_failed_then_a2_passed(self):
        impl = self.unit("slice_impl-01")
        self.assertEqual(
            [(s["attempt"], s["passed"], s["invalidated"])
             for s in impl["seals"]],
            [(1, False, None), (2, True, None)],
        )
        self.assertEqual(impl["seals"][0]["findings"],
                         {"codex": 0, "claude": 1})
        self.assertEqual(impl["seals"][1]["findings"],
                         {"codex": 0, "claude": 0})

    def test_fix_verification_round_recorded_on_impl_unit(self):
        impl = self.unit("slice_impl-01")
        vfix = [r for r in impl["rounds"] if r["kind"] == "fix_verification"]
        self.assertEqual(len(vfix), 1)
        self.assertEqual(vfix[0]["family"], "codex")
        self.assertEqual(vfix[0]["findings"], 1)
        # It happened before any review round on this unit (the deliberate
        # div bug broke pre-review verification).
        self.assertEqual(impl["rounds"][0]["kind"], "fix_verification")

    def test_raw_worker_outputs_exist(self):
        raw_dir = os.path.join(self.work, ".orchestrator", "raw")
        self.assertTrue(os.path.isdir(raw_dir))
        expected = [
            "skeleton-draft.txt",
            "slice_impl-01-draft.txt",
            "slice_impl-01-vfix1.txt",
            "slice_impl-01-sealfix-a1.txt",
            "slice_impl-01-seal-a1-claude.txt",
            "slice_impl-01-seal-a2-codex.txt",
            "slice_impl-01-seal-a2-claude.txt",
        ]
        present = set(os.listdir(raw_dir))
        for name in expected:
            self.assertIn(name, present)
            path = os.path.join(raw_dir, name)
            self.assertGreater(os.path.getsize(path), 0,
                               "%s is empty" % name)
        # Raw outputs are the workers' verbatim JSON replies.
        with open(os.path.join(raw_dir, "slice_impl-01-seal-a1-claude.txt"),
                  "r", encoding="utf-8") as fh:
            half = json.loads(fh.read())
        self.assertEqual(half["kind"], "seal_half")
        self.assertEqual(len(half["findings"]), 1)

    def test_status_json_matches_summary_shape(self):
        summ = self.summary()
        self.assertEqual(
            set(summ.keys()),
            {
                "goal",
                "workspace",
                "milestone_status",
                "slices",
                "current_unit",
                "current_unit_status",
                "failure",
                "units",
                "events_total",
                "last_events",
            },
        )
        self.assertEqual(summ["goal"], GOAL)
        self.assertEqual(summ["workspace"], self.work)
        self.assertIsInstance(summ["events_total"], int)
        self.assertIsInstance(summ["last_events"], list)
        self.assertLessEqual(len(summ["last_events"]), 30)
        self.assertGreaterEqual(summ["events_total"], len(summ["last_events"]))
        for u in summ["units"]:
            self.assertEqual(
                set(u.keys()),
                {"unit", "status", "artifact", "rounds", "seals"},
            )
        # The CLI's JSON is exactly state.summary() over the on-disk state.
        disk = st.load(
            os.path.join(self.work, ".orchestrator", "state.json")
        )
        self.assertEqual(summ, st.summary(disk))


if __name__ == "__main__":
    unittest.main()
