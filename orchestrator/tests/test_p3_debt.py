"""P3 debt deferral with opposite-family reclassification.

When `p3_reclassify_debt` is on, a review round (DOC phase only) or a seal
(both phases) whose findings are ALL P3 gets an opposite-family
reclassification per finding. If every P3 is verified safe to defer, the
findings become tracked debt and the unit advances/seals instead of firing
a fix cycle. Any P0-P2 present, any delta, and impl-phase rounds are
unaffected. A refused verdict routes to the normal fix flow.
"""

import tempfile
import unittest

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import profiles
from orchestrator import runners
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    DriverTestCase,
    battery_entries,
    finding,
    init_state,
    make_config,
    ok,
    report,
    skeleton_script,
    step,
)


def draft_step():
    return skeleton_script()[0]


def reform_draft_step():
    """draft_step() plus the answered question battery a reform profile
    hard-requires on doc drafts (legacy/profile-less drafts stay bare)."""
    s = draft_step()
    s["response"]["battery"] = battery_entries(
        contracts.BATTERY_QUESTIONS_SKELETON)
    return s


def reclassify(defer_ok, family, reason="verified", risk=None):
    # The worker only RATES drift risk; deferral is the driver comparing
    # that rating to p3_defer_max_risk (default "low"). For test intent,
    # defer_ok=True fakes a "low" rating and False a "high" one.
    return step("reclassify",
                ok("reclassify",
                   drift_risk=risk or ("low" if defer_ok else "high"),
                   reason=reason),
                family=family)


class TestP3Debt(DriverTestCase):
    def test_doc_round_p3_only_is_deferred_as_debt(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                # codex round: one lone P3 -> claude reclassifies -> defer
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
                reclassify(True, family="claude", reason="cosmetic, no drift"),
                # codex family advanced; claude round: also a lone P3
                step("review_round",
                     report("review_round", [finding("F1", "typo")]),
                     family="claude"),
                reclassify(True, family="codex", reason="wording only"),
                # both families deferred-clean -> seal
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_SEALED)
            # No fix episode ever fired.
            self.assertEqual(
                [r for r in unit["rounds"] if r["kind"] == "fix_findings"], [])
            # Two P3s recorded as debt, tagged with who cleared them.
            self.assertEqual(len(unit["debt"]), 2)
            self.assertEqual(unit["debt"][0]["cleared_by"], "claude")
            self.assertEqual(unit["debt"][1]["cleared_by"], "codex")
            # Ledger carries the debt events for operator visibility.
            debt_events = [e for e in state["events"]
                           if e["type"] == "debt_recorded"]
            self.assertEqual(len(debt_events), 2)

    def test_reclassifier_refusal_routes_to_the_fixer(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "looks trivial but isn't")]),
                     family="codex"),
                # claude refuses to defer -> normal fix flow
                reclassify(False, family="claude", reason="hidden drift risk"),
            ])
            driver = drv.Driver(path, runner=mock)
            # Step until the unit enters fixing (the refusal path).
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_FIXING)
            self.assertEqual(unit["debt"], [])
            # The P3 is queued for the fixer, not deferred.
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F1"])

    def test_reform_profile_defers_a_lone_p2_as_debt(self):
        # 3b: a reform profile widens the DOC gate to P2/P3. A lone P2 rated
        # at-or-below the profile threshold defers as tracked debt, and the
        # debt records the finding's REAL severity (P2), not a hardcoded P3.
        strict = profiles.SEEDS["strict"]["profile"]  # threshold "low"
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(
                ws, make_config(p3_reclassify_debt=True, profile=strict))
            mock = runners.MockRunner([
                reform_draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "minor phrasing", severity="P2")]),
                     family="codex"),
                reclassify(True, family="claude", reason="cosmetic",
                           risk="low"),
                step("review_round",
                     report("review_round",
                            [finding("F1", "minor phrasing", severity="P2")]),
                     family="claude"),
                reclassify(True, family="codex", reason="cosmetic",
                           risk="low"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            unit = st.load(path)["units"][0]
            self.assertEqual(unit["status"], st.U_SEALED)
            self.assertEqual(
                [r for r in unit["rounds"] if r["kind"] == "fix_findings"], [])
            self.assertEqual(len(unit["debt"]), 2)
            self.assertEqual(unit["debt"][0]["severity"], "P2")

    def test_legacy_profile_still_fixes_a_lone_p2(self):
        # The SAME P2 under the legacy compat profile keeps the pre-reform
        # P3-only scope: not deferrable, so a fix cycle fires (no reclassify
        # call is even made — the round is not all-in-scope).
        legacy = profiles.SEEDS["legacy"]["profile"]
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(
                ws, make_config(p3_reclassify_debt=True, profile=legacy))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "minor phrasing", severity="P2")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            unit = st.load(path)["units"][0]
            self.assertEqual(unit["status"], st.U_FIXING)
            self.assertEqual(unit["debt"], [])

    def test_threshold_decides_over_the_rating(self):
        # A "medium" rating defers under threshold "medium" but is kept
        # under the default "low" — the SAME rating, opposite outcomes:
        # the decision lives in config, not in the worker.
        for threshold, expect_defer in (("medium", True), ("low", False)):
            with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
                cfg = make_config(p3_reclassify_debt=True)
                cfg["p3_defer_max_risk"] = threshold
                path = init_state(ws, cfg)
                script = [
                    draft_step(),
                    step("review_round",
                         report("review_round",
                                [finding("F1", "slightly ambiguous phrase")]),
                         family="codex"),
                    reclassify(True, family="claude",
                               reason="minor ambiguity", risk="medium"),
                ]
                mock = runners.MockRunner(script)
                driver = drv.Driver(path, runner=mock)
                want = st.U_FIXING
                if expect_defer:
                    # advances to the next family's rounds without fixing
                    self.step_until(
                        driver,
                        lambda s: s["units"][0].get("debt"))
                else:
                    self.step_until(
                        driver,
                        lambda s: s["units"][0]["status"] == want)
                state = st.load(path)
                unit = state["units"][0]
                ev = [e for e in state["events"]
                      if e["type"] == "reclassify_recorded"][-1]
                self.assertEqual(ev["drift_risk"], "medium")
                self.assertEqual(ev["threshold"], threshold)
                self.assertEqual(ev["defer_ok"], expect_defer)
                if expect_defer:
                    self.assertEqual(unit["debt"][0]["drift_risk"], "medium")
                    self.assertEqual(unit["fix_queue"], [])
                else:
                    self.assertEqual(unit["debt"], [])
                    self.assertEqual(
                        [f["id"] for f in unit["fix_queue"]], ["F1"])

    def test_p2_alongside_p3_skips_reclassify_and_fixes_all(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "real gap", severity="P2"),
                             finding("F2", "stale word")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            unit = state["units"][0]
            # No reclassify call was made (a P2 was present).
            self.assertNotIn(
                "reclassify", [c[1] for c in mock.calls])
            self.assertEqual(unit["debt"], [])
            # Both findings (P2 and its ride-along P3) went to the fixer.
            self.assertEqual(
                sorted(f["id"] for f in unit["fix_queue"]), ["F1", "F2"])

    def test_feature_off_by_default_p3_still_fixes(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())  # p3_reclassify_debt absent
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            self.assertNotIn("reclassify", [c[1] for c in mock.calls])
            self.assertEqual(state["units"][0]["fix_queue"][0]["id"], "F1")

    def test_single_family_config_never_defers(self):
        # With one family there is no independent opposite reclassifier, so
        # a P3 must never self-defer — it takes the normal fix path.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config(p3_reclassify_debt=True,
                              families_order=["codex"], fix_family="codex")
            path = init_state(ws, cfg)
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            unit = state["units"][0]
            self.assertNotIn("reclassify", [c[1] for c in mock.calls])
            self.assertEqual(unit["debt"], [])
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F1"])

    def test_seal_p3_only_is_deferred_and_seals(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                # Seal: codex half raises a lone P3; claude half clean.
                step("seal_half",
                     report("seal_half", [finding("F1", "note typo")]),
                     family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
                # The codex-half P3 -> claude reclassifies -> defer -> seal.
                reclassify(True, family="claude", reason="cosmetic"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_SEALED)
            # Sealed on the first attempt (no reopen), P3 recorded as debt.
            self.assertEqual(len(unit["seals"]), 1)
            self.assertTrue(unit["seals"][0]["passed"])
            self.assertEqual(len(unit["debt"]), 1)
            self.assertEqual(unit["debt"][0]["id"], "codex-F1")


if __name__ == "__main__":
    unittest.main()
