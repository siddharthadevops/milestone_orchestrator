"""Driver routing of a builder's gap (reform §3, stop-report-repair-resume):
a slice_impl gap reopens its upstream doc for repair; a goal gap stops for
the operator; the back-edge cap and an illegal target both fail cleanly.
These drive the ROUTING; the repair fix/delta/reseal it enters is the
existing (separately tested) machinery.
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


def _gap(target, **over):
    g = {
        "target": target,
        "missing_or_conflict": "the note pins a route the skeleton forbids",
        "where": "docs/slice-01.md:12",
        "forced_decision": "use /v2/x, or relax the skeleton boundary",
        "plain": "the note tells me to call a route the plan bans",
        "example": "calling /v1/x returns 410 at runtime",
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

    def test_impl_gap_reopens_the_upstream_doc(self):
        path = self._state_to_impl_pending()
        state, note = self._drive_one(
            path, [step("implement", _gap_output("implement",
                                                 _gap("slice_doc-01")))])
        units = {st.unit_key(u): u for u in state["units"]}
        doc, impl = units["slice_doc-01"], units["slice_impl-01"]
        # The upstream doc is reopened and its repair is queued as a fix.
        self.assertEqual(doc["status"], st.U_FIXING)
        self.assertEqual([f["id"] for f in doc["fix_queue"]], ["GAP1"])
        self.assertEqual(doc["fix_queue"][0]["severity"], "P1")
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
        impl_view = {u["unit"]: u for u in st.summary(state)["units"]}[
            "slice_impl-01"
        ]
        self.assertEqual(impl_view["work_duration_s"], 0.01)

    def test_impl_gap_targeting_the_skeleton_reopens_the_skeleton(self):
        path = self._state_to_impl_pending()
        state, note = self._drive_one(
            path, [step("implement", _gap_output("implement",
                                                 _gap("skeleton")))])
        units = {st.unit_key(u): u for u in state["units"]}
        self.assertEqual(units["skeleton"]["status"], st.U_FIXING)
        self.assertEqual(units["slice_impl-01"]["status"], st.U_PENDING)

    def test_goal_gap_stops_for_the_operator(self):
        # A skeleton drafter targets the goal → operator-gated failure, not
        # a repair (the goal is operator-authored).
        path = init_state(self.ws, self._reform_config())
        state, note = self._drive_one(
            path, [step("draft_skeleton",
                        _gap_output("draft_skeleton", _gap("goal")))])
        self.assertIsNotNone(state["failure"])
        self.assertEqual(state["failure"]["type"], "goal_gap")
        self.assertIn("goal_gap_reported",
                      [e["type"] for e in state["events"]])

    def test_back_edge_cap_stops_the_run(self):
        path = self._state_to_impl_pending()
        state = st.load(path)
        impl = [u for u in state["units"]
                if st.unit_key(u) == "slice_impl-01"][0]
        impl["gap_repairs"] = 3          # already at the default cap
        st.save(path, state)
        state, note = self._drive_one(
            path, [step("implement", _gap_output("implement",
                                                 _gap("slice_doc-01")))])
        self.assertIsNotNone(state["failure"])
        self.assertEqual(state["failure"]["type"], "gap_stall")

    def test_illegal_target_fails_cleanly(self):
        # An implement gap may not target the goal.
        path = self._state_to_impl_pending()
        state, note = self._drive_one(
            path, [step("implement", _gap_output("implement", _gap("goal")))])
        self.assertIsNotNone(state["failure"])
        self.assertEqual(state["failure"]["type"], "gap_route")

    def test_full_cycle_gap_repair_reseal_redraft_close(self):
        # End to end (git off — pure state flow; git gates are orthogonal
        # and tested elsewhere): the impl reports a gap, the doc is
        # reopened and repaired, reseals, the impl RE-drafts cleanly, and
        # the milestone closes.
        path = self._state_to_impl_pending(git=False)
        script = (
            # 1. impl draft -> gap targeting the doc (reopen)
            [step("implement",
                  _gap_output("implement", _gap("slice_doc-01")))]
            # 2. doc repair (git off: fix returns straight to pre-seal, no
            #    delta), then reseal both halves
            + [step("fix_findings",
                    fix_ok([triaged("GAP1", "fixed", "resolved the route",
                                    severity="P1")],
                           files_changed=["docs/slice-01.md"]),
                    family="codex",
                    side_effect=write_file("docs/slice-01.md",
                                           "# Slice 01\n\nUse /v2/x.\n")),
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
        driver = drv.Driver(path, runner=runners.MockRunner(script))
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
        self.assertEqual(units["slice_doc-01"]["status"], st.U_SEALED)
        self.assertEqual(units["slice_impl-01"]["status"], st.U_SEALED)
        # The doc carries the reopen + repair, and resealed (2 seal attempts).
        self.assertIn("reopened_for_repair",
                      [e["type"] for e in state["events"]])
        self.assertEqual(len(units["slice_doc-01"]["seals"]), 2)
        # The impl drafted successfully on its second attempt.
        self.assertIsNotNone(units["slice_impl-01"]["draft"])


if __name__ == "__main__":
    unittest.main()
