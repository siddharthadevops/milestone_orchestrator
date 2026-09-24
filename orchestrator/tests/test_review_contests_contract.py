"""Review references are corrected before findings enter durable history."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from orchestrator import contracts, driver as drv, judgment_calls
from orchestrator import prompt_contracts, prompt_router, prompt_sets, runners
from orchestrator import state as st
from orchestrator.tests.test_driver_mock import (
    DriverTestCase, append_file, finding, fix_ok, init_state, make_config,
    report, step, triaged,
)
from orchestrator.tests.test_judgment_call_cutover import answers, values_for
from orchestrator.tests.test_p3_debt import draft_step, reclassify
from orchestrator.tests.test_prompt_contracts import report_finding


REVIEW_JOBS = ("review_round@slice_impl", "delta_review@slice_impl")
DEBT_ID = "claude-C1"
REGISTRY_ID = "slice-01-impl-codex-r1/R1"


class ReviewContestsContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="review-contests-")
        self.addCleanup(self.temp.cleanup)

    def prepare(self, job, **changes):
        options = {
            "job": job, "material": "code",
            "values": values_for(self.temp.name, job), "amendments": [],
        }
        options.update(changes)
        return judgment_calls.prepare(self.temp.name, **options)

    def reply(self, prepared, job, ref=None):
        entry = report_finding()
        if ref is not None:
            entry["contests"] = {
                "rejection_id": ref, "new_evidence": "The current test fails.",
            }
        return {
            "status": "ok", "kind": job.split("@", 1)[0],
            "findings": [entry], "questions": answers(prepared.bound),
        }

    def test_active_debt_and_registry_ids_are_accepted_by_both_review_kinds(self):
        for job in REVIEW_JOBS:
            prepared = self.prepare(job, contestable_ids={DEBT_ID, REGISTRY_ID})
            for ref in (DEBT_ID, REGISTRY_ID, None):
                with self.subTest(job=job, ref=ref):
                    reply = self.reply(prepared, job, ref)
                    self.assertEqual(prepared.validate(reply), reply)

    def test_unknown_or_consumed_id_is_a_correctable_contract_error(self):
        for job in REVIEW_JOBS:
            prepared = self.prepare(job, contestable_ids={REGISTRY_ID})
            for ref in (DEBT_ID, "nonexistent-id"):
                with self.subTest(job=job, ref=ref):
                    with self.assertRaisesRegex(
                        contracts.ContractError, r"contests\.rejection_id"
                    ):
                        prepared.validate(self.reply(prepared, job, ref))
            empty = self.prepare(job)
            with self.assertRaises(contracts.ContractError):
                empty.validate(self.reply(empty, job, REGISTRY_ID))

    def test_preparation_freezes_the_current_reference_set(self):
        for job in REVIEW_JOBS:
            ids = {DEBT_ID, REGISTRY_ID}
            prepared = self.prepare(job, contestable_ids=ids)
            ids.clear()
            ids.add("later-id")
            with self.subTest(job=job):
                prepared.validate(self.reply(prepared, job, DEBT_ID))
                prepared.validate(self.reply(prepared, job, REGISTRY_ID))
                self.assertIn(
                    "Contestable IDs: " + json.dumps(sorted((DEBT_ID, REGISTRY_ID))),
                    prepared.prompt,
                )
                self.assertNotIn("later-id", prepared.prompt)
                with self.assertRaises(contracts.ContractError):
                    prepared.validate(self.reply(prepared, job, "later-id"))

    def test_trusted_reference_context_is_typed_and_only_for_reviewers(self):
        for ids in (None, "abc", {"abc": True}, [""], [2]):
            with self.subTest(ids=ids):
                with self.assertRaises(prompt_router.PromptRouterError):
                    self.prepare(REVIEW_JOBS[0], contestable_ids=ids)
        with self.assertRaises(prompt_router.PromptRouterError):
            self.prepare("reclassify@doc", contestable_ids={DEBT_ID})
        values = values_for(self.temp.name, REVIEW_JOBS[0])
        values["contestable_ids"] = [DEBT_ID]
        with self.assertRaises(prompt_router.PromptRouterError):
            self.prepare(REVIEW_JOBS[0], values=values)

    def test_legacy_unbound_validation_retains_structural_contract(self):
        for job in REVIEW_JOBS:
            prepared = self.prepare(job)
            reply = self.reply(prepared, job, "historical-id")
            self.assertEqual(prompt_contracts.validate(prepared.bound, reply), reply)

    def test_installed_review_prompts_receive_current_reference_instruction(self):
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        for member in ("milestone/review_round.json", "milestone/delta_review.json"):
            documents[member]["instructions"]["parts"].append({
                "text": ["INSTALLED REVIEW PROMPT"], "variables": [],
            })
        directory = Path(prompt_sets.prompt_set_dir(self.temp.name, "installed"))
        for member, document in documents.items():
            path = directory / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding="utf-8")
        before = {path: path.read_bytes() for path in directory.rglob("*.json")}
        for job in REVIEW_JOBS:
            prepared = self.prepare(job, prompt_set="installed")
            with self.subTest(job=job):
                self.assertIsNone(prepared.prompt_set_fallback)
                self.assertIn("INSTALLED REVIEW PROMPT", prepared.prompt)
                self.assertEqual(prepared.prompt.count("CONTEST REFERENCES"), 1)
                self.assertIn("current adjudicated rejection or active debt", prepared.prompt)
                self.assertIn("historical records or raw outputs", prepared.prompt)
                self.assertIn("contests: null", prepared.prompt)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_single_existing_correction_keeps_the_finding_with_null_contests(self):
        for job in REVIEW_JOBS:
            kind = job.split("@", 1)[0]
            prepared = self.prepare(job)
            invalid = self.reply(prepared, job, DEBT_ID)
            corrected = copy.deepcopy(invalid)
            corrected["findings"][0]["contests"] = None
            runner = runners.MockRunner([
                step(kind, invalid, family="codex"),
                step(kind, corrected, family="codex"),
            ])
            output, _ = runners.call_worker(
                runner, "codex", prepared.prompt, kind, self.temp.name,
                prepare_call=lambda error: self.prepare(job, correction=error),
            )
            with self.subTest(job=job):
                self.assertEqual(output, corrected)
                self.assertEqual(len(runner.calls), 2)
                self.assertEqual(runner.script, [])
                self.assertNotIn("CONTRACT CORRECTION", runner.calls[0][2])
                self.assertIn("CONTRACT CORRECTION", runner.calls[1][2])
                self.assertIn(DEBT_ID, runner.calls[1][2])
                self.assertEqual(
                    invalid["findings"][0]["contests"]["rejection_id"], DEBT_ID,
                )

    def test_two_invalid_replies_keep_existing_worker_output_failure(self):
        for job in REVIEW_JOBS:
            kind = job.split("@", 1)[0]
            prepared = self.prepare(job)
            invalid = self.reply(prepared, job, DEBT_ID)
            runner = runners.MockRunner([
                step(kind, invalid, family="codex"),
                step(kind, copy.deepcopy(invalid), family="codex"),
            ])
            with self.subTest(job=job):
                with self.assertRaisesRegex(
                    runners.WorkerOutputError, "contract-violating output twice"
                ):
                    runners.call_worker(
                        runner, "codex", prepared.prompt, kind, self.temp.name,
                        prepare_call=lambda error: self.prepare(job, correction=error),
                    )
                self.assertEqual(len(runner.calls), 2)
                self.assertEqual(runner.script, [])
                self.assertIn("CONTRACT CORRECTION", runner.calls[1][2])


class ReviewContestsDriverTest(DriverTestCase):
    def test_consumed_debt_reference_is_corrected_and_finding_reaches_fixer(self):
        with tempfile.TemporaryDirectory(prefix="review-contests-driver-") as workspace:
            path = init_state(workspace, make_config(p3_reclassify_debt=True))
            contest = {
                "rejection_id": "codex-F1",
                "new_evidence": "The topology responder takes a dead-end path.",
            }
            stale = finding(
                "F3", "The topology responder still misses a path", "P1",
                contests=contest,
            )
            corrected = copy.deepcopy(stale)
            corrected["contests"] = None
            runner = runners.MockRunner([
                draft_step(),
                step("review_round", report("review_round", [
                    finding("F1", "old wording"),
                ]), family="codex"),
                reclassify(True, family="claude", reason="cosmetic"),
                step("review_round", report("review_round", [finding(
                    "F2", "The responder has a dead end", "P1", contests=contest,
                )]), family="claude"),
                step("fix_findings", fix_ok([
                    triaged("F2", "fixed", severity="P1"),
                ], files_changed=["docs/skeleton.md"]), family="codex",
                    side_effect=append_file(
                        "docs/skeleton.md", "\nThe first responder path is now covered.\n",
                    )),
                step("delta_review", report("delta_review"), family="codex"),
                step("review_round", report("review_round", [stale]), family="codex"),
                step("review_round", report("review_round", [corrected]), family="codex"),
                step("fix_findings", fix_ok([
                    triaged("F3", "fixed", severity="P1"),
                ], files_changed=["docs/skeleton.md"]), family="codex",
                    side_effect=append_file(
                        "docs/skeleton.md", "\nThe remaining responder path is now covered.\n",
                    )),
            ])
            driver = drv.Driver(path, runner=runner)
            self.step_until(driver, lambda state: any(
                record["kind"] == "fix_findings"
                and any(entry["id"] == "F3"
                        for entry in record["result"].get("findings", []))
                for record in state["units"][0]["rounds"]
            ))

            state = st.load(path)
            unit = state["units"][0]
            self.assertIsNone(state["failure"])
            self.assertEqual(runner.script, [])
            self.assertEqual([entry["id"] for entry in unit["debt"]], ["codex-F1"])
            self.assertEqual(st.active_debt(state, unit), [])
            self.assertEqual(st.debt_ids(state), set())
            contested = [
                event for event in state["events"] if event["type"] == "debt_contested"
            ]
            self.assertEqual(
                [(event["debt_id"], event["contested_by"]) for event in contested],
                [("codex-F1", "F2")],
            )
            review_calls = [call for call in runner.calls if call[1] == "review_round"]
            self.assertEqual(len(review_calls), 4)
            self.assertNotIn("CONTRACT CORRECTION", review_calls[-2][2])
            self.assertIn("CONTRACT CORRECTION", review_calls[-1][2])
            self.assertIn("codex-F1", review_calls[-1][2])
            reviews = [
                record for record in unit["rounds"] if record["kind"] == "review_round"
            ]
            self.assertEqual(len(reviews), 3)
            self.assertEqual(reviews[-1]["result"]["findings"], [corrected])
            fixes = [
                record for record in unit["rounds"] if record["kind"] == "fix_findings"
            ]
            self.assertEqual(len(fixes[-1]["queued"]), 1)
            for field in ("id", "summary", "severity", "contests"):
                self.assertEqual(fixes[-1]["queued"][0][field], corrected[field])
            self.assertEqual(fixes[-1]["result"]["findings"][0]["disposition"], "fixed")


if __name__ == "__main__":
    unittest.main()
