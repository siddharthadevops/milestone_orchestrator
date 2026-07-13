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
    make_halves, seal_current_unit, skeleton_draft,
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
        # The design authority (skeleton) anchors the episode with the
        # objective; every sealed slice note is CO-REOPENED with it (the
        # re-documentation wave — the re-documenter has free rein under the
        # goal, so nothing stays sealed against it).
        self.assertEqual(skel["status"], st.U_FIXING)
        self.assertEqual([f["id"] for f in skel["fix_queue"]], ["GAP1"])
        self.assertEqual(skel["fix_queue"][0]["severity"], "P1")
        # The objective pins the missing datum to the REPORTING unit's own
        # scope — never a future/sealed slice (finding 2).
        self.assertIn("REMODEL OBJECTIVE", skel["fix_queue"][0]["summary"])
        self.assertIn("slice_impl-01", skel["fix_queue"][0]["summary"])
        self.assertEqual(units["slice_doc-01"]["status"], st.U_REPAIRING)
        self.assertEqual(state["redoc_wave"],
                         {"anchor": "skeleton", "docs": ["slice_doc-01"],
                          "reporter": "slice_impl-01"})
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

    def test_stranded_wave_closes_on_startup(self):
        # Crash window: the anchor SEALED but the wave close never ran (a
        # gate failure after the seal transition saved). Once the failure is
        # cleared, driver startup must close the wave — otherwise navigation
        # picks a bare-REPAIRING note and decide() has no move for it.
        path = init_state(self.ws, self._reform_config(git=False))
        state = st.load(path)
        seal_current_unit(state, skeleton_draft(1))
        st.ensure_next_unit(state); seal_current_unit(state)   # doc-1
        st.ensure_next_unit(state)                             # impl-1 pending
        by = {st.unit_key(u): u for u in state["units"]}
        gap = {"classification": "fits_remodel", "forced_decision": "d",
               "plain": "p"}
        st.reopen_for_repair(state, by["slice_doc-01"], gap, "wave",
                             reported_by="slice_impl-01")
        skeleton = state["units"][0]
        st.reopen_for_repair(state, skeleton, gap, "gap",
                             reported_by="slice_impl-01")
        st.enter_fix_episode(
            state, skeleton,
            [{"id": "G1", "severity": "P1", "summary": "objective"}],
            "repair", None, "skeleton-gap", st.U_PRE_SEAL_VERIFY)
        state["redoc_wave"] = {"anchor": "skeleton",
                               "docs": ["slice_doc-01"],
                               "reporter": "slice_impl-01"}
        # The anchor reseals... and the driver dies before the wave close.
        st.transition_unit(state, skeleton, st.U_DELTA_REVIEW)
        st.transition_unit(state, skeleton, st.U_PRE_SEAL_VERIFY)
        st.transition_unit(state, skeleton, st.U_SEALING)
        st.record_seal_attempt(state, skeleton, make_halves(), True)
        st.transition_unit(state, skeleton, st.U_SEALED)
        st.save(path, state)
        # Startup recovery closes the stranded wave; navigation proceeds to
        # the reporter's re-draft, never to a bare-repairing note.
        drv.Driver(path, runner=runners.MockRunner([]))
        state = st.load(path)
        by = {st.unit_key(u): u for u in state["units"]}
        self.assertIsNone(state.get("redoc_wave"))
        self.assertEqual(by["slice_doc-01"]["status"], st.U_SEALED)
        self.assertEqual(by["slice_doc-01"]["seals"][-1]["wave"],
                         "skeleton-a2")
        self.assertEqual(st.unit_key(st.current_unit(state)),
                         "slice_impl-01")

    def test_producer_with_pre_remodel_note_reads_the_remodel(self):
        # A PRODUCER slice — not the gap reporter — whose note sealed BEFORE
        # the skeleton's latest reseal must also read the remodel: only the
        # reporter carries has_gap_remodel, and a producer building from its
        # stale sealed note would omit the remodel's assignment and force
        # the reporter to gap again.
        path = init_state(self.ws, self._reform_config(git=False))
        state = st.load(path)
        seal_current_unit(state, skeleton_draft(2))
        st.ensure_next_unit(state); seal_current_unit(state)   # doc-1
        st.ensure_next_unit(state); seal_current_unit(state)   # impl-1
        st.ensure_next_unit(state); seal_current_unit(state)   # doc-2
        st.ensure_next_unit(state)                             # impl-2 pending
        # A remodel (triggered elsewhere) reopens and reseals the skeleton
        # AFTER doc-2 sealed.
        skeleton = state["units"][0]
        st.reopen_for_repair(
            state, skeleton,
            {"classification": "fits_remodel", "forced_decision": "d",
             "plain": "p"},
            "remodel", reported_by="slice_impl-01",
        )
        st.enter_fix_episode(
            state, skeleton,
            [{"id": "G1", "severity": "P1", "summary": "objective"}],
            "repair", None, "skeleton-gap", st.U_PRE_SEAL_VERIFY)
        st.transition_unit(state, skeleton, st.U_DELTA_REVIEW)
        st.transition_unit(state, skeleton, st.U_PRE_SEAL_VERIFY)
        st.transition_unit(state, skeleton, st.U_SEALING)
        st.record_seal_attempt(state, skeleton, make_halves(), True)
        # Ordering is by ledger seq (the reseal transition is a later event
        # than doc-2's), so same-second seals cannot tie.
        st.transition_unit(state, skeleton, st.U_SEALED)
        st.save(path, state)

        mock = runners.MockRunner(
            [step("implement", ok("implement", files_changed=["calc.py"]),
                  side_effect=write_file("calc.py", "x = 1\n"))])
        drv.Driver(path, runner=mock).step()
        impl_prompts = [p for (_f, kind, p) in mock.calls
                        if kind == "implement"]
        self.assertEqual(len(impl_prompts), 1)
        self.assertIn("slice 2", impl_prompts[0])
        # No has_gap_remodel flag on impl-2 — the note-predates-reseal
        # predicate alone must expose the remodel.
        self.assertIn("REMODEL ASSIGNMENT", impl_prompts[0])

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
        # RE-DOCUMENTATION WAVE: doc-01 was co-reopened with the anchor and
        # resealed by the wave when the anchor's seal passed — a WAVE seal
        # record referencing the anchor's attempt, never its own episode.
        doc = units["slice_doc-01"]
        self.assertEqual(doc["status"], st.U_SEALED)
        self.assertEqual(len(doc["seals"]), 2)
        self.assertEqual(doc["seals"][-1]["wave"], "skeleton-a2")
        self.assertTrue(doc["seals"][-1]["passed"])
        self.assertIsNone(state.get("redoc_wave"))
        self.assertIn("redoc_wave_closed",
                      [e["type"] for e in state["events"]])
        # The wave's fixer + seal prompts declared the SET (re-documenter
        # framing; the seal certifies the whole documentation set).
        fix_prompts = [p for (_f, kind, p) in mock.calls
                       if kind == "fix_findings"]
        self.assertTrue(any("RE-DOCUMENTATION WAVE" in p
                            and "docs/slice-01.md" in p
                            for p in fix_prompts))
        seal_prompts = [p for (_f, kind, p) in mock.calls
                        if kind == "seal_half"]
        self.assertTrue(any("WAVE SEAL" in p and "docs/slice-01.md" in p
                            for p in seal_prompts))
        # Post-wave the producer predicate is self-consistent: the note
        # resealed AFTER the skeleton, so nothing "predates" the design.
        d = drv.Driver(path, runner=runners.MockRunner([]))
        self.assertFalse(d._note_predates_skeleton(1))


if __name__ == "__main__":
    unittest.main()
