"""HTTP API tests for orchestrator/service.py.

Runs a real service.make_server(home, 0) in a thread (ephemeral port,
isolated tempdir home — never ~/.impl_roadmap) and exercises the JSON API
through urllib. No driver processes are ever spawned: every create uses
"autostart": false and liveness is simulated with registry.update(pid=...).
A tearDown guard still kills any accidentally spawned driver process group.
"""

import http.client
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from orchestrator import access, driver, interpreter, model_profiles, profiles, registry
from orchestrator import service, state as st, tasks


def load_tests(loader, tests, pattern):
    """Run the base HTTP contract once, not once through every subclass."""
    filtered = unittest.TestSuite()

    def cases(suite):
        for candidate in suite:
            if isinstance(candidate, unittest.TestSuite):
                yield from cases(candidate)
            else:
                yield candidate

    for test in cases(tests):
        inherited = ServiceApiTest.__dict__.get(test._testMethodName)
        if (
            test.__class__ is not ServiceApiTest
            and inherited is not None
            and getattr(test.__class__, test._testMethodName) is inherited
        ):
            continue
        filtered.addTest(test)
    return filtered


class ServiceApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-service-test-")
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.fake_drivers = []
        self.server = service.make_server(self.home, 0)
        self.port = self.server.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        # Safety net: no test should spawn a driver (autostart is always
        # false), but if one ever does, kill its process group.
        try:
            reg = registry.load(self.home)
            for entry in reg["runs"]:
                pid = entry.get("pid")
                if pid and pid != os.getpid() and registry.pid_alive(pid):
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except OSError:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except OSError:
                            pass
        except Exception:
            pass
        for proc in self.fake_drivers:
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    proc.kill()
            proc.wait()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def spawn_fake_driver(self):
        """A live session-leader process, exactly like a real spawned driver
        (start_new_session=True): the service trusts untracked pids only
        when they lead their own session. Killed in tearDown."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"],
            start_new_session=True,
        )
        self.fake_drivers.append(proc)
        return proc

    # -- helpers -----------------------------------------------------------

    def request(self, method, path, payload=None, raw_body=None):
        """Returns (status, raw bytes)."""
        data = raw_body
        if data is None and payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read()

    def request_json(self, method, path, payload=None, raw_body=None):
        """Returns (status, decoded JSON body)."""
        status, body = self.request(method, path, payload=payload, raw_body=raw_body)
        return status, json.loads(body.decode("utf-8"))

    def workspace(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path, exist_ok=True)
        # Launch-time rule: the workspace must be the root of an existing
        # git repository (no auto-init); tests create the ledger repo the
        # same deliberate way an operator would.
        subprocess.run(["git", "init", "-q", path], check=True)
        return path

    def create_run(self, ws, **extra):
        # Endpoint tests use the legacy flat-`docs` layout so the run's
        # runtime is at the historical <ws>/.orchestrator/ location these
        # tests reference. The per-milestone `.run/` layout is exercised
        # separately in TestPerMilestoneLayout. `docs_dir` is merged in
        # (not replaced) so a test's own config keys still take effect.
        cfg = {"docs_dir": "docs"}
        cfg.update(extra.pop("config", None) or {})
        payload = {"workspace": ws, "goal": "Test goal", "autostart": False,
                   "config": cfg}
        payload.update(extra)
        return self.request_json("POST", "/api/runs", payload)

    # -- static / routing --------------------------------------------------

    def test_root_serves_panel(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("Milestone Orchestrator", text)
        self.assertIn('font: 700 32px/1 "Space Grotesk"', text)
        self.assertIn('font-family: "Space Grotesk"', text)
        self.assertIn("header h1 { grid-column: 1 / 3", text)
        self.assertIn("body.m-detail header h1 { grid-column: 2; }", text)
        self.assertNotIn("local programming service", text)
        self.assertNotIn('id="counts"', text)
        self.assertIn('id="runs"', text)
        self.assertIn(".run-sticky-head { position: sticky", text)
        self.assertIn("padding: 20px 26px 50vh", text)
        self.assertIn("padding: 14px 14px 50vh", text)
        self.assertIn('class="run-sticky-head"', text)
        self.assertIn(".run-title-row { display: flex", text)
        self.assertIn(".run-title-actions { margin-left: auto", text)
        self.assertIn('id="jumpBottom"', text)
        self.assertIn("border: .5px solid var(--accent)", text)
        self.assertIn("border-right: none; background: #fff", text)
        self.assertNotIn("aside .actions { display: flex; gap: 8px; padding: 12px;\n    border-bottom", text)
        self.assertIn("function jumpToBottom", text)
        self.assertIn("function updateBottomJump", text)
        self.assertIn(".activity-line { display: flex", text)
        self.assertIn(".dot.running { background:", text)
        self.assertIn("function currentWorkplace", text)
        self.assertIn("stabilization pending", text)
        self.assertIn("function itemStateRank", text)
        self.assertIn("function projectStateRank", text)
        # Launching is a project act: the standing "+ New milestone"
        # button is gone and both starts live in the project ⋯ menu,
        # which every user who can see the project now gets.
        self.assertNotIn("+ New milestone", text)
        self.assertIn('onclick="newMilestone(event,', text)
        self.assertIn("<span>New milestone</span>", text)
        # Brainstorming is ordered as a task (operator, 2026-08-18): the
        # standalone "New brainstorming" entry left the project menu; the
        # sidebar lists standalone tasks (newest first, bounded page)
        # instead of every session.
        self.assertNotIn('onclick="newBrainstorming(event,', text)
        self.assertNotIn("<span>New brainstorming</span>", text)
        self.assertIn('onclick="newTask(event,', text)
        self.assertIn('"/api/tasks?scope=direct&limit=" + SIDEBAR_TASK_LIMIT', text)
        self.assertNotIn('api("/api/brainstorming/sessions").then', text)
        self.assertIn(
            'id="b_rounds" type="number" min="1" step="1" value="20"',
            text,
        )
        self.assertIn("function openForm(preselect)", text)
        self.assertIn("function selectProjectSlug", text)
        # Brainstorming sessions share the sidebar list with milestones,
        # each kind carrying its own icon, and open their own page.
        self.assertIn('id="bsform"', text)
        self.assertIn("function submitBrainstorming", text)
        self.assertIn('api("/api/brainstorming/sessions"', text)
        # Seats are rows added and removed, never typed ids; references are
        # a managed list with add/remove, not a free textarea.
        self.assertIn("function renderBsRoster", text)
        self.assertIn("function addBsSeat", text)
        self.assertIn("function removeBsSeat", text)
        # The dialog opens on the standing three positions and pins the
        # staffing of none of them: WHO runs a seat is the session's answer
        # at that seat's roster position (staffing-router slice 8).
        self.assertIn('{role: "initial_position", delivery: "llm"},', text)
        self.assertIn('{role: "contrary_position", delivery: "llm"},', text)
        self.assertIn(
            '{role: "common_sense", delivery: "external", '
            'externalProvider: "narrator"},',
            text,
        )
        self.assertNotIn('effort: "max"', text)
        self.assertNotIn("opus-4-8", text)
        self.assertIn(".rosterrow { display: grid", text)
        self.assertIn("function addBsRef", text)
        self.assertIn("function removeBsRef", text)
        self.assertNotIn('id="b_interlocutors"', text)
        # New… proposes a fresh session folder (created at launch via the
        # opt-in create body flag); pickers seed from the bound work area
        # and fall back to the operator's source tree.
        self.assertIn('onclick="newBsTarget()"', text)
        self.assertIn("function newBsTarget", text)
        self.assertIn("create_target_parents", text)
        # Handing the chat over is an unticked box, and the key rides only
        # when it is ticked: an untouched form launches exactly as before.
        self.assertIn('type="checkbox" id="b_deliver_chat"', text)
        self.assertIn(
            'document.getElementById("b_deliver_chat").checked)\n'
            "    requestDoc.deliver_chat = true;",
            text,
        )
        self.assertIn(
            'document.getElementById("b_deliver_chat").checked = false;',
            text,
        )
        self.assertIn("Dante's vote counts", text)
        self.assertIn("every voting seat to accept", text)
        self.assertNotIn("Dante does not vote", text)
        self.assertIn("function browseGoalDoc", text)
        self.assertIn('"~/Development/source"', text)
        self.assertIn("picker.transform", text)
        self.assertIn("function sidebarItems", text)
        self.assertIn("last_action_epoch: r.last_action_epoch", text)
        # Sidebar task rows (standalone tasks) ride beside runs; sessions
        # no longer feed the sidebar.
        self.assertIn('kind: "task"', text)
        self.assertIn("function taskRow", text)
        self.assertNotIn('kind: "brainstorm"', text)
        self.assertIn("const action = Number(item.last_action_epoch)", text)
        self.assertIn("function sessionRow", text)
        self.assertIn("function openSession", text)
        # A session opens IN the right pane: the monitoring page leads
        # with live chips, the final agreement and its audit trail;
        # metadata/participants/accepted target live behind Info…. The
        # standalone page is gone entirely.
        self.assertIn("function refreshSessionDetail", text)
        self.assertIn("function renderSessionDetail", text)
        self.assertIn("function stopSelectedSession", text)
        self.assertIn("function startSelectedSession", text)
        self.assertIn('const displayStatus = !terminal && !running ? "stopped"', text)
        self.assertIn("function sessionChips", text)
        self.assertIn("function sessionClosingCard", text)
        self.assertIn('closing-label">Proposal', text)
        self.assertIn("function sessionRecordedActorLabel", text)
        self.assertIn("function sessionClosureActivity", text)
        self.assertNotIn(
            "`${sessionActorLabel(view, item.participant_id)}: "
            "${item.vote}`",
            text,
        )
        self.assertRegex(
            text,
            r"const votes = \(ballot\.votes \|\| \[\]\)\.map\(item =>\s*"
            r"`\$\{sessionRecordedActorLabel\(\s*view,\s*"
            r"sessionClosureActivity\(\s*view, "
            r"ballot\.after_completed_rounds, \"vote\", "
            r"item\.participant_id\s*\),\s*item\.participant_id\s*\)",
        )
        self.assertIn("proposalLabel", text)
        self.assertIn("is reviewing that proposal", text)
        self.assertIn("Agreement accepted", text)
        self.assertIn("view.final_agreement", text)
        self.assertIn("Final agreement", text)
        self.assertIn("Accepted target:", text)
        self.assertIn("Open questions:", text)
        self.assertIn('onclick="openSessionInfo()">Info', text)
        self.assertIn("function closeSessionInfo", text)
        self.assertIn('family ${esc(p.model_family || "—")}', text)
        self.assertIn('model ${esc(p.model || "—")}', text)
        self.assertIn('effort ${esc(p.effort || "—")}', text)
        # Session content flows with the page — one scroll, preserved
        # across the 2s repaint — never a nested scrollbox that resets.
        self.assertIn(".mdbody.flow { max-height: none", text)
        self.assertIn('class="mdbody flow"', text)
        self.assertIn("function paintSessionDetail", text)
        self.assertIn("det.scrollTop = top", text)
        # Sessions are discardable from the Info page's danger zone
        # (running ones refuse — the button disables, stop first). A
        # broken-state session keeps a discard escape hatch on its
        # failure screen, and an in-flight discard latches the button.
        self.assertIn("function discardSelectedSession", text)
        self.assertIn("?purge=1", text)
        self.assertIn("sessionDiscarding", text)
        self.assertIn("if (!selectedSession || sessionDiscarding) return", text)
        self.assertIn("The session view cannot be loaded", text)
        self.assertNotIn("window.open", text)
        self.assertNotIn("brainstorming.html", text)
        self.assertIn("ICONS.milestone", text)
        self.assertIn("ICONS.brainstorm", text)
        self.assertIn(".run-icon { flex: none", text)
        # ...and a milestone that stopped to ask one chips it in place.
        self.assertIn("function brainstormChip", text)
        self.assertIn(".chip.brainstorm { color:", text)
        self.assertIn('type: "brainstorm", item: b', text)
        self.assertIn(".unit-history { margin-top: 7px", text)
        self.assertIn("function unitHistory", text)
        self.assertIn("const drafts = Array.isArray(u.drafts)", text)
        self.assertIn('liveKind === "review_round"', text)
        self.assertIn("(reviewCounts[family] || 0) + 1", text)
        self.assertIn("function repairChip", text)
        self.assertIn('addLine("Re-documentation"', text)
        self.assertIn('`Episode ${group.number}`', text)
        self.assertIn('d.story === "repair"', text)
        self.assertIn('id="eventsdialog"', text)
        self.assertIn('id="driverlogdialog"', text)
        self.assertIn('id="incidentsdialog"', text)
        self.assertIn('id="discarddialog"', text)
        self.assertIn('id="discardConfirm"', text)
        self.assertIn('onclick="openEvents()">Events</button>', text)
        self.assertIn('onclick="openDriverLog()">Driver log</button>', text)
        self.assertIn('onclick="openWorkerIncidents()">Worker incidents</button>', text)
        self.assertIn('class="bottom-tools"', text)
        self.assertIn("function eventsHtml", text)
        self.assertIn("function workerIncidentsHtml", text)
        self.assertIn("function openWorkerIncidents", text)
        self.assertIn("function openDiscardRun", text)
        self.assertIn("function confirmDiscardRun", text)
        self.assertIn('onclick="openDiscardRun()">Discard run…</button>', text)
        self.assertNotIn('onclick="del()">Forget</button>', text)
        self.assertNotIn('<div class="card"><h3>Events</h3>', text)
        self.assertNotIn('<div class="card"><h3>Driver log</h3>', text)
        self.assertNotIn('<div class="card"><h3>Worker incidents (LLM)</h3>', text)
        self.assertIn("function verificationChip", text)
        self.assertIn(
            '(u.verifications || []).filter(v => !withinRepair(v.at || ""))',
            text,
        )
        self.assertIn("function reclassifyChip", text)
        self.assertIn("function reclassifyWorkChip", text)
        self.assertIn("function reclassifyHistoryChips", text)
        self.assertIn("const reclassByRound = new Map()", text)
        self.assertIn('liveKind === "verification"', text)
        self.assertIn('liveKind === "reclassify"', text)
        self.assertIn('addLine("Verify", label, group.chips)', text)
        self.assertNotIn('addLine("Reclassify", "Decision", group.chips)', text)
        self.assertIn(
            "current.chips.push(...reclassifyHistoryChips(linked, u.unit))",
            text,
        )
        self.assertIn('d.story === "verify"', text)
        self.assertIn('addLine(`${family} review`', text)
        self.assertIn(
            'addLine("Seal", group.deterministic ? "Result" : '
            '`Historical attempt ${group.number}`',
            text,
        )
        # The run's staffing is the router's session: one card on the
        # settings page over the session's own route, and no act grid
        # anywhere (staffing-router slice 8).
        self.assertIn('id="staffingsessiondlg"', text)
        self.assertIn("function staffingSessionCard", text)
        self.assertNotIn('id="a_skeletoner_agent"', text)
        self.assertNotIn('id="ra_skeletoner_model"', text)
        self.assertNotIn('convergence_fixer', text)
        # A Brainstorming seat has no family to switch any more, so the
        # per-seat agent/model/effort machinery — and the family list it
        # read — retired with it (staffing-router slice 8).
        self.assertNotIn("function onAgentChange", text)
        self.assertNotIn("const MODEL_OPTS", text)
        self.assertNotIn("const EFFORT_OPTS", text)
        self.assertNotIn("const FAMILY_DEFAULTS", text)
        self.assertIn("function liveWorkSeconds", text)
        self.assertIn("function runStatusClock", text)
        self.assertIn("function tickLiveClocks", text)
        self.assertIn('host.endsWith(".ngrok-free.app")', text)
        self.assertIn('host.endsWith(".ngrok.dev")', text)
        self.assertIn('host.endsWith(".ngrok-free.dev")', text)
        self.assertIn("return throughNgrok ? 30000 : 2000", text)
        self.assertIn("setInterval(tickLiveClocks, 1000)", text)
        self.assertNotIn("setInterval(refreshRuns, 2000)", text)
        self.assertIn("label.slice(0, 1).toUpperCase() + label.slice(1)", text)
        self.assertIn("function renameRun", text)
        self.assertIn('aria-label="Rename milestone"', text)
        self.assertIn('class="title-sep">·</span>${msChip', text)
        self.assertIn('class="run-name-row"', text)
        self.assertIn('class="run-info-row"', text)
        self.assertIn("activeRunClockInput(running, s.in_flight)", text)
        self.assertIn("const sliceDuration = present.length", text)
        self.assertIn("u.work_duration_s != null", text)
        self.assertNotIn("sum.last_event_epoch - sum.created_epoch", text)

    def test_unknown_path_is_404_json(self):
        status, body = self.request_json("GET", "/definitely/not/here")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])
        self.assertIn("error", body)

    def test_runs_list_empty(self):
        status, body = self.request_json("GET", "/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True, "runs": []})

    # -- POST /api/runs validation ------------------------------------------

    def test_create_missing_workspace_400(self):
        status, body = self.request_json("POST", "/api/runs", {"goal": "x"})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("workspace", body["error"])

    def test_create_missing_goal_and_goal_doc_400(self):
        status, body = self.request_json(
            "POST", "/api/runs", {"workspace": self.workspace("ws-nogoal")}
        )
        self.assertEqual(status, 400)
        self.assertIn("goal", body["error"])

    def test_create_goal_doc_nonexistent_400(self):
        status, body = self.request_json(
            "POST",
            "/api/runs",
            {
                "workspace": self.workspace("ws-baddoc"),
                "goal_doc": os.path.join(self.tmp.name, "no-such-doc.md"),
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("goal_doc", body["error"])

    def test_create_config_non_object_400(self):
        status, body = self.request_json(
            "POST",
            "/api/runs",
            {
                "workspace": self.workspace("ws-badcfg"),
                "goal": "x",
                "config": ["not", "an", "object"],
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("config", body["error"])

    def test_body_invalid_json_400(self):
        status, body = self.request_json("POST", "/api/runs", raw_body=b"not json {")
        self.assertEqual(status, 400)
        self.assertIn("JSON object", body["error"])

    def test_body_json_array_400(self):
        status, body = self.request_json("POST", "/api/runs", raw_body=b"[1, 2, 3]")
        self.assertEqual(status, 400)
        self.assertIn("JSON object", body["error"])

    def test_body_over_1mib_413(self):
        # Spoof a huge Content-Length without sending a body: the server
        # must reject from the header alone, before reading anything.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", "/api/runs")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(service.MAX_BODY + 1))
            conn.endheaders()
            resp = conn.getresponse()
            payload = json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()
        self.assertEqual(resp.status, 413)
        self.assertFalse(payload["ok"])

    def _raw_content_length_request(self, content_length, body=b""):
        """POST /api/runs with an arbitrary (possibly bogus) Content-Length."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", "/api/runs")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", content_length)
            conn.endheaders()
            if body:
                try:
                    conn.send(body)
                except (BrokenPipeError, ConnectionResetError):
                    # The server already rejected from the header alone and
                    # closed its read side — exactly the desired behavior.
                    pass
            resp = conn.getresponse()
            payload = json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()
        return resp.status, payload

    def test_negative_content_length_400_and_body_not_read(self):
        # A negative length must be rejected up front: read(-1) would read
        # the stream to EOF, bypassing MAX_BODY and pinning the handler
        # thread until the client closes.
        status, payload = self._raw_content_length_request(
            "-1", body=b"x" * (2 * 1024 * 1024)
        )
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("Content-Length", payload["error"])

    def test_non_numeric_content_length_400_not_500(self):
        status, payload = self._raw_content_length_request("banana")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("Content-Length", payload["error"])

    # -- create / attach -----------------------------------------------------

    def test_create_autostart_false(self):
        ws = self.workspace("ws-create")
        status, body = self.create_run(ws, config={"max_rounds_per_family": 2})
        self.assertEqual(status, 201)
        self.assertTrue(body["ok"])
        run = body["run"]
        self.assertIsNone(run["pid"])
        self.assertEqual(run["process"], "stopped")
        self.assertEqual(run["milestone_status"], "open")
        # State initialized in the workspace.
        state_path = driver.default_state_path(ws)
        self.assertTrue(os.path.isfile(state_path))
        state = st.load(state_path)
        self.assertEqual(state["goal"], "Test goal")
        self.assertEqual(state["config"]["max_rounds_per_family"], 2)
        # Registry entry exists with pid null.
        entry = registry.get(registry.load(self.home), run["id"])
        self.assertIsNotNone(entry)
        self.assertIsNone(entry["pid"])
        self.assertEqual(entry["state_path"], state_path)

    def test_service_does_not_inject_retired_seal_worker_config(self):
        ws = self.workspace("ws-seal-config")
        status, _ = self.create_run(ws)
        self.assertEqual(status, 201)
        cfg = st.load(driver.default_state_path(ws))["config"]
        for retired in (
            "max_seal_attempts",
            "seal_concurrent",
            "single_seal_first_attempt",
        ):
            self.assertNotIn(retired, cfg)

    def test_create_same_workspace_twice_409(self):
        ws = self.workspace("ws-dupe")
        status, _ = self.create_run(ws)
        self.assertEqual(status, 201)
        status, body = self.create_run(ws)
        self.assertEqual(status, 409)
        self.assertIn("attach", body["error"])

    def test_attach_adopts_existing_state_once(self):
        ws = self.workspace("ws-attach")
        # Bare attach adopts the workspace-root (legacy) state location.
        driver.init_run("adopted goal", ws,
                        state_path=driver.default_state_path(ws))
        status, body = self.request_json(
            "POST",
            "/api/runs",
            {"workspace": ws, "attach": True, "autostart": False},
        )
        self.assertEqual(status, 201)
        run_id = body["run"]["id"]
        status, detail = self.request_json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(status, 200)
        self.assertEqual(detail["summary"]["goal"], "adopted goal")
        # Attaching the SAME state a second time -> duplicate state_path.
        status, body = self.request_json(
            "POST",
            "/api/runs",
            {"workspace": ws, "attach": True, "autostart": False},
        )
        self.assertEqual(status, 409)
        self.assertIn("already registered", body["error"])

    def test_attach_rejects_goal_goal_doc_and_config(self):
        # Attach adopts the state as-is: a supplied goal/goal_doc/config
        # would be silently ignored, so the API must reject it instead of
        # returning 201 as if it were honored.
        ws = self.workspace("ws-attach-strict")
        driver.init_run("ORIGINAL GOAL", ws,
                        state_path=driver.default_state_path(ws))
        for extra in (
            {"goal": "NEW GOAL"},
            {"goal_doc": os.path.join(self.tmp.name, "whatever.md")},
            {"config": {"max_rounds_per_family": 999}},
        ):
            payload = {"workspace": ws, "attach": True, "autostart": False}
            payload.update(extra)
            status, body = self.request_json("POST", "/api/runs", payload)
            self.assertEqual(status, 400, body)
            self.assertIn("attach", body["error"])
        # A bare attach still works, keeping the on-disk goal and config.
        status, body = self.request_json(
            "POST", "/api/runs", {"workspace": ws, "attach": True, "autostart": False}
        )
        self.assertEqual(status, 201, body)
        status, detail = self.request_json("GET", "/api/runs/%s" % body["run"]["id"])
        self.assertEqual(detail["summary"]["goal"], "ORIGINAL GOAL")

    def test_goal_doc_becomes_goal(self):
        ws = self.workspace("ws-goaldoc")
        doc = os.path.join(self.tmp.name, "work-description.md")
        content = "Build the frobnicator.\n\nWith two slices.\n"
        with open(doc, "w", encoding="utf-8") as fh:
            fh.write(content)
        status, body = self.request_json(
            "POST",
            "/api/runs",
            {"workspace": ws, "goal_doc": doc, "autostart": False},
        )
        self.assertEqual(status, 201)
        run_id = body["run"]["id"]
        self.assertEqual(body["run"]["goal_doc"], doc)
        status, detail = self.request_json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(status, 200)
        self.assertEqual(detail["summary"]["goal"], content.strip())

    # -- detail / log ---------------------------------------------------------

    def test_run_detail_and_unknown(self):
        ws = self.workspace("ws-detail")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        status, detail = self.request_json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(status, 200)
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["entry"]["id"], run_id)
        self.assertEqual(detail["status"]["milestone_status"], "open")
        self.assertEqual(detail["summary"]["milestone_status"], "open")
        self.assertEqual(detail["summary"]["current_unit"], "skeleton")
        self.assertEqual(detail["status"]["slices_total"], 0)
        self.assertIsInstance(detail["log"], list)
        status, body = self.request_json("GET", "/api/runs/nope-id")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    def test_run_status_carries_slice_total_for_panel_context(self):
        ws = self.workspace("ws-slice-total")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        entry = registry.get(registry.load(self.home), run_id)
        state = st.load(entry["state_path"])
        state["milestone"]["slices"] = [
            {"id": 1, "title": "one"}, {"id": 2, "title": "two"},
        ]
        st.save(entry["state_path"], state)

        _, listing = self.request_json("GET", "/api/runs")
        run = next(item for item in listing["runs"] if item["id"] == run_id)
        self.assertEqual(run["slices_total"], 2)
        self.assertEqual(run["work_duration_s"], 0.0)
        self.assertEqual(
            run["last_action_epoch"], st.summary(state)["last_event_epoch"]
        )
        _, detail = self.request_json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(detail["status"]["slices_total"], 2)

    def test_run_status_includes_active_brainstorming_work_once(self):
        ws = self.workspace("ws-brainstorming-clock")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        entry = registry.get(registry.load(self.home), run_id)
        state = st.load(entry["state_path"])
        unit = st.current_unit(state)
        st.append_event(
            state,
            "brainstorming_wait_started",
            unit=st.unit_key(unit),
            kind="review_round",
            family="codex",
            session_id="brainstorming-live",
            target_path="docs/decision.md",
        )
        st.save(entry["state_path"], state)
        process = self.spawn_fake_driver()
        registry.update(self.home, run_id, pid=process.pid)
        session = {
            "work_duration_s": 7.5,
            "in_flight": {
                "stage": "discussion",
                "kind": "discussion_turn",
                "model_family": "codex",
                "model": "gpt-5.6-sol",
                "effort": "max",
                "started_at": 100.0,
            },
        }
        with mock.patch.object(
            service.brainstorming_lifecycle,
            "inspect_session",
            return_value=session,
        ):
            _, listing = self.request_json("GET", "/api/runs")
        run = next(item for item in listing["runs"] if item["id"] == run_id)
        self.assertEqual(run["work_duration_s"], 7.5)

        process.terminate()
        process.wait(timeout=5)
        registry.update(self.home, run_id, pid=None)
        with mock.patch.object(
            service.brainstorming_lifecycle,
            "inspect_session",
            return_value=session,
        ):
            _, listing = self.request_json("GET", "/api/runs")
        run = next(item for item in listing["runs"] if item["id"] == run_id)
        self.assertEqual(run["process"], "stopped")
        self.assertEqual(run["work_duration_s"], 7.5)
        self.assertEqual(run["in_flight"]["kind"], "brainstorming")
        self.assertEqual(run["in_flight"]["started_at"], 100.0)

        state = st.load(entry["state_path"])
        st.append_event(
            state,
            "brainstorming_work_recorded",
            unit=st.unit_key(st.current_unit(state)),
            session_id="brainstorming-live",
            duration_s=7.5,
        )
        st.save(entry["state_path"], state)
        with mock.patch.object(
            service.brainstorming_lifecycle,
            "inspect_session",
            return_value=session,
        ):
            _, listing = self.request_json("GET", "/api/runs")
        run = next(item for item in listing["runs"] if item["id"] == run_id)
        self.assertEqual(run["work_duration_s"], 7.5)

    def test_run_status_surfaces_pending_implementation_stabilization(self):
        ws = self.workspace("ws-pending-stabilization")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        entry = registry.get(registry.load(self.home), run_id)
        state = st.load(entry["state_path"])
        st.current_unit(state)["implementation_stabilization"] = {
            "implementation_size": {
                "interrupt_reason": "hard implementation size cutoff",
            }
        }
        st.save(entry["state_path"], state)

        _, listing = self.request_json("GET", "/api/runs")
        run = next(item for item in listing["runs"] if item["id"] == run_id)
        self.assertEqual(run["process"], "stopped")
        self.assertIs(run["implementation_stabilization"], True)

        _, detail = self.request_json("GET", "/api/runs/%s" % run_id)
        self.assertIs(
            detail["summary"]["implementation_stabilization"], True
        )
        self.assertIs(
            detail["status"]["implementation_stabilization"], True
        )

    def test_run_display_name_can_be_renamed_without_mutating_driver_state(self):
        ws = self.workspace("ws-rename")
        _, created = self.create_run(ws, name="Typo name")
        run_id = created["run"]["id"]
        entry = registry.get(registry.load(self.home), run_id)

        status, body = self.request_json(
            "POST", "/api/runs/%s/name" % run_id,
            {"name": "  Better name  "},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["run"]["name"], "Better name")
        self.assertEqual(st.load(entry["state_path"])["name"], "Typo name")

        _, listing = self.request_json("GET", "/api/runs")
        renamed = next(r for r in listing["runs"] if r["id"] == run_id)
        self.assertEqual(renamed["name"], "Better name")
        _, detail = self.request_json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(detail["status"]["name"], "Better name")

        for invalid in (None, "   ", "x" * 161, "bad\nname"):
            status, _ = self.request_json(
                "POST", "/api/runs/%s/name" % run_id, {"name": invalid}
            )
            self.assertEqual(status, 400)

    def test_run_status_surfaces_model_for_legacy_in_flight_marker(self):
        ws = self.workspace("ws-model-chip")
        _, body = self.create_run(
            ws,
            config={
                "model_defaults": {
                    "codex": {"model": "gpt-5.6-sol", "effort": "high"},
                    "claude": {
                        "model": "claude-fable-5", "effort": "medium",
                    },
                },
            },
        )
        run_id = body["run"]["id"]
        entry = registry.get(registry.load(self.home), run_id)
        marker = os.path.join(os.path.dirname(entry["state_path"]), "current.json")
        with open(marker, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "label": "skeleton-claude-r1",
                    "kind": "review_round",
                    "family": "claude",
                    "started_at": 1,
                },
                fh,
            )
        fake = self.spawn_fake_driver()
        registry.update(self.home, run_id, pid=fake.pid)
        try:
            status, payload = self.request_json("GET", "/api/runs")
            self.assertEqual(status, 200)
            run = next(r for r in payload["runs"] if r["id"] == run_id)
            self.assertEqual(run["in_flight"]["model"], "claude-fable-5")
            self.assertEqual(run["current_model"], "gpt-5.6-sol")
        finally:
            registry.update(self.home, run_id, pid=None)

    def test_run_log_empty(self):
        ws = self.workspace("ws-log")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        status, body = self.request_json("GET", "/api/runs/%s/log" % run_id)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True, "lines": []})

    def test_run_log_unknown_id_404(self):
        # Consistent with the sibling detail route: unknown ids are 404,
        # not 200 with an empty tail.
        status, body = self.request_json("GET", "/api/runs/ghost/log")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    # -- start ---------------------------------------------------------------

    def test_start_closed_run_409(self):
        ws = self.workspace("ws-closed")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        # Craft a closed milestone directly with state helpers (append-only
        # safe: events and units untouched).
        state_path = driver.default_state_path(ws)
        state = st.load(state_path)
        state["milestone"]["status"] = st.M_CLOSED
        st.save(state_path, state)
        status, body = self.request_json("POST", "/api/runs/%s/start" % run_id)
        self.assertEqual(status, 409)
        self.assertIn("closed", body["error"])

    def test_start_unknown_404(self):
        status, body = self.request_json("POST", "/api/runs/ghost/start")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    def test_start_while_alive_409(self):
        ws = self.workspace("ws-alive")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        # Simulate a live driver with a real session-leader child.
        fake = self.spawn_fake_driver()
        registry.update(self.home, run_id, pid=fake.pid)
        try:
            status, body = self.request_json("POST", "/api/runs/%s/start" % run_id)
            self.assertEqual(status, 409)
            self.assertIn("already running", body["error"])
        finally:
            registry.update(self.home, run_id, pid=None)

    # -- stop / delete ---------------------------------------------------------

    def test_stop_not_running(self):
        ws = self.workspace("ws-stop")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        status, body = self.request_json("POST", "/api/runs/%s/stop" % run_id)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["stopped"])

    def test_delete_lifecycle(self):
        ws = self.workspace("ws-delete")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        # Running (simulated live session-leader pid) -> 409.
        fake = self.spawn_fake_driver()
        registry.update(self.home, run_id, pid=fake.pid)
        try:
            status, body = self.request_json("DELETE", "/api/runs/%s" % run_id)
            self.assertEqual(status, 409)
            self.assertIn("stop", body["error"])
        finally:
            registry.update(self.home, run_id, pid=None)
        # Stopped -> 200 and gone.
        status, body = self.request_json("DELETE", "/api/runs/%s" % run_id)
        self.assertEqual(status, 200)
        self.assertEqual(body["deleted"], run_id)
        status, _ = self.request_json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(status, 404)
        status, body = self.request_json("GET", "/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(body["runs"], [])
        # Workspace files untouched by the forget.
        self.assertTrue(os.path.isfile(driver.default_state_path(ws)))

    def test_delete_unknown_404(self):
        status, body = self.request_json("DELETE", "/api/runs/ghost")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    # -- corrupted state --------------------------------------------------------

    def test_corrupted_state_reported_not_fatal(self):
        ws = self.workspace("ws-corrupt")
        _, body = self.create_run(ws)
        run_id = body["run"]["id"]
        with open(driver.default_state_path(ws), "w", encoding="utf-8") as fh:
            fh.write("{ this is not json")
        status, body = self.request_json("GET", "/api/runs")
        self.assertEqual(status, 200)
        run = [r for r in body["runs"] if r["id"] == run_id][0]
        self.assertIsNotNone(run["state_error"])
        self.assertIsNone(run["milestone_status"])
        # Detail endpoint also degrades gracefully.
        status, detail = self.request_json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(status, 200)
        self.assertIsNone(detail["summary"])
        self.assertIn("summary_error", detail)
        # Starting an unreadable state is refused, not crashed.
        status, body = self.request_json("POST", "/api/runs/%s/start" % run_id)
        self.assertEqual(status, 409)
        self.assertIn("unreadable", body["error"])


class AmendmentsApiTest(ServiceApiTest):
    def test_add_and_list_amendments(self):
        ws = self.workspace("ws-amend")
        status, body = self.create_run(ws)
        self.assertEqual(status, 201)
        rid = body["run"]["id"]
        status, body = self.request_json(
            "POST", "/api/runs/%s/amendments" % rid,
            {"text": "No hot-path changes: no new indexes."})
        self.assertEqual(status, 200)
        self.assertEqual(body["amendments"][0]["id"], "A1")
        status, body = self.request_json(
            "POST", "/api/runs/%s/amendments" % rid,
            {"text": "Second note."})
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body["amendments"]],
                         ["A1", "A2"])
        # Persisted where the driver reads them.
        with open(os.path.join(ws, ".orchestrator", "amendments.json"),
                  encoding="utf-8") as fh:
            on_disk = json.load(fh)
        self.assertEqual(len(on_disk["amendments"]), 2)
        # And surfaced in the run detail.
        status, body = self.request_json("GET", "/api/runs/%s" % rid)
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body["amendments"]],
                         ["A1", "A2"])

    def test_delete_amendment_and_no_id_reuse(self):
        ws = self.workspace("ws-amend-del")
        status, body = self.create_run(ws)
        rid = body["run"]["id"]
        for text in ("First.", "Second."):
            self.request_json(
                "POST", "/api/runs/%s/amendments" % rid, {"text": text})
        status, body = self.request_json(
            "DELETE", "/api/runs/%s/amendments/A1" % rid)
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body["amendments"]], ["A2"])
        # A new amendment must NOT reuse the deleted A1 slot (the driver
        # dedups amendment_seen by id; reuse would skip the ledger trail).
        status, body = self.request_json(
            "POST", "/api/runs/%s/amendments" % rid, {"text": "Third."})
        self.assertEqual([a["id"] for a in body["amendments"]],
                         ["A2", "A3"])
        status, _ = self.request_json(
            "DELETE", "/api/runs/%s/amendments/A9" % rid)
        self.assertEqual(status, 404)

    def test_amendment_validation(self):
        ws = self.workspace("ws-amend-bad")
        status, body = self.create_run(ws)
        rid = body["run"]["id"]
        status, body = self.request_json(
            "POST", "/api/runs/%s/amendments" % rid, {"text": "   "})
        self.assertEqual(status, 400)
        status, body = self.request_json(
            "POST", "/api/runs/%s/amendments" % rid, {"text": "x" * 4001})
        self.assertEqual(status, 400)
        status, body = self.request_json(
            "POST", "/api/runs/unknown-run/amendments", {"text": "hi"})
        self.assertEqual(status, 404)

    def test_invalid_amendments_source_fails_closed_without_overwrite(self):
        ws = self.workspace("ws-amend-invalid-source")
        status, body = self.create_run(ws)
        self.assertEqual(status, 201)
        rid = body["run"]["id"]
        path = os.path.join(ws, ".orchestrator", "amendments.json")
        invalid = b'{"amendments":['
        with open(path, "wb") as handle:
            handle.write(invalid)

        for method, endpoint, payload in (
            ("GET", "/api/runs/%s" % rid, None),
            ("POST", "/api/runs/%s/amendments" % rid, {"text": "new"}),
            ("DELETE", "/api/runs/%s/amendments/A1" % rid, None),
        ):
            with self.subTest(method=method):
                status, body = self.request_json(method, endpoint, payload)
                self.assertEqual(status, 409, body)
                with open(path, "rb") as handle:
                    self.assertEqual(handle.read(), invalid)


class ActsApiTest(ServiceApiTest):
    def test_projectless_creation_acts_are_single_homed(self):
        ws = self.workspace("ws-creation-acts")
        status, body = self.create_run(ws, config={"acts": {
            "implementer": {"agent": "claude", "model": "launch"},
            "legacy_surface": {"kept": True},
        }})
        self.assertEqual(status, 201, body)
        state_path = os.path.join(ws, ".orchestrator", "state.json")
        with open(os.path.join(ws, ".orchestrator", "acts.json"),
                  encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {
                "implementer": {"agent": "claude", "model": "launch"}
            })
        config_acts = st.load(state_path)["config"]["acts"]
        self.assertEqual(config_acts["implementer"],
                         driver.DEFAULT_CONFIG["acts"]["implementer"])
        self.assertEqual(config_acts["legacy_surface"], {"kept": True})

    def test_creation_acts_use_live_authority_validator(self):
        invalid = (
            {"review_codex": {"agent": "codex", "model": "review"}},
            {"consultation": {"agent": "claude", "effort": "high"}},
            {"fixer": {"agent": "codex", "reasoning": "high"}},
        )
        for index, acts in enumerate(invalid):
            with self.subTest(acts=acts):
                ws = self.workspace("ws-invalid-creation-acts-%d" % index)
                status, body = self.create_run(ws, config={"acts": acts})
                self.assertEqual(status, 400, body)
                self.assertIn("creation act overrides", body["error"])
                self.assertFalse(os.path.exists(os.path.join(
                    ws, ".orchestrator", "state.json"
                )))


class StoryApiTest(ServiceApiTest):
    def _seed(self, ws):
        status, body = self.create_run(ws)
        rid = body["run"]["id"]
        reg = registry.load(self.home)
        entry = registry.get(reg, rid)
        state = st.load(entry["state_path"])
        unit = state["units"][0]
        unit["draft"] = {
            "kind": "draft_skeleton", "family": "codex", "model": "gpt",
            "effort": None, "duration_s": 12.5,
            "at": "2026-07-05T10:00:00+0200", "raw_path": "raw/d.txt",
            "result": {"status": "ok", "kind": "draft_skeleton",
                       "artifact": "docs/skeleton.md",
                       "slices": [{"id": 1, "title": "core"}]},
        }
        unit["artifact"] = "docs/skeleton.md"
        unit["rounds"].append({
            "id": "skeleton-codex-r1", "family": "codex",
            "kind": "review_round", "at": "2026-07-05T10:10:00+0200",
            "duration_s": 33.0, "raw_path": "raw/r1.txt",
            "result": {"status": "ok", "kind": "review_round",
                       "findings": [{"id": "F1", "severity": "P2",
                                     "summary": "boundary unclear"}]},
        })
        unit["rounds"].extend([
            {
                "id": "skeleton-codex-r2", "family": "codex",
                "kind": "review_round", "at": "2026-07-05T10:40:00+0200",
                "duration_s": 20.0, "raw_path": "raw/r2.txt",
                "result": {"status": "ok", "kind": "review_round",
                           "findings": []},
            },
            {
                "id": "skeleton-claude-r1", "family": "claude",
                "kind": "review_round", "at": "2026-07-05T10:50:00+0200",
                "duration_s": 22.0, "raw_path": "raw/r3.txt",
                "result": {"status": "ok", "kind": "review_round",
                           "findings": []},
            },
        ])
        unit["seals"].append({
            "attempt": 1, "passed": True, "invalidated": None,
            "at": "2026-07-05T11:00:00+0200",
            "halves": {},
            "reviews": ["skeleton-codex-r2", "skeleton-claude-r1"],
        })
        unit["debt"] = [{
            "id": "claude-F9", "severity": "P3", "summary": "stale word",
            "raised_by": "claude", "cleared_by": "codex",
            "drift_risk": "low", "reason": "cosmetic; no drift",
        }]
        state["events"].append({
            "seq": 999, "at": "2026-07-05T10:20:00+0200",
            "type": "reclassify_recorded", "unit": "skeleton",
            "finding_id": "claude-F9", "reclassifier": "codex",
            "drift_risk": "low", "threshold": "low",
            "defer_ok": True, "reason": "cosmetic; no drift",
            "token_usage": {
                "input_tokens": 5, "cached_input_tokens": 1,
                "output_tokens": 2, "reasoning_output_tokens": 0,
                "total_tokens": 7,
            },
            "token_usage_partial": False,
        })
        # A repaired first strike, with its malformed raw on disk (the
        # story viewer reads the path recorded by the run's own ledger).
        raw_path = os.path.join(ws, "malformed-r1.txt")
        with open(raw_path, "w", encoding="utf-8") as fh:
            fh.write("I'll review this thoroughly next turn!")
        state["events"].append({
            "seq": 1000, "at": "2026-07-05T10:30:00+0200",
            "type": "worker_malformed", "label": "skeleton-claude-r1",
            "kind": "review_round", "family": "claude",
            "error": "worker[review_round]: missing required key 'status'",
            "duration_s": 440.0, "raw_path": raw_path,
        })
        # A FATAL strike (both attempts violated): two raw files.
        raw2 = os.path.join(ws, "malformed-r2-attempt2.txt")
        with open(raw2, "w", encoding="utf-8") as fh:
            fh.write("second attempt, still prose")
        state["events"].append({
            "seq": 1001, "at": "2026-07-05T10:40:00+0200",
            "type": "worker_malformed", "label": "skeleton-claude-r2",
            "kind": "review_round", "family": "claude", "fatal": True,
            "error": "contract-violating output twice",
            "duration_s": None, "raw_path": raw_path, "raw_path2": raw2,
        })
        st.save(entry["state_path"], state)
        return rid

    def test_verification_story_and_summary_expose_result_and_duration(self):
        ws = self.workspace("ws-verification-story")
        rid = self._seed(ws)
        entry = registry.get(registry.load(self.home), rid)
        state = st.load(entry["state_path"])
        event = st.append_event(
            state, "verification", unit="skeleton",
            stage=st.U_PRE_SEAL_VERIFY, boundary="final",
            cadence="milestone_final", ok=True, stable=True,
            commands=["python3 -m unittest"], output_tail="OK",
            duration_s=12.5,
        )
        st.save(entry["state_path"], state)

        _, detail = self.request_json("GET", "/api/runs/%s" % rid)
        projected = detail["summary"]["units"][0]["verifications"][0]
        self.assertEqual(projected["seq"], event["seq"])
        self.assertEqual(projected["duration_s"], 12.5)
        self.assertEqual(projected["cadence"], "milestone_final")

        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=verify:%s"
            % (rid, event["seq"]),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["story"], "verify")
        self.assertEqual(body["unit"], "skeleton")
        self.assertEqual(body["duration_s"], 12.5)
        self.assertEqual(body["cadence"], "milestone_final")
        self.assertTrue(body["ok"])
        self.assertTrue(body["stable"])
        self.assertEqual(body["commands"], ["python3 -m unittest"])
        self.assertEqual(body["output_tail"], "OK")

    def test_fatal_malformed_story_carries_both_attempts(self):
        ws = self.workspace("ws-fatal")
        rid = self._seed(ws)
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=malformed:1001" % rid)
        self.assertEqual(status, 200)
        self.assertTrue(body["fatal"])
        self.assertEqual(body["raw_text"],
                         "I'll review this thoroughly next turn!")
        self.assertEqual(body["raw_text2"], "second attempt, still prose")

    def test_stabilizer_retry_story_carries_both_attempts(self):
        ws = self.workspace("ws-stabilizer-retry")
        rid = self._seed(ws)
        entry = registry.get(registry.load(self.home), rid)
        state = st.load(entry["state_path"])
        raw1 = os.path.join(ws, "stabilizer-attempt-1.txt")
        raw2 = os.path.join(ws, "stabilizer-attempt-2.txt")
        with open(raw1, "w", encoding="utf-8") as fh:
            fh.write("first empty delivery transport")
        with open(raw2, "w", encoding="utf-8") as fh:
            fh.write("second empty delivery transport")
        state["events"].append({
            "seq": 1002, "at": "2026-07-05T10:45:00+0200",
            "type": "worker_malformed", "label": "slice_impl-06-stabilize",
            "kind": "implement", "family": "codex", "fatal": False,
            "stabilizer_retry": True,
            "error": "contract-violating output twice",
            "duration_s": None, "raw_path": raw1, "raw_path2": raw2,
        })
        st.save(entry["state_path"], state)

        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=malformed:1002" % rid)

        self.assertEqual(status, 200)
        self.assertFalse(body["fatal"])
        self.assertTrue(body["stabilizer_retry"])
        self.assertEqual(body["raw_text"], "first empty delivery transport")
        self.assertEqual(body["raw_text2"],
                         "second empty delivery transport")

    def test_transport_incident_story_keeps_type_without_raw(self):
        ws = self.workspace("ws-transport-incident")
        rid = self._seed(ws)
        entry = registry.get(registry.load(self.home), rid)
        state = st.load(entry["state_path"])
        state["events"].append({
            "seq": 1003, "at": "2026-07-05T10:50:00+0200",
            "type": "worker_malformed", "label": "slice_impl-06-draft",
            "kind": "implement", "family": "codex", "fatal": False,
            "controlled_interruption": True,
            "error": "connection reset after accepted cutoff",
            "duration_s": None, "raw_path": None, "raw_path2": None,
        })
        st.save(entry["state_path"], state)

        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=malformed:1003" % rid)

        self.assertEqual(status, 200)
        self.assertTrue(body["controlled_interruption"])
        self.assertFalse(body["infra_retry"])
        self.assertIn("connection reset", body["error"])
        self.assertIsNone(body["raw_text"])

    def test_malformed_story_and_summary_trail(self):
        ws = self.workspace("ws-malformed")
        rid = self._seed(ws)
        # summary carries the whole-run trail for the panel's chip card
        # (the repaired strike plus the seeded fatal one)
        _, detail = self.request_json("GET", "/api/runs/%s" % rid)
        trail = detail["summary"]["malformed"]
        self.assertEqual(len(trail), 2)
        self.assertEqual(trail[0]["family"], "claude")
        self.assertTrue(trail[1]["fatal"])
        # the story returns the malformed text itself
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=malformed:1000" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["story"], "malformed")
        self.assertEqual(body["label"], "skeleton-claude-r1")
        self.assertIn("missing required key", body["error"])
        self.assertEqual(body["raw_text"],
                         "I'll review this thoroughly next turn!")
        # unknown seq refuses; a vanished raw file degrades to null text
        status, _ = self.request_json(
            "GET", "/api/runs/%s/story?item=malformed:1234" % rid)
        self.assertEqual(status, 404)
        os.unlink(os.path.join(ws, "malformed-r1.txt"))
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=malformed:1000" % rid)
        self.assertEqual(status, 200)
        self.assertIsNone(body["raw_text"])

    def test_round_seal_and_draft_stories(self):
        ws = self.workspace("ws-story")
        rid = self._seed(ws)
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=round:skeleton-codex-r1" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["story"], "round")
        self.assertEqual(body["result"]["findings"][0]["id"], "F1")
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=seal:skeleton:1" % rid)
        self.assertEqual(status, 200)
        self.assertTrue(body["passed"])
        self.assertEqual(
            body["reviews"],
            ["skeleton-codex-r2", "skeleton-claude-r1"],
        )
        self.assertFalse(body["verification_recorded"])
        self.assertEqual(body["halves"], {})
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=draft:skeleton" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["artifact"], "docs/skeleton.md")

    def test_re_documentation_story_compacts_the_repair_episode(self):
        ws = self.workspace("ws-repair-story")
        rid = self._seed(ws)
        entry = registry.get(registry.load(self.home), rid)
        state = st.load(entry["state_path"])
        unit = state["units"][0]
        unit["rounds"].append({
            "id": "skeleton-codex-fix-r1", "family": "codex",
            "kind": "fix_findings", "at": "2026-07-05T12:10:00+0200",
            "duration_s": 40.0,
            "result": {"status": "ok", "kind": "fix_findings",
                       "findings": [{"id": "G1", "severity": "P1",
                                     "summary": "pin grading content"}]},
        })
        unit["rounds"].extend([
            {
                "id": "skeleton-codex-r3", "family": "codex",
                "kind": "review_round", "at": "2026-07-05T12:12:00+0200",
                "duration_s": 20.0,
                "result": {"status": "ok", "kind": "review_round",
                           "findings": []},
            },
            {
                "id": "skeleton-claude-r2", "family": "claude",
                "kind": "review_round", "at": "2026-07-05T12:15:00+0200",
                "duration_s": 20.0,
                "result": {"status": "ok", "kind": "review_round",
                           "findings": []},
            },
        ])
        unit["seals"].append({
            "attempt": 2, "passed": True, "invalidated": None,
            "at": "2026-07-05T12:20:00+0200",
            "halves": {},
            "reviews": ["skeleton-codex-r3", "skeleton-claude-r2"],
        })
        state["events"].extend([
            {"seq": 1002, "at": "2026-07-05T12:00:00+0200",
             "type": "reopened_for_repair", "unit": "skeleton",
             "reported_by": "slice_doc-04", "classification": "fits_remodel",
             "plain": "the grader lacks the question",
             "forced_decision": "pin grading content"},
            {"seq": 1003, "at": "2026-07-05T12:20:00+0200",
             "type": "unit_transition", "unit": "skeleton",
             "from_status": "sealing", "to_status": "sealed",
             "reason": "repaired"},
        ])
        st.save(entry["state_path"], state)

        _, detail = self.request_json("GET", "/api/runs/%s" % rid)
        repair = detail["summary"]["units"][0]["repairs"][0]
        self.assertEqual(
            repair["round_ids"],
            [
                "skeleton-codex-fix-r1",
                "skeleton-codex-r3",
                "skeleton-claude-r2",
            ],
        )
        self.assertEqual(repair["seal_attempts"], [2])
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=repair:skeleton:1002" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["story"], "repair")
        self.assertEqual(body["reported_by"], "slice_doc-04")
        self.assertEqual(body["plain"], "the grader lacks the question")

    def test_debt_story_and_summary_expose_deferred_p3(self):
        # The reclassify leaves no round, so the panel needs the deferred P3
        # both as a summary chip and a clickable story.
        ws = self.workspace("ws-debt")
        rid = self._seed(ws)
        entry = registry.get(registry.load(self.home), rid)
        state = st.load(entry["state_path"])
        state["events"].append({
            "seq": 1002, "at": "2026-07-05T10:25:00+0200",
            "type": "reclassify_recorded", "unit": "skeleton",
            "finding_id": "claude-F10", "reclassifier": "codex",
            "model": "gpt-5.6-sol", "effort": "max",
            "drift_risk": "low", "threshold": "low",
            "defer_ok": True, "reason": "cosmetic",
            "token_usage": {
                "input_tokens": 10, "cached_input_tokens": 2,
                "output_tokens": 3, "reasoning_output_tokens": 1,
                "total_tokens": 13,
            },
            "token_usage_partial": True,
        })
        st.save(entry["state_path"], state)
        # summary carries the debt so the chip can render after the run ends
        _, detail = self.request_json("GET", "/api/runs/%s" % rid)
        skel = detail["summary"]["units"][0]
        self.assertEqual(len(skel["debt"]), 1)
        self.assertEqual(skel["debt"][0]["cleared_by"], "codex")
        # the story shows what was resolved
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=debt:skeleton" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["story"], "debt")
        self.assertEqual(body["debt"][0]["id"], "claude-F9")
        self.assertEqual(body["debt"][0]["drift_risk"], "low")
        self.assertEqual(body["reclassify"][0]["defer_ok"], True)
        self.assertEqual(body["reclassify"][0]["reclassifier"], "codex")
        partial_summary = next(
            event for event in skel["reclassify"]
            if event["finding_id"] == "claude-F10"
        )
        self.assertEqual(partial_summary["model"], "gpt-5.6-sol")
        self.assertEqual(partial_summary["effort"], "max")
        self.assertEqual(body["reclassify"][0]["drift_risk"], "low")
        self.assertEqual(body["reclassify"][0]["threshold"], "low")
        partial = next(
            event for event in body["reclassify"]
            if event["finding_id"] == "claude-F10"
        )
        self.assertTrue(partial["token_usage_partial"])
        self.assertEqual(body["token_usage"]["total_tokens"], 20)
        self.assertTrue(body["token_usage_partial"])

    def test_requeued_impl_debt_stays_in_history_but_not_active_debt(self):
        ws = self.workspace("ws-requeued-debt")
        rid = self._seed(ws)
        reg = registry.load(self.home)
        entry = registry.get(reg, rid)
        state = st.load(entry["state_path"])
        state["milestone"]["slices"] = [{"id": 1, "title": "core"}]
        state["units"][0]["status"] = st.U_SEALED
        doc = st.ensure_next_unit(state)
        doc["status"] = st.U_SEALED
        impl = st.ensure_next_unit(state)
        impl["status"] = st.U_PRE_SEAL_VERIFY
        st.record_debt(state, impl, [{
            "id": "claude-F1", "severity": "P3", "summary": "code bug",
            "raised_by": "claude", "cleared_by": "codex",
        }], "seal", "slice_impl-01-seal-a1")
        st.append_event(
            state, "reclassify_recorded", unit="slice_impl-01",
            finding_id="claude-F1", reclassifier="codex",
            drift_risk="low", threshold="low", defer_ok=True,
        )
        st.requeue_implementation_debt(state)
        st.save(entry["state_path"], state)

        _, detail = self.request_json("GET", "/api/runs/%s" % rid)
        impl_view = next(
            unit for unit in detail["summary"]["units"]
            if unit["unit"] == "slice_impl-01"
        )
        self.assertEqual(impl_view["debt"], [])
        self.assertEqual(len(impl_view["reclassify"]), 1)
        self.assertEqual(
            impl_view["reclassify"][0]["finding_id"], "claude-F1"
        )
        self.assertTrue(impl_view["reclassify"][0]["requeued"])
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=debt:slice_impl-01" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["debt"], [])
        self.assertEqual(len(body["reclassify"]), 1)
        self.assertEqual(body["reclassify"][0]["finding_id"], "claude-F1")
        self.assertTrue(body["reclassify"][0]["requeued"])

    def test_run_detail_carries_commit_web_base(self):
        ws = self.workspace("ws-webbase")
        subprocess.run(
            ["git", "-C", ws, "remote", "add", "origin",
             "https://github.com/me/proj.git"], check=True)
        service._WEB_BASE_CACHE.clear()
        _, body = self.create_run(ws)
        _, detail = self.request_json("GET", "/api/runs/%s" % body["run"]["id"])
        self.assertEqual(
            detail["commit_web_base"], "https://github.com/me/proj")

    def test_artifact_serves_unit_doc(self):
        # The panel's doc viewer: the client names a UNIT and gets the
        # markdown the run's state recorded for it.
        ws = self.workspace("ws-artifact")
        rid = self._seed(ws)
        os.makedirs(os.path.join(ws, "docs"), exist_ok=True)
        with open(os.path.join(ws, "docs", "skeleton.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("# Skeleton\n\nbody text\n")
        status, body = self.request_json(
            "GET", "/api/runs/%s/artifact?unit=skeleton" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["artifact"], "docs/skeleton.md")
        self.assertIn("# Skeleton", body["content"])
        self.assertFalse(body["truncated"])

    def test_artifact_errors(self):
        ws = self.workspace("ws-artifact-bad")
        rid = self._seed(ws)
        # recorded artifact whose file does not exist on disk
        status, _ = self.request_json(
            "GET", "/api/runs/%s/artifact?unit=skeleton" % rid)
        self.assertEqual(status, 404)
        # unknown unit
        status, _ = self.request_json(
            "GET", "/api/runs/%s/artifact?unit=nope" % rid)
        self.assertEqual(status, 404)
        # unit with no artifact recorded yet
        ws2 = self.workspace("ws-artifact-none")
        status, body = self.create_run(ws2)
        status, _ = self.request_json(
            "GET", "/api/runs/%s/artifact?unit=skeleton" % body["run"]["id"])
        self.assertEqual(status, 404)

    def test_commit_serves_gate_commit_diff(self):
        # The local commit viewer: `git show` of the unit's recorded gate
        # commit, straight from the workspace — no push required.
        ws = self.workspace("ws-commit")
        rid = self._seed(ws)
        with open(os.path.join(ws, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("hello\n")
        subprocess.run(["git", "-C", ws, "add", "."], check=True)
        subprocess.run(
            ["git", "-C", ws, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "-m", "Seal milestone skeleton"], check=True)
        sha = subprocess.run(
            ["git", "-C", ws, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        entry = registry.get(registry.load(self.home), rid)
        state = st.load(entry["state_path"])
        state["units"][0]["gate_commit"] = sha
        st.save(entry["state_path"], state)
        status, body = self.request_json(
            "GET", "/api/runs/%s/commit?unit=skeleton" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["sha"], sha)
        self.assertIn("Seal milestone skeleton", body["text"])
        self.assertIn("f.txt", body["text"])
        self.assertIn("+hello", body["text"])
        self.assertFalse(body["truncated"])

    def test_commit_falls_back_to_wip_commit(self):
        # A unit still in flight has no gate commit; the viewer serves its
        # current working commit instead.
        ws = self.workspace("ws-commit-wip")
        rid = self._seed(ws)
        with open(os.path.join(ws, "w.txt"), "w", encoding="utf-8") as fh:
            fh.write("in flight\n")
        subprocess.run(["git", "-C", ws, "add", "."], check=True)
        subprocess.run(
            ["git", "-C", ws, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "-m", "wip: skeleton"], check=True)
        sha = subprocess.run(
            ["git", "-C", ws, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        entry = registry.get(registry.load(self.home), rid)
        state = st.load(entry["state_path"])
        st.append_event(state, "wip_commit", unit="skeleton", sha=sha)
        st.save(entry["state_path"], state)
        status, body = self.request_json(
            "GET", "/api/runs/%s/commit?unit=skeleton" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["sha"], sha)
        self.assertEqual(body["kind"], "wip")
        self.assertIn("+in flight", body["text"])

    def test_commit_errors(self):
        ws = self.workspace("ws-commit-bad")
        rid = self._seed(ws)
        # seeded unit has neither a gate nor a wip commit recorded
        status, _ = self.request_json(
            "GET", "/api/runs/%s/commit?unit=skeleton" % rid)
        self.assertEqual(status, 404)
        # unknown unit
        status, _ = self.request_json(
            "GET", "/api/runs/%s/commit?unit=nope" % rid)
        self.assertEqual(status, 404)
        # recorded sha that git cannot resolve (rewritten/lost) -> 409
        entry = registry.get(registry.load(self.home), rid)
        state = st.load(entry["state_path"])
        state["units"][0]["gate_commit"] = "deadbee"
        st.save(entry["state_path"], state)
        status, _ = self.request_json(
            "GET", "/api/runs/%s/commit?unit=skeleton" % rid)
        self.assertEqual(status, 409)

    def test_story_errors(self):
        ws = self.workspace("ws-story-bad")
        rid = self._seed(ws)
        status, _ = self.request_json(
            "GET", "/api/runs/%s/story?item=round:nope" % rid)
        self.assertEqual(status, 404)
        status, _ = self.request_json(
            "GET", "/api/runs/%s/story?item=weird:x" % rid)
        self.assertEqual(status, 400)


class TestPerMilestoneLayout(ServiceApiTest):
    """A new run keeps its state + runtime inside the milestone directory
    (<docs_dir>/.run/), so a second milestone in the same repo never
    collides with a closed one. This is the default {slug} docs_dir layout
    (no config override)."""

    def _new_run(self, ws, name, goal="g"):
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": ws, "goal": goal, "name": name,
             "autostart": False})
        self.assertEqual(status, 201, body)
        entry = registry.get(registry.load(self.home), body["run"]["id"])
        return entry

    def test_state_lives_in_milestone_dir_not_workspace_root(self):
        ws = self.workspace("ws-layout")
        entry = self._new_run(ws, "My Feature")
        rel = os.path.relpath(entry["state_path"], ws)
        self.assertEqual(
            rel,
            os.path.join("implementation", "milestones", "my-feature",
                         ".run", "state.json"))
        self.assertTrue(os.path.isfile(entry["state_path"]))
        # No legacy workspace-root runtime dir was created.
        self.assertFalse(os.path.exists(os.path.join(ws, ".orchestrator")))

    def test_second_milestone_same_workspace_does_not_collide(self):
        ws = self.workspace("ws-two")
        e1 = self._new_run(ws, "Feature", goal="one")
        e2 = self._new_run(ws, "Feature", goal="two")  # no longer 409s
        self.assertNotEqual(e1["state_path"], e2["state_path"])
        self.assertIn(os.path.join("milestones", "feature", ".run"),
                      e1["state_path"])
        self.assertIn(os.path.join("milestones", "feature-2", ".run"),
                      e2["state_path"])
        self.assertTrue(os.path.isfile(e1["state_path"]))
        self.assertTrue(os.path.isfile(e2["state_path"]))

    def test_cli_workspace_resolves_and_flags_ambiguity(self):
        ws = self.workspace("ws-resolve")
        e1 = self._new_run(ws, "Alpha")
        # One run: --workspace resolves to it.
        self.assertEqual(
            os.path.abspath(driver.resolve_workspace_state(ws)),
            os.path.abspath(e1["state_path"]))
        # Two runs: ambiguous -> SystemExit (operator must pass --state).
        self._new_run(ws, "Beta")
        with self.assertRaises(SystemExit):
            driver.resolve_workspace_state(ws)

    def test_cli_legacy_state_resolution_does_not_walk_workspace(self):
        ws = self.workspace("ws-legacy-resolve")
        legacy = driver.default_state_path(ws)
        os.makedirs(os.path.dirname(legacy), exist_ok=True)
        with open(legacy, "w", encoding="utf-8") as handle:
            handle.write("{}")
        with mock.patch.object(
            driver.os,
            "walk",
            side_effect=AssertionError("legacy resolution must not walk"),
        ):
            self.assertEqual(driver.resolve_workspace_state(ws), legacy)

    def test_attach_rejects_state_from_another_workspace(self):
        ws_a = self.workspace("ws-a")
        ws_b = self.workspace("ws-b")
        entry_a = self._new_run(ws_a, "A")
        # Attaching A's state under workspace B must be refused.
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": ws_b, "attach": True, "autostart": False,
             "state_path": entry_a["state_path"]})
        self.assertEqual(status, 400)
        self.assertIn("belongs to workspace", body["error"])

    def test_operator_files_land_beside_state(self):
        ws = self.workspace("ws-amend-layout")
        entry = self._new_run(ws, "Amd")
        rid = entry["id"]
        status, _ = self.request_json(
            "POST", "/api/runs/%s/amendments" % rid, {"text": "be careful"})
        self.assertEqual(status, 200)
        runtime = os.path.dirname(entry["state_path"])
        self.assertTrue(os.path.isfile(
            os.path.join(runtime, "amendments.json")))
        self.assertFalse(os.path.exists(
            os.path.join(ws, ".orchestrator", "amendments.json")))


class ProfilesApiTest(ServiceApiTest):
    """Editable strategy definitions with run-retained identity/content."""

    def _race_strategy_read_with_edit(self, name, operation):
        before = profiles.load(self.home, name)["profile"]
        observed = threading.Event()
        release = threading.Event()
        result = {}
        real_load = profiles.load

        def paused_load(home, candidate):
            doc = real_load(home, candidate)
            if candidate == name and not observed.is_set():
                observed.set()
                release.wait(timeout=5)
            return doc

        def run_operation():
            result["value"] = operation()

        with mock.patch.object(profiles, "load", side_effect=paused_load):
            thread = threading.Thread(target=run_operation)
            thread.start()
            self.assertTrue(observed.wait(timeout=5))
            edited = real_load(self.home, name)
            edited["profile"] = {"doc_register": "lay+hard-table"}
            profiles.save(self.home, edited)
            release.set()
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        after = profiles.load(self.home, name)["profile"]
        return result["value"], before, after

    def test_seeds_listed_with_hash_and_content(self):
        status, body = self.request_json("GET", "/api/profiles")
        self.assertEqual(status, 200)
        names = {p["name"]: p for p in body["profiles"]}
        self.assertEqual(
            sorted(names), ["legacy", "light", "medium", "strict"]
        )
        strict = names["strict"]
        self.assertEqual(
            strict["hash"], profiles.semantic_hash(strict["profile"]))
        # The decomposition travels so the new-run form can show it.
        self.assertEqual(strict["profile"]["fuser_discard"], "evidence+concur")

    def test_strategy_views_and_panel_have_no_sealed_presentation(self):
        legacy = profiles.load(self.home, "legacy")
        legacy["description"] = "Operator edited compatibility description"
        legacy["sealed"] = True
        status, saved = self.request_json("POST", "/api/profiles", legacy)
        self.assertEqual(status, 200)
        self.assertNotIn("sealed", saved["profile"])
        self.assertEqual(
            saved["profile"]["description"], legacy["description"]
        )
        status, listed = self.request_json("GET", "/api/profiles")
        self.assertEqual(status, 200)
        self.assertTrue(all("sealed" not in p for p in listed["profiles"]))
        listed_legacy = next(
            p for p in listed["profiles"] if p["name"] == "legacy"
        )
        self.assertEqual(listed_legacy["description"], legacy["description"])

        status, raw_panel = self.request("GET", "/")
        self.assertEqual(status, 200)
        panel = raw_panel.decode("utf-8")
        label = panel[
            panel.index("function profileLabel(p)"):
            panel.index("let launchProfiles")
        ]
        self.assertNotIn("sealed", label.lower())
        self.assertNotIn("interpreter that honors it lands", panel)
        self.assertNotIn("for now it re-labels", panel)

    def test_creation_retains_content_and_identity_across_source_edit(self):
        ws = self.workspace("ws-profiled")
        source_path = os.path.join(profiles.profiles_dir(self.home), "light.json")
        with open(source_path, "rb") as fh:
            before_use = fh.read()
        status, body = self.create_run(ws, profile="light")
        self.assertEqual(status, 201)
        rid = body["run"]["id"]
        state_path = driver.default_state_path(ws)
        state = st.load(state_path)
        cfg = state["config"]
        ref = cfg["profile_ref"]
        light = profiles.load(self.home, "light")
        self.assertEqual(
            ref,
            {"name": "light", "version": light["version"],
             "hash": profiles.semantic_hash(light["profile"])},
        )
        self.assertEqual(cfg["profile"], light["profile"])
        self.assertTrue(profiles.verify_retained(ref, cfg["profile"]))
        with open(source_path, "rb") as fh:
            self.assertEqual(fh.read(), before_use)

        edited = profiles.load(self.home, "light")
        edited["profile"]["p3_defer_max_risk"] = "high"
        profiles.save(self.home, edited)
        retained = st.load(state_path)
        interpreter.verify_embedded(retained)
        self.assertEqual(
            retained["config"]["profile"]["p3_defer_max_risk"], "medium"
        )
        self.assertEqual(
            interpreter.effective_config(retained)["p3_defer_max_risk"],
            "medium",
        )
        status, detail = self.request_json("GET", "/api/runs/%s" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(detail["profile"]["governing"], ref)

    def test_creation_racing_edit_retains_one_complete_definition(self):
        profiles.save(self.home, {
            "name": "creation-race", "version": 1, "sealed": False,
            "description": "race", "profile": {"doc_register": "dense"},
        })
        ws = self.workspace("ws-creation-race")
        response, before, after = self._race_strategy_read_with_edit(
            "creation-race", lambda: self.create_run(ws, profile="creation-race")
        )
        self.assertEqual(response[0], 201)
        cfg = st.load(driver.default_state_path(ws))["config"]
        self.assertIn(cfg["profile"], (before, after))
        self.assertEqual(
            cfg["profile_ref"]["hash"], profiles.semantic_hash(cfg["profile"])
        )

    def test_create_unknown_profile_400_and_no_state(self):
        ws = self.workspace("ws-badprofile")
        status, body = self.create_run(ws, profile="ghost")
        self.assertEqual(status, 400)
        self.assertIn("ghost", body["error"])
        # Fail-fast: no orphan state was written for the rejected launch.
        self.assertFalse(os.path.exists(driver.default_state_path(ws)))

    def test_create_blank_profile_400(self):
        ws = self.workspace("ws-blankprofile")
        status, body = self.create_run(ws, profile="   ")
        self.assertEqual(status, 400)
        self.assertIn("profile", body["error"])

    def test_attach_with_profile_400(self):
        ws = self.workspace("ws-attach-profile")
        driver.init_run("adopted", ws,
                        state_path=driver.default_state_path(ws))
        status, body = self.request_json(
            "POST", "/api/runs",
            {"workspace": ws, "attach": True, "autostart": False,
             "profile": "light"})
        self.assertEqual(status, 400)
        self.assertIn("profile", body["error"])

    def test_profileless_run_has_no_ref(self):
        ws = self.workspace("ws-profileless")
        status, body = self.create_run(ws)
        self.assertEqual(status, 201)
        cfg = st.load(driver.default_state_path(ws))["config"]
        self.assertNotIn("profile_ref", cfg)
        status, detail = self.request_json(
            "GET", "/api/runs/%s" % body["run"]["id"])
        self.assertIsNone(detail["profile"])

    def test_post_creates_editable_profile(self):
        doc = {"name": "custom", "version": 1, "sealed": False,
               "description": "d", "profile": {"p3_defer_max_risk": "high"}}
        status, body = self.request_json("POST", "/api/profiles", doc)
        self.assertEqual(status, 200)
        self.assertNotIn("sealed", body["profile"])
        self.assertEqual(
            body["profile"]["hash"], profiles.semantic_hash(doc["profile"]))
        # It now shows up in the listing.
        _, listed = self.request_json("GET", "/api/profiles")
        self.assertIn("custom", {p["name"] for p in listed["profiles"]})

    def test_post_ignores_legacy_sealed_input(self):
        doc = {"name": "wannaseal", "version": 1, "sealed": True,
               "description": "d", "profile": {"doc_register": "dense"}}
        status, body = self.request_json("POST", "/api/profiles", doc)
        self.assertEqual(status, 200)
        self.assertNotIn("sealed", body["profile"])
        self.assertFalse(profiles.load(self.home, "wannaseal")["sealed"])

    def test_post_rejects_bad_document(self):
        for bad in ({}, {"name": "x y", "version": 1, "profile": {"a": 1}},
                    ["not", "a", "dict"]):
            status, body = self.request_json("POST", "/api/profiles", bad)
            self.assertEqual(status, 400)
            self.assertFalse(body["ok"])

    def test_invalid_strategy_edit_preserves_prior_definition(self):
        doc = {"name": "steady", "version": 1, "sealed": False,
               "description": "before", "profile": {"doc_register": "dense"}}
        self.request_json("POST", "/api/profiles", doc)
        invalid = dict(doc, profile={})
        status, body = self.request_json("POST", "/api/profiles", invalid)
        self.assertEqual(status, 400)
        self.assertTrue(body["error"])
        self.assertEqual(profiles.load(self.home, "steady"), doc)

    def test_profile_swap_retains_content_and_governs_future_decisions(self):
        ws = self.workspace("ws-swap")
        status, body = self.create_run(
            ws, profile="light"
        )
        self.assertEqual(status, 201)
        rid = body["run"]["id"]
        entry = registry.get(registry.load(self.home), rid)
        before_state = st.load(entry["state_path"])
        prior_events = json.loads(json.dumps(before_state["events"]))
        base_ref = before_state["config"]["profile_ref"]
        strict_path = os.path.join(
            profiles.profiles_dir(self.home), "strict.json"
        )
        with open(strict_path, "rb") as fh:
            strict_before = fh.read()

        status, sw = self.request_json(
            "POST", "/api/runs/%s/profile" % rid, {"profile": "strict"})
        self.assertEqual(status, 200)
        with open(strict_path, "rb") as fh:
            self.assertEqual(fh.read(), strict_before)
        strict = profiles.load(self.home, "strict")
        swap = sw["profile_swap"]
        self.assertEqual(swap["ref"]["name"], "strict")
        self.assertEqual(swap["profile"], strict["profile"])
        self.assertTrue(profiles.verify_retained(swap["ref"], swap["profile"]))
        overlay = os.path.join(
            os.path.dirname(entry["state_path"]), "profile_swap.json")
        self.assertTrue(os.path.isfile(overlay))
        status, detail = self.request_json("GET", "/api/runs/%s" % rid)
        self.assertEqual(detail["profile"]["base"]["name"], "light")
        self.assertEqual(detail["profile"]["governing"]["name"], "strict")

        runtime = driver.Driver(
            entry["state_path"], runner=mock.Mock(),
            model_profiles_home=self.home,
        )
        def observe_transition(**_kwargs):
            on_disk = st.load(entry["state_path"])
            self.assertEqual(
                on_disk["events"][-1]["type"], "reviewed_policy_frozen"
            )
            event_types = [event["type"] for event in on_disk["events"]]
            self.assertLess(
                event_types.index("profile_changed"),
                event_types.index("reviewed_policy_frozen"),
            )
            record = tasks.task_records(on_disk)[0]
            self.assertEqual(
                record["order"]["configuration"]["p3_defer_max_risk"],
                "low",
            )
            return "observed"

        with mock.patch.object(runtime, "_do_draft", side_effect=observe_transition):
            action, _note = runtime.step()
        self.assertEqual(action.type, driver.A_DRAFT)
        applied = st.load(entry["state_path"])
        self.assertEqual(applied["events"][:len(prior_events)], prior_events)
        transitions = [
            event for event in applied["events"]
            if event.get("type") == "profile_changed"
        ]
        self.assertEqual(len(transitions), 1)
        self.assertGreaterEqual(transitions[0]["seq"], len(prior_events))
        self.assertEqual(
            transitions[0],
            {
                "seq": transitions[0]["seq"],
                "at": transitions[0]["at"],
                "type": "profile_changed",
                "from": base_ref,
                "to": swap["ref"],
                "profile": swap["profile"],
            },
        )
        self.assertEqual(interpreter.governing_profile(applied), swap["profile"])
        self.assertEqual(runtime.config["p3_defer_max_risk"], "low")

        edited = profiles.load(self.home, "strict")
        edited["profile"]["p3_defer_max_risk"] = "high"
        profiles.save(self.home, edited)
        self.assertEqual(
            interpreter.governing_profile(st.load(entry["state_path"]))
            ["p3_defer_max_risk"],
            "low",
        )
        with mock.patch.object(runtime, "_do_draft", return_value="again"):
            runtime.step()
        self.assertEqual(
            len([e for e in runtime.state["events"]
                 if e.get("type") == "profile_changed"]),
            1,
        )

    def test_uninterpretable_profile_is_rejected_before_selection(self):
        status, _body = self.request_json("POST", "/api/profiles", {
            "name": "uninterpretable",
            "version": 1,
            "sealed": False,
            "description": "accepted but not implemented",
            "profile": {"stages": [{"loop": "parallel"}]},
        })
        self.assertEqual(status, 400)
        self.assertFalse(os.path.exists(os.path.join(
            profiles.profiles_dir(self.home), "uninterpretable.json"
        )))

    def test_legacy_identity_only_profile_swap_is_inert(self):
        ws = self.workspace("ws-legacy-swap")
        _, created = self.create_run(ws)
        run_id = created["run"]["id"]
        entry = registry.get(registry.load(self.home), run_id)
        overlay_path = os.path.join(
            os.path.dirname(entry["state_path"]), "profile_swap.json"
        )
        legacy_overlay = {
            "ref": profiles.reference(self.home, "light"),
            "at": registry.now_iso(),
        }
        with open(overlay_path, "w", encoding="utf-8") as fh:
            json.dump(legacy_overlay, fh)

        self.assertIsNone(service.read_profile(entry))
        runtime = driver.Driver(
            entry["state_path"], runner=mock.Mock(),
            model_profiles_home=self.home,
        )
        with mock.patch.object(runtime, "_do_draft", return_value="observed"):
            action, note = runtime.step()

        self.assertEqual(action.type, driver.A_DRAFT)
        self.assertEqual(note, "observed")
        self.assertFalse(any(
            event.get("type") == "profile_changed"
            for event in runtime.state["events"]
        ))
        with open(overlay_path, "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), legacy_overlay)

    def test_profile_swap_unknown_profile_400(self):
        ws = self.workspace("ws-swap-bad")
        _, body = self.create_run(ws, profile="light")
        rid = body["run"]["id"]
        status, out = self.request_json(
            "POST", "/api/runs/%s/profile" % rid, {"profile": "ghost"})
        self.assertEqual(status, 400)
        self.assertIn("ghost", out["error"])

    def test_profile_swap_can_govern_a_run_without_a_base_strategy(self):
        ws = self.workspace("ws-swap-profileless")
        _, body = self.create_run(ws)
        rid = body["run"]["id"]
        status, swap = self.request_json(
            "POST", "/api/runs/%s/profile" % rid, {"profile": "light"}
        )
        self.assertEqual(status, 200)
        entry = registry.get(registry.load(self.home), rid)
        runtime = driver.Driver(
            entry["state_path"], runner=mock.Mock(),
            model_profiles_home=self.home,
        )
        with mock.patch.object(runtime, "_do_draft", return_value="observed"):
            runtime.step()
        event = next(
            e for e in runtime.state["events"]
            if e.get("type") == "profile_changed"
        )
        self.assertIsNone(event["from"])
        self.assertEqual(event["to"], swap["profile_swap"]["ref"])

    def test_profile_swap_racing_edit_retains_one_complete_definition(self):
        profiles.save(self.home, {
            "name": "swap-race", "version": 1, "sealed": False,
            "description": "race", "profile": {"doc_register": "dense"},
        })
        _, created = self.create_run(self.workspace("ws-swap-race"))
        run_id = created["run"]["id"]
        response, before, after = self._race_strategy_read_with_edit(
            "swap-race",
            lambda: self.request_json(
                "POST", "/api/runs/%s/profile" % run_id,
                {"profile": "swap-race"},
            ),
        )
        self.assertEqual(response[0], 200)
        retained = response[1]["profile_swap"]
        self.assertIn(retained["profile"], (before, after))
        self.assertEqual(
            retained["ref"]["hash"],
            profiles.semantic_hash(retained["profile"]),
        )

    def test_concurrent_profile_swaps_do_not_share_staging_file(self):
        profiles.save(self.home, {
            "name": "swap-a", "version": 1, "sealed": False,
            "description": "a", "profile": {"doc_register": "dense"},
        })
        profiles.save(self.home, {
            "name": "swap-b", "version": 1, "sealed": False,
            "description": "b",
            "profile": {"doc_register": "lay+hard-table"},
        })
        _, created = self.create_run(self.workspace("ws-concurrent-swaps"))
        run_id = created["run"]["id"]
        replacements_ready = threading.Barrier(2)
        real_replace = os.replace
        staging_paths = []
        results = []
        errors = []

        def synchronized_replace(source, target):
            staging_paths.append(source)
            replacements_ready.wait(timeout=5)
            real_replace(source, target)

        def change(name):
            try:
                results.append(service.set_profile_swap(
                    self.home, run_id, {"profile": name}
                ))
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(
                service.os, "replace", side_effect=synchronized_replace):
            threads = [threading.Thread(target=change, args=(name,))
                       for name in ("swap-a", "swap-b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(set(staging_paths)), 2)
        self.assertEqual({item["ref"]["name"] for item in results},
                         {"swap-a", "swap-b"})
        entry = registry.get(registry.load(self.home), run_id)
        self.assertIn(service.read_profile_overlay(entry), results)

    def test_profile_swap_unknown_run_404(self):
        status, out = self.request_json(
            "POST", "/api/runs/nope/profile", {"profile": "light"})
        self.assertEqual(status, 404)

    def test_profile_swap_missing_name_400(self):
        ws = self.workspace("ws-swap-noname")
        _, body = self.create_run(ws, profile="light")
        rid = body["run"]["id"]
        status, out = self.request_json(
            "POST", "/api/runs/%s/profile" % rid, {})
        self.assertEqual(status, 400)
        self.assertIn("profile", out["error"])

    def test_used_profile_edit_replaces_content(self):
        doc = {"name": "frozen", "version": 1, "sealed": False,
               "description": "d", "profile": {"doc_register": "dense"}}
        self.request_json("POST", "/api/profiles", doc)
        profiles.reference(self.home, "frozen")
        changed = dict(doc, profile={"doc_register": "lay+hard-table"})
        status, body = self.request_json("POST", "/api/profiles", changed)
        self.assertEqual(status, 200)
        self.assertEqual(
            body["profile"]["profile"], {"doc_register": "lay+hard-table"}
        )
        self.assertNotIn("sealed", body["profile"])


class ProfilesDecisionApiTest(ServiceApiTest):
    def strategy_doc(self, name, content):
        return {
            "name": name,
            "version": 1,
            "sealed": False,
            "description": "test",
            "profile": content,
        }

    def test_catalogue_response_uses_shared_inventory(self):
        status, body = self.request_json("GET", "/api/profiles")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"ok", "profiles", "decisions"})
        self.assertEqual(body["decisions"], profiles.decision_catalogue())

    def test_fixed_open_action_is_not_a_composable_decision(self):
        status, body = self.request_json(
            "POST",
            "/api/profiles",
            self.strategy_doc(
                "action-only",
                {"stages": [{"actions": [{"scope": "open"}]}]},
            ),
        )
        self.assertEqual(status, 400)
        self.assertIn("stages[0].loop", body["error"])

    def test_invalid_stored_profile_fails_listing_instead_of_disappearing(self):
        profiles.save(
            self.home,
            self.strategy_doc("damaged", {"doc_register": "dense"}),
        )
        path = os.path.join(profiles.profiles_dir(self.home), "damaged.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.strategy_doc("damaged", {"unknown": True}), fh)
        status, body = self.request_json("GET", "/api/profiles")
        self.assertEqual(status, 500)
        self.assertFalse(body["ok"])
        self.assertTrue(body["error"])

    def test_invalid_stored_profile_failure_is_visible_on_launch_surface(self):
        status, raw_panel = self.request("GET", "/")
        self.assertEqual(status, 200)
        panel = raw_panel.decode("utf-8")
        launch_surface = panel[
            panel.index("let launchProfiles = [];"):
            panel.index("/* ---- runtime profile swap")
        ]
        self.assertIn("catch (e) { loadError = e.message; }", launch_surface)
        self.assertIn("launchProfilesError = loadError;", launch_surface)
        self.assertIn("hint.textContent = launchProfilesError;",
                      launch_surface)

    def test_advanced_config_validates_raw_strategy_content(self):
        workspace = self.workspace("ws-raw-strategy-config")
        status, body = self.create_run(
            workspace,
            config={
                "git": {"enabled": False},
                "profile": {"doc_register": "lay+hard-table"},
            },
        )
        self.assertEqual(status, 201)
        entry = registry.get(registry.load(self.home), body["run"]["id"])
        state = st.load(entry["state_path"])
        self.assertEqual(
            state["config"]["profile"],
            {"doc_register": "lay+hard-table"},
        )
        self.assertNotIn("profile_ref", state["config"])

        invalid_workspace = self.workspace("ws-invalid-raw-strategy-config")
        before_registry = registry.load(self.home)
        status, body = self.create_run(
            invalid_workspace,
            config={
                "git": {"enabled": False},
                "profile": {"unknown": True},
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("unknown strategy decision", body["error"])
        self.assertEqual(registry.load(self.home), before_registry)
        self.assertFalse(os.path.exists(
            driver.default_state_path(invalid_workspace)
        ))

    def test_project_defaults_validate_raw_strategy_content(self):
        project = "strategy-defaults"
        workspace = self.workspace("ws-project-default-strategy")
        service.create_project(self.home, {
            "slug": project,
            "defaults": {
                "git": {"enabled": False},
                "profile": {"doc_register": "lay+hard-table"},
            },
        })
        service.declare_work_area(self.home, project, {
            "name": "main",
            "primary_path": workspace,
        })
        status, body = self.request_json("POST", "/api/runs", {
            "project": project,
            "work_area": "main",
            "goal": "Test goal",
            "autostart": False,
            "config": {"docs_dir": "docs"},
        })
        self.assertEqual(status, 201)
        entry = registry.get(registry.load(self.home), body["run"]["id"])
        state = st.load(entry["state_path"])
        self.assertEqual(
            state["config"]["profile"],
            {"doc_register": "lay+hard-table"},
        )
        self.assertNotIn("profile_ref", state["config"])

        invalid_workspace = self.workspace("ws-project-invalid-strategy")
        service.update_project(self.home, project, {
            "defaults": {
                "git": {"enabled": False},
                "profile": {"unknown": True},
            },
        })
        service.declare_work_area(self.home, project, {
            "name": "invalid",
            "primary_path": invalid_workspace,
        })
        before_registry = registry.load(self.home)
        status, body = self.request_json("POST", "/api/runs", {
            "project": project,
            "work_area": "invalid",
            "goal": "Test goal",
            "autostart": False,
            "config": {"docs_dir": "docs"},
        })
        self.assertEqual(status, 400)
        self.assertIn("unknown strategy decision", body["error"])
        self.assertEqual(registry.load(self.home), before_registry)
        self.assertFalse(os.path.exists(
            driver.default_state_path(invalid_workspace)
        ))

    def test_case_variant_cannot_replace_legacy_compatibility_profile(self):
        path = os.path.join(profiles.profiles_dir(self.home), "legacy.json")
        with open(path, "rb") as fh:
            prior_bytes = fh.read()
        status, body = self.request_json(
            "POST",
            "/api/profiles",
            self.strategy_doc("Legacy", {"doc_register": "lay+hard-table"}),
        )
        self.assertEqual(status, 400)
        self.assertIn("exactly 'legacy'", body["error"])
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), prior_bytes)

        workspace = self.workspace("ws-exact-legacy")
        status, created = self.create_run(workspace, profile="legacy")
        self.assertEqual(status, 201)
        entry = registry.get(registry.load(self.home), created["run"]["id"])
        state = st.load(entry["state_path"])
        self.assertEqual(
            state["config"]["profile"], profiles.SEEDS["legacy"]["profile"]
        )
        self.assertFalse(interpreter.reform_active(state))

    def test_invalid_strategy_never_creates_or_repoints_a_run(self):
        profiles.save(
            self.home,
            self.strategy_doc("damaged", {"doc_register": "dense"}),
        )
        path = os.path.join(profiles.profiles_dir(self.home), "damaged.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.strategy_doc("damaged", {"unknown": True}), fh)

        rejected_ws = self.workspace("ws-invalid-create")
        status, body = self.create_run(rejected_ws, profile="damaged")
        self.assertEqual(status, 400)
        self.assertTrue(body["error"])
        self.assertFalse(os.path.exists(driver.default_state_path(rejected_ws)))

        _, created = self.create_run(self.workspace("ws-invalid-repoint"))
        run_id = created["run"]["id"]
        status, valid = self.request_json(
            "POST", "/api/runs/%s/profile" % run_id, {"profile": "strict"}
        )
        self.assertEqual(status, 200)
        entry = registry.get(registry.load(self.home), run_id)
        overlay_path = service._profile_overlay_path(entry)
        with open(overlay_path, "rb") as fh:
            prior_bytes = fh.read()
        status, body = self.request_json(
            "POST", "/api/runs/%s/profile" % run_id, {"profile": "damaged"}
        )
        self.assertEqual(status, 400)
        self.assertTrue(body["error"])
        with open(overlay_path, "rb") as fh:
            self.assertEqual(fh.read(), prior_bytes)
        self.assertEqual(service.read_profile_overlay(entry), valid["profile_swap"])

    def test_reserved_content_round_trips_without_runtime_effect(self):
        semantics = (
            {
                "doc_register": "dense",
                "fuser_discard": "evidence",
                "final_open_pass": False,
            },
            {
                "doc_register": "dense",
                "fuser_discard": "evidence+concur",
                "final_open_pass": True,
            },
        )
        states = []
        for index, content in enumerate(semantics):
            name = "reserved-%d" % index
            status, _body = self.request_json(
                "POST", "/api/profiles", self.strategy_doc(name, content)
            )
            self.assertEqual(status, 200)
            ref, resolved = profiles.resolve(self.home, name)
            self.assertEqual(resolved, content)
            self.assertTrue(profiles.verify_retained(ref, resolved))
            _, created = self.create_run(
                self.workspace("ws-%s" % name), profile=name
            )
            entry = registry.get(registry.load(self.home), created["run"]["id"])
            state = st.load(entry["state_path"])
            self.assertEqual(state["config"]["profile"], content)
            states.append(state)

        _, listed = self.request_json("GET", "/api/profiles")
        listed = {item["name"]: item["profile"] for item in listed["profiles"]}
        self.assertEqual([listed["reserved-%d" % i] for i in range(2)], list(semantics))
        self.assertEqual(
            [interpreter.rounds_loop(state) for state in states],
            [interpreter.FAMILY_UNTIL_CLEAN] * 2,
        )
        self.assertEqual(
            [interpreter.doc_register(state) for state in states],
            ["dense", "dense"],
        )
        effective_risks = [
            interpreter.effective_config(state).get("p3_defer_max_risk")
            for state in states
        ]
        self.assertEqual(effective_risks[0], effective_risks[1])
        self.assertEqual(
            [driver.decide(state).type for state in states],
            [driver.A_DRAFT, driver.A_DRAFT],
        )


class StrategyConfiguratorPanelTest(ServiceApiTest):
    """Slice 6: one catalogue-driven strategy form over the existing API."""

    def panel_source(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        return body.decode("utf-8")

    def strategy_source(self):
        panel = self.panel_source()
        return panel[
            panel.index("/* ---- strategy catalogue, configurator"):
            panel.index("function browseGoalDoc")
        ]

    def member_request_json(self, method, path, payload=None):
        data = (json.dumps(payload).encode("utf-8")
                if payload is not None else None)
        req = urllib.request.Request(
            self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Host", "example.ngrok-free.dev")
        req.add_header(access.REMOTE_HEADER, access.REMOTE_MARKER)
        req.add_header(access.USER_HEADER, access.USER_EMAILS[0])
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    @staticmethod
    def editable(view):
        return {
            "name": view["name"],
            "version": view["version"],
            "description": view["description"],
            "profile": json.loads(json.dumps(view["profile"])),
        }

    @staticmethod
    def complete_content(decisions, value_index=0):
        content = {}
        for decision in decisions:
            value = decision["values"][value_index % len(decision["values"])]
            if decision["key"] == "stages[0].loop":
                content["stages"] = [{"loop": value}]
            else:
                content[decision["key"]] = value
        return content

    def test_configurator_uses_catalogue_inventory_and_access(self):
        panel = self.panel_source()
        source = self.strategy_source()
        self.assertIn('id="strategyprofilesdlg"', panel)
        self.assertIn('id="strategyprofileeditor"', panel)
        self.assertIn('id="sp_new" style="display:none"', panel)
        self.assertIn("loadedDecisions = Array.isArray(data.decisions)", source)
        self.assertIn("strategyDecisions.map(decision =>", source)
        self.assertIn("decision.values.map((value, valueIndex)", source)
        self.assertNotIn("openSgEditor", source)
        self.assertNotIn("sg_json", source)
        self.assertIn('create.style.display = appAccess.admin ? "" : "none";',
                      source)
        self.assertIn('appAccess.user ? "" : "none";', panel)

        status, body = self.member_request_json("GET", "/api/profiles")
        self.assertEqual(status, 200)
        self.assertEqual(body["decisions"], profiles.decision_catalogue())
        status, body = self.member_request_json(
            "POST", "/api/profiles", {
                "name": "member-write", "version": 1,
                "description": "refused",
                "profile": {"doc_register": "dense"},
            })
        self.assertEqual(status, 403)
        self.assertFalse(body["ok"])

    def test_configurator_create_posts_complete_decisions(self):
        _, catalogue = self.request_json("GET", "/api/profiles")
        content = self.complete_content(catalogue["decisions"])
        request_doc = {
            "name": "configured", "version": 1,
            "description": "made in the decision form", "profile": content,
        }
        status, saved = self.request_json(
            "POST", "/api/profiles", request_doc)
        self.assertEqual(status, 200)
        self.assertEqual(saved["profile"]["profile"], content)
        self.assertEqual(
            saved["profile"]["hash"], profiles.semantic_hash(content))
        _, refreshed = self.request_json("GET", "/api/profiles")
        configured = next(
            item for item in refreshed["profiles"]
            if item["name"] == "configured")
        self.assertEqual(configured["profile"], content)

        source = self.strategy_source()
        save = source[
            source.index("async function saveStrategyProfile"):
            source.index("function onProfileChange")
        ]
        self.assertIn('launchProfiles.some(profile => profile.name === name)',
                      save)
        self.assertLess(save.index("launchProfiles.some"),
                        save.index('postJSON("/api/profiles"'))
        request_shape = save[
            save.index("const documentValue = {"):save.index("try {")
        ]
        for field in ("name,", "version:", "description:", "profile:"):
            self.assertIn(field, request_shape)
        self.assertNotIn("hash", request_shape)
        self.assertNotIn("sealed", request_shape)

    def test_configurator_edit_preserves_opened_name_and_stage_content(self):
        _, listed = self.request_json("GET", "/api/profiles")
        strict = next(p for p in listed["profiles"] if p["name"] == "strict")
        edited = self.editable(strict)
        edited["profile"]["doc_register"] = "lay+hard-table"
        status, saved = self.request_json("POST", "/api/profiles", edited)
        self.assertEqual(status, 200)
        self.assertEqual(saved["profile"]["name"], "strict")
        self.assertEqual(
            saved["profile"]["profile"]["stages"][0]["actions"],
            [{"scope": "open"}],
        )

        source = self.strategy_source()
        self.assertIn('name.disabled = config.mode === "edit";', source)
        self.assertIn('? strategyEditor.openedName : enteredName;', source)
        self.assertIn(
            "const content = JSON.parse(JSON.stringify(strategyEditor.baseProfile));",
            source,
        )
        self.assertIn("setStrategyDecision(content, decision.key", source)

    def test_configurator_edit_preserves_non_string_description_until_changed(self):
        _, listed = self.request_json("GET", "/api/profiles")
        strict = next(p for p in listed["profiles"] if p["name"] == "strict")
        edited = self.editable(strict)
        edited["description"] = {
            "format": "structured", "content": ["keep", 7, False],
            "toString": "not-callable",
        }
        status, saved = self.request_json("POST", "/api/profiles", edited)
        self.assertEqual(status, 200)
        self.assertEqual(saved["profile"]["description"], edited["description"])
        _, refreshed = self.request_json("GET", "/api/profiles")
        refreshed_strict = next(
            p for p in refreshed["profiles"] if p["name"] == "strict")
        self.assertEqual(
            refreshed_strict["description"], edited["description"])

        source = self.strategy_source()
        self.assertIn(
            "const descriptionText = strategyDescriptionText(config.description);",
            source,
        )
        self.assertIn(
            'esc(strategyDescriptionText(profile.description))', source)
        self.assertIn(
            'esc(strategyDescriptionText(p.description))', source)
        self.assertIn("strategyEditor.descriptionText = descriptionText;", source)
        save = source[
            source.index("async function saveStrategyProfile"):
            source.index("function onProfileChange")
        ]
        self.assertIn(
            "descriptionText === strategyEditor.descriptionText", save)
        self.assertIn("? strategyEditor.description : descriptionText", save)

    def test_configurator_composable_seeds_round_trip_exactly(self):
        _, listed = self.request_json("GET", "/api/profiles")
        views = {p["name"]: p for p in listed["profiles"]}
        for name in ("strict", "medium", "light"):
            before = views[name]
            status, saved = self.request_json(
                "POST", "/api/profiles", self.editable(before))
            self.assertEqual(status, 200)
            self.assertEqual(saved["profile"]["profile"], before["profile"])
            self.assertEqual(saved["profile"]["hash"], before["hash"])
            self.assertEqual(
                saved["profile"]["profile"]["stages"][0]["actions"],
                [{"scope": "open"}],
            )

    def test_configurator_partial_edit_requires_explicit_completion(self):
        partial = {
            "name": "partial", "version": 1, "description": "unfinished",
            "profile": {"doc_register": "dense"},
        }
        status, _ = self.request_json("POST", "/api/profiles", partial)
        self.assertEqual(status, 200)
        path = os.path.join(profiles.profiles_dir(self.home), "partial.json")
        with open(path, "rb") as fh:
            before = fh.read()
        self.panel_source()
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)

        source = self.strategy_source()
        self.assertIn('<option value="">— choose —</option>', source)
        self.assertIn("const incomplete = !strategyEditor.compatibility", source)
        self.assertIn("duplicate || incomplete", source)

        _, catalogue = self.request_json("GET", "/api/profiles")
        completed = dict(partial)
        completed["profile"] = self.complete_content(
            catalogue["decisions"], value_index=1)
        status, saved = self.request_json(
            "POST", "/api/profiles", completed)
        self.assertEqual(status, 200)
        for decision in catalogue["decisions"]:
            key = decision["key"]
            if key == "stages[0].loop":
                self.assertIn("loop", saved["profile"]["profile"]["stages"][0])
            else:
                self.assertIn(key, saved["profile"]["profile"])

    def test_configurator_legacy_is_metadata_only(self):
        _, listed = self.request_json("GET", "/api/profiles")
        legacy = next(p for p in listed["profiles"] if p["name"] == "legacy")
        semantic = json.loads(json.dumps(legacy["profile"]))
        edited = self.editable(legacy)
        edited["description"] = "Compatibility, newly described"
        status, saved = self.request_json("POST", "/api/profiles", edited)
        self.assertEqual(status, 200)
        self.assertEqual(saved["profile"]["profile"], semantic)
        self.assertEqual(saved["profile"]["description"], edited["description"])

        source = self.strategy_source()
        self.assertIn("profile.profile.compat === true", source)
        self.assertIn('innerHTML = compatibility ? "" :', source)
        self.assertIn("if (strategyEditor.compatibility) return content;", source)
        self.assertIn("Compatibility semantics — not composable", source)

    def test_legacy_is_not_selectable_at_launch(self):
        _, listed = self.request_json("GET", "/api/profiles")
        self.assertIn("legacy", [p["name"] for p in listed["profiles"]])

        panel = self.panel_source()
        source = self.strategy_source()
        self.assertIn(
            'return profiles.filter(profile => profile.name !== "legacy");',
            source,
        )
        self.assertIn(
            "const selectableProfiles = selectableLaunchProfiles(launchProfiles);",
            source,
        )
        self.assertIn("selectableProfiles.map(p =>", source)
        self.assertIn("psProfiles = launchProfiles.slice();", source)
        submit = panel[
            panel.index("async function submitForm"):
            panel.index("/* ---- launch binding")
        ]
        self.assertIn("selectableLaunchProfiles(launchProfiles).some(",
                      submit)
        self.assertNotIn("strict / light / legacy", source)

    def test_strategy_surfaces_mark_reserved_values_non_operative(self):
        _, catalogue = self.request_json("GET", "/api/profiles")
        reserved = [d for d in catalogue["decisions"]
                    if d["status"] == "reserved"]
        self.assertEqual(
            [d["key"] for d in reserved],
            ["fuser_discard", "final_open_pass"],
        )
        source = self.strategy_source()
        self.assertIn('? "reserved — non-operative" : decision.status;', source)
        rows = source[
            source.index("function strategyDecisionRows"):
            source.index("function renderStrategyProfiles")
        ]
        self.assertIn("strategySupportText(decision)", rows)
        self.assertNotIn("function profileDials", source)

    def test_configurator_load_and_save_failures_do_not_fallback(self):
        source = self.strategy_source()
        load = source[
            source.index("async function loadProfiles"):
            source.index("async function openStrategyProfiles")
        ]
        self.assertLess(load.index("launchProfiles = [];"), load.index("try {"))
        self.assertLess(load.index("strategyDecisions = [];"), load.index("try {"))
        self.assertIn("loadError = e.message", load)
        self.assertIn("create.disabled = !!launchProfilesError", source)

        corrupt = os.path.join(
            profiles.profiles_dir(self.home), "zz-corrupt.json")
        with open(corrupt, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        status, body = self.request_json("GET", "/api/profiles")
        self.assertEqual(status, 500)
        self.assertFalse(body["ok"])
        os.unlink(corrupt)

        strict_path = os.path.join(
            profiles.profiles_dir(self.home), "strict.json")
        with open(strict_path, "rb") as fh:
            before = fh.read()
        # Build the rejected whole document from the real stored source.
        strict = profiles.load(self.home, "strict")
        invalid = {
            "name": strict["name"], "version": strict["version"],
            "description": strict["description"],
            "profile": {"unknown": True},
        }
        status, body = self.request_json("POST", "/api/profiles", invalid)
        self.assertEqual(status, 400)
        self.assertTrue(body["error"])
        with open(strict_path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        save = source[
            source.index("async function saveStrategyProfile"):
            source.index("function onProfileChange")
        ]
        self.assertLess(save.index("catch (e)"), save.index(
            'document.getElementById("strategyprofileeditor").close()'))

    def test_configurator_ignores_out_of_order_catalogue_loads(self):
        source = self.strategy_source()
        load = source[
            source.index("async function loadProfiles"):
            source.index("async function openStrategyProfiles")
        ]
        self.assertIn("const loadSequence = ++strategyCatalogueLoadSequence;",
                      load)
        stale_guard = (
            "if (loadSequence !== strategyCatalogueLoadSequence) "
            "return false;"
        )
        self.assertIn(stale_guard, load)
        self.assertLess(load.index(stale_guard),
                        load.index("launchProfiles = loadedProfiles;"))
        self.assertLess(load.index(stale_guard),
                        load.index("launchProfilesError = loadError;"))
        self.assertIn("if (!await loadProfiles()) return;", source)

    def test_launch_waits_for_current_catalogue_before_submission(self):
        panel = self.panel_source()
        source = self.strategy_source()
        load = source[
            source.index("async function loadProfiles"):
            source.index("async function openStrategyProfiles")
        ]
        submit = panel[
            panel.index("async function submitForm"):
            panel.index("/* ---- launch binding")
        ]
        self.assertLess(load.index("strategyCatalogueLoading = true;"),
                        load.index('await api("/api/profiles")'))
        self.assertLess(load.index("sel.disabled = true;"),
                        load.index('await api("/api/profiles")'))
        self.assertIn("strategyCatalogueLoading = false;", load)
        self.assertIn("sel.disabled = !!launchProfilesError", load)
        self.assertIn("if (strategyCatalogueLoading)", submit)
        self.assertIn("if (launchProfilesError)", submit)
        self.assertIn(
            "selectableLaunchProfiles(launchProfiles).some(",
            submit,
        )


class ModelProfileSurfacesApiTest(ServiceApiTest):
    """All that survives the model-profile surfaces: the launch refusal.

    A run's staffing is the router's session, so the per-run chooser and
    its `GET/POST /api/runs/<id>/model-profile`, then the catalogue and its
    `GET/POST /api/model-profiles`, retired with the panel controls they
    served (staffing-router slice 8). The stored documents and
    `model_profile.json` are untouched and still read at resume, which
    `test_model_profiles` and `test_model_profile_runtime` cover."""

    def catalogue_doc(self, name, model="profile-model"):
        return {
            "name": name,
            "examples": ["surface test"],
            "configurations": {
                "low": {},
                "medium": {"fixer": {
                    "agent": "codex", "model": model, "effort": "medium"
                }},
                "high": {},
            },
        }

    def selection_path(self, run_id):
        entry = registry.get(registry.load(self.home), run_id)
        return os.path.join(
            os.path.dirname(entry["state_path"]), "model_profile.json"
        )

    def test_launch_refuses_model_profile_and_writes_no_selection(self):
        """`model_profile` decides no call after the driver cutover, so the
        launch refuses it before creating anything and writes no sidecar."""
        model_profiles.save(self.home, self.catalogue_doc("launch"))

        for label, selection in (
            ("named", {"name": "launch", "rigor": "low"}),
            ("unknown", {"name": "missing", "rigor": "medium"}),
            ("null", None),
        ):
            with self.subTest(case=label):
                ws = self.workspace("ws-selection-launch-%s" % label)
                with mock.patch(
                    "orchestrator.service.start_run"
                ) as mocked_start:
                    status, body = self.request_json("POST", "/api/runs", {
                        "workspace": ws, "goal": "launch", "autostart": True,
                        "config": {"docs_dir": "docs"},
                        "model_profile": selection,
                    })
                self.assertEqual(status, 400, body)
                self.assertIn("staffing", body["error"])
                self.assertFalse(
                    os.path.exists(driver.default_state_path(ws)))
                mocked_start.assert_not_called()

        plain_ws = self.workspace("ws-selection-launch-default")
        status, plain = self.create_run(plain_ws)
        self.assertEqual(status, 201, plain)
        self.assertFalse(os.path.lexists(
            self.selection_path(plain["run"]["id"])
        ))

        attach_ws = self.workspace("ws-selection-launch-attach")
        driver.init_run(
            "attach", attach_ws, state_path=driver.default_state_path(attach_ws)
        )
        for selection in ({"name": "launch", "rigor": "medium"}, None):
            status, body = self.request_json("POST", "/api/runs", {
                "workspace": attach_ws, "attach": True, "autostart": False,
                "model_profile": selection,
            })
            self.assertEqual(status, 400, body)
            self.assertIn("staffing", body["error"])


class CommitWebBaseTest(unittest.TestCase):
    """commit_web_base derives an https web URL from a workspace's origin
    remote so the panel can link gate commits. No HTTP server needed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-webbase-")
        service._WEB_BASE_CACHE.clear()

    def tearDown(self):
        service._WEB_BASE_CACHE.clear()
        self.tmp.cleanup()

    def repo(self, name, origin=None):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path)
        subprocess.run(["git", "init", "-q", path], check=True)
        if origin:
            subprocess.run(
                ["git", "-C", path, "remote", "add", "origin", origin],
                check=True,
            )
        return path

    def test_https_origin(self):
        ws = self.repo("a", "https://github.com/me/proj.git")
        self.assertEqual(
            service.commit_web_base(ws), "https://github.com/me/proj")

    def test_scp_ssh_origin(self):
        ws = self.repo("b", "git@github.com:me/proj.git")
        self.assertEqual(
            service.commit_web_base(ws), "https://github.com/me/proj")

    def test_no_origin_is_none(self):
        self.assertIsNone(service.commit_web_base(self.repo("c")))

    def test_local_path_origin_followed_one_hop(self):
        # The self-hosting clone recipe: the milestone clone's origin is the
        # canon checkout itself; the link should reach the canon's web remote.
        upstream = self.repo("canon", "https://github.com/me/canon.git")
        clone = self.repo("clone", upstream)
        self.assertEqual(
            service.commit_web_base(clone), "https://github.com/me/canon")

    def test_local_hop_without_web_remote_is_none(self):
        upstream = self.repo("bare-canon")
        clone = self.repo("clone2", upstream)
        self.assertIsNone(service.commit_web_base(clone))

    def test_cached_per_workspace(self):
        ws = self.repo("d", "https://github.com/me/x.git")
        self.assertEqual(
            service.commit_web_base(ws), "https://github.com/me/x")
        subprocess.run(
            ["git", "-C", ws, "remote", "set-url", "origin",
             "https://github.com/me/y.git"], check=True)
        # remotes effectively never change under a running service; the
        # cached answer sticks (2s polls must not spawn git each tick)
        self.assertEqual(
            service.commit_web_base(ws), "https://github.com/me/x")


if __name__ == "__main__":
    unittest.main()
