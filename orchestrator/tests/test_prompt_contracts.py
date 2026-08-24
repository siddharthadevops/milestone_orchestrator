"""Focused proof for registered prompt reply contracts and QUESTIONS."""
import copy
from pathlib import Path
import tempfile
import unittest
from orchestrator import contracts, prompt_contracts, prompt_router, prompt_sets
def section(section_id):
    return {"id": section_id, "text": ["Contract %s" % section_id],
            "variables": []}
def prompt(kind, section_ids, question_ids=()):
    return {
        "kind": kind,
        "questions": {"items": [
            {"id": question_id, "text": "Question"}
            for question_id in question_ids
        ]},
        "output_contract": [section(section_id) for section_id in section_ids],
    }
def report_finding():
    return {
        "id": "F1", "severity": "P2", "summary": "Concrete problem",
        "validity": {
            "permitted_baseline": "Expected result",
            "actual_outcome": "Wrong result",
            "incremental_harm": "A user gets the wrong result",
            "exceeds_baseline": True,
        },
        "plain": "A user gets the wrong result.",
        "example": "One request returns the wrong value.", "contests": None,
    }


def fix_finding(disposition="rejected", resolution="Consulted and rejected"):
    return {
        "id": "F1",
        "severity": "P2",
        "summary": "Concrete problem",
        "validity": {
            "affected_party": "The operator",
            "observable_damage": "The result is misleading",
            "violated_guarantee": "The declared result contract",
            "permitted_baseline": "Only validated results are accepted",
            "incremental_harm": "An invalid result is accepted",
            "exceeds_baseline": disposition in ("fixed", "blocked"),
        },
        "disposition": disposition,
        "consultation": (
            {"resolution": resolution} if disposition == "rejected" else None
        ),
        "prevention": None,
        "adjudication_ref": None,
    }


class PromptContractsTest(unittest.TestCase):
    def test_shipped_contract_section_registry_is_complete(self):
        documents = prompt_sets.default_seed().documents
        shipped = set(documents["shared/shared.json"]["contract_sections"])
        for member, document in documents.items():
            if member == "shared/shared.json":
                continue
            for item in document["output_contract"]["sections"]:
                shipped.add(item.get("ref", item.get("id")))
        self.assertNotIn(None, shipped)
        self.assertEqual(shipped, set(prompt_contracts.REGISTERED_SECTIONS))
        self.assertTrue(all(
            callable(check)
            for check in prompt_contracts.REGISTERED_SECTIONS.values()
        ))
        rethink = {"status": "need_rethink", "kind": "implement",
                   "finding": {"fact": "conflict"}, "target_path": "note.md"}
        review_rethink = dict(rethink, kind="review_round",
                              finding=report_finding())
        cases = [
            ("envelope_verbose", "implement", {}, []),
            ("envelope_compact", "review_round", {}, []),
            ("common_fields", "implement",
             {"status": "blocked", "kind": "implement",
              "blocked_reason": "Cannot continue"},
             {"status": "blocked", "kind": "implement"}),
            ("draft_skeleton_result", "draft_skeleton",
             {"status": "ok", "kind": "draft_skeleton", "artifact": "a.md"},
             {"status": "ok", "kind": "draft_skeleton", "artifact": ""}),
            ("draft_slice_note_result", "draft_slice_note",
             {"status": "ok", "kind": "draft_slice_note", "artifact": "a.md"},
             {"status": "ok", "kind": "draft_slice_note"}),
            ("implement_result", "implement",
             {"status": "ok", "kind": "implement", "files_changed": []},
             {"status": "ok", "kind": "implement"}),
            ("need_rethink_author", "implement", rethink,
             dict(rethink, target_path="../note.md")),
            ("review_contract", "review_round",
             {"status": "ok", "kind": "review_round", "findings": []},
             {"status": "ok", "kind": "review_round"}),
            ("review_blocked", "review_round",
             {"status": "blocked", "kind": "review_round",
              "blocked_reason": "Cannot judge"},
             {"status": "blocked", "kind": "review_round"}),
            ("review_need_rethink", "review_round", review_rethink,
             dict(review_rethink, finding={})),
            ("fix_results", "fix_findings",
             {"status": "ok", "kind": "fix_findings", "findings": [],
              "files_changed": []},
             {"status": "ok", "kind": "fix_findings", "findings": []}),
            ("fix_blocked", "fix_findings",
             {"status": "blocked", "kind": "fix_findings",
              "blocked_reason": "Cannot fix"},
             {"status": "blocked", "kind": "fix_findings"}),
            ("fix_retry", "fix_findings",
             {"status": "retry", "kind": "fix_findings",
              "retry_reason": "consultation_unavailable"},
             {"status": "retry", "kind": "fix_findings",
              "retry_reason": "later"}),
            ("fix_need_rethink", "fix_findings",
             dict(review_rethink, kind="fix_findings"),
             dict(review_rethink, kind="fix_findings", finding={})),
            ("reclassify_result", "reclassify",
             {"status": "ok", "kind": "reclassify", "drift_risk": "low",
              "drift_damage": "medium", "reason": "Bounded change"},
             {"status": "ok", "kind": "reclassify", "drift_risk": "none",
              "drift_damage": "medium", "reason": "Bounded change"}),
            ("discussion_turn_envelope", "discussion_turn",
             {"kind": "discussion_turn", "markdown": "Position", "ready": True},
             {"kind": "discussion_turn", "markdown": ""}),
            ("questioner_turn_envelope", "questioner_turn",
             {"kind": "questioner_turn", "markdown": "Question"},
             {"kind": "questioner_turn", "markdown": "Question", "ready": True}),
            ("merge_repair_result", "merge_repair",
             {"status": "ok", "kind": "merge_repair", "files_changed": []},
             {"status": "ok", "kind": "merge_repair"}),
            ("questions_output", "implement", {"questions": [
                {"id": "q1", "answer": "Done"}]}, {"questions": []}),
        ]
        with tempfile.TemporaryDirectory(prefix="orch-contract-") as root:
            Path(root, "suite.txt").write_text("suite", encoding="utf-8")
            authority = {"source": "repository", "evidence": [
                {"path": "suite.txt", "basis": "Declares the suite"}]}
            cases.append((
                "suite_checkpoint_result", "suite_checkpoint",
                {"status": "no_suite", "kind": "suite_checkpoint",
                 "commands": [], "results": [], "authority": authority},
                {"status": "no_suite", "kind": "suite_checkpoint",
                 "commands": [], "results": [],
                 "authority": {"source": "repository", "evidence": []}},
            ))
            for section_id, kind, valid, invalid in cases:
                with self.subTest(section_id=section_id):
                    question_ids = ("q1",) if section_id == "questions_output" else ()
                    bound = prompt_contracts.bind(
                        prompt(kind, (section_id,), question_ids)
                    )
                    queued_findings = (
                        [copy.deepcopy(valid["finding"])]
                        if section_id == "fix_need_rethink" else []
                    )
                    options = {
                        "workspace": root,
                        "queued_findings": queued_findings,
                    }
                    self.assertEqual(
                        prompt_contracts.validate(bound, copy.deepcopy(valid),
                                                  **options), valid
                    )
                    with self.assertRaises(contracts.ContractError):
                        prompt_contracts.validate(bound, copy.deepcopy(invalid),
                                                  **options)
    def test_registered_sections_compose_and_append_by_origin(self):
        unknown = section("operator_note")
        base = prompt("implement", ("common_fields",))
        base["output_contract"].append(unknown)
        bound = prompt_contracts.bind(base)
        self.assertEqual(bound.registered_section_ids, ("common_fields",))
        self.assertEqual(bound.prompt["output_contract"][-1], unknown)
        prompt_contracts.validate(
            bound, {"status": "ok", "kind": "implement"}
        )
        prompt_contracts.validate(
            bound,
            {
                "status": "need_rethink",
                "kind": "implement",
                "notes": "Optional context",
            },
        )
        added = section("implement_result")
        combined = prompt_contracts.bind(base, (added,))
        self.assertEqual(
            combined.registered_section_ids,
            ("common_fields", "implement_result"),
        )
        self.assertEqual(combined.prompt["output_contract"][-1], added)
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(
                combined, {"status": "ok", "kind": "implement"}
            )
        prompt_contracts.validate(
            combined,
            {"status": "ok", "kind": "implement", "files_changed": []},
        )
        for additions in ((section("unknown"),), (added, added),
                          (section("common_fields"),)):
            with self.subTest(additions=additions):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.bind(base, additions)

    def test_field_filtering_requires_a_registered_schema_section(self):
        cases = (
            (
                prompt("implement", ("envelope_verbose", "operator_note")),
                {
                    "status": "ok",
                    "kind": "implement",
                    "files_changed": [],
                },
            ),
            (
                prompt(
                    "suite_checkpoint", ("questions_output", "operator_note")
                ),
                {
                    "status": "no_suite",
                    "kind": "suite_checkpoint",
                    "commands": [],
                    "results": [],
                    "authority": {"source": "repository", "evidence": []},
                },
            ),
            (
                prompt(
                    "discussion_turn",
                    ("questions_output", "operator_note"),
                    ("q1",),
                ),
                {
                    "kind": "discussion_turn",
                    "markdown": "Position",
                    "questions": [{"id": "q1", "answer": "Checked"}],
                },
            ),
        )
        for served, reply in cases:
            with self.subTest(kind=served["kind"]):
                prompt_contracts.validate(
                    prompt_contracts.bind(served), copy.deepcopy(reply)
                )

    def test_appended_questions_compose_with_zero_question_technical_result(self):
        bound = prompt_contracts.bind(
            prompt("reclassify", ("reclassify_result",)),
            (section("questions_output"),),
        )
        reply = {
            "status": "ok",
            "kind": "reclassify",
            "drift_risk": "low",
            "drift_damage": "medium",
            "reason": "The change is bounded",
            "questions": [],
        }
        self.assertEqual(prompt_contracts.validate(bound, reply), reply)
        without_questions = dict(reply)
        without_questions.pop("questions")
        prompt_contracts.validate(bound, without_questions)
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(
                bound,
                dict(
                    reply,
                    questions=[{"id": "invented", "answer": "Not mounted"}],
                ),
            )

    def test_fixer_rejects_retired_suite_repair_fields(self):
        bound = prompt_contracts.bind(
            prompt("fix_findings", ("fix_results",))
        )
        reply = {
            "status": "ok",
            "kind": "fix_findings",
            "findings": [],
            "files_changed": [],
            "tests_modified": False,
            "tests_changed": [],
        }
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(bound, reply, queued_findings=[])

    def test_mounted_questions_are_present_in_every_reply(self):
        seed = prompt_sets.default_seed()
        values = prompt_router._validation_values(seed)
        values.pop("task_executor_catalogue", None)
        charges = (
            {"job": "implement@slice_impl", "executor": "agent_call"},
            {"job": "implement@slice_impl", "executor": "brainstorming",
             "role": "initial_position", "lead": True},
        )
        bounds = []
        for charge in charges:
            assembled = prompt_router.assemble(
                seed, material="code", values=values, **charge
            )
            assembled["output_contract"] = [
                item for item in assembled["output_contract"]
                if item["id"] == "questions_output"
            ]
            bounds.append((
                prompt_contracts.bind(assembled),
                charge["executor"] == "brainstorming",
            ))
        for bound, is_session in bounds:
            answers = [{"id": question_id, "answer": "Done"}
                       for question_id in bound.question_ids]
            if is_session:
                prompt_contracts.validate(bound, {"questions": answers})
            else:
                for status in ("ok", "blocked", "retry", "need_rethink"):
                    prompt_contracts.validate(bound, {"status": status,
                                                       "questions": answers})
            long_answers = copy.deepcopy(answers)
            long_answers[0]["answer"] = "x" * 301
            prompt_contracts.validate(bound, {"questions": long_answers})
            bad = [
                {}, {"questions": answers[:-1]},
                {"questions": answers + [copy.deepcopy(answers[0])]},
                {"questions": [dict(answers[0], id="wrong")] + answers[1:]},
                {"questions": [dict(answers[0], answer="")] + answers[1:]},
                {"questions": [dict(answers[0], answer=1)] + answers[1:]},
            ]
            for reply in bad:
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(bound, reply)
        prompt_contracts.validate(
            prompt_contracts.bind(prompt("suite_checkpoint", ("questions_output",))),
            {},
        )

    def test_reclassify_mounted_questions_are_mandatory(self):
        seed = prompt_sets.default_seed()
        values = prompt_router._validation_values(seed)
        values.pop("task_executor_catalogue", None)
        assembled = prompt_router.assemble(
            seed,
            job="reclassify@doc",
            executor="agent_call",
            material="document",
            values=values,
        )
        bound = prompt_contracts.bind(assembled)
        self.assertNotIn("questions_output", bound.registered_section_ids)
        self.assertTrue(bound.question_ids)
        reply = {
            "status": "ok",
            "kind": "reclassify",
            "drift_risk": "low",
            "drift_damage": "medium",
            "reason": "The change is bounded",
        }
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(bound, reply)
        reply["questions"] = [
            {"id": question_id, "answer": "Checked"}
            for question_id in bound.question_ids
        ]
        prompt_contracts.validate(bound, reply)

    def test_suite_checkpoint_rejects_noops_and_contradictory_traces(self):
        bound = prompt_contracts.bind(
            prompt("suite_checkpoint", ("suite_checkpoint_result",))
        )
        passed_noop = {
            "status": "passed",
            "kind": "suite_checkpoint",
            "commands": ["true"],
            "results": [
                {"command": "true", "exit_code": 0, "evidence": "zero"}
            ],
            "authority": {"source": "operator_config", "evidence": []},
        }
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(
                bound, passed_noop, configured_suite_commands=["true"]
            )
        prompt_contracts.validate(
            bound,
            {
                "status": "blocked",
                "kind": "suite_checkpoint",
                "commands": ["true"],
                "results": [],
                "blocked_reason": "The configured command is a no-op",
            },
            configured_suite_commands=["true"],
        )

        commands = ["suite-a", "suite-b"]
        blocked_cases = (
            [
                {"command": "suite-a", "exit_code": 1, "evidence": "failed"},
                {"command": "suite-b", "exit_code": 0, "evidence": "ran"},
            ],
            [
                {"command": command, "exit_code": 0, "evidence": "passed"}
                for command in commands
            ],
        )
        for results in blocked_cases:
            with self.subTest(results=results):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(
                        bound,
                        {
                            "status": "blocked",
                            "kind": "suite_checkpoint",
                            "commands": commands,
                            "results": results,
                            "blocked_reason": "Stopped",
                        },
                        configured_suite_commands=commands,
                    )
        prompt_contracts.validate(
            bound,
            {
                "status": "blocked",
                "kind": "suite_checkpoint",
                "commands": commands,
                "results": [
                    {
                        "command": "suite-a",
                        "exit_code": 0,
                        "evidence": "passed",
                    }
                ],
                "blocked_reason": "The second command cannot start",
            },
            configured_suite_commands=commands,
        )

    def test_rejected_fix_requires_nonempty_consultation_resolution(self):
        bound = prompt_contracts.bind(
            prompt("fix_findings", ("fix_results",))
        )
        reply = {
            "status": "ok",
            "kind": "fix_findings",
            "findings": [fix_finding(resolution="")],
            "files_changed": [],
        }
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(bound, reply)
        reply["findings"][0]["consultation"]["resolution"] = "Agreed invalid"
        prompt_contracts.validate(bound, reply)

    def test_contested_review_requires_meaningful_new_evidence(self):
        bound = prompt_contracts.bind(
            prompt("review_round", ("review_contract",))
        )
        finding = report_finding()
        finding["contests"] = {
            "rejection_id": "prior-rejection",
            "new_evidence": "   ",
        }
        reply = {
            "status": "ok",
            "kind": "review_round",
            "findings": [finding],
        }
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(bound, reply)
        finding["contests"]["new_evidence"] = "The behavior changed"
        prompt_contracts.validate(bound, reply)

    def test_fixer_severity_must_echo_the_queued_finding(self):
        bound = prompt_contracts.bind(
            prompt("fix_findings", ("fix_results",))
        )
        result = fix_finding()
        result["severity"] = "P3"
        reply = {
            "status": "ok",
            "kind": "fix_findings",
            "findings": [result],
            "files_changed": [],
        }
        queued = [{"id": "F1", "severity": "P1"}]
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(bound, reply, queued_findings=queued)
        result["severity"] = "P1"
        prompt_contracts.validate(bound, reply, queued_findings=queued)

    def test_fixer_rethink_must_copy_one_complete_queued_finding(self):
        bound = prompt_contracts.bind(
            prompt("fix_findings", ("fix_need_rethink",))
        )
        queued = [
            report_finding(),
            dict(report_finding(), id="F2", summary="Second problem"),
        ]
        reply = {
            "status": "need_rethink",
            "kind": "fix_findings",
            "finding": copy.deepcopy(queued[0]),
            "target_path": "note.md",
        }
        prompt_contracts.validate(bound, reply, queued_findings=queued)

        mutations = {
            "id": lambda finding: finding.update(id="invented"),
            "severity": lambda finding: finding.update(severity="P1"),
            "summary": lambda finding: finding.update(summary="Rewritten"),
            "body": lambda finding: finding["validity"].update(
                actual_outcome="Different outcome"
            ),
            "missing field": lambda finding: finding.pop("example"),
            "extra field": lambda finding: finding.update(detail="invented"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(queued[0])
                mutate(changed)
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(
                        bound,
                        dict(reply, finding=changed),
                        queued_findings=queued,
                    )

    def test_prevention_requires_declared_changed_path_and_meaningful_note(self):
        bound = prompt_contracts.bind(
            prompt("fix_findings", ("fix_results",))
        )
        result = fix_finding()
        reply = {
            "status": "ok",
            "kind": "fix_findings",
            "findings": [result],
            "files_changed": ["docs/decision.md"],
        }
        invalid = (
            {"documented_in": "/outside.md", "note": "Clarified"},
            {"documented_in": "docs/unrelated.md", "note": "Clarified"},
            {"documented_in": "docs/decision.md", "note": "   "},
        )
        for prevention in invalid:
            with self.subTest(prevention=prevention):
                result["prevention"] = prevention
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(bound, reply)
        result["prevention"] = {
            "documented_in": "docs/decision.md",
            "note": "Clarified the reviewed behavior",
        }
        prompt_contracts.validate(bound, reply)

    def test_finding_text_and_optional_notes_have_declared_shapes(self):
        review_bound = prompt_contracts.bind(
            prompt("review_round", ("review_contract",))
        )
        for field in ("id", "summary"):
            finding = report_finding()
            finding[field] = "   "
            with self.subTest(contract="review", field=field):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(
                        review_bound,
                        {
                            "status": "ok",
                            "kind": "review_round",
                            "findings": [finding],
                        },
                    )
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(
                review_bound,
                {
                    "status": "ok",
                    "kind": "review_round",
                    "findings": [],
                    "notes": 7,
                },
            )

        fix_bound = prompt_contracts.bind(
            prompt("fix_findings", ("fix_results",))
        )
        for field in ("id", "summary"):
            finding = fix_finding()
            finding[field] = "   "
            with self.subTest(contract="fix", field=field):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(
                        fix_bound,
                        {
                            "status": "ok",
                            "kind": "fix_findings",
                            "findings": [finding],
                            "files_changed": [],
                        },
                    )

        retry_bound = prompt_contracts.bind(
            prompt("fix_findings", ("fix_retry",))
        )
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(
                retry_bound,
                {
                    "status": "retry",
                    "kind": "fix_findings",
                    "retry_reason": "consultation_unavailable",
                    "notes": 7,
                },
            )

    def test_result_paths_are_normalized_and_workspace_relative(self):
        cases = (
            (
                "draft_skeleton",
                ("draft_skeleton_result",),
                {"status": "ok", "kind": "draft_skeleton", "artifact": "/a.md"},
            ),
            (
                "implement",
                ("implement_result",),
                {
                    "status": "ok",
                    "kind": "implement",
                    "files_changed": ["../outside.py"],
                },
            ),
            (
                "fix_findings",
                ("fix_results",),
                {
                    "status": "ok",
                    "kind": "fix_findings",
                    "findings": [],
                    "files_changed": ["/outside.py"],
                },
            ),
            (
                "merge_repair",
                ("merge_repair_result",),
                {
                    "status": "ok",
                    "kind": "merge_repair",
                    "files_changed": ["a/../b.py"],
                },
            ),
        )
        for kind, sections, reply in cases:
            with self.subTest(kind=kind):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(
                        prompt_contracts.bind(prompt(kind, sections)), reply
                    )

    def test_forbidden_and_status_incompatible_fields_do_not_survive(self):
        implement = prompt_contracts.bind(
            prompt(
                "implement",
                (
                    "common_fields",
                    "need_rethink_author",
                    "implement_result",
                ),
            )
        )
        invalid_implement = (
            {
                "status": "ok",
                "kind": "implement",
                "files_changed": [],
                "slices": [{"id": 1}],
            },
            {
                "status": "ok",
                "kind": "implement",
                "files_changed": [],
                "suite_command": "python3 -m unittest",
            },
            {
                "status": "blocked",
                "kind": "implement",
                "blocked_reason": "Stopped",
                "files_changed": [],
            },
            {
                "status": "need_rethink",
                "kind": "implement",
                "finding": {"fact": "Conflict"},
                "target_path": "note.md",
                "notes": "Status-incompatible claim",
            },
        )
        for reply in invalid_implement:
            with self.subTest(reply=reply):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(implement, reply)

        fix = prompt_contracts.bind(prompt("fix_findings", ("fix_results",)))
        for field in (
            "suite_command", "design_correction", "brainstorming_application",
        ):
            with self.subTest(field=field):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(
                        fix,
                        {
                            "status": "ok",
                            "kind": "fix_findings",
                            "findings": [],
                            "files_changed": [],
                            field: {},
                        },
                    )

        delta_review = prompt_contracts.bind(
            prompt("delta_review", ("review_contract",))
        )
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(
                delta_review,
                {
                    "status": "ok",
                    "kind": "delta_review",
                    "findings": [],
                    "design_correction_verdict": {},
                },
            )

        discussion = prompt_contracts.bind(
            prompt("discussion_turn", ("discussion_turn_envelope",))
        )
        for field in ("vote", "revision", "accepted_target_revision"):
            with self.subTest(field=field):
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(
                        discussion,
                        {
                            "kind": "discussion_turn",
                            "markdown": "Position",
                            field: "unauthorized",
                        },
                    )
