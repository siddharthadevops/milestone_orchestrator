"""Focused executable evidence for Brainstorming Slice 06."""

import contextlib
import copy
import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from orchestrator import access
from orchestrator import brainstorming as bs
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import brainstorming_tasks as task_adapter
from orchestrator import registry, runners, service, state, tasks, workareas


def closing_summary():
    return {
        "reason": "The participants completed the bounded discussion.",
        "unresolved_objections": [],
        "affected_parties": "The people using the requested target.",
        "damage_altitude": "A bounded and reversible consequence.",
        "proportionality": "The discussion matched the decision.",
        "escalation_evidence": None,
        "open_questions": [],
    }


class StandaloneBrainstormingApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="brainstorming-api-")
        self.home = os.path.join(self.tmp.name, "home")
        self.workspace = os.path.join(self.tmp.name, "workspace")
        os.makedirs(self.home)
        os.makedirs(os.path.join(self.workspace, "docs"))
        self.fake_cli = self._write_fake_cli()
        self.config = lifecycle.driver.load_config(None)
        self.config.update(
            {
                "families_order": ["codex", "claude"],
                "commands": {
                    "codex": [
                        self.fake_cli,
                        "exec",
                        "--output-last-message",
                        "{output_file}",
                    ],
                    "claude": [self.fake_cli, "-p"],
                },
                "timeouts": {"codex": 20, "claude": 20},
                "worker_stall_window_s": 0,
                "worker_stall_min_cpu_s": 0,
            }
        )
        self.config_patch = mock.patch.object(
            lifecycle.driver,
            "load_config",
            side_effect=lambda _path=None: copy.deepcopy(self.config),
        )
        self.config_patch.start()
        self.processes = []
        self.server = service.make_server(self.home, 0)
        self.port = self.server.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        try:
            document = lifecycle._load_registry(self.home)
        except Exception:
            document = {"sessions": []}
        for record in document["sessions"]:
            pid = record.get("pid")
            if pid:
                self._kill_pid(pid)
        for process in self.processes:
            if process.poll() is None:
                self._kill_pid(process.pid)
            try:
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        with lifecycle._CHILDREN_LOCK:
            for pid, (home, _session_id, _process) in list(
                lifecycle._CHILDREN.items()
            ):
                if home == os.path.abspath(self.home):
                    lifecycle._CHILDREN.pop(pid, None)
        self.config_patch.stop()
        self.tmp.cleanup()

    def _write_fake_cli(self):
        path = os.path.join(self.tmp.name, "fake-brainstorming-cli")
        source = """\
        #!/usr/bin/env python3
        import json
        import os
        import re
        import subprocess
        import sys
        import time
        import uuid

        args = sys.argv[1:]
        prompt = sys.stdin.read()
        codex = bool(args and args[0] == "exec")
        codex_resume = codex and len(args) > 1 and args[1] == "resume"
        output_path = None
        if codex:
            output_path = args[args.index("--output-last-message") + 1]
            if not codex_resume:
                print(json.dumps({
                    "type": "thread.started",
                    "thread_id": str(uuid.uuid4()),
                }), flush=True)

        target_match = re.search(r"^- target_path: (.+)$", prompt, re.M)
        target_name = target_match.group(1).strip() if target_match else ""
        discussion = 'kind "discussion_turn"' in prompt
        proposal = 'kind: "closure_proposal"' in prompt
        vote = 'kind "closure_vote"' in prompt

        if (
            discussion
            and target_name.endswith("error.md")
            and "- role: contrary_position" in prompt
        ):
            sys.exit(7)

        if (
            discussion
            and target_name.endswith("recoverable.md")
            and "- role: contrary_position" in prompt
        ):
            counter_path = os.path.join(os.getcwd(), ".recoverable-calls")
            try:
                with open(counter_path, "r", encoding="utf-8") as handle:
                    count = int(handle.read())
            except (OSError, ValueError):
                count = 0
            count += 1
            with open(counter_path, "w", encoding="utf-8") as handle:
                handle.write(str(count))
            if count <= 3:
                rendered = "API Error: 529 Overloaded"
                if output_path:
                    with open(output_path, "w", encoding="utf-8") as handle:
                        handle.write(rendered)
                else:
                    print(rendered, flush=True)
                sys.exit(0)

        if (
            discussion
            and target_name.endswith("slow.md")
            and "- role: initial_position" in prompt
        ):
            target = (
                target_name
                if os.path.isabs(target_name)
                else os.path.join(os.getcwd(), target_name)
            )
            with open(target, "wb") as handle:
                handle.write(b"mutated by in-flight lead")
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(120)"]
            )
            with open(
                os.path.join(os.getcwd(), "slow-child.pid"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(str(child.pid))
            time.sleep(120)

        summary = {
            "reason": "The participants completed the bounded discussion.",
            "unresolved_objections": [],
            "affected_parties": "The people using the requested target.",
            "damage_altitude": "A bounded and reversible consequence.",
            "proportionality": "The discussion matched the decision.",
            "escalation_evidence": None,
            "open_questions": [],
        }
        if discussion:
            answer = {"kind": "discussion_turn", "markdown": "Accepted turn."}
            if (
                target_name.endswith("relative.md")
                and "- role: initial_position" in prompt
            ):
                target = (
                    target_name
                    if os.path.isabs(target_name)
                    else os.path.join(os.getcwd(), target_name)
                )
                with open(target, "wb") as handle:
                    handle.write(b"accepted lead result")
            if (
                target_name.endswith("replacement.md")
                and "- role: initial_position" in prompt
            ):
                target = (
                    target_name
                    if os.path.isabs(target_name)
                    else os.path.join(os.getcwd(), target_name)
                )
                temporary = target + ".lead-replacement"
                with open(temporary, "wb") as handle:
                    handle.write(b"accepted replacement")
                os.replace(temporary, target)
        elif proposal:
            proposes = True
            if target_name.endswith("decline-once.md"):
                counter_path = os.path.join(
                    os.getcwd(), ".decline-closure-calls"
                )
                try:
                    with open(counter_path, "r", encoding="utf-8") as handle:
                        count = int(handle.read())
                except (OSError, ValueError):
                    count = 0
                count += 1
                with open(counter_path, "w", encoding="utf-8") as handle:
                    handle.write(str(count))
                proposes = count > 1
            answer = {
                "kind": "closure_proposal",
                "propose": proposes,
                "closing_summary": summary,
            }
        elif vote:
            answer = {
                "kind": "closure_vote",
                "vote": "object" if target_name.endswith("failure.md") else "accept",
            }
        else:
            answer = {"kind": "discussion_turn", "markdown": "Accepted turn."}

        if target_name.endswith("repair.md") and "REPAIR:" not in prompt:
            rendered = "malformed"
        else:
            rendered = json.dumps(answer)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            print(rendered, flush=True)
        """
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(source))
        os.chmod(path, 0o755)
        return path

    def _target(self, name, content=b"initial target"):
        path = os.path.join(self.workspace, "docs", name)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def _payload(
        self,
        target_name,
        *,
        workspace=None,
        max_rounds=1,
        project=None,
        work_area=None,
    ):
        payload = {
            "request": {
                "workspace_path": workspace or self.workspace,
                "target_path": "docs/%s" % target_name,
                "request": "Select the bounded result to accept.",
                "context": {
                    "brief": "Resolve one bounded request.",
                    "source_payload": {"opaque": ["preserved", 7]},
                },
                "max_rounds": max_rounds,
            },
            "participants": [
                {"id": "lead", "role": "initial_position", "delivery": "llm"},
                {
                    "id": "critic",
                    "role": "contrary_position",
                    "delivery": "llm",
                },
            ],
            "closure_policy": "unanimity",
        }
        if project is not None:
            payload["project"] = project
            payload["work_area"] = work_area
        return payload

    def _request(self, method, path, payload=None, headers=None, raw=None):
        data = raw
        if data is None and payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method=method
        )
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw_body = response.read()
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except ValueError:
                    body = raw_body
                return response.status, body
        except urllib.error.HTTPError as exc:
            with exc:
                return (
                    exc.code,
                    json.loads(exc.read().decode("utf-8")),
                )

    @staticmethod
    def _remote_headers(email):
        return {
            "Host": "example.ngrok-free.dev",
            access.REMOTE_HEADER: access.REMOTE_MARKER,
            access.USER_HEADER: email,
        }

    def _sleeper_launcher(self, _home, _session_id):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.processes.append(process)

        def abort():
            self._kill_pid(process.pid)

        return lifecycle.GatedLaunch(process, lambda: None, abort)

    @staticmethod
    def _kill_pid(pid):
        if not pid:
            return
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                return
        try:
            os.waitpid(pid, 0)
        except (ChildProcessError, OSError):
            pass

    def _stop_sleeper_record(self, session_id):
        record = lifecycle._record_by_id(self.home, session_id)
        pid = record.get("pid")
        if pid:
            self._kill_pid(pid)
            lifecycle._clear_pid(self.home, session_id, pid)
        return lifecycle._record_by_id(self.home, session_id)

    def _poll_terminal(self, session_id, budget=20):
        deadline = time.monotonic() + budget
        last_revision = 0
        while time.monotonic() < deadline:
            status, body = self._request(
                "GET", "/api/brainstorming/sessions/%s" % session_id
            )
            self.assertEqual(status, 200, body)
            session = body["session"]
            self.assertGreaterEqual(session["revision"], last_revision)
            last_revision = session["revision"]
            if (
                session["state"]["status"] in bs.TERMINAL_STATUSES
                and session["process"] == "stopped"
            ):
                return session
            time.sleep(0.05)
        self.fail("Brainstorming session did not reach a stopped result")

    def _ready_project(
        self,
        slug="project",
        area="main",
        workspace=None,
        additional=None,
        users=None,
    ):
        workspace = workspace or self.workspace
        additional = additional or []
        service.create_project(self.home, {"slug": slug})
        if users is not None:
            service.update_project_users(
                self.home, slug, {"users": users}
            )
        view = service.declare_work_area(
            self.home,
            slug,
            {
                "name": area,
                "primary_path": workspace,
                "additional_paths": additional,
            },
        )
        record = view["record"]
        confirmed = service._work_area_store(self.home, slug).confirm(
            area,
            record["primary"],
            record["additional"],
            service._executor_id(self.home),
        )
        self.assertTrue(confirmed.ok)
        return registry.get_project(
            registry.load_projects_record(self.home), slug
        )

    def test_create_runs_without_a_milestone_and_resolves_roster(self):
        self._target("create.md")
        self._target("fallback.md")
        self._target("workspace-command.md")
        launch_count = []

        def launcher(home, session_id):
            launch_count.append(session_id)
            return self._sleeper_launcher(home, session_id)

        with mock.patch.object(
            lifecycle, "_launch_lifecycle_process", side_effect=launcher
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("create.md"),
            )
            self.assertEqual(status, 201, body)
            session = body["session"]
            self.assertEqual(
                set(session),
                {
                    "id",
                    "caller",
                    "project",
                    "work_area",
                    "process",
                    "revision",
                    "state",
                    "activity",
                    "work_duration_s",
                    "work_token_usage",
                    "work_token_usage_partial",
                    "work_cost",
                    "work_cost_partial",
                    "last_action_epoch",
                    "in_flight",
                    "retry",
                    "external_intervention",
                },
            )
            self.assertEqual(session["activity"], [])
            self.assertEqual(session["work_duration_s"], 0)
            self.assertGreater(session["last_action_epoch"], 0)
            self.assertIsNone(session["in_flight"])
            self.assertIsNone(session["retry"])
            self.assertIsNone(session["external_intervention"])
            self.assertEqual(session["process"], "running")
            self.assertIsNone(session["project"])
            self.assertIsNone(session["work_area"])
            roster = session["state"]["run_config"]["participants"]
            self.assertEqual([item["id"] for item in roster], ["lead", "critic"])
            self.assertEqual(
                {item["model_family"] for item in roster},
                {"codex", "claude"},
            )
            self.assertFalse(
                session["state"]["run_config"]["same_family_fallback"]
            )

            original_order = self.config["families_order"]
            self.config["families_order"] = ["codex"]
            try:
                status2, body2 = self._request(
                    "POST",
                    "/api/brainstorming/sessions",
                    self._payload("fallback.md"),
                )
            finally:
                self.config["families_order"] = original_order
            self.assertEqual(status2, 201, body2)
            self.assertTrue(
                body2["session"]["state"]["run_config"][
                    "same_family_fallback"
                ]
            )

            tools = os.path.join(self.workspace, "tools")
            os.makedirs(tools)
            workspace_cli = os.path.join(tools, "brainstorming-cli")
            os.symlink(self.fake_cli, workspace_cli)
            original_commands = self.config["commands"]
            original_order = self.config["families_order"]
            self.config["commands"] = {
                "codex": [
                    "tools/brainstorming-cli",
                    "exec",
                    "--output-last-message",
                    "{output_file}",
                ],
                "claude": [
                    "{workspace}/tools/brainstorming-cli",
                    "-p",
                ],
            }
            self.config["families_order"] = ["codex", "claude"]
            try:
                status3, body3 = self._request(
                    "POST",
                    "/api/brainstorming/sessions",
                    self._payload("workspace-command.md"),
                )
            finally:
                self.config["commands"] = original_commands
                self.config["families_order"] = original_order
            self.assertEqual(status3, 201, body3)
            self.assertEqual(
                {
                    participant["model_family"]
                    for participant in body3["session"]["state"][
                        "run_config"
                    ]["participants"]
                },
                {"codex", "claude"},
            )

        self.assertEqual(len(launch_count), 3)
        self.assertEqual(registry.load(self.home)["runs"], [])
        self.assertFalse(os.path.exists(registry.registry_path(self.home)))
        self.assertFalse(os.path.exists(os.path.join(self.workspace, ".git")))

    def test_create_honors_pinned_seats_and_records_per_seat_executors(self):
        """Panel-configured seats: pinned family/model/effort per seat."""
        self._target("pinned.md")
        self._target("mono.md")
        payload = self._payload("pinned.md")
        payload["participants"] = [
            {
                "id": "lead",
                "role": "initial_position",
                "delivery": "llm",
                "model_family": "claude",
                # Deliberately NOT the claude family default (opus-5), so
                # the pinned seat stays distinguishable from a default one.
                "model": "claude-fable-5",
                "effort": "max",
            },
            {
                "id": "critic-1",
                "role": "contrary_position",
                "delivery": "llm",
                "model_family": "claude",
            },
            {
                "id": "critic-2",
                "role": "contrary_position",
                "delivery": "llm",
            },
        ]
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST", "/api/brainstorming/sessions", payload
            )
            self.assertEqual(status, 201, body)
            roster = body["session"]["state"]["run_config"]["participants"]
            by_id = {item["id"]: item for item in roster}
            self.assertEqual(by_id["lead"]["model_family"], "claude")
            self.assertEqual(by_id["critic-1"]["model_family"], "claude")
            # The unpinned seat keeps the historical rotation: it is the
            # first unpinned seat, so it takes the first available family.
            self.assertEqual(by_id["critic-2"]["model_family"], "codex")
            # Executor refs are per SEAT so two same-family seats can run
            # different models; the recorded runtime carries each seat's
            # resolved model/effort (pin wins, family default otherwise).
            record = lifecycle._record_by_id(
                self.home, body["session"]["id"]
            )
            executors = record["runtime"]["executors"]
            self.assertEqual(
                set(executors),
                {item["executor_ref"] for item in roster},
            )
            lead_seat = executors[by_id["lead"]["executor_ref"]]
            self.assertEqual(
                lead_seat,
                {
                    "model_family": "claude",
                    "model": "claude-fable-5",
                    "effort": "max",
                },
            )
            critic1 = executors[by_id["critic-1"]["executor_ref"]]
            self.assertEqual(critic1["model"], "claude-opus-5")
            self.assertEqual(critic1["effort"], "xhigh")

            # Every seat pinned to ONE family while another is available
            # is a deliberate roster, not an invalid fallback.
            mono = self._payload("mono.md")
            mono["participants"] = [
                {
                    "id": "lead",
                    "role": "initial_position",
                    "delivery": "llm",
                    "model_family": "claude",
                },
                {
                    "id": "critic",
                    "role": "contrary_position",
                    "delivery": "llm",
                    "model_family": "claude",
                },
            ]
            status, mono_body = self._request(
                "POST", "/api/brainstorming/sessions", mono
            )
            self.assertEqual(status, 201, mono_body)
            self.assertTrue(
                mono_body["session"]["state"]["run_config"][
                    "same_family_fallback"
                ]
            )

        # A family this host cannot staff is a request fault — typed and
        # side-effect free.
        bad = self._payload("pinned.md")
        bad["participants"] = [
            {
                "id": "lead",
                "role": "initial_position",
                "delivery": "llm",
                "model_family": "gemini",
            },
            {
                "id": "critic",
                "role": "contrary_position",
                "delivery": "llm",
            },
        ]
        status, refusal = self._request(
            "POST", "/api/brainstorming/sessions", bad
        )
        self.assertEqual(status, 400, refusal)
        self.assertEqual(refusal["error"], lifecycle.INVALID_REQUEST)

    def test_pinning_the_rotation_family_never_herds_default_seats(self):
        """A pin on families[0] must not drag a default seat onto it.

        The pin-blind rotation would staff both seats codex and the
        sealed cross-family rule would refuse a fully satisfiable
        request; the default seat has to diversify instead — in either
        seat order.
        """
        for index, (name, roster) in enumerate((
            ("codex-lead.md", [
                {
                    "id": "lead",
                    "role": "initial_position",
                    "delivery": "llm",
                    "model_family": "codex",
                },
                {
                    "id": "critic",
                    "role": "contrary_position",
                    "delivery": "llm",
                },
            ]),
            ("codex-critic.md", [
                {"id": "lead", "role": "initial_position", "delivery": "llm"},
                {"id": "critic", "role": "contrary_position", "delivery": "llm",
                 "model_family": "codex"},
            ]),
        )):
            self._target(name)
            payload = self._payload(name)
            payload["participants"] = roster
            with mock.patch.object(
                lifecycle,
                "_launch_lifecycle_process",
                side_effect=self._sleeper_launcher,
            ):
                status, body = self._request(
                    "POST", "/api/brainstorming/sessions", payload
                )
            self.assertEqual(status, 201, body)
            resolved = {
                item["id"]: item["model_family"]
                for item in body["session"]["state"]["run_config"][
                    "participants"
                ]
            }
            pinned_id = "lead" if index == 0 else "critic"
            free_id = "critic" if index == 0 else "lead"
            self.assertEqual(resolved[pinned_id], "codex")
            self.assertEqual(resolved[free_id], "claude")
            self.assertFalse(
                body["session"]["state"]["run_config"][
                    "same_family_fallback"
                ]
            )

    def test_discard_created_dirs_spares_any_adopting_sibling(self):
        """Compensation never removes folders a live session lives in."""
        fresh = os.path.join(self.workspace, "shared", "notes")
        payload = self._payload("unused.md")
        payload["request"]["target_path"] = "shared/notes/OTHER.md"
        payload["create_target_parents"] = True
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST", "/api/brainstorming/sessions", payload
            )
        self.assertEqual(status, 201, body)
        self.assertTrue(os.path.isdir(fresh))

        # A failed sibling create (same fresh folders, DIFFERENT target
        # file) must leave the adopted folders alone...
        lifecycle._discard_created_dirs(
            self.home,
            os.path.join(fresh, "DECISION.md"),
            [fresh, os.path.dirname(fresh)],
        )
        self.assertTrue(os.path.isdir(fresh))

        # ...and once no registered session lives under them, the same
        # compensation removes exactly those (empty) folders.
        self._stop_sleeper_record(body["session"]["id"])
        lifecycle._save_registry(self.home, lifecycle._new_registry())
        lifecycle._discard_created_dirs(
            self.home,
            os.path.join(fresh, "DECISION.md"),
            [fresh, os.path.dirname(fresh)],
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.workspace, "shared"))
        )

    def test_delete_session_forgets_frees_target_and_optionally_purges(self):
        """Operator deletion: forget, free the target, purge on request."""
        target = self._target("deletable.md", b"kept bytes")
        store = lifecycle.brainstorming.SessionStore(
            lifecycle.state_directory(self.home)
        )

        status, unknown = self._request(
            "DELETE", "/api/brainstorming/sessions/bs-missing"
        )
        self.assertEqual(status, 404, unknown)
        self.assertEqual(unknown["error"], lifecycle.UNKNOWN_SESSION)

        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, first = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("deletable.md"),
            )
            self.assertEqual(status, 201, first)
            first_id = first["session"]["id"]

            # Running refuses; nothing is forgotten.
            status, refused = self._request(
                "DELETE", "/api/brainstorming/sessions/%s" % first_id
            )
            self.assertEqual(status, 409, refused)
            self.assertEqual(refused["error"], lifecycle.SESSION_RUNNING)
            self._stop_sleeper_record(first_id)

            # Forget WITHOUT purge: the record is gone (the list no longer
            # shows it, the target is free again) but durable state stays
            # readable — a milestone replaying a retained revision keeps
            # its evidence.
            status, forgotten = self._request(
                "DELETE", "/api/brainstorming/sessions/%s" % first_id
            )
            self.assertEqual(status, 200, forgotten)
            self.assertEqual(
                (forgotten["deleted"], forgotten["purged"]),
                (first_id, False),
            )
            status, listed = self._request(
                "GET", "/api/brainstorming/sessions"
            )
            self.assertEqual(listed["sessions"], [])
            self.assertIsNotNone(store.read(first_id))
            status, gone = self._request(
                "GET", "/api/brainstorming/sessions/%s" % first_id
            )
            self.assertEqual(status, 404, gone)

            # The freed target admits a NEW session; purge deletion then
            # removes the whole durable footprint.
            status, second = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("deletable.md"),
            )
            self.assertEqual(status, 201, second)
            second_id = second["session"]["id"]
            self._stop_sleeper_record(second_id)
            transcript = store.transcript_ref(second_id)
            prompt_path = runners.save_prompt_trace(
                store.prompt_directory(second_id),
                "codex",
                "exact discarded prompt",
                label="turn-1",
            )
            self.assertTrue(os.path.exists(prompt_path))
            status, purged = self._request(
                "DELETE",
                "/api/brainstorming/sessions/%s?purge=1" % second_id,
            )
            self.assertEqual(status, 200, purged)
            self.assertTrue(purged["purged"])
            self.assertIsNone(store.read(second_id))
            self.assertFalse(os.path.exists(prompt_path))
            self.assertFalse(os.path.exists(os.path.dirname(transcript)))

        # The target artifact was never touched by any of it.
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"kept bytes")

    def test_delete_refuses_while_a_stop_is_reconciling(self):
        """A stop mid-reconcile owns the target; deletion must wait."""
        self._target("stopping.md")
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("stopping.md"),
            )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]
        self._stop_sleeper_record(session_id)

        token = (os.path.abspath(self.home), session_id)
        with lifecycle._STOPS_GUARD:
            lifecycle._STOPS_IN_FLIGHT.add(token)
        try:
            status, refused = self._request(
                "DELETE", "/api/brainstorming/sessions/%s" % session_id
            )
        finally:
            with lifecycle._STOPS_GUARD:
                lifecycle._STOPS_IN_FLIGHT.discard(token)
        self.assertEqual(status, 409, refused)
        self.assertEqual(refused["error"], lifecycle.SESSION_RUNNING)

        # A completed stop always clears its announcement — even one that
        # refused — so deletion works right after.
        status, stopped = self._request(
            "POST", "/api/brainstorming/sessions/%s/stop" % session_id
        )
        self.assertEqual(status, 200, stopped)
        with lifecycle._STOPS_GUARD:
            self.assertNotIn(token, lifecycle._STOPS_IN_FLIGHT)
        status, deleted = self._request(
            "DELETE",
            "/api/brainstorming/sessions/%s?purge=1" % session_id,
        )
        self.assertEqual(status, 200, deleted)

    def test_projection_racing_a_purge_tidies_its_own_recreation(self):
        """A reader past its pre-check must not strand the purged folder."""
        self._target("raced.md")
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("raced.md"),
            )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]
        self._stop_sleeper_record(session_id)
        store = lifecycle.brainstorming.SessionStore(
            lifecycle.state_directory(self.home)
        )
        transcript = store.transcript_ref(session_id)
        bs_module = lifecycle.brainstorming
        real_exclusive = bs_module._exclusive_transcript
        raced = []

        @contextlib.contextmanager
        def racing(path):
            # The discard lands exactly between the reader's pre-check
            # and its lock acquisition — the reviewed race, made
            # deterministic. Taking the real lock below recreates the
            # folder; the reader's absent-under-lock branch must tidy it.
            if os.path.abspath(path) == transcript and not raced:
                raced.append(1)
                store.discard_session(session_id)
            with real_exclusive(path):
                yield

        with mock.patch.object(bs_module, "_exclusive_transcript", racing):
            self.assertIsNone(store.read(session_id))
        self.assertTrue(raced)
        self.assertFalse(os.path.exists(os.path.dirname(transcript)))

    def test_delete_session_is_authorized_like_the_other_routes(self):
        self._target("guarded.md")
        self._ready_project(users=["jdcf1710@gmail.com"])
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload(
                    "guarded.md", project="project", work_area="main"
                ),
            )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]
        self._stop_sleeper_record(session_id)

        # An unassigned user cannot delete; the assigned member can.
        status, refused = self._request(
            "DELETE",
            "/api/brainstorming/sessions/%s" % session_id,
            headers=self._remote_headers("isabelmariaandresruiz@gmail.com"),
        )
        self.assertEqual(status, 403, refused)
        status, deleted = self._request(
            "DELETE",
            "/api/brainstorming/sessions/%s?purge=1" % session_id,
            headers=self._remote_headers("jdcf1710@gmail.com"),
        )
        self.assertEqual(status, 200, deleted)

    def test_list_route_surfaces_broken_standing_access_as_503(self):
        """A standing-access fault must never render as "no sessions"."""
        self._target("visible.md")
        self._ready_project(users=["jdcf1710@gmail.com"])
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload(
                    "visible.md", project="project", work_area="main"
                ),
            )
        self.assertEqual(status, 201, body)
        with mock.patch.object(
            service.registry,
            "load_projects_record",
            side_effect=RuntimeError("standing access state unreadable"),
        ):
            status, refused = self._request(
                "GET",
                "/api/brainstorming/sessions",
                headers=self._remote_headers("jdcf1710@gmail.com"),
            )
        self.assertEqual(status, 503, refused)
        self.assertEqual(refused["error"], lifecycle.UNAVAILABLE)

    def test_deliver_chat_is_opt_in_and_typed(self):
        """Handing the chat over is the operator's explicit choice."""
        self._target("chat-flag.md")
        self._target("chat-default.md")
        payload = self._payload("chat-flag.md")
        payload["request"]["deliver_chat"] = "yes"
        status, refusal = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 400, refusal)
        self.assertEqual(refusal["error"], lifecycle.INVALID_REQUEST)

        payload["request"]["deliver_chat"] = True
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST", "/api/brainstorming/sessions", payload
            )
            self.assertEqual(status, 201, body)
            self.assertIs(
                body["session"]["state"]["request"]["deliver_chat"], True
            )

            # The default is absence, not a stored false: a session that
            # never asked carries no key at all.
            status, plain = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("chat-default.md"),
            )
            self.assertEqual(status, 201, plain)
            self.assertNotIn(
                "deliver_chat", plain["session"]["state"]["request"]
            )

    def test_create_target_parents_makes_and_compensates_folders(self):
        """The panel's New… flow: fresh session folders, made at launch."""
        deep = os.path.join(
            self.workspace, "brainstorming", "bs-20260726", "DECISION.md"
        )
        payload = self._payload("unused.md")
        payload["request"]["target_path"] = (
            "brainstorming/bs-20260726/DECISION.md"
        )

        # Without the opt-in, the historical refusal stands and nothing
        # is created.
        status, refusal = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 400, refusal)
        self.assertEqual(refusal["error"], lifecycle.INVALID_REQUEST)
        self.assertFalse(
            os.path.exists(os.path.join(self.workspace, "brainstorming"))
        )

        # A non-boolean flag is a typed request fault.
        payload["create_target_parents"] = "yes"
        status, refusal = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 400, refusal)
        self.assertEqual(refusal["error"], lifecycle.INVALID_REQUEST)

        # A launch failure after mkdir compensates: the folders this
        # create added are removed again.
        payload["create_target_parents"] = True
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=RuntimeError("no launcher"),
        ):
            status, refusal = self._request(
                "POST", "/api/brainstorming/sessions", payload
            )
        self.assertEqual(status, 503, refusal)
        self.assertFalse(
            os.path.exists(os.path.join(self.workspace, "brainstorming"))
        )

        # The successful create makes the folders and pins the target.
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST", "/api/brainstorming/sessions", payload
            )
            self.assertEqual(status, 201, body)
            self.assertTrue(os.path.isdir(os.path.dirname(deep)))
            record = lifecycle._record_by_id(
                self.home, body["session"]["id"]
            )
            self.assertEqual(record["target_path"], deep)

            # A second create against the same fresh folder finds the
            # target in use — and must NOT remove the live session's
            # folder on its way out.
            status, clash = self._request(
                "POST", "/api/brainstorming/sessions", payload
            )
        self.assertEqual(status, 409, clash)
        self.assertEqual(clash["error"], lifecycle.TARGET_IN_USE)
        self.assertTrue(os.path.isdir(os.path.dirname(deep)))

    def test_create_target_parents_stays_inside_bound_root(self):
        """Containment is judged before any folder is made."""
        self._ready_project()
        outside = os.path.join(self.tmp.name, "escape", "DECISION.md")
        payload = self._payload(
            "unused.md", project="project", work_area="main"
        )
        payload["request"]["target_path"] = outside
        payload["create_target_parents"] = True
        status, refusal = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 400, refusal)
        self.assertEqual(refusal["error"], lifecycle.INVALID_REQUEST)
        self.assertFalse(
            os.path.exists(os.path.join(self.tmp.name, "escape"))
        )

    def test_create_needs_no_prior_milestone_and_no_repository(self):
        """A discussion runs in a work area declared moments ago.

        The area is `pending` — no milestone has ever launched here — and
        its primary root is a plain directory, not a git repository.
        Brainstorming writes no gate ledger, so neither fact is its
        business; what it verifies is that the roots are there. The
        create also records what it found, so the operator sees a status
        that describes this host rather than one waiting for a milestone
        to write it.
        """
        self._target("no-milestone.md")
        service.create_project(self.home, {"slug": "fresh"})
        service.declare_work_area(
            self.home,
            "fresh",
            {"name": "main", "primary_path": self.workspace},
        )
        store = service._work_area_store(self.home, "fresh")
        self.assertEqual(store.read("main").value["status"], "pending")
        self.assertFalse(
            os.path.isdir(os.path.join(self.workspace, ".git"))
        )

        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload(
                    "no-milestone.md", project="fresh", work_area="main"
                ),
            )
        self.assertEqual(status, 201, body)
        self.assertEqual(body["session"]["work_area"], "main")
        self.assertEqual(store.read("main").value["status"], "ready")

    def test_create_reports_the_missing_root_not_a_stored_status(self):
        """The refusal names what is wrong, and the record agrees."""
        ghost = os.path.join(self.tmp.name, "ghost-root")
        service.create_project(self.home, {"slug": "ghosted"})
        service.declare_work_area(
            self.home,
            "ghosted",
            {"name": "main", "primary_path": ghost},
        )
        payload = self._payload(
            "unused.md", workspace=ghost, project="ghosted", work_area="main"
        )
        status, refusal = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 400, refusal)
        self.assertEqual(refusal["error"], "missing_primary_path")
        record = service._work_area_store(self.home, "ghosted").read("main")
        self.assertEqual(record.value["status"], "unavailable")
        self.assertFalse(os.path.exists(ghost))

    def test_create_refusals_are_typed_and_side_effect_free(self):
        target = self._target("refusal.md")
        launch_count = []

        def launcher(home, session_id):
            launch_count.append(session_id)
            return self._sleeper_launcher(home, session_id)

        invalid = self._payload("refusal.md")
        invalid["unexpected"] = True
        with mock.patch.object(
            lifecycle, "_launch_lifecycle_process", side_effect=launcher
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                raw=b"not-json",
            )
            self.assertEqual(
                (status, body),
                (
                    400,
                    {"ok": False, "error": lifecycle.INVALID_REQUEST},
                ),
            )
            status, body = self._request(
                "POST", "/api/brainstorming/sessions", invalid
            )
            self.assertEqual(
                (status, body),
                (
                    400,
                    {"ok": False, "error": lifecycle.INVALID_REQUEST},
                ),
            )
            self.assertEqual(launch_count, [])

            invalid_path = self._payload("refusal.md")
            invalid_path["request"]["target_path"] = "docs/invalid\x00.md"
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                invalid_path,
            )
            self.assertEqual(
                (status, body),
                (
                    400,
                    {"ok": False, "error": lifecycle.INVALID_REQUEST},
                ),
            )
            self.assertEqual(launch_count, [])

            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("refusal.md"),
                headers=self._remote_headers(access.USER_EMAILS[0]),
            )
            self.assertEqual((status, body["error"]), (403, service.FORBIDDEN))
            self.assertEqual(launch_count, [])

            status, created = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("refusal.md"),
            )
            self.assertEqual(status, 201, created)
            self.assertEqual(len(launch_count), 1)

            alias_root = os.path.join(self.tmp.name, "workspace-alias")
            os.symlink(self.workspace, alias_root)
            alias_payload = self._payload(
                "refusal.md", workspace=alias_root
            )
            status, body = self._request(
                "POST", "/api/brainstorming/sessions", alias_payload
            )
            self.assertEqual(
                (status, body["error"]), (409, lifecycle.TARGET_IN_USE)
            )
            self.assertEqual(len(launch_count), 1)

            authority_payload = self._payload("refusal.md")
            authority_payload["request"]["target_path"] = (
                lifecycle.registry_path(self.home)
            )
            status, body = self._request(
                "POST", "/api/brainstorming/sessions", authority_payload
            )
            self.assertEqual(
                (status, body["error"]),
                (400, lifecycle.INVALID_REQUEST),
            )
            self.assertEqual(len(launch_count), 1)

            commands = self.config["commands"]
            self.config["commands"] = {}
            try:
                unavailable = self._payload("refusal.md")
                unavailable["request"]["target_path"] = "docs/new.md"
                status, body = self._request(
                    "POST", "/api/brainstorming/sessions", unavailable
                )
            finally:
                self.config["commands"] = commands
            self.assertEqual(
                (status, body["error"]), (503, lifecycle.UNAVAILABLE)
            )
            self.assertEqual(len(launch_count), 1)

            additional = os.path.join(self.tmp.name, "read-only-additional")
            os.makedirs(additional)
            foreign_target = os.path.join(additional, "foreign.md")
            with open(foreign_target, "wb") as handle:
                handle.write(b"read-only target")
            project = self._ready_project(additional=[additional])
            outside_grant = self._payload(
                "foreign.md",
                project=project["slug"],
                work_area="main",
            )
            outside_grant["request"]["target_path"] = foreign_target
            with mock.patch.object(
                lifecycle.coordination,
                "capture_target",
                wraps=coordination.capture_target,
            ) as capture_target:
                status, body = self._request(
                    "POST",
                    "/api/brainstorming/sessions",
                    outside_grant,
                )
            self.assertEqual(
                (status, body["error"]),
                (400, lifecycle.INVALID_REQUEST),
            )
            capture_target.assert_not_called()
            self.assertEqual(len(launch_count), 1)
            with open(foreign_target, "rb") as handle:
                self.assertEqual(handle.read(), b"read-only target")

        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")
        self.assertEqual(
            len(lifecycle._load_registry(self.home)["sessions"]), 1
        )
        self.assertEqual(registry.load(self.home)["runs"], [])

    def test_relative_workspace_is_bound_once_across_lifecycle_working_directories(self):
        intended = self._target("relative.md")
        runtime_directory = os.path.join(self.tmp.name, "runtime")
        wrong_workspace = os.path.join(runtime_directory, "workspace")
        wrong_target = os.path.join(wrong_workspace, "docs", "relative.md")
        os.makedirs(os.path.dirname(wrong_target))
        with open(wrong_target, "wb") as handle:
            handle.write(b"unrelated artifact")

        original_directory = os.getcwd()
        try:
            os.chdir(self.tmp.name)
            bound_workspace = os.path.abspath("workspace")
            payload = self._payload("relative.md", workspace="workspace")
            created = lifecycle.create_session(
                self.home,
                payload,
                access.ADMIN_EMAIL,
                launcher=self._sleeper_launcher,
            )
            record = self._stop_sleeper_record(created["id"])

            os.chdir(runtime_directory)
            code = lifecycle.run_lifecycle(
                self.home,
                created["id"],
                require_pid_claim=False,
            )
        finally:
            os.chdir(original_directory)

        self.assertEqual(code, 0)
        state = lifecycle.inspect_session(
            self.home, created["id"], lambda _record: None
        )["state"]
        self.assertEqual(state["request"]["workspace_path"], bound_workspace)
        self.assertEqual(
            record["target_path"],
            os.path.join(bound_workspace, "docs", "relative.md"),
        )
        with open(intended, "rb") as handle:
            self.assertEqual(handle.read(), b"accepted lead result")
        with open(wrong_target, "rb") as handle:
            self.assertEqual(handle.read(), b"unrelated artifact")

    def test_declined_proposal_advances_to_the_next_round(self):
        self._target("decline-once.md")
        created = lifecycle.create_session(
            self.home,
            self._payload("decline-once.md", max_rounds=2),
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        self._stop_sleeper_record(created["id"])

        code = lifecycle.run_lifecycle(
            self.home,
            created["id"],
            require_pid_claim=False,
        )

        self.assertEqual(code, 0)
        state = lifecycle.inspect_session(
            self.home, created["id"], lambda _record: None
        )["state"]
        self.assertEqual(state["status"], "success")
        self.assertEqual(state["rounds_used"], 2)
        self.assertEqual(len(state["completed_turns"]), 4)
        with open(
            os.path.join(self.workspace, ".decline-closure-calls"),
            "r",
            encoding="utf-8",
        ) as handle:
            self.assertEqual(handle.read(), "2")

    def test_active_target_identity_does_not_reserve_replaced_inode(self):
        target = self._target("replacement.md")
        unrelated = self._target("unrelated.md", b"unrelated target")
        created = lifecycle.create_session(
            self.home,
            self._payload("replacement.md"),
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        record = self._stop_sleeper_record(created["id"])
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        participant_execution = lifecycle._participant_execution(
            store, record, lifecycle._spawn_participant
        )
        coordinator = coordination.BrainstormingCoordinator(
            store, participant_execution
        )

        progressed = coordinator.run_next_turn(
            created["id"], record["execution_context"]
        )

        self.assertEqual(len(progressed.state["completed_turns"]), 1)
        prompt_directory = store.prompt_directory(created["id"])
        prompt_names = os.listdir(prompt_directory)
        self.assertEqual(len(prompt_names), 1)
        with open(
            os.path.join(prompt_directory, prompt_names[0]),
            "r",
            encoding="utf-8",
        ) as handle:
            recorded_prompt = handle.read()
        self.assertIn("Brainstorming chat is the shared record", recorded_prompt)
        self.assertIn("role: initial_position", recorded_prompt)
        self.assertFalse(os.path.samefile(target, unrelated))
        real_identity = lifecycle._target_identity

        def reused_identity(path):
            if path == unrelated:
                return copy.deepcopy(record["target_identity"])
            return real_identity(path)

        with mock.patch.object(
            lifecycle, "_target_identity", side_effect=reused_identity
        ):
            second = lifecycle.create_session(
                self.home,
                self._payload("unrelated.md"),
                access.ADMIN_EMAIL,
                launcher=self._sleeper_launcher,
            )
        self.assertNotEqual(second["id"], created["id"])
        self.assertEqual(second["state"]["status"], "running")

    def test_service_authority_does_not_reserve_lock_named_sibling(self):
        service_root = lifecycle.service_directory(self.home)
        os.makedirs(service_root, exist_ok=True)
        log_target = os.path.join(service_root, lifecycle.LOGS_DIRNAME)
        self.assertFalse(os.path.exists(log_target))
        payload = self._payload("unused.md")
        payload["request"]["target_path"] = log_target
        launches = []

        def launcher(home, session_id):
            launches.append(session_id)
            return self._sleeper_launcher(home, session_id)

        with self.assertRaises(lifecycle.PublicLifecycleError) as refused:
            lifecycle.create_session(
                self.home,
                payload,
                access.ADMIN_EMAIL,
                launcher=launcher,
            )

        self.assertEqual(
            (refused.exception.status, refused.exception.code),
            (400, lifecycle.INVALID_REQUEST),
        )
        self.assertEqual(launches, [])
        self.assertFalse(os.path.exists(log_target))
        self.assertEqual(lifecycle._load_registry(self.home)["sessions"], [])

        sibling_target = service_root + ".lock"
        payload["request"]["target_path"] = sibling_target
        created = lifecycle.create_session(
            self.home,
            payload,
            access.ADMIN_EMAIL,
            launcher=launcher,
        )
        self.assertEqual(
            created["state"]["request"]["target_path"], sibling_target
        )
        self.assertEqual(launches, [created["id"]])
        self.assertFalse(os.path.exists(sibling_target))
        self._stop_sleeper_record(created["id"])

    def test_create_post_state_failures_are_compensated_before_release(self):
        for name in (
            "transcript-fault.md",
            "registry-fault.md",
            "projection-fault.md",
        ):
            self._target(name)
        launched = []

        def launcher(home, session_id):
            launched.append(session_id)
            return self._sleeper_launcher(home, session_id)

        with mock.patch.object(
            bs,
            "_atomic_replace_utf8",
            side_effect=OSError("injected transcript publication failure"),
        ):
            with self.assertRaises(lifecycle.PublicLifecycleError) as failed:
                lifecycle.create_session(
                    self.home,
                    self._payload("transcript-fault.md"),
                    access.ADMIN_EMAIL,
                    launcher=launcher,
                )
        self.assertEqual(failed.exception.code, lifecycle.UNAVAILABLE)
        failed_session = launched[-1]
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        self.assertIsNone(store.read(failed_session))
        self.assertFalse(os.path.exists(store.transcript_ref(failed_session)))
        self.assertEqual(lifecycle._load_registry(self.home)["sessions"], [])

        with mock.patch.object(
            lifecycle,
            "_save_registry",
            side_effect=OSError("injected registry failure"),
        ):
            with self.assertRaises(lifecycle.PublicLifecycleError) as failed:
                lifecycle.create_session(
                    self.home,
                    self._payload("registry-fault.md"),
                    access.ADMIN_EMAIL,
                    launcher=launcher,
                )
        self.assertEqual(failed.exception.code, lifecycle.UNAVAILABLE)
        self.assertIsNone(
            bs.SessionStore(lifecycle.state_directory(self.home)).read(
                launched[-1]
            )
        )
        self.assertEqual(lifecycle._load_registry(self.home)["sessions"], [])

        with mock.patch.object(
            lifecycle,
            "_projection",
            side_effect=OSError("injected projection failure"),
        ):
            with self.assertRaises(lifecycle.PublicLifecycleError) as failed:
                lifecycle.create_session(
                    self.home,
                    self._payload("projection-fault.md"),
                    access.ADMIN_EMAIL,
                    launcher=launcher,
                )
        self.assertEqual(failed.exception.code, lifecycle.UNAVAILABLE)
        failed_session = launched[-1]
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        self.assertIsNone(store.read(failed_session))
        self.assertFalse(os.path.exists(store.transcript_ref(failed_session)))
        self.assertEqual(lifecycle._load_registry(self.home)["sessions"], [])
        self.assertTrue(
            all(process.poll() is not None for process in self.processes)
        )

        retried = lifecycle.create_session(
            self.home,
            self._payload("projection-fault.md"),
            access.ADMIN_EMAIL,
            launcher=launcher,
        )
        self.assertEqual(retried["state"]["status"], "running")

    def test_detail_poll_is_authorized_before_state_read_and_revision_monotonic(self):
        self._target("authorized.md")
        project = self._ready_project(
            users=[access.USER_EMAILS[0]]
        )
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload(
                    "authorized.md",
                    project=project["slug"],
                    work_area="main",
                ),
                headers=self._remote_headers(access.USER_EMAILS[0]),
            )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]
        transcript = body["session"]["state"]["transcript_ref"]
        with open(transcript, "w", encoding="utf-8") as handle:
            handle.write("corrupt projection")

        with mock.patch.object(
            bs.SessionStore,
            "read",
            side_effect=AssertionError("foreign state was read"),
        ) as state_read:
            status, refused = self._request(
                "GET",
                "/api/brainstorming/sessions/%s" % session_id,
                headers=self._remote_headers(access.USER_EMAILS[1]),
            )
        self.assertEqual((status, refused["error"]), (403, service.FORBIDDEN))
        state_read.assert_not_called()

        revisions = []
        for _index in range(3):
            status, followed = self._request(
                "GET", "/api/brainstorming/sessions/%s" % session_id
            )
            self.assertEqual(status, 200, followed)
            self.assertEqual(
                set(followed), {"ok", "session"}
            )
            revisions.append(followed["session"]["revision"])
        self.assertEqual(revisions, sorted(revisions))
        with open(transcript, "r", encoding="utf-8") as handle:
            self.assertIn("Brainstorming", handle.read())

        status, streamed = self._request(
            "GET",
            "/api/brainstorming/sessions/%s/events" % session_id,
        )
        self.assertEqual(status, 404, streamed)

    def test_floor_intervention_route_appends_and_refuses_terminal(self):
        self._target("floor.md")
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("floor.md"),
            )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]

        for invalid in (
            {"text": "Steer.", "author_name": "operator",
             "author_id": "critic-1"},
            {"text": "Steer."},
            {"text": "", "author_name": "operator"},
            {"text": "Steer.", "author_name": "operator", "extra": 1},
        ):
            status, refused = self._request(
                "POST",
                "/api/brainstorming/sessions/%s/floor" % session_id,
                invalid,
            )
            self.assertEqual(
                (status, refused["error"]),
                (400, lifecycle.INVALID_REQUEST),
                invalid,
            )

        status, accepted = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/floor" % session_id,
            {"text": "Keep the scope minimal.", "author_name": "operator"},
        )
        self.assertEqual(status, 200, accepted)
        derived = accepted["intervention"]["author_id"]
        self.assertEqual(
            derived, lifecycle.floor_author_id(access.ADMIN_EMAIL)
        )
        self.assertTrue(bs.FLOOR_AUTHOR_ID_RE.match(derived))
        self.assertEqual(accepted["intervention"]["after_completed_turns"], 0)

        explicit = "entity_" + "f" * 32
        status, accepted = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/floor" % session_id,
            {
                "text": "Signed by the external entity.",
                "author_name": "agent 99",
                "author_id": explicit,
            },
        )
        self.assertEqual(status, 200, accepted)
        self.assertEqual(accepted["intervention"]["author_id"], explicit)

        status, view = self._request(
            "GET", "/api/brainstorming/sessions/%s/view" % session_id
        )
        self.assertEqual(status, 200, view)
        transcript = view["view"]["transcript_markdown"]
        self.assertIn("Intervention — operator", transcript)
        self.assertIn("Intervention — agent 99", transcript)
        self.assertNotIn("entity_", transcript)

        store = bs.SessionStore(lifecycle.state_directory(self.home))
        snapshot = store.read(session_id)
        store.transition(
            session_id,
            snapshot.revision,
            "failure",
            {
                "outcome": "failure",
                "target_ref": "docs/floor.md",
                "transcript_ref": snapshot.state["transcript_ref"],
                "rounds_used": 0,
                "reason": closing_summary()["reason"],
            },
            closing_summary(),
        )
        status, refused = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/floor" % session_id,
            {"text": "Too late.", "author_name": "operator"},
        )
        self.assertEqual(
            (status, refused["error"]),
            (409, lifecycle.FLOOR_INTERVENTION_CONFLICT),
        )

    def test_fake_provider_lifecycle_reaches_success_and_failure(self):
        for name in ("success.md", "failure.md", "error.md"):
            self._target(name)
        sessions = {}
        for name in ("success.md", "failure.md", "error.md"):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload(name),
            )
            self.assertEqual(status, 201, body)
            sessions[name] = body["session"]["id"]

        success = self._poll_terminal(sessions["success.md"])
        rejected = self._poll_terminal(sessions["failure.md"])
        operational = self._poll_terminal(sessions["error.md"])
        self.assertEqual(success["state"]["status"], "success")
        self.assertEqual(success["state"]["result"]["outcome"], "success")
        self.assertEqual(rejected["state"]["status"], "failure")
        self.assertEqual(rejected["state"]["result"]["rounds_used"], 1)
        self.assertEqual(operational["state"]["status"], "failure")
        self.assertIn(
            "participant execution failed",
            operational["state"]["result"]["reason"],
        )
        self.assertEqual(len(operational["state"]["completed_turns"]), 1)
        self.assertEqual(
            operational["state"]["transcript_events"],
            [
                {
                    "kind": "material_interruption",
                    "fact": {
                        "after_completed_turns": 1,
                        "plain": (
                            "The discussion stopped because participant "
                            "execution failed."
                        ),
                    },
                }
            ],
        )
        operational_log = os.path.join(
            lifecycle.service_directory(self.home),
            lifecycle.LOGS_DIRNAME,
            "%s.log" % sessions["error.md"],
        )
        with open(operational_log, "r", encoding="utf-8") as handle:
            self.assertIn("family claude exited 7", handle.read())
        for session in (success, rejected, operational):
            self.assertEqual(
                session["state"]["result"]["target_ref"],
                session["state"]["request"]["target_path"],
            )
            self.assertEqual(
                session["state"]["result"]["transcript_ref"],
                session["state"]["transcript_ref"],
            )
            with open(
                session["state"]["transcript_ref"],
                "r",
                encoding="utf-8",
            ) as handle:
                transcript = handle.read()
                self.assertIn("Closing", transcript)
                self.assertNotIn("exited 7", transcript)
                if session is operational:
                    self.assertLess(
                        transcript.index("## Material interruption"),
                        transcript.index("## Closing"),
                    )
        self.assertEqual(registry.load(self.home)["runs"], [])

    def test_dante_narrator_enters_through_the_external_turn_contract(self):
        self._target("dante.md")
        payload = self._payload("dante.md")
        payload["participants"].append(
            {
                "id": "dante",
                "role": "common_sense",
                "delivery": "external",
                "external_provider": "narrator",
                "model_family": "codex",
            }
        )
        status, body = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 201, body)
        terminal = self._poll_terminal(body["session"]["id"])
        self.assertEqual(terminal["state"]["status"], "success")
        self.assertEqual(
            [
                turn["participant_id"]
                for turn in terminal["state"]["completed_turns"]
            ],
            ["lead", "critic", "dante"],
        )
        self.assertIsNone(terminal["external_intervention"])
        dante_calls = [
            event
            for event in terminal["activity"]
            if event["participant_id"] == "dante"
        ]
        self.assertEqual(
            [event["stage"] for event in dante_calls],
            ["discussion"],
        )

    def test_narrator_cannot_occupy_a_voting_position(self):
        self._target("narrator-voter.md")
        payload = self._payload("narrator-voter.md")
        payload["participants"][1] = {
            "id": "critic",
            "role": "contrary_position",
            "delivery": "external",
            "external_provider": "narrator",
            "model_family": "codex",
        }
        status, body = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(
            (status, body),
            (400, {"ok": False, "error": lifecycle.INVALID_REQUEST}),
        )

    def test_manual_external_turn_waits_and_accepts_each_response_once(self):
        self._target("manual-external.md")
        payload = self._payload("manual-external.md")
        payload["participants"].append(
            {
                "id": "human",
                "role": "contrary_position",
                "delivery": "external",
                "external_provider": "manual",
            }
        )
        status, body = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]

        def pending(action_kind):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                code, response = self._request(
                    "GET",
                    "/api/brainstorming/sessions/%s/intervention"
                    % session_id,
                )
                self.assertEqual(code, 200, response)
                intervention = response["intervention"]
                if (
                    intervention is not None
                    and intervention["action_kind"] == action_kind
                ):
                    return intervention
                time.sleep(0.05)
            self.fail("external intervention did not become pending")

        discussion = pending("discussion_turn")
        code, response = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/intervention" % session_id,
            {
                "token": discussion["token"],
                "response": {"markdown": "The human chooses simplicity."},
            },
        )
        self.assertEqual(code, 200, response)
        duplicate, refusal = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/intervention" % session_id,
            {
                "token": discussion["token"],
                "response": {"markdown": "A duplicate answer."},
            },
        )
        self.assertEqual(duplicate, 409, refusal)
        self.assertEqual(
            refusal["error"], lifecycle.EXTERNAL_INTERVENTION_CONFLICT
        )

        closure = pending("closure_vote")
        code, response = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/intervention" % session_id,
            {
                "token": closure["token"],
                "response": {"vote": "accept"},
            },
        )
        self.assertEqual(code, 200, response)
        terminal = self._poll_terminal(session_id)
        self.assertEqual(terminal["state"]["status"], "success")

    def test_external_wait_requires_explicit_start_after_lifecycle_dies(self):
        self._target("external-relaunch.md")
        payload = self._payload("external-relaunch.md")
        payload["participants"].append(
            {
                "id": "human",
                "role": "contrary_position",
                "delivery": "external",
                "external_provider": "manual",
            }
        )
        status, body = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]

        def pending(action_kind):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                code, response = self._request(
                    "GET",
                    "/api/brainstorming/sessions/%s/intervention"
                    % session_id,
                )
                self.assertEqual(code, 200, response)
                intervention = response["intervention"]
                if (
                    intervention is not None
                    and intervention["action_kind"] == action_kind
                ):
                    return intervention
                time.sleep(0.05)
            self.fail("external intervention did not become pending")

        discussion = pending("discussion_turn")
        old_pid = lifecycle._record_by_id(self.home, session_id)["pid"]
        self._kill_pid(old_pid)
        code, response = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/intervention" % session_id,
            {
                "token": discussion["token"],
                "response": {"markdown": "The delayed human answered."},
            },
        )
        self.assertEqual(code, 200, response)
        paused = lifecycle._record_by_id(self.home, session_id)
        self.assertFalse(lifecycle._process_alive(paused))
        code, started = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/start" % session_id,
            {},
        )
        self.assertEqual(code, 200, started)
        new_pid = lifecycle._record_by_id(self.home, session_id)["pid"]
        self.assertNotEqual(new_pid, old_pid)
        self.assertTrue(lifecycle._process_alive(
            lifecycle._record_by_id(self.home, session_id)
        ))

        closure = pending("closure_vote")
        code, response = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/intervention" % session_id,
            {"token": closure["token"], "response": {"vote": "accept"}},
        )
        self.assertEqual(code, 200, response)
        self.assertEqual(
            self._poll_terminal(session_id)["state"]["status"], "success"
        )

    def test_noop_start_does_not_require_legacy_milestone_attachment(self):
        def mark_legacy_milestone(session_id):
            with lifecycle._locked_registry(self.home):
                document = lifecycle._load_registry(self.home)
                record = lifecycle._find_record(document, session_id)
                record["caller"] = "milestone:legacy:slice_impl-02-b"
                lifecycle._save_registry(self.home, document)

        self._target("already-running.md")
        running = lifecycle.create_session(
            self.home,
            self._payload("already-running.md"),
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        mark_legacy_milestone(running["id"])
        with mock.patch.object(
            service,
            "_attached_brainstorming_staffing_session",
            side_effect=AssertionError("attachment lookup is not due"),
        ) as attachment:
            code, response = self._request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % running["id"],
                {},
            )
        self.assertEqual(code, 200, response)
        self.assertEqual(response["session"]["process"], "running")
        attachment.assert_not_called()
        self._stop_sleeper_record(running["id"])

        self._target("already-terminal.md")
        code, created = self._request(
            "POST",
            "/api/brainstorming/sessions",
            self._payload("already-terminal.md"),
        )
        self.assertEqual(code, 201, created)
        session_id = created["session"]["id"]
        terminal = self._poll_terminal(session_id)
        mark_legacy_milestone(session_id)
        with mock.patch.object(
            service,
            "_attached_brainstorming_staffing_session",
            side_effect=AssertionError("attachment lookup is not due"),
        ) as attachment:
            code, response = self._request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % session_id,
                {},
            )
        self.assertEqual(code, 200, response)
        self.assertEqual(
            response["session"]["state"]["status"],
            terminal["state"]["status"],
        )
        attachment.assert_not_called()

    def test_start_refuses_unattached_milestone_without_profile_locator(self):
        self._target("unattached-milestone-restart.md")
        created = lifecycle.create_session(
            self.home,
            self._payload("unattached-milestone-restart.md"),
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        session_id = created["id"]
        self._stop_sleeper_record(session_id)
        with lifecycle._locked_registry(self.home):
            document = lifecycle._load_registry(self.home)
            record = lifecycle._find_record(document, session_id)
            record["caller"] = "milestone:current:slice_impl-02-b"
            lifecycle._save_registry(self.home, document)
        registry_before = pathlib.Path(
            lifecycle.registry_path(self.home)
        ).read_bytes()

        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ) as launch:
            code, response = self._request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % session_id,
                {},
            )
        self.assertEqual(code, 503, response)
        self.assertEqual(response["error"], lifecycle.UNAVAILABLE)
        launch.assert_not_called()
        self.assertEqual(
            pathlib.Path(lifecycle.registry_path(self.home)).read_bytes(),
            registry_before,
        )

    def test_static_task_restart_preserves_terminal_noop_without_relaunch(self):
        task_state = state.new_state(
            "Static Brainstorming task restart proof.",
            self.workspace,
            self.config,
            name="static-task-run",
        )
        record = task_adapter.admit_task(
            task_state,
            {
                "task_executor": "brainstorming",
                "request": {
                    "work_area": {
                        "workspace_path": self.workspace,
                        "primary": self.workspace,
                        "additional": [],
                    },
                    "request": "Produce the agreed workspace effects.",
                    "context": {},
                    "reference_documents": [],
                },
                "configuration": {},
            },
            self.config,
            self.workspace,
        )
        session = task_adapter.start_task(
            task_state,
            record["id"],
            self.config,
            self.home,
            launcher=self._sleeper_launcher,
        )
        session_id = session["id"]
        self._stop_sleeper_record(session_id)
        state_path = os.path.join(self.tmp.name, "task-state.json")
        state.save(state_path, task_state)
        registry.add(
            self.home,
            registry.new_entry(
                "static-task-run",
                "static task run",
                self.workspace,
                state_path,
            ),
        )

        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=OSError("launch refused"),
        ) as refused:
            code, response = self._request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % session_id,
                {},
            )
        self.assertEqual(code, 503, response)
        refused.assert_called_once()
        failed = tasks.task_record(state.load(state_path), record["id"])
        self.assertEqual(failed["result"]["status"], "failure")
        self.assertIn(lifecycle.UNAVAILABLE, failed["result"]["reason"])

        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ) as relaunch:
            code, response = self._request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % session_id,
                {},
            )
        self.assertEqual(code, 503, response)
        relaunch.assert_not_called()

        store = bs.SessionStore(lifecycle.state_directory(self.home))
        snapshot = store.read(session_id)
        reason = "The task-owned session reached a terminal result."
        terminal_session = store.transition(
            session_id,
            snapshot.revision,
            "failure",
            lifecycle._failure_result(snapshot.state, reason),
            lifecycle._closing_summary(
                snapshot.state,
                reason,
                "The session terminality matches its durable task.",
            ),
        )
        task_before = pathlib.Path(state_path).read_bytes()
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=AssertionError("a terminal session cannot relaunch"),
        ) as relaunch:
            code, response = self._request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % session_id,
                {},
            )
        self.assertEqual(code, 200, response)
        self.assertEqual(
            response["session"]["revision"], terminal_session.revision
        )
        self.assertEqual(response["session"]["state"]["status"], "failure")
        relaunch.assert_not_called()
        self.assertEqual(pathlib.Path(state_path).read_bytes(), task_before)

        registry.remove(self.home, "static-task-run")
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=AssertionError("a terminal session cannot relaunch"),
        ) as relaunch:
            code, response = self._request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % session_id,
                {},
            )
        self.assertEqual(code, 200, response)
        self.assertEqual(
            response["session"]["revision"], terminal_session.revision
        )
        self.assertEqual(response["session"]["state"]["status"], "failure")
        relaunch.assert_not_called()
        self.assertEqual(pathlib.Path(state_path).read_bytes(), task_before)

    def test_task_restart_refuses_a_stop_in_progress(self):
        task_state = state.new_state(
            "Static Brainstorming task stop proof.",
            self.workspace,
            self.config,
            name="static-task-stop-run",
        )
        record = task_adapter.admit_task(
            task_state,
            {
                "task_executor": "brainstorming",
                "request": {
                    "work_area": {
                        "workspace_path": self.workspace,
                        "primary": self.workspace,
                        "additional": [],
                    },
                    "request": "Produce the agreed workspace effects.",
                    "context": {},
                    "reference_documents": [],
                },
                "configuration": {},
            },
            self.config,
            self.workspace,
        )
        session = task_adapter.start_task(
            task_state,
            record["id"],
            self.config,
            self.home,
            launcher=self._sleeper_launcher,
        )
        session_id = session["id"]
        self._stop_sleeper_record(session_id)
        state_path = os.path.join(self.tmp.name, "task-stop-state.json")
        state.save(state_path, task_state)
        registry.add(
            self.home,
            registry.new_entry(
                "static-task-stop-run",
                "static task stop run",
                self.workspace,
                state_path,
            ),
        )
        token = (os.path.abspath(self.home), session_id)
        with lifecycle._STOPS_GUARD:
            lifecycle._STOPS_IN_FLIGHT.add(token)
        try:
            with mock.patch.object(
                lifecycle,
                "_launch_lifecycle_process",
                side_effect=AssertionError("a concurrent stop cannot relaunch"),
            ) as launch:
                code, response = self._request(
                    "POST",
                    "/api/brainstorming/sessions/%s/start" % session_id,
                    {},
                )
        finally:
            with lifecycle._STOPS_GUARD:
                lifecycle._STOPS_IN_FLIGHT.discard(token)
        self.assertEqual(code, 409, response)
        self.assertEqual(response["error"], lifecycle.STOP_INCOMPLETE)
        launch.assert_not_called()
        self.assertIsNone(
            tasks.task_record(state.load(state_path), record["id"])["result"]
        )

    def test_stop_preserves_a_pending_external_turn_for_resume(self):
        self._target("external-stop.md")
        payload = self._payload("external-stop.md")
        payload["participants"].append(
            {
                "id": "human",
                "role": "contrary_position",
                "delivery": "external",
                "external_provider": "manual",
            }
        )
        status, body = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]
        deadline = time.monotonic() + 20
        intervention = None
        while time.monotonic() < deadline:
            code, response = self._request(
                "GET",
                "/api/brainstorming/sessions/%s/intervention" % session_id,
            )
            self.assertEqual(code, 200, response)
            intervention = response["intervention"]
            if intervention is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(intervention)

        code, stopped = self._request(
            "POST", "/api/brainstorming/sessions/%s/stop" % session_id, {}
        )
        self.assertEqual(code, 200, stopped)
        self.assertEqual(stopped["session"]["state"]["status"], "running")
        self.assertEqual(stopped["session"]["process"], "stopped")
        self.assertIsNotNone(stopped["session"]["external_intervention"])
        code, followed = self._request(
            "GET",
            "/api/brainstorming/sessions/%s/intervention" % session_id,
        )
        self.assertEqual(code, 200, followed)
        self.assertEqual(followed["intervention"]["token"], intervention["token"])
        code, accepted = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/intervention" % session_id,
            {
                "token": intervention["token"],
                "response": {"markdown": "Too late."},
            },
        )
        self.assertEqual(code, 200, accepted)
        code, resumed = self._request(
            "POST", "/api/brainstorming/sessions/%s/start" % session_id, {}
        )
        self.assertEqual(code, 200, resumed)
        self.assertEqual(resumed["session"]["state"]["status"], "running")
        self.assertEqual(resumed["session"]["process"], "running")

    def test_start_rechecks_a_concurrent_stop_before_launch(self):
        self._target("start-stop-race.md")
        created = lifecycle.create_session(
            self.home,
            self._payload("start-stop-race.md"),
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        session_id = created["id"]
        self._stop_sleeper_record(session_id)
        token = (os.path.abspath(self.home), session_id)
        entered_launch_lock = threading.Event()
        release_launch_lock = threading.Event()
        lock_calls = 0
        calls_guard = threading.Lock()
        real_locked_registry = lifecycle._locked_registry

        @contextlib.contextmanager
        def interposed_registry(home):
            nonlocal lock_calls
            with real_locked_registry(home):
                with calls_guard:
                    lock_calls += 1
                    this_call = lock_calls
                if this_call == 2:
                    entered_launch_lock.set()
                    self.assertTrue(release_launch_lock.wait(5))
                yield

        def start():
            try:
                return lifecycle.start_session(
                    self.home, session_id, lambda _record: None
                )
            except lifecycle.PublicLifecycleError as exc:
                return exc

        with mock.patch.object(
            lifecycle, "_locked_registry", interposed_registry
        ), mock.patch.object(
            lifecycle, "_launch_lifecycle_process"
        ) as launch:
            with ThreadPoolExecutor(max_workers=1) as pool:
                outcome = pool.submit(start)
                self.assertTrue(entered_launch_lock.wait(5))
                with lifecycle._STOPS_GUARD:
                    lifecycle._STOPS_IN_FLIGHT.add(token)
                release_launch_lock.set()
                outcome = outcome.result()
            with lifecycle._STOPS_GUARD:
                lifecycle._STOPS_IN_FLIGHT.discard(token)

        self.assertIsInstance(outcome, lifecycle.PublicLifecycleError)
        self.assertEqual(outcome.code, lifecycle.STOP_INCOMPLETE)
        launch.assert_not_called()

    def test_two_external_participants_chain_their_closure_votes(self):
        self._target("two-external.md")
        payload = self._payload("two-external.md")
        payload["participants"].extend(
            [
                {
                    "id": participant_id,
                    "role": "contrary_position",
                    "delivery": "external",
                    "external_provider": "manual",
                }
                for participant_id in ("human-a", "human-b")
            ]
        )
        status, body = self._request(
            "POST", "/api/brainstorming/sessions", payload
        )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]

        for action_kind, expected_id, response in (
            ("discussion_turn", "human-a", {"markdown": "A speaks."}),
            ("discussion_turn", "human-b", {"markdown": "B speaks."}),
            ("closure_vote", "human-a", {"vote": "accept"}),
            ("closure_vote", "human-b", {"vote": "accept"}),
        ):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                code, viewed = self._request(
                    "GET",
                    "/api/brainstorming/sessions/%s/intervention"
                    % session_id,
                )
                self.assertEqual(code, 200, viewed)
                intervention = viewed["intervention"]
                if (
                    intervention is not None
                    and intervention["action_kind"] == action_kind
                    and intervention["participant_id"] == expected_id
                ):
                    break
                time.sleep(0.05)
            else:
                self.fail("ordered external intervention did not appear")
            code, delivered = self._request(
                "POST",
                "/api/brainstorming/sessions/%s/intervention" % session_id,
                {"token": intervention["token"], "response": response},
            )
            self.assertEqual(code, 200, delivered)

        terminal = self._poll_terminal(session_id)
        self.assertEqual(terminal["state"]["status"], "success")

    def test_stop_leaves_an_ended_narrator_attempt_untouched(self):
        self._target("uncertain-narrator.md")
        payload = self._payload("uncertain-narrator.md")
        payload["participants"].append(
            {
                "id": "dante",
                "role": "common_sense",
                "delivery": "external",
                "external_provider": "narrator",
                "model_family": "codex",
            }
        )
        created = lifecycle.create_session(
            self.home,
            payload,
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        session_id = created["id"]
        record = self._stop_sleeper_record(session_id)
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        execution = lifecycle._participant_execution(
            store, record, lifecycle._spawn_participant
        )
        coordinator = coordination.BrainstormingCoordinator(store, execution)
        coordinator.prepare(session_id)
        coordinator.run_next_turn(session_id, record["execution_context"])
        coordinator.run_next_turn(session_id, record["execution_context"])
        with self.assertRaises(coordination.ExternalInterventionPending):
            coordinator.run_next_turn(
                session_id, record["execution_context"]
            )
        intervention = store.read_external_intervention(session_id)
        store.claim_external_intervention(
            session_id, intervention["token"]
        )

        self.assertEqual(
            lifecycle.run_lifecycle(
                self.home, session_id, require_pid_claim=False
            ),
            3,
        )
        followed = lifecycle.inspect_session(
            self.home, session_id, lambda _record: None
        )
        self.assertEqual(followed["state"]["status"], "running")
        self.assertEqual(followed["process"], "stopped")
        self.assertFalse(
            followed["external_intervention"]["provider_quiescent"]
        )
        stopped = lifecycle.stop_session(
            self.home, session_id, lambda _record: None
        )
        self.assertEqual(stopped["state"]["status"], "running")
        self.assertEqual(stopped["process"], "stopped")
        self.assertFalse(
            stopped["external_intervention"]["provider_quiescent"]
        )

    def test_recoverable_provider_failure_retries_the_same_turn(self):
        self._target("recoverable.md")
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("recoverable.md"),
            )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]
        self._stop_sleeper_record(session_id)
        with mock.patch.object(
            coordination, "OPERATIONAL_RETRY_S", 0
        ):
            code = lifecycle.run_lifecycle(
                self.home,
                session_id,
                require_pid_claim=False,
            )
        self.assertEqual(code, 0)
        session = lifecycle.inspect_session(
            self.home, session_id, lambda _record: None
        )
        self.assertEqual(session["state"]["status"], "success")
        self.assertIsNone(session["retry"])
        critic = [
            event for event in session["activity"]
            if event["participant_id"] == "critic"
            and event["stage"] == "discussion"
        ]
        self.assertEqual(
            [event["status"] for event in critic],
            ["failed", "failed", "failed", "completed"],
        )
        self.assertEqual(
            [event["provider_attempt"] for event in critic], [1, 2, 3, 4]
        )
        self.assertTrue(all(event["recovered"] for event in critic[:3]))
        self.assertGreater(session["work_duration_s"], 0)
        status, listed = self._request(
            "GET", "/api/brainstorming/sessions"
        )
        self.assertEqual(status, 200, listed)
        listed_session = next(
            row for row in listed["sessions"] if row["id"] == session_id
        )
        self.assertEqual(
            listed_session["last_action_epoch"],
            max(
                lifecycle._iso_epoch(event["at"])
                for event in session["activity"]
            ),
        )

    def test_bound_and_unbound_execution_context_passes_through_unchanged(self):
        self._target("repair.md")
        contexts = []

        def record_context(context, argv, popen_kwargs):
            contexts.append(context)
            return subprocess.Popen(argv, **popen_kwargs)

        unbound = lifecycle.create_session(
            self.home,
            self._payload("repair.md"),
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        record = self._stop_sleeper_record(unbound["id"])
        expected = copy.deepcopy(record["execution_context"])
        code = lifecycle.run_lifecycle(
            self.home,
            unbound["id"],
            participant_process_factory=record_context,
            require_pid_claim=False,
        )
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(contexts), 4)
        self.assertTrue(all(context is contexts[0] for context in contexts))
        self.assertEqual(contexts[0], expected)
        unbound_state = lifecycle.inspect_session(
            self.home, unbound["id"], lambda _record: None
        )["state"]
        self.assertEqual(
            unbound_state["request"]["context"]["source_payload"],
            {"opaque": ["preserved", 7]},
        )
        unbound_store = bs.SessionStore(lifecycle.state_directory(self.home))
        accepted = unbound_store.read_target_revision(
            unbound["id"], unbound_state["accepted_target_revision"]
        )
        lead, interlocutor = unbound_state["run_config"]["participants"]
        unbound_prompts = (
            coordination.build_turn_prompt(
                unbound_state, lead, 1, accepted, expected
            ),
            coordination.build_turn_prompt(
                unbound_state, interlocutor, 1, accepted, expected
            ),
            coordination.build_closure_proposal_prompt(
                unbound_state, accepted, expected
            ),
            coordination.build_closure_vote_prompt(
                unbound_state,
                interlocutor,
                accepted,
                closing_summary(),
                expected,
            ),
        )
        for prompt in unbound_prompts:
            self.assertIn(
                "modify no caller path other than target_path",
                prompt,
            )

        bound_workspace = os.path.join(self.tmp.name, "bound-workspace")
        additional = os.path.join(self.tmp.name, "additional")
        os.makedirs(os.path.join(bound_workspace, "docs"))
        os.makedirs(additional)
        with open(
            os.path.join(bound_workspace, "docs", "bound.md"), "wb"
        ) as handle:
            handle.write(b"bound target")
        project = self._ready_project(
            slug="bound",
            workspace=bound_workspace,
            additional=[additional],
        )
        bound_payload = self._payload(
            "bound.md",
            workspace=bound_workspace,
            project="bound",
            work_area="main",
        )
        bound = lifecycle.create_session(
            self.home,
            bound_payload,
            access.ADMIN_EMAIL,
            project_record=project,
            launcher=self._sleeper_launcher,
        )
        bound_record = self._stop_sleeper_record(bound["id"])
        bound_contexts = []

        def bound_factory(context, argv, popen_kwargs):
            bound_contexts.append(context)
            return subprocess.Popen(argv, **popen_kwargs)

        code = lifecycle.run_lifecycle(
            self.home,
            bound["id"],
            participant_process_factory=bound_factory,
            require_pid_claim=False,
        )
        self.assertEqual(code, 0)
        self.assertTrue(
            all(context is bound_contexts[0] for context in bound_contexts)
        )
        self.assertEqual(
            bound_contexts[0]["primary"], bound_record["execution_context"]["primary"]
        )
        self.assertEqual(
            bound_contexts[0]["additional"],
            bound_record["execution_context"]["additional"],
        )
        bound_state = lifecycle.inspect_session(
            self.home, bound["id"], lambda _record: None
        )["state"]
        accepted = bs.SessionStore(
            lifecycle.state_directory(self.home)
        ).read_target_revision(
            bound["id"], bound_state["accepted_target_revision"]
        )
        prompt = coordination.build_turn_prompt(
            bound_state,
            bound_state["run_config"]["participants"][0],
            1,
            accepted,
            bound_record["execution_context"],
        )
        self.assertIn(
            "PRIMARY ROOT %s" % bound_workspace,
            prompt,
        )
        self.assertIn(
            "ADDITIONAL ROOT %s — read-only evidence" % additional,
            prompt,
        )
        self.assertFalse(os.path.exists(os.path.join(bound_workspace, ".git")))

    def test_pause_keeps_accepted_concerns_without_fabricating_closure(self):
        self._target("concern.md")
        created = lifecycle.create_session(
            self.home,
            self._payload("concern.md", max_rounds=2),
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        session_id = created["id"]
        record = self._stop_sleeper_record(session_id)
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        prepared = coordination.BrainstormingCoordinator(
            store, None
        ).prepare(session_id)
        accepted = store.read_target_revision(
            session_id, prepared.state["recovery_baseline_revision"]
        )
        recorded = store.record_completed_turn(
            session_id,
            prepared.revision,
            "lead",
            "A concrete concern remains in the accepted discussion.",
            accepted,
        )
        self.assertEqual(len(recorded.state["completed_turns"]), 1)

        stopped = lifecycle.stop_session(
            self.home, session_id, lambda _record: None
        )
        self.assertEqual(stopped["state"]["status"], "running")
        self.assertNotIn("result", stopped["state"])
        self.assertNotIn("closing_summary", stopped["state"])
        with open(
            stopped["state"]["transcript_ref"], encoding="utf-8"
        ) as handle:
            transcript = handle.read()
        self.assertIn("A concrete concern remains", transcript)
        self.assertNotIn(
            "No unresolved objections were recorded.", transcript
        )
        self.assertIsNone(record["pid"])

    def test_stop_preserves_a_pending_operational_retry_without_rewriting(self):
        target = self._target("stop-retry.md")
        created = lifecycle.create_session(
            self.home,
            self._payload("stop-retry.md"),
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        session_id = created["id"]
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        prepared = coordination.BrainstormingCoordinator(
            store, None
        ).prepare(session_id)
        with coordination._open_target_parent(target) as (
            _descriptor, _name, parent_identity
        ):
            pass
        attempt = store.begin_turn_attempt(session_id, {
            "token": "pending-operational-retry",
            "participant_id": "lead",
            "completed_turn_count": 0,
            "target_revision": prepared.state["accepted_target_revision"],
            "quiescent": False,
            "target_parent": parent_identity,
        })
        store.mark_turn_attempt_quiescent(session_id, attempt["token"])
        store.schedule_operational_retry(
            session_id,
            attempt["token"],
            {"error_type": "busy", "resume_at": None, "evidence": ""},
            time.time() + 300,
        )
        with open(target, "wb") as handle:
            handle.write(b"unaccepted bytes")

        stopped = lifecycle.stop_session(
            self.home, session_id, lambda _record: None
        )

        self.assertEqual(stopped["state"]["status"], "running")
        self.assertIsNotNone(store.read_turn_attempt(session_id))
        self.assertIsNotNone(
            store.read_turn_attempt(session_id)["operational_retry"]
        )
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"unaccepted bytes")

    def test_stop_waits_for_quiescence_recovers_target_and_keeps_session(self):
        target = self._target("slow.md")
        os.chmod(target, 0o640)
        sibling = os.path.join(self.workspace, "sibling.sentinel")
        with open(sibling, "wb") as handle:
            handle.write(b"unchanged sibling")
        status, body = self._request(
            "POST",
            "/api/brainstorming/sessions",
            self._payload("slow.md", max_rounds=2),
        )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]
        child_path = os.path.join(self.workspace, "slow-child.pid")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with open(target, "rb") as handle:
                    mutated = handle.read() == b"mutated by in-flight lead"
            except OSError:
                mutated = False
            if mutated and os.path.exists(child_path):
                break
            time.sleep(0.05)
        else:
            self.fail("fake lead did not begin its target mutation")

        with open(child_path, "r", encoding="utf-8") as handle:
            descendant_pid = int(handle.read())
        status, invalid_stop = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/stop" % session_id,
            {"reason": "caller text is not accepted"},
        )
        self.assertEqual(
            (status, invalid_stop["error"]),
            (400, lifecycle.INVALID_REQUEST),
        )
        status, stopped = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/stop" % session_id,
            {},
        )
        self.assertEqual(status, 200, stopped)
        session = stopped["session"]
        self.assertEqual(session["state"]["status"], "running")
        self.assertEqual(session["process"], "stopped")
        self.assertEqual(session["state"]["rounds_used"], 0)
        self.assertEqual(session["state"]["completed_turns"], [])
        self.assertNotIn("result", session["state"])
        self.assertEqual(session["state"]["transcript_events"], [])
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o640)
        with open(sibling, "rb") as handle:
            self.assertEqual(handle.read(), b"unchanged sibling")
        self.assertFalse(self._non_zombie_process(descendant_pid))

        before = copy.deepcopy(session)
        status, repeated = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/stop" % session_id,
            {},
        )
        self.assertEqual(status, 200, repeated)
        self.assertEqual(repeated["session"], before)

    @staticmethod
    def _non_zombie_process(pid):
        try:
            observed = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        state = observed.stdout.strip()
        return bool(state and not state.startswith("Z"))

    def test_stop_completion_and_duplicate_launch_races_have_one_winner(self):
        self._target("race.md")
        payload = self._payload("race.md")
        launches = []
        launch_lock = threading.Lock()

        def launcher(home, session_id):
            with launch_lock:
                launches.append(session_id)
            return self._sleeper_launcher(home, session_id)

        def create():
            try:
                return lifecycle.create_session(
                    self.home,
                    payload,
                    access.ADMIN_EMAIL,
                    launcher=launcher,
                )
            except lifecycle.PublicLifecycleError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [future.result() for future in [pool.submit(create), pool.submit(create)]]
        winners = [item for item in outcomes if isinstance(item, dict)]
        losers = [
            item
            for item in outcomes
            if isinstance(item, lifecycle.PublicLifecycleError)
        ]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)
        self.assertEqual(losers[0].code, lifecycle.TARGET_IN_USE)
        self.assertEqual(len(launches), 1)

        session_id = winners[0]["id"]
        self._stop_sleeper_record(session_id)
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        coordinator = coordination.BrainstormingCoordinator(store, None)
        prepared = coordinator.prepare(session_id)
        reason = "The lifecycle completed with a bounded failure."
        result = lifecycle._failure_result(prepared.state, reason)
        summary = lifecycle._closing_summary(
            prepared.state,
            reason,
            "The terminal outcome matches the accepted state.",
        )
        barrier = threading.Barrier(2)

        def complete():
            barrier.wait()
            try:
                return store.transition(
                    session_id,
                    prepared.revision,
                    "failure",
                    result,
                    summary,
                )
            except bs.RevisionConflict:
                return None

        def stop():
            barrier.wait()
            return lifecycle.stop_session(
                self.home, session_id, lambda _record: None
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            completion = pool.submit(complete)
            stopping = pool.submit(stop)
            completion.result()
            stopping.result()
        terminal = store.read(session_id)
        self.assertEqual(terminal.state["status"], "failure")
        self.assertEqual(
            [item["status"] for item in terminal.state["history"]],
            ["created", "running", "failure"],
        )
        self.assertLessEqual(len(terminal.state["transcript_events"]), 1)

    def test_stop_of_dead_process_leaves_durable_state_untouched(self):
        target = self._target("unreconciled.md")
        created = lifecycle.create_session(
            self.home,
            self._payload("unreconciled.md"),
            access.ADMIN_EMAIL,
            launcher=self._sleeper_launcher,
        )
        session_id = created["id"]
        self._stop_sleeper_record(session_id)
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        coordinator = coordination.BrainstormingCoordinator(store, None)
        prepared = coordinator.prepare(session_id)
        with coordination._open_target_parent(target) as (
            _descriptor,
            _name,
            parent_identity,
        ):
            pass
        store.begin_turn_attempt(
            session_id,
            {
                "token": "unknown-worker",
                "participant_id": "lead",
                "completed_turn_count": 0,
                "target_revision": prepared.state[
                    "accepted_target_revision"
                ],
                "quiescent": False,
                "target_parent": parent_identity,
            },
        )
        with open(target, "wb") as handle:
            handle.write(b"unconfirmed worker mutation")

        status, stopped = self._request(
            "POST",
            "/api/brainstorming/sessions/%s/stop" % session_id,
            {},
        )
        self.assertEqual(status, 200, stopped)
        self.assertEqual(stopped["session"]["process"], "stopped")
        status, followed = self._request(
            "GET", "/api/brainstorming/sessions/%s" % session_id
        )
        self.assertEqual(status, 200, followed)
        session = followed["session"]
        self.assertEqual(session["process"], "stopped")
        self.assertEqual(session["state"]["status"], "running")
        self.assertNotIn("result", session["state"])
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"unconfirmed worker mutation")

    def test_existing_routes_registry_and_slice_contracts_are_unchanged(self):
        self._target("compatibility.md")
        status, panel_before = self._request("GET", "/")
        self.assertEqual(status, 200)
        status, runs_before = self._request("GET", "/api/runs")
        self.assertEqual(runs_before, {"ok": True, "runs": []})

        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("compatibility.md"),
            )
        self.assertEqual(status, 201, body)
        checked = bs.validate_session_state(body["session"]["state"])
        self.assertEqual(checked["status"], "running")

        status, panel_after = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(panel_after, panel_before)
        status, runs_after = self._request("GET", "/api/runs")
        self.assertEqual(runs_after, {"ok": True, "runs": []})
        self.assertEqual(registry.load(self.home)["runs"], [])
        self.assertFalse(os.path.exists(registry.registry_path(self.home)))
        status, projects = self._request("GET", "/api/projects")
        self.assertEqual(projects, {"ok": True, "projects": []})

        # Listing is a read-only projection added for the panel's unified
        # sidebar; deleting a RUNNING session refuses — stop it first.
        status, listed = self._request(
            "GET", "/api/brainstorming/sessions"
        )
        self.assertEqual(status, 200, listed)
        self.assertEqual(
            [row["id"] for row in listed["sessions"]],
            [body["session"]["id"]],
        )
        status, refused = self._request(
            "DELETE",
            "/api/brainstorming/sessions/%s" % body["session"]["id"],
        )
        self.assertEqual(status, 409, refused)
        self.assertEqual(refused["error"], lifecycle.SESSION_RUNNING)

    def test_list_projects_authorized_rows_and_survives_broken_state(self):
        """The panel's list route: authorized, tolerant, newest first."""
        self._target("listed.md")
        self._target("other.md")
        self._ready_project(users=["jdcf1710@gmail.com"])

        status, empty = self._request("GET", "/api/brainstorming/sessions")
        self.assertEqual(status, 200, empty)
        self.assertEqual(empty, {"ok": True, "sessions": []})

        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, bound = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload(
                    "listed.md", project="project", work_area="main"
                ),
            )
            self.assertEqual(status, 201, bound)
            status, unbound = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("other.md"),
            )
            self.assertEqual(status, 201, unbound)

        status, all_rows = self._request("GET", "/api/brainstorming/sessions")
        self.assertEqual(status, 200, all_rows)
        rows = all_rows["sessions"]
        self.assertEqual(len(rows), 2)
        # Newest creation first, both visible to the administrator.
        self.assertEqual(
            {row["id"] for row in rows},
            {bound["session"]["id"], unbound["session"]["id"]},
        )
        self.assertGreaterEqual(
            rows[0]["created_at"], rows[1]["created_at"]
        )
        listed_bound = next(
            row for row in rows if row["id"] == bound["session"]["id"]
        )
        self.assertEqual(listed_bound["project"], "project")
        self.assertEqual(listed_bound["work_area"], "main")
        self.assertEqual(listed_bound["process"], "running")
        self.assertEqual(listed_bound["status"], "running")
        self.assertEqual(
            listed_bound["request"],
            "Select the bounded result to accept.",
        )
        self.assertEqual(listed_bound["max_rounds"], 1)
        self.assertIsNone(listed_bound["state_error"])
        self.assertTrue(listed_bound["target_path"].endswith("listed.md"))

        # An ordinary assigned user sees the project-bound session only:
        # the administrator's project-less session is never listed.
        status, mine = self._request(
            "GET",
            "/api/brainstorming/sessions",
            headers=self._remote_headers("jdcf1710@gmail.com"),
        )
        self.assertEqual(status, 200, mine)
        self.assertEqual(
            [row["id"] for row in mine["sessions"]],
            [bound["session"]["id"]],
        )
        status, none = self._request(
            "GET",
            "/api/brainstorming/sessions",
            headers=self._remote_headers("isabelmariaandresruiz@gmail.com"),
        )
        self.assertEqual(status, 200, none)
        self.assertEqual(none["sessions"], [])

        # One unreadable session degrades to a named fault; the rest of
        # the list is unaffected.
        with mock.patch.object(
            lifecycle.brainstorming.SessionStore,
            "read",
            side_effect=RuntimeError("state store is unavailable"),
        ):
            status, broken = self._request(
                "GET", "/api/brainstorming/sessions"
            )
        self.assertEqual(status, 200, broken)
        self.assertEqual(len(broken["sessions"]), 2)
        for row in broken["sessions"]:
            self.assertIsNone(row["status"])
            self.assertIsNone(row["request"])
            self.assertEqual(
                row["state_error"], "state store is unavailable"
            )


if __name__ == "__main__":
    unittest.main()
