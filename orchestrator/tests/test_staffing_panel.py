"""Panel contracts for the staffing router (staffing-router slice 8).

Two parts so far. The RUN's staffing: the settings page reads the run's
live session through the router's own routes and edits exactly its four
editable fields, and the per-run model-profile chooser and act-override
dialog retire with the routes they used. The SERVICE's staffing catalogue:
the standing sidebar surface reads whole staffing documents and lets the
administrator save one whole document back, and the model-profile
catalogue and editor retire with `GET/POST /api/model-profiles`.

Two registers, as the panel's other suites use: static assertions over
`static/panel.html` for what the single-page panel asks for, and live
assertions through a real `service.make_server` for what those requests
actually do. The service harness is `test_staffing_api`'s, unchanged.
"""

import json
import os
import re
import subprocess
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from orchestrator import access, registry, service, task_api
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import driver as drv
from orchestrator import model_profiles as mp
from orchestrator import staffing as stf
from orchestrator import state as st

from orchestrator.tests.test_staffing_api import (
    AREA, PROJECT, StaffingApiTestCase, house_doc,
)

PANEL = (Path(__file__).resolve().parents[1] / "static" / "panel.html")


class PanelSourceMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.panel = PANEL.read_text(encoding="utf-8")
        # Everything the run's session card and editor are made of, bounded
        # by its own section header: no other surface may answer for it.
        cls.session_ui = cls.panel.split(
            "/* ---- the run's live staffing session", 1
        )[1].split("/* ---- ", 1)[0]
        # Same bounding for the standing document catalogue and its editor.
        cls.documents_ui = cls.panel.split(
            "/* ---- the staffing-document catalogue", 1
        )[1].split("/* ---- ", 1)[0]
        # And for the one control every standalone entry point shares.
        cls.standalone_ui = cls.panel.split(
            "/* ---- the shared standalone staffing choice", 1
        )[1].split("/* ---- ", 1)[0]

    def section(self, source, header):
        """One whole top-level function body, by its declaration."""
        found = re.search(header + r" \{\n(.*?)\n\}", source, re.S)
        self.assertIsNotNone(found, header)
        return found.group(1)

    @staticmethod
    def code(source):
        """One excerpt with its prose stripped: an absence assertion is
        about what the page DOES, not about what its comments explain.

        A section slice starts INSIDE its own header comment, so the
        dangling opener that survives the split is prose here too.
        """
        _head, sep, rest = source.partition("---- */")
        return re.sub(r"(?m)//.*$", "",
                      re.sub(r"/\*.*?\*/", "", rest if sep else source,
                             flags=re.S))


class RunSessionPanelControls(PanelSourceMixin, StaffingApiTestCase):
    """The settings page shows and edits ONE live session (amendment A3)."""

    def launch(self, name, **extra):
        payload = {
            "workspace": self.workspace(name), "goal": "staffed goal",
            "autostart": False, "config": {"docs_dir": "docs"},
        }
        payload.update(extra)
        return self.expect(201, "POST", "/api/runs", payload)["run"]

    def state_path_of(self, run):
        return registry.get(registry.load(self.home), run["id"])["state_path"]

    def test_run_session_controls_read_edit_clear_and_warn(self):
        # -- what the panel asks for ------------------------------------
        self.assertIn('id="f_staffing_material"', self.panel)
        self.assertIn(
            'material: document.getElementById("f_staffing_material")',
            self.panel,
        )
        self.assertIn('value="default"', self.panel)
        # The binding comes from the summary's id and nothing else, and the
        # selection is read live from the session's own route.
        self.assertIn("(d.summary || {}).staffing_session", self.panel)
        self.assertEqual(self.panel.count('"/api/staffing/sessions/"'), 2)
        self.assertEqual(self.panel.count("encodeURIComponent(sessionId)"), 1)
        # Exactly the four editable fields, and the two optional ones ride
        # as an explicit null when emptied — the store's own clear.
        save = re.search(
            r"async function saveStaffingSession\(\) \{(.*?)\n\}",
            self.session_ui, re.S).group(1)
        self.assertRegex(save, r"document: document\.getElementById"
                               r'\("ss_document"\)\.value,')
        self.assertRegex(save, r"rigor: document\.getElementById"
                               r'\("ss_rigor"\)\.value,')
        self.assertIn("material: material || null,", save)
        self.assertIn("overrides: overrides,", save)
        for absent in ("work_area", "families", "agent", "model", "effort",
                       "index", "round", "family"):
            self.assertNotIn("%s:" % absent, save)
        # Opening seeds from the last poll and writes nothing.
        self.assertNotIn("postJSON", re.search(
            r"async function openStaffingSession\(\) \{(.*?)\n\}",
            self.session_ui, re.S).group(1))
        # The split projection is shown, never used as a gate.
        self.assertIn("staffingSplitWarning", self.session_ui)
        self.assertNotIn("disabled", self.session_ui)

        # -- what those requests do -------------------------------------
        # A launched run's card loads exactly the stored session.
        run = self.launch("ws-session-card")
        bound = st.load(self.state_path_of(run))["staffing_session"]
        self.assertEqual(
            self.expect(200, "GET", "/api/runs/%s" % run["id"]
                        )["summary"]["staffing_session"], bound)
        view = self.expect(200, "GET", self.session_path(bound))
        self.assertEqual(view["session"], stf.read_session(self.home, bound))
        self.assertEqual(view["session"]["material"], "default")

        # A declared split this session cannot honour is projected beside
        # the record and blocks neither the read nor the write.
        self.expect(200, "POST", "/api/staffing/documents", house_doc())
        member = self.member()
        session = self.create_session(
            headers=member, families=["codex"])["id"]
        view = self.expect(200, "GET", self.session_path(session),
                           headers=member)
        self.assertEqual(view["distinct_families_unsatisfiable"], ["review"])

        # Every authorized session owner edits it, live and by project
        # access alone (amendment A3) — no creator, owner or admin rung.
        edited = self.expect(200, "POST", self.session_path(session), {
            "document": "house", "rigor": "high",
            "material": "prose", "overrides": {"assignment": {"plan": {"1": 2}}},
        }, headers=member)["session"]
        self.assertEqual(
            (edited["rigor"], edited["material"]), ("high", "prose"))
        self.assertEqual(edited, stf.read_session(self.home, session))
        self.assertEqual(
            self.expect(200, "GET", self.session_path(session),
                        headers=member
                        )["distinct_families_unsatisfiable"], ["review"])

        # An emptied optional field clears it; the other three are untouched.
        cleared = self.expect(200, "POST", self.session_path(session), {
            "document": "house", "rigor": "high",
            "material": None, "overrides": None,
        }, headers=member)["session"]
        self.assertNotIn("material", cleared)
        self.assertNotIn("overrides", cleared)
        self.assertEqual(cleared["families"], ["codex"])
        self.assertEqual(cleared["work_area"],
                         {"project": PROJECT, "work_area": AREA})

        # A caller who may not work in that project may not edit it either.
        foreign = self.member_headers(access.USER_EMAILS[1])
        before = self.session_bytes(session)
        self.refused(403, service.FORBIDDEN, "POST",
                     self.session_path(session), {"rigor": "low"},
                     headers=foreign)
        self.refused(403, service.FORBIDDEN, "GET",
                     self.session_path(session), headers=foreign)
        self.assertEqual(self.session_bytes(session), before)

    def test_run_session_controls_do_not_bind_or_repair(self):
        # -- what the panel asks for ------------------------------------
        # No create, no repair, no second staffing field: the settings page
        # only reads the id the summary carries and writes that session.
        self.assertNotIn('"/api/staffing/sessions"', self.session_ui)
        self.assertNotIn("method: \"POST\"", self.session_ui)
        self.assertIn("No session is bound to this run yet", self.session_ui)
        self.assertIn("nothing here binds, derives or repairs it",
                      self.session_ui)
        self.assertIn("does not\n        rebind or repair it",
                      self.session_ui)
        # The unreadable branch shows the route's own refusal, verbatim.
        self.assertIn("esc(lastSessionError", self.session_ui)

        # -- what those requests do -------------------------------------
        # An unbound run stays unbound: no session key, no session file.
        ws = self.workspace("ws-unbound")
        drv.init_run("old run", ws, state_path=drv.default_state_path(ws))
        run = self.expect(201, "POST", "/api/runs", {
            "workspace": ws, "attach": True, "autostart": False,
        })["run"]
        before = self.catalogue_files()
        detail = self.expect(200, "GET", "/api/runs/%s" % run["id"])
        self.assertNotIn("staffing_session", detail["summary"])
        self.assertEqual(self.catalogue_files(), before)

        # An id no record answers is the route's one refusal, and reading it
        # neither creates nor repairs anything.
        self.refused(404, service.UNKNOWN_STAFFING_SESSION,
                     "GET", self.session_path("stf-" + "0" * 32))
        self.assertEqual(self.catalogue_files(), before)


class RetiredRunStaffingSurfaces(PanelSourceMixin, StaffingApiTestCase):
    """The per-run profile chooser and the act overlay leave together."""

    def test_retired_run_routes_and_controls_are_absent(self):
        ws = self.workspace("ws-retired")
        run = self.expect(201, "POST", "/api/runs", {
            "workspace": ws, "goal": "retired surfaces", "autostart": False,
        })["run"]
        runtime = os.path.dirname(
            registry.get(registry.load(self.home), run["id"])["state_path"])

        def sidecar_bytes():
            out = {}
            for name in ("model_profile.json", "acts.json"):
                path = os.path.join(runtime, name)
                if os.path.exists(path):
                    with open(path, "rb") as fh:
                        out[name] = fh.read()
            return out

        before = sidecar_bytes()
        # Accessible target, retired input: the ordinary absent-route answer.
        for method, suffix, payload in (
            ("GET", "model-profile", None),
            ("POST", "model-profile", {"name": "default", "rigor": "low"}),
            ("POST", "acts", {"fixer": "claude"}),
            ("PATCH", "acts", {"fixer": None}),
        ):
            with self.subTest(route="%s %s" % (method, suffix)):
                status, body = self.request(
                    method, "/api/runs/%s/%s" % (
                        urllib.parse.quote(run["id"], safe=""), suffix),
                    payload=payload)
                self.assertEqual(status, 404, body)
                self.assertEqual(body, {"ok": False, "error": "not found"})
        self.assertEqual(sidecar_bytes(), before)

        # Run detail loses the member that existed only for that dialog.
        detail = self.expect(200, "GET", "/api/runs/%s" % run["id"])
        self.assertNotIn("acts", detail)

        # And the controls that called them are gone from the panel.
        for retired in ('id="actsdlg"', 'id="modelprofileselectiondlg"',
                        'id="a_skeletoner_agent"', 'id="ra_skeletoner_agent"',
                        "collectActs", "ACT_NAMES", "openActs", "saveActs"):
            self.assertNotIn(retired, self.panel)
        self.assertIsNone(re.search(
            r"/api/runs/\$\{[^}]+\}/(model-profile|acts)", self.panel))


class StaffingDocumentCatalogue(PanelSourceMixin, StaffingApiTestCase):
    """The standing catalogue: whole documents in, whole documents out."""

    def ladders_of(self, document):
        """Every model and effort ladder, in the document's own order."""
        return [(slot["models"], slot["efforts"])
                for _key, slot in sorted(document["families"].items())]

    def test_document_editor_uses_whole_api_and_preserves_ladder_order(self):
        # -- what the panel asks for ------------------------------------
        # Two routes and no third: the catalogue read every staffing choice
        # in this panel already shares, and the one whole-document write.
        self.assertIn('api("/api/staffing/documents")', self.panel)
        self.assertIn('postJSON("/api/staffing/documents", parsed)',
                      self.documents_ui)
        self.assertEqual(self.panel.count("/api/staffing/documents"), 2)

        # Inspection is every authorized viewer's; only the save controls
        # are the administrator's.
        opener = self.section(
            self.documents_ui, r"async function openStaffingDocuments\(\)")
        self.assertNotIn("appAccess.admin", opener)
        render = self.section(
            self.documents_ui, r"function renderStaffingDocuments\(\)")
        self.assertIn('create.style.display = appAccess.admin ? "" : "none";',
                      render)
        self.assertIn("appAccess.admin ?", render)
        for guard in (r"function editStaffingDocument\(name\)",
                      r"function newStaffingDocument\(\)"):
            self.assertIn("if (!appAccess.admin) return;",
                          self.section(self.documents_ui, guard))
        # What a viewer reads is the WHOLE stored document, not a summary
        # the panel would need the schema to build.
        self.assertIn("JSON.stringify(doc, null, 1)", render)

        # No client-side schema, sort, or price rule on this path at all:
        # the ladders are the operator's capability order (amendment A1)
        # and the service is the only validator of what any of it means.
        for forbidden in (".sort(", "localeCompare", "reverse()", "price",
                          "cost", "MODEL_OPTS", "EFFORT_OPTS", "families",
                          "tuning", "assignment", "roles", "materials"):
            self.assertNotIn(forbidden, self.documents_ui)
        # The editor is the shared syntax-only one, and that parse is its
        # ONLY client-side check: it returns before the request, so invalid
        # JSON never reaches the service and changes nothing.
        self.assertIn("openSgEditor({", self.documents_ui)
        save = self.section(self.panel, r"async function saveSgEditor\(\)")
        self.assertIn('catch (e) { err.textContent = "not valid JSON: "'
                      " + e.message; return; }", save)
        self.assertIn("await sgEditor.onSave(parsed);", save)
        self.assertLess(save.index("not valid JSON"), save.index("onSave"))
        # A new document is seeded from a STORED one, so the panel still
        # holds no document shape of its own.
        seed = self.section(self.documents_ui, r"function newStaffingDocument\(\)")
        self.assertIn('staffingDocuments.find(doc => doc.name === "default")',
                      seed)
        self.assertIn('{name: ""}', seed)

        # -- what those requests do -------------------------------------
        member = self.member()
        posted = house_doc("ladders")
        ladders = self.ladders_of(posted)
        # The round trip below only means something because sorting would
        # move every one of these ladders: capability order is not, and is
        # not meant to be, alphabetical order.
        for models, efforts in ladders:
            self.assertNotEqual(models, sorted(models))
            self.assertNotEqual(efforts, sorted(efforts))

        saved = self.expect(200, "POST", "/api/staffing/documents",
                            posted)["document"]
        self.assertEqual(saved, posted)
        # Through the store's own bytes, and through the read the panel
        # renders and re-seeds from: the same arrays, in the same order.
        self.assertEqual(
            self.ladders_of(json.loads(self.document_bytes("ladders"))),
            ladders)
        listed = self.expect(200, "GET", "/api/staffing/documents",
                             headers=member)["documents"]
        by_name = {doc["name"]: doc for doc in listed}
        self.assertEqual(by_name["ladders"], posted)
        self.assertEqual(self.ladders_of(by_name["ladders"]), ladders)

        # A semantically invalid whole document is the service's own
        # refusal, verbatim, and the predecessor keeps every byte.
        before = self.document_bytes("ladders")
        broken = house_doc("ladders")
        broken["assignment"]["plan"] = {"1": 9}  # a slot nobody carries
        self.refused(400, service.INVALID_STAFFING_DOCUMENT, "POST",
                     "/api/staffing/documents", broken)
        self.assertEqual(self.document_bytes("ladders"), before)
        # A viewer who is offered no save control does not write one either.
        self.refused(403, service.FORBIDDEN, "POST",
                     "/api/staffing/documents", house_doc("ladders"),
                     headers=member)
        self.assertEqual(self.document_bytes("ladders"), before)

    def test_retired_model_profile_catalogue_and_routes_are_absent(self):
        """`GET/POST /api/model-profiles` retire with their catalogue.

        The documents they wrote are compatibility bytes — amendment A2
        still reads a run's selected profile name and rigor at resume — so
        nothing here deletes, rewrites or migrates one.
        """
        profiles_dir = mp.model_profiles_dir(self.home)

        def profile_bytes():
            out = {}
            for name in sorted(os.listdir(profiles_dir)):
                with open(os.path.join(profiles_dir, name), "rb") as fh:
                    out[name] = fh.read()
            return out

        # Startup seeded `default`; a second stored document makes the
        # snapshot more than that seed.
        mp.save(self.home, {
            "name": "kept", "examples": ["a retired catalogue"],
            "configurations": {"low": {}, "medium": {"fixer": "codex"},
                               "high": {}},
        })
        before = profile_bytes()
        self.assertEqual(sorted(before), ["default.json", "kept.json"])

        # The local administrator, so the answer is about the ROUTE and not
        # about access: the ordinary absent-route answer, on both methods.
        for method, payload in (
            ("GET", None),
            ("POST", {"name": "new", "examples": ["a refused create"],
                      "configurations": {"low": {}, "medium": {},
                                         "high": {}}}),
        ):
            with self.subTest(method=method):
                status, body = self.request(
                    method, "/api/model-profiles", payload=payload)
                self.assertEqual(status, 404, body)
                self.assertEqual(body, {"ok": False, "error": "not found"})
        self.assertEqual(profile_bytes(), before)

        # The controls that called them are gone, and the catalogue the
        # sidebar now offers in that place is the staffing-document one.
        for retired in ('id="modelprofilesdlg"', 'id="mpeditor"',
                        'id="modelProfilesBtn"', "openModelProfiles(",
                        "MP_ROWS", "mpRenderGrid", "saveModelProfileEditor",
                        "/api/model-profiles"):
            self.assertNotIn(retired, self.panel)
        self.assertIn('id="staffingDocsBtn"', self.panel)
        self.assertIn('onclick="openStaffingDocuments()">Staffing documents',
                      self.panel)
        self.assertIn('id="staffingdocsdlg"', self.panel)


class RecordingTaskHost:
    """Admits and never runs.

    What the panel must prove about a direct order is what it SENDS: the
    durable order carries the id of the session the form just opened. What
    the direct host then does with that id is slice 7's own contract, and
    running a real agent call here would prove nothing this surface owns.
    """

    def __init__(self):
        self.started = []

    def start(self, record, _resolver):
        self.started.append(record["id"])

    def owns_workspace(self, _workspace):
        return False


class StandaloneStaffingHandoff(PanelSourceMixin, StaffingApiTestCase):
    """One shared choice, one session, one id — at all four entry points."""

    GS_AREA = "align area"

    def setUp(self):
        self.task_host = RecordingTaskHost()
        patched = mock.patch.object(
            service.task_api, "DirectTaskHost", return_value=self.task_host)
        patched.start()
        self.addCleanup(patched.stop)
        self.processes = []
        self.addCleanup(self.reap_launched)
        super().setUp()

    # -- fixtures --------------------------------------------------------

    def reap_launched(self):
        for process in self.processes:
            process.kill()
            process.wait(timeout=5)

    def project_path(self, *suffix):
        return "/".join(
            ["/api/projects", urllib.parse.quote(PROJECT, safe="")]
            + list(suffix))

    def declare(self, name, primary):
        return self.expect(200, "POST", self.project_path("work-areas"),
                           {"name": name, "primary_path": primary})

    def entry(self, headers=None):
        """The project view the standalone forms already load."""
        listed = self.expect(200, "GET", "/api/projects",
                             headers=headers)["projects"]
        return next(item for item in listed if item["slug"] == PROJECT)

    def derived_order(self):
        """The order the STANDALONE CONSUMERS derive for this project —
        the direct host's own configuration seam, not a copy of the merge."""
        return service._direct_task_config(self.home, PROJECT)["families_order"]

    def panel_session(self, entry, area, document="house", rigor="high",
                      material=None, headers=None):
        """The panel's FIRST request, exactly as the shared control builds
        it: the selected work area, the selection shown, and the families
        fact the project view supplied — never a constant written here."""
        body = {
            "work_area": {"project": entry["slug"], "work_area": area},
            "families": entry["families_order"],
            "document": document,
            "rigor": rigor,
        }
        if material:
            body["material"] = material
        return self.expect(201, "POST", "/api/staffing/sessions", body,
                           headers=headers)["session"]["id"]

    def task_body(self, executor, area, session):
        return {
            "task_executor": executor,
            "staffing_session": session,
            "request": {
                "work_area": {"project": PROJECT, "work_area": area},
                "request": "Do exactly the caller-authored work.",
                "context": "",
                "reference_documents": [],
            },
        }

    def discussion_body(self, workspace, area, session):
        target = os.path.join(workspace, "DECISION.md")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("initial target\n")
        return {
            "request": {
                "workspace_path": workspace,
                "target_path": "DECISION.md",
                "request": "Settle the bounded request.",
                "context": {"brief": "Everything the seats need."},
                "max_rounds": 1,
            },
            # Exactly what the dedicated form now sends per seat.
            "participants": [
                {"id": "initial-position", "role": "initial_position",
                 "delivery": "llm"},
                {"id": "critic-1", "role": "contrary_position",
                 "delivery": "llm"},
            ],
            "closure_policy": "unanimity",
            "project": PROJECT,
            "work_area": area,
            "staffing_session": session,
        }

    def sleeper_launch(self, *_args, **_kwargs):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        self.processes.append(process)
        return lifecycle.GatedLaunch(process, lambda: None, lambda: None)

    def task_orders(self):
        return [record["order"]
                for record in task_api.StandaloneTaskStore(self.home).records()]

    # -- the four handoffs ----------------------------------------------

    def test_standalone_forms_create_and_carry_one_session(self):
        # -- what the panel asks for ------------------------------------
        # One control, rendered from one place, hosted by all three dialogs
        # (the direct form covers both the agent call and the task-owned
        # discussion, which differ only in the executor already chosen).
        for host in ('id="task_staffing"', 'id="bs_staffing"',
                     'id="gs_staffing"'):
            self.assertIn(host, self.panel)
        for opened in ('loadStandaloneStaffing("task")',
                       'loadStandaloneStaffing("bs")',
                       'loadStandaloneStaffing("gs")'):
            self.assertEqual(self.panel.count(opened), 1)
        # One create route in the whole panel, reached from one function,
        # called once per entry point and never anywhere else.
        self.assertEqual(self.panel.count('"/api/staffing/sessions"'), 1)
        self.assertIn('postJSON("/api/staffing/sessions", body)',
                      self.standalone_ui)
        self.assertEqual(
            self.panel.count("await standaloneStaffingSession("), 3)
        # The returned id rides the operation's OWN existing field.
        self.assertIn("payload.staffing_session = await standaloneStaffingSession(",
                      self.panel)
        self.assertIn("body: JSON.stringify({work_area: area, "
                      "staffing_session: session}),", self.panel)
        # Families are read from the project view, never held here: the
        # three sources are the three project reads the forms already make.
        create = self.section(
            self.standalone_ui,
            r"async function standaloneStaffingSession\(prefix, workArea, families\)")
        self.assertIn("families: families,", create)
        self.assertIn("if (material) body.material = material;", create)
        for source in ("].families_order;", "project.families_order",
                       "gitSyncFamilies = project ? project.families_order : null;"):
            self.assertIn(source, self.panel)
        # Two of those three reads name their project in the same expression
        # that supplies the fact. The alignment's does not — it keeps the
        # order in a global that outlives one open — so its read only lands
        # while the dialog still names the project it was made for, on both
        # its success and its failure path. Otherwise an earlier project's
        # slower read would staff a later project's alignment.
        opening = self.code(self.section(
            self.panel, r"async function openGitSync\(event, key\)"))
        guard = "if (key !== gitSyncProject) return;"
        self.assertEqual(opening.count(guard), 2)
        self.assertLess(opening.index(guard),
                        opening.index("gitSyncFamilies = project ?"))
        # And the alignment goes to the project whose Sync was pressed:
        # the submit captures its slug and its families BEFORE the session
        # round trip and never reads those globals again, so a dialog
        # closed and reopened on another project mid-request cannot
        # retarget a merge-and-push at the repository it now names.
        aligning = self.code(self.section(
            self.panel, r"async function runGitSync\(\)"))
        self.assertIn("const project = gitSyncProject;", aligning)
        self.assertIn("const families = gitSyncFamilies;", aligning)
        after = aligning.split("const families = gitSyncFamilies;", 1)[1]
        self.assertIn("{project: project, work_area: area}, families)", after)
        self.assertIn('encodeURIComponent(project) + "/git-sync"', after)
        self.assertNotIn("gitSyncFamilies", after)
        # …and what comes BACK is shown under the name it was asked for:
        # the verdict, the report and the button state are written only
        # while the shared dialog still names this project, so a reply to
        # a superseded open is dropped instead of rendering A's "Aligned."
        # inside the dialog now labelled B. That is the one thing the
        # global may still be read for here.
        for read in after.split("gitSyncProject")[:-1]:
            self.assertTrue(read.endswith("if (project !== ")
                            or read.endswith("if (project === "), read[-60:])
        self.assertEqual(
            after.count("if (project !== gitSyncProject) return;"), 2)
        self.assertIn("if (project === gitSyncProject) go.disabled = false;",
                      after)
        # A project the view could not supply that fact for submits nothing.
        self.assertIn("if (!Array.isArray(families))", create)
        self.assertIn("if (staffingDocumentsError) throw new Error(", create)

        # -- what those requests do -------------------------------------
        member = self.member()
        self.expect(200, "POST", "/api/staffing/documents", house_doc())
        work = self.workspace("ws-standalone")
        align = self.workspace("ws-align")
        self.declare(AREA, work)
        self.declare(self.GS_AREA, align)

        # The fact the view carries IS the order the standalone consumers
        # derive — under the service default and under a project override.
        for label, defaults in (
            ("service default", None),
            ("project override", {"families_order": ["claude", "codex"]}),
        ):
            with self.subTest(order=label):
                updated = None
                if defaults is not None:
                    updated = self.expect(200, "POST", self.project_path(),
                                          {"defaults": defaults})["project"]
                entry = self.entry()
                self.assertEqual(entry["families_order"],
                                 self.derived_order())
                # Every route that answers with an entry gains that one
                # fact — the listing, the single read and the defaults
                # update alike — and a member reads what an admin reads.
                self.assertEqual(
                    self.expect(200, "GET", self.project_path()
                                )["project"], entry)
                if updated is not None:
                    self.assertEqual(updated, entry)
                self.assertEqual(self.entry(headers=member), entry)
                session = self.panel_session(entry, AREA, material="prose",
                                             headers=member)
                stored = stf.read_session(self.home, session)
                self.assertEqual(stored["families"], entry["families_order"])
                self.assertEqual(stored["work_area"],
                                 {"project": PROJECT, "work_area": AREA})
                self.assertEqual(
                    (stored["document"], stored["rigor"], stored["material"]),
                    ("house", "high", "prose"))

        # The order the project now derives is NOT the service default:
        # a browser constant would have recorded the wrong one above.
        self.assertNotEqual(self.derived_order(),
                            drv.DEFAULT_CONFIG["families_order"])

        # 1 + 2. The direct form, at both executors it can order.
        entry = self.entry()
        for executor in ("agent_call", "brainstorming"):
            with self.subTest(executor=executor):
                session = self.panel_session(entry, AREA)
                task = self.expect(201, "POST", "/api/tasks",
                                   self.task_body(executor, AREA, session))
                self.assertIn(task["task"]["id"], self.task_host.started)
                self.assertEqual(
                    task["task"]["order"]["staffing_session"], session)
                self.assertIn(
                    session, [order["staffing_session"]
                              for order in self.task_orders()])

        # 3. The dedicated discussion form.
        session = self.panel_session(entry, AREA)
        with mock.patch.object(lifecycle, "_launch_lifecycle_process",
                               side_effect=self.sleeper_launch):
            created = self.expect(
                201, "POST", "/api/brainstorming/sessions",
                self.discussion_body(work, AREA, session))
        record = lifecycle._record_by_id(self.home, created["session"]["id"])
        self.assertEqual(record["staffing_session"], session)
        # Its seats were staffed BY that session, on the project's own
        # family order — nothing the participant entries pinned.
        seats = [seat["model_family"] for seat in
                 created["session"]["state"]["run_config"]["participants"]]
        self.assertEqual(seats, [
            stf.resolve(self.home, session, "brainstorm", index=index, round=1,
                        families=list(entry["families_order"])
                        ).answer["agent"]
            for index in (1, 2)])

        # 4. The git alignment, whose one call resolves through it live.
        session = self.panel_session(entry, self.GS_AREA)
        answer = stf.resolve(self.home, session, "sync", index=1, round=1,
                             families=list(entry["families_order"])).answer
        captured = []
        with mock.patch.object(
            service.gitsync, "run_sync",
            side_effect=lambda *args, **kwargs: (
                captured.append((args[2], kwargs.get("model"),
                                 kwargs.get("effort")))
                or {"outcome": "aligned", "report": "done"})
        ):
            synced = self.expect(200, "POST", self.project_path("git-sync"),
                                 {"work_area": self.GS_AREA,
                                  "staffing_session": session})
        self.assertEqual(synced["sync"]["outcome"], "aligned")
        self.assertEqual(
            captured, [(answer["agent"], answer["model"], answer["effort"])])

        # A fact the session store would not keep VERBATIM is not a handoff
        # this panel makes either. The store normalizes each catalogue
        # string it keeps, so the order the router later reads can differ
        # from the one the project names — a different family, at a
        # different cost, staffing the operation. The shared control
        # compares what came back with what it sent and submits nothing on
        # a mismatch, so no operation is ordered on families nobody chose.
        self.expect(200, "POST", self.project_path(),
                    {"defaults": {"families_order": [" codex ", "claude"]}})
        padded = self.entry()
        self.assertEqual(padded["families_order"], [" codex ", "claude"])
        drifted = self.panel_session(padded, AREA)
        self.assertNotEqual(stf.read_session(self.home, drifted)["families"],
                            padded["families_order"])
        self.assertIn("const stored = (created.session || {}).families;",
                      create)
        self.assertIn("stored.some((name, i) => name !== families[i])",
                      create)

        # And a project whose declared defaults leave no readable order
        # carries no fact at all: the entry is still a successful entry —
        # every other project route answers exactly as before — while the
        # guard above has nothing to submit an operation on.
        opened = self.catalogue_files()
        self.expect(200, "POST", self.project_path(),
                    {"defaults": {"families_order": "not an order"}})
        unreadable = self.entry()
        self.assertNotIn("families_order", unreadable)
        self.assertNotIn("error", unreadable)
        self.assertEqual(self.catalogue_files(), opened)

    def test_standalone_forms_expose_no_seat_staffing(self):
        # The shared control offers document, rigor and material, and the
        # three ids it renders are the only inputs it reads.
        markup = self.code(self.section(
            self.standalone_ui, r"function standaloneStaffingMarkup\(prefix\)"))
        self.assertEqual(
            re.findall(r"\$\{prefix\}_staffing_(\w+)", markup),
            ["document", "rigor", "material", "hint"])
        for pinned in ("family", "families", "model", "effort", "agent",
                       "index", "round", "seat", "assignment", "tuning"):
            self.assertNotIn(pinned, markup)
        # Rigor is the router's own three-value vocabulary, and the whole
        # control names no family, model or effort of its own: the one it
        # records is the fact the project view supplied.
        self.assertIn('const STANDALONE_RIGORS = ["low", "medium", "high"];',
                      self.standalone_ui)
        shared = self.code(self.standalone_ui)
        for named in ("codex", "claude", "gpt-", "opus", "sonnet", "fable",
                      "xhigh"):
            self.assertNotIn(named, shared)

        # The Agent-call role is still the catalogue's own control, built
        # from the returned schema and from no list written in the browser.
        task_ui = self.panel.split(
            "/* ---- standalone task ordering", 1
        )[1].split("/* ---- ", 1)[0]
        self.assertIn('api("/api/task-executors")', task_ui)
        self.assertIn("entry.configuration_schema", task_ui)
        self.assertIn("(definition.choices || [])", task_ui)
        for copied in ('"role"', '"agent_call"'):
            self.assertNotIn(copied, task_ui)

        # A dedicated Brainstorming participant entry carries the roster
        # fact and nothing about who runs it, at any roster size.
        submit = self.section(
            self.panel, r"async function submitBrainstorming\(\)")
        seat = re.search(r"const entry = \{(.*?)\n    \};", submit, re.S)
        self.assertEqual(
            sorted(re.findall(r"^\s*(\w+):", seat.group(1), re.M)),
            ["delivery", "id", "role"])
        self.assertIn("entry.external_provider = seat.externalProvider;",
                      submit)
        for pinned in ("model_family", "entry.model", "entry.effort"):
            self.assertNotIn(pinned, submit)
        add = self.section(self.panel, r"function addBsSeat\(\)")
        self.assertIn('bsRoster.push({role: "contrary_position", '
                      'delivery: "llm"});', add)
        # And the family/model/effort vocabulary the roster used to read
        # is gone from the page: one authority, and it is the document.
        for retired in ("const MODEL_OPTS", "const EFFORT_OPTS",
                        "const FAMILY_DEFAULTS", "function onAgentChange",
                        "_agent\"", "_effort\""):
            self.assertNotIn(retired, self.panel)

        # The catalogue this form reads says the same thing: a Brainstorming
        # order is staffed by its session, not by a profile or a roster pin.
        entries = {entry["id"]: entry for entry in
                   self.expect(200, "GET", "/api/task-executors"
                               )["task_executors"]}
        for executor in ("agent_call", "brainstorming"):
            with self.subTest(executor=executor):
                described = entries[executor]["available_agent_configurations"]
                self.assertIn("staffing session", described)
                self.assertNotIn("profiles", described)

    def test_handoff_failure_and_legacy_routes_are_bounded(self):
        """The two-request composition, and no retired input reborn here.

        Retirement itself is proven by this module's two retirement cases
        (`RetiredRunStaffingSurfaces` and the model-profile catalogue): what
        is asserted here is that the standalone surfaces this slice ADDS
        reach none of those routes.
        """
        # -- what the panel asks for ------------------------------------
        # The session is opened INSIDE the guarded submit and before the
        # operation, and nothing compensates for a refusal afterwards.
        submit = self.section(self.panel, r"async function submitTaskForm\(\)")
        self.assertLess(submit.index("taskSubmitPending = true"),
                        submit.index("await standaloneStaffingSession("))
        self.assertLess(submit.index("await standaloneStaffingSession("),
                        submit.index("await postJSON(path, payload)"))
        for surface in (submit,
                        self.section(self.panel,
                                     r"async function submitBrainstorming\(\)"),
                        self.section(self.panel, r"async function runGitSync\(\)")):
            self.assertEqual(surface.count("await standaloneStaffingSession("), 1)
        shared = self.code(self.standalone_ui)
        for forbidden in ("DELETE", "retry", "setTimeout", "setInterval",
                          "/api/model-profiles", "/model-profile", "/acts"):
            self.assertNotIn(forbidden, shared)
        self.assertNotIn("catch", shared)  # the caller shows the refusal

        # -- what those requests do -------------------------------------
        member = self.member()
        self.expect(200, "POST", "/api/staffing/documents", house_doc())
        work = self.workspace("ws-bounded")
        self.declare(AREA, work)
        entry = self.entry()
        before = self.catalogue_files()

        # Call one refused: no session, and no operation was ever sent.
        self.refused(400, service.INVALID_STAFFING_SESSION, "POST",
                     "/api/staffing/sessions",
                     {"work_area": {"project": PROJECT, "work_area": AREA},
                      "families": entry["families_order"],
                      "document": "house", "rigor": "unheard-of"},
                     headers=member)
        self.assertEqual(self.catalogue_files(), before)
        self.assertEqual(self.task_orders(), [])
        self.assertEqual(self.task_host.started, [])

        # Call two refused: the session stays, inert and readable, and no
        # work was admitted. Nothing deletes it and nothing tries again.
        session = self.panel_session(entry, AREA, headers=member)
        opened = self.catalogue_files()
        refused = self.task_body("agent_call", AREA, session)
        refused["request"]["request"] = ""  # the route's own refusal
        self.expect(400, "POST", "/api/tasks", refused, headers=member)
        self.assertEqual(self.catalogue_files(), opened)
        self.assertEqual(self.task_orders(), [])
        self.assertEqual(self.task_host.started, [])
        self.assertEqual(stf.read_session(self.home, session)["id"], session)
        # The retried-by-hand order is ONE order, on that same session.
        accepted = self.expect(201, "POST", "/api/tasks",
                               self.task_body("agent_call", AREA, session),
                               headers=member)
        self.assertEqual(len(self.task_orders()), 1)
        self.assertEqual(accepted["task"]["order"]["staffing_session"],
                         session)
        self.assertEqual(self.catalogue_files(), opened)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
