"""Durable provider references survive the existing worker call boundaries."""

import tempfile
from types import SimpleNamespace
import unittest

from orchestrator import kvstore, runners, staffing, worker_conversations


class SessionRunner:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.seeds = []

    def seed_codex_session_usage(self, reference, usage, *, cost_payload=None):
        self.seeds.append((reference, usage, cost_payload))

    def invoke(self, mode, family, reference, prompt, workspace, **kwargs):
        self.calls.append((mode, family, reference, kwargs))
        outcome = self.outcomes.pop(0)
        outcome.session_ref = getattr(outcome, "session_ref", reference)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def start_session(self, family, prompt, workspace, execution_context=None, **kwargs):
        return self.invoke("start", family, "session-%d" % len(self.calls), prompt, workspace, **kwargs)

    def continue_session(self, family, reference, prompt, workspace, execution_context=None, **kwargs):
        return self.invoke("continue", family, reference, prompt, workspace, **kwargs)


class WorkerConversationsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="worker-conversations-")
        self.addCleanup(temporary.cleanup)
        self.store = kvstore.LocalKVClient(temporary.name)
        self.group = SimpleNamespace(call_worker=runners.call_worker)
        self.key = "conversation:compose:0"

    @staticmethod
    def outcome(text='{"answer": "ok"}', usage=3, cumulative=13):
        result = runners.RunnerResult(
            text, 0, 0.01, token_usage={"input_tokens": usage},
            cost_payloads=[{"input_tokens": usage}],
        )
        result.session_token_usage = runners.normalize_token_usage({"input_tokens": cumulative})
        result.session_cost_payload = {"input_tokens": cumulative}
        result.token_usage_is_delta = True
        return result

    def call(self, runner, **kwargs):
        return worker_conversations.call_worker(
            self.store, self.key, self.group, runner, "codex", "Prompt", "unused", "/tmp",
            prepare_call=lambda _error: SimpleNamespace(prompt="Current prompt", validate=lambda reply: reply),
            **kwargs,
        )

    def test_starts_then_resumes_with_current_model_and_cumulative_baseline(self):
        runner = SessionRunner([self.outcome(cumulative=13), self.outcome(cumulative=16)])
        self.call(runner, model="first", effort="medium")
        self.call(runner, model="second", effort="xhigh")
        self.assertEqual([item[0] for item in runner.calls], ["start", "continue"])
        self.assertEqual(runner.calls[0][2], runner.calls[1][2])
        self.assertEqual(runner.calls[1][3]["model"], "second")
        self.assertEqual(runner.calls[1][3]["effort"], "xhigh")
        self.assertEqual(runner.seeds[0][1]["total_tokens"], 13)
        self.assertEqual(runner.seeds[0][2], {"input_tokens": 13})
        self.assertEqual(self.store.get(self.key)["token_usage"]["total_tokens"], 16)

    def test_changed_family_starts_a_new_conversation(self):
        runner = SessionRunner([self.outcome(), self.outcome()])
        self.call(runner)
        self.call(runner, resolve_dispatch=lambda: ("claude", "current-model", "medium"))
        self.assertEqual([item[0] for item in runner.calls], ["start", "start"])
        self.assertEqual(self.store.get(self.key), {"family": "claude", "session_ref": "session-1"})

    def test_pause_keeps_the_conversation(self):
        result = runners.ControlledInterruptionResult("partial", -9, 0.01, "operator pause")
        result.session_token_usage = {"input_tokens": 13}
        runner = SessionRunner([result])
        reply, returned = self.call(runner)
        self.assertIsNone(reply)
        self.assertIs(returned, result)
        self.assertEqual(self.store.get(self.key)["session_ref"], "session-0")

    def test_transport_error_keeps_its_reference_and_original_error(self):
        error = runners.RunnerError("transport stopped")
        error.session_token_usage = {"input_tokens": 13}
        error.session_cost_payload = {"input_tokens": 13}
        runner = SessionRunner([error])
        with self.assertRaises(runners.RunnerError) as caught:
            self.call(runner)
        self.assertIs(caught.exception, error)
        saved = self.store.get(self.key)
        self.assertEqual(saved["session_ref"], "session-0")
        self.assertEqual(saved["token_usage"]["total_tokens"], 13)

    def test_single_attempt_invalid_output_still_keeps_the_session(self):
        runner = SessionRunner([self.outcome(text="invalid")])
        with self.assertRaises(runners.WorkerProtocolError):
            self.call(runner, single_attempt=True)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(self.store.get(self.key)["session_ref"], "session-0")

    def test_double_invalid_output_saves_last_session_snapshot_not_aggregate_cost(self):
        first = self.outcome(text="invalid", usage=3, cumulative=13)
        second = self.outcome(text="invalid again", usage=5, cumulative=18)
        second.session_ref = "latest-session"
        runner = SessionRunner([first, second])
        with self.assertRaises(runners.WorkerOutputError) as caught:
            self.call(runner)
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(caught.exception.token_usage["total_tokens"], 8)
        saved = self.store.get(self.key)
        self.assertEqual(saved["session_ref"], "latest-session")
        self.assertEqual(saved["token_usage"]["total_tokens"], 18)
        self.assertEqual(saved["cost_payload"], {"input_tokens": 18})
        resumed = SessionRunner([self.outcome(cumulative=21)])
        self.call(resumed)
        self.assertEqual(resumed.seeds, [("latest-session", saved["token_usage"], saved["cost_payload"])])
        self.assertEqual(resumed.calls[0][0:3], ("continue", "codex", "latest-session"))

    def test_repair_transport_failure_preserves_latest_cumulative_snapshot(self):
        error = runners.RunnerError("repair stopped")
        error.token_usage = {"input_tokens": 5}
        error.session_token_usage = {"input_tokens": 18}
        error.session_cost_payload = {"input_tokens": 18}
        runner = SessionRunner([self.outcome(text="invalid"), error])
        with self.assertRaises(runners.RunnerError) as caught:
            self.call(runner)
        self.assertEqual(caught.exception.token_usage["total_tokens"], 8)
        self.assertEqual(self.store.get(self.key)["token_usage"]["total_tokens"], 18)

    def test_blocked_repair_retains_the_first_completed_session(self):
        runner = SessionRunner([self.outcome(text="invalid")])

        def resolve():
            if runner.calls:
                raise runners.RunnerError("staffing is unavailable before repair")
            return "codex", "current-model", "medium"

        with self.assertRaises(runners.RunnerError) as caught:
            self.call(runner, resolve_dispatch=resolve)
        self.assertFalse(caught.exception.provider_dispatch_started)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(self.store.get(self.key)["session_ref"], "session-0")
        self.assertEqual(self.store.get(self.key)["token_usage"]["total_tokens"], 13)

    def test_no_dispatch_leaves_the_existing_reference_unchanged(self):
        runner = SessionRunner([self.outcome()])
        self.call(runner)
        previous = self.store.get(self.key)

        def refuse():
            raise runners.RunnerError("refused before dispatch")

        with self.assertRaises(runners.RunnerError):
            self.call(runner, resolve_dispatch=refuse)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(self.store.get(self.key), previous)

    def test_staffing_condition_before_repair_preserves_the_completed_session(self):
        runner = SessionRunner([self.outcome(text="invalid")])

        def resolve():
            if runner.calls:
                raise staffing.StaffingConditionError("condition", "staffing changed before repair")
            return "codex", "current-model", "medium"

        with self.assertRaises(staffing.StaffingConditionError):
            self.call(runner, resolve_dispatch=resolve)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(self.store.get(self.key)["session_ref"], "session-0")
        self.assertEqual(self.store.get(self.key)["token_usage"]["total_tokens"], 13)

    def test_successful_repair_without_snapshot_does_not_lose_the_first_turn(self):
        first = self.outcome(text="invalid")
        second = self.outcome(usage=5)
        first.session_token_usage = second.session_token_usage = None
        runner = SessionRunner([self.outcome(cumulative=10), first, second])
        self.call(runner)
        reply, result = self.call(runner)
        self.assertEqual(reply, {"answer": "ok"})
        self.assertTrue(result.repair)
        self.assertEqual(self.store.get(self.key)["session_ref"], "session-0")
        self.assertIsNone(self.store.get(self.key)["token_usage"])

    def test_aggregate_failure_without_snapshots_does_not_invent_a_baseline(self):
        first = runners.RunnerResult("invalid", 0, 0.01, token_usage={"input_tokens": 3})
        second = runners.RunnerResult("invalid again", 0, 0.01, token_usage={"input_tokens": 5})
        runner = SessionRunner([first, second])
        with self.assertRaises(runners.WorkerOutputError):
            self.call(runner)
        self.assertEqual(self.store.get(self.key), {
            "family": "codex", "session_ref": "session-0", "token_usage": None, "cost_payload": None,
        })
