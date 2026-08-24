"""Focused Slice 04 prompt-set binding and operator-surface contract."""

import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from orchestrator import driver, prompt_sets, registry, service
from orchestrator import state as st


_MISSING = object()


class PromptSetBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-prompt-binding-")
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.server = service.make_server(self.home, 0)
        self.port = self.server.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=body, method=method
        )
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
                content = response.read()
        except urllib.error.HTTPError as exc:
            with exc:
                status = exc.code
                content = exc.read()
        return status, json.loads(content.decode("utf-8"))

    def workspace(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path)
        return path

    def create(self, name, prompt_set=_MISSING, autostart=False):
        workspace = self.workspace(name)
        payload = {
            "workspace": workspace,
            "goal": "Bind one prompt set.",
            "autostart": autostart,
            "config": {"docs_dir": "docs", "git": {"enabled": False}},
        }
        if prompt_set is not _MISSING:
            payload["prompt_set"] = prompt_set
        status, response = self.request("POST", "/api/runs", payload)
        return workspace, status, response

    def entry_state(self, response):
        entry = registry.get(registry.load(self.home), response["run"]["id"])
        return entry, st.load(entry["state_path"])

    def test_new_run_binding_defaults_validates_and_never_resolves(self):
        malformed = Path(prompt_sets.prompt_set_dir(self.home, "malformed"))
        malformed.mkdir()
        (malformed / "shared.json").write_text("{broken", encoding="utf-8")

        with mock.patch.object(
            prompt_sets, "resolve",
            side_effect=AssertionError("launch must not resolve prompt content"),
        ) as resolve:
            for index, (supplied, expected) in enumerate((
                (_MISSING, "default"),
                ("operator", "operator"),
                ("missing", "missing"),
                ("malformed", "malformed"),
            )):
                _workspace, status, response = self.create(
                    "valid-%d" % index, supplied
                )
                self.assertEqual(status, 201, response)
                _entry, state = self.entry_state(response)
                self.assertEqual(state[st.PROMPT_SET_KEY], expected)

            cli_workspace = self.workspace("cli")
            cli_state = os.path.join(cli_workspace, "state.json")
            self.assertEqual(
                driver.main([
                    "init", "--goal", "CLI binding",
                    "--workspace", cli_workspace,
                    "--state", cli_state,
                    "--prompt-set", "operator",
                    "--model-profiles-home", self.home,
                ]),
                0,
            )
            self.assertEqual(st.load(cli_state)[st.PROMPT_SET_KEY], "operator")
            resolve.assert_not_called()

        existing_runs = copy.deepcopy(registry.load(self.home)["runs"])
        invalid_values = (
            None, 7, True, "", "../other", "a.b", "two words", "café"
        )
        with mock.patch.object(service, "start_run") as start:
            for index, invalid in enumerate(invalid_values):
                workspace, status, response = self.create(
                    "invalid-%d" % index, invalid, autostart=True
                )
                self.assertEqual(status, 400, (invalid, response))
                self.assertFalse(os.path.exists(driver.default_state_path(workspace)))
            start.assert_not_called()
        self.assertEqual(registry.load(self.home)["runs"], existing_runs)

        bad_cli_workspace = self.workspace("bad-cli")
        bad_cli_state = os.path.join(bad_cli_workspace, "state.json")
        self.assertEqual(
            driver.main([
                "init", "--goal", "Bad CLI binding",
                "--workspace", bad_cli_workspace,
                "--state", bad_cli_state,
                "--prompt-set", "../other",
                "--model-profiles-home", self.home,
            ]),
            2,
        )
        self.assertFalse(os.path.exists(bad_cli_state))

    def test_attach_and_legacy_binding_are_read_only(self):
        explicit_workspace = self.workspace("explicit-attach")
        explicit_path = os.path.join(explicit_workspace, "state.json")
        driver.init_run(
            "Explicit binding", explicit_workspace, state_path=explicit_path,
            prompt_set="operator",
        )
        explicit_before = Path(explicit_path).read_bytes()
        for supplied in (None, "default", "operator"):
            status, response = self.request("POST", "/api/runs", {
                "workspace": explicit_workspace,
                "state_path": explicit_path,
                "attach": True,
                "autostart": False,
                "prompt_set": supplied,
            })
            self.assertEqual(status, 400, response)
            self.assertIn("attach", response["error"])
        self.assertEqual(Path(explicit_path).read_bytes(), explicit_before)

        status, response = self.request("POST", "/api/runs", {
            "workspace": explicit_workspace,
            "state_path": explicit_path,
            "attach": True,
            "autostart": False,
        })
        self.assertEqual(status, 201, response)
        status, detail = self.request(
            "GET", "/api/runs/%s" % response["run"]["id"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["summary"]["prompt_set"], "operator")
        self.assertEqual(Path(explicit_path).read_bytes(), explicit_before)

        legacy_workspace = self.workspace("legacy-attach")
        legacy_path = os.path.join(legacy_workspace, "state.json")
        legacy = st.new_state(
            "Legacy binding", legacy_workspace, driver.load_config(None)
        )
        legacy.pop(st.PROMPT_SET_KEY)
        st.append_event(legacy, "initialized", goal=legacy["goal"])
        st.save_new(legacy_path, legacy)
        legacy_before = Path(legacy_path).read_bytes()
        status, response = self.request("POST", "/api/runs", {
            "workspace": legacy_workspace,
            "state_path": legacy_path,
            "attach": True,
            "autostart": False,
        })
        self.assertEqual(status, 201, response)
        status, detail = self.request(
            "GET", "/api/runs/%s" % response["run"]["id"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["summary"]["prompt_set"], "default")
        self.assertEqual(Path(legacy_path).read_bytes(), legacy_before)

        unrelated = st.load(legacy_path)
        st.append_event(unrelated, "unrelated_test_event")
        st.save(legacy_path, unrelated)
        self.assertNotIn(st.PROMPT_SET_KEY, st.load(legacy_path))
        rewritten = st.load(legacy_path)
        rewritten[st.PROMPT_SET_KEY] = "operator"
        with self.assertRaisesRegex(st.HistoryRewriteError, "prompt_set"):
            st.save(legacy_path, rewritten)

        rewritten = st.load(explicit_path)
        rewritten[st.PROMPT_SET_KEY] = "default"
        with self.assertRaisesRegex(st.HistoryRewriteError, "prompt_set"):
            st.save(explicit_path, rewritten)

    def test_prompt_set_catalogue_is_names_only_and_fresh(self):
        root = Path(prompt_sets.prompt_sets_dir(self.home))
        for name in ("zed", "operator", "malformed", "bad.name", "two words"):
            (root / name).mkdir()
        broken = root / "malformed" / "shared.json"
        broken.write_text("not json", encoding="utf-8")
        (root / "file_only").write_text("not a directory", encoding="utf-8")
        before = broken.read_bytes()

        with mock.patch.object(
            prompt_sets, "load",
            side_effect=AssertionError("catalogue must not parse documents"),
        ) as load:
            status, response = self.request("GET", "/api/prompt-sets")
            self.assertEqual(status, 200)
            self.assertEqual(set(response), {"ok", "prompt_sets"})
            self.assertEqual(
                response["prompt_sets"],
                ["default", "malformed", "operator", "zed"],
            )

            (root / "alpha").mkdir()
            status, changed = self.request("GET", "/api/prompt-sets")
            self.assertEqual(status, 200)
            self.assertEqual(changed["prompt_sets"][0:2], ["default", "alpha"])
            (root / "alpha").rmdir()
            status, restored = self.request("GET", "/api/prompt-sets")
            self.assertEqual(status, 200)
            self.assertNotIn("alpha", restored["prompt_sets"])
            load.assert_not_called()
        self.assertEqual(broken.read_bytes(), before)

    def test_run_detail_projects_binding_and_canonical_plan_in_delivery_order(self):
        _workspace, status, response = self.create("detail", "operator")
        self.assertEqual(status, 201, response)
        entry, state = self.entry_state(response)
        projected = [
            {
                "id": 20,
                "title": "First delivered",
                "intent": "This appears first despite its larger id.",
                "material": "docs",
                "producer_task_executor": {
                    "draft_slice_note": {"task_executor": "agent_call"},
                    "implement": {"task_executor": "agent_call"},
                },
            },
            {
                "id": 3,
                "title": "Second delivered",
                "intent": "This appears second.",
                "producer_task_executor": {
                    "draft_slice_note": {"task_executor": "agent_call"},
                    "implement": {"task_executor": "agent_call"},
                },
            },
        ]
        state["milestone"]["slices"] = projected
        st.save(entry["state_path"], state)
        before = Path(entry["state_path"]).read_bytes()

        status, detail = self.request(
            "GET", "/api/runs/%s" % response["run"]["id"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["summary"]["prompt_set"], "operator")
        self.assertEqual(detail["summary"]["slices"], projected)
        self.assertEqual(
            [item["id"] for item in detail["summary"]["slices"]], [20, 3]
        )
        self.assertNotIn("plan_authoring_authorized", detail["summary"])
        self.assertEqual(Path(entry["state_path"]).read_bytes(), before)
        status, _response = self.request(
            "POST", "/api/runs/%s/plan" % response["run"]["id"], {}
        )
        self.assertEqual(status, 404)

    def test_panel_prompt_set_selector_and_plan_projection_are_server_driven(self):
        panel = (
            Path(__file__).resolve().parents[1] / "static" / "panel.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="f_prompt_set"', panel)
        self.assertEqual(panel.count('api("/api/prompt-sets")'), 1)
        self.assertIn(
            'payload.prompt_set = document.getElementById("f_prompt_set").value',
            panel,
        )
        self.assertIn('select.value = "default"', panel)
        self.assertIn("prompt set: ${esc(sum.prompt_set)}", panel)
        self.assertIn("${esc(sl.intent)}", panel)
        self.assertIn("(sum.slices || []).forEach(sl =>", panel)
        self.assertNotIn("sort((a, b) => a.id - b.id)", panel)
        self.assertNotIn("^[A-Za-z0-9_-]+$", panel)
        self.assertIn("openProducerTask(${sliceId},'draft_slice_note')", panel)
        self.assertIn("openSliceMaterial(${sliceId})", panel)


if __name__ == "__main__":
    unittest.main()
