"""Periodic suite deferrals stay scoped, evidenced, and separate from a pass."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from orchestrator import contracts, judgment_calls, prompt_contracts, prompt_sets
from orchestrator import prompt_router, prompts


SCOPE = {
    "completed_slice_ids": [1, 2, 3, 4, 5],
    "pending_slice_ids": [6, 7, 8],
    "skeleton_path": "implementation/skeleton.md",
}
COMMANDS = ["check-format", "check-types", "test-all"]


def account(command="check-types", owner=8):
    return {
        "command": command,
        "owner_slice_id": owner,
        "authorization": "Skeleton transition rule and amendment A1 permit this until slice 8.",
        "evidence": "Unchanged legacy adapter causes the listed type failures; slice 8 owns it.",
    }


def reply():
    return {
        "status": "not_verified",
        "kind": "suite_checkpoint",
        "commands": list(COMMANDS),
        "results": [
            {"command": command, "exit_code": code, "evidence": "Actual command output"}
            for command, code in zip(COMMANDS, (0, 2, 0))
        ],
        "authority": {"source": "operator_config", "evidence": []},
        "deferred_failures": [account()],
    }


class PeriodicCheckpointContractTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="periodic-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.home = self.temporary.name

    def prepare(self, scope=SCOPE, **changes):
        options = {
            "job": "suite_checkpoint@workspace",
            "material": "code",
            "values": {
                "kind": "suite_checkpoint",
                "workspace": self.home,
                "checkpoint_reason": "five_slice_checkpoint",
            },
            "amendments": [],
            "configured_suite_commands": list(COMMANDS),
            "periodic_checkpoint": copy.deepcopy(scope),
        }
        options.update(changes)
        return judgment_calls.prepare(self.home, **options)

    def write_set(self, name, documents):
        base = Path(prompt_sets.prompt_set_dir(self.home, name))
        for member, document in documents.items():
            path = base / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding="utf-8")

    def test_complete_authorized_trace_and_multiple_causes_are_admitted(self):
        prepared = self.prepare()
        payload = reply()
        payload["deferred_failures"].append(account(owner=7))
        self.assertEqual(prepared.validate(payload), payload)
        self.assertIn("Account for ALL failure causes and affected tests", prepared.prompt)
        self.assertIn("Being periodic is never an implicit waiver", prepared.prompt)
        self.assertIn("Never defer failures in focused/current-slice checks", prepared.prompt)
        self.assertIn("Do not pull future slice work forward", prepared.prompt)
        self.assertIn("NOT VERIFIED is not a pass", prepared.prompt)
        self.assertIn('"pending_slice_ids": [', prepared.prompt)

    def test_strict_checkpoints_reject_not_verified_despite_periodic_reason(self):
        with self.assertRaises(contracts.ContractError):
            self.prepare(None).validate(reply())

    def test_scope_is_frozen_with_the_worker_charge(self):
        scope = copy.deepcopy(SCOPE)
        prepared = self.prepare(scope=scope)
        scope["pending_slice_ids"][:] = [99]
        prepared.validate(reply())
        invalid = reply()
        invalid["deferred_failures"][0]["owner_slice_id"] = 99
        with self.assertRaises(contracts.ContractError):
            prepared.validate(invalid)

    def test_not_verified_rejects_incomplete_or_unaccounted_execution(self):
        prepared = self.prepare()
        defects = {
            "truncated": lambda p: p["results"].pop(),
            "all_green": lambda p: p["results"][1].update(exit_code=0),
            "no_accounts": lambda p: p.update(deferred_failures=[]),
            "missing_accounts": lambda p: p.pop("deferred_failures"),
            "uncovered_failure": lambda p: p["results"][2].update(exit_code=1),
            "passed_command_account": lambda p: p["deferred_failures"][0].update(command="check-format"),
            "unexecuted_command_account": lambda p: p["deferred_failures"][0].update(command="unknown"),
            "completed_owner": lambda p: p["deferred_failures"][0].update(owner_slice_id=5),
            "unknown_owner": lambda p: p["deferred_failures"][0].update(owner_slice_id=99),
            "boolean_owner": lambda p: p["deferred_failures"][0].update(owner_slice_id=True),
            "empty_authorization": lambda p: p["deferred_failures"][0].update(authorization=" "),
            "empty_evidence": lambda p: p["deferred_failures"][0].update(evidence=""),
            "extra_account_field": lambda p: p["deferred_failures"][0].update(approved=True),
            "wrong_authority": lambda p: p["authority"].update(source="repository"),
            "wrong_plan": lambda p: p["commands"].reverse(),
            "wrong_result_order": lambda p: p["results"].reverse(),
            "failure_account": lambda p: p.update(failure_account={}),
        }
        for name, mutate in defects.items():
            with self.subTest(defect=name):
                payload = reply()
                mutate(payload)
                with self.assertRaises(contracts.ContractError):
                    prepared.validate(payload)

    def test_discovered_suite_still_requires_repository_evidence(self):
        prepared = self.prepare(configured_suite_commands=None)
        payload = reply()
        payload["authority"] = {
            "source": "repository",
            "evidence": [{"path": "README.md", "basis": "Official suite commands"}],
        }
        with self.assertRaises(contracts.ContractError):
            prepared.validate(payload)
        Path(self.home, "README.md").write_text("Complete suite: ...\n")
        prepared.validate(payload)

    def test_later_real_failure_keeps_failed_semantics(self):
        payload = reply()
        payload["status"] = "failed"
        payload.pop("deferred_failures")
        payload["results"][2]["exit_code"] = 1
        payload["failure_account"] = {
            "command": "test-all", "exit_code": 1,
            "diagnostics": "New current-slice regression", "affected_tests": ["test_current"],
        }
        self.prepare().validate(payload)
        with self.assertRaises(contracts.ContractError):
            self.prepare(None).validate(payload)
        payload["failure_account"]["command"] = "check-types"
        with self.assertRaises(contracts.ContractError):
            self.prepare().validate(payload)

    def test_block_after_allowed_failure_is_blocked_not_continuable(self):
        payload = reply()
        payload.update(status="blocked", blocked_reason="Cannot execute test-all")
        payload.pop("authority")
        payload.pop("deferred_failures")
        payload["results"].pop()
        self.prepare().validate(payload)
        with self.assertRaises(contracts.ContractError):
            self.prepare(None).validate(payload)
        payload["results"].append(reply()["results"][-1])
        with self.assertRaises(contracts.ContractError):
            self.prepare().validate(payload)

    def test_passed_cannot_carry_deferred_failures(self):
        payload = reply()
        payload["status"] = "passed"
        payload["results"][1]["exit_code"] = 0
        with self.assertRaises(contracts.ContractError):
            self.prepare().validate(payload)
        payload.pop("deferred_failures")
        self.prepare().validate(payload)

    def test_malformed_scope_cannot_enable_periodic_contract(self):
        invalid_scopes = [
            {}, {**SCOPE, "pending_slice_ids": []},
            {**SCOPE, "pending_slice_ids": [True]},
            {**SCOPE, "pending_slice_ids": [5]},
            {**SCOPE, "pending_slice_ids": [8, 8]},
            {**SCOPE, "skeleton_path": "../skeleton.md"},
        ]
        for scope in invalid_scopes:
            with self.subTest(scope=scope), self.assertRaises(prompt_router.PromptRouterError):
                self.prepare(scope)
        values = {"workspace": self.home, "checkpoint_reason": "periodic", "periodic_checkpoint": SCOPE}
        with self.assertRaises(prompt_router.PromptRouterError):
            self.prepare(values=values)

    def test_persisted_old_prompts_fall_back_only_for_periodic_scope(self):
        self.assertTrue(prompt_sets.ensure_default(self.home))
        old = copy.deepcopy(prompt_sets.default_seed().documents)
        instruction = old["milestone/suite_checkpoint.json"]["instructions"]
        instruction["parts"] = [
            part for part in instruction["parts"]
            if not any(v["name"] == "periodic_checkpoint" for v in part.get("variables", []))
        ]
        self.write_set("old-checkpoint", old)
        strict = self.prepare(None, prompt_set="old-checkpoint")
        self.assertIsNone(strict.prompt_set_fallback)
        with self.assertRaises(contracts.ContractError):
            strict.validate(reply())
        prepared = self.prepare(prompt_set="old-checkpoint")
        self.assertEqual(prepared.prompt_set_fallback, prompt_sets.PROMPT_SET_FALLBACK_DEFAULT)
        prepared.validate(reply())
        self.write_set("default", old)
        prepared = self.prepare()
        self.assertEqual(prepared.prompt_set_fallback, prompt_sets.PROMPT_SET_FALLBACK_SEED)
        prepared.validate(reply())

    def test_periodic_repair_preserves_future_ownership_and_rechecks_after_review(self):
        prepared = judgment_calls.prepare(
            self.home, job="fix_findings@slice_impl", material="code",
            values={"workspace": self.home, "task_subject": "slice 5",
                    "goal_path": "goal.md", "skeleton_path": SCOPE["skeleton_path"],
                    "editable_path": "slice-5.md"},
            amendments=[], queued_findings=[],
            suite_repair={"commands": COMMANDS, "cadence": "five_slice_checkpoint",
                          "periodic_checkpoint": SCOPE},
        )
        self.assertIn("PERIODIC CHECKPOINT REPAIR", prepared.prompt)
        self.assertIn("Do not pull future work forward", prepared.prompt)
        self.assertIn("Do not run the complete suite in this fix call", prepared.prompt)
        self.assertIn("does\n  not certify a passing suite", prepared.prompt)
        self.assertIn("executes a fresh scheduled checkpoint", prepared.prompt)
        self.assertNotIn("certifies that the complete command", prepared.prompt)
        strict = prompts.suite_repair_block(COMMANDS, "milestone_final")
        self.assertIn("certifies that the complete command", strict)
        self.assertNotIn("PERIODIC CHECKPOINT REPAIR", strict)

    def test_deferral_field_is_reserved_for_policy_extensions(self):
        self.assertIn("deferred_failures", contracts.reserved_output_keys("suite_checkpoint"))
        self.assertIn("deferred_failures", prompt_contracts.reserved_output_fields(self.prepare().bound))


if __name__ == "__main__":
    unittest.main()
