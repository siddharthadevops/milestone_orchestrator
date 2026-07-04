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

from orchestrator import driver, registry, service, state as st


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
        return path

    def create_run(self, ws, **extra):
        payload = {"workspace": ws, "goal": "Test goal", "autostart": False}
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

    def test_create_same_workspace_twice_409(self):
        ws = self.workspace("ws-dupe")
        status, _ = self.create_run(ws)
        self.assertEqual(status, 201)
        status, body = self.create_run(ws)
        self.assertEqual(status, 409)
        self.assertIn("attach", body["error"])

    def test_attach_adopts_existing_state_once(self):
        ws = self.workspace("ws-attach")
        driver.init_run("adopted goal", ws)
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
        driver.init_run("ORIGINAL GOAL", ws)
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


if __name__ == "__main__":
    unittest.main()
