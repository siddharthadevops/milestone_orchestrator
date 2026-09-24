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


def sparse_creation_reply():
    return {"search_material": {
        "objective": "Find a useful next step.", "context_summary": "An existing community room.",
        "facts": ["The room is available."], "constraints": [{"id": "budget", "text": "No spend."}],
        "assumptions": ["People may join."], "unknowns": ["Attendance."],
        "dimensions": [{"id": "room", "meaning": "The shared room"},
                       {"id": "readers", "meaning": "Current readers"},
                       {"id": "neighbors", "meaning": "Potential participants"}],
        "variants": [{"id": "z", "text": "Share"}, {"id": "b", "text": "Exchange"},
                     {"id": "a", "text": "Share"}],
        "composition_guidance": "Interpret the selected pairs in order.",
        "criteria": [{"id": "useful", "text": "Serves current participants."}],
        "order_semantics": "Sequence in which actions take effect.",
    }}


DEFAULT_CREATIVITY_QUESTION_IDS = (
    "substantive_originality", "productive_connections", "unexamined_assumptions",
    "creative_potential", "consequences_and_tensions", "contribution_to_brief",
)


def question_answers(question_ids):
    return [
        {"id": question_id, "answer": "Checked %s against the supplied material." % question_id}
        for question_id in question_ids
    ]


def sparse_gene_pool_reply(question_ids=DEFAULT_CREATIVITY_QUESTION_IDS):
    return {
        "gene_pool": {
            "subjects": ["Subject %d" % index for index in range(1, 11)],
            "verbs": ["Verb %d" % index for index in range(1, 11)],
            "adjectives": ["Adjective %d" % index for index in range(1, 11)],
        },
        "questions": question_answers(question_ids),
    }


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
                expected_sections = (kind + "_result",)
                if bound.question_ids:
                    expected_sections += ("questions_output",)
                self.assertEqual(bound.registered_section_ids, expected_sections)
                for case, reply in accepted.items():
                    with self.subTest(material=material, accepted=case):
                        prepared = copy.deepcopy(reply)
                        if bound.question_ids and isinstance(prepared, dict):
                            prepared.setdefault("questions", question_answers(bound.question_ids))
                        self.assertIs(
                            prompt_contracts.validate(bound, prepared, **context), prepared,
                        )
                for case, reply in rejected.items():
                    with self.subTest(material=material, rejected=case):
                        prepared = copy.deepcopy(reply)
                        if bound.question_ids and isinstance(prepared, dict):
                            prepared.setdefault("questions", question_answers(bound.question_ids))
                        with self.assertRaises(contracts.ContractError):
                            prompt_contracts.validate(bound, prepared, **context)

    def test_evaluate_candidates_contextual_contract(self):
        valid = {
            "candidate_id": "c1",
            "constraint_valid": True, "constraint_violations": [],
            "reason": "Uses available capacity without spending.", "assumptions": [], "score": 0,
        }
        invalid = {
            "candidate_id": "c2",
            "constraint_valid": False, "constraint_violations": ["budget", "capacity"],
            "reason": "Useful but exceeds the budget and available capacity.",
            "assumptions": ["A larger room is available"], "score": 0,
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
        records["proposal_contaminates_review"] = dict(valid, proposal="A rewritten proposal")
        records["rejected_nonzero_score"] = dict(
            valid, constraint_valid=False,
            constraint_violations=["__insufficient_detail__"], score=0.5,
        )
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
            "reordered_with_rejection": reply,
            "fractional_score": {"evaluations": [dict(valid, score=0.5), invalid]},
        }, rejected, candidate_ids=["c1", "c2"], constraint_ids=["budget", "capacity"])
        self.assert_creativity_replies("evaluate_candidates", {
            "no_constraints": {"evaluations": [valid]},
        }, {}, candidate_ids=["c1"], constraint_ids=[])
        for rejection_id in prompt_contracts.CREATIVITY_REJECTION_IDS:
            service_rejection = dict(
                valid, constraint_valid=False,
                constraint_violations=[rejection_id], score=0,
            )
            self.assert_creativity_replies("evaluate_candidates", {
                rejection_id: {"evaluations": [service_rejection]},
            }, {}, candidate_ids=["c1"], constraint_ids=[])

    def test_compose_candidates_contextual_contract(self):
        first = {"candidate_id": "c1", "proposal": "Share the existing room."}
        second = {"candidate_id": "c2", "proposal": "Expose the missing access agreement."}
        reply = {"compositions": [second, first]}
        rejected = closed_object_defects(reply)
        rejected.update({
            "empty_coverage": {"compositions": []},
            "missing_candidate": {"compositions": [first]},
            "duplicate_candidate": {"compositions": [first, first]},
            "extra_candidate": {
                "compositions": [first, second, dict(first, candidate_id="c3")],
            },
            "evaluation_contamination": {
                "compositions": [dict(first, score=1), second],
            },
            "missing_questions": {"compositions": [first, second], "questions": []},
        })
        for case, record in closed_object_defects(first).items():
            rejected["record_" + case] = {"compositions": [record, second]}
        self.assert_creativity_replies(
            "compose_candidates", {"reordered": reply}, rejected,
            candidate_ids=["c1", "c2"],
        )

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
            "order_semantics": "Sequence in which the chosen actions are applied.",
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
        invalid.append(replaced(("search_material", "objective"), 42))
        invalid.append(replaced(("search_material", "order_semantics"), ""))
        invalid.append(replaced(("search_material", "dimensions", 0, "id"), "__order__"))
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
        request = (
            "Help me find a useful next step for our existing room. We have no money "
            "to spend, so explore ways to use its current capacity. Distinguish facts "
            "from assumptions and explain which possibilities serve current participants."
        )
        self.assertNotEqual(minimal["search_material"]["objective"], request)
        echoed = replaced(("search_material", "objective"), request)
        values = {"workspace": "/workspace", "objective": request, "gene_count": 10,
                  "context": "", "references": "[]"}
        with tempfile.TemporaryDirectory() as home:
            prompt_sets.ensure_default(home)
            for material_name in ("default", "literature", "business"):
                served = prompt_router.resolve(
                    home, job="create_genes@creativity", executor="agent_call",
                    material=material_name, values=values,
                ).prompt
                bound = prompt_contracts.bind(served)
                self.assertEqual(
                    bound.registered_section_ids,
                    ("create_genes_result", "questions_output"),
                )
                for reply in (minimal, populated, echoed):
                    reply = dict(
                        reply, questions=question_answers(bound.question_ids),
                    )
                    self.assertIs(prompt_contracts.validate(
                        bound, reply,
                    ), reply)
                for index, reply in enumerate(invalid):
                    with self.subTest(material=material_name, invalid=index):
                        reply = copy.deepcopy(reply)
                        if isinstance(reply, dict):
                            reply.setdefault(
                                "questions", question_answers(bound.question_ids),
                            )
                        with self.assertRaises(contracts.ContractError):
                            prompt_contracts.validate(bound, reply)
                served["kind"] = "evaluate_candidates"
                with self.assertRaisesRegex(contracts.ContractError, "prompt kind"):
                    prompt_contracts.validate(
                        prompt_contracts.bind(served), dict(
                            minimal, questions=question_answers(bound.question_ids),
                        ),
                    )
                served["output_contract"] = [section("operator_data_only")]
                served["questions"]["items"] = []
                self.assertEqual(prompt_contracts.validate(
                    prompt_contracts.bind(served), {"operator": "reply"},
                ), {"operator": "reply"})

    def test_sparse_material_contract(self):
        reply = sparse_creation_reply()
        larger = copy.deepcopy(reply)
        larger["search_material"]["variants"] = [
            {"id": str(index), "text": "Action %d" % index} for index in range(15)
        ]
        minimal = copy.deepcopy(reply)
        minimal["search_material"]["dimensions"] = reply["search_material"]["dimensions"][:1]
        minimal["search_material"]["variants"] = reply["search_material"]["variants"][:1]
        for key in ("facts", "constraints", "assumptions", "unknowns"):
            minimal["search_material"][key] = []
        invalid = {}

        def replace(path, value):
            changed = copy.deepcopy(reply)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return changed

        objects = [(), ("search_material",)] + [
            ("search_material", key, 0) for key in ("dimensions", "variants", "constraints", "criteria")
        ]
        for path in objects:
            record = reply
            for key in path:
                record = record[key]
            for defect, value in closed_object_defects(record).items():
                invalid[str(path) + defect] = replace(path, value) if path else value
        for key in ("facts", "assumptions", "unknowns"):
            for value in ([""], [42]):
                invalid[key + str(value)] = replace(("search_material", key), value)
        for key in ("dimensions", "variants", "constraints", "criteria"):
            first = reply["search_material"][key][0]
            invalid[key + " duplicate"] = replace(("search_material", key), [first, first])
            if key != "constraints":
                invalid[key + " empty"] = replace(("search_material", key), [])
        for key, identifier in (("dimensions", "__order__"), ("dimensions", "__omit__"),
                                ("variants", "__omit__")):
            invalid[key + identifier] = replace(("search_material", key, 0, "id"), identifier)
        invalid["per_dimension_variants"] = replace(
            ("search_material", "dimensions", 0), dict(reply["search_material"]["dimensions"][0],
                                                      variants=reply["search_material"]["variants"]),
        )
        accepted = {"minimal": minimal, "more_dimensions_than_values": reply, "larger_repertoire": larger}
        for case, value in accepted.items():
            with self.subTest(supplied=case):
                prompt_contracts.validate_create_genes_reply(value, creativity_semantics="sparse_v2")
        for case, value in invalid.items():
            with self.subTest(supplied=case), self.assertRaises(contracts.ContractError):
                prompt_contracts.validate_create_genes_reply(value, creativity_semantics="sparse_v2")
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate_create_genes_reply(reply)

    def test_sparse_gene_pool_contextual_contract(self):
        valid = sparse_gene_pool_reply()
        valid.pop("questions")
        invalid = closed_object_defects(valid)

        def replace(path, value):
            changed = copy.deepcopy(valid)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return changed

        for category in ("subjects", "verbs", "adjectives"):
            values = valid["gene_pool"][category]
            invalid[category + "_nine"] = replace(("gene_pool", category), values[:-1])
            invalid[category + "_eleven"] = replace(
                ("gene_pool", category), values + ["Extra"],
            )
            invalid[category + "_blank"] = replace(
                ("gene_pool", category, 0), " ",
            )
            invalid[category + "_non_string"] = replace(
                ("gene_pool", category, 0), 42,
            )
            duplicate = list(values)
            duplicate[-1] = values[0].swapcase()
            invalid[category + "_duplicate_casefolded"] = replace(
                ("gene_pool", category), duplicate,
            )
        invalid["missing_questions"] = dict(valid, questions=[])
        invalid["legacy_shape"] = sparse_creation_reply()
        self.assert_creativity_replies(
            "create_genes", {"exact_ten_each": valid}, invalid,
            creativity_semantics="sparse_v2",
        )

    def test_sparse_material_normalization(self):
        from itertools import permutations

        source = sparse_creation_reply()
        # Exact text equality only: whitespace and case are not rewritten.
        source["search_material"]["variants"].extend([
            {"id": "c", "text": "share"}, {"id": "d", "text": "Share "},
        ])
        expected = copy.deepcopy(source)
        expected["search_material"]["variants"] = sorted(
            expected["search_material"]["variants"][1:], key=lambda item: item["id"],
        )
        for variants in permutations(source["search_material"]["variants"]):
            value = copy.deepcopy(source)
            value["search_material"]["variants"] = list(variants)
            before = copy.deepcopy(value)
            admitted = prompt_contracts.validate_create_genes_reply(value, creativity_semantics="sparse_v2")
            self.assertEqual(value, before)
            self.assertEqual(admitted, expected)

    def test_fragment_pool_contract_uses_requested_count_and_preserves_input(self):
        source = {"gene_pool": ["Firebase", "rojo intenso", "calor   compartido local"]}
        before = copy.deepcopy(source)
        self.assertIs(prompt_contracts.validate_fragment_pool_reply(
            source, gene_count=3,
        ), source)
        self.assertEqual(source, before)
        self.assertEqual(prompt_contracts.validate_fragment_pool_reply(
            {"gene_pool": ["fragmento %d" % index for index in range(10)]},
        )["gene_pool"], ["fragmento %d" % index for index in range(10)])

        invalid = [None, [], {}, {"gene_pool": {}},
                   {"gene_pool": source["gene_pool"], "questions": []}]
        for pool in ([], source["gene_pool"][:2], source["gene_pool"] + ["extra"],
                     [None, "rojo", "verde"], ["", "rojo", "verde"],
                     [" \n\t", "rojo", "verde"], ["uno dos tres cuatro", "rojo", "verde"],
                     ["rojo intenso", " ROJO   intenso ", "verde"],
                     ["Firebase", "firebase", "verde"]):
            invalid.append({"gene_pool": pool})
        for reply in invalid:
            with self.subTest(reply=reply), self.assertRaises(contracts.ContractError):
                prompt_contracts.validate_fragment_pool_reply(reply, gene_count=3)
        for count in (None, True, 0, -1, 3.0, "3"):
            with self.subTest(count=count), self.assertRaises(contracts.ContractError):
                prompt_contracts.validate_fragment_pool_reply(source, gene_count=count)

    def test_fragment_creation_requires_questions_and_exact_configured_pool(self):
        valid = {"gene_pool": ["casa", "roja", "limpiar"]}
        invalid = closed_object_defects(valid)
        invalid.update({
            "wrong_count": {"gene_pool": ["casa", "roja"]},
            "four_words": {"gene_pool": ["casa de color rojo", "roja", "limpiar"]},
            "duplicate": {"gene_pool": ["casa", " CASA ", "limpiar"]},
            "missing_questions": dict(valid, questions=[]),
            "sparse_v2_shape": {"gene_pool": sparse_gene_pool_reply()["gene_pool"]},
            "canonical_material": sparse_creation_reply(),
        })
        self.assert_creativity_replies(
            "create_genes", {"three_fragments": valid}, invalid,
            creativity_semantics="fragments_v3", gene_count=3,
        )

    def test_creativity_requires_every_new_question_and_rejects_retired_answers(self):
        values = validation_values(prompt_sets.default_seed())
        values.pop("task_executor_catalogue")
        replies = {
            "create_genes": {"gene_pool": ["casa", "roja", "limpiar"]},
            "compose_candidates": {"compositions": [
                {"candidate_id": "c1", "proposal": "Use the supplied seed."},
            ]},
            "evaluate_candidates": {"evaluations": [{
                "candidate_id": "c1", "constraint_valid": True,
                "constraint_violations": [], "reason": "Answers the brief.",
                "assumptions": [], "score": 0.5,
            }]},
        }
        context = dict(creativity_semantics="fragments_v3", gene_count=3,
                       candidate_ids=["c1"], constraint_ids=[])
        retired = ("machinery_trust", "environment_fit", "human_scale",
                   "character_idiolect", "reader_emotion", "reader_legibility",
                   "meaningful_surprise")
        with tempfile.TemporaryDirectory() as home:
            prompt_sets.ensure_default(home)
            for material in ("default", "literature", "business"):
                for kind, payload in replies.items():
                    with self.subTest(material=material, kind=kind):
                        served = prompt_router.resolve(
                            home, job=kind + "@creativity", executor="agent_call",
                            material=material, values=values,
                        ).prompt
                        bound = prompt_contracts.bind(served)
                        self.assertEqual(bound.question_ids, DEFAULT_CREATIVITY_QUESTION_IDS)
                        answers = question_answers(DEFAULT_CREATIVITY_QUESTION_IDS)
                        prompt_contracts.validate(bound, dict(payload, questions=answers), **context)
                        for missing in range(len(answers)):
                            with self.subTest(missing=answers[missing]["id"]):
                                with self.assertRaises(contracts.ContractError):
                                    prompt_contracts.validate(bound, dict(
                                        payload, questions=answers[:missing] + answers[missing + 1:],
                                    ), **context)
                        for old_id in retired:
                            with self.subTest(retired=old_id):
                                with self.assertRaises(contracts.ContractError):
                                    prompt_contracts.validate(bound, dict(
                                        payload, questions=[dict(answers[0], id=old_id)] + answers[1:],
                                    ), **context)

    def test_fragment_canonical_material_uses_shared_variants(self):
        reply = sparse_creation_reply()
        material = reply["search_material"]
        material["dimensions"] = [
            {"id": "fragment_01", "meaning": "casa"},
            {"id": "fragment_02", "meaning": "roja"},
        ]
        material["variants"] = [
            {"id": "affirm", "text": "Include"},
            {"id": "negate", "text": "Exclude"},
        ]
        self.assertEqual(prompt_contracts.validate_create_genes_reply(
            reply, creativity_semantics="fragments_v3",
        ), reply)
        with self.assertRaises(contracts.ContractError):
            prompt_contracts.validate_create_genes_reply(reply)

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
