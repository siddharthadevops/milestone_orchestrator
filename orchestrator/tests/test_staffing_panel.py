"""Panel contracts for the staffing router (staffing-router slice 8).

This part covers the RUN's staffing: the settings page reads the run's live
session through the router's own routes and edits exactly its four editable
fields, and the per-run model-profile chooser and act-override dialog retire
with the routes they used.

Two registers, as the panel's other suites use: static assertions over
`static/panel.html` for what the single-page panel asks for, and live
assertions through a real `service.make_server` for what those requests
actually do. The service harness is `test_staffing_api`'s, unchanged.
"""

import os
import re
import unittest
import urllib.parse
from pathlib import Path

from orchestrator import access, registry, service
from orchestrator import driver as drv
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
