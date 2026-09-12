"""Task-owned creativity composition, durable handoffs and explicit continuation."""

import copy
import json
import os
import tempfile
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from orchestrator import kvstore, prompt_sets, runners, staffing, task_api, tasks
from orchestrator.tests import test_creativity_evaluation as evaluation_fixture
from orchestrator.tests import test_creativity_search as search_fixture
from orchestrator.tests import test_task_api as api_fixture
from orchestrator.tests import test_task_recovery as recovery_fixture
from orchestrator.tests.test_staffing_sessions import resolver_doc, session_body
from orchestrator.tests.test_tasks import creativity_configuration


class CreativityTaskTest(unittest.TestCase):
    order = api_fixture.TaskApiTest.order
    _wait = recovery_fixture.TaskRecoveryTest._wait
    _paused = recovery_fixture.TaskRecoveryTest._paused
    _terminal = recovery_fixture.TaskRecoveryTest._terminal
    result = evaluation_fixture.CreativityEvaluationTest.result
    write_prompt = evaluation_fixture.CreativityEvaluationTest.write_prompt

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="creativity-task-")
        self.addCleanup(temporary.cleanup)
        self.home = os.path.join(temporary.name, "home")
        self.primary = os.path.join(temporary.name, "workspace")
        self.additional = os.path.join(temporary.name, "references")
        os.makedirs(self.primary)
        os.makedirs(self.additional)
        self.references = [os.path.join(self.additional, name) for name in ("second.md", "first.md")]
        for path in self.references:
            with open(path, "w") as handle:
                handle.write("Reference material to read, never edit.")
        source = search_fixture.CreativitySearchTest()
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.material = source.accepted_material()
        self.calls = []
        self.valid = True
        self.additions = [{"dimension_id": "format", "variants": [
            {"id": "new", "text": "Serial", "reason": "Another reading format."},
        ]}]
        staffing.save(self.home, resolver_doc())
        self.session = staffing.create_session(self.home, session_body(document="matrix"))["id"]
        prompt_sets.ensure_default(self.home)

    @staticmethod
    def config():
        return {"billing": {"codex": "api", "claude": "api"}}

    def admit(self, prompt_set="default", **configuration):
        # Seed an admitted internal order: public catalogue admission is Slice 9.
        order = self.order("creativity", request=search_fixture.OBJECTIVE,
                           reference_documents=self.references)
        order.update(
            request=tasks.validate_request(order["request"]), staffing_session=self.session, prompt_set=prompt_set,
            configuration=tasks.resolve_creativity_configuration(creativity_configuration(**configuration)),
        )
        record = {"id": uuid.uuid4().hex, "order": order, "resolved_staffing": {}, "result": None}
        store = task_api.StandaloneTaskStore(self.home)
        self.assertTrue(store._store.cas(
            task_api.task_key(record["id"]), None,
            store._document(record, task_api._admission_stamp()),
        ).ok)
        return record

    def host(self, physical=None):
        return task_api.DirectTaskHost(
            self.home, runner_factory=lambda _config, _workspace: SimpleNamespace(call=physical or self.physical),
            poll_interval=0.001,
        )

    def checkpoint(self, record):
        return task_api.creativity_checkpoint_store(self.home, record["id"]).get("checkpoint")

    def physical(self, family, prompt, workspace, execution_context=None, **_kwargs):
        job = next(job for job in ("create_genes", "evaluate_candidates", "expand_genes")
                   if "KIND: " + job in prompt)
        call = {"job": job, "prompt": prompt, "family": family, "execution_context": execution_context}
        call.update(model=_kwargs.get("model"), effort=_kwargs.get("effort"))
        self.calls.append(call)
        self.assertEqual(workspace, self.primary)
        if job == "create_genes":
            reply = {"search_material": self.material}
        elif job == "expand_genes":
            reply = {"additions": self.additions}
        else:
            batch = json.loads(prompt.split(
                "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n",
            )[1].splitlines()[0])
            call["ids"] = [item["candidate_id"] for item in batch]
            fixed = json.loads(prompt.split("IMMUTABLE SEARCH MATERIAL AND CRITERIA (JSON):\n")[1].splitlines()[0])
            for key in self.material.keys() - {"dimensions"}:
                self.assertEqual(fixed[key], self.material[key])
            reply = {"evaluations": [{
                "candidate_id": item["candidate_id"], "proposal": "Use this combination.",
                "constraint_valid": self.valid, "constraint_violations": [] if self.valid else ["budget"],
                "reason": "Assessment against the stated objective.", "assumptions": [], "score": 0.4,
            } for item in batch]}
        return self.result(reply)

    def test_creativity_composes_search_and_results(self):
        catalogue = tasks.task_executor_catalogue()
        for reason, overrides in (
            ("generation_limit", {"generation_limit": 3}),
            ("evaluation_budget", {"max_evaluated_candidates": 3}),
            ("persistent_stagnation", {}),
            ("repertoire_exhausted", {}),
            ("generation_limit", {"generation_limit": 1}),
        ):
            with self.subTest(reason=reason, overrides=overrides):
                self.calls.clear()
                self.valid = overrides.get("generation_limit") != 1
                if reason == "repertoire_exhausted":
                    self.material["dimensions"] = self.material["dimensions"][:1]
                    self.additions = []
                configuration = dict(generation_limit=10, max_evaluated_candidates=20)
                configuration.update(overrides)
                record, host = self.admit(**configuration), self.host()
                host.start(record, self.config)
                result = self._terminal(host, record["id"])["result"]
                self.assertEqual(result["status"], "success", result)
                native = result["native_result"]
                self.assertEqual(native["stop_reason"], reason)
                self.assertEqual(native["outcome"], "proposals" if self.valid else "no_valid_candidates")
                self.assertLessEqual(len(native["proposals"]), 2)
                self.assertLessEqual(native["generations_completed"], configuration["generation_limit"])
                self.assertLessEqual(native["evaluated_candidates"], configuration["max_evaluated_candidates"])
                genes = self.calls[0]
                self.assertEqual(genes["job"], "create_genes")
                self.assertIn(search_fixture.OBJECTIVE, genes["prompt"])
                self.assertIn(json.dumps({"source": "test"}), genes["prompt"])
                self.assertIn(json.dumps(self.references), genes["prompt"])
                self.assertIn("READ-ONLY", genes["prompt"])
                self.assertIn("Do not edit files", genes["prompt"])
                self.assertEqual(genes["execution_context"]["additional"], [{"path": self.additional}])
                for proposal in native["proposals"]:
                    self.assertEqual([part["dimension_id"] for part in proposal["components"]],
                                     [dimension["id"] for dimension in self.material["dimensions"]])
                if overrides.get("generation_limit") == 3:
                    self.assertEqual(native["generations_completed"], 3)
                    self.assertEqual(native["evaluated_candidates"], 6)
                    self.assertEqual(native["expansion_interventions"], 1)
                    self.assertIn("expand_genes", [call["job"] for call in self.calls])
        self.assertEqual(tasks.task_executor_catalogue(), catalogue)
        self.assertNotIn("creativity", [item["id"] for item in catalogue])

    def test_creativity_resume_keeps_saved_work(self):
        for boundary in ("genes", "batch", "generation", "expansion", "result"):
            with self.subTest(boundary=boundary):
                self.calls.clear()
                record = self.admit(generation_limit=3, max_evaluated_candidates=12,
                                    evaluation_batch_size=1, evaluation_concurrency=2)
                checkpoint_store = task_api.creativity_checkpoint_store(self.home, record["id"])
                saved = threading.Event()
                claimed = threading.Event()
                lock = threading.Lock()
                put = kvstore.LocalKVClient.put

                def interrupt_after_save(store, key, value):
                    revision = put(store, key, value)
                    if store.directory != checkpoint_store.directory or saved.is_set():
                        return revision
                    progress = value["progress"]
                    reached = {
                        "genes": value["search_material"] is not None,
                        "batch": bool(value.get("evaluation", {}).get("batches")),
                        "generation": progress["generations_completed"] == 1,
                        "expansion": progress["expansion_interventions"] == 1,
                        "result": value["native_result"] is not None,
                    }[boundary]
                    if reached:
                        saved.set()
                        raise SystemExit("simulated host interruption after saved " + boundary)
                    return revision

                def physical(*args, **kwargs):
                    if boundary == "batch" and "KIND: evaluate_candidates" in args[1]:
                        with lock:
                            sibling = claimed.is_set()
                            claimed.set()
                        if sibling:
                            self.assertTrue(saved.wait(5))
                            raise runners.ProviderResponseError("interrupted sibling")
                    return self.physical(*args, **kwargs)

                host = self.host(physical)
                with mock.patch.object(kvstore.LocalKVClient, "put", new=interrupt_after_save):
                    thread = host.start(record, self.config)
                    thread.join(10)
                    self.assertFalse(thread.is_alive())
                self.assertTrue(saved.is_set(), self.checkpoint(record))
                before = self.checkpoint(record)
                if boundary == "batch":
                    self.assertEqual(before["evaluation"]["accepted_count"], 1)
                previous_calls = copy.deepcopy(self.calls)
                fresh = self.host()
                fresh.adopt_open_tasks(lambda _record: self.config)
                self.assertEqual(self.calls, previous_calls)
                self.assertEqual(self.checkpoint(record), before)
                paused = self._paused(fresh, record["id"])
                fresh.resume(record["id"], self.config, paused["revision"])
                result = self._terminal(fresh, record["id"])["result"]
                self.assertEqual(result["status"], "success", result)
                after = self.checkpoint(record)
                self.assertEqual(result["native_result"], after["native_result"])
                self.assertEqual(after["progress"]["generations_completed"], 3)
                self.assertEqual(after["progress"]["expansion_interventions"], 1)
                self.assertEqual(after["progress"]["evaluated_candidates"], 6)
                self.assertEqual({key: after["candidates"][key] for key in before["candidates"]}, before["candidates"])
                ids = [identity for call in self.calls for identity in call.get("ids", [])]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual([call["job"] for call in self.calls].count("create_genes"), 1)
                self.assertEqual([call["job"] for call in self.calls].count("expand_genes"), 1)
                if boundary == "result":
                    self.assertEqual(self.calls, previous_calls)

    def test_creativity_gene_correction_reads_live_authorities(self):
        self.write_prompt("FIRST PROMPT", "create_genes")
        record = self.admit(prompt_set="operator", rigor={"create_genes": "high"})

        def physical(*args, **kwargs):
            result = self.physical(*args, **kwargs)
            if len(self.calls) == 1:
                document = resolver_doc()
                document["assignment"]["plan"]["1"] = 3
                document["tuning"]["high"]["3"]["plan"] = [3, 5]
                staffing.save(self.home, document)
                staffing.edit_session(self.home, self.session, {"material": "business"})
                self.write_prompt("SECOND PROMPT", "create_genes")
                return self.result({"search_material": dict(self.material, objective="Rewritten objective")})
            return result

        host = self.host(physical)
        host.start(record, self.config)
        result = self._terminal(host, record["id"])["result"]
        self.assertEqual(result["status"], "success")
        genes = [call for call in self.calls if call["job"] == "create_genes"]
        self.assertEqual(len(genes), 2)
        self.assertIn("FIRST PROMPT", genes[0]["prompt"])
        self.assertIn("SECOND PROMPT", genes[1]["prompt"])
        self.assertEqual((genes[1]["family"], genes[1]["model"], genes[1]["effort"]),
                         ("claude", "claude-fable-5", "max"))
        self.assertEqual(self.checkpoint(record)["search_material"]["objective"], search_fixture.OBJECTIVE)
        receipts = [event["physical_dispatch"] for event in host.store.lifecycle(record["id"])["history"]
                    if "physical_dispatch" in event]
        self.assertEqual([item["call_context"]["material"] for item in receipts[:2]], ["default", "business"])
        self.assertEqual(result["native_result"]["evaluated_candidates"], 2)
        self.assertEqual(result["token_usage"]["input_tokens"], 30)

    def test_creativity_failed_checkpoint_never_accepts_work(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                self.calls.clear()
                record, host = self.admit(), self.host()
                directory = task_api.creativity_checkpoint_store(self.home, record["id"]).directory
                put = kvstore.LocalKVClient.put

                def fail_save(store, key, value):
                    if store.directory == directory and value["search_material"] is not None:
                        if cancel:
                            host.stop(record["id"], "cancel during failed save")
                        raise OSError("checkpoint unavailable")
                    return put(store, key, value)

                with mock.patch.object(kvstore.LocalKVClient, "put", new=fail_save):
                    host.start(record, self.config)
                    if cancel:
                        result = self._terminal(host, record["id"])["result"]
                        self.assertEqual(result["status"], "failure")
                        self.assertEqual(result["reason"], "cancel during failed save")
                    else:
                        self._paused(host, record["id"])
                self.assertIsNone(self.checkpoint(record)["search_material"])
                self.assertEqual(len(self.calls), 1)
                if not cancel:
                    fresh = self.host()
                    fresh.adopt_open_tasks(lambda _record: self.config)
                    paused = self._paused(fresh, record["id"])
                    fresh.resume(record["id"], self.config, paused["revision"])
                    result = self._terminal(fresh, record["id"])["result"]
                    self.assertEqual(result["status"], "success")
                    self.assertEqual([call["job"] for call in self.calls].count("create_genes"), 2)

    def test_creativity_cancel_wins_over_saved_success(self):
        record, host = self.admit(), self.host()
        with mock.patch.object(host.store, "record_result_locked", side_effect=OSError("publication failed")):
            host.start(record, self.config)
            self._paused(host, record["id"])
        self.assertIsNotNone(self.checkpoint(record)["native_result"])
        previous_calls = copy.deepcopy(self.calls)
        fresh = self.host()
        fresh.adopt_open_tasks(lambda _record: self.config)
        self.assertTrue(fresh.stop(record["id"], "cancel saved result"))
        result = self._terminal(fresh, record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "cancel saved result")
        self.assertEqual(self.calls, previous_calls)
        receipts = [event["attempt"] for event in fresh.store.lifecycle(record["id"])["history"]
                    if "physical_dispatch" in event]
        self.assertEqual(len(receipts), len(self.calls))
        self.assertAlmostEqual(result["cost"]["api_usd"], sum(item["cost"]["api_usd"] for item in receipts))
        self.assertEqual(result["token_usage"]["input_tokens"], len(self.calls) * 10)
        self.assertFalse(fresh.stop(record["id"]))
        self.assertEqual(fresh.store.record(record["id"])["result"], result)
