"""Focused proof for the reusable direct-judgment call package."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import canonical_plan, contracts, driver, judgment_calls
from orchestrator import prompt_router, prompt_sets, prompts, runners, state
from orchestrator import verifiers


JOBS = (
    "review_round@skeleton",
    "review_round@slice_doc",
    "review_round@slice_impl",
    "delta_review@skeleton",
    "delta_review@slice_doc",
    "delta_review@slice_impl",
    "fix_findings@skeleton",
    "fix_findings@slice_doc",
    "fix_findings@slice_impl",
    "reclassify@doc",
)


def values_for(workspace, job):
    kind = job.split("@", 1)[0]
    values = {
        "kind": kind,
        "workspace": workspace,
        "goal_path": "implementation/milestones/router/goal.md",
        "skeleton_path": "implementation/milestones/router/skeleton.md",
    }
    if kind == "review_round":
        values["task"] = "full review of the selected milestone unit"
        if not job.endswith("@skeleton"):
            values.update({
                "target": "the selected artifact and governed code",
                "reference_path": (
                    "implementation/milestones/router/slice-06.md"
                ),
            })
    elif kind == "delta_review":
        values["delta_base_revision"] = "a" * 40
        if not job.endswith("@skeleton"):
            values["reference_path"] = (
                "implementation/milestones/router/slice-06.md"
            )
    elif kind == "fix_findings":
        if not job.endswith("@skeleton"):
            values.update({
                "task_subject": "the selected milestone unit",
                "editable_path": (
                    "implementation/milestones/router/slice-06.md"
                ),
            })
        values.update({
            "consultation_family": "claude",
            "consultation_command": "consult --family claude",
            "scratch_path": ".orchestrator/scratch/",
        })
    else:
        values = {
            "kind": "reclassify",
            "workspace": workspace,
            "artifact_path": (
                "implementation/milestones/router/slice-06.md"
            ),
            "builders": "the next milestone authors",
            "finding_severity": "P3",
            "finding_id": "F1",
            "finding_summary": "The wording can drift.",
            "finding_plain": "A later author could read the rule wrongly.",
            "finding_example": "An author follows the obsolete sentence.",
        }
    return values


def answers(bound, text="Checked the current artifact and contract."):
    return [
        {"id": question_id, "answer": text}
        for question_id in bound.question_ids
    ]


def policy(field="reuse_evidence"):
    return {
        "id": "reuse-proof",
        "version": 1,
        "enabled": True,
        "scope": {
            "kinds": ["reclassify"],
            "unit_kinds": ["slice_doc"],
        },
        "prompt": "Name the concrete reuse evidence.",
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


def canonical_document(title="One", slice_id=1, material=None):
    slice_plan = {
        "id": slice_id,
        "title": title,
        "intent": "Exercise the routed judgment boundary.",
        "producer_task_executor": {
            "draft_slice_note": "agent_call",
            "implement": "agent_call",
        },
    }
    if material is not None:
        slice_plan["material"] = material
    plan = {"slices": [slice_plan]}
    return (
        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
        % json.dumps(plan, separators=(",", ":"))
    )


class RaisingRunner(object):
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def call(self, family, prompt, workspace, model=None, effort=None):
        self.calls += 1
        raise self.exc


class JudgmentCallPreparationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orch-judgment-")
        self.addCleanup(self.temp.cleanup)

    def prepare(self, job, **changes):
        queued = changes.pop("queued_findings", None)
        options = {
            "job": job,
            "material": (
                "code" if job.endswith("@slice_impl") else "document"
            ),
            "values": values_for(self.temp.name, job),
            "amendments": [],
            "operator_complete": True,
        }
        if job.startswith("fix_findings"):
            options["queued_findings"] = list(queued or ())
        options.update(changes)
        return judgment_calls.prepare(self.temp.name, **options)

    def write_set(self, name, documents):
        directory = Path(prompt_sets.prompt_set_dir(self.temp.name, name))
        for member, document in documents.items():
            path = directory / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding="utf-8")

    def test_exact_judgment_route_matrix_uses_one_bound_charge(self):
        for job in JOBS:
            with self.subTest(job=job):
                prepared = self.prepare(job)
                kind = job.split("@", 1)[0]
                self.assertEqual(prepared.bound.prompt["kind"], kind)
                self.assertEqual(prepared.prompt.splitlines()[:2], [
                    "KIND: %s" % kind,
                    "WORKSPACE: %s" % self.temp.name,
                ])
                self.assertEqual(
                    prepared.prompt_set_fallback,
                    prompt_sets.PROMPT_SET_FALLBACK_SEED,
                )

    def test_registered_judgment_envelopes_validate_without_legacy_fields(self):
        review = self.prepare("review_round@slice_impl")
        review_reply = {
            "status": "ok",
            "kind": "review_round",
            "findings": [],
            "questions": answers(review.bound),
        }
        self.assertEqual(review.validate(copy.deepcopy(review_reply)), review_reply)

        delta = self.prepare("delta_review@slice_doc")
        delta_reply = {
            "status": "ok",
            "kind": "delta_review",
            "findings": [],
            "questions": answers(delta.bound),
        }
        self.assertEqual(delta.validate(copy.deepcopy(delta_reply)), delta_reply)

        fixer = self.prepare("fix_findings@skeleton")
        fix_reply = {
            "status": "ok",
            "kind": "fix_findings",
            "findings": [],
            "files_changed": [],
            "questions": answers(fixer.bound),
        }
        self.assertEqual(fixer.validate(copy.deepcopy(fix_reply)), fix_reply)

        rating = self.prepare("reclassify@doc")
        rating_reply = {
            "status": "ok",
            "kind": "reclassify",
            "drift_risk": "low",
            "drift_damage": "medium",
            "reason": "The ambiguity is visible and locally corrected.",
            "questions": answers(rating.bound),
        }
        self.assertEqual(rating.validate(copy.deepcopy(rating_reply)), rating_reply)

        for field in ("slices", "suite_command"):
            with self.subTest(field=field):
                invalid = dict(review_reply, **{field: "retired"})
                with self.assertRaises(contracts.ContractError):
                    review.validate(invalid)

    def test_provisional_delta_keeps_its_routed_verdict_contract(self):
        correction = {
            "artifact": "implementation/slices/slice-06.md",
            "authority_artifact": "implementation/authority.md",
            "contradiction": "The current note conflicts with its authority.",
            "resolution": "Use the authority's existing boundary.",
        }
        prepared = self.prepare(
            "delta_review@slice_impl", design_correction=correction
        )
        self.assertIn(
            "design_correction_verdict", prepared.bound.registered_section_ids
        )
        self.assertEqual(
            [
                section
                for section in prepared.bound.prompt["output_contract"]
                if section["id"] == "design_correction_verdict"
            ],
            [prompts.design_correction_verdict_section(correction)],
        )
        expected_values = values_for(
            self.temp.name, "delta_review@slice_impl"
        )
        expected_values["operator_amendments"] = (
            judgment_calls._current_amendments([], True)
        )
        self.assertEqual(
            prepared.prompt,
            prompt_router.render(prepared.bound.prompt, expected_values),
        )
        reply = {
            "status": "ok",
            "kind": "delta_review",
            "findings": [],
            "design_correction_verdict": {
                "decision": "ratify",
                "reason": "The cited authority uniquely resolves it.",
            },
            "questions": answers(prepared.bound),
        }
        self.assertEqual(prepared.validate(copy.deepcopy(reply)), reply)
        without_verdict = copy.deepcopy(reply)
        del without_verdict["design_correction_verdict"]
        with self.assertRaises(contracts.ContractError):
            prepared.validate(without_verdict)

    def test_fixer_prompt_and_validator_share_one_frozen_finding_queue(self):
        queued = [{
            "id": "F1",
            "severity": "P2",
            "summary": "The served and validated queues can diverge.",
        }]
        values = values_for(self.temp.name, "fix_findings@slice_impl")
        prepared = self.prepare(
            "fix_findings@slice_impl", values=values, queued_findings=queued
        )
        expected_values = dict(values)
        expected_values.update({
            "operator_amendments": judgment_calls._current_amendments(
                [], True
            ),
            "queued_findings": json.dumps(
                queued, ensure_ascii=False, sort_keys=True, indent=2
            ),
        })
        self.assertEqual(
            prepared.prompt,
            prompt_router.render(prepared.bound.prompt, expected_values),
        )

        queued[0]["id"] = "F2"
        reply = {
            "status": "ok",
            "kind": "fix_findings",
            "findings": [],
            "files_changed": [],
            "questions": answers(prepared.bound),
        }
        with self.assertRaises(contracts.ContractError):
            prepared.validate(reply)

        values["queued_findings"] = "[]"
        with self.assertRaises(ValueError):
            judgment_calls.prepare(
                self.temp.name,
                job="fix_findings@slice_impl",
                material="code",
                values=values,
                amendments=[],
                operator_complete=True,
                queued_findings=[],
            )

    def test_named_rungs_omitting_owned_payloads_fall_as_a_whole(self):
        self.assertTrue(prompt_sets.ensure_default(self.temp.name))
        cases = (
            (
                "review-without-target",
                "review_round@slice_impl",
                lambda document: document["variants"]["target_frame"].__setitem__(
                    "slice_unit",
                    {"text": ["TASK: full review. REPORT ONLY."],
                     "variables": []},
                ),
                {},
            ),
            (
                "delta-without-base",
                "delta_review@slice_doc",
                lambda document: document["variants"]["target_frame"].__setitem__(
                    "slice_unit",
                    {"text": ["TASK: incremental review. REPORT ONLY."],
                     "variables": []},
                ),
                {},
            ),
            (
                "fix-without-queue",
                "fix_findings@slice_impl",
                lambda document: document["instructions"].__setitem__(
                    "parts",
                    [
                        part for part in document["instructions"]["parts"]
                        if not any(
                            variable.get("name") == "queued_findings"
                            for variable in part.get("variables", [])
                        )
                    ],
                ),
                {"queued_findings": [{
                    "id": "F1", "severity": "P2", "summary": "Fix me."
                }]},
            ),
            (
                "fix-without-target",
                "fix_findings@slice_impl",
                lambda document: document["variants"]["target_frame"].__setitem__(
                    "slice_unit",
                    {"text": ["TASK: fix queued findings."],
                     "variables": []},
                ),
                {},
            ),
            (
                "fix-without-consultation",
                "fix_findings@slice_impl",
                lambda document: document["instructions"].__setitem__(
                    "parts",
                    [
                        part for part in document["instructions"]["parts"]
                        if not any(
                            variable.get("name") == "consultation_command"
                            for variable in part.get("variables", [])
                        )
                    ],
                ),
                {},
            ),
            (
                "rating-without-finding",
                "reclassify@doc",
                lambda document: document["instructions"].__setitem__(
                    "parts",
                    [
                        part for part in document["instructions"]["parts"]
                        if not any(
                            variable.get("name") == "finding_id"
                            for variable in part.get("variables", [])
                        )
                    ],
                ),
                {},
            ),
            (
                "rating-without-target",
                "reclassify@doc",
                lambda document: document["instructions"].__setitem__(
                    "parts",
                    [
                        part for part in document["instructions"]["parts"]
                        if not any(
                            variable.get("name") == "artifact_path"
                            for variable in part.get("variables", [])
                        )
                    ],
                ),
                {},
            ),
        )
        for name, job, omit_payload, options in cases:
            with self.subTest(job=job):
                documents = copy.deepcopy(prompt_sets.default_seed().documents)
                kind = job.split("@", 1)[0]
                omit_payload(documents["milestone/%s.json" % kind])
                self.write_set(name, documents)
                self.assertEqual(
                    prompt_sets.load(self.temp.name, name).name, name
                )
                prepared = self.prepare(job, prompt_set=name, **options)
                self.assertEqual(
                    prepared.prompt_set_fallback,
                    prompt_sets.PROMPT_SET_FALLBACK_DEFAULT,
                )
                expected = self.prepare(job, prompt_set="default", **options)
                self.assertEqual(prepared.prompt, expected.prompt)

    def test_named_rungs_without_judgment_envelopes_fall_as_a_whole(self):
        self.assertTrue(prompt_sets.ensure_default(self.temp.name))
        cases = (
            ("review-envelope", "review_round@slice_impl", "review_contract"),
            ("fix-envelope", "fix_findings@slice_impl", "fix_results"),
            ("rating-envelope", "reclassify@doc", "reclassify_result"),
        )
        for name, job, required_section in cases:
            with self.subTest(job=job):
                documents = copy.deepcopy(prompt_sets.default_seed().documents)
                kind = job.split("@", 1)[0]
                document = documents["milestone/%s.json" % kind]
                document["output_contract"]["sections"] = [{
                    "id": "unregistered_judgment_result",
                    "text": ["Return the result as JSON."],
                    "variables": [],
                }]
                self.write_set(name, documents)
                self.assertEqual(
                    prompt_sets.load(self.temp.name, name).name, name
                )

                prepared = self.prepare(job, prompt_set=name)

                self.assertEqual(
                    prepared.prompt_set_fallback,
                    prompt_sets.PROMPT_SET_FALLBACK_DEFAULT,
                )
                self.assertIn(
                    required_section, prepared.bound.registered_section_ids
                )

    def test_named_rung_with_job_incompatible_envelope_falls_as_a_whole(self):
        self.assertTrue(prompt_sets.ensure_default(self.temp.name))
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        fix_result = copy.deepcopy(
            documents["milestone/fix_findings.json"]
            ["output_contract"]["sections"][1]
        )
        documents["milestone/review_round.json"]["output_contract"][
            "sections"
        ].append(fix_result)
        self.write_set("mixed-review-envelope", documents)
        self.assertEqual(
            prompt_sets.load(self.temp.name, "mixed-review-envelope").name,
            "mixed-review-envelope",
        )

        prepared = self.prepare(
            "review_round@slice_impl",
            prompt_set="mixed-review-envelope",
        )

        self.assertEqual(
            prepared.prompt_set_fallback,
            prompt_sets.PROMPT_SET_FALLBACK_DEFAULT,
        )
        self.assertNotIn("fix_results", prepared.bound.registered_section_ids)
        reply = {
            "status": "ok",
            "kind": "review_round",
            "findings": [],
            "questions": answers(prepared.bound),
        }
        self.assertEqual(prepared.validate(copy.deepcopy(reply)), reply)

    def test_named_rungs_defaulting_owned_payloads_are_not_dispatched(self):
        self.assertTrue(prompt_sets.ensure_default(self.temp.name))
        cases = (
            (
                "delta-with-defaulted-base",
                "delta_review@slice_doc",
                "delta_base_revision",
            ),
            (
                "rating-with-defaulted-id",
                "reclassify@doc",
                "finding_id",
            ),
        )
        for name, job, payload in cases:
            with self.subTest(job=job):
                documents = copy.deepcopy(prompt_sets.default_seed().documents)
                kind = job.split("@", 1)[0]
                document = documents["milestone/%s.json" % kind]
                if kind == "delta_review":
                    units = document["variants"]["target_frame"][
                        "slice_unit"
                    ]["variables"]
                else:
                    units = document["instructions"]["parts"][-2][
                        "variables"
                    ]
                declaration = next(
                    item for item in units if item["name"] == payload
                )
                declaration["required"] = False
                declaration["default"] = "fabricated"
                self.write_set(name, documents)

                values = values_for(self.temp.name, job)
                del values[payload]
                with self.assertRaises(prompt_sets.PromptSetError):
                    self.prepare(job, prompt_set=name, values=values)

    def test_current_amendment_set_is_source_rendered_and_required(self):
        amendments = [
            {"id": "A2", "text": "Use the bounded path."},
            {
                "id": "B1",
                "text": "Keep one canonical plan.",
                "authority": "brainstorming_design",
            },
        ]
        values = values_for(self.temp.name, "review_round@skeleton")
        current = self.prepare(
            "review_round@skeleton",
            values=values,
            amendments=amendments,
        )
        expected_values = dict(values)
        expected_values["operator_amendments"] = (
            judgment_calls._current_amendments(amendments, True)
        )
        self.assertEqual(
            current.prompt,
            prompt_router.render(current.bound.prompt, expected_values),
        )

        with self.assertRaises(ValueError):
            self.prepare(
                "review_round@skeleton", operator_complete=False
            )

    def test_dynamic_scope_correction_and_fixer_recovery_are_routed_values(self):
        scope = {
            "part": "b",
            "scope": "Complete the coherent judgment cutover.",
            "delegated_remaining": "Complete the later lifecycle conversion.",
            "source_unit": "slice_impl-06-a",
        }
        values = values_for(self.temp.name, "fix_findings@slice_impl")
        values["implementation_scope"] = scope
        prepared = self.prepare(
            "fix_findings@slice_impl",
            values=values,
            correction="reply.findings must cover the queued ids",
            fixer_recovery_state="pending_partial_delta",
        )

        mounted = {
            declaration["name"]
            for unit in prepared.bound.prompt["instructions"]
            for declaration in unit["variables"]
        }
        self.assertTrue({
            "implementation_scope",
            "contract_correction",
            "fixer_recovery_state",
        }.issubset(mounted))
        expected_values = dict(values)
        expected_values.update({
            "implementation_scope": prompts._implementation_scope_block(
                scope
            ).rstrip("\n"),
            "operator_amendments": judgment_calls._current_amendments(
                [], True
            ),
            "queued_findings": "[]",
            "contract_correction": (
                "reply.findings must cover the queued ids"
            ),
            "fixer_recovery_state": "pending_partial_delta",
        })
        self.assertEqual(
            prepared.prompt,
            prompt_router.render(prepared.bound.prompt, expected_values),
        )

        for job in ("review_round@slice_impl", "delta_review@slice_impl"):
            with self.subTest(job=job):
                routed_values = values_for(self.temp.name, job)
                routed_values["implementation_scope"] = scope
                routed = self.prepare(job, values=routed_values)
                declarations = {
                    declaration["name"]
                    for unit in routed.bound.prompt["instructions"]
                    for declaration in unit["variables"]
                }
                self.assertIn("implementation_scope", declarations)

    def test_missing_dynamic_payload_unit_falls_as_a_whole(self):
        self.assertTrue(prompt_sets.ensure_default(self.temp.name))
        scope = {
            "part": "b",
            "scope": "Complete the coherent judgment cutover.",
            "delegated_remaining": "Complete the later lifecycle conversion.",
            "source_unit": "slice_impl-06-a",
        }
        cases = (
            (
                "scope",
                "review_round@slice_impl",
                "implementation_scope",
                {"values": {
                    **values_for(self.temp.name, "review_round@slice_impl"),
                    "implementation_scope": scope,
                }},
            ),
            (
                "correction",
                "reclassify@doc",
                "contract_correction",
                {"correction": "invalid rating envelope"},
            ),
            (
                "recovery",
                "fix_findings@slice_impl",
                "fixer_recovery",
                {"fixer_recovery_state": "pending_partial_delta"},
            ),
        )
        for name, job, unit_id, options in cases:
            with self.subTest(name=name):
                documents = copy.deepcopy(prompt_sets.default_seed().documents)
                parts = documents["milestone/%s.json" % job.split("@", 1)[0]][
                    "instructions"
                ]["parts"]
                documents["milestone/%s.json" % job.split("@", 1)[0]][
                    "instructions"
                ]["parts"] = [
                    part for part in parts if part.get("ref") != unit_id
                ]
                self.write_set("missing-dynamic-%s" % name, documents)
                prepared = self.prepare(
                    job,
                    prompt_set="missing-dynamic-%s" % name,
                    **options,
                )
                self.assertEqual(
                    prepared.prompt_set_fallback,
                    prompt_sets.PROMPT_SET_FALLBACK_DEFAULT,
                )

    def test_duplicate_adapter_authority_units_fall_as_a_whole(self):
        self.assertTrue(prompt_sets.ensure_default(self.temp.name))
        cases = (
            (
                "duplicate-amendment-unit",
                "operator_amendments_review",
                {},
            ),
            (
                "duplicate-project-context-unit",
                "project_context",
                {"project_context": project_context(self.temp.name, [])},
            ),
        )
        for name, unit_id, options in cases:
            with self.subTest(name=name):
                documents = copy.deepcopy(prompt_sets.default_seed().documents)
                parts = documents["milestone/review_round.json"][
                    "instructions"
                ]["parts"]
                index = parts.index({"ref": unit_id})
                parts.insert(index + 1, {"ref": unit_id})
                self.write_set(name, documents)
                self.assertEqual(
                    prompt_sets.load(self.temp.name, name).name, name
                )

                prepared = self.prepare(
                    "review_round@skeleton", prompt_set=name, **options
                )
                expected = self.prepare(
                    "review_round@skeleton", prompt_set="default", **options
                )

                self.assertEqual(
                    prepared.prompt_set_fallback,
                    prompt_sets.PROMPT_SET_FALLBACK_DEFAULT,
                )
                self.assertEqual(prepared.prompt, expected.prompt)

    def test_duplicate_adapter_authority_substitutions_fall_as_a_whole(self):
        self.assertTrue(prompt_sets.ensure_default(self.temp.name))
        cases = (
            (
                "duplicate-amendment-substitution",
                "operator_amendments_review",
                "operator_amendments",
                {},
            ),
            (
                "duplicate-project-context-substitution",
                "project_context",
                "ecosystem_map",
                {"project_context": project_context(self.temp.name, [])},
            ),
        )
        for name, unit_id, variable, options in cases:
            with self.subTest(name=name):
                documents = copy.deepcopy(prompt_sets.default_seed().documents)
                documents["shared/shared.json"]["units"][unit_id][
                    "text"
                ].append("{{%s}}" % variable)
                self.write_set(name, documents)
                self.assertEqual(
                    prompt_sets.load(self.temp.name, name).name, name
                )

                prepared = self.prepare(
                    "review_round@skeleton", prompt_set=name, **options
                )
                expected = self.prepare(
                    "review_round@skeleton", prompt_set="default", **options
                )

                self.assertEqual(
                    prepared.prompt_set_fallback,
                    prompt_sets.PROMPT_SET_FALLBACK_DEFAULT,
                )
                self.assertEqual(prepared.prompt, expected.prompt)

    def test_rating_accepts_and_enforces_its_scoped_project_extension(self):
        complete_policy = policy()
        complete_policy["prompt"] = ("x" * 2500) + " binding-tail"
        authority = project_context(self.temp.name, [complete_policy])
        values = values_for(self.temp.name, "reclassify@doc")
        prepared = self.prepare(
            "reclassify@doc",
            values=values,
            project_context=authority,
        )
        expected_values = dict(values)
        expected_values.update({
            "operator_amendments": judgment_calls._current_amendments(
                [], True
            ),
            "ecosystem_map": prompts.project_context_body(authority),
        })
        self.assertEqual(
            prepared.prompt,
            prompt_router.render(prepared.bound.prompt, expected_values),
        )
        reply = {
            "status": "ok",
            "kind": "reclassify",
            "drift_risk": "low",
            "drift_damage": "low",
            "reason": "The correction is local and self-revealing.",
            "questions": answers(prepared.bound),
        }
        with self.assertRaises(contracts.ContractError):
            prepared.validate(copy.deepcopy(reply))
        reply["reuse_evidence"] = [{"finding": "Reused the routed binder."}]
        self.assertEqual(prepared.validate(copy.deepcopy(reply)), reply)

    def test_incomplete_project_authority_stops_during_preparation(self):
        complete = project_context(self.temp.name, [])
        for missing in ("project", "work_area", "safeguards"):
            with self.subTest(missing=missing):
                authority = copy.deepcopy(complete)
                del authority[missing]
                with self.assertRaises(ValueError):
                    self.prepare(
                        "review_round@skeleton",
                        project_context=authority,
                    )

        malformed = copy.deepcopy(complete)
        malformed["safeguards"] = None
        with self.assertRaises(ValueError):
            self.prepare(
                "review_round@skeleton", project_context=malformed
            )

        malformed = copy.deepcopy(complete)
        malformed["reuse_sources"] = [{}]
        with self.assertRaises(ValueError):
            self.prepare(
                "review_round@skeleton", project_context=malformed
            )

    def test_invalid_inventory_root_stops_during_judgment_preparation(self):
        inventory_policy = {
            "id": "inventory",
            "version": 1,
            "enabled": True,
            "scope": {
                "kinds": ["reclassify"],
                "unit_kinds": ["slice_doc"],
            },
            "prompt": "Inventory the granted directory.",
            "contract": {
                "field": "inventory",
                "required": True,
                "entry": {"package": {"type": "string"}},
                "checks": [{
                    "kind": "dir_listing_matches",
                    "root": "../outside",
                    "match_field": "package",
                }],
            },
        }
        with self.assertRaises(verifiers.PolicyConfigError):
            self.prepare(
                "reclassify@doc",
                project_context=project_context(
                    self.temp.name, [inventory_policy]
                ),
            )

    def test_question_answers_enforce_the_structural_length_limit(self):
        prepared = self.prepare("review_round@skeleton")
        reply = {
            "status": "ok",
            "kind": "review_round",
            "findings": [],
            "questions": answers(prepared.bound, "x" * 300),
        }
        self.assertEqual(prepared.validate(copy.deepcopy(reply)), reply)
        reply["questions"][0]["answer"] = "x" * 301
        with self.assertRaises(contracts.ContractError):
            prepared.validate(reply)

    def test_trusted_judgment_prose_is_not_a_runtime_schema(self):
        self.assertTrue(prompt_sets.ensure_default(self.temp.name))
        trusted_jobs = (
            "review_round@skeleton",
            "review_round@slice_doc",
            "review_round@slice_impl",
            "delta_review@skeleton",
            "delta_review@slice_doc",
            "delta_review@slice_impl",
            "reclassify@doc",
        )
        instruction = (
            "Treat the repository as read-only: preserve its work tree, "
            "index, and HEAD exactly."
        )
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        documents["shared/shared.json"]["units"][
            "trusted_judgment_read_only"
        ]["text"] = [instruction]
        self.write_set("edited-trusted", documents)

        for job in trusted_jobs:
            with self.subTest(job=job):
                prepared = self.prepare(
                    job, prompt_set="edited-trusted"
                )

                self.assertIsNone(prepared.prompt_set_fallback)

        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        documents["shared/shared.json"]["units"].pop(
            "trusted_judgment_read_only"
        )
        for member in (
            "milestone/review_round.json",
            "milestone/delta_review.json",
            "milestone/reclassify.json",
        ):
            parts = documents[member]["instructions"]["parts"]
            documents[member]["instructions"]["parts"] = [
                part for part in parts
                if part != {"ref": "trusted_judgment_read_only"}
            ]
        self.write_set("without-trusted-prose", documents)

        for job in trusted_jobs:
            with self.subTest(job=job, prose="absent"):
                prepared = self.prepare(
                    job, prompt_set="without-trusted-prose"
                )
                self.assertIsNone(prepared.prompt_set_fallback)

    def test_only_the_ten_direct_judgment_jobs_are_admitted(self):
        with self.assertRaises(ValueError):
            self.prepare("implement@slice_impl")

        with self.assertRaises(ValueError):
            judgment_calls.prepare(
                self.temp.name,
                job="fix_findings@skeleton",
                material="document",
                values=values_for(
                    self.temp.name, "fix_findings@skeleton"
                ),
                amendments=[],
                operator_complete=True,
            )


class JudgmentDriverBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orch-judgment-driver-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = self.temp.name
        subprocess.run(["git", "init", "-q"], cwd=self.workspace, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Judgment Test"],
            cwd=self.workspace, check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "judgment@example.invalid"],
            cwd=self.workspace, check=True,
        )
        config = driver.load_config(None)
        driver.merge_config(config, {
            "error_classifier": False,
            "infra_retry_backoff_s": [],
            "git": {"enabled": True},
        })
        self.state_path = driver.init_run(
            "Exercise routed judgments.", self.workspace, config=config
        )
        self.subject = driver.Driver(
            self.state_path, runner=runners.MockRunner([])
        )
        self.skeleton = self.subject._skeleton_artifact()
        path = os.path.join(self.workspace, self.skeleton)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(canonical_document())
        subprocess.run(
            ["git", "add", self.skeleton], cwd=self.workspace, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "canonical plan"],
            cwd=self.workspace, check=True,
        )
        unit = state.current_unit(self.subject.state)
        unit["artifact"] = self.skeleton
        canonical_plan.establish_current_plan(
            self.subject.state, self.skeleton
        )
        self.subject._save()

    @staticmethod
    def questions():
        return [
            {"id": "environment_fit", "answer": "The repository standard."},
            {"id": "human_scale", "answer": "The judgment is proportional."},
        ]

    def test_trusted_review_keeps_other_mutations_and_projects_plan(self):
        def edit(workspace):
            with open(os.path.join(workspace, self.skeleton), "w") as handle:
                handle.write(canonical_document("Changed"))
            with open(os.path.join(workspace, "trusted.txt"), "w") as handle:
                handle.write("kept\n")

        self.subject.runner = runners.MockRunner([{
            "expect_kind": "review_round",
            "side_effect": edit,
            "response": {
                "status": "ok", "kind": "review_round", "findings": [],
                "questions": self.questions(),
            },
        }])
        unit = state.current_unit(self.subject.state)
        output, _result, _raw = self.subject._call(
            "codex", "legacy", "review_round", "trusted-review",
            prepare_call=self.subject._judgment_prepare_call(
                unit, "review_round", "trusted-review"
            ),
            episode_unit=unit,
        )

        self.assertEqual(output["findings"], [])
        self.assertEqual(
            self.subject.state["milestone"]["slices"][0]["title"], "Changed"
        )
        self.assertTrue(os.path.exists(os.path.join(self.workspace, "trusted.txt")))

    def test_unchanged_trusted_review_does_not_snapshot_the_worktree(self):
        self.subject.runner = runners.MockRunner([{
            "expect_kind": "review_round",
            "response": {
                "status": "ok", "kind": "review_round", "findings": [],
                "questions": self.questions(),
            },
        }])
        unit = state.current_unit(self.subject.state)

        with mock.patch.object(
            canonical_plan.gitops,
            "snapshot_worktree_tree",
            side_effect=AssertionError("trusted observation staged the worktree"),
        ):
            output, _result, _raw = self.subject._call(
                "codex", "legacy", "review_round", "trusted-unchanged",
                prepare_call=self.subject._judgment_prepare_call(
                    unit, "review_round", "trusted-unchanged"
                ),
                episode_unit=unit,
            )

        self.assertEqual(output["findings"], [])
        self.assertIsNone(self.subject.state.get("failure"))

    def test_provisional_delta_consumer_receives_routed_verdict(self):
        unit = self._open_slice_impl()
        base_revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        correction = {
            "phase": "proposed",
            "artifact": "implementation/slices/slice-01.md",
            "authority_artifact": "implementation/authority.md",
            "contradiction": "The note conflicts with retained authority.",
            "resolution": "Restore the retained boundary.",
        }
        unit["status"] = state.U_DELTA_REVIEW
        unit["design_correction"] = correction
        unit["fix_source"] = {
            "type": "round",
            "origin_type": "round",
            "return_to": state.U_ROUNDS,
        }
        unit["rounds"] = [{
            "id": "slice_impl-01-fix1",
            "kind": contracts.KIND_FIX_FINDINGS,
            "family": "codex",
            "meta": {"delta_base_revision": base_revision},
            "result": {"findings": []},
        }]
        self.subject.runner = runners.MockRunner([{
            "expect_kind": "delta_review",
            "response": {
                "status": "ok",
                "kind": "delta_review",
                "findings": [],
                "design_correction_verdict": {
                    "decision": "ratify",
                    "reason": "The retained authority uniquely resolves it.",
                },
                "questions": self.questions(),
            },
        }])

        prepared_calls = []
        real_prepare = judgment_calls.prepare

        def capture_prepare(*args, **kwargs):
            prepared = real_prepare(*args, **kwargs)
            prepared_calls.append(prepared)
            return prepared

        with (
            mock.patch.object(
                self.subject, "_design_correction_integrity_error",
                return_value=None,
            ),
            mock.patch.object(
                self.subject, "_design_correction_review_context",
                return_value=correction,
            ),
            mock.patch.object(
                driver.gitops, "worktree_diff", return_value="pending delta"
            ),
            mock.patch.object(
                self.subject, "_ratify_design_correction",
                return_value="correction ratified",
            ) as ratify,
            mock.patch.object(
                judgment_calls, "prepare", side_effect=capture_prepare
            ),
        ):
            outcome = self.subject._do_delta_review()

        self.assertEqual(outcome, "correction ratified")
        ratify.assert_called_once()
        self.assertEqual(len(prepared_calls), 1)
        prepared = prepared_calls[0]
        self.assertEqual(
            [
                section
                for section in prepared.bound.prompt["output_contract"]
                if section["id"] == "design_correction_verdict"
            ],
            [prompts.design_correction_verdict_section(correction)],
        )
        self.assertEqual(self.subject.runner.calls[0][2], prepared.prompt)

    def test_restart_preserves_completed_trusted_plan_change(self):
        def edit(workspace):
            with open(
                os.path.join(workspace, self.skeleton), "w", encoding="utf-8"
            ) as handle:
                handle.write(canonical_document("Changed before restart"))
            with open(
                os.path.join(workspace, "trusted.txt"), "w", encoding="utf-8"
            ) as handle:
                handle.write("kept across restart\n")

        self.subject.runner = runners.MockRunner([{
            "expect_kind": "review_round",
            "side_effect": edit,
            "response": {
                "status": "ok", "kind": "review_round", "findings": [],
                "questions": self.questions(),
            },
        }])
        unit = state.current_unit(self.subject.state)
        self.subject._call(
            "codex", "legacy", "review_round", "trusted-restart",
            prepare_call=self.subject._judgment_prepare_call(
                unit, "review_round", "trusted-restart"
            ),
            episode_unit=unit,
        )
        with open(self.subject._busy_path(), encoding="utf-8") as handle:
            self.assertTrue(json.load(handle)["completed"])

        restarted = driver.Driver(
            self.state_path, runner=runners.MockRunner([])
        )

        with open(
            os.path.join(self.workspace, self.skeleton), encoding="utf-8"
        ) as handle:
            self.assertEqual(
                handle.read(), canonical_document("Changed before restart")
            )
        with open(
            os.path.join(self.workspace, "trusted.txt"), encoding="utf-8"
        ) as handle:
            self.assertEqual(handle.read(), "kept across restart\n")
        self.assertEqual(
            restarted.state["milestone"]["slices"][0]["title"],
            "Changed before restart",
        )
        self.assertFalse(any(
            event["type"] == "unclean_stop_restored"
            for event in restarted.state["events"]
        ))
        canonical_plan.begin_observed_call(restarted.state, self.skeleton)
        self.assertFalse(os.path.exists(restarted._busy_path()))

    def test_restart_during_correction_preserves_trusted_non_plan_mutation(self):
        def edit(workspace):
            with open(
                os.path.join(workspace, "trusted.txt"), "w", encoding="utf-8"
            ) as handle:
                handle.write("kept across correction restart\n")

        def interrupt(_workspace):
            raise KeyboardInterrupt()

        self.subject.runner = runners.MockRunner([
            {
                "expect_kind": "review_round",
                "side_effect": edit,
                "response": {"bad": 1},
            },
            {
                "expect_kind": "review_round",
                "side_effect": interrupt,
                "response": {},
            },
        ])
        unit = state.current_unit(self.subject.state)
        unit["status"] = state.U_ROUNDS
        task = self.subject._admit_worker_task(
            unit, contracts.KIND_REVIEW_ROUND, "legacy", "codex"
        )

        with self.assertRaises(KeyboardInterrupt):
            self.subject._call(
                "codex", "legacy", "review_round", "trusted-correction",
                task_id=task["id"],
                prepare_call=self.subject._judgment_prepare_call(
                    unit, "review_round", "trusted-correction"
                ),
                episode_unit=unit,
            )

        anchor = self.subject.state["milestone"][canonical_plan.ANCHOR_KEY]
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(anchor["revision"], head)
        with open(self.subject._busy_path(), encoding="utf-8") as handle:
            self.assertFalse(json.load(handle).get("completed", False))

        restarted = driver.Driver(
            self.state_path, runner=runners.MockRunner([])
        )

        with open(
            os.path.join(self.workspace, "trusted.txt"), encoding="utf-8"
        ) as handle:
            self.assertEqual(handle.read(), "kept across correction restart\n")
        self.assertEqual(
            restarted.state["milestone"]["slices"][0]["title"],
            "One",
        )
        self.assertFalse(any(
            event["type"] == "unclean_stop_restored"
            for event in restarted.state["events"]
        ))
        canonical_plan.begin_observed_call(restarted.state, self.skeleton)
        self.assertFalse(os.path.exists(restarted._busy_path()))

    def _open_slice_impl(self, material=None):
        if material is not None:
            path = os.path.join(self.workspace, self.skeleton)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(canonical_document(material=material))
            subprocess.run(
                ["git", "add", self.skeleton], cwd=self.workspace, check=True
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "set slice material"],
                cwd=self.workspace,
                check=True,
            )
            canonical_plan.establish_current_plan(
                self.subject.state, self.skeleton
            )
        skeleton = state.current_unit(self.subject.state)
        skeleton["status"] = state.U_SEALED
        slice_doc = state.ensure_next_unit(self.subject.state)
        slice_doc["status"] = state.U_SEALED
        slice_doc["artifact"] = "implementation/slices/slice-01.md"
        unit = state.ensure_next_unit(self.subject.state)
        unit["artifact"] = "orchestrator/driver.py"
        unit["status"] = state.U_ROUNDS
        self.subject._save()
        return unit

    def test_plan_deleting_review_keeps_material_for_nested_rating(self):
        unit = self._open_slice_impl(material="document")

        def replace_plan(workspace):
            with open(
                os.path.join(workspace, self.skeleton), "w", encoding="utf-8"
            ) as handle:
                handle.write(canonical_document("Replacement", slice_id=2))

        self.subject.runner = runners.MockRunner([
            {
                "expect_kind": "review_round",
                "side_effect": replace_plan,
                "response": {
                    "status": "ok", "kind": "review_round", "findings": [],
                    "questions": self.questions(),
                },
            },
            {
                "expect_kind": "reclassify",
                "response": {
                    "status": "ok",
                    "kind": "reclassify",
                    "drift_risk": "high",
                    "drift_damage": "high",
                    "reason": "The finding remains material.",
                    "questions": self.questions(),
                },
            },
        ])
        self.subject._call(
            "codex", "legacy", "review_round", "plan-deleting-review",
            prepare_call=self.subject._judgment_prepare_call(
                unit, "review_round", "plan-deleting-review"
            ),
            episode_unit=unit,
        )
        finding = {
            "id": "F1", "severity": "P3", "summary": "Ambiguous text.",
            "validity": {}, "plain": "A builder can read it two ways.",
            "example": "One builder chooses the wrong branch.",
        }

        debt, retained = self.subject._partition_defer_candidates(
            unit, [(finding, "codex")]
        )

        self.assertEqual(debt, [])
        self.assertEqual(retained, [(finding, "codex")])
        self.assertEqual(len(self.subject.runner.calls), 2)
        self.assertEqual(unit[state.PLAN_FOLLOWUP_MATERIAL_KEY], "document")

    def test_plan_changing_judgment_keeps_origin_current_for_follow_up(self):
        unit = self._open_slice_impl()

        def replace_plan(workspace):
            with open(
                os.path.join(workspace, self.skeleton), "w", encoding="utf-8"
            ) as handle:
                handle.write(canonical_document("Replacement", slice_id=2))

        self.subject.runner = runners.MockRunner([{
            "expect_kind": "review_round",
            "side_effect": replace_plan,
            "response": {
                "status": "ok", "kind": "review_round", "findings": [],
                "questions": self.questions(),
            },
        }])
        self.subject._call(
            "codex", "legacy", "review_round", "plan-follow-up-review",
            prepare_call=self.subject._judgment_prepare_call(
                unit, "review_round", "plan-follow-up-review"
            ),
            episode_unit=unit,
        )
        state.enter_fix_episode(
            self.subject.state,
            unit,
            [{"id": "F1", "severity": "P1", "summary": "Fix it."}],
            "round",
            "codex",
            "slice_impl-01-codex-r1",
            state.U_ROUNDS,
        )

        self.assertTrue(unit[state.PLAN_FOLLOWUP_KEY])
        self.assertIs(state.current_unit(self.subject.state), unit)
        self.assertFalse(state.maybe_close_milestone(self.subject.state))

    def test_pre_activation_run_without_mutable_authority_still_dispatches(self):
        os.unlink(self.subject._amendments_path())
        self.subject.runner = runners.MockRunner([{
            "expect_kind": "review_round",
            "response": {
                "status": "ok", "kind": "review_round", "findings": [],
                "questions": self.questions(),
            },
        }])
        unit = state.current_unit(self.subject.state)

        output, _result, _raw = self.subject._call(
            "codex", "legacy", "review_round", "legacy-compatible-review",
            prepare_call=self.subject._judgment_prepare_call(
                unit, "review_round", "legacy-compatible-review"
            ),
            episode_unit=unit,
        )

        self.assertEqual(output["findings"], [])
        self.assertEqual(len(self.subject.runner.calls), 1)
        self.assertIsNone(self.subject.state.get("failure"))

    def test_activated_run_without_mutable_authority_fails_before_dispatch(self):
        os.unlink(self.subject._amendments_path())
        self.subject.state["schema_version"] = (
            state.PROMPT_ROUTER_ACTIVATION_SCHEMA_VERSION
        )
        self.subject.runner = runners.MockRunner([])
        unit = state.current_unit(self.subject.state)

        with self.assertRaises(driver.StopStep):
            self.subject._call(
                "codex", "legacy", "review_round", "activated-review",
                prepare_call=self.subject._judgment_prepare_call(
                    unit, "review_round", "activated-review"
                ),
                episode_unit=unit,
            )

        self.assertEqual(self.subject.runner.calls, [])
        self.assertEqual(self.subject.state["failure"]["type"], "orchestrator")

    def test_fixer_values_use_the_ignored_runtime_scratch_directory(self):
        unit = state.current_unit(self.subject.state)
        values = self.subject._judgment_values(
            unit,
            contracts.KIND_FIX_FINDINGS,
            {
                "consultation_family": "claude",
                "consultation_command": ["claude"],
            },
        )

        self.assertEqual(
            values["scratch_path"],
            os.path.join(self.workspace, ".orchestrator", "scratch")
            + os.sep,
        )

    def test_driver_supplies_the_exact_part_scope_to_owned_judgments(self):
        unit = state._new_unit(state.UNIT_SLICE_IMPL, 1)
        unit["implementation_cut"] = {
            "part": "b",
            "next_part": "c",
            "cut_scope": "Complete the coherent judgment cutover.",
            "remaining_scope": "Complete the later lifecycle conversion.",
        }
        expected = state.implementation_scope(self.subject.state, unit)

        for kind, context in (
            (contracts.KIND_REVIEW_ROUND, {}),
            (
                contracts.KIND_FIX_FINDINGS,
                {
                    "consultation_family": "claude",
                    "consultation_command": ["claude"],
                },
            ),
            (
                contracts.KIND_DELTA_REVIEW,
                {"delta_base_revision": "a" * 40},
            ),
        ):
            with self.subTest(kind=kind):
                values = self.subject._judgment_values(unit, kind, context)
                self.assertEqual(values["implementation_scope"], expected)

    def test_fixer_invalid_plan_restores_once_and_fails_terminally(self):
        def damage(workspace):
            with open(os.path.join(workspace, self.skeleton), "w") as handle:
                handle.write("# invalid\n")
            with open(os.path.join(workspace, "discarded.txt"), "w") as handle:
                handle.write("discard me\n")

        self.subject.runner = runners.MockRunner([{
            "expect_kind": "fix_findings",
            "side_effect": damage,
            "response": {
                "status": "ok", "kind": "fix_findings", "findings": [],
                "files_changed": [], "questions": self.questions(),
            },
        }])
        unit = state.current_unit(self.subject.state)
        with self.assertRaises(driver.StopStep):
            self.subject._call(
                "codex", "legacy", "fix_findings", "invalid-fix",
                prepare_call=self.subject._judgment_prepare_call(
                    unit, "fix_findings", "invalid-fix",
                    context={
                        "consultation_family": "claude",
                        "consultation_command": ["claude"],
                    },
                    queued_findings=[],
                ),
                episode_unit=unit,
            )

        self.assertEqual(len(self.subject.runner.calls), 1)
        self.assertEqual(
            self.subject.state["failure"]["type"], "canonical_plan_boundary"
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.workspace, "discarded.txt"))
        )

    def test_fixer_restoration_prevents_need_rethink_handoff(self):
        skeleton_unit = state.current_unit(self.subject.state)
        skeleton_unit["status"] = state.U_SEALED
        skeleton_unit["gate_commit"] = self.subject.state["milestone"][
            canonical_plan.ANCHOR_KEY
        ]["revision"]
        slice_path = "implementation/slices/slice-01.md"
        full_slice_path = os.path.join(self.workspace, slice_path)
        os.makedirs(os.path.dirname(full_slice_path), exist_ok=True)
        with open(full_slice_path, "w", encoding="utf-8") as handle:
            handle.write("# Slice 01\n")
        subprocess.run(
            ["git", "add", slice_path], cwd=self.workspace, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "slice note"],
            cwd=self.workspace,
            check=True,
        )
        unit = state.ensure_next_unit(self.subject.state)
        unit["artifact"] = slice_path
        unit["status"] = state.U_FIXING
        finding = {
            "id": "F1",
            "severity": "P2",
            "summary": "The implementation contradicts its design.",
            "validity": {
                "permitted_baseline": "The implementation follows its design.",
                "actual_outcome": "The implementation contradicts its design.",
                "incremental_harm": "The contradiction blocks a valid fix.",
                "exceeds_baseline": True,
            },
            "plain": "The implementation cannot satisfy the current design.",
            "example": "The required outputs conflict.",
            "contests": None,
        }
        unit["fix_queue"] = [copy.deepcopy(finding)]
        unit["fix_source"] = {
            "type": "round",
            "family": "codex",
            "return_to": state.U_ROUNDS,
        }
        self.subject._save()

        def tamper_with_sealed_skeleton(workspace):
            path = os.path.join(workspace, self.skeleton)
            with open(path, encoding="utf-8") as handle:
                document = handle.read()
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(document.replace("# Skeleton", "# Tampered", 1))

        self.subject.runner = runners.MockRunner([{
            "expect_kind": "fix_findings",
            "side_effect": tamper_with_sealed_skeleton,
            "response": {
                "status": "need_rethink",
                "kind": "fix_findings",
                "finding": copy.deepcopy(finding),
                "target_path": slice_path,
                "questions": self.questions(),
            },
        }])

        with mock.patch.object(self.subject, "_start_rethink") as start_rethink:
            with self.assertRaises(driver.StopStep):
                self.subject._do_fix()

        start_rethink.assert_not_called()
        self.assertEqual(
            self.subject.state["failure"]["type"], "worker_blocked"
        )
        restored = [
            event for event in self.subject.state["events"]
            if event["type"] == "sealed_artifact_restored"
        ]
        self.assertEqual([event["artifact"] for event in restored], [self.skeleton])

    def test_suite_repair_keeps_its_delegated_empty_findings_contract(self):
        unit = state.current_unit(self.subject.state)
        unit["status"] = state.U_FIXING
        unit["fix_queue"] = [{
            "id": "V1",
            "severity": "P1",
            "summary": "The configured full suite is not green.",
            "validity": {},
            "contests": None,
        }]
        unit["fix_source"] = {
            "type": "verification",
            "family": "codex",
            "source_round_id": "skeleton-verify-pre_seal-1",
            "return_to": state.U_PRE_REVIEW_VERIFY,
        }
        self.subject.config["verification"] = ["true"]
        self.subject.runner = runners.MockRunner([{
            "expect_kind": "fix_findings",
            "response": {
                "status": "ok",
                "kind": "fix_findings",
                "findings": [],
                "files_changed": [],
                "tests_modified": False,
                "tests_changed": [],
            },
        }])

        with mock.patch.object(
            judgment_calls,
            "prepare",
            side_effect=AssertionError("suite repair entered routed triage"),
        ):
            note = self.subject._do_fix()

        self.assertIn("full suite green", note)
        self.assertEqual(len(self.subject.runner.calls), 1)
        self.assertEqual(unit["fix_queue"], [])
        self.assertIsNone(unit["fix_source"])

    def test_fixer_commit_survives_and_is_reviewed_from_pre_fix_revision(self):
        unit = state.current_unit(self.subject.state)
        unit["status"] = state.U_FIXING
        finding = {
            "id": "F1",
            "severity": "P1",
            "summary": "The implementation needs a bounded correction.",
            "validity": {
                "affected_party": "the operator",
                "observable_damage": "the correction is absent",
                "violated_guarantee": "accepted fixes remain reviewable",
                "permitted_baseline": "the fixer may edit ordinary work",
                "incremental_harm": "the required correction is missing",
                "exceeds_baseline": True,
            },
            "contests": None,
        }
        unit["fix_queue"] = [copy.deepcopy(finding)]
        unit["fix_source"] = {
            "type": "round",
            "family": "codex",
            "source_round_id": "skeleton-codex-r1",
            "return_to": state.U_ROUNDS,
        }

        def commit_fix(workspace):
            with open(os.path.join(workspace, "fix.txt"), "w") as handle:
                handle.write("fixed\n")
            subprocess.run(
                ["git", "add", "fix.txt"], cwd=workspace, check=True
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "fixer-owned repair"],
                cwd=workspace,
                check=True,
            )

        self.subject.runner = runners.MockRunner([
            {
                "expect_kind": "fix_findings",
                "side_effect": commit_fix,
                "response": {
                    "status": "ok",
                    "kind": "fix_findings",
                    "findings": [{
                        **copy.deepcopy(finding),
                        "disposition": "fixed",
                        "consultation": None,
                        "prevention": None,
                        "adjudication_ref": None,
                    }],
                    "files_changed": ["fix.txt"],
                    "questions": self.questions(),
                },
            },
            {
                "expect_kind": "delta_review",
                "response": {
                    "status": "ok",
                    "kind": "delta_review",
                    "findings": [],
                    "questions": self.questions(),
                },
            },
        ])

        self.subject._do_fix()
        self.assertEqual(unit["status"], state.U_DELTA_REVIEW)
        self.assertFalse(any(
            event["type"] == "fixer_commits_folded"
            for event in self.subject.state["events"]
        ))
        subjects = subprocess.run(
            ["git", "log", "--format=%s"],
            cwd=self.workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("fixer-owned repair", subjects)

        note = self.subject._do_delta_review()

        self.assertIn("delta review clean", note)
        self.assertEqual(len(self.subject.runner.calls), 2)
        self.assertFalse(any(
            event["type"] == "phantom_fix_retry"
            for event in self.subject.state["events"]
        ))

    def test_trusted_review_mutations_rebind_without_restarting_cycle(self):
        unit = self._open_slice_impl()

        def leave(path):
            def change(workspace):
                with open(os.path.join(workspace, path), "w") as handle:
                    handle.write("left by trusted review\n")
            return change

        clean = {
            "status": "ok",
            "kind": "review_round",
            "findings": [],
            "questions": self.questions(),
        }
        self.subject.runner = runners.MockRunner([
            {
                "expect_kind": "review_round",
                "side_effect": leave("review-one.txt"),
                "response": copy.deepcopy(clean),
            },
            {
                "expect_kind": "review_round",
                "side_effect": leave("review-two.txt"),
                "response": copy.deepcopy(clean),
            },
        ])

        self.subject._do_review_round()
        first_fingerprint = unit["review_evidence_fingerprint"]
        self.subject._do_review_round()
        second_fingerprint = unit["review_evidence_fingerprint"]

        self.assertNotEqual(first_fingerprint, second_fingerprint)
        self.assertEqual(unit["status"], state.U_PRE_SEAL_VERIFY)
        self.assertEqual(len(self.subject.runner.calls), 2)
        self.assertFalse(any(
            event["type"] == "review_cycle_restarted"
            for event in self.subject.state["events"]
        ))
        self.assertEqual(len(self.subject._seal_reviews(
            unit,
            current_fingerprint=self.subject._review_evidence_fingerprint(unit),
        )), 2)

    def test_trusted_rating_mutation_does_not_discard_parent_review(self):
        unit = self._open_slice_impl()
        finding = {
            "id": "F1",
            "severity": "P3",
            "summary": "The low-risk wording can be deferred.",
            "validity": {
                "permitted_baseline": "Low-risk debt may be deferred.",
                "actual_outcome": "The wording remains locally ambiguous.",
                "incremental_harm": "A later maintainer may reread it.",
                "exceeds_baseline": True,
            },
            "plain": "The wording may require a second reading.",
            "example": "A maintainer pauses before making the local edit.",
            "contests": None,
        }

        def rating_mutation(workspace):
            with open(os.path.join(workspace, "rating.txt"), "w") as handle:
                handle.write("left by trusted rating\n")

        self.subject.runner = runners.MockRunner([
            {
                "expect_kind": "review_round",
                "response": {
                    "status": "ok",
                    "kind": "review_round",
                    "findings": [copy.deepcopy(finding)],
                    "questions": self.questions(),
                },
            },
            {
                "expect_kind": "reclassify",
                "side_effect": rating_mutation,
                "response": {
                    "status": "ok",
                    "kind": "reclassify",
                    "drift_risk": "low",
                    "drift_damage": "low",
                    "reason": "The ambiguity is local and cheap to revisit.",
                    "questions": self.questions(),
                },
            },
            {
                "expect_kind": "review_round",
                "response": {
                    "status": "ok",
                    "kind": "review_round",
                    "findings": [],
                    "questions": self.questions(),
                },
            },
        ])

        first_note = self.subject._do_review_round()
        second_note = self.subject._do_review_round()

        self.assertIn("deferred as debt", first_note)
        self.assertIn("round: clean", second_note)
        self.assertEqual(unit["status"], state.U_PRE_SEAL_VERIFY)
        self.assertEqual(len(self.subject.runner.calls), 3)
        self.assertFalse(any(
            event["type"] == "review_cycle_restarted"
            for event in self.subject.state["events"]
        ))

    def test_exhausted_rating_contract_is_terminal(self):
        self.subject.runner = runners.MockRunner([
            {"expect_kind": "reclassify", "response": {"bad": 1}},
            {"expect_kind": "reclassify", "response": {"bad": 2}},
        ])
        unit = state.current_unit(self.subject.state)
        finding = {
            "id": "F1", "severity": "P3", "summary": "Ambiguous text.",
            "validity": {}, "plain": "A builder can read it two ways.",
            "example": "One builder chooses the wrong branch.",
        }

        with self.assertRaises(driver.StopStep):
            self.subject._partition_defer_candidates(
                unit, [(finding, "codex")]
            )

        self.assertEqual(len(self.subject.runner.calls), 2)
        self.assertFalse(any(
            event["type"] == "reclassify_recorded"
            for event in self.subject.state["events"]
        ))
        self.assertEqual(self.subject.state["failure"]["type"], "worker_protocol")

    def test_protocol_reply_prose_cannot_enter_infrastructure_classification(self):
        self.subject.runner = runners.MockRunner([
            {"expect_kind": "review_round", "response": {"invalid": 1}},
            {"expect_kind": "review_round", "response": {"invalid": 2}},
        ])
        unit = state.current_unit(self.subject.state)

        with mock.patch.object(
            self.subject,
            "_classify_failure",
            side_effect=AssertionError("protocol output reached errclass"),
        ):
            with self.assertRaises(driver.StopStep):
                self.subject._call(
                    "codex", "legacy", "review_round", "protocol-review",
                    prepare_call=self.subject._judgment_prepare_call(
                        unit, "review_round", "protocol-review"
                    ),
                    episode_unit=unit,
                )

        self.assertEqual(len(self.subject.runner.calls), 2)
        self.assertEqual(
            self.subject.state["failure"]["type"], "worker_protocol"
        )
        self.assertIsNone(self.subject.state["failure"]["resume_at"])

    def test_fixer_protocol_failure_is_terminal_without_classification(self):
        self.subject.runner = runners.MockRunner([
            {"expect_kind": "fix_findings", "response": {"invalid": 1}},
            {"expect_kind": "fix_findings", "response": {"invalid": 2}},
        ])
        unit = state.current_unit(self.subject.state)

        with mock.patch.object(
            self.subject,
            "_classify_failure",
            side_effect=AssertionError("protocol output reached errclass"),
        ):
            with self.assertRaises(driver.StopStep):
                self.subject._call(
                    "codex", "legacy", "fix_findings", "protocol-fixer",
                    prepare_call=self.subject._judgment_prepare_call(
                        unit,
                        "fix_findings",
                        "protocol-fixer",
                        context={
                            "consultation_family": "claude",
                            "consultation_command": ["claude"],
                        },
                        queued_findings=[],
                    ),
                    episode_unit=unit,
                )

        self.assertEqual(len(self.subject.runner.calls), 2)
        self.assertEqual(
            self.subject.state["failure"]["type"], "worker_protocol"
        )
        self.assertIsNone(self.subject.state["failure"]["resume_at"])

    def test_provider_started_rating_transport_failure_is_recoverable(self):
        failure = runners.ProviderResponseError("service unavailable")
        self.subject.runner = RaisingRunner(failure)
        unit = state.current_unit(self.subject.state)
        finding = {
            "id": "F1", "severity": "P3", "summary": "Ambiguous text.",
            "validity": {}, "plain": "A builder can read it two ways.",
            "example": "One builder chooses the wrong branch.",
        }

        with self.assertRaises(driver.StopStep):
            self.subject._partition_defer_candidates(
                unit, [(finding, "codex")]
            )

        self.assertEqual(self.subject.runner.calls, 1)
        self.assertEqual(self.subject.state["failure"]["type"], "busy")
        self.assertIsNotNone(self.subject.state["failure"]["resume_at"])
        self.assertFalse(os.path.exists(self.subject._busy_path()))

    def test_rating_policy_preparation_failure_is_recorded_before_dispatch(self):
        unit = state.current_unit(self.subject.state)
        finding = {
            "id": "F1", "severity": "P3", "summary": "Ambiguous text.",
            "validity": {}, "plain": "A builder can read it two ways.",
            "example": "One builder chooses the wrong branch.",
        }

        with mock.patch.object(
            judgment_calls,
            "prepare",
            side_effect=verifiers.PolicyConfigError("invalid rating policy"),
        ):
            with self.assertRaises(driver.StopStep):
                self.subject._partition_defer_candidates(
                    unit, [(finding, "codex")]
                )

        self.assertEqual(self.subject.runner.calls, [])
        self.assertEqual(
            self.subject.state["failure"]["type"], "orchestrator"
        )
        self.assertTrue(self.subject.state["failure"]["reason"])
        self.assertFalse(os.path.exists(self.subject._busy_path()))

    def test_rating_authority_failure_preserves_parent_review_accounting(self):
        unit = state.current_unit(self.subject.state)
        self.subject.state["project"] = {
            "directory": self.workspace,
            "project": "orchestrators",
            "work_area": "implementation",
            "primary": {"path": self.workspace, "device": 1},
            "additional": [],
        }
        self.subject._save()
        usage = {
            "input_tokens": 20,
            "cached_input_tokens": 5,
            "output_tokens": 4,
            "reasoning_output_tokens": 1,
            "total_tokens": 24,
        }
        parent = runners.RunnerResult(
            '{"status":"ok","kind":"review_round"}', 0, 0.01,
            token_usage=usage,
        )
        self.assertTrue(self.subject._mark_busy(
            "parent-review", contracts.KIND_REVIEW_ROUND, "codex"
        ))
        self.assertTrue(self.subject._update_busy_accounting(parent))
        parent.cost = {"api_usd": 0.02, "real_usd": 0.0}
        parent.cost_partial = False
        finding = {
            "id": "F1", "severity": "P3", "summary": "Ambiguous text.",
            "validity": {}, "plain": "A builder can read it two ways.",
            "example": "One builder chooses the wrong branch.",
        }

        with mock.patch.object(
            self.subject,
            "_read_standing_law",
            side_effect=driver._StandingLawError("unreadable authority"),
        ):
            with self.assertRaises(driver.StopStep):
                self.subject._partition_defer_candidates(
                    unit,
                    [(finding, "codex")],
                    parent_call=(
                        contracts.KIND_REVIEW_ROUND, "codex", parent
                    ),
                )

        parent_events = [
            event for event in self.subject.state["events"]
            if event["type"] == "worker_unaccepted"
            and event["kind"] == contracts.KIND_REVIEW_ROUND
        ]
        self.assertEqual(len(parent_events), 1)
        self.assertEqual(parent_events[0]["unit"], state.unit_key(unit))
        self.assertEqual(parent_events[0]["duration_s"], parent.duration_s)
        self.assertEqual(parent_events[0]["token_usage"], usage)
        self.assertEqual(parent_events[0]["cost"], parent.cost)
        summary = state.summary(self.subject.state)
        self.assertEqual(summary["work_duration_s"], parent.duration_s)
        self.assertEqual(summary["work_token_usage"], usage)
        self.assertEqual(summary["work_cost"], parent.cost)
        self.assertEqual(
            self.subject.state["failure"]["reason"],
            "project standing law unavailable for the reclassify call: "
            "unreadable authority",
        )
        self.assertFalse(os.path.exists(self.subject._busy_path()))

    def test_rating_correction_keeps_coordinates_after_plan_deletes_slice(self):
        skeleton_unit = state.current_unit(self.subject.state)
        skeleton_unit["status"] = state.U_SEALED
        slice_doc = state.ensure_next_unit(self.subject.state)
        slice_doc["status"] = state.U_SEALED
        slice_doc["artifact"] = "implementation/slices/slice-01.md"
        unit = state.ensure_next_unit(self.subject.state)
        unit["artifact"] = "orchestrator/driver.py"
        self.subject._save()

        def replace_plan(workspace):
            with open(
                os.path.join(workspace, self.skeleton), "w", encoding="utf-8"
            ) as handle:
                handle.write(canonical_document("Replacement", slice_id=2))

        self.subject.runner = runners.MockRunner([
            {
                "expect_kind": "reclassify",
                "side_effect": replace_plan,
                "response": {"bad": 1},
            },
            {
                "expect_kind": "reclassify",
                "response": {
                    "status": "ok",
                    "kind": "reclassify",
                    "drift_risk": "high",
                    "drift_damage": "high",
                    "reason": "The ambiguity materially affects builders.",
                    "questions": self.questions(),
                },
            },
        ])
        finding = {
            "id": "F1", "severity": "P3", "summary": "Ambiguous text.",
            "validity": {}, "plain": "A builder can read it two ways.",
            "example": "One builder chooses the wrong branch.",
        }

        debt, retained = self.subject._partition_defer_candidates(
            unit, [(finding, "codex")]
        )

        self.assertEqual(debt, [])
        self.assertEqual(retained, [(finding, "codex")])
        self.assertEqual(len(self.subject.runner.calls), 2)
        self.assertEqual(
            [item["id"] for item in self.subject.state["milestone"]["slices"]],
            [2],
        )

    def test_exhausted_rating_keeps_parent_on_captured_unit_after_plan_change(self):
        skeleton_unit = state.current_unit(self.subject.state)
        skeleton_unit["status"] = state.U_SEALED
        slice_doc = state.ensure_next_unit(self.subject.state)
        slice_doc["status"] = state.U_SEALED
        slice_doc["artifact"] = "implementation/slices/slice-01.md"
        unit = state.ensure_next_unit(self.subject.state)
        unit["artifact"] = "orchestrator/driver.py"
        self.subject._save()

        def replace_plan(workspace):
            with open(
                os.path.join(workspace, self.skeleton), "w", encoding="utf-8"
            ) as handle:
                handle.write(canonical_document("Replacement", slice_id=2))

        self.subject.runner = runners.MockRunner([
            {
                "expect_kind": "reclassify",
                "side_effect": replace_plan,
                "response": {"bad": 1},
            },
            {"expect_kind": "reclassify", "response": {"bad": 2}},
        ])
        finding = {
            "id": "F1", "severity": "P3", "summary": "Ambiguous text.",
            "validity": {}, "plain": "A builder can read it two ways.",
            "example": "One builder chooses the wrong branch.",
        }
        parent = runners.RunnerResult(
            '{"status":"ok","kind":"review_round"}', 0, 0.01
        )

        with self.assertRaises(driver.StopStep):
            self.subject._partition_defer_candidates(
                unit,
                [(finding, "codex")],
                parent_call=(contracts.KIND_REVIEW_ROUND, "codex", parent),
            )

        parent_events = [
            event for event in self.subject.state["events"]
            if event["type"] == "worker_unaccepted"
            and event["kind"] == contracts.KIND_REVIEW_ROUND
        ]
        self.assertEqual(len(parent_events), 1)
        self.assertEqual(parent_events[0]["unit"], state.unit_key(unit))


if __name__ == "__main__":
    unittest.main()
