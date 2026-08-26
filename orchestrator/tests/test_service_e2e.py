"""Service e2e: the full panel lifecycle with REAL detached driver processes.

Starts the local-service HTTP server in a thread over a temporary --home,
then exercises the JSON API exactly like the panel does: POST /api/runs with
the fake-LLM calculator config (the same scenario as run_demo.sh: deliberate
div bug, a first-family review finding whose scripted fix also corrects that
bug, and a second-family review finding -> fix episode -> clean restart -> one
final suite), poll until the milestone closes, then stop/forget. Service
launches enable git by
default (the panel promises the FULL enforced flow), so like the demo this
run exercises delta reviews, amends, and gate commits — inside the
tempdir workspace only.

The spawned driver is a real detached subprocess (`python3 -m
orchestrator.driver run`) launched by service.start_run. Because the server
runs in-process here, that driver is a direct child of the test process.
The service itself keeps the Popen and reaps exited drivers (clearing the
registry pid) on every API call; the test's own waitpid(WNOHANG) while
polling pid_alive is a belt-and-braces safety net, since a zombie child
would still pass the raw os.kill(pid, 0) probe.

Never touches ~/.impl_roadmap; everything lives in TemporaryDirectory.
"""

import json
import os
import subprocess
import signal
import threading
import time
import tempfile
import unittest
import urllib.error
import urllib.request

from orchestrator import registry, service, state as st

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FAKE_LLM = os.path.join(
    REPO, "orchestrator", "examples", "calculator", "fake_llm.py"
)
GOAL = "Build a small CLI calculator (add/sub/mul/div) with unit tests"

POLL_INTERVAL_S = 0.5
CLOSE_BUDGET_S = 60.0
EXIT_BUDGET_S = 30.0


class TestServicePanelE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-svc-e2e-")
        self.home = os.path.join(self.tmp.name, "home")
        self.work = os.path.join(self.tmp.name, "work")
        os.makedirs(self.home)
        os.makedirs(self.work)
        subprocess.run(["git", "init", "-q", self.work], check=True)
        self.spawned_pids = set()
        self.server = service.make_server(self.home, 0)  # ephemeral port
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        try:
            for pid in self.spawned_pids:
                self._kill_process_group(pid)
        finally:
            server = getattr(self, "server", None)
            if server is not None:
                server.shutdown()
                server.server_close()
            thread = getattr(self, "thread", None)
            if thread is not None:
                thread.join(timeout=5)
            self.tmp.cleanup()

    # -- process helpers -----------------------------------------------------

    @staticmethod
    def _reap(pid):
        """Reap the pid if it is an exited child of this process (the
        in-thread server spawns drivers as our children); without this a
        zombie keeps registry.pid_alive() True forever."""
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass

    def _kill_process_group(self, pid):
        self._reap(pid)
        if not registry.pid_alive(pid):
            return
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self._reap(pid)
            if not registry.pid_alive(pid):
                return
            time.sleep(0.05)

    def _wait_pid_exit(self, pid):
        deadline = time.monotonic() + EXIT_BUDGET_S
        while time.monotonic() < deadline:
            self._reap(pid)
            if not registry.pid_alive(pid):
                return
            time.sleep(0.2)
        self.fail(
            "driver pid %d still alive %ds after the milestone closed"
            % (pid, EXIT_BUDGET_S)
        )

    # -- HTTP helpers ----------------------------------------------------------

    def _request(self, method, path, payload=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = {"raw": body}
            return exc.code, parsed

    def _config(self):
        return {
            "commands": {
                "codex": [
                    "python3", FAKE_LLM, "--workspace", "{workspace}",
                    "--family", "codex",
                ],
                "claude": [
                    "python3", FAKE_LLM, "--workspace", "{workspace}",
                    "--family", "claude",
                ],
            },
            "timeouts": {"codex": 60, "claude": 60},
            # The skeleton defaults to claude/opus-5/max in real runs; in this
            # fake-CLI scenario keep it on codex (the fake claude only scripts
            # review work, not skeleton drafting/fixing).
            "acts": {"skeletoner": "codex"},
            "verification": ["python3 run_checks.py"],
            # The calculator fake writes its canonical artifacts under docs/.
            "docs_dir": "docs",
            "guarantee_calibration": {"enabled": False},
        }

    def _create_run(self, autostart):
        status, body = self._request(
            "POST",
            "/api/runs",
            {
                "workspace": self.work,
                "goal": GOAL,
                "autostart": autostart,
                "config": self._config(),
            },
        )
        self.assertEqual(status, 201, "create failed: %r" % (body,))
        self.assertTrue(body.get("ok"), body)
        run = body["run"]
        if run.get("pid"):
            self.spawned_pids.add(run["pid"])
        return run

    def _log_text(self, run_id):
        status, body = self._request("GET", "/api/runs/%s/log" % run_id)
        self.assertEqual(status, 200, body)
        return "".join(body.get("lines", []))

    def _wait_closed(self, run_id):
        """Poll run detail until the milestone closes; fail loudly on
        'failed' with the recorded reason and the driver log."""
        deadline = time.monotonic() + CLOSE_BUDGET_S
        detail = None
        while time.monotonic() < deadline:
            status, detail = self._request("GET", "/api/runs/%s" % run_id)
            self.assertEqual(status, 200, detail)
            pid = (detail.get("entry") or {}).get("pid")
            if pid:
                self.spawned_pids.add(pid)
            milestone = detail["status"]["milestone_status"]
            if milestone == "closed":
                return detail
            if milestone == "failed":
                self.fail(
                    "run failed: %r\ndriver log:\n%s"
                    % (detail["status"]["failure_reason"], self._log_text(run_id))
                )
            time.sleep(POLL_INTERVAL_S)
        self.fail(
            "milestone not closed within %ds; last status=%r\ndriver log:\n%s"
            % (
                CLOSE_BUDGET_S,
                (detail or {}).get("status"),
                self._log_text(run_id),
            )
        )

    # -- shared assertions -----------------------------------------------------

    def _find_unit(self, summary, key):
        for unit in summary["units"]:
            if unit["unit"] == key:
                return unit
        self.fail("unit %s not in summary: %r" % (key, summary["units"]))

    def _assert_closed_outcome(self, run_id, detail):
        summary = detail.get("summary")
        self.assertIsNotNone(
            summary, "no state summary in detail: %r" % (detail,)
        )
        self.assertEqual(summary["milestone_status"], "closed")
        self.assertIsNone(summary["failure"])
        self.assertEqual(
            [(u["unit"], u["status"]) for u in summary["units"]],
            [
                ("skeleton", "sealed"),
                ("slice_doc-01", "sealed"),
                ("slice_impl-01", "sealed"),
            ],
        )
        impl = self._find_unit(summary, "slice_impl-01")
        self.assertEqual(
            [(s["attempt"], s["passed"]) for s in impl["seals"]],
            [(1, True)],
            "impl seals: %r" % (impl["seals"],),
        )
        impl_kinds = [r["kind"] for r in impl["rounds"]]
        # Implementation now opens with ordinary review work: no full suite
        # is inserted after implement or between review/fix cycles.
        self.assertEqual(
            impl_kinds[0], "review_round",
            "implementation did not enter reviews directly: %r"
            % (impl["rounds"],),
        )
        self.assertIn(
            "review_round", impl_kinds,
            "no review rounds on impl: %r" % (impl["rounds"],),
        )
        # Claude's missing-README finding forces another fix episode after
        # codex was clean. Accepted byte changes restart the whole review
        # cycle; with git enabled every fix is followed by a delta review.
        self.assertEqual(
            impl_kinds[-4:],
            ["fix_findings", "delta_review", "review_round", "review_round"],
            "expected the README fix followed by a complete clean review "
            "restart: %r" % (impl["rounds"],),
        )
        final_reviews = [
            round_["id"]
            for round_ in impl["rounds"]
            if round_["kind"] == "review_round" and not round_["findings"]
        ][-2:]
        self.assertEqual(impl["seals"][0]["reviews"], final_reviews)

        # There is no pre-implementation baseline. The one logical slice is
        # also the milestone end, so its suite runs after the last clean review.
        state = st.load(detail["entry"]["state_path"])
        events = state["events"]
        verifications = [
            e for e in events
            if e["type"] == "verification" and e["unit"] == "slice_impl-01"
        ]
        self.assertEqual(
            [e["boundary"] for e in verifications], ["final"]
        )
        self.assertEqual(verifications[0]["cadence"], "milestone_final")
        self.assertFalse(verifications[0].get("reused", False))
        self.assertTrue(all(e["ok"] for e in verifications))
        self.assertTrue(all(
            not str(r.get("source_round_id") or "").startswith(
                "slice_impl-01-verify-"
            )
            for r in next(
                u for u in state["units"]
                if st.unit_key(u) == "slice_impl-01"
            )["rounds"]
            if r["kind"] == "fix_findings"
        ))
        last_review_seq = max(
            e["seq"] for e in events
            if e["type"] == "round_recorded"
            and e.get("unit") == "slice_impl-01"
            and e.get("kind") == "review_round"
        )
        self.assertGreater(verifications[-1]["seq"], last_review_seq)
        # The run list shows the same closed run.
        status, body = self._request("GET", "/api/runs")
        self.assertEqual(status, 200, body)
        listed = [r for r in body["runs"] if r["id"] == run_id]
        self.assertEqual(len(listed), 1, body)
        self.assertEqual(listed[0]["milestone_status"], "closed")
        self.assertIsNone(listed[0]["failure_reason"])

    def _assert_exit_stop_delete(self, run_id, pid):
        self.assertTrue(pid, "no driver pid recorded for run %s" % run_id)
        self._wait_pid_exit(pid)
        # Process has exited and been reaped: its output is fully flushed.
        self.assertIn("milestone closed", self._log_text(run_id))
        status, body = self._request("POST", "/api/runs/%s/stop" % run_id)
        self.assertEqual(status, 200, body)
        self.assertIs(body["stopped"], False, body)
        status, body = self._request("DELETE", "/api/runs/%s" % run_id)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["deleted"], run_id)
        status, body = self._request("GET", "/api/runs")
        self.assertEqual(status, 200, body)
        self.assertEqual(
            [r for r in body["runs"] if r["id"] == run_id], [],
            "run still listed after DELETE",
        )

    # -- tests -------------------------------------------------------------------

    def test_autostart_lifecycle_closes_then_stop_and_forget(self):
        # The pid is captured at spawn time: once the driver exits, the
        # service reaps it and clears the entry's pid, so the entry field
        # observed at close time may already be None.
        run = self._create_run(autostart=True)
        pid = run["pid"]
        detail = self._wait_closed(run["id"])
        self._assert_closed_outcome(run["id"], detail)
        self._assert_exit_stop_delete(run["id"], pid)

    def test_manual_start_reaches_same_closed_outcome(self):
        run = self._create_run(autostart=False)
        self.assertEqual(run["process"], "stopped")
        self.assertIsNone(run["pid"])
        self.assertEqual(run["milestone_status"], "open")
        status, body = self._request("POST", "/api/runs/%s/start" % run["id"])
        self.assertEqual(status, 200, "start failed: %r" % (body,))
        started = body["run"]
        if started.get("pid"):
            self.spawned_pids.add(started["pid"])
        detail = self._wait_closed(run["id"])
        self._assert_closed_outcome(run["id"], detail)
        self._assert_exit_stop_delete(run["id"], started["pid"])


if __name__ == "__main__":
    unittest.main()
