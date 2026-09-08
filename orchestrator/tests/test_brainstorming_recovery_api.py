"""Explicit recovery retains a failed discussion's accepted work and owner."""

import copy
from pathlib import Path
import unittest
from unittest import mock

from orchestrator import brainstorming as bs
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import brainstorming_tasks as adapter
from orchestrator import gitops, service, task_api
from orchestrator.tests import test_task_api as task_tests


class RecoveryHost(task_tests.NoopHost):
    def is_active(self, _task_id):
        return False


class BrainstormingRecoveryApiTest(unittest.TestCase):
    def setUp(self):
        self.api = task_tests.TaskApiTest("runTest")
        self.api.setUp()
        self.addCleanup(self.api.doCleanups)
        self.host = RecoveryHost()
        self.api.start_server(self.host)
        self.home = self.api.home
        self.store = task_api.StandaloneTaskStore(self.home)
        self.session_store = bs.SessionStore(lifecycle.state_directory(self.home))
        config = lifecycle.driver.load_config(None)
        selection = {"session": None}
        order = self.api.order("brainstorming")
        order["brainstorming_mode"] = "repository_review"
        self.task = self.store.admit(
            order, adapter.resolve_staffing(config, self.api.primary,
                                            staffing_selection=selection),
            self.api.primary,
        )
        processes = []

        def launch(*_args, **_kwargs):
            process = self.api._sleeper()
            processes.append(process)
            return lifecycle.GatedLaunch(process, lambda: None, process.terminate)

        with mock.patch.object(lifecycle, "_launch_lifecycle_process", side_effect=launch):
            projection = adapter.start_task(
                {"tasks": [self.task]}, self.task["id"], config, self.home,
                staffing_selection=selection,
            )
        self.session_id = projection["id"]
        for process in processes:
            process.terminate()
            process.wait(timeout=5)
        lifecycle.reap_children(self.home)
        snapshot = coordination.BrainstormingCoordinator(
            self.session_store, None
        ).prepare(self.session_id)
        participant = snapshot.state["run_config"]["participants"][0]
        snapshot = self.session_store.record_repository_turn(
            self.session_id, snapshot.revision, participant["id"],
            "Accepted contribution retained after the quota failure.",
            gitops.head_full_sha(self.api.primary), False,
        )
        reason = "The discussion stopped because participant execution failed."
        self.failed = self.session_store.close_with_interruption(
            self.session_id, snapshot.revision,
            {"after_completed_turns": 1, "plain": reason},
            lifecycle._failure_result(snapshot.state, reason),
            lifecycle._closing_summary(snapshot.state, reason, "Accepted work is retained."),
            failure_origin="operational",
        )
        self.result = {
            "status": "failure", "reason": reason,
            "native_result": dict(self.failed.state["result"], session_id=self.session_id),
            "duration_s": 12.5, "token_usage": None,
            "token_usage_partial": True, "cost": None, "cost_partial": True,
        }
        self.store.record_result(self.task["id"], self.result)
        self.endpoint = "/api/brainstorming/sessions/%s/start" % self.session_id

    def launch(self, *_args, **_kwargs):
        process = self.api._sleeper()
        return lifecycle.GatedLaunch(process, lambda: None, process.terminate)

    def recover(self, revision=None):
        return self.api.request("POST", self.endpoint, {
            "recovery_revision": self.failed.revision if revision is None else revision,
        })

    def test_recovery_preserves_work_failure_history_and_task_identity(self):
        before = copy.deepcopy(self.failed.state)
        activity = self.session_store.read_activity(self.session_id)
        with mock.patch.object(lifecycle, "_launch_lifecycle_process", side_effect=self.launch) as launch:
            status, body = self.recover()
            self.assertEqual(status, 200, body)
            launch.assert_called_once()
            status, repeated = self.recover()
            self.assertEqual(status, 409, repeated)
            launch.assert_called_once()
        resumed = self.session_store.read(self.session_id).state
        self.assertEqual(resumed["history"][:-1], before["history"])
        self.assertEqual(resumed["status"], "running")
        self.assertNotIn("result", resumed)
        for key in ("completed_turns", "transcript_events", "accepted_target_revision"):
            self.assertEqual(resumed[key], before[key])
        self.assertEqual(self.session_store.read_activity(self.session_id), activity)
        task = self.store.record(self.task["id"])
        self.assertIsNone(task["result"])
        self.assertEqual(task["order"], self.task["order"])
        self.assertEqual(task["resolved_staffing"], self.task["resolved_staffing"])
        history = self.store.lifecycle(task["id"])["history"]
        self.assertEqual([event["attempt"] for event in history], [self.result])
        self.assertEqual(self.host.started, [task["id"]])

    def test_stale_recovery_does_not_reopen_owner_or_spawn(self):
        with mock.patch.object(lifecycle, "_launch_lifecycle_process") as launch:
            status, body = self.recover(self.failed.revision - 1)
        self.assertEqual(status, 409, body)
        launch.assert_not_called()
        self.assertEqual(self.store.record(self.task["id"])["result"], self.result)
        self.assertEqual(self.session_store.read(self.session_id), self.failed)

    def test_spawn_refusal_keeps_terminal_owner_and_session(self):
        with mock.patch.object(lifecycle, "_launch_lifecycle_process", side_effect=OSError("cannot spawn")):
            status, body = self.recover()
        self.assertEqual(status, 503, body)
        self.assertEqual(self.store.record(self.task["id"])["result"], self.result)
        self.assertEqual(self.session_store.read(self.session_id), self.failed)

    def test_cancellation_fences_recovery_and_hides_resume(self):
        # A prior Stop intent remains authoritative even if an older worker
        # incorrectly published its operational failure afterward.
        current, document = self.store._read_document(self.task["id"])
        document["stop_reason"] = "Cancelled by operator"
        self.assertTrue(self.store._store.cas(
            task_api.task_key(self.task["id"]), current["revision"], document
        ).ok)
        with mock.patch.object(lifecycle, "_launch_lifecycle_process") as launch:
            status, body = self.recover()
        self.assertEqual(status, 409, body)
        launch.assert_not_called()
        status, body = self.api.request(
            "GET", "/api/brainstorming/sessions/%s/view" % self.session_id
        )
        self.assertEqual(status, 200, body)
        self.assertFalse(body["view"]["recoverable"])
        self.assertEqual(self.session_store.read(self.session_id), self.failed)

    def test_dirty_repository_is_preserved_and_recovery_is_refused(self):
        changed = Path(self.api.primary, "user-work.txt")
        changed.write_text("Unaccepted user work must remain.\n", encoding="utf-8")
        with mock.patch.object(lifecycle, "_launch_lifecycle_process") as launch:
            status, body = self.recover()
        self.assertEqual(status, 409, body)
        launch.assert_not_called()
        self.assertEqual(changed.read_text(), "Unaccepted user work must remain.\n")
        self.assertEqual(self.store.record(self.task["id"])["result"], self.result)

    def test_busy_workspace_does_not_reopen_or_spawn(self):
        with mock.patch.object(service, "workspace_sync_in_flight", return_value=True), \
                mock.patch.object(lifecycle, "_launch_lifecycle_process") as launch:
            status, body = self.recover()
        self.assertEqual((status, body["error"]), (409, service.WORK_AREA_BUSY))
        launch.assert_not_called()
        self.assertEqual(self.store.record(self.task["id"])["result"], self.result)

    def test_foreign_request_cannot_recover_the_session(self):
        with mock.patch.object(lifecycle, "_launch_lifecycle_process") as launch:
            status, body = self.api.request(
                "POST", self.endpoint,
                {"recovery_revision": self.failed.revision},
                headers=self.api.member(),
            )
        self.assertEqual(status, 403, body)
        launch.assert_not_called()
        self.assertEqual(self.store.record(self.task["id"])["result"], self.result)


if __name__ == "__main__":
    unittest.main()
