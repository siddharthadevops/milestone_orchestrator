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

from orchestrator import driver, profiles, registry, service, state as st


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
        self.assertIn("impl roadmap", text)
        self.assertIn('id="runs"', text)

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

    def test_service_forces_seal_defaults_on(self):
        # Live runs seal concurrently and single-half on the first attempt.
        ws = self.workspace("ws-seal-defaults")
        status, _ = self.create_run(ws)
        self.assertEqual(status, 201)
        cfg = st.load(driver.default_state_path(ws))["config"]
        self.assertTrue(cfg["seal_concurrent"])
        self.assertTrue(cfg["single_seal_first_attempt"])

    def test_service_seal_defaults_overridable(self):
        # An explicit advanced-config value still wins over the forced default.
        ws = self.workspace("ws-seal-override")
        status, _ = self.create_run(
            ws, config={"single_seal_first_attempt": False,
                        "seal_concurrent": False})
        self.assertEqual(status, 201)
        cfg = st.load(driver.default_state_path(ws))["config"]
        self.assertFalse(cfg["single_seal_first_attempt"])
        self.assertFalse(cfg["seal_concurrent"])

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
            {"config": {"max_seal_attempts": 999}},
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
        self.assertIsInstance(detail["log"], list)
        status, body = self.request_json("GET", "/api/runs/nope-id")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

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
             "fixer": "codex",
             "drafter": None})
        self.assertEqual(status, 200)
        self.assertEqual(body["acts"]["implementer"]["model"], "sonnet")
        self.assertNotIn("drafter", body["acts"])
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
            "POST", "/api/runs/%s/acts" % rid, {"fixer": {"model": "x" * 200}})
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
        unit["seals"].append({
            "attempt": 1, "passed": True, "invalidated": None,
            "at": "2026-07-05T11:00:00+0200",
            "halves": {"codex": {"result": {"findings": []},
                                 "duration_s": 60.0,
                                 "raw_path": "raw/s1.txt",
                                 "workspace_modified": False}},
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
        })
        st.save(entry["state_path"], state)
        return rid

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
        self.assertIn("codex", body["halves"])
        status, body = self.request_json(
            "GET", "/api/runs/%s/story?item=draft:skeleton" % rid)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["artifact"], "docs/skeleton.md")

    def test_debt_story_and_summary_expose_deferred_p3(self):
        # The reclassify leaves no round, so the panel needs the deferred P3
        # both as a summary chip and a clickable story.
        ws = self.workspace("ws-debt")
        rid = self._seed(ws)
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
        self.assertEqual(body["reclassify"][0]["drift_risk"], "low")
        self.assertEqual(body["reclassify"][0]["threshold"], "low")

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
