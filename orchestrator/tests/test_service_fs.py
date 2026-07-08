"""Tests for the panel pickers layer: /api/fs browsing and form memory
(/api/recents), plus the query-string routing change they required."""

import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from orchestrator import driver, registry, service


def _get(port, path):
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d%s" % (port, path), timeout=10
        ) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post(port, path, payload):
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class BrowseFsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        for d in ("Beta", "alpha", ".hidden_dir"):
            os.makedirs(os.path.join(self.root, d))
        for f in ("Notes.MD", "readme.txt", "code.py", ".secret.md"):
            with open(os.path.join(self.root, f), "w") as fh:
                fh.write("x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dir_mode_lists_sorted_dirs_only(self):
        out = service.browse_fs(self.root, mode="dir")
        self.assertEqual(out["dirs"], ["alpha", "Beta"])
        self.assertEqual(out["files"], [])
        self.assertEqual(out["path"], os.path.abspath(self.root))
        self.assertEqual(out["parent"], os.path.dirname(os.path.abspath(self.root)))

    def test_hidden_entries_skipped_unless_requested(self):
        out = service.browse_fs(self.root, mode="file")
        self.assertNotIn(".hidden_dir", out["dirs"])
        self.assertNotIn(".secret.md", out["files"])
        shown = service.browse_fs(self.root, mode="file", show_hidden=True)
        self.assertIn(".hidden_dir", shown["dirs"])
        self.assertIn(".secret.md", shown["files"])

    def test_file_mode_default_ext_filter_is_case_insensitive(self):
        out = service.browse_fs(self.root, mode="file")
        self.assertIn("Notes.MD", out["files"])
        self.assertIn("readme.txt", out["files"])
        self.assertNotIn("code.py", out["files"])

    def test_file_mode_custom_exts(self):
        out = service.browse_fs(self.root, mode="file", exts=(".py",))
        self.assertEqual(out["files"], ["code.py"])

    def test_errors(self):
        with self.assertRaises(service.ApiError) as ctx:
            service.browse_fs(os.path.join(self.root, "missing"))
        self.assertEqual(ctx.exception.status, 404)
        with self.assertRaises(service.ApiError) as ctx:
            service.browse_fs(os.path.join(self.root, "readme.txt"))
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(service.ApiError) as ctx:
            service.browse_fs(self.root, mode="weird")
        self.assertEqual(ctx.exception.status, 400)

    def test_root_has_no_parent_and_tilde_expands(self):
        root = os.path.abspath(os.sep)
        out = service.browse_fs(root, mode="dir")
        self.assertIsNone(out["parent"])
        home = service.browse_fs("~", mode="dir")
        self.assertEqual(home["path"], os.path.expanduser("~"))

    def test_nearest_walks_up_to_existing_ancestor(self):
        missing = os.path.join(self.root, "new-ws", "deeper")
        with self.assertRaises(service.ApiError):  # strict mode still 404s
            service.browse_fs(missing)
        out = service.browse_fs(missing, mode="dir", nearest=True)
        self.assertEqual(out["path"], os.path.abspath(self.root))

    def test_nearest_on_a_file_opens_its_directory(self):
        fpath = os.path.join(self.root, "readme.txt")
        out = service.browse_fs(fpath, mode="file", nearest=True)
        self.assertEqual(out["path"], os.path.abspath(self.root))
        self.assertIn("readme.txt", out["files"])

    def test_non_utf8_names_are_skipped_not_fatal(self):
        # os.scandir yields PEP-383 surrogate-escaped names for raw
        # non-UTF-8 bytes on byte-oriented filesystems (Linux ext4/NFS);
        # APFS refuses to create them, so fake the scandir result. One such
        # name must not 500 the whole listing via _json's UTF-8 encode.
        class E:
            def __init__(self, name, is_dir):
                self.name = name
                self._is_dir = is_dir

            def is_dir(self, follow_symlinks=True):
                return self._is_dir

        entries = [
            E("bad-\udcff\udcfe", True),
            E("good", True),
            E("bad-\udcff.md", False),
            E("ok.md", False),
        ]

        class FakeScandir:
            def __enter__(self):
                return iter(entries)

            def __exit__(self, *exc):
                return False

        with mock.patch.object(
            service.os, "scandir", return_value=FakeScandir()
        ):
            out = service.browse_fs(self.root, mode="file")
        self.assertEqual(out["dirs"], ["good"])
        self.assertEqual(out["files"], ["ok.md"])
        # the payload must survive the service's JSON response encoding
        json.dumps(out, ensure_ascii=False).encode("utf-8")

    def test_truncation_flag(self):
        old = service.FS_MAX_ENTRIES
        service.FS_MAX_ENTRIES = 1
        try:
            out = service.browse_fs(self.root, mode="dir")
            self.assertEqual(len(out["dirs"]), 1)
            self.assertTrue(out["truncated"])
        finally:
            service.FS_MAX_ENTRIES = old


class RecentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_and_corrupt(self):
        self.assertEqual(
            registry.load_recents(self.home),
            {"workspaces": [], "goal_docs": []},
        )
        with open(registry.recents_path(self.home), "w") as fh:
            fh.write("{broken")
        self.assertEqual(
            registry.load_recents(self.home),
            {"workspaces": [], "goal_docs": []},
        )

    def test_mru_dedupe_and_cap(self):
        registry.remember_recent(self.home, "workspaces", "/a")
        registry.remember_recent(self.home, "workspaces", "/b")
        registry.remember_recent(self.home, "workspaces", "/a")
        rec = registry.load_recents(self.home)
        self.assertEqual(rec["workspaces"], ["/a", "/b"])
        for i in range(registry.RECENTS_MAX + 5):
            registry.remember_recent(self.home, "workspaces", "/w%d" % i)
        rec = registry.load_recents(self.home)
        self.assertEqual(len(rec["workspaces"]), registry.RECENTS_MAX)
        self.assertEqual(rec["workspaces"][0], "/w%d" % (registry.RECENTS_MAX + 4))

    def test_unknown_kind_and_empty_value(self):
        with self.assertRaises(ValueError):
            registry.remember_recent(self.home, "nope", "/x")
        registry.remember_recent(self.home, "workspaces", "")
        self.assertEqual(registry.load_recents(self.home)["workspaces"], [])

    def test_write_failure_is_swallowed(self):
        # recents are convenience: an unwritable home must not raise out of
        # remember_recent (create_run would 500 AFTER registering the run).
        if os.name == "nt":
            self.skipTest("POSIX permission semantics required")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root bypasses directory permissions")
        registry.remember_recent(self.home, "workspaces", "/kept")
        os.chmod(self.home, 0o500)  # mkstemp for the atomic write fails
        try:
            registry.remember_recent(self.home, "workspaces", "/lost")
        finally:
            os.chmod(self.home, 0o700)
        self.assertEqual(
            registry.load_recents(self.home)["workspaces"], ["/kept"]
        )

    def test_recent_paths_merges_registry_workspaces(self):
        registry.remember_recent(self.home, "workspaces", "/recent")
        entry = registry.new_entry("r-x", "x", "/from-registry", "/from-registry/.orchestrator/state.json")
        registry.add(self.home, entry)
        out = service.recent_paths(self.home)
        self.assertEqual(out["workspaces"][0], "/recent")
        self.assertIn("/from-registry", out["workspaces"])


class UiStateTest(unittest.TestCase):
    """Sidebar cosmetics (project order, collapsed groups): tolerant load,
    atomic merge-patch save, same posture as Recents above."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_and_corrupt(self):
        self.assertEqual(
            registry.load_ui_state(self.home),
            {"project_order": [], "collapsed": []},
        )
        with open(registry.ui_state_path(self.home), "w") as fh:
            fh.write("{broken")
        self.assertEqual(
            registry.load_ui_state(self.home),
            {"project_order": [], "collapsed": []},
        )

    def test_non_dict_and_malformed_fields_degrade_to_defaults(self):
        with open(registry.ui_state_path(self.home), "w") as fh:
            json.dump([1, 2, 3], fh)
        self.assertEqual(
            registry.load_ui_state(self.home),
            {"project_order": [], "collapsed": []},
        )
        with open(registry.ui_state_path(self.home), "w") as fh:
            json.dump({"project_order": "not-a-list", "collapsed": [1, "b"]}, fh)
        out = registry.load_ui_state(self.home)
        self.assertEqual(out["project_order"], [])
        self.assertEqual(out["collapsed"], ["b"])  # non-strings filtered

    def test_save_merges_only_present_keys(self):
        registry.save_ui_state(self.home, {"project_order": ["b", "a"]})
        registry.save_ui_state(self.home, {"collapsed": ["b"]})
        self.assertEqual(
            registry.load_ui_state(self.home),
            {"project_order": ["b", "a"], "collapsed": ["b"]},
        )

    def test_save_ignores_malformed_patch_values(self):
        registry.save_ui_state(self.home, {"project_order": ["a"]})
        # A malformed patch value for a key is ignored, not an error, and
        # the prior state for that key survives untouched.
        registry.save_ui_state(self.home, {"project_order": "nope", "collapsed": "nope"})
        self.assertEqual(
            registry.load_ui_state(self.home),
            {"project_order": ["a"], "collapsed": []},
        )
        registry.save_ui_state(self.home, "not-a-dict-either")
        self.assertEqual(
            registry.load_ui_state(self.home),
            {"project_order": ["a"], "collapsed": []},
        )

    def test_write_failure_is_swallowed(self):
        if os.name == "nt":
            self.skipTest("POSIX permission semantics required")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root bypasses directory permissions")
        registry.save_ui_state(self.home, {"project_order": ["kept"]})
        os.chmod(self.home, 0o500)
        try:
            registry.save_ui_state(self.home, {"project_order": ["lost"]})
        finally:
            os.chmod(self.home, 0o700)
        self.assertEqual(
            registry.load_ui_state(self.home)["project_order"], ["kept"]
        )


class FsHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.tree = os.path.join(self.tmp.name, "tree")
        os.makedirs(os.path.join(self.tree, "sub"))
        with open(os.path.join(self.tree, "GOAL.md"), "w") as fh:
            fh.write("# goal doc content\n")
        self.server = service.make_server(self.home, 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def test_fs_endpoint_dir_and_file_modes(self):
        status, data = _get(self.port, "/api/fs?path=%s&mode=dir" % self.tree)
        self.assertEqual(status, 200)
        self.assertEqual(data["dirs"], ["sub"])
        self.assertEqual(data["files"], [])
        status, data = _get(
            self.port, "/api/fs?path=%s&mode=file&ext=.md" % self.tree
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["files"], ["GOAL.md"])

    def test_fs_endpoint_errors_are_json(self):
        status, data = _get(self.port, "/api/fs?path=%s/none" % self.tree)
        self.assertEqual(status, 404)
        self.assertFalse(data["ok"])

    def test_fs_endpoint_nearest_param(self):
        status, data = _get(
            self.port,
            "/api/fs?path=%s/new-ws/deeper&mode=dir&nearest=1" % self.tree,
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["path"], os.path.abspath(self.tree))

    def test_create_survives_recents_write_failure(self):
        # A clobbered recents.json (here: a directory, so os.replace fails)
        # must not 500 the create after the run is already registered.
        os.makedirs(self.home, exist_ok=True)
        os.mkdir(os.path.join(self.home, "recents.json"))
        ws = os.path.join(self.tmp.name, "ws2")
        os.makedirs(ws, exist_ok=True)
        subprocess.run(["git", "init", "-q", ws], check=True)
        status, data = _post(
            self.port,
            "/api/runs",
            {"workspace": ws, "goal": "g", "autostart": False,
             "config": {"verification": []}},
        )
        self.assertEqual(status, 201, data)
        status, data = _get(self.port, "/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["runs"]), 1)
        status, data = _get(self.port, "/api/recents")  # still serves
        self.assertEqual(status, 200)
        self.assertIn(os.path.abspath(ws), data["workspaces"])

    def test_query_string_routing_regression(self):
        status, data = _get(self.port, "/api/runs?refresh=1")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])

    def test_ui_state_flow_get_post_merge(self):
        status, data = _get(self.port, "/api/ui-state")
        self.assertEqual(status, 200)
        self.assertEqual(data["project_order"], [])
        self.assertEqual(data["collapsed"], [])
        status, data = _post(
            self.port, "/api/ui-state", {"project_order": ["proj-b", "proj-a"]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["project_order"], ["proj-b", "proj-a"])
        self.assertEqual(data["collapsed"], [])
        # A later POST touching only "collapsed" leaves project_order intact
        # (merge-patch, not full overwrite).
        status, data = _post(self.port, "/api/ui-state", {"collapsed": ["proj-b"]})
        self.assertEqual(status, 200)
        self.assertEqual(data["project_order"], ["proj-b", "proj-a"])
        self.assertEqual(data["collapsed"], ["proj-b"])
        status, data = _get(self.port, "/api/ui-state")
        self.assertEqual(status, 200)
        self.assertEqual(data["project_order"], ["proj-b", "proj-a"])
        self.assertEqual(data["collapsed"], ["proj-b"])

    def test_recents_flow_via_create(self):
        status, data = _get(self.port, "/api/recents")
        self.assertEqual(status, 200)
        self.assertEqual(data["workspaces"], [])
        ws = os.path.join(self.tmp.name, "ws1")
        os.makedirs(ws, exist_ok=True)
        subprocess.run(["git", "init", "-q", ws], check=True)
        doc = os.path.join(self.tree, "GOAL.md")
        status, data = _post(
            self.port,
            "/api/runs",
            {"workspace": ws, "goal_doc": doc, "autostart": False,
             "config": {"verification": []}},
        )
        self.assertEqual(status, 201, data)
        status, data = _get(self.port, "/api/recents")
        self.assertEqual(status, 200)
        self.assertEqual(data["workspaces"][0], os.path.abspath(ws))
        self.assertEqual(data["goal_docs"][0], os.path.abspath(doc))
        # goal_doc content became the goal
        run_id = None
        _s, runs = _get(self.port, "/api/runs")
        run_id = runs["runs"][0]["id"]
        _s, detail = _get(self.port, "/api/runs/%s" % run_id)
        self.assertEqual(detail["summary"]["goal"], "# goal doc content")

    def test_panel_contains_picker_markup(self):
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/" % self.port, timeout=10
        ) as resp:
            body = resp.read().decode("utf-8")
        for marker in ('id="picker"', 'id="dl_ws"', 'id="dl_doc"', "openPicker"):
            self.assertIn(marker, body)


if __name__ == "__main__":
    unittest.main()
