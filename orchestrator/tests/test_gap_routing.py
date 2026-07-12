"""Driver routing of a builder's gap (reform §3, stop-report-repair-resume):
the worker CLASSIFIES (fits_remodel | needs_operator) and the machine routes
— a fits_remodel reopens the SKELETON (the design authority) toward the gap
as an objective; a needs_operator stops for the operator; the back-edge cap
and a fits_remodel with no sealed skeleton both fail cleanly. These drive the
ROUTING; the repair fix/delta/reseal it enters is the existing (separately
tested) machinery.
"""

import os
import tempfile
import unittest

from orchestrator import driver as drv
from orchestrator import profiles
from orchestrator import runners
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    make_config, init_state, step, ok, report, fix_ok, triaged,
    write_file, append_file,
)
from orchestrator.tests.test_state import (
    seal_current_unit, skeleton_draft,
)


def _gap(classification, **over):
    g = {
        "classification": classification,
        "missing_or_conflict": "this step needs a field no earlier step records",
        "where": "docs/slice-01.md:12",
        "forced_decision": "record the field upstream so this step can read it",
        "plain": "the design never produces a field this step must read",
        "example": "the scorer reads a field that is never written; it stalls",
    }
    g.update(over)
    return g


def _gap_output(kind, *gaps):
    return {"status": "gap", "kind": kind, "gaps": list(gaps)}


class GapRoutingCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix="orch-gaproute-")
        self.addCleanup(self.tmpdir.cleanup)
        self.ws = os.path.join(self.tmpdir.name, "ws")
        os.makedirs(self.ws)

    def _reform_config(self, git=True):
        cfg = make_config()
        cfg["profile"] = profiles.SEEDS["strict"]["profile"]  # reform profile
        if not git:
            cfg["git"] = {"enabled": False}
        return cfg

    def _state_to_impl_pending(self, git=True):
        """Skeleton + slice_doc-01 sealed, slice_impl-01 pending — a reform
        run, persisted on disk."""
        path = init_state(self.ws, self._reform_config(git=git))
        state = st.load(path)
        seal_current_unit(state, skeleton_draft(1))
        st.ensure_next_unit(state)     # slice_doc-01
        seal_current_unit(state)       # seal the doc
        st.ensure_next_unit(state)     # slice_impl-01 (pending)
        st.save(path, state)
        return path

    def _drive_one(self, path, script):
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        action, note = driver.step()
        return st.load(path), note

    def test_impl_fits_remodel_reopens_the_skeleton(self):
        path = self._state_to_impl_pending()
        state, note = self._drive_one(
            path, [step("implement", _gap_output("implement",
                                                 _gap("fits_remodel")))])
        units = {st.unit_key(u): u for u in state["units"]}
        skel, impl = units["skeleton"], units["slice_impl-01"]
        # The design authority (skeleton) is reopened with the objective;
        # the slice_doc is NOT touched — the worker never routed to it.
        self.assertEqual(skel["status"], st.U_FIXING)
        self.assertEqual([f["id"] for f in skel["fix_queue"]], ["GAP1"])
        self.assertEqual(skel["fix_queue"][0]["severity"], "P1")
        # The objective pins the missing datum to the REPORTING unit's own
        # scope — never a future/sealed slice (finding 2).
        self.assertIn("REMODEL OBJECTIVE", skel["fix_queue"][0]["summary"])
        self.assertIn("slice_impl-01", skel["fix_queue"][0]["summary"])
        self.assertEqual(units["slice_doc-01"]["status"], st.U_SEALED)
        # The downstream impl finished nothing — it stays pending and its
        # back-edge counter ticked.
        self.assertEqual(impl["status"], st.U_PENDING)
        self.assertIsNone(impl["draft"])
        self.assertEqual(impl["gap_repairs"], 1)
        types = [e["type"] for e in state["events"]]
        self.assertIn("gap_reported", types)
        self.assertIn("reopened_for_repair", types)
        gap_event = [e for e in state["events"]
                     if e["type"] == "gap_reported"][-1]
        self.assertEqual(gap_event["duration_s"], 0.01)
        self.assertEqual(gap_event["gaps"][0]["classification"], "fits_remodel")

    def test_needs_operator_stops_for_the_operator(self):
        # An out-of-goal (or goal-contradiction) gap stops for the operator,
        # from any builder — the goal is operator-authored.
        path = init_state(self.ws, self._reform_config())
        state, note = self._drive_one(
            path, [step("draft_skeleton",
                        _gap_output("draft_skeleton",
                                    _gap("needs_operator")))])
        self.assertIsNotNone(state["failure"])
        self.assertEqual(state["failure"]["type"], "goal_gap")
        self.assertIn("goal_gap_reported",
                      [e["type"] for e in state["events"]])

    def test_needs_operator_outranks_fits_remodel(self):
        # A report carrying both classes escalates: the operator issue wins.
        path = self._state_to_impl_pending()
        state, note = self._drive_one(
            path, [step("implement",
                        _gap_output("implement",
                                    _gap("fits_remodel"),
                                    _gap("needs_operator")))])
        self.assertIsNotNone(state["failure"])
        self.assertEqual(state["failure"]["type"], "goal_gap")

    def test_back_edge_cap_stops_the_run(self):
        path = self._state_to_impl_pending()
        state = st.load(path)
        impl = [u for u in state["units"]
                if st.unit_key(u) == "slice_impl-01"][0]
        impl["gap_repairs"] = 3          # already at the default cap
        st.save(path, state)
        state, note = self._drive_one(
            path, [step("implement", _gap_output("implement",
                                                 _gap("fits_remodel")))])
        self.assertIsNotNone(state["failure"])
        self.assertEqual(state["failure"]["type"], "gap_stall")

    def test_fits_remodel_with_no_sealed_skeleton_fails_cleanly(self):
        # A fits_remodel needs a sealed skeleton to remodel; a skeleton
        # drafter reporting one (its skeleton is not yet sealed) is a routing
        # impossibility, not an operator decision.
        path = init_state(self.ws, self._reform_config())
        state, note = self._drive_one(
            path, [step("draft_skeleton",
                        _gap_output("draft_skeleton",
                                    _gap("fits_remodel")))])
        self.assertIsNotNone(state["failure"])
        self.assertEqual(state["failure"]["type"], "gap_route")

    def test_full_cycle_fits_remodel_reseal_redraft_close(self):
        # End to end (git off — pure state flow; git gates are orthogonal
        # and tested elsewhere): the impl reports a fits_remodel gap, the
        # SKELETON is reopened and remodelled toward the objective, reseals,
        # the impl RE-drafts cleanly, and the milestone closes.
        path = self._state_to_impl_pending(git=False)
        script = (
            # 1. impl draft -> fits_remodel gap (reopens the skeleton)
            [step("implement",
                  _gap_output("implement", _gap("fits_remodel")))]
            # 2. skeleton remodel (git off: fix returns straight to pre-seal,
            #    no delta), then reseal both halves
            + [step("fix_findings",
                    fix_ok([triaged("GAP1", "fixed", "recorded the field",
                                    severity="P1")],
                           files_changed=["docs/skeleton.md"]),
                    family="codex",
                    side_effect=write_file(
                        "docs/skeleton.md",
                        "# Skeleton\n\nSlice 01 records the field.\n")),
               step("seal_half", report("seal_half"), family="codex"),
               step("seal_half", report("seal_half"), family="claude")]
            # 3. impl RE-draft, clean reviews, seal -> close
            + [step("implement", ok("implement", files_changed=["calc.py"]),
                    side_effect=write_file("calc.py", "def add(a,b):\n return a+b\n")),
               step("review_round", report("review_round"), family="codex"),
               step("review_round", report("review_round"), family="claude"),
               step("seal_half", report("seal_half"), family="codex"),
               step("seal_half", report("seal_half"), family="claude")]
        )
        mock = runners.MockRunner(script)
        driver = drv.Driver(path, runner=mock)
        for _ in range(200):
            action, _note = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
        if action.type == drv.A_DONE:
            driver.run()  # closes the milestone when all units sealed
        state = st.load(path)
        self.assertIsNone(state["failure"])
        self.assertEqual(state["milestone"]["status"], st.M_CLOSED)
        units = {st.unit_key(u): u for u in state["units"]}
        self.assertEqual(units["skeleton"]["status"], st.U_SEALED)
        self.assertEqual(units["slice_impl-01"]["status"], st.U_SEALED)
        # The skeleton carries the reopen + remodel, and resealed (2 seal
        # attempts: the original + the remodel reseal).
        self.assertIn("reopened_for_repair",
                      [e["type"] for e in state["events"]])
        self.assertEqual(len(units["skeleton"]["seals"]), 2)
        # The impl drafted successfully on its second attempt.
        self.assertIsNotNone(units["slice_impl-01"]["draft"])
        # The loop actually closes because the RE-draft exposed the remodel:
        # the first implement prompt had no assignment, the retry does — a
        # byte-identical retry would just re-gap forever (r4 finding 2).
        impl_prompts = [p for (_f, kind, p) in mock.calls
                        if kind == "implement"]
        self.assertEqual(len(impl_prompts), 2)
        self.assertNotIn("REMODEL ASSIGNMENT", impl_prompts[0])
        self.assertIn("REMODEL ASSIGNMENT", impl_prompts[1])


if __name__ == "__main__":
    unittest.main()
