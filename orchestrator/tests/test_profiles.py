"""Strategy profiles: store, identity hashing, sealing, cloning, seeds.

Phase 1 of the build-driven review reform. The invariants under test:

- identity = hash of the canonical SEMANTIC content only; metadata
  (name, version, description, sealed) never moves it;
- a profile seals on first production reference and its semantic
  content becomes immutable (metadata edits stay legal);
- editing sealed content requires clone();
- a run's stored reference is verified against the file on disk and
  divergence fails loudly;
- seeds are written only when missing.
"""

import os
import tempfile
import unittest

from orchestrator import profiles as pr


class ProfilesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-profiles-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def doc(self, name="p", **content):
        base = {"threshold": "x"}
        base.update(content)
        return {"name": name, "version": 1, "sealed": False,
                "description": "d", "profile": base}


class TestIdentity(ProfilesCase):
    def test_hash_covers_semantic_content_only(self):
        a = self.doc()
        b = {"name": "other", "version": 9, "sealed": True,
             "description": "different", "profile": {"threshold": "x"}}
        self.assertEqual(
            pr.semantic_hash(a["profile"]), pr.semantic_hash(b["profile"])
        )

    def test_sealing_does_not_change_identity(self):
        pr.save(self.home, self.doc("p"))
        before = pr.semantic_hash(pr.load(self.home, "p")["profile"])
        pr.seal(self.home, "p")
        after = pr.semantic_hash(pr.load(self.home, "p")["profile"])
        self.assertEqual(before, after)
        self.assertTrue(pr.load(self.home, "p")["sealed"])

    def test_canonicalization_ignores_key_order(self):
        self.assertEqual(
            pr.semantic_hash({"a": 1, "b": [1, 2]}),
            pr.semantic_hash({"b": [1, 2], "a": 1}),
        )


class TestSealing(ProfilesCase):
    def test_sealed_semantic_content_is_immutable(self):
        pr.save(self.home, self.doc("p"))
        pr.seal(self.home, "p")
        changed = self.doc("p", threshold="y")
        with self.assertRaises(pr.ProfileError):
            pr.save(self.home, changed)

    def test_sealed_metadata_edits_stay_legal_and_seal_sticks(self):
        pr.save(self.home, self.doc("p"))
        pr.seal(self.home, "p")
        edit = self.doc("p")
        edit["description"] = "clearer words"
        edit["sealed"] = False  # an attempt to un-seal is ignored
        saved = pr.save(self.home, edit)
        self.assertTrue(saved["sealed"])
        self.assertEqual(pr.load(self.home, "p")["description"],
                         "clearer words")

    def test_reference_seals_and_snapshots_identity(self):
        pr.save(self.home, self.doc("p"))
        ref = pr.reference(self.home, "p")
        self.assertTrue(pr.load(self.home, "p")["sealed"])
        self.assertEqual(
            ref,
            {"name": "p", "version": 1,
             "hash": pr.semantic_hash(self.doc()["profile"])},
        )

    def test_verify_reference_fails_loudly_on_hand_mutation(self):
        pr.save(self.home, self.doc("p"))
        ref = pr.reference(self.home, "p")
        # Hand-mutate the sealed file behind the store's back.
        path = os.path.join(pr.profiles_dir(self.home), "p.json")
        import json
        raw = json.load(open(path))
        raw["profile"]["threshold"] = "tampered"
        json.dump(raw, open(path, "w"))
        with self.assertRaises(pr.ProfileError):
            pr.verify_reference(self.home, ref)

    def test_clone_copies_content_unsealed_under_new_identity_name(self):
        pr.save(self.home, self.doc("p"))
        pr.seal(self.home, "p")
        c = pr.clone(self.home, "p", "p2")
        self.assertFalse(c["sealed"])
        self.assertEqual(c["profile"], self.doc()["profile"])
        with self.assertRaises(pr.ProfileError):
            pr.clone(self.home, "p", "p2")  # name collision refused


class TestValidationAndSeeds(ProfilesCase):
    def test_rejects_bad_documents(self):
        bad = [
            {"name": "", "version": 1, "sealed": False, "profile": {"a": 1}},
            {"name": "x y", "version": 1, "sealed": False,
             "profile": {"a": 1}},
            {"name": "p", "version": 0, "sealed": False,
             "profile": {"a": 1}},
            {"name": "p", "version": 1, "sealed": "no",
             "profile": {"a": 1}},
            {"name": "p", "version": 1, "sealed": False, "profile": {}},
            {"name": "p", "version": 1, "sealed": False,
             "profile": {"p3_defer_max_risk": "extreme"}},
        ]
        for doc in bad:
            with self.subTest(doc=doc):
                with self.assertRaises(pr.ProfileError):
                    pr.save(self.home, doc)

    def test_unknown_profile_and_broken_json(self):
        with self.assertRaises(pr.ProfileError):
            pr.load(self.home, "ghost")
        os.makedirs(pr.profiles_dir(self.home), exist_ok=True)
        with open(os.path.join(pr.profiles_dir(self.home), "bad.json"),
                  "w") as fh:
            fh.write("{not json")
        with self.assertRaises(pr.ProfileError):
            pr.load(self.home, "bad")
        # list_profiles skips the unreadable file instead of dying.
        self.assertEqual(pr.list_profiles(self.home), [])

    def test_seeds_written_once_and_never_overwritten(self):
        created = pr.ensure_seeds(self.home)
        self.assertEqual(sorted(created), ["legacy", "light", "strict"])
        # Operator edits a seed; re-ensuring must not clobber it.
        light = pr.load(self.home, "light")
        light["profile"]["p3_defer_max_risk"] = "low"
        pr.save(self.home, light)
        self.assertEqual(pr.ensure_seeds(self.home), [])
        self.assertEqual(
            pr.load(self.home, "light")["profile"]["p3_defer_max_risk"],
            "low",
        )

    def test_seed_thresholds_match_operator_doctrine(self):
        pr.ensure_seeds(self.home)
        self.assertEqual(
            pr.load(self.home, "strict")["profile"]["p3_defer_max_risk"],
            "low",
        )
        self.assertEqual(
            pr.load(self.home, "light")["profile"]["p3_defer_max_risk"],
            "medium",
        )
        self.assertEqual(
            pr.load(self.home, "strict")["profile"]["fuser_discard"],
            "evidence+concur",
        )


if __name__ == "__main__":
    unittest.main()
