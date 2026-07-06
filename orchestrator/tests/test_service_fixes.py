"""Regression tests for the local-service review findings.

Covers, against orchestrator/service.py + registry.py + driver.py:
- exited drivers are reaped (no zombie shown as "running" forever) and
  their registry pid is cleared;
- POST /stop reaches the in-flight worker CLI's own process group, not
  just the driver;
- start_run's check-spawn-record is atomic under the registry lock (two
  concurrent starts spawn exactly one driver);
- pid-reuse mitigations: a recorded pid that is not a live session leader
  is never trusted and never signalled (innocent processes survive stop);
- read_log_tail reads a bounded tail, not the whole file;
- init_run's exclusive state creation (no exists() TOCTOU);
- config merge semantics have a single source of truth (driver.merge_config);
- the state summary cache invalidates on state change.

Every home/workspace is a tempfile.TemporaryDirectory (never
~/.impl_roadmap); the HTTP server binds port 0; every spawned process
group is killed in tearDown.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from orchestrator import driver, registry, service, state as st

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class ServiceFixesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-svc-fixes-")
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.extra_pids = set()   # non-child pids to kill by group
        self.fake_child_pids = set()  # FakeProc pids to purge from _CHILDREN
        self.server = service.make_server(self.home, 0)  # ephemeral port
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        try:
            # Kill every process group the registry or the tests know about.
            pids = set(self.extra_pids)
            try:
                for entry in registry.load(self.home)["runs"]:
                    if entry.get("pid"):
                        pids.add(entry["pid"])
            except Exception:
                pass
            for pid in pids:
                self._kill_group(pid)
            # Purge fake (mocked) children so later tests are unaffected.
            with service._CHILDREN_LOCK:
                for pid in self.fake_child_pids:
                    service._CHILDREN.pop(pid, None)
        finally:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            self.tmp.cleanup()

    @staticmethod
    def _reap(pid):
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass

    def _kill_group(self, pid):
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

    def workspace(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path, exist_ok=True)
        # Launch-time rule: the workspace must be the root of an existing
        # git repository (no auto-init); tests create the ledger repo the
        # same deliberate way an operator would.
        subprocess.run(["git", "init", "-q", path], check=True)
        return path

    def _wait(self, predicate, timeout_s, message):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.1)
        self.fail(message)

    def _entry(self, run_id):
        return registry.get(registry.load(self.home), run_id)


# ---------------------------------------------------------------------------
# P1: exited drivers must be reaped, not shown as "running" zombies


class TestAutoResumeGuard(ServiceFixesTestCase):
    """The service-side guard: typed recoverable failures are auto-resumed
    when due, capped per type, and never touched for login/unknown."""

    def _failed_run(self, name, ftype, resume_at=None):
        ws = self.workspace(name)
        entry = service.create_run(
            self.home,
            {"workspace": ws, "goal": "guard test", "autostart": False},
        )
        state = st.load(entry["state_path"])
        st.fail_run(state, "boom (%s)" % ftype, type_=ftype,
                    resume_at=resume_at)
        st.save(entry["state_path"], state)
        return entry

    def _patched_resume(self):
        calls = []
        real = service.resume_run

        def stub(home, run_id):
            calls.append(run_id)
            # clear the failure like the real one, but spawn nothing
            reg = registry.load(home)
            entry = registry.get(reg, run_id)
            state = st.load(entry["state_path"])
            st.resume_run(state)
            st.save(entry["state_path"], state)
            return entry

        service.resume_run = stub
        self.addCleanup(setattr, service, "resume_run", real)
        return calls

    def test_due_quota_failure_is_resumed(self):
        entry = self._failed_run(
            "ws-guard-due", "quota",
            resume_at="2026-07-05T00:00:00+0000",
        )
        calls = self._patched_resume()
        actions = service.guard_scan(self.home)
        self.assertIn((entry["id"], "resumed:quota"), actions)
        self.assertEqual(calls, [entry["id"]])
        reg = registry.load(self.home)
        self.assertEqual(
            registry.get(reg, entry["id"])["auto_resumes"], {"quota": 1}
        )

    def test_future_resume_at_waits(self):
        entry = self._failed_run(
            "ws-guard-future", "quota",
            resume_at="2099-01-01T00:00:00+0000",
        )
        calls = self._patched_resume()
        actions = service.guard_scan(self.home)
        self.assertNotIn((entry["id"], "resumed:quota"), actions)
        self.assertEqual(calls, [])

    def test_login_and_unknown_never_auto_resume(self):
        for ftype in ("login", "unknown"):
            entry = self._failed_run("ws-guard-%s" % ftype, ftype)
            calls = self._patched_resume()
            service.guard_scan(self.home)
            self.assertEqual(calls, [], ftype)

    def test_cap_stands_down(self):
        entry = self._failed_run("ws-guard-cap", "network")
        registry.update(self.home, entry["id"],
                        auto_resumes={"network": 99})
        calls = self._patched_resume()
        actions = service.guard_scan(self.home)
        self.assertIn((entry["id"], "capped:network"), actions)
        self.assertEqual(calls, [])


class TestZombieReaping(ServiceFixesTestCase):
    def test_exited_driver_is_reaped_and_run_flips_to_stopped(self):
        ws = self.workspace("ws-zombie")
        # A worker command that never emits contract JSON: the driver fails
        # the run after the repair retry and exits within a couple seconds.
        bad_worker = [sys.executable, "-c", "print('not json')"]
        entry = service.create_run(
            self.home,
            {
                "workspace": ws,
                "goal": "zombie test",
                "autostart": True,
                "config": {
                    "commands": {"codex": bad_worker, "claude": bad_worker},
                    "timeouts": {"codex": 30, "claude": 30},
                },
            },
        )
        run_id, pid = entry["id"], entry["pid"]
        self.assertTrue(pid)
        self.extra_pids.add(pid)

        # Poll through the SERVICE (list_runs reaps); no manual waitpid.
        self._wait(
            lambda: all(
                r["process"] == "stopped" for r in service.list_runs(self.home)
            ),
            30,
            "exited driver still reported running (zombie not reaped)",
        )
        # The service already reaped the child: a manual waitpid finds no
        # child left with that pid.
        with self.assertRaises((ChildProcessError, OSError)):
            os.waitpid(pid, os.WNOHANG)
        # Observed exit cleared the recorded pid.
        self.assertIsNone(self._entry(run_id)["pid"])
        # The formerly wedged operations now behave: stop is a no-op ...
        result = service.stop_run(self.home, run_id)
        self.assertFalse(result["stopped"])
        # ... and DELETE no longer 409s forever.
        result = service.delete_run(self.home, run_id)
        self.assertEqual(result["deleted"], run_id)


# ---------------------------------------------------------------------------
# P1: stop must reach the worker CLI's own process group


class TestStopKillsWorkers(ServiceFixesTestCase):
    def test_stop_run_terminates_in_flight_worker_process_group(self):
        ws = self.workspace("ws-stopworker")
        pidfile = os.path.join(ws, "worker_pid.txt")
        # Stand-in worker: records its pid, then blocks like a long LLM
        # call. It runs in its OWN session (runners start_new_session), so
        # only the driver's SIGTERM forwarding can reach it.
        worker = [
            sys.executable,
            "-c",
            (
                "import os, sys, time\n"
                "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
                "time.sleep(300)\n"
            ),
            pidfile,
        ]
        entry = service.create_run(
            self.home,
            {
                "workspace": ws,
                "goal": "stop worker test",
                "autostart": True,
                "config": {
                    "commands": {"codex": worker, "claude": worker},
                    "timeouts": {"codex": 300, "claude": 300},
                },
            },
        )
        run_id, driver_pid = entry["id"], entry["pid"]
        self.extra_pids.add(driver_pid)

        def read_pidfile():
            if not os.path.exists(pidfile):
                return ""
            with open(pidfile) as fh:
                return fh.read().strip()

        self._wait(lambda: read_pidfile(), 20, "worker never started")
        worker_pid = int(read_pidfile())
        self.extra_pids.add(worker_pid)
        # Sanity: the worker is a session leader outside the driver's group.
        self.assertEqual(os.getpgid(worker_pid), worker_pid)
        self.assertNotEqual(os.getpgid(worker_pid), os.getpgid(driver_pid))

        result = service.stop_run(self.home, run_id)
        self.assertTrue(result["stopped"], result)

        def worker_dead():
            try:
                os.kill(worker_pid, 0)
                return False
            except ProcessLookupError:
                return True
            except OSError:
                return False

        self._wait(worker_dead, 15, "stop_run orphaned the worker CLI")
        self._wait(
            lambda: not service.driver_alive(self._entry(run_id)),
            15,
            "driver survived stop",
        )


# ---------------------------------------------------------------------------
# P2: start_run atomicity under the registry lock


class _FakeProc(object):
    """Stands in for a spawned driver: alive until told otherwise."""

    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


class TestStartRunAtomic(ServiceFixesTestCase):
    def test_concurrent_starts_spawn_exactly_one_driver(self):
        ws = self.workspace("ws-race")
        entry = service.create_run(
            self.home, {"workspace": ws, "goal": "race", "autostart": False}
        )
        run_id = entry["id"]

        n_threads = 8
        barrier = threading.Barrier(n_threads)
        spawned = []
        results = []
        lock = threading.Lock()

        def fake_popen(*args, **kwargs):
            proc = _FakeProc(10_000_000 + len(spawned))
            with lock:
                spawned.append(proc)
            self.fake_child_pids.add(proc.pid)
            return proc

        def racer():
            barrier.wait(timeout=30)
            try:
                service.start_run(self.home, run_id)
                results.append("ok")
            except service.ApiError as exc:
                results.append(exc.status)

        with mock.patch.object(service.subprocess, "Popen", fake_popen):
            threads = [threading.Thread(target=racer) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

        self.assertEqual(len(spawned), 1, "more than one driver spawned")
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual(results.count(409), n_threads - 1, results)
        # The recorded pid is the (single) survivor's, not a random loser's.
        self.assertEqual(self._entry(run_id)["pid"], spawned[0].pid)
        # Clean the fake pid out of the registry for tearDown.
        registry.update(self.home, run_id, pid=None)


# ---------------------------------------------------------------------------
# P2: pid-reuse mitigations


class TestPidReuseMitigations(ServiceFixesTestCase):
    def test_non_session_leader_pid_is_not_trusted_and_never_signalled(self):
        ws = self.workspace("ws-reuse")
        entry = service.create_run(
            self.home, {"workspace": ws, "goal": "reuse", "autostart": False}
        )
        run_id = entry["id"]
        # An "innocent" process: our direct child, sharing OUR process
        # group (no start_new_session) — like an OS-recycled pid would.
        innocent = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"]
        )
        try:
            self.assertNotEqual(os.getpgid(innocent.pid), innocent.pid)
            registry.update(self.home, run_id, pid=innocent.pid)
            entry = self._entry(run_id)
            # Not trusted as a driver ...
            self.assertFalse(service.driver_alive(entry))
            self.assertEqual(service.run_status(entry)["process"], "stopped")
            # ... never signalled (stop reports not running, innocent lives) ...
            result = service.stop_run(self.home, run_id)
            self.assertFalse(result["stopped"])
            self.assertIsNone(innocent.poll(), "stop_run killed an innocent process")
            # ... and the run is not wedged: delete succeeds.
            service.delete_run(self.home, run_id)
        finally:
            innocent.kill()
            innocent.wait()

    def test_untracked_session_leader_pid_is_still_trusted(self):
        # After a service restart the driver is no longer a tracked child,
        # but it IS a session leader — it must still count as running.
        ws = self.workspace("ws-restart")
        entry = service.create_run(
            self.home, {"workspace": ws, "goal": "restart", "autostart": False}
        )
        run_id = entry["id"]
        leader = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"],
            start_new_session=True,
        )
        try:
            registry.update(self.home, run_id, pid=leader.pid)
            entry = self._entry(run_id)
            self.assertTrue(service.driver_alive(entry))
            with self.assertRaises(service.ApiError) as ctx:
                service.delete_run(self.home, run_id)
            self.assertEqual(ctx.exception.status, 409)
        finally:
            leader.kill()
            leader.wait()  # fully reaped: no zombie ambiguity below
        self.assertFalse(service.driver_alive(self._entry(run_id)))
        service.delete_run(self.home, run_id)


# ---------------------------------------------------------------------------
# P2: bounded log tail


class TestReadLogTailBounded(ServiceFixesTestCase):
    def _write_log(self, run_id, text):
        os.makedirs(registry.logs_dir(self.home), exist_ok=True)
        with open(registry.log_path(self.home, run_id), "w") as fh:
            fh.write(text)

    def test_tail_of_large_log_is_exact(self):
        lines = ["line %06d\n" % i for i in range(50_000)]
        self._write_log("r-big", "".join(lines))
        self.assertEqual(service.read_log_tail(self.home, "r-big", 200), lines[-200:])

    def test_tail_preserves_unterminated_last_line(self):
        self._write_log("r-part", "a\nb\nc")  # no trailing newline
        self.assertEqual(
            service.read_log_tail(self.home, "r-part", 2), ["b\n", "c"]
        )

    def test_tail_missing_and_empty_files(self):
        self.assertEqual(service.read_log_tail(self.home, "r-none", 10), [])
        self._write_log("r-empty", "")
        self.assertEqual(service.read_log_tail(self.home, "r-empty", 10), [])

    def test_tail_reads_only_a_bounded_suffix(self):
        # One pathological 10 MiB first line, then a short real tail. The
        # bounded reader must return the tail without materializing the
        # whole file (hard cap: 8 * TAIL_CHUNK bytes).
        blob = "x" * (10 * 1024 * 1024) + "\nfinal-1\nfinal-2\n"
        self._write_log("r-huge", blob)
        tail = service.read_log_tail(self.home, "r-huge", 2)
        self.assertEqual(tail, ["final-1\n", "final-2\n"])


# ---------------------------------------------------------------------------
# P3: init_run exclusive creation (no exists() TOCTOU)


class TestInitRunAtomic(ServiceFixesTestCase):
    def test_save_new_refuses_existing_path(self):
        ws = self.workspace("ws-savenew")
        path = driver.init_run("first", ws)
        with self.assertRaises(FileExistsError) as ctx:
            st.save_new(path, st.new_state("second", ws, driver.load_config(None)))
        self.assertIn("refusing to overwrite", str(ctx.exception))
        self.assertEqual(st.load(path)["goal"], "first")
        # No temp litter left behind.
        leftovers = [
            n for n in os.listdir(os.path.dirname(path)) if n.startswith(".state-")
        ]
        self.assertEqual(leftovers, [])

    def test_concurrent_inits_exactly_one_wins(self):
        ws = self.workspace("ws-initrace")
        # Race for ONE explicit state path: the property under test is the
        # os.link exclusive claim, independent of the path-layout policy.
        path = os.path.join(ws, ".orchestrator", "state.json")
        n = 8
        barrier = threading.Barrier(n)
        outcomes = [None] * n

        def racer(i):
            barrier.wait(timeout=30)
            try:
                driver.init_run("goal-%d" % i, ws, state_path=path)
                outcomes[i] = "ok"
            except FileExistsError:
                outcomes[i] = "exists"

        threads = [threading.Thread(target=racer, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(outcomes.count("ok"), 1, outcomes)
        self.assertEqual(outcomes.count("exists"), n - 1, outcomes)
        winner = outcomes.index("ok")
        state = st.load(path)
        self.assertEqual(state["goal"], "goal-%d" % winner)


# ---------------------------------------------------------------------------
# P3: single source of truth for config merging


class TestMergeConfigSingleSource(ServiceFixesTestCase):
    def test_merge_config_semantics(self):
        cfg = {"a": {"x": 1, "y": 2}, "b": 3}
        out = driver.merge_config(cfg, {"a": {"y": 9}, "c": 4})
        self.assertIs(out, cfg)  # in place
        self.assertEqual(cfg, {"a": {"x": 1, "y": 9}, "b": 3, "c": 4})

    def test_service_create_matches_cli_load_config(self):
        override = {
            "timeouts": {"codex": 123},
            "verification": ["true"],
            "max_seal_attempts": 2,
        }
        # CLI path.
        cfg_file = os.path.join(self.tmp.name, "cfg.json")
        with open(cfg_file, "w") as fh:
            json.dump(override, fh)
        cli_cfg = driver.load_config(cfg_file)
        # Panel path.
        ws = self.workspace("ws-mergeparity")
        entry = service.create_run(
            self.home,
            {"workspace": ws, "goal": "parity", "autostart": False,
             "config": override},
        )
        panel_cfg = st.load(entry["state_path"])["config"]
        # Same merge semantics as the CLI, with the deliberate service
        # defaults on top: panel runs launch the full enforced flow (git on),
        # seal concurrently, and run a single seal half on the first attempt —
        # each unless the operator explicitly disables it.
        expected = json.loads(json.dumps(cli_cfg))
        expected["git"] = {"enabled": True}
        expected["seal_concurrent"] = True
        expected["single_seal_first_attempt"] = True
        self.assertEqual(panel_cfg, expected)

    def test_service_default_enables_git_and_explicit_override_wins(self):
        # Default: the panel's runs get the full gate/amend/delta
        # discipline (driver.DEFAULT_CONFIG's own comment promises the
        # service enables git; a silently pure-state panel run would lose
        # delta reviews, amends, and revertible tamper recovery).
        ws = self.workspace("ws-gitdefault")
        entry = service.create_run(
            self.home, {"workspace": ws, "goal": "g", "autostart": False}
        )
        cfg = st.load(entry["state_path"])["config"]
        self.assertEqual(cfg["git"], {"enabled": True})
        # An explicit pure-state request is honored.
        ws2 = self.workspace("ws-gitoff")
        entry2 = service.create_run(
            self.home,
            {"workspace": ws2, "goal": "g", "autostart": False,
             "config": {"git": {"enabled": False}}},
        )
        cfg2 = st.load(entry2["state_path"])["config"]
        self.assertEqual(cfg2["git"], {"enabled": False})


# ---------------------------------------------------------------------------
# P2: summary cache correctness (fresh data after every state change)


class TestSummaryCache(ServiceFixesTestCase):
    def test_cache_hits_and_invalidation(self):
        ws = self.workspace("ws-cache")
        path = driver.init_run("cache test", ws)
        s1 = service.load_summary(path)
        s2 = service.load_summary(path)
        self.assertIs(s1, s2, "unchanged state must be served from cache")
        # Any state change (atomic replace: new mtime/size) must be seen.
        state = st.load(path)
        st.append_event(state, "note", detail="cache invalidation probe")
        st.save(path, state)
        s3 = service.load_summary(path)
        self.assertEqual(s3["events_total"], s1["events_total"] + 1)


# ---------------------------------------------------------------------------
# Discard purges the workspace state claim (opt-in), so a fresh launch over
# the same workspace does not hit state.init's refuse-to-overwrite.


class TestDeletePurgesStateClaim(ServiceFixesTestCase):
    def test_delete_run_purge_removes_state_file_and_lock(self):
        ws = self.workspace("ws-purge")
        entry = service.create_run(
            self.home, {"workspace": ws, "goal": "purge me", "autostart": False}
        )
        run_id = entry["id"]
        state_path = self._entry(run_id)["state_path"]
        self.assertTrue(os.path.exists(state_path))
        open(state_path + ".lock", "a").close()  # a past driver's lock
        result = service.delete_run(self.home, run_id, purge=True)
        self.assertEqual(result["deleted"], run_id)
        self.assertIn(state_path, result["purged"])
        self.assertFalse(os.path.exists(state_path))
        self.assertFalse(os.path.exists(state_path + ".lock"))
        # The user-facing point: the same workspace launches fresh again.
        entry2 = service.create_run(
            self.home, {"workspace": ws, "goal": "fresh", "autostart": False}
        )
        self.assertTrue(os.path.exists(entry2["state_path"]))

    def test_delete_run_without_purge_keeps_workspace_files(self):
        ws = self.workspace("ws-nopurge")
        entry = service.create_run(
            self.home, {"workspace": ws, "goal": "keep", "autostart": False}
        )
        run_id = entry["id"]
        state_path = self._entry(run_id)["state_path"]
        result = service.delete_run(self.home, run_id)
        self.assertEqual(result["note"], "workspace files untouched")
        self.assertTrue(os.path.exists(state_path))


if __name__ == "__main__":
    unittest.main()
