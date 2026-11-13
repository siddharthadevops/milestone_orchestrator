"""Exercise the stored legal corpus through routing and served reply contracts.

These tests prove that the authored set is usable as a complete independent
corpus. They do not attempt to judge legal reasoning or research quality.
"""

import copy
from pathlib import Path
import unittest

from orchestrator import contracts, prompt_contracts, prompt_router, prompt_sets


ROOT = Path(__file__).resolve().parents[2]
MATERIALS = ("default", "code", "legal")


def fixture_values(prompt_set):
    """Provide opaque substitutions while leaving router-owned values alone."""
    names = set()
    fixed = {"kind", "role", "workarea_boundary"}

    def walk(value):
        if isinstance(value, dict):
            names.update(item["name"] for item in value.get("variables", ()))
            if isinstance(value.get("defaults"), dict):
                fixed.update(value["defaults"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(prompt_set.documents)
    return {name: "fixture value" for name in names - fixed}


class LegalPromptSetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prompt_set = prompt_sets.load(str(ROOT), "legal")
        cls.all_values = fixture_values(cls.prompt_set)

    def values(self, job):
        values = dict(self.all_values)
        if job != "draft_skeleton@skeleton":
            values.pop("task_executor_catalogue", None)
        return values

    def route(self, job, *, material="legal", executor="agent_call", **seat):
        values = self.values(job)
        coordinates = dict(job=job, executor=executor, material=material,
                           values=values, **seat)
        assembled = prompt_router.assemble(self.prompt_set, **coordinates)
        selected = prompt_router.resolve(str(ROOT), prompt_set="legal", **coordinates)
        self.assertIsNone(selected.prompt_set_fallback)
        self.assertEqual(selected.prompt, assembled)
        rendered = prompt_router.render(assembled, values)
        self.assertTrue(rendered.strip())
        self.assertNotRegex(rendered, r"\{\{[A-Za-z_]\w*\}\}")
        bound = prompt_contracts.bind(assembled)
        self.assertEqual(len(bound.question_ids), len(set(bound.question_ids)))
        section_ids = [section["id"] for section in assembled["output_contract"]]
        self.assertEqual(len(section_ids), len(set(section_ids)))
        return assembled, bound

    @staticmethod
    def answers(bound):
        return [{"id": question_id, "answer": "Fixture contract answer."}
                for question_id in bound.question_ids]

    def assert_required_questions(self, bound, reply, **options):
        self.assertTrue(bound.question_ids)
        self.assertIs(prompt_contracts.validate(bound, reply, **options), reply)
        for change in ("missing_field", "missing_answer", "duplicate_answer"):
            malformed = copy.deepcopy(reply)
            if change == "missing_field":
                malformed.pop("questions")
            elif change == "missing_answer":
                malformed["questions"].pop()
            else:
                malformed["questions"].append(copy.deepcopy(malformed["questions"][0]))
            with self.subTest(question_failure=change):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(bound, malformed, **options)

    def test_stored_corpus_loads_completely_without_fallback(self):
        corpus = ROOT / "prompt_sets" / "legal"
        members = {str(path.relative_to(corpus)) for path in corpus.rglob("*.json")}
        self.assertEqual(members, set(prompt_sets.CANONICAL_MEMBERS))
        resolved = prompt_sets.resolve(str(ROOT), "legal")
        self.assertIsNone(resolved.prompt_set_fallback)
        self.assertEqual(resolved.prompt_set.name, "legal")
        self.assertEqual(resolved.prompt_set, self.prompt_set)
        self.assertIn("legal", prompt_sets.list_names(str(ROOT)))

    def test_every_direct_route_assembles_renders_and_binds(self):
        for material in MATERIALS:
            for job, (kind, _) in prompt_router.DIRECT_ROUTES.items():
                with self.subTest(material=material, job=job):
                    prompt, _ = self.route(job, material=material)
                    self.assertEqual(prompt["kind"], kind)

    def test_creativity_prompts_include_confidential_search_instructions(self):
        for material in MATERIALS:
            for kind in ("create_genes", "compose_candidates", "evaluate_candidates", "expand_genes"):
                job = kind + "@creativity"
                with self.subTest(material=material, job=job):
                    prompt, _ = self.route(job, material=material)
                    rendered = " ".join(prompt_router.render(prompt, self.values(job)).split())
                    self.assertIn("Keep searches generic or anonymized.", rendered)
                    self.assertIn(
                        "Do not send confidential documents or identifying client facts "
                        "to public search services.", rendered,
                    )

    def test_every_session_role_and_target_preserves_inherited_questions(self):
        for material in MATERIALS:
            for job in prompt_router.SESSION_JOBS:
                targets = ("document", "implementation") if job == "rethink" else (None,)
                for target in targets:
                    for (role, lead), kind in prompt_router.SEATS.items():
                        with self.subTest(material=material, job=job, target=target,
                                          role=role):
                            prompt, bound = self.route(
                                job, material=material, executor="brainstorming",
                                role=role, lead=lead, artifact_type=target,
                            )
                            self.assertEqual(prompt["kind"], kind)
                            if lead and job in ("draft_slice_note@slice_doc", "implement@slice_impl"):
                                _, charge = self.route(job, material=material)
                                self.assertTrue(set(charge.question_ids).issubset(bound.question_ids))
                                self.assertGreater(len(bound.question_ids), len(charge.question_ids))
                            reply = {"kind": kind, "markdown": "Fixture session turn.",
                                     "questions": self.answers(bound)}
                            self.assert_required_questions(bound, reply)

    def test_duel_contracts_keep_real_artifacts_and_joint_review(self):
        for job in ("author_candidate@duel", "review_candidate@duel"):
            with self.subTest(job=job):
                _, bound = self.route(job)
                reply = (
                    {"action": "revise", "artifacts": ["analysis.md"],
                     "summary": "Fixture delivery."}
                    if job == "author_candidate@duel" else
                    {"scores": {"a": 0.4, "b": 0.6}, "report": "Fixture shared review."}
                )
                reply["questions"] = self.answers(bound)
                self.assert_required_questions(bound, reply, duel_round=1)
                malformed = copy.deepcopy(reply)
                if job == "author_candidate@duel":
                    malformed["artifacts"] = ["../other/analysis.md"]
                else:
                    malformed["scores"].pop("b")
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(bound, malformed, duel_round=1)

    def test_creativity_reply_shapes_require_the_mounted_legal_questions(self):
        cases = (
            ("create_genes", {"gene_pool": ["notice", "alternative", "sequence"]},
             {"creativity_semantics": "fragments_v3", "gene_count": 3}),
            ("compose_candidates", {"compositions": [
                {"candidate_id": "c1", "proposal": "Fixture conditional proposal."}]},
             {"candidate_ids": ["c1"]}),
            ("evaluate_candidates", {"evaluations": [
                {"candidate_id": "c1", "constraint_valid": False,
                 "constraint_violations": ["__insufficient_detail__"],
                 "reason": "Fixture missing context.", "assumptions": [], "score": 0}]},
             {"candidate_ids": ["c1"], "constraint_ids": []}),
        )
        for kind, reply, options in cases:
            with self.subTest(kind=kind):
                _, bound = self.route(kind + "@creativity")
                reply["questions"] = self.answers(bound)
                self.assert_required_questions(bound, reply, **options)
                malformed = copy.deepcopy(reply)
                if kind == "create_genes":
                    malformed["gene_pool"].append("extra")
                elif kind == "compose_candidates":
                    malformed["compositions"][0]["candidate_id"] = "unknown"
                else:
                    malformed["evaluations"][0]["score"] = 0.5
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(bound, malformed, **options)

    def test_expansion_preserves_the_additions_only_contract(self):
        _, bound = self.route("expand_genes@creativity")
        self.assertEqual(bound.question_ids, ())
        dimensions = [{"id": "approach", "variants": [{"id": "existing"}]}]
        for reply in ({"additions": []}, {"additions": [
            {"dimension_id": "approach", "variants": [
                {"id": "new", "text": "Fixture alternative", "reason": "Fixture basis."}]}]}):
            with self.subTest(reply=reply):
                self.assertIs(prompt_contracts.validate(bound, reply, dimensions=dimensions), reply)
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(bound, dict(reply, questions=[]), dimensions=dimensions)
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(bound, {"additions": [
                {"dimension_id": "unknown", "variants": [
                    {"id": "new", "text": "Alternative", "reason": "Basis"}]}]},
                dimensions=dimensions)


if __name__ == "__main__":
    unittest.main()
