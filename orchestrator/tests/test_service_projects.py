"""Service API tests for the standing project surface (slice 7): project
and work-area CRUD over the sealed stores, the (project, work_area) launch
binding with validation-as-reconcile, config precedence at bound launches,
run-status project handles, and the change-driven run:<run_id>/status
projection.

Conventions of test_service_api.py: a real service.make_server(home, 0) in
a thread over an isolated tempdir home (never ~/.impl_roadmap), exercised
through urllib with "autostart": false everywhere; stores are seeded
through the API itself. Where lifecycle observation needs run progress,
states advance via the sealed driver over MockRunner (the test_run_init
convention). Standard library only.
"""

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from orchestrator import access
from orchestrator import driver as drv
from orchestrator import kvstore, projects, registry, runners, service, workareas
from orchestrator import state as st
from orchestrator.tests.test_driver_mock import ok, step, write_file

GOAL = "Exercise the standing project surface"

# Both default handles carry spaces: every route in the file then
# round-trips URL-encoded Slice 2-valid values by construction.
PROJECT = "life prod"
AREA = "main area"



def _ws_states(workspace):
    """All run states under `workspace`, both layouts (existence probe:
    the per-milestone layout moved states from <ws>/.orchestrator into
    <milestone>/.run, so a bare default_state_path check goes stale)."""
    out = []
    legacy = drv.default_state_path(workspace)
    if os.path.isfile(legacy):
        out.append(legacy)
    for root, dirs, files in os.walk(workspace):
        if os.path.basename(root) == ".run" and "state.json" in files:
            out.append(os.path.join(root, "state.json"))
            dirs[:] = []
    return out


def _ws_state(workspace):
    """The single run state under `workspace`, either layout."""
    states = _ws_states(workspace)
    assert len(states) == 1, "expected exactly one state, got %r" % states
    return states[0]


def draft_step():
    """One scripted skeleton draft: the MockRunner step that proves a
    bound run is drivable and moves the summary for change-driven
    projection tests."""
    return step(
        "draft_skeleton",
        ok(
            "draft_skeleton",
            artifact="docs/skeleton.md",
            slices=[{"id": 1, "title": "One"}],
        ),
        # The service config inherits the skeletoner default (claude), so a
        # real bound run drafts the skeleton with claude.
        family="claude",
        side_effect=write_file("docs/skeleton.md", "# Skeleton\n"),
    )


def policy_object(policy_id="lpc-reuse-audit"):
    """A minimal valid sealed policy value (slice-03 shape)."""
    return {
        "id": policy_id,
        "version": 1,
        "enabled": True,
        "scope": {"kinds": ["implement"], "unit_kinds": ["slice_impl"]},
        "prompt": "Enumerate the reuse inventory before inventing.",
        "contract": {
            "field": "reuse_audit",
            "required": True,
            "entry": {"source": {"type": "string"}},
            "checks": [],
        },
    }


class ProjectsServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-projects-test-")
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.start_server()

    # -- server lifecycle (restartable for persistence tests) ---------------

    def start_server(self):
        server = service.make_server(self.home, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stopped = []

        def stop():
            if stopped:
                return
            stopped.append(True)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.addCleanup(stop)
        self._stop_server = stop
        self.base = "http://127.0.0.1:%d" % server.server_address[1]

    def restart_server(self):
        """A fresh service instance over the same home."""
        self._stop_server()
        self.start_server()

    # -- request helpers -----------------------------------------------------

    def request_json(self, method, path, payload=None, headers=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    def expect(self, expected_status, method, path, payload=None):
        status, body = self.request_json(method, path, payload=payload)
        self.assertEqual(status, expected_status, body)
        if 200 <= expected_status < 300:
            # The service keeps its one top-level envelope everywhere.
            self.assertIs(body.get("ok"), True, body)
        return body

    def refused(self, expected_status, expected_error, method, path,
                payload=None):
        """A refusal's error body is the reason token, verbatim."""
        body = self.expect(expected_status, method, path, payload=payload)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], expected_error)
        return body

    @staticmethod
    def q(segment):
        return urllib.parse.quote(segment, safe="")

    def project_path(self, slug=PROJECT, *suffix):
        return "/".join(["/api/projects", self.q(slug)] + [
            part if part in ("work-areas", "meta") else self.q(part)
            for part in suffix
        ])

    @staticmethod
    def remote_headers(email, marker=access.REMOTE_MARKER):
        return {
            "Host": "example.ngrok-free.dev",
            access.REMOTE_HEADER: marker,
            access.USER_HEADER: email,
        }

    # -- fixture helpers -----------------------------------------------------

    def repo(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path)
        subprocess.run(["git", "init", "-q", path], check=True)
        return path

    def plain_dir(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path)
        return path

    def create_project(self, slug=PROJECT, defaults=None):
        payload = {"slug": slug}
        if defaults is not None:
            payload["defaults"] = defaults
        return self.expect(201, "POST", "/api/projects", payload)["project"]

    def declare(self, primary, slug=PROJECT, name=AREA, additional=None,
                **extra):
        payload = {"name": name, "primary_path": primary}
        if additional is not None:
            payload["additional_paths"] = additional
        payload.update(extra)
        return self.expect(
            200, "POST", self.project_path(slug, "work-areas"), payload
        )["work_area"]

    def wa_record(self, slug=PROJECT, name=AREA):
        body = self.expect(
            200, "GET", self.project_path(slug, "work-areas", name)
        )
        return body["work_area"]["record"]

    def launch(self, slug=PROJECT, area=AREA, expect=201, **extra):
        launch_config = {
            "guarantee_calibration": {"enabled": False},
        }
        launch_config.update(extra.pop("config", {}) or {})
        payload = {
            "project": slug,
            "work_area": area,
            "goal": GOAL,
            "autostart": False,
            "config": launch_config,
        }
        payload.update(extra)
        status, body = self.request_json("POST", "/api/runs", payload)
        if expect is not None:
            self.assertEqual(status, expect, body)
        return status, body

    # -- store access (assertion-side reads) ---------------------------------

    def store_dir(self, slug=PROJECT):
        return os.path.join(registry.projects_base(self.home), slug)

    def kv_file(self, slug=PROJECT):
        return os.path.join(self.store_dir(slug), kvstore.STORE_FILENAME)

    def envelopes(self, slug=PROJECT):
        return kvstore.RevisionEnvelopeStore(
            kvstore.LocalKVClient(self.store_dir(slug))
        )

    def make_ready(self, primary, slug=PROJECT, name=AREA, additional=None):
        """Take a declared area pending -> ready through the sealed seam,
        exactly as a bound launch's confirm does."""
        store = self.sealed_store(slug)
        record = store.read(name).value
        result = store.confirm(
            name,
            record["primary"],
            record["additional"] if additional is None else additional,
            service._executor_id(self.home),
        )
        self.assertTrue(result.ok, result.reason)
        return result

    def sealed_store(self, slug=PROJECT):
        return workareas.WorkAreaStore(
            registry.projects_base(self.home), slug
        )

    @staticmethod
    def run_key(run_id):
        return kvstore.KeyBuilder().run_status(run_id)

    def run_entries(self, slug=PROJECT):
        """All run:* keys in the project's store (tombstones included)."""
        prefix = "%s/run:" % kvstore.DEFAULT_NAMESPACE
        client = kvstore.LocalKVClient(self.store_dir(slug))
        return [
            item["key"]
            for item in client.list_entries(prefix=prefix)["items"]
        ]

    def corrupt_raw_record(self, slug=PROJECT, name=AREA):
        """Write a raw work-area value outside the agent_99 domain."""
        store = self.sealed_store(slug)
        store.client.put(
            kvstore.raw_work_area_key(name),
            {kvstore.Atom("name"): name, kvstore.Atom("version"): 1},
        )

    def assert_nothing_created(self, primary, slug=PROJECT):
        """The refusal postcondition: no state file, no registry entry,
        no projection entry."""
        self.assertFalse(
            bool(_ws_states(primary))
        )
        body = self.expect(200, "GET", "/api/runs")
        self.assertEqual(body["runs"], [])
        self.assertEqual(self.run_entries(slug), [])

    def drive(self, primary, steps=None):
        """Advance the run's state through the sealed driver (MockRunner)."""
        mock_runner = runners.MockRunner(steps or [draft_step()])
        driver = drv.Driver(
            _ws_state(primary), runner=mock_runner
        )
        driver.step()
        self.assertEqual(mock_runner.script, [])


# ---------------------------------------------------------------------------
# Remote Google identity and per-project authorization


class ProjectAccessApiTest(ProjectsServiceTestCase):
    def test_admin_assigns_users_and_member_sees_only_assigned_project(self):
        self.create_project(PROJECT)
        self.create_project("other")
        self.expect(
            200, "POST", self.project_path(PROJECT, "users"),
            {"users": [access.USER_EMAILS[0]]},
        )

        member = self.remote_headers(access.USER_EMAILS[0])
        status, auth = self.request_json("GET", "/api/access", headers=member)
        self.assertEqual(status, 200, auth)
        self.assertEqual(auth["user"], access.USER_EMAILS[0])
        self.assertFalse(auth["admin"])
        self.assertNotIn("users", auth)

        status, body = self.request_json("GET", "/api/projects", headers=member)
        self.assertEqual(status, 200, body)
        self.assertEqual([p["slug"] for p in body["projects"]], [PROJECT])
        status, body = self.request_json(
            "GET", self.project_path("other"), headers=member
        )
        self.assertEqual((status, body["error"]), (403, service.FORBIDDEN))

        # Membership permits run work, never project rebinding/configuration.
        # Otherwise a member could point the project at another host path and
        # make the project boundary meaningless.
        for method, path, payload in (
            ("GET", self.project_path(PROJECT, "users"), None),
            ("POST", self.project_path(PROJECT), {"defaults": {}}),
            ("POST", "/api/projects", {"slug": "forbidden"}),
            ("DELETE", self.project_path(PROJECT), None),
            ("GET", "/api/fs", None),
            ("GET", "/api/recents", None),
        ):
            with self.subTest(method=method, path=path):
                status, body = self.request_json(
                    method, path, payload, headers=member
                )
                self.assertEqual((status, body["error"]),
                                 (403, service.FORBIDDEN))

    def test_members_browse_their_own_work_area_and_nothing_else(self):
        # Unscoped /api/fs stays administrative (asserted above); a
        # project+work_area scope lets a member pick a brainstorming target
        # inside their area without handing them the operator's machine.
        primary = self.repo("member-area")
        os.makedirs(os.path.join(primary, "docs"))
        with open(os.path.join(primary, "docs", "note.md"), "w") as fh:
            fh.write("x")
        self.create_project()
        self.declare(primary)
        # Only a READY area is browsable: the picker must never reach into
        # one the product itself would refuse to bind.
        self.make_ready(primary)
        self.create_project("other")
        other_primary = self.repo("other-area")
        self.declare(other_primary, slug="other")
        self.make_ready(other_primary, slug="other")
        self.expect(
            200, "POST", self.project_path(PROJECT, "users"),
            {"users": [access.USER_EMAILS[0]]},
        )
        member = self.remote_headers(access.USER_EMAILS[0])
        scope = "project=%s&work_area=%s" % (
            urllib.parse.quote(PROJECT), urllib.parse.quote(AREA),
        )

        status, body = self.request_json(
            "GET", "/api/fs?%s&mode=dir" % scope, headers=member
        )
        self.assertEqual(status, 200, body)
        # The DECLARED root is what surfaces (containment resolves symlinks
        # internally, but a member sees the path their area declares).
        self.assertEqual(body["path"], os.path.abspath(primary))
        self.assertIn("docs", body["dirs"])
        # The area root is the ceiling: no "up" out of it.
        self.assertIsNone(body["parent"])

        status, body = self.request_json(
            "GET",
            "/api/fs?%s&mode=file&path=%s"
            % (scope, urllib.parse.quote(os.path.join(primary, "docs"))),
            headers=member,
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["files"], ["note.md"])

        # Asking for somewhere else lands back on the area, never outside.
        status, body = self.request_json(
            "GET",
            "/api/fs?%s&path=%s" % (scope, urllib.parse.quote(self.tmp.name)),
            headers=member,
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["path"], os.path.abspath(primary))

        # A project the member is not assigned to refuses, scope or not.
        status, body = self.request_json(
            "GET",
            "/api/fs?project=other&work_area=%s" % urllib.parse.quote(AREA),
            headers=member,
        )
        self.assertEqual((status, body["error"]), (403, service.FORBIDDEN))

        # And the whole-host form is still administrative for a member.
        status, body = self.request_json("GET", "/api/fs", headers=member)
        self.assertEqual((status, body["error"]), (403, service.FORBIDDEN))

    def test_runs_are_filtered_and_guarded_by_project_membership(self):
        for slug in (PROJECT, "other"):
            self.create_project(slug)
            self.declare(self.repo("repo-" + slug.replace(" ", "-")), slug=slug)
        self.expect(
            200, "POST", self.project_path(PROJECT, "users"),
            {"users": [access.USER_EMAILS[1]]},
        )
        member = self.remote_headers(access.USER_EMAILS[1])
        status, allowed = self.request_json(
            "POST", "/api/runs",
            {"project": PROJECT, "work_area": AREA, "goal": GOAL,
             "name": "allowed", "autostart": False},
            headers=member,
        )
        self.assertEqual(status, 201, allowed)
        _, hidden = self.launch("other", name="hidden")

        status, body = self.request_json("GET", "/api/runs", headers=member)
        self.assertEqual(status, 200, body)
        self.assertEqual(
            [run["id"] for run in body["runs"]], [allowed["run"]["id"]]
        )
        status, body = self.request_json(
            "GET", "/api/runs/" + hidden["run"]["id"], headers=member
        )
        self.assertEqual((status, body["error"]), (403, service.FORBIDDEN))
        status, body = self.request_json(
            "POST", "/api/runs",
            {"project": "other", "work_area": AREA, "goal": GOAL,
             "name": "forbidden", "autostart": False},
            headers=member,
        )
        self.assertEqual((status, body["error"]), (403, service.FORBIDDEN))

    def test_run_visibility_uses_durable_binding_before_reading_state(self):
        for slug in (PROJECT, "other"):
            self.create_project(slug)
            self.declare(self.repo("repo-" + slug.replace(" ", "-")), slug=slug)
        self.expect(
            200, "POST", self.project_path(PROJECT, "users"),
            {"users": [access.USER_EMAILS[1]]},
        )
        member = self.remote_headers(access.USER_EMAILS[1])
        _, allowed = self.launch(PROJECT, name="allowed")
        _, hidden = self.launch("other", name="hidden")
        hidden_id = hidden["run"]["id"]
        hidden_path = registry.get(
            registry.load(self.home), hidden_id
        )["state_path"]
        real_load = service.load_summary

        def forged_summary(path):
            summary = real_load(path)
            if path == hidden_path:
                summary = dict(summary)
                summary["project"] = PROJECT
            return summary

        with mock.patch.object(service, "load_summary", side_effect=forged_summary):
            status, body = self.request_json("GET", "/api/runs", headers=member)
        self.assertEqual(status, 200, body)
        self.assertEqual(
            [run["id"] for run in body["runs"]], [allowed["run"]["id"]]
        )

    def test_remote_requests_fail_closed_without_valid_injected_identity(self):
        for headers in (
            {"Host": "example.ngrok-free.dev"},
            self.remote_headers("unknown@example.com"),
            self.remote_headers(access.ADMIN_EMAIL, marker="spoofed"),
        ):
            with self.subTest(headers=headers):
                status, body = self.request_json(
                    "GET", "/api/access", headers=headers
                )
                self.assertEqual((status, body["error"]),
                                 (403, service.FORBIDDEN))

    def test_remote_admin_has_all_projects_and_manages_membership(self):
        self.create_project(PROJECT)
        self.create_project("other")
        admin = self.remote_headers(access.ADMIN_EMAIL)
        status, body = self.request_json("GET", "/api/projects", headers=admin)
        self.assertEqual(status, 200, body)
        self.assertEqual(
            [project["slug"] for project in body["projects"]],
            [PROJECT, "other"],
        )
        status, body = self.request_json(
            "POST", self.project_path(PROJECT, "users"),
            {"users": list(access.USER_EMAILS)}, headers=admin,
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["admin"], access.ADMIN_EMAIL)
        self.assertEqual(body["users"], list(access.USER_EMAILS))


# AC1 + AC2: project lifecycle, GET /api/projects, fail-closed markers


class TestProjectSurface(ProjectsServiceTestCase):
    def test_create_list_read_roundtrip_with_encoded_slug(self):
        defaults = {"docs_dir": "notes/{slug}"}
        created = self.create_project(defaults=defaults)
        self.assertEqual(
            created,
            {
                "slug": PROJECT,
                "work_areas": [],
                "policy": [],
                "defaults": defaults,
            },
        )
        body = self.expect(200, "GET", "/api/projects")
        self.assertEqual(body["projects"], [created])
        body = self.expect(200, "GET", self.project_path())
        self.assertEqual(body["project"], created)

    def test_declaration_materializes_readable_zero_entry_store(self):
        self.create_project()
        with open(self.kv_file(), "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"entries": {}})
        # Readable through the sealed store: an EMPTY project, not an
        # error and not a bare directory.
        listed = self.sealed_store().list_records()
        self.assertTrue(listed.ok)
        self.assertEqual(listed.value, [])

    def test_invalid_slug_refuses_invalid_project(self):
        for bad in ("a/b", "..", "   ", ""):
            self.refused(400, "invalid_project", "POST", "/api/projects",
                         {"slug": bad})
        self.refused(400, "invalid_project", "GET",
                     "/api/projects/%s" % self.q(".."))

    def test_duplicate_create_conflicts_without_mutation(self):
        self.create_project(defaults={"docs_dir": "a"})
        self.refused(409, "project_exists", "POST", "/api/projects",
                     {"slug": PROJECT, "defaults": {"docs_dir": "b"}})
        body = self.expect(200, "GET", self.project_path())
        self.assertEqual(body["project"]["defaults"], {"docs_dir": "a"})

    def test_defaults_update_clear_and_invalid(self):
        self.create_project()
        body = self.expect(200, "POST", self.project_path(),
                           {"defaults": {"git": {"enabled": False}}})
        self.assertEqual(
            body["project"]["defaults"], {"git": {"enabled": False}}
        )
        # null clears; the entry then omits the key entirely.
        body = self.expect(200, "POST", self.project_path(),
                           {"defaults": None})
        self.assertNotIn("defaults", body["project"])
        # Invalid values refuse with the sealed reason; nothing changes.
        for bad in (["list"], "text", 7):
            self.refused(400, "invalid_defaults", "POST",
                         self.project_path(), {"defaults": bad})
        self.refused(400, "invalid_defaults", "POST", self.project_path(),
                     {})  # the update surface demands the key
        self.refused(400, "invalid_defaults", "POST", "/api/projects",
                     {"slug": "other", "defaults": ["list"]})

    def test_defaults_update_validates_project_before_body(self):
        self.create_project()
        self.refused(400, "invalid_project", "POST",
                     self.project_path("bad/slug"), {"defaults": ["list"]})
        self.refused(404, "unknown_project", "POST",
                     self.project_path("ghost"), {"defaults": ["list"]})

    def test_unknown_project_404_on_every_project_bound_route(self):
        for method, path, payload in (
            ("GET", self.project_path("ghost"), None),
            ("POST", self.project_path("ghost"), {"defaults": None}),
            ("DELETE", self.project_path("ghost"), None),
            ("POST", self.project_path("ghost", "work-areas"),
             {"name": AREA, "primary_path": "/x"}),
            ("GET", self.project_path("ghost", "work-areas", AREA), None),
            ("POST", self.project_path("ghost", "work-areas", AREA),
             {"display_name": "X"}),
            ("DELETE", self.project_path("ghost", "work-areas", AREA), None),
            ("GET", self.project_path("ghost", "work-areas", AREA, "meta"),
             None),
            ("POST", self.project_path("ghost", "work-areas", AREA, "meta"),
             {"reuse_sources": []}),
        ):
            self.refused(404, "unknown_project", method, path, payload)

    def test_restart_persistence(self):
        self.create_project(defaults={"docs_dir": "notes/{slug}"})
        self.restart_server()
        body = self.expect(200, "GET", "/api/projects")
        self.assertEqual(
            body["projects"],
            [{
                "slug": PROJECT,
                "work_areas": [],
                "policy": [],
                "defaults": {"docs_dir": "notes/{slug}"},
            }],
        )

    def test_fail_closed_listing_keeps_healthy_projects(self):
        self.create_project("healthy")
        self.create_project("corrupt")
        self.create_project("lost")
        with open(self.kv_file("corrupt"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        os.unlink(self.kv_file("lost"))
        body = self.expect(200, "GET", "/api/projects")
        by_slug = {p["slug"]: p for p in body["projects"]}
        self.assertEqual(
            by_slug["healthy"],
            {"slug": "healthy", "work_areas": [], "policy": []},
        )
        # Error entries carry the reason and no partial record.
        self.assertEqual(
            by_slug["corrupt"],
            {"slug": "corrupt", "error": {"reason": "malformed_store"}},
        )
        self.assertEqual(
            by_slug["lost"],
            {"slug": "lost", "error": {"reason": "missing_store"}},
        )
        # Single-project reads fail closed with the same reasons.
        self.refused(500, "malformed_store", "GET",
                     self.project_path("corrupt"))
        self.refused(500, "missing_store", "GET", self.project_path("lost"))

    def test_malformed_work_area_meta_fails_project_not_listing(self):
        self.create_project("healthy")
        self.declare(self.plain_dir("healthy-root"), slug="healthy")
        self.create_project("bad-meta")
        self.declare(self.plain_dir("bad-meta-root"), slug="bad-meta")

        store = self.sealed_store("bad-meta")
        store.client.put(store.keys.work_area_meta(AREA),
                         {"not": "an envelope"})

        body = self.expect(200, "GET", "/api/projects")
        by_slug = {p["slug"]: p for p in body["projects"]}
        self.assertNotIn("error", by_slug["healthy"])
        self.assertEqual(
            by_slug["bad-meta"],
            {"slug": "bad-meta", "error": {"reason": "malformed_store"}},
        )
        self.refused(500, "malformed_store", "GET",
                     self.project_path("bad-meta"))

    def test_malformed_work_area_record_fails_the_project_closed(self):
        self.create_project()
        self.declare(self.plain_dir("wa-root"))
        self.corrupt_raw_record()
        body = self.expect(200, "GET", "/api/projects")
        self.assertEqual(
            body["projects"],
            [{"slug": PROJECT, "error": {"reason": "malformed_work_area"}}],
        )


# ---------------------------------------------------------------------------
# AC3 + AC4: work-area CRUD through the sealed store; meta beside the record


class TestWorkAreaCrud(ProjectsServiceTestCase):
    def setUp(self):
        super().setUp()
        self.create_project()
        self.primary = self.plain_dir("primary-root")
        self.lib = self.plain_dir("lib-root")

    def test_declare_returns_full_public_domain_at_v1_pending(self):
        view = self.declare(self.primary, additional=[self.lib])
        self.assertIsNone(view["meta"])
        self.assertEqual(
            view["record"],
            {
                "name": AREA,
                "display_name": AREA,
                "primary": {"path": self.primary, "device": "local"},
                "additional": [{"path": self.lib, "device": "local"}],
                "executor_id": view["record"]["executor_id"],
                "version": 1,
                "status": "pending",
            },
        )
        self.assertTrue(view["record"]["executor_id"].strip())

    def test_redeclare_semantics_ride_the_sealed_store(self):
        self.declare(self.primary)
        # Different content: the sealed content-update — version+1, back
        # to pending.
        view = self.declare(self.primary, additional=[self.lib])
        self.assertEqual(
            (view["record"]["version"], view["record"]["status"]),
            (2, "pending"),
        )
        # Identical content: the sealed no-op.
        view = self.declare(self.primary, additional=[self.lib])
        self.assertEqual(
            (view["record"]["version"], view["record"]["status"]),
            (2, "pending"),
        )

    def test_relabel_updates_display_name_and_preserves_version(self):
        self.declare(self.primary)
        body = self.expect(
            200, "POST", self.project_path(PROJECT, "work-areas", AREA),
            {"display_name": "Main / Chat surface"},
        )
        record = body["work_area"]["record"]
        self.assertEqual(record["display_name"], "Main / Chat surface")
        self.assertEqual(record["version"], 1)  # label-only edit (I3)
        self.refused(400, "invalid_display_name", "POST",
                     self.project_path(PROJECT, "work-areas", AREA),
                     {"display_name": "   "})

    def test_delete_tombstones_record_and_sibling_meta(self):
        meta = {
            "reuse_sources": [{
                "root": self.lib,
                "inventory": "packages/",
                "registry": "docs/registry.md",
                "consumption": "path dep",
            }]
        }
        self.declare(self.primary)
        self.expect(200, "POST",
                    self.project_path(PROJECT, "work-areas", AREA, "meta"),
                    meta)
        body = self.expect(
            200, "DELETE", self.project_path(PROJECT, "work-areas", AREA)
        )
        self.assertEqual(
            body["work_area"], {"name": AREA, "deleted": True, "version": 2}
        )
        # Reads and listings now report the name unknown.
        self.refused(404, "unknown_work_area", "GET",
                     self.project_path(PROJECT, "work-areas", AREA))
        listed = self.expect(200, "GET", self.project_path())
        self.assertEqual(listed["project"]["work_areas"], [])
        self.refused(404, "unknown_work_area", "GET",
                     self.project_path(PROJECT, "work-areas", AREA, "meta"))
        # Re-declaring the same name starts with NO retained meta.
        view = self.declare(self.primary)
        self.assertEqual(
            (view["record"]["version"], view["record"]["status"]),
            (1, "pending"),
        )
        self.assertIsNone(view["meta"])
        body = self.expect(
            200, "GET",
            self.project_path(PROJECT, "work-areas", AREA, "meta"),
        )
        self.assertIsNone(body["meta"])

    def test_delete_does_not_raw_tombstone_before_meta_is_readable(self):
        meta = {
            "reuse_sources": [{
                "root": self.lib,
                "inventory": "packages/",
                "registry": "docs/registry.md",
                "consumption": "path dep",
            }]
        }
        self.declare(self.primary)
        store = self.sealed_store()
        meta_key = store.keys.work_area_meta(AREA)
        store.client.put(meta_key, {"not": "an envelope"})

        self.refused(500, "malformed_store", "DELETE",
                     self.project_path(PROJECT, "work-areas", AREA))
        still_live = store.read(AREA)
        self.assertTrue(still_live.ok)
        self.assertEqual(still_live.value["status"], "pending")

        store.client.put(
            meta_key, {"revision": 1, "value": meta, "deleted?": False}
        )
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        view = self.declare(self.primary)
        self.assertIsNone(view["meta"])

    def test_delete_raw_tombstone_failure_keeps_standing_meta(self):
        # The raw tombstone is the FIRST write: a failed delete leaves the
        # record live WITH its reuse-source roles — never a live record
        # whose standing meta was silently erased.
        meta = {
            "reuse_sources": [{
                "root": self.lib,
                "inventory": "packages/",
                "registry": "docs/registry.md",
                "consumption": "path dep",
            }]
        }
        self.declare(self.primary)
        self.expect(200, "POST",
                    self.project_path(PROJECT, "work-areas", AREA, "meta"),
                    meta)
        store = self.sealed_store()
        raw_key = store.keys.raw_work_area(AREA)
        original_set_entry = kvstore.LocalKVClient._set_entry

        def fail_raw_write(doc, key, value, rev):
            if key == raw_key:
                raise RuntimeError("store hiccup")
            return original_set_entry(doc, key, value, rev)

        with mock.patch.object(kvstore.LocalKVClient, "_set_entry",
                               side_effect=fail_raw_write):
            self.refused(500, "malformed_store", "DELETE",
                         self.project_path(PROJECT, "work-areas", AREA))

        still_live = store.read(AREA)
        self.assertTrue(still_live.ok)
        self.assertEqual(still_live.value["status"], "pending")
        self.assertEqual(store.read_meta(AREA)["value"], meta)

        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        self.assertIsNone(self.declare(self.primary)["meta"])

    def test_delete_meta_write_failure_never_resurrects_meta(self):
        # The meta tombstone lands LAST: if it fails after the raw
        # tombstone landed, the name reads unknown, the fault is reported,
        # and the orphaned meta is cleared by the next declare — stale
        # roles never ride a live record.
        meta = {
            "reuse_sources": [{
                "root": self.lib,
                "inventory": "packages/",
                "registry": "docs/registry.md",
                "consumption": "path dep",
            }]
        }
        self.declare(self.primary)
        self.expect(200, "POST",
                    self.project_path(PROJECT, "work-areas", AREA, "meta"),
                    meta)
        store = self.sealed_store()
        meta_key = store.keys.work_area_meta(AREA)
        original_set_entry = kvstore.LocalKVClient._set_entry

        def fail_meta_write(doc, key, value, rev):
            if key == meta_key:
                raise RuntimeError("store hiccup")
            return original_set_entry(doc, key, value, rev)

        with mock.patch.object(kvstore.LocalKVClient, "_set_entry",
                               side_effect=fail_meta_write):
            self.refused(500, "malformed_store", "DELETE",
                         self.project_path(PROJECT, "work-areas", AREA))

        # The raw tombstone landed (the record is gone); the orphaned meta
        # survives in the store but no live-record surface can read it.
        self.refused(404, "unknown_work_area", "GET",
                     self.project_path(PROJECT, "work-areas", AREA))
        self.refused(404, "unknown_work_area", "GET",
                     self.project_path(PROJECT, "work-areas", AREA, "meta"))
        self.assertEqual(store.read_meta(AREA)["value"], meta)

        # Re-declaring the same name clears the orphan first: no stale
        # roles resurrect onto the fresh incarnation.
        view = self.declare(self.primary)
        self.assertEqual(
            (view["record"]["version"], view["record"]["status"]),
            (1, "pending"),
        )
        self.assertIsNone(view["meta"])
        self.assertFalse(store.read_meta(AREA)["exists?"])

    def test_invalid_inputs_refuse_with_sealed_reasons_verbatim(self):
        self.refused(400, "invalid_name", "POST",
                     self.project_path(PROJECT, "work-areas"),
                     {"name": "a/b", "primary_path": self.primary})
        self.refused(400, "invalid_descriptor", "POST",
                     self.project_path(PROJECT, "work-areas"),
                     {"name": AREA, "primary_path": "relative/path"})
        self.refused(400, "invalid_descriptor", "POST",
                     self.project_path(PROJECT, "work-areas"),
                     {"name": AREA, "primary_path": self.primary,
                      "additional_paths": "not-a-list"})
        self.refused(400, "duplicate_root", "POST",
                     self.project_path(PROJECT, "work-areas"),
                     {"name": AREA, "primary_path": self.primary,
                      "additional_paths": [self.primary]})
        self.refused(404, "unknown_work_area", "GET",
                     self.project_path(PROJECT, "work-areas", "ghost"))

    def test_corrupt_declared_store_refuses_work_area_routes_stably(self):
        self.declare(self.primary)
        with open(self.kv_file(), "w", encoding="utf-8") as fh:
            fh.write("{ not json")

        for method, path, payload in (
            ("POST", self.project_path(PROJECT, "work-areas"),
             {"name": "other", "primary_path": self.primary}),
            ("GET", self.project_path(PROJECT, "work-areas", AREA), None),
            ("POST", self.project_path(PROJECT, "work-areas", AREA),
             {"display_name": "Renamed"}),
            ("DELETE", self.project_path(PROJECT, "work-areas", AREA),
             None),
            ("GET", self.project_path(PROJECT, "work-areas", AREA, "meta"),
             None),
            ("POST", self.project_path(PROJECT, "work-areas", AREA, "meta"),
             {"reuse_sources": []}),
        ):
            with self.subTest(method=method, path=path):
                self.refused(500, "malformed_store", method, path, payload)

        status, body = self.launch(expect=None)
        self.assertEqual((status, body["error"]), (500, "malformed_store"))

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "root can read a chmod-000 store",
    )
    def test_unreadable_store_refuses_work_area_route_stably(self):
        # The store is made genuinely unreadable rather than mocked at the
        # loader: a store whose CONTENT is unchanged is exactly the case a
        # parsed-document cache could answer from memory, and refusing must
        # not depend on having missed the cache.
        self.declare(self.primary)
        path = self.kv_file()
        self.expect(200, "GET", self.project_path(PROJECT, "work-areas", AREA))
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        self.refused(500, "unreadable_store", "GET",
                     self.project_path(PROJECT, "work-areas", AREA))

    def test_name_with_spaces_round_trips_url_encoded(self):
        # PROJECT and AREA both carry spaces; the fixture helpers already
        # encode every segment — this pins the encoded round-trip end to
        # end on the nested routes.
        self.assertIn(" ", PROJECT)
        self.assertIn(" ", AREA)
        self.declare(self.primary)
        self.assertEqual(self.wa_record()["name"], AREA)
        body = self.expect(
            200, "POST", self.project_path(PROJECT, "work-areas", AREA),
            {"display_name": "Renamed"},
        )
        self.assertEqual(body["work_area"]["record"]["display_name"],
                         "Renamed")
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))

    def test_meta_roundtrip_beside_the_record_never_inside(self):
        self.declare(self.primary)
        meta = {
            "reuse_sources": [{
                "root": self.lib,
                "inventory": "packages/",
                "registry": "docs/registry.md",
                "consumption": "submodule + path dep",
            }]
        }
        # The POST body is the raw sealed value, not wrapped in "meta".
        body = self.expect(
            200, "POST",
            self.project_path(PROJECT, "work-areas", AREA, "meta"), meta,
        )
        self.assertEqual(body["meta"], meta)
        body = self.expect(
            200, "GET",
            self.project_path(PROJECT, "work-areas", AREA, "meta"),
        )
        self.assertEqual(body["meta"], meta)
        # Project reads carry it BESIDE the untouched Slice 2 record.
        listed = self.expect(200, "GET", self.project_path())
        (view,) = listed["project"]["work_areas"]
        self.assertEqual(view["meta"], meta)
        self.assertNotIn("meta", view["record"])
        self.assertNotIn("reuse_sources", view["record"])

    def test_meta_refusals(self):
        self.declare(self.primary)
        # Absent meta is not an error.
        body = self.expect(
            200, "GET",
            self.project_path(PROJECT, "work-areas", AREA, "meta"),
        )
        self.assertIsNone(body["meta"])
        # A corrupt work_area_meta envelope refuses with a stable token on
        # both verbs; raw exception text must not leak through the API.
        store = self.sealed_store()
        meta_key = store.keys.work_area_meta(AREA)
        store.client.put(meta_key, {"not": "an envelope"})
        self.refused(500, "malformed_store", "GET",
                     self.project_path(PROJECT, "work-areas", AREA, "meta"))
        self.refused(500, "malformed_store", "POST",
                     self.project_path(PROJECT, "work-areas", AREA, "meta"),
                     {"reuse_sources": []})
        store.client.put(
            meta_key, {"revision": 1, "value": {"reuse_sources": []}}
        )
        self.refused(500, "malformed_store", "POST",
                     self.project_path(PROJECT, "work-areas", AREA, "meta"),
                     {"reuse_sources": []})
        store.client.put(
            meta_key,
            {"revision": 1, "value": {"reuse_sources": []},
             "deleted?": False},
        )
        # Malformed values refuse 400 (sealed shape: exactly
        # {reuse_sources: [{root, inventory, registry, consumption}]}).
        for bad in (
            {"reuse_sources": [{"root": "/x"}]},
            {"reuse_sources": "nope"},
            {"other": []},
        ):
            self.refused(
                400, "invalid_meta", "POST",
                self.project_path(PROJECT, "work-areas", AREA, "meta"), bad,
            )
        # Unknown and tombstoned names refuse 404 on both verbs.
        for name in ("ghost",):
            self.refused(404, "unknown_work_area", "GET",
                         self.project_path(PROJECT, "work-areas", name,
                                           "meta"))
            self.refused(404, "unknown_work_area", "POST",
                         self.project_path(PROJECT, "work-areas", name,
                                           "meta"), {"reuse_sources": []})
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        self.refused(404, "unknown_work_area", "GET",
                     self.project_path(PROJECT, "work-areas", AREA, "meta"))
        # A malformed underlying record refuses 5xx-class.
        self.corrupt_raw_record()
        self.refused(500, "malformed_work_area", "GET",
                     self.project_path(PROJECT, "work-areas", AREA, "meta"))
        self.refused(500, "malformed_work_area", "POST",
                     self.project_path(PROJECT, "work-areas", AREA, "meta"),
                     {"reuse_sources": []})


# ---------------------------------------------------------------------------
# AC5 + AC6: the launch reconcile happy path and stable-identity idempotency


class TestLaunchBinding(ProjectsServiceTestCase):
    def setUp(self):
        super().setUp()
        self.create_project()
        self.primary = self.repo("bound-repo")
        self.lib = self.plain_dir("bound-lib")
        self.declare(self.primary, additional=[self.lib])

    def test_happy_path_reconciles_binds_and_drives(self):
        status, body = self.launch()
        run = body["run"]
        self.assertEqual(run["project"], PROJECT)
        self.assertEqual(run["work_area"], AREA)
        self.assertEqual(run["workspace"], self.primary)
        # The first reconcile is the sealed pending v1 -> ready v2 bump.
        record = self.wa_record()
        self.assertEqual((record["status"], record["version"]),
                         ("ready", 2))
        # Slice 5's state block, roots verbatim; exactly one
        # project_resolved event.
        state = st.load(_ws_state(self.primary))
        self.assertEqual(
            state["project"],
            {
                "directory": registry.projects_base(self.home),
                "project": PROJECT,
                "work_area": AREA,
                "primary": {"path": self.primary, "device": "local"},
                "additional": [{"path": self.lib, "device": "local"}],
            },
        )
        resolved = [e for e in state["events"]
                    if e["type"] == "project_resolved"]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["project"], PROJECT)
        self.assertEqual(resolved[0]["work_area"], AREA)
        # Both handles ride GET /api/runs.
        listed = self.expect(200, "GET", "/api/runs")
        self.assertEqual(listed["runs"][0]["project"], PROJECT)
        self.assertEqual(listed["runs"][0]["work_area"], AREA)
        # The run is drivable: the work-area-backed store satisfies the
        # driver's standing-law reads.
        self.drive(self.primary)
        state = st.load(_ws_state(self.primary))
        self.assertIsNone(state["failure"])
        self.assertEqual(state["units"][0]["artifact"], "docs/skeleton.md")

    def test_relaunch_after_purge_is_version_silent_across_restart(self):
        status, body = self.launch()
        run_id = body["run"]["id"]
        self.expect(200, "DELETE", "/api/runs/%s?purge=1" % run_id)
        self.restart_server()
        # Same home, fresh service instance: the stable executor/device
        # identity keeps the re-confirm version-silent (I3).
        self.launch()
        record = self.wa_record()
        self.assertEqual((record["status"], record["version"]),
                         ("ready", 2))


# ---------------------------------------------------------------------------
# AC7: the refusal matrix — verbatim tokens, nothing created


class TestLaunchRefusals(ProjectsServiceTestCase):
    def setUp(self):
        super().setUp()
        self.create_project()

    def test_missing_primary_refuses_and_creates_nothing(self):
        ghost = os.path.join(self.tmp.name, "ghost-primary")
        self.declare(ghost)
        self.launch(expect=None)
        status, body = self.launch(expect=None)
        self.assertEqual((status, body["error"]),
                         (400, "missing_primary_path"))
        record = self.wa_record()
        self.assertEqual((record["status"], record["version"]),
                         ("pending", 1))  # status untouched
        self.assert_nothing_created(ghost)

    def test_non_repo_primary_with_git_enabled_refuses(self):
        primary = self.plain_dir("non-repo")
        self.declare(primary)
        status, body = self.launch(expect=None)
        self.assertEqual((status, body["error"]),
                         (400, "primary_not_repo_root"))
        record = self.wa_record()
        self.assertEqual((record["status"], record["version"]),
                         ("pending", 1))
        self.assert_nothing_created(primary)

    def test_missing_additional_root_refuses(self):
        primary = self.repo("repo-add")
        self.declare(primary,
                     additional=[os.path.join(self.tmp.name, "ghost-lib")])
        status, body = self.launch(expect=None)
        self.assertEqual((status, body["error"]),
                         (400, "missing_additional_root"))
        record = self.wa_record()
        self.assertEqual((record["status"], record["version"]),
                         ("pending", 1))
        self.assert_nothing_created(primary)

    def test_addressing_refusals_ride_the_sealed_tokens(self):
        primary = self.repo("repo-addr")
        self.declare(primary)
        # Undeclared project: the launch seam's no-store posture.
        status, body = self.launch(slug="ghost", expect=None)
        self.assertEqual((status, body["error"]), (400, "unknown_work_area"))
        # Unknown work-area name.
        status, body = self.launch(area="ghost", expect=None)
        self.assertEqual((status, body["error"]), (400, "unknown_work_area"))
        # Invalid handles reuse the sealed validation vocabulary.
        status, body = self.launch(slug="a/b", expect=None)
        self.assertEqual((status, body["error"]), (400, "invalid_project"))
        status, body = self.launch(area="a/b", expect=None)
        self.assertEqual((status, body["error"]), (400, "invalid_name"))
        # Tombstoned name.
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        status, body = self.launch(expect=None)
        self.assertEqual((status, body["error"]), (400, "unknown_work_area"))
        # Corrupted record: 400-class HERE (the launch seam), not the
        # CRUD routes' 5xx mapping.
        self.declare(primary)
        self.corrupt_raw_record()
        status, body = self.launch(expect=None)
        self.assertEqual((status, body["error"]),
                         (400, "malformed_work_area"))
        self.assert_nothing_created(primary)

    def test_bound_addressing_refusals_precede_goal_resolution(self):
        missing_doc = os.path.join(self.tmp.name, "no-such-goal.md")
        for payload, expected in (
            ({"project": "a/b", "work_area": AREA}, "invalid_project"),
            ({"project": "ghost", "work_area": AREA}, "unknown_work_area"),
            ({"project": PROJECT, "work_area": "ghost"}, "unknown_work_area"),
            ({"project": PROJECT, "work_area": "a/b"}, "invalid_name"),
        ):
            payload.update({"goal_doc": missing_doc, "autostart": False})
            status, body = self.request_json("POST", "/api/runs", payload)
            self.assertEqual((status, body["error"]), (400, expected))

    def test_attach_cannot_combine_with_a_binding(self):
        primary = self.repo("repo-attach")
        self.declare(primary)
        self.launch()
        run_id = self.expect(200, "GET", "/api/runs")["runs"][0]["id"]
        self.expect(200, "DELETE", "/api/runs/%s" % run_id)  # forget
        for extra in ({"project": PROJECT}, {"work_area": AREA},
                      {"project": PROJECT, "work_area": AREA}):
            payload = {"workspace": primary, "attach": True,
                       "autostart": False,
                       "state_path": _ws_state(primary)}
            payload.update(extra)
            status, body = self.request_json("POST", "/api/runs", payload)
            self.assertEqual(status, 400, body)
            self.assertIn("attach", body["error"])

    def test_workspace_mismatch_refuses_equal_passes(self):
        primary = self.repo("repo-ws")
        other = self.plain_dir("elsewhere")
        self.declare(primary)
        status, body = self.launch(workspace=other, expect=None)
        self.assertEqual((status, body["error"]), (400, "workspace_mismatch"))
        # The reconcile already validated real roots: the prior truthful
        # ready transition may persist — but nothing else was created.
        record = self.wa_record()
        self.assertEqual((record["status"], record["version"]),
                         ("ready", 2))
        self.assert_nothing_created(primary)
        self.assertEqual(os.listdir(other), [])
        # A supplied workspace EQUAL to primary.path passes the sealed
        # strict-equality cross-check.
        status, body = self.launch(workspace=primary)
        self.assertEqual(body["run"]["workspace"], primary)

    def test_existing_state_stays_409_with_attach_hint(self):
        primary = self.repo("repo-409")
        self.declare(primary)
        legacy_cfg = {"docs_dir": "docs"}
        status, body = self.launch(config=legacy_cfg)
        run_id = body["run"]["id"]
        self.expect(200, "DELETE", "/api/runs/%s" % run_id)  # state remains
        # Legacy docs_dir: the relaunch would clobber the surviving
        # state, so the refusal (and its attach hint) survives there.
        status, body = self.launch(config=legacy_cfg, expect=None)
        self.assertEqual(status, 409, body)
        self.assertIn("attach", body["error"])
        # Per-milestone layout: a relaunch UNIQUIFIES and coexists — the
        # surviving state is not clobbered and no refusal is owed.
        status, body = self.launch()
        first_state = _ws_states(primary)
        self.assertEqual(status, 201, body)
        self.assertTrue(
            os.path.isfile(drv.default_state_path(primary))
        )  # the forgotten legacy state still exists untouched

    def test_stale_registry_claim_refuses_before_bound_state_create(self):
        primary = self.repo("repo-stale-claim")
        self.declare(primary)
        # The stale claim is at the LEGACY workspace-root path, which a
        # LEGACY-layout launch actually resolves to — so the guard fires.
        state_path = drv.default_state_path(primary)
        stale = registry.new_entry("old-run", "old", primary, state_path)
        registry.add(self.home, stale)
        self.assertFalse(os.path.exists(state_path))

        status, body = self.launch(config={"docs_dir": "docs"}, expect=None)
        self.assertEqual(status, 409, body)
        self.assertIn("already registered", body["error"])
        self.assertFalse(os.path.exists(state_path))
        reg = registry.load(self.home)
        self.assertEqual([entry["id"] for entry in reg["runs"]],
                         ["old-run"])
        self.assertEqual(self.run_entries(), [])

    def test_per_milestone_launch_ignores_a_legacy_path_claim(self):
        # Regression (LPC N30, 2026-07-09): a CLOSED legacy-layout run
        # registered at the workspace-root path must NOT block a new
        # per-milestone milestone — which resolves to its own uniquified
        # dir and can never collide with the flat root state.
        primary = self.repo("repo-legacy-coexist")
        self.declare(primary)
        legacy = drv.default_state_path(primary)
        stale = registry.new_entry("old-legacy", "old", primary, legacy)
        registry.add(self.home, stale)

        status, body = self.launch()  # default per-milestone layout
        self.assertEqual(status, 201, body)
        reg = registry.load(self.home)
        self.assertIn("old-legacy", [e["id"] for e in reg["runs"]])  # untouched
        new = [e for e in reg["runs"] if e["id"] != "old-legacy"][0]
        self.assertNotEqual(new["state_path"], legacy)
        self.assertIn("implementation/milestones", new["state_path"])

    def test_confirm_failures_map_by_the_sealed_vocabulary(self):
        primary = self.repo("repo-confirm")
        self.declare(primary)
        for reason, expected_status in (
            (workareas.DESCRIPTOR_MISMATCH, 400),
            (workareas.CONFLICT, 409),
        ):
            with mock.patch.object(
                workareas.WorkAreaStore, "confirm",
                return_value=workareas.WorkAreaResult(False, reason=reason),
            ):
                status, body = self.launch(expect=None)
            self.assertEqual((status, body["error"]),
                             (expected_status, reason))
        record = self.wa_record()
        self.assertEqual((record["status"], record["version"]),
                         ("pending", 1))
        self.assert_nothing_created(primary)


# ---------------------------------------------------------------------------
# AC8: effective config precedence at bound launches


class TestConfigPrecedence(ProjectsServiceTestCase):
    def test_project_defaults_beat_the_service_git_convention(self):
        # Standing operator law: pure-state launches for this project.
        self.create_project(defaults={"git": {"enabled": False}})
        primary = self.plain_dir("pure-state-root")  # NOT a repo
        self.declare(primary)
        status, body = self.launch()  # validation skipped the repo gate
        state = st.load(_ws_state(primary))
        self.assertFalse(state["config"]["git"]["enabled"])

    def test_explicit_launch_config_beats_project_defaults(self):
        self.create_project(defaults={"git": {"enabled": False}})
        primary = self.plain_dir("gated-root")
        self.declare(primary)
        status, body = self.launch(config={"git": {"enabled": True}},
                                   expect=None)
        self.assertEqual((status, body["error"]),
                         (400, "primary_not_repo_root"))

    def test_convention_applies_above_default_config_without_defaults(self):
        # DEFAULT_CONFIG disables git; the service convention still gates
        # bound panel launches when the project has no defaults.
        self.create_project()
        primary = self.plain_dir("conventional-root")
        self.declare(primary)
        status, body = self.launch(expect=None)
        self.assertEqual((status, body["error"]),
                         (400, "primary_not_repo_root"))
        # ...unless the launch config itself disables git.
        status, body = self.launch(config={"git": {"enabled": False}})
        state = st.load(_ws_state(primary))
        self.assertFalse(state["config"]["git"]["enabled"])

    def test_bound_launch_enables_git_without_legacy_seal_flags(self):
        self.create_project()
        primary = self.repo("bound-root")
        self.declare(primary)
        self.launch()
        state = st.load(_ws_state(primary))
        self.assertTrue(state["config"]["git"]["enabled"])
        self.assertNotIn("seal_concurrent", state["config"])
        self.assertNotIn("single_seal_first_attempt", state["config"])

    def test_docs_dir_default_applies_and_launch_wins(self):
        self.create_project(defaults={"docs_dir": "notes/{slug}"})
        first = self.repo("docs-repo-a")
        second = self.repo("docs-repo-b")
        self.declare(first, name="area a")
        self.declare(second, name="area b")
        self.launch(area="area a", name="My Feature")
        state = st.load(_ws_state(first))
        self.assertEqual(state["config"]["docs_dir"], "notes/{slug}")
        self.assertEqual(state["docs_dir"], "notes/my-feature")
        self.launch(area="area b", name="My Feature",
                    config={"docs_dir": "docs"})
        state = st.load(_ws_state(second))
        self.assertEqual(state["docs_dir"], "docs")


# ---------------------------------------------------------------------------
# AC9: the run:<run_id>/status projection lifecycle


class TestProjection(ProjectsServiceTestCase):
    def setUp(self):
        super().setUp()
        self.create_project()
        self.create_project("other project")
        self.primary = self.repo("proj-repo")
        self.declare(self.primary)
        self.other_primary = self.repo("other-repo")
        self.declare(self.other_primary, slug="other project",
                     name="other area")

    def read_projection(self, run_id, slug=PROJECT):
        return self.envelopes(slug).read(self.run_key(run_id))

    def test_initial_write_exact_path_free_value_in_the_bound_store_only(self):
        status, body = self.launch(name="Fix %s" % self.primary)
        run_id = body["run"]["id"]
        record = self.read_projection(run_id)
        self.assertEqual(record["revision"], 1)
        self.assertTrue(record["exists?"])
        summ = self.expect(200, "GET", "/api/runs/%s" % run_id)["summary"]
        self.assertEqual(
            record["value"],
            {
                "run_id": run_id,
                "name": "Fix <path>",  # path-sanitized display name
                "project": PROJECT,
                "work_area": AREA,
                "milestone_status": summ["milestone_status"],
                "current_unit": summ["current_unit"],
                "current_unit_status": summ["current_unit_status"],
                "failure_reason": None,
            },
        )
        # The raw name survives in registry/durable state, only the
        # projection is path-free.
        self.assertEqual(summ["name"], "Fix %s" % self.primary)
        # No other declared project store — and no service-level KV —
        # received anything.
        self.assertEqual(self.run_entries("other project"), [])
        self.assertFalse(
            os.path.exists(os.path.join(self.home, kvstore.STORE_FILENAME))
        )
        self.assertFalse(os.path.exists(os.path.join(
            registry.projects_base(self.home), kvstore.STORE_FILENAME
        )))

    def test_change_driven_revisions(self):
        status, body = self.launch()
        run_id = body["run"]["id"]
        self.assertEqual(self.read_projection(run_id)["revision"], 1)
        # Observations without change move nothing.
        self.expect(200, "GET", "/api/runs")
        self.expect(200, "GET", "/api/runs")
        self.assertEqual(self.read_projection(run_id)["revision"], 1)
        # Real progress, then one observation: exactly one write.
        self.drive(self.primary)
        self.expect(200, "GET", "/api/runs")
        record = self.read_projection(run_id)
        self.assertEqual(record["revision"], 2)
        self.assertEqual(record["value"]["current_unit_status"],
                         "pre_review_verify")
        self.expect(200, "GET", "/api/runs")
        self.assertEqual(self.read_projection(run_id)["revision"], 2)

    def test_display_rename_updates_projection_not_driver_state(self):
        _, body = self.launch(name="Typo name")
        run_id = body["run"]["id"]
        renamed = self.expect(
            200, "POST", "/api/runs/%s/name" % run_id,
            {"name": "Better name"},
        )
        self.assertEqual(renamed["run"]["name"], "Better name")
        record = self.read_projection(run_id)
        self.assertEqual(record["revision"], 2)
        self.assertEqual(record["value"]["name"], "Better name")
        summary = self.expect(
            200, "GET", "/api/runs/%s" % run_id
        )["summary"]
        self.assertEqual(summary["name"], "Typo name")

    def test_projection_reconciles_against_durable_envelope(self):
        status, body = self.launch()
        run_id = body["run"]["id"]
        self.assertEqual(self.read_projection(run_id)["revision"], 1)
        # A wiped-but-readable store is repaired from durable state.
        with open(self.kv_file(), "w", encoding="utf-8") as fh:
            json.dump({"entries": {}}, fh)
        self.expect(200, "GET", "/api/runs")
        repaired = self.read_projection(run_id)
        self.assertTrue(repaired["exists?"])
        self.assertEqual(repaired["revision"], 1)
        # A cold process must not rewrite an unchanged durable projection
        # and bump its envelope revision.
        self.restart_server()
        self.expect(200, "GET", "/api/runs")
        self.assertEqual(self.read_projection(run_id)["revision"], 1)

    def test_guard_scan_is_an_observation_path(self):
        status, body = self.launch()
        run_id = body["run"]["id"]
        self.drive(self.primary)
        service.guard_scan(self.home)
        record = self.read_projection(run_id)
        self.assertEqual(record["revision"], 2)

    def test_failure_reason_mirrors_path_sanitized(self):
        status, body = self.launch()
        run_id = body["run"]["id"]
        state_path = _ws_state(self.primary)
        state = st.load(state_path)
        st.fail_run(state, "suite failed under %s (see log)" % self.primary)
        st.save(state_path, state)
        self.expect(200, "GET", "/api/runs")
        value = self.read_projection(run_id)["value"]
        self.assertEqual(value["failure_reason"],
                         "suite failed under <path> (see log)")
        self.assertNotIn(self.primary, json.dumps(value))
        # The raw reason stays in the durable summary.
        summ = self.expect(200, "GET", "/api/runs/%s" % run_id)["summary"]
        self.assertIn(self.primary, summ["failure"]["reason"])

    def test_projection_sanitizes_workspace_paths_with_spaces(self):
        primary = self.repo("proj repo with spaces")
        self.declare(primary, name="space area")
        status, body = self.launch(
            area="space area", name="Fix %s" % primary
        )
        run_id = body["run"]["id"]
        value = self.read_projection(run_id)["value"]
        self.assertEqual(value["name"], "Fix <path>")
        self.assertNotIn(primary, json.dumps(value))
        self.assertNotIn("proj repo with spaces", json.dumps(value))

        state_path = _ws_state(primary)
        state = st.load(state_path)
        st.fail_run(state, "suite failed under %s (see log)" % primary)
        st.save(state_path, state)
        self.expect(200, "GET", "/api/runs")
        value = self.read_projection(run_id)["value"]
        self.assertEqual(value["failure_reason"],
                         "suite failed under <path> (see log)")
        self.assertNotIn(primary, json.dumps(value))
        self.assertNotIn("proj repo with spaces", json.dumps(value))

    def test_projection_falls_back_for_existing_parenthesized_path_tail(self):
        longer = self.primary + " (copy 2)"
        os.makedirs(longer)
        status, body = self.launch(name="Fix %s" % longer)
        run_id = body["run"]["id"]
        value = self.read_projection(run_id)["value"]
        self.assertEqual(value["name"], "run")
        self.assertNotIn("copy 2", json.dumps(value))

        state_path = _ws_state(self.primary)
        state = st.load(state_path)
        st.fail_run(state, "suite failed under %s" % longer)
        st.save(state_path, state)
        self.expect(200, "GET", "/api/runs")
        value = self.read_projection(run_id)["value"]
        self.assertEqual(value["failure_reason"], "failure_recorded")
        self.assertNotIn("copy 2", json.dumps(value))

    def test_projection_falls_back_for_unknown_parenthesized_path_tail(self):
        foreign = os.path.join(self.tmp.name, "foreign-proj")
        leaked = foreign + " (copy 2)"
        status, body = self.launch(name="Fix %s" % leaked)
        run_id = body["run"]["id"]
        value = self.read_projection(run_id)["value"]
        self.assertEqual(value["name"], "run")
        self.assertNotIn("copy 2", json.dumps(value))

        state_path = _ws_state(self.primary)
        state = st.load(state_path)
        st.fail_run(state, "suite failed under %s" % leaked)
        st.save(state_path, state)
        self.expect(200, "GET", "/api/runs")
        value = self.read_projection(run_id)["value"]
        self.assertEqual(value["failure_reason"], "failure_recorded")
        self.assertNotIn("copy 2", json.dumps(value))

    def test_purge_tombstones_forget_leaves_the_snapshot(self):
        status, body = self.launch()
        purged_id = body["run"]["id"]
        status, body = self.launch(slug="other project", area="other area")
        forgotten_id = body["run"]["id"]
        self.expect(200, "DELETE", "/api/runs/%s?purge=1" % purged_id)
        tomb = self.read_projection(purged_id)
        self.assertFalse(tomb["exists?"])
        self.assertEqual(tomb["revision"], 2)  # envelope tombstone write
        self.expect(200, "DELETE", "/api/runs/%s" % forgotten_id)
        kept = self.read_projection(forgotten_id, slug="other project")
        self.assertTrue(kept["exists?"])  # last truthful snapshot

    def test_purge_tombstones_projection_when_state_is_unreadable(self):
        status, body = self.launch()
        run_id = body["run"]["id"]
        with open(_ws_state(self.primary), "w",
                  encoding="utf-8") as fh:
            fh.write("{ not json")
        self.expect(200, "DELETE", "/api/runs/%s?purge=1" % run_id)
        tomb = self.read_projection(run_id)
        self.assertFalse(tomb["exists?"])
        self.assertEqual(tomb["revision"], 2)

    def test_purge_tombstone_failure_keeps_observation_path(self):
        status, body = self.launch()
        run_id = body["run"]["id"]
        state_path = _ws_state(self.primary)
        with mock.patch.object(kvstore.RevisionEnvelopeStore, "delete",
                               side_effect=RuntimeError("store hiccup")):
            self.refused(
                500, "projection_tombstone_failed", "DELETE",
                "/api/runs/%s?purge=1" % run_id,
            )
        self.assertTrue(os.path.exists(state_path))
        self.assertIsNotNone(registry.get(registry.load(self.home), run_id))
        self.assertTrue(self.read_projection(run_id)["exists?"])

        self.expect(200, "DELETE", "/api/runs/%s?purge=1" % run_id)
        self.assertFalse(self.read_projection(run_id)["exists?"])

    def test_contained_initial_write_failure_then_self_heal(self):
        with mock.patch.object(kvstore.RevisionEnvelopeStore, "put",
                               side_effect=RuntimeError("store hiccup")):
            status, body = self.launch()  # 201 despite the failed write
        run_id = body["run"]["id"]
        self.assertFalse(self.read_projection(run_id)["exists?"])
        # The next observation heals the projection.
        self.expect(200, "GET", "/api/runs")
        record = self.read_projection(run_id)
        self.assertTrue(record["exists?"])
        self.assertEqual(record["revision"], 1)

    def test_observation_failures_log_and_continue_then_self_heal(self):
        status, body = self.launch()
        run_id = body["run"]["id"]
        # Advance the run while the store is intact (a bound run's DRIVER
        # fails closed without readable standing law — slice-06), then
        # lose the store before the change is ever observed.
        self.drive(self.primary)
        with open(self.kv_file(), "rb") as fh:
            saved = fh.read()
        os.unlink(self.kv_file())
        listed = self.expect(200, "GET", "/api/runs")  # poll still answers
        self.assertEqual(listed["runs"][0]["id"], run_id)
        self.assertIsNone(listed["runs"][0]["state_error"])
        log = self.expect(200, "GET", "/api/runs/%s/log" % run_id)
        self.assertTrue(any("[projection]" in line
                            for line in log["lines"]))
        # Restore the store: the pump self-heals on the next observation.
        with open(self.kv_file(), "wb") as fh:
            fh.write(saved)
        self.expect(200, "GET", "/api/runs")
        record = self.read_projection(run_id)
        self.assertEqual(record["revision"], 2)
        self.assertEqual(record["value"]["current_unit_status"],
                         "pre_review_verify")

    def test_reserved_digest_key_is_never_written(self):
        status, body = self.launch()
        self.drive(self.primary)
        self.expect(200, "GET", "/api/runs")
        run_id = body["run"]["id"]
        client = kvstore.LocalKVClient(self.store_dir())
        keys = [item["key"] for item in client.list_entries()["items"]]
        self.assertIn(self.run_key(run_id), keys)
        self.assertNotIn(kvstore.KeyBuilder().run_digest(run_id), keys)


# ---------------------------------------------------------------------------
# AC10 + AC12: run status carries the handles; project-less inertness


class TestStatusHandlesAndInertness(ProjectsServiceTestCase):
    def test_bound_and_attached_runs_carry_the_handles(self):
        self.create_project()
        primary = self.repo("handles-repo")
        self.declare(primary)
        status, body = self.launch()
        run_id = body["run"]["id"]
        detail = self.expect(200, "GET", "/api/runs/%s" % run_id)
        self.assertEqual(detail["status"]["project"], PROJECT)
        self.assertEqual(detail["status"]["work_area"], AREA)
        self.assertEqual(detail["summary"]["project"], PROJECT)
        self.assertEqual(detail["summary"]["work_area"], AREA)
        # A run adopted via attach reports the same handles.
        self.expect(200, "DELETE", "/api/runs/%s" % run_id)
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": primary, "attach": True, "autostart": False,
             "state_path": _ws_state(primary)},
        )
        self.assertEqual(status, 201, body)
        self.assertEqual(body["run"]["project"], PROJECT)
        self.assertEqual(body["run"]["work_area"], AREA)

    def test_projectless_run_is_unbound_and_key_identical(self):
        ws = self.repo("plain-ws")
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": ws, "goal": GOAL, "autostart": False},
        )
        self.assertEqual(status, 201, body)
        run = body["run"]
        self.assertIsNone(run["project"])
        self.assertIsNone(run["work_area"])
        detail = self.expect(200, "GET", "/api/runs/%s" % run["id"])
        # The summary document mirrors the state block: ABSENT, not null.
        self.assertNotIn("project", detail["summary"])
        self.assertNotIn("work_area", detail["summary"])

    def test_projectless_launch_touches_no_project_machinery(self):
        ws = self.repo("inert-ws")
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": ws, "goal": GOAL, "autostart": False},
        )
        self.assertEqual(status, 201, body)
        self.expect(200, "GET", "/api/runs")
        # Zero KV access: no project store base, no projects record.
        self.assertFalse(os.path.exists(registry.projects_base(self.home)))
        self.assertFalse(
            os.path.exists(registry.projects_record_path(self.home))
        )
        # Forget + purge stay inert too (readable unbound state).
        run_id = body["run"]["id"]
        self.expect(200, "DELETE", "/api/runs/%s" % run_id)
        self.assertFalse(
            os.path.exists(registry.projects_record_path(self.home))
        )

    def test_projectless_unreadable_plain_forget_keeps_no_project_claim(self):
        self.create_project("unrelated")
        ws = self.repo("plain-corrupt-forget")
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": ws, "goal": GOAL, "autostart": False},
        )
        self.assertEqual(status, 201, body)
        run_id = body["run"]["id"]
        with open(_ws_state(ws), "w", encoding="utf-8") as fh:
            fh.write("{ not json")

        self.expect(200, "DELETE", "/api/runs/%s" % run_id)
        rec = registry.load_projects_record(self.home)
        self.assertEqual(rec["retained_states"], [])
        self.expect(200, "DELETE", self.project_path("unrelated"))

    def test_attached_unreadable_state_keeps_unproven_claim(self):
        self.create_project("unrelated")
        ws = self.repo("attached-corrupt-forget")
        state_path = drv.default_state_path(ws)
        os.makedirs(os.path.dirname(state_path))
        with open(state_path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")

        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": ws, "attach": True, "autostart": False},
        )
        self.assertEqual(status, 201, body)
        self.expect(200, "DELETE", "/api/runs/%s" % body["run"]["id"])
        rec = registry.load_projects_record(self.home)
        self.assertEqual(rec["retained_states"], [state_path])
        self.refused(409, "project_in_use", "DELETE",
                     self.project_path("unrelated"))

        os.unlink(state_path)
        self.expect(200, "DELETE", self.project_path("unrelated"))


# ---------------------------------------------------------------------------
# AC11: the guarded-delete matrix


class TestGuardedDelete(ProjectsServiceTestCase):
    def setUp(self):
        super().setUp()
        self.create_project()

    def test_live_work_area_blocks_until_tombstoned(self):
        self.declare(self.plain_dir("guard-root"))
        self.refused(409, "project_in_use", "DELETE", self.project_path())
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        # Tombstone-only history never blocks deletion.
        self.expect(200, "DELETE", self.project_path())
        body = self.expect(200, "GET", "/api/projects")
        self.assertEqual(body["projects"], [])

    def test_project_delete_waits_for_inflight_work_area_declare(self):
        primary = self.plain_dir("guard-race-root")
        entered = threading.Event()
        release = threading.Event()
        results = {}
        original = workareas.WorkAreaStore.declare

        def delayed_declare(store, *args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return original(store, *args, **kwargs)

        def run_declare():
            results["declare"] = service.declare_work_area(
                self.home,
                PROJECT,
                {"name": AREA, "primary_path": primary},
            )

        def run_delete():
            try:
                results["delete"] = service.delete_project(self.home, PROJECT)
            except service.ApiError as exc:
                results["delete"] = (exc.status, str(exc))

        with mock.patch.object(
            workareas.WorkAreaStore, "declare", delayed_declare
        ):
            declare_thread = threading.Thread(target=run_declare)
            declare_thread.start()
            self.assertTrue(entered.wait(5))
            delete_thread = threading.Thread(target=run_delete)
            delete_thread.start()
            for _ in range(50):
                if "delete" in results:
                    break
                time.sleep(0.01)
            self.assertNotIn("delete", results)
            release.set()
            declare_thread.join(timeout=5)
            delete_thread.join(timeout=5)
        self.assertFalse(declare_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertIn("declare", results)
        self.assertEqual(results["delete"], (409, "project_in_use"))

    def test_live_policy_blocks_until_removed(self):
        # Policies have no authoring endpoint yet (the safeguard editor is
        # the panel slice's); seed and remove through the sealed store.
        store = projects.PolicyStore(
            registry.projects_base(self.home), PROJECT
        )
        store.put(policy_object())
        self.refused(409, "project_in_use", "DELETE", self.project_path())
        store.delete("lpc-reuse-audit")  # envelope tombstone remains
        self.expect(200, "DELETE", self.project_path())

    def test_bound_registered_run_blocks_until_purged(self):
        primary = self.repo("guard-run-repo")
        self.declare(primary)
        status, body = self.launch()
        run_id = body["run"]["id"]
        # Isolate the run condition: tombstone the work area (a store
        # mutation never rebinds the live run).
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        self.refused(409, "project_in_use", "DELETE", self.project_path())
        self.expect(200, "DELETE", "/api/runs/%s?purge=1" % run_id)
        self.expect(200, "DELETE", self.project_path())

    def test_unreadable_registered_state_blocks(self):
        primary = self.repo("guard-corrupt-repo")
        self.declare(primary)
        status, body = self.launch()
        run_id = body["run"]["id"]
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        with open(_ws_state(primary), "w",
                  encoding="utf-8") as fh:
            fh.write("{ not json")
        self.refused(409, "project_in_use", "DELETE", self.project_path())
        self.expect(200, "DELETE", "/api/runs/%s?purge=1" % run_id)
        self.expect(200, "DELETE", self.project_path())

    def test_missing_registered_state_blocks_until_run_removed(self):
        primary = self.repo("guard-missing-repo")
        self.declare(primary)
        status, body = self.launch()
        run_id = body["run"]["id"]
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        os.unlink(_ws_state(primary))
        self.refused(409, "project_in_use", "DELETE", self.project_path())
        self.expect(200, "DELETE", "/api/runs/%s?purge=1" % run_id)
        self.expect(200, "DELETE", self.project_path())

    def test_unreadable_projectless_registered_state_never_blocks(self):
        # The registry's durable binding proves the run unbound, so its
        # now-unreadable state cannot hold standing law hostage.
        ws = self.repo("guard-projectless-corrupt")
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": ws, "goal": GOAL, "autostart": False},
        )
        self.assertEqual(status, 201, body)
        with open(_ws_state(ws), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        self.expect(200, "DELETE", self.project_path())

    def test_unreadable_state_bound_elsewhere_blocks_only_its_project(self):
        self.create_project("other")
        primary = self.repo("guard-other-repo")
        self.declare(primary, slug="other")
        status, body = self.launch(slug="other")
        run_id = body["run"]["id"]
        self.expect(200, "DELETE",
                    self.project_path("other", "work-areas", AREA))
        with open(_ws_state(primary), "w",
                  encoding="utf-8") as fh:
            fh.write("{ not json")
        # The durable binding names "other": this project stays deletable.
        self.expect(200, "DELETE", self.project_path())
        self.refused(409, "project_in_use", "DELETE",
                     self.project_path("other"))
        self.expect(200, "DELETE", "/api/runs/%s?purge=1" % run_id)
        self.expect(200, "DELETE", self.project_path("other"))

    def test_attached_unreadable_registered_state_blocks(self):
        # An attach of an already-unreadable state carries no proof either
        # way, so the guard stays fail-closed while the run is registered.
        ws = self.repo("guard-attached-corrupt")
        state_path = drv.default_state_path(ws)
        os.makedirs(os.path.dirname(state_path))
        with open(state_path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": ws, "attach": True, "autostart": False},
        )
        self.assertEqual(status, 201, body)
        run_id = body["run"]["id"]
        self.refused(409, "project_in_use", "DELETE", self.project_path())
        self.expect(200, "DELETE", "/api/runs/%s?purge=1" % run_id)
        self.expect(200, "DELETE", self.project_path())

    def test_forgotten_bound_state_blocks_until_purged(self):
        primary = self.repo("guard-forgotten-repo")
        self.declare(primary)
        status, body = self.launch()
        run_id = body["run"]["id"]
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        self.expect(200, "DELETE", "/api/runs/%s" % run_id)  # plain forget
        # The retained, attachable state still binds the project.
        self.refused(409, "project_in_use", "DELETE", self.project_path())
        # Re-attach and purge-delete it: the guard releases.
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": primary, "attach": True, "autostart": False,
             "state_path": _ws_state(primary)},
        )
        self.assertEqual(status, 201, body)
        self.expect(200, "DELETE",
                    "/api/runs/%s?purge=1" % body["run"]["id"])
        self.expect(200, "DELETE", self.project_path())

    def test_project_delete_waits_for_plain_forget_retained_claim(self):
        primary = self.repo("guard-forget-race-repo")
        self.declare(primary)
        status, body = self.launch()
        run_id = body["run"]["id"]
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))

        entered = threading.Event()
        release = threading.Event()
        results = {}
        original = service._claim_retained_state_locked

        def delayed_claim(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return original(*args, **kwargs)

        def run_forget():
            try:
                results["forget"] = service.delete_run(self.home, run_id)
            except service.ApiError as exc:
                results["forget"] = (exc.status, str(exc))

        def run_delete():
            try:
                results["delete"] = service.delete_project(self.home, PROJECT)
            except service.ApiError as exc:
                results["delete"] = (exc.status, str(exc))

        with mock.patch.object(service, "_claim_retained_state_locked",
                               delayed_claim):
            forget_thread = threading.Thread(target=run_forget)
            forget_thread.start()
            self.assertTrue(entered.wait(5))
            delete_thread = threading.Thread(target=run_delete)
            delete_thread.start()
            for _ in range(50):
                if "delete" in results:
                    break
                time.sleep(0.01)
            self.assertNotIn("delete", results)
            release.set()
            forget_thread.join(timeout=5)
            delete_thread.join(timeout=5)

        self.assertFalse(forget_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertEqual(results["forget"]["deleted"], run_id)
        self.assertEqual(results["delete"], (409, "project_in_use"))

    def test_forgotten_unreadable_state_blocks_until_removed(self):
        primary = self.repo("guard-unprovable-repo")
        self.declare(primary)
        status, body = self.launch()
        run_id = body["run"]["id"]
        self.expect(200, "DELETE",
                    self.project_path(PROJECT, "work-areas", AREA))
        state_path = _ws_state(primary)
        with open(state_path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        self.expect(200, "DELETE", "/api/runs/%s" % run_id)  # plain forget
        # Unreadable: cannot be proven unbound.
        self.refused(409, "project_in_use", "DELETE", self.project_path())
        os.unlink(state_path)  # the operator's repair
        self.expect(200, "DELETE", self.project_path())

    def test_policy_lifecycle_drives_the_guard_end_to_end_over_http(self):
        # Slice 8 AC5: slice-07 could only seed this guard through the
        # store directly; the standing-law lifecycle is now drivable
        # entirely over HTTP.
        self.expect(200, "POST",
                    self.project_path(PROJECT) + "/policies",
                    policy_object())
        self.refused(409, "project_in_use", "DELETE", self.project_path())
        self.expect(
            200, "DELETE",
            self.project_path(PROJECT) + "/policies?id="
            + self.q("lpc-reuse-audit"),
        )
        self.expect(200, "DELETE", self.project_path())
        body = self.expect(200, "GET", "/api/projects")
        self.assertEqual(body["projects"], [])

    def test_redeclare_after_delete_starts_empty(self):
        self.create_project("reborn", defaults={"docs_dir": "notes/{slug}"})
        primary = self.plain_dir("reborn-root")
        self.declare(primary, slug="reborn", name="area")
        self.expect(200, "POST",
                    self.project_path("reborn", "work-areas", "area", "meta"),
                    {"reuse_sources": [{"root": primary, "inventory": "x",
                                        "registry": "y",
                                        "consumption": "z"}]})
        projects.PolicyStore(
            registry.projects_base(self.home), "reborn"
        ).put(policy_object())
        # Tear everything down, then delete.
        self.expect(200, "DELETE",
                    self.project_path("reborn", "work-areas", "area"))
        projects.PolicyStore(
            registry.projects_base(self.home), "reborn"
        ).delete("lpc-reuse-audit")
        self.expect(200, "DELETE", self.project_path("reborn"))
        # Nothing resurrects: no old defaults, policies, or work areas.
        created = self.create_project("reborn")
        self.assertEqual(
            created, {"slug": "reborn", "work_areas": [], "policy": []}
        )
        with open(self.kv_file("reborn"), "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"entries": {}})


# ---------------------------------------------------------------------------
# Slice 8, contract A: the policy authoring routes. Upsert through the
# sealed PolicyStore, verbatim version discipline, the gated delete, and
# amendment A2's two pins: the id rides a QUERY parameter (never a path
# segment browsers could normalize away) and the corrupt-entry recovery
# promise is narrowed to malformed VALUES inside VALID envelopes.


class TestPolicyAuthoring(ProjectsServiceTestCase):
    def setUp(self):
        super().setUp()
        self.create_project()

    # -- helpers -------------------------------------------------------------

    def policies_path(self, slug=PROJECT):
        return self.project_path(slug) + "/policies"

    def delete_path(self, policy_id, slug=PROJECT):
        """The A2 route shape: the policy id as an URL-encoded query
        parameter."""
        return "%s?id=%s" % (self.policies_path(slug), self.q(policy_id))

    def put_policy_api(self, policy, slug=PROJECT):
        return self.expect(
            200, "POST", self.policies_path(slug), policy
        )["policy"]

    def entry_policies(self, slug=PROJECT):
        return self.expect(
            200, "GET", self.project_path(slug)
        )["project"]["policy"]

    @staticmethod
    def key_of(policy_id):
        return kvstore.KeyBuilder().policy(policy_id)

    def store_keys(self, slug=PROJECT):
        client = kvstore.LocalKVClient(self.store_dir(slug))
        return [i["key"] for i in client.list_entries()["items"]]

    def store_bytes(self, slug=PROJECT):
        """The strongest write-nothing pin: the store file's exact bytes."""
        with open(self.kv_file(slug), "rb") as fh:
            return fh.read()

    # -- upsert matrix (AC1) ---------------------------------------------------

    def test_upsert_creates_and_overwrites_wholesale(self):
        policy = policy_object()
        body = self.expect(200, "POST", self.policies_path(), policy)
        # The response is the stored validated value under "policy" and
        # nothing else: the envelope's control revision stays internal.
        self.assertEqual(set(body), {"ok", "policy"})
        self.assertEqual(set(body["policy"]), projects.POLICY_KEYS)
        self.assertEqual(body["policy"], policy)
        self.assertEqual(self.entry_policies(), [policy])
        # Overwrite under the same id replaces the object WHOLESALE.
        changed = policy_object()
        changed["version"] = 2
        changed["prompt"] = "Enumerate, cite, decide."
        changed["scope"] = {
            "kinds": ["implement", "review_round"],
            "unit_kinds": ["slice_impl"],
        }
        self.assertEqual(self.put_policy_api(changed), changed)
        self.assertEqual(self.entry_policies(), [changed])

    def test_version_and_enabled_ride_verbatim(self):
        policy = policy_object()
        self.put_policy_api(policy)
        key = self.key_of(policy["id"])
        first = self.envelopes().read(key)["revision"]
        # A re-put with the SAME version reads back with that version:
        # nothing auto-bumps, even on a substance change.
        same = dict(policy, prompt="Changed substance, same version.")
        self.assertEqual(self.put_policy_api(same)["version"], 1)
        self.assertEqual(self.entry_policies()[0]["prompt"], same["prompt"])
        # A bumped version reads back bumped, verbatim.
        bumped = dict(same, version=5)
        self.assertEqual(self.put_policy_api(bumped)["version"], 5)
        # The toggle's API path: ONLY enabled flips, version untouched.
        flipped = dict(bumped, enabled=False)
        stored = self.put_policy_api(flipped)
        self.assertEqual((stored["version"], stored["enabled"]), (5, False))
        # The control revision advanced with every write yet never leaked
        # into the domain object: control revision ⟂ domain version.
        env = self.envelopes().read(key)
        self.assertEqual(env["revision"], first + 3)
        self.assertEqual(env["value"], stored)

    # -- refusals (AC3) --------------------------------------------------------

    def test_refusal_matrix_rides_verbatim_tokens(self):
        self.refused(400, "invalid_policy", "POST", self.policies_path(),
                     policy_object("a/b"))
        missing = policy_object()
        del missing["prompt"]
        extra = policy_object()
        extra["surprise"] = True
        unknown_kind = policy_object()
        unknown_kind["scope"] = {
            "kinds": ["reviewer"], "unit_kinds": ["slice_impl"]
        }
        zero_version = policy_object()
        zero_version["version"] = 0
        for bad in (missing, extra, unknown_kind, zero_version):
            with self.subTest(bad=sorted(bad)):
                self.refused(400, "malformed_policy", "POST",
                             self.policies_path(), bad)
        self.assertEqual(self.entry_policies(), [])  # nothing landed
        # The project-bound gates of every project route, on both verbs.
        self.refused(400, "invalid_project", "POST",
                     self.policies_path(slug="a/b"), policy_object())
        self.refused(404, "unknown_project", "POST",
                     self.policies_path(slug="ghost"), policy_object())
        self.refused(400, "invalid_project", "DELETE",
                     self.delete_path("x", slug="a/b"))
        self.refused(404, "unknown_project", "DELETE",
                     self.delete_path("x", slug="ghost"))
        # No new read surface: policies are read from the assembled entry.
        status, body = self.request_json("GET", self.policies_path())
        self.assertEqual((status, body["error"]), (404, "not found"))

    def test_missing_store_refuses_and_the_write_resurrects_nothing(self):
        os.unlink(self.kv_file())
        self.refused(500, "missing_store", "POST", self.policies_path(),
                     policy_object())
        self.refused(500, "missing_store", "DELETE", self.delete_path("x"))
        # Never a silent re-create: the lost store stays lost.
        self.assertFalse(os.path.exists(self.kv_file()))

    def test_corrupt_and_unreadable_store_refuse_stably(self):
        with open(self.kv_file(), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        # The service opens the store for the put -> its store token; the
        # sealed read owns the delete's gate read -> its own reason.
        self.refused(500, "malformed_store", "POST", self.policies_path(),
                     policy_object())
        self.refused(500, "malformed_policy", "DELETE",
                     self.delete_path("x"))
        with mock.patch.object(
            kvstore.LocalKVClient, "_load_doc",
            side_effect=OSError("permission denied"),
        ):
            self.refused(500, "unreadable_store", "POST",
                         self.policies_path(), policy_object())
            self.refused(500, "unreadable_store", "DELETE",
                         self.delete_path("x"))

    # -- delete matrix (AC4) ---------------------------------------------------

    def test_delete_gate_matrix(self):
        policy = policy_object()
        self.put_policy_api(policy)
        key = self.key_of(policy["id"])
        # Live delete: exact response, entry removal, tombstoned readback
        # — and the key STAYS listed (frozen tombstones-in-listings).
        body = self.expect(200, "DELETE", self.delete_path(policy["id"]))
        self.assertEqual(body["policy"],
                         {"id": policy["id"], "deleted": True})
        self.assertEqual(self.entry_policies(), [])
        record = self.envelopes().read(key)
        self.assertFalse(record["exists?"])
        self.assertEqual(record["revision"], 2)
        self.assertIn(key, self.store_keys())
        # Tombstoned and never-written ids refuse 404 and write NOTHING:
        # no junk tombstone key is ever minted.
        for ghost in (policy["id"], "never-written"):
            with self.subTest(ghost=ghost):
                before = self.store_bytes()
                self.refused(404, "unknown_policy", "DELETE",
                             self.delete_path(ghost))
                self.assertEqual(self.store_bytes(), before)
        self.assertNotIn(self.key_of("never-written"), self.store_keys())
        # A tombstoned id is re-creatable fresh through the same upsert;
        # its envelope revision continues past the tombstone.
        self.put_policy_api(policy)
        self.assertEqual(self.entry_policies(), [policy])
        self.assertEqual(self.envelopes().read(key)["revision"], 3)

    def test_malformed_value_delete_refuses_and_reput_recovers(self):
        # Amendment A2 narrows the recovery promise to exactly this case:
        # a malformed policy VALUE inside a VALID envelope. The sealed put
        # validates only the NEW value and reads the prior envelope just
        # for its revision, so a valid re-put replaces it wholesale.
        key = self.key_of("broken")
        self.envelopes().put(key, {"not": "a policy"})
        before = self.store_bytes()
        self.refused(500, "malformed_policy", "DELETE",
                     self.delete_path("broken"))
        self.assertEqual(self.store_bytes(), before)  # fail-closed
        # The assembled read model fails closed too, reason verbatim.
        self.refused(500, "malformed_policy", "GET", self.project_path())
        # The API-level recovery: a valid re-put succeeds and replaces it.
        fixed = policy_object("broken")
        self.assertEqual(self.put_policy_api(fixed), fixed)
        self.assertEqual(self.entry_policies(), [fixed])
        self.assertEqual(self.envelopes().read(key)["revision"], 2)
        # The recovered policy deletes normally.
        self.expect(200, "DELETE", self.delete_path("broken"))
        self.assertEqual(self.entry_policies(), [])

    def test_invalid_envelope_blocks_both_verbs_remedy_is_store_level(self):
        # Amendment A2's second pin: an entry whose stored ENVELOPE is
        # itself invalid cannot be replaced through the put route nor
        # tombstoned through the gated delete — BOTH verbs are gated by
        # the sealed envelope read. The gate matters most for corrupt
        # envelopes that still carry a readable revision: the raw sealed
        # put would silently overwrite those (it reads the prior envelope
        # only for its revision), so the matrix covers both the
        # revision-unreadable and the revision-readable corruptions.
        # Both verbs refuse writing nothing; the remedy is store-level,
        # because descriptors are disposable by design: remove the store
        # file, delete the now-storeless project, re-declare fresh.
        client = kvstore.LocalKVClient(self.store_dir())
        key = self.key_of("wedged")
        intact = policy_object("wedged")
        for shape in (
            {"value": policy_object("wedged"), "deleted?": False},  # no rev
            "not-even-a-dict",
            # Revision readable, envelope still invalid:
            {"revision": 3, "deleted?": False},  # value key missing
            {"revision": 3, "value": intact, "deleted?": "yes"},  # bad flag
            {"revision": 3, "value": intact, "deleted?": False,
             "extra": 1},  # foreign key
            {"revision": True, "value": intact, "deleted?": False},  # bool
        ):
            with self.subTest(shape=repr(shape)[:60]):
                client.put(key, shape)
                before = self.store_bytes()
                self.refused(500, "malformed_store", "POST",
                             self.policies_path(), policy_object("wedged"))
                self.assertEqual(self.store_bytes(), before)
                self.refused(500, "malformed_policy", "DELETE",
                             self.delete_path("wedged"))
                self.assertEqual(self.store_bytes(), before)
        # The exact operator remedy, observable end to end.
        os.unlink(self.kv_file())
        self.expect(200, "DELETE", self.project_path())
        created = self.create_project()
        self.assertEqual(
            created, {"slug": PROJECT, "work_areas": [], "policy": []}
        )

    def test_delete_id_rides_query_never_a_path_segment(self):
        # Amendment A2's first pin. The sealed fragment grammar admits
        # ids like "." and ".." that browsers NORMALIZE AWAY inside URL
        # path segments (a policy delete could silently become a project
        # delete), so the id rides as an URL-encoded query parameter and
        # every sealed-valid id round-trips.
        for policy_id in (".", "..", "dotted id", "50% & +plus"):
            with self.subTest(policy_id=policy_id):
                policy = policy_object(policy_id)
                self.put_policy_api(policy)
                self.assertEqual(self.entry_policies(), [policy])
                self.expect(200, "DELETE", self.delete_path(policy_id))
                self.assertEqual(self.entry_policies(), [])
        # A missing or blank id parameter is a blank fragment: refused by
        # the sealed grammar (the project-bound gates still run first);
        # no policy key is consulted and nothing is written.
        self.refused(400, "invalid_policy", "DELETE", self.policies_path())
        self.refused(400, "invalid_policy", "DELETE",
                     self.policies_path() + "?id=")
        # No path-segment delete route EXISTS: the dotted forms browsers
        # rewrite can never address a policy — or the project — here.
        live = policy_object("..")
        self.put_policy_api(live)
        for segment in ("%2E%2E", "..", "."):
            with self.subTest(segment=segment):
                status, body = self.request_json(
                    "DELETE", self.policies_path() + "/" + segment
                )
                self.assertEqual((status, body["error"]),
                                 (404, "not found"))
        self.assertEqual(self.entry_policies(), [live])  # nothing deleted
        body = self.expect(200, "GET", "/api/projects")  # project intact
        self.assertEqual(len(body["projects"]), 1)

    # -- served-page markers (AC6) ---------------------------------------------

    def test_served_page_carries_the_operator_surfaces(self):
        req = urllib.request.Request(self.base + "/")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            text = resp.read().decode("utf-8")
        # Pre-existing markers stay intact (test_root_serves_panel).
        self.assertIn("Milestone Orchestrator", text)
        self.assertIn('id="runs"', text)
        # The standing projects surface: the per-project editor (opened
        # from the sidebar tree), the create dialog behind "+ Project",
        # and the sidebar loader that shows run-less projects.
        self.assertIn('id="projedit"', text)
        self.assertIn('id="peBody"', text)
        self.assertIn('id="projcreate"', text)
        self.assertIn("openProjectEditor(", text)
        self.assertIn("openProjectCreate()", text)
        self.assertIn("presentProjectKeys", text)
        self.assertIn('aria-haspopup="menu"', text)
        self.assertIn('role="menuitem"', text)
        self.assertIn("configureProject(", text)
        self.assertNotIn("OTHERS_KEY", text)
        self.assertIn(
            'codex: ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]',
            text,
        )
        for model_id, visible in (
            ("gpt-5.6-sol", "sol"),
            ("gpt-5.6-terra", "terra"),
            ("gpt-5.6-luna", "luna"),
            ("gpt-5.5", "5.5"),
            ("fable-5", "fable"),
            ("opus-5", "opus"),
            ("sonnet-5", "sonnet"),
        ):
            self.assertIn('"%s": "%s"' % (model_id, visible), text)
        # The safeguard editor dialog.
        self.assertIn('id="sgeditor"', text)
        self.assertIn('id="sg_json"', text)
        # The launch-binding controls.
        self.assertIn('id="f_project"', text)
        self.assertIn('id="f_area"', text)
        self.assertIn('id="f_resolved"', text)
        # Every control rides the one read model and the policy routes.
        self.assertIn("/api/projects", text)
        self.assertIn("/policies", text)

    def test_panel_excludes_dot_segment_work_area_names(self):
        # Amendment A2's transport rule, applied to work-area NAMES: "."
        # and ".." are sealed-valid names, but encodeURIComponent leaves
        # dots bare and browsers normalize dot segments out of URL paths
        # before any route sees them — a work-area DELETE on ".." would
        # reach the PROJECT delete route. The panel therefore neither
        # authors nor addresses such names (the sealed slice-07 API is
        # unchanged; non-normalizing machine clients still round-trip
        # them). No JS harness exists, so the guard is pinned at the
        # served-page level (the AC6 posture): the guard function plus
        # its five call sites — redeclare (work dir / read-root edits),
        # named declare, relabel, delete, meta.
        req = urllib.request.Request(self.base + "/")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            text = resp.read().decode("utf-8")
        self.assertIn("function waDotSegment", text)
        self.assertEqual(text.count("waDotSegment("), 6)


if __name__ == "__main__":
    unittest.main()
