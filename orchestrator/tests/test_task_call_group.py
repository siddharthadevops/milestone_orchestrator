"""Concurrent members share physical ownership, never each other's outcome fence."""

import json
import os
import signal
import subprocess
import sys
import threading
import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest import mock

from orchestrator import pricing, registry, runners, task_api, tasks
from orchestrator.task_execution import ExecutionBusy, TaskCallGroup, TaskExecutionLease
from orchestrator.tests import test_task_execution as execution_fixture
from orchestrator.tests import test_task_api as api_fixture


GROUP_OWNER = r'''
import os, signal, sys, threading
from orchestrator.runners import ActiveCallControl, SubprocessRunner
from orchestrator.task_execution import TaskExecutionLease
from orchestrator.tests.test_task_execution import WORKER
task_dir, workspace, mode, transport = sys.argv[1:]
with TaskExecutionLease(task_dir) as lease:
    def run(index, ready):
        directory = os.path.join(workspace, str(index))
        member = lease.member()
        record = member.record_worker
        def recorded(pid):
            if mode == "spawn-gap" and index == 1:
                os.kill(os.getpid(), signal.SIGKILL)
            record(pid)
            with open(os.path.join(directory, "recorded"), "w") as handle:
                handle.write(str(pid))
            ready.set()
        member.record_worker = recorded
        runner = SubprocessRunner({}, {}, execution_lease=member)
        worker_mode = "close-fds" if mode == "spawn-gap" else mode
        argv = [sys.executable, "-c", WORKER, directory, worker_mode, transport]
        if transport == "live":
            runner._call_live_transport(
                "claude", "prompt", directory, argv, argv,
                active_control=ActiveCallControl(),
            )
        else:
            runner._call_template("fake", "prompt", directory, argv)
    threads = []
    for index in range(2):
        ready = threading.Event()
        thread = threading.Thread(target=run, args=(index, ready))
        threads.append(thread)
        thread.start()
        if not ready.wait(5):
            raise RuntimeError("worker identity was not recorded")
    for thread in threads:
        thread.join()
'''


class TaskCallGroupLeaseTests(unittest.TestCase):
    setUp = execution_fixture.TaskExecutionLeaseTests.setUp
    _wait_until = execution_fixture.TaskExecutionLeaseTests._wait_until

    def _call(self, member, transport, workspace, name, fail=False, complete=None):
        payload = json.dumps({"status": "ok", "kind": "draft_slice_note",
                              "retained": name})
        script = "import json,sys\n"
        script += "with open(sys.argv[1], 'a') as handle: handle.write(%r)\n" % (name + "\n")
        if transport == "live":
            script += "sys.stdin.readline()\n"
            script += "print(json.dumps(%r), flush=True)\n" % {
                "type": "result", "is_error": fail,
                "result": "original failure " + name if fail else payload,
            }
        elif not fail:
            script += "print(%r, flush=True)\n" % payload
        if fail:
            script += "sys.stderr.write(%r); sys.exit(7)\n" % ("original failure " + name)
        argv = [sys.executable, "-c", script, os.path.join(workspace, "invocations")]
        native = runners.SubprocessRunner({}, {}, execution_lease=member)

        def physical_call(_family, prompt, directory, **_kwargs):
            if transport == "live":
                return native._call_live_transport(
                    "claude", prompt, directory, argv, argv,
                    active_control=runners.ActiveCallControl(),
                )
            return native._call_template("fake", prompt, directory, argv)

        prepared = SimpleNamespace(prompt="prompt", validate=lambda value: value,
                                   complete=complete)
        return runners.call_worker(
            SimpleNamespace(call=physical_call), "fake", "prompt",
            "draft_slice_note", workspace, prepare_call=lambda _error: prepared,
            single_attempt=True,
        )

    def test_member_completion_keeps_other_dispatch_evidence(self):
        for transport in ("template", "live"):
            with self.subTest(transport=transport):
                directory = os.path.join(self.temporary.name, transport)
                with TaskExecutionLease(directory) as lease:
                    unknown, completed = lease.member(), lease.member()
                    unknown.prepare_spawn({})
                    output, _result = self._call(completed, transport, directory, "completed")
                    self.assertEqual(output["retained"], "completed")
                    with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
                        lease.ensure_quiescent()
                with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
                    TaskExecutionLease(directory).acquire()

    def test_member_outcome_waits_for_own_quiescence(self):
        for transport in ("template", "live"):
            for fail in (False, True):
                with self.subTest(transport=transport, fail=fail):
                    self._independent_outcomes(transport, fail)

    def _independent_outcomes(self, transport, fail):
        pending, release = threading.Event(), threading.Event()
        delivered = {name: threading.Event() for name in ("held", "quiet")}
        values, errors, completions, held_pids = {}, {}, [], set()
        directory = os.path.join(self.temporary.name, transport + str(fail))
        lease = TaskExecutionLease(directory, poll_interval=0.005)
        real_observe = runners._process_group_quiescent

        def observe(pgid):
            if pgid in held_pids and not release.is_set():
                pending.set()
                return None
            return real_observe(pgid)

        def run(name, member):
            try:
                values[name] = self._call(
                    member, transport, directory, name, fail=fail and name == "held",
                    complete=lambda: completions.append(name),
                )
            except BaseException as exc:
                errors[name] = exc
            finally:
                delivered[name].set()

        with lease, mock.patch.object(
            runners, "_wait_for_process_group_quiescence", side_effect=observe,
        ), mock.patch.object(runners, "_process_group_quiescent", side_effect=observe):
            held, quiet = lease.member(), lease.member()
            record = held.record_worker

            def record_held(pid):
                held_pids.add(pid)
                record(pid)

            held.record_worker = record_held
            threads = [threading.Thread(target=run, args=(name, member), daemon=True)
                       for name, member in (("held", held), ("quiet", quiet))]
            try:
                for thread in threads:
                    thread.start()
                self.assertTrue(pending.wait(5), "member never reached quiescence fence")
                self.assertTrue(delivered["quiet"].wait(5), "sibling could not deliver independently")
                self.assertFalse(delivered["held"].wait(0.05))
                self.assertEqual(completions, ["quiet"])
                self.assertEqual(values["quiet"][0]["retained"], "quiet")
                self.assertEqual(errors, {})
                with self.assertRaises(ExecutionBusy):
                    lease.ensure_quiescent()
            finally:
                release.set()
                for thread in threads:
                    thread.join(timeout=5)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(completions, ["quiet", "held"])
            if fail:
                self.assertIsInstance(errors["held"], runners.RunnerError)
                self.assertIn("original failure held", str(errors["held"]))
            else:
                self.assertEqual(errors, {})
                self.assertEqual(values["held"][0]["retained"], "held")
            lease.ensure_quiescent()
            with open(os.path.join(directory, "invocations")) as handle:
                self.assertCountEqual(handle.read().splitlines(), ["held", "quiet"])

    def test_group_quiescence_survives_owner_death(self):
        for transport in ("template", "live"):
            for mode in ("inherit", "close-fds", "descendant", "spawn-gap"):
                with self.subTest(transport=transport, mode=mode):
                    self._owner_death(transport, mode)

    def _owner_death(self, transport, mode):
        directory = os.path.join(self.temporary.name, transport, mode)
        task_dir = os.path.join(directory, "task")
        workspaces = [os.path.join(directory, str(index)) for index in range(2)]
        for workspace in workspaces:
            os.makedirs(workspace)
        env = dict(os.environ)
        env.pop("ORCH_REAL_LLM", None)
        repo = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        env["PYTHONPATH"] = repo + os.pathsep + env.get("PYTHONPATH", "")
        owner = subprocess.Popen(
            [sys.executable, "-c", GROUP_OWNER, task_dir, directory, mode, transport],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, env=env, start_new_session=True,
        )
        pids = []
        try:
            for workspace in workspaces:
                path = os.path.join(workspace, "worker.pid")
                self._wait_until(lambda: os.path.exists(path) and os.path.getsize(path),
                                 "concurrent worker start")
                with open(path) as handle:
                    pids.append(int(handle.read()))
                marker = "descendant.pid" if mode == "descendant" else "recorded"
                if mode != "spawn-gap":
                    self._wait_until(lambda: os.path.exists(os.path.join(workspace, marker)),
                                     "worker evidence")
            if mode == "spawn-gap":
                self._wait_until(lambda: owner.poll() is not None, "death during dispatch")
            else:
                owner.kill()
            owner.wait(timeout=3)
            self.assertEqual(owner.returncode, -signal.SIGKILL)
            if mode == "descendant":
                for pid in pids:
                    os.kill(pid, signal.SIGKILL)
            for workspace in workspaces:
                heartbeat = os.path.join(workspace, "heartbeat")
                before = os.path.getsize(heartbeat)
                self._wait_until(lambda: os.path.getsize(heartbeat) > before,
                                 "surviving group writes")
            with self.assertRaises(ExecutionBusy):
                TaskExecutionLease(task_dir).acquire()
            os.killpg(pids[0], signal.SIGKILL)
            self._wait_until(lambda: runners._process_group_quiescent(pids[0]) is True,
                             "first member quiescence")
            with self.assertRaises(ExecutionBusy):
                TaskExecutionLease(task_dir).acquire()
            self.assertIs(runners._process_group_quiescent(pids[1]), False)
            os.killpg(pids[1], signal.SIGKILL)
            self._wait_until(lambda: runners._process_group_quiescent(pids[1]) is True,
                             "second member quiescence")
            if mode == "spawn-gap":
                with self.assertRaisesRegex(ExecutionBusy, "before worker identity"):
                    TaskExecutionLease(task_dir).acquire()
            else:
                with TaskExecutionLease(task_dir):
                    pass
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=3)
            for workspace in workspaces:
                try:
                    with open(os.path.join(workspace, "worker.pid")) as handle:
                        os.killpg(int(handle.read()), signal.SIGKILL)
                except (OSError, ValueError):
                    pass
            owner.stderr.close()


class GroupRunner(runners.SubprocessRunner):
    """Local calls finish only when their individual release file appears."""

    def __init__(self, transport):
        super().__init__({}, {})
        self.transport = transport
        self.calls = {}
        self.pids = {}
        self.lock = threading.Lock()

    def call(self, family, prompt, workspace, active_control=None, **_kwargs):
        name = prompt.splitlines()[0]
        with self.lock:
            label = name + str(sum(key.startswith(name) for key in self.calls) + 1)
            self.calls[label] = (active_control, self.execution_lease.member_id)
        record = self.execution_lease.record_worker

        def recorded(pid):
            self.pids[label] = pid
            record(pid)

        self.execution_lease.record_worker = recorded
        text = "not json" if label == "repair1" else json.dumps({"retained": label})
        event = {"type": "result", "result": text, "is_error": name == "failed",
                 "usage": {"input_tokens": 7, "output_tokens": 3},
                 "total_cost_usd": 0.02}
        if name == "failed":
            event["subtype"] = "original failure"
        script = (
            "import json,os,sys,time\n"
            + ("sys.stdin.readline()\n" if self.transport == "live" else "sys.stdin.read()\n")
            + "open(sys.argv[1] + '.started', 'w').close()\n"
            + "while not os.path.exists(sys.argv[1] + '.release'): time.sleep(0.005)\n"
        )
        if name == "failed" and self.transport == "template":
            script += "sys.stderr.write('original failure'); sys.exit(7)\n"
        else:
            script += "print(json.dumps(%r), flush=True)\n" % event
        argv = [sys.executable, "-c", script, os.path.join(workspace, label)]
        if self.transport == "live":
            return self._call_live_transport(
                family, prompt, workspace, argv, argv, active_control=active_control,
            )
        return self._call_template(family, prompt, workspace, argv, active_control=active_control)


class TaskCallGroupControlTests(unittest.TestCase):
    setUp = execution_fixture.TaskExecutionLeaseTests.setUp
    _wait_until = execution_fixture.TaskExecutionLeaseTests._wait_until
    order = api_fixture.TaskApiTest.order

    def _group(self, name, bound):
        lease = TaskExecutionLease(os.path.join(self.temporary.name, name), poll_interval=0.005)
        lease.acquire()
        self.addCleanup(lease.close)
        return TaskCallGroup(lease, bound)

    @staticmethod
    def _release(group, label):
        with open(os.path.join(group.lease.task_dir, label + ".release"), "w"):
            pass

    def _started(self, group, label):
        self._wait_until(
            lambda: os.path.exists(os.path.join(group.lease.task_dir, label + ".started")),
            "worker did not start: " + label,
        )

    @staticmethod
    def _call(group, runner, name, **kwargs):
        kwargs.setdefault("prepare_call", lambda _error: SimpleNamespace(
            prompt=name, validate=lambda value: value,
        ))
        return group.call_worker(
            runner, "claude", name, "draft_slice_note", group.lease.task_dir, **kwargs,
        )

    def _start(self, group, runner, name, **kwargs):
        future = Future()

        def run():
            try:
                future.set_result(self._call(group, runner, name, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

        thread = threading.Thread(target=run, name=name, daemon=True)
        thread.start()

        def cleanup():
            group.interrupt("test cleanup")
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), "call did not settle")

        self.addCleanup(cleanup)
        return future

    def test_group_bound_and_independent_completions(self):
        for transport in ("template", "live"):
            for bound in (1, 2):
                with self.subTest(transport=transport, bound=bound):
                    group = self._group(transport + str(bound), bound)
                    runner = GroupRunner(transport)
                    names = ["member%d-" % index for index in range(bound)]
                    futures = [self._start(group, runner, name) for name in names]
                    for name in names:
                        self._started(group, name + "1")
                    with self.assertRaises(ExecutionBusy):
                        self._call(group, runner, "excess")
                    self.assertEqual(len(runner.calls), bound)
                    self.assertEqual(len({member for _control, member in runner.calls.values()}), bound)
                    for index in reversed(range(bound)):
                        self._release(group, names[index] + "1")
                        self.assertEqual(futures[index].result(5)[0], {"retained": names[index] + "1"})
                        if index:
                            with self.assertRaises(ExecutionBusy):
                                group.ensure_quiescent()
                    group.ensure_quiescent()
                    failure = self._start(group, runner, "failed")
                    self._started(group, "failed1")
                    self._release(group, "failed1")
                    with self.assertRaisesRegex(runners.RunnerError, "original failure"):
                        failure.result(5)
                    group.ensure_quiescent()

    def test_group_control_covers_dispatch_and_repair(self):
        for transport in ("template", "live"):
            for boundary in ("handoff", "binding", "repair-preparation", "repair-running"):
                with self.subTest(transport=transport, boundary=boundary):
                    group = self._group(transport + boundary, 2)
                    receipts = {}
                    group.on_attempt = lambda dispatch: receipts.update({dispatch["call_id"]: dispatch})
                    runner = GroupRunner(transport)
                    entered, release = threading.Event(), threading.Event()
                    sibling = self._start(group, runner, "sibling")
                    self._started(group, "sibling1")
                    bind = runners.ActiveCallControl._bind

                    def gate():
                        entered.set()
                        self.assertTrue(release.wait(5))

                    def bind_at_boundary(control, *args):
                        if boundary == "binding" and threading.current_thread().name == "repair":
                            gate()
                        return bind(control, *args)

                    def prepare(error):
                        if boundary == "repair-preparation" and error is not None:
                            gate()
                        return SimpleNamespace(prompt="repair", validate=lambda value: value)

                    with mock.patch.object(runners.ActiveCallControl, "_bind", bind_at_boundary):
                        if boundary.startswith("repair-"):
                            self._release(group, "repair1")
                        target = self._start(
                            group, runner, "repair", prepare_call=prepare,
                            call_context={"job": "evaluate_candidates", "generation": 3, "batch": "b2"},
                            before_dispatch=lambda *_args: gate() if boundary == "handoff" else None,
                        )
                        try:
                            if boundary == "repair-running":
                                self._started(group, "repair2")
                                with self.assertRaises(ExecutionBusy):
                                    self._call(group, runner, "excess")
                            else:
                                self.assertTrue(entered.wait(5))
                            group.interrupt("paused by operator")
                        finally:
                            release.set()
                        if boundary in ("handoff", "repair-preparation"):
                            with self.assertRaises(runners.RunnerError) as caught:
                                target.result(5)
                            self.assertFalse(caught.exception.provider_dispatch_started)
                            if boundary == "repair-preparation":
                                self.assertEqual(caught.exception.token_usage["input_tokens"], 7)
                                self.assertEqual(len(caught.exception.physical_dispatches), 1)
                                self.assertIn(caught.exception.physical_dispatches[0]["call_id"], receipts)
                        else:
                            output, result = target.result(5)
                            self.assertIsNone(output)
                            if boundary == "repair-running":
                                self.assertEqual(result.repair["token_usage"]["input_tokens"], 7)
                                self.assertEqual(result.repair["cost_payloads"][0]["total_cost_usd"], 0.02)
                                self.assertIsNot(runner.calls["repair1"][0], runner.calls["repair2"][0])
                                self.assertEqual(len(result.physical_dispatches), 2)
                                self.assertNotEqual(result.call_id, result.repair["call_id"])
                                self.assertEqual(result.physical_dispatches[0]["call_id"], result.repair["call_id"])
                        self.assertIsNone(sibling.result(5)[0])
                    target_receipts = [entry for entry in receipts.values() if entry["call_context"]]
                    expected = {"handoff": 0, "binding": 1, "repair-preparation": 1, "repair-running": 2}
                    self.assertEqual(len(target_receipts), expected[boundary])
                    for receipt in target_receipts:
                        self.assertTrue(receipt["completed"])
                        self.assertEqual(receipt["call_context"], {
                            "job": "evaluate_candidates", "generation": 3, "batch": "b2",
                        })
                    with self.assertRaises(runners.RunnerError):
                        self._call(group, runner, "later")
                    self.assertNotIn("later1", runner.calls)
                    group.ensure_quiescent()

    def _owned_group(self, host, name, config=None):
        workspace = os.path.join(host.home, name)
        os.makedirs(workspace)
        order = self.order(work_area={
            "workspace_path": workspace, "primary": workspace, "additional": [],
        })
        with registry.locked(host.home):
            record = host.store.admit_locked(order, {}, workspace)
        identity = record["id"]
        host._active[identity] = workspace
        host._leases[identity] = host._lease(identity).acquire()

        def cleanup():
            host._active.pop(identity, None)
            host._controls.pop(identity, None)
            lease = host._leases.pop(identity, None)
            if lease is not None:
                lease.close()

        self.addCleanup(cleanup)
        return identity, host.create_call_group(identity, 2, config=config)

    def test_group_accounting_keeps_each_physical_attempt(self):
        for unknown in (False, True):
            with self.subTest(unknown_usage=unknown):
                host = task_api.DirectTaskHost(os.path.join(self.temporary.name, "cost-" + str(unknown)))
                identity, group = self._owned_group(host, "work", config={
                    "billing": {"claude": "api", "codex": "subscription"},
                })
                contexts = {
                    "success": {"job": "create_genes", "generation": 0, "batch": "initial"},
                    "failed": {"job": "expand_genes", "generation": 2, "batch": "expansion"},
                    "repair": {"job": "evaluate_candidates", "generation": 2, "batch": "b7"},
                }
                usage = lambda inputs, outputs: {"input_tokens": inputs, "output_tokens": outputs}
                failure = runners.ProviderResponseError(
                    "paid operational failure", token_usage=usage(30, 4),
                    cost_payloads=[{"total_cost_usd": 0.05}],
                )
                failure.duration_s = 5.0
                correction_usage = usage(40, 5)
                correction = runners.ControlledInterruptionResult(
                    "", 0, 7.0, "stopped by operator",
                    token_usage=None if unknown else correction_usage,
                    cost_payloads=[] if unknown else [correction_usage],
                )
                outcomes = {
                    "repair1": runners.RunnerResult("not json", 0, 2.0, token_usage=usage(10, 2),
                                                    cost_payloads=[{"total_cost_usd": 0.02}]),
                    "repair2": correction,
                    "success": runners.RunnerResult('{"answer":"own success"}', 0, 3.0,
                                                   token_usage=usage(20, 3), cost_payloads=[{"total_cost_usd": 0.03}]),
                    "failed": failure,
                }
                ready = {name: threading.Event() for name in outcomes}
                release = {name: threading.Event() for name in outcomes}
                staffing = {name: ("claude", "claude-fable-5", "high") for name in outcomes}
                staffing["repair2"] = ("codex", "gpt-5.6-luna", "low")
                actual_staffing = {}

                def physical(family, prompt, _workspace, model=None, effort=None, active_control=None):
                    actual_staffing[prompt] = (family, model, effort)
                    active_control._bind(lambda _text: False, lambda _reason: release[prompt].set() or True)
                    try:
                        ready[prompt].set()
                        self.assertTrue(release[prompt].wait(5))
                        outcome = outcomes[prompt]
                        if isinstance(outcome, BaseException):
                            raise outcome
                        if prompt == "repair2":
                            self.assertTrue(active_control.interrupted)
                        return outcome
                    finally:
                        active_control._close()

                runner = SimpleNamespace(call=physical)
                def start(name):
                    current = {}

                    def prepare(error):
                        label = name if name != "repair" else "repair" + ("2" if error else "1")
                        current["label"] = label
                        return SimpleNamespace(prompt=label, validate=lambda value: value,
                                               prompt_set_fallback={"fixture": label})

                    return self._start(group, runner, name, prepare_call=prepare,
                                       call_context=contexts[name],
                                       resolve_dispatch=lambda: staffing[current["label"]])

                repaired, success = start("repair"), start("success")
                self.assertTrue(ready["repair1"].wait(5))
                self.assertTrue(ready["success"].wait(5))
                # Reread while active: unfinished dispatch evidence stays partial.
                reread = task_api.StandaloneTaskStore(host.home)
                pending = reread.lifecycle(identity)["accounting"]
                self.assertTrue(pending["token_usage_partial"])
                self.assertTrue(pending["cost_partial"])
                release["success"].set()
                self.assertEqual(success.result(5)[0], {"answer": "own success"})
                failed = start("failed")
                self.assertTrue(ready["failed"].wait(5))
                release["repair1"].set()
                self.assertTrue(ready["repair2"].wait(5))
                history = reread.lifecycle(identity)["history"]
                first = next(event for event in history if
                             event.get("physical_dispatch", {}).get("prompt_set_fallback") == {"fixture": "repair1"})
                self.assertEqual(first["attempt"]["cost"]["api_usd"], 0.02)
                self.assertEqual(first["attempt"]["status"], "failure")
                self.assertEqual(first["attempt"]["token_usage"]["input_tokens"], 10)
                release["failed"].set()
                with self.assertRaisesRegex(runners.ProviderResponseError, "paid operational failure") as caught:
                    failed.result(5)
                self.assertIs(caught.exception, failure)
                host.stop(identity)
                self.assertIsNone(repaired.result(5)[0])
                group.ensure_quiescent()

                lifecycle = reread.lifecycle(identity)
                events = [event for event in lifecycle["history"] if "physical_dispatch" in event]
                self.assertEqual(len(events), 4)
                self.assertEqual(len({event["call_id"] for event in events}), 4)
                self.assertEqual(actual_staffing, staffing)
                for event in events:
                    evidence = event["physical_dispatch"]
                    label = evidence["prompt_set_fallback"]["fixture"]
                    self.assertTrue(evidence["completed"])
                    self.assertEqual((evidence["family"], evidence["model"], evidence["effort"]), staffing[label])
                    self.assertEqual(evidence["call_context"], contexts["repair" if label.startswith("repair") else label])
                    self.assertEqual(evidence["call_id"], outcomes[label].call_id)
                    self.assertEqual(event["attempt"]["duration_s"], {"repair1": 2, "repair2": 7, "success": 3, "failed": 5}[label])
                aggregate = tasks.deep_task_result("failure", [event["attempt"] for event in events], "stopped by operator")
                self.assertEqual(aggregate["duration_s"], 17.0)
                self.assertEqual(aggregate["token_usage"]["input_tokens"], 60 if unknown else 100)
                self.assertEqual(aggregate["token_usage"]["output_tokens"], 9 if unknown else 14)
                extra = 0 if unknown else pricing.quote("codex", "gpt-5.6-luna", correction_usage).api_usd
                self.assertAlmostEqual(aggregate["cost"]["api_usd"], 0.10 + extra)
                self.assertAlmostEqual(aggregate["cost"]["real_usd"], 0.10)
                self.assertEqual(aggregate["token_usage_partial"], unknown)
                self.assertEqual(aggregate["cost_partial"], unknown)
                # A logical aggregate carries no additional physical charge.
                with registry.locked(host.home):
                    host.store.pause_locked(identity, "Retain the group outcome", source="error", attempt=aggregate)
                self.assertEqual(reread.lifecycle(identity)["accounting"], lifecycle["accounting"])
                host.store.record_result(identity, aggregate)
                self.assertEqual(reread.record(identity)["result"], aggregate)
                self.assertEqual(reread.lifecycle(identity)["accounting"], lifecycle["accounting"])

    def test_group_repair_outcomes_keep_actual_identity(self):
        for outcome in ("success", "failure", "spawn-refused"):
            with self.subTest(outcome=outcome):
                host = task_api.DirectTaskHost(os.path.join(self.temporary.name, outcome))
                identity, group = self._owned_group(host, "work")
                first = runners.RunnerResult("not json", 0, 2.0, token_usage={"input_tokens": 10},
                                             cost_payloads=[{"total_cost_usd": 0.02}])
                calls = []

                def physical(family, prompt, workspace, **_kwargs):
                    calls.append(family)
                    if len(calls) == 1:
                        return first
                    if outcome == "spawn-refused":
                        return runners.SubprocessRunner({}, {})._call_template(
                            family, prompt, workspace, [os.path.join(workspace, "absent-cli")],
                        )
                    if outcome == "failure":
                        raise runners.ProviderResponseError("second provider failed")
                    return runners.RunnerResult('{"retained":"repaired"}', 0, 3.0)

                dispatches = iter([("claude", "claude-fable-5", "high"), ("codex", None, None)])
                context = {"job": "evaluate_candidates", "generation": 1, "batch": "b1"}
                arguments = dict(resolve_dispatch=lambda: next(dispatches), call_context=context,
                                 model="initial-model", effort="initial-effort")
                if outcome == "success":
                    output, carrier = self._call(group, SimpleNamespace(call=physical), "repair", **arguments)
                    self.assertEqual(output, {"retained": "repaired"})
                else:
                    with self.assertRaises(runners.RunnerError) as caught:
                        self._call(group, SimpleNamespace(call=physical), "repair", **arguments)
                    carrier = caught.exception
                evidence = carrier.physical_dispatches
                self.assertEqual(len(evidence), 1 if outcome == "spawn-refused" else 2)
                self.assertEqual(evidence[0]["call_id"], first.call_id)
                self.assertEqual(evidence[0]["call_context"], context)
                if len(evidence) == 2:
                    self.assertNotEqual(evidence[0]["call_id"], evidence[1]["call_id"])
                    self.assertEqual(evidence[1]["call_context"], context)
                    self.assertEqual(evidence[1]["family"], "codex")
                    self.assertIsNone(evidence[1]["model"])
                    self.assertIsNone(evidence[1]["effort"])
                events = [event for event in host.store.lifecycle(identity)["history"] if "physical_dispatch" in event]
                self.assertEqual({event["call_id"] for event in events}, {item["call_id"] for item in evidence})
                self.assertEqual(host.store.lifecycle(identity)["accounting"]["cost"]["api_usd"], 0.02)
                group.ensure_quiescent()

    def test_group_pause_and_stop_reach_all_members(self):
        for transport in ("template", "live"):
            for action in ("pause", "stop"):
                with self.subTest(transport=transport, action=action):
                    host = task_api.DirectTaskHost(
                        os.path.join(self.temporary.name, transport + action), poll_interval=0.005,
                    )
                    identity, group = self._owned_group(host, "target")
                    other_id, other = self._owned_group(host, "other")
                    runner, other_runner = GroupRunner(transport), GroupRunner(transport)
                    release = threading.Event()
                    real_observe = runners._process_group_quiescent

                    def observe(pgid):
                        if pgid in runner.pids.values() and not release.is_set():
                            return None
                        return real_observe(pgid)

                    with mock.patch.object(runners, "_process_group_quiescent", side_effect=observe), \
                            mock.patch.object(runners, "_wait_for_process_group_quiescence", side_effect=observe):
                        targets = [self._start(group, runner, name) for name in ("first", "second")]
                        outsider = self._start(other, other_runner, "other")
                        for name in ("first1", "second1"):
                            self._started(group, name)
                        self._started(other, "other1")
                        try:
                            getattr(host, action)(identity)
                            self.assertFalse(host.lifecycle(identity)["can_resume"])
                            if action == "pause":
                                self.assertEqual(host.lifecycle(identity)["status"], "pausing")
                            for control, _member in runner.calls.values():
                                self.assertTrue(control.interrupted)
                            self.assertTrue(all(not future.done() for future in targets))
                            self.assertFalse(outsider.done())
                            self.assertIs(real_observe(other_runner.pids["other1"]), False)
                            with self.assertRaises(task_api.TaskControlConflict):
                                host.resume(identity, lambda: {}, host.lifecycle(identity)["revision"])
                            with self.assertRaises(task_api.TaskControlConflict):
                                host.create_call_group(identity, 2)
                        finally:
                            release.set()
                        for future in targets:
                            self.assertIsNone(future.result(5)[0])
                        group.ensure_quiescent()
                        # The ordinary host lifecycle settles accepted control
                        # after the test caller's members have all returned.
                        host._run(identity, lambda: {})
                        if action == "stop":
                            result = host.store.record(identity)["result"]
                            self.assertEqual(result["status"], "failure")
                            self.assertEqual(result["reason"], "stopped by operator")
                        else:
                            self.assertTrue(host.lifecycle(identity)["can_resume"])
                        self.assertEqual(host.lifecycle(other_id)["status"], "running")
                        self._release(other, "other1")
                        self.assertEqual(outsider.result(5)[0], {"retained": "other1"})
                        self.assertEqual(len(host.store.records()), 2)

    def test_group_outcome_waits_for_own_quiescence(self):
        for transport in ("template", "live"):
            for name in ("held", "failed"):
                for action in ("pause", "stop"):
                    with self.subTest(transport=transport, name=name, action=action):
                        group = self._group(transport + name + action, 2)
                        runner = GroupRunner(transport)
                        pending, release = threading.Event(), threading.Event()
                        group.lease.on_pending = pending.set
                        completions = []
                        real_observe = runners._process_group_quiescent

                        def observe(pgid):
                            if pgid == runner.pids.get(name + "1") and not release.is_set():
                                return None
                            return real_observe(pgid)

                        def prepare(label):
                            return lambda _error: SimpleNamespace(
                                prompt=label, validate=lambda value: value,
                                complete=lambda: completions.append(label),
                            )

                        with mock.patch.object(runners, "_process_group_quiescent", side_effect=observe), \
                                mock.patch.object(runners, "_wait_for_process_group_quiescence", side_effect=observe):
                            held = self._start(group, runner, name, prepare_call=prepare(name))
                            quiet = self._start(group, runner, "quiet", prepare_call=prepare("quiet"))
                            self._release(group, name + "1")
                            self._release(group, "quiet1")
                            try:
                                self.assertTrue(pending.wait(5))
                                self.assertEqual(quiet.result(5)[0], {"retained": "quiet1"})
                                group.interrupt(action + " by operator")
                                self.assertFalse(held.done())
                                self.assertEqual(completions, ["quiet"])
                                with self.assertRaises(ExecutionBusy):
                                    group.ensure_quiescent()
                                with self.assertRaises(runners.RunnerError):
                                    self._call(group, runner, "later")
                            finally:
                                release.set()
                            if name == "failed":
                                with self.assertRaisesRegex(runners.RunnerError, "original failure"):
                                    held.result(5)
                            else:
                                self.assertEqual(held.result(5)[0], {"retained": "held1"})
                            self.assertEqual(completions, ["quiet", name])
                            self.assertEqual(set(runner.calls), {name + "1", "quiet1"})
                            group.ensure_quiescent()


if __name__ == "__main__":
    unittest.main()
