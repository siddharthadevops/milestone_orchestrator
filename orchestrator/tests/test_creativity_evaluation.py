"""Evaluation integration through live routers and host-owned call groups."""

import copy
import json
import os
import re
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from types import SimpleNamespace
from unittest import mock

from orchestrator import creativity_evaluation as evaluation
from orchestrator import kvstore, pricing, prompt_sets, runners, staffing, task_api
from orchestrator.task_execution import ExecutionBusy
from orchestrator.tests import test_creativity_search as search_fixture
from orchestrator.tests import test_prompt_router as router_fixture
from orchestrator.tests import test_task_call_group as group_fixture
from orchestrator.tests.test_staffing_sessions import resolver_doc, session_body
from orchestrator.tests.test_tasks import creativity_configuration, legacy_creativity_configuration
from orchestrator.tests.test_prompt_contracts import (
    DEFAULT_CREATIVITY_QUESTION_IDS, sparse_gene_pool_reply,
)


DEFAULT_QUESTION_IDS = DEFAULT_CREATIVITY_QUESTION_IDS
LITERATURE_QUESTION_IDS = DEFAULT_QUESTION_IDS + (
    "character_idiolect", "reader_emotion", "reader_legibility", "meaningful_surprise",
)


class CreativityEvaluationFixture(unittest.TestCase):
    order = group_fixture.TaskCallGroupControlTests.order
    _owned_group = group_fixture.TaskCallGroupControlTests._owned_group
    creativity_semantics = None

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="creativity-evaluation-")
        self.addCleanup(self.temporary.cleanup)
        self.home = os.path.join(self.temporary.name, "home")
        self.host = task_api.DirectTaskHost(self.home)
        self.identity, self.group = self._owned_group(self.host, "work", config={
            "billing": {"codex": "api", "claude": "api"},
        })
        self.workspace = self.host._active[self.identity]
        source = search_fixture.CreativitySearchTest()
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.source = source
        self.material = source.accepted_material()
        genomes = [{"format": "a", "channel": "b"}, {"format": "b", "channel": "a"}]
        self.candidates = dict(zip(("c-0", "c-1"), genomes))
        evaluated = [copy.deepcopy(pair[1]) for pair in source.evaluated(
            genomes, [0.4, 0.0], invalid=(1,), prefix="c",
        )]
        self.proposals = {}
        for item in evaluated:
            proposal = item.pop(
                "proposal", "Use the exact supplied combination for %s." % item["candidate_id"],
            )
            self.proposals[item["candidate_id"]] = proposal
            item["proposal"] = proposal
        self.reply = {"evaluations": evaluated[::-1]}
        fixture = (creativity_configuration if self.creativity_semantics == "sparse_v2"
                   else legacy_creativity_configuration)
        self.configuration = fixture(order_mode="fixed")
        self.document = resolver_doc()
        for slot in ("2", "3"):
            for rigor, cell in (("low", [1, 1]), ("medium", [2, 2]), ("high", [3, 4])):
                self.document["tuning"][rigor][slot]["review"] = cell
                self.document["tuning"][rigor][slot]["brainstorm"] = cell
        staffing.save(self.home, self.document)
        self.session = staffing.create_session(
            self.home, session_body(document="matrix", rigor="low"),
        )["id"]
        prompt_sets.ensure_default(self.home)
        self.store = kvstore.LocalKVClient(os.path.join(self.home, "search"))
        self.store.put("checkpoint", {"search_material": self.material, "generation": 2})

    def wave(self, physical=None, **changes):
        options = dict(
            home=self.home, session=self.session, workspace=self.workspace,
            configuration=dict(self.configuration, max_evaluated_candidates=20,
                               evaluation_batch_size=1, evaluation_concurrency=2),
            search_material=self.material, candidates=self.candidates,
            comparison_ids=list(self.candidates), generation=2, execution_context=None,
            store=self.store, checkpoint_key="checkpoint",
            creativity_semantics=self.creativity_semantics,
        )
        options.update(changes)
        return evaluation.evaluate_wave(
            self.group, SimpleNamespace(call=physical or self.batch_result), **options,
        )

    @staticmethod
    def question_answers(prompt):
        return [
            {"id": question_id, "answer": "Checked %s." % question_id}
            for question_id in re.findall(r"^- ([A-Za-z0-9_-]+):", prompt, re.MULTILINE)
        ]

    def compositions(self, candidates=None):
        candidates = self.candidates if candidates is None else candidates
        return [
            {
                "candidate_id": candidate_id,
                "proposal": self.proposals.get(
                    candidate_id, "Use the exact supplied combination for %s." % candidate_id,
                ),
            }
            for candidate_id in candidates
        ]

    @staticmethod
    def prompt_records(prompt, *markers):
        for marker in markers:
            if marker in prompt:
                return json.loads(prompt.split(marker, 1)[1].splitlines()[0])
        raise AssertionError("prompt contains none of the expected JSON markers")

    def batch_result(self, _family, prompt, _workspace, **_kwargs):
        questions = self.question_answers(prompt)
        if "KIND: compose_candidates" in prompt:
            seeds = self.prompt_records(
                prompt,
                "EXACT CANDIDATE SEEDS (JSON; IDs identify candidates, not rank):\n",
                "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n",
            )
            return self.result({
                "compositions": self.compositions({item["candidate_id"]: None for item in seeds}),
                "questions": questions,
            })
        if "KIND: evaluate_candidates" not in prompt:
            raise AssertionError("unexpected creativity job")
        supplied = self.prompt_records(
            prompt,
            "IMMUTABLE COMPOSITIONS AND THEIR EXACT COMPONENTS (JSON):\n",
            "IMMUTABLE COMPOSITIONS TO EVALUATE (JSON):\n",
            "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n",
        )
        ids = [item["candidate_id"] for item in supplied]
        templates = {item["candidate_id"]: item for item in self.reply["evaluations"]}
        valid = next(item for item in self.reply["evaluations"] if item["constraint_valid"])
        evaluations = []
        for candidate_id in reversed(ids):
            item = dict(templates.get(candidate_id, valid), candidate_id=candidate_id)
            item.pop("proposal", None)
            evaluations.append(item)
        return self.result({
            "evaluations": evaluations,
            "questions": questions,
        })

    def evaluation_result(self, prompt, evaluations):
        cleaned = []
        for evaluation_item in evaluations:
            item = dict(evaluation_item)
            item.pop("proposal", None)
            cleaned.append(item)
        return self.result({
            "evaluations": cleaned,
            "questions": self.question_answers(prompt),
        })

    def progress_wave(self, progress, physical=None, **changes):
        options = dict(
            home=self.home, session=self.session, workspace=self.workspace,
            configuration=self.configuration, search_material=self.material,
            generation=progress["generations_completed"] + 1, execution_context=None,
            store=self.store, checkpoint_key="checkpoint",
            creativity_semantics=self.creativity_semantics,
        )
        options.update(changes)
        return evaluation.evaluate_progress_wave(
            self.group, SimpleNamespace(call=physical or self.batch_result), progress=progress, **options,
        )

    def checkpoint(self):
        return kvstore.LocalKVClient(self.store.directory).get("checkpoint")

    def call(self, physical, **changes):
        options = dict(
            home=self.home, session=self.session, workspace=self.workspace,
            configuration=self.configuration, search_material=self.material,
            candidates=self.candidates, generation=2, batch="b1", execution_context=None,
            creativity_semantics=self.creativity_semantics,
            compositions=self.compositions(changes.get("candidates", self.candidates)),
            prompt_values={"ecosystem_map": "ADDITIONAL ROOT /reference — READ-ONLY"},
        )
        options.update(changes)
        return evaluation.call_evaluation_batch(self.group, SimpleNamespace(call=physical), **options)

    def result(self, reply=None):
        usage = {"input_tokens": 10, "output_tokens": 2}
        return runners.RunnerResult(
            json.dumps(self.reply if reply is None else reply), 0, 1.0,
            token_usage=usage, cost_payloads=[dict(usage, total_cost_usd=0.02)],
        )

    def evidence(self):
        lifecycle = task_api.StandaloneTaskStore(self.home).lifecycle(self.identity)
        return [event["physical_dispatch"] for event in lifecycle["history"]
                if "physical_dispatch" in event], lifecycle["accounting"]

    def write_prompt(self, marker, kind="evaluate_candidates"):
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        documents["milestone/" + kind + ".json"]["instructions"]["parts"].append(
            {"text": [marker], "variables": []},
        )
        return router_fixture.PromptRouterTest.write_set(self.home, "operator", documents)

    def stagnant_progress(self):
        self.configuration = dict(self.configuration, generation_limit=20,
                                  max_evaluated_candidates=40, max_stagnation_expansions=2)
        progress = evaluation.creativity_search.new_progress()
        for candidates in (self.candidates, {}):
            evaluation.creativity_search.begin_generation(progress, candidates, self.configuration)
            self.progress_wave(progress)
        return progress

    def expand(self, progress, physical, **changes):
        options = dict(
            home=self.home, session=self.session, workspace=self.workspace,
            configuration=self.configuration, search_material=self.material,
            explored={evaluation.creativity_search.genome_key(g) for g in self.candidates.values()},
            explored_account="Explored a full story online and an excerpt at a library.",
            execution_context=None,
            prompt_values={"ecosystem_map": "ADDITIONAL ROOT /reference — READ-ONLY"},
        )
        options.update(changes)
        return evaluation.expand_progress(self.group, SimpleNamespace(call=physical), progress=progress, **options)


class CreativityEvaluationTest(CreativityEvaluationFixture):
    def test_creation_uses_matching_semantics_for_prompt_and_reply(self):
        for semantics in (None, "sparse_v2"):
            with self.subTest(semantics=semantics):
                source = (sparse_gene_pool_reply() if semantics else {
                    "search_material": self.material,
                    "questions": [
                        {"id": question_id, "answer": "Checked %s." % question_id}
                        for question_id in DEFAULT_QUESTION_IDS
                    ],
                })
                calls = []

                def physical(_family, prompt, _workspace, **_kwargs):
                    calls.append(prompt)
                    self.assertIn("SAVED MATERIAL SEMANTICS: " + (semantics or "legacy"), prompt)
                    return self.result(source)

                material, result = evaluation.create_genes(
                    self.group, SimpleNamespace(call=physical), objective=search_fixture.OBJECTIVE,
                    context="", references=[], home=self.home, session=self.session,
                    workspace=self.workspace, configuration=self.configuration, execution_context=None,
                    creativity_semantics=semantics,
                )
                self.assertEqual(len(calls), 1)
                self.assertIsInstance(result, runners.RunnerResult)
                self.assertEqual(
                    [item["id"] for item in result.diligence_questions],
                    list(DEFAULT_QUESTION_IDS),
                )
                if semantics:
                    self.assertEqual(len(material["dimensions"]), 10)
                    self.assertEqual(len(material["variants"]), 100)
                    self.assertEqual(material["dimensions"][0], {
                        "id": "subject_01", "meaning": "Subject 1",
                    })
                    self.assertEqual(material["variants"][0], {
                        "id": "verb_01__adjective_01",
                        "text": 'verb "Verb 1"; adjective "Adjective 1"',
                    })
                    self.assertEqual(material["objective"], search_fixture.OBJECTIVE)
                else:
                    self.assertEqual(material, self.material)

    def test_creation_answers_default_and_literature_perspective_checks(self):
        for material_name, expected_ids in (
            ("default", DEFAULT_QUESTION_IDS),
            ("literature", LITERATURE_QUESTION_IDS),
        ):
            with self.subTest(material=material_name):
                staffing.edit_session(self.home, self.session, {"material": material_name})

                def physical(_family, prompt, _workspace, **_kwargs):
                    return self.result(sparse_gene_pool_reply(
                        item["id"] for item in self.question_answers(prompt)
                    ))

                _material, result = evaluation.create_genes(
                    self.group, SimpleNamespace(call=physical),
                    objective=search_fixture.OBJECTIVE, context="", references=[],
                    home=self.home, session=self.session, workspace=self.workspace,
                    configuration=self.configuration, execution_context=None,
                    creativity_semantics="sparse_v2",
                )
                self.assertEqual(
                    [item["id"] for item in result.diligence_questions], list(expected_ids),
                )

    def test_sparse_creation_falls_back_from_legacy_named_prompt(self):
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        creation = documents["milestone/create_genes.json"]
        semantics = next(
            part for part in creation["instructions"]["parts"]
            if any(variable["name"] == "creativity_semantics"
                   for variable in part.get("variables", []))
        )
        semantics["text"] = [
            "STALE NAMED PROMPT",
            "Code combines exactly one variant per dimension.",
        ]
        semantics["variables"] = []
        creation["output_contract"]["sections"][0]["text"] = [
            "OUTPUT CONTRACT: return exactly one JSON object and nothing else.",
            "The only top-level key is search_material.",
            "search_material has exactly objective, context_summary, facts, constraints, assumptions, unknowns, dimensions, composition_guidance, criteria and order_semantics.",
            "Each dimension contains id, meaning and nested variants.",
        ]
        router_fixture.PromptRouterTest.write_set(
            self.home, "legacy-operator", documents,
        )
        source = sparse_gene_pool_reply()
        prompts = []

        def physical(_family, prompt, _workspace, **_kwargs):
            prompts.append(prompt)
            return self.result(source)

        material, result = evaluation.create_genes(
            self.group, SimpleNamespace(call=physical),
            objective=search_fixture.OBJECTIVE, context="", references=[],
            home=self.home, session=self.session, workspace=self.workspace,
            configuration=self.configuration, execution_context=None,
            creativity_semantics="sparse_v2", prompt_set="legacy-operator",
        )

        self.assertEqual(len(prompts), 1)
        self.assertIn("SAVED MATERIAL SEMANTICS: sparse_v2", prompts[0])
        self.assertNotIn("STALE NAMED PROMPT", prompts[0])
        self.assertEqual(result.prompt_set_fallback, "stored_default")
        self.assertEqual(len(material["dimensions"]), 10)
        self.assertEqual(len(material["variants"]), 100)

    def test_sparse_creation_falls_back_from_wrong_contract_marker(self):
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        creation = documents["milestone/create_genes.json"]
        instruction = next(
            part for part in creation["instructions"]["parts"]
            if any(variable["name"] == "creativity_contract"
                   for variable in part.get("variables", []))
        )
        marker = next(
            variable for variable in instruction["variables"]
            if variable["name"] == "creativity_contract"
        )
        marker["default"] = "combined_creation_and_evaluation_v0"
        instruction["text"].append("STALE CONTRACT MARKER")
        router_fixture.PromptRouterTest.write_set(
            self.home, "wrong-contract", documents,
        )
        prompts = []

        def physical(_family, prompt, _workspace, **_kwargs):
            prompts.append(prompt)
            return self.result(sparse_gene_pool_reply())

        material, result = evaluation.create_genes(
            self.group, SimpleNamespace(call=physical),
            objective=search_fixture.OBJECTIVE, context="", references=[],
            home=self.home, session=self.session, workspace=self.workspace,
            configuration=self.configuration, execution_context=None,
            creativity_semantics="sparse_v2", prompt_set="wrong-contract",
        )

        self.assertEqual(len(prompts), 1)
        self.assertNotIn("STALE CONTRACT MARKER", prompts[0])
        self.assertIn(evaluation.CREATIVITY_CONTRACT, prompts[0])
        self.assertEqual(result.prompt_set_fallback, "stored_default")
        self.assertEqual(len(material["variants"]), 100)

    def test_expansion_uses_live_routed_contract(self):
        progress = self.stagnant_progress()
        records_before = len(self.evidence()[0])
        self.write_prompt("FIRST PROMPT", "expand_genes")
        staffing.edit_session(self.home, self.session, {"material": "literature"})
        addition = {"additions": [{"dimension_id": "format", "variants": [
            {"id": "new", "text": "Full story", "reason": "Another arrangement."},
        ]}]}
        dispatched = []

        def physical(family, prompt, workspace, model=None, effort=None, **_kwargs):
            dispatched.append((family, model, effort, prompt, workspace))
            if len(dispatched) == 1:
                self.document["assignment"]["brainstorm"]["1"] = 3
                staffing.save(self.home, self.document)
                staffing.edit_session(self.home, self.session, {"material": "business", "rigor": "high"})
                self.write_prompt("SECOND PROMPT", "expand_genes")
                return self.result({"additions": [dict(addition["additions"][0], dimension_id="unknown")]})
            # The later intervention must reject an ID incorporated by the first.
            return self.result(addition if len(dispatched) in (2, 3) else {"additions": []})

        expanded, carrier = self.expand(progress, physical, prompt_set="operator")
        self.assertEqual(progress["expansion_interventions"], 1)
        self.assertEqual(progress["evaluated_candidates"], 2)
        self.assertEqual(progress["expansions"][0]["call_id"], carrier.call_id)
        self.assertEqual(progress["expansions"][0]["additions"], addition["additions"])
        self.assertEqual(dispatched[0][:3], ("codex", "gpt-5.6-luna", "low"))
        self.assertEqual(dispatched[1][:3], ("claude", "claude-fable-5", "xhigh"))
        self.assertIn("FIRST PROMPT", dispatched[0][3])
        self.assertIn("LITERATURE REFINEMENT", dispatched[0][3])
        self.assertIn("SECOND PROMPT", dispatched[1][3])
        self.assertIn("BUSINESS REFINEMENT", dispatched[1][3])
        self.assertIn("REPAIR:", dispatched[1][3])
        # No second intervention until the next full window.
        self.assertIsNone(self.expand(progress, physical, search_material=expanded)[1])
        evaluation.creativity_search.begin_generation(progress, {}, self.configuration)
        self.progress_wave(progress, search_material=expanded)
        self.write_prompt("THIRD PROMPT", "expand_genes")
        self.document["assignment"]["brainstorm"]["1"] = 2
        staffing.save(self.home, self.document)
        staffing.edit_session(self.home, self.session, {"material": "unlayered"})
        before = staffing.read_session(self.home, self.session)
        current, _ = self.expand(progress, physical, search_material=expanded, prompt_set="operator",
                                configuration=dict(self.configuration, rigor={
                                    "default": "medium", "expand_genes": "low",
                                }))
        self.assertEqual(current, expanded)
        self.assertIsNone(progress["stop_reason"])
        self.assertEqual(progress["expansion_interventions"], 2)
        self.assertEqual(dispatched[-1][:3], ("codex", "gpt-5.6-luna", "low"))
        self.assertIn("THIRD PROMPT", dispatched[-1][3])
        self.assertNotIn("REFINEMENT", dispatched[-1][3])
        self.assertEqual(staffing.read_session(self.home, self.session), before)
        for index, (_family, _model, _effort, prompt, workspace) in enumerate(dispatched):
            self.assertEqual(workspace, self.workspace)
            self.assertIn("KIND: expand_genes", prompt)
            self.assertIn("ADDITIONAL ROOT /reference — READ-ONLY", prompt)
            self.assertIn("Do not edit files or execute proposals", prompt)
            self.assertIn("SEARCH OBJECTIVE:\n" + self.material["objective"], prompt)
            self.assertIn("Explored a full story online and an excerpt at a library.", prompt)
            supplied = json.loads(prompt.split("COMPLETE SEARCH MATERIAL (JSON):\n")[1].splitlines()[0])
            self.assertEqual(supplied, self.material if index < 2 else expanded)
            promising = json.loads(prompt.split(
                "PROMISING EVALUATED CANDIDATES (JSON):\n",
            )[1].splitlines()[0])
            self.assertEqual(len(promising), 1)
            self.assertEqual(set(promising[0]), {
                "candidate_id", "proposal", "constraint_valid",
                "constraint_violations", "reason", "assumptions", "score", "components",
            })
            self.assertEqual(promising[0]["candidate_id"], "c-0")
        records, accounting = self.evidence()
        expansions = records[records_before:]
        self.assertEqual(len(expansions), 4)
        self.assertEqual(len({record["call_id"] for record in expansions}), 4)
        self.assertEqual(expansions[0]["call_context"]["batch"], expansions[1]["call_context"]["batch"])
        self.assertEqual(expansions[2]["call_context"]["batch"], expansions[3]["call_context"]["batch"])
        self.assertEqual([r["call_context"]["generation"] for r in expansions], [2, 2, 3, 3])
        self.assertEqual([r["call_context"]["material"] for r in expansions],
                         ["literature", "business", "unlayered", "unlayered"])
        self.assertTrue(all(r["call_context"]["job"] == "expand_genes" for r in expansions))
        self.assertEqual(accounting["token_usage"]["input_tokens"], 10 * len(records))
        expected_cost = sum((pricing.codex_api_cost if r["family"] == "codex" else pricing.claude_api_cost)(
            r["model"], r["cost_payloads"][0],
        ) for r in records)
        self.assertAlmostEqual(accounting["cost"]["api_usd"], expected_cost)
        evaluation.creativity_search.begin_generation(progress, {}, self.configuration)
        self.progress_wave(progress, search_material=current)
        self.assertIsNone(self.expand(progress, physical, search_material=current)[1])
        self.assertEqual(progress["stop_reason"], "persistent_stagnation")
        self.assertEqual(self.evidence(), (records, accounting))

    def test_expansion_faults_keep_shared_controls_and_evidence(self):
        progress = self.stagnant_progress()
        original = copy.deepcopy(progress)
        records_before = len(self.evidence()[0])
        reused = {"additions": [{"dimension_id": "format", "variants": [
            {"id": "a", "text": "Full story", "reason": "Already present."},
        ]}]}
        with self.assertRaises(runners.WorkerProtocolError):
            self.expand(progress, lambda *_args, **_kwargs: self.result(reused))
        self.assertEqual(len(self.evidence()[0]) - records_before, 2)
        session = staffing.create_session(self.home, session_body(document="matrix", families=[]))["id"]
        with self.assertRaises(staffing.StaffingConditionError) as caught:
            self.expand(progress, lambda *_a, **_kw: self.fail("unavailable dispatch"), session=session)
        self.assertEqual(caught.exception.code, "staffing_unavailable")
        self.document["roles"]["brainstorm"] = {"distinct_families": True}
        staffing.save(self.home, self.document)
        with self.assertRaises(staffing.StaffingConditionError) as caught:
            self.expand(progress, lambda *_a, **_kw: self.fail("unsatisfiable dispatch"))
        self.assertEqual(caught.exception.code, "distinct_families_unsatisfiable")
        self.document["roles"]["brainstorm"] = {}
        staffing.save(self.home, self.document)

        def failed(*_args, **_kwargs):
            raise runners.ProviderResponseError("expansion failed")

        with self.assertRaisesRegex(runners.ProviderResponseError, "expansion failed"):
            self.expand(progress, failed)
        self.assertEqual(len(self.evidence()[0]) - records_before, 3)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def physical(_family, _prompt, _workspace, active_control=None, **_kwargs):
            active_control._bind(lambda _text: False, lambda _reason: release.set() or True)
            try:
                entered.set()
                self.assertTrue(release.wait(5))
                return runners.ControlledInterruptionResult("", 0, 0.1, "stopped")
            finally:
                active_control._close()

        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(self.expand, progress, physical)
            self.assertTrue(entered.wait(5))
            self.host.stop(self.identity)
            material, result = future.result(5)
        self.assertEqual(material, self.material)
        self.assertEqual(result.interrupt_reason, "stopped")
        self.assertEqual(progress, original)
        self.group.ensure_quiescent()
        with self.assertRaises(runners.RunnerError):
            self.expand(progress, lambda *_a, **_kw: self.fail("stopped dispatch"))
        records, accounting = self.evidence()
        self.assertEqual(len(records) - records_before, 4)
        self.assertTrue(all(r["call_context"]["job"] == "expand_genes" for r in records[records_before:]))
        self.assertTrue(accounting["token_usage_partial"])
        self.assertTrue(accounting["cost_partial"])

    def test_each_attempt_reads_live_authorities(self):
        self.write_prompt("FIRST PROMPT")
        staffing.edit_session(self.home, self.session, {"material": "literature"})
        dispatched = []

        def physical(family, prompt, workspace, model=None, effort=None, **_kwargs):
            dispatched.append((family, model, effort, prompt, workspace))
            if len(dispatched) == 1:
                self.document["assignment"]["review"] = {"1": 3, "2": 2}
                staffing.save(self.home, self.document)
                staffing.edit_session(self.home, self.session, {"material": "business", "rigor": "high"})
                self.write_prompt("SECOND PROMPT")
                return self.evaluation_result(prompt, [])
            return self.batch_result(family, prompt, workspace, model=model, effort=effort)

        accepted, result = self.call(physical, prompt_set="operator")
        self.assertEqual(dispatched[0][:3], ("codex", "gpt-5.6-luna", "low"))
        self.assertEqual(dispatched[1][:3], ("claude", "claude-fable-5", "xhigh"))
        self.assertIn("FIRST PROMPT", dispatched[0][3])
        self.assertIn("LITERATURE REFINEMENT", dispatched[0][3])
        self.assertNotIn("SECOND PROMPT", dispatched[0][3])
        self.assertIn("SECOND PROMPT", dispatched[1][3])
        self.assertIn("BUSINESS REFINEMENT", dispatched[1][3])
        self.assertIn("REPAIR:", dispatched[1][3])
        self.assertEqual(accepted["regime"], {
            "material": "business", "agent": "claude", "model": "claude-fable-5", "effort": "xhigh",
        })
        self.assertEqual(accepted["call_id"], result.physical_dispatches[-1]["call_id"])
        self.assertNotEqual(accepted["call_id"], result.repair["call_id"])
        self.assertEqual(accepted["prompt_path"], result.call_context["prompt_path"])
        self.assertEqual(
            [item["id"] for item in accepted["questions"]], list(DEFAULT_QUESTION_IDS),
        )
        records, _accounting = self.evidence()
        self.assertEqual([item["call_context"]["material"] for item in records], ["literature", "business"])

        # Complete saves between batches, with job rigor overriding task and session.
        path = self.write_prompt("THIRD PROMPT")
        self.document["assignment"]["review"] = {"1": 2, "2": 3}
        staffing.save(self.home, self.document)
        staffing.edit_session(self.home, self.session, {"material": "unlayered"})
        before = staffing.read_session(self.home, self.session)
        configuration = dict(self.configuration, rigor={"default": "medium", "evaluate_candidates": "low"})
        third, _ = self.call(physical, prompt_set="operator", configuration=configuration, batch="b2")
        self.assertEqual(dispatched[-1][:3], ("codex", "gpt-5.6-luna", "low"))
        self.assertIn("THIRD PROMPT", dispatched[-1][3])
        self.assertNotIn("REFINEMENT", dispatched[-1][3])
        self.assertEqual(third["regime"]["material"], "unlayered")
        self.assertEqual(staffing.read_session(self.home, self.session), before)
        (path / "milestone/evaluate_candidates.json").unlink()
        _fourth, fallback = self.call(physical, prompt_set="operator", batch="b3",
                                     configuration=dict(self.configuration, rigor={"default": "medium"}))
        self.assertEqual(dispatched[-1][:3], ("codex", "gpt-5.6-terra", "medium"))
        self.assertNotIn("THIRD PROMPT", dispatched[-1][3])
        self.assertEqual(fallback.prompt_set_fallback, "stored_default")
        self.assertEqual(self.evidence()[0][-1]["prompt_set_fallback"], "stored_default")
        records, _ = self.evidence()
        self.assertEqual(len({item["call_context"]["prompt_path"] for item in records}), len(dispatched))
        for record, dispatch in zip(records, dispatched):
            with open(record["call_context"]["prompt_path"], encoding="utf-8") as trace:
                self.assertEqual(trace.read(), dispatch[3])
            self.assertEqual((record["family"], record["model"], record["effort"]), dispatch[:3])
        self.assertEqual(accepted["prompt_path"], records[1]["call_context"]["prompt_path"])

        for _family, _model, _effort, prompt, workspace in dispatched:
            self.assertEqual(workspace, self.workspace)
            self.assertIn("KIND: evaluate_candidates", prompt)
            self.assertIn("ADDITIONAL ROOT /reference — READ-ONLY", prompt)
            self.assertIn("Do not edit files or execute proposals", prompt)
            material_text = prompt.split("IMMUTABLE SEARCH MATERIAL (JSON):\n")[1].splitlines()[0]
            inputs = self.prompt_records(
                prompt,
                "IMMUTABLE COMPOSITIONS AND THEIR EXACT COMPONENTS (JSON):\n",
                "IMMUTABLE COMPOSITIONS TO EVALUATE (JSON):\n",
                "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n",
            )
            problem = {key: self.material[key] for key in (
                "objective", "context_summary", "facts", "constraints", "assumptions",
                "unknowns", "composition_guidance", "criteria", "order_semantics",
            )}
            self.assertEqual(json.loads(material_text), problem)
            self.assertEqual([item["candidate_id"] for item in inputs], list(self.candidates))
            for item in inputs:
                self.assertEqual(set(item), {"candidate_id", "components", "proposal"})
                self.assertEqual({part["dimension_id"]: part["variant_id"] for part in item["components"]},
                                 self.candidates[item["candidate_id"]])
                self.assertEqual(item["proposal"], self.proposals[item["candidate_id"]])
                self.assertTrue(all(part["dimension"] and part["variant"] for part in item["components"]))

    def test_overlapping_batches_retain_their_dispatched_authorities(self):
        self.write_prompt("OLD PROMPT")
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        dispatched = {}

        def physical(family, prompt, _workspace, model=None, effort=None, **_kwargs):
            old = "OLD PROMPT" in prompt
            dispatched[old] = (family, model, effort, prompt)
            if old:
                entered.set()
                self.assertTrue(release.wait(5))
            return self.batch_result(family, prompt, _workspace, model=model, effort=effort)

        with ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(self.call, physical, prompt_set="operator", batch="old")
            self.assertTrue(entered.wait(5))
            self.write_prompt("NEW PROMPT")
            staffing.edit_session(self.home, self.session, {"material": "business", "rigor": "high"})
            new = pool.submit(self.call, physical, prompt_set="operator", batch="new")
            try:
                new_batch, _ = new.result(timeout=5)
                self.assertFalse(old.done())
                self.assertEqual(new_batch["regime"], {
                    "material": "business", "agent": "codex", "model": "gpt-5.6-sol", "effort": "xhigh",
                })
            finally:
                release.set()
            old_batch, _ = old.result(timeout=5)
        self.assertEqual(old_batch["regime"], {
            "material": "default", "agent": "codex", "model": "gpt-5.6-luna", "effort": "low",
        })
        self.assertNotIn("NEW PROMPT", dispatched[True][3])
        self.assertIn("BUSINESS REFINEMENT", dispatched[False][3])
        records, _ = self.evidence()
        by_id = {record["call_id"]: record for record in records}
        for batch in (old_batch, new_batch):
            record = by_id[batch["call_id"]]
            self.assertEqual(record["call_context"]["batch"], batch["batch"])
            self.assertEqual(record["call_context"]["material"], batch["regime"]["material"])
        self.group.ensure_quiescent()

    def test_evaluation_answers_default_and_literature_perspective_checks(self):
        for material_name, expected_ids in (
            ("default", DEFAULT_QUESTION_IDS),
            ("literature", LITERATURE_QUESTION_IDS),
        ):
            with self.subTest(material=material_name):
                staffing.edit_session(self.home, self.session, {"material": material_name})
                accepted, _result = self.call(
                    self.batch_result, batch="questions-" + material_name,
                )
                self.assertEqual(
                    [item["id"] for item in accepted["questions"]], list(expected_ids),
                )

    def test_batch_reply_coverage_and_association(self):
        original = copy.deepcopy(self.candidates)
        accepted, _result = self.call(self.batch_result)
        self.assertEqual(accepted["genomes"], original)
        self.assertEqual(accepted["evaluations"], self.reply["evaluations"])
        self.assertEqual(accepted["generation"], 2)
        self.assertEqual(accepted["batch"], "b1")
        self.assertFalse(accepted["evaluations"][0]["constraint_valid"])
        self.assertEqual(accepted["evaluations"][0]["score"], 0.0)
        self.assertEqual(
            [item["id"] for item in accepted["questions"]], list(DEFAULT_QUESTION_IDS),
        )
        invalid, valid = self.reply["evaluations"]
        rejected = {
            "duplicate": [invalid, valid, valid],
            "missing": [valid],
            "foreign": [invalid, dict(valid, candidate_id="foreign")],
            "violations": [dict(invalid, constraint_violations=["foreign"]), valid],
            "score": [invalid, dict(valid, score=1.1)],
            "rejected_score": [dict(invalid, score=0.1), valid],
        }
        for label, evaluations in rejected.items():
            with self.subTest(label=label):
                calls = []

                def physical(_family, prompt, _workspace, **_kwargs):
                    calls.append(True)
                    reply = evaluations if len(calls) == 1 else self.reply["evaluations"]
                    return self.evaluation_result(prompt, reply)

                corrected, carrier = self.call(physical, batch=label)
                self.assertEqual(len(calls), 2)
                self.assertEqual(corrected["evaluations"], self.reply["evaluations"])
                self.assertEqual(corrected["genomes"], original)
                self.assertEqual(len(carrier.physical_dispatches), 2)
        calls = []

        def malformed(_family, prompt, _workspace, **_kwargs):
            calls.append(True)
            return self.evaluation_result(prompt, [])

        with self.assertRaises(runners.WorkerProtocolError):
            self.call(malformed, batch="exhausted")
        self.assertEqual(len(calls), 2)
        self.assertEqual(accepted["evaluations"], self.reply["evaluations"])
        self.assertEqual(self.candidates, original)

    def test_interchangeable_genomes_reach_evaluator_as_ordered_semantic_components(self):
        semantic = {"format": "a", "channel": "b"}
        candidates = {
            "c-0": {evaluation.creativity_search.ORDER_GENE: 0, **semantic},
            "c-1": {evaluation.creativity_search.ORDER_GENE: 1, **semantic},
        }
        prompts = []

        def physical(_family, prompt, _workspace, **_kwargs):
            prompts.append(prompt)
            return self.batch_result(_family, prompt, _workspace, **_kwargs)

        accepted, _result = self.call(
            physical, candidates=candidates,
            configuration=dict(self.configuration, order_mode="interchangeable"),
        )
        supplied = self.prompt_records(
            prompts[0],
            "IMMUTABLE COMPOSITIONS AND THEIR EXACT COMPONENTS (JSON):\n",
            "IMMUTABLE COMPOSITIONS TO EVALUATE (JSON):\n",
            "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n",
        )
        by_id = {item["candidate_id"]: item["components"] for item in supplied}
        self.assertEqual(
            [component["dimension_id"] for component in by_id["c-0"]],
            ["format", "channel"],
        )
        self.assertEqual(
            [component["dimension_id"] for component in by_id["c-1"]],
            ["channel", "format"],
        )
        self.assertTrue(all(
            component["dimension_id"] != evaluation.creativity_search.ORDER_GENE
            for components in by_id.values() for component in components
        ))
        self.assertIn("exact order", prompts[0])
        self.assertEqual(accepted["genomes"], candidates)
        self.assertNotEqual(
            evaluation.creativity_search.genome_key(candidates["c-0"]),
            evaluation.creativity_search.genome_key(candidates["c-1"]),
        )

    def test_batch_faults_keep_existing_conditions_and_no_retry(self):
        calls = []

        def physical(*_args, **_kwargs):
            calls.append(True)
            raise runners.ProviderResponseError("provider failure")

        with self.assertRaisesRegex(runners.ProviderResponseError, "provider failure"):
            self.call(physical)
        self.assertEqual(len(calls), 1)
        session = staffing.create_session(self.home, session_body(document="matrix", families=[]))["id"]
        with self.assertRaises(staffing.StaffingConditionError) as caught:
            self.call(physical, session=session)
        self.assertEqual(caught.exception.code, "staffing_unavailable")
        self.assertEqual(len(calls), 1)
        records, accounting = self.evidence()
        self.assertEqual(len(records), 1)
        self.assertIn("provider failure", records[0]["error"])
        self.assertTrue(accounting["token_usage_partial"])
        self.assertTrue(accounting["cost_partial"])

    def test_wave_evidence_uses_common_accounting(self):
        self.wave(candidates={"c-0": self.candidates["c-0"]})
        calls = []

        def corrected(*args, **kwargs):
            if "KIND: compose_candidates" in args[1]:
                return self.batch_result(*args, **kwargs)
            calls.append(True)
            if len(calls) == 1:
                staffing.edit_session(self.home, self.session, {"rigor": "high"})
                return self.evaluation_result(args[1], [])
            return self.batch_result(*args, **kwargs)

        handoff = self.wave(corrected)
        self.assertEqual(handoff["accepted_count"], 2)
        sparse = self.creativity_semantics == "sparse_v2"
        self.assertEqual(handoff["unfinished"], [] if sparse else ["c-0"])
        self.assertEqual(handoff["rebaseline_required"], not sparse)
        accepted = self.checkpoint()["evaluation"]["batches"][-1]

        def failed(*_args, **_kwargs):
            result = self.result()
            raise runners.ProviderResponseError(
                "paid failure", token_usage=result.token_usage, cost_payloads=result.cost_payloads,
            )

        pending = {"c-2": {"format": "a", "channel": "a"}}
        with self.assertRaises(runners.ProviderResponseError):
            self.wave(failed, candidates=pending, comparison_ids=list(pending))
        interrupted = runners.ControlledInterruptionResult("", 0, 1.0, "paused by operator")
        handoff = self.wave(lambda *_args, **_kwargs: interrupted,
                            candidates=pending, comparison_ids=list(pending))
        self.assertEqual(handoff["evaluated"], [])
        self.assertIs(handoff["interruption"], interrupted)
        records, accounting = self.evidence()
        self.assertEqual(len(records), 7)
        self.assertEqual(len({record["call_id"] for record in records}), 7)
        self.assertEqual(len({record["call_context"]["batch"] for record in records}), 4)
        self.assertEqual(records[0]["call_context"]["batch"], records[1]["call_context"]["batch"])
        self.assertEqual(len({records[index]["call_context"]["batch"] for index in (2, 3, 4)}), 1)
        self.assertEqual(
            [record["call_context"]["job"] for record in records],
            ["compose_candidates", "evaluate_candidates",
             "compose_candidates", "evaluate_candidates", "evaluate_candidates",
             "compose_candidates", "compose_candidates"],
        )
        self.assertTrue(all(record["call_context"]["generation"] == 2 for record in records))
        self.assertTrue(all(record["completed"] and record["duration_s"] >= 0 for record in records))
        self.assertEqual(accepted["call_id"], records[4]["call_id"])
        self.assertEqual(accepted["regime"]["model"], "gpt-5.6-sol")
        self.assertEqual(records[3]["model"], "gpt-5.6-luna")
        self.assertEqual(accounting["token_usage"]["input_tokens"], 60)
        self.assertEqual(accounting["token_usage"]["output_tokens"], 12)
        expected_cost = sum(pricing.codex_api_cost(record["model"], record["cost_payloads"][0])
                            for record in records[:6])
        self.assertAlmostEqual(accounting["cost"]["api_usd"], expected_cost)
        self.assertTrue(accounting["token_usage_partial"])
        self.assertTrue(accounting["cost_partial"])
        self.wave(candidates={"c-1": self.candidates["c-1"]}, comparison_ids=["c-1"])
        self.assertEqual(self.checkpoint()["evaluation"]["accepted_count"], 2)
        self.assertEqual(self.evidence(), (records, accounting))

    def test_batch_group_controls_reach_overlapping_calls(self):
        for control in ("pause", "stop"):
            with self.subTest(control=control):
                identity, self.group = self._owned_group(self.host, control)
                self.workspace = self.host._active[identity]
                entered = threading.Barrier(3)
                release = threading.Event()
                self.addCleanup(release.set)

                def physical(_family, _prompt, _workspace, active_control=None, **_kwargs):
                    active_control._bind(lambda _text: False, lambda _reason: release.set() or True)
                    try:
                        entered.wait(timeout=5)
                        self.assertTrue(release.wait(5))
                        return runners.ControlledInterruptionResult("", 0, 0.1, control)
                    finally:
                        active_control._close()

                with ThreadPoolExecutor(max_workers=2) as pool:
                    pending = [pool.submit(self.call, physical, batch="b%d" % index) for index in range(2)]
                    entered.wait(timeout=5)
                    with self.assertRaises(ExecutionBusy):
                        self.group.ensure_quiescent()
                    getattr(self.host, control)(identity)
                    for future in pending:
                        accepted, result = future.result(timeout=5)
                        self.assertIsNone(accepted)
                        self.assertEqual(result.interrupt_reason, control)
                self.group.ensure_quiescent()
                with self.assertRaises(runners.RunnerError):
                    self.call(lambda *_args, **_kwargs: self.fail("fenced dispatch ran"))

    def test_wave_bounds_and_candidate_allowance(self):
        candidates = {"c-%s" % index: {"format": format_id, "channel": channel_id}
                      for index, (format_id, channel_id) in enumerate(product(("a", "b"), ("a", "b", "c")))}
        self.host._controls.pop(self.identity)
        self.group = self.host.create_call_group(self.identity, 3)
        for bound in (1, 2, 3):
            with self.subTest(concurrency=bound):
                self.store.put("checkpoint", {"search_material": self.material})
                barrier, release = threading.Barrier(bound), threading.Event()
                calls = []

                def physical(*args, **kwargs):
                    result = self.batch_result(*args, **kwargs)
                    if "KIND: compose_candidates" in args[1]:
                        return result
                    ids = [item["candidate_id"] for item in json.loads(result.text)["evaluations"]]
                    calls.append(ids)
                    barrier.wait(timeout=5)
                    if bound > 1 and "c-0" in ids:
                        self.assertTrue(release.wait(5))
                    else:
                        release.set()
                    return result

                configuration = dict(self.configuration, max_evaluated_candidates=3,
                                     evaluation_concurrency=bound, evaluation_batch_size=1 if bound == 3 else 2)
                handoff = self.wave(physical, candidates=candidates, comparison_ids=list(candidates),
                                    configuration=configuration)
                self.assertEqual(handoff["accepted_count"], min(3, bound * 2))
                if bound == 1:
                    handoff = self.wave(physical, candidates=candidates, comparison_ids=list(candidates),
                                        configuration=configuration)
                self.assertEqual(handoff["accepted_count"], 3)
                self.assertEqual(sorted(map(len, calls)), [1, 1, 1] if bound == 3 else [1, 2])
                self.assertEqual(set(sum(calls, [])), {"c-0", "c-1", "c-2"})
                self.assertFalse(handoff["comparison_ready"])
                before = self.evidence()
                exhausted = self.wave(candidates=candidates, comparison_ids=list(candidates),
                                      configuration=configuration)
                self.assertEqual(exhausted["unfinished"], ["c-3", "c-4", "c-5"])
                self.assertEqual(exhausted["evaluated"], [])
                self.wave(candidates={}, comparison_ids=[])
                self.assertEqual(self.evidence(), before)

    def test_checkpoint_reentry_keeps_accepted_work(self):
        saved, release = threading.Event(), threading.Event()
        put = self.store.put

        def observe(key, value):
            revision = put(key, value)
            if value["evaluation"]["accepted_count"] == 1:
                saved.set()
            return revision

        def physical(*args, **kwargs):
            if '"candidate_id": "c-0"' in args[1]:
                self.assertTrue(release.wait(5))
            return self.batch_result(*args, **kwargs)

        with mock.patch.object(self.store, "put", side_effect=observe), ThreadPoolExecutor(1) as pool:
            future = pool.submit(self.wave, physical)
            try:
                self.assertTrue(saved.wait(5))
                checkpoint = self.checkpoint()
                self.assertEqual(checkpoint["evaluation"]["accepted_count"], 1)
                batch = checkpoint["evaluation"]["batches"][0]
                self.assertEqual(batch["genomes"], {"c-1": self.candidates["c-1"]})
                self.assertEqual(batch["regime"], checkpoint["evaluation"]["regime"])
                self.assertFalse(future.done())
                with self.assertRaises(ExecutionBusy):
                    self.wave()
            finally:
                release.set()
            handoff = future.result(5)
            self.assertTrue(handoff["comparison_ready"])
            survivors = evaluation.creativity_search.select_survivors(handoff["evaluated"], self.configuration)
            self.assertEqual([genome for genome, _item in survivors], [self.candidates["c-0"]])
        self.assertEqual([list(batch["genomes"]) for batch in self.checkpoint()["evaluation"]["batches"]],
                         [["c-1"], ["c-0"]])
        self.assertEqual(self.checkpoint()["search_material"], self.material)
        self.assertEqual(self.checkpoint()["generation"], 2)
        before = self.evidence()
        self.assertEqual(self.wave()["accepted_count"], 2)
        self.assertEqual(self.evidence(), before)

        self.store.put("checkpoint", {"search_material": self.material})
        def interrupted(*args, **kwargs):
            if ("KIND: evaluate_candidates" in args[1]
                    and '"candidate_id": "c-0"' in args[1]):
                return runners.ControlledInterruptionResult("", 0, 0.1, "paused")
            return self.batch_result(*args, **kwargs)

        partial = self.wave(interrupted)
        self.assertEqual(partial["unfinished"], ["c-0"])
        self.assertEqual(partial["interruption"].interrupt_reason, "paused")
        records = len(self.evidence()[0])
        accepted_before = self.checkpoint()["evaluation"]["batches"]
        compositions_before = copy.deepcopy(
            self.checkpoint()["evaluation"]["composition_batches"]
        )
        self.assertEqual(
            {item["candidate_id"] for batch in compositions_before
             for item in batch["compositions"]},
            {"c-0", "c-1"},
        )
        self.assertTrue(all(
            [item["id"] for item in batch["questions"]] == list(DEFAULT_QUESTION_IDS)
            for batch in compositions_before
        ))
        self.store = kvstore.LocalKVClient(self.store.directory)
        if self.creativity_semantics == "sparse_v2":
            staffing.edit_session(self.home, self.session, {"rigor": "high"})
        resumed = self.wave()
        self.assertTrue(resumed["comparison_ready"])
        self.assertEqual(resumed["accepted_count"], 2)
        self.assertEqual(len(self.evidence()[0]), records + 1)
        self.assertEqual(self.checkpoint()["evaluation"]["batches"][:1], accepted_before)
        self.assertEqual(
            self.checkpoint()["evaluation"]["composition_batches"], compositions_before,
        )
        self.assertEqual(self.evidence()[0][-1]["call_context"]["job"], "evaluate_candidates")
        self.assertEqual(
            [item["id"] for item in self.checkpoint()["evaluation"]["batches"][-1]["questions"]],
            list(DEFAULT_QUESTION_IDS),
        )
        self.assertFalse(resumed["rebaseline_required"])

    def test_regime_changes_withhold_comparison(self):
        sparse = self.creativity_semantics == "sparse_v2"
        original_call = evaluation.call_evaluation_batch
        original_put = self.store.put
        for component in ("material", "agent", "model", "effort"):
            with self.subTest(component=component):
                self.store.put("checkpoint", {"search_material": self.material})
                original_document = copy.deepcopy(self.document)
                entered, accepted, release = (threading.Event() for _ in range(3))

                def change(new):
                    document = copy.deepcopy(original_document)
                    if component == "material":
                        staffing.edit_session(self.home, self.session, {"material": "business" if new else "default"})
                    elif component == "agent":
                        document["assignment"]["review"] = {"1": 3, "2": 2} if new else {"1": 2, "2": 3}
                    else:
                        document["tuning"]["low"]["2"]["review"] = (
                            [2, 1] if component == "model" else [1, 2]
                        ) if new else [1, 1]
                    staffing.save(self.home, document)

                def gated(*args, **kwargs):
                    if "c-1" in kwargs["candidates"]:
                        self.assertTrue(entered.wait(5))
                    return original_call(*args, **kwargs)

                def observe(key, value):
                    revision = original_put(key, value)
                    if value["evaluation"]["accepted_count"] == 1:
                        accepted.set()
                    return revision

                def physical(*args, **kwargs):
                    if "KIND: evaluate_candidates" in args[1] and not entered.is_set():
                        change(True)
                        entered.set()
                        self.assertTrue(release.wait(5))
                    return self.batch_result(*args, **kwargs)

                with mock.patch.object(evaluation, "call_evaluation_batch", side_effect=gated), \
                        mock.patch.object(self.store, "put", side_effect=observe), ThreadPoolExecutor(1) as pool:
                    future = pool.submit(self.wave, physical)
                    try:
                        self.assertTrue(accepted.wait(5))
                        self.assertFalse(future.done())
                    finally:
                        release.set()
                    handoff = future.result(5)
                self.assertEqual(handoff["unfinished"], [] if sparse else ["c-0"])
                self.assertEqual(handoff["comparison_ready"], sparse)
                expected = [(self.candidates[item["candidate_id"]], item)
                            for item in reversed(self.reply["evaluations"])] if sparse else []
                self.assertEqual(handoff["evaluated"], expected)
                self.assertEqual(handoff["rebaseline_required"], not sparse)
                batches = self.checkpoint()["evaluation"]["batches"]
                self.assertNotEqual(batches[0]["regime"][component], batches[1]["regime"][component])
                self.store = kvstore.LocalKVClient(self.store.directory)
                original_put = self.store.put
                ready = self.wave(reference_revision=1)
                self.assertTrue(ready["comparison_ready"])
                self.assertEqual(ready["accepted_count"], 2 if sparse else 3)
                self.assertEqual(ready["rebaseline_required"], not sparse)
                # Between waves, evaluator changes invalidate legacy survivors only.
                change(False)
                candidates = dict(self.candidates, **{"c-2": {"format": "a", "channel": "a"}})
                changed = self.wave(candidates=candidates, comparison_ids=list(candidates), reference_revision=2)
                self.assertEqual(changed["unfinished"], [] if sparse else ["c-0", "c-1"])
                self.assertEqual(changed["comparison_ready"], sparse)
                ready = self.wave(candidates=candidates, comparison_ids=list(candidates), reference_revision=2)
                self.assertTrue(ready["comparison_ready"])
                self.assertEqual(ready["accepted_count"], 3 if sparse else 6)
                self.write_prompt("PROMPT ONLY")
                candidates["c-3"] = {"format": "b", "channel": "b"}
                ready = self.wave(candidates=candidates, comparison_ids=list(candidates),
                                  reference_revision=3, prompt_set="operator")
                self.assertTrue(ready["comparison_ready"])
                self.assertFalse(ready["rebaseline_required"])
                self.assertEqual(ready["accepted_count"], 4 if sparse else 7)
                self.assertEqual(self.checkpoint()["evaluation"]["batches"][:2], batches)

    def test_decimal_cumulative_progress_at_threshold(self):
        search = evaluation.creativity_search
        genomes = [{"format": "a", "channel": channel} for channel in ("a", "b", "c")]
        for final_score, expected_progress in (
            (0.42, True),
            (0.41999999999999993, False),
            (0.42000000000000004, True),
        ):
            with self.subTest(final_score=final_score):
                self.configuration = legacy_creativity_configuration(
                    generation_limit=8, max_evaluated_candidates=20,
                    minimum_improvement=0.02, patience_generations=2,
                    order_mode="fixed",
                )
                self.store.put("checkpoint", {"search_material": self.material})
                progress = search.new_progress()
                for generation, (score, genome) in enumerate(zip((0.40, 0.41, final_score), genomes)):
                    self.reply["evaluations"][1]["score"] = score
                    search.begin_generation(progress, {"decimal-%s" % generation: genome}, self.configuration)
                    wave = self.progress_wave(progress)
                    self.assertTrue(wave["comparison_ready"])
                    self.assertFalse(wave["rebaseline_required"])
                    self.assertEqual(wave["regime_revision"], 1)
                    if generation < 2:
                        self.assertEqual(progress["reference_score"], 0.40)
                        self.assertFalse(progress["progress_made"])
                        self.assertEqual(progress["stagnant_generations"], generation)
                        self.assertFalse(progress["window_complete"])
                    if generation == 0:
                        progress.update(consecutive_expansions=1, expansion_interventions=2)

                self.assertEqual(progress["best_score"], final_score)
                self.assertEqual(progress["progress_made"], expected_progress)
                self.assertEqual(progress["reference_score"], final_score if expected_progress else 0.40)
                self.assertEqual(progress["stagnant_generations"], 0 if expected_progress else 2)
                self.assertEqual(progress["consecutive_expansions"], 0 if expected_progress else 1)
                self.assertEqual(progress["window_complete"], not expected_progress)
                self.assertEqual(progress["expansion_interventions"], 2)
                self.assertEqual(progress["generations_completed"], 3)
                self.assertEqual(progress["evaluated_candidates"], 3)

    def test_rebaseline_without_progress_credit(self):
        search = evaluation.creativity_search
        self.configuration = legacy_creativity_configuration(
            generation_limit=10, max_evaluated_candidates=20, minimum_improvement=0.125,
            patience_generations=3, evaluation_batch_size=1, evaluation_concurrency=2,
            order_mode="fixed",
        )
        progress = search.new_progress()
        assessments = {"c-0": (0.25, True), "c-1": (0.125, True),
                       "c-2": (0.5, True), "c-3": (0.8125, True)}
        inputs = []

        def physical(*args, **kwargs):
            if "KIND: compose_candidates" in args[1]:
                return self.batch_result(*args, **kwargs)
            inputs.extend(self.prompt_records(
                args[1],
                "IMMUTABLE COMPOSITIONS AND THEIR EXACT COMPONENTS (JSON):\n",
                "IMMUTABLE COMPOSITIONS TO EVALUATE (JSON):\n",
                "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n",
            ))
            reply = json.loads(self.batch_result(*args, **kwargs).text)
            for item in reply["evaluations"]:
                item["score"], item["constraint_valid"] = assessments[item["candidate_id"]]
                item["constraint_violations"] = [] if item["constraint_valid"] else ["budget"]
                if not item["constraint_valid"]:
                    item["score"] = 0
            return self.result(reply)

        search.begin_generation(progress, self.candidates, self.configuration)
        self.progress_wave(progress, physical)
        self.assertEqual(progress["reference_score"], 0.25)
        self.assertEqual(progress["generations_completed"], 1)
        progress.update(consecutive_expansions=1, expansion_interventions=2)
        search.begin_generation(progress, {"c-2": {"format": "a", "channel": "a"}}, self.configuration)
        staffing.edit_session(self.home, self.session, {"rigor": "high"})
        assessments.update({"c-0": (0.75, True), "c-1": (0.9375, False)})
        changed = self.progress_wave(progress, physical)
        self.assertTrue(changed["rebaseline_required"])
        self.assertEqual(progress["archive"], [])
        self.assertIsNone(progress["best_score"])
        self.assertIsNone(progress["reference_score"])
        self.assertEqual(progress["generations_completed"], 1)
        self.assertEqual(search.progress_evaluation_request(progress)["candidates"], self.candidates)

        self.progress_wave(progress, physical)
        self.assertEqual(progress["reference_score"], 0.75)
        self.assertEqual(progress["stagnant_generations"], 0)
        self.assertFalse(progress["progress_made"])
        self.assertEqual(progress["consecutive_expansions"], 1)
        self.assertEqual(progress["expansion_interventions"], 2)
        self.assertEqual(progress["generations_completed"], 1)
        self.assertEqual(progress["evaluated_candidates"], 5)
        self.assertEqual([item["candidate_id"] for _, item in progress["archive"]], ["c-0"])
        self.assertNotIn("c-1", search.progress_evaluation_request(progress)["comparison_ids"])
        before = self.evidence()
        self.progress_wave(progress, physical)
        self.assertEqual(self.evidence(), before)
        self.assertEqual(progress["generations_completed"], 2)
        self.assertEqual(progress["stagnant_generations"], 1)
        self.assertFalse(progress["progress_made"])

        self.write_prompt("PROMPT ONLY")
        search.begin_generation(progress, {"c-3": {"format": "b", "channel": "b"}}, self.configuration)
        ready = self.progress_wave(progress, physical, prompt_set="operator")
        self.assertFalse(ready["rebaseline_required"])
        self.assertEqual(progress["best_score"], 0.8125)
        self.assertEqual(progress["reference_score"], 0.75)
        self.assertEqual(progress["generations_completed"], 3)
        self.assertEqual(progress["evaluated_candidates"], 6)
        self.assertEqual(progress["consecutive_expansions"], 1)
        for item in inputs:
            self.assertEqual(set(item), {"candidate_id", "components", "proposal"})

    def test_progress_rebaseline_ignores_late_old_regime_completion(self):
        search = evaluation.creativity_search
        self.configuration = legacy_creativity_configuration(
            generation_limit=10, max_evaluated_candidates=20, minimum_improvement=0.125,
            patience_generations=3, evaluation_batch_size=1, evaluation_concurrency=2,
            order_mode="fixed",
        )
        progress = search.new_progress()
        search.begin_generation(progress, self.candidates, self.configuration)
        self.progress_wave(progress)
        search.begin_generation(progress, {
            "c-2": {"format": "a", "channel": "a"},
            "c-3": {"format": "b", "channel": "b"},
        }, self.configuration)
        entered, accepted, release = (threading.Event() for _ in range(3))
        self.addCleanup(release.set)
        original_call, original_put = evaluation.call_evaluation_batch, self.store.put

        def gated(*args, **kwargs):
            if "c-3" in kwargs["candidates"]:
                self.assertTrue(entered.wait(5))
            return original_call(*args, **kwargs)

        def observe(key, value):
            revision = original_put(key, value)
            if value["evaluation"]["accepted_count"] == 3:
                accepted.set()
            return revision

        def physical(*args, **kwargs):
            if ("KIND: evaluate_candidates" in args[1]
                    and '"candidate_id": "c-2"' in args[1] and not entered.is_set()):
                staffing.edit_session(self.home, self.session, {"rigor": "high"})
                entered.set()
                self.assertTrue(release.wait(5))
            return self.batch_result(*args, **kwargs)

        with mock.patch.object(evaluation, "call_evaluation_batch", side_effect=gated), \
                mock.patch.object(self.store, "put", side_effect=observe), ThreadPoolExecutor(1) as pool:
            future = pool.submit(self.progress_wave, progress, physical)
            try:
                self.assertTrue(accepted.wait(5))
                self.assertFalse(future.done())
            finally:
                release.set()
            changed = future.result(5)
        self.assertEqual(set(changed["unfinished"]), {"c-0", "c-2"})
        self.assertEqual(progress["archive"], [])
        request = search.progress_evaluation_request(progress)
        self.assertEqual(request["candidates"], {"c-0": self.candidates["c-0"]})
        self.progress_wave(progress)
        self.assertEqual(progress["generations_completed"], 1)
        self.assertFalse(progress["progress_made"])
        ready = self.progress_wave(progress)
        self.assertTrue(ready["comparison_ready"])
        self.assertEqual(progress["generations_completed"], 2)
        self.assertEqual(progress["evaluated_candidates"], 6)
        records, _ = self.evidence()
        self.assertEqual([record["call_context"]["generation"] for record in records].count(2), 6)

    def test_progress_limits_and_interrupted_reassessment(self):
        search = evaluation.creativity_search
        self.configuration = legacy_creativity_configuration(
            generation_limit=1, max_evaluated_candidates=20, order_mode="fixed",
        )
        progress = search.new_progress()
        search.begin_generation(progress, self.candidates, self.configuration)
        self.progress_wave(progress)
        self.assertEqual(progress["stop_reason"], "generation_limit")
        self.assertEqual(progress["generations_completed"], 1)
        self.assertEqual(progress["evaluated_candidates"], 2)
        before = self.evidence()
        search.begin_generation(progress, {"c-2": {"format": "a", "channel": "a"}}, self.configuration)
        self.assertIsNone(self.progress_wave(progress))
        self.assertEqual(self.evidence(), before)

        self.store.put("checkpoint", {"search_material": self.material})
        self.configuration = dict(self.configuration, generation_limit=10, max_evaluated_candidates=3)
        progress = search.new_progress()
        search.begin_generation(progress, self.candidates, self.configuration)
        self.progress_wave(progress)
        search.begin_generation(progress, {"c-2": {"format": "a", "channel": "a"}}, self.configuration)
        staffing.edit_session(self.home, self.session, {"rigor": "high"})
        interrupted = runners.ControlledInterruptionResult("", 0, 0.1, "paused")

        def interrupt_evaluator(*args, **kwargs):
            if "KIND: compose_candidates" in args[1]:
                return self.batch_result(*args, **kwargs)
            return interrupted

        wave = self.progress_wave(progress, interrupt_evaluator)
        self.assertIs(wave["interruption"], interrupted)
        self.assertIsNone(progress["stop_reason"])
        self.assertEqual(progress["archive"], [])
        self.assertEqual(progress["evaluated_candidates"], 2)
        # Explicitly complete the survivor reassessment, spending the last place.
        self.progress_wave(progress)
        self.assertEqual(progress["reference_score"], 0.4)
        self.assertEqual(progress["generations_completed"], 1)
        before = self.evidence()
        self.progress_wave(progress)
        self.assertEqual(progress["stop_reason"], "evaluation_budget")
        self.assertEqual(progress["evaluated_candidates"], 3)
        self.assertEqual(progress["generations_completed"], 1)
        self.assertIsNone(self.progress_wave(progress))
        self.assertEqual(self.evidence(), before)

    def test_progress_budget_stops_incomplete_rebaseline(self):
        search = evaluation.creativity_search
        self.configuration = legacy_creativity_configuration(
            generation_limit=10, max_evaluated_candidates=4,
            evaluation_batch_size=1, evaluation_concurrency=2,
            order_mode="fixed",
        )
        for item in self.reply["evaluations"]:
            item.update(score=0.25, constraint_valid=True, constraint_violations=[])
        progress = search.new_progress()
        search.begin_generation(progress, self.candidates, self.configuration)
        self.progress_wave(progress)
        self.assertEqual(len(progress["archive"]), 2)
        search.begin_generation(progress, {"c-2": {"format": "a", "channel": "a"}}, self.configuration)
        staffing.edit_session(self.home, self.session, {"rigor": "high"})
        self.progress_wave(progress)
        self.assertEqual(progress["evaluated_candidates"], 3)
        self.assertEqual(search.progress_evaluation_request(progress)["candidates"], self.candidates)
        wave = self.progress_wave(progress)
        self.assertFalse(wave["comparison_ready"])
        self.assertEqual(len(wave["unfinished"]), 1)
        self.assertEqual(progress["stop_reason"], "evaluation_budget")
        self.assertEqual(progress["evaluated_candidates"], 4)
        self.assertEqual(progress["generations_completed"], 1)
        self.assertEqual(progress["archive"], [])
        self.assertIsNone(progress["reference_score"])
        before = self.evidence()
        self.assertIsNone(self.progress_wave(progress))
        self.assertEqual(self.evidence(), before)

    def test_wave_faults_keep_accepted_siblings_and_checkpoint_failure_is_unfinished(self):
        def malformed(*args, **kwargs):
            if ("KIND: evaluate_candidates" in args[1]
                    and '"candidate_id": "c-1"' in args[1]):
                return self.evaluation_result(args[1], [])
            return self.batch_result(*args, **kwargs)

        with self.assertRaises(runners.WorkerProtocolError):
            self.wave(malformed)
        self.assertEqual(self.checkpoint()["evaluation"]["accepted_count"], 1)
        self.assertEqual(len(self.evidence()[0]), 5)
        before = self.checkpoint()
        put = self.store.put

        def failed_write(key, value):
            if value["evaluation"]["accepted_count"] > 1:
                raise OSError("checkpoint write failed")
            return put(key, value)

        with mock.patch.object(self.store, "put", side_effect=failed_write):
            with self.assertRaisesRegex(OSError, "checkpoint write failed"):
                self.wave()
        self.assertEqual(self.checkpoint(), before)
        self.assertEqual(len(self.evidence()[0]), 6)
        session = staffing.create_session(self.home, session_body(document="matrix", families=[]))["id"]
        with self.assertRaises(staffing.StaffingConditionError) as caught:
            self.wave(session=session)
        self.assertEqual(caught.exception.code, "staffing_unavailable")
        self.assertEqual(self.checkpoint(), before)
        self.assertEqual(len(self.evidence()[0]), 6)
        self.assertEqual(self.wave()["accepted_count"], 2)

    def test_wave_uses_task_controls_and_surfaces_faults(self):
        for control, repair in product(("pause", "stop"), (False, True)):
            with self.subTest(control=control, repair=repair):
                identity, self.group = self._owned_group(self.host, "wave-%s-%s" % (control, repair))
                self.workspace = self.host._active[identity]
                self.store.put("checkpoint", {"search_material": self.material})
                self.wave(candidates={"c-0": self.candidates["c-0"]})
                entered, release = threading.Barrier(3), threading.Event()
                candidates = dict(self.candidates, **{"c-2": {"format": "a", "channel": "a"}})
                calls = []

                def physical(_family, prompt, _workspace, active_control=None, **_kwargs):
                    if "KIND: compose_candidates" in prompt:
                        return self.batch_result(_family, prompt, _workspace, **_kwargs)
                    calls.append(prompt)
                    active_control._bind(lambda _text: False, lambda _reason: release.set() or True)
                    try:
                        entered.wait(timeout=5)
                        self.assertTrue(release.wait(5))
                        if repair and '"candidate_id": "c-1"' in prompt:
                            return self.result({"evaluations": []})
                        return runners.ControlledInterruptionResult("", 0, 0.1, control)
                    finally:
                        active_control._close()

                with ThreadPoolExecutor(1) as pool:
                    future = pool.submit(self.wave, physical, candidates=candidates, comparison_ids=list(candidates))
                    entered.wait(timeout=5)
                    getattr(self.host, control)(identity)
                    if repair:
                        with self.assertRaises(runners.RunnerError):
                            future.result(5)
                    else:
                        handoff = future.result(5)
                        self.assertEqual(handoff["unfinished"], ["c-1", "c-2"])
                        self.assertEqual(handoff["interruption"].interrupt_reason, control)
                self.assertEqual(len(calls), 2)
                self.assertEqual(self.checkpoint()["evaluation"]["accepted_count"], 1)
                with self.assertRaises(runners.RunnerError):
                    self.wave(lambda *_args, **_kwargs: self.fail("fenced wave dispatched"))
                self.group.ensure_quiescent()


class SparseCreativityEvaluationTest(CreativityEvaluationFixture):
    creativity_semantics = "sparse_v2"

    def setUp(self):
        super().setUp()
        self.material = dict(self.material, dimensions=[
            {"id": item["id"], "meaning": item["meaning"]} for item in self.material["dimensions"]
        ], variants=[{"id": key, "text": "Action " + key} for key in ("a", "b", "c")])
        self.store.put("checkpoint", {"search_material": self.material, "generation": 2})

    def test_sparse_evaluation_falls_back_from_legacy_named_prompt(self):
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        evaluator = documents["milestone/evaluate_candidates.json"]
        semantics = next(
            part for part in evaluator["instructions"]["parts"]
            if any(variable["name"] == "creativity_semantics"
                   for variable in part.get("variables", []))
        )
        semantics["text"] = [
            "STALE EVALUATOR PROMPT",
            "Each candidate combines one variant per dimension.",
        ]
        semantics["variables"] = []
        router_fixture.PromptRouterTest.write_set(
            self.home, "legacy-operator", documents,
        )
        prompts = []

        def physical(*args, **kwargs):
            prompts.append(args[1])
            return self.batch_result(*args, **kwargs)

        _accepted, result = self.call(
            physical, prompt_set="legacy-operator",
        )

        self.assertEqual(len(prompts), 1)
        self.assertIn("SAVED MATERIAL SEMANTICS: sparse_v2", prompts[0])
        self.assertNotIn("STALE EVALUATOR PROMPT", prompts[0])
        self.assertEqual(result.prompt_set_fallback, "stored_default")

    # Explicit entry points distinguish sparse fixtures in the suite inventory
    # while reusing the same host, router, correction and checkpoint scenarios.
    def test_sparse_evaluation_provenance(self):
        CreativityEvaluationTest.test_each_attempt_reads_live_authorities(self)

    def test_sparse_evaluation_configuration_continuity(self):
        CreativityEvaluationTest.test_regime_changes_withhold_comparison(self)

    def test_wave_bounds_and_candidate_allowance(self):
        CreativityEvaluationTest.test_wave_bounds_and_candidate_allowance(self)

    def test_checkpoint_reentry_keeps_accepted_work(self):
        CreativityEvaluationTest.test_checkpoint_reentry_keeps_accepted_work(self)

    def test_wave_evidence_uses_common_accounting(self):
        CreativityEvaluationTest.test_wave_evidence_uses_common_accounting(self)

    def test_wave_uses_task_controls_and_surfaces_faults(self):
        CreativityEvaluationTest.test_wave_uses_task_controls_and_surfaces_faults(self)

    def test_batch_faults_keep_existing_conditions_and_no_retry(self):
        CreativityEvaluationTest.test_batch_faults_keep_existing_conditions_and_no_retry(self)

    def test_sparse_progress_resume_preserves_scored_work(self):
        search = evaluation.creativity_search
        self.configuration = dict(
            self.configuration, order_mode="interchangeable", generation_limit=2,
            max_evaluated_candidates=3, evaluation_batch_size=1, evaluation_concurrency=2,
        )
        self.candidates = {
            "c-0": {"format": "a", "channel": search.OMIT, "__order__": 1},
            "c-1": {"format": "b", "channel": "a", "__order__": 1},
        }
        original_candidates, original_material = copy.deepcopy((self.candidates, self.material))
        progress = search.new_progress()
        search.begin_generation(progress, self.candidates, self.configuration,
                                creativity_semantics="sparse_v2")
        calls, interrupt = [], True

        def physical(*args, **kwargs):
            if "KIND: compose_candidates" in args[1]:
                return self.batch_result(*args, **kwargs)
            sent = self.prompt_records(
                args[1],
                "IMMUTABLE COMPOSITIONS AND THEIR EXACT COMPONENTS (JSON):\n",
                "IMMUTABLE COMPOSITIONS TO EVALUATE (JSON):\n",
                "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n",
            )
            calls.extend(sent)
            if interrupt and sent[0]["candidate_id"] == "c-0":
                return runners.ControlledInterruptionResult("", 0, 0.1, "paused")
            return self.batch_result(*args, **kwargs)

        partial = self.progress_wave(progress, physical)
        self.assertEqual(partial["interruption"].interrupt_reason, "paused")
        self.assertEqual(progress["evaluated_candidates"], 1)
        self.assertEqual(progress["generations_completed"], 0)
        self.assertEqual(progress["pending"]["unfinished"], ["c-0"])
        self.assertIsNone(progress["stop_reason"])
        accepted = copy.deepcopy(self.checkpoint()["evaluation"]["batches"])

        def reopen():
            checkpoint = self.checkpoint()
            # Use the task owner's existing JSON representation of pairs.
            progress["archive"] = [list(pair) for pair in progress["archive"]]
            checkpoint.update(progress=progress, candidates=self.candidates)
            self.store.put("checkpoint", checkpoint)
            self.store = kvstore.LocalKVClient(self.store.directory)
            return self.checkpoint()["progress"]

        progress = reopen()
        interrupt = False
        staffing.edit_session(self.home, self.session, {"rigor": "high"})
        self.write_prompt("UPDATED SPARSE EVALUATOR")
        resumed = self.progress_wave(progress, physical, prompt_set="operator")
        self.assertFalse(resumed["rebaseline_required"])
        self.assertTrue(resumed["comparison_ready"])
        self.assertEqual(progress["evaluated_candidates"], 2)
        self.assertEqual(progress["generations_completed"], 1)
        self.assertEqual(progress["best_score"], 0.4)
        self.assertTrue(progress["archive"][0][1]["constraint_valid"])
        self.assertEqual([g for g, _ in progress["archive"]],
                         [self.candidates["c-0"]])
        self.assertEqual(self.checkpoint()["evaluation"]["batches"][:1], accepted)
        batches = self.checkpoint()["evaluation"]["batches"]
        self.assertNotEqual(batches[0]["regime"], batches[1]["regime"])
        for index, batch in enumerate(batches):
            with open(batch["prompt_path"], encoding="utf-8") as trace:
                self.assertEqual("UPDATED SPARSE EVALUATOR" in trace.read(), index == 1)

        progress = reopen()
        completed = copy.deepcopy(progress)
        before = self.evidence()
        self.assertIsNone(self.progress_wave(progress, physical, prompt_set="operator"))
        self.assertEqual(progress, completed)
        self.assertEqual(self.evidence(), before)
        fresh = {"c-2": {"format": search.OMIT, "channel": "c", "__order__": 0}}
        search.begin_generation(progress, fresh, self.configuration, creativity_semantics="sparse_v2")
        self.candidates.update(fresh)
        progress = reopen()
        self.assertIn("c-0", search.progress_evaluation_request(progress)["comparison_ids"])
        self.progress_wave(progress, physical, prompt_set="operator")
        self.assertEqual(progress["stop_reason"], "generation_limit")
        self.assertEqual(progress["generations_completed"], 2)
        self.assertEqual(progress["evaluated_candidates"], 3)
        accepted_by_id = {
            item["candidate_id"]: item
            for batch in self.checkpoint()["evaluation"]["batches"]
            for item in batch["evaluations"]
        }
        self.assertEqual(progress["archive"][0][1], accepted_by_id["c-0"])
        self.assertEqual(sorted(item["candidate_id"] for item in calls), ["c-0", "c-0", "c-1", "c-2"])
        expected_seeds = {
            "c-0": [("format", "a")], "c-1": [("channel", "a"), ("format", "b")],
            "c-2": [("channel", "c")],
        }
        for item in calls:
            self.assertEqual([(c["dimension_id"], c["variant_id"]) for c in item["components"]],
                             expected_seeds[item["candidate_id"]])
        self.assertEqual(self.checkpoint()["evaluation"]["batches"][:1], accepted)
        self.assertEqual(self.checkpoint()["search_material"], original_material)
        self.assertEqual(self.checkpoint()["candidates"], dict(original_candidates, **fresh))
        self.assertEqual(progress["expansion_interventions"], 0)
        self.assertIsNone(progress["reference_score"])

    def test_sparse_progress_budget_keeps_unfinished_work(self):
        search = evaluation.creativity_search
        self.configuration = dict(self.configuration, generation_limit=5, max_evaluated_candidates=3)
        progress = search.new_progress()
        search.begin_generation(progress, self.candidates, self.configuration, creativity_semantics="sparse_v2")
        self.progress_wave(progress)
        retained = copy.deepcopy(progress["archive"])
        accepted = copy.deepcopy(self.checkpoint()["evaluation"]["batches"])
        fresh = {
            "c-2": {"format": search.OMIT, "channel": "c"},
            "c-3": {"format": "b", "channel": search.OMIT},
        }
        search.begin_generation(progress, fresh, self.configuration, creativity_semantics="sparse_v2")
        wave = self.progress_wave(progress)
        self.assertFalse(wave["comparison_ready"])
        self.assertEqual(progress["stop_reason"], "evaluation_budget")
        self.assertEqual(progress["generations_completed"], 1)
        self.assertEqual(progress["evaluated_candidates"], 3)
        self.assertEqual(progress["pending"]["unfinished"], ["c-3"])
        self.assertEqual(progress["archive"], retained)
        batches = self.checkpoint()["evaluation"]["batches"]
        self.assertEqual(batches[:1], accepted)
        self.assertEqual(batches[1]["genomes"], {"c-2": fresh["c-2"]})
        self.assertEqual(batches[1]["evaluations"][0]["candidate_id"], "c-2")
        self.assertEqual(batches[1]["evaluations"][0]["score"], 0.4)
        before = self.evidence()
        self.assertIsNone(self.progress_wave(progress))
        self.assertEqual(self.evidence(), before)

    def test_sparse_evaluation_input(self):
        material = self.source.sparse_material(10, 3)
        original = copy.deepcopy(material)
        problem = dict(material)
        problem.pop("dimensions")
        problem.pop("variants")
        pairs = [
            {"dimension_id": "d1", "dimension": "Focus 1", "variant_id": "v1", "variant": "Action 1"},
            {"dimension_id": "d4", "dimension": "Focus 4", "variant_id": "v2", "variant": "Action 2"},
            {"dimension_id": "d8", "dimension": "Focus 8", "variant_id": "v0", "variant": "Action 0"},
        ]
        for mode in ("fixed", "interchangeable"):
            with self.subTest(order_mode=mode):
                genome = {item["id"]: evaluation.creativity_search.OMIT for item in material["dimensions"]}
                genome.update(d1="v1", d4="v2", d8="v0")
                if mode == "interchangeable":
                    ids = list(genome)
                    genome["__order__"] = evaluation.creativity_search.rank_order(ids, ids[::-1])
                candidates, prompts = {"c-0": genome}, []

                def physical(*args, **kwargs):
                    prompts.append(args[1])
                    return self.batch_result(*args, **kwargs)

                accepted, _ = self.call(physical, search_material=material, candidates=candidates,
                                        configuration=dict(self.configuration, order_mode=mode))
                sent_material = prompts[0].split("IMMUTABLE SEARCH MATERIAL (JSON):\n")[1]
                sent_candidates = self.prompt_records(
                    prompts[0],
                    "IMMUTABLE COMPOSITIONS AND THEIR EXACT COMPONENTS (JSON):\n",
                    "IMMUTABLE COMPOSITIONS TO EVALUATE (JSON):\n",
                    "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n",
                )
                self.assertEqual(json.loads(sent_material.splitlines()[0]), problem)
                self.assertEqual(sent_candidates, [{
                    "candidate_id": "c-0", "components": pairs if mode == "fixed" else pairs[::-1],
                    "proposal": self.proposals["c-0"],
                }])
                self.assertEqual(accepted["genomes"], candidates)
                self.assertEqual(material, original)

    def test_sparse_evaluation_diagnostics(self):
        self.proposals["c-0"] = "Apply the actions sequentially to the same resource."
        self.reply["evaluations"][1].update(
            score=0, proposal=self.proposals["c-0"],
            reason="The actions undo each other, so the complete proposal is incoherent.",
            assumptions=["The resource survives the first action."],
        )
        expected = [(self.candidates[item["candidate_id"]], item)
                    for item in reversed(self.reply["evaluations"])]
        for batch_size in (2, 1):
            with self.subTest(batch_size=batch_size):
                self.store.put("checkpoint", {"search_material": self.material})
                handoff = self.wave(configuration=dict(
                    self.configuration, evaluation_batch_size=batch_size, evaluation_concurrency=1,
                ))
                if batch_size == 1:
                    handoff = self.wave()
                self.assertTrue(handoff["comparison_ready"])
                self.assertEqual(handoff["evaluated"], expected)
                self.assertEqual(handoff["accepted_count"], 2)
                batches = self.checkpoint()["evaluation"]["batches"]
                if batch_size == 2:
                    self.assertEqual(batches[0]["evaluations"], self.reply["evaluations"])
                self.assertEqual({item["candidate_id"]: item for batch in batches for item in batch["evaluations"]},
                                 {item["candidate_id"]: item for _, item in expected})
