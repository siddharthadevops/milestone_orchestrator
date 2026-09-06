"""Pause/Resume preserves logical work and never retries completed steps."""

import copy
from concurrent import futures
from contextlib import ExitStack
import threading
import time
import unittest
from unittest import mock

from orchestrator import brainstorming, brainstorming_lifecycle, brainstorming_milestone
from orchestrator import contracts, gitops, runners, service, task_api
from orchestrator import driver as drv
from orchestrator import state as st
from orchestrator.tests import test_reviewed_task_api as reviewed_tests
from orchestrator.tests import test_task_api as api_tests


class TaskRecoveryTest(unittest.TestCase):
    # Shared real-Git and HTTP fixtures, without inheriting unrelated tests.
    setUp = api_tests.TaskApiTest.setUp
    directory = api_tests.TaskApiTest.directory
    start_server = api_tests.TaskApiTest.start_server
    request = api_tests.TaskApiTest.request
    order = api_tests.TaskApiTest.order
    _git = staticmethod(reviewed_tests.ReviewedTaskOrderingTest._git)
    _script = staticmethod(reviewed_tests.ReviewedTaskOrderingTest._script)
    _config = staticmethod(reviewed_tests.ReviewedTaskOrderingTest._config)
    _sleeper = api_tests.TaskApiTest._sleeper
    _manual_brainstorming = api_tests.TaskApiTest._manual_brainstorming
    _waiting_manual_brainstorming = api_tests.TaskApiTest._waiting_manual_brainstorming
    _waiting_rethink_session = reviewed_tests.ReviewedTaskOrderingTest._waiting_rethink_session

    def _admit(self, executor="reviewed_task", kind="draft_slice_note"):
        order = self.order(executor, work_area={
            "workspace_path": self.primary,
            "primary": self.primary,
            "additional": [],
        })
        if executor == "reviewed_task":
            order["configuration"] = {"task_kind": kind}
        with mock.patch.object(
            service, "_direct_task_config", return_value=self._config()
        ):
            status, body = self.request("POST", "/api/tasks", order)
        self.assertEqual(status, 201, body)
        return body["task"]

    def _host(self, *owned_runners):
        pending = list(owned_runners)
        host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: pending.pop(0),
            poll_interval=0.001,
        )
        host.test_pending_runners = pending
        return host

    def _wait(self, predicate, description):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.01)
        self.fail(description)

    def _paused(self, host, task_id):
        store = task_api.StandaloneTaskStore(self.home)

        def paused():
            lifecycle = store.lifecycle(task_id)
            self.assertIsNone(store.record(task_id)["result"], lifecycle)
            return lifecycle if lifecycle["status"] == "paused" \
                and not host.is_active(task_id) else None

        lifecycle = self._wait(paused, "task did not become durably paused")
        self.assertIsNone(store.record(task_id)["result"])
        return lifecycle

    def _terminal(self, host, task_id):
        store = task_api.StandaloneTaskStore(self.home)

        def finished():
            record = store.record(task_id)
            return record if record["result"] is not None \
                and not host.is_active(task_id) else None

        return self._wait(finished, "task did not settle its terminal result")

    def _state(self, task_id):
        return st.load(task_api.reviewed_state_path(self.home, task_id))

    @staticmethod
    def _unit(state):
        return next(unit for unit in state["units"]
                    if st.unit_key(unit) == state["reviewed_task"]["unit"])

    @staticmethod
    def _fail_call(_workspace):
        error = runners.ProviderResponseError(
            "usage limit exceeded", token_usage={
                "input_tokens": 17, "output_tokens": 3,
            },
        )
        error.duration_s = 0.25
        raise error

    def _failed_review_script(self, kind):
        script = self._script(kind)
        failure = copy.deepcopy(script[1])
        failure["side_effect"] = self._fail_call
        return [script[0], failure], script[1:]

    def test_review_failure_resumes_same_unit_without_repeating_production(self):
        record = self._admit()
        failed_script, continuation = self._failed_review_script(
            contracts.KIND_DRAFT_SLICE_NOTE
        )
        first = runners.MockRunner(failed_script)
        second = runners.MockRunner(continuation)
        host = self._host(first, second)
        host.start(record, self._config)
        paused = self._paused(host, record["id"])
        before = self._state(record["id"])
        before_unit = self._unit(before)
        self.assertEqual(before_unit["failed_from"], st.U_ROUNDS)
        self.assertEqual(len(first.calls), 2)
        history = copy.deepcopy(before["events"])

        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])
        after = self._state(record["id"])
        self.assertEqual(terminal["id"], record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        self.assertEqual(after["events"][:len(history)], history)
        self.assertEqual(self._unit(after)["draft"], before_unit["draft"])
        self.assertEqual(sum(
            kind == contracts.KIND_DRAFT_SLICE_NOTE
            for _family, kind, _prompt in first.calls + second.calls
        ), 1)
        self.assertEqual(sum(
            event["type"] == "wip_commit" for event in after["events"]
        ), 1)
        self.assertEqual(sum(
            event["type"] == "resumed" for event in after["events"]
        ), 1)
        self.assertEqual(terminal["result"]["token_usage"]["input_tokens"], 17)
        self.assertEqual(terminal["result"]["token_usage"]["output_tokens"], 3)
        self.assertAlmostEqual(terminal["result"]["duration_s"], 0.28)

    def test_first_network_or_protocol_failure_pauses_without_automatic_retry(self):
        for fault in ("network", "protocol"):
            with self.subTest(fault=fault):
                record = self._admit()
                script = self._script(
                    contracts.KIND_DRAFT_SLICE_NOTE, marker=fault
                )
                failed_review = copy.deepcopy(script[1])
                if fault == "network":
                    def network_failure(_workspace):
                        raise runners.RunnerError("connection reset by peer")

                    failed_review["side_effect"] = network_failure
                else:
                    failed_review["response"] = "not a JSON review"
                first = runners.MockRunner([script[0], failed_review])
                second = runners.MockRunner(script[1:])
                host = self._host(first, second)
                config = self._config()
                # Even inherited automatic-retry policy must not launch a
                # second physical attempt for an operator-resumable task.
                config["infra_retry_backoff_s"] = [0]
                host.start(record, lambda: config)
                paused = self._paused(host, record["id"])
                self.assertEqual(len(first.calls), 2, [
                    kind for _family, kind, _prompt in first.calls
                ])
                self.assertEqual(second.calls, [])
                host.resume(record["id"], lambda: config, paused["revision"])
                result = self._terminal(host, record["id"])["result"]
                self.assertEqual(result["status"], "success", result)

    def test_manual_pause_finishes_current_production_then_waits_for_resume(self):
        record = self._admit()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        script = self._script(contracts.KIND_DRAFT_SLICE_NOTE)
        write_draft = script[0]["side_effect"]

        def blocked_production(workspace):
            entered.set()
            if not release.wait(10):
                raise AssertionError("test did not release active production")
            write_draft(workspace)

        script[0]["side_effect"] = blocked_production
        first = runners.MockRunner(script[:1])
        second = runners.MockRunner(script[1:])
        host = self._host(first, second)
        host.start(record, self._config)
        self.assertTrue(entered.wait(5))
        host.pause(record["id"], "operator wants to inspect the draft")
        store = task_api.StandaloneTaskStore(self.home)
        self.assertEqual(store.lifecycle(record["id"])["status"], "pausing")
        self.assertIsNone(store.record(record["id"])["result"])
        release.set()
        paused = self._paused(host, record["id"])
        state = self._state(record["id"])
        self.assertIsNotNone(self._unit(state)["draft"])
        self.assertIsNone(state["failure"])
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(second.calls, [])

        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        self.assertEqual(len(first.calls + second.calls), 3)

    def test_deep_child_failure_pauses_parent_and_resumes_exact_child(self):
        record = self._admit("deep_task")
        doc_runner = runners.MockRunner(self._script(
            contracts.KIND_DRAFT_SLICE_NOTE
        ))
        failed_script, continuation = self._failed_review_script(
            contracts.KIND_IMPLEMENT
        )
        failed_impl = runners.MockRunner(failed_script)
        resumed_impl = runners.MockRunner(continuation)
        host = self._host(doc_runner, failed_impl, resumed_impl)
        host.start(record, self._config)
        paused = self._paused(host, record["id"])
        store = task_api.StandaloneTaskStore(self.home)
        doc = store.related(record["id"], "documentation", None)
        child = store.related(record["id"], "implementation", "a")
        self.assertEqual(doc["result"]["status"], "success")
        self.assertIsNone(child["result"])
        self.assertEqual(store.lifecycle(child["id"])["status"], "paused")
        self.assertIsNone(store.related(record["id"], "implementation", "b"))

        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        self.assertEqual(store.related(
            record["id"], "documentation", None
        ), doc)
        resumed_child = store.related(record["id"], "implementation", "a")
        self.assertEqual(resumed_child["id"], child["id"])
        self.assertEqual(resumed_child["result"]["status"], "success")
        self.assertEqual(len(store.records()), 3)
        self.assertEqual(sum(
            kind == contracts.KIND_IMPLEMENT
            for _family, kind, _prompt in failed_impl.calls + resumed_impl.calls
        ), 1)
        self.assertEqual(host.test_pending_runners, [])

    def test_failed_family_resume_returns_every_member_to_paused(self):
        record = self._admit("deep_task")
        failed_script, continuation = self._failed_review_script(
            contracts.KIND_IMPLEMENT
        )
        host = self._host(
            runners.MockRunner(self._script(contracts.KIND_DRAFT_SLICE_NOTE)),
            runners.MockRunner(failed_script),
            runners.MockRunner(continuation),
        )
        host.start(record, self._config)
        paused = self._paused(host, record["id"])
        store = task_api.StandaloneTaskStore(self.home)
        child = store.related(record["id"], "implementation", "a")
        resume_member = host.store.resume_locked

        def fail_child_write(task_id, revision):
            if task_id == child["id"]:
                raise OSError("could not save child resume control")
            return resume_member(task_id, revision)

        with mock.patch.object(
            host.store, "resume_locked", side_effect=fail_child_write
        ), self.assertRaises(OSError):
            host.resume(record["id"], self._config, paused["revision"])
        for identity in (record["id"], child["id"]):
            self.assertEqual(store.lifecycle(identity)["status"], "paused")
            self.assertFalse(host.is_active(identity))
            self.assertIsNone(store.record(identity)["result"])
        current = store.lifecycle(record["id"])
        host.resume(record["id"], self._config, current["revision"])
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        self.assertEqual(store.related(
            record["id"], "implementation", "a"
        )["id"], child["id"])
        self.assertEqual(sum(
            event["type"] == "resumed"
            for event in self._state(child["id"])["events"]
        ), 1)

    def test_manual_deep_pause_through_child_preserves_the_whole_family(self):
        record = self._admit("deep_task")
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        script = self._script(contracts.KIND_IMPLEMENT)
        write_implementation = script[0]["side_effect"]

        def blocked_production(workspace):
            entered.set()
            if not release.wait(10):
                raise AssertionError("test did not release deep implementation")
            write_implementation(workspace)

        script[0]["side_effect"] = blocked_production
        first = runners.MockRunner(script[:1])
        second = runners.MockRunner(script[1:])
        host = self._host(
            runners.MockRunner(self._script(contracts.KIND_DRAFT_SLICE_NOTE)),
            first, second,
        )
        host.start(record, self._config)
        self.assertTrue(entered.wait(8))
        store = task_api.StandaloneTaskStore(self.home)
        child = store.related(record["id"], "implementation", "a")
        documentation = store.related(record["id"], "documentation", None)
        host.pause(child["id"], "inspect the current implementation")
        self.assertEqual(store.lifecycle(record["id"])["status"], "pausing")
        release.set()
        self._paused(host, record["id"])
        child_pause = self._paused(host, child["id"])
        self.assertEqual(first.calls[0][1], contracts.KIND_IMPLEMENT)
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(second.calls, [])
        self.assertIsNotNone(self._unit(self._state(child["id"]))["draft"])
        host.resume(child["id"], self._config, child_pause["revision"])
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        self.assertEqual(store.related(
            record["id"], "documentation", None
        ), documentation)
        self.assertEqual(store.related(
            record["id"], "implementation", "a"
        )["id"], child["id"])

    def test_failed_gate_adopts_landed_commit_without_second_commit_or_call(self):
        record = self._admit()
        first = runners.MockRunner(self._script(
            contracts.KIND_DRAFT_SLICE_NOTE
        ))
        second = runners.MockRunner([])
        host = self._host(first, second)
        real_gate = gitops.finalize_gate

        def land_then_fail(workspace, message):
            real_gate(workspace, message)
            raise gitops.GitError("lost gate acknowledgement")

        with mock.patch.object(
            gitops, "finalize_gate", side_effect=land_then_fail
        ):
            host.start(record, self._config)
            paused = self._paused(host, record["id"])
        landed = self._git(self.primary, "rev-parse", "HEAD")
        commits = self._git(self.primary, "rev-list", "--count", "HEAD")
        self.assertIsNotNone(self._state(record["id"])["pending_gate_unit"])

        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        self.assertEqual(self._git(self.primary, "rev-parse", "HEAD"), landed)
        self.assertEqual(self._git(
            self.primary, "rev-list", "--count", "HEAD"
        ), commits)
        self.assertEqual(second.calls, [])

    def test_pause_winning_reviewed_result_fence_retains_completed_gate(self):
        record = self._admit()
        first = runners.MockRunner(self._script(
            contracts.KIND_DRAFT_SLICE_NOTE
        ))
        second = runners.MockRunner([])
        host = self._host(first, second)
        publish = host._record_reviewed_terminal

        def pause_before_publication(task_id, result, **kwargs):
            host.pause(task_id, "pause won immediately before result publication")
            return publish(task_id, result, **kwargs)

        with mock.patch.object(
            host, "_record_reviewed_terminal", side_effect=pause_before_publication
        ):
            host.start(record, self._config)
            paused = self._paused(host, record["id"])
        landed = self._git(self.primary, "rev-parse", "HEAD")
        unit = self._unit(self._state(record["id"]))
        self.assertEqual(unit["status"], st.U_SEALED)
        self.assertTrue(unit["gate_commit"])
        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        self.assertEqual(self._git(self.primary, "rev-parse", "HEAD"), landed)
        self.assertEqual(second.calls, [])

    def test_stale_resume_cannot_start_a_second_attempt(self):
        record = self._admit("agent_call")
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        class Worker:
            calls = 0

            def call(_self, *_args, **_kwargs):
                _self.calls += 1
                if _self.calls == 1:
                    raise runners.RunnerError("provider refused first attempt")
                entered.set()
                if not release.wait(10):
                    raise AssertionError("test did not release resumed worker")
                return runners.RunnerResult("done", 0, 0.1)

        runner = Worker()
        host = self._host(runner, runner)
        host.start(record, self._config)
        paused = self._paused(host, record["id"])
        competing_resumes = threading.Barrier(2)

        def resume_once():
            competing_resumes.wait(timeout=5)
            try:
                host.resume(record["id"], self._config, paused["revision"])
                return "accepted"
            except task_api.TaskControlConflict:
                return "conflict"

        with futures.ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(resume_once) for _ in range(2)]
            self.assertCountEqual(
                [attempt.result(timeout=5) for attempt in attempts],
                ["accepted", "conflict"],
            )
        self.assertTrue(entered.wait(5))
        with self.assertRaises(task_api.TaskControlConflict):
            host.resume(record["id"], self._config, paused["revision"])
        self.assertEqual(runner.calls, 2)
        release.set()
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)

    def test_historical_terminal_failure_and_success_cannot_be_reopened(self):
        store = task_api.StandaloneTaskStore(self.home)
        host = self._host()
        for result_status in ("failure", "success"):
            with self.subTest(result_status=result_status):
                record = self._admit("agent_call")
                result = {
                    "status": result_status,
                    "duration_s": 0.1, "token_usage": None,
                    "token_usage_partial": True,
                    "cost": None, "cost_partial": True,
                    "native_result": "done" if result_status == "success"
                    else None,
                }
                if result_status == "failure":
                    result["reason"] = "historical terminal failure"
                terminal = store.record_result(record["id"], result)
                with self.assertRaises(task_api.TaskControlConflict):
                    host.resume(record["id"], self._config, 0)
                self.assertEqual(store.record(record["id"]), terminal)
                self.assertFalse(host.is_active(record["id"]))

    def test_cancel_after_failure_is_terminal_not_another_pause(self):
        record = self._admit("agent_call")

        class Worker:
            def call(_self, *_args, **_kwargs):
                raise runners.RunnerError("provider refused first attempt")

        host = self._host(Worker())
        host.start(record, self._config)
        paused = self._paused(host, record["id"])
        self.assertTrue(host.stop(record["id"], "cancelled deliberately"))
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertIn("cancelled deliberately", terminal["result"]["reason"])
        with self.assertRaises(task_api.TaskControlConflict):
            host.resume(record["id"], self._config, paused["revision"])
        self.assertEqual(task_api.StandaloneTaskStore(self.home).record(
            record["id"]
        ), terminal)

    def test_agent_call_success_during_pause_is_retained_until_resume(self):
        record = self._admit("agent_call")
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        class Worker:
            calls = 0

            def call(_self, *_args, **_kwargs):
                _self.calls += 1
                entered.set()
                if not release.wait(10):
                    raise AssertionError("test did not release paused worker")
                return runners.RunnerResult("completed once", 0, 0.125)

        runner = Worker()
        host = self._host(runner)
        host.start(record, self._config)
        self.assertTrue(entered.wait(5))
        host.pause(record["id"], "pause before publishing the answer")
        release.set()
        paused = self._paused(host, record["id"])
        self.assertEqual(runner.calls, 1)
        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal)
        self.assertEqual(terminal["result"]["native_result"], "completed once")
        self.assertEqual(terminal["result"]["duration_s"], 0.125)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(host.test_pending_runners, [])

    def test_failed_agent_call_resume_accumulates_both_attempts_once(self):
        record = self._admit("agent_call")

        class Worker:
            calls = 0

            def call(_self, *_args, **_kwargs):
                _self.calls += 1
                if _self.calls == 1:
                    error = runners.ProviderResponseError(
                        "usage limit exceeded", token_usage={
                            "input_tokens": 17, "output_tokens": 3,
                        },
                    )
                    error.duration_s = 0.25
                    raise error
                return runners.RunnerResult(
                    "second attempt succeeded", 0, 0.5,
                    token_usage={"input_tokens": 5, "output_tokens": 7},
                )

        runner = Worker()
        host = self._host(runner, runner)
        host.start(record, self._config)
        paused = self._paused(host, record["id"])
        self.assertEqual(runner.calls, 1)
        self.assertEqual(paused["source"], "error")
        host.resume(record["id"], self._config, paused["revision"])
        result = self._terminal(host, record["id"])["result"]
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["native_result"], "second attempt succeeded")
        self.assertEqual(result["duration_s"], 0.75)
        self.assertEqual(result["token_usage"]["input_tokens"], 22)
        self.assertEqual(result["token_usage"]["output_tokens"], 10)
        self.assertEqual(runner.calls, 2)

    def test_restart_preserves_pause_without_automatic_worker_retry(self):
        record = self._admit("agent_call")

        class Worker:
            calls = 0

            def call(_self, *_args, **_kwargs):
                _self.calls += 1
                raise runners.RunnerError("provider unavailable")

        runner = Worker()
        first_host = self._host(runner)
        first_host.start(record, self._config)
        paused = self._paused(first_host, record["id"])
        restarted = self._host()
        restarted.adopt_open_tasks(lambda _record: self._config)
        self.assertFalse(restarted.is_active(record["id"]))
        lifecycle = task_api.StandaloneTaskStore(self.home).lifecycle(record["id"])
        self.assertEqual(lifecycle["status"], "paused")
        self.assertEqual(lifecycle["revision"], paused["revision"])
        self.assertIsNone(task_api.StandaloneTaskStore(self.home).record(
            record["id"]
        )["result"])
        self.assertEqual(runner.calls, 1)

    def test_restart_marks_unfinished_call_paused_without_dispatching(self):
        record = self._admit("agent_call")
        restarted = self._host()
        restarted.adopt_open_tasks(lambda _record: self._config)
        self.assertFalse(restarted.is_active(record["id"]))
        store = task_api.StandaloneTaskStore(self.home)
        self.assertEqual(store.lifecycle(record["id"])["status"], "paused")
        self.assertIsNone(store.record(record["id"])["result"])
        self.assertEqual(restarted.test_pending_runners, [])

    def test_restart_adopts_completed_worker_marker_and_charges_it_once(self):
        record = self._admit("agent_call")
        result = {
            "status": "success", "duration_s": 0.375,
            "token_usage": runners.normalize_token_usage({
                "input_tokens": 9, "output_tokens": 4,
            }),
            "token_usage_partial": False,
            "cost": {"api_usd": 0.07, "real_usd": 0.02},
            "cost_partial": False,
            "native_result": "delivery was durable before the service died",
        }
        task_api._write_worker_marker(self.home, record["id"], {
            "task_id": record["id"], "call_id": "completed-before-task-write",
            "family": "codex", "started_at": time.time(), "completed": True,
            "result": result,
            **{field: result[field] for field in (
                "duration_s", "token_usage", "token_usage_partial", "cost", "cost_partial",
            )},
        })
        host = self._host()
        host.adopt_open_tasks(lambda _record: self._config)
        paused = self._paused(host, record["id"])
        host.adopt_open_tasks(lambda _record: self._config)
        repeated = host.store.lifecycle(record["id"])
        self.assertEqual(repeated, paused)
        host.resume(record["id"], self._config, paused["revision"])
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"], result)
        self.assertEqual(host.test_pending_runners, [])

    def test_reviewed_resume_restarts_same_discussion_without_topping_up_waiting_rounds(self):
        for exhausted in (False, True):
            with self.subTest(exhausted=exhausted), ExitStack() as cleanups:
                session_id, waiting, attach = self._waiting_rethink_session(
                    self.primary, "pause-owner-%s.md" % exhausted
                )
                record = self._admit("reviewed_task", "implement")
                path = task_api.ensure_reviewed_state(self.home, record, self._config())
                subject = drv.Driver(
                    path,
                    runner=runners.MockRunner([
                        reviewed_tests.ReviewedTaskOrderingTest._rethink_step(
                            contracts.KIND_IMPLEMENT
                        )
                    ]),
                    model_profiles_home=self.home,
                )
                with mock.patch.object(
                    brainstorming_milestone, "create_session", side_effect=attach
                ), mock.patch.object(
                    brainstorming_milestone, "terminal_handoff", return_value=None
                ):
                    reviewed_tests.ReviewedTaskOrderingTest._standalone_step(subject)
                session_store = brainstorming.SessionStore(
                    brainstorming_lifecycle.state_directory(self.home)
                )
                if not exhausted:
                    # This explicit fixture action gives the running case
                    # headroom BEFORE testing the owner's Pause/Resume.
                    session_store.continue_waiting(session_id, waiting.revision)
                baseline = session_store.read(session_id)
                polled = threading.Event()

                def awaiting_discussion(*_args, **_kwargs):
                    polled.set()
                    return None

                def launch(*_args, **_kwargs):
                    process = self._sleeper()
                    return brainstorming_lifecycle.GatedLaunch(
                        process, lambda: None, process.terminate
                    )

                first, second = runners.MockRunner([]), runners.MockRunner([])
                host = self._host(first, second)

                def cancel_owner():
                    if host.store.record(record["id"])["result"] is None:
                        host.stop(record["id"], "test cleanup cancellation")
                        self._terminal(host, record["id"])

                cleanups.callback(cancel_owner)
                with mock.patch.object(
                    brainstorming_lifecycle, "_launch_lifecycle_process", side_effect=launch
                ) as launches, mock.patch.object(
                    brainstorming_milestone, "terminal_handoff", side_effect=awaiting_discussion
                ):
                    if not exhausted:
                        started = brainstorming_lifecycle.start_session(
                            self.home, session_id, lambda _record: None
                        )
                        self.assertEqual(started["process"], "running")
                    launches.reset_mock()
                    host.start(record, self._config)
                    self.assertTrue(polled.wait(5))
                    host.pause(record["id"], "inspect the pending discussion")
                    paused = self._paused(host, record["id"])
                    stopped = brainstorming_lifecycle.inspect_session(
                        self.home, session_id, lambda _record: None
                    )
                    self.assertEqual(stopped["process"], "stopped")
                    self.assertEqual(launches.call_count, 0)
                    polled.clear()
                    host.resume(record["id"], self._config, paused["revision"])
                    self.assertTrue(polled.wait(5))
                    if exhausted:
                        self.assertEqual(launches.call_count, 0)
                    else:
                        self._wait(lambda: launches.call_count == 1,
                                   "owner Resume did not restart its stopped discussion")
                        self.assertEqual(launches.call_args.args[:2], (self.home, session_id))
                    current = session_store.read(session_id)
                    self.assertEqual(current.revision, baseline.revision)
                    self.assertEqual(current.state, baseline.state)
                    self.assertEqual(
                        self._unit(self._state(record["id"]))["brainstorming_wait"]["session_id"],
                        session_id,
                    )
                    self.assertIsNone(host.store.record(record["id"])["result"])
                    self.assertEqual(first.calls + second.calls, [])
                    self.assertTrue(host.stop(record["id"], "test cleanup cancellation"))
                    terminal = self._terminal(host, record["id"])
                    self.assertEqual(terminal["result"]["status"], "failure")


if __name__ == "__main__":
    unittest.main()
