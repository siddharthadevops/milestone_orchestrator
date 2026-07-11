"""Finding-debt deferral with opposite-family reclassification.

When `p3_reclassify_debt` is on, eligible review/seal findings receive a
reclassification one by one. Ratings below the configured threshold become
tracked debt; only the remaining findings reach the fixer. One blocking
finding never drags accepted debt into its fix cycle. The deferrable scope is
phase-dependent (interpreter.defer_scope_for): the DOC phase defers P3 (legacy)
or P2/P3 (reform); the IMPL phase defers cosmetic P3s only (a code P2 always
fixes). Delta findings always take the normal fix/reject path.
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
    fix_ok,
    init_state,
    make_config,
    ok,
    report,
    skeleton_script,
    step,
    triaged,
    write_file,
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


def reclassify(defer_ok, family, reason="verified", risk=None,
               damage=None):
    # The worker only RATES; deferral is the driver comparing the gated
    # axis to p3_defer_max_risk (risk for legacy, DAMAGE for reform).
    # For test intent, defer_ok=True fakes a "low" rating and False a
    # "high" one; drift_damage rides along (harmless extra key for
    # legacy validation, required under reform).
    lvl = "low" if defer_ok else "high"
    return step("reclassify",
                ok("reclassify",
                   drift_risk=risk or lvl,
                   drift_damage=damage or lvl,
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
                     report("review_round", [finding(
                         "F1", "stale word", plain="PLAIN_DEBT_SENTINEL",
                         example="EXAMPLE_DEBT_SENTINEL")]),
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
            # Once rated, later reviewers/sealers receive only the compact
            # technical fingerprint — never the lay framing used by the
            # reclassifier to calibrate gravity.
            claude_review = [
                prompt for fam, kind, prompt in mock.calls
                if fam == "claude" and kind == "review_round"
            ][0]
            self.assertIn("codex-F1", claude_review)
            self.assertNotIn("PLAIN_DEBT_SENTINEL", claude_review)
            self.assertNotIn("EXAMPLE_DEBT_SENTINEL", claude_review)
            seal_prompts = [
                prompt for _fam, kind, prompt in mock.calls
                if kind == "seal_half"
            ]
            self.assertEqual(len(seal_prompts), 2)
            for prompt in seal_prompts:
                self.assertIn("codex-F1", prompt)
                self.assertIn("claude-F1", prompt)

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

    def test_fixed_reclassifier_rates_even_its_own_family(self):
        # acts.reclassifier = "codex" (operator 2026-07-09: a fixed fast
        # rater beats an 8-minute opposite-family rating of a 4-minute
        # review's findings). The codex-raised P3 is rated BY CODEX —
        # the MockRunner's expect_family proves who was asked — and the
        # explicit policy overrides the same-family degeneracy guard.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config(p3_reclassify_debt=True)
            cfg["acts"] = dict(cfg["acts"], reclassifier="codex")
            path = init_state(ws, cfg)
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
                reclassify(True, family="codex", reason="cosmetic"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver, lambda s: s["units"][0].get("debt"))
            state = st.load(path)
            ev = [e for e in state["events"]
                  if e["type"] == "reclassify_recorded"][-1]
            self.assertEqual(ev["reclassifier"], "codex")
            self.assertTrue(ev["defer_ok"])
            self.assertEqual(ev["duration_s"], 0.01)
            # Draft + review + rating are three distinct completed calls.
            self.assertAlmostEqual(
                st.summary(state)["units"][0]["work_duration_s"], 0.03
            )

    def test_reform_gates_on_damage_not_probability(self):
        # The two-axis decision (operator 2026-07-09): a certain-but-cheap
        # drift defers; an unlikely-but-destructive one is fixed.
        strict = profiles.SEEDS["strict"]["profile"]
        for risk, damage, expect_defer in (
            ("xhigh", "low", True),   # builder WILL trip it; costs pennies
            ("low", "xhigh", False),  # unlikely; catastrophic if it lands
        ):
            with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
                path = init_state(
                    ws, make_config(p3_reclassify_debt=True, profile=strict))
                mock = runners.MockRunner([
                    reform_draft_step(),
                    step("review_round",
                         report("review_round",
                                [finding("F1", "two-axis case")]),
                         family="codex"),
                    reclassify(True, family="claude", risk=risk,
                               damage=damage, reason="two-axis"),
                ])
                driver = drv.Driver(path, runner=mock)
                if expect_defer:
                    self.step_until(
                        driver, lambda s: s["units"][0].get("debt"))
                else:
                    self.step_until(
                        driver,
                        lambda s: s["units"][0]["status"] == st.U_FIXING)
                state = st.load(path)
                unit = state["units"][0]
                ev = [e for e in state["events"]
                      if e["type"] == "reclassify_recorded"][-1]
                self.assertEqual(ev["drift_risk"], risk)
                self.assertEqual(ev["drift_damage"], damage)
                self.assertEqual(ev["defer_ok"], expect_defer)
                if expect_defer:
                    self.assertEqual(unit["debt"][0]["drift_damage"], damage)
                else:
                    self.assertEqual(unit["debt"], [])

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

    def test_mixed_round_keeps_debt_out_of_the_fix_queue(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "real gap", severity="P2"),
                             finding("F2", "stale word")]),
                     family="codex"),
                reclassify(True, family="claude", reason="wording only"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            unit = state["units"][0]
            self.assertIn("reclassify", [c[1] for c in mock.calls])
            self.assertEqual([d["id"] for d in unit["debt"]], ["codex-F2"])
            # The real P2 is fixed; the independently accepted P3 no longer
            # rides along merely because another finding blocked the round.
            self.assertEqual(
                [f["id"] for f in unit["fix_queue"]], ["F1"])

    def test_mixed_ratings_do_not_discard_accepted_debt(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "cheap wording"),
                             finding("F2", "serious drift")]),
                     family="codex"),
                reclassify(True, family="claude", reason="local correction"),
                reclassify(False, family="claude", reason="cross-slice drift"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            unit = st.load(path)["units"][0]
            self.assertEqual([d["id"] for d in unit["debt"]], ["codex-F1"])
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F2"])

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

    def _impl_pending(self, ws):
        # State with skeleton + slice_doc SEALED and the slice_impl unit
        # pending, ready for its implement draft (mirrors the setup the
        # existing impl-seal test uses, but stops before implement).
        path = init_state(ws, make_config(p3_reclassify_debt=True))
        state = st.load(path)
        state["milestone"]["slices"] = [{"id": 1, "title": "impl"}]
        state["units"][0]["status"] = st.U_SEALED
        st.ensure_next_unit(state)["status"] = st.U_SEALED
        impl = st.ensure_next_unit(state)
        self.assertEqual(impl["kind"], "slice_impl")
        st.save(path, state)
        return path

    def test_impl_round_p3_only_is_deferred_as_debt(self):
        # Regression: the debt valve used to be DOC-phase only, so an impl
        # slice whose reviewer supplied an unbounded stream of fresh P3s
        # fix-looped until the round cap FAILED the run (found live
        # 2026-07-12, certification-llm slice_impl-08: 12 claude rounds, all
        # P3, never a clean round). The impl REVIEW ROUND now defers cosmetic
        # P3s as debt just like the doc phase — so a lone-P3 impl round is
        # deferred-clean and advances toward the seal.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = self._impl_pending(ws)
            mock = runners.MockRunner([
                step("implement",
                     ok("implement", files_changed=["calculator.py"]),
                     family="codex",
                     side_effect=write_file(
                         "calculator.py", "def add(a, b):\n    return a + b\n")),
                # codex impl round: one lone P3 -> claude reclassifies -> defer
                step("review_round",
                     report("review_round",
                            [finding("F1", "module lacks a docstring")]),
                     family="codex"),
                reclassify(True, family="claude", reason="cosmetic polish"),
                # claude impl round: also a lone P3 -> codex defers
                step("review_round",
                     report("review_round",
                            [finding("F1", "test names could be clearer")]),
                     family="claude"),
                reclassify(True, family="codex", reason="test-naming nit"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda s: s["units"][-1]["status"] == st.U_SEALED,
                max_steps=200)
            self.assertEqual(mock.script, [])
            impl = st.load(path)["units"][-1]
            self.assertEqual(impl["kind"], "slice_impl")
            self.assertEqual(impl["status"], st.U_SEALED)
            # No fix episode ever fired on the impl unit — the P3s deferred.
            self.assertEqual(
                [r for r in impl["rounds"] if r["kind"] == "fix_findings"], [])
            # Both P3s recorded as impl debt for operator visibility.
            self.assertEqual(len(impl["debt"]), 2)
            self.assertEqual({d["cleared_by"] for d in impl["debt"]},
                             {"claude", "codex"})

    def test_impl_round_p2_is_never_deferred(self):
        # The impl scope is P3-only: a code P2 (a real functional deviation)
        # always reaches the fixer even with the debt valve armed.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = self._impl_pending(ws)
            mock = runners.MockRunner([
                step("implement",
                     ok("implement", files_changed=["calculator.py"]),
                     family="codex",
                     side_effect=write_file(
                         "calculator.py", "def add(a, b):\n    return a + b\n")),
                step("review_round",
                     report("review_round",
                            [finding("F1", "div by zero unhandled",
                                     severity="P2")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda s: s["units"][-1]["status"] == st.U_FIXING,
                max_steps=200)
            impl = st.load(path)["units"][-1]
            self.assertEqual(impl["status"], st.U_FIXING)
            self.assertEqual(impl["debt"], [])
            self.assertNotIn("reclassify", [c[1] for c in mock.calls])
            self.assertEqual([f["id"] for f in impl["fix_queue"]], ["F1"])

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

    def test_mixed_seal_keeps_debt_out_of_the_fix_queue(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half",
                     report("seal_half",
                            [finding("F1", "real break", severity="P1"),
                             finding("F2", "minor wording")]),
                     family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
                reclassify(True, family="claude", reason="local correction"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            unit = st.load(path)["units"][0]
            self.assertEqual([d["id"] for d in unit["debt"]], ["codex-F2"])
            self.assertEqual(
                [f["id"] for f in unit["fix_queue"]], ["codex-F1"])
            self.assertFalse(unit["seals"][0]["passed"])

    def test_implementation_seal_p3_is_never_deferred(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            state = st.load(path)
            state["milestone"]["slices"] = [{"id": 1, "title": "impl"}]
            state["units"][0]["status"] = st.U_SEALED
            doc = st.ensure_next_unit(state)
            doc["status"] = st.U_SEALED
            unit = st.ensure_next_unit(state)
            unit["status"] = st.U_SEALING
            unit["artifact"] = "docs/slices/slice-01.md"
            st.save(path, state)
            mock = runners.MockRunner([
                step("seal_half",
                     report("seal_half", [finding("F1", "small code bug")]),
                     family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            driver.step()

            self.assertEqual(mock.script, [])
            self.assertNotIn("reclassify", [call[1] for call in mock.calls])
            unit = st.load(path)["units"][-1]
            self.assertEqual(unit["status"], st.U_FIXING)
            self.assertEqual(unit["debt"], [])
            self.assertEqual(
                [finding_["id"] for finding_ in unit["fix_queue"]],
                ["codex-F1"],
            )

    def test_reform_doc_seal_uses_the_same_p2_scope_as_review(self):
        strict = profiles.SEEDS["strict"]["profile"]
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            config = make_config(p3_reclassify_debt=True, profile=strict)
            config["git"] = {"enabled": False}
            path = init_state(
                ws, config)
            mock = runners.MockRunner([
                reform_draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round",
                     report("review_round", [
                         finding("F0", "forces a real edit", severity="P1")
                     ]),
                     family="claude"),
                step("fix_findings",
                     fix_ok([triaged("F0", "fixed", "forces a real edit",
                                             severity="P1")]),
                     family="codex"),
                step("review_round", report("review_round"), family="claude"),
                # Codex's earlier clean review is stale after the fix, so the
                # reform predicate requests exactly this one fresh half.
                step("seal_half",
                     report("seal_half", [
                         finding("F1", "bounded doc correction", severity="P2")
                     ]),
                     family="codex"),
                reclassify(True, family="claude", risk="high",
                           damage="low", reason="local doc correction"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            unit = st.load(path)["units"][0]
            self.assertEqual(unit["debt"][0]["severity"], "P2")
            self.assertEqual(
                len([r for r in unit["rounds"]
                     if r["kind"] == contracts.KIND_FIX_FINDINGS]),
                1, "the deferred seal P2 must not open another fix episode")


if __name__ == "__main__":
    unittest.main()
