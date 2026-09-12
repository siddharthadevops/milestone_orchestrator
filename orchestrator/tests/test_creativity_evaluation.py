"""Evaluation integration through live routers and host-owned call groups."""

import copy
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from orchestrator import creativity_evaluation as evaluation
from orchestrator import pricing, prompt_sets, runners, staffing, task_api, tasks
from orchestrator.task_execution import ExecutionBusy
from orchestrator.tests import test_creativity_search as search_fixture
from orchestrator.tests import test_prompt_router as router_fixture
from orchestrator.tests import test_task_call_group as group_fixture
from orchestrator.tests.test_staffing_sessions import resolver_doc, session_body
from orchestrator.tests.test_tasks import creativity_configuration


class CreativityEvaluationTest(unittest.TestCase):
    order = group_fixture.TaskCallGroupControlTests.order
    _owned_group = group_fixture.TaskCallGroupControlTests._owned_group

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
        self.material = source.accepted_material()
        genomes = [{"format": "a", "channel": "b"}, {"format": "b", "channel": "a"}]
        self.candidates = dict(zip(("c-0", "c-1"), genomes))
        self.reply = {"evaluations": [pair[1] for pair in source.evaluated(
            genomes, [0.4, 1.0], invalid=(1,), prefix="c",
        )][::-1]}
        self.configuration = tasks.resolve_creativity_configuration(creativity_configuration())
        self.document = resolver_doc()
        for slot in ("2", "3"):
            for rigor, cell in (("low", [1, 1]), ("medium", [2, 2]), ("high", [3, 4])):
                self.document["tuning"][rigor][slot]["review"] = cell
        staffing.save(self.home, self.document)
        self.session = staffing.create_session(
            self.home, session_body(document="matrix", rigor="low"),
        )["id"]
        prompt_sets.ensure_default(self.home)

    def call(self, physical, **changes):
        options = dict(
            home=self.home, session=self.session, workspace=self.workspace,
            configuration=self.configuration, search_material=self.material,
            candidates=self.candidates, generation=2, batch="b1", execution_context=None,
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

    def write_prompt(self, marker):
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        documents["milestone/evaluate_candidates.json"]["instructions"]["parts"].append(
            {"text": [marker], "variables": []},
        )
        return router_fixture.PromptRouterTest.write_set(self.home, "operator", documents)

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
                return self.result({"evaluations": []})
            return self.result()

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

        for _family, _model, _effort, prompt, workspace in dispatched:
            self.assertEqual(workspace, self.workspace)
            self.assertIn("KIND: evaluate_candidates", prompt)
            self.assertIn("ADDITIONAL ROOT /reference — READ-ONLY", prompt)
            self.assertIn("Do not edit files or execute proposals", prompt)
            material_text = prompt.split("IMMUTABLE SEARCH MATERIAL AND CRITERIA (JSON):\n")[1].splitlines()[0]
            batch_text = prompt.split("CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n")[1].splitlines()[0]
            self.assertEqual(json.loads(material_text), self.material)
            inputs = json.loads(batch_text)
            self.assertEqual([item["candidate_id"] for item in inputs], list(self.candidates))
            for item in inputs:
                self.assertEqual(set(item), {"candidate_id", "components"})
                self.assertEqual({part["dimension_id"]: part["variant_id"] for part in item["components"]},
                                 self.candidates[item["candidate_id"]])
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
            return self.result()

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

    def test_batch_reply_coverage_and_association(self):
        original = copy.deepcopy(self.candidates)
        accepted, _result = self.call(lambda *_args, **_kwargs: self.result())
        self.assertEqual(accepted["genomes"], original)
        self.assertEqual(accepted["evaluations"], self.reply["evaluations"])
        self.assertEqual(accepted["generation"], 2)
        self.assertEqual(accepted["batch"], "b1")
        self.assertFalse(accepted["evaluations"][0]["constraint_valid"])
        self.assertEqual(accepted["evaluations"][0]["score"], 1.0)
        invalid, valid = self.reply["evaluations"]
        rejected = {
            "duplicate": [invalid, valid, valid],
            "missing": [valid],
            "foreign": [invalid, dict(valid, candidate_id="foreign")],
            "violations": [dict(invalid, constraint_violations=["foreign"]), valid],
            "score": [invalid, dict(valid, score=1.1)],
        }
        for label, evaluations in rejected.items():
            with self.subTest(label=label):
                calls = []

                def physical(*_args, **_kwargs):
                    calls.append(True)
                    return self.result({"evaluations": evaluations} if len(calls) == 1 else self.reply)

                corrected, carrier = self.call(physical, batch=label)
                self.assertEqual(len(calls), 2)
                self.assertEqual(corrected["evaluations"], self.reply["evaluations"])
                self.assertEqual(corrected["genomes"], original)
                self.assertEqual(len(carrier.physical_dispatches), 2)
        calls = []

        def malformed(*_args, **_kwargs):
            calls.append(True)
            return self.result({"evaluations": []})

        with self.assertRaises(runners.WorkerProtocolError):
            self.call(malformed, batch="exhausted")
        self.assertEqual(len(calls), 2)
        self.assertEqual(accepted["evaluations"], self.reply["evaluations"])
        self.assertEqual(self.candidates, original)

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

    def test_batch_evidence_uses_common_accounting(self):
        self.call(lambda *_args, **_kwargs: self.result(), batch="success")
        calls = []

        def corrected(*_args, **_kwargs):
            calls.append(True)
            if len(calls) == 1:
                staffing.edit_session(self.home, self.session, {"rigor": "high"})
                return self.result({"evaluations": []})
            return self.result()

        accepted, carrier = self.call(corrected, batch="corrected")

        def failed(*_args, **_kwargs):
            result = self.result()
            raise runners.ProviderResponseError(
                "paid failure", token_usage=result.token_usage, cost_payloads=result.cost_payloads,
            )

        with self.assertRaises(runners.ProviderResponseError):
            self.call(failed, batch="failed")
        interrupted = runners.ControlledInterruptionResult("", 0, 1.0, "paused by operator")
        output, returned = self.call(lambda *_args, **_kwargs: interrupted, batch="interrupted")
        self.assertIsNone(output)
        self.assertIs(returned, interrupted)
        records, accounting = self.evidence()
        self.assertEqual(len(records), 5)
        self.assertEqual(len({record["call_id"] for record in records}), 5)
        self.assertEqual([record["call_context"]["batch"] for record in records],
                         ["success", "corrected", "corrected", "failed", "interrupted"])
        self.assertTrue(all(record["call_context"]["job"] == "evaluate_candidates" and
                            record["call_context"]["generation"] == 2 for record in records))
        self.assertTrue(all(record["completed"] and record["duration_s"] >= 0 for record in records))
        self.assertEqual(accepted["call_id"], records[2]["call_id"])
        self.assertEqual(carrier.repair["call_id"], records[1]["call_id"])
        self.assertEqual(accepted["regime"]["model"], "gpt-5.6-sol")
        self.assertEqual(records[1]["model"], "gpt-5.6-luna")
        self.assertEqual(accounting["token_usage"]["input_tokens"], 40)
        self.assertEqual(accounting["token_usage"]["output_tokens"], 8)
        expected_cost = sum(pricing.codex_api_cost(record["model"], record["cost_payloads"][0])
                            for record in records[:4])
        self.assertAlmostEqual(accounting["cost"]["api_usd"], expected_cost)
        self.assertTrue(accounting["token_usage_partial"])
        self.assertTrue(accounting["cost_partial"])
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
