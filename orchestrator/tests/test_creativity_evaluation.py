"""Evaluation integration through live routers and host-owned call groups."""

import copy
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from types import SimpleNamespace
from unittest import mock

from orchestrator import creativity_evaluation as evaluation
from orchestrator import kvstore, pricing, prompt_sets, runners, staffing, task_api, tasks
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
        )
        options.update(changes)
        return evaluation.evaluate_wave(
            self.group, SimpleNamespace(call=physical or self.batch_result), **options,
        )

    def batch_result(self, _family, prompt, _workspace, **_kwargs):
        text = prompt.split("CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n")[1]
        ids = [item["candidate_id"] for item in json.loads(text.splitlines()[0])]
        return self.result({"evaluations": [dict(
            self.reply["evaluations"][0 if key == "c-1" else 1], candidate_id=key,
        ) for key in reversed(ids)]})

    def checkpoint(self):
        return kvstore.LocalKVClient(self.store.directory).get("checkpoint")

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

    def test_wave_evidence_uses_common_accounting(self):
        self.wave(candidates={"c-0": self.candidates["c-0"]})
        calls = []

        def corrected(*args, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                staffing.edit_session(self.home, self.session, {"rigor": "high"})
                return self.result({"evaluations": []})
            return self.batch_result(*args, **kwargs)

        handoff = self.wave(corrected)
        self.assertEqual(handoff["accepted_count"], 2)
        self.assertEqual(handoff["unfinished"], ["c-0"])
        self.assertTrue(handoff["rebaseline_required"])
        accepted = self.checkpoint()["evaluation"]["batches"][-1]

        def failed(*_args, **_kwargs):
            result = self.result()
            raise runners.ProviderResponseError(
                "paid failure", token_usage=result.token_usage, cost_payloads=result.cost_payloads,
            )

        with self.assertRaises(runners.ProviderResponseError):
            self.wave(failed)
        interrupted = runners.ControlledInterruptionResult("", 0, 1.0, "paused by operator")
        handoff = self.wave(lambda *_args, **_kwargs: interrupted)
        self.assertEqual(handoff["evaluated"], [])
        self.assertIs(handoff["interruption"], interrupted)
        records, accounting = self.evidence()
        self.assertEqual(len(records), 5)
        self.assertEqual(len({record["call_id"] for record in records}), 5)
        self.assertEqual(len({record["call_context"]["batch"] for record in records}), 4)
        self.assertEqual(records[1]["call_context"]["batch"], records[2]["call_context"]["batch"])
        self.assertTrue(all(record["call_context"]["job"] == "evaluate_candidates" and
                            record["call_context"]["generation"] == 2 for record in records))
        self.assertTrue(all(record["completed"] and record["duration_s"] >= 0 for record in records))
        self.assertEqual(accepted["call_id"], records[2]["call_id"])
        self.assertEqual(accepted["regime"]["model"], "gpt-5.6-sol")
        self.assertEqual(records[1]["model"], "gpt-5.6-luna")
        self.assertEqual(accounting["token_usage"]["input_tokens"], 40)
        self.assertEqual(accounting["token_usage"]["output_tokens"], 8)
        expected_cost = sum(pricing.codex_api_cost(record["model"], record["cost_payloads"][0])
                            for record in records[:4])
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
            if '"candidate_id": "c-0"' in args[1]:
                return runners.ControlledInterruptionResult("", 0, 0.1, "paused")
            return self.batch_result(*args, **kwargs)

        partial = self.wave(interrupted)
        self.assertEqual(partial["unfinished"], ["c-0"])
        self.assertEqual(partial["interruption"].interrupt_reason, "paused")
        records = len(self.evidence()[0])
        resumed = self.wave()
        self.assertTrue(resumed["comparison_ready"])
        self.assertEqual(resumed["accepted_count"], 2)
        self.assertEqual(len(self.evidence()[0]), records + 1)

    def test_regime_changes_withhold_comparison(self):
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
                    if not entered.is_set():
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
                self.assertEqual(handoff["unfinished"], ["c-0"])
                self.assertEqual(handoff["evaluated"], [])
                self.assertTrue(handoff["rebaseline_required"])
                batches = self.checkpoint()["evaluation"]["batches"]
                self.assertNotEqual(batches[0]["regime"][component], batches[1]["regime"][component])
                ready = self.wave(reference_revision=1)
                self.assertTrue(ready["comparison_ready"])
                self.assertEqual(ready["accepted_count"], 3)
                self.assertTrue(ready["rebaseline_required"])
                # Between waves, a changed evaluator invalidates both survivors.
                change(False)
                candidates = dict(self.candidates, **{"c-2": {"format": "a", "channel": "a"}})
                changed = self.wave(candidates=candidates, comparison_ids=list(candidates), reference_revision=2)
                self.assertEqual(changed["unfinished"], ["c-0", "c-1"])
                self.assertFalse(changed["comparison_ready"])
                ready = self.wave(candidates=candidates, comparison_ids=list(candidates), reference_revision=2)
                self.assertTrue(ready["comparison_ready"])
                self.assertEqual(ready["accepted_count"], 6)
                self.write_prompt("PROMPT ONLY")
                candidates["c-3"] = {"format": "b", "channel": "b"}
                ready = self.wave(candidates=candidates, comparison_ids=list(candidates),
                                  reference_revision=3, prompt_set="operator")
                self.assertTrue(ready["comparison_ready"])
                self.assertFalse(ready["rebaseline_required"])

    def test_wave_faults_keep_accepted_siblings_and_checkpoint_failure_is_unfinished(self):
        def malformed(*args, **kwargs):
            if '"candidate_id": "c-1"' in args[1]:
                return self.result({"evaluations": []})
            return self.batch_result(*args, **kwargs)

        with self.assertRaises(runners.WorkerProtocolError):
            self.wave(malformed)
        self.assertEqual(self.checkpoint()["evaluation"]["accepted_count"], 1)
        self.assertEqual(len(self.evidence()[0]), 3)
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
        self.assertEqual(len(self.evidence()[0]), 4)
        session = staffing.create_session(self.home, session_body(document="matrix", families=[]))["id"]
        with self.assertRaises(staffing.StaffingConditionError) as caught:
            self.wave(session=session)
        self.assertEqual(caught.exception.code, "staffing_unavailable")
        self.assertEqual(self.checkpoint(), before)
        self.assertEqual(len(self.evidence()[0]), 4)
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
