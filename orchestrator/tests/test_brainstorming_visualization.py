"""Focused executable evidence for Brainstorming Slice 07."""
import os
import re
import unittest
from unittest import mock
from orchestrator import access
from orchestrator import brainstorming as bs
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import registry, service
from orchestrator.tests import test_brainstorming_api as api_tests
VIEW_KEYS = {
    "id", "caller", "status", "question", "process", "revision", "target",
    "participants", "same_family_fallback", "closure_policy",
    "closure_ballots", "round", "transcript_markdown", "result",
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
        return store.close_with_ballot(
            session_id, snapshot.revision, ballot,
            {
                "outcome": "success", "target_ref": state["request"]["target_path"],
                "transcript_ref": state["transcript_ref"],
                "rounds_used": state["rounds_used"],
            },
            {
                "reason": "The bounded result is agreed.",
                "unresolved_objections": [],
                "affected_parties": "The operator following this session.",
                "damage_altitude": "The effect is limited to this target.",
                "proportionality": "The accepted result is proportionate.",
                "escalation_evidence": None,
            }
        )
    def test_dedicated_page_and_routes_are_brainstorming_only(self):
        status, page = self.api._request("GET", "/brainstorming.html?session=x")
        self.assertEqual(status, 200)
        html = page.decode("utf-8")
        self.assertIn("/api/brainstorming/sessions/", html)
        self.assertIn("textContent", html)
        self.assertIn("clearSensitive();", html)
        self.assertIn("li { overflow-wrap: anywhere; }", html)
        self.assertNotIn("innerHTML", html)
        self.assertIsNone(re.search(
            r"\b(?:milestone|slice|review|seal|chronology)\b", html.lower()
        ))
        session_id, _store = self._create("route.md")
        view = self._view(session_id)
        self.assertEqual(set(view["target"]), {
            "ref", "revision", "exists", "content", "truncated"
        })
        status, detail = self.api._request(
            "GET", "/api/brainstorming/sessions/%s" % session_id
        )
        self.assertEqual((status, set(detail)), (200, {"ok", "session"}))
        status, missing = self.api._request(
            "GET", "/api/brainstorming/sessions/%s/view/extra" % session_id
        )
        self.assertEqual((status, missing["error"]), (404, "not found"))
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
        self.assertEqual(view["participants"], state["run_config"]["participants"])
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
        self.assertEqual(view["closure_ballots"], [rejected, accepted])
        self.assertEqual(view["result"], terminal.state["result"])
        self.assertEqual(view["round"], {"current": 2, "completed": 2, "maximum": 2})
    def test_absent_binary_and_large_target_previews_are_honest(self):
        session_id, store = self._create("missing.md", content=None, rounds=3)
        self.assertEqual(
            self._view(session_id)["target"],
            {"ref": "docs/missing.md",
             "revision": None, "exists": None, "content": None, "truncated": False},
        )
        snapshot = coordination.BrainstormingCoordinator(store, None).prepare(session_id)
        self.assertEqual(self._view(session_id)["target"]["exists"], False)
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
        with open(
            os.path.join(service.STATIC_DIR, "brainstorming.html"),
            encoding="utf-8",
        ) as handle:
            html = handle.read()
        for contract in (
            "sequence !== requestSequence", "view.revision < renderedRevision",
            "Showing the last known revision", "return ngrok ? 30000 : 2000",
            '{method: "POST"}', "await refreshView()", "setTimeout(poll",
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
        self.assertNotIn(b"transcript_markdown", panel_after)
if __name__ == "__main__":
    unittest.main()
