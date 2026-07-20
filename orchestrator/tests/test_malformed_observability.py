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

import json
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
        self.assertEqual(e["unit"], "skeleton")
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
        # Draft + malformed first strike + repaired review: three completed
        # calls, each counted once.
        self.assertAlmostEqual(
            st.summary(state)["units"][0]["work_duration_s"], 0.03
        )

    def test_unterminated_envelope_is_visible_without_costing_a_retry(self):
        # Live shape (2026-07-19): a complete review whose envelope lacks
        # only its final `}`. It must still surface as malformed — the
        # model dropping the brace is a real defect — but it must NOT cost
        # a replacement re-review, which is what silently changed verdicts.
        valid = report("review_round")
        unterminated = json.dumps(valid)[:-1] + "\n"
        state = self._drive(
            [
                draft(),
                step("review_round", unterminated, family="codex"),
            ],
            stop=lambda s: self._malformed_events(s),
        )
        events = self._malformed_events(state)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["kind"], "review_round")
        self.assertIn("unterminated", e["error"])
        # No retry was spent, so no wasted duration is attributed.
        self.assertIsNone(e["duration_s"])
        with open(os.path.join(state["workspace"], e["raw_path"]),
                  "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), unterminated)
        # The round landed with the findings the worker actually reported,
        # not a second opinion.
        rounds = state["units"][0]["rounds"]
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0]["result"]["findings"], valid["findings"])

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
        self.assertEqual(events[0]["unit"], "skeleton")
        # The stashed strike never leaks into the recorded seal halves —
        # the ledger keeps its exact historical shape.
        for s_ in state["units"][0]["seals"]:
            for half in (s_.get("halves") or {}).values():
                self.assertNotIn("repair", half)

    def test_seal_half_recovery_is_not_silent(self):
        # The seal is the LAST place a malformed output could slip past
        # unseen: a clean seal_half missing only its final `}` recovers,
        # so it must still leave the same trail a repaired strike does.
        seal = report("seal_half")
        state = self._drive(
            [
                draft(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", json.dumps(seal)[:-1] + "\n",
                     family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ],
            stop=lambda s: s["units"][0]["status"] == st.U_SEALED,
        )
        self.assertEqual(state["units"][0]["status"], st.U_SEALED)
        events = self._malformed_events(state)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "seal_half")
        self.assertEqual(events[0]["family"], "codex")
        self.assertIn("unterminated", events[0]["error"])
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

    def test_double_violation_records_a_fatal_event(self):
        # BOTH attempts malformed: the run fails AND the strike is a
        # FATAL event carrying both attempts' raw paths (the red chip).
        state = self._drive(
            [
                draft(),
                step("review_round", MALFORMED_REVIEW, family="codex"),
                step("review_round", MALFORMED_REVIEW, family="codex"),
            ],
            stop=lambda s: s.get("failure"),
        )
        self.assertIsNotNone(state["failure"])
        events = self._malformed_events(state)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertTrue(e["fatal"])
        self.assertEqual(e["kind"], "review_round")
        self.assertIn("contract-violating output twice", e["error"])
        for rel in (e["raw_path"], e["raw_path2"]):
            self.assertTrue(rel, "fatal event must carry both raw paths")
            with open(os.path.join(state["workspace"], rel),
                      "r", encoding="utf-8") as fh:
                self.assertIn('"kind": "review_round"', fh.read())
        # The summary trail carries it for the panel's red chip.
        self.assertTrue(st.summary(state)["malformed"][0]["fatal"])

    def test_seal_half_double_violation_records_fatal(self):
        state = self._drive(
            [
                draft(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", MALFORMED_SEAL, family="codex"),
                step("seal_half", MALFORMED_SEAL, family="codex"),
            ],
            stop=lambda s: s.get("failure"),
        )
        self.assertIsNotNone(state["failure"])
        events = self._malformed_events(state)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["fatal"])
        self.assertEqual(events[0]["kind"], "seal_half")
        self.assertEqual(events[0]["family"], "codex")
        self.assertTrue(events[0]["raw_path2"])

    def test_runner_failure_records_a_fatal_incident(self):
        # ANY definitively failed LLM call is a red incident — here the
        # CLI itself dies (RunnerError), no output captured at all.
        class DyingRunner(runners.MockRunner):
            def call(self, family, prompt, workspace, model=None,
                     effort=None):
                if runners.prompt_kind(prompt) == "review_round":
                    raise runners.RunnerError(
                        "family %s exited 1 with no output" % family
                    )
                return super().call(family, prompt, workspace,
                                    model=model, effort=effort)

        path = init_state(
            self.ws,
            make_config(git={"enabled": False}, infra_retry_backoff_s=[]),
        )
        driver = drv.Driver(path, runner=DyingRunner([draft()]))
        for _ in range(10):
            action, _n = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
            if st.load(path).get("failure"):
                break
        state = st.load(path)
        self.assertIsNotNone(state["failure"])
        events = self._malformed_events(state)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertTrue(e["fatal"])
        self.assertEqual(e["kind"], "review_round")
        self.assertIn("exited 1", e["error"])
        self.assertIsNone(e["raw_path"])  # the CLI died: nothing captured

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
