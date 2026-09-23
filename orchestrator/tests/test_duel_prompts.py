"""Duel's independent routes, context questions and operational replies."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from orchestrator import contracts, prompt_contracts, prompt_router, prompt_sets


ROOT = Path(__file__).resolve().parents[2]


class DuelPromptsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-duel-prompts-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.values = {
            "workspace": "/workspace", "request": "Write a complete proposal.",
            "context": "{}", "references": "[]", "candidate_id": "a",
            "candidate_directory": "/workspace/duel/a",
            "opponent_directory": "/workspace/duel/b", "round": 1,
            "max_rounds": 3, "previous_reviews": "[]", "artifacts": '["proposal.md"]',
        }

    def route(self, role, prompt_set_name="default", material="document"):
        return prompt_router.resolve(
            self.home, job=("author_candidate" if role == "author" else "review_candidate") + "@duel",
            executor="agent_call", material=material, values=self.values,
            prompt_set=prompt_set_name,
        )

    def replies(self, role):
        bound = prompt_contracts.bind(self.route(role).prompt)
        reply = (
            {"action": "revise", "artifacts": ["proposal.md", "appendix/sources.md"], "summary": "Wrote the complete proposal."}
            if role == "author" else
            {"score": 0.7, "report": "# Review\nThe proposed schedule omits the stated delivery constraint."}
        )
        reply["questions"] = [{"id": item, "answer": "No supporting evidence found."} for item in bound.question_ids]
        return bound, reply

    def test_routes_have_dedicated_questions_and_operational_sections(self):
        for role in ("author", "review"):
            with self.subTest(role=role):
                served = self.route(role).prompt
                bound = prompt_contracts.bind(served)
                rendered = prompt_router.render(served, self.values)
                self.assertEqual(served["kind"], "duel_" + role)
                self.assertEqual(bound.registered_section_ids, ("duel_" + role + "_result", "questions_output"))
                self.assertTrue(all(identifier.startswith(role + "_") for identifier in bound.question_ids))
                self.assertIn("candidate_id: a", rendered)
                self.assertIn("candidate_directory: /workspace/duel/a", rendered)
                self.assertIn("round: 1", rendered)
                self.assertIn("driver discards", rendered)
                self.assertNotIn("ready_revision", rendered)
                if role == "author":
                    self.assertIn("opponent_directory: /workspace/duel/b", rendered)
                    self.assertIn("No diversity", rendered)
                else:
                    self.assertNotIn("/workspace/duel/b", rendered)
                    self.assertNotIn("PREVIOUS REVIEWS", rendered)
                    self.assertIn("Do not concede merely because a claim sounds", rendered)

    def test_author_contract_requires_real_delivery_shape_and_initial_production(self):
        bound, reply = self.replies("author")
        self.assertIs(prompt_contracts.validate(bound, reply, duel_round=1), reply)
        finished = dict(reply, action="finish")
        self.assertIs(prompt_contracts.validate(bound, finished, duel_round=2), finished)
        invalid = [
            (finished, 1), (dict(reply, action="continue"), 2),
            (dict(reply, artifacts=[]), 1),
            (dict(reply, artifacts=["../b/proposal.md"]), 1),
            (dict(reply, artifacts=["/workspace/duel/a/proposal.md"]), 1),
            (dict(reply, artifacts=["proposal.md", "proposal.md"]), 1),
            (dict(reply, summary=" "), 1),
            (dict(reply, ready=True), 1),
        ]
        for record, round_number in invalid:
            with self.subTest(record=record, round=round_number):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(bound, record, duel_round=round_number)

    def test_review_contract_has_no_vote_and_only_checks_score_and_report_shape(self):
        bound, reply = self.replies("review")
        for score in (0, 0.5, 1):
            record = dict(reply, score=score)
            self.assertIs(prompt_contracts.validate(bound, record), record)
        for score in (True, -0.01, 1.01, float("nan"), float("inf"), "0.7"):
            with self.subTest(score=score):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(bound, dict(reply, score=score))
        for record in (dict(reply, report=" "), dict(reply, vote="accept")):
            with self.assertRaises(contracts.ContractError):
                prompt_contracts.validate(bound, record)

    def test_context_answers_have_structural_but_no_semantic_authority(self):
        for role in ("author", "review"):
            bound, reply = self.replies(role)
            for answer in ("No, unresolved.", "Yes, complete.", "Not applicable."):
                record = copy.deepcopy(reply)
                for question in record["questions"]:
                    question["answer"] = answer
                self.assertIs(prompt_contracts.validate(bound, record, duel_round=1), record)
            with self.assertRaises(contracts.ContractError):
                prompt_contracts.validate(bound, dict(reply, questions=[]), duel_round=1)

    def test_literature_set_is_complete_and_keeps_its_own_duel_questions(self):
        documents = {
            member: json.loads((ROOT / "prompt_sets/literature" / member).read_text())
            for member in prompt_sets.CANONICAL_MEMBERS
        }
        self.write_set("literature", documents)
        for material in ("document", "code", "literature"):
            for role in ("author", "review"):
                with self.subTest(role=role, material=material):
                    resolved = self.route(role, "literature", material)
                    self.assertIsNone(resolved.prompt_set_fallback)
                    rendered = prompt_router.render(resolved.prompt, self.values)
                    self.assertIn("LITERATURE:", rendered)
                    self.assertIn(role + "_literary_voice", rendered)
                    self.assertIn("established canon", rendered)
                    self.assertEqual(len(prompt_contracts.bind(resolved.prompt).question_ids), 7)

    def test_review_combines_opposition_and_dante_questions_in_the_saved_report(self):
        documents = {
            member: json.loads((ROOT / "prompt_sets/literature" / member).read_text())
            for member in prompt_sets.CANONICAL_MEMBERS
        }
        self.write_set("literature", documents)
        for set_name in ("default", "literature"):
            with self.subTest(prompt_set=set_name):
                reviewer = self.route("review", set_name).prompt
                rendered = prompt_router.render(reviewer, self.values)
                self.assertIn("Try to disprove", rendered)
                self.assertIn("DANTE'S ANTI-DRIFT QUESTIONS FOR THE AUTHOR", rendered)
                self.assertIn("few simple, awkward questions", rendered)
                self.assertIn("observable\ndamage", rendered)
                self.assertIn("ordinary permitted operation", rendered)
                self.assertIn("clearly labeled section of the report Markdown", rendered)
                self.assertIn("do not answer your own questions", rendered)
                self.assertIn('"No further questions."', rendered)
                self.assertIn("not only in the top-level questions", rendered)
                self.assertIn("extra agent, separate turn, vote, readiness field or condition", rendered)
                bound = prompt_contracts.bind(reviewer)
                reply = {
                    "score": 0.8,
                    "report": "# Assessment\nUseful plan; delivery timing is uncertain.\n\n## Questions for the author\nWho needs the result before the stated deadline?",
                    "questions": [{"id": item, "answer": "Inspected the request."} for item in bound.question_ids],
                }
                self.assertIs(prompt_contracts.validate(bound, reply), reply)
                author = prompt_router.render(self.route("author", set_name).prompt, self.values)
                self.assertIn("anti-drift questions addressed to you", author)
                self.assertIn("do not invent changes or disagreement", author)
                if set_name == "literature":
                    self.assertIn("LITERARY ANTI-DRIFT QUESTIONS", rendered)
                    self.assertIn("surrounding voice and continuity", rendered)
                    self.assertIn("Do not require a question for each lens", rendered)

    def write_set(self, name, documents):
        directory = Path(prompt_sets.prompt_set_dir(self.home, name))
        for member, document in documents.items():
            path = directory / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document))
        return directory

    def test_pre_duel_stored_set_uses_existing_whole_set_fallback_without_repair(self):
        documents = prompt_sets.default_seed().documents
        old_documents = {key: value for key, value in documents.items() if not key.startswith("duel/")}
        directory = self.write_set("literature", old_documents)
        self.write_set("default", old_documents)
        original = {path: path.read_bytes() for path in directory.rglob("*.json")}
        self.assertEqual(self.route("author", "literature").prompt_set_fallback, "in_code_seed")
        self.assertFalse((directory / "duel").exists())
        self.assertEqual(original, {path: path.read_bytes() for path in directory.rglob("*.json")})
        self.write_set("default", documents)
        self.assertEqual(self.route("review", "literature").prompt_set_fallback, "stored_default")


if __name__ == "__main__":
    unittest.main()
