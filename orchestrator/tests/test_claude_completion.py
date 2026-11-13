"""Claude turn results must not terminate pending background work."""

import json
import unittest
from unittest import mock

from orchestrator import runners


def state(value):
    return {"type": "system", "subtype": "session_state_changed", "state": value}


def tasks(*values):
    return {"type": "system", "subtype": "background_tasks_changed",
            "tasks": [{"task_id": value, "task_type": "local_agent"} for value in values]}


def result(text="delivery", *, ident="result-1", reply_to=0, **extra):
    def event(sent):
        value = {"type": "result", "uuid": ident, "subtype": "success",
                 "is_error": False, "session_id": "session-1", "result": text,
                 "usage": {"input_tokens": 10, "output_tokens": 2},
                 "total_cost_usd": 1.0, **extra}
        if reply_to is not None:
            value["user_message_uuid"] = sent[reply_to]["uuid"]
        return value
    return event


class Control:
    def __init__(self, steer=None):
        self.steer = steer
        self.observed = []

    def _bind(self, steer, interrupt):
        self.interrupt = interrupt
        if self.steer:
            steer(self.steer)

    def observe_model_message(self, text):
        self.observed.append(text)


class ClaudeCompletionTests(unittest.TestCase):
    def drive(self, events, *, control=None):
        sent, consumed, recorded = [], [], []
        iterator = iter(events)

        def read():
            event = next(iterator, None)
            if isinstance(event, Exception):
                raise event
            value = event(sent) if callable(event) else event
            consumed.append(value)
            return value

        answer = runners.SubprocessRunner._drive_claude_stream(
            "write the delivery", "session-1", control or Control(), object(),
            lambda message: sent.append(message) or True,
            recorded.append, read, object(),
        )
        return answer, sent, consumed, recorded

    def test_result_and_idle_can_arrive_in_either_order(self):
        for ending in ([result(), state("idle")], [state("idle"), result()]):
            with self.subTest(ending=ending):
                answer, sent, consumed, _ = self.drive([state("running"), *ending])
                self.assertTrue(answer["complete"])
                self.assertTrue(answer["ok"])
                self.assertEqual(answer["text"], "delivery")
                self.assertEqual(len(consumed), 3)
                self.assertEqual(sent[0]["origin"], {"kind": "coordinator"})

    def test_pending_result_is_not_promoted_by_tasks_empty_and_idle(self):
        answer, _, consumed, _ = self.drive([
            state("running"), tasks("review-a", "review-b"),
            result("waiting for reviewers"), tasks(), state("idle"),
            state("running"),
            result("final synthesis", ident="result-2", reply_to=None,
                   origin={"kind": "task-notification"}, total_cost_usd=3.0),
            state("idle"),
        ])
        self.assertEqual(answer["text"], "final synthesis")
        self.assertEqual(len(consumed), 8)
        self.assertEqual(answer["token_usage"]["input_tokens"], 20)
        self.assertEqual(answer["cost_payloads"][0]["total_cost_usd"], 3.0)
        self.assertEqual(len(answer["cost_payloads"]), 1)

    def test_task_completion_without_later_result_stays_incomplete(self):
        answer, _, _, _ = self.drive([
            state("running"), tasks("reviewer"), result("waiting"),
            tasks(), state("idle"),
        ])
        self.assertFalse(answer["complete"])
        self.assertTrue(answer["token_usage_partial"])
        self.assertEqual(answer["text"], "")

    def test_new_running_invalidates_previous_result(self):
        answer, _, _, _ = self.drive([
            state("running"), result("first turn"), state("requires_action"),
            state("running"), state("idle"),
        ])
        self.assertFalse(answer["complete"])

    def test_stale_notification_cannot_complete_new_prompt(self):
        for old_text in ("", "old delivery"):
            with self.subTest(old_text=old_text):
                answer, _, consumed, _ = self.drive([
                    state("idle"), state("running"),
                    result(old_text, ident="old", reply_to=None,
                           origin={"kind": "task-notification"}),
                    state("idle"), state("running"), result(), state("idle"),
                ])
                self.assertEqual(answer["text"], "delivery")
                self.assertEqual(len(consumed), 7)

    def test_other_prompt_result_cannot_complete_new_prompt(self):
        old = result("old", reply_to=None, user_message_uuid="old-prompt")
        answer, _, _, _ = self.drive([state("running"), old, state("idle")])
        self.assertFalse(answer["complete"])

    def test_startup_idle_alone_is_not_completion(self):
        answer, _, _, _ = self.drive([state("idle"), result()])
        self.assertFalse(answer["complete"])

    def test_empty_answer_to_current_prompt_reaches_contract_validation(self):
        answer, _, _, _ = self.drive([state("running"), result(""), state("idle")])
        self.assertTrue(answer["complete"])
        self.assertEqual(answer["text"], "")

    def test_empty_followup_cannot_replace_required_synthesis(self):
        answer, _, _, _ = self.drive([
            state("running"), tasks("reviewer"), result("waiting"), tasks(),
            result("", ident="empty", reply_to=None, origin={"kind": "task-notification"}),
            state("idle"),
        ])
        self.assertFalse(answer["complete"])

    def test_auto_continuation_can_deliver_synthesis(self):
        answer, _, _, _ = self.drive([
            state("running"), tasks("reviewer"), result("waiting"), tasks(),
            result("final", ident="continued", reply_to=None,
                   origin={"kind": "auto-continuation"}), state("idle"),
        ])
        self.assertEqual(answer["text"], "final")

    def test_repeated_running_does_not_discard_same_turn_result(self):
        answer, _, _, _ = self.drive([
            state("running"), result(), state("running"), state("idle"),
        ])
        self.assertTrue(answer["complete"])

    def test_deduplicates_result_usage_and_cumulative_cost(self):
        first = result("waiting")
        answer, _, _, _ = self.drive([
            state("running"), tasks("reviewer"), first, first, tasks(),
            result("done", ident="result-2", total_cost_usd=4.0), state("idle"),
        ])
        self.assertEqual(answer["token_usage"]["input_tokens"], 20)
        self.assertEqual(answer["cost_payloads"][0]["total_cost_usd"], 4.0)

    def test_structured_output_is_the_delivery(self):
        answer, _, _, _ = self.drive([
            state("running"), result("display text", structured_output={"action": "revise"}),
            state("idle"),
        ])
        self.assertEqual(json.loads(answer["text"]), {"action": "revise"})

    def test_oauth_error_reports_detail_not_success_subtype(self):
        detail = "Failed to authenticate: OAuth session expired and could not be refreshed"
        answer, _, _, _ = self.drive([result(detail, is_error=True, reply_to=None)])
        self.assertFalse(answer["ok"])
        self.assertTrue(answer["complete"])
        self.assertEqual(answer["error"], detail)

    def test_error_array_is_preserved_without_erasing_prior_cost(self):
        answer, _, _, _ = self.drive([
            state("running"), tasks("reviewer"), result("waiting", total_cost_usd=4.0),
            result("", ident="error", reply_to=None, subtype="error_during_execution",
                   is_error=True, errors=["authentication failed", "refresh failed"],
                   usage={"input_tokens": 0, "output_tokens": 0}, total_cost_usd=0),
        ])
        self.assertEqual(answer["error"], "authentication failed; refresh failed")
        self.assertEqual(answer["cost_payloads"][0]["total_cost_usd"], 4.0)

    def test_missing_idle_or_live_tasks_at_eof_is_incomplete(self):
        for events in ([state("running"), result()],
                       [state("running"), tasks("reviewer"), result(), state("idle")]):
            with self.subTest(events=events):
                answer, _, _, _ = self.drive(events)
                self.assertFalse(answer["complete"])
                self.assertIn("idle session", answer["error"])

    def test_ambient_tasks_do_not_block_delivery(self):
        ambient = tasks("housekeeping")
        ambient["tasks"][0]["ambient"] = True
        answer, _, _, _ = self.drive([state("running"), ambient, result(), state("idle")])
        self.assertTrue(answer["complete"])

    def test_unanswered_steer_blocks_completion(self):
        answer, sent, _, recorded = self.drive(
            [state("running"), result(), state("idle")], control=Control("include edits"),
        )
        self.assertEqual(len(sent), 2)
        self.assertEqual(recorded, ["include edits"])
        self.assertFalse(answer["complete"])

    def test_merged_steer_result_answers_both_messages(self):
        def merged(sent):
            value = result(reply_to=1)(sent)
            value["user_message_uuids"] = [message["uuid"] for message in sent]
            return value
        answer, _, _, _ = self.drive(
            [state("running"), merged, state("idle")], control=Control("include edits"),
        )
        self.assertTrue(answer["complete"])

    def test_queued_turn_count_prevents_early_completion(self):
        answer, _, _, _ = self.drive([
            state("running"), result(queued_turn_count=1), state("idle"),
        ])
        self.assertFalse(answer["complete"])

    def test_timeout_keeps_accumulated_accounting(self):
        with self.assertRaises(runners.RunnerError) as caught:
            self.drive([state("running"), tasks("reviewer"), result(),
                        runners.RunnerError("timed out")])
        self.assertEqual(caught.exception.token_usage["input_tokens"], 10)
        self.assertTrue(caught.exception.token_usage_partial)
        self.assertEqual(caught.exception.cost_payloads[0]["total_cost_usd"], 1.0)

    def test_interrupt_binding_still_terminates_worker_group(self):
        control = Control()
        self.drive([], control=control)
        with mock.patch.object(runners, "_kill_group") as kill:
            self.assertTrue(control.interrupt("stop"))
        kill.assert_called_once()

    def test_activity_events_are_required_in_worker_environment(self):
        env = runners._worker_env({}, "claude")
        self.assertEqual(env["CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS"], "1")
        self.assertEqual(env["CLAUDE_CODE_BG_TASKS_REPORT_RUNNING"], "1")


if __name__ == "__main__":
    unittest.main()
