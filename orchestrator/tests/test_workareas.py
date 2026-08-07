import os
import tempfile
import unittest

from orchestrator import kvstore
from orchestrator import workareas


A = kvstore.Atom


class WorkAreaStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="orch-workareas-test-")
        self.home = self._tmp.name
        self.store = workareas.WorkAreaStore(self.home, "project-a")
        self.primary = {"path": "/repo", "device": 1}
        self.additional = [{"path": "/repo/lib", "device": "dev"}]

    def tearDown(self):
        self._tmp.cleanup()

    def raw(self, name):
        return self.store.client.get(kvstore.raw_work_area_key(name))

    def declare(self, name="main", primary=None, additional=None,
                executor_id="local-exec", display_name=None):
        return self.store.declare(
            name,
            primary if primary is not None else self.primary,
            additional if additional is not None else list(self.additional),
            executor_id,
            display_name=display_name,
        )


class TestDomainAndValidation(WorkAreaStoreTestCase):
    def test_created_record_is_agent99_atom_keyed_full_domain(self):
        result = self.declare(display_name=" Main/Workspace ")
        self.assertTrue(result.ok)
        self.assertEqual(result.value["display_name"], "Main/Workspace")
        self.assertEqual(result.value["status"], workareas.STATUS_PENDING)
        self.assertEqual(result.value["version"], 1)

        raw = self.raw("main")
        self.assertEqual(set(raw), workareas.RECORD_KEYS)
        self.assertTrue(all(isinstance(key, kvstore.Atom) for key in raw))
        self.assertEqual(raw[A("name")], "main")
        self.assertEqual(raw[A("display_name")], "Main/Workspace")
        self.assertEqual(set(raw[A("primary")]), {A("path"), A("device")})
        self.assertEqual(
            raw[A("additional")],
            [{A("path"): "/repo/lib", A("device"): "dev"}],
        )

        confirmed = self.store.confirm(
            "main", self.primary, list(self.additional), "local-exec"
        )
        self.assertTrue(confirmed.ok)
        self.assertEqual(confirmed.value["status"], workareas.STATUS_READY)
        self.assertEqual(confirmed.value["version"], 2)
        self.assertEqual(self.store.read("main").value, confirmed.value)

    def test_malformed_full_domain_values_are_rejected_and_not_repaired(self):
        raw = {
            A("name"): "broken",
            A("primary"): {A("path"): "/repo", A("device"): 1},
            A("additional"): [],
            A("executor_id"): "exec",
            A("version"): 1,
            A("status"): workareas.STATUS_PENDING,
        }
        self.store.client.put(kvstore.raw_work_area_key("broken"), raw)

        self.assertEqual(self.store.read("broken").reason, workareas.MALFORMED)
        self.assertEqual(
            self.store.confirm("broken", self.primary, [], "exec").reason,
            workareas.MALFORMED,
        )
        self.assertEqual(self.raw("broken"), raw)

        healed = self.store.declare("broken", self.primary, [], "exec")
        self.assertTrue(healed.ok)
        self.assertEqual(healed.value["version"], 1)
        self.assertEqual(healed.value["status"], workareas.STATUS_PENDING)

    def test_read_interpretation_trims_stored_display_name_without_rewriting(self):
        raw = {
            A("name"): "padded",
            A("display_name"): " Padded/Label ",
            A("primary"): {A("path"): "/repo", A("device"): 1},
            A("additional"): [],
            A("executor_id"): "exec",
            A("version"): 1,
            A("status"): workareas.STATUS_PENDING,
        }
        self.store.client.put(kvstore.raw_work_area_key("padded"), raw)

        read = self.store.read("padded")
        self.assertTrue(read.ok)
        self.assertEqual(read.value["display_name"], "Padded/Label")

        listed = self.store.list_records()
        self.assertTrue(listed.ok)
        self.assertEqual([record["display_name"] for record in listed.value],
                         ["Padded/Label"])
        self.assertEqual(
            self.raw("padded")[A("display_name")],
            " Padded/Label ",
        )

    def test_field_domain_matrix(self):
        invalid_names = ["", "   ", "has/slash", "bad\ncontrol", "a" * 129]
        for name in invalid_names:
            with self.subTest(name=name):
                self.assertEqual(self.declare(name=name).reason, workareas.INVALID_NAME)
                self.assertIs(
                    self.store.client.get("refs/work_area:%s" % name),
                    kvstore.ABSENT,
                )

        spaced = self.declare(name=" main ")
        self.assertTrue(spaced.ok)
        self.assertEqual(spaced.value["name"], " main ")
        self.assertEqual(spaced.value["display_name"], "main")

        self.assertTrue(self.declare(name="slash-display",
                                     display_name=" A/B ").ok)
        for display_name in ["", "   ", "bad\ncontrol", "a" * 129, 7]:
            with self.subTest(display_name=display_name):
                result = self.store.relabel("slash-display", display_name)
                self.assertEqual(result.reason, workareas.INVALID_DISPLAY_NAME)

        for executor_id in ["", "   ", 1, None]:
            with self.subTest(executor_id=executor_id):
                self.assertEqual(
                    self.declare(name="bad-exec", executor_id=executor_id).reason,
                    workareas.INVALID_EXECUTOR_ID,
                )

        invalid_roots = [
            {"path": "relative", "device": 1},
            {"path": "/repo/../other", "device": 1},
            {"path": "/repo//other", "device": 1},
            {"path": "/repo/.", "device": 1},
            {"path": "/repo/trailing/", "device": 1},
            {"path": "/repo/blank-device", "device": ""},
            {"path": "/repo/missing-device", "device": None},
            {"path": "/repo/bool-device", "device": True},
        ]
        for root in invalid_roots:
            with self.subTest(root=root):
                result = self.declare(name="bad-root", primary=root)
                self.assertEqual(result.reason, workareas.INVALID_DESCRIPTOR)

        duplicate = self.declare(
            name="dup",
            primary={"path": "/repo", "device": 1},
            additional=[{"path": "/repo", "device": 1}],
        )
        self.assertEqual(duplicate.reason, workareas.DUPLICATE_ROOT)

    def test_invalid_utf8_strings_return_domain_errors_or_malformed(self):
        invalid_utf8 = "\ud800"
        self.assertEqual(
            self.declare(name=invalid_utf8).reason, workareas.INVALID_NAME
        )
        self.assertEqual(
            self.declare(name="bad-display", display_name=invalid_utf8).reason,
            workareas.INVALID_DISPLAY_NAME,
        )
        self.declare(name="main")
        self.assertEqual(
            self.store.relabel("main", invalid_utf8).reason,
            workareas.INVALID_DISPLAY_NAME,
        )

        raw = {
            A("name"): invalid_utf8,
            A("display_name"): "Invalid",
            A("primary"): {A("path"): "/repo", A("device"): 1},
            A("additional"): [],
            A("executor_id"): "exec",
            A("version"): 1,
            A("status"): workareas.STATUS_PENDING,
        }
        self.assertEqual(workareas._interpret(raw)[0], "malformed")
        raw[A("name")] = "invalid-display"
        raw[A("display_name")] = invalid_utf8
        self.assertEqual(workareas._interpret(raw)[0], "malformed")

    def test_read_accepts_unavailable_but_rejects_bad_status_and_version(self):
        raw = {
            A("name"): "offline",
            A("display_name"): "Offline",
            A("primary"): {A("path"): "/repo", A("device"): 1},
            A("additional"): [],
            A("executor_id"): "exec",
            A("version"): 0,
            A("status"): workareas.STATUS_UNAVAILABLE,
        }
        self.store.client.put(kvstore.raw_work_area_key("offline"), raw)
        read = self.store.read("offline")
        self.assertTrue(read.ok)
        self.assertEqual(read.value["status"], workareas.STATUS_UNAVAILABLE)
        self.assertEqual(self.store.resolve("offline").reason, workareas.NOT_READY)

        for field, value in [("status", "bad"), ("version", -1), ("version", True)]:
            with self.subTest(field=field, value=value):
                bad = dict(raw)
                bad[A(field)] = value
                self.store.client.put(kvstore.raw_work_area_key("offline"), bad)
                self.assertEqual(self.store.read("offline").reason, workareas.MALFORMED)


class TestStateMachine(WorkAreaStoreTestCase):
    def test_declare_create_redeclare_and_content_change(self):
        created = self.declare(display_name="Main Label")
        self.assertTrue(created.ok)
        self.assertEqual(created.value["version"], 1)
        self.assertEqual(created.value["status"], workareas.STATUS_PENDING)

        ready = self.store.confirm(
            "main", self.primary, list(self.additional), "local-exec"
        )
        self.assertTrue(ready.ok)
        self.assertEqual(ready.value["version"], 2)

        same = self.declare(display_name="Ignored Label")
        self.assertTrue(same.ok)
        self.assertEqual(same.value["version"], 2)
        self.assertEqual(same.value["status"], workareas.STATUS_READY)
        self.assertEqual(same.value["display_name"], "Main Label")

        unavailable = dict(self.raw("main"))
        unavailable[A("status")] = workareas.STATUS_UNAVAILABLE
        self.store.client.put(kvstore.raw_work_area_key("main"), unavailable)
        still_unavailable = self.declare()
        self.assertTrue(still_unavailable.ok)
        self.assertEqual(still_unavailable.value["version"], 2)
        self.assertEqual(still_unavailable.value["status"],
                         workareas.STATUS_UNAVAILABLE)

        renamed = self.store.relabel("main", " Kept Label ")
        self.assertTrue(renamed.ok)
        changed = self.declare(
            primary={"path": "/repo/new", "device": 1},
            executor_id="other-exec",
        )
        self.assertTrue(changed.ok)
        self.assertEqual(changed.value["version"], 3)
        self.assertEqual(changed.value["status"], workareas.STATUS_PENDING)
        self.assertEqual(changed.value["executor_id"], "other-exec")
        self.assertEqual(changed.value["display_name"], "Kept Label")

    def test_declare_over_absent_malformed_and_tombstoned_starts_pending_v1(self):
        self.assertEqual(self.declare(name="absent").value["version"], 1)

        self.store.client.put(kvstore.raw_work_area_key("bad"), {"bad": "value"})
        bad = self.declare(name="bad")
        self.assertTrue(bad.ok)
        self.assertEqual(bad.value["version"], 1)
        self.assertEqual(bad.value["status"], workareas.STATUS_PENDING)

        self.declare(name="gone")
        self.store.delete("gone")
        gone = self.declare(name="gone")
        self.assertTrue(gone.ok)
        self.assertEqual(gone.value["version"], 1)
        self.assertEqual(gone.value["status"], workareas.STATUS_PENDING)

    def test_confirm_rules_and_transition_only_errors(self):
        self.declare(display_name="Main")
        mismatch = self.store.confirm(
            "main", {"path": "/other", "device": 1}, [], "local-exec"
        )
        self.assertEqual(mismatch.reason, workareas.DESCRIPTOR_MISMATCH)
        self.assertEqual(self.store.read("main").value["version"], 1)

        ready = self.store.confirm(
            "main", self.primary, list(self.additional), "local-exec"
        )
        self.assertTrue(ready.ok)
        self.assertEqual(ready.value["version"], 2)
        self.assertEqual(ready.value["display_name"], "Main")

        same = self.store.confirm(
            "main", self.primary, list(self.additional), "local-exec"
        )
        self.assertTrue(same.ok)
        self.assertEqual(same.value["version"], 2)

        changed_exec = self.store.confirm(
            "main", self.primary, list(self.additional), "new-exec"
        )
        self.assertTrue(changed_exec.ok)
        self.assertEqual(changed_exec.value["version"], 3)
        self.assertEqual(changed_exec.value["executor_id"], "new-exec")

        self.assertEqual(
            self.store.confirm("missing", self.primary, [], "exec").reason,
            workareas.UNKNOWN,
        )
        self.store.client.put(kvstore.raw_work_area_key("bad"), {"bad": "value"})
        self.assertEqual(
            self.store.confirm("bad", self.primary, [], "exec").reason,
            workareas.MALFORMED,
        )
        self.declare(name="gone")
        self.store.delete("gone")
        self.assertEqual(
            self.store.confirm("gone", self.primary, list(self.additional),
                               "exec").reason,
            workareas.UNKNOWN,
        )

    def test_mark_unavailable_mirrors_confirm_and_guards_the_descriptor(self):
        self.declare(display_name="Main")
        # An absence is a statement about the roots that were checked: a
        # descriptor repointed underneath must not be condemned by it.
        mismatch = self.store.mark_unavailable(
            "main", {"path": "/other", "device": 1}, [], "local-exec"
        )
        self.assertEqual(mismatch.reason, workareas.DESCRIPTOR_MISMATCH)
        self.assertEqual(self.store.read("main").value["version"], 1)

        gone = self.store.mark_unavailable(
            "main", self.primary, list(self.additional), "local-exec"
        )
        self.assertTrue(gone.ok)
        self.assertEqual(gone.value["status"], workareas.STATUS_UNAVAILABLE)
        self.assertEqual(gone.value["version"], 2)
        self.assertEqual(gone.value["display_name"], "Main")

        # Version follows confirm's rule in both directions.
        same = self.store.mark_unavailable(
            "main", self.primary, list(self.additional), "local-exec"
        )
        self.assertEqual(same.value["version"], 2)
        back = self.store.confirm(
            "main", self.primary, list(self.additional), "local-exec"
        )
        self.assertEqual(
            (back.value["status"], back.value["version"]),
            (workareas.STATUS_READY, 3),
        )

    def test_relabel_preserves_version_status_roots_key_and_is_transition_only(self):
        self.declare()
        self.store.confirm("main", self.primary, list(self.additional), "local-exec")
        before = self.store.read("main").value
        renamed = self.store.relabel("main", " Renamed/Label ")
        self.assertTrue(renamed.ok)
        self.assertEqual(renamed.value["name"], "main")
        self.assertEqual(renamed.value["display_name"], "Renamed/Label")
        self.assertEqual(renamed.value["version"], before["version"])
        self.assertEqual(renamed.value["status"], before["status"])
        self.assertEqual(renamed.value["primary"], before["primary"])
        self.assertEqual(renamed.value["additional"], before["additional"])
        self.assertEqual(renamed.value["executor_id"], before["executor_id"])

        self.assertEqual(self.store.relabel("missing", "x").reason, workareas.UNKNOWN)
        self.store.client.put(kvstore.raw_work_area_key("bad"), {"bad": "value"})
        self.assertEqual(self.store.relabel("bad", "x").reason, workareas.MALFORMED)
        self.declare(name="gone")
        self.store.delete("gone")
        self.assertEqual(self.store.relabel("gone", "x").reason, workareas.UNKNOWN)

    def test_delete_writes_positive_version_raw_tombstone(self):
        self.declare()
        self.store.confirm("main", self.primary, list(self.additional), "local-exec")
        deleted = self.store.delete("main")
        self.assertTrue(deleted.ok)
        self.assertEqual(
            self.raw("main"),
            {A("name"): "main", A("deleted"): True, A("version"): 3},
        )
        self.assertEqual(self.store.read("main").reason, workareas.UNKNOWN)

        self.assertEqual(self.store.delete("missing").reason, workareas.UNKNOWN)
        self.assertEqual(self.store.delete("main").reason, workareas.UNKNOWN)
        self.store.client.put(kvstore.raw_work_area_key("bad"), {"bad": "value"})
        self.assertEqual(self.store.delete("bad").reason, workareas.MALFORMED)


class TestWholeValueCas(WorkAreaStoreTestCase):
    def _inject_once_before_cas(self, action):
        original = self.store.client.cas
        fired = []

        def wrapped(key, expected, value):
            if not fired:
                fired.append(True)
                self.store.client.cas = original
                try:
                    action()
                finally:
                    self.store.client.cas = wrapped
            return original(key, expected, value)

        self.store.client.cas = wrapped
        return original

    def test_stale_cas_rereads_and_still_qualifies_without_lost_update(self):
        self.declare()

        original = self._inject_once_before_cas(
            lambda: self.store.relabel("main", "Raced Label")
        )
        try:
            result = self.store.confirm(
                "main", self.primary, list(self.additional), "local-exec"
            )
        finally:
            self.store.client.cas = original

        self.assertTrue(result.ok)
        final = self.store.read("main").value
        self.assertEqual(final["display_name"], "Raced Label")
        self.assertEqual(final["status"], workareas.STATUS_READY)
        self.assertEqual(final["version"], 2)

    def test_stale_cas_rereads_and_stops_when_fresh_record_no_longer_qualifies(self):
        self.store.declare("race", self.primary, [], "exec")

        def content_change():
            self.store.declare(
                "race", {"path": "/changed", "device": 1}, [], "exec"
            )

        original = self._inject_once_before_cas(content_change)
        try:
            result = self.store.confirm("race", self.primary, [], "exec")
        finally:
            self.store.client.cas = original

        self.assertEqual(result.reason, workareas.DESCRIPTOR_MISMATCH)
        final = self.store.read("race").value
        self.assertEqual(final["primary"], {"path": "/changed", "device": 1})
        self.assertEqual(final["version"], 2)
        self.assertEqual(final["status"], workareas.STATUS_PENDING)


class TestReadResolveListAndMeta(WorkAreaStoreTestCase):
    def test_read_resolve_and_list_records(self):
        self.store.declare("a-pending", self.primary, [], "exec")
        self.store.declare("b-ready", self.primary, [], "exec")
        self.store.confirm("b-ready", self.primary, [], "exec")

        unavailable = {
            A("name"): "c-unavailable",
            A("display_name"): "Unavailable",
            A("primary"): {A("path"): "/repo/unavailable", A("device"): 1},
            A("additional"): [],
            A("executor_id"): "exec",
            A("version"): 4,
            A("status"): workareas.STATUS_UNAVAILABLE,
        }
        self.store.client.put(
            kvstore.raw_work_area_key("c-unavailable"), unavailable
        )
        self.store.declare("d-gone", self.primary, [], "exec")
        self.store.delete("d-gone")

        self.assertTrue(self.store.read("a-pending").ok)
        self.assertEqual(self.store.resolve("a-pending").reason, workareas.NOT_READY)
        self.assertEqual(self.store.resolve("c-unavailable").reason,
                         workareas.NOT_READY)
        resolved = self.store.resolve("b-ready")
        self.assertTrue(resolved.ok)
        self.assertEqual(resolved.value, {"primary": self.primary, "additional": []})
        self.assertEqual(self.store.read("d-gone").reason, workareas.UNKNOWN)

        listed = self.store.list_records()
        self.assertTrue(listed.ok)
        self.assertEqual(
            [record["name"] for record in listed.value],
            ["a-pending", "b-ready", "c-unavailable"],
        )

    def test_read_and_list_fail_closed_for_malformed_entries_without_writes(self):
        raw = {
            A("name"): "other",
            A("display_name"): "Other",
            A("primary"): {A("path"): "/repo", A("device"): 1},
            A("additional"): [],
            A("executor_id"): "exec",
            A("version"): 1,
            A("status"): workareas.STATUS_PENDING,
        }
        self.store.client.put(kvstore.raw_work_area_key("mismatch"), raw)
        self.assertEqual(self.store.read("mismatch").reason, workareas.MALFORMED)
        self.assertEqual(self.store.list_records().reason, workareas.MALFORMED)
        self.assertEqual(self.raw("mismatch"), raw)

        clean = workareas.WorkAreaStore(self.home, "bad-list-project")
        clean.client.put("refs/work_area:bad/name", raw)
        self.assertEqual(clean.list_records().reason, workareas.MALFORMED)
        self.assertEqual(clean.client.get("refs/work_area:bad/name"), raw)

        malformed = workareas.WorkAreaStore(self.home, "malformed-list-project")
        malformed.client.put(kvstore.raw_work_area_key("bad"), {"bad": "value"})
        self.assertEqual(malformed.list_records().reason, workareas.MALFORMED)
        self.assertEqual(malformed.client.get(kvstore.raw_work_area_key("bad")),
                         {"bad": "value"})

    def test_meta_family_is_enveloped_validated_and_separate_from_raw(self):
        self.declare()
        value = {
            "reuse_sources": [
                {
                    "root": "lpc",
                    "inventory": "docs/inventory.md",
                    "registry": "docs/registry.md",
                    "consumption": "submodule + path dep",
                }
            ]
        }
        first = self.store.put_meta("main", value)
        self.assertEqual(first, {"exists?": True, "revision": 1, "value": value})
        self.assertEqual(self.store.read_meta("main"), first)

        second = self.store.put_meta("main", {"reuse_sources": []})
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["value"], {"reuse_sources": []})

        raw = self.raw("main")
        self.assertIn(A("status"), raw)
        self.assertEqual(
            self.store.client.list_entries(prefix=workareas.RAW_PREFIX)["items"],
            [{"key": "refs/work_area:main", "rev": 1}],
        )
        meta_key = kvstore.work_area_meta_key("main")
        self.assertEqual(
            self.store.client.list_entries(prefix="milestone_orchestrator/work_area_meta:")["items"],
            [{"key": meta_key, "rev": 2}],
        )

        invalid_values = [
            {},
            {"reuse_sources": {}},
            {"reuse_sources": [{"root": "lpc"}]},
            {"reuse_sources": [{"root": "lpc", "inventory": "i",
                                "registry": "r", "consumption": 1}]},
        ]
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.store.put_meta("main", invalid)

    def test_project_scopes_are_independent_without_project_segments_in_keys(self):
        project_a = workareas.WorkAreaStore(self.home, "scope-a")
        project_b = workareas.WorkAreaStore(self.home, "scope-b")

        project_a.declare("main", {"path": "/a", "device": 1}, [], "exec-a")
        project_b.declare("main", {"path": "/b", "device": 1}, [], "exec-b")
        project_a.confirm("main", {"path": "/a", "device": 1}, [], "exec-a")
        project_b.put_meta("main", {"reuse_sources": []})
        project_a.delete("main")

        self.assertEqual(
            project_a.client.list_entries(prefix=workareas.RAW_PREFIX)["items"],
            [{"key": "refs/work_area:main", "rev": 3}],
        )
        self.assertEqual(
            project_b.client.list_entries(prefix=workareas.RAW_PREFIX)["items"],
            [{"key": "refs/work_area:main", "rev": 1}],
        )
        self.assertEqual(project_a.read("main").reason, workareas.UNKNOWN)
        self.assertEqual(project_b.read("main").value["primary"]["path"], "/b")
        self.assertEqual(project_a.read_meta("main")["revision"], None)
        self.assertEqual(project_b.read_meta("main")["revision"], 1)
        self.assertTrue(os.path.isdir(os.path.join(self.home, "scope-a")))
        self.assertTrue(os.path.isdir(os.path.join(self.home, "scope-b")))

        for project in [".", "..", "has/slash", ""]:
            with self.subTest(project=project):
                with self.assertRaises(workareas.WorkAreaValidationError):
                    workareas.WorkAreaStore(self.home, project)


if __name__ == "__main__":
    unittest.main()
