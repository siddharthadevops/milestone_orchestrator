"""Strategy profiles: editable store, retained identity, and seeds.

Phase 1 of the build-driven review reform. The invariants under test:

- identity = hash of the canonical SEMANTIC content only; metadata
  (name, version, description, sealed) never moves it;
- selecting a profile never mutates or freezes the reusable source;
- identity and content are resolved from one document and retained together;
- retained verification never consults a later mutable source;
- seeds are written only when missing.
"""

import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from orchestrator import driver
from orchestrator import profiles as pr


class ProfilesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-profiles-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def doc(self, name="p", **content):
        base = {"doc_register": "dense"}
        base.update(content)
        return {"name": name, "version": 1, "sealed": False,
                "description": "d", "profile": base}


class TestIdentity(ProfilesCase):
    def test_hash_covers_semantic_content_only(self):
        a = self.doc()
        b = {"name": "other", "version": 9, "sealed": True,
             "description": "different", "profile": {"doc_register": "dense"}}
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
        documents = [self.doc("p", doc_register=value)
                     for value in ("dense", "lay+hard-table")]
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
        changed = self.doc("p", doc_register="lay+hard-table")
        changed["sealed"] = True  # legacy input has no authority
        saved = pr.save(self.home, changed)
        self.assertFalse(saved["sealed"])
        self.assertEqual(
            pr.load(self.home, "p")["profile"]["doc_register"],
            "lay+hard-table",
        )

    def test_legacy_stored_seal_does_not_block_edit(self):
        pr.save(self.home, self.doc("p"))
        path = os.path.join(pr.profiles_dir(self.home), "p.json")
        with open(path) as fh:
            raw = json.load(fh)
        raw["sealed"] = True
        with open(path, "w") as fh:
            json.dump(raw, fh)
        saved = pr.save(
            self.home, self.doc("p", doc_register="lay+hard-table")
        )
        self.assertFalse(saved["sealed"])
        self.assertEqual(saved["profile"]["doc_register"], "lay+hard-table")

    def test_resolve_returns_one_detached_matching_pair(self):
        pr.save(self.home, self.doc("p"))
        ref, content = pr.resolve(self.home, "p")
        self.assertTrue(pr.verify_retained(ref, content))
        content["doc_register"] = "lay+hard-table"
        self.assertEqual(
            pr.load(self.home, "p")["profile"]["doc_register"], "dense"
        )

    def test_verify_retained_fails_loudly_on_mismatch(self):
        pr.save(self.home, self.doc("p"))
        ref, content = pr.resolve(self.home, "p")
        content["doc_register"] = "lay+hard-table"
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
        with self.assertRaises(pr.ProfileError):
            pr.list_profiles(self.home)

    def test_case_variant_save_preserves_a_usable_catalogue(self):
        lower = self.doc("custom", doc_register="dense")
        upper = self.doc("Custom", doc_register="lay+hard-table")
        pr.save(self.home, lower)
        lower_path = os.path.join(pr.profiles_dir(self.home), "custom.json")
        upper_path = os.path.join(pr.profiles_dir(self.home), "Custom.json")
        if os.path.exists(upper_path) and os.path.samefile(lower_path, upper_path):
            with self.assertRaisesRegex(pr.ProfileError, "conflicts with"):
                pr.save(self.home, upper)
            self.assertEqual(pr.list_profiles(self.home), [lower])
        else:
            pr.save(self.home, upper)
            self.assertEqual(pr.load(self.home, "custom"), lower)
            self.assertEqual(pr.load(self.home, "Custom"), upper)
            self.assertEqual(pr.list_profiles(self.home), [upper, lower])

    def test_case_alias_collision_is_refused_portably(self):
        lower = self.doc("custom", doc_register="dense")
        upper = self.doc("Custom", doc_register="lay+hard-table")
        pr.save(self.home, lower)
        real_link = os.link
        real_samefile = os.path.samefile

        def case_insensitive_link(source, target):
            requested = os.path.basename(target).casefold()
            if any(
                    filename.casefold() == requested
                    for filename in os.listdir(os.path.dirname(target))):
                raise FileExistsError(target)
            real_link(source, target)

        def case_insensitive_samefile(left, right):
            if (os.path.dirname(left) == os.path.dirname(right)
                    and os.path.basename(left).casefold()
                    == os.path.basename(right).casefold()):
                return True
            return real_samefile(left, right)

        with mock.patch.object(pr.os, "link", side_effect=case_insensitive_link), \
             mock.patch.object(
                 pr.os.path, "samefile", side_effect=case_insensitive_samefile):
            with self.assertRaisesRegex(pr.ProfileError, "conflicts with"):
                pr.save(self.home, upper)

        self.assertEqual(pr.list_profiles(self.home), [lower])

    def test_stored_name_mismatch_fails_loudly(self):
        pr.save(self.home, self.doc("custom"))
        path = os.path.join(pr.profiles_dir(self.home), "custom.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.doc("different"), fh)
        with self.assertRaisesRegex(pr.ProfileError, "catalogue is damaged"):
            pr.load(self.home, "custom")

    def test_legacy_name_is_exactly_lowercase(self):
        with self.assertRaisesRegex(
                pr.ProfileError, "must be exactly 'legacy'"):
            pr.save(self.home, self.doc("Legacy"))

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


class StrategyDecisionCatalogueTest(ProfilesCase):
    EXPECTED = [
        {"key": "stages[0].loop", "status": "active",
         "values": ["family_until_clean"]},
        {"key": "doc_reclassify_from", "status": "active",
         "values": ["disabled", "P3", "P2", "P1", "P0"]},
        {"key": "impl_reclassify_from", "status": "active",
         "values": ["disabled", "P3", "P2", "P1", "P0"]},
        {"key": "p3_defer_max_risk", "status": "active",
         "values": ["low", "medium", "high", "xhigh"]},
        {"key": "p3_reclassify_debt", "status": "active",
         "values": [False, True]},
        {"key": "doc_register", "status": "active",
         "values": ["dense", "lay+hard-table"]},
        {"key": "fuser_discard", "status": "reserved",
         "values": ["evidence", "evidence+concur"]},
        {"key": "final_open_pass", "status": "reserved",
         "values": [False, True]},
    ]

    def test_exact_decision_keys_statuses_and_values(self):
        self.assertEqual(pr.decision_catalogue(), self.EXPECTED)

    def test_strict_and_light_decision_round_trip_is_semantically_exact(self):
        keys = [item["key"] for item in pr.decision_catalogue()]
        for name in ("strict", "light"):
            source = pr.SEEDS[name]["profile"]
            rebuilt = {}
            for key in keys:
                if key == "stages[0].loop":
                    rebuilt.setdefault("stages", [{}])[0]["loop"] = (
                        source["stages"][0]["loop"]
                    )
                else:
                    rebuilt[key] = source[key]
            self.assertEqual(
                source["stages"][0]["actions"], [{"scope": "open"}]
            )
            rebuilt["stages"][0]["actions"] = [{"scope": "open"}]
            self.assertEqual(rebuilt, source)
            self.assertEqual(pr.semantic_hash(rebuilt), pr.semantic_hash(source))
            self.assertIn("non-operative", pr.SEEDS[name]["description"])

    def test_seed_classification_floors_match_operator_defaults(self):
        for name in ("strict", "light"):
            content = pr.SEEDS[name]["profile"]
            self.assertEqual(content["doc_reclassify_from"], "P2")
            self.assertEqual(content["impl_reclassify_from"], "P1")


class StrategyDecisionValidationTest(ProfilesCase):
    def strategy_doc(self, name, content):
        return {
            "name": name,
            "version": 1,
            "sealed": False,
            "description": "test",
            "profile": content,
        }

    def test_known_partial_profiles_validate_and_bad_present_content_fails(self):
        legal = []
        for decision in pr.decision_catalogue():
            for value in decision["values"]:
                key = decision["key"]
                if key == "stages[0].loop":
                    legal.append({"stages": [{"loop": value}]})
                else:
                    legal.append({key: value})
        legal.append({
            "stages": [{
                "loop": "family_until_clean",
                "actions": [{"scope": "open"}],
            }],
            "doc_register": "dense",
        })
        for index, content in enumerate(legal):
            with self.subTest(legal=content):
                pr.save(self.home, self.strategy_doc("legal-%d" % index, content))

        prior = self.strategy_doc("steady", {"doc_register": "dense"})
        pr.save(self.home, prior)
        path = os.path.join(pr.profiles_dir(self.home), "steady.json")
        with open(path, "rb") as fh:
            prior_bytes = fh.read()
        invalid = [
            {"unknown": True},
            {"doc_register": "brief"},
            {"doc_reclassify_from": "P4"},
            {"impl_reclassify_from": False},
            {"p3_reclassify_debt": 1},
            {"final_open_pass": "false"},
            {"stages": []},
            {"stages": [{}, {}]},
            {"stages": [{}]},
            {"stages": [{"loop": "parallel"}]},
            {"stages": [{"loop": "family_until_clean", "extra": True}]},
            {"stages": [{"actions": [{"scope": "open"}]}]},
            {"stages": [{"loop": "family_until_clean", "actions": []}]},
            {"stages": [{
                "loop": "family_until_clean",
                "actions": [{"scope": "closed"}],
            }]},
            {"stages": [{
                "loop": "family_until_clean",
                "actions": [{"scope": "open", "extra": True}],
            }]},
        ]
        for content in invalid:
            with self.subTest(invalid=content), self.assertRaises(pr.ProfileError):
                pr.save(self.home, self.strategy_doc("steady", content))
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), prior_bytes)

    def test_cli_rejects_invalid_raw_strategy_before_creating_state(self):
        workspace = os.path.join(self.tmp.name, "invalid-cli-strategy")
        config_path = os.path.join(self.tmp.name, "invalid-strategy.json")
        state_path = os.path.join(self.tmp.name, "state.json")
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump({
                "git": {"enabled": False},
                "profile": {"unknown": True},
            }, fh)
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = driver.main([
                "init", "--goal", "invalid raw strategy",
                "--workspace", workspace,
                "--config", config_path,
                "--state", state_path,
                "--model-profiles-home", self.home,
            ])
        self.assertEqual(code, 2)
        self.assertIn("unknown strategy decision", error.getvalue())
        self.assertFalse(os.path.exists(state_path))

    def test_legacy_is_selectable_equivalent_and_not_composable(self):
        legacy = json.loads(json.dumps(pr.SEEDS["legacy"]))
        legacy["description"] = "edited metadata"
        legacy["version"] = 2
        saved = pr.save(self.home, legacy)
        ref, content = pr.resolve(self.home, "legacy")
        self.assertEqual(content, pr.SEEDS["legacy"]["profile"])
        self.assertTrue(pr.verify_retained(ref, content))
        with self.assertRaises(pr.ProfileError):
            pr.save(self.home, self.strategy_doc("copy", content))
        changed = json.loads(json.dumps(legacy))
        changed["profile"]["doc_register"] = "dense"
        with self.assertRaises(pr.ProfileError):
            pr.save(self.home, changed)
        self.assertEqual(saved["description"], "edited metadata")


if __name__ == "__main__":
    unittest.main()
