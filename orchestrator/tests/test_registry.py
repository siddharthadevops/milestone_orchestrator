"""Tests for orchestrator/registry.py: the local-service run registry.

Covers: load on a missing file, save/load round-trip, atomic saves (the
registry file is always valid JSON, even when a save fails mid-write),
schema_version enforcement, add/update/remove/get semantics, run-id
generation, pid liveness checks, and the advisory lock serializing
concurrent read-modify-write cycles from threads and separate processes.

Standard library only; every home directory is a tempfile.TemporaryDirectory
(never ~/.impl_roadmap). No servers are started and no drivers are spawned;
the only child processes are tiny `python3 -c` helpers that are waited on
(and killed in tearDown if a wait somehow did not happen).
"""

import glob
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

from orchestrator import registry

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def make_entry(run_id, home="unused", suffix=None):
    """A registry entry with distinct workspace/state_path per run id."""
    tag = suffix if suffix is not None else run_id
    workspace = os.path.join(home, "ws-%s" % tag)
    return registry.new_entry(
        run_id,
        "name-%s" % tag,
        workspace,
        os.path.join(workspace, ".orchestrator", "state.json"),
    )


class RegistryTestCase(unittest.TestCase):
    """Base: fresh temp home per test; defensive child-process cleanup."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="orch-registry-test-")
        self.home = self._tmp.name
        self.procs = []

    def tearDown(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# load / save


class TestLoadSave(RegistryTestCase):
    def test_load_missing_file_returns_empty_registry(self):
        self.assertFalse(os.path.exists(registry.registry_path(self.home)))
        reg = registry.load(self.home)
        self.assertEqual(
            reg, {"schema_version": registry.SCHEMA_VERSION, "runs": []}
        )
        # Loading must not create the file as a side effect.
        self.assertFalse(os.path.exists(registry.registry_path(self.home)))

    def test_save_load_round_trip(self):
        reg = {"schema_version": registry.SCHEMA_VERSION, "runs": []}
        reg["runs"].append(make_entry("r-20260101-000000-aaaaaa", self.home))
        reg["runs"].append(make_entry("r-20260101-000001-bbbbbb", self.home))
        registry.save(self.home, reg)
        self.assertEqual(registry.load(self.home), reg)

    def test_save_creates_home_directory(self):
        home = os.path.join(self.home, "does", "not", "exist", "yet")
        reg = {"schema_version": registry.SCHEMA_VERSION, "runs": []}
        registry.save(home, reg)
        self.assertEqual(registry.load(home), reg)

    def test_saved_file_is_directly_parseable_json(self):
        reg = {"schema_version": registry.SCHEMA_VERSION, "runs": []}
        registry.save(self.home, reg)
        with open(registry.registry_path(self.home), "r", encoding="utf-8") as fh:
            raw = fh.read()
        self.assertEqual(json.loads(raw), reg)

    def test_schema_version_mismatch_raises_runtime_error(self):
        os.makedirs(self.home, exist_ok=True)
        with open(registry.registry_path(self.home), "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 999, "runs": []}, fh)
        with self.assertRaises(RuntimeError):
            registry.load(self.home)

    def test_missing_schema_version_raises_runtime_error(self):
        os.makedirs(self.home, exist_ok=True)
        with open(registry.registry_path(self.home), "w", encoding="utf-8") as fh:
            json.dump({"runs": []}, fh)
        with self.assertRaises(RuntimeError):
            registry.load(self.home)

    def test_failed_save_leaves_previous_file_intact(self):
        good = {"schema_version": registry.SCHEMA_VERSION, "runs": []}
        good["runs"].append(make_entry("r-20260101-000000-aaaaaa", self.home))
        registry.save(self.home, good)

        # json.dump writes incrementally, so a non-serializable payload
        # fails mid-write; the atomic temp+rename scheme must never let the
        # partial output reach registry.json, and must clean up the temp.
        bad = {"schema_version": registry.SCHEMA_VERSION, "runs": [object()]}
        with self.assertRaises(TypeError):
            registry.save(self.home, bad)

        self.assertEqual(registry.load(self.home), good)
        leftovers = glob.glob(os.path.join(self.home, ".registry-*"))
        self.assertEqual(leftovers, [])


# ---------------------------------------------------------------------------
# add / update / remove / get


class TestEntryOperations(RegistryTestCase):
    def test_new_entry_shape(self):
        entry = registry.new_entry(
            "r-x", "my milestone", "/ws", "/ws/.orchestrator/state.json",
            goal_doc="/docs/goal.md",
        )
        self.assertEqual(entry["id"], "r-x")
        self.assertEqual(entry["name"], "my milestone")
        self.assertEqual(entry["workspace"], "/ws")
        self.assertEqual(entry["state_path"], "/ws/.orchestrator/state.json")
        self.assertEqual(entry["goal_doc"], "/docs/goal.md")
        self.assertIsNone(entry["pid"])
        self.assertIsNone(entry["last_spawn_at"])
        self.assertTrue(entry["created_at"])

    def test_add_appends_entry(self):
        first = make_entry("r-1", self.home)
        second = make_entry("r-2", self.home)
        registry.add(self.home, first)
        returned = registry.add(self.home, second)
        self.assertEqual(returned, second)
        reg = registry.load(self.home)
        self.assertEqual([e["id"] for e in reg["runs"]], ["r-1", "r-2"])
        self.assertEqual(reg["runs"][1], second)

    def test_add_duplicate_id_raises_value_error(self):
        registry.add(self.home, make_entry("r-1", self.home, suffix="a"))
        with self.assertRaises(ValueError):
            registry.add(self.home, make_entry("r-1", self.home, suffix="b"))
        # Failed add must not have modified the registry.
        self.assertEqual(len(registry.load(self.home)["runs"]), 1)

    def test_add_duplicate_state_path_raises_value_error(self):
        first = make_entry("r-1", self.home)
        registry.add(self.home, first)
        clash = make_entry("r-2", self.home)
        clash["state_path"] = first["state_path"]
        with self.assertRaises(ValueError):
            registry.add(self.home, clash)
        self.assertEqual(len(registry.load(self.home)["runs"]), 1)

    def test_update_merges_fields(self):
        entry = make_entry("r-1", self.home)
        registry.add(self.home, entry)
        returned = registry.update(
            self.home, "r-1", pid=4242, last_spawn_at="2026-07-04T00:00:00"
        )
        self.assertEqual(returned["pid"], 4242)
        self.assertEqual(returned["last_spawn_at"], "2026-07-04T00:00:00")
        stored = registry.get(registry.load(self.home), "r-1")
        self.assertEqual(stored["pid"], 4242)
        self.assertEqual(stored["last_spawn_at"], "2026-07-04T00:00:00")
        # Untouched fields survive the merge.
        self.assertEqual(stored["name"], entry["name"])
        self.assertEqual(stored["workspace"], entry["workspace"])
        self.assertEqual(stored["state_path"], entry["state_path"])

    def test_update_unknown_id_raises_key_error(self):
        with self.assertRaises(KeyError):
            registry.update(self.home, "r-missing", pid=1)

    def test_remove_deletes_entry(self):
        keep = make_entry("r-keep", self.home)
        gone = make_entry("r-gone", self.home)
        registry.add(self.home, keep)
        registry.add(self.home, gone)
        returned = registry.remove(self.home, "r-gone")
        self.assertEqual(returned["id"], "r-gone")
        reg = registry.load(self.home)
        self.assertEqual([e["id"] for e in reg["runs"]], ["r-keep"])

    def test_remove_unknown_id_raises_key_error(self):
        with self.assertRaises(KeyError):
            registry.remove(self.home, "r-missing")

    def test_get_returns_entry_or_none(self):
        entry = make_entry("r-1", self.home)
        registry.add(self.home, entry)
        reg = registry.load(self.home)
        self.assertEqual(registry.get(reg, "r-1"), entry)
        self.assertIsNone(registry.get(reg, "r-nope"))


# ---------------------------------------------------------------------------
# make_run_id


class TestMakeRunId(unittest.TestCase):
    def test_injectable_when_and_token(self):
        self.assertEqual(
            registry.make_run_id(when="20260704-101112", token="abc123"),
            "r-20260704-101112-abc123",
        )

    def test_defaults_are_well_formed_and_unique(self):
        ids = [registry.make_run_id() for _ in range(32)]
        for run_id in ids:
            self.assertRegex(run_id, r"^r-\d{8}-\d{6}-[0-9a-f]{6}$")
        self.assertEqual(len(set(ids)), len(ids))


# ---------------------------------------------------------------------------
# pid_alive


class TestPidAlive(RegistryTestCase):
    def test_current_process_is_alive(self):
        self.assertTrue(registry.pid_alive(os.getpid()))

    def test_exited_child_is_not_alive(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        self.procs.append(proc)
        proc.wait()  # reap so the pid no longer exists
        self.assertFalse(registry.pid_alive(proc.pid))

    def test_none_and_zero_are_not_alive(self):
        self.assertFalse(registry.pid_alive(None))
        self.assertFalse(registry.pid_alive(0))


class TestSessionLeaderAlive(RegistryTestCase):
    def test_session_leader_child_is_trusted(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        self.procs.append(proc)
        try:
            self.assertTrue(registry.session_leader_alive(proc.pid))
        finally:
            proc.kill()
            proc.wait()
        self.assertFalse(registry.session_leader_alive(proc.pid))

    def test_non_leader_child_is_not_trusted(self):
        # Inherits our process group: exactly what an OS-recycled pid looks
        # like — must never be mistaken for (or signalled as) a driver.
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        self.procs.append(proc)
        try:
            self.assertFalse(registry.session_leader_alive(proc.pid))
        finally:
            proc.kill()
            proc.wait()

    def test_none_and_zero_are_not_leaders(self):
        self.assertFalse(registry.session_leader_alive(None))
        self.assertFalse(registry.session_leader_alive(0))


# ---------------------------------------------------------------------------
# locked(): concurrent read-modify-write serialization


class TestLockedSerialization(RegistryTestCase):
    def test_threads_hammering_add_all_land_and_file_stays_valid_json(self):
        n_threads = 12
        adds_per_thread = 5
        barrier = threading.Barrier(n_threads)
        add_errors = []
        read_errors = []
        stop_reading = threading.Event()
        path = registry.registry_path(self.home)

        def reader():
            # A concurrent reader must only ever observe a missing file or
            # complete, valid JSON — never a partially written registry.
            while not stop_reading.is_set():
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        json.loads(fh.read())
                except FileNotFoundError:
                    pass
                except Exception as exc:  # noqa: BLE001 - recorded for assert
                    read_errors.append(repr(exc))
                    return

        def writer(worker):
            try:
                barrier.wait(timeout=30)
                for i in range(adds_per_thread):
                    run_id = "r-w%02d-%d" % (worker, i)
                    registry.add(self.home, make_entry(run_id, self.home))
            except Exception as exc:  # noqa: BLE001 - recorded for assert
                add_errors.append(repr(exc))

        reader_thread = threading.Thread(target=reader)
        reader_thread.start()
        writers = [
            threading.Thread(target=writer, args=(w,)) for w in range(n_threads)
        ]
        for thread in writers:
            thread.start()
        for thread in writers:
            thread.join(timeout=60)
        stop_reading.set()
        reader_thread.join(timeout=10)

        self.assertEqual(add_errors, [])
        self.assertEqual(read_errors, [])
        reg = registry.load(self.home)
        ids = [e["id"] for e in reg["runs"]]
        expected = {
            "r-w%02d-%d" % (w, i)
            for w in range(n_threads)
            for i in range(adds_per_thread)
        }
        self.assertEqual(len(ids), len(expected), "lost or duplicated adds")
        self.assertEqual(set(ids), expected)

    def test_two_processes_hammering_add_all_land(self):
        adds_per_proc = 8
        script = (
            "import sys\n"
            "from orchestrator import registry\n"
            "from orchestrator.tests.test_registry import make_entry\n"
            "home, tag, count = sys.argv[1], sys.argv[2], int(sys.argv[3])\n"
            "for i in range(count):\n"
            "    registry.add(home, make_entry('r-%s-%d' % (tag, i), home))\n"
        )
        procs = []
        for tag in ("p1", "p2"):
            proc = subprocess.Popen(
                [sys.executable, "-c", script, self.home, tag,
                 str(adds_per_proc)],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.procs.append(proc)
            procs.append(proc)
        for proc in procs:
            _, err = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, err.decode("utf-8", "replace"))

        reg = registry.load(self.home)
        ids = set(e["id"] for e in reg["runs"])
        expected = {
            "r-%s-%d" % (tag, i)
            for tag in ("p1", "p2")
            for i in range(adds_per_proc)
        }
        self.assertEqual(len(reg["runs"]), len(expected))
        self.assertEqual(ids, expected)


if __name__ == "__main__":
    unittest.main()
