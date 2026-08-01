"""Focused executable evidence for Brainstorming Slice 03."""

import copy
import json
import os
import stat
import subprocess
import sys
import threading
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from orchestrator import brainstorming as bs
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_execution as execution
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import runners


MISSING = object()


def participants(same_family=False):
    roster = [
        {
            "id": "lead",
            "role": "initial_position",
            "delivery": "llm",
            "executor_ref": "codex-lead",
            "model_family": "codex",
        },
        {
            "id": "critic",
            "role": "contrary_position",
            "delivery": "llm",
            "executor_ref": "claude-critic",
            "model_family": "claude",
        },
    ]
    if same_family:
        roster[1]["executor_ref"] = "codex-critic"
        roster[1]["model_family"] = "codex"
    return roster


def run_config(roster):
    return bs.resolve_run_config(roster, "unanimity", roster)


def envelope(markdown):
    return {"kind": "discussion_turn", "markdown": markdown}


def closing_summary():
    return {
        "reason": "Adopt the bounded result and leave no question open.",
        "unresolved_objections": [],
        "affected_parties": "The people using the requested target.",
        "damage_altitude": "A bounded and reversible consequence.",
        "proportionality": "The discussion matched the decision.",
        "escalation_evidence": None,
        "open_questions": [],
    }


class ScriptedExecutor:
    def __init__(self, model_family, responses):
        self.model_family = model_family
        self.responses = list(responses)
        self.calls = []
        self._lock = threading.Lock()
        self._next_ref = 0

    def supports_continuation(self):
        return True

    def _call(
        self, mode, session_ref, prompt, workspace_path, execution_context
    ):
        with self._lock:
            if not self.responses:
                raise AssertionError("scripted participant responses exhausted")
            response = self.responses.pop(0)
            if mode == "start":
                self._next_ref += 1
                session_ref = "participant-%d" % self._next_ref
            self.calls.append(
                {
                    "mode": mode,
                    "session_ref": session_ref,
                    "prompt": prompt,
                    "workspace_path": workspace_path,
                    "execution_context": execution_context,
                }
            )
        if callable(response):
            response = response(prompt, workspace_path, execution_context)
        waiter = None
        if (
            isinstance(response, tuple)
            and len(response) == 2
            and callable(response[1])
        ):
            response, waiter = response
        text = json.dumps(response) if isinstance(response, dict) else response
        result = runners.RunnerResult(text, 0, 0.01)
        result.session_ref = session_ref
        result.quiescence_waiter = waiter
        return result

    def start(self, prompt, workspace_path, execution_context):
        return self._call(
            "start", None, prompt, workspace_path, execution_context
        )

    def continue_session(
        self, session_ref, prompt, workspace_path, execution_context
    ):
        return self._call(
            "continue",
            session_ref,
            prompt,
            workspace_path,
            execution_context,
        )

    @staticmethod
    def wait_for_quiescence(result):
        waiter = getattr(result, "quiescence_waiter", None)
        if waiter is not None:
            waiter()
        return True


class BrainstormingCoordinationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(
            prefix="brainstorming-coordination-"
        )
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.store = bs.SessionStore(os.path.join(self.root, "state"))

    def _create_running(
        self,
        session_id,
        *,
        roster=None,
        max_rounds=2,
        initial=b"initial target",
        context=None,
    ):
        roster = roster or participants()
        workspace = os.path.join(self.root, session_id)
        docs = os.path.join(workspace, "docs")
        os.makedirs(docs)
        target = os.path.join(docs, "decision.md")
        if initial is not MISSING:
            with open(target, "wb") as handle:
                handle.write(initial)
        request = {
            "workspace_path": workspace,
            "target_path": "docs/decision.md",
            "request": "Choose the compatible option to adopt.",
            "context": context or {
                "brief": "Resolve one bounded design request.",
                "references": ["requirements.md"],
                "source_payload": {"opaque": True},
            },
            "max_rounds": max_rounds,
        }
        created = self.store.create(
            session_id, request, run_config(roster), roster
        )
        self.store.transition(session_id, created.revision, "running")
        return target

    def test_dante_never_receives_a_closure_vote(self):
        roster = participants() + [
            {
                "id": "dante",
                "role": "common_sense",
                "delivery": "external",
                "external_ref": "external-dante",
            }
        ]
        request = {
            "workspace_path": self.root,
            "target_path": "decision.md",
            "request": "Choose a practical result.",
            "context": {
                "brief": "Keep the decision human-sized.",
                "amendments": [
                    {"id": "A1", "text": "Prefer the small path."}
                ],
                "source_payload": {
                    "authority_context": {
                        "project_context": "DO NOT INLINE THIS",
                    }
                },
            },
            "max_rounds": 1,
        }
        state = bs.new_session_state(
            request,
            run_config(roster),
            os.path.join(self.root, "chat.md"),
        )
        intervention = {
            "token": "dante-closure",
            "participant_id": "dante",
            "action_kind": "closure_vote",
            "completed_turn_count": 3,
            "round": 1,
            "target_revision": None,
            "input": {
                "request": request["request"],
                "context": request["context"],
                "workspace_path": request["workspace_path"],
                "target_path": request["target_path"],
                "transcript_ref": state["transcript_ref"],
            },
            "created_at": 100.0,
            "provider_attempt": 0,
            "provider_quiescent": True,
            "response": None,
            "closure_context": {
                "closing_summary": {
                    "reason": "Adopt the deliberately small solution.",
                    "unresolved_objections": [],
                    "affected_parties": "The project's ordinary users.",
                    "damage_altitude": "A reversible local inconvenience.",
                    "proportionality": "No larger machinery is justified.",
                    "escalation_evidence": None,
                },
                "votes": [
                    {"participant_id": "lead", "vote": "accept"},
                    {"participant_id": "critic", "vote": "object"},
                ],
            },
        }

        with self.assertRaisesRegex(bs.ContractError, "does not vote"):
            coordination.build_external_narrator_prompt(state, intervention)

        discussion = dict(intervention)
        discussion["action_kind"] = "discussion_turn"
        discussion.pop("closure_context")
        discussion_prompt = coordination.build_external_narrator_prompt(
            state, discussion
        )
        self.assertIn("Dante is a human project lead", discussion_prompt)
        self.assertIn("ask the few simple, awkward questions", discussion_prompt)
        self.assertIn("He asks only questions", discussion_prompt)
        self.assertIn("Read the Brainstorming chat", discussion_prompt)
        self.assertIn("anti-drift questions", discussion_prompt)
        self.assertIn(
            "same natural language as the\nBrainstorming request",
            discussion_prompt,
        )
        self.assertNotIn("natural English", discussion_prompt)
        self.assertTrue(
            discussion_prompt.endswith(coordination.DANTE_MANDATORY_LINE)
        )
        self.assertIn("Dante amended the project", discussion_prompt)
        self.assertIn("A1: Prefer the small path.", discussion_prompt)
        self.assertNotIn("DO NOT INLINE THIS", discussion_prompt)

    def _subject(self, roster, scripts, store=None, failure_classifier=None):
        store = store or self.store
        executors = {
            participant["executor_ref"]: ScriptedExecutor(
                participant["model_family"],
                scripts[participant["id"]],
            )
            for participant in roster
        }
        participant_execution = execution.ParticipantExecution(
            store, executors, failure_classifier=failure_classifier
        )
        return (
            coordination.BrainstormingCoordinator(
                store, participant_execution
            ),
            executors,
        )

    @staticmethod
    def _write_action(path, content, markdown):
        def action(_prompt, _workspace, _context):
            with open(path, "wb") as handle:
                handle.write(content)
            return envelope(markdown)

        return action

    @staticmethod
    def _delete_action(path, markdown):
        def action(_prompt, _workspace, _context):
            os.unlink(path)
            return envelope(markdown)

        return action

    def test_persisted_order_and_turn_view_survive_restart(self):
        for same_family in (False, True):
            with self.subTest(same_family=same_family):
                suffix = "same" if same_family else "cross"
                session_id = "ordered-" + suffix
                roster = participants(same_family=same_family)
                target = self._create_running(session_id, roster=roster)
                subject, executors = self._subject(
                    roster,
                    {
                        "lead": [
                            self._write_action(
                                target, b"lead revision one", "lead one"
                            ),
                            self._write_action(
                                target, b"lead revision two", "lead two"
                            ),
                        ],
                        "critic": [envelope("critic one")],
                    },
                )
                first = subject.run_next_turn(
                    session_id, {"caller": suffix}
                )
                first_revision = first.state["accepted_target_revision"]

                reopened = bs.SessionStore(os.path.join(self.root, "state"))
                resumed = coordination.BrainstormingCoordinator(
                    reopened,
                    execution.ParticipantExecution(reopened, executors),
                )
                second = resumed.run_next_turn(
                    session_id, {"caller": suffix}
                )
                third = resumed.run_next_turn(
                    session_id, {"caller": suffix}
                )

                self.assertEqual(
                    [
                        item["participant_id"]
                        for item in third.state["completed_turns"]
                    ],
                    ["lead", "critic", "lead"],
                )
                critic_prompt = executors[
                    roster[1]["executor_ref"]
                ].calls[0]["prompt"]
                self.assertNotIn("lead one", critic_prompt)
                self.assertIn(third.state["transcript_ref"], critic_prompt)
                self.assertIn(first_revision, critic_prompt)
                self.assertIn("Do not edit the target document", critic_prompt)
                lead_prompt = executors[
                    roster[0]["executor_ref"]
                ].calls[1]["prompt"]
                self.assertNotIn("lead one", lead_prompt)
                self.assertNotIn("critic one", lead_prompt)
                self.assertIn(
                    second.state["accepted_target_revision"], lead_prompt
                )
                self.assertIn("cheapest sufficient result", lead_prompt)
                first_lead_prompt = executors[
                    roster[0]["executor_ref"]
                ].calls[0]["prompt"]
                self.assertLess(
                    abs(len(lead_prompt) - len(first_lead_prompt)), 300
                )
                with open(
                    third.state["transcript_ref"], encoding="utf-8"
                ) as handle:
                    transcript = handle.read()
                self.assertLess(
                    transcript.index("lead one"),
                    transcript.index("critic one"),
                )
                self.assertEqual(
                    [call["mode"] for call in executors[
                        roster[0]["executor_ref"]
                    ].calls],
                    ["start", "continue"],
                )

    def test_every_discussion_and_closure_prompt_gets_proportionality_check(
        self,
    ):
        session_id = "proportionality-prompts"
        roster = participants()
        self._create_running(session_id, roster=roster)
        subject, _executors = self._subject(
            roster,
            {
                "lead": [envelope("unused")],
                "critic": [envelope("unused")],
            },
        )
        snapshot = subject.prepare(session_id)
        revision = (
            snapshot.state["accepted_target_revision"]
            or snapshot.state["recovery_baseline_revision"]
        )
        target_revision = self.store.read_target_revision(
            session_id, revision
        )
        prompts_under_test = (
            coordination.build_turn_prompt(
                snapshot.state, roster[0], 1, target_revision
            ),
            coordination.build_turn_prompt(
                snapshot.state, roster[1], 1, target_revision
            ),
            coordination.build_closure_proposal_prompt(
                snapshot.state, target_revision
            ),
            coordination.build_closure_vote_prompt(
                snapshot.state,
                roster[1],
                target_revision,
                closing_summary(),
            ),
        )
        anchors = (
            "Brainstorming chat is the shared record",
            "identify real affected parties",
            "realistic harm and reversibility",
            "reuse existing mechanisms",
            "cheapest sufficient result",
            "Escalate only on concrete evidence",
        )
        for prompt in prompts_under_test:
            prompt = " ".join(prompt.split())
            for anchor in anchors:
                self.assertIn(anchor, prompt)
            self.assertNotIn('"opaque": true', prompt)
            self.assertNotIn("Earlier accepted session transcript", prompt)

        discussion_prompt, critic_prompt, proposal_prompt, vote_prompt = (
            prompts_under_test
        )
        self.assertIn("final agreement", proposal_prompt)
        self.assertIn(
            "Adopt the bounded result and leave no question open.",
            vote_prompt,
        )
        self.assertLess(len(discussion_prompt), 6000)
        self.assertLess(len(critic_prompt), 6000)
        self.assertLess(len(proposal_prompt), 7000)

    def test_prompts_project_only_paths_and_amendments_from_opaque_context(self):
        session_id = "lean-context"
        roster = participants()
        self._create_running(
            session_id,
            roster=roster,
            context={
                "brief": "Resolve the bounded request.",
                "references": [
                    "goal.md",
                    "docs/reference.md",
                    "JIRA-123",
                    "urn:case:7",
                ],
                "amendments": [
                    {"id": "A7", "text": "Keep the result small."}
                ],
                "source_payload": {
                    "finding": "DO NOT INLINE FINDING",
                    "authority_context": {
                        "project_context": "DO NOT INLINE PROJECT CONTEXT",
                    },
                },
            },
        )
        subject, _executors = self._subject(
            roster,
            {"lead": [envelope("unused")], "critic": [envelope("unused")]},
        )
        snapshot = subject.prepare(session_id)
        revision = snapshot.state["recovery_baseline_revision"]
        target_revision = self.store.read_target_revision(
            session_id, revision
        )
        prompts = (
            coordination.build_turn_prompt(
                snapshot.state, roster[0], 1, target_revision
            ),
            coordination.build_closure_proposal_prompt(
                snapshot.state, target_revision
            ),
            coordination.build_closure_vote_prompt(
                snapshot.state,
                roster[1],
                target_revision,
                closing_summary(),
            ),
        )
        for prompt in prompts:
            self.assertIn("A7: Keep the result small.", prompt)
            self.assertIn("goal.md", prompt)
            self.assertIn("docs/reference.md", prompt)
            self.assertIn("JIRA-123", prompt)
            self.assertIn("urn:case:7", prompt)
            self.assertNotIn(
                os.path.join(
                    snapshot.state["request"]["workspace_path"],
                    "JIRA-123",
                ),
                prompt,
            )
            self.assertNotIn("DO NOT INLINE FINDING", prompt)
            self.assertNotIn("DO NOT INLINE PROJECT CONTEXT", prompt)

    def test_coordination_without_exact_launch_baseline_is_rejected(self):
        session_id = "missing-launch-baseline"
        roster = participants()
        target = self._create_running(session_id, roster=roster)
        subject, _executors = self._subject(
            roster,
            {
                "lead": [
                    self._write_action(
                        target, b"lead revision", "lead completed"
                    )
                ],
                "critic": [envelope("critic pending")],
            },
        )
        prepared = subject.prepare(session_id)
        baseline = prepared.state["recovery_baseline_revision"]
        completed = subject.run_next_turn(session_id, object())
        accepted = completed.state["accepted_target_revision"]
        self.assertNotEqual(accepted, baseline)

        key = bs._session_key(session_id)
        unsupported = copy.deepcopy(self.store._store.read(key)["value"])
        unsupported.pop("recovery_baseline_revision")
        self.store._store.put(key, unsupported)

        reopened = bs.SessionStore(os.path.join(self.root, "state"))
        with self.assertRaisesRegex(
            bs.ContractError,
            "accepted coordination fields must be present together",
        ):
            reopened.read(session_id)

        persisted = reopened._store.read(key)["value"]
        self.assertNotIn("recovery_baseline_revision", persisted)
        self.assertEqual(persisted["accepted_target_revision"], accepted)

    def test_only_complete_passes_increment_rounds_used(self):
        session_id = "rounds"
        roster = participants()
        self._create_running(
            session_id, roster=roster, max_rounds=2
        )
        subject, _executors = self._subject(
            roster,
            {
                "lead": [
                    "not json",
                    envelope("repaired lead turn"),
                    envelope("second lead turn"),
                ],
                "critic": [
                    envelope("first critic turn"),
                    envelope("second critic turn"),
                ],
            },
        )

        expected = [
            (1, 0),
            (2, 1),
            (3, 1),
            (4, 2),
        ]
        for turn_count, rounds_used in expected:
            snapshot = subject.run_next_turn(session_id, object())
            self.assertEqual(len(snapshot.state["completed_turns"]), turn_count)
            self.assertEqual(snapshot.state["rounds_used"], rounds_used)
        with self.assertRaises(coordination.RoundLimitReached):
            subject.run_next_turn(session_id, object())
        final = self.store.read(session_id)
        self.assertEqual(len(final.state["completed_turns"]), 4)
        self.assertEqual(final.state["rounds_used"], 2)
        activity = self.store.read_activity(session_id)
        self.assertEqual(len(activity["events"]), 5)
        self.assertEqual(
            [item["status"] for item in activity["events"]],
            ["failed", "completed", "completed", "completed", "completed"],
        )
        self.assertEqual(
            [item["provider_attempt"] for item in activity["events"][:2]],
            [1, 2],
        )
        self.assertEqual(
            activity["events"][0]["action_id"],
            activity["events"][1]["action_id"],
        )
        self.assertAlmostEqual(
            sum(item["duration_s"] for item in activity["events"]),
            0.05,
        )
        self.assertEqual(
            self.store.read_activity_output(
                session_id, activity["events"][0]["raw_ref"]
            ),
            "not json",
        )

    def test_old_session_lazily_starts_activity_ledger(self):
        session_id = "activity-upgrade"
        roster = participants()
        self._create_running(session_id, roster=roster)
        key = bs._activity_key(session_id)
        existing = self.store._store.read(key)
        self.store._store.delete(key, existing["revision"])
        subject, _executors = self._subject(
            roster,
            {"lead": [envelope("accepted after upgrade")], "critic": []},
        )

        subject.run_next_turn(session_id, object())

        activity = self.store.read_activity(session_id)
        self.assertEqual(len(activity["events"]), 1)
        self.assertEqual(activity["events"][0]["status"], "completed")

    def test_quiescent_turn_keeps_partial_accounting_when_activity_write_fails(
        self,
    ):
        session_id = "lost-internal-activity"
        roster = participants()
        self._create_running(session_id, roster=roster)
        subject, _executors = self._subject(
            roster,
            {"lead": [envelope("paid result")], "critic": []},
        )

        with mock.patch.object(
            subject.participant_execution,
            "_record_activity",
            side_effect=RuntimeError("activity unavailable"),
        ), self.assertRaisesRegex(RuntimeError, "activity unavailable"):
            subject.run_next_turn(session_id, object())

        events = self.store.read_activity(session_id)["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "failed")
        self.assertTrue(events[0]["token_usage_partial"])
        self.assertNotIn("token_usage", events[0])
        self.assertIsNone(self.store.read_turn_attempt(session_id))

    def test_quiescent_turn_preserves_unrecorded_classifier_call(self):
        session_id = "lost-classifier-activity"
        roster = participants()
        target = self._create_running(session_id, roster=roster)
        subject, _executors = self._subject(
            roster, {"lead": [], "critic": []}
        )
        prepared = subject.prepare(session_id)
        attempt = {
            "token": "classifier-parent-call",
            "participant_id": "lead",
            "completed_turn_count": 0,
            "target_revision": prepared.state["accepted_target_revision"],
            "quiescent": False,
        }
        with coordination._open_target_parent(target) as (
            _descriptor,
            _name,
            parent_identity,
        ):
            attempt["target_parent"] = parent_identity
        self.store.begin_turn_attempt(session_id, attempt)
        self.store.begin_turn_classifier_call(
            session_id,
            {
                "family": "claude",
                "model": "opus",
                "effort": "max",
                "started_at": 10.0,
            },
        )
        self.store.mark_turn_attempt_quiescent(
            session_id, attempt["token"]
        )

        self.store.preserve_turn_attempt_accounting(
            session_id, attempt["token"]
        )
        self.store.finish_turn_attempt(session_id, attempt["token"])

        events = self.store.read_activity(session_id)["events"]
        self.assertEqual(
            [event["action_id"] for event in events],
            [attempt["token"], attempt["token"] + ":classifier"],
        )
        self.assertTrue(events[1]["token_usage_partial"])

    def test_classifier_raw_failure_does_not_hide_exact_activity(self):
        session_id = "classifier-raw-failure"
        roster = participants()
        target = self._create_running(session_id, roster=roster)
        subject, _executors = self._subject(
            roster, {"lead": [], "critic": []}
        )
        prepared = subject.prepare(session_id)
        attempt = {
            "token": "classifier-raw-parent",
            "participant_id": "lead",
            "completed_turn_count": 0,
            "target_revision": prepared.state["accepted_target_revision"],
            "quiescent": False,
        }
        with coordination._open_target_parent(target) as (
            _descriptor,
            _name,
            parent_identity,
        ):
            attempt["target_parent"] = parent_identity
        self.store.begin_turn_attempt(session_id, attempt)
        call = {
            "family": "claude",
            "model": "opus",
            "effort": "max",
            "started_at": 10.0,
            "duration_s": 2.0,
            "status": "completed",
            "raw": "classified",
            "token_usage": {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "output_tokens": 3,
                "reasoning_output_tokens": 1,
                "total_tokens": 13,
            },
        }
        self.store.begin_turn_classifier_call(session_id, call)

        with mock.patch.object(
            self.store,
            "save_activity_output",
            side_effect=OSError("raw unavailable"),
        ):
            lifecycle._record_classifier_activity(
                self.store, session_id, call
            )

        events = self.store.read_activity(session_id)["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["token_usage"], call["token_usage"])
        self.assertNotIn("raw_ref", events[0])
        self.assertNotIn(
            "classifier_call", self.store.read_turn_attempt(session_id)
        )

    def test_completed_lead_turn_creates_or_advances_target_revision_atomically(
        self,
    ):
        session_id = "lead-atomic"
        roster = participants()
        target = self._create_running(session_id, roster=roster)
        subject, _executors = self._subject(
            roster,
            {
                "lead": [
                    envelope("lead accepted unchanged target"),
                    self._write_action(
                        target, b"accepted lead bytes", "lead changed target"
                    ),
                ],
                "critic": [envelope("critic kept target")],
            },
        )
        prepared = subject.prepare(session_id)
        self.assertIsNone(prepared.state["accepted_target_revision"])
        baseline_revision = prepared.state["recovery_baseline_revision"]
        first_lead = subject.run_next_turn(session_id, object())
        self.assertEqual(
            first_lead.state["accepted_target_revision"],
            baseline_revision,
        )
        critic = subject.run_next_turn(session_id, object())
        self.assertEqual(
            critic.state["accepted_target_revision"], baseline_revision
        )
        later_lead = subject.run_next_turn(session_id, object())
        accepted_revision = later_lead.state["accepted_target_revision"]
        self.assertNotEqual(baseline_revision, accepted_revision)
        retained = self.store.read_target_revision(
            session_id, accepted_revision
        )
        self.assertEqual(
            bs.target_revision_content(retained),
            (True, b"accepted lead bytes"),
        )

        failed_id = "lead-write-failure"
        failed_target = self._create_running(failed_id, roster=roster)
        failed, _ = self._subject(
            roster,
            {
                "lead": [
                    self._write_action(
                        failed_target, b"must roll back", "not durable"
                    ),
                    envelope("retry also not durable"),
                ],
                "critic": [],
            },
        )
        before = failed.prepare(failed_id)
        real_cas = self.store._store.cas

        def fail_completed_turn(key, expected_revision, value):
            if (
                key.startswith("brainstorming/session:")
                and isinstance(value, dict)
                and len(value.get("completed_turns", [])) == 1
            ):
                raise OSError("simulated durable write failure")
            return real_cas(key, expected_revision, value)

        with mock.patch.object(
            self.store._store, "cas", side_effect=fail_completed_turn
        ):
            with self.assertRaises(OSError):
                failed.run_next_turn(failed_id, object())
        after = self.store.read(failed_id)
        self.assertEqual(after.state["completed_turns"], [])
        self.assertEqual(
            after.state["accepted_target_revision"],
            before.state["accepted_target_revision"],
        )
        with open(failed_target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

    def test_worker_quiescence_precedes_target_validation_and_turn_acceptance(self):
        session_id = "quiescence"
        base_roster = participants()
        roster = [base_roster[1], base_roster[0]]
        target = self._create_running(session_id, roster=roster)
        waiter_started = threading.Event()
        allow_mutation = threading.Event()

        def delayed_mutation(_prompt, _workspace, _context):
            def mutate():
                allow_mutation.wait()
                with open(target, "wb") as handle:
                    handle.write(b"late unauthorized bytes")

            worker = threading.Thread(target=mutate)
            worker.start()

            def wait():
                waiter_started.set()
                worker.join()

            return envelope("candidate before quiet"), wait

        subject, _executors = self._subject(
            roster,
            {
                "lead": [],
                "critic": [
                    delayed_mutation,
                    envelope("accepted retry"),
                ],
            },
        )
        outcomes = {}

        def run(name):
            try:
                outcomes[name] = subject.run_next_turn(
                    session_id, {"attempt": name}
                )
            except BaseException as exc:
                outcomes[name] = exc

        first = threading.Thread(target=run, args=("first",))
        first.start()
        self.assertTrue(waiter_started.wait(timeout=2))
        waiting = self.store.read(session_id)
        self.assertEqual(waiting.state["completed_turns"], [])
        self.assertEqual(waiting.state["rounds_used"], 0)

        second = threading.Thread(target=run, args=("second",))
        second.start()
        second.join(timeout=0.1)
        self.assertTrue(second.is_alive())
        self.assertEqual(self.store.read(session_id).state["completed_turns"], [])

        allow_mutation.set()
        first.join(timeout=2)
        second.join(timeout=2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        snapshots = [
            outcome
            for outcome in outcomes.values()
            if not isinstance(outcome, BaseException)
            and hasattr(outcome, "state")
        ]
        conflicts = [
            outcome
            for outcome in outcomes.values()
            if isinstance(outcome, bs.RevisionConflict)
        ]
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(
            snapshots[0].state["completed_turns"][0]["markdown"],
            "accepted retry",
        )
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

        restart_id = "unknown-after-restart"
        restart_target = self._create_running(restart_id, roster=roster)
        restarted, restart_executors = self._subject(
            roster,
            {
                "lead": [],
                "critic": [envelope("must wait")],
            },
        )
        restart_state = restarted.prepare(restart_id)
        restart_attempt = {
            "token": "crash-surviving-attempt",
            "participant_id": "critic",
            "completed_turn_count": 0,
            "target_revision": restart_state.state[
                "accepted_target_revision"
            ],
            "quiescent": False,
        }
        with coordination._open_target_parent(restart_target) as (
            _descriptor,
            _name,
            parent_identity,
        ):
            restart_attempt["target_parent"] = parent_identity
        self.store.begin_turn_attempt(restart_id, restart_attempt)
        with open(restart_target, "wb") as handle:
            handle.write(b"possibly still changing")
        reopened = bs.SessionStore(os.path.join(self.root, "state"))
        after_restart = coordination.BrainstormingCoordinator(
            reopened,
            execution.ParticipantExecution(reopened, restart_executors),
        )
        with self.assertRaises(coordination.CoordinationRejected):
            after_restart.run_next_turn(restart_id, object())
        self.assertEqual(
            restart_executors["claude-critic"].calls, []
        )
        with open(restart_target, "rb") as handle:
            self.assertEqual(handle.read(), b"possibly still changing")

        reopened.mark_turn_attempt_quiescent(
            restart_id, restart_attempt["token"]
        )
        after_restart.prepare(restart_id)
        corrected_attempt = reopened.read_turn_attempt(restart_id)
        self.assertEqual(
            corrected_attempt["target_mutation_corrections"], 1
        )
        self.assertTrue(corrected_attempt["retry_pending"])
        with open(restart_target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")
        accepted_after_restart = after_restart.run_next_turn(
            restart_id, object()
        )
        self.assertEqual(
            accepted_after_restart.state["completed_turns"][0]["markdown"],
            "must wait",
        )
        self.assertIsNone(reopened.read_turn_attempt(restart_id))

    def test_interlocutor_target_mutation_is_rejected_and_restored(self):
        session_id = "interlocutor-mutation"
        roster = participants()
        target = self._create_running(session_id, roster=roster)
        os.chmod(target, 0o640)
        sentinel = os.path.join(os.path.dirname(target), "sentinel.bin")
        with open(sentinel, "wb") as handle:
            handle.write(b"do not touch")

        def change_mode_only(_prompt, _workspace, _context):
            os.chmod(target, 0o755)
            return envelope("critic claims success")

        subject, _executors = self._subject(
            roster,
            {
                "lead": [envelope("lead unchanged")],
                "critic": [
                    change_mode_only,
                    envelope("critic accepted after correction"),
                ],
            },
        )
        lead = subject.run_next_turn(session_id, object())
        corrected = subject.run_next_turn(session_id, object())
        durable = self.store.read(session_id)
        self.assertEqual(
            durable.state["completed_turns"],
            corrected.state["completed_turns"],
        )
        self.assertEqual(
            durable.state["completed_turns"][:1],
            lead.state["completed_turns"],
        )
        self.assertEqual(durable.state["rounds_used"], 1)
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o640)
        with open(sentinel, "rb") as handle:
            self.assertEqual(handle.read(), b"do not touch")

    def test_envelope_repair_allowance_survives_target_mutation_retry(self):
        session_id = "independent-repair-bounds"
        base_roster = participants()
        roster = [base_roster[1], base_roster[0]]
        target = self._create_running(session_id, roster=roster)

        def repaired_but_mutating(_prompt, _workspace, _context):
            with open(target, "wb") as handle:
                handle.write(b"invalid repaired mutation")
            return envelope("repaired envelope with invalid target mutation")

        subject, executors = self._subject(
            roster,
            {
                "critic": [
                    "first malformed envelope",
                    repaired_but_mutating,
                    "second malformed envelope",
                    envelope("must not receive a second repair"),
                ],
                "lead": [],
            },
        )

        with self.assertRaises(runners.WorkerProtocolError):
            subject.run_next_turn(session_id, object())

        calls = executors["claude-critic"].calls
        self.assertEqual(
            [call["mode"] for call in calls],
            ["start", "continue", "continue"],
        )
        self.assertIn("REPAIR:", calls[1]["prompt"])
        self.assertNotIn("REPAIR:", calls[2]["prompt"])
        self.assertEqual(
            executors["claude-critic"].responses,
            [envelope("must not receive a second repair")],
        )
        self.assertEqual(
            self.store.read(session_id).state["completed_turns"], []
        )
        self.assertIsNone(self.store.read_turn_attempt(session_id))
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

    def test_stable_symbolic_link_parent_is_accepted_and_recovered(self):
        base_roster = participants()
        roster = [base_roster[1], base_roster[0]]
        session_id = "stable-linked-parent"
        real_workspace = os.path.join(self.root, "real-workspace")
        linked_workspace = os.path.join(self.root, "linked-workspace")
        docs = os.path.join(real_workspace, "docs")
        os.makedirs(docs)
        os.symlink(real_workspace, linked_workspace)
        target = os.path.join(linked_workspace, "docs", "decision.md")
        with open(target, "wb") as handle:
            handle.write(b"accepted through link")
        request = {
            "workspace_path": linked_workspace,
            "target_path": "docs/decision.md",
            "request": "Choose the compatible option to adopt.",
            "context": {"brief": "Resolve one bounded design request."},
            "max_rounds": 2,
        }
        created = self.store.create(
            session_id, request, run_config(roster), roster
        )
        self.store.transition(session_id, created.revision, "running")

        subject, _executors = self._subject(
            roster,
            {
                "critic": [
                    self._write_action(
                        target, b"invalid critic edit", "invalid"
                    ),
                    envelope("valid after correction"),
                ],
                "lead": [],
            },
        )
        accepted = subject.run_next_turn(session_id, object())

        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"accepted through link")
        self.assertEqual(
            accepted.state["completed_turns"][0]["markdown"],
            "valid after correction",
        )
        self.assertIsNone(self.store.read_turn_attempt(session_id))

    def test_directory_recovery_uses_portable_target_only_operations(self):
        session_id = "portable-directory-recovery"
        roster = participants()
        target = self._create_running(session_id, roster=roster)
        subject, _executors = self._subject(
            roster, {"lead": [], "critic": []}
        )
        subject.prepare(session_id)
        sentinel = os.path.join(os.path.dirname(target), "sentinel")
        with open(sentinel, "wb") as handle:
            handle.write(b"outside target")

        os.unlink(target)
        nested = os.path.join(target, "nested")
        os.makedirs(nested)
        os.symlink(
            sentinel, os.path.join(nested, "sentinel-link")
        )
        with open(os.path.join(nested, "worker-file"), "wb") as handle:
            handle.write(b"worker bytes")
        os.chmod(nested, 0)
        os.chmod(target, 0)
        try:
            subject.prepare(session_id)
        finally:
            if os.path.isdir(target):
                os.chmod(target, 0o700)
                if os.path.isdir(nested):
                    os.chmod(nested, 0o700)

        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")
        with open(sentinel, "rb") as handle:
            self.assertEqual(handle.read(), b"outside target")

    def test_quiescent_failed_lead_exchange_uses_target_mutation_retry(self):
        roster = participants()
        failed_id = "lead-provider-failure"
        target = self._create_running(failed_id, roster=roster)

        def mutate_then_fail(_prompt, _workspace, _context):
            with open(target, "wb") as handle:
                handle.write(b"incomplete lead bytes")
            error = runners.RunnerError("provider failed")
            error.worker_quiescent = True
            raise error

        failed, _executors = self._subject(
            roster,
            {
                "lead": [
                    mutate_then_fail,
                    envelope("accepted corrected retry"),
                ],
                "critic": [],
            },
        )
        prepared = failed.prepare(failed_id)
        accepted = failed.run_next_turn(failed_id, object())
        durable = self.store.read(failed_id)
        self.assertEqual(
            durable.state["completed_turns"][0]["markdown"],
            "accepted corrected retry",
        )
        self.assertEqual(
            durable.state["accepted_target_revision"],
            prepared.state["recovery_baseline_revision"],
        )
        self.assertEqual(
            accepted.state["completed_turns"],
            durable.state["completed_turns"],
        )
        self.assertIsNone(self.store.read_turn_attempt(failed_id))
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

        raised_protocol_id = "lead-protocol-failure"
        raised_protocol_target = self._create_running(
            raised_protocol_id, roster=roster
        )

        def mutate_then_protocol_error(_prompt, _workspace, _context):
            with open(raised_protocol_target, "wb") as handle:
                handle.write(b"incomplete protocol bytes")
            error = runners.WorkerProtocolError("invalid provider envelope")
            error.worker_quiescent = True
            raise error

        raised_protocol, _ = self._subject(
            roster,
            {
                "lead": [
                    mutate_then_protocol_error,
                    envelope("accepted after protocol correction"),
                ],
                "critic": [],
            },
        )
        protocol_accepted = raised_protocol.run_next_turn(
            raised_protocol_id, object()
        )
        self.assertEqual(
            protocol_accepted.state["completed_turns"][0]["markdown"],
            "accepted after protocol correction",
        )
        with open(raised_protocol_target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

        repeated_id = "lead-provider-failure-twice"
        repeated_target = self._create_running(
            repeated_id, roster=roster
        )

        def provider_failure(content):
            def action(_prompt, _workspace, _context):
                with open(repeated_target, "wb") as handle:
                    handle.write(content)
                error = runners.RunnerError("provider failed")
                error.worker_quiescent = True
                raise error

            return action

        repeated, _ = self._subject(
            roster,
            {
                "lead": [
                    provider_failure(b"first rejected bytes"),
                    provider_failure(b"second rejected bytes"),
                ],
                "critic": [],
            },
        )
        repeated.prepare(repeated_id)
        repeated_terminal = repeated.run_next_turn(
            repeated_id, object()
        )
        self.assertEqual(repeated_terminal.state["status"], "failure")
        self.assertEqual(
            repeated_terminal.state["result"]["outcome"], "failure"
        )
        self.assertEqual(repeated_terminal.state["completed_turns"], [])
        with open(repeated_target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

        protocol_id = "lead-two-strikes"
        target2 = self._create_running(protocol_id, roster=roster)

        def malformed(content):
            def action(_prompt, _workspace, _context):
                with open(target2, "wb") as handle:
                    handle.write(content)
                return "malformed"

            return action

        protocol, _ = self._subject(
            roster,
            {
                "lead": [malformed(b"first"), malformed(b"second")],
                "critic": [],
            },
        )
        protocol.prepare(protocol_id)
        terminal = protocol.run_next_turn(protocol_id, object())
        self.assertEqual(terminal.state["status"], "failure")
        self.assertEqual(terminal.state["result"]["outcome"], "failure")
        self.assertEqual(
            self.store.read(protocol_id).state["completed_turns"], []
        )
        with open(target2, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

    def test_quiescent_control_interrupt_restores_target_without_inline_retry(
        self,
    ):
        roster = participants()
        for exception_type in (
            KeyboardInterrupt,
            SystemExit,
            GeneratorExit,
        ):
            with self.subTest(exception_type=exception_type.__name__):
                session_id = "interrupt-" + exception_type.__name__.lower()
                target = self._create_running(session_id, roster=roster)

                def interrupt(_prompt, _workspace, _context):
                    with open(target, "wb") as handle:
                        handle.write(b"unfinished interrupt bytes")
                    error = exception_type()
                    error.worker_quiescent = True
                    raise error

                subject, _executors = self._subject(
                    roster,
                    {
                        "lead": [interrupt, envelope("accepted retry")],
                        "critic": [],
                    },
                )
                with self.assertRaises(exception_type):
                    subject.run_next_turn(session_id, object())
                activity = self.store.read_activity(session_id)
                self.assertEqual(len(activity["events"]), 1)
                self.assertEqual(activity["events"][0]["status"], "failed")
                self.assertEqual(
                    activity["events"][0]["failure_type"], "execution"
                )
                self.assertEqual(
                    activity["events"][0]["error"], exception_type.__name__
                )
                with open(target, "rb") as handle:
                    self.assertEqual(handle.read(), b"initial target")
                self.assertIsNone(self.store.read_turn_attempt(session_id))

                retried = subject.run_next_turn(session_id, object())
                self.assertEqual(
                    retried.state["completed_turns"][0]["markdown"],
                    "accepted retry",
                )

    def test_recoverable_failure_preserves_and_retries_the_same_action(self):
        roster = participants()
        session_id = "recoverable-provider-failure"
        target = self._create_running(session_id, roster=roster)
        classifications = []

        def overloaded(_prompt, _workspace, _context):
            with open(target, "wb") as handle:
                handle.write(b"unaccepted partial work")
            error = runners.WorkerProtocolError(
                "participant envelope failed twice",
                raw_texts=["API Error: 529 Overloaded"],
            )
            error.worker_quiescent = True
            raise error

        def classify(_session_id, participant, _executor, error):
            classifications.append((participant["id"], error.raw_texts))
            return {
                "error_type": "busy",
                "resume_at": None,
                "evidence": "",
            }

        subject, _executors = self._subject(
            roster,
            {
                "lead": [
                    "not an envelope",
                    overloaded,
                    envelope("accepted after retry"),
                ],
                "critic": [],
            },
            failure_classifier=classify,
        )
        subject.prepare(session_id)
        with self.assertRaises(coordination.OperationalRetryPending):
            subject.run_next_turn(session_id, object())
        pending = self.store.read_turn_attempt(session_id)
        token = pending["token"]
        self.assertTrue(pending["quiescent"])
        self.assertEqual(
            pending["operational_retry"]["error_type"], "busy"
        )
        self.assertTrue(pending["envelope_repair_used"])
        self.assertEqual(classifications, [("lead", ["API Error: 529 Overloaded"])])
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

        due = pending["operational_retry"]["retry_at"] + 1
        with mock.patch.object(coordination.time, "time", return_value=due), \
                mock.patch.object(bs.time, "time", return_value=due):
            accepted = subject.run_next_turn(session_id, object())
        self.assertEqual(
            accepted.state["completed_turns"][0]["markdown"],
            "accepted after retry",
        )
        self.assertIsNone(self.store.read_turn_attempt(session_id))
        activity = self.store.read_activity(session_id)["events"]
        self.assertEqual(
            [(item["action_id"], item["provider_attempt"]) for item in activity],
            [(token, 1), (token, 2), (token, 3)],
        )

    def test_other_quiescent_failure_uses_one_target_mutation_retry(self):
        roster = participants()
        repeated_id = "other-quiescent-failure-twice"
        repeated_target = self._create_running(
            repeated_id, roster=roster
        )

        def other_failure(_prompt, _workspace, _context):
            with open(repeated_target, "wb") as handle:
                handle.write(b"unfinished other-failure bytes")
            error = RuntimeError("other quiescent worker failure")
            error.worker_quiescent = True
            raise error

        repeated, executors = self._subject(
            roster,
            {
                "lead": [other_failure, other_failure],
                "critic": [],
            },
        )
        terminal = repeated.run_next_turn(repeated_id, object())
        self.assertEqual(terminal.state["status"], "failure")
        self.assertEqual(terminal.state["result"]["outcome"], "failure")
        self.assertEqual(terminal.state["completed_turns"], [])
        self.assertEqual(len(executors["codex-lead"].calls), 2)
        self.assertIsNone(self.store.read_turn_attempt(repeated_id))
        with open(repeated_target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

    def test_unknown_worker_state_keeps_attempt_and_target_exclusive(self):
        roster = participants()
        for failure_point in ("execution", "quiescence"):
            with self.subTest(failure_point=failure_point):
                session_id = "unknown-" + failure_point
                target = self._create_running(session_id, roster=roster)

                def fail_execution(_prompt, _workspace, _context):
                    with open(target, "wb") as handle:
                        handle.write(b"possibly still changing")
                    raise runners.RunnerError("worker state is unknown")

                def fail_quiescence(_prompt, _workspace, _context):
                    with open(target, "wb") as handle:
                        handle.write(b"possibly still changing")

                    def wait():
                        raise RuntimeError("quiescence check failed")

                    return envelope("candidate"), wait

                action = (
                    fail_execution
                    if failure_point == "execution"
                    else fail_quiescence
                )
                subject, executors = self._subject(
                    roster,
                    {
                        "lead": [action, envelope("must not retry")],
                        "critic": [],
                    },
                )
                with self.assertRaises(
                    (runners.RunnerError, RuntimeError)
                ):
                    subject.run_next_turn(session_id, object())

                attempt = self.store.read_turn_attempt(session_id)
                self.assertIsNotNone(attempt)
                self.assertFalse(attempt["quiescent"])
                self.assertEqual(
                    self.store.read(session_id).state["completed_turns"], []
                )
                with open(target, "rb") as handle:
                    self.assertEqual(
                        handle.read(), b"possibly still changing"
                    )
                transcript = self.store.read(session_id).state["transcript_ref"]
                with open(transcript, encoding="utf-8") as handle:
                    account = handle.read()
                self.assertEqual(
                    account.count("## Material interruption"), 1
                )
                self.assertIn(
                    "could not be confirmed as finished", account
                )

                with self.assertRaises(
                    coordination.CoordinationRejected
                ):
                    subject.run_next_turn(session_id, object())
                self.assertEqual(len(executors["codex-lead"].calls), 1)

    def test_redirected_parent_recovery_never_touches_external_entry(self):
        base_roster = participants()
        roster = [base_roster[1], base_roster[0]]
        session_id = "redirected-parent"
        target = self._create_running(
            session_id, roster=roster, initial=MISSING
        )
        parent = os.path.dirname(target)
        parked_parent = parent + "-parked"
        external = os.path.join(self.root, "external")
        os.mkdir(external)
        victim = os.path.join(external, os.path.basename(target))
        with open(victim, "wb") as handle:
            handle.write(b"unrelated bytes")

        def redirect_parent(_prompt, _workspace, _context):
            os.rename(parent, parked_parent)
            os.symlink(external, parent)
            return envelope("redirected the parent")

        subject, _executors = self._subject(
            roster,
            {
                "lead": [],
                "critic": [redirect_parent],
            },
        )
        with self.assertRaises(coordination.TargetRecoveryError):
            subject.run_next_turn(session_id, object())

        with open(victim, "rb") as handle:
            self.assertEqual(handle.read(), b"unrelated bytes")
        durable = self.store.read(session_id)
        self.assertEqual(durable.state["completed_turns"], [])
        attempt = self.store.read_turn_attempt(session_id)
        self.assertIsNotNone(attempt)
        self.assertTrue(attempt["quiescent"])
        with open(durable.state["transcript_ref"], encoding="utf-8") as handle:
            account = handle.read()
        self.assertEqual(account.count("## Material interruption"), 1)
        self.assertIn(
            "could not be restored to the last accepted Brainstorming revision",
            account,
        )

    def test_legacy_attempt_without_parent_stops_before_redirected_recovery(self):
        session_id = "legacy-attempt-without-parent"
        roster = participants()
        target = self._create_running(session_id, roster=roster)
        subject, _executors = self._subject(
            roster, {"lead": [], "critic": []}
        )
        prepared = subject.prepare(session_id)
        legacy_attempt = {
            "token": "pre-parent-pinning-attempt",
            "participant_id": "lead",
            "completed_turn_count": 0,
            "target_revision": prepared.state[
                "accepted_target_revision"
            ],
            "quiescent": True,
        }
        self.store._store.put(
            bs._turn_attempt_key(session_id), legacy_attempt
        )

        parent = os.path.dirname(target)
        parked_parent = parent + "-parked"
        external = os.path.join(self.root, "legacy-external")
        os.mkdir(external)
        victim = os.path.join(external, os.path.basename(target))
        with open(victim, "wb") as handle:
            handle.write(b"unrelated bytes")
        os.rename(parent, parked_parent)
        os.symlink(external, parent)

        with self.assertRaises(coordination.TargetRecoveryError):
            subject.prepare(session_id)

        with open(victim, "rb") as handle:
            self.assertEqual(handle.read(), b"unrelated bytes")
        with open(
            os.path.join(parked_parent, os.path.basename(target)), "rb"
        ) as handle:
            self.assertEqual(handle.read(), b"initial target")
        self.assertIsNotNone(self.store.read_turn_attempt(session_id))

    def test_runner_preflight_failure_clears_attempt_and_allows_retry(self):
        session_id = "runner-preflight-retry"
        roster = participants()
        target = self._create_running(session_id, roster=roster)
        spawned = []

        def participant_process_factory(
            execution_context, argv, popen_kwargs
        ):
            spawned.append((execution_context, argv, popen_kwargs))
            raise AssertionError("preflight must not spawn a worker")

        provider_runner = runners.SubprocessRunner(
            {
                "codex": [
                    "codex",
                    "exec",
                    "--model",
                    "{model}",
                    "--output-last-message",
                    "{output_file}",
                ]
            },
            {},
            participant_process_factory=participant_process_factory,
        )
        participant_execution = execution.ParticipantExecution(
            self.store,
            {
                "codex-lead": execution.RunnerParticipantExecutor(
                    "codex", provider_runner
                )
            },
        )
        subject = coordination.BrainstormingCoordinator(
            self.store, participant_execution
        )

        with self.assertRaises(runners.RunnerError) as failed:
            subject.run_next_turn(session_id, object())

        self.assertTrue(failed.exception.worker_quiescent)
        self.assertEqual(spawned, [])
        self.assertIsNone(self.store.read_turn_attempt(session_id))
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

        participant_execution.executors["codex-lead"] = ScriptedExecutor(
            "codex", [envelope("accepted after configuration fix")]
        )
        retried = subject.run_next_turn(session_id, object())
        self.assertEqual(
            retried.state["completed_turns"][0]["markdown"],
            "accepted after configuration fix",
        )

    def test_factory_spawn_then_raise_keeps_attempt_open(self):
        session_id = "runner-spawn-unknown"
        roster = participants()
        target = self._create_running(session_id, roster=roster)
        spawned = []

        def participant_process_factory(
            execution_context, argv, popen_kwargs
        ):
            process = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                **popen_kwargs
            )
            spawned.append((execution_context, process))
            raise RuntimeError("launcher failed after spawning")

        provider_runner = runners.SubprocessRunner(
            {
                "codex": [
                    "codex",
                    "exec",
                    "--output-last-message",
                    "{output_file}",
                ]
            },
            {},
            participant_process_factory=participant_process_factory,
        )
        participant_execution = execution.ParticipantExecution(
            self.store,
            {
                "codex-lead": execution.RunnerParticipantExecutor(
                    "codex", provider_runner
                )
            },
        )
        subject = coordination.BrainstormingCoordinator(
            self.store, participant_execution
        )

        try:
            with self.assertRaises(runners.RunnerError) as failed:
                subject.run_next_turn(session_id, {"caller": "context"})

            self.assertFalse(
                hasattr(failed.exception, "worker_quiescent")
            )
            self.assertEqual(len(spawned), 1)
            self.assertEqual(spawned[0][0], {"caller": "context"})
            self.assertIsNone(spawned[0][1].poll())
            self.assertIsNotNone(self.store.read_turn_attempt(session_id))
            with self.assertRaises(coordination.CoordinationRejected):
                subject.run_next_turn(session_id, object())
            self.assertEqual(len(spawned), 1)
            with open(target, "rb") as handle:
                self.assertEqual(handle.read(), b"initial target")
            self.assertEqual(
                self.store.read(session_id).state["completed_turns"], []
            )
        finally:
            if spawned:
                runners._kill_group(spawned[0][1])
                spawned[0][1].communicate(timeout=5)

    def test_creation_rejects_brainstorming_state_store_target_before_writing(
        self,
    ):
        session_id = "store-target-alias"
        roster = participants()
        workspace = os.path.join(self.root, session_id)
        os.makedirs(workspace)
        request = {
            "workspace_path": workspace,
            "target_path": self.store.path,
            "request": "Decide whether the target may overwrite session authority.",
            "context": {"brief": "Keep target and session state independent."},
            "max_rounds": 1,
        }
        transcript = self.store.transcript_ref(session_id)

        with self.assertRaises(bs.ContractError):
            self.store.create(
                session_id, request, run_config(roster), roster
            )

        self.assertFalse(os.path.exists(self.store.path))
        self.assertFalse(os.path.exists(self.store.path + ".lock"))
        self.assertFalse(os.path.exists(transcript))

    def test_creation_rejects_brainstorming_state_lock_target_before_writing(
        self,
    ):
        session_id = "store-lock-target-alias"
        roster = participants()
        workspace = os.path.join(self.root, session_id)
        os.makedirs(workspace)
        lock_path = self.store.path + ".lock"
        request = {
            "workspace_path": workspace,
            "target_path": lock_path,
            "request": "Decide whether the target may replace the state lock.",
            "context": {"brief": "Keep target and session locking independent."},
            "max_rounds": 1,
        }
        transcript = self.store.transcript_ref(session_id)

        with self.assertRaises(bs.ContractError):
            self.store.create(
                session_id, request, run_config(roster), roster
            )

        self.assertFalse(os.path.exists(self.store.path))
        self.assertFalse(os.path.exists(lock_path))
        self.assertFalse(os.path.exists(transcript))

    def test_target_cannot_use_target_coordination_lock_namespace(self):
        session_id = "target-lock-alias"
        roster = participants()
        workspace = os.path.join(self.root, session_id)
        os.makedirs(workspace)
        victim_target = os.path.join(self.root, "victim", "decision.md")
        reserved_lock = coordination._target_lock_path(
            self.store.path, victim_target
        )
        os.makedirs(os.path.dirname(reserved_lock), exist_ok=True)
        with open(reserved_lock, "wb") as handle:
            handle.write(b"coordination lock")
        before = os.stat(reserved_lock)
        request = {
            "workspace_path": workspace,
            "target_path": reserved_lock,
            "request": "Decide whether a target may replace a coordination lock.",
            "context": {
                "brief": "Keep target artifacts separate from control locks."
            },
            "max_rounds": 1,
        }
        created = self.store.create(
            session_id, request, run_config(roster), roster
        )
        self.store.transition(
            session_id, created.revision, "running"
        )
        subject, executors = self._subject(
            roster, {"lead": [envelope("must not run")], "critic": []}
        )

        with self.assertRaises(coordination.CoordinationRejected):
            subject.prepare(session_id)

        after = os.stat(reserved_lock)
        self.assertEqual(
            (after.st_dev, after.st_ino, after.st_size),
            (before.st_dev, before.st_ino, before.st_size),
        )
        with open(reserved_lock, "rb") as handle:
            self.assertEqual(handle.read(), b"coordination lock")
        durable = self.store.read(session_id)
        self.assertEqual(durable.state["status"], "running")
        self.assertIsNone(bs.coordination_projection(durable.state))
        self.assertEqual(executors["codex-lead"].calls, [])

    def test_missing_target_and_restart_recover_last_accepted_revision(self):
        roster = participants()
        session_id = "missing-target"
        target = self._create_running(
            session_id, roster=roster, initial=MISSING
        )
        subject, executors = self._subject(
            roster,
            {
                "lead": [
                    self._write_action(
                        target, b"created target", "created target"
                    )
                ],
                "critic": [],
            },
        )
        prepared = subject.prepare(session_id)
        self.assertIsNone(prepared.state["accepted_target_revision"])
        absent = self.store.read_target_revision(
            session_id, prepared.state["recovery_baseline_revision"]
        )
        self.assertEqual(bs.target_revision_content(absent), (False, b""))
        accepted = subject.run_next_turn(session_id, object())
        accepted_revision = accepted.state["accepted_target_revision"]

        with open(target, "wb") as handle:
            handle.write(b"divergent after restart")
        reopened = bs.SessionStore(os.path.join(self.root, "state"))
        resumed = coordination.BrainstormingCoordinator(
            reopened,
            execution.ParticipantExecution(reopened, executors),
        )
        reconciled = resumed.prepare(session_id)
        self.assertEqual(
            reconciled.state["accepted_target_revision"], accepted_revision
        )
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"created target")

        sentinel = os.path.join(os.path.dirname(target), "sentinel")
        with open(sentinel, "wb") as handle:
            handle.write(b"stable")
        os.unlink(target)
        os.mkdir(target)
        with open(os.path.join(target, "wrong"), "wb") as handle:
            handle.write(b"wrong")
        resumed.prepare(session_id)
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"created target")
        with open(sentinel, "rb") as handle:
            self.assertEqual(handle.read(), b"stable")

        os.unlink(target)
        os.symlink(sentinel, target)
        resumed.prepare(session_id)
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"created target")
        with open(sentinel, "rb") as handle:
            self.assertEqual(handle.read(), b"stable")

        delete_id = "accepted-deletion"
        delete_target = self._create_running(delete_id, roster=roster)
        deleting, _ = self._subject(
            roster,
            {
                "lead": [
                    self._delete_action(delete_target, "deleted target")
                ],
                "critic": [],
            },
        )
        deleted = deleting.run_next_turn(delete_id, object())
        deleted_record = self.store.read_target_revision(
            delete_id, deleted.state["accepted_target_revision"]
        )
        self.assertEqual(
            bs.target_revision_content(deleted_record), (False, b"")
        )
        with open(delete_target, "wb") as handle:
            handle.write(b"must disappear")
        deleting.prepare(delete_id)
        self.assertFalse(os.path.lexists(delete_target))

        hardlink_id = "hardlinked-start"
        hardlink_target = self._create_running(
            hardlink_id, roster=roster
        )
        other_name = os.path.join(
            os.path.dirname(hardlink_target), "other-name.md"
        )
        os.link(hardlink_target, other_name)
        hardlinked, hardlink_executors = self._subject(
            roster,
            {"lead": [envelope("must not run")], "critic": []},
        )
        with self.assertRaises(coordination.CoordinationRejected):
            hardlinked.run_next_turn(hardlink_id, object())
        self.assertEqual(
            hardlink_executors["codex-lead"].calls, []
        )
        with open(other_name, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

    def test_stale_coordinator_cannot_duplicate_or_reorder_turns(self):
        session_id = "stale-coordinator"
        roster = participants()
        self._create_running(session_id, roster=roster)
        waiter_started = threading.Event()
        release = threading.Event()

        def held_result(_prompt, _workspace, _context):
            def wait():
                waiter_started.set()
                release.wait()

            return envelope("sole accepted turn"), wait

        subject, executors = self._subject(
            roster,
            {"lead": [held_result], "critic": []},
        )

        def run():
            try:
                return subject.run_next_turn(session_id, object())
            except BaseException as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run)
            self.assertTrue(waiter_started.wait(timeout=2))
            second = pool.submit(run)
            release.set()
            outcomes = [first.result(timeout=2), second.result(timeout=2)]

        self.assertEqual(
            sum(isinstance(item, bs.SessionSnapshot) for item in outcomes), 1
        )
        self.assertEqual(
            sum(isinstance(item, bs.RevisionConflict) for item in outcomes), 1
        )
        durable = self.store.read(session_id)
        self.assertEqual(len(durable.state["completed_turns"]), 1)
        self.assertEqual(
            durable.state["completed_turns"][0]["participant_id"], "lead"
        )
        self.assertEqual(len(executors["codex-lead"].calls), 1)

    def test_coordination_reuses_execution_without_public_surface_changes(self):
        session_id = "compatibility"
        roster = participants()
        target = self._create_running(session_id, roster=roster)

        class LegacyExecutor(ScriptedExecutor):
            wait_for_quiescence = None

        legacy = LegacyExecutor(
            "codex",
            [envelope("ordinary exchange"), envelope("must not launch")],
        )
        participant_execution = execution.ParticipantExecution(
            self.store, {"codex-lead": legacy}
        )
        accepted, _result = participant_execution.exchange(
            session_id, "lead", "ordinary prompt", {"caller": "unchanged"}
        )
        self.assertEqual(accepted, envelope("ordinary exchange"))
        self.assertEqual(len(legacy.calls), 1)

        subject = coordination.BrainstormingCoordinator(
            self.store, participant_execution
        )
        with self.assertRaises(execution.ExecutionRejected):
            subject.run_next_turn(session_id, {"caller": "unchanged"})
        self.assertEqual(len(legacy.calls), 1)
        self.assertEqual(
            self.store.read(session_id).state["completed_turns"], []
        )
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")


if __name__ == "__main__":
    unittest.main()
