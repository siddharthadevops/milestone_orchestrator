"""Focused proof for registered prompt reply contracts and QUESTIONS."""
import copy
from pathlib import Path
import tempfile
import unittest
from orchestrator import contracts, prompt_contracts, prompt_router, prompt_sets


def validation_values(prompt_set):
    names = set()
    fixed = {"kind", "role", "workarea_boundary"}

    def walk(value):
        if isinstance(value, dict):
            for item in value.get("variables", ()):
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    names.add(item["name"])
            defaults = value.get("defaults")
            if isinstance(defaults, dict):
                fixed.update(defaults)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(prompt_set.documents)
    return {name: "validation value" for name in names - fixed}


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


def fix_finding(disposition="rejected"):
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
        "prevention": None,
        "adjudication_ref": None,
    }


def closed_object_defects(record):
    defects = {"not_object": [], "extra_field": dict(record, unexpected="extra")}
    for key, value in record.items():
        defects["missing_" + key] = {k: v for k, v in record.items() if k != key}
        defects["wrong_type_" + key] = dict(record, **{key: None})
        if isinstance(value, str):
            defects["blank_" + key] = dict(record, **{key: " \n"})
    return defects


class PromptContractsTest(unittest.TestCase):
    def assert_creativity_replies(self, kind, accepted, rejected, **context):
        values = validation_values(prompt_sets.default_seed())
        values.pop("task_executor_catalogue")
        with tempfile.TemporaryDirectory() as home:
            prompt_sets.ensure_default(home)
            for material in ("default", "literature", "business"):
                served = prompt_router.resolve(
                    home, job=kind + "@creativity", executor="agent_call",
                    material=material, values=values,
                ).prompt
                prompt_router.render(served, values)
                bound = prompt_contracts.bind(served)
                self.assertEqual(bound.registered_section_ids, (kind + "_result",))
                for case, reply in accepted.items():
                    with self.subTest(material=material, accepted=case):
                        self.assertIs(prompt_contracts.validate(bound, reply, **context), reply)
                for case, reply in rejected.items():
                    with self.subTest(material=material, rejected=case):
                        with self.assertRaises(contracts.ContractError):
                            prompt_contracts.validate(bound, reply, **context)

    def test_evaluate_candidates_contextual_contract(self):
        valid = {
            "candidate_id": "c1", "proposal": "Share existing space.",
            "constraint_valid": True, "constraint_violations": [],
            "reason": "Uses available capacity without spending.", "assumptions": [], "score": 0,
        }
        invalid = {
            "candidate_id": "c2", "proposal": "Rent a larger room.",
            "constraint_valid": False, "constraint_violations": ["budget", "capacity"],
            "reason": "Useful but exceeds the budget and available capacity.",
            "assumptions": ["A larger room is available"], "score": 1,
        }
        reply = {"evaluations": [invalid, valid]}
        rejected = closed_object_defects(reply)
        rejected.update({
            "empty_coverage": {"evaluations": []},
            "missing_candidate": {"evaluations": [valid]},
            "duplicate_candidate": {"evaluations": [invalid, valid, valid]},
            "extra_candidate": {"evaluations": [invalid, valid, dict(valid, candidate_id="c3")]},
        })
        records = closed_object_defects(valid)
        records["invalid_without_violations"] = dict(valid, constraint_valid=False)
        records["valid_with_violations"] = dict(valid, constraint_violations=["budget"])
        for label, violations in (
            ("unknown", ["unknown"]), ("duplicate", ["budget", "budget"]),
            ("blank", [" "]), ("non_string", [42]), ("not_list", "budget"),
        ):
            records["violations_" + label] = dict(
                valid, constraint_valid=False, constraint_violations=violations,
            )
        for value in (0, 1, "false"):
            records["validity_" + repr(value)] = dict(valid, constraint_valid=value)
        for value in ([" "], [42], "assumed access"):
            records["assumptions_" + repr(value)] = dict(valid, assumptions=value)
        for score in (True, False, float("nan"), float("inf"), -float("inf"), -0.01, 1.01, "0.5"):
            records["score_" + repr(score)] = dict(valid, score=score)
        for case, record in records.items():
            rejected["record_" + case] = {"evaluations": [invalid, record]}
        self.assert_creativity_replies("evaluate_candidates", {
            "reordered_with_high_scoring_invalid": reply,
            "fractional_score": {"evaluations": [dict(valid, score=0.5), invalid]},
        }, rejected, candidate_ids=["c1", "c2"], constraint_ids=["budget", "capacity"])
        self.assert_creativity_replies("evaluate_candidates", {
            "no_constraints": {"evaluations": [valid]},
        }, {}, candidate_ids=["c1"], constraint_ids=[])

    def test_expand_genes_contextual_contract(self):
        dimensions = [
            {"id": "approach", "meaning": "How to proceed",
             "variants": [{"id": "v1", "text": "Reuse space"}]},
            {"id": "recipient", "meaning": "Who benefits",
             "variants": [{"id": "v2", "text": "Current participants"}]},
        ]
        # IDs are local to a dimension; identical text is not a structural defect.
        variant = {"id": "v2", "text": "Reuse space", "reason": "Another arrangement"}
        addition = {"dimension_id": "approach", "variants": [
            variant, {"id": "v3", "text": "Share time", "reason": "Uses spare capacity"},
        ]}
        other = {"dimension_id": "recipient", "variants": [
            {"id": "v3", "text": "Neighbors", "reason": "Extends access"},
        ]}
        reply = {"additions": [addition, other]}
        rejected = closed_object_defects(reply)
        rejected["duplicate_dimension"] = {"additions": [addition, addition]}
        groups = closed_object_defects(addition)
        groups.update({
            "unknown_dimension": dict(addition, dimension_id="unknown"),
            "empty_variants": dict(addition, variants=[]),
            "duplicate_variant": dict(addition, variants=[variant, variant]),
            "reused_variant": dict(addition, variants=[dict(variant, id="v1")]),
        })
        for case, group in groups.items():
            rejected["addition_" + case] = {"additions": [group]}
        for case, record in closed_object_defects(variant).items():
            rejected["variant_" + case] = {"additions": [dict(addition, variants=[record])]}
        self.assert_creativity_replies("expand_genes", {
            "exhausted": {"additions": []},
            "subset_of_dimensions": {"additions": [addition]},
            "ids_scoped_to_dimensions": reply,
        }, rejected, dimensions=dimensions)

    def test_create_genes_contextual_contract(self):
        minimal = {"search_material": {
            "objective": "Find a useful next step.", "context_summary": "Limited resources.",
            "facts": [], "constraints": [], "assumptions": [], "unknowns": [],
            "dimensions": [{"id": "approach", "meaning": "How to proceed",
                            "variants": [{"id": "v1", "text": "Reuse what exists"}]}],
            "composition_guidance": "Combine the chosen parts faithfully.",
            "criteria": [{"id": "useful", "text": "Serves the objective"}],
        }}
        populated = copy.deepcopy(minimal)
        material = populated["search_material"]
        material.update(facts=["One room"], assumptions=["Access is available"],
                        unknowns=["Interest"], constraints=[{"id": "budget", "text": "No spend"}])
        material["dimensions"].append({
            "id": "recipient", "meaning": "Who benefits",
            "variants": [{"id": "v1", "text": "Current participants"}],
        })

        def replaced(path, value):
            reply = copy.deepcopy(populated)
            if not path:
                return value
            target = reply
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return reply

        objects = [
            (), ("search_material",), ("search_material", "constraints", 0),
            ("search_material", "criteria", 0), ("search_material", "dimensions", 0),
            ("search_material", "dimensions", 0, "variants", 0),
        ]
        invalid = []
        for path in objects:
            record = populated
            for key in path:
                record = record[key]
            for defect in closed_object_defects(record).values():
                invalid.append(replaced(path, defect))
        invalid.append(replaced(("search_material", "objective"), "A different objective"))
        for key in ("facts", "assumptions", "unknowns"):
            invalid.append(replaced(("search_material", key), [""]))
            invalid.append(replaced(("search_material", key), [42]))
        for path in (
            ("search_material", "constraints"), ("search_material", "criteria"),
            ("search_material", "dimensions"),
            ("search_material", "dimensions", 0, "variants"),
        ):
            records = populated
            for key in path:
                records = records[key]
            invalid.append(replaced(path, [records[0], records[0]]))
            if path[-1] != "constraints":
                invalid.append(replaced(path, []))
        objective = minimal["search_material"]["objective"]
        values = {"workspace": "/workspace", "objective": objective,
                  "context": "", "references": "[]"}
        with tempfile.TemporaryDirectory() as home:
            prompt_sets.ensure_default(home)
            for material_name in ("default", "literature", "business"):
                served = prompt_router.resolve(
                    home, job="create_genes@creativity", executor="agent_call",
                    material=material_name, values=values,
                ).prompt
                bound = prompt_contracts.bind(served)
                self.assertEqual(bound.registered_section_ids, ("create_genes_result",))
                for reply in (minimal, populated):
                    self.assertIs(prompt_contracts.validate(
                        bound, reply, expected_objective=objective,
                    ), reply)
                for index, reply in enumerate(invalid):
                    with self.subTest(material=material_name, invalid=index):
                        with self.assertRaises(contracts.ContractError):
                            prompt_contracts.validate(bound, reply, expected_objective=objective)
                served["kind"] = "evaluate_candidates"
                with self.assertRaisesRegex(contracts.ContractError, "prompt kind"):
                    prompt_contracts.validate(
                        prompt_contracts.bind(served), minimal, expected_objective=objective,
                    )
                served["output_contract"][0]["id"] = "operator_data_only"
                self.assertEqual(prompt_contracts.validate(
                    prompt_contracts.bind(served), {"operator": "reply"},
                ), {"operator": "reply"})

    def test_shipped_contract_section_registry_is_complete(self):
        documents = prompt_sets.default_seed().documents
        shipped = set(documents["shared/shared.json"]["contract_sections"])
        for member, document in documents.items():
            if member == "shared/shared.json":
                continue
            for item in document["output_contract"]["sections"]:
                shipped.add(item.get("ref", item.get("id")))
        self.assertNotIn(None, shipped)
        self.assertNotIn(prompt_contracts.NEED_RETHINK_SECTION_ID, shipped)
        self.assertEqual(
            shipped | {
                prompt_contracts.NEED_RETHINK_SECTION_ID,
                "questioner_readiness",
            },
            set(prompt_contracts.REGISTERED_SECTIONS),
        )
        self.assertTrue(all(
            callable(check)
            for check in prompt_contracts.REGISTERED_SECTIONS.values()
        ))

    def test_questioner_readiness_cannot_mount_on_another_kind(self):
        bound = prompt_contracts.bind(
            prompt("discussion_turn", ("discussion_turn_envelope",)),
            consumer_sections=(section("questioner_readiness"),),
        )
        with self.assertRaisesRegex(contracts.ContractError, "prompt kind"):
            prompt_contracts.validate(bound, {
                "kind": "discussion_turn",
                "markdown": "Position.",
                "ready": True,
            })

    def test_registered_contract_examples(self):
        rethink = {
            "status": "need_rethink",
            "problem": "The governing design requires incompatible outcomes.",
        }
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
            ("need_rethink", "implement", rethink,
             dict(rethink, problem="  ")),
            ("review_contract", "review_round",
             {"status": "ok", "kind": "review_round", "findings": []},
             {"status": "ok", "kind": "review_round"}),
            ("review_blocked", "review_round",
             {"status": "blocked", "kind": "review_round",
              "blocked_reason": "Cannot judge"},
             {"status": "blocked", "kind": "review_round"}),
            ("fix_results", "fix_findings",
             {"status": "ok", "kind": "fix_findings", "findings": [],
              "files_changed": []},
             {"status": "ok", "kind": "fix_findings", "findings": []}),
            ("fix_blocked", "fix_findings",
             {"status": "blocked", "kind": "fix_findings",
              "blocked_reason": "Cannot fix"},
             {"status": "blocked", "kind": "fix_findings"}),
            ("reclassify_result", "reclassify",
             {"status": "ok", "kind": "reclassify", "drift_risk": "low",
              "drift_damage": "medium", "reason": "Bounded change"},
             {"status": "ok", "kind": "reclassify", "drift_risk": "none",
              "drift_damage": "medium", "reason": "Bounded change"}),
            ("discussion_turn_envelope", "discussion_turn",
             {"kind": "discussion_turn", "markdown": "Position", "ready": True},
             {"kind": "discussion_turn", "markdown": ""}),
            ("questioner_turn_envelope", "questioner_turn",
             {"kind": "questioner_turn", "markdown": "Question", "ready": True},
             {"kind": "questioner_turn", "markdown": "Question", "ready": "yes"}),
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
                    options = {
                        "workspace": root,
                        "queued_findings": [],
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

        undeclared = section("implement_result")
        undeclared["text"] = ["Return {{files_changed}}"]
        with self.assertRaisesRegex(
            contracts.ContractError, "undeclared: files_changed"
        ):
            prompt_contracts.bind(base, (undeclared,))

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
        values = validation_values(seed)
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
            assembled["questions"]["items"].append({
                "id": "fixture_%s_question" % charge["executor"],
                "text": "Was the structural fixture answered?",
            })
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
            long_answers[0]["answer"] = "x" * 3000
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
        values = validation_values(seed)
        values.pop("task_executor_catalogue", None)
        assembled = prompt_router.assemble(
            seed,
            job="reclassify@doc",
            executor="agent_call",
            material="document",
            values=values,
        )
        assembled["questions"]["items"].append({
            "id": "fixture_reclassify_question",
            "text": "Was the reclassification fixture answered?",
        })
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

    def test_suite_checkpoint_trusts_command_meaning_but_rejects_bad_traces(self):
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
        prompt_contracts.validate(
            bound, passed_noop, configured_suite_commands=["true"]
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

    def test_rejected_fix_is_direct_and_rejects_retired_consultation(self):
        bound = prompt_contracts.bind(
            prompt("fix_findings", ("fix_results",))
        )
        reply = {
            "status": "ok",
            "kind": "fix_findings",
            "findings": [fix_finding()],
            "files_changed": [],
        }
        prompt_contracts.validate(bound, reply)
        reply["findings"][0]["consultation"] = {
            "resolution": "retired nested dialogue"
        }
        with self.assertRaises(contracts.ContractError):
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

    def test_need_rethink_is_problem_only_for_every_eligible_kind(self):
        for kind in (
            "draft_slice_note", "implement", "review_round",
            "delta_review", "fix_findings",
        ):
            with self.subTest(kind=kind):
                served = prompt(kind, (), ("q1",))
                bound = prompt_contracts.bind(
                    served,
                    consumer_sections=(section("need_rethink"),),
                )
                reply = {
                    "status": "need_rethink",
                    "problem": "Two governing requirements contradict.",
                    "questions": [{"id": "q1", "answer": "Inspected."}],
                }
                self.assertEqual(
                    prompt_contracts.validate(
                        bound, copy.deepcopy(reply), queued_findings=[]
                    ),
                    reply,
                )
                for invalid in (
                    dict(reply, problem=""),
                    dict(reply, problem=7),
                    dict(reply, kind=kind),
                    dict(reply, finding=report_finding()),
                    dict(reply, target_path="docs/design.md"),
                    {key: value for key, value in reply.items()
                     if key != "questions"},
                ):
                    with self.assertRaises(contracts.ContractError):
                        prompt_contracts.validate(
                            bound, invalid, queued_findings=[]
                        )

    def test_need_rethink_does_not_depend_on_the_fixer_queue(self):
        bound = prompt_contracts.bind(
            prompt("fix_findings", ()),
            consumer_sections=(section("need_rethink"),),
        )
        reply = {
            "status": "need_rethink",
            "problem": "The queued work exposes a governing contradiction.",
        }
        for queued in ([], [report_finding()]):
            with self.subTest(queued=bool(queued)):
                self.assertEqual(
                    prompt_contracts.validate(
                        bound, copy.deepcopy(reply), queued_findings=queued
                    ),
                    reply,
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

        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate(
                fix_bound,
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
                    "need_rethink",
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
                "problem": "The design contradicts itself.",
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
