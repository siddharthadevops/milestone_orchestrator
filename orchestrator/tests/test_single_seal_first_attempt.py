"""Single seal on the first attempt.

When `single_seal_first_attempt` is on, the first seal attempt (a1) runs only
the leading families (families_order[:-1]) — dropping the last reviewer's
redundant re-review of the exact bytes it just blessed. Any finding reopens
the unit and every later attempt runs the full double seal, because the
artifact has by then changed. A single-family config keeps its only sealer.
Parallelization is orthogonal (decided by half count, tested elsewhere): a
lone a1 half runs directly.
"""

import tempfile
import unittest

from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    DriverTestCase,
    append_file,
    finding,
    fix_ok,
    init_state,
    make_config,
    ok,
    report,
    step,
    triaged,
    write_file,
)


def _skeleton_draft():
    # The first unit of any run is the skeleton (also a DOC-phase unit); seal
    # behavior is identical across unit kinds, so we exercise it here.
    return step(
        "draft_skeleton",
        ok("draft_skeleton", artifact="docs/skeleton.md",
           slices=[{"id": 1, "title": "Calculator core"}]),
        family="codex",
        side_effect=write_file(
            "docs/skeleton.md",
            "# Calculator milestone\n\nGoal: CLI calculator with tests.\n",
        ),
    )


class TestSingleSealFirstAttempt(DriverTestCase):
    def test_a1_runs_only_leading_family_and_seals(self):
        # Both families review clean; a1 runs ONLY codex (the last reviewer,
        # claude, is dropped) and the unit seals on that single half.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(single_seal_first_attempt=True))
            mock = runners.MockRunner([
                _skeleton_draft(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])  # claude's a1 half never called
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(len(unit["seals"]), 1)
            self.assertTrue(unit["seals"][0]["passed"])
            self.assertEqual(set(unit["seals"][0]["halves"]), {"codex"})
            # claude was never asked for a seal half.
            self.assertNotIn(
                "claude",
                [fam for fam, kind, _ in mock.calls if kind == "seal_half"])
            # The reduction is recorded for audit.
            ev = [e for e in state["events"]
                  if e["type"] == "seal_single_first_attempt"]
            self.assertEqual(len(ev), 1)
            self.assertEqual(ev[0]["ran"], ["codex"])
            self.assertEqual(ev[0]["skipped"], ["claude"])

    def test_a1_finding_reopens_to_full_double_seal(self):
        # codex's a1 half raises a real P2 -> reopen -> fix -> a2 runs the
        # FULL double seal (artifact changed), which passes.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(single_seal_first_attempt=True))
            mock = runners.MockRunner([
                _skeleton_draft(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                # a1: only codex, and it finds a P2.
                step("seal_half",
                     report("seal_half",
                            [finding("S1", "real gap", severity="P2")]),
                     family="codex"),
                # reopen -> fixer (codex) edits, delta review clean.
                step("fix_findings",
                     fix_ok([triaged("codex-S1", "fixed", "real gap",
                                     severity="P2")],
                            files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\nClarified the gap.\n")),
                step("delta_review", report("delta_review"), family="codex"),
                # a2: full double seal, both clean.
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(len(unit["seals"]), 2)
            # a1 single (codex, failed), a2 full double (both, passed).
            self.assertEqual(set(unit["seals"][0]["halves"]), {"codex"})
            self.assertFalse(unit["seals"][0]["passed"])
            self.assertEqual(set(unit["seals"][1]["halves"]),
                             {"codex", "claude"})
            self.assertTrue(unit["seals"][1]["passed"])
            # Exactly one reduction event (only a1 reduced).
            self.assertEqual(
                len([e for e in state["events"]
                     if e["type"] == "seal_single_first_attempt"]), 1)

    def test_flag_off_runs_full_double_seal_on_a1(self):
        # Default (flag absent): a1 already runs BOTH halves, unchanged.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                _skeleton_draft(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(set(unit["seals"][0]["halves"]),
                             {"codex", "claude"})
            self.assertEqual(
                [e for e in state["events"]
                 if e["type"] == "seal_single_first_attempt"], [])

    def test_single_family_config_keeps_its_only_sealer_on_a1(self):
        # One family: there is nothing to drop, so a1 runs that family and no
        # reduction event is emitted (the len>1 guard holds).
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config(single_seal_first_attempt=True,
                              families_order=["codex"], fix_family="codex")
            path = init_state(ws, cfg)
            mock = runners.MockRunner([
                _skeleton_draft(),
                step("review_round", report("review_round"), family="codex"),
                step("seal_half", report("seal_half"), family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(set(unit["seals"][0]["halves"]), {"codex"})
            self.assertEqual(
                [e for e in state["events"]
                 if e["type"] == "seal_single_first_attempt"], [])

    def test_seal_families_helper(self):
        # a1 drops the last family; a2+ keeps all; off -> always all.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            on = init_state(ws, make_config(single_seal_first_attempt=True))
            d_on = drv.Driver(on, runner=runners.MockRunner([]))
            unit = st.current_unit(d_on.state)
            self.assertEqual(d_on._seal_families(unit, 1), ["codex"])
            self.assertEqual(d_on._seal_families(unit, 2), ["codex", "claude"])
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws2:
            off = init_state(ws2, make_config())
            d_off = drv.Driver(off, runner=runners.MockRunner([]))
            unit = st.current_unit(d_off.state)
            self.assertEqual(d_off._seal_families(unit, 1), ["codex", "claude"])


if __name__ == "__main__":
    unittest.main()
