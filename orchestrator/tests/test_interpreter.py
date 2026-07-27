"""The stage interpreter in isolation (phase 2: family_until_clean only)."""

import unittest

from orchestrator import contracts
from orchestrator import driver
from orchestrator import interpreter as it
from orchestrator import profiles
from orchestrator import prompts
from orchestrator import state as st


def _state(config):
    return {"config": config}


class GoverningProfileTest(unittest.TestCase):
    def test_profileless_is_none(self):
        self.assertIsNone(it.governing_profile(_state({})))
        self.assertIsNone(it.governing_profile({"config": None}))

    def test_ref_only_label_has_no_content(self):
        # A run that recorded a profile_ref label but no embedded content
        # is interpreted exactly like profile-less.
        st = _state({"profile_ref": {"name": "light", "version": 1,
                                     "hash": "abc"}})
        self.assertIsNone(it.governing_profile(st))

    def test_embedded_content_is_returned(self):
        content = {"stages": [{"loop": "family_until_clean"}]}
        self.assertEqual(
            it.governing_profile(_state({"profile": content})), content)


class RoundsLoopTest(unittest.TestCase):
    def test_profileless_is_family_until_clean(self):
        self.assertEqual(it.rounds_loop(_state({})), it.FAMILY_UNTIL_CLEAN)

    def test_legacy_seed_is_family_until_clean(self):
        legacy = profiles.SEEDS["legacy"]["profile"]
        self.assertEqual(
            it.rounds_loop(_state({"profile": legacy})),
            it.FAMILY_UNTIL_CLEAN)

    def test_seed_strict_and_light_are_family_until_clean(self):
        # In phase 2 every seed's rounds loop is the canonical flow.
        for name in ("strict", "light"):
            self.assertEqual(
                it.rounds_loop(_state({"profile": profiles.SEEDS[name]["profile"]})),
                it.FAMILY_UNTIL_CLEAN)

    def test_empty_or_missing_stages_default(self):
        self.assertEqual(
            it.rounds_loop(_state({"profile": {"compat": True}})),
            it.FAMILY_UNTIL_CLEAN)
        self.assertEqual(
            it.rounds_loop(_state({"profile": {"stages": []}})),
            it.FAMILY_UNTIL_CLEAN)

    def test_unknown_loop_is_surfaced_verbatim(self):
        # The interpreter returns the loop name so the driver can reject an
        # as-yet-uninterpreted loop loudly (phase 3 implements them).
        st = _state({"profile": {"stages": [{"loop": "parallel"}]}})
        self.assertEqual(it.rounds_loop(st), "parallel")


class EffectiveConfigTest(unittest.TestCase):
    """The profile's dials merge over the run config (spec §5); profile-less
    and dial-less (legacy) runs get the raw config UNCHANGED."""

    def test_profileless_returns_config_unchanged(self):
        cfg = {"p3_defer_max_risk": "low", "x": 1}
        self.assertIs(it.effective_config(_state(cfg)), cfg)

    def test_legacy_has_no_dials_returns_config_unchanged(self):
        cfg = {"p3_defer_max_risk": "low"}
        st = _state(dict(cfg))
        st["config"]["profile"] = profiles.SEEDS["legacy"]["profile"]
        # legacy declares no dial keys → identical object back.
        self.assertIs(it.effective_config(st), st["config"])

    def test_strict_and_light_thresholds_win(self):
        base = {"p3_defer_max_risk": "high", "other": 7}
        for name, expected in (("strict", "low"), ("light", "medium")):
            st = _state(dict(base))
            st["config"]["profile"] = profiles.SEEDS[name]["profile"]
            eff = it.effective_config(st)
            self.assertEqual(eff["p3_defer_max_risk"], expected)
            self.assertEqual(eff["other"], 7)          # untouched keys ride
            self.assertEqual(st["config"]["p3_defer_max_risk"], "high")  # no mutation

    def test_only_known_dials_merge_not_structural_keys(self):
        st = _state({"a": 1})
        st["config"]["profile"] = {"p3_defer_max_risk": "medium",
                                   "stages": [{"loop": "x"}], "compat": True}
        eff = it.effective_config(st)
        self.assertEqual(eff["p3_defer_max_risk"], "medium")
        self.assertNotIn("stages", eff)
        self.assertNotIn("compat", eff)


class VerifyEmbeddedTest(unittest.TestCase):
    def test_profileless_and_ref_only_are_noops(self):
        it.verify_embedded(_state({}))
        it.verify_embedded(_state({"profile_ref": {"hash": "x"}}))

    def test_consistent_embed_passes(self):
        content = profiles.SEEDS["legacy"]["profile"]
        st = _state({"profile": content,
                     "profile_ref": {"name": "legacy", "version": 1,
                                     "hash": profiles.semantic_hash(content)}})
        it.verify_embedded(st)  # no raise

    def test_mismatched_hash_fails_loudly(self):
        content = profiles.SEEDS["legacy"]["profile"]
        st = _state({"profile": content,
                     "profile_ref": {"hash": "deadbeef"}})
        with self.assertRaises(ValueError):
            it.verify_embedded(st)

    def test_embed_without_recorded_hash_is_tolerated(self):
        # No recorded hash to check against (a bare content embed) — not an
        # inconsistency, just nothing to verify.
        it.verify_embedded(_state({"profile": {"stages": []}}))


class DocDeferScopeTest(unittest.TestCase):
    """The DOC-gate deferral scope (spec §2): legacy/profile-less defer only
    lone P3s; a reform profile widens to P2/P3 (P0/P1 always fix)."""

    def test_profileless_and_legacy_are_p3_only(self):
        self.assertEqual(it.doc_defer_scope(_state({})), ("P3",))
        legacy = _state({"profile": profiles.SEEDS["legacy"]["profile"]})
        self.assertEqual(it.doc_defer_scope(legacy), ("P3",))

    def test_reform_profiles_widen_to_p2_p3(self):
        for name in ("strict", "light"):
            st = _state({"profile": profiles.SEEDS[name]["profile"]})
            self.assertEqual(set(it.doc_defer_scope(st)), {"P2", "P3"})

    def test_all_in_severity_matches_scope(self):
        p3 = [{"severity": "P3"}]
        p2p3 = [{"severity": "P2"}, {"severity": "P3"}]
        with_p1 = [{"severity": "P1"}, {"severity": "P3"}]
        # legacy scope: only all-P3 rounds are eligible.
        self.assertTrue(contracts.all_in_severity(p3, ("P3",)))
        self.assertFalse(contracts.all_in_severity(p2p3, ("P3",)))
        # reform scope: P2/P3 eligible, a P0/P1 present blocks deferral.
        self.assertTrue(contracts.all_in_severity(p2p3, ("P2", "P3")))
        self.assertFalse(contracts.all_in_severity(with_p1, ("P2", "P3")))
        # empty is never eligible; all_p3 stays a P3-only alias.
        self.assertFalse(contracts.all_in_severity([], ("P2", "P3")))
        self.assertTrue(contracts.all_p3(p3))
        self.assertFalse(contracts.all_p3(p2p3))


class ImplDeferScopeTest(unittest.TestCase):
    """The IMPL-phase deferral scope: always P3 only — a code P2 is a
    visible functional deviation that must be fixed even under the lightest
    profile, so only cosmetic P3s become debt. defer_scope_for dispatches
    by phase and returns empty for any non-unit kind."""

    def test_impl_scope_is_p3_only_for_every_profile(self):
        self.assertEqual(it.impl_defer_scope(_state({})), ("P3",))
        for name in ("legacy", "strict", "light"):
            state = _state({"profile": profiles.SEEDS[name]["profile"]})
            self.assertEqual(it.impl_defer_scope(state), ("P3",))

    def test_defer_scope_for_dispatches_by_phase(self):
        # A reform profile: docs widen to P2/P3, impl stays P3-only.
        state = _state({"profile": profiles.SEEDS["light"]["profile"]})
        self.assertEqual(set(it.defer_scope_for(state, st.UNIT_SKELETON)),
                         {"P2", "P3"})
        self.assertEqual(set(it.defer_scope_for(state, st.UNIT_SLICE_DOC)),
                         {"P2", "P3"})
        self.assertEqual(it.defer_scope_for(state, st.UNIT_SLICE_IMPL),
                         ("P3",))
        # Any other kind defers nothing.
        self.assertEqual(it.defer_scope_for(state, "something_else"), ())


class ReformActiveTest(unittest.TestCase):
    """The single reform predicate: ON for every reform profile, OFF for
    the `legacy` compatibility artifact and for profile-less runs."""

    def test_reform_profiles_are_active(self):
        for name in ("strict", "light"):
            state = _state({"profile": profiles.SEEDS[name]["profile"]})
            self.assertTrue(it.reform_active(state))

    def test_legacy_and_profileless_are_inactive(self):
        self.assertFalse(it.reform_active(_state({})))
        legacy = _state({"profile": profiles.SEEDS["legacy"]["profile"]})
        self.assertFalse(it.reform_active(legacy))

    def test_gap_predicate_delegates(self):
        # gap_semantics is reform_active by another name; they must never
        # diverge.
        for cfg in ({},
                    {"profile": profiles.SEEDS["legacy"]["profile"]},
                    {"profile": profiles.SEEDS["strict"]["profile"]},
                    {"profile": profiles.SEEDS["light"]["profile"]}):
            state = _state(cfg)
            self.assertEqual(it.gap_semantics(state),
                             it.reform_active(state))


class BatteryQuestionsTest(unittest.TestCase):
    """The question battery (spec §4) is a DOC gate every reform profile
    carries — not a dial: strict and light ask the same questions;
    implementation units and non-reform runs carry none."""

    def test_reform_doc_units_carry_the_battery(self):
        for name in ("strict", "light"):
            state = _state({"profile": profiles.SEEDS[name]["profile"]})
            self.assertEqual(it.battery_questions(state, "skeleton"),
                             contracts.BATTERY_QUESTIONS_SKELETON)
            self.assertEqual(it.battery_questions(state, "slice_doc"),
                             contracts.BATTERY_QUESTIONS_SLICE_NOTE)

    def test_impl_units_have_no_battery(self):
        strict = _state({"profile": profiles.SEEDS["strict"]["profile"]})
        self.assertIsNone(it.battery_questions(strict, "slice_impl"))

    def test_legacy_and_profileless_have_none(self):
        legacy = _state({"profile": profiles.SEEDS["legacy"]["profile"]})
        for kind in ("skeleton", "slice_doc", "slice_impl"):
            self.assertIsNone(it.battery_questions(_state({}), kind))
            self.assertIsNone(it.battery_questions(legacy, kind))


class DocRegisterTest(unittest.TestCase):
    """The doc-authoring register (spec §6) and the plain-mirror hard-
    require flag (spec §7), read from the governing profile."""

    def test_doc_register_defaults_dense(self):
        self.assertEqual(it.doc_register(_state({})), "dense")
        legacy = _state({"profile": profiles.SEEDS["legacy"]["profile"]})
        self.assertEqual(it.doc_register(legacy), "dense")
        strict = _state({"profile": profiles.SEEDS["strict"]["profile"]})
        self.assertEqual(it.doc_register(strict), "dense")

    def test_light_asks_for_lay_hard_table(self):
        light = _state({"profile": profiles.SEEDS["light"]["profile"]})
        self.assertEqual(it.doc_register(light), "lay+hard-table")

    def test_two_register_block_gated_in_the_drafter(self):
        dense = prompts.build_draft_skeleton("codex", "/ws", "goal",
                                             two_register=False)
        two = prompts.build_draft_skeleton("codex", "/ws", "goal",
                                           two_register=True)
        self.assertNotIn("PINNED-FACTS TABLE", dense)
        self.assertIn("PINNED-FACTS TABLE", two)
        self.assertIn("do-not-touch", two)


class DecideSeamTest(unittest.TestCase):
    """The decide() seam in the driver: family_until_clean (and every
    profile-less run) yields a review round exactly as before; any loop the
    interpreter does not yet implement is rejected LOUDLY — never run as the
    wrong flow."""

    def _rounds_state(self, profile=None):
        cfg = {"families_order": ["codex", "claude"]}
        if profile is not None:
            cfg["profile"] = profile
        return {
            "failure": None,
            # slices: every real ledger carries it (new_state) and
            # current_unit navigates in plan order, so the minimal
            # fixture needs it too.
            "milestone": {"status": st.M_OPEN, "slices": []},
            "units": [{"kind": st.UNIT_SKELETON, "slice_id": None,
                       "status": st.U_ROUNDS, "family_index": 0}],
            "config": cfg,
        }

    def test_profileless_yields_review_round(self):
        action = driver.decide(self._rounds_state())
        self.assertEqual(action.type, driver.A_REVIEW_ROUND)
        self.assertEqual(action.params["family"], "codex")

    def test_legacy_profile_yields_review_round(self):
        action = driver.decide(
            self._rounds_state(profiles.SEEDS["legacy"]["profile"]))
        self.assertEqual(action.type, driver.A_REVIEW_ROUND)
        self.assertEqual(action.params["family"], "codex")

    def test_uninterpreted_loop_is_rejected_loudly(self):
        state = self._rounds_state({"stages": [{"loop": "parallel"}]})
        with self.assertRaises(st.IllegalTransition):
            driver.decide(state)


if __name__ == "__main__":
    unittest.main()
