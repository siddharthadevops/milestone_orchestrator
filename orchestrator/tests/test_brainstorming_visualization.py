"""Focused executable evidence for Brainstorming Slice 07."""
import os
import time
import unittest
from unittest import mock
from orchestrator import access
from orchestrator import brainstorming as bs
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import registry, service
from orchestrator.tests import test_brainstorming_api as api_tests
VIEW_KEYS = {
    "id", "caller", "status", "request", "process", "revision", "target",
    "participants", "same_family_fallback", "closure_policy",
    "closure_ballots", "round", "transcript_markdown", "result",
    "final_agreement",
    "activity", "work_duration_s", "in_flight", "retry",
    "external_intervention",
}
class BrainstormingVisualizationTest(unittest.TestCase):
    def setUp(self):
        self.api = api_tests.StandaloneBrainstormingApiTest("runTest")
        self.api.setUp()
    def tearDown(self):
        self.api.tearDown()
    def _create(self, name, content=b"initial", rounds=1, live=False):
        if content is not None:
            self.api._target(name, content)
        with mock.patch.object(
            lifecycle, "_launch_lifecycle_process", side_effect=self.api._sleeper_launcher
        ):
            status, body = self.api._request(
                "POST", "/api/brainstorming/sessions",
                self.api._payload(name, max_rounds=rounds)
            )
        self.assertEqual(status, 201, body)
        session_id = body["session"]["id"]
        if not live:
            self.api._stop_sleeper_record(session_id)
        return session_id, bs.SessionStore(lifecycle.state_directory(self.api.home))
    def _view(self, session_id, headers=None):
        status, body = self.api._request(
            "GET", "/api/brainstorming/sessions/%s/view" % session_id,
            headers=headers
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(set(body), {"ok", "view"})
        self.assertEqual(set(body["view"]), VIEW_KEYS)
        return body["view"]
    @staticmethod
    def _revision(content, exists=True):
        return bs.make_target_revision(exists, content, 0o644 if exists else None)
    @staticmethod
    def _turn(store, session_id, snapshot, participant, markdown, target):
        return store.record_completed_turn(
            session_id, snapshot.revision, participant, markdown, target
        )
    @staticmethod
    def _ballot(snapshot, approved):
        votes = [
            {"participant_id": participant["id"],
             "vote": "accept" if participant["role"] == "lead" or approved else "object"}
            for participant in snapshot.state["run_config"]["participants"]
        ]
        return {
            "after_completed_rounds": snapshot.state["rounds_used"],
            "target_revision": snapshot.state["accepted_target_revision"],
            "votes": votes, "approved": approved,
        }
    @staticmethod
    def _close(store, session_id, snapshot, ballot):
        state = snapshot.state
        closing = {
            "reason": "The bounded result is agreed.",
            "unresolved_objections": [],
            "affected_parties": "The operator following this session.",
            "damage_altitude": "The effect is limited to this target.",
            "proportionality": "The accepted result is proportionate.",
            "escalation_evidence": None,
            "open_questions": [],
        }
        ballot = dict(ballot, closing_summary=closing)
        return store.close_with_ballot(
            session_id, snapshot.revision, ballot,
            {
                "outcome": "success", "target_ref": state["request"]["target_path"],
                "transcript_ref": state["transcript_ref"],
                "rounds_used": state["rounds_used"],
            },
            closing,
        )
    def test_dedicated_page_and_routes_are_brainstorming_only(self):
        # The standalone page is retired: the panel's right pane is the
        # only session viewer, and the old route is gone entirely.
        status, gone = self.api._request(
            "GET", "/brainstorming.html?session=x"
        )
        self.assertEqual(status, 404, gone)
        self.assertFalse(
            os.path.exists(
                os.path.join(service.STATIC_DIR, "brainstorming.html")
            )
        )
        session_id, _store = self._create("route.md")
        view = self._view(session_id)
        self.assertEqual(set(view["target"]), {
            "ref", "revision", "changed", "exists", "content", "truncated"
        })
        status, detail = self.api._request(
            "GET", "/api/brainstorming/sessions/%s" % session_id
        )
        self.assertEqual((status, set(detail)), (200, {"ok", "session"}))
        status, missing = self.api._request(
            "GET", "/api/brainstorming/sessions/%s/view/extra" % session_id
        )
        self.assertEqual((status, missing["error"]), (404, "not found"))

    def test_activity_failures_times_and_raw_output_are_visible(self):
        session_id, store = self._create("activity.md")
        common = {
            "action_id": "turn-1",
            "at": "2026-07-29T10:00:00+0200",
            "started_at": 100.0,
            "kind": "discussion_turn",
            "stage": "discussion",
            "round": 1,
            "participant_id": "lead",
            "model_family": "codex",
            "model": "gpt-5.6-sol",
            "effort": "max",
        }
        failed_ref = store.save_activity_output(
            session_id, "activity-failed", "not valid json"
        )
        store.append_activity(session_id, {
            **common,
            "id": "activity-failed",
            "provider_attempt": 1,
            "duration_s": 1.25,
            "status": "failed",
            "failure_type": "protocol",
            "error": "invalid envelope",
            "raw_ref": failed_ref,
        })
        store.append_activity(session_id, {
            **common,
            "id": "activity-repaired",
            "provider_attempt": 2,
            "duration_s": 2.25,
            "status": "completed",
        })

        view = self._view(session_id)
        self.assertEqual(view["work_duration_s"], 3.5)
        self.assertTrue(view["activity"][0]["recovered"])
        self.assertFalse(view["activity"][1]["recovered"])
        status, detail = self.api._request(
            "GET",
            "/api/brainstorming/sessions/%s/activity/activity-failed"
            % session_id,
        )
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["raw_text"], "not valid json")
        self.assertFalse(detail["truncated"])

    def test_classifier_call_is_visible_and_counts_as_work(self):
        session_id, store = self._create("classifier.md", live=True)
        target = os.path.join(self.api.workspace, "docs", "classifier.md")
        prepared = coordination.BrainstormingCoordinator(
            store, None
        ).prepare(session_id)
        with coordination._open_target_parent(target) as (
            _descriptor, _name, parent_identity
        ):
            pass
        store.begin_turn_attempt(session_id, {
            "token": "classified-turn",
            "participant_id": "lead",
            "completed_turn_count": 0,
            "target_revision": prepared.state["accepted_target_revision"],
            "quiescent": False,
            "target_parent": parent_identity,
        })
        store.append_activity(session_id, {
            "id": "activity-failed-before-classification",
            "action_id": "classified-turn",
            "provider_attempt": 1,
            "at": "2026-07-30T10:00:00+0200",
            "started_at": 90.0,
            "duration_s": 1.0,
            "kind": "discussion_turn",
            "stage": "discussion",
            "round": 1,
            "participant_id": "lead",
            "model_family": "codex",
            "model": "gpt-5.6-sol",
            "effort": "max",
            "status": "failed",
            "failure_type": "execution",
            "error": "provider call failed",
        })
        lifecycle._record_classifier_activity(store, session_id, {
            "family": "claude",
            "model": "claude-fable-5",
            "effort": "max",
            "prompt": "classify this failure",
            "raw": '{"error_type":"network"}',
            "started_at": 100.0,
            "duration_s": 2.5,
            "status": "completed",
            "failure_type": None,
            "error": None,
            "prompt_path": None,
        })

        view = self._view(session_id)
        self.assertEqual(view["work_duration_s"], 3.5)
        self.assertIsNone(view["in_flight"])
        self.assertEqual(view["activity"][1]["kind"], "classifier")
        self.assertEqual(view["activity"][1]["stage"], "classification")
        self.assertEqual(view["activity"][1]["model_family"], "claude")
        self.assertEqual(view["activity"][1]["participant_id"],
                         "recovery-classifier")

    def test_active_provider_call_exposes_its_live_clock(self):
        session_id, store = self._create("active-clock.md", live=True)
        started_at = time.time() - 5
        store._store.put(bs._turn_attempt_key(session_id), {
            "token": "active-turn",
            "participant_id": "lead",
            "completed_turn_count": 0,
            "target_revision": None,
            "quiescent": False,
            "started_at": started_at,
            "provider_attempt": 1,
        })

        view = self._view(session_id)

        self.assertEqual(view["in_flight"]["action_id"], "active-turn")
        self.assertEqual(view["in_flight"]["participant_id"], "lead")
        self.assertEqual(view["in_flight"]["started_at"], started_at)
    def test_view_projection_is_authorized_exact_and_revision_coherent(self):
        project = self.api._ready_project(users=[access.USER_EMAILS[0]])
        self.api._target("authorized-view.md")
        headers = self.api._remote_headers(access.USER_EMAILS[0])
        with mock.patch.object(
            lifecycle, "_launch_lifecycle_process", side_effect=self.api._sleeper_launcher
        ):
            status, created = self.api._request(
                "POST", "/api/brainstorming/sessions",
                self.api._payload(
                    "authorized-view.md", project=project["slug"], work_area="main"
                ),
                headers=headers
            )
        self.assertEqual(status, 201, created)
        session_id = created["session"]["id"]
        self.api._stop_sleeper_record(session_id)
        with mock.patch.object(
            bs.SessionStore, "read", side_effect=AssertionError("state read")
        ) as read:
            status, refused = self.api._request(
                "GET", "/api/brainstorming/sessions/%s/view" % session_id,
                headers=self.api._remote_headers(access.USER_EMAILS[1])
            )
        self.assertEqual((status, refused), (403, {"ok": False, "error": "forbidden"}))
        read.assert_not_called()
        view = self._view(session_id, headers=headers)
        state = created["session"]["state"]
        self.assertEqual(view["revision"], created["session"]["revision"])
        record = lifecycle._record_by_id(self.api.home, session_id)
        expected_participants = []
        for participant in state["run_config"]["participants"]:
            binding = record["runtime"]["executors"][
                participant["executor_ref"]
            ]
            expected_participants.append({
                "id": participant["id"],
                "role": participant["role"],
                "delivery": "llm",
                "external_provider": None,
                "model_family": participant["model_family"],
                "model": binding["model"],
                "effort": binding["effort"],
            })
        self.assertEqual(view["participants"], expected_participants)
        self.assertTrue(all(
            "executor_ref" not in participant
            for participant in view["participants"]
        ))
        self.assertEqual(view["transcript_markdown"], bs.render_transcript(state))
        status, unknown = self.api._request(
            "GET", "/api/brainstorming/sessions/unknown/view", headers=headers
        )
        self.assertEqual(
            (status, unknown),
            (404, {"ok": False, "error": "unknown_brainstorming_session"})
        )
    def test_transcript_ballots_target_and_result_follow_accepted_state(self):
        session_id, store = self._create("ordered.md", rounds=2)
        snapshot = coordination.BrainstormingCoordinator(store, None).prepare(session_id)
        first = self._revision(b"<script>target one</script>")
        for participant, markdown in (("lead", "<img onerror=go>"), ("critic", "Revise.")):
            snapshot = self._turn(
                store, session_id, snapshot, participant, markdown, first
            )
        rejected = self._ballot(snapshot, False)
        snapshot = store.record_closure_ballot(session_id, snapshot.revision, rejected)
        view = self._view(session_id)
        self.assertEqual(view["closure_ballots"], [rejected])
        self.assertIsNone(view["final_agreement"])
        self.assertEqual(view["target"]["content"], "<script>target one</script>")
        self.assertEqual(view["transcript_markdown"], bs.render_transcript(snapshot.state))
        second = self._revision(b"accepted target")
        for participant in ("lead", "critic"):
            snapshot = self._turn(
                store, session_id, snapshot, participant, "Agreed.", second
            )
        accepted = self._ballot(snapshot, True)
        terminal = self._close(store, session_id, snapshot, accepted)
        view = self._view(session_id)
        self.assertEqual(
            view["closure_ballots"],
            [
                event["fact"]
                for event in terminal.state["transcript_events"]
                if event["kind"] == "closure_ballot"
            ],
        )
        self.assertEqual(view["result"], terminal.state["result"])
        self.assertEqual(
            view["final_agreement"],
            {
                "markdown": "The bounded result is agreed.",
                "open_questions": [],
                "unresolved_objections": [],
            },
        )
        self.assertTrue(view["target"]["changed"])
        self.assertEqual(view["round"], {"current": 2, "completed": 2, "maximum": 2})
    def test_coordination_without_lead_acceptance_is_not_yet_accepted(self):
        session_id, store = self._create("missing.md", content=None, rounds=4)
        self.assertEqual(
            self._view(session_id)["target"],
            {"ref": "docs/missing.md",
             "revision": None, "changed": None, "exists": None,
             "content": None, "truncated": False},
        )
        snapshot = coordination.BrainstormingCoordinator(store, None).prepare(session_id)
        self.assertIsNone(self._view(session_id)["target"]["exists"])
        absent = store.read_target_revision(
            session_id, snapshot.state["recovery_baseline_revision"]
        )
        snapshot = self._turn(
            store, session_id, snapshot, "lead", "Absent.", absent
        )
        self.assertEqual(self._view(session_id)["target"]["exists"], False)
        snapshot = self._turn(
            store, session_id, snapshot, "critic", "Observed.", absent
        )
        binary = self._revision(b"\xff\x00")
        snapshot = self._turn(store, session_id, snapshot, "lead", "Binary.", binary)
        self.assertIsNone(self._view(session_id)["target"]["content"])
        snapshot = self._turn(
            store, session_id, snapshot, "critic", "Observed.", binary
        )
        large = self._revision(b"x" * (service.ARTIFACT_MAX + 1))
        snapshot = self._turn(store, session_id, snapshot, "lead", "Large.", large)
        target = self._view(session_id)["target"]
        self.assertTrue(target["truncated"])
        self.assertEqual(len(target["content"]), service.ARTIFACT_MAX)
        snapshot = self._turn(
            store, session_id, snapshot, "critic", "Observed.", large
        )
        exact = self._revision("Café".encode("utf-8"))
        self._turn(store, session_id, snapshot, "lead", "Text.", exact)
        self.assertEqual(self._view(session_id)["target"]["content"], "Café")
    def test_page_poll_stop_and_stale_contract(self):
        # The polling/stale/stop contract now lives in the panel's
        # in-pane session view: a request-sequence guard, a stale banner
        # that keeps the last good render, and the bodiless stop POST.
        with open(
            os.path.join(service.STATIC_DIR, "panel.html"),
            encoding="utf-8",
        ) as handle:
            html = handle.read()
        for contract in (
            "seq !== sessionSeq", "showing last known revision, retrying",
            "function refreshSessionDetail", "function stopSelectedSession",
            '{method: "POST"}',
        ):
            self.assertIn(contract, html)
        session_id, _store = self._create("stop.md", live=True)
        status, stopped = self.api._request(
            "POST", "/api/brainstorming/sessions/%s/stop" % session_id
        )
        self.assertEqual(status, 200, stopped)
        view = self._view(session_id)
        self.assertEqual((view["status"], view["result"]["outcome"]), ("failure", "failure"))
    def test_milestone_panel_routes_and_state_remain_unchanged(self):
        status, panel_before = self.api._request("GET", "/")
        self.assertEqual(status, 200)
        status, runs_before = self.api._request("GET", "/api/runs")
        session_id, _store = self._create("independent.md")
        self._view(session_id)
        status, panel_after = self.api._request("GET", "/")
        self.assertEqual((status, panel_after), (200, panel_before))
        status, runs_after = self.api._request("GET", "/api/runs")
        self.assertEqual(runs_after, runs_before)
        self.assertEqual(registry.load(self.api.home)["runs"], [])
        # The panel now renders sessions in its right pane, so its static
        # code references the view's fields — but session STATE still
        # never leaks into the served bytes (panel_after == panel_before
        # above holds across a session create).
        self.assertIn(b"transcript_markdown", panel_after)
if __name__ == "__main__":
    unittest.main()
