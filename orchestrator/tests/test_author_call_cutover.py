"""Focused proof for the reusable direct-author call package."""

import copy
import json
import os
import sys
import tempfile
import unittest

from orchestrator import author_calls, contracts, prompt_sets, runners
from orchestrator import verifiers


def implement_values(workspace, **changes):
    values = {
        "kind": "implement",
        "workspace": workspace,
        "slice_id": "5",
        "slice_title": "Milestone author-call cutover",
        "skeleton_path": "implementation/milestones/router/skeleton.md",
        "goal_path": "implementation/milestones/router/goal.md",
        "slice_note_path": "implementation/milestones/router/slice-05.md",
        "soft_lines": "41",
        "hard_lines": "63",
    }
    values.update(changes)
    return values


def draft_skeleton_values(workspace):
    return {
        "kind": "draft_skeleton",
        "workspace": workspace,
        "goal_path": "implementation/milestones/router/goal.md",
        "skeleton_path": "implementation/milestones/router/skeleton.md",
        "task_executor_catalogue": "[]",
    }


def safeguard_policy(field="reuse_evidence"):
    return {
        "id": "reuse-proof",
        "version": 1,
        "enabled": True,
        "scope": {
            "kinds": ["implement"],
            "unit_kinds": ["slice_impl"],
        },
        "prompt": "Explain the concrete reuse evidence.",
        "contract": {
            "field": field,
            "required": True,
            "entry": {"finding": {"type": "string"}},
            "checks": [{"kind": "non_empty", "field": "finding"}],
        },
    }


def project_context(workspace, policies):
    return {
        "project": "orchestrators",
        "work_area": "implementation",
        "primary": {"path": workspace},
        "additional": [],
        "reuse_sources": [],
        "safeguards": policies,
    }


def answered(bound):
    return [
        {"id": question_id, "answer": "Checked the delivered boundary."}
        for question_id in bound.question_ids
    ]


class AuthorCallPreparationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orch-author-call-")
        self.addCleanup(self.temp.cleanup)

    def prepare(self, **changes):
        options = {
            "job": "implement@slice_impl",
            "material": "code",
            "values": implement_values(self.temp.name),
        }
        options.update(changes)
        return author_calls.prepare(self.temp.name, **options)

    def test_charge_renders_and_validates_exact_served_contract(self):
        prepared = self.prepare()
        self.assertTrue(prepared.prompt.startswith(
            "KIND: implement\nWORKSPACE: %s\n" % self.temp.name
        ))
        self.assertNotIn("FAMILY:", prepared.prompt)
        self.assertNotIn("SEQUENTIAL IMPLEMENTATION PART", prepared.prompt)
        self.assertIn("around 41", prepared.prompt)
        self.assertIn("at 63", prepared.prompt)
        self.assertLess(
            prepared.prompt.index("QUESTIONS (answer each in output"),
            prepared.prompt.index("Common fields:"),
        )
        self.assertEqual(
            prepared.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )

        valid = {
            "status": "ok",
            "kind": "implement",
            "files_changed": ["orchestrator/author_calls.py"],
            "questions": answered(prepared.bound),
        }
        self.assertEqual(prepared.validate(copy.deepcopy(valid)), valid)
        invalid = dict(valid, suite_command="python3 -m unittest")
        with self.assertRaises(contracts.ContractError):
            prepared.validate(invalid)

    def test_implementation_charge_renders_exact_current_part_scope(self):
        scope = {
            "part": "b",
            "scope": "Activate only the remaining author-call boundary.",
            "delegated_remaining": "Retire the legacy controls in part c.",
            "source_unit": "slice_impl-05-a",
        }

        prepared = self.prepare(values=implement_values(
            self.temp.name, implementation_scope=scope
        ))

        self.assertIn("SEQUENTIAL IMPLEMENTATION PART — b", prepared.prompt)
        self.assertIn(
            '- CURRENT PART SCOPE (JSON quoted): "Activate only the remaining '
            'author-call boundary."',
            prepared.prompt,
        )
        self.assertIn(
            '- DELEGATED REMAINDER (JSON quoted): "Retire the legacy controls '
            'in part c."',
            prepared.prompt,
        )
        self.assertLess(
            prepared.prompt.index("SEQUENTIAL IMPLEMENTATION PART — b"),
            prepared.prompt.index("IMPLEMENTATION RULES"),
        )

    def test_continuation_falls_past_stored_set_that_omits_part_scope(self):
        prompt_sets.ensure_default(self.temp.name)
        implement_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "milestone",
            "implement.json",
        )
        shared_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "shared",
            "shared.json",
        )
        with open(implement_path, "r", encoding="utf-8") as handle:
            stored_implement = json.load(handle)
        stored_implement["instructions"]["parts"] = [
            part for part in stored_implement["instructions"]["parts"]
            if part.get("ref") != "implementation_scope"
        ]
        with open(implement_path, "w", encoding="utf-8") as handle:
            json.dump(stored_implement, handle)
        with open(shared_path, "r", encoding="utf-8") as handle:
            stored_shared = json.load(handle)
        del stored_shared["units"]["implementation_scope"]
        with open(shared_path, "w", encoding="utf-8") as handle:
            json.dump(stored_shared, handle)

        uncut = self.prepare()
        self.assertIsNone(uncut.prompt_set_fallback)

        scope = {
            "part": "b",
            "scope": "Activate only the remaining author-call boundary.",
            "delegated_remaining": "Retire the legacy controls in part c.",
            "source_unit": "slice_impl-05-a",
        }
        continuation = self.prepare(values=implement_values(
            self.temp.name, implementation_scope=scope
        ))

        self.assertEqual(
            continuation.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )
        self.assertIn("SEQUENTIAL IMPLEMENTATION PART — b", continuation.prompt)
        self.assertIn(
            '- CURRENT PART SCOPE (JSON quoted): "Activate only the remaining '
            'author-call boundary."',
            continuation.prompt,
        )

    def test_project_extension_is_paired_with_bound_author_contract(self):
        prepared = self.prepare(
            project_context=project_context(
                self.temp.name, [safeguard_policy()]
            )
        )
        self.assertIn("Explain the concrete reuse evidence.", prepared.prompt)
        self.assertIn("REQUIRED OUTPUT FIELD 'reuse_evidence'", prepared.prompt)
        self.assertIn("non_empty(field=finding)", prepared.prompt)
        reply = {
            "status": "ok",
            "kind": "implement",
            "files_changed": [],
            "questions": answered(prepared.bound),
        }
        with self.assertRaises(contracts.ContractError):
            prepared.validate(copy.deepcopy(reply))
        reply["reuse_evidence"] = [{"finding": "Reused the router."}]
        self.assertEqual(prepared.validate(copy.deepcopy(reply)), reply)

        blocked = {
            "status": "blocked",
            "kind": "implement",
            "blocked_reason": "The required source is unavailable.",
            "questions": answered(prepared.bound),
        }
        self.assertEqual(prepared.validate(copy.deepcopy(blocked)), blocked)

    def test_active_safeguards_fall_past_an_incomplete_stored_rung(self):
        prompt_sets.ensure_default(self.temp.name)
        implement_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "milestone",
            "implement.json",
        )
        with open(implement_path, "r", encoding="utf-8") as handle:
            custom_implement = json.load(handle)
        custom_implement["instructions"]["parts"] = [
            part for part in custom_implement["instructions"]["parts"]
            if part.get("ref") != "project_context"
        ]
        with open(implement_path, "w", encoding="utf-8") as handle:
            json.dump(custom_implement, handle)

        prepared = self.prepare(
            project_context=project_context(
                self.temp.name, [safeguard_policy()]
            )
        )

        self.assertEqual(
            prepared.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )
        self.assertIn("Explain the concrete reuse evidence.", prepared.prompt)
        self.assertIn("REQUIRED OUTPUT FIELD 'reuse_evidence'", prepared.prompt)

    def test_unbindable_served_contract_falls_through_the_whole_rung(self):
        prompt_sets.ensure_default(self.temp.name)
        shared_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "shared",
            "shared.json",
        )
        with open(shared_path, "r", encoding="utf-8") as handle:
            shared = json.load(handle)
        shared["contract_sections"]["implement_result"]["text"] = []
        with open(shared_path, "w", encoding="utf-8") as handle:
            json.dump(shared, handle)

        prepared = self.prepare()

        self.assertEqual(
            prepared.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )
        self.assertIn('"files_changed"', prepared.prompt)

    def test_undeclared_consumer_placeholder_fails_during_preparation(self):
        consumer_section = {
            "id": "suite_checkpoint_result",
            "text": ["Return {{undeclared_field}}"],
            "variables": [],
        }

        with self.assertRaisesRegex(
            prompt_sets.PromptSetError, "undeclared: undeclared_field"
        ):
            self.prepare(consumer_sections=(consumer_section,))

    def test_draft_skeleton_requires_the_supplied_artifact_path(self):
        prepared = author_calls.prepare(
            self.temp.name,
            job="draft_skeleton@skeleton",
            material="document",
            values=draft_skeleton_values(self.temp.name),
        )
        reply = {
            "status": "ok",
            "kind": "draft_skeleton",
            "artifact": "implementation/milestones/other/skeleton.md",
            "questions": answered(prepared.bound),
        }
        with self.assertRaisesRegex(
            contracts.ContractError, "exactly equal the supplied skeleton path"
        ):
            prepared.validate(reply)
        reply["artifact"] = (
            "implementation/milestones/router/skeleton.md"
        )
        self.assertEqual(prepared.validate(copy.deepcopy(reply)), reply)

    def test_safeguards_cannot_collide_with_routed_protocol_fields(self):
        for field in ("questions", "artifact"):
            with self.subTest(field=field):
                # The legacy compiler must remain usable by consumers that
                # have not moved to the routed reply vocabulary yet.
                verifiers.compile_policy(safeguard_policy(field))
                with self.assertRaisesRegex(
                    verifiers.PolicyConfigError,
                    "collides with the routed implement reply protocol",
                ):
                    self.prepare(
                        project_context=project_context(
                            self.temp.name, [safeguard_policy(field)]
                        )
                    )

        prompt_sets.ensure_default(self.temp.name)
        implement_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "milestone",
            "implement.json",
        )
        with open(implement_path, "r", encoding="utf-8") as handle:
            custom_implement = json.load(handle)
        custom_implement["output_contract"]["sections"] = []
        with open(implement_path, "w", encoding="utf-8") as handle:
            json.dump(custom_implement, handle)

        questions_only = self.prepare(
            project_context=project_context(
                self.temp.name, [safeguard_policy()]
            )
        )
        self.assertTrue(questions_only.bound.question_ids)
        self.assertFalse(questions_only.bound.registered_section_ids)

        with self.assertRaisesRegex(
            verifiers.PolicyConfigError,
            "collides with the routed implement reply protocol",
        ):
            self.prepare(
                project_context=project_context(
                    self.temp.name, [safeguard_policy("questions")]
                )
            )

    def test_only_the_three_direct_author_jobs_are_admitted(self):
        with self.assertRaisesRegex(
            ValueError, "not a direct milestone author charge"
        ):
            self.prepare(job="review_round@slice_impl")


class PhysicalPreparationTest(unittest.TestCase):
    def test_late_dispatch_does_not_rewrite_a_prepared_prompt(self):
        prompt = (
            "KIND: implement\n"
            "FAMILY: author-owned\n"
            "WORKSPACE: /workspace\n\n"
            "ROUTED\n"
        )
        runner = runners.MockRunner([{
            "expect_kind": "implement",
            "expect_family": "claude",
            "response": {"attempt": 1},
        }])

        output, _result = runners.call_worker(
            runner,
            "codex",
            "legacy prompt must not dispatch",
            "implement",
            "/workspace",
            prepare_call=lambda _error: author_calls.PreparedAuthorCall(
                prompt, lambda reply: reply, "rung-1", None
            ),
            resolve_dispatch=lambda: ("claude", None, None),
        )

        self.assertEqual(output, {"attempt": 1})
        self.assertEqual(runner.calls[0][2], prompt)

    def test_initial_preparation_preserves_policy_config_fault(self):
        runner = runners.MockRunner([])
        fault = verifiers.PolicyConfigError("safeguard collision")

        def prepare(_error):
            raise fault

        with self.assertRaises(verifiers.PolicyConfigError) as caught:
            runners.call_worker(
                runner,
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
            )

        self.assertIs(caught.exception, fault)
        self.assertFalse(caught.exception.provider_dispatch_started)
        self.assertEqual(runner.calls, [])

    def test_repair_preparation_preserves_policy_config_fault(self):
        runner = runners.MockRunner([{
            "expect_kind": "implement",
            "response": {"attempt": 1},
        }])
        fault = verifiers.PolicyConfigError("safeguard collision")
        preparations = []

        def prepare(error):
            preparations.append(error)
            if error is not None:
                raise fault

            def validate(_reply):
                raise contracts.ContractError("reply needs repair")

            return author_calls.PreparedAuthorCall(
                "KIND: implement\nROUTED\n",
                validate,
                "rung-1",
                None,
            )

        with self.assertRaises(verifiers.PolicyConfigError) as caught:
            runners.call_worker(
                runner,
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
            )

        self.assertIs(caught.exception, fault)
        self.assertFalse(caught.exception.provider_dispatch_started)
        self.assertEqual(len(preparations), 2)
        self.assertEqual(len(runner.calls), 1)
        self.assertTrue(caught.exception.completed_attempt_before_dispatch_failure)
        self.assertEqual(len(caught.exception.physical_dispatches), 1)

    def test_contract_repair_gets_a_fresh_package_without_legacy_suffix(self):
        runner = runners.MockRunner([
            {"expect_kind": "implement", "response": {"attempt": 1}},
            {"expect_kind": "implement", "response": {"attempt": 2}},
        ])
        preparations = []

        def prepare(error):
            attempt = len(preparations) + 1
            preparations.append(error)
            prompt = (
                "KIND: implement\nWORKSPACE: /workspace\n"
                "ROUTED ATTEMPT %d\nRECOVERY: %s\n"
                % (attempt, error or "none")
            )

            def validate(reply):
                if reply.get("attempt") != 2:
                    raise contracts.ContractError(
                        "reply does not satisfy routed attempt %d" % attempt
                    )
                return reply

            return author_calls.PreparedAuthorCall(
                prompt, validate, "rung-%d" % attempt, None
            )

        output, result = runners.call_worker(
            runner,
            "codex",
            "legacy prompt must not dispatch",
            "implement",
            "/workspace",
            prepare_call=prepare,
        )

        self.assertEqual(output, {"attempt": 2})
        self.assertEqual(len(preparations), 2)
        self.assertIsNone(preparations[0])
        self.assertIn("routed attempt 1", preparations[1])
        self.assertEqual(
            [call[2].splitlines()[2] for call in runner.calls],
            ["ROUTED ATTEMPT 1", "ROUTED ATTEMPT 2"],
        )
        self.assertNotIn("REPAIR:", runner.calls[1][2])
        self.assertEqual(result.prompt_set_fallback, "rung-2")
        self.assertEqual(
            result.repair["prompt_set_fallback"], "rung-1"
        )

    def test_failed_repair_keeps_each_attempt_fallback_sidecar(self):
        runner = runners.MockRunner([
            {"expect_kind": "implement", "response": {"attempt": 1}},
            {"expect_kind": "implement", "response": {"attempt": 2}},
        ])
        attempts = []

        def prepare(_error):
            attempt = len(attempts) + 1
            attempts.append(attempt)

            def validate(_reply):
                raise contracts.ContractError("invalid attempt")

            return author_calls.PreparedAuthorCall(
                "KIND: implement\nATTEMPT: %d\n" % attempt,
                validate,
                "rung-%d" % attempt,
                None,
            )

        with self.assertRaises(runners.WorkerProtocolError) as caught:
            runners.call_worker(
                runner,
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
            )

        self.assertEqual(
            [
                dispatch["prompt_set_fallback"]
                for dispatch in caught.exception.physical_dispatches
            ],
            ["rung-1", "rung-2"],
        )

    def test_failed_repair_transport_keeps_dispatched_fallback_sidecar(self):
        def fail_transport(_workspace):
            raise runners.RunnerError("repair transport failed")

        runner = runners.MockRunner([
            {"expect_kind": "implement", "response": {"attempt": 1}},
            {
                "expect_kind": "implement",
                "side_effect": fail_transport,
                "response": "unreachable",
            },
        ])
        attempts = []

        def prepare(_error):
            attempt = len(attempts) + 1
            attempts.append(attempt)

            def validate(_reply):
                raise contracts.ContractError("invalid attempt")

            return author_calls.PreparedAuthorCall(
                "KIND: implement\nATTEMPT: %d\n" % attempt,
                validate,
                "rung-%d" % attempt,
                None,
            )

        with self.assertRaises(runners.RunnerError) as caught:
            runners.call_worker(
                runner,
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
            )

        self.assertTrue(caught.exception.provider_dispatch_started)
        self.assertEqual(
            [
                dispatch["prompt_set_fallback"]
                for dispatch in caught.exception.physical_dispatches
            ],
            ["rung-1", "rung-2"],
        )

    def test_repair_trace_failure_does_not_invent_physical_attempt(self):
        with tempfile.TemporaryDirectory(
            prefix="orch-author-trace-failure-"
        ) as workspace:
            marker = os.path.join(workspace, "worker-started")
            script = (
                "import json, pathlib, sys\n"
                "path = pathlib.Path(sys.argv[1])\n"
                "prior = path.read_text() if path.exists() else ''\n"
                "path.write_text(prior + 'started\\n')\n"
                "print(json.dumps({'attempt': 1}))\n"
            )
            recorded = []

            def record(_family, prompt):
                recorded.append(prompt)
                if len(recorded) == 2:
                    raise OSError("trace disk unavailable")
                return "first-trace"

            runner = runners.SubprocessRunner(
                {"fam": [sys.executable, "-c", script, marker]},
                {"fam": 5},
                prompt_recorder=record,
            )
            attempts = []

            def prepare(_error):
                attempt = len(attempts) + 1
                attempts.append(attempt)

                def validate(_reply):
                    raise contracts.ContractError("invalid attempt")

                return author_calls.PreparedAuthorCall(
                    "KIND: implement\nATTEMPT: %d\n" % attempt,
                    validate,
                    "rung-%d" % attempt,
                    None,
                )

            with self.assertRaises(runners.RunnerError) as caught:
                runners.call_worker(
                    runner,
                    "fam",
                    "legacy prompt must not dispatch",
                    "implement",
                    workspace,
                    prepare_call=prepare,
                )

            error = caught.exception
            self.assertFalse(error.provider_dispatch_started)
            self.assertFalse(hasattr(error, "prompt_set_fallback"))
            self.assertEqual(len(error.physical_dispatches), 1)
            self.assertEqual(
                error.physical_dispatches[0]["prompt_set_fallback"],
                "rung-1",
            )
            with open(marker, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "started\n")
            self.assertEqual(len(recorded), 2)

    def test_failed_initial_transport_keeps_dispatched_fallback_sidecar(self):
        def fail_transport(_workspace):
            raise runners.RunnerError("initial transport failed")

        runner = runners.MockRunner([{
            "expect_kind": "implement",
            "side_effect": fail_transport,
            "response": "unreachable",
        }])

        def prepare(_error):
            return author_calls.PreparedAuthorCall(
                "KIND: implement\nROUTED\n",
                lambda reply: reply,
                "rung-1",
                None,
            )

        with self.assertRaises(runners.RunnerError) as caught:
            runners.call_worker(
                runner,
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
            )

        error = caught.exception
        self.assertTrue(error.provider_dispatch_started)
        self.assertEqual(error.prompt_set_fallback, "rung-1")
        self.assertEqual(len(error.physical_dispatches), 1)
        self.assertEqual(
            error.physical_dispatches[0]["prompt_set_fallback"], "rung-1"
        )

    def test_prelaunch_initial_errors_do_not_invent_physical_attempt(self):
        def prepare(_error):
            return author_calls.PreparedAuthorCall(
                "KIND: implement\nROUTED\n",
                lambda reply: reply,
                "rung-1",
                None,
            )

        cases = (
            ("missing command", runners.SubprocessRunner({}, {}), None),
            ("command template resolution failure", runners.SubprocessRunner(
                {"codex": ["codex", "exec", "--model", "{model}"]},
                {"codex": 1},
            ), None),
            ("template spawn failure", runners.SubprocessRunner(
                {"codex": ["/definitely/missing/orchestrator-worker"]},
                {"codex": 1},
            ), None),
            ("live spawn failure", runners.SubprocessRunner(
                {"codex": [
                    "/definitely/missing/orchestrator-worker",
                    "exec",
                    "--dangerously-bypass-approvals-and-sandbox",
                ]},
                {"codex": 1},
            ), runners.ActiveCallControl()),
        )
        for name, runner, active_control in cases:
            with self.subTest(name=name):
                with self.assertRaises(runners.RunnerError) as caught:
                    runners.call_worker(
                        runner,
                        "codex",
                        "legacy prompt must not dispatch",
                        "implement",
                        "/workspace",
                        prepare_call=prepare,
                        active_control=active_control,
                    )

                error = caught.exception
                self.assertFalse(error.provider_dispatch_started)
                self.assertFalse(hasattr(error, "physical_dispatches"))
                self.assertFalse(hasattr(error, "prompt_set_fallback"))

    def test_invalid_repair_resolver_does_not_invent_physical_attempt(self):
        runner = runners.MockRunner([{
            "expect_kind": "implement",
            "response": "not-json",
        }])
        resolutions = iter([
            ("codex", None, None),
            ("invalid",),
        ])

        def prepare(_error):
            return author_calls.PreparedAuthorCall(
                "KIND: implement\nROUTED\n",
                lambda reply: reply,
                "rung-1",
                None,
            )

        with self.assertRaises(runners.RunnerError) as caught:
            runners.call_worker(
                runner,
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
                resolve_dispatch=lambda: next(resolutions),
            )

        error = caught.exception
        self.assertFalse(error.provider_dispatch_started)
        self.assertEqual(len(error.physical_dispatches), 1)
        self.assertEqual(len(runner.calls), 1)
        self.assertTrue(error.completed_attempt_before_dispatch_failure)
        self.assertEqual(
            error.physical_dispatches[0]["prompt_set_fallback"], "rung-1"
        )

    def test_prepared_safeguard_failure_keeps_completed_call_accounting(self):
        usage = {
            "input_tokens": 11,
            "cached_input_tokens": 2,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
            "total_tokens": 14,
        }
        cost_payload = {"provider": "accounting-evidence"}

        class AccountingRunner(object):
            def call(self, *_args, **_kwargs):
                return runners.RunnerResult(
                    '{"status":"ok"}',
                    0,
                    2.5,
                    token_usage=usage,
                    cost_payloads=[cost_payload],
                )

        def prepare(_error):
            def validate(_reply):
                raise verifiers.OperationalError(
                    "safeguard source is unavailable"
                )

            return author_calls.PreparedAuthorCall(
                "KIND: implement\nROUTED\n",
                validate,
                "rung-1",
                None,
            )

        with self.assertRaises(verifiers.OperationalError) as caught:
            runners.call_worker(
                AccountingRunner(),
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
            )

        error = caught.exception
        self.assertEqual(error.duration_s, 2.5)
        self.assertEqual(error.token_usage, usage)
        self.assertEqual(error.cost_payloads, [cost_payload])
        self.assertEqual(len(error.physical_dispatches), 1)
        self.assertEqual(
            error.physical_dispatches[0]["prompt_set_fallback"], "rung-1"
        )


if __name__ == "__main__":
    unittest.main()
