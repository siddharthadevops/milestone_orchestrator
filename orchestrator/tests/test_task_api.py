"""Focused service proof for standalone TaskExecutor ordering."""

import copy
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from orchestrator import access, brainstorming_tasks, registry, runners, service
from orchestrator import state as st
from orchestrator import task_api, tasks


class NoopHost:
    def __init__(self):
        self.started = []

    def start(self, record, _config_resolver):
        self.started.append(record["id"])


class TaskApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-task-api-")
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.primary = self.directory("primary")
        self.additional = self.directory("additional")
        self.outside = self.directory("outside")
        self.start_server(NoopHost())

    def directory(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path)
        return path

    def start_server(self, host):
        if hasattr(self, "_stop"):
            self._stop()
        server = service.make_server(self.home, 0, task_host=host)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stopped = []

        def stop():
            if not stopped:
                stopped.append(True)
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self._stop = stop
        self.addCleanup(stop)
        self.base = "http://127.0.0.1:%d" % server.server_address[1]

    def request(self, method, path, payload=None, headers=None, raw=None):
        data = raw
        if raw is None and payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    def order(self, executor="worker", work_area=None, **request_changes):
        request = {
            "work_area": work_area or {
                "workspace_path": self.primary,
                "primary": self.primary,
                "additional": [self.additional],
            },
            "request": "Do exactly the caller-authored work.",
            "context": {"source": "test"},
            "reference_documents": [],
        }
        request.update(request_changes)
        return {"task_executor": executor, "request": request}

    def project(self, slug, primary, users=()):
        self.assertEqual(self.request("POST", "/api/projects", {"slug": slug})[0], 201)
        path = "/api/projects/%s/work-areas" % slug
        payload = {"name": "main", "primary_path": primary}
        self.assertEqual(self.request("POST", path, payload)[0], 200)
        self.assertEqual(self.request(
            "POST", "/api/projects/%s/users" % slug, {"users": list(users)}
        )[0], 200)

    @staticmethod
    def member(email=access.USER_EMAILS[0]):
        return {
            "Host": "example.ngrok-free.dev",
            access.REMOTE_HEADER: access.REMOTE_MARKER,
            access.USER_HEADER: email,
        }

    def wait_record(self, task_id, terminal=True):
        deadline = time.time() + 5
        while time.time() < deadline:
            record = task_api.StandaloneTaskStore(self.home).record(task_id)
            if (record["result"] is not None) == terminal:
                return record
            time.sleep(0.01)
        self.fail("task %s did not reach expected state" % task_id)

    def test_catalogue_route_reuses_shared_schema(self):
        status, body = self.request("GET", "/api/task-executors")
        self.assertEqual(status, 200)
        self.assertEqual(body, {
            "ok": True, "task_executors": tasks.task_executor_catalogue()
        })
        definition = tasks._TASK_EXECUTOR_BY_ID["brainstorming"][
            "configuration_schema"
        ]["max_rounds"]
        with mock.patch.dict(definition, {"default": 17}):
            body = self.request("GET", "/api/task-executors")[1]
            self.assertEqual(body["task_executors"][1]["configuration_schema"]
                             ["max_rounds"]["default"], 17)
            self.assertEqual(tasks.resolve_configuration("brainstorming")
                             ["max_rounds"], 17)

    def test_direct_order_resolves_access_before_admission(self):
        self.project("mine", self.primary, [access.USER_EMAILS[0]])
        other = self.directory("other-primary")
        self.project("other", other)
        member = self.member()
        project_order = self.order(work_area={"project": "mine", "work_area": "main"})
        status, body = self.request("POST", "/api/tasks", project_order, member)
        self.assertEqual(status, 201, body)
        frozen = body["task"]["order"]["request"]["work_area"]
        self.assertEqual(frozen["project"], "mine")
        self.assertEqual(frozen["primary"]["path"], self.primary)

        additional_ref = self.order(reference_documents=[
            os.path.join(self.additional, "missing.md")
        ])
        self.assertEqual(self.request("POST", "/api/tasks", additional_ref)[0], 201)
        before = len(task_api.StandaloneTaskStore(self.home).records())
        refusals = (
            (400, tasks.INVALID_TASK_REQUEST, self.order(
                reference_documents=[os.path.join(self.outside, "secret.md")]
            ), None),
            (400, tasks.INVALID_TASK_REQUEST, self.order(
                reference_documents=["bad\x00reference"]
            ), None),
            (400, tasks.INVALID_TASK_REQUEST, self.order(
                reference_documents=["bad" + chr(0xD800)]
            ), None),
            (400, tasks.INVALID_TASK_REQUEST, self.order(
                output_directory=self.additional
            ), None),
            (400, tasks.INVALID_TASK_REQUEST, self.order(
                output_directory="bad\x00destination"
            ), None),
            (400, tasks.INVALID_TASK_REQUEST, self.order(
                output_directory="bad" + chr(0xD800)
            ), None),
            (400, tasks.INVALID_TASK_REQUEST, self.order(
                request="bad" + chr(0xD800)
            ), None),
            (400, tasks.INVALID_TASK_REQUEST, self.order(
                context={"nested": ["bad" + chr(0xDFFF)]}
            ), None),
            (400, tasks.UNKNOWN_TASK_EXECUTOR, self.order("other"), None),
            (400, tasks.INVALID_TASK_REQUEST, {**project_order, "extra": True}, member),
            (400, tasks.INVALID_TASK_REQUEST, self.order(work_area={
                "project": "mine", "work_area": "main", "extra": True,
            }), member),
            (403, service.FORBIDDEN, self.order(), member),
            (403, service.FORBIDDEN, self.order(
                work_area={"project": "other", "work_area": "main"}
            ), member),
            (404, "unknown_work_area", self.order(
                work_area={"project": "mine", "work_area": "missing"}
            ), member),
        )
        for expected_status, error, order, headers in refusals:
            with self.subTest(error=error):
                status, body = self.request("POST", "/api/tasks", order, headers)
                self.assertEqual((status, body["error"]), (expected_status, error))
                self.assertEqual(
                    len(task_api.StandaloneTaskStore(self.home).records()), before
                )
        status, body = self.request("POST", "/api/tasks", raw=b"not-json")
        self.assertEqual((status, body["error"]), (400, tasks.INVALID_TASK_REQUEST))

    def test_post_returns_durable_open_task_before_completion(self):
        entered, release = threading.Event(), threading.Event()

        class Runner:
            def call(_self, *_args, **_kwargs):
                entered.set()
                release.wait(5)
                return runners.RunnerResult("done", 0, 0.1)

        host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: Runner()
        )
        self.start_server(host)
        status, body = self.request("POST", "/api/tasks", self.order())
        record = body["task"]
        self.assertEqual(status, 201)
        self.assertIsNone(record["result"])
        self.assertTrue(entered.wait(2))
        self.assertEqual(task_api.StandaloneTaskStore(self.home).record(
            record["id"]
        ), record)
        self.start_server(NoopHost())
        self.assertEqual(self.request("GET", "/api/tasks/%s" % record["id"])[1]
                         ["task"], record)
        release.set()
        self.assertEqual(self.wait_record(record["id"])["result"]["status"], "success")

    def test_direct_worker_preserves_raw_request_result_and_accounting(self):
        release = threading.Event()
        seen = []
        fail = []
        raw = '{"status":"need_rethink","artifact":"do-not-parse"}'

        class Runner:
            def call(_self, family, prompt, workspace, model=None, effort=None):
                seen.append((family, prompt, workspace, model, effort))
                if fail:
                    raise runners.ProviderResponseError(
                        "provider unavailable", raw_texts=["partial evidence"]
                    )
                return runners.RunnerResult(
                    raw, 0, 2.0,
                    token_usage={
                        "input_tokens": 10, "cached_input_tokens": 2,
                        "output_tokens": 5, "reasoning_output_tokens": 1,
                        "total_tokens": 15,
                    },
                    cost_payloads=[{"total_cost_usd": 0.25}],
                )

        host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: Runner()
        )
        self.start_server(host)
        old = service.driver.load_config(None)
        old["families_order"] = ["codex"]
        new = service.driver.load_config(None)
        new["families_order"] = ["claude"]
        new["model_defaults"]["claude"] = {"model": "actual", "effort": "high"}
        new["billing"]["claude"] = "api"
        calls = []

        def config(_home, _project=None):
            calls.append(True)
            if len(calls) == 1:
                return copy.deepcopy(old)
            release.wait(5)
            return copy.deepcopy(new)

        with mock.patch.object(service, "_direct_task_config", side_effect=config):
            body = self.request("POST", "/api/tasks", self.order())[1]
            self.assertEqual(body["task"]["resolved_staffing"]["worker"]["agent"],
                             "codex")
            release.set()
            record = self.wait_record(body["task"]["id"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], "Do exactly the caller-authored work.")
        self.assertEqual(record["result"]["native_result"], raw)
        self.assertEqual(record["result"]["cost"], {"api_usd": 0.25, "real_usd": 0.25})
        marker = task_api.read_worker_marker(self.home, record["id"])
        self.assertEqual((marker["family"], marker["model"], marker["effort"]),
                         ("claude", "actual", "high"))
        self.assertEqual(marker["task_id"], record["id"])
        fail.append(True)
        failed_id = self.request("POST", "/api/tasks", self.order())[1]["task"]["id"]
        failure = self.wait_record(failed_id)["result"]
        self.assertEqual((failure["status"], failure["native_result"]),
                         ("failure", "partial evidence"))
        self.assertTrue(failure["token_usage_partial"])
        self.assertTrue(failure["cost_partial"])

    def test_worker_marker_completion_failure_keeps_native_success(self):
        class Runner:
            def call(_self, *_args, **_kwargs):
                return runners.RunnerResult("completed work", 0, 0.1)

        host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: Runner()
        )
        self.start_server(host)
        write_marker = task_api._write_worker_marker

        def fail_completion(home, task_id, marker):
            if marker.get("completed"):
                raise OSError("terminal marker unavailable")
            return write_marker(home, task_id, marker)

        with mock.patch.object(
            task_api, "_write_worker_marker", side_effect=fail_completion
        ):
            record = self.request("POST", "/api/tasks", self.order())[1]["task"]
            terminal = self.wait_record(record["id"])

        self.assertEqual(terminal["result"]["status"], "success")
        self.assertEqual(terminal["result"]["native_result"], "completed work")
        marker = task_api.read_worker_marker(self.home, record["id"])
        self.assertNotIn("completed", marker)

    def test_malformed_billing_configuration_keeps_cost_partial(self):
        class Runner:
            def call(_self, *_args, **_kwargs):
                return runners.RunnerResult(
                    "completed work",
                    0,
                    0.1,
                    cost_payloads=[{"total_cost_usd": 0.25}],
                )

        config = service.driver.load_config(None)
        config["billing"] = "api"
        host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: Runner()
        )
        self.start_server(host)

        with mock.patch.object(
            service, "_direct_task_config", return_value=config
        ):
            task_id = self.request("POST", "/api/tasks", self.order())[1][
                "task"
            ]["id"]
            result = self.wait_record(task_id)["result"]

        self.assertEqual(result["status"], "success")
        self.assertIsNone(result["cost"])
        self.assertTrue(result["cost_partial"])
        marker = task_api.read_worker_marker(self.home, task_id)
        self.assertIsNone(marker["cost"])
        self.assertTrue(marker["cost_partial"])

    def test_direct_brainstorming_freezes_and_runs_static_order(self):
        effect_started, effect_release = threading.Event(), threading.Event()
        pins = {"dispatch_authority": "static", "participants": [{"id": "lead"}]}
        captured = []

        def start(state, task_id, config, home):
            captured.append((tasks.task_record(state, task_id), config, home))
            return {"id": "session-one"}

        def finish(state, task_id, _home, _session_id, apply_effects):
            effect_started.set()
            effect_release.wait(5)
            self.assertTrue(apply_effects({"request": {}, "agreement": {}})["completed"])
            return tasks.record_task_result(state, task_id, {
                "status": "success", "duration_s": 1.0,
                "token_usage": None, "token_usage_partial": True,
                "cost": None, "cost_partial": True,
                "native_result": {"agreement": "kept opaque"},
            })

        host = task_api.DirectTaskHost(self.home, poll_interval=0.01)
        self.start_server(host)
        order = self.order("brainstorming")
        order["configuration"] = {"max_rounds": 4, "closure_policy": "majority"}
        with mock.patch.object(brainstorming_tasks, "resolve_staffing", return_value=pins), \
                mock.patch.object(brainstorming_tasks, "start_task", side_effect=start), \
                mock.patch.object(brainstorming_tasks, "finish_task", side_effect=finish), \
                mock.patch.object(brainstorming_tasks, "apply_agreed_effects",
                                  return_value={"completed": True}):
            status, body = self.request("POST", "/api/tasks", order)
            self.assertEqual(status, 201)
            task_id = body["task"]["id"]
            self.assertEqual(body["task"]["order"]["configuration"],
                             {"max_rounds": 4, "closure_policy": "majority"})
            self.assertEqual(body["task"]["resolved_staffing"], pins)
            self.assertTrue(effect_started.wait(2))
            self.assertIsNone(task_api.StandaloneTaskStore(self.home).record(task_id)
                              ["result"])
            effect_release.set()
            self.assertEqual(self.wait_record(task_id)["result"]["native_result"],
                             {"agreement": "kept opaque"})
        before = len(task_api.StandaloneTaskStore(self.home).records())
        unavailable = tasks.TaskRequestError(tasks.TASK_UNAVAILABLE, "no seats")
        with mock.patch.object(brainstorming_tasks, "resolve_staffing",
                               side_effect=unavailable):
            status, body = self.request("POST", "/api/tasks", self.order("brainstorming"))
        self.assertEqual((status, body["error"]), (503, tasks.TASK_UNAVAILABLE))
        self.assertEqual(len(task_api.StandaloneTaskStore(self.home).records()), before)

    def test_malformed_standing_staffing_is_unavailable_before_admission(self):
        malformed_defaults = service.driver.load_config(None)
        malformed_defaults["model_defaults"] = True
        malformed_families = service.driver.load_config(None)
        malformed_families["families_order"] = "codex"
        malformed_command = service.driver.load_config(None)
        malformed_command["families_order"] = ["codex"]
        malformed_command["commands"]["codex"].append(
            {"{model}": "not an argv string"}
        )
        malformed_timeouts = service.driver.load_config(None)
        malformed_timeouts["timeouts"] = True
        before = len(task_api.StandaloneTaskStore(self.home).records())

        for executor, config in (
            ("worker", malformed_defaults),
            ("brainstorming", malformed_defaults),
            ("worker", malformed_families),
            ("worker", malformed_command),
            ("brainstorming", malformed_command),
            ("brainstorming", malformed_timeouts),
        ):
            with self.subTest(executor=executor, config=config):
                with mock.patch.object(
                    service, "_direct_task_config", return_value=config
                ):
                    status, body = self.request(
                        "POST", "/api/tasks", self.order(executor)
                    )
                self.assertEqual(
                    (status, body["error"]), (503, tasks.TASK_UNAVAILABLE)
                )
                self.assertEqual(
                    len(task_api.StandaloneTaskStore(self.home).records()), before
                )

    def test_static_recovery_inspects_owned_session_before_current_config(self):
        pins = {
            "dispatch_authority": "static",
            "participants": [{"id": "lead"}],
        }
        with mock.patch.object(
            brainstorming_tasks, "resolve_staffing", return_value=pins
        ):
            record = self.request(
                "POST", "/api/tasks", self.order("brainstorming")
            )[1]["task"]

        native = {"outcome": "failure", "reason": "session refused"}
        usage = {
            "input_tokens": 6,
            "cached_input_tokens": 1,
            "output_tokens": 4,
            "reasoning_output_tokens": 2,
            "total_tokens": 10,
        }
        projection = {
            "id": "owned-static-session",
            "caller": "task:" + record["id"],
            "process": "stopped",
            "state": {"status": "failure", "result": native},
            "work_duration_s": 7.0,
            "work_token_usage": usage,
            "work_token_usage_partial": False,
            "work_cost": {"api_usd": 0.7, "real_usd": 0.2},
            "work_cost_partial": False,
        }

        def inspect(_home, _session_id, authorize):
            authorize({"caller": projection["caller"]})
            return copy.deepcopy(projection)

        host = task_api.DirectTaskHost(self.home, poll_interval=0.01)
        with mock.patch.object(
            brainstorming_tasks.lifecycle,
            "list_sessions",
            return_value=[{"id": projection["id"]}],
        ), mock.patch.object(
            brainstorming_tasks.lifecycle,
            "inspect_session",
            side_effect=inspect,
        ):
            host._run_brainstorming(
                record,
                mock.Mock(side_effect=RuntimeError("configuration unavailable")),
            )

        result = task_api.StandaloneTaskStore(self.home).record(
            record["id"]
        )["result"]
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], native["reason"])
        self.assertEqual(result["duration_s"], 7.0)
        self.assertEqual(result["token_usage"], usage)
        self.assertEqual(result["cost"], {"api_usd": 0.7, "real_usd": 0.2})
        self.assertEqual(result["native_result"], native)

    def test_missing_open_task_workspace_does_not_abort_service_startup(self):
        pins = {
            "dispatch_authority": "static",
            "participants": [{"id": "lead"}],
        }
        with mock.patch.object(
            brainstorming_tasks, "resolve_staffing", return_value=pins
        ):
            record = self.request(
                "POST", "/api/tasks", self.order("brainstorming")
            )[1]["task"]
        os.rmdir(self.primary)

        server = service.make_server(self.home, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:%d/api/tasks/%s" % (
                server.server_address[1], record["id"]
            )
            with urllib.request.urlopen(url, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(body["task"]["id"], record["id"])
            self.assertIsNone(body["task"]["result"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_service_restart_does_not_auto_start_open_brainstorming_task(self):
        pins = {
            "dispatch_authority": "static",
            "participants": [{"id": "lead"}],
        }
        with mock.patch.object(
            brainstorming_tasks, "resolve_staffing", return_value=pins
        ):
            record = self.request(
                "POST", "/api/tasks", self.order("brainstorming")
            )[1]["task"]

        restarted_host = NoopHost()
        with mock.patch.object(
            service.task_api, "DirectTaskHost", return_value=restarted_host
        ):
            server = service.make_server(self.home, 0)
        try:
            self.assertIsNone(
                task_api.StandaloneTaskStore(self.home).record(record["id"])["result"]
            )
            self.assertEqual(restarted_host.started, [])
        finally:
            server.server_close()

    def test_standalone_brainstorming_session_restart_uses_durable_task(self):
        host = NoopHost()
        self.start_server(host)
        pins = {
            "dispatch_authority": "static",
            "participants": [{"id": "lead"}],
        }
        with mock.patch.object(
            brainstorming_tasks, "resolve_staffing", return_value=pins
        ):
            record = self.request(
                "POST", "/api/tasks", self.order("brainstorming")
            )[1]["task"]

        session_id = "standalone-session"
        session_record = {
            "id": session_id,
            "caller": "task:%s" % record["id"],
            "project": None,
            "execution_context": {"workspace_path": self.primary},
        }
        projection = {
            "id": session_id,
            "process": "running",
            "state": {"status": "running"},
        }
        captured = []

        def restart(state, task_id, config, home, session_id=None):
            captured.append((state, task_id, config, home, session_id))
            return projection

        with mock.patch.object(
            service.brainstorming_lifecycle,
            "_record_by_id",
            return_value=session_record,
        ), mock.patch.object(
            service.brainstorming_lifecycle,
            "inspect_session",
            return_value={"state": {"status": "running"}, "process": "stopped"},
        ), mock.patch.object(
            brainstorming_tasks, "start_task", side_effect=restart
        ):
            status, body = self.request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % session_id,
                {},
            )

        self.assertEqual((status, body["session"]), (200, projection))
        self.assertEqual(len(captured), 1)
        state, task_id, config, home, attached_session = captured[0]
        self.assertEqual(tasks.task_record(state, task_id), record)
        self.assertEqual((config, home, attached_session), ({}, self.home, session_id))
        self.assertEqual(host.started, [record["id"], record["id"]])

    def test_terminal_standalone_session_restart_completes_open_task(self):
        admission_host = NoopHost()
        self.start_server(admission_host)
        pins = {
            "dispatch_authority": "static",
            "participants": [{"id": "lead"}],
        }
        with mock.patch.object(
            brainstorming_tasks, "resolve_staffing", return_value=pins
        ):
            record = self.request(
                "POST", "/api/tasks", self.order("brainstorming")
            )[1]["task"]

        session_id = "terminal-standalone-session"
        session_record = {
            "id": session_id,
            "caller": "task:%s" % record["id"],
            "project": None,
            "execution_context": {"workspace_path": self.primary},
        }
        projection = {
            "id": session_id,
            "process": "stopped",
            "state": {"status": "success"},
        }
        terminal_result = {
            "status": "success",
            "duration_s": 1.0,
            "token_usage": None,
            "token_usage_partial": True,
            "cost": None,
            "cost_partial": True,
            "native_result": {"agreement": "kept opaque"},
        }

        def finish(state, task_id, *_args, **_kwargs):
            return tasks.record_task_result(state, task_id, terminal_result)

        host = task_api.DirectTaskHost(self.home, poll_interval=0.01)
        self.start_server(host)
        with mock.patch.object(
            service.brainstorming_lifecycle,
            "_record_by_id",
            return_value=session_record,
        ), mock.patch.object(
            service.brainstorming_lifecycle,
            "inspect_session",
            return_value=projection,
        ), mock.patch.object(
            brainstorming_tasks, "start_task", return_value=projection
        ) as started, mock.patch.object(
            brainstorming_tasks, "finish_task", side_effect=finish
        ):
            with service._git_sync_lease(self.home, self.primary):
                status, body = self.request(
                    "POST",
                    "/api/brainstorming/sessions/%s/start" % session_id,
                    {},
                )
            self.assertEqual(
                (status, body["error"]), (409, service.WORK_AREA_BUSY)
            )
            self.assertEqual(started.call_count, 0)
            self.assertIsNone(
                task_api.StandaloneTaskStore(self.home).record(record["id"])[
                    "result"
                ]
            )

            status, body = self.request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % session_id,
                {},
            )
            completed = self.wait_record(record["id"])

        self.assertEqual((status, body["session"]), (200, projection))
        self.assertGreaterEqual(started.call_count, 2)
        self.assertEqual(completed["id"], record["id"])
        self.assertEqual(completed["result"], terminal_result)

    def test_task_list_and_inspect_apply_record_access(self):
        self.project("mine", self.primary, [access.USER_EMAILS[0]])
        other = self.directory("foreign")
        self.project("other", other)
        mine = self.request("POST", "/api/tasks", self.order(
            work_area={"project": "mine", "work_area": "main"}
        ))[1]["task"]
        foreign = self.request("POST", "/api/tasks", self.order(
            work_area={"project": "other", "work_area": "main"}
        ))[1]["task"]
        administrative = self.request("POST", "/api/tasks", self.order())[1]["task"]
        store = task_api.StandaloneTaskStore(self.home)
        store.record_result(administrative["id"], {
            "status": "success", "duration_s": 0.0,
            "token_usage": None, "token_usage_partial": True,
            "cost": None, "cost_partial": True, "native_result": "done",
        })

        state_path = os.path.join(self.tmp.name, "registered-state.json")
        state = st.new_state("registered", self.primary, {})
        milestone = tasks.admit_task(
            state, mine["order"], {"worker": {"agent": "codex"}}, self.primary
        )
        foreign_bound = tasks.admit_task(
            state, foreign["order"], {"worker": {"agent": "codex"}}, other
        )
        st.save_new(state_path, state)
        registry.add(self.home, registry.new_entry(
            "registered", "registered", self.primary, state_path,
            project="mine", work_area="main",
        ))
        with open(task_api.records_path(self.home), "rb") as handle:
            before = handle.read()
        member = self.member()
        member_tasks = self.request("GET", "/api/tasks", headers=member)[1]["tasks"]
        self.assertEqual({row["id"] for row in member_tasks}, {mine["id"], milestone["id"]})
        admin_tasks = self.request("GET", "/api/tasks")[1]["tasks"]
        self.assertEqual({row["id"] for row in admin_tasks},
                         {mine["id"], foreign["id"], administrative["id"],
                          milestone["id"], foreign_bound["id"]})
        self.assertEqual(self.request("GET", "/api/tasks/unknown")[0], 404)
        registry.add(self.home, registry.new_entry(
            "broken-foreign", "broken-foreign", other,
            os.path.join(self.tmp.name, "missing-foreign-state.json"),
            project="other", work_area="main",
        ))
        self.assertEqual(self.request("GET", "/api/tasks/%s" % mine["id"],
                                      headers=member)[1]["task"], mine)
        self.assertEqual(self.request(
            "GET", "/api/tasks/%s" % milestone["id"], headers=member
        )[1]["task"], milestone)
        status, body = self.request(
            "GET", "/api/tasks/%s" % foreign_bound["id"], headers=member
        )
        self.assertEqual((status, body["error"]), (403, service.FORBIDDEN))
        status, body = self.request("GET", "/api/tasks/%s" % foreign["id"],
                                    headers=member)
        self.assertEqual((status, body["error"]), (403, service.FORBIDDEN))

        registry.add(self.home, registry.new_entry(
            "broken-accessible", "broken-accessible", self.primary,
            os.path.join(self.tmp.name, "missing-accessible-state.json"),
            project="mine", work_area="main",
        ))
        status, body = self.request("GET", "/api/tasks", headers=member)
        self.assertEqual(status, 200, body)
        self.assertEqual(
            {row["id"] for row in body["tasks"]},
            {mine["id"], milestone["id"]},
        )
        status, body = self.request("GET", "/api/tasks")
        self.assertEqual(status, 200, body)
        self.assertEqual(
            {row["id"] for row in body["tasks"]},
            {
                mine["id"], foreign["id"], administrative["id"],
                milestone["id"], foreign_bound["id"],
            },
        )
        with open(task_api.records_path(self.home), "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_direct_tasks_share_the_two_way_git_sync_exclusion(self):
        before = len(task_api.StandaloneTaskStore(self.home).records())
        with service._git_sync_lease(self.home, self.primary):
            status, body = self.request("POST", "/api/tasks", self.order())
        self.assertEqual((status, body["error"]), (409, service.WORK_AREA_BUSY))
        self.assertEqual(
            len(task_api.StandaloneTaskStore(self.home).records()), before
        )

        entered, release = threading.Event(), threading.Event()

        class Runner:
            def call(_self, *_args, **_kwargs):
                entered.set()
                release.wait(5)
                return runners.RunnerResult("done", 0, 0.1)

        host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: Runner()
        )
        self.start_server(host)
        self.project("mine", self.primary)
        record = self.request(
            "POST",
            "/api/tasks",
            self.order(work_area={"project": "mine", "work_area": "main"}),
        )[1]["task"]
        self.assertTrue(entered.wait(2))
        try:
            with mock.patch.object(
                service.gitops, "is_repo_root", return_value=True
            ), mock.patch.object(
                service.gitsync,
                "run_sync",
                side_effect=AssertionError("sync must not launch"),
            ):
                status, body = self.request(
                    "POST",
                    "/api/projects/mine/git-sync",
                    {"work_area": "main"},
                )
            self.assertEqual(
                (status, body["error"]), (409, service.WORK_AREA_BUSY)
            )
        finally:
            release.set()
        self.assertEqual(
            self.wait_record(record["id"])["result"]["status"], "success"
        )

    def test_direct_interruption_adds_no_retry_or_liveness_claim(self):
        first = self.request("POST", "/api/tasks", self.order())[1]["task"]
        second = self.request("POST", "/api/tasks", self.order())[1]["task"]
        self.assertNotEqual(first["id"], second["id"])
        self.assertIsNone(task_api.StandaloneTaskStore(self.home).record(first["id"])
                          ["result"])
        for method, suffix in (
            ("POST", "start"), ("POST", "retry"), ("POST", "cancel"),
            ("DELETE", ""),
        ):
            path = "/api/tasks/%s%s" % (
                first["id"], "/" + suffix if suffix else ""
            )
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(method, path, {})[0], 404)


if __name__ == "__main__":
    unittest.main()
