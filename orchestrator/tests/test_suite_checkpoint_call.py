import copy
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import canonical_plan, driver, gitops, judgment_calls, runners
from orchestrator import staffing
from orchestrator import state as st


def _slice(slice_id):
    return {
        "id": slice_id,
        "title": "Slice %d" % slice_id,
        "intent": "Deliver slice %d." % slice_id,
        "producer_task_executor": {
            "draft_slice_note": "agent_call",
            "implement": "agent_call",
        },
    }


def _document(ids):
    return (
        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
        % json.dumps(
            {"slices": [_slice(value) for value in ids]},
            separators=(",", ":"),
        )
    )


class SuiteCheckpointCallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="suite-checkpoint-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = self.temp.name
        self.skeleton = "docs/skeleton.md"
        self.command = "python3 -m unittest discover -s tests"
        self._git("init", "-q")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "Tests")
        self._write(".gitignore", "\n".join(gitops.ignore_lines()) + "\n")
        self._write(self.skeleton, _document((1,)))
        self._write("app.txt", "baseline\n")
        self.head = self._commit("checkpoint baseline")
        self._git("config", "--local", gitops.BASELINE_MARK, "true")

        config = driver.load_config(None)
        driver.merge_config(config, {
            "verification": [self.command],
            "git": {"enabled": True},
            "error_classifier": False,
            "infra_retry_backoff_s": [],
        })
        self.model_home = tempfile.TemporaryDirectory(
            prefix="suite-checkpoint-models-"
        )
        self.addCleanup(self.model_home.cleanup)
        staffing.ensure_documents(self.model_home.name, config=config)
        self.checkpoint_question_ids = judgment_calls.prepare(
            self.model_home.name,
            job="suite_checkpoint@workspace",
            material="code",
            values={
                "kind": "suite_checkpoint",
                "workspace": self.workspace,
                "checkpoint_reason": "four_slice_checkpoint",
            },
            amendments=[],
            configured_suite_commands=[self.command],
        ).bound.question_ids

        state = st.new_state("goal", self.workspace, config)
        state["milestone"]["slices"] = copy.deepcopy(
            canonical_plan.validate_canonical_plan(
                _document((1,))
            )["projection"]
        )
        state["milestone"][canonical_plan.ANCHOR_KEY] = {
            "path": self.skeleton,
            "revision": self.head,
        }
        skeleton = st._new_unit(st.UNIT_SKELETON, None)
        skeleton["status"] = st.U_SEALED
        skeleton["artifact"] = self.skeleton
        skeleton["gate_commit"] = self.head[:12]
        slice_note = st._new_unit(st.UNIT_SLICE_DOC, 1)
        slice_note["status"] = st.U_SEALED
        slice_note["gate_commit"] = self.head[:12]
        implementation = st._new_unit(st.UNIT_SLICE_IMPL, 1)
        implementation["status"] = st.U_PRE_SEAL_VERIFY
        state["units"] = [skeleton, slice_note, implementation]
        st.append_event(
            state,
            "gate_commit",
            unit=st.UNIT_SKELETON,
            sha=self.head,
        )
        self.state_path = driver.default_state_path(self.workspace)
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(
            os.path.join(os.path.dirname(self.state_path), "amendments.json"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write('{"amendments":[]}')
        st.save(self.state_path, state)

    def _git(self, *args):
        return subprocess.run(
            ("git",) + args,
            cwd=self.workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _write(self, relative, content):
        path = os.path.join(self.workspace, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def _commit(self, message):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD")

    def _response(self, status="passed", commands=None):
        commands = [self.command] if commands is None else commands
        response = {
            "status": status,
            "kind": "suite_checkpoint",
            "commands": commands,
            "results": [
                {
                    "command": command,
                    "exit_code": 0,
                    "evidence": "complete suite passed",
                }
                for command in commands
            ],
            "authority": {
                "source": "operator_config",
                "evidence": [],
            },
        }
        return self._with_questions(response)

    def _questions(self):
        return [
            {"id": question_id, "answer": "Checked."}
            for question_id in self.checkpoint_question_ids
        ]

    def _with_questions(self, response):
        questions = self._questions()
        if questions:
            response["questions"] = questions
        return response

    def test_default_config_discovers_repository_suite(self):
        self.assertNotIn("verification", driver.load_config())

    def _subject(self, response, side_effect=None):
        return driver.Driver(
            self.state_path,
            model_profiles_home=self.model_home.name,
            runner=runners.MockRunner([{
                "expect_kind": "suite_checkpoint",
                "side_effect": side_effect,
                "response": response,
            }]),
        )

    def _verify(self, subject):
        with mock.patch.object(
            subject, "_review_evidence_fingerprint", return_value="reviewed"
        ), mock.patch.object(
            subject, "_seal_reviews", return_value=["review-1"]
        ), mock.patch.object(
            subject, "_full_verification_cadence",
            return_value="four_slice_checkpoint",
        ), mock.patch.object(
            subject, "_complete_seal_from_reviews", return_value="sealed"
        ) as seal:
            note = subject._do_verify()
        return note, seal

    def test_unchanged_configured_checkpoint_can_seal(self):
        subject = self._subject(self._response())

        note, seal = self._verify(subject)

        self.assertIn("passed", note)
        seal.assert_called_once()
        self.assertEqual(len(subject.runner.calls), 1)
        self.assertIn(json.dumps([self.command]), subject.runner.calls[0][2])
        event = subject.state["events"][-1]
        self.assertEqual(event["type"], "verification")
        self.assertTrue(event["ok"])
        self.assertTrue(event["stable"])
        self.assertEqual(event["commands"], [self.command])

    def test_ordinary_mutation_is_restored_and_status_discarded(self):
        def mutate(_workspace):
            self._write("app.txt", "changed by checkpoint\n")

        subject = self._subject(self._response(), side_effect=mutate)

        note, seal = self._verify(subject)

        self.assertIn("invalidated", note)
        seal.assert_not_called()
        with open(os.path.join(self.workspace, "app.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "baseline\n")
        event = subject.state["events"][-1]
        self.assertFalse(event["ok"])
        self.assertFalse(event["stable"])
        self.assertEqual(event["returned_status"], "passed")
        self.assertFalse(event["plan_changed"])
        self.assertTrue(any(
            candidate.get("type") == "suite_checkpoint_rerun_required"
            for candidate in subject.state["events"]
        ))

    def test_contract_correction_gets_a_fresh_restored_attempt(self):
        malformed = self._response(commands=["wrong configured command"])

        def mutate(_workspace):
            self._write("app.txt", "changed during rejected attempt\n")

        subject = driver.Driver(
            self.state_path,
            model_profiles_home=self.model_home.name,
            runner=runners.MockRunner([
                {
                    "expect_kind": "suite_checkpoint",
                    "side_effect": mutate,
                    "response": malformed,
                },
                {
                    "expect_kind": "suite_checkpoint",
                    "response": self._response(),
                },
            ]),
        )

        note, seal = self._verify(subject)

        self.assertIn("passed", note)
        seal.assert_called_once()
        self.assertEqual(len(subject.runner.calls), 2)
        self.assertIn("CONTRACT CORRECTION", subject.runner.calls[1][2])
        with open(os.path.join(self.workspace, "app.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "baseline\n")
        event = subject.state["events"][-1]
        self.assertTrue(event["ok"])
        self.assertTrue(event["stable"])

    def test_valid_plan_block_is_preserved_alone_and_status_discarded(self):
        def change_plan(_workspace):
            self._write(self.skeleton, _document((1, 2)))
            self._write("app.txt", "unrelated checkpoint mutation\n")

        subject = self._subject(self._response(), side_effect=change_plan)

        note, seal = self._verify(subject)

        self.assertIn("invalidated", note)
        seal.assert_not_called()
        with open(os.path.join(self.workspace, self.skeleton), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), _document((1, 2)))
        with open(os.path.join(self.workspace, "app.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "baseline\n")
        event = subject.state["events"][-1]
        self.assertTrue(event["plan_changed"])
        self.assertTrue(any(
            candidate.get("type") == "suite_checkpoint_rerun_required"
            and candidate.get("plan_changed") is True
            for candidate in subject.state["events"]
        ))
        self.assertEqual(
            subject._invalidated_suite_checkpoint_cadence(
                next(
                    unit for unit in subject.state["units"]
                    if st.unit_key(unit) == "slice_impl-01"
                )
            ),
            "four_slice_checkpoint",
        )
        self.assertNotEqual(self._git("rev-parse", "HEAD"), self.head)
        self.assertEqual(
            subject.state["milestone"][canonical_plan.ANCHOR_KEY]["revision"],
            self._git("rev-parse", "HEAD"),
        )

    def test_durable_rerun_obligation_survives_a_rebuilt_source_unit(self):
        subject = self._subject(self._response())
        source = next(
            unit for unit in subject.state["units"]
            if st.unit_key(unit) == "slice_impl-01"
        )
        st.append_event(
            subject.state,
            "suite_checkpoint_rerun_required",
            unit=st.unit_key(source),
            cadence="milestone_final",
        )
        rebuilt = st._new_unit(st.UNIT_SLICE_IMPL, 2)
        rebuilt["status"] = st.U_PRE_SEAL_VERIFY

        self.assertEqual(
            subject._invalidated_suite_checkpoint_cadence(rebuilt),
            "milestone_final",
        )
        st.append_event(
            subject.state,
            "verification",
            unit=st.unit_key(rebuilt),
            status="passed",
            cadence="milestone_final",
            ok=True,
            stable=True,
        )
        self.assertIsNone(
            subject._invalidated_suite_checkpoint_cadence(rebuilt)
        )

    def test_reconciliation_stop_records_rerun_before_reply_adoption(self):
        def replace_started_plan(_workspace):
            self._write(self.skeleton, _document((2,)))

        subject = self._subject(
            self._response(), side_effect=replace_started_plan
        )

        with mock.patch.object(
            subject, "_review_evidence_fingerprint", return_value="reviewed"
        ), mock.patch.object(
            subject, "_seal_reviews", return_value=["review-1"]
        ), mock.patch.object(
            subject, "_full_verification_cadence",
            return_value="milestone_final",
        ):
            with self.assertRaises(driver.PlanReconciliationOpened):
                subject._do_verify()

        persisted = st.load(self.state_path)
        self.assertIn(
            canonical_plan.RECONCILIATION_KEY, persisted["milestone"]
        )
        self.assertTrue(any(
            event.get("type") == "suite_checkpoint_rerun_required"
            and event.get("cadence") == "milestone_final"
            and event.get("plan_changed") is True
            for event in persisted["events"]
        ))
        self.assertFalse(any(
            event.get("type") == "verification"
            for event in persisted["events"]
        ))

    def test_discovery_ignores_historical_command_and_accepts_no_suite(self):
        state = st.load(self.state_path)
        state["config"]["verification"] = []
        state["suite_command"] = "historical narrowed command"
        os.unlink(self.state_path)
        st.save_new(self.state_path, state)
        response = {
            "status": "no_suite",
            "kind": "suite_checkpoint",
            "commands": [],
            "results": [],
            "authority": {
                "source": "repository",
                "evidence": [{
                    "path": ".gitignore",
                    "basis": "No complete suite is declared.",
                }],
            },
        }
        self._with_questions(response)
        subject = self._subject(response)

        note, seal = self._verify(subject)

        self.assertIn("no_suite", note)
        seal.assert_called_once()
        event = subject.state["events"][-1]
        self.assertEqual(event["commands"], [])
        self.assertTrue(event["ok"])

    def test_unchanged_failure_account_is_preserved_without_sealing(self):
        failure = {
            "command": self.command,
            "exit_code": 1,
            "diagnostics": "test_example failed with an assertion",
            "affected_tests": ["test_example"],
        }
        response = {
            "status": "failed",
            "kind": "suite_checkpoint",
            "commands": [self.command],
            "results": [{
                "command": self.command,
                "exit_code": 1,
                "evidence": "one failing test",
            }],
            "authority": {"source": "operator_config", "evidence": []},
            "failure_account": failure,
        }
        self._with_questions(response)
        subject = self._subject(response)

        note, seal = self._verify(subject)

        self.assertIn("failed", note)
        seal.assert_not_called()
        event = next(
            event for event in reversed(subject.state["events"])
            if event.get("type") == "verification"
        )
        self.assertEqual(event["status"], "failed")
        self.assertEqual(event["failure_account"], failure)
        self.assertTrue(event["stable"])
        self.assertFalse(event["ok"])
        unit = st.current_unit(subject.state)
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertEqual(unit["fix_source"]["type"], "suite_checkpoint")
        self.assertEqual(unit["fix_source"]["return_to"], st.U_PRE_SEAL_VERIFY)
        self.assertEqual(len(unit["fix_queue"]), 1)
        finding = unit["fix_queue"][0]
        self.assertEqual(finding["severity"], "P1")
        self.assertEqual(finding["failure_account"], failure)
        subject.state["milestone"]["slices"].append(
            canonical_plan.validate_canonical_plan(
                _document((1, 2))
            )["projection"][1]
        )
        self.assertEqual(
            subject._invalidated_suite_checkpoint_cadence(unit),
            "four_slice_checkpoint",
        )


if __name__ == "__main__":
    unittest.main()
