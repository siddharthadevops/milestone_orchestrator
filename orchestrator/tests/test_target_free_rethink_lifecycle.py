"""Focused proof for repository-scoped, target-free milestone rethink."""

import os
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming
from orchestrator import brainstorming_coordination
from orchestrator import brainstorming_lifecycle


class _Process:
    pid = 424242

    @staticmethod
    def poll():
        return None


class _Launch:
    process = _Process()

    @staticmethod
    def abort():
        raise AssertionError("released lifecycle must not abort")

    @staticmethod
    def release():
        return None


class TargetFreeRethinkLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="target-free-rethink-")
        self.addCleanup(self.temp.cleanup)
        self.home = os.path.join(self.temp.name, "home")
        self.workspace = os.path.join(self.temp.name, "repo")
        os.makedirs(self.home)
        os.makedirs(self.workspace)
        self.revision = "a" * 40
        self.participants = [
            {
                "id": "lead",
                "role": "initial_position",
                "delivery": "llm",
                "executor_ref": "lead-executor",
                "model_family": "codex",
            },
            {
                "id": "critic",
                "role": "contrary_position",
                "delivery": "llm",
                "executor_ref": "critic-executor",
                "model_family": "claude",
            },
            {
                "id": "dante",
                "role": "common_sense",
                "delivery": "external",
                "external_ref": "narrator",
            },
        ]

    def charge(self, job="rethink"):
        charge = {
            "job": job,
            "prompt_set": "default",
            "values": {},
            "amendments_path": os.path.join(
                self.temp.name, "amendments.json"
            ),
            "accepted_amendments": [],
            "repository": {
                "state_path": os.path.join(self.temp.name, "state.json"),
                "skeleton_path": "skeleton.md",
                "pre_session_commit": self.revision,
            },
        }
        if job == "rethink":
            charge["values"]["rethink_problem"] = (
                "A contradiction spans several repository files."
            )
            charge["artifact_type"] = "implementation"
        return charge

    def request(self, job="rethink"):
        request = {
            "workspace_path": self.workspace,
            "request": "Resolve the repository problem.",
            "context": {
                "brief": "Generic lifecycle context.",
                "source_payload": {
                    "session_charge": self.charge(job),
                },
            },
            "max_rounds": 1,
        }
        if job != "rethink":
            request["target_path"] = "docs/decision.md"
        return request

    def run_config(self):
        return brainstorming.resolve_run_config(
            self.participants, "unanimity", self.participants
        )

    def test_state_result_transcript_and_external_input_omit_target(self):
        store = brainstorming.SessionStore(
            os.path.join(self.temp.name, "session-state")
        )
        created = store.create(
            "rethink", self.request(), self.run_config(), self.participants
        )
        snapshot = store.transition(
            "rethink", created.revision, "running"
        )
        snapshot = store.initialize_repository_coordination(
            "rethink", snapshot.revision, self.revision
        )
        for participant, ready in (
            ("lead", True), ("critic", True), ("dante", True)
        ):
            snapshot = store.record_repository_turn(
                "rethink",
                snapshot.revision,
                participant,
                "%s accepted the repository state." % participant,
                self.revision,
                ready,
            )

        self.assertEqual(snapshot.state["status"], "success")
        self.assertNotIn("target_path", snapshot.state["request"])
        self.assertNotIn("target_ref", snapshot.state["result"])
        transcript = brainstorming.render_transcript(snapshot.state)
        self.assertNotIn("target", transcript.lower())
        self.assertIn(
            "A contradiction spans several repository files.", transcript
        )
        self.assertNotIn("Generic lifecycle context.", transcript)
        self.assertIn(
            "%s..%s" % (self.revision, self.revision), transcript
        )
        external = brainstorming_coordination.BrainstormingCoordinator(
            store, None
        )._external_input(snapshot.state)
        self.assertNotIn("target_path", external)

    def test_lifecycle_skips_target_admission_and_registry_fields(self):
        body = {
            "request": self.request(),
            "participants": [
                {
                    "id": item["id"],
                    "role": item["role"],
                    "delivery": item["delivery"],
                    **(
                        {"external_provider": "narrator"}
                        if item["delivery"] == "external" else {}
                    ),
                }
                for item in self.participants
            ],
            "closure_policy": "unanimity",
        }
        context = {
            "workspace_path": self.workspace,
            "project": None,
            "work_area": None,
            "primary": None,
            "additional": [],
        }
        with mock.patch.object(
            brainstorming_lifecycle,
            "_runtime_and_roster",
            return_value=({}, self.run_config(), self.participants),
        ), mock.patch.object(
            brainstorming_lifecycle,
            "_resolved_target_path",
            side_effect=AssertionError("target path resolution reached"),
        ), mock.patch.object(
            brainstorming_lifecycle,
            "_target_identity",
            side_effect=AssertionError("target identity reached"),
        ), mock.patch.object(
            brainstorming_lifecycle,
            "_reject_authority_overlap",
            side_effect=AssertionError("target authorization reached"),
        ), mock.patch.object(
            brainstorming_coordination,
            "capture_target",
            side_effect=AssertionError("target capture reached"),
        ), mock.patch.object(
            brainstorming_lifecycle, "_track_child"
        ):
            created = brainstorming_lifecycle.create_resolved_session(
                self.home,
                body,
                "milestone:test:slice_impl/01",
                context,
                {},
                launcher=lambda *_args: _Launch(),
            )

        record = brainstorming_lifecycle._load_registry(self.home)[
            "sessions"
        ][0]
        self.assertNotIn("target_path", record)
        self.assertNotIn("target_identity", record)
        self.assertNotIn("target_path", created["state"]["request"])
        listed = brainstorming_lifecycle.list_sessions(
            self.home, lambda _record: True
        )[0]
        self.assertNotIn("target_path", listed)
        self.assertEqual(listed["workspace_path"], self.workspace)
        view = brainstorming_lifecycle.view_session(
            self.home, created["id"], lambda _record: None, 1000
        )
        self.assertIsNone(view["target"])
        self.assertEqual(
            view["repository"]["source_base_revision"], self.revision
        )

    def test_repository_producer_remains_target_backed(self):
        request = self.request("implement@slice_impl")
        checked = brainstorming.validate_request(request)
        self.assertEqual(checked["target_path"], "docs/decision.md")
        with self.assertRaises(brainstorming.ContractError):
            brainstorming.validate_request(
                {key: value for key, value in request.items()
                 if key != "target_path"}
            )


if __name__ == "__main__":
    unittest.main()
