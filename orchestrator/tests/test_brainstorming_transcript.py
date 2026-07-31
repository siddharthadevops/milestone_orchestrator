"""Focused executable evidence for Brainstorming Slice 04."""

import copy
import contextlib
import os
import re
import tempfile
import threading
import unicodedata
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from orchestrator import brainstorming as bs
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_execution as execution


def participants(same_family=False, three=False):
    roster = [
        {
            "id": "lead-machine",
            "role": "initial_position",
            "delivery": "llm",
            "executor_ref": "codex-machine",
            "model_family": "codex",
        },
        {
            "id": "critic-machine",
            "role": "contrary_position",
            "delivery": "llm",
            "executor_ref": "claude-machine",
            "model_family": "claude",
        },
    ]
    if same_family:
        roster[1].update(
            executor_ref="codex-critic-machine", model_family="codex"
        )
    if three:
        roster.append(
            {
                "id": "reader-machine",
                "role": "contrary_position",
                "delivery": "llm",
                "executor_ref": "gemini-machine",
                "model_family": "gemini",
            }
        )
    return roster


def run_config(roster, policy="unanimity"):
    return bs.resolve_run_config(roster, policy, roster)


def closing_summary(reason, objections=None):
    return {
        "reason": reason,
        "unresolved_objections": list(objections or []),
        "affected_parties": "The people who will use the target.",
        "damage_altitude": "A bounded, reversible design consequence.",
        "proportionality": "The discussion effort matched the decision.",
        "escalation_evidence": None,
        "open_questions": [],
    }


class BrainstormingTranscriptTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(
            prefix="brainstorming-transcript-"
        )
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.store = bs.SessionStore(os.path.join(self.root, "state"))

    def _create(
        self,
        session_id,
        *,
        roster=None,
        policy="unanimity",
        max_rounds=2,
        status="running",
        request_text="Which compatible option should be adopted?",
        brief="Resolve one bounded design request.",
        target_path="docs/decision.md",
        payload=None,
    ):
        roster = roster or participants()
        workspace = os.path.join(self.root, "workspaces", session_id)
        os.makedirs(os.path.join(workspace, "docs"), exist_ok=True)
        request = {
            "workspace_path": workspace,
            "target_path": target_path,
            "request": request_text,
            "context": {
                "brief": brief,
                "source_payload": payload,
            },
            "max_rounds": max_rounds,
        }
        created = self.store.create(
            session_id, request, run_config(roster, policy), roster
        )
        if status == "running":
            return self.store.transition(
                session_id, created.revision, "running"
            )
        return created

    def _initialize(self, session_id, snapshot, content=b"initial"):
        return self.store.initialize_coordination(
            session_id,
            snapshot.revision,
            bs.make_target_revision(True, content, 0o644),
        )

    def _turn(self, session_id, snapshot, participant_id, markdown, content=None):
        if content is None:
            revision = (
                snapshot.state["accepted_target_revision"]
                or snapshot.state["recovery_baseline_revision"]
            )
            target = self.store.read_target_revision(
                session_id, revision
            )
        else:
            target = bs.make_target_revision(True, content, 0o644)
        return self.store.record_completed_turn(
            session_id,
            snapshot.revision,
            participant_id,
            markdown,
            target,
        )

    def _ballot(self, session_id, snapshot, votes, approved):
        ballot = self._ballot_fact(snapshot, votes, approved)
        return self.store.record_closure_ballot(
            session_id, snapshot.revision, ballot
        )

    @staticmethod
    def _ballot_fact(snapshot, votes, approved, proposed_summary=None):
        ballot = {
            "after_completed_rounds": snapshot.state["rounds_used"],
            "target_revision": snapshot.state["accepted_target_revision"],
            "votes": [
                {
                    "participant_id": participant["id"],
                    "vote": vote,
                }
                for participant, vote in zip(
                    snapshot.state["run_config"]["participants"], votes
                )
            ],
            "approved": approved,
        }
        if proposed_summary is not None:
            ballot["closing_summary"] = proposed_summary
        return ballot

    def _terminal_ballot(
        self, session_id, snapshot, votes, approved, reason
    ):
        outcome = "success" if approved else "failure"
        result = {
            "outcome": outcome,
            "target_ref": snapshot.state["request"]["target_path"],
            "transcript_ref": snapshot.state["transcript_ref"],
            "rounds_used": snapshot.state["rounds_used"],
        }
        if outcome == "failure":
            result["reason"] = reason
        final_summary = closing_summary(
            reason, ["One objection remains."]
        )
        return self.store.close_with_ballot(
            session_id,
            snapshot.revision,
            self._ballot_fact(
                snapshot, votes, approved, final_summary
            ),
            result,
            final_summary,
        )

    def _terminal(self, session_id, snapshot, outcome, reason):
        result = {
            "outcome": outcome,
            "target_ref": snapshot.state["request"]["target_path"],
            "transcript_ref": snapshot.state["transcript_ref"],
            "rounds_used": snapshot.state.get("rounds_used", 0),
        }
        if outcome == "failure":
            result["reason"] = reason
        if outcome == "success":
            votes = tuple(
                "accept"
                for _participant in snapshot.state["run_config"]["participants"]
            )
            return self._terminal_ballot(
                session_id, snapshot, votes, True, reason
            )
        return self.store.transition(
            session_id,
            snapshot.revision,
            outcome,
            result,
            closing_summary(reason, ["One objection remains."]),
        )

    @staticmethod
    def _headings(markdown):
        return re.findall(r"^## (.+)$", markdown, flags=re.MULTILINE)

    @staticmethod
    def _read(snapshot):
        with open(snapshot.state["transcript_ref"], encoding="utf-8") as handle:
            return handle.read()

    def test_opening_precedes_turns_and_refs_are_session_scoped(self):
        first = self._create(
            "opening-a",
            roster=participants(three=True),
            payload={"opaque-sentinel": "never-render"},
        )
        second = self._create(
            "opening-b",
            policy="majority",
            request_text="Choose the smaller option.",
        )
        one = self._read(first)
        two = self._read(second)

        self.assertNotEqual(
            first.state["transcript_ref"], second.state["transcript_ref"]
        )
        self.assertTrue(first.state["transcript_ref"].endswith("/chat.md"))
        self.assertEqual(
            os.path.commonpath(
                (self.store.transcript_ref(".."), self.store.path + ".sessions")
            ),
            self.store.path + ".sessions",
        )
        self.assertEqual(self._headings(one), ["Opening"])
        for expected in (
            "Which compatible option",
            "Resolve one bounded design request",
            "docs/decision.md",
            "Initial Position",
            "Contrary Position",
            "Contrary Position 2",
            "Every position must agree",
            "at most 2 rounds",
        ):
            self.assertIn(expected, one)
        self.assertIn("strict majority", two)
        self.assertIn("a tie is a gap", two)
        for forbidden in (
            "opaque-sentinel",
            "lead-machine",
            "codex-machine",
            "same_family_fallback",
        ):
            self.assertNotIn(forbidden, one)

    def test_missing_session_read_creates_no_transcript_artifacts(self):
        session_id = "missing-session"
        transcript = self.store.transcript_ref(session_id)

        self.assertIsNone(self.store.read(session_id))
        self.assertFalse(os.path.exists(os.path.dirname(transcript)))
        self.assertFalse(os.path.exists(transcript + ".lock"))
        self.assertNotIn(transcript + ".lock", bs._TRANSCRIPT_LOCKS)

    def test_completed_turns_render_once_in_order_with_human_labels(self):
        session_id = "ordered"
        snapshot = self._initialize(
            session_id,
            self._create(session_id, roster=participants(three=True)),
        )
        for participant_id, markdown in (
            ("lead-machine", "Lead proposal."),
            ("critic-machine", "First critique."),
            ("reader-machine", "Second critique."),
        ):
            snapshot = self._turn(
                session_id, snapshot, participant_id, markdown
            )
        before = self._read(snapshot)
        reopened = bs.SessionStore(os.path.join(self.root, "state"))
        after = self._read(reopened.read(session_id))

        self.assertEqual(before, after)
        self.assertEqual(
            self._headings(after),
            [
                "Opening",
                "Discussion turn — Round 1 — Initial Position",
                "Discussion turn — Round 1 — Contrary Position",
                "Discussion turn — Round 1 — Contrary Position 2",
            ],
        )
        for markdown in ("Lead proposal.", "First critique.", "Second critique."):
            self.assertEqual(after.count(markdown), 1)

        fallback = self._create(
            "same-family", roster=participants(same_family=True)
        )
        fallback = self._initialize("same-family", fallback)
        fallback = self._turn(
            "same-family", fallback, "lead-machine", "Same-family lead."
        )
        self.assertIn(
            "Discussion turn — Round 1 — Initial Position",
            self._read(fallback),
        )

    def test_renderer_changes_do_not_rewrite_accepted_entries(self):
        session_id = "format-upgrade"
        snapshot = self._initialize(session_id, self._create(session_id))
        snapshot = self._turn(
            session_id, snapshot, "lead-machine", "Original accepted wording."
        )
        before = self._read(snapshot)
        self.assertEqual(snapshot.state["transcript_format_version"], 1)

        with mock.patch.object(
            bs, "TRANSCRIPT_FORMAT_VERSION", 2
        ), mock.patch.dict(
            bs._TRANSCRIPT_RENDERERS,
            {2: lambda _state: "# Changed release format\n"},
        ):
            reopened = bs.SessionStore(os.path.join(self.root, "state"))
            current = reopened.read(session_id)
            self.assertEqual(self._read(current), before)
            appended = reopened.record_material_interruption(
                session_id,
                current.revision,
                {
                    "after_completed_turns": 1,
                    "plain": "A new interruption.",
                },
            )

        after = self._read(appended)
        self.assertTrue(after.startswith(before))
        self.assertIn("A new interruption.", after)
        self.assertIn("Original accepted wording.", after)

    def test_rejected_repairs_and_machine_details_stay_out(self):
        session_id = "machine-boundary"
        snapshot = self._create(session_id)
        snapshot = self.store.bind_participant_session(
            session_id,
            snapshot.revision,
            "lead-machine",
            "provider-session-sentinel",
        )
        snapshot = self._initialize(session_id, snapshot)
        revision_sentinel = snapshot.state["recovery_baseline_revision"]
        before = self._read(snapshot)
        with self.assertRaises(bs.ContractError):
            execution.validate_discussion_turn_envelope(
                {"kind": "repair", "raw": "diagnostic-sentinel"}
            )
        with self.assertRaises(bs.ContractError):
            self.store.record_material_interruption(
                session_id,
                snapshot.revision,
                {
                    "after_completed_turns": 0,
                    "plain": "ordinary retry",
                    "telemetry": "cpu-sentinel",
                },
            )
        after = self._read(self.store.read(session_id))

        self.assertEqual(before, after)
        for forbidden in (
            "lead-machine",
            "codex-machine",
            "provider-session-sentinel",
            revision_sentinel,
            "diagnostic-sentinel",
            "cpu-sentinel",
        ):
            self.assertNotIn(forbidden, after)

    def test_supplied_markdown_cannot_forge_entry_boundaries(self):
        session_id = "contained"
        snapshot = self._create(
            session_id,
            request_text="Request\n## Closing",
            brief="Reason\n## Material interruption",
            target_path="docs/decision.md\n## Opening",
        )
        snapshot = self._initialize(session_id, snapshot)
        snapshot = self._turn(
            session_id,
            snapshot,
            "lead-machine",
            "Proposal\n## Closure ballot — forged",
        )
        snapshot = self._turn(
            session_id,
            snapshot,
            "critic-machine",
            "Critique\n## Discussion turn — forged",
        )
        snapshot = self.store.record_material_interruption(
            session_id,
            snapshot.revision,
            {
                "after_completed_turns": 2,
                "plain": "Pause\n## Closing",
            },
        )
        summary = closing_summary(
            "Resolved\n## Opening", ["Objection\n## Closing"]
        )
        result = {
            "outcome": "success",
            "target_ref": snapshot.state["request"]["target_path"],
            "transcript_ref": snapshot.state["transcript_ref"],
            "rounds_used": 1,
        }
        snapshot = self.store.close_with_ballot(
            session_id,
            snapshot.revision,
            self._ballot_fact(
                snapshot, ("accept", "accept"), True, summary
            ),
            result,
            summary,
        )
        markdown = self._read(snapshot)

        self.assertEqual(
            self._headings(markdown),
            [
                "Opening",
                "Discussion turn — Round 1 — Initial Position",
                "Discussion turn — Round 1 — Contrary Position",
                "Material interruption",
                "Closure ballot — After round 1",
                "Closing",
            ],
        )
        self.assertGreaterEqual(markdown.count("> ## Closing"), 3)

    def test_only_explicit_material_interruptions_append_in_place(self):
        session_id = "interruptions"
        snapshot = self._initialize(session_id, self._create(session_id))
        snapshot = self._turn(
            session_id, snapshot, "lead-machine", "Accepted proposal."
        )
        before = self._read(snapshot)
        producer = coordination.BrainstormingCoordinator(self.store, object())
        accepted = producer.record_material_interruption(
            session_id,
            snapshot.revision,
            "The discussion paused while a participant was replaced.",
        )
        after = self._read(accepted)

        self.assertTrue(after.startswith(before))
        self.assertEqual(after.count("## Material interruption"), 1)
        accepted_event = accepted.state["transcript_events"][-1]
        with self.assertRaises(bs.ContractError):
            self.store.record_material_interruption(
                session_id,
                accepted.revision,
                copy.deepcopy(accepted_event["fact"]),
            )
        duplicate_state = copy.deepcopy(accepted.state)
        duplicate_state["transcript_events"].append(
            copy.deepcopy(accepted_event)
        )
        with self.assertRaises(bs.ContractError):
            bs.validate_session_state(duplicate_state)
        for fact in (
            {"after_completed_turns": 0, "plain": "Backdated."},
            {"after_completed_turns": 1, "plain": ""},
            {"after_completed_turns": 1, "plain": "Retry.", "extra": True},
        ):
            with self.assertRaises(
                (bs.ContractError, bs.HistoryRewriteError)
            ):
                self.store.record_material_interruption(
                    session_id, accepted.revision, fact
                )
        with self.assertRaises(bs.RevisionConflict):
            self.store.record_material_interruption(
                session_id,
                snapshot.revision,
                {"after_completed_turns": 1, "plain": "Stale retry."},
            )
        self.assertEqual(after, self._read(self.store.read(session_id)))

    def test_closure_ballots_render_every_vote_and_failed_attempt_in_order(self):
        session_id = "ballots"
        snapshot = self._create(session_id)
        snapshot = self._initialize(session_id, snapshot)
        for participant_id, markdown in (
            ("lead-machine", "First proposal."),
            ("critic-machine", "First objection."),
        ):
            snapshot = self._turn(
                session_id, snapshot, participant_id, markdown
            )
        first_revision = snapshot.state["accepted_target_revision"]
        snapshot = self._ballot(
            session_id, snapshot, ("accept", "object"), False
        )
        accepted_ballot = snapshot.state["transcript_events"][-1]
        with self.assertRaises((bs.ContractError, bs.HistoryRewriteError)):
            self.store.record_closure_ballot(
                session_id,
                snapshot.revision,
                copy.deepcopy(accepted_ballot["fact"]),
            )
        duplicate_state = copy.deepcopy(snapshot.state)
        duplicate_state["transcript_events"].append(
            copy.deepcopy(accepted_ballot)
        )
        with self.assertRaises(bs.ContractError):
            bs.validate_session_state(duplicate_state)
        snapshot = self.store.record_material_interruption(
            session_id,
            snapshot.revision,
            {
                "after_completed_turns": 2,
                "plain": "The failed ballot returned the group to discussion.",
            },
        )
        for participant_id, markdown in (
            ("lead-machine", "Revised proposal."),
            ("critic-machine", "Objection resolved."),
        ):
            snapshot = self._turn(
                session_id, snapshot, participant_id, markdown
            )
        second_revision = snapshot.state["accepted_target_revision"]
        snapshot = self._terminal_ballot(
            session_id,
            snapshot,
            ("accept", "accept"),
            True,
            "Agreement was reached.",
        )
        markdown = self._read(snapshot)

        self.assertEqual(markdown.count("## Closure ballot"), 2)
        self.assertLess(
            markdown.index("did not approve closure"),
            markdown.index("Revised proposal."),
        )
        self.assertIn("This ballot approved closure.", markdown)
        self.assertEqual(markdown.count("**Initial Position:** `accept`"), 2)
        self.assertEqual(markdown.count("**Contrary Position:**"), 2)
        self.assertNotIn("lead-machine", markdown)
        self.assertNotIn(first_revision, markdown)
        self.assertNotIn(second_revision, markdown)

        malformed = {
            "after_completed_rounds": 2,
            "target_revision": second_revision,
            "votes": [
                {"participant_id": "lead-machine", "vote": "accept"}
            ],
            "approved": True,
        }
        with self.assertRaises(
            (bs.ContractError, bs.IllegalTransition)
        ):
            self.store.record_closure_ballot(
                session_id, snapshot.revision, malformed
            )

    def test_next_turn_prompt_points_to_chat_with_prior_session_history(self):
        session_id = "prompt-history"
        snapshot = self._initialize(
            session_id, self._create(session_id, max_rounds=2)
        )
        snapshot = self._turn(
            session_id, snapshot, "lead-machine", "Initial proposal."
        )
        snapshot = self._turn(
            session_id, snapshot, "critic-machine", "Initial objection."
        )
        snapshot = self._ballot(
            session_id, snapshot, ("accept", "object"), False
        )
        snapshot = self.store.record_material_interruption(
            session_id,
            snapshot.revision,
            {
                "after_completed_turns": 2,
                "plain": "Supervision materially paused the discussion.",
            },
        )
        target_revision = self.store.read_target_revision(
            session_id, snapshot.state["accepted_target_revision"]
        )

        prompt = coordination.build_turn_prompt(
            snapshot.state,
            snapshot.state["run_config"]["participants"][0],
            2,
            target_revision,
        )

        self.assertIn(snapshot.state["transcript_ref"], prompt)
        self.assertNotIn("Earlier accepted session transcript", prompt)
        self.assertNotIn("Initial objection.", prompt)
        with open(
            snapshot.state["transcript_ref"], encoding="utf-8"
        ) as handle:
            transcript = handle.read()
        self.assertLess(
            transcript.index("Initial objection."),
            transcript.index("Closure ballot — After round 1"),
        )
        self.assertLess(
            transcript.index("Closure ballot — After round 1"),
            transcript.index("Supervision materially paused the discussion."),
        )

    def test_final_round_failed_ballot_is_not_rendered_as_resumable(self):
        session_id = "final-ballot"
        snapshot = self._initialize(
            session_id, self._create(session_id, max_rounds=1)
        )
        snapshot = self._turn(
            session_id, snapshot, "lead-machine", "Final proposal."
        )
        snapshot = self._turn(
            session_id, snapshot, "critic-machine", "Final objection."
        )
        snapshot = self._terminal_ballot(
            session_id,
            snapshot,
            ("accept", "object"),
            False,
            "The final ballot did not reach agreement.",
        )

        markdown = self._read(snapshot)
        self.assertNotIn("discussion could continue", markdown)
        self.assertIn(
            "No complete discussion round remained within the configured "
            "limit.",
            markdown,
        )

    def test_terminal_closing_is_complete_even_before_first_turn(self):
        success_id = "closing-success"
        success = self._initialize(success_id, self._create(success_id))
        success = self._turn(
            success_id, success, "lead-machine", "Proposal."
        )
        success = self._turn(
            success_id, success, "critic-machine", "Accepted."
        )
        success = self._terminal(
            success_id, success, "success", "Everyone agreed."
        )

        failure_id = "closing-failure"
        failure = self._initialize(failure_id, self._create(failure_id))
        failure = self._turn(
            failure_id, failure, "lead-machine", "Unfinished proposal."
        )
        failure = self._terminal(
            failure_id, failure, "failure", "The group did not converge."
        )

        zero_id = "closing-zero"
        zero = self._create(zero_id, status="created")
        zero = self._terminal(
            zero_id, zero, "failure", "No participant completed a turn."
        )

        for snapshot, expected in (
            (success, "Agreement was reached."),
            (failure, "The target was left unfinished."),
            (zero, "No participant completed a turn."),
        ):
            markdown = self._read(snapshot)
            self.assertEqual(markdown.count("## Closing"), 1)
            self.assertEqual(self._headings(markdown)[-1], "Closing")
            self.assertIn(expected, markdown)
            for field in (
                "Affected parties",
                "Realistic damage",
                "Proportionality",
                "Escalation evidence",
                "Unresolved objections",
            ):
                self.assertIn(field, markdown)

        invalid = self._create("invalid-closing", status="created")
        result = {
            "outcome": "failure",
            "target_ref": invalid.state["request"]["target_path"],
            "transcript_ref": invalid.state["transcript_ref"],
            "rounds_used": 0,
            "reason": "Stopped.",
        }
        for summary in (
            None,
            dict(closing_summary("Stopped."), extra=True),
            closing_summary("Different reason."),
        ):
            with self.assertRaises(bs.ContractError):
                bs.transition_session(
                    invalid.state, "failure", result, summary
                )
        wrong_ref = copy.deepcopy(result)
        wrong_ref["transcript_ref"] = "/other/chat.md"
        with self.assertRaises(bs.ContractError):
            bs.transition_session(
                invalid.state,
                "failure",
                wrong_ref,
                closing_summary("Stopped."),
            )

    def test_restart_repairs_projection_without_rewriting_prefix(self):
        session_id = "repair"
        snapshot = self._initialize(session_id, self._create(session_id))
        snapshot = self._turn(
            session_id, snapshot, "lead-machine", "Accepted before failure."
        )
        snapshot = self._turn(
            session_id, snapshot, "critic-machine", "Accepted response."
        )
        snapshot = self.store.record_material_interruption(
            session_id,
            snapshot.revision,
            {
                "after_completed_turns": 2,
                "plain": "A material pause was recorded.",
            },
        )
        snapshot = self._ballot(
            session_id, snapshot, ("accept", "object"), False
        )
        before = self._read(snapshot)
        with mock.patch(
            "orchestrator.brainstorming.os.replace",
            side_effect=OSError("simulated atomic replace failure"),
        ):
            with self.assertRaises(OSError):
                bs._atomic_replace_utf8(
                    snapshot.state["transcript_ref"], before + "partial"
                )
        self.assertEqual(before, self._read(snapshot))
        original = bs._atomic_replace_utf8
        def fail_final_publication(path, content):
            if "\n## Closing\n" in content:
                raise OSError("simulated transcript publication failure")
            return original(path, content)

        with mock.patch(
            "orchestrator.brainstorming._atomic_replace_utf8",
            side_effect=fail_final_publication,
        ):
            with self.assertRaises(OSError):
                self.store.transition(
                    session_id,
                    snapshot.revision,
                    "failure",
                    {
                        "outcome": "failure",
                        "target_ref": snapshot.state["request"]["target_path"],
                        "transcript_ref": snapshot.state["transcript_ref"],
                        "rounds_used": 1,
                        "reason": "The discussion stopped after the ballot.",
                    },
                    closing_summary(
                        "The discussion stopped after the ballot."
                    ),
                )
        with open(snapshot.state["transcript_ref"], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)

        reopened = bs.SessionStore(os.path.join(self.root, "state"))
        repaired = self._read(reopened.read(session_id))
        self.assertTrue(repaired.startswith(before))
        self.assertIn("A material pause was recorded.", repaired)
        self.assertIn("Closure ballot", repaired)
        self.assertEqual(self._headings(repaired)[-1], "Closing")

    def test_stale_writer_cannot_duplicate_or_publish_losing_transcript(self):
        session_id = "concurrent"
        snapshot = self._initialize(session_id, self._create(session_id))
        second_store = bs.SessionStore(os.path.join(self.root, "state"))
        barrier = threading.Barrier(2)

        def append(store, plain):
            barrier.wait()
            try:
                return (
                    "ok",
                    store.record_material_interruption(
                        session_id,
                        snapshot.revision,
                        {"after_completed_turns": 0, "plain": plain},
                    ),
                )
            except bs.RevisionConflict as exc:
                return ("stale", exc.current)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    lambda args: append(*args),
                    (
                        (self.store, "First candidate."),
                        (second_store, "Second candidate."),
                    ),
                )
            )
        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 1)
        self.assertEqual([kind for kind, _ in outcomes].count("stale"), 1)
        durable = self.store.read(session_id)
        markdown = self._read(durable)
        self.assertEqual(markdown.count("## Material interruption"), 1)
        self.assertEqual(
            sum(
                candidate in markdown
                for candidate in ("First candidate.", "Second candidate.")
            ),
            1,
        )

    def test_transcript_isolated_from_target_and_current_consumers(self):
        session_id = "target-alias"
        snapshot = self._create(session_id)
        transcript = snapshot.state["transcript_ref"]
        target = os.path.join(
            snapshot.state["request"]["workspace_path"],
            snapshot.state["request"]["target_path"],
        )
        os.link(transcript, target)

        class RecordingExecution:
            def __init__(self):
                self.calls = []

            def exchange_quiescent(self, *args):
                self.calls.append(args)
                raise AssertionError("participant must not run")

        participant_execution = RecordingExecution()
        subject = coordination.BrainstormingCoordinator(
            self.store, participant_execution
        )
        before = self._read(snapshot)
        with self.assertRaises(coordination.CoordinationRejected):
            subject.run_next_turn(session_id, object())
        self.assertEqual(participant_execution.calls, [])
        self.assertEqual(before, self._read(self.store.read(session_id)))
        self.assertTrue(os.path.samefile(transcript, target))

        victim = self._create("other-session")
        victim_before = self._read(victim)
        with self.assertRaises(bs.ContractError):
            self._create(
                "cross-session-alias",
                target_path=victim.state["transcript_ref"],
            )
        self.assertEqual(
            victim_before, self._read(self.store.read("other-session"))
        )

        hardlink_attacker = self._create("cross-session-hardlink")
        hardlink_target = os.path.join(
            hardlink_attacker.state["request"]["workspace_path"],
            hardlink_attacker.state["request"]["target_path"],
        )
        os.link(victim.state["transcript_ref"], hardlink_target)
        with self.assertRaises(coordination.CoordinationRejected):
            subject.prepare("cross-session-hardlink")
        self.assertEqual(
            victim_before, self._read(self.store.read("other-session"))
        )

    def test_creation_rejects_own_transcript_target_before_publication(self):
        session_id = "pre-publication-alias"
        transcript = self.store.transcript_ref(session_id)
        os.makedirs(os.path.dirname(transcript))
        with open(transcript, "wb") as handle:
            handle.write(b"operator target bytes")
        roster = participants()
        request = {
            "workspace_path": self.root,
            "target_path": transcript,
            "request": "Change this target if the discussion supports it.",
            "context": {"brief": "Protect the existing target."},
            "max_rounds": 1,
        }

        with self.assertRaises(bs.ContractError):
            self.store.create(
                session_id, request, run_config(roster), roster
            )

        with open(transcript, "rb") as handle:
            self.assertEqual(handle.read(), b"operator target bytes")
        self.assertFalse(os.path.exists(transcript + ".lock"))
        self.assertIsNone(self.store.read(session_id))

    def test_creation_rejects_case_alias_before_publication(self):
        session_id = "pre-publication-case-alias"
        transcript = self.store.transcript_ref(session_id)
        transcript_root = self.store._transcript_root
        alias_root = transcript_root.swapcase()
        target = alias_root + transcript[len(transcript_root) :]
        roster = participants()
        request = {
            "workspace_path": self.root,
            "target_path": target,
            "request": "Change this target if the discussion supports it.",
            "context": {"brief": "Protect the target authority."},
            "max_rounds": 1,
        }

        case_behavior = (
            contextlib.nullcontext()
            if bs._filesystem_ignores_case(transcript_root)
            else mock.patch.object(
                bs, "_filesystem_ignores_case", return_value=True
            )
        )
        with case_behavior:
            with self.assertRaises(bs.ContractError):
                self.store.create(
                    session_id, request, run_config(roster), roster
                )

        self.assertFalse(os.path.exists(transcript))
        self.assertFalse(os.path.exists(transcript + ".lock"))
        self.assertIsNone(self.store.read(session_id))

    def test_creation_rejects_unicode_state_alias_before_publication(self):
        store = bs.SessionStore(
            self.root, filename="Café-brainstorming-state.json"
        )
        target = unicodedata.normalize("NFD", store.path)
        self.assertNotEqual(store.path, target)
        roster = participants()
        request = {
            "workspace_path": self.root,
            "target_path": target,
            "request": "Change this target if the discussion supports it.",
            "context": {"brief": "Protect durable session state."},
            "max_rounds": 1,
        }

        with self.assertRaises(bs.ContractError):
            store.create(
                "unicode-state-alias", request, run_config(roster), roster
            )

        self.assertFalse(os.path.exists(store.path))
        self.assertFalse(os.path.exists(target))
        self.assertFalse(os.path.exists(store._transcript_root))

    def test_creation_rejects_unicode_alias_before_publication(self):
        unicode_root = os.path.join(self.root, "Café")
        store = bs.SessionStore(os.path.join(unicode_root, "state"))
        session_id = "pre-publication-unicode-alias"
        transcript = store.transcript_ref(session_id)
        target = unicodedata.normalize("NFD", transcript)
        self.assertNotEqual(transcript, target)
        roster = participants()
        request = {
            "workspace_path": self.root,
            "target_path": target,
            "request": "Change this target if the discussion supports it.",
            "context": {"brief": "Protect the target authority."},
            "max_rounds": 1,
        }

        with self.assertRaises(bs.ContractError):
            store.create(
                session_id, request, run_config(roster), roster
            )

        self.assertFalse(os.path.exists(transcript))
        self.assertFalse(os.path.exists(transcript + ".lock"))
        self.assertIsNone(store.read(session_id))

    def test_creation_rejects_unresolved_unicode_alias_without_probe_write(
        self,
    ):
        unicode_root = os.path.join(self.root, "Café")
        store = bs.SessionStore(os.path.join(unicode_root, "state"))
        session_id = "new-unicode-component-alias"
        transcript = store.transcript_ref(session_id)
        target = unicodedata.normalize("NFD", transcript)
        roster = participants()
        request = {
            "workspace_path": self.root,
            "target_path": target,
            "request": "Change this target if the discussion supports it.",
            "context": {"brief": "Protect the target authority."},
            "max_rounds": 1,
        }

        with mock.patch.object(
            bs.tempfile,
            "mkstemp",
            side_effect=AssertionError("alias validation must be read-only"),
        ):
            with self.assertRaises(bs.ContractError):
                store.create(
                    session_id, request, run_config(roster), roster
                )

        self.assertFalse(os.path.exists(unicode_root))
        self.assertFalse(os.path.exists(transcript))
        self.assertFalse(os.path.exists(transcript + ".lock"))

    def test_creation_rejects_target_ancestor_without_creating_it(self):
        target = os.path.join(self.root, "operator-target")
        store = bs.SessionStore(
            os.path.join(target, "brainstorming-authority")
        )
        session_id = "target-contains-authority"
        roster = participants()
        request = {
            "workspace_path": self.root,
            "target_path": target,
            "request": "Change this target if the discussion supports it.",
            "context": {"brief": "Protect the target from non-lead creation."},
            "max_rounds": 1,
        }

        with self.assertRaises(bs.ContractError):
            store.create(
                session_id, request, run_config(roster), roster
            )

        self.assertFalse(os.path.exists(target))
        self.assertFalse(os.path.exists(store.path))

    def test_case_sensitivity_probe_matches_the_filesystem(self):
        probe = os.path.join(self.root, "CaseProbe")
        os.makedirs(probe)
        alias = os.path.join(self.root, "cASEpROBE")
        expected = os.path.exists(alias) and os.path.samefile(probe, alias)

        self.assertEqual(
            bs._filesystem_ignores_case(os.path.join(probe, "missing")),
            expected,
        )

    def test_unicode_equivalent_unresolved_tails_overlap_conservatively(self):
        composed = ("Café", "chat.md")
        decomposed = tuple(
            unicodedata.normalize("NFD", component)
            for component in composed
        )
        store_path = os.path.join(self.root, "Café-state.json")
        target_path = unicodedata.normalize("NFD", store_path)
        with mock.patch.object(
            bs, "_filesystem_ignores_case", return_value=False
        ):
            self.assertTrue(
                bs._tails_overlap_on_filesystem(
                    composed, decomposed, self.root
                )
            )
            self.assertTrue(
                bs._target_overlaps_state_storage(store_path, target_path)
            )

    def test_unicode_alias_rejection_survives_metadata_probe_error(self):
        store = bs.SessionStore(
            self.root, filename="Café-error-state.json"
        )
        target = unicodedata.normalize("NFD", store.path)
        roster = participants()
        request = {
            "workspace_path": self.root,
            "target_path": target,
            "request": "Change this target if the discussion supports it.",
            "context": {"brief": "Protect durable session state."},
            "max_rounds": 1,
        }
        real_samefile = os.path.samefile

        def samefile(first, second):
            if os.path.abspath(first) == os.path.abspath(second):
                return real_samefile(first, second)
            raise OSError("metadata unavailable")

        with mock.patch(
            "orchestrator.brainstorming.os.path.samefile",
            side_effect=samefile,
        ):
            with self.assertRaises(bs.ContractError):
                store.create(
                    "unicode-metadata-error",
                    request,
                    run_config(roster),
                    roster,
                )

        self.assertFalse(os.path.exists(store.path))
        self.assertFalse(os.path.exists(target))

    def test_creation_rejects_parent_case_alias_across_mount_boundary(self):
        mount_root = os.path.join(self.root, "CaseSensitiveMount")
        os.makedirs(mount_root)
        store = bs.SessionStore(mount_root)
        parent = os.path.dirname(mount_root)
        parent_alias = os.path.join(
            os.path.dirname(parent), os.path.basename(parent).swapcase()
        )
        alias_mount_root = os.path.join(
            parent_alias, os.path.basename(mount_root)
        )
        target = os.path.join(
            alias_mount_root,
            os.path.basename(store._transcript_root),
            "other",
            "chat.md",
        )
        workspace = os.path.join(mount_root, "workspace")
        os.makedirs(workspace)
        roster = participants()
        request = {
            "workspace_path": workspace,
            "target_path": target,
            "request": "Use transcript storage as the target if allowed.",
            "context": {"brief": "Keep transcript storage isolated."},
            "max_rounds": 1,
        }
        real_lexists = os.path.lexists
        real_samefile = os.path.samefile
        real_ismount = os.path.ismount
        real_realpath = os.path.realpath

        def translate_alias(path):
            absolute = os.path.abspath(path)
            try:
                within_alias = (
                    os.path.commonpath((absolute, alias_mount_root))
                    == alias_mount_root
                )
            except ValueError:
                within_alias = False
            if within_alias:
                return mount_root + absolute[len(alias_mount_root) :]
            return absolute

        def lexists(path):
            return real_lexists(translate_alias(path))

        def samefile(first, second):
            return real_samefile(
                translate_alias(first), translate_alias(second)
            )

        def realpath(path):
            absolute = os.path.abspath(path)
            for root in (mount_root, alias_mount_root):
                try:
                    if os.path.commonpath((absolute, root)) == root:
                        return absolute
                except ValueError:
                    pass
            return real_realpath(path)

        with mock.patch(
            "orchestrator.brainstorming.os.path.lexists",
            side_effect=lexists,
        ), mock.patch(
            "orchestrator.brainstorming.os.path.ismount",
            side_effect=lambda path: (
                translate_alias(path) == mount_root
                or real_ismount(translate_alias(path))
            ),
        ), mock.patch(
            "orchestrator.brainstorming.os.path.samefile",
            side_effect=samefile,
        ), mock.patch(
            "orchestrator.brainstorming.os.path.realpath",
            side_effect=realpath,
        ):
            with self.assertRaises(bs.ContractError):
                store.create(
                    "parent-case-alias",
                    request,
                    run_config(roster),
                    roster,
                )

        self.assertFalse(
            os.path.exists(store.transcript_ref("parent-case-alias"))
        )
        self.assertIsNone(store.read("parent-case-alias"))

    def test_mount_root_case_alias_is_rejected_without_probe_write(self):
        mount_root = os.path.join(self.root, "CaseSensitiveMount")
        os.makedirs(mount_root)
        store = bs.SessionStore(mount_root)
        target_root = os.path.join(
            mount_root, os.path.basename(store._transcript_root).swapcase()
        )
        target = os.path.join(target_root, "other", "chat.md")
        workspace = os.path.join(mount_root, "workspace")
        os.makedirs(workspace)
        roster = participants()
        request = {
            "workspace_path": workspace,
            "target_path": target,
            "request": "Use this distinct target.",
            "context": {"brief": "Keep transcript storage isolated."},
            "max_rounds": 1,
        }
        real_samefile = os.path.samefile
        real_ismount = os.path.ismount
        real_realpath = os.path.realpath
        parent_alias = os.path.join(
            os.path.dirname(mount_root),
            os.path.basename(mount_root).swapcase(),
        )

        def samefile(first, second):
            first = os.path.abspath(first)
            second = os.path.abspath(second)
            if {first, second} == {mount_root, parent_alias}:
                return True
            if (
                os.path.commonpath((first, mount_root)) == mount_root
                and os.path.commonpath((second, mount_root)) == mount_root
                and first != second
            ):
                raise FileNotFoundError
            return real_samefile(first, second)

        def realpath(path):
            absolute = os.path.abspath(path)
            if os.path.commonpath((absolute, mount_root)) == mount_root:
                return absolute
            return real_realpath(path)

        with mock.patch(
            "orchestrator.brainstorming.os.path.ismount",
            side_effect=lambda path: (
                os.path.abspath(path) == mount_root
                or real_ismount(path)
            ),
        ), mock.patch(
            "orchestrator.brainstorming.os.path.samefile",
            side_effect=samefile,
        ), mock.patch(
            "orchestrator.brainstorming.os.path.realpath",
            side_effect=realpath,
        ), mock.patch.object(
            bs.tempfile,
            "mkstemp",
            side_effect=AssertionError("alias validation must be read-only"),
        ):
            with self.assertRaises(bs.ContractError):
                store.create(
                    "mount-boundary", request, run_config(roster), roster
                )

        self.assertIsNone(store.read("mount-boundary"))
        self.assertFalse(
            os.path.exists(store.transcript_ref("mount-boundary"))
        )
        self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
