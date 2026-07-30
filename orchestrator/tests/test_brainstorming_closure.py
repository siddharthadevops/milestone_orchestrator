"""Focused executable evidence for Brainstorming Slice 05."""

import copy
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from orchestrator import brainstorming as bs
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_execution as execution
from orchestrator import runners


def participants(count=2):
    roster = [
        {
            "id": "lead",
            "role": "lead",
            "executor_ref": "codex-lead",
            "model_family": "codex",
        }
    ]
    for index in range(1, count):
        family = "claude" if index % 2 else "codex"
        roster.append(
            {
                "id": "critic-%d" % index,
                "role": "interlocutor",
                "executor_ref": "%s-critic-%d" % (family, index),
                "model_family": family,
            }
        )
    return roster


def discussion(markdown):
    return {"kind": "discussion_turn", "markdown": markdown}


def summary(reason="The participants reached a bounded decision."):
    return {
        "reason": reason,
        "unresolved_objections": [],
        "affected_parties": "The people who use the requested target.",
        "damage_altitude": "A bounded and reversible design consequence.",
        "proportionality": "The discussion matched the size of the decision.",
        "escalation_evidence": None,
    }


def proposal(propose=True, reason="The participants reached a bounded decision."):
    return {
        "kind": "closure_proposal",
        "propose": propose,
        "closing_summary": summary(reason),
    }


def vote(value):
    return {"kind": "closure_vote", "vote": value}


class ScriptedExecutor:
    def __init__(self, model_family, responses):
        self.model_family = model_family
        self.responses = list(responses)
        self.calls = []
        self._next_ref = 0
        self._lock = threading.Lock()

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
                session_ref = "logical-%d" % self._next_ref
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


class BrainstormingClosureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(
            prefix="brainstorming-closure-"
        )
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.store = bs.SessionStore(os.path.join(self.root, "state"))

    def _make(
        self,
        session_id,
        scripts,
        *,
        roster=None,
        policy="unanimity",
        max_rounds=2,
        target_exists=True,
    ):
        roster = roster or participants()
        workspace = os.path.join(self.root, session_id)
        docs = os.path.join(workspace, "docs")
        os.makedirs(docs)
        target = os.path.join(docs, "decision.md")
        if target_exists:
            with open(target, "wb") as handle:
                handle.write(b"initial target")
        sibling = os.path.join(workspace, "sibling.sentinel")
        with open(sibling, "wb") as handle:
            handle.write(b"untouched sibling")
        request = {
            "workspace_path": workspace,
            "target_path": "docs/decision.md",
            "question": "Which compatible option should be adopted?",
            "context": {
                "brief": "Resolve one bounded design question.",
                "source_payload": {"opaque": ["kept", 7]},
            },
            "max_rounds": max_rounds,
        }
        config = bs.resolve_run_config(roster, policy, roster)
        created = self.store.create(session_id, request, config, roster)
        self.store.transition(session_id, created.revision, "running")
        executors = {
            participant["executor_ref"]: ScriptedExecutor(
                participant["model_family"], scripts[participant["id"]]
            )
            for participant in roster
        }
        subject = coordination.BrainstormingCoordinator(
            self.store,
            execution.ParticipantExecution(self.store, executors),
        )
        return subject, roster, executors, target, sibling

    @staticmethod
    def _complete_round(subject, session_id, roster, context=None):
        context = object() if context is None else context
        snapshot = None
        for _participant in roster:
            snapshot = subject.run_next_turn(session_id, context)
        return snapshot

    @staticmethod
    def _ballot(state, values, *, approved=None, round_number=None,
                target_revision=None):
        votes = [
            {"participant_id": participant["id"], "vote": value}
            for participant, value in zip(
                state["run_config"]["participants"], values
            )
        ]
        if approved is None:
            approved = bs.evaluate_closure(state["run_config"], votes)
        return {
            "after_completed_rounds": (
                state["rounds_used"]
                if round_number is None
                else round_number
            ),
            "target_revision": (
                state["accepted_target_revision"]
                if target_revision is None
                else target_revision
            ),
            "votes": votes,
            "approved": approved,
        }

    @staticmethod
    def _result(state, outcome, reason=None):
        result = {
            "outcome": outcome,
            "target_ref": state["request"]["target_path"],
            "transcript_ref": state["transcript_ref"],
            "rounds_used": state.get("rounds_used", 0),
        }
        if outcome == "failure":
            result["reason"] = reason
        return result

    @staticmethod
    def _read_transcript(snapshot):
        with open(snapshot.state["transcript_ref"], encoding="utf-8") as handle:
            return handle.read()

    def _boundary(
        self,
        session_id,
        *,
        policy="unanimity",
        max_rounds=2,
        roster=None,
    ):
        roster = roster or participants()
        scripts = {
            participant["id"]: [discussion("round contribution")]
            for participant in roster
        }
        subject, roster, executors, target, sibling = self._make(
            session_id,
            scripts,
            roster=roster,
            policy=policy,
            max_rounds=max_rounds,
        )
        snapshot = self._complete_round(subject, session_id, roster)
        return snapshot, subject, roster, executors, target, sibling

    def test_ballot_is_complete_ordered_and_decision_is_derived(self):
        snapshot, _subject, _roster, _executors, _target, _sibling = (
            self._boundary("ballot-shape")
        )
        state = snapshot.state
        valid = self._ballot(state, ("accept", "object"))
        self.assertFalse(valid["approved"])

        invalid = []
        candidate = copy.deepcopy(valid)
        candidate["votes"] = candidate["votes"][:-1]
        invalid.append(candidate)
        candidate = copy.deepcopy(valid)
        candidate["votes"] = [candidate["votes"][0]] * 2
        invalid.append(candidate)
        candidate = copy.deepcopy(valid)
        candidate["votes"].reverse()
        invalid.append(candidate)
        candidate = copy.deepcopy(valid)
        candidate["votes"].append(
            {"participant_id": "extra", "vote": "accept"}
        )
        invalid.append(candidate)
        candidate = copy.deepcopy(valid)
        candidate["votes"][1]["extra"] = True
        invalid.append(candidate)
        candidate = copy.deepcopy(valid)
        candidate["votes"][1]["participant_id"] = "outsider"
        invalid.append(candidate)
        candidate = copy.deepcopy(valid)
        candidate["votes"][1]["vote"] = "abstain"
        invalid.append(candidate)
        candidate = copy.deepcopy(valid)
        candidate["votes"][0]["vote"] = "object"
        invalid.append(candidate)
        candidate = copy.deepcopy(valid)
        candidate["approved"] = True
        invalid.append(candidate)
        for candidate in invalid:
            with self.assertRaises(bs.ContractError):
                bs.validate_closure_ballot(
                    candidate, state["run_config"]
                )

        for candidate in (
            self._ballot(state, ("accept", "object"), round_number=2),
            self._ballot(
                state,
                ("accept", "object"),
                target_revision=bs.make_target_revision(
                    True, b"other", 0o644
                )["revision"],
            ),
        ):
            with self.assertRaises(bs.HistoryRewriteError):
                bs.transcript_event_successor(
                    state, "closure_ballot", candidate
                )

        accepted = self.store.record_closure_ballot(
            "ballot-shape", snapshot.revision, valid
        )
        recorded = accepted.state["transcript_events"][-1]["fact"]
        self.assertEqual(recorded["approved"], bs.evaluate_closure(
            state["run_config"], recorded["votes"]
        ))

    def test_unanimity_majority_and_lead_tiebreak_matrix(self):
        two = participants(2)
        unanimous = bs.resolve_run_config(two, "unanimity", two)
        majority_two = bs.resolve_run_config(
            two, "majority_with_lead_tiebreak", two
        )
        all_accept = [
            {"participant_id": "lead", "vote": "accept"},
            {"participant_id": "critic-1", "vote": "accept"},
        ]
        disagreement = copy.deepcopy(all_accept)
        disagreement[1]["vote"] = "object"
        self.assertTrue(bs.evaluate_closure(unanimous, all_accept))
        self.assertFalse(bs.evaluate_closure(unanimous, disagreement))
        self.assertTrue(
            bs.evaluate_closure(majority_two, disagreement),
            "the two-person exact tie follows the lead's accept proposal",
        )

        three = participants(3)
        majority_three = bs.resolve_run_config(
            three, "majority_with_lead_tiebreak", three
        )
        accept_majority = [
            {"participant_id": "lead", "vote": "accept"},
            {"participant_id": "critic-1", "vote": "accept"},
            {"participant_id": "critic-2", "vote": "object"},
        ]
        object_majority = copy.deepcopy(accept_majority)
        object_majority[1]["vote"] = "object"
        self.assertTrue(bs.evaluate_closure(
            majority_three, accept_majority
        ))
        self.assertFalse(bs.evaluate_closure(
            majority_three, object_majority
        ))

        four = participants(4)
        majority_four = bs.resolve_run_config(
            four, "majority_with_lead_tiebreak", four
        )
        exact_tie = [
            {"participant_id": "lead", "vote": "accept"},
            {"participant_id": "critic-1", "vote": "object"},
            {"participant_id": "critic-2", "vote": "accept"},
            {"participant_id": "critic-3", "vote": "object"},
        ]
        self.assertTrue(bs.evaluate_closure(majority_four, exact_tie))

    def test_target_mutation_retries_closure_once_and_restores_only_target(self):
        def mutate(path, operation, response):
            def action(_prompt, _workspace, _context):
                if operation == "write":
                    with open(path, "wb") as handle:
                        handle.write(b"invalid mutation")
                    return response
                if operation == "delete":
                    os.unlink(path)
                    return response
                if operation == "recreate":
                    os.unlink(path)
                    with open(path, "wb") as handle:
                        handle.write(b"recreated mutation")
                    return response

                def late_write():
                    with open(path, "wb") as handle:
                        handle.write(b"late mutation")

                return response, late_write

            return action

        cases = (
            ("lead-write", "lead", "write"),
            ("critic-write", "critic", "write"),
            ("critic-delete", "critic", "delete"),
            ("critic-recreate", "critic", "recreate"),
            ("critic-late", "critic", "late"),
        )
        for session_id, actor, operation in cases:
            with self.subTest(actor=actor, operation=operation):
                roster = participants()
                scripts = {
                    "lead": [discussion("lead discussion")],
                    "critic-1": [discussion("critic discussion")],
                }
                subject, roster, _executors, target, sibling = self._make(
                    session_id, scripts, roster=roster
                )
                before = self._complete_round(
                    subject, session_id, roster
                )
                lead_response = proposal()
                critic_response = vote("accept")
                lead_executor = subject.participant_execution.executors[
                    "codex-lead"
                ]
                critic_executor = subject.participant_execution.executors[
                    "claude-critic-1"
                ]
                lead_executor.responses.append(
                    mutate(target, operation, lead_response)
                    if actor == "lead"
                    else lead_response
                )
                if actor == "lead":
                    lead_executor.responses.append(lead_response)
                critic_executor.responses.append(
                    mutate(target, operation, critic_response)
                    if actor == "critic"
                    else critic_response
                )
                if actor == "critic":
                    critic_executor.responses.append(critic_response)

                after = subject.run_closure(session_id, object())
                for field in (
                    "completed_turns",
                    "rounds_used",
                    "accepted_target_revision",
                ):
                    self.assertEqual(after.state[field], before.state[field])
                self.assertEqual(after.state["status"], "success")
                self.assertEqual(after.state["result"]["outcome"], "success")
                ballots = [
                    event
                    for event in after.state["transcript_events"]
                    if event["kind"] == "closure_ballot"
                ]
                self.assertEqual(len(ballots), 1)
                self.assertIsNone(self.store.read_turn_attempt(session_id))
                with open(target, "rb") as handle:
                    self.assertEqual(handle.read(), b"initial target")
                with open(sibling, "rb") as handle:
                    self.assertEqual(handle.read(), b"untouched sibling")

    def test_target_mutation_is_detected_before_protocol_repair(self):
        roster = participants()
        scripts = {
            "lead": [discussion("lead discussion")],
            "critic-1": [discussion("critic discussion")],
        }
        subject, roster, executors, target, sibling = self._make(
            "mutation-before-repair", scripts, roster=roster
        )
        before = self._complete_round(
            subject, "mutation-before-repair", roster
        )
        retry_prompts = []

        def malformed_after_mutation(_prompt, _workspace, _context):
            with open(target, "wb") as handle:
                handle.write(b"invalid mutation")
            return "not a control envelope"

        def malformed_retry(prompt, _workspace, _context):
            retry_prompts.append(prompt)
            return "still not a control envelope"

        def repaired_retry(prompt, _workspace, _context):
            retry_prompts.append(prompt)
            return proposal()

        lead_executor = executors["codex-lead"]
        lead_executor.responses.extend(
            [malformed_after_mutation, malformed_retry, repaired_retry]
        )
        executors["claude-critic-1"].responses.append(vote("accept"))

        after = subject.run_closure("mutation-before-repair", object())

        self.assertNotIn("REPAIR:", retry_prompts[0])
        self.assertIn("REPAIR:", retry_prompts[1])
        self.assertEqual(lead_executor.responses, [])
        for field in (
            "completed_turns",
            "rounds_used",
            "accepted_target_revision",
        ):
            self.assertEqual(after.state[field], before.state[field])
        self.assertEqual(after.state["result"]["outcome"], "success")
        self.assertIsNone(
            self.store.read_turn_attempt("mutation-before-repair")
        )
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")
        with open(sibling, "rb") as handle:
            self.assertEqual(handle.read(), b"untouched sibling")

    def test_corrected_closure_vote_resumes_same_vote_after_restart(self):
        roster = participants()
        scripts = {
            "lead": [discussion("lead discussion")],
            "critic-1": [
                discussion("critic discussion"),
                vote("accept"),
            ],
        }
        subject, roster, executors, target, _sibling = self._make(
            "closure-vote-restart", scripts, roster=roster
        )
        completed = self._complete_round(
            subject, "closure-vote-restart", roster
        )
        with coordination._open_target_parent(target) as (
            _descriptor,
            _name,
            parent_identity,
        ):
            attempt = {
                "token": "corrected-vote",
                "participant_id": "critic-1",
                "completed_turn_count": len(
                    completed.state["completed_turns"]
                ),
                "target_revision": completed.state[
                    "accepted_target_revision"
                ],
                "quiescent": False,
                "target_parent": parent_identity,
                "kind": "closure",
                "action_context": {
                    "stage": "vote",
                    "closing_summary": summary(),
                    "votes_by_id": {"lead": "accept"},
                },
            }
        self.store.begin_turn_attempt("closure-vote-restart", attempt)
        self.store.mark_turn_attempt_quiescent(
            "closure-vote-restart", attempt["token"]
        )
        self.assertFalse(
            self.store.mark_turn_attempt_target_mutation(
                "closure-vote-restart", attempt["token"]
            )
        )
        lead_calls = len(executors["codex-lead"].calls)
        restarted = coordination.BrainstormingCoordinator(
            bs.SessionStore(os.path.join(self.root, "state")),
            subject.participant_execution,
        )
        terminal = restarted.run_closure(
            "closure-vote-restart", object()
        )
        self.assertEqual(terminal.state["status"], "success")
        self.assertEqual(len(executors["codex-lead"].calls), lead_calls)
        self.assertEqual(
            executors["claude-critic-1"].calls[-1]["mode"], "continue"
        )
        self.assertIsNone(
            self.store.read_turn_attempt("closure-vote-restart")
        )

    def test_operational_closure_vote_resumes_the_same_vote(self):
        roster = participants()
        scripts = {
            "lead": [discussion("lead discussion")],
            "critic-1": [
                discussion("critic discussion"),
                vote("accept"),
            ],
        }
        subject, roster, executors, target, _sibling = self._make(
            "closure-vote-operational-retry", scripts, roster=roster
        )
        completed = self._complete_round(
            subject, "closure-vote-operational-retry", roster
        )
        with coordination._open_target_parent(target) as (
            _descriptor, _name, parent_identity
        ):
            attempt = {
                "token": "operational-vote",
                "participant_id": "critic-1",
                "completed_turn_count": len(
                    completed.state["completed_turns"]
                ),
                "target_revision": completed.state[
                    "accepted_target_revision"
                ],
                "quiescent": False,
                "target_parent": parent_identity,
                "kind": "closure",
                "action_context": {
                    "stage": "vote",
                    "closing_summary": summary(),
                    "votes_by_id": {"lead": "accept"},
                },
            }
        self.store.begin_turn_attempt(
            "closure-vote-operational-retry", attempt
        )
        self.store.mark_turn_attempt_quiescent(
            "closure-vote-operational-retry", attempt["token"]
        )
        self.store.schedule_operational_retry(
            "closure-vote-operational-retry",
            attempt["token"],
            {"error_type": "busy", "resume_at": None, "evidence": ""},
            1.0,
        )
        lead_calls = len(executors["codex-lead"].calls)

        terminal = subject.run_closure(
            "closure-vote-operational-retry", object()
        )

        self.assertEqual(terminal.state["status"], "success")
        self.assertEqual(len(executors["codex-lead"].calls), lead_calls)
        self.assertEqual(
            executors["claude-critic-1"].calls[-1]["mode"], "continue"
        )
        self.assertIsNone(
            self.store.read_turn_attempt("closure-vote-operational-retry")
        )

    def test_failed_ballot_requires_another_complete_round(self):
        roster = participants()
        scripts = {
            "lead": [
                discussion("first lead proposal"),
                proposal(),
                discussion("revised lead proposal"),
                proposal(),
            ],
            "critic-1": [
                discussion("first objection"),
                vote("object"),
                discussion("objection resolved"),
                vote("accept"),
            ],
        }
        subject, roster, executors, _target, _sibling = self._make(
            "resume", scripts, roster=roster, max_rounds=2
        )
        first_round = self._complete_round(subject, "resume", roster)
        failed_ballot = subject.run_closure("resume", object())
        self.assertEqual(failed_ballot.state["status"], "running")
        self.assertEqual(failed_ballot.state["rounds_used"], 1)
        self.assertFalse(
            failed_ballot.state["transcript_events"][-1]["fact"]["approved"]
        )
        calls_before = sum(len(item.calls) for item in executors.values())
        with self.assertRaises(coordination.ClosureNotEligible):
            subject.run_closure("resume", object())
        self.assertEqual(
            sum(len(item.calls) for item in executors.values()), calls_before
        )

        second_round = self._complete_round(subject, "resume", roster)
        self.assertEqual(second_round.state["rounds_used"], 2)
        lead_round_two_prompt = executors["codex-lead"].calls[2]["prompt"]
        self.assertIn("Closure ballot — After round 1", lead_round_two_prompt)
        closed = subject.run_closure("resume", object())
        self.assertEqual(closed.state["status"], "success")
        self.assertEqual(
            [
                event["fact"]["after_completed_rounds"]
                for event in closed.state["transcript_events"]
                if event["kind"] == "closure_ballot"
            ],
            [1, 2],
        )
        self.assertEqual(first_round.state["rounds_used"], 1)

    def test_round_exhaustion_without_approval_is_failure(self):
        cases = (
            ("final-rejected", True),
            ("no-proposal", False),
        )
        for session_id, proposes in cases:
            with self.subTest(proposes=proposes):
                roster = participants()
                scripts = {
                    "lead": [
                        discussion("final lead turn"),
                        proposal(
                            proposes,
                            "The round bound ended without agreement.",
                        ),
                    ],
                    "critic-1": [discussion("final objection")],
                }
                if proposes:
                    scripts["critic-1"].append(vote("object"))
                subject, roster, _executors, _target, _sibling = self._make(
                    session_id,
                    scripts,
                    roster=roster,
                    max_rounds=1,
                )
                self._complete_round(subject, session_id, roster)
                terminal = subject.run_closure(session_id, object())
                self.assertEqual(terminal.state["status"], "failure")
                self.assertEqual(terminal.state["result"]["rounds_used"], 1)
                self.assertTrue(terminal.state["result"]["reason"])
                ballots = [
                    event
                    for event in terminal.state["transcript_events"]
                    if event["kind"] == "closure_ballot"
                ]
                self.assertEqual(len(ballots), int(proposes))
                if ballots:
                    self.assertFalse(ballots[0]["fact"]["approved"])
                markdown = self._read_transcript(terminal)
                self.assertIn("The target was left unfinished.", markdown)
                with self.assertRaises(coordination.CoordinationRejected):
                    subject.run_next_turn(session_id, object())
                with self.assertRaises(coordination.CoordinationRejected):
                    subject.run_closure(session_id, object())

    def test_success_requires_current_approved_ballot_and_is_atomic(self):
        majority_roster = participants(3)
        snapshot, subject, roster, executors, _target, _sibling = (
            self._boundary(
                "eligibility",
                policy="majority_with_lead_tiebreak",
                max_rounds=2,
                roster=majority_roster,
            )
        )
        state = snapshot.state
        approved = self._ballot(
            state, ("accept", "accept", "object")
        )
        result = self._result(state, "success")
        closing = summary()
        with self.assertRaises(bs.ContractError):
            self.store.transition(
                "eligibility",
                snapshot.revision,
                "success",
                result,
                closing,
            )
        with self.assertRaises(bs.IllegalTransition):
            self.store.record_closure_ballot(
                "eligibility", snapshot.revision, approved
            )

        rejected = self._ballot(
            state, ("accept", "object", "object")
        )
        with self.assertRaises(
            (bs.IllegalTransition, bs.ContractError)
        ):
            bs.terminal_closure_successor(
                state, rejected, result, closing
            )
        for bad_ballot in (
            self._ballot(
                state,
                ("accept", "accept", "object"),
                round_number=2,
            ),
            self._ballot(
                state,
                ("accept", "accept", "object"),
                target_revision=bs.make_target_revision(
                    True, b"stale", 0o644
                )["revision"],
            ),
        ):
            with self.assertRaises(bs.HistoryRewriteError):
                bs.terminal_closure_successor(
                    state, bad_ballot, result, closing
                )
        bad_result = copy.deepcopy(result)
        bad_result["transcript_ref"] = "/wrong/chat.md"
        with self.assertRaises(bs.ContractError):
            bs.terminal_closure_successor(
                state, approved, bad_result, closing
            )
        bad_result = copy.deepcopy(result)
        bad_result["rounds_used"] = 0
        with self.assertRaises(bs.ContractError):
            bs.terminal_closure_successor(
                state, approved, bad_result, closing
            )
        bad_summary = copy.deepcopy(closing)
        del bad_summary["proportionality"]
        with self.assertRaises(bs.ContractError):
            bs.terminal_closure_successor(
                state, approved, result, bad_summary
            )

        executors["codex-lead"].responses.append(proposal())
        executors["claude-critic-1"].responses.append(vote("accept"))
        executors["codex-critic-2"].responses.append(vote("object"))
        terminal = subject.run_closure("eligibility", object())
        self.assertEqual(terminal.state["status"], "success")
        self.assertTrue(
            terminal.state["transcript_events"][-1]["fact"]["approved"]
        )
        self.assertEqual(terminal.state["result"], terminal.state["history"][-1][
            "result"
        ])
        self.assertEqual(
            terminal.state["closing_summary"],
            terminal.state["history"][-1]["closing_summary"],
        )
        self.assertEqual(
            terminal.state["closing_summary"]["unresolved_objections"],
            ["Interlocutor 2 objected to closure."],
        )
        markdown = self._read_transcript(terminal)
        self.assertIn("This ballot approved closure.", markdown)
        self.assertIn("Interlocutor 2 objected to closure.", markdown)
        self.assertEqual(markdown.count("## Closing"), 1)

    def test_terminal_objections_ignore_a_ballot_invalidated_by_a_later_turn(
        self,
    ):
        snapshot, _subject, _roster, _executors, _target, _sibling = (
            self._boundary("stale-terminal-objection", max_rounds=3)
        )
        rejected = bs.transcript_event_successor(
            snapshot.state,
            "closure_ballot",
            self._ballot(snapshot.state, ("accept", "object")),
        )
        revised_target = bs.make_target_revision(
            True, b"revised target", 0o644
        )["revision"]
        after_lead_edit = bs.completed_turn_successor(
            rejected,
            "lead",
            "The lead revised the target after the rejected ballot.",
            revised_target,
        )
        after_interlocutor = bs.completed_turn_successor(
            after_lead_edit,
            "critic-1",
            "The interlocutor discussed the revised target.",
            revised_target,
        )
        returned_to_original = bs.completed_turn_successor(
            after_interlocutor,
            "lead",
            "The lead restored the original target content.",
            rejected["accepted_target_revision"],
        )
        reason = "The run stopped after the target changed."
        terminal = bs.transition_session(
            returned_to_original,
            "failure",
            self._result(returned_to_original, "failure", reason),
            summary(reason),
        )
        self.assertEqual(
            terminal["closing_summary"]["unresolved_objections"], []
        )

    def test_generic_failure_derives_current_ballot_objections(self):
        snapshot, _subject, _roster, _executors, _target, _sibling = (
            self._boundary("interrupted-terminal-objection", max_rounds=2)
        )
        rejected = bs.transcript_event_successor(
            snapshot.state,
            "closure_ballot",
            self._ballot(snapshot.state, ("accept", "object")),
        )
        resumed = bs.completed_turn_successor(
            rejected,
            "lead",
            "Discussion resumed without changing the target.",
            rejected["accepted_target_revision"],
        )
        interrupted = bs.transcript_event_successor(
            resumed,
            "material_interruption",
            {
                "after_completed_turns": len(resumed["completed_turns"]),
                "plain": "The provider stopped before discussion resumed.",
            },
        )
        reason = "The run stopped after the rejected ballot."
        result = self._result(interrupted, "failure", reason)
        closing = summary(reason)
        closing["unresolved_objections"] = [
            "The participant's authored concern remains unresolved."
        ]
        terminal = bs.transition_session(
            interrupted, "failure", result, closing
        )
        self.assertEqual(
            terminal["closing_summary"]["unresolved_objections"],
            [
                "The participant's authored concern remains unresolved.",
                "Interlocutor 1 objected to closure.",
            ],
        )

    def test_absent_target_only_fails_at_exhaustion(self):
        roster = participants()
        scripts = {
            "lead": [
                discussion("The target is still absent."),
                proposal(),
                discussion("The target remains absent."),
                proposal(),
            ],
            "critic-1": [
                discussion("The target must be produced."),
                discussion("The target is still required."),
            ],
        }
        subject, roster, _executors, target, _sibling = self._make(
            "absent-success",
            scripts,
            roster=roster,
            target_exists=False,
        )
        boundary = self._complete_round(
            subject, "absent-success", roster
        )
        approved = self._ballot(
            boundary.state, ("accept", "accept")
        )
        with self.assertRaises(bs.ContractError):
            self.store.close_with_ballot(
                "absent-success",
                boundary.revision,
                approved,
                self._result(boundary.state, "success"),
                summary(),
            )

        continuing = subject.run_closure("absent-success", object())
        self.assertEqual(continuing.state["status"], "running")
        self.assertEqual(continuing.state["rounds_used"], 1)
        self.assertNotIn("result", continuing.state)
        self.assertFalse(any(
            event["kind"] == "closure_ballot"
            for event in continuing.state["transcript_events"]
        ))

        second_round = self._complete_round(
            subject, "absent-success", roster
        )
        self.assertEqual(second_round.state["rounds_used"], 2)
        terminal = subject.run_closure("absent-success", object())
        self.assertEqual(terminal.state["status"], "failure")
        self.assertEqual(
            terminal.state["result"]["reason"],
            "The requested target was not produced.",
        )
        self.assertFalse(os.path.exists(target))
        self.assertFalse(any(
            event["kind"] == "closure_ballot"
            for event in terminal.state["transcript_events"]
        ))
        markdown = self._read_transcript(terminal)
        self.assertIn("The target was left unfinished.", markdown)
        self.assertNotIn("The target was produced.", markdown)

    def test_terminal_closing_records_object_votes_as_unresolved_objections(self):
        roster = participants()
        authored_objection = "The requested safeguard remains unresolved."
        closing = summary("The final ballot did not reach agreement.")
        closing["unresolved_objections"] = [authored_objection]
        scripts = {
            "lead": [
                discussion("The lead considers the target ready."),
                {
                    "kind": "closure_proposal",
                    "propose": True,
                    "closing_summary": closing,
                },
            ],
            "critic-1": [
                discussion("The remaining concern is unresolved."),
                vote("object"),
            ],
        }
        subject, roster, _executors, _target, _sibling = self._make(
            "record-objection",
            scripts,
            roster=roster,
            max_rounds=1,
        )
        self._complete_round(subject, "record-objection", roster)
        terminal = subject.run_closure("record-objection", object())
        generated_objection = "Interlocutor 1 objected to closure."
        self.assertEqual(terminal.state["status"], "failure")
        self.assertEqual(
            terminal.state["closing_summary"]["unresolved_objections"],
            [authored_objection, generated_objection],
        )
        self.assertEqual(
            terminal.state["closing_summary"],
            terminal.state["history"][-1]["closing_summary"],
        )
        markdown = self._read_transcript(terminal)
        self.assertIn(authored_objection, markdown)
        self.assertIn(generated_objection, markdown)
        self.assertIn("**Interlocutor 1:** `object`", markdown)
        self.assertNotIn(
            "No unresolved objections were recorded.", markdown
        )

    def test_failure_before_first_turn_retains_complete_evidence(self):
        workspace = os.path.join(self.root, "zero")
        os.makedirs(workspace)
        target = os.path.join(workspace, "decision.md")
        with open(target, "wb") as handle:
            handle.write(b"unfinished target")
        roster = participants()
        request = {
            "workspace_path": workspace,
            "target_path": "decision.md",
            "question": "Can this run start?",
            "context": {"brief": "The provider failed before speaking."},
            "max_rounds": 1,
        }
        config = bs.resolve_run_config(roster, "unanimity", roster)
        created = self.store.create("zero", request, config, roster)
        reason = "No participant completed a turn."
        result = {
            "outcome": "failure",
            "target_ref": "decision.md",
            "transcript_ref": created.state["transcript_ref"],
            "rounds_used": 0,
            "reason": reason,
        }
        terminal = self.store.transition(
            "zero",
            created.revision,
            "failure",
            result,
            summary(reason),
        )
        self.assertEqual(terminal.state["status"], "failure")
        self.assertEqual(terminal.state["result"]["rounds_used"], 0)
        self.assertEqual(
            terminal.state["closing_summary"]["reason"], reason
        )
        self.assertFalse(any(
            event["kind"] == "closure_ballot"
            for event in terminal.state["transcript_events"]
        ))
        self.assertEqual(terminal.state["request"]["target_path"], "decision.md")
        self.assertTrue(os.path.exists(target))
        markdown = self._read_transcript(terminal)
        self.assertIn(reason, markdown)
        self.assertEqual(markdown.count("## Closing"), 1)
        with self.assertRaises(bs.IllegalTransition):
            self.store.transition(
                "zero",
                terminal.revision,
                "failure",
                result,
                summary(reason),
            )

    def test_stale_closure_attempt_cannot_publish_losing_state(self):
        snapshot, _subject, _roster, _executors, target, _sibling = (
            self._boundary("contended", max_rounds=1)
        )
        state = snapshot.state
        candidates = (
            (
                self._ballot(state, ("accept", "accept")),
                self._result(state, "success"),
                summary("Winning success account."),
            ),
            (
                self._ballot(state, ("accept", "object")),
                self._result(
                    state, "failure", "Losing failure account."
                ),
                summary("Losing failure account."),
            ),
        )
        barrier = threading.Barrier(2)

        def close(candidate):
            ballot, result, closing = candidate
            barrier.wait()
            try:
                return (
                    "ok",
                    self.store.close_with_ballot(
                        "contended",
                        snapshot.revision,
                        ballot,
                        result,
                        closing,
                    ),
                )
            except bs.RevisionConflict as exc:
                return "stale", exc.current

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(close, candidates))
        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 1)
        self.assertEqual([kind for kind, _ in outcomes].count("stale"), 1)
        terminal = self.store.read("contended")
        ballots = [
            event
            for event in terminal.state["transcript_events"]
            if event["kind"] == "closure_ballot"
        ]
        self.assertEqual(len(ballots), 1)
        self.assertEqual(terminal.state["result"]["outcome"], terminal.state[
            "status"
        ])
        markdown = self._read_transcript(terminal)
        winning_reason = terminal.state["closing_summary"]["reason"]
        losing_reason = (
            "Losing failure account."
            if winning_reason != "Losing failure account."
            else "Winning success account."
        )
        self.assertIn(winning_reason, markdown)
        self.assertNotIn(losing_reason, markdown)
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"initial target")

    def test_closure_reuses_sessions_and_changes_no_public_surface(self):
        service_path = os.path.join(
            os.path.dirname(bs.__file__), "service.py"
        )
        panel_path = os.path.join(
            os.path.dirname(bs.__file__), "static", "panel.html"
        )
        with open(service_path, "rb") as handle:
            service_before = handle.read()
        with open(panel_path, "rb") as handle:
            panel_before = handle.read()

        roster = participants()
        scripts = {
            "lead": [discussion("lead turn"), proposal()],
            "critic-1": [discussion("critic turn"), vote("accept")],
        }
        subject, roster, executors, _target, sibling = self._make(
            "compatibility", scripts, roster=roster
        )
        context = {"roots": ["primary", "read-only-neighbour"]}
        boundary = self._complete_round(
            subject, "compatibility", roster, context
        )
        sessions_before = copy.deepcopy(
            boundary.state["participant_sessions"]
        )
        terminal = subject.run_closure("compatibility", context)
        self.assertEqual(
            terminal.state["participant_sessions"], sessions_before
        )
        for executor in executors.values():
            self.assertEqual(
                [call["mode"] for call in executor.calls],
                ["start", "continue"],
            )
            self.assertEqual(
                executor.calls[0]["session_ref"],
                executor.calls[1]["session_ref"],
            )
            self.assertTrue(all(
                call["execution_context"] is context
                for call in executor.calls
            ))
        self.assertEqual(
            set(terminal.state["result"]),
            {"outcome", "target_ref", "transcript_ref", "rounds_used"},
        )
        self.assertNotIn("milestone", terminal.state)
        with open(sibling, "rb") as handle:
            self.assertEqual(handle.read(), b"untouched sibling")
        with open(service_path, "rb") as handle:
            self.assertEqual(handle.read(), service_before)
        with open(panel_path, "rb") as handle:
            self.assertEqual(handle.read(), panel_before)


if __name__ == "__main__":
    unittest.main()
