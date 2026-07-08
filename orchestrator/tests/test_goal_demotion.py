"""Goal demotion after the skeleton seals (reform runs only).

The skeleton consumes the operator's goal verbatim; under a reform
profile every later unit's prompts carry a REFERENCE instead — the
sealed skeleton is the operative restatement (spec §2's chain of
consumption), and the full goal text stays one read away in the
generated milestone record. Legacy and profile-less runs keep the full
goal in every prompt, bit-identically.
"""

import os
import tempfile
import unittest

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import profiles
from orchestrator import runners
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    battery_entries, init_state, make_config, ok, report, step,
)

GOAL_MARKER = "GOAL-MARKER-XYZZY: build the frobnicator per this mandate"


class PromptCapturingRunner(runners.MockRunner):
    """MockRunner that also records every prompt, keyed by KIND."""

    def __init__(self, script):
        super().__init__(script)
        self.prompts = []

    def call(self, family, prompt, workspace, model=None, effort=None):
        self.prompts.append((runners.prompt_kind(prompt), prompt))
        return super().call(
            family, prompt, workspace, model=model, effort=effort
        )


class GoalDemotionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-goaldemo-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "ws")
        os.makedirs(self.ws)

    def _drive(self, cfg, script, stop):
        path = init_state(self.ws, cfg, goal=GOAL_MARKER)
        runner = PromptCapturingRunner(script)
        driver = drv.Driver(path, runner=runner)
        for _ in range(40):
            if stop(st.load(path)):
                break
            action, _n = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
        return st.load(path), runner

    def _prompt(self, runner, kind, last=True):
        hits = [p for k, p in runner.prompts if k == kind]
        self.assertTrue(hits, "no %s prompt captured" % kind)
        return hits[-1] if last else hits[0]

    def test_reform_slice_prompts_reference_the_skeleton(self):
        cfg = make_config(git={"enabled": False},
                          profile=profiles.SEEDS["strict"]["profile"])
        state, runner = self._drive(
            cfg,
            [
                step("draft_skeleton",
                     ok("draft_skeleton", artifact="docs/skeleton.md",
                        slices=[{"id": 1, "title": "Core"}],
                        battery=battery_entries(
                            contracts.BATTERY_QUESTIONS_SKELETON)),
                     family="codex"),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                # strict seals the skeleton by predicate — no seal halves —
                # then the slice-doc drafter runs.
                step("draft_slice_note",
                     ok("draft_slice_note", artifact="docs/slice-01.md",
                        battery=battery_entries(
                            contracts.BATTERY_QUESTIONS_SLICE_NOTE)),
                     family="codex"),
                step("review_round", report("review_round"), family="codex"),
            ],
            stop=lambda s: any(
                u["kind"] == st.UNIT_SLICE_DOC and u["rounds"]
                for u in s["units"]
            ),
        )
        # The skeleton drafter saw the operator's goal verbatim.
        self.assertIn(GOAL_MARKER,
                      self._prompt(runner, "draft_skeleton"))
        # The slice-note drafter and its reviewer saw the reference, not
        # the goal text.
        note_prompt = self._prompt(runner, "draft_slice_note")
        self.assertNotIn(GOAL_MARKER, note_prompt)
        self.assertIn("operative restatement", note_prompt)
        self.assertIn("docs/skeleton.md", note_prompt)
        review_prompts = [p for k, p in runner.prompts
                          if k == "review_round"]
        # first two reviews are the skeleton's (full goal); the last is
        # the slice note's (reference).
        self.assertIn(GOAL_MARKER, review_prompts[0])
        self.assertNotIn(GOAL_MARKER, review_prompts[-1])
        self.assertIn("operative restatement", review_prompts[-1])

    def test_legacy_keeps_the_full_goal_everywhere(self):
        cfg = make_config(git={"enabled": False},
                          profile=profiles.SEEDS["legacy"]["profile"])
        state, runner = self._drive(
            cfg,
            [
                step("draft_skeleton",
                     ok("draft_skeleton", artifact="docs/skeleton.md",
                        slices=[{"id": 1, "title": "Core"}]),
                     family="codex"),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
                step("draft_slice_note",
                     ok("draft_slice_note", artifact="docs/slice-01.md"),
                     family="codex"),
            ],
            stop=lambda s: any(
                u["kind"] == st.UNIT_SLICE_DOC and u.get("draft")
                for u in s["units"]
            ),
        )
        note_prompt = self._prompt(runner, "draft_slice_note")
        self.assertIn(GOAL_MARKER, note_prompt)
        self.assertNotIn("operative restatement", note_prompt)
        # Seal halves carried it too (pre-reform shape, untouched).
        self.assertIn(GOAL_MARKER, self._prompt(runner, "seal_half"))


if __name__ == "__main__":
    unittest.main()
