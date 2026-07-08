"""The stage interpreter in isolation (phase 2: family_until_clean only)."""

import unittest

from orchestrator import driver
from orchestrator import interpreter as it
from orchestrator import profiles
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
            "milestone": {"status": st.M_OPEN},
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
