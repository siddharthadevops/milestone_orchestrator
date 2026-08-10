"""Strategy profiles: editable store, retained identity, and seeds.

Phase 1 of the build-driven review reform. The invariants under test:

- identity = hash of the canonical SEMANTIC content only; metadata
  (name, version, description, sealed) never moves it;
- selecting a profile never mutates or freezes the reusable source;
- identity and content are resolved from one document and retained together;
- retained verification never consults a later mutable source;
- seeds are written only when missing.
"""

import os
import tempfile
import threading
import unittest
from unittest import mock

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

    def test_legacy_seal_metadata_does_not_change_identity(self):
        a = self.doc("p")
        b = dict(a, sealed=True)
        self.assertEqual(
            pr.semantic_hash(a["profile"]), pr.semantic_hash(b["profile"])
        )

    def test_canonicalization_ignores_key_order(self):
        self.assertEqual(
            pr.semantic_hash({"a": 1, "b": [1, 2]}),
            pr.semantic_hash({"b": [1, 2], "a": 1}),
        )


class TestEditability(ProfilesCase):
    def test_concurrent_same_name_saves_do_not_share_staging_file(self):
        pr.save(self.home, self.doc("p"))
        documents = [self.doc("p", threshold=value) for value in ("a", "b")]
        replacements_ready = threading.Barrier(2)
        real_replace = os.replace
        staging_paths = []
        results = []
        errors = []

        def synchronized_replace(source, target):
            staging_paths.append(source)
            replacements_ready.wait(timeout=5)
            real_replace(source, target)

        def save(document):
            try:
                results.append(pr.save(self.home, document))
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(pr.os, "replace", side_effect=synchronized_replace):
            threads = [threading.Thread(target=save, args=(doc,))
                       for doc in documents]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(set(staging_paths)), 2)
        self.assertCountEqual(results, documents)
        self.assertIn(pr.load(self.home, "p"), documents)

    def test_used_profile_edit_replaces_content_without_first_use_mutation(self):
        pr.save(self.home, self.doc("p"))
        path = os.path.join(pr.profiles_dir(self.home), "p.json")
        with open(path, "rb") as fh:
            before = fh.read()
        ref = pr.reference(self.home, "p")
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(
            ref,
            {"name": "p", "version": 1,
             "hash": pr.semantic_hash(self.doc()["profile"])},
        )
        changed = self.doc("p", threshold="y")
        changed["sealed"] = True  # legacy input has no authority
        saved = pr.save(self.home, changed)
        self.assertFalse(saved["sealed"])
        self.assertEqual(pr.load(self.home, "p")["profile"]["threshold"], "y")

    def test_legacy_stored_seal_does_not_block_edit(self):
        pr.save(self.home, self.doc("p"))
        path = os.path.join(pr.profiles_dir(self.home), "p.json")
        import json
        with open(path) as fh:
            raw = json.load(fh)
        raw["sealed"] = True
        with open(path, "w") as fh:
            json.dump(raw, fh)
        saved = pr.save(self.home, self.doc("p", threshold="new"))
        self.assertFalse(saved["sealed"])
        self.assertEqual(saved["profile"]["threshold"], "new")

    def test_resolve_returns_one_detached_matching_pair(self):
        pr.save(self.home, self.doc("p"))
        ref, content = pr.resolve(self.home, "p")
        self.assertTrue(pr.verify_retained(ref, content))
        content["threshold"] = "local change"
        self.assertEqual(pr.load(self.home, "p")["profile"]["threshold"], "x")

    def test_verify_retained_fails_loudly_on_mismatch(self):
        pr.save(self.home, self.doc("p"))
        ref, content = pr.resolve(self.home, "p")
        content["threshold"] = "tampered"
        with self.assertRaises(pr.ProfileError):
            pr.verify_retained(ref, content)


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
