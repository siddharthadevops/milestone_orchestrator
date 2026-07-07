import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from orchestrator import kvstore


class KVStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="orch-kvstore-test-")
        self.home = self._tmp.name
        self.client = kvstore.LocalKVClient(self.home)
        self.env = kvstore.RevisionEnvelopeStore(self.client)

    def tearDown(self):
        self._tmp.cleanup()


class TestEnvelopeSemantics(KVStoreTestCase):
    def test_round_trip_monotonic_revision_and_stable_json(self):
        value = {"version": 7, "items": [{"b": 2, "a": 1}]}
        first = self.env.put("milestone_orchestrator/policy:p1", value)
        self.assertEqual(
            first,
            {"exists?": True, "revision": 1, "value": value},
        )
        self.assertEqual(self.env.read("milestone_orchestrator/policy:p1"), first)

        second_value = {"version": 7, "items": [{"a": 3}]}
        second = self.env.put(
            "milestone_orchestrator/policy:p1", second_value
        )
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["value"], second_value)

        raw_before = json.dumps(
            second["value"], sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        )
        raw_after = json.dumps(
            self.env.read("milestone_orchestrator/policy:p1")["value"],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        self.assertEqual(raw_after, raw_before)

    def test_rejects_non_json_and_non_string_map_keys_without_writing(self):
        key = "milestone_orchestrator/policy:p2"
        with self.assertRaises(ValueError):
            self.env.put(key, {"bad": object()})
        self.assertEqual(
            self.env.read(key),
            {"exists?": False, "revision": None, "value": None},
        )

        with self.assertRaises(ValueError):
            self.env.put(key, {1: "not a JSON object key"})
        self.assertEqual(
            self.env.read(key),
            {"exists?": False, "revision": None, "value": None},
        )

    def test_never_written_read(self):
        self.assertEqual(
            self.env.read("milestone_orchestrator/policy:missing"),
            {"exists?": False, "revision": None, "value": None},
        )

    def test_cas_matrix_and_revision_mismatch_record(self):
        key = "milestone_orchestrator/policy:p3"
        created = self.env.cas(key, None, {"id": "p3", "version": 1})
        self.assertTrue(created.ok)
        self.assertEqual(created.record["revision"], 1)

        create_again = self.env.cas(key, None, {"id": "p3", "version": 2})
        self.assertFalse(create_again.ok)
        self.assertEqual(create_again.reason, "revision_mismatch")
        self.assertEqual(create_again.record, created.record)

        updated = self.env.cas(key, 1, {"id": "p3", "version": 2})
        self.assertTrue(updated.ok)
        self.assertEqual(updated.record["revision"], 2)

        stale = self.env.cas(key, 1, {"id": "p3", "version": 3})
        self.assertFalse(stale.ok)
        self.assertEqual(stale.reason, "revision_mismatch")
        self.assertEqual(stale.record, updated.record)
        self.assertEqual(self.env.read(key), updated.record)

    def test_revision_cas_rejects_bool_revision(self):
        key = "milestone_orchestrator/policy:bool-revision"
        created = self.env.put(key, {"id": "bool-revision"})

        with self.assertRaises(ValueError):
            self.env.cas(key, True, {"id": "wrong-type"})
        with self.assertRaises(ValueError):
            self.env.delete(key, True)

        self.assertEqual(self.env.read(key), created)

    def test_tombstone_delete_listing_and_rewrite_from_tombstone(self):
        key = "milestone_orchestrator/run:r1/status"
        self.assertEqual(self.env.put(key, {"state": "open"})["revision"], 1)
        deleted = self.env.delete(key)
        self.assertTrue(deleted.ok)
        self.assertEqual(
            deleted.record,
            {"exists?": False, "revision": 2, "value": None},
        )
        self.assertEqual(self.env.read(key), deleted.record)

        listed = self.client.list_entries(
            prefix="milestone_orchestrator/run:", include_values=True
        )
        self.assertEqual([item["key"] for item in listed["items"]], [key])
        self.assertTrue(listed["items"][0]["value"]["deleted?"])

        create_only = self.env.cas(key, None, {"state": "recreated"})
        self.assertFalse(create_only.ok)
        self.assertEqual(create_only.record, deleted.record)

        rewritten = self.env.cas(key, 2, {"state": "recreated"})
        self.assertTrue(rewritten.ok)
        self.assertEqual(
            rewritten.record,
            {
                "exists?": True,
                "revision": 3,
                "value": {"state": "recreated"},
            },
        )

    def test_envelope_revision_is_independent_from_domain_version(self):
        key = "milestone_orchestrator/policy:domain-version"
        self.env.put(key, {"version": 100})
        self.env.put(key, {"version": 100})
        read = self.env.read(key)
        self.assertEqual(read["revision"], 2)
        self.assertEqual(read["value"]["version"], 100)
        self.env.put(key, {"version": 101})
        read = self.env.read(key)
        self.assertEqual(read["revision"], 3)
        self.assertEqual(read["value"]["version"], 101)


class TestPointKVPrimitive(KVStoreTestCase):
    def test_put_get_absent_and_whole_value_cas(self):
        self.assertIs(self.client.get("raw:key"), kvstore.ABSENT)
        self.assertEqual(self.client.put("raw:key", {"v": 1}), 1)
        self.assertEqual(self.client.get("raw:key"), {"v": 1})

        conflict = self.client.cas("raw:key", {"v": 0}, {"v": 2})
        self.assertFalse(conflict.ok)
        self.assertEqual(conflict.current, {"v": 1})
        self.assertEqual(conflict.rev, 1)
        self.assertEqual(self.client.get("raw:key"), {"v": 1})

        written = self.client.cas("raw:key", {"v": 1}, {"v": 2})
        self.assertTrue(written.ok)
        self.assertEqual(written.rev, 2)
        self.assertEqual(self.client.get("raw:key"), {"v": 2})

        created = self.client.cas("raw:new", kvstore.ABSENT, {"v": "new"})
        self.assertTrue(created.ok)
        self.assertEqual(created.rev, 1)

    def test_whole_value_cas_is_json_type_exact(self):
        self.client.put("raw:scalar", 1)
        scalar_conflict = self.client.cas("raw:scalar", True, 2)
        self.assertFalse(scalar_conflict.ok)
        self.assertEqual(scalar_conflict.current, 1)
        self.assertEqual(self.client.get("raw:scalar"), 1)

        nested = {"items": [{"enabled": True}, 0]}
        self.client.put("raw:nested", nested)
        nested_conflict = self.client.cas(
            "raw:nested",
            {"items": [{"enabled": 1}, False]},
            {"items": []},
        )
        self.assertFalse(nested_conflict.ok)
        self.assertEqual(nested_conflict.current, nested)
        self.assertEqual(self.client.get("raw:nested"), nested)

    def test_point_values_reject_unsafe_non_codec_terms(self):
        for bad_value in [
            {1: "not a JSON object key"},
            {"bytes": b"not-json"},
            {"tuple": ("not", "json")},
            {"object": object()},
            kvstore.ABSENT,
        ]:
            with self.subTest(value=repr(bad_value)):
                with self.assertRaises(ValueError):
                    self.client.put("raw:bad", bad_value)
                with self.assertRaises(ValueError):
                    self.client.cas("raw:bad", kvstore.ABSENT, bad_value)
                self.assertIs(self.client.get("raw:bad"), kvstore.ABSENT)

    def test_point_store_accepts_atom_keyed_raw_work_area_terms(self):
        A = kvstore.Atom
        key = kvstore.raw_work_area_key("main")
        raw = {
            A("name"): "main",
            A("display_name"): "Main",
            A("primary"): {A("path"): "/repo", A("device"): 1},
            A("additional"): [{A("path"): "/repo/lib", A("device"): "dev"}],
            A("executor_id"): "local-orchestrator",
            A("version"): 1,
            A("status"): "pending",
        }
        tombstone = {A("name"): "main", A("deleted"): True, A("version"): 2}

        self.assertEqual(self.client.put(key, raw), 1)
        self.assertEqual(self.client.get(key), raw)
        self.assertEqual(
            self.client.list_entries(prefix="refs/work_area:", include_values=True),
            {"items": [{"key": key, "rev": 1, "value": raw}], "next_cursor": None},
        )

        conflict = self.client.cas(key, {"name": "main"}, tombstone)
        self.assertFalse(conflict.ok)
        self.assertEqual(conflict.current, raw)
        self.assertEqual(self.client.get(key), raw)

        written = self.client.cas(key, raw, tombstone)
        self.assertTrue(written.ok)
        self.assertEqual(written.rev, 2)
        self.assertEqual(self.client.get(key), tombstone)

    def test_successful_writes_bump_native_rev_and_failed_cas_does_not(self):
        self.assertEqual(self.client.put("k", "one"), 1)
        self.assertEqual(self.client.put("k", "two"), 2)
        failed = self.client.cas("k", "not-two", "three")
        self.assertFalse(failed.ok)
        self.assertEqual(failed.rev, 2)
        self.assertEqual(
            self.client.list_entries(include_values=True)["items"],
            [{"key": "k", "rev": 2, "value": "two"}],
        )
        self.assertTrue(self.client.cas("k", "two", "three").ok)
        self.assertEqual(
            self.client.list_entries(include_values=True)["items"],
            [{"key": "k", "rev": 3, "value": "three"}],
        )

    def test_lpc_shaped_sorted_paged_listings(self):
        for key, value in [
            ("b:1", "b1"),
            ("a:1", "a1"),
            ("a:2", "a2"),
            ("a:3", "a3"),
        ]:
            self.client.put(key, value)

        first = self.client.list_entries(prefix="a:", limit=2)
        self.assertEqual(
            first,
            {
                "items": [{"key": "a:1", "rev": 1}, {"key": "a:2", "rev": 1}],
                "next_cursor": "a:2",
            },
        )
        second = self.client.list_entries(
            prefix="a:", cursor=first["next_cursor"], limit=2,
            include_values=True,
        )
        self.assertEqual(
            second,
            {
                "items": [{"key": "a:3", "rev": 1, "value": "a3"}],
                "next_cursor": None,
            },
        )

    def test_listings_include_envelope_tombstones(self):
        key = "milestone_orchestrator/policy:deleted"
        self.env.put(key, {"enabled": True})
        self.env.delete(key)
        listed = self.client.list_entries(
            prefix="milestone_orchestrator/policy:", include_values=True
        )
        self.assertEqual(len(listed["items"]), 1)
        self.assertEqual(listed["items"][0]["key"], key)
        self.assertTrue(listed["items"][0]["value"]["deleted?"])


class TestPersistenceAndConcurrency(KVStoreTestCase):
    def test_file_backed_persistence_survives_reopen(self):
        self.client.put("plain", {"x": 1})
        raw = {kvstore.Atom("name"): "main", kvstore.Atom("version"): 1}
        self.client.put(kvstore.raw_work_area_key("main"), raw)
        live = self.env.put("milestone_orchestrator/policy:persist", {"p": 1})
        self.env.put("milestone_orchestrator/policy:gone", {"p": 2})
        deleted = self.env.delete("milestone_orchestrator/policy:gone")

        reopened_client = kvstore.LocalKVClient(self.home)
        reopened_env = kvstore.RevisionEnvelopeStore(reopened_client)

        self.assertEqual(reopened_client.get("plain"), {"x": 1})
        self.assertEqual(
            reopened_client.list_entries(prefix="plain")["items"],
            [{"key": "plain", "rev": 1}],
        )
        self.assertEqual(
            reopened_client.get(kvstore.raw_work_area_key("main")), raw
        )
        self.assertEqual(
            reopened_env.read("milestone_orchestrator/policy:persist"), live
        )
        self.assertEqual(
            reopened_env.read("milestone_orchestrator/policy:gone"),
            deleted.record,
        )
        self.assertEqual(
            reopened_client.list_entries(
                prefix="milestone_orchestrator/policy:"
            )["items"],
            [
                {"key": "milestone_orchestrator/policy:gone", "rev": 2},
                {"key": "milestone_orchestrator/policy:persist", "rev": 1},
            ],
        )

    def test_backing_file_is_json_data_not_pickle(self):
        self.client.put("plain", {"x": 1})
        with open(os.path.join(self.home, kvstore.STORE_FILENAME), "r",
                  encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["entries"]["plain"]["value_encoding"], "json")
        self.assertEqual(data["entries"]["plain"]["value"], {"x": 1})

    def test_pickle_payload_in_backing_file_is_rejected_not_executed(self):
        marker = os.path.join(self.home, "pickle-ran")
        payload = (
            b"cos\nsystem\n"
            + b"(S"
            + repr("touch %s" % marker).encode("ascii")
            + b"\ntR."
        )
        with open(os.path.join(self.home, kvstore.STORE_FILENAME), "wb") as fh:
            fh.write(payload)

        with self.assertRaises(RuntimeError):
            self.client.get("plain")
        self.assertFalse(os.path.exists(marker))

    def test_racing_create_only_writes_have_one_winner(self):
        barrier = threading.Barrier(2)

        def create(value):
            barrier.wait()
            return self.client.cas("race", kvstore.ABSENT, {"winner": value})

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, ["a", "b"]))

        self.assertEqual([result.ok for result in results].count(True), 1)
        self.assertEqual([result.ok for result in results].count(False), 1)
        self.assertIn(self.client.get("race")["winner"], ["a", "b"])
        self.assertEqual(
            self.client.list_entries(prefix="race")["items"][0]["rev"], 1
        )

    def test_readers_never_observe_torn_values_while_writers_run(self):
        stop = threading.Event()
        errors = []
        thread_errors = []

        def writer():
            try:
                for number in range(60):
                    self.client.put(
                        "big",
                        {"n": number, "payload": [number for _ in range(128)]},
                    )
            except BaseException as exc:
                thread_errors.append(exc)
            finally:
                stop.set()

        def reader():
            try:
                while not stop.is_set():
                    value = self.client.get("big")
                    if value is kvstore.ABSENT:
                        continue
                    if any(item != value["n"] for item in value["payload"]):
                        errors.append(value)
            except BaseException as exc:
                thread_errors.append(exc)

        threads = [threading.Thread(target=writer)] + [
            threading.Thread(target=reader) for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(thread_errors, [])
        self.assertEqual(errors, [])


class TestKeyGrammar(unittest.TestCase):
    def test_default_and_custom_namespace_keys(self):
        self.assertEqual(
            kvstore.work_area_meta_key("main"),
            "milestone_orchestrator/work_area_meta:main",
        )
        self.assertEqual(
            kvstore.policy_key("lpc-reuse-audit"),
            "milestone_orchestrator/policy:lpc-reuse-audit",
        )
        self.assertEqual(
            kvstore.run_status_key("r-1"),
            "milestone_orchestrator/run:r-1/status",
        )
        self.assertEqual(
            kvstore.run_digest_key("r-1"),
            "milestone_orchestrator/run:r-1/digest",
        )
        self.assertEqual(
            kvstore.work_area_meta_key("main", namespace="custom"),
            "custom/work_area_meta:main",
        )
        self.assertEqual(
            kvstore.run_digest_key("r-1", namespace="custom"),
            "custom/run:r-1/digest",
        )

    def test_raw_work_area_key_is_native_and_never_namespaced(self):
        self.assertEqual(kvstore.raw_work_area_key("main"), "refs/work_area:main")
        builder = kvstore.KeyBuilder(namespace="custom")
        self.assertEqual(builder.raw_work_area("main"), "refs/work_area:main")

    def test_invalid_fragments_and_namespaces_are_rejected(self):
        invalid = ["", "   ", "has/slash", "bad\ncontrol"]
        for value in invalid:
            with self.assertRaises(ValueError):
                kvstore.KeyBuilder(namespace=value)
            with self.assertRaises(ValueError):
                kvstore.work_area_meta_key(value)
            with self.assertRaises(ValueError):
                kvstore.policy_key(value)
            with self.assertRaises(ValueError):
                kvstore.run_status_key(value)
            with self.assertRaises(ValueError):
                kvstore.raw_work_area_key(value)


class TestRootContainment(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="orch-roots-test-")
        self.root = os.path.realpath(os.path.join(self._tmp.name, "root"))
        self.outside = os.path.realpath(os.path.join(self._tmp.name, "outside"))
        os.mkdir(self.root)
        os.mkdir(self.outside)
        os.mkdir(os.path.join(self.root, "sub"))
        with open(os.path.join(self.root, "sub", "file.txt"), "w") as fh:
            fh.write("inside")
        with open(os.path.join(self.outside, "file.txt"), "w") as fh:
            fh.write("outside")
        os.symlink(
            os.path.join(self.outside, "file.txt"),
            os.path.join(self.root, "sub", "escape-link"),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_inside_absolute_and_relative_paths_are_accepted(self):
        self.assertTrue(
            kvstore.path_is_inside_roots(
                os.path.join(self.root, "sub", "file.txt"), [self.root]
            )
        )
        self.assertTrue(
            kvstore.path_is_inside_roots("sub/file.txt", [self.root])
        )

    def test_escapes_and_empty_root_set_are_rejected(self):
        self.assertFalse(
            kvstore.path_is_inside_roots("../outside/file.txt", [self.root])
        )
        self.assertFalse(
            kvstore.path_is_inside_roots(
                os.path.join(self.outside, "file.txt"), [self.root]
            )
        )
        self.assertFalse(
            kvstore.path_is_inside_roots("sub/escape-link", [self.root])
        )
        self.assertFalse(
            kvstore.path_is_inside_roots(
                os.path.join(self.root, "sub", "file.txt"), []
            )
        )


if __name__ == "__main__":
    unittest.main()
