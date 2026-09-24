"""New fragment orders through the real host with scripted model responses.

These tests establish transport, validation and persistence. Scripted proposals
and scores do not establish the literary or engineering quality of a model.
"""

import copy
import json
import unittest
from unittest import mock

from orchestrator import creativity_search, task_api
from orchestrator.tests import test_creativity_task as fixture


class FragmentCreativityTaskTest(unittest.TestCase):
    creativity_semantics = "fragments_v3"
    order = fixture.CreativityTaskTest.order
    admit = fixture.CreativityTaskTest.admit
    host = fixture.CreativityTaskTest.host
    config = staticmethod(fixture.CreativityTaskTest.config)
    checkpoint = fixture.CreativityTaskTest.checkpoint
    question_answers = staticmethod(fixture.CreativityTaskTest.question_answers)
    physical = fixture.CreativityTaskTest.physical
    result = fixture.CreativityTaskTest.result
    _wait = fixture.CreativityTaskTest._wait
    _paused = fixture.CreativityTaskTest._paused
    _terminal = fixture.CreativityTaskTest._terminal

    def setUp(self):
        fixture.CreativityTaskTest.setUp(self)
        self.fragments = ["casa", "roja", "limpiar", "Firebase"]

    def _run(self, record, physical=None):
        self.assertEqual(record["order"]["creativity_semantics"], "fragments_v3")
        host = self.host(physical)
        host.start(record, self.config)
        terminal = self._terminal(host, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal["result"])
        return terminal

    def _job_calls(self, job):
        return [call for call in self.calls if call["job"] == job]

    @staticmethod
    def _prompt_material(call):
        return json.loads(call["prompt"].split(
            "IMMUTABLE SEARCH MATERIAL (JSON):\n", 1,
        )[1].splitlines()[0])

    def test_generated_count_preserves_brief_context_and_reference_order(self):
        fragments = list(self.fragments)
        for count in (3, 4):
            with self.subTest(gene_count=count):
                self.calls.clear()
                self.fragments = fragments[:count]
                brief = "Propón un acceso al terminal respetando el contexto."
                context = {"canon": ["Manipula el terminal"], "creative_freedom": True}
                order = self.order(
                    "creativity", request=brief, context=copy.deepcopy(context),
                    reference_documents=list(self.references),
                )
                order.update(
                    staffing_session=self.session,
                    configuration={"gene_count": count, "generation_limit": 1},
                )
                record = task_api.StandaloneTaskStore(self.home).admit(order, {}, self.primary)
                order["request"]["context"]["canon"].append("Later caller mutation")
                terminal = self._run(record)
                material = self.checkpoint(record)["search_material"]
                self.assertEqual(material["objective"], brief)
                self.assertEqual([item["meaning"] for item in material["dimensions"]], self.fragments)
                self.assertEqual(material["variants"], [
                    {"id": "affirmed", "text": "Include"},
                    {"id": "negated", "text": "Exclude"},
                ])
                creation = self._job_calls("create_genes")
                self.assertEqual(len(creation), 1)
                self.assertIn("return exactly %d distinct fragments" % count, creation[0]["prompt"])
                self.assertIn(brief, creation[0]["prompt"])
                self.assertIn(json.dumps(self.references, ensure_ascii=False), creation[0]["prompt"])
                for job in ("compose_candidates", "evaluate_candidates"):
                    calls = self._job_calls(job)
                    self.assertTrue(calls)
                    for call in calls:
                        received = self._prompt_material(call)
                        self.assertEqual(received["objective"], brief)
                        self.assertEqual(json.loads(received["context_summary"]), {
                            "context": context, "reference_documents": self.references,
                        })
                self.assertNotIn("expand_genes", [call["job"] for call in self.calls])
                self.assertEqual(terminal["order"]["configuration"]["gene_count"], count)

    def test_initial_fragments_skip_generator_in_both_order_modes(self):
        for mode in ("fixed", "interchangeable"):
            with self.subTest(order_mode=mode):
                self.calls.clear()
                record = self.admit(
                    supplied=True, gene_count=len(self.fragments), order_mode=mode,
                )
                terminal = self._run(record)
                self.assertEqual(self._job_calls("create_genes"), [])
                self.assertEqual({call["job"] for call in self.calls}, {
                    "compose_candidates", "evaluate_candidates",
                })
                self.assertEqual(
                    [item["meaning"] for item in self.checkpoint(record)["search_material"]["dimensions"]],
                    self.fragments,
                )
                view = task_api.creativity_view(self.home, terminal)
                self.assertTrue(view["initial_genes_supplied"])
                self.assertNotIn("create_genes", view["diligence"])

    def test_negation_order_and_omission_cross_both_call_boundaries(self):
        record = self.admit(
            supplied=True, gene_count=4, order_mode="interchangeable",
        )
        ids = ["fragment_%02d" % index for index in range(1, 5)]
        genomes = [
            dict(zip(ids, ("affirmed", "negated", creativity_search.OMIT, "affirmed")),
                 __order__=0),
            dict(zip(ids, ("affirmed", creativity_search.OMIT, "affirmed", "negated")),
                 __order__=creativity_search.rank_order(ids, list(reversed(ids)))),
        ]
        # Supply deterministic seeds at the population boundary. The host, real
        # component projection, routers, validators and storage remain in use.
        with mock.patch.object(creativity_search, "make_population", return_value=genomes):
            terminal = self._run(record)
        expected = [
            [("casa", "affirmed"), ("roja", "negated"), ("Firebase", "affirmed")],
            [("Firebase", "negated"), ("limpiar", "affirmed"), ("casa", "affirmed")],
        ]
        composed = [item for call in self._job_calls("compose_candidates") for item in call["candidates"]]
        evaluated = {item["candidate_id"]: item
                     for call in self._job_calls("evaluate_candidates")
                     for item in call["compositions"]}
        self.assertEqual(len(composed), 2)
        self.assertEqual(
            {tuple((item["dimension"], item["variant_id"])
                   for item in candidate["components"]) for candidate in composed},
            {tuple(sequence) for sequence in expected},
        )
        for candidate in composed:
            self.assertEqual(evaluated[candidate["candidate_id"]]["components"], candidate["components"])
            self.assertNotIn(creativity_search.OMIT, json.dumps(candidate["components"]))
        for proposal in terminal["result"]["native_result"]["proposals"]:
            self.assertEqual(proposal["components"], evaluated[proposal["candidate_id"]]["components"])
            self.assertEqual(proposal["proposal"], self.compositions[proposal["candidate_id"]])

    def test_rejected_assessments_remain_visible_and_never_enter_shortlist(self):
        for all_rejected in (False, True):
            with self.subTest(all_rejected=all_rejected):
                self.calls.clear()
                assessments = []

                def physical(*args, **kwargs):
                    result = self.physical(*args, **kwargs)
                    if "KIND: evaluate_candidates" not in args[1]:
                        return result
                    reply = json.loads(result.text)
                    for item in reply["evaluations"]:
                        reject = all_rejected or not assessments
                        item.update(
                            constraint_valid=not reject,
                            constraint_violations=["__objective__"] if reject else [],
                            score=0 if reject else 0.8,
                        )
                        assessments.append(copy.deepcopy(item))
                    return self.result(reply)

                record = self.admit(supplied=True, gene_count=4)
                terminal = self._run(record, physical)
                native = terminal["result"]["native_result"]
                view = task_api.creativity_view(self.home, terminal)
                self.assertEqual(len(view["candidate_evaluations"]), 2)
                self.assertEqual(
                    [{key: item[key] for key in assessments[0]}
                     for item in view["candidate_evaluations"]], assessments,
                )
                expected_ids = {item["candidate_id"] for item in assessments if item["constraint_valid"]}
                self.assertEqual({item["candidate_id"] for item in native["proposals"]}, expected_ids)
                self.assertEqual(view["best_candidates"], native["proposals"])
                self.assertEqual(native["outcome"], "no_valid_candidates" if all_rejected else "proposals")

    def test_evaluator_rewrite_is_rejected_and_resume_reuses_saved_compositions(self):
        record = self.admit(supplied=True, gene_count=4)

        def rewriting_evaluator(*args, **kwargs):
            result = self.physical(*args, **kwargs)
            if "KIND: evaluate_candidates" in args[1]:
                reply = json.loads(result.text)
                for item in reply["evaluations"]:
                    item["proposal"] = "Evaluator tried to replace the composition."
                return self.result(reply)
            return result

        host = self.host(rewriting_evaluator)
        host.start(record, self.config)
        paused = self._paused(host, record["id"])
        self.assertEqual(paused["source"], "error")
        before = self.checkpoint(record)
        saved = copy.deepcopy(before["evaluation"]["composition_batches"])
        self.assertTrue(saved)
        self.assertEqual(before["evaluation"]["batches"], [])
        self.assertIsNone(before["native_result"])
        composition_calls = copy.deepcopy(self._job_calls("compose_candidates"))
        previous_count = len(self.calls)

        fresh = self.host()
        fresh.adopt_open_tasks(lambda _record: self.config)
        paused = self._paused(fresh, record["id"])
        fresh.resume(record["id"], self.config, paused["revision"])
        terminal = self._terminal(fresh, record["id"])
        self.assertEqual(terminal["result"]["status"], "success", terminal["result"])
        self.assertEqual(self._job_calls("compose_candidates"), composition_calls)
        self.assertEqual(self.checkpoint(record)["evaluation"]["composition_batches"], saved)
        self.assertEqual({call["job"] for call in self.calls[previous_count:]}, {"evaluate_candidates"})
        for item in terminal["result"]["native_result"]["proposals"]:
            self.assertEqual(item["proposal"], self.compositions[item["candidate_id"]])


if __name__ == "__main__":
    unittest.main()
