"""Task-owned creativity composition, durable handoffs and explicit continuation."""

import copy
import json
import os
import sys
import tempfile
import textwrap
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from orchestrator import brainstorming_lifecycle
from orchestrator import kvstore, prompt_sets, registry, runners, service, staffing, task_api, tasks
from orchestrator.tests import test_creativity_evaluation as evaluation_fixture
from orchestrator.tests import test_creativity_search as search_fixture
from orchestrator.tests import test_task_api as api_fixture
from orchestrator.tests import test_task_recovery as recovery_fixture
from orchestrator.tests import test_task_call_group as group_fixture
from orchestrator.tests import test_task_cancel_recovery as cancel_fixture
from orchestrator.tests import test_task_controls_api as controls_fixture
from orchestrator.tests.test_staffing_sessions import resolver_doc, session_body
from orchestrator.tests.test_tasks import creativity_configuration


class CreativityTaskTest(unittest.TestCase):
    order = api_fixture.TaskApiTest.order
    _wait = recovery_fixture.TaskRecoveryTest._wait
    _paused = recovery_fixture.TaskRecoveryTest._paused
    _terminal = recovery_fixture.TaskRecoveryTest._terminal
    result = evaluation_fixture.CreativityEvaluationTest.result
    write_prompt = evaluation_fixture.CreativityEvaluationTest.write_prompt
    start_server = api_fixture.TaskApiTest.start_server
    request = api_fixture.TaskApiTest.request
    project = api_fixture.TaskApiTest.project
    member = staticmethod(api_fixture.TaskApiTest.member)

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

    def admit(self, prompt_set="default", work_area=None, **configuration):
        order = self.order("creativity", work_area=work_area, request=search_fixture.OBJECTIVE,
                           reference_documents=self.references)
        order.update(
            staffing_session=self.session, prompt_set=prompt_set,
            configuration=creativity_configuration(**configuration),
        )
        return task_api.StandaloneTaskStore(self.home).admit(order, {}, self.primary)

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
        self.assertIn("creativity", [item["id"] for item in catalogue])

    def test_creativity_cross_domain_contracts(self):
        examples = os.path.join(os.path.dirname(__file__), "..", "..", "implementation",
                                "milestones", "creativity", "examples")
        # Scripted model material, deliberately separate from the common inputs
        # used by the real comparison. These are not domain templates or defaults.
        dimensions = {
            "language": [
                ("action", "What the daughter does", [
                    "Tightens a knot", "Hides a torn net", "Counts her father's stitches", "Unties a knot",
                ]),
                ("trace", "Sensory trace of the missing minute", [
                    "A cooling cup", "A stopped bell", "A wet handprint", "A thread pulled taut",
                ]),
            ],
            "business": [
                ("offer", "Paid service to test", [
                    "Brake adjustment", "Puncture clinic", "Commuter safety check", "Chain care lesson",
                ]),
                ("delivery", "Bounded delivery arrangement", [
                    "Two booked counter slots", "One small workshop", "Three short appointments", "One demo",
                ]),
            ],
        }
        document = resolver_doc()
        document["assignment"]["plan"] = {"1": 3}
        document["assignment"]["brainstorm"]["1"] = 3
        document["tuning"]["high"]["3"]["plan"] = [3, 5]
        document["tuning"]["medium"]["3"]["brainstorm"] = [2, 2]
        staffing.save(self.home, document)
        configuration = {
            "population_size": 4, "generation_limit": 4, "max_evaluated_candidates": 16,
            "elite_count": 2, "diversity_count": 1, "mutation_rate": 0.5,
            "minimum_improvement": 0.1, "patience_generations": 2,
            "max_stagnation_expansions": 1, "evaluation_batch_size": 2,
            "evaluation_concurrency": 2, "shortlist_size": 3,
            "rigor": {"default": "medium", "create_genes": "high", "evaluate_candidates": "low"},
        }
        expected_staffing = {
            "create_genes": ("claude", "claude-fable-5", "max"),
            "evaluate_candidates": ("codex", "gpt-5.6-luna", "low"),
            "expand_genes": ("claude", "claude-opus-5", "medium"),
        }
        for domain, layer in (("language", "literature"), ("business", "business")):
            with open(os.path.join(examples, domain + ".json"), encoding="utf-8") as handle:
                problem = json.load(handle)
            for material in ("default", layer):
                with self.subTest(domain=domain, material=material):
                    self.calls.clear()
                    staffing.edit_session(self.home, self.session, {"rigor": "high", "material": material})
                    session = staffing.read_session(self.home, self.session)
                    self.material = dict(copy.deepcopy(problem["context"]), objective=problem["request"],
                                         dimensions=[{
                                             "id": key, "meaning": meaning, "variants": [
                                                 {"id": "v" + str(i), "text": text}
                                                 for i, text in enumerate(variants)
                                             ],
                                         } for key, meaning, variants in dimensions[domain]])
                    self.additions = [{"dimension_id": dimensions[domain][0][0], "variants": [{
                        "id": "expanded", "text": ("Cuts a remembered stitch" if domain == "language"
                                                   else "Wheel care lesson"),
                        "reason": "Adds a different action within the existing dimension.",
                    }]}]
                    active, peak, entered = 0, 0, 0
                    evaluated_ids, invalid_ids, best_ids = [], [], []
                    lock, overlap = threading.Lock(), threading.Barrier(2, timeout=5)

                    def physical(family, prompt, workspace, **kwargs):
                        nonlocal active, peak, entered
                        if "KIND: evaluate_candidates" not in prompt:
                            return self.physical(family, prompt, workspace, **kwargs)
                        with lock:
                            active += 1
                            peak = max(peak, active)
                            entered += 1
                            first_wave = entered <= 2
                        try:
                            result = self.physical(family, prompt, workspace, **kwargs)
                            reply = json.loads(result.text)
                            with lock:
                                for item in reply["evaluations"]:
                                    identity = item["candidate_id"]
                                    evaluated_ids.append(identity)
                                    if not invalid_ids:
                                        invalid_ids.append(identity)
                                        item.update(constraint_valid=False, score=1.0,
                                                    constraint_violations=[self.material["constraints"][0]["id"]])
                                    elif not best_ids:
                                        best_ids.append(identity)
                                        item["score"] = 0.6
                            if first_wave:
                                overlap.wait()
                            return self.result(reply)
                        finally:
                            with lock:
                                active -= 1

                    host = self.host(physical)
                    self.start_server(host)
                    code, catalogue = self.request("GET", "/api/task-executors")
                    self.assertEqual(code, 200)
                    self.assertIn("creativity", [item["id"] for item in catalogue["task_executors"]])
                    order = self.order("creativity", **problem)
                    order.update(configuration=configuration, staffing_session=self.session)
                    with mock.patch.object(service, "_direct_task_config", return_value=self.config()):
                        code, response = self.request("POST", "/api/tasks", order)
                    self.assertEqual(code, 201, response)
                    record = self._terminal(host, response["task"]["id"])
                    code, public = self.request("GET", "/api/tasks/" + record["id"])
                    self.assertEqual(code, 200)
                    self.assertEqual(public["task"], record)
                    result, checkpoint = record["result"], self.checkpoint(record)
                    self.assertEqual(result["status"], "success", result)
                    self.assertEqual(record["order"]["configuration"], configuration)
                    for key, value in problem.items():
                        self.assertEqual(record["order"]["request"][key], value)
                    self.assertEqual(staffing.read_session(self.home, self.session), session)
                    self.assertEqual((active, peak), (0, configuration["evaluation_concurrency"]))

                    native = result["native_result"]
                    self.assertEqual(native["stop_reason"], "generation_limit")
                    self.assertEqual(native["outcome"], "proposals")
                    self.assertEqual(native["generations_completed"], configuration["generation_limit"])
                    self.assertEqual(native["evaluated_candidates"], len(evaluated_ids))
                    self.assertEqual(len(evaluated_ids), configuration["max_evaluated_candidates"])
                    self.assertEqual(len(set(evaluated_ids)), len(evaluated_ids))
                    self.assertEqual(native["expansion_interventions"], 1)
                    self.assertEqual(checkpoint["progress"]["expansions"][0]["generation"], 3)
                    expanded = copy.deepcopy(self.material)
                    expanded["dimensions"][0]["variants"].append({
                        key: self.additions[0]["variants"][0][key] for key in ("id", "text")
                    })
                    self.assertEqual(checkpoint["search_material"], expanded)
                    for genome in checkpoint["candidates"].values():
                        self.assertEqual(set(genome), {dimension["id"] for dimension in expanded["dimensions"]})
                        for dimension in expanded["dimensions"]:
                            self.assertIn(genome[dimension["id"]], [variant["id"]
                                                                   for variant in dimension["variants"]])

                    proposals = native["proposals"]
                    self.assertLessEqual(len(proposals), configuration["shortlist_size"])
                    final_ids = {item["candidate_id"] for item in proposals}
                    self.assertTrue(final_ids.isdisjoint(invalid_ids))
                    self.assertTrue(set(best_ids) <= final_ids)
                    genomes = []
                    for item in proposals:
                        parts = item["components"]
                        self.assertEqual(len(parts), len(expanded["dimensions"]))
                        for part, dimension in zip(parts, expanded["dimensions"]):
                            self.assertEqual(part["dimension_id"], dimension["id"])
                            self.assertEqual(part["dimension"], dimension["meaning"])
                            self.assertIn({"id": part["variant_id"], "text": part["variant"]},
                                          dimension["variants"])
                        genomes.append(tuple(part["variant_id"] for part in parts))
                    self.assertEqual(len(set(genomes)), len(genomes))

                    for call in self.calls:
                        job, prompt = call["job"], call["prompt"]
                        self.assertEqual(tuple(call[key] for key in ("family", "model", "effort")),
                                         expected_staffing[job])
                        self.assertEqual(layer.upper() + " REFINEMENT" in prompt, material == layer)
                        self.assertIn("Do not edit files or execute proposals", prompt)
                        if job == "create_genes":
                            self.assertIn(problem["request"], prompt)
                            self.assertEqual(json.loads(prompt.split("\nCONTEXT:\n")[1].splitlines()[0]),
                                             problem["context"])
                            self.assertIn("ORDERED REFERENCE PATHS (JSON array; may be empty):\n[]", prompt)
                        elif job == "evaluate_candidates":
                            self.assertLessEqual(len(call["ids"]), configuration["evaluation_batch_size"])
                        else:
                            self.assertEqual(json.loads(prompt.split(
                                "COMPLETE SEARCH MATERIAL (JSON):\n",
                            )[1].splitlines()[0]), self.material)
                            promising = json.loads(prompt.split(
                                "PROMISING VALID CANDIDATES (JSON; no historical scores or prestige):\n",
                            )[1].splitlines()[0])
                            promising_ids = {item["candidate_id"] for item in promising}
                            self.assertTrue(promising_ids.isdisjoint(invalid_ids))
                            self.assertTrue(set(best_ids) <= promising_ids)
                            self.assertTrue(all("score" not in item for item in promising))

                    receipts = [event for event in public["lifecycle"]["history"] if "physical_dispatch" in event]
                    self.assertEqual(len(receipts), len(self.calls))
                    self.assertEqual(len({event["call_id"] for event in receipts}), len(receipts))
                    self.assertEqual(len(receipts), 10)  # Genes, eight batches, one expansion.
                    batches = {batch["call_id"]: batch for batch in checkpoint["evaluation"]["batches"]}
                    self.assertEqual(len(batches), 8)
                    self.assertEqual({call["job"] for call in self.calls}, set(expected_staffing))
                    for event in receipts:
                        dispatch = event["physical_dispatch"]
                        context = dispatch["call_context"]
                        self.assertEqual(context["material"], material)
                        self.assertIsNone(dispatch["prompt_set_fallback"])
                        self.assertEqual(tuple(dispatch[key] for key in ("family", "model", "effort")),
                                         expected_staffing[context["job"]])
                        if context["job"] == "evaluate_candidates":
                            batch = batches[event["call_id"]]
                            self.assertEqual((batch["batch"], batch["generation"]),
                                             (context["batch"], context["generation"]))
                            self.assertCountEqual(batch["genomes"], [item["candidate_id"]
                                                                    for item in batch["evaluations"]])
                    attempts = [event["attempt"] for event in receipts]
                    self.assertAlmostEqual(result["duration_s"], sum(item["duration_s"] for item in attempts))
                    for key in ("input_tokens", "output_tokens"):
                        self.assertEqual(result["token_usage"][key],
                                         sum(item["token_usage"][key] for item in attempts))
                    for key in ("api_usd", "real_usd"):
                        self.assertAlmostEqual(result["cost"][key], sum(item["cost"][key] for item in attempts))
                    self.assertFalse(result["token_usage_partial"])
                    self.assertFalse(result["cost_partial"])

    def test_creativity_default_runner_composes_with_execution_context(self):
        replies = os.path.join(self.primary, "replies.json")
        with open(replies, "w", encoding="utf-8") as handle:
            json.dump({"create_genes": {"search_material": self.material},
                       "expand_genes": {"additions": self.additions}}, handle)
        worker = os.path.join(self.primary, "fake-creativity-cli.py")
        with open(worker, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(r'''
                import json, sys

                live = "--input-format" in sys.argv
                prompt = (json.loads(sys.stdin.readline())["message"]["content"][0]["text"]
                          if live else sys.stdin.read())
                job = next(job for job in ("create_genes", "evaluate_candidates", "expand_genes")
                           if "KIND: " + job in prompt)
                with open(sys.argv[1], encoding="utf-8") as handle:
                    replies = json.load(handle)
                if job == "evaluate_candidates":
                    batch = json.loads(prompt.split(
                        "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n"
                    )[1].splitlines()[0])
                    reply = {"evaluations": [{
                        "candidate_id": item["candidate_id"], "proposal": "Use this combination.",
                        "constraint_valid": True, "constraint_violations": [],
                        "reason": "Assessment against the objective.", "assumptions": [], "score": 0.4,
                    } for item in batch]}
                else:
                    reply = replies[job]
                answer = json.dumps(reply)
                print(json.dumps({"type": "result", "result": answer, "is_error": False})
                      if live else answer, flush=True)
            '''))
        for family, flags in (("codex", []), ("claude", ["-p"])):
            with self.subTest(family=family):
                self.session = staffing.create_session(
                    self.home, session_body(document="matrix", families=[family]),
                )["id"]
                config = dict(self.config(), commands={family: [sys.executable, worker, replies] + flags})
                record = self.admit(generation_limit=3, max_evaluated_candidates=12)
                host = task_api.DirectTaskHost(self.home, poll_interval=0.001)
                with mock.patch.object(brainstorming_lifecycle, "_spawn_participant",
                                       wraps=brainstorming_lifecycle._spawn_participant) as spawn:
                    host.start(record, lambda: config)
                    result = self._terminal(host, record["id"])["result"]
                self.assertEqual(result["status"], "success", result)
                native = result["native_result"]
                self.assertEqual(native["stop_reason"], "generation_limit")
                self.assertEqual(native["generations_completed"], 3)
                self.assertEqual(native["evaluated_candidates"], 6)
                self.assertEqual(native["expansion_interventions"], 1)
                self.assertTrue(native["proposals"])
                self.assertEqual(self.checkpoint(record)["native_result"], native)
                self.assertEqual(spawn.call_count, 5)
                for call in spawn.call_args_list:
                    context, argv, kwargs = call.args
                    self.assertEqual(context, {
                        "workspace_path": self.primary, "primary": {"path": self.primary},
                        "additional": [{"path": self.additional}], "project": None, "work_area": None,
                    })
                    self.assertEqual("--input-format" in argv, family == "claude")
                    self.assertEqual(kwargs["cwd"], self.primary)
                    self.assertTrue(kwargs["start_new_session"])
                    self.assertTrue(kwargs["pass_fds"])
                self.assertFalse(host.owns_workspace(self.primary))
                self.assertFalse(os.path.exists(os.path.join(
                    self.home, "task-runtime", record["id"], "execution.json",
                )))

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

    def test_creativity_resume_reads_live_authorities_and_accounts_once(self):
        for regime_change, cancel in ((False, False), (True, False), (True, True)):
            with self.subTest(regime_change=regime_change, cancel=cancel):
                self.calls.clear()
                document = resolver_doc()
                document["tuning"]["high"]["2"]["plan"] = [3, 4]
                document["tuning"]["medium"]["2"]["brainstorm"] = [2, 2]
                staffing.save(self.home, document)
                staffing.edit_session(self.home, self.session, {"rigor": "high", "material": "default"})
                self.write_prompt("BEFORE RESUME")
                record = self.admit(
                    prompt_set="operator", generation_limit=3, max_evaluated_candidates=8,
                    minimum_improvement=0.1,
                    rigor={"default": "medium", "create_genes": "high", "evaluate_candidates": "low"},
                )

                def interrupted(*args, **kwargs):
                    result = self.physical(*args, **kwargs)
                    if len(self.calls) == 1:
                        # Provider returned no usage/price with its rejected reply.
                        return runners.RunnerResult("{}", 0, 1.0)
                    if self.calls[-1]["job"] == "expand_genes":
                        failure = runners.ProviderResponseError(
                            "paid expansion fault", token_usage={"input_tokens": 7, "output_tokens": 3},
                            cost_payloads=[{"input_tokens": 7, "output_tokens": 3, "total_cost_usd": 0.07}],
                        )
                        failure.duration_s = 0.375
                        raise failure
                    return result

                host = self.host(interrupted)
                host.start(record, self.config)
                paused = self._paused(host, record["id"])
                self.assertIn("paid expansion fault", paused["reason"])
                before = self.checkpoint(record)
                self.assertEqual((before["progress"]["generations_completed"],
                                  before["progress"]["evaluated_candidates"]), (2, 4))
                self.assertEqual(before["progress"]["expansion_interventions"], 0)
                survivors = {item["candidate_id"] for _, item in before["progress"]["archive"]}
                prior_calls = copy.deepcopy(self.calls)
                self.write_prompt("AFTER RESUME")
                if regime_change:
                    document["assignment"]["review"]["1"] = 3
                    document["tuning"]["low"]["3"]["review"] = [3, 5]
                    staffing.save(self.home, document)
                    staffing.edit_session(self.home, self.session, {"material": "business"})

                def resumed(*args, **kwargs):
                    result = self.physical(*args, **kwargs)
                    if self.calls[-1]["job"] == "evaluate_candidates":
                        reply = json.loads(result.text)
                        for item in reply["evaluations"]:
                            item["score"] = 0.9
                        return self.result(reply)
                    return result

                fresh = self.host(resumed)
                fresh.adopt_open_tasks(lambda _record: self.config)
                self.assertEqual(self.calls, prior_calls)
                self.assertEqual(self.checkpoint(record), before)
                rebased = []
                directory = task_api.creativity_checkpoint_store(self.home, record["id"]).directory
                put = kvstore.LocalKVClient.put

                def observe_rebaseline(store, key, value):
                    revision = put(store, key, value)
                    if store.directory == directory:
                        progress = value["progress"]
                        if progress["generations_completed"] == 2 and progress["reference_score"] == 0.9:
                            rebased.append(copy.deepcopy(progress))
                    return revision

                with mock.patch.object(kvstore.LocalKVClient, "put", new=observe_rebaseline), \
                        mock.patch.object(fresh.store, "record_result_locked", side_effect=OSError("hold publication")):
                    fresh.resume(record["id"], self.config, paused["revision"])
                    self._paused(fresh, record["id"])
                saved = self.checkpoint(record)
                native = saved["native_result"]
                self.assertEqual(native["evaluated_candidates"], 8 if regime_change else 6)
                self.assertEqual(native["generations_completed"], 3)
                self.assertEqual(native["expansion_interventions"], 1)
                self.assertEqual(bool(rebased), regime_change)
                for progress in rebased:
                    self.assertFalse(progress["progress_made"])
                    self.assertEqual(progress["stagnant_generations"], 0)
                    self.assertEqual(progress["consecutive_expansions"], 1)
                    self.assertEqual(progress["evaluated_candidates"], 8)
                later = self.calls[len(prior_calls):]
                evaluations = [call for call in later if call["job"] == "evaluate_candidates"]
                self.assertEqual(len(evaluations), 2 if regime_change else 1)
                self.assertTrue(survivors.isdisjoint(evaluations[0]["ids"]))
                if regime_change:
                    self.assertEqual(set(evaluations[1]["ids"]), survivors)
                for call in evaluations:
                    self.assertIn("AFTER RESUME", call["prompt"])
                    self.assertEqual((call["family"], call["model"], call["effort"]),
                                     ("claude", "claude-fable-5", "max") if regime_change
                                     else ("codex", "gpt-5.6-luna", "low"))
                self.assertEqual((self.calls[0]["model"], self.calls[0]["effort"]), ("gpt-5.6-sol", "xhigh"))
                self.assertEqual((later[0]["model"], later[0]["effort"]), ("gpt-5.6-terra", "medium"))
                self.assertEqual(staffing.read_session(self.home, self.session)["rigor"], "high")
                receipts = [event for event in fresh.store.lifecycle(record["id"])["history"]
                            if "physical_dispatch" in event]
                self.assertEqual(len({event["call_id"] for event in receipts}), len(self.calls))
                self.assertEqual(len(receipts), len(self.calls))
                for event, call in zip(receipts, self.calls):
                    dispatch = event["physical_dispatch"]
                    self.assertEqual(dispatch["call_context"]["job"], call["job"])
                    for field in ("family", "model", "effort"):
                        self.assertEqual(dispatch[field], call[field])
                    self.assertIsInstance(dispatch["call_context"]["generation"], int)
                    self.assertTrue(dispatch["call_context"]["batch"])
                    self.assertEqual(dispatch["call_context"]["material"],
                                     "business" if regime_change and call in later else "default")
                    self.assertIsNone(dispatch["prompt_set_fallback"])
                completed_calls = copy.deepcopy(self.calls)
                final = self.host()
                final.adopt_open_tasks(lambda _record: self.config)
                if cancel:
                    final.stop(record["id"], "cancel accounted search")
                else:
                    final.resume(record["id"], self.config, self._paused(final, record["id"])["revision"])
                result = self._terminal(final, record["id"])["result"]
                self.assertEqual(result["status"], "failure" if cancel else "success")
                self.assertEqual(result["native_result"], None if cancel else native)
                self.assertEqual(self.calls, completed_calls)
                final_receipts = [event for event in final.store.lifecycle(record["id"])["history"]
                                  if "physical_dispatch" in event]
                self.assertEqual(final_receipts, receipts)
                attempts = [event["attempt"] for event in receipts]
                self.assertAlmostEqual(result["duration_s"], sum(item["duration_s"] for item in attempts))
                for key in ("input_tokens", "output_tokens"):
                    self.assertEqual(result["token_usage"][key],
                                     sum(item["token_usage"][key] for item in attempts if item["token_usage"]))
                for key in ("api_usd", "real_usd"):
                    self.assertAlmostEqual(result["cost"][key],
                                           sum(item["cost"][key] for item in attempts if item["cost"]))
                known_successes = len(self.calls) - 2  # Unknown correction plus the paid fault.
                self.assertEqual(result["token_usage"]["input_tokens"], 10 * known_successes + 7)
                self.assertEqual(result["token_usage"]["output_tokens"], 2 * known_successes + 3)
                paid = next(event["attempt"] for event in receipts
                            if event["physical_dispatch"]["error"] == "paid expansion fault")
                self.assertIsNotNone(paid["cost"])
                self.assertGreater(paid["cost"]["api_usd"], 0)
                self.assertTrue(result["token_usage_partial"])
                self.assertTrue(result["cost_partial"])
                for key, value in final.store.lifecycle(record["id"])["accounting"].items():
                    self.assertEqual(result[key], value)

    def test_creativity_provider_and_protocol_faults_keep_saved_work(self):
        for job in ("create_genes", "evaluate_candidates", "expand_genes"):
            for fault in ("provider", "protocol"):
                with self.subTest(job=job, fault=fault):
                    self.calls.clear()
                    failed_ids, lock = [], threading.Lock()

                    def physical(*args, **kwargs):
                        result = self.physical(*args, **kwargs)
                        if "KIND: " + job not in args[1]:
                            return result
                        if job == "evaluate_candidates":
                            identity = json.loads(result.text)["evaluations"][0]["candidate_id"]
                            with lock:
                                if not failed_ids:
                                    failed_ids.append(identity)
                            if identity != failed_ids[0]:
                                return result
                        if fault == "provider":
                            raise runners.ProviderResponseError("provider unavailable")
                        return self.result({})

                    record = self.admit(prompt_set="missing", generation_limit=3, max_evaluated_candidates=12,
                                        evaluation_batch_size=1, evaluation_concurrency=2)
                    host = self.host(physical)
                    host.start(record, self.config)
                    paused = self._paused(host, record["id"])
                    self.assertEqual(paused["source"], "error")
                    before = self.checkpoint(record)
                    self.assertEqual(before["job"], job)
                    self.assertIsNone(before["native_result"])
                    self.assertEqual(before["search_material"] is None, job == "create_genes")
                    accepted = before.get("evaluation", {}).get("batches", [])
                    accepted_ids = {item["candidate_id"] for batch in accepted for item in batch["evaluations"]}
                    self.assertEqual(len(accepted_ids), {"create_genes": 0, "evaluate_candidates": 1,
                                                        "expand_genes": 4}[job])
                    failed_calls = [call for call in self.calls if call["job"] == job
                                    and (job != "evaluate_candidates" or call["ids"] == failed_ids)]
                    self.assertEqual(len(failed_calls), 1 if fault == "provider" else 2)
                    previous_calls = copy.deepcopy(self.calls)
                    fresh = self.host()
                    fresh.adopt_open_tasks(lambda _record: self.config)
                    self.assertEqual(self.calls, previous_calls)
                    self.assertEqual(self.checkpoint(record), before)
                    fresh.resume(record["id"], self.config, paused["revision"])
                    result = self._terminal(fresh, record["id"])["result"]
                    self.assertEqual(result["status"], "success", result)
                    self.assertEqual(result["native_result"]["evaluated_candidates"], 6)
                    resumed_ids = {identity for call in self.calls[len(previous_calls):]
                                   for identity in call.get("ids", [])}
                    self.assertTrue(accepted_ids.isdisjoint(resumed_ids))
                    receipts = [event["physical_dispatch"] for event in fresh.store.lifecycle(record["id"])["history"]
                                if "physical_dispatch" in event]
                    self.assertEqual(len(receipts), len(self.calls))
                    self.assertTrue(all(item["prompt_set_fallback"] == "stored_default" for item in receipts))

    def test_creativity_staffing_faults_pause_without_dispatch(self):
        for code in ("staffing_unavailable", "distinct_families_unsatisfiable"):
            with self.subTest(code=code):
                self.calls.clear()
                document = resolver_doc()
                if code == "distinct_families_unsatisfiable":
                    document["roles"]["brainstorm"] = {"distinct_families": True}
                else:
                    for slot in ("2", "3"):
                        document["families"][slot]["name"] = "unavailable-" + slot
                staffing.save(self.home, document)
                record, host = self.admit(generation_limit=3, max_evaluated_candidates=12), self.host()
                host.start(record, self.config)
                paused = self._paused(host, record["id"])
                self.assertIn(code, paused["reason"])
                self.assertEqual(len(self.calls), 0 if code == "staffing_unavailable" else 3)
                self.assertNotIn("expand_genes", [call["job"] for call in self.calls])
                receipts = [event for event in host.store.lifecycle(record["id"])["history"]
                            if "physical_dispatch" in event]
                self.assertEqual(len(receipts), len(self.calls))
                before = self.checkpoint(record)
                staffing.save(self.home, resolver_doc())
                fresh = self.host()
                fresh.adopt_open_tasks(lambda _record: self.config)
                self.assertEqual(self.checkpoint(record), before)
                fresh.resume(record["id"], self.config, paused["revision"])
                result = self._terminal(fresh, record["id"])["result"]
                self.assertEqual(result["status"], "success", result)
                self.assertEqual([call["job"] for call in self.calls].count("create_genes"), 1)

    def test_creativity_controls_wait_for_quiescence(self):
        for job in ("create_genes", "evaluate_candidates", "expand_genes"):
            for action in ("pause", "stop"):
                with self.subTest(job=job, action=action):
                    label = job + "-" + action

                    class HeldJob(group_fixture.GroupRunner):
                        def call(worker, family, prompt, workspace, **kwargs):
                            if "KIND: " + job in prompt:
                                return super().call(family, label, workspace, **kwargs)
                            return self.physical(family, prompt, workspace, **kwargs)

                    held = HeldJob("template")
                    record = self.admit(generation_limit=3, max_evaluated_candidates=12,
                                        evaluation_batch_size=1, evaluation_concurrency=2)
                    host = task_api.DirectTaskHost(self.home, runner_factory=lambda *_args: held,
                                                   poll_interval=0.005)
                    fixture = group_fixture.TaskCallGroupControlTests()
                    self.addCleanup(fixture.doCleanups)
                    other_id, other = fixture._owned_group(host, "unrelated-" + label)
                    outsider_runner = group_fixture.GroupRunner("template")
                    outsider = fixture._start(other, outsider_runner, "other")
                    fixture._started(other, "other1")
                    release = threading.Event()
                    real_observe = runners._process_group_quiescent

                    def observe(pgid):
                        if pgid in held.pids.values() and not release.is_set():
                            return None
                        return real_observe(pgid)

                    with mock.patch.object(runners, "_process_group_quiescent", side_effect=observe), \
                            mock.patch.object(runners, "_wait_for_process_group_quiescence", side_effect=observe):
                        thread = host.start(record, self.config)
                        count = 2 if job == "evaluate_candidates" else 1
                        try:
                            self._wait(lambda: len(held.calls) == count and all(os.path.exists(
                                os.path.join(self.primary, name + ".started")) for name in held.calls),
                                "semantic workers did not start")
                            getattr(host, action)(record["id"])
                            lifecycle = host.lifecycle(record["id"])
                            self.assertFalse(lifecycle["can_resume"])
                            if action == "pause":
                                self.assertEqual(lifecycle["status"], "pausing")
                            else:
                                self.assertEqual(host.store.stop_reason(record["id"]), "stopped by operator")
                            self.assertIsNone(host.store.record(record["id"])["result"])
                            self.assertTrue(all(control.interrupted for control, _ in held.calls.values()))
                            self.assertTrue(thread.is_alive())
                            with self.assertRaises(task_api.TaskControlConflict):
                                host.resume(record["id"], self.config, lifecycle["revision"])
                            self.assertEqual(len(held.calls), count)
                            self.assertFalse(outsider.done())
                            self.assertFalse(outsider_runner.calls["other1"][0].interrupted)
                            self.assertIs(real_observe(outsider_runner.pids["other1"]), False)
                        finally:
                            release.set()
                            thread.join(10)
                            fixture._release(other, "other1")
                        self.assertFalse(thread.is_alive())
                    self.assertEqual(outsider.result(5)[0], {"retained": "other1"})
                    if action == "pause":
                        paused = self._paused(host, record["id"])
                        self.assertTrue(host.lifecycle(record["id"])["can_resume"])
                        host.runner_factory = lambda *_args: SimpleNamespace(call=self.physical)
                        host.resume(record["id"], self.config, paused["revision"])
                    result = self._terminal(host, record["id"])["result"]
                    self.assertEqual(result["status"], "success" if action == "pause" else "failure")
                    fixture.doCleanups()
                    host.store.record_result(other_id, {
                        "status": "success", "native_result": "unrelated call finished",
                        **host.store.lifecycle(other_id)["accounting"],
                    })

    def test_creativity_restart_waits_for_surviving_worker(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                record, host = self.admit(), self.host()
                with mock.patch.object(host.store, "record_result_locked", side_effect=OSError("hold publication")):
                    host.start(record, self.config)
                    self._paused(host, record["id"])
                before, calls = self.checkpoint(record), copy.deepcopy(self.calls)
                worker = cancel_fixture.TaskCancelRecoveryTest._surviving_lease_worker(self, record)
                if cancel:
                    with registry.locked(self.home):
                        host.store.record_stop_locked(record["id"], "cancel before restart")
                fresh = self.host()
                fresh.adopt_open_tasks(lambda _record: self.config)
                self._wait(lambda: fresh.store.lifecycle(record["id"])["status"] == "pausing",
                           "surviving worker did not block settlement")
                self.assertFalse(fresh.lifecycle(record["id"])["can_resume"])
                self.assertIsNone(fresh.store.record(record["id"])["result"])
                self.assertIsNone(worker.poll())
                self.assertTrue(fresh.owns_workspace(self.primary))
                with self.assertRaises(task_api.TaskControlConflict):
                    fresh.resume(record["id"], self.config, fresh.lifecycle(record["id"])["revision"])
                worker.communicate(input=b"release", timeout=5)
                if not cancel:
                    paused = self._paused(fresh, record["id"])
                    self.assertEqual(self.calls, calls)
                    self.assertEqual(self.checkpoint(record), before)
                    fresh.resume(record["id"], self.config, paused["revision"])
                result = self._terminal(fresh, record["id"])["result"]
                self.assertEqual(result["status"], "failure" if cancel else "success")
                self.assertEqual(self.calls, calls)
                self.assertFalse(fresh.owns_workspace(self.primary))

    def test_creativity_ownership_and_deletion(self):
        other, other_host = self.admit(), self.host()
        other_host.start(other, self.config)
        other_record = self._terminal(other_host, other["id"])
        other_checkpoint = self.checkpoint(other)
        host = self.host()
        self.start_server(host)
        self.project("private", self.primary)
        area = dict(self.order()["request"]["work_area"], project="private", work_area="main")
        record = self.admit(work_area=area)
        path = "/api/tasks/" + record["id"]
        kept = os.path.join(self.primary, "keep.md")
        with open(kept, "w") as handle:
            handle.write("Workspace content belongs to the operator.")
        originals = {}
        for filename in [kept] + self.references:
            with open(filename) as handle:
                originals[filename] = handle.read()
        self.assertEqual(self.request("DELETE", path)[0], 409)
        with mock.patch.object(host.store, "record_result_locked", side_effect=OSError("hold publication")):
            host.start(record, self.config)
            self._paused(host, record["id"])
        checkpoint = self.checkpoint(record)
        held = controls_fixture.HeldHost(self.home)
        self.start_server(held)
        status, response = self.request("POST", path + "/pause", {})
        self.assertEqual(status, 200, response)
        paused = response["lifecycle"]
        self.assertTrue(paused["can_resume"])
        self.assertTrue(held.owns_workspace(self.primary))
        for action, body in (("pause", {}), ("resume", {"revision": paused["revision"]}), ("stop", {})):
            self.assertEqual(self.request("POST", path + "/" + action, body, self.member())[0], 403)
        self.assertEqual(self.request("DELETE", path, headers=self.member())[0], 403)
        self.assertEqual(held.lifecycle(record["id"]), paused)
        self.assertEqual(self.request("DELETE", path)[0], 409)
        with mock.patch.object(held, "owns_workspace_except", return_value=True) as owns:
            status, response = self.request("POST", path + "/resume", {"revision": paused["revision"]})
        self.assertEqual((status, response["error"]), (409, service.WORK_AREA_BUSY))
        owns.assert_called_once_with(self.primary, record["id"])
        self.assertEqual(self.request("POST", path + "/resume", {"revision": paused["revision"] - 1})[0], 409)
        self.assertEqual(held.started, [])
        self.assertEqual(self.request("POST", path + "/resume", {"revision": paused["revision"]})[0], 200)
        self.assertEqual(self.request("POST", path + "/resume", {"revision": paused["revision"]})[0], 409)
        self.assertEqual(held.started, [record["id"]])
        self.assertEqual(self.request("DELETE", path)[0], 409)
        self.assertEqual(self.request("POST", path + "/pause", {})[0], 200)
        self.assertEqual(self.checkpoint(record), checkpoint)
        final = self.host()
        final.adopt_open_tasks(lambda _record: self.config)
        self.start_server(final)
        self.assertEqual(self.request("POST", path + "/stop", {})[0], 200)
        result = self._terminal(final, record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        with final._lease(record["id"]):
            status, response = self.request("DELETE", path)
            self.assertEqual(status, 409, response)
            self.assertIn("not quiescent", response["error"])
            self.assertEqual(final.store.record(record["id"])["result"], result)
        self.assertEqual(self.request("DELETE", path)[0], 200)
        self.assertEqual(self.request("GET", path)[0], 404)
        self.assertFalse(os.path.exists(task_api.creativity_checkpoint_store(self.home, record["id"]).directory))
        self.assertEqual(final.store.record(other["id"]), other_record)
        self.assertEqual(self.checkpoint(other), other_checkpoint)
        for filename, content in originals.items():
            with open(filename) as handle:
                self.assertEqual(handle.read(), content)

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
