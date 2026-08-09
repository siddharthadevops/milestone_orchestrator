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

from orchestrator import access, driver, model_profiles, profiles, registry
from orchestrator import service, state as st


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
        self.assertIn('onclick="newBrainstorming(event,', text)
        self.assertIn("<span>New milestone</span>", text)
        self.assertIn("<span>New brainstorming</span>", text)
        self.assertIn(
            'id="b_rounds" type="number" min="1" step="1" value="10"',
            text,
        )
        self.assertIn("function openForm(preselect)", text)
        self.assertIn("function selectProjectSlug", text)
        # Brainstorming sessions share the sidebar list with milestones,
        # each kind carrying its own icon, and open their own page.
        self.assertIn('id="bsform"', text)
        self.assertIn("function submitBrainstorming", text)
        self.assertIn('api("/api/brainstorming/sessions"', text)
        # Seats are configured like milestone acts (agent/model/effort per
        # row, add/remove), never as typed ids; references are a managed
        # list with add/remove, not a free textarea.
        self.assertIn("function renderBsRoster", text)
        self.assertIn("function addBsSeat", text)
        self.assertIn("function removeBsSeat", text)
        # The dialog opens pre-staffed with Codex, Claude, and Dante; the
        # retired claude id is gone from every option list.
        self.assertIn(
            '{role: "initial_position", delivery: "llm", agent: "codex",', text)
        self.assertIn(
            '{role: "contrary_position", delivery: "llm", agent: "claude",',
            text,
        )
        self.assertIn('model: "claude-opus-5", effort: "max"', text)
        self.assertIn(
            '{role: "common_sense", delivery: "external", '
            'externalProvider: "narrator",',
            text,
        )
        self.assertIn('agent: "codex", model: "gpt-5.6-sol", effort: "max"',
                      text)
        self.assertIn('"claude-opus-5"', text)
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
        self.assertIn("function browseGoalDoc", text)
        self.assertIn('"~/Development/source"', text)
        self.assertIn("picker.transform", text)
        self.assertIn("function sidebarItems", text)
        self.assertIn("last_action_epoch: r.last_action_epoch", text)
        self.assertIn("last_action_epoch: s.last_action_epoch", text)
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
        self.assertIn("sessionActorLabel(view, lead && lead.id)", text)
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
        self.assertIn('id="a_skeletoner_agent"', text)
        self.assertIn('id="ra_skeletoner_model"', text)
        self.assertNotIn('convergence_fixer', text)
        # Switching an act's family resets model+effort (not just the
        # datalist): the onAgentChange userChanged branch clears both.
        self.assertIn("function onAgentChange(prefix, act, userChanged)", text)
        self.assertIn("if (userChanged)", text)
        self.assertIn("modelEl.value = \"\"", text)
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


class ActsApiTest(ServiceApiTest):
    def test_set_and_read_acts(self):
        ws = self.workspace("ws-acts")
        status, body = self.create_run(ws)
        rid = body["run"]["id"]
        status, body = self.request_json(
            "POST", "/api/runs/%s/acts" % rid,
            {"implementer": {"agent": "claude", "model": "sonnet",
                             "effort": "high"},
             "review_codex": {"model": "gpt-5.6-terra",
                              "effort": "high"},
             "review_claude": {"agent": "claude",
                               "model": "claude-sonnet-5",
                               "effort": "medium"},
             "fixer": "codex",
             "skeletoner": {"agent": "claude",
                            "model": "claude-fable-5",
                            "effort": "max"},
             "drafter": None})
        self.assertEqual(status, 200)
        self.assertEqual(body["acts"]["implementer"]["model"], "sonnet")
        self.assertNotIn("drafter", body["acts"])
        self.assertEqual(body["acts"]["review_codex"]["effort"], "high")
        self.assertEqual(body["acts"]["review_claude"]["model"],
                         "claude-sonnet-5")
        self.assertNotIn("agent", body["acts"]["review_claude"])
        self.assertEqual(body["acts"]["skeletoner"]["effort"], "max")
        status, body = self.request_json("GET", "/api/runs/%s" % rid)
        self.assertEqual(body["acts"]["fixer"], "codex")
        with open(os.path.join(ws, ".orchestrator", "acts.json"),
                  encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["implementer"]["effort"], "high")

    def test_acts_validation(self):
        ws = self.workspace("ws-acts-bad")
        status, body = self.create_run(ws)
        rid = body["run"]["id"]
        status, _ = self.request_json(
            "POST", "/api/runs/%s/acts" % rid, {"reviewer": "claude"})
        self.assertEqual(status, 400)
        status, _ = self.request_json(
            "POST", "/api/runs/%s/acts" % rid,
            {"delta_review": {"agent": "claude", "model": "x"}})
        self.assertEqual(status, 400)
        status, _ = self.request_json(
            "POST", "/api/runs/%s/acts" % rid, {"fixer": {"model": "x" * 200}})
        self.assertEqual(status, 400)
        status, _ = self.request_json(
            "POST", "/api/runs/%s/acts" % rid,
            {"review_codex": {"agent": "claude", "model": "x"}})
        self.assertEqual(status, 400)
        status, _ = self.request_json(
            "POST", "/api/runs/%s/acts" % rid,
            {"review_claude": "claude"})
        self.assertEqual(status, 400)


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
    """Per-run strategy profiles (build-driven review reform, phase 1b):
    the seeds are listable, a run snapshots+seals its chosen profile, and
    profile-less runs stay untouched."""

    def test_seeds_listed_with_hash_and_content(self):
        status, body = self.request_json("GET", "/api/profiles")
        self.assertEqual(status, 200)
        names = {p["name"]: p for p in body["profiles"]}
        self.assertEqual(sorted(names), ["legacy", "light", "strict"])
        strict = names["strict"]
        self.assertEqual(
            strict["hash"], profiles.semantic_hash(strict["profile"]))
        # The decomposition travels so the new-run form can show it.
        self.assertEqual(strict["profile"]["fuser_discard"], "evidence+concur")

    def test_create_with_profile_snapshots_and_seals(self):
        ws = self.workspace("ws-profiled")
        status, body = self.create_run(ws, profile="light")
        self.assertEqual(status, 201)
        rid = body["run"]["id"]
        # The run config carries the {name, version, hash} snapshot.
        cfg = st.load(driver.default_state_path(ws))["config"]
        ref = cfg["profile_ref"]
        light = profiles.load(self.home, "light")
        self.assertEqual(
            ref,
            {"name": "light", "version": light["version"],
             "hash": profiles.semantic_hash(light["profile"])},
        )
        # The sealed semantic content is embedded too, so the driver can
        # interpret the run self-containedly and its hash matches the ref.
        self.assertEqual(cfg["profile"], light["profile"])
        self.assertEqual(
            profiles.semantic_hash(cfg["profile"]), ref["hash"])
        # First production reference sealed the profile on disk.
        self.assertTrue(light["sealed"])
        # run_detail surfaces the governing profile for the panel.
        status, detail = self.request_json("GET", "/api/runs/%s" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(detail["profile"]["governing"], ref)

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

    def test_post_creates_profile_unsealed(self):
        doc = {"name": "custom", "version": 1, "sealed": False,
               "description": "d", "profile": {"p3_defer_max_risk": "high"}}
        status, body = self.request_json("POST", "/api/profiles", doc)
        self.assertEqual(status, 200)
        self.assertFalse(body["profile"]["sealed"])
        self.assertEqual(
            body["profile"]["hash"], profiles.semantic_hash(doc["profile"]))
        # It now shows up in the listing.
        _, listed = self.request_json("GET", "/api/profiles")
        self.assertIn("custom", {p["name"] for p in listed["profiles"]})

    def test_post_never_seals_even_if_body_asks(self):
        # The save API must not seal — only a run's first reference does.
        doc = {"name": "wannaseal", "version": 1, "sealed": True,
               "description": "d", "profile": {"a": 1}}
        status, body = self.request_json("POST", "/api/profiles", doc)
        self.assertEqual(status, 200)
        self.assertFalse(body["profile"]["sealed"])
        self.assertFalse(profiles.load(self.home, "wannaseal")["sealed"])

    def test_post_rejects_bad_document(self):
        for bad in ({}, {"name": "x y", "version": 1, "profile": {"a": 1}},
                    ["not", "a", "dict"]):
            status, body = self.request_json("POST", "/api/profiles", bad)
            self.assertEqual(status, 400)
            self.assertFalse(body["ok"])

    def test_profile_swap_writes_overlay_and_regoverns(self):
        ws = self.workspace("ws-swap")
        status, body = self.create_run(ws, profile="light")
        self.assertEqual(status, 201)
        rid = body["run"]["id"]
        # Repoint the run at strict.
        status, sw = self.request_json(
            "POST", "/api/runs/%s/profile" % rid, {"profile": "strict"})
        self.assertEqual(status, 200)
        strict = profiles.load(self.home, "strict")
        self.assertEqual(sw["profile_swap"]["ref"]["name"], "strict")
        self.assertTrue(strict["sealed"])  # referencing strict sealed it
        # The overlay file sits beside the state, operator-owned.
        entry = registry.get(registry.load(self.home), rid)
        overlay = os.path.join(
            os.path.dirname(entry["state_path"]), "profile_swap.json")
        self.assertTrue(os.path.isfile(overlay))
        # run_detail now governs by the swap; base is preserved.
        status, detail = self.request_json("GET", "/api/runs/%s" % rid)
        self.assertEqual(detail["profile"]["base"]["name"], "light")
        self.assertEqual(detail["profile"]["governing"]["name"], "strict")
        self.assertEqual(
            detail["profile"]["swap"]["ref"]["hash"],
            profiles.semantic_hash(strict["profile"]))
        # Base config.profile_ref is untouched — swap != edit of the run.
        cfg = st.load(entry["state_path"])["config"]
        self.assertEqual(cfg["profile_ref"]["name"], "light")

    def test_profile_swap_unknown_profile_400(self):
        ws = self.workspace("ws-swap-bad")
        _, body = self.create_run(ws, profile="light")
        rid = body["run"]["id"]
        status, out = self.request_json(
            "POST", "/api/runs/%s/profile" % rid, {"profile": "ghost"})
        self.assertEqual(status, 400)
        self.assertIn("ghost", out["error"])

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

    def test_post_preserves_seal_and_refuses_content_change(self):
        doc = {"name": "frozen", "version": 1, "sealed": False,
               "description": "d", "profile": {"a": 1}}
        self.request_json("POST", "/api/profiles", doc)
        profiles.reference(self.home, "frozen")  # first production use seals it
        # A metadata-only edit still lands.
        meta = dict(doc, description="clearer words")
        status, body = self.request_json("POST", "/api/profiles", meta)
        self.assertEqual(status, 200)
        self.assertTrue(body["profile"]["sealed"])
        self.assertEqual(body["profile"]["description"], "clearer words")
        # A semantic-content change on the sealed profile is refused.
        changed = dict(doc, profile={"a": 2})
        status, body = self.request_json("POST", "/api/profiles", changed)
        self.assertEqual(status, 400)
        self.assertIn("sealed", body["error"])


class ModelProfilesApiTest(ServiceApiTest):
    """Model-profile catalogue API (model-profiles slice 1): the seeded
    `default` is listed from startup, POST is the sole create/edit surface
    with loud validation and no mutation on refusal, stored corruption
    fails the listing instead of shortening it, and the strategy
    `/api/profiles` surface stays untouched."""

    def member_request_json(self, method, path, payload=None):
        """The same request as an authenticated NON-admin member (the
        remote OAuth identity headers a real member request carries)."""
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

    def catalogue_doc(self, name="docs-work"):
        return {
            "name": name,
            "examples": ["internal note", "public API contract"],
            "configurations": {
                "low": {"implementer": {"agent": "claude",
                                        "model": "claude-sonnet-5",
                                        "effort": "medium"}},
                "medium": {"fixer": "codex", "consultation": "opposite"},
                "high": {"review_codex": {"effort": "max"}},
            },
        }

    def test_list_create_edit_and_validation_contract(self):
        # Startup seeded the editable `default`; the listing serves the
        # exact source documents, sorted by name, in the pinned envelope.
        status, body = self.request_json("GET", "/api/model-profiles")
        self.assertEqual(status, 200)
        self.assertIs(body["ok"], True)
        names = [p["name"] for p in body["profiles"]]
        self.assertEqual(names, sorted(names))
        self.assertIn("default", names)
        default = [p for p in body["profiles"] if p["name"] == "default"][0]
        self.assertEqual(default, model_profiles.DEFAULT_SEED)
        self.assertEqual(set(default), {"name", "examples", "configurations"})

        # A case variant is a conflicting catalogue identity, not a second
        # create.  Refuse it before a case-insensitive filesystem can replace
        # the seeded default and make listing/startup fail.
        status, body = self.request_json(
            "POST", "/api/model-profiles", self.catalogue_doc("Default"))
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("case-insensitively unique", body["error"])
        self.assertEqual(model_profiles.load(self.home, "default"),
                         model_profiles.DEFAULT_SEED)
        status, body = self.request_json("GET", "/api/model-profiles")
        self.assertEqual(status, 200)
        self.assertEqual([p["name"] for p in body["profiles"]], ["default"])

        # Create through the sole create/edit operation.
        doc = self.catalogue_doc()
        status, body = self.request_json("POST", "/api/model-profiles", doc)
        self.assertEqual(status, 200)
        self.assertIs(body["ok"], True)
        self.assertEqual(body["profile"], doc)
        prefix_doc = self.catalogue_doc("default-heavy")
        status, body = self.request_json(
            "POST", "/api/model-profiles", prefix_doc)
        self.assertEqual(status, 200)
        self.assertIs(body["ok"], True)
        status, body = self.request_json("GET", "/api/model-profiles")
        self.assertEqual([p["name"] for p in body["profiles"]],
                         ["default", "default-heavy", "docs-work"])

        # A same-name save wholly replaces the definition.
        edited = {
            "name": "docs-work",
            "examples": ["storage migration"],
            "configurations": {
                "low": {},
                "medium": {"drafter": {"agent": "codex", "effort": "low"}},
                "high": {"review_claude": {"effort": "max"}},
            },
        }
        status, body = self.request_json(
            "POST", "/api/model-profiles", edited)
        self.assertEqual(status, 200)
        _, body = self.request_json("GET", "/api/model-profiles")
        stored = [p for p in body["profiles"] if p["name"] == "docs-work"][0]
        self.assertEqual(stored, edited)
        self.assertNotIn("fixer", stored["configurations"]["medium"])

        # Invalid input: pinned 400 envelope, and the prior definition
        # survives byte-identical.
        extra_key = dict(self.catalogue_doc(), version=1)
        missing_rigor = self.catalogue_doc()
        del missing_rigor["configurations"]["high"]
        unknown_act = self.catalogue_doc()
        unknown_act["configurations"]["medium"] = {"delta_review": "codex"}
        dead_agent = self.catalogue_doc()
        dead_agent["configurations"]["medium"] = {
            "review_claude": {"agent": "claude"}}
        dead_consultation = self.catalogue_doc()
        dead_consultation["configurations"]["medium"] = {
            "consultation": {"model": "gpt-5.6-sol"}}
        for bad in (extra_key, missing_rigor, unknown_act, dead_agent,
                    dead_consultation, ["not", "a", "document"]):
            status, body = self.request_json(
                "POST", "/api/model-profiles", bad)
            self.assertEqual(status, 400, body)
            self.assertFalse(body["ok"])
            self.assertTrue(body["error"])
        self.assertEqual(
            model_profiles.load(self.home, "docs-work"), edited)

        # POST is administrative under the existing access posture; the
        # catalogue read stays member-visible like /api/profiles.
        status, body = self.member_request_json("GET", "/api/model-profiles")
        self.assertEqual(status, 200)
        status, body = self.member_request_json(
            "POST", "/api/model-profiles", self.catalogue_doc("member-try"))
        self.assertEqual(status, 403)
        self.assertFalse(body["ok"])
        with self.assertRaises(model_profiles.ModelProfileError):
            model_profiles.load(self.home, "member-try")

        # The seeded default is an ordinary editable profile, and a
        # service restart over the same home never re-seeds over the edit.
        edited_default = json.loads(
            json.dumps(model_profiles.DEFAULT_SEED))
        edited_default["examples"] = ["operator edited clue"]
        status, _ = self.request_json(
            "POST", "/api/model-profiles", edited_default)
        self.assertEqual(status, 200)
        second = service.make_server(self.home, 0)
        thread = threading.Thread(
            target=second.serve_forever, daemon=True)
        thread.start()
        base = self.base
        try:
            self.base = "http://127.0.0.1:%d" % second.server_address[1]
            status, body = self.request_json("GET", "/api/model-profiles")
        finally:
            self.base = base
            second.shutdown()
            second.server_close()
            thread.join(timeout=5)
        self.assertEqual(status, 200)
        restarted = [p for p in body["profiles"]
                     if p["name"] == "default"][0]
        self.assertEqual(restarted["examples"], ["operator edited clue"])

        # A damaged stored definition fails the WHOLE listing loudly with
        # the common 500 envelope — never a silently shortened catalogue.
        corrupt = os.path.join(
            self.home, model_profiles.MODEL_PROFILES_DIRNAME,
            "zz-corrupt.json")
        with open(corrupt, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        status, body = self.request_json("GET", "/api/model-profiles")
        self.assertEqual(status, 500)
        self.assertFalse(body["ok"])
        self.assertTrue(body["error"])
        os.unlink(corrupt)
        status, body = self.request_json("GET", "/api/model-profiles")
        self.assertEqual(status, 200)

        # The strategy-profile surface is untouched by the new catalogue:
        # same names, same envelope keys, and no model profile leaks in.
        status, body = self.request_json("GET", "/api/profiles")
        self.assertEqual(status, 200)
        strategy = {p["name"]: p for p in body["profiles"]}
        self.assertEqual(sorted(strategy), ["legacy", "light", "strict"])
        for entry in strategy.values():
            self.assertEqual(
                set(entry),
                {"name", "version", "sealed", "description", "hash",
                 "profile"})


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
