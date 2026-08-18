"""Session tests for orchestrator/staffing.py (staffing-router slice 3).

Covers the closed session record — the five facts an owner supplies, the two
optional selections, and the session override in the document's own inner
shape validated for shape ALONE — the loud save-time validation that leaves a
refused edit's predecessor byte-identical, and the store's whole create /
read / edit behaviour with its assigned id, its four editable fields and its
last-write-wins saves.

Nothing here staffs a call: the resolver that reads a session is the second
half of this slice, and every dispatch still reads model profiles.
"""

import copy
import json
import os
import tempfile
import unittest

from orchestrator import staffing as stf
from orchestrator import workareas

# More decimal digits than CPython converts between `int` and `str`.
LONG_INDEX_KEY = "1" + "0" * 5000


def session_body(**changes):
    """The body an owner posts: everything but the store-assigned id."""
    body = {
        "work_area": {"project": "orchestrators",
                      "work_area": "implementation"},
        "families": ["codex", "claude"],
        "document": "prose-first",
        "rigor": "medium",
    }
    body.update(changes)
    return body


def mutated_body(mutate):
    body = session_body()
    mutate(body)
    return body


class StaffingSessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-staffing-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    # -- helpers -----------------------------------------------------------

    def read_file(self, session_id):
        with open(os.path.join(self.home, stf.STAFFING_SESSIONS_DIRNAME,
                               "%s.json" % session_id), "rb") as fh:
            return fh.read()

    def session_files(self):
        d = os.path.join(self.home, stf.STAFFING_SESSIONS_DIRNAME)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    # -- the record contract -----------------------------------------------

    def test_session_shape_is_closed_and_write_is_loud(self):
        """Every departure from the closed shape is refused BEFORE any byte
        changes, on create and on edit alike, and the stored session
        survives byte-identical."""
        record = stf.create_session(self.home, session_body())
        stored = self.read_file(record["id"])

        def put(value, *path):
            def _mutate(body):
                node = body
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
            return _mutate

        def drop(*path):
            def _mutate(body):
                node = body
                for key in path[:-1]:
                    node = node[key]
                del node[path[-1]]
            return _mutate

        override = {"assignment": {"fix": {"1": 2}}}
        cases = {
            # closed key set, both directions
            "unknown key": put("bs-1", "run"),
            "missing work_area": drop("work_area"),
            "missing families": drop("families"),
            "missing document": drop("document"),
            "missing rigor": drop("rigor"),
            "not an object": None,
            # the id is the store's, never a caller's
            "caller-supplied id": put("stf-mine", "id"),
            # rigor is exactly low/medium/high
            "unknown rigor": put("extreme", "rigor"),
            "rigor as a number": put(1, "rigor"),
            # the document is a NAME reference and a filename with it
            "document with a separator": put("../default", "document"),
            "empty document": put("", "document"),
            "document as an object": put({"name": "default"}, "document"),
            # work area handles: refused exactly where the store that owns
            # them refuses, never by a catalogue rule of this module's own
            "unknown handle": put("/tmp/x", "work_area", "root"),
            "project without its work area": drop("work_area", "work_area"),
            "work area without its project": drop("work_area", "project"),
            "no handle at all": put({}, "work_area"),
            "work area name with a separator": put(
                "impl/here", "work_area", "work_area"),
            "work area name with a control character": put(
                "impl\there", "work_area", "work_area"),
            "work area name past its byte cap": put(
                "a" * (workareas.MAX_NAME_BYTES + 1), "work_area",
                "work_area"),
            "blank work area name": put("   ", "work_area", "work_area"),
            "work area name as a number": put(1, "work_area", "work_area"),
            "project that is a path segment": put(
                "..", "work_area", "project"),
            "blank workspace_path": put("  ", "work_area", "workspace_path"),
            "path with a NUL": put("/tmp/a\x00b", "work_area",
                                   "workspace_path"),
            # families is a list of names
            "families as an object": put({"1": "codex"}, "families"),
            "family name as a number": put([1], "families"),
            # the material is one short word of the owner's vocabulary
            "material as a list": put(["prose"], "material"),
            "empty material": put("", "material"),
            # the override is the document's inner shape, at least one half
            "empty override": put({}, "overrides"),
            "override with an unknown key": put(
                dict(override, rules=[]), "overrides"),
            "override on an unknown role": put(
                {"assignment": {"refactor": {"1": 2}}}, "overrides"),
            "override assigning no role": put({"assignment": {}},
                                              "overrides"),
            "override index key with a leading zero": put(
                {"assignment": {"fix": {"01": 2}}}, "overrides"),
            "override index key that is not a number": put(
                {"assignment": {"fix": {"first": 2}}}, "overrides"),
            "override index key past the number limit": put(
                {"assignment": {"fix": {LONG_INDEX_KEY: 2}}}, "overrides"),
            "override tuning slot past the number limit": put(
                {"tuning": {"low": {LONG_INDEX_KEY: {"fix": [1, 2]}}}},
                "overrides"),
            "override slot at zero": put(
                {"assignment": {"fix": {"1": 0}}}, "overrides"),
            "override slot as a boolean": put(
                {"assignment": {"fix": {"1": True}}}, "overrides"),
            "override tuning on an unknown rigor": put(
                {"tuning": {"extreme": {"1": {"fix": [1, 2]}}}}, "overrides"),
            "override tuning naming no rigor": put({"tuning": {}},
                                                   "overrides"),
            "override tuning rank at zero": put(
                {"tuning": {"low": {"1": {"fix": [0, 2]}}}}, "overrides"),
            "override tuning as a triple": put(
                {"tuning": {"low": {"1": {"fix": [1, 2, 3]}}}}, "overrides"),
            "override tuning on an unknown role": put(
                {"tuning": {"low": {"1": {"refactor": [1, 2]}}}},
                "overrides"),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                body = mutated_body(mutate) if mutate else ["not", "a", "dict"]
                with self.assertRaises(stf.StaffingError):
                    stf.create_session(self.home, body)
                # A malformed value in one of the four editable fields is
                # refused on the way in through an edit as well.
                baseline = session_body()
                edit = {key: body[key]
                        for key in stf.SESSION_EDITABLE_FIELDS
                        if isinstance(body, dict) and key in body
                        and body[key] != baseline.get(key)}
                if edit:
                    with self.assertRaises(stf.StaffingError):
                        stf.edit_session(self.home, record["id"], edit)
        # One session, unchanged: not one refusal wrote a byte.
        self.assertEqual(self.session_files(), ["%s.json" % record["id"]])
        self.assertEqual(self.read_file(record["id"]), stored)

        # And every handle the owner's own store accepts is recorded
        # EXACTLY as given: surrounding space is part of a name there, so
        # trimming or shortening one here would file the session under a
        # different work area than the one its owner named.
        for handle in (" alpha ", "a" * workareas.MAX_NAME_BYTES):
            with self.subTest(handle=handle):
                self.assertEqual(workareas.validate_name(handle), handle)
                kept = stf.create_session(self.home, session_body(
                    work_area={"project": handle, "work_area": handle}))
                self.assertEqual(kept["work_area"],
                                 {"project": handle, "work_area": handle})
                self.assertEqual(
                    stf.read_session(self.home, kept["id"]), kept)

    def test_an_empty_families_list_is_stored_as_the_machine_fact_it_is(self):
        """Nobody to call is a fact about the machine, not a bad record.

        Refusing it at save would make a session unopenable on a machine
        whose families are configured afterwards; the request that has
        nobody to call is the moment that surfaces, in the resolver.
        """
        record = stf.create_session(self.home, session_body(families=[]))
        self.assertEqual(record["families"], [])
        self.assertEqual(stf.read_session(self.home, record["id"]), record)

    def test_a_session_override_is_not_validated_against_its_document(self):
        """Shape only: the document is a live reference.

        A slot no document carries, and a document that does not exist at
        all, both save — the first collapses at resolution and the second
        is the mandatory fallback's business. Validating here would refuse a
        session for the state of a document that may be edited, replaced or
        created between this save and the next call.
        """
        self.assertEqual(stf.document_names(self.home), [])
        record = stf.create_session(self.home, session_body(
            document="never-written",
            overrides={"assignment": {"fix": {"1": 97}},
                       "tuning": {"high": {"97": {"fix": [40, 40]}}}},
        ))
        self.assertEqual(record["document"], "never-written")
        self.assertEqual(record["overrides"]["assignment"]["fix"], {"1": 97})
        self.assertEqual(
            record["overrides"]["tuning"]["high"]["97"]["fix"], [40, 40])

    # -- the store ---------------------------------------------------------

    def test_session_store_creates_reads_and_edits(self):
        """Create assigns the id, read gives it back, edit moves exactly the
        four editable fields, and two saves are last-write-wins."""
        record = stf.create_session(self.home, session_body(material="prose"))
        self.assertTrue(record["id"].startswith("stf-"))
        self.assertEqual(stf.read_session(self.home, record["id"]), record)
        self.assertEqual(sorted(record), [
            "document", "families", "id", "material", "rigor", "work_area"])
        # Two sessions of one owner are two records, never one.
        other = stf.create_session(self.home, session_body())
        self.assertNotEqual(other["id"], record["id"])
        self.assertEqual(len(self.session_files()), 2)

        # The four editable fields move, one at a time and together.
        edited = stf.edit_session(self.home, record["id"], {
            "document": "default",
            "rigor": "high",
            "material": "code",
            "overrides": {"assignment": {"fix": {"1": 2}}},
        })
        self.assertEqual(edited["document"], "default")
        self.assertEqual(edited["rigor"], "high")
        self.assertEqual(edited["material"], "code")
        self.assertEqual(edited["overrides"], {"assignment": {"fix": {"1": 2}}})
        # An untouched field keeps its value; the facts are still the facts.
        self.assertEqual(edited["work_area"], record["work_area"])
        self.assertEqual(edited["families"], record["families"])
        self.assertEqual(edited["id"], record["id"])
        self.assertEqual(stf.read_session(self.home, record["id"]), edited)
        # The other session did not move.
        self.assertEqual(stf.read_session(self.home, other["id"]), other)

        # An explicit None withdraws an optional selection; the two
        # required ones cannot be cleared at all.
        cleared = stf.edit_session(self.home, record["id"], {
            "material": None, "overrides": None})
        self.assertNotIn("material", cleared)
        self.assertNotIn("overrides", cleared)
        for field in ("document", "rigor"):
            with self.assertRaises(stf.StaffingError):
                stf.edit_session(self.home, record["id"], {field: None})

        # Only those four. The work area, the machine's families and the id
        # are facts an edit may not move.
        for field, value in (("work_area", {"workspace_path": "/tmp/other"}),
                             ("families", ["claude"]),
                             ("id", "stf-somebody-else"),
                             ("name", "x")):
            with self.subTest(field=field):
                with self.assertRaises(stf.StaffingError):
                    stf.edit_session(self.home, record["id"], {field: value})
        self.assertEqual(stf.read_session(self.home, record["id"]), cleared)

        # Optimistic: no compare-and-set and no version, so two saves each
        # land and the last completed one governs the next call.
        stf.edit_session(self.home, record["id"], {"rigor": "low"})
        stf.edit_session(self.home, record["id"], {"rigor": "medium"})
        self.assertEqual(
            stf.read_session(self.home, record["id"])["rigor"], "medium")

    def test_reading_an_unknown_or_damaged_session_is_loud(self):
        """Unknown, malformed and damaged are one loud failure.

        One error class because the resolver's mandatory fallback treats
        "cannot be read" as one condition; a caller that wants to tell them
        apart reads the message, and nothing repairs a stored record.
        """
        record = stf.create_session(self.home, session_body())
        d = os.path.join(self.home, stf.STAFFING_SESSIONS_DIRNAME)
        with self.assertRaises(stf.StaffingError):
            stf.read_session(self.home, "stf-nobody")
        with self.assertRaises(stf.StaffingError):
            stf.edit_session(self.home, "stf-nobody", {"rigor": "low"})
        # An id is a filename and nothing else.
        for bad in ("../../etc/passwd", "", "a/b"):
            with self.subTest(id=bad):
                with self.assertRaises(stf.StaffingError):
                    stf.read_session(self.home, bad)

        for label, payload in (
            ("not JSON", "{"),
            ("not an object", "[]"),
            ("invalid record", json.dumps({"id": record["id"]})),
            # A key with more digits than the interpreter converts is
            # damage like any other: one loud class, never a raw
            # conversion failure the fallback would not recognize.
            ("an index key past the number limit",
             json.dumps(dict(record, overrides={
                 "assignment": {"fix": {LONG_INDEX_KEY: 1}}}))),
            # Deeper nesting than the interpreter decodes (CPython's
            # recursion limit) is damage in the same way: one loud class,
            # never a raw recursion failure the fallback would not
            # recognize.
            ("nesting past the recursion limit",
             "[" * 10000 + "]" * 10000),
        ):
            with self.subTest(case=label):
                with open(os.path.join(d, "%s.json" % record["id"]), "w",
                          encoding="utf-8") as fh:
                    fh.write(payload)
                with self.assertRaises(stf.StaffingError):
                    stf.read_session(self.home, record["id"])

        # A record whose file and id disagree is damage, not a rename.
        stray = copy.deepcopy(record)
        stray["id"] = "stf-elsewhere"
        with open(os.path.join(d, "%s.json" % record["id"]), "w",
                  encoding="utf-8") as fh:
            json.dump(stray, fh)
        with self.assertRaises(stf.StaffingError):
            stf.read_session(self.home, record["id"])

    def test_sessions_live_beside_the_documents_and_not_inside_them(self):
        """Two catalogues, two directories: a session is never a document
        candidate the document store would try to load and validate."""
        record = stf.create_session(self.home, session_body())
        self.assertNotEqual(
            stf.staffing_sessions_dir(self.home),
            stf.staffing_documents_dir(self.home))
        self.assertEqual(self.session_files(), ["%s.json" % record["id"]])
        self.assertEqual(stf.document_names(self.home), [])
        self.assertEqual(stf.list_staffing_documents(self.home), [])


if __name__ == "__main__":
    unittest.main()
