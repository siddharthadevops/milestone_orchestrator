"""Session and resolution tests for orchestrator/staffing.py (slice 3).

Covers the closed session record — the five facts an owner supplies, the two
optional selections, and the session override in the document's own inner
shape validated for shape ALONE — the loud save-time validation that leaves a
refused edit's predecessor byte-identical, and the store's whole create /
read / edit behaviour with its assigned id, its four editable fields and its
last-write-wins saves.

Then the resolver: the whole resolution matrix seat by seat, `step_up` from
its round with both saturations, the mandatory fallback's three levels down
to the in-code seed, the two surfaced conditions beside the input refusals
that are neither, the two live document readers, and the live-and-writes-
nothing posture.

Nothing here staffs a real call: no dispatch seam is touched, and every
dispatch still reads model profiles until its own later slice.
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
LONG_INDEX = 10 ** 5000

# Deeper nesting than CPython decodes.
DEEP_NESTING = "[" * 10000 + "]" * 10000


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



# ---------------------------------------------------------------------------
# Resolution
#
# Every document below is written so that each matrix row's answer names
# exactly ONE rule: the family this machine does not have sits in the LOWEST
# slot, so collapse has to find the lowest AVAILABLE slot rather than slot 1;
# the two materials move the same role to different rungs; and every tuning
# cell is written, so no answer comes from a value nobody chose.

RESOLVER_FAMILIES = {
    "1": {"name": "gemini",
          "models": ["gem-flash", "gem-pro"],
          "efforts": ["low", "high"]},
    "2": {"name": "codex",
          "models": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
          "efforts": ["low", "medium", "high", "xhigh", "max"]},
    "3": {"name": "claude",
          "models": ["claude-sonnet-5", "claude-opus-5", "claude-fable-5"],
          "efforts": ["low", "medium", "high", "xhigh", "max"]},
}

# What the session says this machine actually has: never `gemini`.
HERE = ["codex", "claude"]


def staffing(agent, model, effort):
    return {"agent": agent, "model": model, "effort": effort}


def base_cells():
    return {rigor: {slot: {role: [1, 1] for role in stf.ROLES}
                    for slot in RESOLVER_FAMILIES}
            for rigor in stf.RIGORS}


def resolver_doc(name="matrix"):
    """The one document the whole matrix reads."""
    assignment = {role: {"1": 2} for role in stf.ROLES}
    assignment["plan"] = {"1": 1}            # a family this machine lacks
    assignment["draft"] = {"1": 3}
    assignment["implement"] = {"1": 3}
    assignment["consult"] = {"1": 3}
    assignment["review"] = {"1": 2, "2": 3}
    assignment["brainstorm"] = {"1": 2, "2": 3, "3": 2}
    tuning = base_cells()
    tuning["medium"]["2"]["plan"] = [2, 3]   # read after the collapse
    tuning["medium"]["2"]["sync"] = [9, 9]   # past the end of both ladders
    tuning["medium"]["2"]["fix"] = [2, 2]
    tuning["medium"]["3"]["implement"] = [2, 2]
    tuning["high"]["3"]["implement"] = [3, 5]   # rigor picks the table
    return {
        "name": name,
        "families": copy.deepcopy(RESOLVER_FAMILIES),
        "roles": {role: ({"distinct_families": True} if role == "review"
                         else {})
                  for role in stf.ROLES},
        "materials": {"prose": {"examples": ["contracts"]},
                      "code": {"examples": ["python modules"]}},
        "tuning": tuning,
        "assignment": assignment,
        "overrides": {
            "prose": {"assignment": {"draft": {"1": 2},
                                     "consult": {"2": 2}},
                      "tuning": {"medium": {"2": {"draft": [3, 4]}}}},
            "code": {"assignment": {"draft": {"1": 2}},
                     "tuning": {"medium": {"2": {"draft": [1, 2]}}}},
        },
        "rules": [],
    }


def climb_doc(name="climb"):
    """One family, every seat placed to show one step of the ladder."""
    tuning = {rigor: {"1": {role: [1, 1] for role in stf.ROLES}}
              for rigor in stf.RIGORS}
    tuning["medium"]["1"]["review"] = [1, 2]   # room on both ladders
    tuning["medium"]["1"]["fix"] = [1, 5]      # effort already at the top
    tuning["medium"]["1"]["plan"] = [3, 5]     # both already at the top
    tuning["medium"]["1"]["draft"] = [1, 9]    # saturates, THEN steps
    return {
        "name": name,
        "families": {"1": copy.deepcopy(RESOLVER_FAMILIES["2"])},
        "roles": {role: {} for role in stf.ROLES},
        "materials": {},
        "tuning": tuning,
        "assignment": {role: {"1": 1} for role in stf.ROLES},
        "overrides": {},
        "rules": [
            {"type": "step_up", "role": "review", "min_round": 3},
            {"type": "step_up", "role": "fix", "min_round": 2},
            {"type": "step_up", "role": "plan", "min_round": 1},
            {"type": "step_up", "role": "draft", "min_round": 1},
            # Two entries for one role: progression is written as DATA.
            {"type": "step_up", "role": "classify", "min_round": 2},
            {"type": "step_up", "role": "classify", "min_round": 3},
        ],
    }


def default_doc():
    """The stored `default`, answering as no other document here does."""
    tuning = {rigor: {slot: {role: [1, 1] for role in stf.ROLES}
                      for slot in ("1", "2")}
              for rigor in stf.RIGORS}
    tuning["medium"]["2"]["implement"] = [1, 1]   # claude-sonnet-5 / low
    tuning["high"]["2"]["implement"] = [3, 3]     # claude-fable-5 / high
    tuning["medium"]["1"]["implement"] = [2, 4]   # after collapsing to codex
    assignment = {role: {"1": 1} for role in stf.ROLES}
    assignment["implement"] = {"1": 2}
    return {
        "name": "default",
        "families": {"1": copy.deepcopy(RESOLVER_FAMILIES["2"]),
                     "2": copy.deepcopy(RESOLVER_FAMILIES["3"])},
        "roles": {role: {} for role in stf.ROLES},
        "materials": {},
        "tuning": tuning,
        "assignment": assignment,
        "overrides": {},
        "rules": [],
    }


class StaffingResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-staffing-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    # -- helpers -----------------------------------------------------------

    def open_session(self, document="matrix", families=None, **changes):
        """One session over *document*, and its store-assigned id."""
        return stf.create_session(self.home, session_body(
            document=document,
            families=list(HERE if families is None else families),
            **changes))["id"]

    def answer(self, session, role, **request):
        """One ordinary answer: three keys, and no fallback note."""
        resolution = stf.resolve(self.home, session, role, **request)
        self.assertIsNone(resolution.staffing_fallback)
        self.assertEqual(sorted(resolution.answer),
                         ["agent", "effort", "model"])
        return resolution.answer

    def corrupt(self, path, payload="{not json"):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(payload)

    def snapshot(self):
        """Every byte under the service home, by relative path."""
        out = {}
        for root, _dirs, files in os.walk(self.home):
            for filename in files:
                path = os.path.join(root, filename)
                with open(path, "rb") as fh:
                    out[os.path.relpath(path, self.home)] = fh.read()
        return out

    # -- the matrix --------------------------------------------------------

    def test_resolution_matrix(self):
        """Every rule of the resolution order, one row at a time, each row
        asserting the WHOLE answer."""
        stf.save(self.home, resolver_doc())
        plain = self.open_session()
        coded = self.open_session(material="code")

        # Base: the document's own seat, nothing layered over it.
        self.assertEqual(self.answer(plain, "implement"),
                         staffing("claude", "claude-opus-5", "medium"))

        # Collapse: `plan` sits on slot 1, whose family this machine does
        # not have, so it runs on the lowest-numbered slot it does — slot 2,
        # not slot 3 — and reads THAT slot's tuning.
        self.assertEqual(self.answer(plain, "plan"),
                         staffing("codex", "gpt-5.6-terra", "high"))

        # Saturation: rank 9 on a 3-rung and a 5-rung ladder is each
        # ladder's top, not a refusal.
        self.assertEqual(self.answer(plain, "sync"),
                         staffing("codex", "gpt-5.6-sol", "max"))

        # Material precedence: the request's beats the session's default,
        # and both beat the base assignment.
        self.assertEqual(self.answer(coded, "draft", material="prose"),
                         staffing("codex", "gpt-5.6-sol", "xhigh"))
        self.assertEqual(self.answer(coded, "draft"),
                         staffing("codex", "gpt-5.6-luna", "medium"))
        self.assertEqual(self.answer(plain, "draft"),
                         staffing("claude", "claude-sonnet-5", "low"))

        # An unknown material counts as ABSENT wherever it is named, so the
        # chain moves on to the next one rather than dropping to base.
        self.assertEqual(self.answer(coded, "draft", material="sculpture"),
                         self.answer(coded, "draft"))
        unknown = self.open_session(material="sculpture")
        self.assertEqual(self.answer(unknown, "draft"),
                         self.answer(plain, "draft"))

        # A seat no layer assigns is that role's index 1 — layered like any
        # other seat, so the material's own index 1 answers it too.
        self.assertEqual(self.answer(plain, "implement", index=7),
                         self.answer(plain, "implement", index=1))
        self.assertEqual(self.answer(coded, "draft", index=9,
                                     material="prose"),
                         self.answer(coded, "draft", material="prose"))

        # An index with more digits than the interpreter converts is one no
        # stored key can spell, so it is unassigned like any other and takes
        # the role's index 1 instead of failing the request.
        self.assertEqual(self.answer(plain, "implement", index=LONG_INDEX),
                         self.answer(plain, "implement", index=1))

        # The session's own override outranks the material's, which outranks
        # base — for the assignment and for the tuning alike.
        layered = self.open_session(material="code", overrides={
            "assignment": {"draft": {"1": 3}},
            "tuning": {"medium": {"3": {"draft": [2, 3]}}}})
        self.assertEqual(self.answer(layered, "draft"),
                         staffing("claude", "claude-opus-5", "high"))

        # A session override naming a slot the document does not carry
        # collapses like any other absent family — and the tuning it wrote
        # for that slot goes nowhere, because the slot that RUNS is slot 2.
        uncarried = self.open_session(overrides={
            "assignment": {"fix": {"1": 97}},
            "tuning": {"medium": {"97": {"fix": [3, 5]}}}})
        self.assertEqual(self.answer(uncarried, "fix"),
                         staffing("codex", "gpt-5.6-terra", "medium"))

        # `brief` is accepted and read by nothing.
        self.assertEqual(
            self.answer(plain, "implement", brief="rewrite the parser"),
            self.answer(plain, "implement", brief="do nothing at all"))
        self.assertEqual(self.answer(plain, "implement", brief=None),
                         self.answer(plain, "implement"))

    # -- the one rule ------------------------------------------------------

    def test_step_up_fires_from_its_round_and_saturates(self):
        """One step per matching entry, after saturation, from its round."""
        stf.save(self.home, climb_doc())
        session = self.open_session(document="climb", families=["codex"])

        def at(role, round_number):
            return self.answer(session, role, round=round_number)

        # Below `min_round` the answer is the tuned one; at and above it the
        # effort is one rung higher — and no higher, however many rounds
        # pass, because ONE entry is one step.
        tuned = staffing("codex", "gpt-5.6-luna", "medium")
        self.assertEqual(at("review", 1), tuned)
        self.assertEqual(at("review", 2), tuned)
        for round_number in (3, 4, 99):
            self.assertEqual(at("review", round_number),
                             staffing("codex", "gpt-5.6-luna", "high"))

        # Effort already at the top: the next model, at its FIRST effort.
        self.assertEqual(at("fix", 1),
                         staffing("codex", "gpt-5.6-luna", "max"))
        self.assertEqual(at("fix", 2),
                         staffing("codex", "gpt-5.6-terra", "low"))

        # Both at the top: nothing moves.
        self.assertEqual(at("plan", 1), staffing("codex", "gpt-5.6-sol", "max"))

        # Saturation happens FIRST: rank 9 is `max`, and the step then takes
        # the next model rather than a rung that does not exist.
        self.assertEqual(at("draft", 1),
                         staffing("codex", "gpt-5.6-terra", "low"))

        # Two matching entries apply two steps.
        self.assertEqual(at("classify", 1),
                         staffing("codex", "gpt-5.6-luna", "low"))
        self.assertEqual(at("classify", 2),
                         staffing("codex", "gpt-5.6-luna", "medium"))
        self.assertEqual(at("classify", 3),
                         staffing("codex", "gpt-5.6-luna", "high"))

        # A role no entry names never steps, whatever the round.
        self.assertEqual(at("sync", 9), staffing("codex", "gpt-5.6-luna", "low"))

    # -- the mandatory fallback -------------------------------------------

    def test_unreadable_inputs_resolve_on_the_default_document(self):
        """Absent and corrupt inputs alike answer on the default document,
        report that they did, and write nothing."""
        stf.save(self.home, default_doc())
        stf.save(self.home, resolver_doc())
        before = self.snapshot()

        def resolved(session, role="implement", **request):
            resolution = stf.resolve(self.home, session, role, **request)
            self.assertEqual(resolution.staffing_fallback, "default_document")
            self.assertEqual(self.snapshot(), before)
            return resolution.answer

        # No session at all: `default` at `medium` with the families the
        # CALLER passed, since a session is where both of those live.
        on_default = staffing("claude", "claude-sonnet-5", "low")
        self.assertEqual(resolved("stf-nobody", families=HERE), on_default)

        # A session id of any shape is a session that cannot be read, and
        # every shape reaches the SAME fallback — including a number past
        # the interpreter's conversion limit, which the context prefix
        # renders by size rather than escaping as a raw conversion failure
        # the fallback would not recognize.
        for label, session_id in (("a small number", 123),
                                  ("a number past conversion", LONG_INDEX),
                                  ("a list", ["stf-nobody"]),
                                  ("nothing at all", None)):
            with self.subTest(case=label):
                self.assertEqual(resolved(session_id, families=HERE),
                                 on_default)

        # A corrupt session record is the same condition, answered the same
        # way — and it stays corrupt.
        broken = self.open_session()
        self.corrupt(os.path.join(stf.staffing_sessions_dir(self.home),
                                  "%s.json" % broken))
        before = self.snapshot()
        self.assertEqual(resolved(broken, families=HERE), on_default)

        # An unreadable DOCUMENT loses only the document: the session's own
        # rigor and families still govern.
        absent = self.open_session(document="never-written", rigor="high")
        before = self.snapshot()
        self.assertEqual(resolved(absent),
                         staffing("claude", "claude-fable-5", "high"))

        narrow = self.open_session(document="never-written",
                                   families=["codex"])
        before = self.snapshot()
        self.assertEqual(resolved(narrow),
                         staffing("codex", "gpt-5.6-terra", "xhigh"))

        corrupt_doc = self.open_session(document="matrix", rigor="high")
        self.corrupt(os.path.join(stf.staffing_documents_dir(self.home),
                                  "matrix.json"))
        before = self.snapshot()
        self.assertEqual(resolved(corrupt_doc),
                         staffing("claude", "claude-fable-5", "high"))

        # Nesting deeper than the interpreter DECODES is unreadable in the
        # same way, so it reaches the same fallback rather than escaping as
        # a raw recursion failure the fallback would not recognize.
        self.corrupt(os.path.join(stf.staffing_documents_dir(self.home),
                                  "matrix.json"), DEEP_NESTING)
        before = self.snapshot()
        self.assertEqual(resolved(corrupt_doc),
                         staffing("claude", "claude-fable-5", "high"))

        # The floor: a corrupt stored `default` answers from the IN-CODE
        # seed, and is neither healed nor rewritten.
        seed = stf.default_document_seed()
        seed_families = [slot["name"] for slot in seed["families"].values()]
        self.corrupt(os.path.join(stf.staffing_documents_dir(self.home),
                                  "default.json"))
        floor = self.open_session(document="never-written",
                                  families=seed_families)
        before = self.snapshot()
        self.assertEqual(
            resolved(floor),
            staffing(*stf.base_staffing(seed, "medium", "implement")))
        # And with no session either, still the seed, still at `medium`.
        self.assertEqual(resolved("stf-nobody", families=seed_families),
                         staffing(*stf.base_staffing(seed, "medium",
                                                     "implement")))

        # The floor holds for a `default` damaged that other way too: a
        # stored one nested past the recursion limit still answers from the
        # in-code seed.
        self.corrupt(os.path.join(stf.staffing_documents_dir(self.home),
                                  "default.json"), DEEP_NESTING)
        before = self.snapshot()
        self.assertEqual(
            resolved(floor),
            staffing(*stf.base_staffing(seed, "medium", "implement")))
        self.assertEqual(resolved("stf-nobody", families=seed_families),
                         staffing(*stf.base_staffing(seed, "medium",
                                                     "implement")))

        # Nothing was repaired: both damaged files are still damaged.
        for name in ("default", "matrix"):
            with self.assertRaises(stf.StaffingError):
                stf.load(self.home, name)

    # -- the two surfaced conditions --------------------------------------

    def test_the_two_surfaced_conditions(self):
        """Exactly two conditions are surfaced, and an input error is
        neither of them."""
        stf.save(self.home, resolver_doc())

        # Nobody to call at all — an empty families list, and one naming
        # only families the document has no slot for.
        for families in ([], ["mistral"]):
            with self.subTest(families=families):
                session = self.open_session(families=families)
                with self.assertRaises(stf.StaffingConditionError) as caught:
                    stf.resolve(self.home, session, "implement")
                self.assertEqual(caught.exception.code, "staffing_unavailable")

        # `distinct_families` is judged on the role's OWN seats, after
        # collapse: two seats that land on one slot are one family however
        # the document numbered them.
        def review_document(seats, distinct=True, name="split"):
            doc = resolver_doc(name)
            doc["assignment"]["review"] = dict(seats)
            doc["roles"]["review"] = ({"distinct_families": True} if distinct
                                      else {})
            return doc

        for label, seats in (("both on one slot", {"1": 2, "2": 2}),
                             ("collapsing onto one slot", {"1": 1, "2": 2})):
            with self.subTest(case=label):
                stf.save(self.home, review_document(seats))
                session = self.open_session(document="split")
                with self.assertRaises(stf.StaffingConditionError) as caught:
                    stf.resolve(self.home, session, "review")
                self.assertEqual(caught.exception.code,
                                 "distinct_families_unsatisfiable")
                # Every seat of the role is refused, not only the colliding
                # one: milestone law cannot be served at all.
                with self.assertRaises(stf.StaffingConditionError):
                    stf.resolve(self.home, session, "review", index=2)

        # One assigned seat is trivially honoured, and a role that declares
        # nothing shares a family freely.
        stf.save(self.home, review_document({"1": 2}, name="single"))
        single = self.open_session(document="single")
        self.assertEqual(self.answer(single, "review"),
                         staffing("codex", "gpt-5.6-luna", "low"))
        stf.save(self.home, review_document({"1": 2, "2": 2}, distinct=False,
                                            name="shared"))
        shared = self.open_session(document="shared")
        self.assertEqual(self.answer(shared, "review", index=2),
                         staffing("codex", "gpt-5.6-luna", "low"))

        # The check reads the LAYERED assignment, so a session override can
        # create the collision the document does not have.
        collided = self.open_session(
            overrides={"assignment": {"review": {"2": 2}}})
        with self.assertRaises(stf.StaffingConditionError) as caught:
            stf.resolve(self.home, collided, "review")
        self.assertEqual(caught.exception.code,
                         "distinct_families_unsatisfiable")

        # An invalid request is an INPUT error, not either condition, and it
        # never reaches the fallback.
        session = self.open_session()
        for label, request in (
            ("unknown role", {"role": "refactor"}),
            ("index at zero", {"role": "fix", "index": 0}),
            ("negative index", {"role": "fix", "index": -1}),
            ("index as a boolean", {"role": "fix", "index": True}),
            ("round at zero", {"role": "fix", "round": 0}),
            ("round as a string", {"role": "fix", "round": "3"}),
            ("material as a list", {"role": "fix", "material": ["prose"]}),
            # A value with more digits than the interpreter converts is
            # refused as the input error it is: naming it in the message is
            # the module's business, and cannot cost the caller the declared
            # class it is guarding.
            ("index below zero and beyond conversion",
             {"role": "fix", "index": -LONG_INDEX}),
            ("round below zero and beyond conversion",
             {"role": "fix", "round": -LONG_INDEX}),
            ("material as a number beyond conversion",
             {"role": "fix", "material": LONG_INDEX}),
            ("role as a number beyond conversion", {"role": LONG_INDEX}),
        ):
            with self.subTest(case=label):
                with self.assertRaises(stf.StaffingError) as caught:
                    stf.resolve(self.home, session, **request)
                self.assertNotIsInstance(caught.exception,
                                         stf.StaffingConditionError)
        # The same unknown role over a session that cannot be read is still
        # an input error: the fallback answers unreadable INPUTS, never a
        # request naming something no vocabulary contains.
        with self.assertRaises(stf.StaffingError) as caught:
            stf.resolve(self.home, "stf-nobody", "refactor", families=HERE)
        self.assertNotIsInstance(caught.exception, stf.StaffingConditionError)

        # And nothing else raises: every other awkward input answers.
        self.assertIsNotNone(self.answer(session, "fix", material="sculpture"))
        self.assertIsNotNone(self.answer(session, "fix", index=44, round=44))
        self.assertIsNotNone(self.answer(session, "fix", brief=object()))

    # -- the two live document reads ---------------------------------------

    def test_seats_and_distinct_families_projection(self):
        """A role's seats and the projection are readable over a session,
        without dispatching anything."""
        stf.save(self.home, resolver_doc())
        plain = self.open_session()

        self.assertEqual(stf.session_seats(self.home, plain, "review"), [1, 2])
        self.assertEqual(
            stf.session_seats(self.home, plain, "brainstorm"), [1, 2, 3])
        self.assertEqual(stf.session_seats(self.home, plain, "implement"), [1])

        # The seats are the LAYERED assignment's own index set: an override
        # that adds a seat adds a seat the consumer iterates.
        widened = self.open_session(
            overrides={"assignment": {"review": {"3": 3}}})
        self.assertEqual(
            stf.session_seats(self.home, widened, "review"), [1, 2, 3])
        self.assertEqual(
            stf.session_seats(self.home, plain, "consult", material="prose"),
            [1, 2])
        self.assertEqual(stf.session_seats(self.home, plain, "consult"), [1])

        with self.assertRaises(stf.StaffingError):
            stf.session_seats(self.home, plain, "refactor")
        with self.assertRaises(stf.StaffingError):
            stf.session_seats(self.home, plain, LONG_INDEX)

        # Both reads take the same unreadable-session fallback the resolver
        # does, for a session id of any shape: the document in force is the
        # default's, never a raw conversion failure.
        for session_id in (LONG_INDEX, None, ["stf-nobody"]):
            with self.subTest(session=type(session_id).__name__):
                self.assertEqual(
                    stf.session_seats(self.home, session_id, "implement",
                                      families=HERE), [1])
                self.assertEqual(
                    stf.distinct_families_projection(self.home, session_id,
                                                     families=HERE), [])

        # The projection names exactly the roles whose declared
        # `distinct_families` cannot be honoured — none, here.
        self.assertEqual(
            stf.distinct_families_projection(self.home, plain), [])

        # It follows the DOCUMENT live: the same session, read twice across
        # one document save.
        collided = resolver_doc()
        collided["assignment"]["review"] = {"1": 2, "2": 2}
        collided["roles"]["brainstorm"] = {"distinct_families": True}
        collided["assignment"]["brainstorm"] = {"1": 2, "2": 2, "3": 2}
        stf.save(self.home, collided)
        self.assertEqual(stf.distinct_families_projection(self.home, plain),
                         ["review", "brainstorm"])

        # One assigned seat is honoured, so it leaves the projection.
        single = resolver_doc()
        single["assignment"]["review"] = {"1": 2}
        stf.save(self.home, single)
        self.assertEqual(
            stf.distinct_families_projection(self.home, plain), [])

        # A read ANSWERS: with nobody to call at all it reports the roles it
        # cannot honour rather than refusing.
        stf.save(self.home, collided)
        nobody = self.open_session(families=[])
        self.assertEqual(stf.distinct_families_projection(self.home, nobody),
                         ["review", "brainstorm"])
        self.assertEqual(stf.session_seats(self.home, nobody, "review"),
                         [1, 2])

    # -- live, and pure ----------------------------------------------------

    def test_resolution_is_live_and_writes_nothing(self):
        """The last completed write governs the next call, through one
        caller, and resolving changes no byte on disk."""
        stf.save(self.home, resolver_doc())
        session = self.open_session()

        first = self.answer(session, "implement")
        self.assertEqual(first, staffing("claude", "claude-opus-5", "medium"))

        # The SESSION changes between two identical requests.
        stf.edit_session(self.home, session, {"rigor": "high"})
        second = self.answer(session, "implement")
        self.assertEqual(second, staffing("claude", "claude-fable-5", "max"))
        self.assertNotEqual(first, second)

        stf.edit_session(self.home, session,
                         {"rigor": "medium", "material": "code"})
        self.assertEqual(self.answer(session, "draft"),
                         staffing("codex", "gpt-5.6-luna", "medium"))

        # And the DOCUMENT changes, under the same unchanged session.
        edited = resolver_doc()
        edited["tuning"]["medium"]["3"]["implement"] = [1, 4]
        stf.save(self.home, edited)
        third = self.answer(session, "implement")
        self.assertEqual(third, staffing("claude", "claude-sonnet-5", "xhigh"))
        self.assertNotEqual(third, first)

        # Nothing is cached and nothing is written: every file under the
        # service home is byte-identical around a resolution.
        before = self.snapshot()
        self.assertEqual(self.answer(session, "implement"), third)
        stf.session_seats(self.home, session, "review")
        stf.distinct_families_projection(self.home, session)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
