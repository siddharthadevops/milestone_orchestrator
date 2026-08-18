"""Store tests for orchestrator/staffing.py (staffing-router slice 2).

Covers the closed staffing-document schema with its completeness rule, the
loud save-time validation that leaves a refused document's predecessor
byte-identical, whole create/replace/list/load behaviour with loud failure
(no silent skip, no partial merge, no case collision), and the total base
lookup that completeness buys.
"""

import copy
import json
import os
import tempfile
import unittest

from orchestrator import staffing as stf

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


if __name__ == "__main__":
    unittest.main()
