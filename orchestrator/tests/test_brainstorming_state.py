"""Focused contract and persistence checks for brainstorming Slice 01."""

import copy
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from orchestrator import brainstorming as bs


def request(source_payload=None, include_optional=True):
    context = {"brief": "Resolve one bounded design request."}
    if include_optional:
        context["references"] = ["docs/current.md", "https://example.test/fact"]
        context["source_payload"] = source_payload
    return {
        "workspace_path": "/workspace",
        "target_path": "docs/decision.md",
        "request": "Choose the compatible option to adopt.",
        "context": context,
        "max_rounds": 2,
    }


def cross_family_participants():
    return [
        {
            "id": "editor",
            "role": "initial_position",
            "delivery": "llm",
            "executor_ref": "codex-primary",
            "model_family": "codex",
        },
        {
            "id": "critic",
            "role": "contrary_position",
            "delivery": "llm",
            "executor_ref": "claude-reviewer",
            "model_family": "claude",
        },
    ]


def same_family_participants():
    participants = cross_family_participants()
    participants[1]["executor_ref"] = "codex-secondary"
    participants[1]["model_family"] = "codex"
    return participants


def external_participants():
    return [
        copy.deepcopy(cross_family_participants()[0]),
        copy.deepcopy(cross_family_participants()[1]),
        {
            "id": "dante",
            "role": "common_sense",
            "delivery": "external",
            "external_ref": "external-dante",
        },
    ]


def run_config(participants=None, policy="unanimity",
               eligible_participants=None):
    participants = (
        cross_family_participants() if participants is None else participants
    )
    eligible_participants = (
        participants
        if eligible_participants is None
        else eligible_participants
    )
    return bs.resolve_run_config(
        participants, policy, eligible_participants
    )


def success_result(transcript_ref, rounds_used=0):
    return {
        "outcome": "success",
        "target_ref": "docs/decision.md",
        "transcript_ref": transcript_ref,
        "rounds_used": rounds_used,
    }


def failure_result(transcript_ref, rounds_used=0):
    return {
        "outcome": "failure",
        "target_ref": "docs/decision.md",
        "transcript_ref": transcript_ref,
        "rounds_used": rounds_used,
        "reason": "The bounded discussion did not reach agreement.",
    }


def closing_summary(reason="The bounded discussion did not reach agreement."):
    return {
        "reason": reason,
        "unresolved_objections": [],
        "affected_parties": "Only the people using the requested target.",
        "damage_altitude": "A bounded and reversible design consequence.",
        "proportionality": "The bounded discussion matched the decision.",
        "escalation_evidence": None,
        "open_questions": [],
    }


class BrainstormingStateTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="brainstorming-state-")
        self.root = self._tmp.name
        self.store = bs.SessionStore(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _successful_closure(self, session_id, running, reason):
        target = bs.make_target_revision(True, b"accepted target", 0o644)
        snapshot = self.store.initialize_coordination(
            session_id, running.revision, target
        )
        for participant in snapshot.state["run_config"]["participants"]:
            snapshot = self.store.record_completed_turn(
                session_id,
                snapshot.revision,
                participant["id"],
                "Accepted contribution.",
                target,
            )
        votes = [
            {"participant_id": participant["id"], "vote": "accept"}
            for participant in bs.closure_voters(
                snapshot.state["run_config"]
            )
        ]
        ballot = {
            "after_completed_rounds": 1,
            "target_revision": snapshot.state["accepted_target_revision"],
            "votes": votes,
            "approved": True,
            "closing_summary": closing_summary(reason),
        }
        return self.store.close_with_ballot(
            session_id,
            snapshot.revision,
            ballot,
            success_result(snapshot.state["transcript_ref"], rounds_used=1),
            closing_summary(reason),
        )

    def _external_turn_ready(self, session_id):
        roster = external_participants()
        created = self.store.create(
            session_id,
            request(),
            run_config(roster, eligible_participants=roster),
            roster,
        )
        running = self.store.transition(
            session_id, created.revision, "running"
        )
        target = bs.make_target_revision(True, b"accepted target", 0o644)
        initialized = self.store.initialize_coordination(
            session_id, running.revision, target
        )
        ready = self.store.record_completed_turn(
            session_id,
            initialized.revision,
            "editor",
            "The technical lead presents the case.",
            target,
        )
        ready = self.store.record_completed_turn(
            session_id,
            ready.revision,
            "critic",
            "The contrary position challenges the case.",
            target,
        )
        req = ready.state["request"]
        intervention = {
            "token": "external-token-1",
            "participant_id": "dante",
            "action_kind": "discussion_turn",
            "completed_turn_count": 2,
            "round": 1,
            "target_revision": ready.state["accepted_target_revision"],
            "input": {
                "request": req["request"],
                "context": req["context"],
                "workspace_path": req["workspace_path"],
                "target_path": req["target_path"],
                "transcript_ref": ready.state["transcript_ref"],
            },
            "created_at": 100.0,
            "provider_attempt": 0,
            "provider_quiescent": True,
            "response": None,
        }
        return ready, intervention

    def test_external_intervention_is_published_for_the_exact_next_turn(self):
        _ready, intervention = self._external_turn_ready("external-publish")
        published = self.store.publish_external_intervention(
            "external-publish", intervention
        )
        self.assertEqual(published, intervention)
        self.assertEqual(
            self.store.read_external_intervention("external-publish"),
            intervention,
        )

    def test_external_intervention_accepts_a_late_durable_response(self):
        _ready, intervention = self._external_turn_ready("external-late")
        self.store.publish_external_intervention("external-late", intervention)
        reopened = bs.SessionStore(self.root)
        with mock.patch("orchestrator.brainstorming.time.time", return_value=900.0):
            answered = reopened.submit_external_intervention(
                "external-late",
                intervention["token"],
                {"markdown": "Dante accepts the ordinary residual risk."},
            )
        self.assertEqual(answered["response"], {
            "received_at": 900.0,
            "payload": {
                "markdown": "Dante accepts the ordinary residual risk."
            },
        })

    def test_external_intervention_rejects_a_duplicate_response(self):
        _ready, intervention = self._external_turn_ready("external-duplicate")
        self.store.publish_external_intervention(
            "external-duplicate", intervention
        )
        self.store.submit_external_intervention(
            "external-duplicate",
            intervention["token"],
            {"markdown": "Dante chooses the simple option."},
        )
        with self.assertRaises(bs.HistoryRewriteError):
            self.store.submit_external_intervention(
                "external-duplicate",
                intervention["token"],
                {"markdown": "A conflicting second answer."},
            )

    def test_terminal_transition_atomically_invalidates_external_response(self):
        ready, intervention = self._external_turn_ready("external-terminal")
        self.store.publish_external_intervention(
            "external-terminal", intervention
        )
        terminal = self.store.transition(
            "external-terminal",
            ready.revision,
            "failure",
            failure_result(ready.state["transcript_ref"]),
            closing_summary(),
        )

        self.assertEqual(terminal.state["status"], "failure")
        self.assertIsNone(
            self.store.read_external_intervention("external-terminal")
        )
        with self.assertRaises(bs.HistoryRewriteError):
            self.store.submit_external_intervention(
                "external-terminal",
                intervention["token"],
                {"markdown": "Too late."},
            )

    def test_unconfirmed_provider_attempt_cannot_be_claimed_or_answered(self):
        _ready, intervention = self._external_turn_ready("external-active")
        self.store.publish_external_intervention(
            "external-active", intervention
        )
        claimed = self.store.claim_external_intervention(
            "external-active", intervention["token"]
        )
        self.assertFalse(claimed["provider_quiescent"])
        with self.assertRaises(bs.HistoryRewriteError):
            self.store.claim_external_intervention(
                "external-active", intervention["token"]
            )
        with self.assertRaises(bs.HistoryRewriteError):
            self.store.submit_external_intervention(
                "external-active",
                intervention["token"],
                {"markdown": "Racing answer."},
            )

    def _assert_create_rejected(self, session_id, req=None, config=None):
        with self.assertRaises((bs.ContractError, ValueError)):
            self.store.create(
                session_id,
                request() if req is None else req,
                run_config() if config is None else config,
                cross_family_participants(),
            )
        self.assertIsNone(self.store.read(session_id))

    def test_request_and_context_contract(self):
        minimal = request(include_optional=False)
        created = self.store.create(
            "minimal", minimal, run_config(), cross_family_participants()
        )
        self.assertEqual(created.state["request"], minimal)

        full = request(
            {
                "finding": {"id": "F1", "facts": [True, 3, None]},
                "alternatives": ["keep", "change"],
            }
        )
        created = self.store.create(
            "full", full, run_config(), cross_family_participants()
        )
        self.assertEqual(created.state["request"], full)

        invalid = []
        for key in ("workspace_path", "target_path", "request", "context",
                    "max_rounds"):
            candidate = request()
            del candidate[key]
            invalid.append(candidate)
        for key in ("workspace_path", "target_path", "request"):
            for value in ("", "   ", 7):
                candidate = request()
                candidate[key] = value
                invalid.append(candidate)
        for value in (0, -1, True, 1.5, "2"):
            candidate = request()
            candidate["max_rounds"] = value
            invalid.append(candidate)

        for context in (
            {},
            {"brief": ""},
            {"brief": "ok", "references": "not-a-list"},
            {"brief": "ok", "references": None},
            {"brief": "ok", "references": [""]},
            {"brief": "ok", "references": [3]},
            {"brief": "ok", "source_payload": object()},
            {"brief": "ok", "unexpected": "field"},
        ):
            candidate = request()
            candidate["context"] = context
            invalid.append(candidate)
        for forbidden in ("answer_options", "problem_type", "domain_type"):
            candidate = request()
            candidate[forbidden] = []
            invalid.append(candidate)

        for index, candidate in enumerate(invalid):
            self._assert_create_rejected("invalid-%d" % index, req=candidate)

    def test_source_payload_round_trips_opaque(self):
        payload = {
            "status": "success",
            "closure_policy": "not-a-real-policy",
            "participants": [{"role": "initial_position"}],
            "finding": {"id": "F7", "evidence": [1, False, None]},
        }
        left = self.store.create(
            "opaque-a", request(payload), run_config(),
            cross_family_participants(),
        )
        right_payload = {"completely": ["different", {"nested": 9}]}
        right = self.store.create(
            "opaque-b", request(right_payload), run_config(),
            cross_family_participants(),
        )

        reopened = bs.SessionStore(self.root)
        self.assertEqual(
            reopened.read("opaque-a").state["request"]["context"]["source_payload"],
            payload,
        )
        self.assertEqual(left.state["run_config"], right.state["run_config"])
        self.assertEqual(left.state["status"], right.state["status"])
        self.assertEqual(left.state["history"], right.state["history"])

        left_done = self.store.transition(
            "opaque-a",
            left.revision,
            "failure",
            failure_result(left.state["transcript_ref"]),
            closing_summary(),
        )
        right_done = self.store.transition(
            "opaque-b",
            right.revision,
            "failure",
            failure_result(right.state["transcript_ref"]),
            closing_summary(),
        )
        self.assertEqual(left_done.state["status"], right_done.state["status"])
        self.assertNotEqual(
            left_done.state["result"]["transcript_ref"],
            right_done.state["result"]["transcript_ref"],
        )
        self.assertEqual(
            left_done.state["run_config"], right_done.state["run_config"]
        )

    def test_roster_and_policy_contract(self):
        different = run_config(cross_family_participants(), "unanimity")
        self.assertFalse(different["same_family_fallback"])
        self.assertEqual(
            [item["id"] for item in different["participants"]],
            ["editor", "critic"],
        )
        created = self.store.create(
            "different", request(), different, cross_family_participants()
        )
        self.assertEqual(
            bs.SessionStore(self.root).read("different").state["run_config"],
            different,
        )

        fallback = run_config(
            same_family_participants(), "majority"
        )
        self.assertTrue(fallback["same_family_fallback"])
        created = self.store.create(
            "fallback", request(), fallback, same_family_participants()
        )
        self.assertEqual(created.state["run_config"], fallback)

        eligible = same_family_participants()
        eligible.append({
            "id": "critic",
            "role": "contrary_position",
            "delivery": "llm",
            "executor_ref": "claude-reviewer",
            "model_family": "claude",
        })
        with self.assertRaises(bs.ContractError):
            run_config(
                same_family_participants(),
                "unanimity",
                eligible_participants=eligible,
            )
        with self.assertRaises(bs.ContractError):
            self.store.create(
                "avoidable-fallback", request(), fallback, eligible
            )
        self.assertIsNone(self.store.read("avoidable-fallback"))

        preferred_participants = [
            eligible[0],
            eligible[-1],
        ]
        preferred = run_config(
            preferred_participants,
            "unanimity",
            eligible_participants=eligible,
        )
        self.assertFalse(preferred["same_family_fallback"])
        preferred_session = self.store.create(
            "preferred-family", request(), preferred, eligible
        )
        self.assertFalse(
            preferred_session.state["run_config"]["same_family_fallback"]
        )

        invalid = []
        for missing in ("participants", "closure_policy",
                        "same_family_fallback"):
            candidate = copy.deepcopy(different)
            del candidate[missing]
            invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["extra"] = "caller"
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["participants"] = "not-a-list"
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["participants"] = []
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        del candidate["participants"][0]["executor_ref"]
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["participants"][0]["extra"] = True
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["participants"][1]["id"] = "editor"
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["participants"][1]["role"] = "lead"
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["participants"][0]["role"] = "interlocutor"
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["participants"][1]["role"] = "observer"
        invalid.append(candidate)
        for field in ("id", "executor_ref", "model_family"):
            candidate = copy.deepcopy(different)
            candidate["participants"][0][field] = ""
            invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["participants"][0]["model_family"] = []
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["closure_policy"] = "default"
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["same_family_fallback"] = True
        invalid.append(candidate)
        candidate = copy.deepcopy(fallback)
        candidate["same_family_fallback"] = False
        invalid.append(candidate)
        candidate = copy.deepcopy(different)
        candidate["same_family_fallback"] = 0
        invalid.append(candidate)

        for index, candidate in enumerate(invalid):
            self._assert_create_rejected(
                "bad-config-%d" % index, config=candidate
            )

    def test_session_contract_is_immutable(self):
        created = self.store.create(
            "fixed", request(), run_config(), cross_family_participants()
        )
        with open(self.store.path, "rb") as fh:
            durable_before = fh.read()

        mutations = []
        candidate = copy.deepcopy(created.state)
        candidate["request"]["request"] = "A different request"
        mutations.append(candidate)
        candidate = copy.deepcopy(created.state)
        candidate["request"]["context"]["source_payload"] = {"changed": True}
        mutations.append(candidate)
        candidate = copy.deepcopy(created.state)
        candidate["run_config"]["participants"].reverse()
        mutations.append(candidate)
        candidate = copy.deepcopy(created.state)
        candidate["run_config"]["participants"][0]["executor_ref"] = "other"
        mutations.append(candidate)
        candidate = copy.deepcopy(created.state)
        candidate["run_config"]["participants"][0]["model_family"] = "other"
        mutations.append(candidate)
        candidate = copy.deepcopy(created.state)
        candidate["run_config"]["closure_policy"] = (
            "majority"
        )
        mutations.append(candidate)
        candidate = copy.deepcopy(created.state)
        candidate["caller"] = "metadata-cannot-rewrite-state"
        mutations.append(candidate)

        for candidate in mutations:
            candidate["status"] = "running"
            candidate["history"].append({"status": "running"})
            with self.assertRaises(
                (bs.ContractError, bs.HistoryRewriteError)
            ):
                self.store.save("fixed", created.revision, candidate)
            self.assertEqual(self.store.read("fixed"), created)
            with open(self.store.path, "rb") as fh:
                self.assertEqual(fh.read(), durable_before)

        typed_request = request({"audit_value": 1})
        typed = self.store.create(
            "typed-evidence",
            typed_request,
            run_config(),
            cross_family_participants(),
        )
        with open(self.store.path, "rb") as fh:
            typed_durable_before = fh.read()
        candidate = copy.deepcopy(typed.state)
        candidate["request"]["context"]["source_payload"]["audit_value"] = True
        candidate["status"] = "running"
        candidate["history"].append({"status": "running"})
        with self.assertRaises(bs.HistoryRewriteError):
            self.store.save("typed-evidence", typed.revision, candidate)
        durable_value = self.store.read(
            "typed-evidence"
        ).state["request"]["context"]["source_payload"]["audit_value"]
        self.assertIs(type(durable_value), int)
        self.assertEqual(durable_value, 1)
        with open(self.store.path, "rb") as fh:
            self.assertEqual(fh.read(), typed_durable_before)

    def test_history_and_terminal_result_are_append_only(self):
        created = self.store.create(
            "terminal", request(), run_config(), cross_family_participants()
        )
        running = self.store.transition(
            "terminal", created.revision, "running"
        )
        terminal = self._successful_closure(
            "terminal",
            running,
            "The participants reached agreement.",
        )
        durable = self.store.read("terminal")

        rewrites = []
        candidate = copy.deepcopy(terminal.state)
        candidate["history"] = candidate["history"][:-1]
        candidate["status"] = "running"
        candidate.pop("result")
        rewrites.append(candidate)
        candidate = copy.deepcopy(terminal.state)
        candidate["history"][1]["status"] = "failure"
        candidate["history"][1]["result"] = failure_result(
            terminal.state["transcript_ref"]
        )
        rewrites.append(candidate)
        candidate = copy.deepcopy(terminal.state)
        candidate["result"]["rounds_used"] = 9
        candidate["history"][-1]["result"]["rounds_used"] = 9
        rewrites.append(candidate)

        for candidate in rewrites:
            with self.assertRaises(
                (bs.ContractError, bs.HistoryRewriteError,
                 bs.IllegalTransition)
            ):
                self.store.save("terminal", terminal.revision, candidate)
            self.assertEqual(self.store.read("terminal"), durable)

        with self.assertRaises(bs.IllegalTransition):
            self.store.transition(
                "terminal",
                terminal.revision,
                "failure",
                failure_result(terminal.state["transcript_ref"]),
                closing_summary(),
            )
        self.assertEqual(self.store.read("terminal"), durable)

    def test_atomic_persistence_and_stale_update_rejection(self):
        created = self.store.create(
            "atomic", request(), run_config(), cross_family_participants()
        )
        running_candidate = bs.transition_session(created.state, "running")
        failure_candidate = bs.transition_session(
            created.state,
            "failure",
            failure_result(created.state["transcript_ref"]),
            closing_summary(),
        )

        with open(self.store.path, "rb") as fh:
            before = fh.read()
        with mock.patch(
            "orchestrator.kvstore.os.replace",
            side_effect=OSError("simulated write failure"),
        ):
            with self.assertRaises(OSError):
                self.store.save(
                    "atomic", created.revision, running_candidate
                )
        with open(self.store.path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(self.store.read("atomic"), created)

        barrier = threading.Barrier(2)

        def commit(candidate):
            barrier.wait()
            try:
                return ("ok", self.store.save(
                    "atomic", created.revision, candidate
                ))
            except bs.RevisionConflict as exc:
                return ("stale", exc.current)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(
                commit, (running_candidate, failure_candidate)
            ))

        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 1)
        self.assertEqual([kind for kind, _ in outcomes].count("stale"), 1)
        durable = self.store.read("atomic")
        self.assertEqual(durable.revision, created.revision + 1)
        self.assertIn(
            durable.state, (running_candidate, failure_candidate)
        )
        with open(self.store.path, "r", encoding="utf-8") as fh:
            json.load(fh)

    def test_lifecycle_and_result_contract(self):
        created = self.store.create(
            "success", request(), run_config(), cross_family_participants()
        )
        self.assertNotIn("result", created.state)
        with self.assertRaises(bs.IllegalTransition):
            self.store.transition(
                "success",
                created.revision,
                "success",
                success_result(created.state["transcript_ref"]),
                closing_summary("Agreement was reached."),
            )
        with self.assertRaises(bs.ContractError):
            bs.transition_session(
                created.state,
                "running",
                success_result(created.state["transcript_ref"]),
            )

        running = self.store.transition(
            "success", created.revision, "running"
        )
        self.assertNotIn("result", running.state)
        for illegal in ("created", "running"):
            with self.assertRaises(bs.IllegalTransition):
                bs.transition_session(running.state, illegal)

        invalid_results = []
        candidate = success_result(running.state["transcript_ref"])
        candidate["outcome"] = "failure"
        invalid_results.append(candidate)
        candidate = success_result(running.state["transcript_ref"])
        candidate["target_ref"] = "docs/other.md"
        invalid_results.append(candidate)
        candidate = success_result(running.state["transcript_ref"])
        candidate["transcript_ref"] = ""
        invalid_results.append(candidate)
        candidate = success_result(running.state["transcript_ref"])
        candidate["rounds_used"] = -1
        invalid_results.append(candidate)
        candidate = success_result(running.state["transcript_ref"])
        candidate["rounds_used"] = True
        invalid_results.append(candidate)
        candidate = success_result(running.state["transcript_ref"])
        candidate["reason"] = "success does not carry a reason"
        invalid_results.append(candidate)
        candidate = success_result(running.state["transcript_ref"])
        candidate["caller_action"] = "continue"
        invalid_results.append(candidate)
        candidate = success_result(running.state["transcript_ref"])
        del candidate["transcript_ref"]
        invalid_results.append(candidate)

        for result in invalid_results:
            with self.assertRaises(bs.ContractError):
                bs.transition_session(
                    running.state,
                    "success",
                    result,
                    closing_summary("Agreement was reached."),
                )

        success = self._successful_closure(
            "success", running, "Agreement was reached."
        )
        self.assertEqual(success.state["status"], "success")
        self.assertEqual(success.state["result"]["outcome"], "success")
        self.assertEqual(
            success.state["result"]["target_ref"],
            success.state["request"]["target_path"],
        )
        self.assertEqual(success.state["result"]["rounds_used"], 1)
        self.assertNotIn("reason", success.state["result"])

        failed = self.store.create(
            "failure", request(), run_config(), cross_family_participants()
        )
        for result in (
            {key: value for key, value in failure_result(
                failed.state["transcript_ref"]
            ).items()
             if key != "reason"},
            dict(
                failure_result(failed.state["transcript_ref"]), reason=""
            ),
            dict(
                failure_result(failed.state["transcript_ref"]),
                extra="caller-action",
            ),
        ):
            with self.assertRaises(bs.ContractError):
                bs.transition_session(
                    failed.state, "failure", result, closing_summary()
                )
        failed = self.store.transition(
            "failure",
            failed.revision,
            "failure",
            failure_result(failed.state["transcript_ref"]),
            closing_summary(),
        )
        self.assertEqual(failed.state["status"], "failure")
        self.assertEqual(failed.state["result"]["outcome"], "failure")
        self.assertTrue(failed.state["result"]["reason"])
        self.assertEqual(failed.state["result"]["rounds_used"], 0)

    def test_brainstorming_state_is_independent(self):
        orchestrator_dir = os.path.join(self.root, ".orchestrator")
        os.makedirs(orchestrator_dir)
        ledger_path = os.path.join(orchestrator_dir, "state.json")
        ledger = b'{"schema_version":2,"events":[{"type":"existing"}]}\n'
        with open(ledger_path, "wb") as fh:
            fh.write(ledger)

        store = bs.SessionStore(orchestrator_dir)
        req = request({
            "milestone": "opaque-only",
            "slice": 7,
            "operator_route": "opaque-only",
        })
        created = store.create(
            "generic", req, run_config(), cross_family_participants()
        )
        store.transition("generic", created.revision, "running")
        with open(ledger_path, "rb") as fh:
            self.assertEqual(fh.read(), ledger)

        forbidden = {
            "milestone", "slice", "review", "seal", "continuation",
            "operator_route",
        }
        keys = set()

        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    keys.add(key)
                    if key != "source_payload":
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(store.read("generic").state)
        self.assertTrue(keys.isdisjoint(forbidden))


if __name__ == "__main__":
    unittest.main()
