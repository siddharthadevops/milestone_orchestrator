"""Store tests for orchestrator/model_profiles.py (model-profiles slice 1).

Covers the closed document contract, the per-act authority matrix, whole
create/edit/list behavior with loud failure (no silent skip, no partial
merge), the missing-only editable `default` seed, and the behavioral
equivalence of the seeded `medium` configuration with today's effective
staffing (DEFAULT_CONFIG acts + model_defaults) across every configurable
act, including the fixed and derived seats.
"""

import copy
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from orchestrator import driver, model_profiles as mp, runners, state as st


def valid_doc(name="web-ui"):
    return {
        "name": name,
        "examples": ["public API contract", "storage migration"],
        "configurations": {
            "low": {"implementer": {"agent": "claude",
                                    "model": "claude-sonnet-5",
                                    "effort": "medium"}},
            "medium": {"fixer": "codex", "consultation": "opposite"},
            "high": {"review_codex": {"effort": "max"}},
        },
    }


class ModelProfileStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-model-profiles-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    # -- helpers -----------------------------------------------------------

    def assert_rejected(self, doc):
        with self.assertRaises(mp.ModelProfileError):
            mp.save(self.home, doc)

    def read_file(self, name):
        with open(os.path.join(self.home, "model_profiles",
                               "%s.json" % name), "rb") as fh:
            return fh.read()

    def write_file(self, name, data):
        d = os.path.join(self.home, "model_profiles")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "%s.json" % name), "w",
                  encoding="utf-8") as fh:
            fh.write(data)

    # -- document contract -------------------------------------------------

    def test_document_contract_and_three_rigors(self):
        # A complete valid document round-trips whole.
        saved = mp.save(self.home, valid_doc())
        loaded = mp.load(self.home, "web-ui")
        self.assertEqual(loaded, saved)
        self.assertEqual(set(loaded), {"name", "examples", "configurations"})
        self.assertEqual(tuple(sorted(loaded["configurations"])),
                         tuple(sorted(mp.RIGORS)))
        self.assertEqual(loaded["examples"],
                         ["public API contract", "storage migration"])

        # Exactly five words is the ceiling, inclusive.
        five = valid_doc("five-words")
        five["examples"] = ["one two three four five"]
        mp.save(self.home, five)

        # Missing top-level keys.
        for key in ("name", "examples", "configurations"):
            with self.subTest(missing=key):
                doc = valid_doc()
                del doc[key]
                self.assert_rejected(doc)
        # Extra top-level keys: the schema is closed — no metadata,
        # version, or seal lifecycle.
        for key, value in (("version", 1), ("sealed", False),
                           ("description", "x"), ("rigor", "medium")):
            with self.subTest(extra=key):
                doc = valid_doc()
                doc[key] = value
                self.assert_rejected(doc)
        # Invalid names.
        for bad in ("", "has space", "a/b", 7, None):
            with self.subTest(name=bad):
                doc = valid_doc()
                doc["name"] = bad
                self.assert_rejected(doc)
        # Malformed examples: wrong type, empty, empty/blank/non-string
        # items, and a six-word item.
        for bad in ("not-a-list", [], [""], ["   "], [7],
                    ["one two three four five six"],
                    ["fine words", ""]):
            with self.subTest(examples=bad):
                doc = valid_doc()
                doc["examples"] = bad
                self.assert_rejected(doc)
        # Rigor set must be exactly low/medium/high.
        missing_rigor = valid_doc()
        del missing_rigor["configurations"]["high"]
        self.assert_rejected(missing_rigor)
        extra_rigor = valid_doc()
        extra_rigor["configurations"]["xhigh"] = {}
        self.assert_rejected(extra_rigor)
        not_a_map = valid_doc()
        not_a_map["configurations"] = "strict"
        self.assert_rejected(not_a_map)
        rigor_not_a_map = valid_doc()
        rigor_not_a_map["configurations"]["medium"] = "codex"
        self.assert_rejected(rigor_not_a_map)
        # The whole document must be an object.
        for bad in (None, [], "doc", 5):
            with self.subTest(doc=bad):
                self.assert_rejected(bad)
        # A refused create leaves no file behind.
        ghost = valid_doc("ghost")
        del ghost["configurations"]["low"]
        self.assert_rejected(ghost)
        with self.assertRaises(mp.ModelProfileError):
            mp.load(self.home, "ghost")

    # -- per-act authority matrix ------------------------------------------

    def test_per_act_authority_matrix(self):
        def doc_for(act_map):
            doc = valid_doc("matrix")
            doc["configurations"]["medium"] = act_map
            return doc

        # Full-policy acts: family-policy string or {agent, model, effort}.
        for act in mp.FULL_POLICY_ACTS:
            for entry in ("codex", "opposite", "self",
                          {"agent": "claude", "model": "claude-opus-5",
                           "effort": "high"},
                          {"effort": "xhigh"},
                          {"model": "gpt-5.6-terra"}):
                with self.subTest(act=act, entry=entry):
                    saved = mp.save(self.home, doc_for({act: entry}))
                    self.assertEqual(
                        saved["configurations"]["medium"], {act: entry})
        # Fixed/derived-family acts: model and/or effort only.
        for act in mp.MODEL_EFFORT_ACTS:
            for entry in ({"model": "claude-sonnet-5"}, {"effort": "low"},
                          {"model": "gpt-5.6-luna", "effort": "max"}):
                with self.subTest(act=act, entry=entry):
                    saved = mp.save(self.home, doc_for({act: entry}))
                    self.assertEqual(
                        saved["configurations"]["medium"], {act: entry})
        # Consultation: family-policy string only.
        for entry in ("opposite", "codex", "self"):
            with self.subTest(act="consultation", entry=entry):
                mp.save(self.home, doc_for({"consultation": entry}))
        # Omitted acts are legal, down to a fully empty act map per rigor.
        empty = valid_doc("empty-maps")
        empty["configurations"] = {"low": {}, "medium": {}, "high": {}}
        saved = mp.save(self.home, empty)
        self.assertEqual(saved["configurations"],
                         {"low": {}, "medium": {}, "high": {}})
        # Values are stored stripped (the acts channel's input posture).
        padded = mp.save(self.home, doc_for(
            {"fixer": " codex ", "implementer": {"model": " m-1 "}}))
        self.assertEqual(padded["configurations"]["medium"],
                         {"fixer": "codex", "implementer": {"model": "m-1"}})

        # Unknown acts are input errors (delta review is deliberately not
        # independently staffable).
        for act in ("delta_review", "verifier", "seal_half"):
            with self.subTest(unknown_act=act):
                self.assert_rejected(doc_for({act: "codex"}))
        # Empty entries are errors, never a cleared no-op.
        for act in mp.PROFILE_ACT_KEYS:
            for entry in (None, "", {}):
                with self.subTest(act=act, empty=entry):
                    self.assert_rejected(doc_for({act: entry}))
        # Full-policy objects: closed field set, non-empty short strings.
        for entry in ({"temperature": "1"}, {"family": "codex"},
                      {"model": ""}, {"effort": 3}, {"agent": "  "},
                      {"model": "x" * 101}, {"agent": "claude", "mode": "y"}):
            with self.subTest(fixer=entry):
                self.assert_rejected(doc_for({"fixer": entry}))
        # Fixed reviews and the counterpart never accept an agent — not
        # even one naming the structurally fixed family — nor a string.
        self.assert_rejected(doc_for({"review_codex": {"agent": "codex"}}))
        self.assert_rejected(doc_for({"review_claude": {"agent": "claude"}}))
        self.assert_rejected(
            doc_for({"brainstorming_counterpart": {"agent": "codex"}}))
        for act in mp.MODEL_EFFORT_ACTS:
            for entry in ("codex", "opposite", {"model": ""},
                          {"family": "codex"}, 5):
                with self.subTest(act=act, entry=entry):
                    self.assert_rejected(doc_for({act: entry}))
        # Consultation carries no model/effort/agent — its staffing beyond
        # the family is derived; the acts channel's historical silent
        # acceptance does not carry into profiles.
        for entry in ({"model": "m"}, {"effort": "high"},
                      {"agent": "claude"}, {"model": "m", "effort": "low"},
                      5, ["codex"]):
            with self.subTest(consultation=entry):
                self.assert_rejected(doc_for({"consultation": entry}))

    # -- create / edit / list ----------------------------------------------

    def test_store_create_edit_list_and_failure_atomicity(self):
        for name in ("bravo", "alpha", "alpha-ui", "charlie"):
            doc = valid_doc(name)
            doc["examples"] = ["clue for %s" % name]
            mp.save(self.home, doc)
        listed = mp.list_model_profiles(self.home)
        self.assertEqual([d["name"] for d in listed],
                         ["alpha", "alpha-ui", "bravo", "charlie"])

        # A valid same-name save WHOLLY replaces the prior source: nothing
        # of the old definition survives, no key-wise merge.
        v2 = {
            "name": "alpha",
            "examples": ["second alpha clue"],
            "configurations": {
                "low": {},
                "medium": {"drafter": {"agent": "codex", "effort": "low"}},
                "high": {"review_claude": {"effort": "max"}},
            },
        }
        mp.save(self.home, v2)
        loaded = mp.load(self.home, "alpha")
        self.assertEqual(loaded, v2)
        self.assertNotIn("fixer", loaded["configurations"]["medium"])
        self.assertEqual(loaded["examples"], ["second alpha clue"])

        # An invalid edit changes nothing: the prior source stays equal.
        bad = copy.deepcopy(v2)
        del bad["configurations"]["high"]
        self.assert_rejected(bad)
        bad_entry = copy.deepcopy(v2)
        bad_entry["configurations"]["medium"]["review_claude"] = {
            "agent": "claude"}
        self.assert_rejected(bad_entry)
        self.assertEqual(mp.load(self.home, "alpha"), v2)

        # Loading an unknown name is loud.
        with self.assertRaises(mp.ModelProfileError):
            mp.load(self.home, "missing")

        # One damaged stored file makes LISTING fail — never a silently
        # shortened catalogue: broken JSON, a structurally invalid
        # document, and a file whose content names another profile.
        good = self.read_file("bravo")
        self.write_file("bravo", "{not json")
        with self.assertRaises(mp.ModelProfileError):
            mp.load(self.home, "bravo")
        with self.assertRaises(mp.ModelProfileError):
            mp.list_model_profiles(self.home)
        self.write_file("bravo", json.dumps({"name": "bravo"}))
        with self.assertRaises(mp.ModelProfileError):
            mp.list_model_profiles(self.home)
        with open(os.path.join(self.home, "model_profiles", "bravo.json"),
                  "wb") as fh:
            fh.write(good)
        mismatched = valid_doc("delta")
        self.write_file("charlie", json.dumps(mismatched))
        with self.assertRaises(mp.ModelProfileError):
            mp.list_model_profiles(self.home)

    def test_concurrent_saves_are_atomic_and_last_replacement_wins(self):
        mp.ensure_default(self.home)
        first = copy.deepcopy(mp.DEFAULT_SEED)
        first["examples"] = ["first completed save"]
        second = copy.deepcopy(mp.DEFAULT_SEED)
        second["examples"] = ["second completed save"]
        real_replace = os.replace
        both_ready = threading.Barrier(2)
        first_replaced = threading.Event()
        errors = []

        def ordered_replace(source, target):
            both_ready.wait(timeout=5)
            if threading.current_thread().name == "profile-first":
                real_replace(source, target)
                first_replaced.set()
            else:
                self.assertTrue(first_replaced.wait(timeout=5))
                real_replace(source, target)

        def save(doc):
            try:
                mp.save(self.home, doc)
            except Exception as exc:  # pragma: no cover - assertion surface
                errors.append(exc)

        with mock.patch(
                "orchestrator.model_profiles.os.replace",
                side_effect=ordered_replace):
            threads = (
                threading.Thread(
                    target=save, args=(first,), name="profile-first"
                ),
                threading.Thread(
                    target=save, args=(second,), name="profile-second"
                ),
            )
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(mp.load(self.home, "default"), second)

    def test_staged_save_does_not_enter_catalogue(self):
        reached_replace = threading.Event()
        release_replace = threading.Event()
        real_replace = os.replace
        errors = []

        def paused_replace(source, target):
            reached_replace.set()
            self.assertTrue(release_replace.wait(timeout=5))
            real_replace(source, target)

        def save():
            try:
                mp.save(self.home, valid_doc("alpha"))
            except Exception as exc:  # pragma: no cover - assertion surface
                errors.append(exc)

        with mock.patch(
                "orchestrator.model_profiles.os.replace",
                side_effect=paused_replace):
            thread = threading.Thread(target=save)
            thread.start()
            self.assertTrue(reached_replace.wait(timeout=5))
            try:
                self.assertEqual(mp.list_model_profiles(self.home), [])
            finally:
                release_replace.set()
                thread.join(timeout=10)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(mp.list_model_profiles(self.home), [valid_doc("alpha")])

    def test_valid_long_profile_name_remains_writable(self):
        # The final 250-byte component fits the common 255-byte filesystem
        # limit.  Staging must not add the profile name again with overhead.
        name = "a" * 245
        expected = valid_doc(name)

        self.assertEqual(mp.save(self.home, expected), expected)
        self.assertEqual(mp.load(self.home, name), expected)

    def test_case_variant_create_cannot_overwrite_catalogue_entry(self):
        self.assertTrue(mp.ensure_default(self.home))
        default_bytes = self.read_file("default")

        with self.assertRaisesRegex(
                mp.ModelProfileError, "case-insensitively unique"):
            mp.save(self.home, valid_doc("Default"))

        self.assertEqual(self.read_file("default"), default_bytes)
        self.assertEqual(mp.list_model_profiles(self.home), [mp.DEFAULT_SEED])
        self.assertFalse(mp.ensure_default(self.home))

    # -- seeded default ----------------------------------------------------

    def test_default_seed_is_missing_only(self):
        self.assertTrue(mp.ensure_default(self.home))
        doc = mp.load(self.home, "default")
        self.assertEqual(doc["name"], "default")
        self.assertEqual(set(doc["configurations"]), set(mp.RIGORS))
        self.assertEqual(doc, mp.DEFAULT_SEED)

        # Re-running the seed never rewrites the file, not even a byte.
        pristine = self.read_file("default")
        self.assertFalse(mp.ensure_default(self.home))
        self.assertEqual(self.read_file("default"), pristine)

        # An operator edit survives another initialization exactly.
        edited = copy.deepcopy(doc)
        edited["examples"] = ["operator edited clue"]
        edited["configurations"]["medium"]["fixer"] = "claude"
        mp.save(self.home, edited)
        edited_bytes = self.read_file("default")
        self.assertFalse(mp.ensure_default(self.home))
        self.assertEqual(self.read_file("default"), edited_bytes)
        self.assertEqual(mp.load(self.home, "default"), edited)

        # An invalid existing default is REPORTED, never healed or
        # replaced by the seed.
        self.write_file("default", "{broken")
        with self.assertRaises(mp.ModelProfileError):
            mp.ensure_default(self.home)
        self.assertEqual(self.read_file("default"), b"{broken")
        self.write_file("default", json.dumps({"name": "default"}))
        with self.assertRaises(mp.ModelProfileError):
            mp.ensure_default(self.home)
        self.assertEqual(json.loads(self.read_file("default")),
                         {"name": "default"})

    def test_dangling_default_link_is_unavailable_not_missing(self):
        directory = mp.model_profiles_dir(self.home)
        os.makedirs(directory)
        path = os.path.join(directory, "default.json")
        target = os.path.join(self.home, "temporarily-unavailable-default")
        os.symlink(target, path)

        with self.assertRaisesRegex(mp.ModelProfileError, "unavailable"):
            mp.ensure_default(self.home)

        self.assertTrue(os.path.islink(path))
        self.assertEqual(os.readlink(path), target)

    # -- seeded medium == today's staffing ---------------------------------

    def _driver_with_acts(self, tmp, name, acts):
        """A real Driver over DEFAULT_CONFIG whose `acts` are replaced —
        the resolution seams themselves are the comparison surface."""
        ws = os.path.join(tmp, name)
        os.makedirs(ws)
        cfg = json.loads(json.dumps(driver.DEFAULT_CONFIG))
        cfg["acts"] = acts
        path = driver.default_state_path(ws)
        st.save(path, st.new_state("model-profile equivalence probe",
                                   ws, cfg))
        return driver.Driver(path, runner=runners.MockRunner([]))

    def _staffing_snapshot(self, d):
        """Every configurable act's effective staffing: family plus
        model/effort with family defaults filled (as _call fills them),
        across both origin families where the act is origin-sensitive,
        plus the fixed reviews and the derived delta, counterpart, and
        consultation seats."""

        def filled(family, model, effort):
            default_model, default_effort = d._family_defaults(family)
            return (family, model or default_model, effort or default_effort)

        snap = {}
        for act in ("drafter", "implementer"):
            snap[act] = filled(*d._act_profile(act))
        for origin in d.config["families_order"]:
            snap["skeletoner/%s" % origin] = filled(
                *d._skeletoner_profile(origin))
            fix_family, fix_model, fix_effort = d._act_profile(
                "fixer", origin, default_family="codex")
            snap["fixer/%s" % origin] = filled(
                fix_family, fix_model, fix_effort)
            snap["reclassifier/%s" % origin] = filled(*d._act_profile(
                "reclassifier", origin_family=origin,
                default_family=d._opposite(origin)))
            snap["delta_review/%s" % origin] = filled(
                *d._delta_review_profile(origin))
            # Consultation: derived family, model from the consulted
            # family's defaults, effort from the calling fixer — compare
            # the fully resolved command line the fixer would run.
            consulted = d._resolve_act("consultation", origin)
            _model, fixer_family_effort = d._family_defaults(fix_family)
            snap["consultation/%s" % origin] = (
                consulted,
                d._consultation_command(
                    consulted, fix_effort or fixer_family_effort),
            )
        for family in d.config["families_order"]:
            snap["review_%s" % family] = (family,) + d._review_profile(
                family)
        lead, counterpart = d._brainstorming_profiles()
        snap["brainstorming_lead"] = (
            lead["agent"], lead["model"], lead["effort"])
        snap["brainstorming_counterpart"] = (
            counterpart["agent"], counterpart["model"], counterpart["effort"])
        return snap

    def test_default_medium_matches_current_effective_staffing(self):
        mp.ensure_default(self.home)
        medium = mp.load(self.home, "default")["configurations"]["medium"]
        with tempfile.TemporaryDirectory(prefix="orch-mp-equiv-") as tmp:
            current = self._driver_with_acts(
                tmp, "current",
                json.loads(json.dumps(driver.DEFAULT_CONFIG["acts"])))
            seeded = self._driver_with_acts(
                tmp, "seeded", json.loads(json.dumps(medium)))
            expected = self._staffing_snapshot(current)
            actual = self._staffing_snapshot(seeded)
        self.assertEqual(actual, expected)
        # The comparison must be over fully resolved staffing — no seat
        # may have been left as a None placeholder on either side.
        for key, value in expected.items():
            if key.startswith("consultation/"):
                family, command = value
                self.assertTrue(family and command, key)
            else:
                self.assertTrue(all(value), key)


if __name__ == "__main__":
    unittest.main()
