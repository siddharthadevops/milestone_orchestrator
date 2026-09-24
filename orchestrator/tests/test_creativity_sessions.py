"""Configurable Creativity conversations through the real host and scripted runners.

These checks establish transport, live routing and durable session boundaries;
they make no claim about provider latency or creative quality.
"""

import copy
import threading
import unittest
import uuid
from types import SimpleNamespace

from orchestrator import registry, staffing, task_api
from orchestrator.tests import test_creativity_fragments as fragment_fixture
from orchestrator.tests import test_task_api as api_fixture
from orchestrator.tests.test_staffing_sessions import resolver_doc


class CreativitySessionsTest(unittest.TestCase):
    # Reuse the fragment fixture without inheriting its unrelated test cases.
    creativity_semantics = "fragments_v3"
    order = fragment_fixture.FragmentCreativityTaskTest.order
    admit = fragment_fixture.FragmentCreativityTaskTest.admit
    config = staticmethod(fragment_fixture.FragmentCreativityTaskTest.config)
    checkpoint = fragment_fixture.FragmentCreativityTaskTest.checkpoint
    question_answers = staticmethod(fragment_fixture.FragmentCreativityTaskTest.question_answers)
    physical = fragment_fixture.FragmentCreativityTaskTest.physical
    result = fragment_fixture.FragmentCreativityTaskTest.result
    _wait = fragment_fixture.FragmentCreativityTaskTest._wait
    _paused = fragment_fixture.FragmentCreativityTaskTest._paused
    _terminal = fragment_fixture.FragmentCreativityTaskTest._terminal

    def setUp(self):
        fragment_fixture.FragmentCreativityTaskTest.setUp(self)
        self.session_calls = []
        self.session_lock = threading.Lock()
        self.active_references = set()
        self.max_active_references = 0

    @staticmethod
    def job(prompt):
        return next(line.removeprefix("KIND: ") for line in prompt.splitlines()
                    if line.startswith("KIND: "))

    def session_runner(self, physical):
        def invoke(mode, family, reference, prompt, workspace, execution_context, kwargs):
            with self.session_lock:
                self.session_calls.append({
                    "job": self.job(prompt), "mode": mode, "family": family,
                    "session_ref": reference, "model": kwargs.get("model"),
                    "effort": kwargs.get("effort"), "prompt": prompt,
                })
                if reference is not None:
                    self.assertNotIn(reference, self.active_references)
                    self.active_references.add(reference)
                    self.max_active_references = max(
                        self.max_active_references, len(self.active_references),
                    )
            try:
                result = physical(
                    family, prompt, workspace, execution_context=execution_context, **kwargs,
                )
                result.session_ref = reference
                return result
            finally:
                if reference is not None:
                    with self.session_lock:
                        self.active_references.remove(reference)

        def fresh(family, prompt, workspace, execution_context=None, **kwargs):
            return invoke("fresh", family, None, prompt, workspace, execution_context, kwargs)

        def start(family, prompt, workspace, execution_context=None, **kwargs):
            return invoke("start", family, str(uuid.uuid4()), prompt, workspace, execution_context, kwargs)

        def resume(family, session_ref, prompt, workspace, execution_context=None, **kwargs):
            return invoke("continue", family, session_ref, prompt, workspace, execution_context, kwargs)

        return SimpleNamespace(call=fresh, start_session=start, continue_session=resume)

    def host(self, physical=None):
        return task_api.DirectTaskHost(
            self.home, runner_factory=lambda *_args: self.session_runner(physical or self.physical),
            poll_interval=0.001,
        )

    def admit_sessions(self, **changes):
        configuration = {
            "session_mode": "persistent", "supplied": True, "gene_count": 4,
            "generation_limit": 2, "max_evaluated_candidates": 4,
        }
        configuration.update(changes)
        return self.admit(**configuration)

    def completed(self, host, record):
        result = self._terminal(host, record["id"])
        self.assertEqual(result["result"]["status"], "success", result["result"])
        return result

    def conversations(self, record):
        store = task_api.creativity_checkpoint_store(self.home, record["id"])
        return {item["key"]: item["value"] for item in store.list_entries(
            prefix="conversation:", include_values=True,
        )["items"]}

    def calls_for(self, job):
        return [call for call in self.session_calls if call["job"] == job]

    def test_new_orders_default_to_persistent_session_transport(self):
        record = self.admit(
            supplied=True, gene_count=4, generation_limit=2, max_evaluated_candidates=4,
        )
        self.assertEqual(record["order"]["configuration"]["session_mode"], "persistent")
        host = self.host()
        host.start(record, self.config)
        self.completed(host, record)
        self.assertEqual(set(self.conversations(record)), {
            "conversation:compose_candidates:0", "conversation:evaluate_candidates:0",
        })
        for job in ("compose_candidates", "evaluate_candidates"):
            calls = self.calls_for(job)
            self.assertEqual([call["mode"] for call in calls], ["start", "continue"])
            self.assertEqual(len({call["session_ref"] for call in calls}), 1)

    def test_explicit_fresh_and_old_orders_use_no_session_transport_or_storage(self):
        for omitted in (False, True):
            with self.subTest(legacy_without_field=omitted):
                self.calls.clear()
                self.session_calls.clear()
                record = self.admit_sessions(session_mode="fresh")
                if omitted:
                    del record["order"]["configuration"]["session_mode"]
                    api_fixture.TaskApiTest._age_stored_record(
                        task_api.StandaloneTaskStore(self.home), record,
                    )
                original = copy.deepcopy(record["order"])
                host = self.host()
                host.start(record, self.config)
                terminal = self.completed(host, record)
                self.assertEqual(len(self.session_calls), 4)
                self.assertEqual({call["mode"] for call in self.session_calls}, {"fresh"})
                self.assertTrue(all(call["session_ref"] is None for call in self.session_calls))
                self.assertEqual(self.conversations(record), {})
                self.assertEqual(terminal["order"], original)
                dispatches = [event["physical_dispatch"] for event in host.store.lifecycle(record["id"])["history"]
                              if "physical_dispatch" in event]
                self.assertTrue(all("conversation_slot" not in item["call_context"] for item in dispatches))

    def test_persistent_mode_keeps_generator_composer_and_evaluator_separate(self):
        record = self.admit_sessions(supplied=False)
        host = self.host()
        host.start(record, self.config)
        self.completed(host, record)
        saved = self.conversations(record)
        self.assertEqual(set(saved), {
            "conversation:create_genes:0", "conversation:compose_candidates:0",
            "conversation:evaluate_candidates:0",
        })
        references = set()
        for job in ("create_genes", "compose_candidates", "evaluate_candidates"):
            calls = self.calls_for(job)
            self.assertEqual([call["mode"] for call in calls],
                             ["start"] if job == "create_genes" else ["start", "continue"])
            reference = saved["conversation:%s:0" % job]["session_ref"]
            self.assertEqual({call["session_ref"] for call in calls}, {reference})
            self.assertEqual({call["family"] for call in calls}, {"codex"})
            references.add(reference)
        self.assertEqual(len(references), 3)

    def test_parallel_batches_have_stable_disjoint_slots_without_active_ref_reuse(self):
        record = self.admit_sessions(
            population_size=4, evaluation_batch_size=2, evaluation_concurrency=2,
            max_evaluated_candidates=8,
        )
        barriers = {job: threading.Barrier(2) for job in ("compose_candidates", "evaluate_candidates")}

        def overlap_calls(family, prompt, workspace, **kwargs):
            result = self.physical(family, prompt, workspace, **kwargs)
            barriers[self.job(prompt)].wait(5)
            return result

        host = self.host(overlap_calls)
        host.start(record, self.config)
        self.completed(host, record)
        saved = self.conversations(record)
        self.assertEqual(set(saved), {
            "conversation:%s:%d" % (job, slot)
            for job in barriers for slot in (0, 1)
        })
        self.assertEqual(len({item["session_ref"] for item in saved.values()}), 4)
        self.assertGreaterEqual(self.max_active_references, 2)
        self.assertEqual(self.active_references, set())
        for key, conversation in saved.items():
            calls = [call for call in self.session_calls if call["session_ref"] == conversation["session_ref"]]
            self.assertEqual([call["mode"] for call in calls], ["start", "continue"], key)
            self.assertEqual({call["job"] for call in calls}, {key.split(":")[1]})
        dispatches = [event["physical_dispatch"] for event in host.store.lifecycle(record["id"])["history"]
                      if "physical_dispatch" in event]
        for job in barriers:
            slots = [item["call_context"]["conversation_slot"] for item in dispatches
                     if item["call_context"]["job"] == job]
            self.assertEqual(sorted(slots), [0, 0, 1, 1])

    def test_new_host_resumes_saved_conversations_without_repeating_accepted_calls(self):
        record = self.admit_sessions()

        def pause_after_first_evaluation(family, prompt, workspace, **kwargs):
            result = self.physical(family, prompt, workspace, **kwargs)
            if self.job(prompt) == "evaluate_candidates":
                host.pause(record["id"])
            return result

        host = self.host(pause_after_first_evaluation)
        host.start(record, self.config)
        paused = self._paused(host, record["id"])
        original = self.conversations(record)
        self.assertEqual(len(self.session_calls), 2)
        resumed = self.host()
        resumed.resume(record["id"], self.config, paused["revision"])
        self.completed(resumed, record)
        self.assertEqual(len(self.session_calls), 4)
        for job in ("compose_candidates", "evaluate_candidates"):
            calls = self.calls_for(job)
            self.assertEqual([call["mode"] for call in calls], ["start", "continue"])
            self.assertEqual({call["session_ref"] for call in calls}, {
                original["conversation:%s:0" % job]["session_ref"],
            })
        self.assertEqual(self.checkpoint(record)["evaluation"]["accepted_count"], 4)

    def test_live_rigor_and_model_changes_keep_same_family_conversations(self):
        document = resolver_doc()
        for role in ("brainstorm", "review"):
            document["tuning"]["high"]["2"][role] = [3, 4]
        staffing.save(self.home, document)
        record = self.admit_sessions(rigor={"default": "low"})
        original_order = copy.deepcopy(record["order"])

        def raise_rigor_after_evaluation(family, prompt, workspace, **kwargs):
            result = self.physical(family, prompt, workspace, **kwargs)
            if self.job(prompt) == "evaluate_candidates":
                with registry.locked(self.home):
                    host.store.set_creativity_rigor_locked(record["id"], {"default": "high"})
            return result

        host = self.host(raise_rigor_after_evaluation)
        host.start(record, self.config)
        terminal = self.completed(host, record)
        self.assertEqual(terminal["order"], original_order)
        for job in ("compose_candidates", "evaluate_candidates"):
            calls = self.calls_for(job)
            self.assertEqual([call["mode"] for call in calls], ["start", "continue"])
            self.assertEqual(len({call["session_ref"] for call in calls}), 1)
            self.assertEqual([(call["family"], call["model"], call["effort"]) for call in calls], [
                ("codex", "gpt-5.6-luna", "low"), ("codex", "gpt-5.6-sol", "xhigh"),
            ])

    def test_family_changes_start_only_the_changed_job_fresh(self):
        record = self.admit_sessions(generation_limit=3, max_evaluated_candidates=6)
        evaluations = 0

        def change_composer_family(family, prompt, workspace, **kwargs):
            nonlocal evaluations
            result = self.physical(family, prompt, workspace, **kwargs)
            if self.job(prompt) == "evaluate_candidates":
                evaluations += 1
                document = resolver_doc()
                document["assignment"]["brainstorm"]["1"] = 3 if evaluations == 1 else 2
                staffing.save(self.home, document)
            return result

        host = self.host(change_composer_family)
        host.start(record, self.config)
        self.completed(host, record)
        composed = self.calls_for("compose_candidates")
        self.assertEqual([call["family"] for call in composed], ["codex", "claude", "codex"])
        self.assertEqual([call["mode"] for call in composed], ["start", "start", "start"])
        self.assertEqual(len({call["session_ref"] for call in composed}), 3)
        evaluated = self.calls_for("evaluate_candidates")
        self.assertEqual([call["mode"] for call in evaluated], ["start", "continue", "continue"])
        self.assertEqual(len({call["session_ref"] for call in evaluated}), 1)
        self.assertTrue({call["session_ref"] for call in composed}.isdisjoint(
            call["session_ref"] for call in evaluated
        ))

    def test_exhausted_contract_correction_keeps_session_for_operator_resume(self):
        record = self.admit_sessions(generation_limit=1, max_evaluated_candidates=2)

        def malformed_evaluation(family, prompt, workspace, **kwargs):
            result = self.physical(family, prompt, workspace, **kwargs)
            if self.job(prompt) == "evaluate_candidates":
                result.text = "This is not the evaluation contract."
            return result

        host = self.host(malformed_evaluation)
        host.start(record, self.config)
        paused = self._paused(host, record["id"])
        self.assertEqual(paused["source"], "error")
        evaluated = self.calls_for("evaluate_candidates")
        self.assertEqual([call["mode"] for call in evaluated], ["start", "continue"])
        reference = self.conversations(record)["conversation:evaluate_candidates:0"]["session_ref"]
        self.assertEqual({call["session_ref"] for call in evaluated}, {reference})
        self.assertEqual(self.checkpoint(record)["evaluation"]["accepted_count"], 0)
        resumed = self.host()
        resumed.resume(record["id"], self.config, paused["revision"])
        self.completed(resumed, record)
        evaluated = self.calls_for("evaluate_candidates")
        self.assertEqual([call["mode"] for call in evaluated], ["start", "continue", "continue"])
        self.assertEqual({call["session_ref"] for call in evaluated}, {reference})
        self.assertEqual(len(self.calls_for("compose_candidates")), 1)


if __name__ == "__main__":
    unittest.main()
