"""Focused executable evidence for brainstorming Slice 02."""

import json
import os
import subprocess
import tempfile
import textwrap
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from orchestrator import brainstorming as bs
from orchestrator import brainstorming_execution as execution
from orchestrator import runners


def request(workspace_path="/workspace"):
    return {
        "workspace_path": workspace_path,
        "target_path": "docs/decision.md",
        "request": "Choose the compatible option to adopt.",
        "context": {"brief": "Resolve one bounded design request."},
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


def run_config(participants):
    return bs.resolve_run_config(
        participants, "unanimity", participants
    )


def envelope(markdown):
    return {"kind": "discussion_turn", "markdown": markdown}


def failure_result(transcript_ref):
    return {
        "outcome": "failure",
        "target_ref": "docs/decision.md",
        "transcript_ref": transcript_ref,
        "rounds_used": 0,
        "reason": "Stopped before agreement.",
    }


def closing_summary():
    return {
        "reason": "Stopped before agreement.",
        "unresolved_objections": [],
        "affected_parties": "The people using the requested target.",
        "damage_altitude": "A bounded reversible consequence.",
        "proportionality": "Stopping was proportionate to the failed run.",
        "escalation_evidence": None,
    }


def runner_result(response, session_ref=None):
    text = json.dumps(response) if isinstance(response, dict) else response
    result = runners.RunnerResult(text, 0, 0.01)
    if session_ref is not None:
        result.session_ref = session_ref
    return result


class RecordingExecutor:
    def __init__(
        self,
        model_family,
        responses=None,
        continuable=True,
        ref_prefix="session",
    ):
        self.model_family = model_family
        self.responses = list(responses or [])
        self.continuable = continuable
        self.ref_prefix = ref_prefix
        self.calls = []
        self._next_ref = 0

    def supports_continuation(self):
        return self.continuable

    def _response(self):
        if not self.responses:
            raise AssertionError("recording executor response script exhausted")
        return self.responses.pop(0)

    def start(self, prompt, workspace_path, execution_context):
        self._next_ref += 1
        ref = "%s-%d" % (self.ref_prefix, self._next_ref)
        self.calls.append(
            {
                "mode": "start",
                "session_ref": ref,
                "prompt": prompt,
                "workspace_path": workspace_path,
                "execution_context": execution_context,
            }
        )
        return runner_result(self._response(), ref)

    def continue_session(
        self, session_ref, prompt, workspace_path, execution_context
    ):
        self.calls.append(
            {
                "mode": "continue",
                "session_ref": session_ref,
                "prompt": prompt,
                "workspace_path": workspace_path,
                "execution_context": execution_context,
            }
        )
        return runner_result(self._response(), session_ref)


class BrainstormingExecutionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(
            prefix="brainstorming-execution-"
        )
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.store = bs.SessionStore(self.root)
        self.fake_state = os.path.join(self.root, "provider-state")
        os.makedirs(self.fake_state)
        self.launched_contexts = []
        self.fake_cli = self._write_executable(
            "fake-participant-cli",
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            import uuid

            args = sys.argv[1:]
            prompt = sys.stdin.read()
            state_dir = args[args.index("--state-dir") + 1]
            is_codex = bool(args and args[0] == "exec")
            family = "codex" if is_codex else "claude"
            if is_codex:
                mode = "continue" if len(args) > 1 and args[1] == "resume" else "start"
                if mode == "continue":
                    session_ref = args[-2]
                else:
                    session_ref = str(uuid.uuid4())
                output_path = args[args.index("--output-last-message") + 1]
            else:
                if "--resume" in args:
                    mode = "continue"
                    session_ref = args[args.index("--resume") + 1]
                else:
                    mode = "start"
                    session_ref = args[args.index("--session-id") + 1]
                output_path = None

            path = os.path.join(state_dir, family + "-" + session_ref + ".json")
            if mode == "continue":
                with open(path, "r", encoding="utf-8") as fh:
                    history = json.load(fh)
            else:
                history = []
            history.append(prompt)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(history, fh)

            record = {
                "family": family,
                "mode": mode,
                "session_ref": session_ref,
                "args": args,
                "prompt": prompt,
            }
            with open(os.path.join(state_dir, "calls.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\\n")

            if "force-repair" in prompt and "REPAIR:" not in prompt:
                answer = "malformed"
            else:
                answer = json.dumps({
                    "kind": "discussion_turn",
                    "markdown": family + ":" + "|".join(history),
                })
            if is_codex and "missing-thread-id" not in prompt:
                print(json.dumps({
                    "type": "thread.started",
                    "thread_id": session_ref,
                }), flush=True)
            if is_codex:
                with open(output_path, "w", encoding="utf-8") as fh:
                    fh.write(answer)
            else:
                print(answer)
            """,
        )

    def _write_executable(self, name, body):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(body))
        os.chmod(path, 0o755)
        return path

    def _create_running(
        self, session_id, participants=None, workspace_path="/workspace"
    ):
        participants = participants or cross_family_participants()
        created = self.store.create(
            session_id,
            request(workspace_path),
            run_config(participants),
            participants,
        )
        return self.store.transition(
            session_id, created.revision, "running"
        )

    def _provider_runner(self):
        def participant_process_factory(
            execution_context, argv, popen_kwargs
        ):
            self.launched_contexts.append(execution_context)
            return subprocess.Popen(argv, **popen_kwargs)

        commands = {
            "codex": [
                self.fake_cli,
                "exec",
                "--state-dir",
                self.fake_state,
                "--model",
                "{model}",
                "--effort",
                "{effort}",
                "--output-last-message",
                "{output_file}",
            ],
            "claude": [
                self.fake_cli,
                "-p",
                "--state-dir",
                self.fake_state,
                "--model",
                "{model}",
                "--effort",
                "{effort}",
            ],
        }
        return runners.SubprocessRunner(
            commands,
            {},
            participant_process_factory=participant_process_factory,
        )

    def test_failed_activity_uses_usage_carried_by_the_exception(self):
        captured = []

        class ActivityStore(object):
            @staticmethod
            def read_turn_attempt(_session_id):
                return {
                    "token": "turn-1", "provider_attempt": 1,
                    "completed_turn_count": 0, "kind": "discussion_turn",
                }

            @staticmethod
            def save_activity_output(_session_id, _event_id, _raw):
                return "activity.txt"

            @staticmethod
            def read(_session_id):
                return type("Snapshot", (), {"state": {
                    "run_config": {
                        "participants": cross_family_participants()
                    }
                }})()

            @staticmethod
            def append_activity(_session_id, event):
                captured.append(event)

        usage = {
            "input_tokens": 10, "cached_input_tokens": 2,
            "output_tokens": 3, "reasoning_output_tokens": 1,
            "total_tokens": 13,
        }
        failure = runners.ProviderResponseError(
            "provider failed", raw_texts=["failed"], token_usage=usage
        )
        failure.token_usage_partial = True
        subject = execution.ParticipantExecution(ActivityStore(), {})
        subject._record_activity(
            "session", cross_family_participants()[0],
            RecordingExecutor("codex"), time.time(),
            status="failed", failure_type="execution", error=failure,
        )

        self.assertEqual(captured[0]["token_usage"], usage)
        self.assertTrue(captured[0]["token_usage_partial"])

    def test_validated_external_envelope_is_durable_before_activity_failure(self):
        roster = [
            cross_family_participants()[0],
            cross_family_participants()[1],
            {
                "id": "dante",
                "role": "common_sense",
                "delivery": "external",
                "external_ref": "external-dante",
            },
        ]
        running = self._create_running("external-acceptance", roster)
        target = bs.make_target_revision(True, b"accepted target", 0o644)
        initialized = self.store.initialize_coordination(
            "external-acceptance", running.revision, target
        )
        ready = self.store.record_completed_turn(
            "external-acceptance",
            initialized.revision,
            "editor",
            "The lead has spoken.",
            target,
        )
        ready = self.store.record_completed_turn(
            "external-acceptance",
            ready.revision,
            "critic",
            "The contrary position has spoken.",
            target,
        )
        req = ready.state["request"]
        intervention = {
            "token": "external-acceptance-token",
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
        self.store.publish_external_intervention(
            "external-acceptance", intervention
        )
        self.store.claim_external_intervention(
            "external-acceptance", intervention["token"]
        )
        executor = RecordingExecutor(
            "codex", [envelope("Dante chooses the practical option.")]
        )
        executor.wait_for_quiescence = lambda _result: True
        participant_execution = execution.ParticipantExecution(
            self.store, {"external-dante": executor}
        )

        with (
            mock.patch.object(
                participant_execution,
                "_record_activity",
                side_effect=RuntimeError("activity store unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "activity store unavailable"),
        ):
            participant_execution.exchange_quiescent(
                "external-acceptance",
                "dante",
                "Narrate Dante's turn.",
                {},
                after_validate=lambda accepted: (
                    self.store.complete_external_provider(
                        "external-acceptance",
                        intervention["token"],
                        {"markdown": accepted["markdown"]},
                    )
                ),
            )

        accepted = self.store.read_external_intervention(
            "external-acceptance"
        )
        self.assertTrue(accepted["provider_quiescent"])
        self.assertEqual(
            accepted["response"]["payload"],
            {"markdown": "Dante chooses the practical option."},
        )
        latest = self.store.read("external-acceptance")
        self.store.record_completed_turn(
            "external-acceptance",
            latest.revision,
            "dante",
            accepted["response"]["payload"]["markdown"],
            target,
        )
        self.store.finish_external_intervention(
            "external-acceptance", intervention["token"]
        )
        activity = self.store.read_activity("external-acceptance")
        self.assertEqual(len(activity["events"]), 1)
        self.assertTrue(activity["events"][0]["token_usage_partial"])
        self.assertIsNone(
            self.store.read_external_intervention("external-acceptance")
        )

    def _bindings(self, provider_runner, participants):
        return {
            participant["executor_ref"]: execution.RunnerParticipantExecutor(
                participant["model_family"],
                provider_runner,
                model="test-model",
                effort="high",
            )
            for participant in participants
        }

    def _provider_calls(self):
        path = os.path.join(self.fake_state, "calls.jsonl")
        with open(path, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_explicit_session_refs_survive_reload_and_isolate_participants(self):
        participants = cross_family_participants()
        self._create_running(
            "cross-family", participants, workspace_path=self.root
        )
        provider_runner = self._provider_runner()
        bindings = self._bindings(provider_runner, participants)
        first = execution.ParticipantExecution(self.store, bindings)

        editor_one, _ = first.exchange(
            "cross-family", "editor", "editor-alpha", {"roots": ["a"]}
        )
        critic_one, _ = first.exchange(
            "cross-family", "critic", "critic-beta", {"roots": ["a"]}
        )
        before = self.store.read("cross-family").state[
            "participant_sessions"
        ]

        reopened = bs.SessionStore(self.root)
        second = execution.ParticipantExecution(reopened, bindings)
        editor_two, _ = second.exchange(
            "cross-family", "editor", "editor-second", {"roots": ["a"]}
        )
        critic_two, _ = second.exchange(
            "cross-family", "critic", "critic-second", {"roots": ["a"]}
        )
        after = reopened.read("cross-family").state["participant_sessions"]

        self.assertEqual(before, after)
        self.assertIn("editor-alpha", editor_one["markdown"])
        self.assertIn("editor-alpha", editor_two["markdown"])
        self.assertNotIn("critic-beta", editor_two["markdown"])
        self.assertIn("critic-beta", critic_one["markdown"])
        self.assertIn("critic-beta", critic_two["markdown"])
        self.assertNotIn("editor-alpha", critic_two["markdown"])
        self.assertTrue(after["editor"].startswith("codex-primary:"))
        self.assertTrue(after["critic"].startswith("claude-reviewer:"))

        calls = self._provider_calls()
        by_family = {
            family: [item for item in calls if item["family"] == family]
            for family in ("codex", "claude")
        }
        for family_calls in by_family.values():
            self.assertEqual(
                [item["mode"] for item in family_calls],
                ["start", "continue"],
            )
            self.assertEqual(
                family_calls[0]["session_ref"],
                family_calls[1]["session_ref"],
            )

    def test_same_family_participants_never_use_implicit_latest_session(self):
        participants = same_family_participants()
        self._create_running(
            "same-family", participants, workspace_path=self.root
        )
        provider_runner = self._provider_runner()
        subject = execution.ParticipantExecution(
            self.store, self._bindings(provider_runner, participants)
        )

        subject.exchange(
            "same-family", "editor", "editor-private", object()
        )
        subject.exchange(
            "same-family", "critic", "critic-private", object()
        )
        editor_two, _ = subject.exchange(
            "same-family", "editor", "editor-again", object()
        )
        critic_two, _ = subject.exchange(
            "same-family", "critic", "critic-again", object()
        )

        refs = self.store.read("same-family").state["participant_sessions"]
        self.assertNotEqual(refs["editor"], refs["critic"])
        self.assertIn("editor-private", editor_two["markdown"])
        self.assertNotIn("critic-private", editor_two["markdown"])
        self.assertIn("critic-private", critic_two["markdown"])
        self.assertNotIn("editor-private", critic_two["markdown"])

        calls = self._provider_calls()
        self.assertEqual(
            [item["mode"] for item in calls],
            ["start", "start", "continue", "continue"],
        )
        expected_raw = {
            participant_id: bs.provider_session_ref(
                next(
                    item["executor_ref"]
                    for item in participants
                    if item["id"] == participant_id
                ),
                refs[participant_id],
            )
            for participant_id in ("editor", "critic")
        }
        self.assertEqual(calls[2]["session_ref"], expected_raw["editor"])
        self.assertEqual(calls[3]["session_ref"], expected_raw["critic"])
        for call in calls:
            self.assertNotIn("--last", call["args"])
            self.assertNotIn("--continue", call["args"])

    def test_execution_admission_binding_and_context_pass_through(self):
        participant = cross_family_participants()[0]
        participants = cross_family_participants()
        executor = RecordingExecutor(
            "codex",
            responses=[
                envelope("first"),
                envelope("continued"),
                "malformed",
                envelope("repaired"),
            ],
        )

        created = self.store.create(
            "created",
            request(),
            run_config(participants),
            participants,
        )
        subject = execution.ParticipantExecution(
            self.store, {"codex-primary": executor}
        )
        with self.assertRaises(execution.ExecutionRejected):
            subject.exchange("created", participant["id"], "prompt", object())
        self.assertEqual(executor.calls, [])
        self.assertEqual(created.state["participant_sessions"], {})

        terminal = self.store.create(
            "terminal",
            request(),
            run_config(participants),
            participants,
        )
        terminal = self.store.transition(
            "terminal",
            terminal.revision,
            "failure",
            failure_result(terminal.state["transcript_ref"]),
            closing_summary(),
        )
        with self.assertRaises(execution.ExecutionRejected):
            subject.exchange("terminal", participant["id"], "prompt", object())
        self.assertEqual(executor.calls, [])
        self.assertEqual(terminal.state["participant_sessions"], {})

        for session_id, bindings in (
            ("missing", {}),
            (
                "mismatch",
                {"codex-primary": RecordingExecutor("claude")},
            ),
            (
                "noncontinuable",
                {
                    "codex-primary": RecordingExecutor(
                        "codex", continuable=False
                    )
                },
            ),
        ):
            self._create_running(session_id)
            rejected = execution.ParticipantExecution(self.store, bindings)
            with self.assertRaises(execution.ExecutionRejected):
                rejected.exchange(
                    session_id, participant["id"], "prompt", object()
                )
            self.assertEqual(
                self.store.read(session_id).state["participant_sessions"], {}
            )
            for binding in bindings.values():
                self.assertEqual(binding.calls, [])

        self._create_running("valid")
        context = {
            "tools": object(),
            "environment": {"SENTINEL": "present"},
            "primary_root": "/primary",
            "additional_roots": ["/additional"],
            "sibling_access": True,
            "access_rules": object(),
        }
        context_before = dict(context)
        subject.exchange("valid", "editor", "turn one", context)
        subject.exchange("valid", "editor", "turn two", context)
        repaired, _ = subject.exchange(
            "valid", "editor", "turn three", context
        )
        self.assertEqual(repaired, envelope("repaired"))
        self.assertEqual(context, context_before)
        self.assertEqual(len(executor.calls), 4)
        for call in executor.calls:
            self.assertIs(call["execution_context"], context)
            self.assertEqual(call["workspace_path"], "/workspace")
        durable_ref = bs.provider_session_ref(
            "codex-primary",
            self.store.read("valid").state["participant_sessions"]["editor"],
        )
        self.assertTrue(
            all(
                call["session_ref"] == durable_ref
                for call in executor.calls[1:]
            )
        )

        class FreshFallbackExecutor(RecordingExecutor):
            def continue_session(
                inner_self,
                session_ref,
                prompt,
                workspace_path,
                execution_context,
            ):
                result = super().continue_session(
                    session_ref,
                    prompt,
                    workspace_path,
                    execution_context,
                )
                result.session_ref = "silently-fresh"
                return result

        self._create_running("fresh-fallback")
        fallback = FreshFallbackExecutor(
            "codex",
            responses=[envelope("first"), envelope("must be rejected")],
        )
        fallback_subject = execution.ParticipantExecution(
            self.store, {"codex-primary": fallback}
        )
        fallback_subject.exchange(
            "fresh-fallback", "editor", "first", context
        )
        before = self.store.read("fresh-fallback")
        with self.assertRaises(execution.ExecutionRejected):
            fallback_subject.exchange(
                "fresh-fallback", "editor", "second", context
            )
        self.assertEqual(self.store.read("fresh-fallback"), before)

    def test_runner_adapter_delegates_the_exact_caller_context(self):
        participants = cross_family_participants()
        self._create_running(
            "runner-context", participants, workspace_path=self.root
        )
        provider_runner = self._provider_runner()
        subject = execution.ParticipantExecution(
            self.store, self._bindings(provider_runner, participants)
        )
        context = {
            "tools": object(),
            "environment": {"SENTINEL": "caller"},
            "primary_root": self.root,
            "additional_roots": ["/read-only-neighbor"],
            "sibling_access": True,
            "access_rules": object(),
        }

        subject.exchange("runner-context", "editor", "first", context)
        subject.exchange("runner-context", "editor", "second", context)
        subject.exchange(
            "runner-context", "editor", "force-repair", context
        )

        self.assertEqual(len(self.launched_contexts), 4)
        self.assertTrue(
            all(item is context for item in self.launched_contexts)
        )

    def test_plain_runner_exchange_keeps_unmeasurable_quiescence_fail_open(self):
        participants = cross_family_participants()
        self._create_running(
            "plain-unmeasurable", participants, workspace_path=self.root
        )
        self._create_running(
            "ordered-unmeasurable", participants, workspace_path=self.root
        )
        provider_runner = self._provider_runner()
        subject = execution.ParticipantExecution(
            self.store, self._bindings(provider_runner, participants)
        )

        with mock.patch(
            "orchestrator.runners._process_group_quiescent",
            return_value=None,
        ):
            accepted, result = subject.exchange(
                "plain-unmeasurable",
                "editor",
                "plain participant exchange",
                {"caller": "context"},
            )
            with self.assertRaises(execution.ExecutionRejected):
                subject.exchange_quiescent(
                    "ordered-unmeasurable",
                    "editor",
                    "ordered participant turn",
                    {"caller": "context"},
                )

        self.assertEqual(accepted["kind"], "discussion_turn")
        self.assertFalse(hasattr(result, "worker_quiescent"))
        plain = self.store.read("plain-unmeasurable")
        self.assertIn("editor", plain.state["participant_sessions"])
        ordered = self.store.read("ordered-unmeasurable")
        self.assertNotIn("editor", ordered.state["participant_sessions"])

    def test_quiescent_exchange_consumes_shared_runner_completion_evidence(self):
        participants = cross_family_participants()
        self._create_running(
            "quiescent-runner", participants, workspace_path=self.root
        )
        provider_runner = self._provider_runner()
        subject = execution.ParticipantExecution(
            self.store, self._bindings(provider_runner, participants)
        )
        accepted, result = subject.exchange_quiescent(
            "quiescent-runner",
            "editor",
            "one supervised turn",
            {"caller": "context"},
        )
        self.assertEqual(accepted["kind"], "discussion_turn")
        self.assertTrue(result.worker_quiescent)
        with runners._ACTIVE_WORKERS_LOCK:
            self.assertEqual(runners._ACTIVE_WORKERS, set())

    def test_codex_session_ref_failure_preserves_quiescence_evidence(self):
        participants = cross_family_participants()
        self._create_running(
            "missing-codex-ref", participants, workspace_path=self.root
        )
        provider_runner = self._provider_runner()
        subject = execution.ParticipantExecution(
            self.store, self._bindings(provider_runner, participants)
        )

        with self.assertRaises(runners.RunnerError) as failed:
            subject.exchange_quiescent(
                "missing-codex-ref",
                "editor",
                "missing-thread-id",
                {"caller": "context"},
            )

        self.assertTrue(failed.exception.worker_quiescent)
        with runners._ACTIVE_WORKERS_LOCK:
            self.assertEqual(runners._ACTIVE_WORKERS, set())

    def test_unscoped_or_stdout_only_runner_is_rejected_before_spawn(self):
        spawned = []

        def participant_process_factory(
            execution_context, argv, popen_kwargs
        ):
            spawned.append((execution_context, argv))
            return subprocess.Popen(argv, **popen_kwargs)

        stdout_only = runners.SubprocessRunner(
            {"codex": [self.fake_cli, "exec"]},
            {},
            participant_process_factory=participant_process_factory,
        )
        output_capable_but_unscoped = runners.SubprocessRunner(
            {
                "codex": [
                    self.fake_cli,
                    "exec",
                    "--output-last-message",
                    "{output_file}",
                ]
            },
            {},
        )

        self.assertFalse(stdout_only.supports_session_continuation("codex"))
        self.assertFalse(
            output_capable_but_unscoped.supports_session_continuation("codex")
        )
        with self.assertRaises(runners.RunnerError):
            stdout_only.start_session(
                "codex", "prompt", self.root, {"caller": "context"}
            )
        with self.assertRaises(runners.RunnerError):
            output_capable_but_unscoped.start_session(
                "codex", "prompt", self.root, {"caller": "context"}
            )
        self.assertEqual(spawned, [])

    def test_discussion_turn_envelope_contract(self):
        valid = envelope("A Markdown contribution.")
        self.assertEqual(
            execution.validate_discussion_turn_envelope(valid), valid
        )
        invalid = [
            {},
            {"kind": "discussion_turn"},
            {"markdown": "text"},
            {"kind": "other", "markdown": "text"},
            {"kind": "discussion_turn", "markdown": ""},
            {"kind": "discussion_turn", "markdown": 3},
            dict(valid, participant_id="editor"),
            dict(valid, role="lead"),
            dict(valid, round=1),
            dict(valid, target="changed"),
            dict(valid, revision=2),
            dict(valid, vote="accept"),
            dict(valid, result="success"),
            dict(valid, transport_status="ok"),
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(bs.ContractError):
                    execution.validate_discussion_turn_envelope(candidate)

        ambiguous = runners.RunnerResult(
            json.dumps(valid) + "\n" + json.dumps(valid), 0, 0.01
        )
        with self.assertRaises(ValueError):
            execution.ParticipantExecution._parse(ambiguous)

    def test_protocol_repair_continues_once_without_completing_an_extra_turn(self):
        self._create_running("one-repair")
        executor = RecordingExecutor(
            "codex", responses=["not json", envelope("one accepted turn")]
        )
        subject = execution.ParticipantExecution(
            self.store, {"codex-primary": executor}
        )
        accepted, result = subject.exchange(
            "one-repair", "editor", "discuss", {"sentinel": True}
        )
        self.assertEqual(accepted, envelope("one accepted turn"))
        self.assertEqual(
            [call["mode"] for call in executor.calls],
            ["start", "continue"],
        )
        self.assertEqual(
            executor.calls[0]["session_ref"],
            executor.calls[1]["session_ref"],
        )
        self.assertTrue(executor.calls[1]["prompt"].startswith("discuss"))
        self.assertIn("REPAIR:", executor.calls[1]["prompt"])
        self.assertEqual(result.repair["raw_text"], "not json")

        self._create_running("two-strikes")
        twice = RecordingExecutor(
            "codex", responses=["first bad", "second bad"]
        )
        failed = execution.ParticipantExecution(
            self.store, {"codex-primary": twice}
        )
        with self.assertRaises(runners.WorkerProtocolError) as caught:
            failed.exchange(
                "two-strikes", "editor", "discuss", {"sentinel": True}
            )
        self.assertEqual(
            caught.exception.raw_texts, ["first bad", "second bad"]
        )
        self.assertEqual(len(twice.calls), 2)
        self.assertEqual(
            twice.calls[0]["session_ref"], twice.calls[1]["session_ref"]
        )

    def test_first_session_ref_compare_and_set_is_write_once(self):
        self._create_running("race")
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        counter = {"value": 0}

        class RacingExecutor(RecordingExecutor):
            def start(inner_self, prompt, workspace_path, execution_context):
                with lock:
                    counter["value"] += 1
                    ref = "racer-%d" % counter["value"]
                inner_self.calls.append(
                    {
                        "mode": "start",
                        "session_ref": ref,
                        "prompt": prompt,
                        "workspace_path": workspace_path,
                        "execution_context": execution_context,
                    }
                )
                barrier.wait()
                return runner_result(envelope(ref), ref)

        executor = RacingExecutor("codex")
        subject = execution.ParticipantExecution(
            self.store, {"codex-primary": executor}
        )

        def exchange_once(index):
            try:
                accepted, _ = subject.exchange(
                    "race", "editor", "attempt %d" % index, object()
                )
                return "ok", accepted["markdown"]
            except bs.RevisionConflict as exc:
                return "stale", exc.current

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(exchange_once, (1, 2)))
        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 1)
        self.assertEqual([kind for kind, _ in outcomes].count("stale"), 1)
        durable = self.store.read("race")
        raw = bs.provider_session_ref(
            "codex-primary",
            durable.state["participant_sessions"]["editor"],
        )
        self.assertEqual(
            raw, next(value for kind, value in outcomes if kind == "ok")
        )
        with self.assertRaises(bs.HistoryRewriteError):
            self.store.bind_participant_session(
                "race", durable.revision, "editor", "replacement"
            )
        self.assertEqual(self.store.read("race"), durable)

        self._create_running("write-failure")
        failed_executor = RecordingExecutor(
            "codex", responses=[envelope("must not escape")]
        )
        failed = execution.ParticipantExecution(
            self.store, {"codex-primary": failed_executor}
        )
        with mock.patch(
            "orchestrator.kvstore.os.replace",
            side_effect=OSError("simulated durable write failure"),
        ):
            with self.assertRaises(OSError):
                failed.exchange(
                    "write-failure", "editor", "attempt", object()
                )
        self.assertEqual(
            self.store.read("write-failure").state["participant_sessions"], {}
        )

    def test_participant_calls_reuse_liveness_and_stop_supervision(self):
        def codex_executor(script, window, floor):
            def participant_process_factory(
                execution_context, argv, popen_kwargs
            ):
                return subprocess.Popen(argv, **popen_kwargs)

            runner = runners.SubprocessRunner(
                {
                    "codex": [
                        script,
                        "exec",
                        "--output-last-message",
                        "{output_file}",
                    ]
                },
                {},
                stall_window_s=window,
                stall_min_cpu_s=floor,
                participant_process_factory=participant_process_factory,
            )
            return execution.RunnerParticipantExecutor("codex", runner)

        frozen = self._write_executable(
            "frozen-codex",
            """\
            #!/usr/bin/env python3
            import time
            time.sleep(30)
            """,
        )
        with self.assertRaises(runners.WorkerStalled) as stalled_error:
            codex_executor(frozen, 0.5, 0.2).start(
                "prompt", self.root, object()
            )
        self.assertTrue(stalled_error.exception.worker_quiescent)

        active = self._write_executable(
            "active-codex",
            """\
            #!/usr/bin/env python3
            import json
            import sys
            import time
            args = sys.argv[1:]
            output_path = args[args.index("--output-last-message") + 1]
            for index in range(6):
                print(json.dumps({"type": "progress", "index": index}), flush=True)
                time.sleep(0.2)
            print(json.dumps({"type": "thread.started", "thread_id": "active-ref"}), flush=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump({"kind": "discussion_turn", "markdown": "active"}, fh)
            """,
        )
        active_result = codex_executor(active, 0.5, 0.2).start(
            "prompt", self.root, object()
        )
        self.assertEqual(active_result.session_ref, "active-ref")

        blind = self._write_executable(
            "blind-codex",
            """\
            #!/usr/bin/env python3
            import json
            import sys
            import time
            args = sys.argv[1:]
            output_path = args[args.index("--output-last-message") + 1]
            time.sleep(1)
            print(json.dumps({"type": "thread.started", "thread_id": "blind-ref"}), flush=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump({"kind": "discussion_turn", "markdown": "blind"}, fh)
            """,
        )
        with mock.patch(
            "orchestrator.runners.group_cpu_by_pid", return_value=None
        ):
            blind_result = codex_executor(blind, 0.3, 0.2).start(
                "prompt", self.root, object()
            )
        self.assertEqual(blind_result.session_ref, "blind-ref")

        stopped = self._write_executable(
            "stopped-codex",
            """\
            #!/usr/bin/env python3
            import time
            time.sleep(30)
            """,
        )
        stop_executor = codex_executor(stopped, 0, 0)
        stop_outcome = {}

        def run_stopped():
            try:
                stop_executor.start("prompt", self.root, object())
            except Exception as exc:
                stop_outcome["error"] = exc

        thread = threading.Thread(target=run_stopped)
        thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            with runners._ACTIVE_WORKERS_LOCK:
                if runners._ACTIVE_WORKERS:
                    break
            time.sleep(0.02)
        runners.kill_active_worker_groups()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(stop_outcome.get("error"), runners.RunnerError)
        self.assertTrue(stop_outcome["error"].worker_quiescent)
        with runners._ACTIVE_WORKERS_LOCK:
            self.assertEqual(runners._ACTIVE_WORKERS, set())

        child_pid_path = os.path.join(self.root, "participant-child.pid")
        descendant_process = {}
        descendant = self._write_executable(
            "descendant-codex",
            """\
            #!/usr/bin/env python3
            import json
            import subprocess
            import sys
            args = sys.argv[1:]
            output_path = args[args.index("--output-last-message") + 1]
            pid_path = args[args.index("--pid-path") + 1]
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with open(pid_path, "w", encoding="utf-8") as fh:
                fh.write(str(child.pid))
            print(json.dumps({"type": "thread.started", "thread_id": "descendant-ref"}), flush=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump({"kind": "discussion_turn", "markdown": "done"}, fh)
            """,
        )

        def spawn_descendant(execution_context, argv, popen_kwargs):
            process = subprocess.Popen(argv, **popen_kwargs)
            descendant_process["process"] = process
            return process

        descendant_runner = runners.SubprocessRunner(
            {
                "codex": [
                    descendant,
                    "exec",
                    "--pid-path",
                    child_pid_path,
                    "--output-last-message",
                    "{output_file}",
                ]
            },
            {},
            participant_process_factory=spawn_descendant,
        )
        descendant_result = execution.RunnerParticipantExecutor(
            "codex", descendant_runner
        ).start("prompt", self.root, object())
        self.assertEqual(descendant_result.session_ref, "descendant-ref")
        self.assertTrue(descendant_result.worker_quiescent)
        self.assertTrue(
            runners._process_group_quiescent(
                descendant_process["process"].pid
            )
        )
        with open(child_pid_path, "r", encoding="utf-8") as fh:
            child_pid = int(fh.read())
        with self.assertRaises(OSError):
            os.kill(child_pid, 0)

    def test_legacy_runner_call_contract_is_unchanged(self):
        observed = os.path.join(self.root, "legacy-observed.json")
        script = self._write_executable(
            "legacy-call",
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            prompt = sys.stdin.read()
            workspace, output_path, observed, model, effort = sys.argv[1:]
            with open(observed, "w", encoding="utf-8") as fh:
                json.dump({
                    "argv": sys.argv[1:],
                    "cwd": os.getcwd(),
                    "prompt": prompt,
                    "sentinel": os.environ["LEGACY_SENTINEL"],
                }, fh)
            with open(output_path, "w", encoding="utf-8") as fh:
                fh.write("legacy output")
            """,
        )
        env = dict(os.environ)
        env["LEGACY_SENTINEL"] = "unchanged"
        runner = runners.SubprocessRunner(
            {
                "legacy": [
                    script,
                    "{workspace}",
                    "{output_file}",
                    observed,
                    "{model}",
                    "{effort}",
                ]
            },
            {"legacy": 5},
            env=env,
        )
        result = runner.call(
            "legacy",
            "legacy prompt",
            self.root,
            model="legacy-model",
            effort="legacy-effort",
        )
        self.assertEqual(result.text, "legacy output")
        with open(observed, "r", encoding="utf-8") as fh:
            seen = json.load(fh)
        self.assertEqual(
            os.path.realpath(seen["cwd"]), os.path.realpath(self.root)
        )
        self.assertEqual(seen["prompt"], "legacy prompt")
        self.assertEqual(seen["sentinel"], "unchanged")
        self.assertEqual(seen["argv"][0], self.root)
        self.assertEqual(seen["argv"][-2:], [
            "legacy-model", "legacy-effort"
        ])
        self.assertNotIn("resume", seen["argv"])
        self.assertNotIn("--session-id", seen["argv"])
        self.assertFalse(hasattr(result, "session_ref"))


if __name__ == "__main__":
    unittest.main()
