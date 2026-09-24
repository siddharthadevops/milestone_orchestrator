"""Fresh suite failures cannot be disposed through historic adjudications."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from orchestrator import contracts, judgment_calls, prompt_sets, prompts
from orchestrator.tests.test_judgment_call_cutover import answers, values_for
from orchestrator.tests.test_prompt_contracts import fix_finding, report_finding


REJECTION_ID = "slice-01-impl-codex-r1/R1"
DEBT = {"id": "claude-C1", "severity": "P3", "summary": "Legacy fixtures"}


class SuiteFixerContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="suite-fixer-contract-")
        self.addCleanup(self.temp.cleanup)

    def prepare(self, job="fix_findings@slice_impl", **changes):
        options = {
            "job": job,
            "material": "code",
            "values": values_for(self.temp.name, job),
            "amendments": [],
        }
        if job.startswith("fix_findings"):
            options["queued_findings"] = [report_finding()]
        options.update(changes)
        return judgment_calls.prepare(self.temp.name, **options)

    def reply(self, prepared, disposition="rejected", ref=None):
        result = fix_finding(disposition)
        result["adjudication_ref"] = ref
        return {
            "status": "ok", "kind": "fix_findings", "findings": [result],
            "files_changed": [], "questions": answers(prepared.bound),
        }

    def test_ordinary_adjudication_is_validated_against_frozen_registry(self):
        registry_ids = {REJECTION_ID}
        prepared = self.prepare(adjudication_ids=registry_ids)
        registry_ids.clear()
        registry_ids.add(DEBT["id"])

        reply = self.reply(prepared, "rejected_adjudicated", REJECTION_ID)
        self.assertEqual(prepared.validate(reply), reply)
        for ref in (DEBT["id"], "nonexistent-id"):
            with self.subTest(ref=ref):
                with self.assertRaisesRegex(contracts.ContractError, "adjudication_ref"):
                    prepared.validate(self.reply(prepared, "rejected_adjudicated", ref))

    def test_every_nonnull_reference_must_be_an_actual_adjudication(self):
        prepared = self.prepare(adjudication_ids=[REJECTION_ID])
        for disposition in ("fixed", "rejected", "blocked", "rejected_adjudicated"):
            for ref in (DEBT["id"], "nonexistent-id", "", [REJECTION_ID]):
                with self.subTest(disposition=disposition, ref=ref):
                    with self.assertRaises(contracts.ContractError):
                        prepared.validate(self.reply(prepared, disposition, ref))
        empty_registry = self.prepare()
        with self.assertRaisesRegex(contracts.ContractError, "adjudication_ref"):
            empty_registry.validate(
                self.reply(empty_registry, "rejected_adjudicated", REJECTION_ID)
            )

    def test_suite_origin_rejects_adjudication_even_when_registry_id_exists(self):
        prepared = self.prepare(
            suite_checkpoint_origin=True, adjudication_ids=[REJECTION_ID]
        )
        with self.assertRaisesRegex(
            contracts.ContractError, "rejected_adjudicated is forbidden"
        ):
            prepared.validate(self.reply(prepared, "rejected_adjudicated", REJECTION_ID))

    def test_suite_origin_admits_direct_judgment_blocked_and_rethink(self):
        prepared = self.prepare(suite_checkpoint_origin=True)
        for disposition in ("fixed", "rejected", "blocked"):
            with self.subTest(disposition=disposition):
                reply = self.reply(prepared, disposition)
                self.assertEqual(prepared.validate(reply), reply)
        for reply in (
            {"status": "blocked", "kind": "fix_findings",
             "blocked_reason": "The required test service is unavailable."},
            {"status": "need_rethink",
             "problem": "The fixture contract contradicts the current schema."},
        ):
            reply["questions"] = answers(prepared.bound)
            self.assertEqual(prepared.validate(reply), reply)

    def test_runtime_instruction_covers_installed_prompt_without_changing_store(self):
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        documents["milestone/fix_findings.json"]["instructions"]["parts"].append({
            "text": ["INSTALLED FIXER: use rejected_adjudicated for settled duplicates."],
            "variables": [],
        })
        directory = Path(prompt_sets.prompt_set_dir(self.temp.name, "installed"))
        for member, document in documents.items():
            path = directory / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding="utf-8")
        before = {path: path.read_bytes() for path in directory.rglob("*.json")}

        prepared = self.prepare(prompt_set="installed", suite_checkpoint_origin=True)

        self.assertIsNone(prepared.prompt_set_fallback)
        self.assertIn("INSTALLED FIXER", prepared.prompt)
        self.assertEqual(prepared.prompt.count("The checkpoint failure is new evidence"), 1)
        self.assertIn("rejected_adjudicated is forbidden even if a generic prompt offers it", prepared.prompt)
        self.assertIn("If the governing design contradicts the required fix, use need_rethink", prepared.prompt)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        ordinary = self.prepare(prompt_set="installed")
        self.assertIn("INSTALLED FIXER", ordinary.prompt)
        self.assertNotIn("The checkpoint failure is new evidence", ordinary.prompt)

    def test_legacy_suite_prompt_omits_settled_context_and_duplicate_path(self):
        registry = [{"id": REJECTION_ID, "summary": "Prior rejection"}]
        args = ("codex", self.temp.name, "goal.md", "implementation", [report_finding()], registry)
        prompt = prompts.build_fix_findings(
            *args, debt=[DEBT], suite_checkpoint_origin=True
        )
        self.assertNotIn("DEFERRED DEBT", prompt)
        self.assertNotIn("ADJUDICATED REJECTIONS", prompt)
        self.assertNotIn(DEBT["id"], prompt)
        self.assertNotIn(REJECTION_ID, prompt)
        self.assertNotIn("settled duplicate without new evidence", prompt)
        self.assertIn("rejected_adjudicated is forbidden even if a generic prompt offers it", prompt)
        self.assertIn("The checkpoint failure is new evidence", prompt)

        ordinary = prompts.build_fix_findings(*args, debt=[DEBT])
        self.assertIn("DEFERRED DEBT", ordinary)
        self.assertIn("ADJUDICATED REJECTIONS", ordinary)
        self.assertIn(DEBT["id"], ordinary)
        self.assertIn(REJECTION_ID, ordinary)
        self.assertIn("settled duplicate without new evidence", ordinary)
        self.assertNotIn("The checkpoint failure is new evidence", ordinary)

    def test_reviewers_keep_adjudication_and_debt_context_and_contests(self):
        registry = [{"id": REJECTION_ID, "summary": "Prior rejection"}]
        for builder, extra in (
            (prompts.build_review_round, ("docs/slice-01.md",)),
            (prompts.build_delta_review, ()),
        ):
            text = builder(
                "codex", self.temp.name, "goal.md", "implementation",
                *extra, registry, debt=[DEBT],
            )
            self.assertIn("DEFERRED DEBT", text)
            self.assertIn("ADJUDICATED REJECTIONS", text)
            self.assertIn(DEBT["id"], text)
            self.assertIn(REJECTION_ID, text)
            self.assertNotIn("The checkpoint failure is new evidence", text)
        for job in ("review_round@slice_impl", "delta_review@slice_impl"):
            prepared = self.prepare(job, contestable_ids=[DEBT["id"], REJECTION_ID])
            finding = report_finding()
            finding["contests"] = {
                "rejection_id": DEBT["id"], "new_evidence": "Current test failed."
            }
            reply = {
                "kind": job.split("@", 1)[0], "status": "ok",
                "findings": [finding], "questions": answers(prepared.bound),
            }
            self.assertEqual(prepared.validate(reply), reply)
            self.assertNotIn("The checkpoint failure is new evidence", prepared.prompt)


if __name__ == "__main__":
    unittest.main()
