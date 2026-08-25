"""Focused proof for the reusable direct-judgment call package."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from orchestrator import contracts, judgment_calls, prompt_sets, verifiers


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
            "scratch_path": ".consultations/",
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
                    prepared.prompt.count(
                        "CURRENT MUTABLE OPERATOR AMENDMENTS: none."
                    ),
                    1,
                )
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

    def test_fixer_prompt_and_validator_share_one_frozen_finding_queue(self):
        queued = [{
            "id": "F1",
            "severity": "P2",
            "summary": "The served and validated queues can diverge.",
        }]
        expected = json.dumps(
            queued, ensure_ascii=False, sort_keys=True, indent=2
        )
        prepared = self.prepare(
            "fix_findings@slice_impl", queued_findings=queued
        )
        self.assertIn(expected, prepared.prompt)

        queued[0]["id"] = "F2"
        reply = {
            "status": "ok",
            "kind": "fix_findings",
            "findings": [],
            "files_changed": [],
            "questions": answers(prepared.bound),
        }
        with self.assertRaisesRegex(
            contracts.ContractError, r"queued=\['F1'\] got=\[\]"
        ):
            prepared.validate(reply)

        values = values_for(self.temp.name, "fix_findings@slice_impl")
        values["queued_findings"] = "[]"
        with self.assertRaisesRegex(
            ValueError, "judgment-owned values are adapter-owned"
        ):
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
                "full review of the selected milestone unit",
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
                "a" * 40,
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
                '"id": "F1"',
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
                "the selected milestone unit",
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
                "consult --family claude",
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
                "FINDING (severity P3, id F1)",
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
                "implementation/milestones/router/slice-06.md",
            ),
        )
        for name, job, omit_payload, options, served_payload in cases:
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
                self.assertIn(served_payload, prepared.prompt)

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

    def test_current_amendment_set_is_complete_replacing_and_required(self):
        current = self.prepare(
            "review_round@skeleton",
            amendments=[
                {"id": "A2", "text": "Use the bounded path."},
                {
                    "id": "B1",
                    "text": "Keep one canonical plan.",
                    "authority": "brainstorming_design",
                },
            ],
        )
        self.assertIn(
            "This set replaces every mutable operator amendment shown earlier.",
            current.prompt,
        )
        self.assertIn("[A2] Use the bounded path.", current.prompt)
        self.assertIn(
            "ACCEPTED BRAINSTORMING DESIGN AMENDMENTS (append-only)",
            current.prompt,
        )
        self.assertNotIn(
            "CURRENT MUTABLE OPERATOR AMENDMENTS: none.", current.prompt
        )

        with self.assertRaisesRegex(
            ValueError, "current mutable operator amendments are unavailable"
        ):
            self.prepare(
                "review_round@skeleton", operator_complete=False
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
        prepared = self.prepare(
            "reclassify@doc",
            project_context=project_context(
                self.temp.name, [complete_policy]
            ),
        )
        self.assertIn(complete_policy["prompt"], prepared.prompt)
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
                with self.assertRaisesRegex(
                    ValueError, "missing authority field %r" % missing
                ):
                    self.prepare(
                        "review_round@skeleton",
                        project_context=authority,
                    )

        malformed = copy.deepcopy(complete)
        malformed["safeguards"] = None
        with self.assertRaisesRegex(
            ValueError, "project_context.safeguards must be a list"
        ):
            self.prepare(
                "review_round@skeleton", project_context=malformed
            )

        malformed = copy.deepcopy(complete)
        malformed["reuse_sources"] = [{}]
        with self.assertRaisesRegex(
            ValueError, "reuse source has invalid fields"
        ):
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
        with self.assertRaisesRegex(
            verifiers.PolicyConfigError, "outside every granted"
        ):
            self.prepare(
                "reclassify@doc",
                project_context=project_context(
                    self.temp.name, [inventory_policy]
                ),
            )

    def test_question_answers_enforce_the_authored_300_character_limit(self):
        prepared = self.prepare("review_round@skeleton")
        self.assertIn(
            "non-empty answer per mounted id and at most 300 characters",
            prepared.prompt,
        )
        rating = self.prepare("reclassify@doc")
        self.assertIn(
            "each answer must be non-empty and at most 300 characters",
            rating.prompt,
        )
        reply = {
            "status": "ok",
            "kind": "review_round",
            "findings": [],
            "questions": answers(prepared.bound, "x" * 300),
        }
        self.assertEqual(prepared.validate(copy.deepcopy(reply)), reply)
        reply["questions"][0]["answer"] = "x" * 301
        with self.assertRaisesRegex(
            contracts.ContractError, "at most 300 characters"
        ):
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
        with self.assertRaisesRegex(
            ValueError, "not a direct milestone judgment charge"
        ):
            self.prepare("implement@slice_impl")

        with self.assertRaisesRegex(
            ValueError, "requires its queued findings"
        ):
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


if __name__ == "__main__":
    unittest.main()
