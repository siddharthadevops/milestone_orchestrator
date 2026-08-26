"""Focused proof for the reusable direct-author call package."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from orchestrator import author_calls, canonical_plan, contracts
from orchestrator import driver, ledgers
from orchestrator import prompt_sets, runners, staffing, state, tasks
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

    def test_recovery_is_routed_and_unmetered_stabilization_drops_limits(self):
        values = implement_values(self.temp.name)
        del values["soft_lines"]
        del values["hard_lines"]
        values["author_recovery"] = "FORCED CONTROLLED-CUTOFF RECOVERY"

        prepared = self.prepare(values=values)

        self.assertIn(values["author_recovery"], prepared.prompt)
        self.assertNotIn("meters reviewable Git lines", prepared.prompt)
        self.assertEqual(
            prepared.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )

    def test_explicit_null_optional_inputs_are_omitted(self):
        prepared = self.prepare(values=implement_values(
            self.temp.name,
            author_recovery=None,
            soft_lines=None,
            hard_lines=None,
        ))

        self.assertNotIn("None", prepared.prompt)
        self.assertNotIn("meters reviewable Git lines", prepared.prompt)

    def test_absent_runtime_inputs_cannot_be_replaced_by_prompt_defaults(self):
        prompt_sets.ensure_default(self.temp.name)
        shared_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "shared",
            "shared.json",
        )
        with open(shared_path, "r", encoding="utf-8") as handle:
            shared = json.load(handle)
        original_shared = copy.deepcopy(shared)
        invented = {
            "implementation_scope": "INVENTED IMPLEMENTATION SCOPE",
            "author_recovery": "INVENTED RECOVERY",
            "soft_lines": "500",
            "hard_lines": "750",
        }
        for unit_name, names in (
            ("implementation_scope", ("implementation_scope",)),
            ("author_recovery", ("author_recovery",)),
            ("implementation_metering", ("soft_lines", "hard_lines")),
        ):
            declarations = shared["units"][unit_name]["variables"]
            by_name = {item["name"]: item for item in declarations}
            for name in names:
                by_name[name].pop("drop_unit_if_absent")
                by_name[name]["default"] = invented[name]
        with open(shared_path, "w", encoding="utf-8") as handle:
            json.dump(shared, handle)

        values = implement_values(self.temp.name)
        values.pop("soft_lines")
        values.pop("hard_lines")
        prepared = self.prepare(values=values)

        self.assertEqual(
            prepared.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )
        for value in invented.values():
            self.assertNotIn(value, prepared.prompt)
        self.assertNotIn("meters reviewable Git lines", prepared.prompt)

        with open(shared_path, "w", encoding="utf-8") as handle:
            json.dump(original_shared, handle)
        implement_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "milestone",
            "implement.json",
        )
        with open(implement_path, "r", encoding="utf-8") as handle:
            implement = json.load(handle)
        original_implement = copy.deepcopy(implement)
        scope_part = next(
            part for part in implement["instructions"]["parts"]
            if part.get("ref") == "implementation_scope"
        )
        scope_part["defaults"] = {
            "implementation_scope": invented["implementation_scope"]
        }
        with open(implement_path, "w", encoding="utf-8") as handle:
            json.dump(implement, handle)

        fixed_default = self.prepare(values=values)
        self.assertEqual(
            fixed_default.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )
        self.assertNotIn(invented["implementation_scope"], fixed_default.prompt)

        output_default = "INVENTED OUTPUT-CONTRACT SCOPE"
        shared = copy.deepcopy(original_shared)
        common_fields = shared["contract_sections"]["common_fields"]
        common_fields["text"].append(
            "  invented_scope: {{implementation_scope}}"
        )
        common_fields["variables"].append({
            "name": "implementation_scope",
            "required": False,
            "default": output_default,
            "description": "Consumer regression fixture.",
        })
        with open(shared_path, "w", encoding="utf-8") as handle:
            json.dump(shared, handle)
        with open(implement_path, "w", encoding="utf-8") as handle:
            json.dump(original_implement, handle)

        output_contract = self.prepare(values=values)
        self.assertEqual(
            output_contract.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )
        self.assertNotIn(output_default, output_contract.prompt)

        chained_default = "INVENTED CHAINED SCOPE"
        shared = copy.deepcopy(original_shared)
        scope_unit = shared["units"]["implementation_scope"]
        scope_unit["text"] = [
            "{{carrier}} / {{implementation_scope}}"
        ]
        scope_unit["variables"].append({
            "name": "carrier",
            "required": False,
            "default": "unused",
            "description": "Consumer regression fixture.",
        })
        scope_declaration = next(
            item for item in scope_unit["variables"]
            if item["name"] == "implementation_scope"
        )
        scope_declaration.pop("drop_unit_if_absent")
        scope_declaration["default"] = chained_default
        implement = copy.deepcopy(original_implement)
        scope_part = next(
            part for part in implement["instructions"]["parts"]
            if part.get("ref") == "implementation_scope"
        )
        scope_part["defaults"] = {
            "carrier": "{{implementation_scope}}"
        }
        with open(shared_path, "w", encoding="utf-8") as handle:
            json.dump(shared, handle)
        with open(implement_path, "w", encoding="utf-8") as handle:
            json.dump(implement, handle)

        chained = self.prepare(values=values)
        self.assertEqual(
            chained.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )
        self.assertNotIn(chained_default, chained.prompt)

    def test_unmounted_route_default_does_not_reject_current_charge(self):
        prompt_sets.ensure_default(self.temp.name)
        review_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "milestone",
            "review_round.json",
        )
        with open(review_path, "r", encoding="utf-8") as handle:
            review = json.load(handle)
        review["instructions"]["parts"].append({
            "ref": "implementation_scope",
            "defaults": {
                "implementation_scope": "UNRELATED REVIEW DEFAULT",
            },
        })
        with open(review_path, "w", encoding="utf-8") as handle:
            json.dump(review, handle)

        values = implement_values(self.temp.name)
        values.pop("soft_lines")
        values.pop("hard_lines")
        prepared = self.prepare(values=values)

        self.assertIsNone(prepared.prompt_set_fallback)
        self.assertNotIn("UNRELATED REVIEW DEFAULT", prepared.prompt)

    def test_recovery_requires_the_selected_rung_to_mount_its_variable(self):
        prompt_sets.ensure_default(self.temp.name)
        root = prompt_sets.prompt_set_dir(self.temp.name, "default")
        shared_path = os.path.join(root, "shared", "shared.json")
        with open(shared_path, "r", encoding="utf-8") as handle:
            shared = json.load(handle)
        del shared["units"]["author_recovery"]
        with open(shared_path, "w", encoding="utf-8") as handle:
            json.dump(shared, handle)
        for name in ("draft_skeleton", "draft_slice_note", "implement"):
            path = os.path.join(root, "milestone", name + ".json")
            with open(path, "r", encoding="utf-8") as handle:
                job = json.load(handle)
            job["instructions"]["parts"] = [
                part for part in job["instructions"]["parts"]
                if part.get("ref") != "author_recovery"
            ]
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(job, handle)

        prepared = self.prepare(values=implement_values(
            self.temp.name,
            author_recovery="IMPLEMENTATION RULES",
        ))

        self.assertEqual(
            prepared.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_SEED,
        )

    def test_custom_meter_wording_keeps_the_selected_prompt_rung(self):
        prompt_sets.ensure_default(self.temp.name)
        shared_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "shared",
            "shared.json",
        )
        with open(shared_path, "r", encoding="utf-8") as handle:
            shared = json.load(handle)
        metering = shared["units"]["implementation_metering"]["text"]
        metering[1] = "  expect a soft-close request near {{soft_lines}}"
        metering[2] = "  and a firm stop once {{hard_lines}} is crossed."
        with open(shared_path, "w", encoding="utf-8") as handle:
            json.dump(shared, handle)

        prepared = self.prepare()

        self.assertIsNone(prepared.prompt_set_fallback)
        self.assertIn("soft-close request near 41", prepared.prompt)
        self.assertIn("firm stop once 63", prepared.prompt)

    def test_continuation_falls_past_stored_set_that_omits_part_scope(self):
        prompt_sets.ensure_default(self.temp.name)
        implement_path = os.path.join(
            prompt_sets.prompt_set_dir(self.temp.name, "default"),
            "milestone",
            "implement.json",
        )
        with open(implement_path, "r", encoding="utf-8") as handle:
            stored_implement = json.load(handle)
        stored_implement["instructions"]["parts"] = [
            part for part in stored_implement["instructions"]["parts"]
            if part.get("ref") != "implementation_scope"
        ]
        with open(implement_path, "w", encoding="utf-8") as handle:
            json.dump(stored_implement, handle)
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


class DriverAuthorActivationTest(unittest.TestCase):
    def test_skeleton_dispatch_uses_router_and_persists_plan_adoption(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-driver-") as ws, \
                tempfile.TemporaryDirectory(prefix="orch-author-home-") as home:
            subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=ws, check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=ws, check=True,
            )
            with open(os.path.join(ws, "README"), "w", encoding="utf-8") as fh:
                fh.write("seed\n")
            subprocess.run(["git", "add", "README"], cwd=ws, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "seed"], cwd=ws, check=True
            )
            config = driver.load_config(None)
            driver.merge_config(config, {
                "git": {"enabled": True}, "docs_dir": "milestone",
            })
            state_path = driver.init_run(
                "Build one slice.", ws, config=config,
                model_profiles_home=home,
                prompt_set="missing",
            )
            skeleton_path = ledgers.skeleton_path(state.load(state_path))

            def write_plan(workspace):
                path = os.path.join(workspace, skeleton_path)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                payload = {"slices": [{
                    "id": 1, "title": "One", "intent": "Build one thing.",
                    "producer_task_executor": {
                        "draft_slice_note": "agent_call",
                        "implement": "agent_call",
                    },
                }]}
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(
                        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                        % json.dumps(payload)
                    )

            reply = {
                "status": "ok", "kind": "draft_skeleton",
                "artifact": skeleton_path,
                "questions": [
                    {"id": name, "answer": "Checked."}
                    for name in (
                        "due_diligence_count", "machinery_trust",
                        "environment_fit", "human_scale",
                        "guarantee_fit", "cheapest_sufficient",
                        "rare_failure_posture",
                    )
                ],
            }
            runner = runners.MockRunner([{
                "expect_kind": "draft_skeleton",
                "side_effect": write_plan,
                "response": reply,
            }])
            driver.Driver(
                state_path, runner=runner, model_profiles_home=home
            ).step()

            persisted = state.load(state_path)
            self.assertEqual(runner.calls[0][2].splitlines()[:2], [
                "KIND: draft_skeleton", "WORKSPACE: %s" % ws,
            ])
            self.assertNotIn("FAMILY:", runner.calls[0][2])
            self.assertIn(
                "This set replaces every mutable operator amendment shown "
                "earlier.",
                runner.calls[0][2],
            )
            self.assertIn(
                "CURRENT MUTABLE OPERATOR AMENDMENTS: none.",
                runner.calls[0][2],
            )
            self.assertEqual(
                [item["id"] for item in persisted["milestone"]["slices"]],
                [1],
            )
            self.assertIn("canonical_plan_anchor", persisted["milestone"])
            fallback = prompt_sets.PROMPT_SET_FALLBACK_DEFAULT
            self.assertEqual(
                persisted["units"][0]["draft"]["prompt_set_fallback"],
                fallback,
            )
            self.assertEqual(
                persisted["tasks"][0]["result"]["prompt_set_fallback"],
                fallback,
            )
            draft_event = next(
                event for event in persisted["events"]
                if event["type"] == "draft_recorded"
            )
            self.assertEqual(draft_event["prompt_set_fallback"], fallback)
            projected = state.summary(persisted)["units"][0]
            self.assertEqual(
                projected["draft"]["prompt_set_fallback"], fallback
            )
            self.assertEqual(
                projected["drafts"][0]["prompt_set_fallback"], fallback
            )

    def test_first_anchor_reselects_before_dispatching_a_stale_unit(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-order-") as ws, \
                tempfile.TemporaryDirectory(prefix="orch-author-home-") as home:
            subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=ws,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=ws,
                check=True,
            )
            config = driver.load_config(None)
            driver.merge_config(config, {
                "git": {"enabled": True}, "docs_dir": "milestone",
            })
            state_path = driver.init_run(
                "Build two slices.", ws, config=config,
                model_profiles_home=home,
            )
            persisted = state.load(state_path)
            skeleton_path = ledgers.skeleton_path(persisted)
            plan = {
                "slices": [
                    {
                        "id": slice_id,
                        "title": "Slice %d" % slice_id,
                        "intent": "Build slice %d." % slice_id,
                        "producer_task_executor": {
                            "draft_slice_note": "agent_call",
                            "implement": "agent_call",
                        },
                    }
                    for slice_id in (1, 2)
                ]
            }
            path = os.path.join(ws, skeleton_path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                    % json.dumps(plan)
                )
            subprocess.run(
                ["git", "add", skeleton_path], cwd=ws, check=True
            )
            subprocess.run(
                ["git", "commit", "-qm", "reviewed skeleton"],
                cwd=ws,
                check=True,
            )

            persisted["milestone"]["slices"] = [plan["slices"][1]]
            skeleton = persisted["units"][0]
            skeleton["status"] = state.U_SEALED
            skeleton["artifact"] = skeleton_path
            state.ensure_next_unit(persisted)
            state.save(state_path, persisted)

            runner = runners.MockRunner([])
            action, note = driver.Driver(
                state_path, runner=runner, model_profiles_home=home
            ).step()

            self.assertEqual(action.type, driver.A_DRAFT)
            self.assertEqual(
                note, "canonical plan established; work order refreshed"
            )
            reloaded = state.load(state_path)
            self.assertEqual(runner.calls, [])
            self.assertEqual(
                state.unit_identity(state.current_unit(reloaded)),
                (state.UNIT_SLICE_DOC, 1, None),
            )
            self.assertEqual(reloaded.get("tasks", []), [])

    def test_plan_drift_blocks_before_dispatch_without_worker_classification(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-drift-") as ws, \
                tempfile.TemporaryDirectory(prefix="orch-author-home-") as home:
            subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=ws,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=ws,
                check=True,
            )
            config = driver.load_config(None)
            driver.merge_config(config, {
                "git": {"enabled": True}, "docs_dir": "milestone",
            })
            state_path = driver.init_run(
                "Build one slice.", ws, config=config,
                model_profiles_home=home,
            )
            persisted = state.load(state_path)
            skeleton_path = ledgers.skeleton_path(persisted)

            def write_plan(title):
                payload = {"slices": [{
                    "id": 1,
                    "title": title,
                    "intent": "Build one thing.",
                    "producer_task_executor": {
                        "draft_slice_note": "agent_call",
                        "implement": "agent_call",
                    },
                }]}
                path = os.path.join(ws, skeleton_path)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(
                        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                        % json.dumps(payload)
                    )

            write_plan("Anchored")
            subprocess.run(
                ["git", "add", skeleton_path], cwd=ws, check=True
            )
            subprocess.run(
                ["git", "commit", "-qm", "anchor plan"], cwd=ws, check=True
            )
            canonical_plan.establish_current_plan(persisted, skeleton_path)
            state.save(state_path, persisted)
            write_plan("Drifted")

            runner = runners.MockRunner([])
            active = driver.Driver(
                state_path, runner=runner, model_profiles_home=home
            )

            def unexpected_classifier(*_args, **_kwargs):
                self.fail("pre-dispatch plan drift reached failure classification")

            active._classify_failure = unexpected_classifier
            action, _note = active.step()

            self.assertEqual(action.type, driver.A_DRAFT)
            reloaded = state.load(state_path)
            self.assertEqual(runner.calls, [])
            self.assertEqual(
                reloaded["failure"]["type"], "canonical_plan_boundary"
            )
            self.assertFalse(any(
                event["type"] in (
                    "worker_malformed", "error_classifier_call"
                )
                for event in reloaded["events"]
            ))
            self.assertIsNone(reloaded["tasks"][0]["result"])


class DriverAuthorFindingRegressionTest(unittest.TestCase):
    @staticmethod
    def _projected_slice(slice_id, intent="Exercise attribution."):
        return {
            "id": slice_id,
            "title": "Slice %d" % slice_id,
            "intent": intent,
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "agent_call"},
            },
        }

    def _subject(self, workspace, runner):
        config = driver.load_config(None)
        driver.merge_config(config, {
            "git": {"enabled": False},
            "error_classifier": False,
            "infra_retry_backoff_s": [],
        })
        state_path = driver.init_run(
            "Exercise one author call.", workspace, config=config
        )
        return state_path, driver.Driver(state_path, runner=runner)

    def test_repaired_and_failed_attempts_persist_each_fallback(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-fallback-") as ws:
            repaired_runner = runners.MockRunner([
                {"expect_kind": "implement", "response": {"attempt": 1}},
                {"expect_kind": "implement", "response": {"attempt": 2}},
            ])
            _path, subject = self._subject(ws, repaired_runner)
            attempts = []

            def prepare_repair(_error):
                attempt = len(attempts) + 1
                attempts.append(attempt)

                def validate(reply):
                    if reply.get("attempt") != 2:
                        raise contracts.ContractError("repair required")
                    return reply

                return author_calls.PreparedAuthorCall(
                    "KIND: implement\nATTEMPT: %d\n" % attempt,
                    validate,
                    "rung-%d" % attempt,
                    None,
                )

            _output, result, _raw_path = subject._call(
                "codex",
                "legacy prompt",
                contracts.KIND_IMPLEMENT,
                "repair-fallback",
                prepare_call=prepare_repair,
            )
            repaired = next(
                event for event in subject.state["events"]
                if event["type"] == "worker_malformed"
            )
            self.assertEqual(repaired["prompt_set_fallback"], "rung-1")
            self.assertEqual(result.prompt_set_fallback, "rung-2")
            self.assertEqual(
                subject._read_busy()["prompt_set_fallback"], "rung-2"
            )
            subject._clear_busy()

        with tempfile.TemporaryDirectory(prefix="orch-author-fatal-") as ws:
            failed_runner = runners.MockRunner([
                {"expect_kind": "implement", "response": {"attempt": 1}},
                {"expect_kind": "implement", "response": {"attempt": 2}},
            ])
            _path, subject = self._subject(ws, failed_runner)
            attempts = []

            def prepare_failure(_error):
                attempt = len(attempts) + 1
                attempts.append(attempt)
                return author_calls.PreparedAuthorCall(
                    "KIND: implement\nATTEMPT: %d\n" % attempt,
                    lambda _reply: (_ for _ in ()).throw(
                        contracts.ContractError("invalid attempt")
                    ),
                    "rung-%d" % attempt,
                    None,
                )

            subject._classify_failure = lambda *_args, **_kwargs: (
                "protocol", None, "deterministic test classification"
            )
            with self.assertRaises(driver.StopStep):
                subject._call(
                    "codex",
                    "legacy prompt",
                    contracts.KIND_IMPLEMENT,
                    "fatal-fallback",
                    prepare_call=prepare_failure,
                )
            fatal = next(
                event for event in subject.state["events"]
                if event["type"] == "worker_malformed" and event["fatal"]
            )
            self.assertEqual(
                [
                    dispatch["prompt_set_fallback"]
                    for dispatch in fatal["physical_dispatches"]
                ],
                ["rung-1", "rung-2"],
            )

    def test_rejected_plan_boundary_cannot_enter_infrastructure_retry(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-boundary-") as ws:
            runner = runners.MockRunner([
                {
                    "expect_kind": "implement",
                    "response": {"status": "ok", "note": "network error"},
                },
                {
                    "expect_kind": "implement",
                    "response": {"status": "ok", "note": "network error"},
                },
            ])
            _path, subject = self._subject(ws, runner)
            subject.config["infra_retry_backoff_s"] = [0]

            def reject_plan():
                raise canonical_plan.CanonicalPlanError(
                    "invalid canonical block"
                )

            prepared = author_calls.PreparedAuthorCall(
                "KIND: implement\nROUTED\n",
                lambda reply: reply,
                "rung-1",
                None,
                reject_plan,
            )

            with self.assertRaises(driver.StopStep):
                subject._call(
                    "codex",
                    "legacy prompt",
                    contracts.KIND_IMPLEMENT,
                    "rejected-plan-boundary",
                    prepare_call=lambda _error: prepared,
                )

            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(
                subject.state["failure"]["type"], "canonical_plan_boundary"
            )
            self.assertIsNone(subject.state["failure"].get("resume_at"))
            self.assertFalse(any(
                event["type"] in ("infra_retry", "error_classifier_call")
                for event in subject.state["events"]
            ))

    def test_rejected_plan_boundary_overrides_accepted_size_interruption(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-boundary-") as ws:
            interruptions = []
            persisted = []

            class InterruptedRunner(object):
                def __init__(self):
                    self.calls = 0

                def call(
                    self, _family, _prompt, _workspace, model=None,
                    effort=None, active_control=None,
                ):
                    del model, effort
                    self.calls += 1
                    active_control._bind(
                        lambda _text: True,
                        lambda _reason: True,
                    )
                    self.assert_interrupted = active_control.interrupt(
                        "implementation hard limit reached"
                    )
                    active_control._close()
                    return runners.RunnerResult(
                        '{"status":"ok"}', 0, 0.01
                    )

            runner = InterruptedRunner()
            _path, subject = self._subject(ws, runner)
            unit = state.current_unit(subject.state)
            cutoff_marker = {
                "episode_id": "rejected-plan-cutoff",
                "soft_lines": 500,
                "hard_lines": 750,
            }

            def persist_interrupt(reason):
                interruptions.append(reason)
                subject._persist_implementation_stabilization(
                    cutoff_marker,
                    interrupt_reason=reason,
                    unit=unit,
                )
                persisted.append("implementation_stabilization" in unit)

            control = runners.ActiveCallControl(
                on_interrupt=persist_interrupt
            )

            def reject_plan():
                raise canonical_plan.CanonicalPlanError(
                    "invalid canonical block"
                )

            prepared = author_calls.PreparedAuthorCall(
                "KIND: implement\nROUTED\n",
                lambda reply: reply,
                "rung-1",
                None,
                reject_plan,
            )

            with self.assertRaises(driver.StopStep):
                subject._call(
                    "codex",
                    "legacy prompt",
                    contracts.KIND_IMPLEMENT,
                    "interrupted-rejected-plan-boundary",
                    active_control=control,
                    prepare_call=lambda _error: prepared,
                    episode_unit=unit,
                    cutoff_marker=cutoff_marker,
                )

            self.assertTrue(runner.assert_interrupted)
            self.assertEqual(interruptions, [
                "implementation hard limit reached"
            ])
            self.assertEqual(persisted, [True])
            self.assertEqual(runner.calls, 1)
            self.assertEqual(
                subject.state["failure"]["type"], "canonical_plan_boundary"
            )
            self.assertNotIn("implementation_stabilization", unit)
            self.assertFalse(any(
                event.get("controlled_interruption")
                for event in subject.state["events"]
            ))

    def test_inserted_unit_does_not_inherit_author_failure_history(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-owner-") as ws:
            runner = runners.MockRunner([
                {"expect_kind": "implement", "response": {"attempt": 1}},
                {"expect_kind": "implement", "response": {"attempt": 2}},
            ])
            _path, subject = self._subject(ws, runner)

            skeleton = state.current_unit(subject.state)
            skeleton["status"] = state.U_SEALED
            subject.state["milestone"]["slices"] = [self._projected_slice(2)]
            origin = state.ensure_next_unit(subject.state)
            subject.state["milestone"]["slices"] = [
                self._projected_slice(3), self._projected_slice(2),
            ]
            inserted = state.ensure_due_unit(subject.state)
            self.assertIs(state.current_unit(subject.state), inserted)

            prepared = author_calls.PreparedAuthorCall(
                "KIND: implement\nROUTED\n",
                lambda _reply: (_ for _ in ()).throw(
                    contracts.ContractError("invalid attempt")
                ),
                "rung",
                None,
            )
            subject._classify_failure = lambda *_args, **_kwargs: (
                "protocol", None, "deterministic test classification"
            )

            with self.assertRaises(driver.StopStep):
                subject._call(
                    "codex",
                    "legacy prompt",
                    contracts.KIND_IMPLEMENT,
                    "inserted-owner",
                    prepare_call=lambda _error: prepared,
                    episode_unit=origin,
                )

            fatal = next(
                event for event in reversed(subject.state["events"])
                if event["type"] == "worker_malformed" and event["fatal"]
            )
            self.assertEqual(fatal["unit"], state.unit_key(origin))
            self.assertEqual(
                subject.state["failure"]["unit"], state.unit_key(origin)
            )
            self.assertEqual(origin["status"], state.U_FAILED)
            self.assertEqual(inserted["status"], state.U_PENDING)

    def test_accounted_author_marker_keeps_owner_after_plan_reorder(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-owner-") as ws:
            state_path, subject = self._subject(ws, runners.MockRunner([]))

            skeleton = state.current_unit(subject.state)
            skeleton["status"] = state.U_SEALED
            subject.state["milestone"]["slices"] = [self._projected_slice(
                2, "Exercise restart attribution."
            )]
            origin = state.ensure_next_unit(subject.state)
            task = subject._admit_worker_task(
                origin,
                contracts.KIND_DRAFT_SLICE_NOTE,
                "frozen author prompt",
                "codex",
            )
            self.assertTrue(subject._mark_busy(
                "slice_doc-02-draft",
                contracts.KIND_DRAFT_SLICE_NOTE,
                "codex",
                task_id=task["id"],
            ))
            subject.state["milestone"]["slices"] = [
                self._projected_slice(3, "Exercise restart attribution."),
                self._projected_slice(2, "Exercise restart attribution."),
            ]
            inserted = state.ensure_due_unit(subject.state)
            subject._save()
            completed = runners.RunnerResult(
                "{}", 0, 2.5,
                token_usage={
                    "input_tokens": 10,
                    "cached_input_tokens": 0,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            )
            self.assertTrue(subject._update_busy_accounting(completed))

            restarted = driver.Driver(
                state_path, runner=runners.MockRunner([])
            )

            interrupted = next(
                event for event in restarted.state["events"]
                if event["type"] == "worker_interrupted"
            )
            self.assertEqual(interrupted["unit"], state.unit_key(origin))
            self.assertEqual(interrupted["task_id"], task["id"])
            self.assertEqual(interrupted["duration_s"], 2.5)
            reloaded_origin = next(
                unit for unit in restarted.state["units"]
                if state.unit_identity(unit) == state.unit_identity(origin)
            )
            reloaded_inserted = next(
                unit for unit in restarted.state["units"]
                if state.unit_identity(unit) == state.unit_identity(inserted)
            )
            self.assertEqual(reloaded_origin["status"], state.U_PENDING)
            self.assertEqual(reloaded_inserted["status"], state.U_PENDING)

    def test_durable_failed_author_attempt_is_not_accounted_twice(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-accounted-") as ws:
            state_path, subject = self._subject(ws, runners.MockRunner([]))

            skeleton = state.current_unit(subject.state)
            skeleton["status"] = state.U_SEALED
            subject.state["milestone"]["slices"] = [self._projected_slice(2)]
            unit = state.ensure_next_unit(subject.state)
            kind = contracts.KIND_DRAFT_SLICE_NOTE
            task = subject._admit_worker_task(
                unit, kind, "frozen author prompt", "codex"
            )
            self.assertTrue(subject._mark_busy(
                "slice_doc-02-draft",
                kind,
                "codex",
                task_id=task["id"],
            ))
            completed = runners.RunnerResult(
                "{}", 0, 2.5,
                token_usage={
                    "input_tokens": 10,
                    "cached_input_tokens": 0,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            )
            self.assertTrue(subject._update_busy_accounting(completed))
            state.append_event(
                subject.state,
                "worker_malformed",
                unit=state.unit_key(unit),
                label="slice_doc-02-draft",
                kind=kind,
                family="codex",
                fatal=False,
                stabilizer_retry=True,
                duration_s=completed.duration_s,
                token_usage=completed.token_usage,
                token_usage_partial=False,
                cost=completed.cost,
                cost_partial=completed.cost_partial,
                task_id=task["id"],
            )
            subject._save()

            restarted = driver.Driver(
                state_path, runner=runners.MockRunner([])
            )

            self.assertFalse(any(
                event["type"] == "worker_interrupted"
                for event in restarted.state["events"]
            ))
            accounting = tasks.task_accounting(restarted.state, task["id"])
            self.assertEqual(accounting["token_usage"]["total_tokens"], 12)
            self.assertEqual(accounting["duration_s"], 2.5)
            self.assertIsNotNone(restarted._active_worker_task(unit, kind))

    def test_author_dispatch_staffing_failure_keeps_episode_owner(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-owner-") as ws, \
                tempfile.TemporaryDirectory(prefix="orch-author-home-") as home:
            config = driver.load_config(None)
            driver.merge_config(config, {
                "git": {"enabled": False},
                "error_classifier": False,
                "infra_retry_backoff_s": [],
            })
            state_path = driver.init_run(
                "Exercise author staffing ownership.",
                ws,
                config=config,
                model_profiles_home=home,
            )
            subject = driver.Driver(
                state_path,
                runner=runners.MockRunner([]),
                model_profiles_home=home,
            )

            skeleton = state.current_unit(subject.state)
            skeleton["status"] = state.U_SEALED
            subject.state["milestone"]["slices"] = [self._projected_slice(
                2, "Exercise staffing attribution."
            )]
            origin = state.ensure_next_unit(subject.state)
            kind = contracts.KIND_DRAFT_SLICE_NOTE
            subject._admit_worker_task(
                origin, kind, "frozen author prompt", "codex"
            )
            subject.state["milestone"]["slices"] = [
                self._projected_slice(3, "Exercise staffing attribution."),
                self._projected_slice(2, "Exercise staffing attribution."),
            ]
            inserted = state.ensure_due_unit(subject.state)
            subject._save()
            resolver = subject._dispatch_for_worker_kind(origin, kind)
            condition = staffing.StaffingConditionError(
                staffing.STAFFING_UNAVAILABLE,
                "no configured family is available",
            )

            with mock.patch.object(
                staffing, "resolve", side_effect=condition
            ), self.assertRaises(driver.StopStep):
                resolver()

            reloaded = state.load(state_path)
            failed_origin = next(
                unit for unit in reloaded["units"]
                if state.unit_identity(unit) == state.unit_identity(origin)
            )
            pending_inserted = next(
                unit for unit in reloaded["units"]
                if state.unit_identity(unit) == state.unit_identity(inserted)
            )
            self.assertEqual(
                reloaded["failure"]["unit"], state.unit_key(origin)
            )
            self.assertEqual(failed_origin["status"], state.U_FAILED)
            self.assertEqual(failed_origin["failed_from"], state.U_PENDING)
            self.assertEqual(pending_inserted["status"], state.U_PENDING)

    def test_nonfatal_stabilizer_retry_persists_each_fallback(self):
        with tempfile.TemporaryDirectory(
            prefix="orch-author-stabilizer-fallback-"
        ) as workspace:
            runner = runners.MockRunner([
                {"expect_kind": "implement", "response": {"attempt": 1}},
                {"expect_kind": "implement", "response": {"attempt": 2}},
                {"expect_kind": "implement", "response": {"attempt": 3}},
            ])
            _path, subject = self._subject(workspace, runner)
            attempts = []

            def prepare(_error):
                attempt = len(attempts) + 1
                attempts.append(attempt)

                def validate(reply):
                    if reply.get("attempt") < 3:
                        raise contracts.ContractError("invalid attempt")
                    return reply

                return author_calls.PreparedAuthorCall(
                    "KIND: implement\nATTEMPT: %d\n" % attempt,
                    validate,
                    "rung-%d" % attempt,
                    None,
                )

            output, result, _raw_path = subject._call(
                "codex",
                "legacy prompt",
                contracts.KIND_IMPLEMENT,
                "stabilizer-fallback",
                repeat_protocol=True,
                prepare_call=prepare,
            )

            self.assertEqual(output, {"attempt": 3})
            incident = next(
                event for event in subject.state["events"]
                if event.get("stabilizer_retry")
            )
            self.assertFalse(incident["fatal"])
            self.assertEqual(
                [
                    dispatch["prompt_set_fallback"]
                    for dispatch in incident["physical_dispatches"]
                ],
                ["rung-1", "rung-2"],
            )
            self.assertEqual(result.prompt_set_fallback, "rung-3")

    def test_rethink_origin_persists_its_fallback_sidecar(self):
        with tempfile.TemporaryDirectory(prefix="orch-author-rethink-") as ws:
            subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=ws,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=ws,
                check=True,
            )
            with open(os.path.join(ws, "seed.txt"), "w", encoding="utf-8") as handle:
                handle.write("seed\n")
            subprocess.run(["git", "add", "seed.txt"], cwd=ws, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "baseline"], cwd=ws, check=True
            )
            state_path, subject = self._subject(ws, runners.MockRunner([]))
            result = runners.RunnerResult("{}", 0, 1.0)
            result.prompt_set_fallback = "rung-1"
            result.session_ref = "provider-session"
            checked = {
                "status": "need_rethink",
                "kind": contracts.KIND_IMPLEMENT,
                "request": "Resolve one bounded question.",
                "finding": {"id": "F1", "summary": "Question"},
                "target_path": "proposal.md",
                "max_rounds": 20,
                "result_mode": "proposal",
            }
            created = {
                "id": "bs-fallback",
                "state": {
                    "completed_turns": [],
                    "rounds_used": 0,
                    "recovery_baseline_revision": "baseline",
                    "accepted_target_revision": None,
                },
            }
            with mock.patch.object(
                driver.brainstorming_milestone,
                "validate_origin_signal",
                return_value=checked,
            ), mock.patch.object(
                driver.brainstorming_milestone,
                "create_session",
                return_value=created,
            ):
                subject._start_rethink(
                    state.current_unit(subject.state),
                    contracts.KIND_IMPLEMENT,
                    "codex",
                    None,
                    None,
                    checked,
                    result,
                    "raw/origin.txt",
                    "origin",
                )

            reloaded = state.load(state_path)
            origin = next(
                event for event in reloaded["events"]
                if event["type"] == "brainstorming_origin_recorded"
            )
            self.assertEqual(origin["prompt_set_fallback"], "rung-1")
            self.assertEqual(
                state.current_unit(reloaded)["brainstorming_wait"]["origin"][
                    "prompt_set_fallback"
                ],
                "rung-1",
            )

    def test_preparation_faults_stop_without_worker_incidents_or_classifier(self):
        cases = (
            ("prompt", ValueError("stored prompt is unreadable")),
            ("standing-law", verifiers.PolicyConfigError("policy collision")),
        )
        for label, fault in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix="orch-author-preparation-"
            ) as ws:
                runner = runners.MockRunner([])
                state_path, subject = self._subject(ws, runner)

                def unexpected_classifier(*_args, **_kwargs):
                    self.fail("pre-dispatch preparation reached classification")

                subject._classify_failure = unexpected_classifier

                def prepare(_error):
                    raise fault

                with self.assertRaises(driver.StopStep):
                    subject._call(
                        "codex",
                        "legacy prompt",
                        contracts.KIND_IMPLEMENT,
                        "preparation-fault",
                        prepare_call=prepare,
                    )

                reloaded = state.load(state_path)
                self.assertEqual(reloaded["failure"]["type"], "orchestrator")
                self.assertIn(str(fault), reloaded["failure"]["reason"])
                self.assertEqual(runner.calls, [])
                self.assertFalse(any(
                    event["type"] in (
                        "worker_malformed",
                        "worker_unaccepted",
                        "error_classifier_call",
                    )
                    for event in reloaded["events"]
                ))


class PhysicalPreparationTest(unittest.TestCase):
    def test_completion_boundary_runs_before_reply_validation(self):
        completed = []

        def prepare(_error):
            def validate(reply):
                self.assertEqual(completed, ["done"])
                return reply

            return author_calls.PreparedAuthorCall(
                "KIND: implement\nROUTED\n",
                validate,
                "rung-1",
                None,
                lambda: completed.append("done"),
            )

        output, _result = runners.call_worker(
            runners.MockRunner([{
                "expect_kind": "implement",
                "response": {"status": "ok"},
            }]),
            "codex",
            "legacy prompt must not dispatch",
            "implement",
            "/workspace",
            prepare_call=prepare,
        )

        self.assertEqual(output, {"status": "ok"})
        self.assertEqual(completed, ["done"])

    def test_completion_rejection_keeps_physical_call_evidence(self):
        usage = {
            "input_tokens": 7,
            "cached_input_tokens": 1,
            "output_tokens": 2,
            "reasoning_output_tokens": 0,
            "total_tokens": 9,
        }

        class AccountingRunner(object):
            def call(self, *_args, **_kwargs):
                return runners.RunnerResult(
                    '{"status":"ok"}', 0, 1.5,
                    token_usage=usage,
                    cost_payloads=[{"provider": "evidence"}],
                )

        def reject():
            error = ValueError("invalid canonical block")
            error.call_boundary_failure = True
            raise error

        prepared = author_calls.PreparedAuthorCall(
            "KIND: implement\nROUTED\n",
            lambda reply: reply,
            "rung-1",
            None,
            reject,
        )
        with self.assertRaises(runners.RunnerError) as caught:
            runners.call_worker(
                AccountingRunner(),
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=lambda _error: prepared,
            )

        error = caught.exception
        self.assertTrue(error.provider_dispatch_started)
        self.assertTrue(error.call_boundary_failure)
        self.assertEqual(error.token_usage, usage)
        self.assertEqual(error.prompt_set_fallback, "rung-1")
        self.assertEqual(len(error.physical_dispatches), 1)

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

    def test_rejecting_repair_completion_keeps_both_attempts(self):
        first_usage = {
            "input_tokens": 7,
            "cached_input_tokens": 1,
            "output_tokens": 2,
            "reasoning_output_tokens": 0,
            "total_tokens": 9,
        }
        repair_usage = {
            "input_tokens": 5,
            "cached_input_tokens": 0,
            "output_tokens": 1,
            "reasoning_output_tokens": 0,
            "total_tokens": 6,
        }

        class RejectingRepairRunner(object):
            def __init__(self):
                self.calls = 0

            def call(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return runners.RunnerResult(
                        '{"attempt":1}', 0, 1.5,
                        token_usage=first_usage,
                        cost_payloads=[{"provider": "first"}],
                    )
                error = runners.RunnerError("repair transport failed")
                error.raw_texts = ['{"repair":"transport failure"}']
                error.duration_s = 2.0
                error.token_usage = repair_usage
                error.token_usage_partial = False
                error.cost_payloads = [{"provider": "repair"}]
                raise error

        attempts = []

        def prepare(_error):
            attempt = len(attempts) + 1
            attempts.append(attempt)

            def validate(_reply):
                raise contracts.ContractError("invalid attempt")

            def complete():
                if attempt == 2:
                    raise ValueError("repair repository rejected")

            return author_calls.PreparedAuthorCall(
                "KIND: implement\nATTEMPT: %d\n" % attempt,
                validate,
                "rung-%d" % attempt,
                None,
                complete,
            )

        with self.assertRaisesRegex(
            runners.RunnerError, "repair repository rejected"
        ) as caught:
            runners.call_worker(
                RejectingRepairRunner(),
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
            )

        error = caught.exception
        self.assertEqual(error.raw_texts, [
            '{"attempt":1}',
            '{"repair":"transport failure"}',
        ])
        self.assertEqual(len(error.physical_dispatches), 2)
        self.assertEqual(
            [
                dispatch["prompt_set_fallback"]
                for dispatch in error.physical_dispatches
            ],
            ["rung-1", "rung-2"],
        )
        self.assertEqual(error.duration_s, 3.5)
        self.assertEqual(error.token_usage, {
            "input_tokens": 12,
            "cached_input_tokens": 1,
            "output_tokens": 3,
            "reasoning_output_tokens": 0,
            "total_tokens": 15,
        })
        self.assertFalse(error.token_usage_partial)
        self.assertEqual(error.cost_payloads, [
            {"provider": "first"},
            {"provider": "repair"},
        ])

    def test_non_runner_repair_exception_still_completes_the_attempt(self):
        repair_usage = {
            "input_tokens": 5,
            "cached_input_tokens": 1,
            "output_tokens": 2,
            "reasoning_output_tokens": 0,
            "total_tokens": 7,
        }

        def fail_adapter(_workspace):
            error = ValueError("provider adapter interrupted")
            error.duration_s = 2.0
            error.token_usage = repair_usage
            error.token_usage_partial = False
            error.cost_payloads = [{"provider": "repair evidence"}]
            raise error

        runner = runners.MockRunner([
            {"expect_kind": "implement", "response": {"attempt": 1}},
            {
                "expect_kind": "implement",
                "side_effect": fail_adapter,
                "response": "unreachable",
            },
        ])
        completed = []
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
                lambda: completed.append(attempt),
            )

        with self.assertRaisesRegex(
            ValueError, "provider adapter interrupted"
        ) as caught:
            runners.call_worker(
                runner,
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
            )

        self.assertEqual(completed, [1, 2])
        error = caught.exception
        self.assertEqual(len(error.physical_dispatches), 2)
        self.assertEqual(
            [
                dispatch["prompt_set_fallback"]
                for dispatch in error.physical_dispatches
            ],
            ["rung-1", "rung-2"],
        )
        self.assertEqual(error.duration_s, 2.01)
        self.assertEqual(error.token_usage, repair_usage)
        self.assertTrue(error.token_usage_partial)
        self.assertEqual(
            error.cost_payloads,
            [None, {"provider": "repair evidence"}],
        )

    def test_verifier_repair_exception_keeps_both_attempts_accounting(self):
        repair_usage = {
            "input_tokens": 8,
            "cached_input_tokens": 2,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
            "total_tokens": 11,
        }

        def fail_verifier(_workspace):
            error = verifiers.OperationalError("repair policy unavailable")
            error.duration_s = 1.0
            error.token_usage = repair_usage
            error.token_usage_partial = False
            error.cost_payloads = [{"provider": "verifier repair"}]
            raise error

        runner = runners.MockRunner([
            {"expect_kind": "implement", "response": {"attempt": 1}},
            {
                "expect_kind": "implement",
                "side_effect": fail_verifier,
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
                lambda: None,
            )

        with self.assertRaisesRegex(
            verifiers.OperationalError, "repair policy unavailable"
        ) as caught:
            runners.call_worker(
                runner,
                "codex",
                "legacy prompt must not dispatch",
                "implement",
                "/workspace",
                prepare_call=prepare,
            )

        error = caught.exception
        self.assertEqual(len(error.physical_dispatches), 2)
        self.assertEqual(
            [
                dispatch["prompt_set_fallback"]
                for dispatch in error.physical_dispatches
            ],
            ["rung-1", "rung-2"],
        )
        self.assertEqual(error.duration_s, 1.01)
        self.assertEqual(error.token_usage, repair_usage)
        self.assertTrue(error.token_usage_partial)
        self.assertEqual(
            error.cost_payloads,
            [None, {"provider": "verifier repair"}],
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
