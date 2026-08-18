"""Store tests for orchestrator/staffing.py (staffing-router slice 2).

Covers the closed staffing-document schema with its completeness rule, the
loud save-time validation that leaves a refused document's predecessor
byte-identical, whole create/replace/list/load behaviour with loud failure
(no silent skip, no partial merge, no case collision), the total base
lookup that completeness buys, and the one-time missing-only conversion of
stored model profiles — its seat-by-seat equality with today's effective
staffing measured through a real `Driver`, its whole-vocabulary ladders in
the operator's order, and its initialization posture.
"""

import copy
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from orchestrator import brainstorming_milestone, driver
from orchestrator import model_profiles as mp
from orchestrator import runners, staffing as stf, state as st

FAMILIES = {
    "1": {"name": "codex",
          "models": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
          "efforts": ["low", "medium", "high", "xhigh", "max"]},
    "2": {"name": "claude",
          "models": ["claude-sonnet-5", "claude-opus-5", "claude-fable-5"],
          "efforts": ["low", "medium", "high", "xhigh", "max"]},
}


def valid_doc(name="prose-first"):
    """A complete document: nine roles, both slots, all three rigors."""
    assignment = {role: {"1": 1} for role in stf.ROLES}
    assignment["review"] = {"1": 1, "2": 2}
    assignment["brainstorm"] = {"1": 1, "2": 2, "3": 1}
    assignment["consult"] = {"1": 2}
    return {
        "name": name,
        "families": copy.deepcopy(FAMILIES),
        "roles": {
            role: ({"distinct_families": True} if role == "review" else {})
            for role in stf.ROLES
        },
        "materials": {
            "prose": {"examples": ["contracts", "policy documents"]},
        },
        "tuning": {
            rigor: {
                slot: {role: [2, 4] for role in stf.ROLES}
                for slot in ("1", "2")
            }
            for rigor in stf.RIGORS
        },
        "assignment": assignment,
        "overrides": {"prose": {"assignment": {"plan": {"1": 2}}}},
        "rules": [{"type": "step_up", "role": "review", "min_round": 3}],
    }


def mutated(mutate, name="prose-first"):
    doc = valid_doc(name)
    mutate(doc)
    return doc


class StaffingDocumentStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-staffing-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    # -- helpers -----------------------------------------------------------

    def read_file(self, name):
        with open(os.path.join(self.home, stf.STAFFING_DOCUMENTS_DIRNAME,
                               "%s.json" % name), "rb") as fh:
            return fh.read()

    def write_file(self, name, data):
        d = os.path.join(self.home, stf.STAFFING_DOCUMENTS_DIRNAME)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "%s.json" % name), "w",
                  encoding="utf-8") as fh:
            fh.write(data)

    # -- document contract -------------------------------------------------

    def test_document_shape_is_closed_and_complete(self):
        """Every departure from the closed schema is refused BEFORE any byte
        changes, and the previously stored document survives untouched."""
        stf.save(self.home, valid_doc())
        stored = self.read_file("prose-first")

        def drop(*path):
            def _mutate(doc):
                node = doc
                for key in path[:-1]:
                    node = node[key]
                del node[path[-1]]
            return _mutate

        def put(value, *path):
            def _mutate(doc):
                node = doc
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
            return _mutate

        cases = {
            # closed key set, both directions
            "unknown top-level key": put(1, "version"),
            "missing top-level key": drop("rules"),
            "not an object": None,
            # rigors are exactly low/medium/high
            "missing rigor": drop("tuning", "low"),
            "extra rigor": put({}, "tuning", "extreme"),
            # roles are exactly the nine of the closed vocabulary
            "unknown role in roles": put({}, "roles", "refactor"),
            "missing role in roles": drop("roles", "sync"),
            "unknown role in assignment": put({"1": 1}, "assignment",
                                              "refactor"),
            "missing role in assignment": drop("assignment", "sync"),
            "unknown key on a role": put(True, "roles", "plan", "cross"),
            "non-boolean distinct_families": put(
                "yes", "roles", "review", "distinct_families"),
            # completeness: index 1 and every tuning cell
            "role without an index-1 assignment": put(
                {"2": 2}, "assignment", "review"),
            "role with no seat at all": put({}, "assignment", "draft"),
            "missing tuning cell": drop("tuning", "medium", "2", "consult"),
            "missing tuning slot": drop("tuning", "high", "2"),
            "extra tuning slot": put({}, "tuning", "low", "3"),
            "unknown role in a tuning slot": put(
                [1, 1], "tuning", "low", "1", "refactor"),
            # ranks are 1-based positive integers, and only that
            "zero rank": put([0, 4], "tuning", "medium", "1", "plan"),
            "negative rank": put([2, -1], "tuning", "medium", "1", "plan"),
            "fractional rank": put([1.5, 4], "tuning", "medium", "1", "plan"),
            "boolean rank": put([True, 4], "tuning", "medium", "1", "plan"),
            "string rank": put(["2", 4], "tuning", "medium", "1", "plan"),
            "rank triple": put([2, 4, 1], "tuning", "medium", "1", "plan"),
            "rank not a pair": put(2, "tuning", "medium", "1", "plan"),
            # ladders
            "empty models ladder": put([], "families", "1", "models"),
            "empty efforts ladder": put([], "families", "2", "efforts"),
            "repeated rung": put(["max", "max"], "families", "1", "efforts"),
            "blank rung": put(["", "high"], "families", "2", "efforts"),
            "ladder is not an array": put("max", "families", "1", "efforts"),
            # family slots are numbered, and assignment names carried ones
            "no family slot at all": put({}, "families"),
            "unnumbered family slot": put(FAMILIES["1"], "families", "first"),
            "leading-zero family slot": put(FAMILIES["1"], "families", "01"),
            "zero family slot": put(FAMILIES["1"], "families", "0"),
            "unknown key on a family slot": put(
                "api", "families", "1", "billing"),
            "family slot without efforts": drop("families", "2", "efforts"),
            "assignment names a missing slot": put(
                {"1": 3}, "assignment", "plan"),
            "assignment slot is not a number": put(
                {"1": "1"}, "assignment", "plan"),
            "assignment index is not a number": put(
                {"first": 1}, "assignment", "plan"),
            # materials and overrides
            "material without examples": put({}, "materials", "prose"),
            "material with empty examples": put(
                [], "materials", "prose", "examples"),
            "override on an unknown material": put(
                {"assignment": {"plan": {"1": 2}}}, "overrides", "verse"),
            "override with an unknown key": put(
                {"rigor": "high"}, "overrides", "prose"),
            "override that changes nothing": put({}, "overrides", "prose"),
            "override naming an unknown role": put(
                {"assignment": {"refactor": {"1": 2}}}, "overrides", "prose"),
            "override naming a missing slot": put(
                {"assignment": {"plan": {"1": 9}}}, "overrides", "prose"),
            "override tuning naming an unknown rigor": put(
                {"tuning": {"extreme": {"1": {"plan": [1, 1]}}}},
                "overrides", "prose"),
            # typed rules
            "unknown rule type": put(
                [{"type": "step_down", "role": "review", "min_round": 2}],
                "rules"),
            "rule without min_round": put(
                [{"type": "step_up", "role": "review"}], "rules"),
            "rule with an extra field": put(
                [{"type": "step_up", "role": "review", "min_round": 2,
                  "to": "sol"}], "rules"),
            "rule naming an unknown role": put(
                [{"type": "step_up", "role": "refactor", "min_round": 2}],
                "rules"),
            "rule with a zero min_round": put(
                [{"type": "step_up", "role": "review", "min_round": 0}],
                "rules"),
            "rules is not an array": put({}, "rules"),
        }
        for label, mutate in cases.items():
            with self.subTest(refused=label):
                doc = mutated(mutate) if mutate is not None else None
                with self.assertRaises(stf.StaffingError):
                    stf.save(self.home, doc)
                self.assertEqual(self.read_file("prose-first"), stored)

        # A rank BEYOND its ladder stays valid: saturation is resolution's
        # answer, not a save-time refusal.
        beyond = mutated(put([9, 9], "tuning", "medium", "1", "plan"))
        self.assertEqual(
            stf.save(self.home, beyond)["tuning"]["medium"]["1"]["plan"],
            [9, 9])

    def test_a_complete_document_is_accepted_and_normalized(self):
        doc = valid_doc()
        saved = stf.save(self.home, doc)
        self.assertEqual(saved, doc)
        self.assertEqual(stf.load(self.home, "prose-first"), doc)
        # An absent `distinct_families` means false and is not invented on
        # the operator's behalf.
        self.assertEqual(saved["roles"]["plan"], {})
        self.assertTrue(saved["roles"]["review"]["distinct_families"])
        # `validate_document` is the same gate without a store.
        self.assertEqual(stf.validate_document(doc), doc)

    # -- create / replace / list -------------------------------------------

    def test_store_create_replace_list_and_damage(self):
        self.assertEqual(stf.document_names(self.home), [])
        self.assertEqual(stf.list_staffing_documents(self.home), [])
        for name in ("bravo", "alpha", "alpha-ui", "charlie"):
            stf.save(self.home, valid_doc(name))
        self.assertEqual(
            [d["name"] for d in stf.list_staffing_documents(self.home)],
            ["alpha", "alpha-ui", "bravo", "charlie"])

        # A valid same-name save WHOLLY replaces the prior document: nothing
        # of the old definition survives, no key-wise merge.
        v2 = valid_doc("alpha")
        v2["families"] = {"1": copy.deepcopy(FAMILIES["2"])}
        v2["tuning"] = {
            rigor: {"1": {role: [1, 1] for role in stf.ROLES}}
            for rigor in stf.RIGORS
        }
        v2["assignment"] = {role: {"1": 1} for role in stf.ROLES}
        v2["materials"] = {}
        v2["overrides"] = {}
        v2["rules"] = []
        stf.save(self.home, v2)
        loaded = stf.load(self.home, "alpha")
        self.assertEqual(loaded, v2)
        self.assertNotIn("2", loaded["families"])
        self.assertEqual(loaded["materials"], {})
        self.assertEqual(loaded["rules"], [])
        self.assertEqual(loaded["assignment"]["review"], {"1": 1})

        # An invalid replace changes nothing: the prior document stays equal.
        bad = copy.deepcopy(v2)
        del bad["tuning"]["high"]
        with self.assertRaises(stf.StaffingError):
            stf.save(self.home, bad)
        self.assertEqual(stf.load(self.home, "alpha"), v2)

        # Loading an unknown name is loud.
        with self.assertRaises(stf.StaffingError):
            stf.load(self.home, "missing")

        # One damaged stored file makes LISTING fail — never a silently
        # shortened catalogue: broken JSON, a structurally invalid
        # document, and a file whose content names another document.
        good = self.read_file("bravo")
        self.write_file("bravo", "{not json")
        with self.assertRaises(stf.StaffingError):
            stf.load(self.home, "bravo")
        with self.assertRaises(stf.StaffingError):
            stf.list_staffing_documents(self.home)
        self.write_file("bravo", json.dumps({"name": "bravo"}))
        with self.assertRaises(stf.StaffingError):
            stf.list_staffing_documents(self.home)
        # The name is still listed: the catalogue is damaged, not shorter.
        self.assertIn("bravo", stf.document_names(self.home))
        with open(os.path.join(self.home, stf.STAFFING_DOCUMENTS_DIRNAME,
                               "bravo.json"), "wb") as fh:
            fh.write(good)
        self.write_file("charlie", json.dumps(valid_doc("delta")))
        with self.assertRaises(stf.StaffingError):
            stf.list_staffing_documents(self.home)

    def test_case_insensitive_names_are_refused_before_writing(self):
        stf.save(self.home, valid_doc("alpha"))
        with self.assertRaises(stf.StaffingError):
            stf.save(self.home, valid_doc("Alpha"))
        self.assertEqual(stf.document_names(self.home), ["alpha"])
        # The same name in its own spelling still replaces normally.
        stf.save(self.home, valid_doc("alpha"))
        self.assertEqual(stf.document_names(self.home), ["alpha"])

    # -- what completeness buys --------------------------------------------

    def test_base_staffing_is_a_total_lookup_over_a_stored_document(self):
        """Total in completeness's own sense: every cell it reads is there.

        Structural presence — the index-1 assignment and the rigor x slot x
        role pair — not a promise that every valid document answers. A rank
        beyond its ladder is the documented exception, and the next test owns
        it.
        """
        stf.save(self.home, valid_doc())
        doc = stf.load(self.home, "prose-first")
        for rigor in stf.RIGORS:
            for role in stf.ROLES:
                with self.subTest(rigor=rigor, role=role):
                    family, model, effort = stf.base_staffing(
                        doc, rigor, role)
                    self.assertTrue(family and model and effort)
        # The numbers select: [2, 4] on slot 1 is the second model and the
        # fourth effort of THAT slot's ladders.
        self.assertEqual(
            stf.base_staffing(doc, "medium", "plan"),
            ("codex", "gpt-5.6-terra", "xhigh"))
        # Seats beyond index 1 read their own slot.
        self.assertEqual(
            stf.base_staffing(doc, "medium", "review", 2),
            ("claude", "claude-opus-5", "xhigh"))
        self.assertEqual(
            stf.base_staffing(doc, "low", "consult"),
            ("claude", "claude-opus-5", "xhigh"))
        # No fallback here: collapse and the missing-seat rule belong to
        # resolution, so an unassigned seat is an error at this level.
        with self.assertRaises(stf.StaffingError):
            stf.base_staffing(doc, "medium", "review", 3)
        with self.assertRaises(stf.StaffingError):
            stf.base_staffing(doc, "extreme", "plan")
        with self.assertRaises(stf.StaffingError):
            stf.base_staffing(doc, "medium", "refactor")

    def test_a_saturated_rank_is_refused_in_this_modules_own_error(self):
        """A rank beyond its ladder saves, loads, and refuses to be read.

        Both halves matter: the document stays valid — saturation is
        resolution's answer, not a save-time refusal — and the lookup that
        cannot answer it says so in `StaffingError` instead of leaking an
        `IndexError` from a ladder index.
        """
        doc = valid_doc("saturated")
        doc["tuning"]["medium"]["1"]["plan"] = [9, 1]
        doc["tuning"]["high"]["1"]["draft"] = [1, 9]
        stf.save(self.home, doc)
        stored = stf.load(self.home, "saturated")
        self.assertEqual(stored["tuning"]["medium"]["1"]["plan"], [9, 1])

        for rigor, role, ladder in (
            ("medium", "plan", "model"),
            ("high", "draft", "effort"),
        ):
            with self.subTest(rigor=rigor, role=role):
                with self.assertRaises(stf.StaffingError) as caught:
                    stf.base_staffing(stored, rigor, role)
                message = str(caught.exception)
                # The refusal names the cell and the rank, so the operator
                # can find the seat he over-tuned without a stack trace.
                self.assertIn("'saturated'", message)
                self.assertIn("%s.1.%s" % (rigor, role), message)
                self.assertIn("%s rank 9" % ladder, message)

        # Only the saturated cell refuses; the rest of the document still
        # answers, so one over-tuned seat does not cost the whole catalogue.
        self.assertEqual(
            stf.base_staffing(stored, "medium", "draft"),
            ("codex", "gpt-5.6-terra", "xhigh"))
        self.assertEqual(
            stf.base_staffing(stored, "low", "plan"),
            ("codex", "gpt-5.6-terra", "xhigh"))


# ---------------------------------------------------------------------------
# Conversion: the profile shapes that exist
#
# Conversion is proven against the profiles that exist rather than invented
# ones: the profile store's own seeded `default`, and the two shapes this
# machine stores. Each carries a configuration the others do not, and each
# has already been the specific place a naive conversion goes wrong.


def stored_default_shaped(name="stored-default"):
    """A profile shaped like this machine's stored `default`.

    Its plan, draft, implement and fix acts all sit on the FIRST configured
    family — where the in-code seed puts plan and implement on the second —
    it pins a `brainstorming_counterpart` effort the seed pins at no rigor,
    and at exactly one rigor it pins the counterpart MODEL: the one seat
    whose model a profile may pin and no profile stored here pins.
    """
    return {
        "name": name,
        "examples": ["any ordinary work"],
        "configurations": {
            "low": {
                "skeletoner": {"agent": "codex", "model": "gpt-5.6-terra",
                               "effort": "high"},
                "drafter": {"agent": "codex", "effort": "medium"},
                "implementer": {"agent": "codex", "model": "gpt-5.6-terra",
                                "effort": "high"},
                "fixer": {"agent": "codex", "effort": "medium"},
                "review_codex": {"effort": "medium"},
                "review_claude": {"model": "claude-sonnet-5",
                                  "effort": "medium"},
                "brainstorming_counterpart": {"effort": "high"},
                "consultation": "opposite",
                "reclassifier": {"agent": "codex", "effort": "medium"},
            },
            "medium": {
                "skeletoner": {"agent": "codex", "model": "gpt-5.6-sol",
                               "effort": "max"},
                "drafter": {"agent": "codex", "effort": "xhigh"},
                "implementer": {"agent": "codex", "model": "gpt-5.6-sol",
                                "effort": "max"},
                "fixer": "codex",
                # The counterpart model — pinned here and nowhere else.
                "brainstorming_counterpart": {"model": "claude-fable-5",
                                              "effort": "max"},
                "consultation": "opposite",
                "reclassifier": {"agent": "codex", "effort": "xhigh"},
            },
            "high": {
                "skeletoner": {"agent": "codex", "model": "gpt-5.6-sol",
                               "effort": "max"},
                "drafter": {"agent": "codex", "effort": "max"},
                "implementer": {"agent": "codex", "model": "gpt-5.6-sol",
                                "effort": "max"},
                "fixer": {"agent": "codex", "effort": "max"},
                "review_codex": {"effort": "max"},
                "review_claude": {"effort": "max"},
                "brainstorming_counterpart": {"effort": "max"},
                "consultation": "opposite",
                "reclassifier": {"agent": "codex", "effort": "max"},
            },
        },
    }


def claude_lead_shaped(name="claude-lead"):
    """A profile shaped like this machine's `claude-lead`.

    Its `medium` fixer sits on the SECOND configured family, which is the
    one configuration where a naive conversion of `consult 1` — resolving
    the consultation policy with no origin instead of with the converted
    fixer's family — picks the wrong family.
    """
    return {
        "name": name,
        "examples": ["claude led implementation"],
        "configurations": {
            "low": {
                "skeletoner": {"agent": "claude", "model": "claude-sonnet-5",
                               "effort": "medium"},
                "drafter": {"agent": "claude", "effort": "medium"},
                "implementer": {"agent": "claude", "model": "claude-sonnet-5",
                                "effort": "medium"},
                "fixer": {"agent": "claude", "effort": "medium"},
                "review_codex": {"effort": "medium"},
                "review_claude": {"effort": "medium"},
                "consultation": "opposite",
                "reclassifier": {"agent": "codex", "effort": "medium"},
            },
            "medium": {
                "skeletoner": {"agent": "claude", "model": "claude-fable-5",
                               "effort": "max"},
                "drafter": {"agent": "claude", "effort": "xhigh"},
                "implementer": {"agent": "claude", "model": "claude-fable-5",
                                "effort": "max"},
                "fixer": {"agent": "claude", "effort": "xhigh"},
                "consultation": "opposite",
                "reclassifier": {"agent": "codex", "effort": "xhigh"},
            },
            "high": {
                "skeletoner": {"agent": "claude", "model": "claude-fable-5",
                               "effort": "max"},
                "drafter": {"agent": "claude", "effort": "max"},
                "implementer": {"agent": "claude", "model": "claude-fable-5",
                                "effort": "max"},
                "fixer": {"agent": "claude", "effort": "max"},
                "review_codex": {"effort": "max"},
                "review_claude": {"effort": "max"},
                "consultation": "opposite",
                "reclassifier": {"agent": "codex", "effort": "max"},
            },
        },
    }


class StaffingConversionTest(unittest.TestCase):
    """The conversion, measured against today rather than against itself."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-staffing-conv-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.config = driver.load_config(None)

    # -- the comparison surface --------------------------------------------

    def _driver_for(self, label, profile_name, rigor):
        """A real `Driver` over the SHIPPED configuration, resolving through
        the production current-state path: the profile lives in the store and
        the run's selection sidecar names it at *rigor*, so every seat below
        is measured by the same seams a dispatch uses."""
        workspace = os.path.join(self.home, "ws-%s" % label)
        os.makedirs(workspace)
        state_path = driver.default_state_path(workspace)
        st.save(state_path,
                st.new_state("staffing conversion probe", workspace,
                             driver.load_config(None)))
        with open(os.path.join(os.path.dirname(state_path),
                               "model_profile.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"name": profile_name, "rigor": rigor}, fh)
        return driver.Driver(state_path, runner=runners.MockRunner([]),
                             model_profiles_home=self.home)

    @staticmethod
    def _today(d):
        """Today's effective staffing for every Conversion Reference seat.

        Each entry is read from the seam that actually staffs that seat, with
        model and effort filled exactly as its dispatch fills them — never
        re-derived from the shipped configuration by this test.
        """

        def filled(family, model, effort):
            default_model, default_effort = d._family_defaults(family)
            return (family, model or default_model, effort or default_effort)

        families = d.config["families_order"]
        seats = {}
        seats[("plan", 1)] = filled(*d._skeletoner_profile())
        seats[("draft", 1)] = filled(*d._act_profile("drafter"))
        seats[("implement", 1)] = filled(*d._act_profile("implementer"))
        fix_family, fix_model, fix_effort = d._act_profile(
            "fixer", default_family="codex")
        seats[("fix", 1)] = filled(fix_family, fix_model, fix_effort)
        seats[("classify", 1)] = filled(*d._act_profile("reclassifier"))
        for index, family in enumerate(families, start=1):
            seats[("review", index)] = (family,) + d._review_profile(family)
        # The three Brainstorming seats through the adapter that pins them,
        # so Dante's copy of the lead is measured and not assumed.
        lead, counterpart = d._brainstorming_profiles()
        for index, participant in enumerate(
                brainstorming_milestone._participants(lead, counterpart),
                start=1):
            seats[("brainstorm", index)] = (
                participant["model_family"], participant["model"],
                participant["effort"])
        consulted = d._resolve_act("consultation", fix_family)
        _consulted_model, _e = d._family_defaults(consulted)
        _m, fix_family_effort = d._family_defaults(fix_family)
        seats[("consult", 1)] = (
            consulted, _consulted_model, fix_effort or fix_family_effort)
        # git alignment reads no profile act: the first configured family.
        seats[("sync", 1)] = (families[0],) + d._family_defaults(families[0])
        return seats

    def _assert_reproduces_today(self, label, profile, document):
        for rigor in stf.RIGORS:
            d = self._driver_for("%s-%s" % (label, rigor),
                                 profile["name"], rigor)
            expected = self._today(d)
            for seat, today in sorted(expected.items()):
                role, index = seat
                with self.subTest(profile=label, rigor=rigor, seat=seat):
                    actual = stf.base_staffing(document, rigor, role, index)
                    self.assertEqual(actual, today)
                    # Nothing may pass as a None placeholder on either side.
                    self.assertTrue(all(today), today)
                    self.assertTrue(all(actual), actual)
            # The document assigns exactly the seats the reference names —
            # no invented seat, none quietly dropped.
            assigned = {
                (role, int(index))
                for role in stf.ROLES
                for index in document["assignment"][role]
            }
            self.assertEqual(assigned, set(expected))
            # End to end for the one derived command line: the consultation
            # is a COMMAND and not just a triple, so the document's seat is
            # compared as the line it produces. The reference is the same
            # profile-side one every other seat above uses — the command the
            # fixer runs is router-backed after slice 4, and measuring the
            # document against it would compare the document with itself.
            family, model, effort = stf.base_staffing(
                document, rigor, "consult")
            reference = expected[("consult", 1)]
            self.assertEqual(
                runners.apply_model_effort(
                    d.config["commands"][family], model, effort),
                runners.apply_model_effort(
                    d.config["commands"][reference[0]],
                    reference[1], reference[2]))

    # -- the drift alarm ---------------------------------------------------

    def test_conversion_matches_current_effective_staffing(self):
        """Seat by seat, at every rigor, for every profile shape that exists.

        A wrong reference for one seat is invisible until a real call runs at
        the wrong family, and conversion is missing-only, so a wrong document
        is never corrected by a later start. This is the guard, and it
        measures today through the resolution seams rather than re-deriving
        them.
        """
        # The in-code seed IS the conversion of the profile store's own
        # `default` seed — one definition of today's staffing, which cannot
        # disagree with itself.
        self.assertEqual(stf.default_document_seed(),
                         stf.convert_profile(mp.DEFAULT_SEED))

        shapes = [
            ("seeded-default", copy.deepcopy(mp.DEFAULT_SEED)),
            ("stored-default", stored_default_shaped()),
            ("claude-lead", claude_lead_shaped()),
        ]
        for label, profile in shapes:
            mp.save(self.home, copy.deepcopy(profile))
        for label, profile in shapes:
            document = (stf.default_document_seed()
                        if label == "seeded-default"
                        else stf.convert_profile(profile))
            with self.subTest(profile=label):
                self._assert_reproduces_today(label, profile, document)

    def test_second_family_fixer_seats_consult_on_its_opposite(self):
        """The one seat a naive conversion gets wrong.

        With the fixer on the SECOND configured family, the consultation's
        `opposite` policy must be applied to that fixer's family — giving the
        first family — and not to the no-origin fallback, which would hand
        the consultation back to the fixer's own family.
        """
        profile = claude_lead_shaped()
        mp.save(self.home, copy.deepcopy(profile))
        document = stf.convert_profile(profile)

        families = self.config["families_order"]
        fixer_family = stf.base_staffing(document, "medium", "fix")[0]
        self.assertEqual(fixer_family, families[1])

        consult_family = stf.base_staffing(document, "medium", "consult")[0]
        self.assertEqual(consult_family, families[0])

        # What the no-origin fallback would have produced, computed through
        # the same seam: it lands on the fixer's own family, which is not a
        # second opinion at all.
        naive = driver._resolve_act_from_layers(
            self.config, True, {},
            profile["configurations"]["medium"], "consultation")[0]
        self.assertEqual(naive, fixer_family)
        self.assertNotEqual(consult_family, naive)

    # -- ladders -----------------------------------------------------------

    @staticmethod
    def _panel_lists(panel, name):
        """The panel's per-family vocabulary, read statically."""
        block = panel.split("const %s = {" % name, 1)[1].split("};", 1)[0]
        return {
            family: re.findall(r'"([^"]+)"', body)
            for family, body in re.findall(r"(\w+):\s*\[([^\]]*)\]", block)
        }

    def test_ladders_are_whole_vocabulary_in_operator_order(self):
        """Amendment A1's order, and the whole vocabulary whatever was used.

        The panel lists models strongest-first for display; copied verbatim
        they would invert the operator's order and make `step_up` climb
        downwards. The order is asserted explicitly, and the vocabulary
        agreement with the panel is asserted separately.
        """
        expected_models = {
            "codex": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
            "claude": ["claude-sonnet-5", "claude-opus-5", "claude-fable-5"],
        }
        expected_efforts = ["low", "medium", "high", "xhigh", "max"]

        # A profile that names ONE model and ONE effort per family still
        # converts to the whole vocabulary: `step_up` needs rungs above
        # today's choice to climb into.
        frugal = claude_lead_shaped("frugal")
        for rigor in mp.RIGORS:
            frugal["configurations"][rigor] = {
                "implementer": {"agent": "claude",
                                "model": "claude-sonnet-5",
                                "effort": "low"},
                "fixer": {"agent": "codex", "effort": "low"},
            }
        documents = [stf.default_document_seed(),
                     stf.convert_profile(frugal),
                     stf.convert_profile(stored_default_shaped())]
        for document in documents:
            for slot in document["families"]:
                family = document["families"][slot]["name"]
                with self.subTest(document=document["name"], family=family):
                    self.assertEqual(document["families"][slot]["models"],
                                     expected_models[family])
                    self.assertEqual(document["families"][slot]["efforts"],
                                     expected_efforts)

        # The same models and efforts the panel offers for that family —
        # a static agreement check, not a new sharing mechanism.
        panel = (
            Path(__file__).resolve().parents[1] / "static" / "panel.html"
        ).read_text(encoding="utf-8")
        panel_models = self._panel_lists(panel, "MODEL_OPTS")
        panel_efforts = self._panel_lists(panel, "EFFORT_OPTS")
        self.assertEqual(set(panel_models), set(expected_models))
        for family, models in expected_models.items():
            with self.subTest(family=family):
                self.assertEqual(set(panel_models[family]), set(models))
                self.assertEqual(set(panel_efforts[family]),
                                 set(expected_efforts))

    def test_unknown_values_append_after_the_known_rungs(self):
        """A model or effort outside the family's vocabulary is kept.

        The profile store applies no vocabulary whitelist, so a profile may
        name anything. Conversion appends it AFTER the known rungs, so the
        converted staffing still reproduces exactly and A1's order of the
        named models is untouched.
        """
        profile = claude_lead_shaped("exotic")
        profile["configurations"]["medium"]["implementer"] = {
            "agent": "claude", "model": "claude-nova-9", "effort": "extreme"}
        document = stf.convert_profile(profile)
        slot = next(s for s, f in document["families"].items()
                    if f["name"] == "claude")
        self.assertEqual(
            document["families"][slot]["models"],
            ["claude-sonnet-5", "claude-opus-5", "claude-fable-5",
             "claude-nova-9"])
        self.assertEqual(
            document["families"][slot]["efforts"],
            ["low", "medium", "high", "xhigh", "max", "extreme"])
        self.assertEqual(
            stf.base_staffing(document, "medium", "implement"),
            ("claude", "claude-nova-9", "extreme"))

    def test_a_seat_on_a_family_with_no_slot_takes_slot_one(self):
        """A profile that cannot run today either does not fail conversion.

        It seats on slot 1 and the half it leaves unsaid is TUNED there
        like any cell nothing staffs: the configuration holds no model and
        no effort for a family it does not have, so slot 1's ordinary
        defaults fill that half — while a value the seat does name stays its
        own. Rung 1 would pin the weakest model and the lowest effort —
        under amendment A1 an explicit choice, and one this profile never
        made.
        """
        first = self.config["families_order"][0]
        defaults = self.config["model_defaults"][first]
        profile = claude_lead_shaped("stranger")
        profile["configurations"]["medium"]["drafter"] = {"agent": "gemini"}
        document = stf.convert_profile(profile)
        self.assertEqual(document["assignment"]["draft"]["1"], 1)
        self.assertEqual(
            stf.base_staffing(document, "medium", "draft"),
            (first, defaults["model"], defaults["effort"]))

        # Only the half the seat leaves unsaid falls back: a value it does
        # name is still its own.
        profile["configurations"]["medium"]["drafter"] = {
            "agent": "gemini", "effort": "max"}
        document = stf.convert_profile(profile)
        self.assertEqual(
            stf.base_staffing(document, "medium", "draft"),
            (first, defaults["model"], "max"))

    def test_a_derived_seat_follows_the_slot_its_origin_converts_onto(self):
        """A seat derived from another seat is derived from the CONVERTED one.

        `brainstorm 2` is opposite `brainstorm 1`'s family and `consult 1`
        applies the `consultation` policy to the `fix 1` family. When the
        origin seat names a family the configuration has no slot for it
        converts onto slot 1, so the seat derived from it must take slot 1's
        opposite. Deriving from the raw family instead picks the first
        configured family — which is slot 1 — and collapses both seats onto
        the one slot, leaving the Contrary Position and the consultation on
        the very family they exist to argue with.
        """
        first, second = self.config["families_order"][:2]
        profile = claude_lead_shaped("stranger-origins")
        for rigor in stf.RIGORS:
            profile["configurations"][rigor]["implementer"] = "gemini"
            profile["configurations"][rigor]["fixer"] = "gemini"
            profile["configurations"][rigor]["consultation"] = "opposite"
        document = stf.convert_profile(profile)

        # Both origins converted onto slot 1, as a family with no slot does.
        self.assertEqual(document["assignment"]["brainstorm"]["1"], 1)
        self.assertEqual(document["assignment"]["fix"]["1"], 1)
        self.assertEqual(stf.base_staffing(document, "medium", "fix")[0],
                         first)

        # And each derived seat took slot 1's opposite, not slot 1 again.
        self.assertEqual(document["assignment"]["brainstorm"]["2"], 2)
        self.assertEqual(document["assignment"]["consult"]["1"], 2)
        self.assertEqual(
            stf.base_staffing(document, "medium", "brainstorm", 2)[0], second)
        self.assertEqual(
            stf.base_staffing(document, "medium", "consult")[0], second)

        # A `self` policy stays on the converted fixer rather than following
        # the raw family into nothing.
        for rigor in stf.RIGORS:
            profile["configurations"][rigor]["consultation"] = "self"
        document = stf.convert_profile(profile)
        self.assertEqual(document["assignment"]["consult"]["1"], 1)
        self.assertEqual(
            stf.base_staffing(document, "medium", "consult")[0], first)

    def test_conversion_writes_no_materials_overrides_or_rules(self):
        """A profile carries nothing that maps to them."""
        for document in (stf.default_document_seed(),
                         stf.convert_profile(claude_lead_shaped())):
            self.assertEqual(document["materials"], {})
            self.assertEqual(document["overrides"], {})
            self.assertEqual(document["rules"], [])
            self.assertEqual(
                {role for role, entry in document["roles"].items()
                 if entry.get("distinct_families")},
                {"review"})

    # -- initialization ----------------------------------------------------

    @staticmethod
    def _file_bytes(path):
        with open(path, "rb") as fh:
            return fh.read()

    def _document_bytes(self, name):
        return self._file_bytes(
            os.path.join(stf.staffing_documents_dir(self.home),
                         "%s.json" % name))

    def _profile_bytes(self):
        directory = mp.model_profiles_dir(self.home)
        return {
            name: self._file_bytes(os.path.join(directory, name))
            for name in sorted(os.listdir(directory))
        }

    def test_initialization_is_missing_only_and_reads_profiles(self):
        """A second start reverts no edit and rewrites no profile."""
        mp.ensure_default(self.home)
        mp.save(self.home, claude_lead_shaped())
        stf.ensure_documents(self.home)
        self.assertEqual(stf.document_names(self.home),
                         ["claude-lead", "default"])
        # What initialization stored IS the conversion, not a variant of it.
        self.assertEqual(stf.load(self.home, "claude-lead"),
                         stf.convert_profile(claude_lead_shaped()))

        # The operator edits a converted document, and a profile appears
        # between the two initializations.
        edited = stf.load(self.home, "claude-lead")
        edited["tuning"]["medium"]["1"]["fix"] = [1, 1]
        edited["rules"] = [{"type": "step_up", "role": "review",
                            "min_round": 2}]
        stf.save(self.home, edited)
        edited_bytes = self._document_bytes("claude-lead")
        default_bytes = self._document_bytes("default")
        mp.save(self.home, stored_default_shaped("late-arrival"))
        before = self._profile_bytes()

        written = stf.ensure_documents(self.home)

        # Missing-only: the edit survives and `default` is not re-seeded.
        self.assertEqual(written, ["late-arrival"])
        self.assertEqual(self._document_bytes("claude-lead"), edited_bytes)
        self.assertEqual(self._document_bytes("default"), default_bytes)
        # The profile created in between is converted at the second start.
        self.assertEqual(stf.load(self.home, "late-arrival"),
                         stf.convert_profile(
                             stored_default_shaped("late-arrival")))
        # Profile files are only READ: never edited, moved, or deleted.
        self.assertEqual(self._profile_bytes(), before)

    def test_a_stored_default_is_never_seeded_over(self):
        """The `default` floor sources the stored profile, not the seed."""
        stored = stored_default_shaped("default")
        mp.save(self.home, stored)
        stf.ensure_documents(self.home)
        self.assertEqual(stf.load(self.home, "default"),
                         stf.convert_profile(stored))
        self.assertNotEqual(stf.load(self.home, "default"),
                            stf.default_document_seed())

    def test_damaged_profile_is_skipped(self):
        """Start-up never gets louder than it is today for one bad profile."""
        mp.ensure_default(self.home)
        mp.save(self.home, claude_lead_shaped())
        directory = mp.model_profiles_dir(self.home)
        with open(os.path.join(directory, "corrupt.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{not json")
        with open(os.path.join(directory, "incomplete.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"name": "incomplete"}, fh)
        # Unreadable rather than malformed: a dangling symlink.
        os.symlink(os.path.join(self.home, "gone"),
                   os.path.join(directory, "vanished.json"))

        written = stf.ensure_documents(self.home)

        self.assertEqual(written, ["claude-lead", "default"])
        self.assertEqual(stf.document_names(self.home),
                         ["claude-lead", "default"])
        # And the `default` floor still holds.
        self.assertEqual(stf.load(self.home, "default")["name"], "default")

    def test_a_damaged_default_document_is_not_the_floor(self):
        """A floor that cannot be loaded is not the guarantee.

        The stored `default` is the one entry initialization must leave
        usable, so its filename does not stand in for it: a damaged one is
        neither accepted nor healed — healing would revert an operator's own
        document and conversion is no repair step — and initialization fails
        loudly, exactly as an invalid stored `default` profile makes
        `model_profiles.ensure_default` fail at the same moment.
        """
        mp.ensure_default(self.home)
        stf.ensure_documents(self.home)
        path = os.path.join(stf.staffing_documents_dir(self.home),
                            "default.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        damaged = self._file_bytes(path)

        with self.assertRaises(stf.StaffingError) as caught:
            stf.ensure_documents(self.home)

        self.assertIn("default", str(caught.exception))
        # Refused, not repaired: the operator's own bytes are untouched.
        self.assertEqual(self._file_bytes(path), damaged)
        # The damage stays loud through the catalogue too, for the store's
        # own reason: a damaged catalogue never looks shorter. The only
        # document here IS the floor; an ordinary damaged document's loud
        # listing is test_store_create_replace_list_and_damage.
        with self.assertRaises(stf.StaffingError):
            stf.list_staffing_documents(self.home)

    def test_a_case_variant_default_cannot_pass_for_the_floor(self):
        """`Default` is a name the catalogue owns and no consumer can load.

        Names are case-insensitively unique, so seeding `default` beside it
        is refused; loading `default` does not yield it either. Initialization
        says so instead of returning as though the floor existed.
        """
        variant = stf.default_document_seed()
        variant["name"] = "Default"
        stf.save(self.home, variant)

        with self.assertRaises(stf.StaffingError):
            stf.ensure_documents(self.home)

        self.assertEqual(stf.document_names(self.home), ["Default"])

    def _fresh_home(self, label):
        directory = tempfile.TemporaryDirectory(prefix="orch-staffing-%s-"
                                                % label)
        self.addCleanup(directory.cleanup)
        return directory.name

    def test_initialization_runs_at_the_three_catalogue_sites(self):
        """The catalogue initializes wherever the profile seed already does:
        driver start-up readiness, run creation, and service start-up."""
        mp.save(self.home, claude_lead_shaped())
        self._driver_for("startup", "claude-lead", "medium")
        self.assertEqual(stf.document_names(self.home),
                         ["claude-lead", "default"])

        creation_home = self._fresh_home("create")
        mp.save(creation_home, claude_lead_shaped())
        driver.init_run(
            "staffing catalogue at run creation",
            os.path.join(creation_home, "ws"),
            config=driver.load_config(None),
            model_profiles_home=creation_home,
            creation_acts=None,
        )
        self.assertEqual(stf.document_names(creation_home),
                         ["claude-lead", "default"])

        service_home = self._fresh_home("serve")
        from orchestrator import service
        server = service.make_server(service_home, 0)
        try:
            self.assertEqual(stf.document_names(service_home), ["default"])
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
