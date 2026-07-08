"""The reform seal PREDICATE (spec §5): a unit seals when every family's
most recent whole-artifact review is clean on the CURRENT bytes — no
dedicated seal-half calls — else the seal falls back to the proven halves.
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
    make_config, init_state, step, ok, report, finding, battery_entries,
)


def _rev(fam, findings=0, invalidated=False, deferred=False, rid=None):
    r = {
        "id": rid or ("%s-rev" % fam),
        "family": fam,
        "kind": "review_round",
        "result": {"findings": [{"id": "F", "severity": "P3"}] * findings},
    }
    if invalidated:
        r["invalidated"] = "reviewer edited"
    if deferred:
        r["deferred_clean"] = True
    return r


def _fix(fam="codex"):
    return {"id": "%s-fix" % fam, "family": fam, "kind": "fix_findings",
            "result": {"findings": []}}


def _unit(*rounds):
    return {"rounds": list(rounds)}


FAMS = ("codex", "claude")


class SealPredicateLogicTest(unittest.TestCase):
    def test_both_clean_no_fix_is_satisfied(self):
        u = _unit(_rev("codex", rid="c1"), _rev("claude", rid="k1"))
        self.assertEqual(st.seal_predicate_reviews(u, FAMS), ["c1", "k1"])

    def test_deferred_clean_counts(self):
        u = _unit(_rev("codex", findings=1, deferred=True, rid="c1"),
                  _rev("claude", deferred=True, findings=1, rid="k1"))
        self.assertEqual(st.seal_predicate_reviews(u, FAMS), ["c1", "k1"])

    def test_fix_after_a_review_makes_it_stale(self):
        # codex clean, then claude fixed something (bytes changed), then
        # claude clean — codex's look is now stale.
        u = _unit(_rev("codex", rid="c1"), _rev("claude", findings=1),
                  _fix("claude"), _rev("claude", rid="k2"))
        self.assertIsNone(st.seal_predicate_reviews(u, FAMS))

    def test_re_review_after_the_fix_satisfies(self):
        # Same, but codex ALSO re-reviewed after the fix → both current.
        u = _unit(_rev("codex"), _rev("claude", findings=1), _fix("claude"),
                  _rev("claude", rid="k2"), _rev("codex", rid="c2"))
        self.assertEqual(
            set(st.seal_predicate_reviews(u, FAMS)), {"c2", "k2"})

    def test_a_family_that_never_reviewed_is_unsatisfied(self):
        self.assertIsNone(
            st.seal_predicate_reviews(_unit(_rev("codex")), FAMS))

    def test_dirty_last_review_is_unsatisfied(self):
        u = _unit(_rev("codex"), _rev("claude", findings=1))
        self.assertIsNone(st.seal_predicate_reviews(u, FAMS))

    def test_invalidated_review_ignored(self):
        u = _unit(_rev("codex", rid="c1"),
                  _rev("claude", invalidated=True), _rev("claude", rid="k2"))
        self.assertEqual(st.seal_predicate_reviews(u, FAMS), ["c1", "k2"])


class SealPredicateDriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-sealpred-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "ws")
        os.makedirs(self.ws)

    def _config(self, profile_name):
        cfg = make_config()
        cfg["git"] = {"enabled": False}
        if profile_name:
            cfg["profile"] = profiles.SEEDS[profile_name]["profile"]
        return cfg

    def _drive(self, cfg, script):
        path = init_state(self.ws, cfg)
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            if driver.state["units"][0]["status"] == st.U_SEALED:
                break   # the skeleton is sealed; that is all these test
            action, _n = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
        return st.load(path), driver

    def _skeleton_clean_no_seal_halves(self, battery=None):
        # draft + a clean review per family; NO seal_half steps (a reform
        # unit seals by predicate). A reform draft carries the answered
        # question battery; a legacy draft (battery=None) carries none —
        # faithful to pre-reform workers.
        draft = ok("draft_skeleton", artifact="docs/skeleton.md",
                   slices=[{"id": 1, "title": "Core"}])
        if battery:
            draft["battery"] = battery
        return [
            step("draft_skeleton", draft, family="codex"),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]

    def test_reform_skeleton_seals_by_predicate(self):
        state, _ = self._drive(
            self._config("strict"),
            self._skeleton_clean_no_seal_halves(
                battery=battery_entries(
                    contracts.BATTERY_QUESTIONS_SKELETON)))
        sk = state["units"][0]
        self.assertEqual(sk["status"], st.U_SEALED)
        # Sealed with NO seal-half findings recorded, and a seal_satisfied
        # event citing the two clean reviews.
        satisfied = [e for e in state["events"]
                     if e["type"] == "seal_satisfied"]
        self.assertEqual(len(satisfied), 1)
        self.assertEqual(len(satisfied[0]["reviews"]), 2)
        self.assertEqual(sk["seals"][0]["halves"], {})

    def test_legacy_still_runs_seal_halves(self):
        # The legacy profile keeps the double-seal halves — the script MUST
        # provide them or the run would stall asking for a seal_half.
        script = self._skeleton_clean_no_seal_halves() + [
            step("seal_half", report("seal_half"), family="codex"),
            step("seal_half", report("seal_half"), family="claude"),
        ]
        state, driver = self._drive(self._config("legacy"), script)
        self.assertEqual(state["units"][0]["status"], st.U_SEALED)
        self.assertEqual(driver.runner.script, [], "seal halves were used")
        self.assertNotIn("seal_satisfied",
                         [e["type"] for e in state["events"]])


if __name__ == "__main__":
    unittest.main()
