"""HTTP API tests for the staffing router (staffing-router slice 5).

The thin public surface over slice 2's document store, slice 3's session
store and resolver, and slice 4's run binding: the document catalogue and
its administrative whole-replacement write, session create / read / edit
with the live split-family projection beside every successful response, one
resolution that is exactly the router's answer, and the run summary's
id-only exposure of the run's session.

Conventions of test_service_api.py: a real service.make_server(home, 0) in a
thread over an isolated tempdir home (never ~/.impl_roadmap), exercised
through urllib with "autostart": false everywhere. Identity is the service's
own: a loopback request with no headers is the local administrator, and the
remote Google headers make a member. Nothing here dispatches a call — the
routes only configure and answer.
"""

import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from orchestrator import access, registry, service
from orchestrator import driver as drv
from orchestrator import staffing as stf
from orchestrator import state as st

from orchestrator.tests.test_staffing_documents import valid_doc

PROJECT = "life prod"
AREA = "main area"

SESSION_RECORD_KEYS = {"id", "work_area", "families", "document", "rigor"}
DOCUMENT_RECORD_KEYS = {"name", "families", "tuning", "assignment"}


def house_doc(name="house"):
    """The test catalogue's own document: `valid_doc` with rigor actually
    telling the three tunings apart, so a live rigor change is visible in
    the next answer rather than hidden behind one calibration."""
    doc = valid_doc(name)
    doc["tuning"]["low"] = {
        slot: {role: [1, 1] for role in stf.ROLES} for slot in ("1", "2")
    }
    doc["tuning"]["high"] = {
        slot: {role: [3, 5] for role in stf.ROLES} for slot in ("1", "2")
    }
    return doc


def _objects(node):
    """Every JSON object inside a decoded response, the root included."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _objects(value)


class StaffingApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-staffing-api-")
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.server = service.make_server(self.home, 0)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    # -- request helpers ---------------------------------------------------

    @staticmethod
    def member_headers(email):
        """The identity the generated ngrok policy injects for one user."""
        return {
            "Host": "example.ngrok-free.dev",
            access.REMOTE_HEADER: access.REMOTE_MARKER,
            access.USER_HEADER: email,
        }

    def request(self, method, path, payload=None, headers=None,
                raw_body=None):
        data = raw_body
        if data is None and payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def expect(self, status, method, path, payload=None, headers=None,
               raw_body=None):
        got, body = self.request(
            method, path, payload=payload, headers=headers,
            raw_body=raw_body)
        self.assertEqual(got, status, body)
        if 200 <= status < 300:
            self.assertIs(body.get("ok"), True, body)
        return body

    def refused(self, status, token, method, path, payload=None,
                headers=None, raw_body=None):
        """A refusal's error body is the fixed token, verbatim."""
        body = self.expect(
            status, method, path, payload=payload, headers=headers,
            raw_body=raw_body)
        self.assertIs(body["ok"], False, body)
        self.assertEqual(body["error"], token, body)
        return body

    # -- fixture helpers ---------------------------------------------------

    def member(self, email=access.USER_EMAILS[0], slug=PROJECT):
        """One project the caller is a member of, and their headers."""
        self.expect(201, "POST", "/api/projects", {"slug": slug})
        self.set_users(slug, [email])
        return self.member_headers(email)

    def set_users(self, slug, emails):
        self.expect(
            200, "POST",
            "/api/projects/%s/users" % urllib.parse.quote(slug, safe=""),
            {"users": list(emails)},
        )

    def session_body(self, **changes):
        body = {
            "work_area": {"project": PROJECT, "work_area": AREA},
            "families": ["codex", "claude"],
            "document": "house",
            "rigor": "medium",
        }
        body.update(changes)
        return body

    def create_session(self, headers=None, **changes):
        body = self.expect(
            201, "POST", "/api/staffing/sessions",
            self.session_body(**changes), headers=headers)
        return body["session"]

    def session_path(self, session_id, *suffix):
        return "/".join(["/api/staffing/sessions", session_id] + list(suffix))

    # -- store-side reads (assertion side) ---------------------------------

    def document_bytes(self, name):
        with open(os.path.join(stf.staffing_documents_dir(self.home),
                               "%s.json" % name), "rb") as fh:
            return fh.read()

    def session_bytes(self, session_id):
        with open(os.path.join(stf.staffing_sessions_dir(self.home),
                               "%s.json" % session_id), "rb") as fh:
            return fh.read()

    def catalogue_files(self):
        """Every stored record filename, both catalogues."""
        def names(directory):
            return sorted(os.listdir(directory)) \
                if os.path.isdir(directory) else []
        return (names(stf.staffing_documents_dir(self.home)),
                names(stf.staffing_sessions_dir(self.home)))

    def workspace(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path, exist_ok=True)
        subprocess.run(["git", "init", "-q", path], check=True)
        return path


# ---------------------------------------------------------------------------
# Documents


class StaffingDocumentRoutes(StaffingApiTestCase):
    def test_document_list_save_replace_validation_and_access(self):
        """The catalogue reads to any authenticated caller; writing it is
        administrative, whole, and byte-stable when refused."""
        member = self.member()

        # Writing is the administrator's. A member reaches the catalogue
        # only to read it.
        self.refused(403, service.FORBIDDEN, "POST",
                     "/api/staffing/documents", house_doc(),
                     headers=member)
        self.assertEqual(self.catalogue_files()[0], ["default.json"])

        saved = self.expect(
            200, "POST", "/api/staffing/documents", house_doc())["document"]
        self.assertEqual(saved, stf.load(self.home, "house"))
        self.expect(200, "POST", "/api/staffing/documents",
                    house_doc("aardvark"))

        # The stored source document, in name order, to a member.
        listed = self.expect(
            200, "GET", "/api/staffing/documents", headers=member)
        self.assertEqual([d["name"] for d in listed["documents"]],
                         ["aardvark", "default", "house"])
        self.assertEqual(listed["documents"],
                         stf.list_staffing_documents(self.home))

        # A save WHOLLY replaces: the removed rule and the removed second
        # review seat are gone, not merged back in from the predecessor.
        replacement = house_doc()
        replacement["rules"] = []
        del replacement["assignment"]["review"]["2"]
        stored = self.expect(
            200, "POST", "/api/staffing/documents",
            replacement)["document"]
        self.assertEqual(stored["rules"], [])
        self.assertEqual(stored["assignment"]["review"], {"1": 1})
        self.assertEqual(stf.load(self.home, "house"), stored)

        # A refused save changes no byte of its predecessor.
        before = self.document_bytes("house")
        for label, mutate in (
            ("missing block", lambda d: d.pop("rules")),
            ("unknown key", lambda d: d.update(version=1)),
            ("incomplete tuning", lambda d: d["tuning"].pop("low")),
            ("unknown role", lambda d: d["assignment"].update(ship={"1": 1})),
            ("slot nobody carries",
             lambda d: d["assignment"]["plan"].update({"1": 9})),
            # JSON admits an escaped unpaired surrogate and the store
            # records strings verbatim, but no response could carry one
            # back: refused before the write, rather than committed behind
            # a failed answer and left to break the catalogue read.
            ("a string no response could carry",
             lambda d: d["materials"]["prose"]["examples"].append("\ud800")),
        ):
            with self.subTest(refusal=label):
                broken = house_doc()
                mutate(broken)
                self.refused(400, service.INVALID_STAFFING_DOCUMENT,
                             "POST", "/api/staffing/documents", broken)
                self.assertEqual(self.document_bytes("house"), before)
        self.refused(400, service.INVALID_STAFFING_DOCUMENT, "POST",
                     "/api/staffing/documents", raw_body=b"{ not json")
        self.assertEqual(self.document_bytes("house"), before)
        self.assertEqual(self.catalogue_files()[0],
                         ["aardvark.json", "default.json", "house.json"])
        # No refusal above left the catalogue unreadable behind it.
        self.expect(200, "GET", "/api/staffing/documents", headers=member)

        # A damaged catalogue FAILS the read rather than looking shorter.
        with open(os.path.join(stf.staffing_documents_dir(self.home),
                               "aardvark.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        status, _body = self.request("GET", "/api/staffing/documents")
        self.assertEqual(status, 500)


# ---------------------------------------------------------------------------
# Sessions


class StaffingSessionRoutes(StaffingApiTestCase):
    def setUp(self):
        StaffingApiTestCase.setUp(self)
        self.expect(200, "POST", "/api/staffing/documents", house_doc())

    def test_session_create_read_and_live_condition_projection(self):
        """Create assigns the id and returns the stored record; an
        unsatisfiable split refuses nothing, and its role list is read live
        on every response."""
        created = self.expect(
            201, "POST", "/api/staffing/sessions",
            self.session_body(work_area={"workspace_path": "/tmp/ws"}))
        record = created["session"]
        self.assertTrue(record["id"].startswith("stf-"))
        self.assertEqual(record, stf.read_session(self.home, record["id"]))
        self.assertEqual(created["distinct_families_unsatisfiable"], [])
        self.assertEqual(set(created), {"ok", "session",
                                       "distinct_families_unsatisfiable"})

        # The id is the store's. A caller may not name — and so overwrite —
        # a record.
        self.refused(400, service.INVALID_STAFFING_SESSION, "POST",
                     "/api/staffing/sessions",
                     self.session_body(
                         id=record["id"],
                         work_area={"workspace_path": "/tmp/ws"}))

        # A string no response could carry back is refused before the
        # write: a create that committed behind a failed answer would
        # strand a record whose id the caller never learns.
        stored = self.catalogue_files()[1]
        self.refused(400, service.INVALID_STAFFING_SESSION, "POST",
                     "/api/staffing/sessions",
                     self.session_body(
                         material="\ud800",
                         work_area={"workspace_path": "/tmp/ws"}))
        self.assertEqual(self.catalogue_files()[1], stored)

        # A machine with one family cannot honour `review`'s declared split.
        # That still CREATES and still READS; it is named, not refused.
        one = self.expect(
            201, "POST", "/api/staffing/sessions",
            self.session_body(families=["codex"],
                              work_area={"workspace_path": "/tmp/ws"}))
        self.assertEqual(one["distinct_families_unsatisfiable"], ["review"])
        sid = one["session"]["id"]
        read = self.expect(200, "GET", self.session_path(sid))
        self.assertEqual(set(read), {"ok", "session",
                                     "distinct_families_unsatisfiable"})
        self.assertEqual(read["session"], one["session"])
        self.assertEqual(read["distinct_families_unsatisfiable"], ["review"])

        # A live DOCUMENT change recomputes it: one review seat is
        # trivially honoured, and restoring the second brings it back.
        one_seat = house_doc()
        del one_seat["assignment"]["review"]["2"]
        self.expect(200, "POST", "/api/staffing/documents", one_seat)
        self.assertEqual(
            self.expect(200, "GET", self.session_path(sid))[
                "distinct_families_unsatisfiable"], [])
        self.expect(200, "POST", "/api/staffing/documents", house_doc())
        self.assertEqual(
            self.expect(200, "GET", self.session_path(sid))[
                "distinct_families_unsatisfiable"], ["review"])

        # And a live SESSION change recomputes it the same way: a session
        # override that seats both reviewers on one slot cannot honour the
        # split; clearing it restores two distinct families.
        both = self.create_session(work_area={"workspace_path": "/tmp/ws"})
        collapsed = self.expect(
            200, "POST", self.session_path(both["id"]),
            {"overrides": {"assignment": {"review": {"2": 1}}}})
        self.assertEqual(collapsed["distinct_families_unsatisfiable"],
                         ["review"])
        # An unsatisfied split gates no edit either: the session goes on
        # being configured while it is named.
        still = self.expect(200, "POST", self.session_path(both["id"]),
                            {"rigor": "high"})
        self.assertEqual(set(still), {"ok", "session",
                                      "distinct_families_unsatisfiable"})
        self.assertEqual(still["session"]["rigor"], "high")
        self.assertEqual(still["distinct_families_unsatisfiable"], ["review"])
        cleared = self.expect(
            200, "POST", self.session_path(both["id"]), {"overrides": None})
        self.assertEqual(cleared["distinct_families_unsatisfiable"], [])

        # A session nobody stored is not there.
        self.refused(404, service.UNKNOWN_STAFFING_SESSION, "GET",
                     self.session_path("stf-nobody"))
        self.refused(404, service.UNKNOWN_STAFFING_SESSION, "POST",
                     self.session_path("stf-nobody"), {"rigor": "high"})

        # The surface is exactly create, read, edit and resolve: no
        # listing, no deletion, no lifecycle.
        for method, path in (
            ("GET", "/api/staffing/sessions"),
            ("DELETE", self.session_path(sid)),
            ("POST", self.session_path(sid, "close")),
        ):
            with self.subTest(absent=path, method=method):
                status, body = self.request(method, path, payload={})
                self.assertEqual(status, 404, body)
                self.assertEqual(body["error"], "not found", body)

    def test_session_access_and_authorized_override_authors(self):
        """The session's own work area is the whole policy: live project
        access for a project session, the administrator for a workspace-only
        one, and every caller who passes may write and clear overrides."""
        member = self.member()
        foreign = self.member_headers(access.USER_EMAILS[1])

        record = self.create_session(headers=member)
        self.assertEqual(set(record), SESSION_RECORD_KEYS)
        stored = json.loads(self.session_bytes(record["id"]))
        self.assertEqual(set(stored), SESSION_RECORD_KEYS)
        self.assertNotIn(access.USER_EMAILS[0], self.session_bytes(
            record["id"]).decode("utf-8"))

        # A member — not the operator — writes and clears an override, and
        # resolves through it. There is no creator check and no owner rung.
        written = self.expect(
            200, "POST", self.session_path(record["id"]),
            {"overrides": {"assignment": {"implement": {"1": 2}}}},
            headers=member)
        self.assertEqual(written["session"]["overrides"],
                         {"assignment": {"implement": {"1": 2}}})
        self.assertEqual(
            self.expect(200, "POST",
                        self.session_path(record["id"], "resolve"),
                        {"role": "implement"}, headers=member)["staffing"],
            {"agent": "claude", "model": "claude-opus-5", "effort": "xhigh"},
        )
        cleared = self.expect(
            200, "POST", self.session_path(record["id"]),
            {"overrides": None}, headers=member)
        self.assertNotIn("overrides", cleared["session"])
        self.expect(200, "GET", self.session_path(record["id"]),
                    headers=member)

        # Another known user with no access to that project reaches none of
        # it, and cannot open one there either.
        for method, path, payload in (
            ("GET", self.session_path(record["id"]), None),
            ("POST", self.session_path(record["id"]), {"rigor": "high"}),
            ("POST", self.session_path(record["id"], "resolve"),
             {"role": "implement"}),
            ("POST", "/api/staffing/sessions", self.session_body()),
        ):
            with self.subTest(route=path, method=method):
                self.refused(403, service.FORBIDDEN, method, path,
                             payload=payload, headers=foreign)

        # A project a caller NAMES is a claim, so the project gate decides
        # it for every identity: not even the operator opens a session for
        # a project the service does not declare, and nothing is stored for
        # one — the work area of a written record is not editable, and no
        # route deletes it.
        stored = self.catalogue_files()[1]
        undeclared = self.session_body(
            work_area={"project": "no-such-project", "work_area": AREA})
        for label, headers in (("operator", None), ("member", member)):
            with self.subTest(undeclared_project=label):
                self.refused(404, service.UNKNOWN_PROJECT, "POST",
                             "/api/staffing/sessions", undeclared,
                             headers=headers)
        self.assertEqual(self.catalogue_files()[1], stored)

        # A session with no project handle stays on the local-administrator
        # path: a member may not open one, the operator may.
        workspace_only = self.session_body(
            work_area={"workspace_path": "/tmp/ws"})
        self.refused(403, service.FORBIDDEN, "POST",
                     "/api/staffing/sessions", workspace_only,
                     headers=member)
        local = self.expect(201, "POST", "/api/staffing/sessions",
                            workspace_only)["session"]
        self.refused(403, service.FORBIDDEN, "GET",
                     self.session_path(local["id"]), headers=member)
        self.expect(200, "GET", self.session_path(local["id"]))

        # Access is LIVE: withdrawing the membership withdraws the session
        # with it, on the very next request.
        self.set_users(PROJECT, [])
        self.refused(403, service.FORBIDDEN, "GET",
                     self.session_path(record["id"]), headers=member)
        self.expect(200, "GET", self.session_path(record["id"]))

    def test_session_edit_shape_clear_and_byte_stable_refusal(self):
        """An edit is partial, closed to exactly four fields, and leaves the
        stored record byte-identical whenever it is refused."""
        record = self.create_session(
            work_area={"workspace_path": "/tmp/ws"}, material="prose",
            overrides={"assignment": {"plan": {"1": 2}}})

        # One field at a time; nothing omitted is replaced.
        edited = self.expect(200, "POST", self.session_path(record["id"]),
                             {"rigor": "high"})["session"]
        self.assertEqual(edited, dict(record, rigor="high"))
        edited = self.expect(200, "POST", self.session_path(record["id"]),
                             {"document": "default"})["session"]
        self.assertEqual(edited,
                         dict(record, rigor="high", document="default"))
        edited = self.expect(
            200, "POST", self.session_path(record["id"]),
            {"material": "granite",
             "overrides": {"assignment": {"fix": {"1": 2}}}})["session"]
        self.assertEqual(
            edited,
            dict(record, rigor="high", document="default",
                 material="granite",
                 overrides={"assignment": {"fix": {"1": 2}}}))

        # Explicit null clears the two optional selections and nothing else.
        cleared = self.expect(
            200, "POST", self.session_path(record["id"]),
            {"material": None, "overrides": None})["session"]
        self.assertEqual(set(cleared), SESSION_RECORD_KEYS)
        for field in ("document", "rigor"):
            with self.subTest(cannot_clear=field):
                self.refused(400, service.INVALID_STAFFING_SESSION, "POST",
                             self.session_path(record["id"]), {field: None})

        before = self.session_bytes(record["id"])
        for label, changes in (
            ("id", {"id": "stf-other"}),
            ("work area", {"work_area": {"workspace_path": "/tmp/elsewhere"}}),
            ("families", {"families": ["codex"]}),
            ("unknown field", {"owner": "someone@example.com"}),
            ("unknown rigor", {"rigor": "extreme"}),
            ("document that is not a name", {"document": "../escape"}),
            ("override outside the document's shape",
             {"overrides": {"assignment": {"ship": {"1": 1}}}}),
            ("a string no response could carry", {"material": "\ud800"}),
        ):
            with self.subTest(refusal=label):
                self.refused(400, service.INVALID_STAFFING_SESSION, "POST",
                             self.session_path(record["id"]), changes)
                self.assertEqual(self.session_bytes(record["id"]), before)
        self.refused(400, service.INVALID_STAFFING_SESSION, "POST",
                     self.session_path(record["id"]), raw_body=b"{ not json")
        self.assertEqual(self.session_bytes(record["id"]), before)


# ---------------------------------------------------------------------------
# Resolution


class StaffingResolveRoute(StaffingApiTestCase):
    def setUp(self):
        StaffingApiTestCase.setUp(self)
        self.expect(200, "POST", "/api/staffing/documents", house_doc())
        self.record = self.create_session(
            work_area={"workspace_path": "/tmp/ws"})

    def resolve(self, body, session_id=None, headers=None):
        return self.expect(
            200, "POST",
            self.session_path(session_id or self.record["id"], "resolve"),
            body, headers=headers)

    def test_resolve_answer_defaults_fallback_and_error_mapping(self):
        """One request, exactly the router's three-value answer, and four
        refusals that keep their fixed status and token."""
        answered = self.resolve({"role": "implement"})
        self.assertEqual(set(answered), {"ok", "staffing"})
        self.assertEqual(
            answered["staffing"],
            stf.resolve(self.home, self.record["id"], "implement").answer)
        self.assertEqual(
            answered["staffing"],
            {"agent": "codex", "model": "gpt-5.6-terra", "effort": "xhigh"})

        # An omitted index is seat 1 and an omitted round is round 1: both
        # answer exactly as the explicit value does, and the seat and the
        # `step_up` round are visibly different answers.
        self.assertEqual(self.resolve({"role": "review"})["staffing"],
                         self.resolve({"role": "review",
                                       "index": 1, "round": 1})["staffing"])
        self.assertEqual(self.resolve({"role": "review"})["staffing"],
                         {"agent": "codex", "model": "gpt-5.6-terra",
                          "effort": "xhigh"})
        self.assertEqual(
            self.resolve({"role": "review", "index": 2})["staffing"],
            {"agent": "claude", "model": "claude-opus-5",
             "effort": "xhigh"})
        self.assertEqual(
            self.resolve({"role": "review", "round": 3})["staffing"],
            {"agent": "codex", "model": "gpt-5.6-terra", "effort": "max"})

        # `brief` travels with the request, changes no answer, and is
        # stored nowhere.
        before = self.session_bytes(self.record["id"])
        self.assertEqual(
            self.resolve({"role": "implement",
                          "brief": "rewrite the seal predicate"})["staffing"],
            answered["staffing"])
        self.assertEqual(self.session_bytes(self.record["id"]), before)

        # A material the document carries changes the answer; one it does
        # not carry is not a material at all.
        self.assertEqual(
            self.resolve({"role": "plan", "material": "prose"})["staffing"],
            {"agent": "claude", "model": "claude-opus-5",
             "effort": "xhigh"})
        self.assertEqual(
            self.resolve({"role": "plan", "material": "granite"})["staffing"],
            {"agent": "codex", "model": "gpt-5.6-terra", "effort": "xhigh"})

        # Admission: a request no vocabulary answers is 400, and never one
        # of the two surfaced conditions.
        for label, payload in (
            ("no role", {"index": 1}),
            ("unknown role", {"role": "ship"}),
            ("unknown key", {"role": "implement", "families": ["codex"]}),
            ("zero index", {"role": "implement", "index": 0}),
            ("boolean index", {"role": "implement", "index": True}),
            ("null round", {"role": "implement", "round": None}),
            ("non-string material", {"role": "implement", "material": 5}),
        ):
            with self.subTest(refusal=label):
                self.refused(400, service.INVALID_STAFFING_REQUEST, "POST",
                             self.session_path(self.record["id"], "resolve"),
                             payload)
        self.refused(400, service.INVALID_STAFFING_REQUEST, "POST",
                     self.session_path(self.record["id"], "resolve"),
                     raw_body=b"{ not json")

        # An unknown session is 404, before any body is looked at.
        self.refused(404, service.UNKNOWN_STAFFING_SESSION, "POST",
                     self.session_path("stf-nobody", "resolve"),
                     {"role": "implement"})
        self.refused(404, service.UNKNOWN_STAFFING_SESSION, "POST",
                     self.session_path("stf-nobody", "resolve"),
                     {"role": "ship"})

        # The two surfaced conditions keep their own tokens and statuses.
        # Nobody to call at all:
        nobody = self.create_session(
            families=[], work_area={"workspace_path": "/tmp/ws"})
        self.refused(503, stf.STAFFING_UNAVAILABLE, "POST",
                     self.session_path(nobody["id"], "resolve"),
                     {"role": "implement"})
        # A declared split this machine cannot honour — refused at the
        # RESOLUTION while the session itself still reads:
        single = self.create_session(
            families=["codex"], work_area={"workspace_path": "/tmp/ws"})
        self.refused(409, stf.DISTINCT_FAMILIES_UNSATISFIABLE, "POST",
                     self.session_path(single["id"], "resolve"),
                     {"role": "review"})
        read = self.expect(200, "GET", self.session_path(single["id"]))
        self.assertEqual(read["distinct_families_unsatisfiable"], ["review"])
        # ...and only the roles it affects.
        self.assertEqual(
            self.resolve({"role": "implement"},
                         session_id=single["id"])["staffing"],
            {"agent": "codex", "model": "gpt-5.6-terra", "effort": "xhigh"})

        # A referenced document that cannot be read is neither: the
        # mandatory fallback answers on `default`, and the answer carries no
        # note that it did. Absent and damaged alike, which is the one
        # condition the router's fallback answers.
        default_answer = dict(zip(
            ("agent", "model", "effort"),
            stf.base_staffing(stf.load(self.home, "default"), "medium",
                              "implement")))
        self.assertNotEqual(default_answer, answered["staffing"])
        self.expect(200, "POST", self.session_path(self.record["id"]),
                    {"document": "gone"})
        fell_back = self.resolve({"role": "implement"})
        self.assertEqual(set(fell_back), {"ok", "staffing"})
        self.assertEqual(fell_back["staffing"], default_answer)

        self.expect(200, "POST", self.session_path(self.record["id"]),
                    {"document": "house"})
        with open(os.path.join(stf.staffing_documents_dir(self.home),
                               "house.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        damaged = self.resolve({"role": "implement"})
        self.assertEqual(set(damaged), {"ok", "staffing"})
        self.assertEqual(damaged["staffing"], default_answer)
        # It is the RESOLUTION that falls back, not the session: reading the
        # session still succeeds and still names the document it references.
        read_back = self.expect(200, "GET",
                                self.session_path(self.record["id"]))
        self.assertEqual(read_back["session"]["document"], "house")

    def test_session_and_document_edits_reach_the_next_resolution(self):
        """Two equal requests around a live edit differ, and resolving
        writes nothing at all."""
        catalogue = self.catalogue_files()
        session_before = self.session_bytes(self.record["id"])
        first = self.resolve({"role": "implement"})["staffing"]

        # The SESSION's selection: a rigor change reaches the next call.
        self.expect(200, "POST", self.session_path(self.record["id"]),
                    {"rigor": "low"})
        second = self.resolve({"role": "implement"})["staffing"]
        self.assertEqual(
            second,
            {"agent": "codex", "model": "gpt-5.6-luna", "effort": "low"})
        self.assertNotEqual(second, first)

        # The referenced DOCUMENT: a replacement reaches it the same way,
        # with no second write anywhere.
        moved = house_doc()
        moved["assignment"]["implement"] = {"1": 2}
        self.expect(200, "POST", "/api/staffing/documents", moved)
        third = self.resolve({"role": "implement"})["staffing"]
        self.assertEqual(
            third,
            {"agent": "claude", "model": "claude-sonnet-5", "effort": "low"})
        self.assertNotEqual(third, second)

        # Resolution keeps no history and adds no record: the only byte that
        # moved is the one the edit moved, and the answer is three keys.
        self.assertEqual(self.catalogue_files(), catalogue)
        self.assertNotEqual(self.session_bytes(self.record["id"]),
                            session_before)
        stable = self.session_bytes(self.record["id"])
        for _repeat in range(3):
            answer = self.resolve({"role": "implement"})["staffing"]
            self.assertEqual(list(answer), ["agent", "model", "effort"])
        self.assertEqual(self.session_bytes(self.record["id"]), stable)
        self.assertEqual(self.catalogue_files(), catalogue)


# ---------------------------------------------------------------------------
# The run's binding, as the run detail shows it


class RunSummaryStaffingSession(StaffingApiTestCase):
    def launch(self, name, **extra):
        payload = {
            "workspace": self.workspace(name), "goal": "staffed goal",
            "autostart": False, "config": {"docs_dir": "docs"},
        }
        payload.update(extra)
        return self.expect(201, "POST", "/api/runs", payload)["run"]

    def state_path_of(self, run):
        return registry.get(registry.load(self.home), run["id"])["state_path"]

    def test_run_summary_exposes_only_the_staffing_session_id(self):
        """A bound run's authorized detail names its session; an unbound one
        gains no invented session, and neither embeds a copy."""
        run = self.launch("ws-bound")
        bound = st.load(self.state_path_of(run))["staffing_session"]
        detail = self.expect(200, "GET", "/api/runs/%s" % run["id"])
        self.assertEqual(detail["summary"]["staffing_session"], bound)

        # The ID and nothing else: no session record and no document rides
        # anywhere inside the detail.
        for node in _objects(detail):
            self.assertFalse(SESSION_RECORD_KEYS <= set(node), node)
            self.assertFalse(DOCUMENT_RECORD_KEYS <= set(node), node)

        # It is the same live session everyone else uses, reached through
        # the same route.
        self.assertEqual(
            self.expect(200, "GET", self.session_path(bound))["session"],
            stf.read_session(self.home, bound))

        # An attached run adopts its state as it is: no key, and nothing
        # invented for it.
        attached_ws = self.workspace("ws-attached")
        drv.init_run("attached", attached_ws,
                     state_path=drv.default_state_path(attached_ws))
        attached = self.expect(201, "POST", "/api/runs", {
            "workspace": attached_ws, "attach": True, "autostart": False,
        })["run"]
        self.assertIsNone(
            st.load(self.state_path_of(attached)).get("staffing_session"))
        detail = self.expect(200, "GET", "/api/runs/%s" % attached["id"])
        self.assertNotIn("staffing_session", detail["summary"])

        # The existing run-detail access check is still the whole
        # authorization: an unknown run is 404 and a run this caller may not
        # see is 403, session or no session.
        member = self.member()
        status, body = self.request("GET", "/api/runs/no-such-run")
        self.assertEqual(status, 404, body)
        self.refused(403, service.FORBIDDEN, "GET",
                     "/api/runs/%s" % run["id"], headers=member)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
