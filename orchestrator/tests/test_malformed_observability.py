"""Repaired first strikes are visible (worker_malformed observability).

A worker whose first output violates the contract and whose single repair
retry then validates used to leave NO trace — no event, no raw file, its
duration unrecorded (a panel round showing 7 minutes that took 20 on the
wall). Now: the malformed text lands in raw/ as <label>-malformed.txt and
a worker_malformed event carries label/kind/family/error/duration/raw
path; state.summary projects the full trail for the panel's chip card.
Covers the ordinary _call path, the seal-half thread path (event emitted
on the MAIN thread after the join; the seal record keeps its historical
shape), and the summary projection.
"""

import os
import tempfile
import unittest

from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    init_state, make_config, ok, report, step,
)

MALFORMED_REVIEW = {"kind": "review_round", "findings": []}   # no "status"
MALFORMED_SEAL = {"kind": "seal_half", "findings": []}        # no "status"


def draft():
    return step(
        "draft_skeleton",
        ok("draft_skeleton", artifact="docs/skeleton.md",
           slices=[{"id": 1, "title": "Core"}]),
        family="codex",
    )


class MalformedObservabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-malformed-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "ws")
        os.makedirs(self.ws)

    def _drive(self, script, stop):
        path = init_state(self.ws, make_config(git={"enabled": False}))
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(40):
            state = st.load(path)
            if stop(state):
                break
            action, _n = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
        return st.load(path)

    def _malformed_events(self, state):
        return [e for e in state["events"]
                if e.get("type") == "worker_malformed"]

    def test_repaired_round_leaves_event_and_raw(self):
        state = self._drive(
            [
                draft(),
                # First attempt violates the contract; the repair retry
                # (same kind, same runner) returns a valid clean round.
                step("review_round", MALFORMED_REVIEW, family="codex"),
                step("review_round", report("review_round"), family="codex"),
            ],
            stop=lambda s: self._malformed_events(s),
        )
        events = self._malformed_events(state)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["kind"], "review_round")
        self.assertEqual(e["family"], "codex")
        self.assertIn("missing required key 'status'", e["error"])
        self.assertIsNotNone(e["duration_s"])
        self.assertTrue(e["label"].startswith("skeleton-codex-r"))
        # The malformed text itself is on disk, verbatim (raw paths are
        # recorded workspace-relative, like every _save_raw artifact).
        with open(os.path.join(state["workspace"], e["raw_path"]),
                  "r", encoding="utf-8") as fh:
            self.assertIn('"kind": "review_round"', fh.read())
        # The round itself recorded normally (the repair succeeded).
        rounds = state["units"][0]["rounds"]
        self.assertEqual(len(rounds), 1)
        self.assertIsNone(rounds[0].get("invalidated"))

    def test_seal_half_repair_records_event_on_the_main_thread(self):
        state = self._drive(
            [
                draft(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                # codex half: malformed then repaired; claude half clean.
                step("seal_half", MALFORMED_SEAL, family="codex"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ],
            stop=lambda s: s["units"][0]["status"] == st.U_SEALED,
        )
        self.assertEqual(state["units"][0]["status"], st.U_SEALED)
        events = self._malformed_events(state)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "seal_half")
        self.assertEqual(events[0]["family"], "codex")
        # The stashed strike never leaks into the recorded seal halves —
        # the ledger keeps its exact historical shape.
        for s_ in state["units"][0]["seals"]:
            for half in (s_.get("halves") or {}).values():
                self.assertNotIn("repair", half)

    def test_summary_projects_the_malformed_trail(self):
        state = self._drive(
            [
                draft(),
                step("review_round", MALFORMED_REVIEW, family="codex"),
                step("review_round", report("review_round"), family="codex"),
            ],
            stop=lambda s: self._malformed_events(s),
        )
        summ = st.summary(state)
        self.assertEqual(len(summ["malformed"]), 1)
        self.assertEqual(summ["malformed"][0]["kind"], "review_round")
        self.assertIn("seq", summ["malformed"][0])

    def test_clean_run_records_nothing(self):
        state = self._drive(
            [
                draft(),
                step("review_round", report("review_round"), family="codex"),
            ],
            stop=lambda s: bool(s["units"][0]["rounds"]),
        )
        self.assertEqual(self._malformed_events(state), [])
        self.assertEqual(st.summary(state)["malformed"], [])


if __name__ == "__main__":
    unittest.main()
