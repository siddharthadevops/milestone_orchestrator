"""Public Pause/Resume authorization, durable projection and fencing."""

import os
import copy
import threading
import unittest
from unittest import mock

from orchestrator import brainstorming, brainstorming_lifecycle
from orchestrator import contracts, registry, runners, service, task_api, tasks
from orchestrator import state as st
from orchestrator.tests import test_task_api as task_api_tests


class HeldHost(task_api.DirectTaskHost):
    """Exercise real control/store logic without dispatching any agent work."""

    def __init__(self, home):
        super().__init__(home)
        self.started = []

    def start(self, record, config_resolver, parent_task_id=None):
        self.started.append(record["id"])


class TaskControlsApiTest(unittest.TestCase):
    directory = task_api_tests.TaskApiTest.directory
    start_server = task_api_tests.TaskApiTest.start_server
    request = task_api_tests.TaskApiTest.request
    order = task_api_tests.TaskApiTest.order
    project = task_api_tests.TaskApiTest.project
    member = staticmethod(task_api_tests.TaskApiTest.member)
    wait_record = task_api_tests.TaskApiTest.wait_record
    wait_lifecycle = task_api_tests.TaskApiTest.wait_lifecycle
    _sleeper = task_api_tests.TaskApiTest._sleeper
    _manual_brainstorming = task_api_tests.TaskApiTest._manual_brainstorming
    _waiting_manual_brainstorming = task_api_tests.TaskApiTest._waiting_manual_brainstorming

    def setUp(self):
        task_api_tests.TaskApiTest.setUp(self)
        self.host = HeldHost(self.home)
        self.start_server(self.host)
        self.store = self.host.store

    def create(self, executor="agent_call", work_area=None):
        order = self.order(executor, work_area=work_area)
        if executor == "reviewed_task":
            order["configuration"] = {"task_kind": contracts.KIND_IMPLEMENT}
        status, response = self.request("POST", "/api/tasks", order)
        self.assertEqual(status, 201, response)
        return response["task"]

    def pause(self, record, body=None):
        code, response = self.request(
            "POST", "/api/tasks/%s/pause" % record["id"], body or {}
        )
        self.assertEqual(code, 200, response)
        return response["lifecycle"]

    def finish(self, record):
        self.store.record_result(record["id"], {
            "status": "success", "duration_s": 1.0, "token_usage": None,
            "token_usage_partial": True, "cost": None, "cost_partial": True,
            "native_result": "finished",
        })

    def test_all_three_types_pause_and_resume_same_canonical_identity(self):
        for executor in ("agent_call", "reviewed_task", "deep_task"):
            with self.subTest(executor=executor):
                record = self.create(executor)
                paused = self.pause(record, {"reason": "Wait for operator"})
                self.assertEqual(paused["status"], "paused")
                self.assertEqual(paused["reason"], "Wait for operator")
                self.assertTrue(paused["can_resume"])
                code, read = self.request("GET", "/api/tasks/" + record["id"])
                self.assertEqual(code, 200, read)
                self.assertEqual(read["task"], record)
                self.assertEqual(read["lifecycle"]["revision"], paused["revision"])
                if executor != "agent_call":
                    self.assertEqual(read[executor]["status"], "paused")
                rows = self.request("GET", "/api/tasks?scope=direct")[1]["rows"]
                row = next(row for row in rows if row["record"]["id"] == record["id"])
                self.assertEqual(row["lifecycle"]["status"], "paused")
                self.assertIsNone(row["record"]["result"])
                code, resumed = self.request(
                    "POST", "/api/tasks/%s/resume" % record["id"],
                    {"revision": paused["revision"]},
                )
                self.assertEqual(code, 200, resumed)
                self.assertEqual(resumed["lifecycle"]["status"], "running")
                self.assertEqual(self.store.record(record["id"]), record)
                self.assertEqual(self.host.started.count(record["id"]), 2)
                self.finish(record)

    def test_invalid_control_bodies_do_not_change_durable_state(self):
        record = self.create()
        initial = self.store.lifecycle(record["id"])
        for body in ({"reason": ""}, {"reason": 8}, {"reason": None}, {"force": True}):
            with self.subTest(pause=body):
                self.assertEqual(self.request(
                    "POST", "/api/tasks/%s/pause" % record["id"], body
                )[0], 400)
        self.assertEqual(initial, self.store.lifecycle(record["id"]))
        paused = self.pause(record)
        for body in ({}, {"revision": True}, {"revision": -1},
                     {"revision": "1"}, {"revision": 1.5},
                     {"revision": paused["revision"], "force": True}):
            with self.subTest(resume=body):
                self.assertEqual(self.request(
                    "POST", "/api/tasks/%s/resume" % record["id"], body
                )[0], 400)
        self.assertEqual(self.store.lifecycle(record["id"])["status"], "paused")
        self.assertEqual(self.host.started.count(record["id"]), 1)

    def test_stale_and_repeated_resume_return_conflict_without_relaunch(self):
        record = self.create()
        paused = self.pause(record)
        path = "/api/tasks/%s/resume" % record["id"]
        self.assertEqual(self.request("POST", path, {
            "revision": paused["revision"] - 1
        })[0], 409)
        self.assertEqual(self.request("POST", path, {
            "revision": paused["revision"]
        })[0], 200)
        self.assertEqual(self.request("POST", path, {
            "revision": paused["revision"]
        })[0], 409)
        self.assertEqual(self.host.started.count(record["id"]), 2)

    def test_failure_pause_survives_new_host_and_http_server(self):
        record = self.create()
        with registry.locked(self.home):
            self.store.pause_locked(record["id"], "review quota exhausted", source="error")
        before = self.request("GET", "/api/tasks/" + record["id"])[1]
        self.host = HeldHost(self.home)
        self.start_server(self.host)
        after = self.request("GET", "/api/tasks/" + record["id"])[1]
        self.assertEqual(before["lifecycle"], after["lifecycle"])
        self.assertEqual(after["task"], record)
        self.assertTrue(after["lifecycle"]["can_resume"])
        self.assertEqual(self.host.started, [])

    def test_live_execution_lease_blocks_resume_and_explains_it_in_get(self):
        record = self.create()
        paused = self.pause(record)
        lease = self.host._lease(record["id"]).acquire()
        try:
            read = self.request("GET", "/api/tasks/" + record["id"])[1]
            self.assertFalse(read["lifecycle"]["can_resume"])
            self.assertTrue(read["lifecycle"]["blocked_reason"])
            self.assertEqual(self.request(
                "POST", "/api/tasks/%s/resume" % record["id"],
                {"revision": paused["revision"]},
            )[0], 409)
            self.assertEqual(self.store.lifecycle(record["id"])["status"], "paused")
        finally:
            lease.close()
        read = self.request("GET", "/api/tasks/" + record["id"])[1]
        self.assertTrue(read["lifecycle"]["can_resume"])

    def test_controls_enforce_project_access_unknown_ids_and_run_ownership(self):
        self.project("private", self.primary)
        record = self.create(work_area={"project": "private", "work_area": "main"})
        self.pause(record)
        for action, body in (("pause", {}), ("resume", {"revision": 1})):
            self.assertEqual(self.request(
                "POST", "/api/tasks/%s/%s" % (record["id"], action),
                body, self.member(),
            )[0], 403)
            self.assertEqual(self.request(
                "POST", "/api/tasks/no-such-task/" + action, body,
            )[0], 404)
        path = os.path.join(self.tmp.name, "milestone.json")
        state = st.new_state("milestone", self.primary, {})
        milestone = tasks.admit_task(
            state, record["order"], {"worker": {"agent": "codex"}}, self.primary
        )
        st.save_new(path, state)
        registry.add(self.home, registry.new_entry(
            "milestone", "milestone", self.primary, path,
            project="private", work_area="main",
        ))
        for action, body in (("pause", {}), ("resume", {"revision": 0})):
            code, response = self.request(
                "POST", "/api/tasks/%s/%s" % (milestone["id"], action), body
            )
            self.assertEqual(code, 409, response)
            self.assertIn("milestone", response["error"])

    def test_brainstorming_keeps_its_own_control_routes(self):
        record = self.create("brainstorming")
        for action, body in (("pause", {}), ("resume", {"revision": 0})):
            code, response = self.request(
                "POST", "/api/tasks/%s/%s" % (record["id"], action), body
            )
            self.assertEqual(code, 409, response)
            self.assertIn("discussion", response["error"])

    def test_terminal_history_is_not_reopened(self):
        record = self.create()
        result = {
            "status": "failure", "reason": "Historical terminal error",
            "duration_s": 3.0, "token_usage": None, "token_usage_partial": True,
            "cost": None, "cost_partial": True, "native_result": "original output",
        }
        self.store.record_result(record["id"], result)
        for action, body in (("pause", {}), ("resume", {"revision": 0})):
            self.assertEqual(self.request(
                "POST", "/api/tasks/%s/%s" % (record["id"], action), body
            )[0], 409)
        self.assertEqual(self.store.record(record["id"])["result"], result)

    def test_workspace_conflict_does_not_accept_resume(self):
        record = self.create()
        paused = self.pause(record)
        with mock.patch.object(self.host, "owns_workspace_except", return_value=True) as owns:
            code, response = self.request(
                "POST", "/api/tasks/%s/resume" % record["id"],
                {"revision": paused["revision"]},
            )
        self.assertEqual((code, response["error"]), (409, service.WORK_AREA_BUSY))
        owns.assert_called_once_with(self.primary, record["id"])
        self.assertEqual(self.store.lifecycle(record["id"])["status"], "paused")

    def test_pausing_child_projects_parent_and_resumes_existing_child(self):
        template = self.create("reviewed_task")
        self.finish(template)
        parent = self.create("deep_task")
        with registry.locked(self.home):
            child = self.store.admit_related_locked(
                parent["id"], "documentation", None, template["order"], {}, self.primary
            )
        paused = self.pause(child)
        self.assertEqual(paused["root_task_id"], parent["id"])
        code, read = self.request("GET", "/api/tasks/" + parent["id"])
        self.assertEqual(code, 200, read)
        self.assertEqual(read["lifecycle"]["status"], "paused")
        self.assertEqual(read["deep_task"]["status"], "paused")
        self.assertEqual(read["deep_task"]["children"][0]["status"], "paused")
        before = [item["id"] for item in self.store.records()]
        code, response = self.request(
            "POST", "/api/tasks/%s/resume" % parent["id"],
            {"revision": read["lifecycle"]["revision"]},
        )
        self.assertEqual(code, 200, response)
        self.assertEqual([item["id"] for item in self.store.records()], before)
        self.assertEqual(self.store.lifecycle(child["id"])["status"], "running")
        self.assertEqual(self.host.started.count(parent["id"]), 2)

    def test_handoff_failure_is_acknowledged_as_same_resumable_order(self):
        with mock.patch.object(self.host, "start", side_effect=RuntimeError("launcher unavailable")):
            record = self.create()
        self.assertIsNone(record["result"])
        read = self.request("GET", "/api/tasks/" + record["id"])[1]
        self.assertEqual(read["task"], record)
        self.assertEqual(read["lifecycle"]["status"], "paused")
        self.assertEqual(read["lifecycle"]["source"], "error")
        self.assertIn("launcher unavailable", read["lifecycle"]["reason"])
        self.assertTrue(read["lifecycle"]["can_resume"])

    def test_cancel_refusal_is_a_conflict_not_a_server_error(self):
        record = self.create()
        self.pause(record)
        with mock.patch.object(self.host, "stop", side_effect=task_api.TaskControlConflict("previous worker alive")):
            code, answer = self.request(
                "POST", "/api/tasks/%s/stop" % record["id"], {}
            )
        self.assertEqual((code, answer["error"]), (409, "previous worker alive"))

    def test_public_pause_waits_for_active_call_and_resume_reuses_its_result(self):
        entered, released = threading.Event(), threading.Event()
        self.addCleanup(released.set)
        calls = []

        class Runner:
            def call(_self, *_args, **_kwargs):
                calls.append(True)
                entered.set()
                released.wait(5)
                return runners.RunnerResult("completed before pause boundary", 0, 0.5)

        self.host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: Runner(),
            poll_interval=0.01,
        )
        self.start_server(self.host)
        record = self.create()
        self.assertTrue(entered.wait(3))
        pausing = self.pause(record)
        self.assertEqual(pausing["status"], "pausing")
        self.assertFalse(pausing["can_resume"])
        released.set()
        paused = self.wait_lifecycle(record["id"], "paused")
        # Wait for the coordinator's lease release, which gates Resume.
        for _ in range(300):
            if self.host.lifecycle(record["id"])["can_resume"]:
                break
            threading.Event().wait(0.01)
        self.assertIsNone(self.store.record(record["id"])["result"])
        code, response = self.request(
            "POST", "/api/tasks/%s/resume" % record["id"],
            {"revision": paused["revision"]},
        )
        self.assertEqual(code, 200, response)
        terminal = self.wait_record(record["id"])
        self.assertEqual(terminal["result"]["native_result"], "completed before pause boundary")
        self.assertEqual(len(calls), 1)

    def test_public_failure_resume_retries_once_with_same_id_and_accounting(self):
        calls = []

        class Runner:
            def call(_self, *_args, **_kwargs):
                calls.append(True)
                if len(calls) == 1:
                    failure = runners.ProviderResponseError("quota failure", raw_texts=["partial output"])
                    failure.duration_s = 0.25
                    raise failure
                return runners.RunnerResult("recovered", 0, 0.25)

        self.host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: Runner(),
            poll_interval=0.01,
        )
        self.start_server(self.host)
        record = self.create()
        paused = self.wait_lifecycle(record["id"], "paused")
        for _ in range(300):
            if self.host.lifecycle(record["id"])["can_resume"]:
                break
            threading.Event().wait(0.01)
        self.assertEqual(paused["source"], "error")
        self.assertIsNone(self.store.record(record["id"])["result"])
        code, response = self.request(
            "POST", "/api/tasks/%s/resume" % record["id"],
            {"revision": paused["revision"]},
        )
        self.assertEqual(code, 200, response)
        terminal = self.wait_record(record["id"])
        self.assertEqual(terminal["result"]["status"], "success")
        self.assertEqual(terminal["result"]["native_result"], "recovered")
        self.assertEqual(terminal["result"]["duration_s"], 0.5)
        self.assertEqual(len(calls), 2)

    def test_cancel_winning_after_resume_does_not_count_retained_success_twice(self):
        record = self.create()
        completed = {
            "status": "success", "duration_s": 5.0, "token_usage": None,
            "token_usage_partial": True, "cost": {"api_usd": 2.0, "real_usd": 2.0},
            "cost_partial": False, "native_result": "retained success",
        }
        with registry.locked(self.home):
            paused = self.store.pause_locked(
                record["id"], "manual pause", attempt=completed, completed_result=completed
            )
            self.store.resume_locked(record["id"], paused["revision"])
        # Cancel wins between the optimistic stop read and the read performed
        # under the terminal result lock. No provider work is dispatched.
        with mock.patch.object(self.host, "_stop_reason", side_effect=[None, "cancel accepted"]), \
                mock.patch.object(self.host, "runner_factory") as runner:
            self.host._run_worker(record, lambda: {})
        runner.assert_not_called()
        result = self.store.record(record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["duration_s"], 5.0)
        self.assertEqual(result["cost"], completed["cost"])

    def test_malformed_lifecycle_is_refused_without_reinterpreting_it_as_legacy(self):
        record = self.create()
        key = task_api.task_key(record["id"])
        original = self.store._store.read(key)["value"]
        # The actual legacy shape has NO lifecycle member, and keeps its
        # original canonical task rather than undergoing a migration.
        self.assertNotIn("lifecycle", original)
        self.assertEqual(self.store.lifecycle(record["id"])["status"], "running")
        valid = {"status": "paused", "revision": 1, "reason": "quota",
                 "source": "error", "history": []}
        malformed = [None, {}, dict(valid, history=[None]),
                     dict(valid, reason={}), dict(valid, source=None),
                     dict(valid, revision=True), dict(valid, completed_result={}),
                     dict(valid, history=[{"status": "paused", "at": "today"}]),
                     dict(valid, history=[{"status": "paused", "at": "today",
                                          "reason": "quota", "source": "error", "attempt": {}}])]
        for lifecycle in malformed:
            with self.subTest(lifecycle=lifecycle):
                current = self.store._store.read(key)
                self.store._store.cas(key, current["revision"],
                                      dict(copy.deepcopy(original), lifecycle=lifecycle))
                with self.assertRaises(tasks.TaskRecordError):
                    self.store.lifecycle(record["id"])
                with self.assertRaises(tasks.TaskRecordError):
                    self.host.resume(record["id"], lambda: {}, 1)
                self.assertEqual(self.host.started, [record["id"]])
        current = self.store._store.read(key)
        self.store._store.cas(key, current["revision"], original)
        self.assertEqual(self.store.record(record["id"]), record)

    def test_delete_terminal_task_retains_owner_until_prior_worker_is_quiescent(self):
        record = self.create()
        lease = self.host._lease(record["id"]).acquire()
        self.finish(record)
        try:
            code, response = self.request("DELETE", "/api/tasks/" + record["id"])
            self.assertEqual(code, 409, response)
            self.assertIn("not quiescent", response["error"])
            self.assertEqual(self.store.record(record["id"])["id"], record["id"])
        finally:
            lease.close()
        code, response = self.request("DELETE", "/api/tasks/" + record["id"])
        self.assertEqual(code, 200, response)
        self.assertTrue(response["deleted"])
        self.assertTrue(os.path.isfile(lease.lock_path))

    def test_cancel_winning_failure_pause_race_settles_without_restart(self):
        entered, released = threading.Event(), threading.Event()
        self.addCleanup(released.set)
        runner = runners.MockRunner([])
        self.host = task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: runner,
            poll_interval=0.01,
        )
        self.start_server(self.host)
        pause_failure = self.host._pause_failure
        run_reviewed = self.host._run_reviewed

        def failed_step(record):
            if self.store.stop_reason(record["id"]):
                return run_reviewed(record)  # The real Cancel settlement path.
            self.host._publish_reviewed_terminal(
                record["id"], None, None,
                {"status": "failure", "reason": "review failed"},
            )

        def delayed_pause(task_id, reason, **kwargs):
            entered.set()
            released.wait(5)
            return pause_failure(task_id, reason, **kwargs)

        with mock.patch.object(self.host, "_run_reviewed", side_effect=failed_step), \
                mock.patch.object(self.host, "_pause_failure", side_effect=delayed_pause):
            record = self.create("reviewed_task")
            self.assertTrue(entered.wait(3))
            code, response = self.request(
                "POST", "/api/tasks/%s/stop" % record["id"], {}
            )
            self.assertEqual(code, 200, response)
            self.assertTrue(response["stopped"])
            released.set()
            terminal = self.wait_record(record["id"])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertIn("stopped by", terminal["result"]["reason"])

    def _owned_waiting_discussion(self, producer=False, deep=False):
        session_id, waiting = self._waiting_manual_brainstorming("owner-pause.md")
        parent = self.create("deep_task") if deep else None
        if parent:
            with registry.locked(self.home):
                owner = self.store.admit_related_locked(
                    parent["id"], "documentation", None,
                    tasks.deep_documentation_order(parent), {}, self.primary,
                )
        else:
            owner = self.create("reviewed_task")
        path = task_api.ensure_reviewed_state(
            self.home, owner, service._reviewed_task_config(self.home)
        )
        state = st.load(path)
        unit_key = state["reviewed_task"]["unit"]
        unit = next(unit for unit in state["units"] if st.unit_key(unit) == unit_key)
        unit["brainstorming_wait"] = {"session_id": session_id}
        if producer:
            inner = tasks.admit_task(state, self.order("brainstorming"),
                                     {"dispatch_authority": "static"}, self.primary)
            caller = "task:" + inner["id"]
        else:
            caller = "milestone:%s:%s" % (state["name"], unit_key)
        st.save(path, state)
        with brainstorming_lifecycle._locked_registry(self.home):
            document = brainstorming_lifecycle._load_registry(self.home)
            session = brainstorming_lifecycle._find_record(document, session_id)
            session["caller"] = caller
            session["execution_context"] = {"workspace_path": self.primary}
            brainstorming_lifecycle._save_registry(self.home, document)
        return owner, parent, session_id, waiting

    def test_reviewed_pause_blocks_discussion_continue_without_consuming_revision(self):
        owner, _, session_id, waiting = self._owned_waiting_discussion()
        self.pause(owner)
        with mock.patch.object(brainstorming_lifecycle, "_launch_lifecycle_process") as launch:
            code, answer = self.request(
                "POST", "/api/brainstorming/sessions/%s/continue" % session_id,
                {"waiting_revision": waiting.revision},
            )
        launch.assert_not_called()
        self.assertEqual(code, 409, answer)
        self.assertIn("Resume", answer["error"])
        self.assertEqual(brainstorming.SessionStore(
            brainstorming_lifecycle.state_directory(self.home)
        ).read(session_id).revision, waiting.revision)

    def test_paused_deep_owner_blocks_inner_producer_continue(self):
        owner, parent, session_id, waiting = self._owned_waiting_discussion(producer=True, deep=True)
        # Also covers the small parent-first pause-persistence window.
        with registry.locked(self.home):
            self.store.pause_locked(parent["id"], "operator pause")
        with mock.patch.object(brainstorming_lifecycle, "_launch_lifecycle_process") as launch:
            code, answer = self.request(
                "POST", "/api/brainstorming/sessions/%s/continue" % session_id,
                {"waiting_revision": waiting.revision},
            )
        self.assertEqual(code, 409, answer)
        self.assertIn("Resume", answer["error"])
        launch.assert_not_called()
        self.assertEqual(self.store.lifecycle(owner["id"])["status"], "running")

    def test_discussion_start_requires_owner_resume_but_then_remains_available(self):
        owner, _, session_id, waiting = self._owned_waiting_discussion()
        brainstorming.SessionStore(brainstorming_lifecycle.state_directory(self.home)).continue_waiting(
            session_id, waiting.revision
        )
        paused = self.pause(owner)
        path = "/api/brainstorming/sessions/%s/start" % session_id
        with mock.patch.object(brainstorming_lifecycle, "_launch_lifecycle_process") as launch:
            code, answer = self.request("POST", path, {})
        self.assertEqual(code, 409, answer)
        self.assertIn("Resume", answer["error"])
        launch.assert_not_called()
        code, resumed = self.request("POST", "/api/tasks/%s/resume" % owner["id"],
                                     {"revision": paused["revision"]})
        self.assertEqual(code, 200, resumed)
        process = self._sleeper()
        with mock.patch.object(brainstorming_lifecycle, "_launch_lifecycle_process",
                               return_value=brainstorming_lifecycle.GatedLaunch(
                                   process, lambda: None, process.terminate)) as launch:
            code, answer = self.request("POST", path, {})
        self.assertEqual(code, 200, answer)
        launch.assert_called_once()
        self.assertEqual(answer["session"]["process"], "running")

    def test_running_reviewed_owner_allows_normal_waiting_continuation(self):
        owner, _, session_id, waiting = self._owned_waiting_discussion(producer=True)
        process = self._sleeper()
        with mock.patch.object(brainstorming_lifecycle, "_launch_lifecycle_process",
                               return_value=brainstorming_lifecycle.GatedLaunch(
                                   process, lambda: None, process.terminate)) as launch:
            code, answer = self.request(
                "POST", "/api/brainstorming/sessions/%s/continue" % session_id,
                {"waiting_revision": waiting.revision},
            )
        self.assertEqual(code, 200, answer)
        launch.assert_called_once()
        self.assertEqual(answer["session"]["state"]["status"], "running")
        self.assertEqual(self.store.lifecycle(owner["id"])["status"], "running")

    def test_stale_session_projection_cannot_skip_owner_pause_fence(self):
        owner, _, session_id, waiting = self._owned_waiting_discussion()
        self.pause(owner)
        stale = brainstorming_lifecycle.inspect_session(self.home, session_id, lambda _: None)
        stale["state"]["status"] = "running"
        stale["revision"] = waiting.revision - 1
        with mock.patch.object(brainstorming_lifecycle, "inspect_session", return_value=stale), \
                mock.patch.object(brainstorming_lifecycle, "_launch_lifecycle_process") as launch:
            code, answer = self.request(
                "POST", "/api/brainstorming/sessions/%s/continue" % session_id,
                {"waiting_revision": waiting.revision},
            )
        self.assertEqual(code, 409, answer)
        self.assertIn("Resume", answer["error"])
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
