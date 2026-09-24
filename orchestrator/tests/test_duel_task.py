"""Duel keeps both document candidates and improves only unfinished authors."""

from collections import Counter
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
import uuid
from types import SimpleNamespace
from urllib.parse import urlencode

from orchestrator import duel, prompt_sets, runners, staffing, task_api
from orchestrator.tests import test_task_api as api_fixture
from orchestrator.tests import test_task_recovery as recovery_fixture
from orchestrator.tests.test_staffing_sessions import resolver_doc, session_body


QUESTION_SENTINEL = "CONTEXT_SEARCH_ANSWER_NOT_A_DRIVER_DECISION"
REVIEW_CONTEXT_FINDING = (
    "Have you preserved the original request instead of broadening it? "
    "The draft adds an unsupported objective; remove it."
)


class DuelTaskTest(unittest.TestCase):
    order = api_fixture.TaskApiTest.order
    start_server = api_fixture.TaskApiTest.start_server
    request = api_fixture.TaskApiTest.request
    _wait = recovery_fixture.TaskRecoveryTest._wait
    _paused = recovery_fixture.TaskRecoveryTest._paused
    _terminal = recovery_fixture.TaskRecoveryTest._terminal

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="duel-task-")
        self.addCleanup(temporary.cleanup)
        self.home = os.path.join(temporary.name, "home")
        self.primary = os.path.join(temporary.name, "workspace")
        self.additional = os.path.join(temporary.name, "references")
        os.makedirs(self.primary)
        os.makedirs(self.additional)
        self.reference = os.path.join(self.additional, "brief.md")
        with open(self.reference, "w", encoding="utf-8") as handle:
            handle.write("The common source material for both authors.")
        staffing.save(self.home, resolver_doc())
        self.session = staffing.create_session(
            self.home, session_body(document="matrix"),
        )["id"]
        prompt_sets.ensure_default(self.home)
        self.calls = []
        self.session_calls = []
        self.lock = threading.Lock()
        self.finish_round = {}
        self.documents = {"a": ["draft.md"], "b": ["draft.md"]}

    @staticmethod
    def config():
        return {"billing": {"codex": "api", "claude": "api"}}

    def admit(self, max_rounds=1, output_directory=None, **options):
        order = self.order(
            "duel", request="Write a proposal supported by the shared brief.",
            reference_documents=[self.reference],
        )
        order.update(
            staffing_session=self.session,
            prompt_set="default",
            configuration={"max_rounds": max_rounds},
        )
        order.update(options)
        if output_directory is not None:
            order["request"]["output_directory"] = output_directory
        return task_api.StandaloneTaskStore(self.home).admit(order, {}, self.primary)

    def host(self, physical=None):
        return task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda *_args: self.session_runner(physical or self.physical),
            poll_interval=0.001,
        )

    def session_runner(self, physical):
        def invoke(mode, family, session_ref, prompt, workspace, execution_context, kwargs):
            call = self.call_info(prompt)
            with self.lock:
                self.session_calls.append(dict(
                    call, mode=mode, family=family, session_ref=session_ref,
                ))
            result = physical(
                family, prompt, workspace, execution_context=execution_context, **kwargs,
            )
            result.session_ref = session_ref
            return result

        def start(family, prompt, workspace, execution_context=None, **kwargs):
            return invoke(
                "start", family, str(uuid.uuid4()), prompt, workspace, execution_context, kwargs,
            )

        def resume(family, session_ref, prompt, workspace, execution_context=None, **kwargs):
            return invoke(
                "continue", family, session_ref, prompt, workspace, execution_context, kwargs,
            )

        return SimpleNamespace(call=physical, start_session=start, continue_session=resume)

    def checkpoint(self, record):
        return task_api.duel_checkpoint_store(self.home, record["id"]).get("checkpoint")

    @staticmethod
    def prompt_value(prompt, key):
        prefix = key + ": "
        return next(line[len(prefix):] for line in prompt.splitlines() if line.startswith(prefix))

    @staticmethod
    def question_answers(prompt):
        if "QUESTIONS (" not in prompt:
            return []
        block = prompt.split("QUESTIONS (", 1)[1].split("\n\n", 1)[0]
        return [
            {"id": line[2:].split(":", 1)[0], "answer": QUESTION_SENTINEL}
            for line in block.splitlines() if line.startswith("- ")
        ]

    def call_info(self, prompt):
        kind = self.prompt_value(prompt, "KIND")
        call = {
            "kind": kind,
            "round": int(self.prompt_value(prompt, "round")),
        }
        if kind == "duel_author":
            call.update(
                id=self.prompt_value(prompt, "candidate_id"),
                directory=self.prompt_value(prompt, "candidate_directory"),
            )
        else:
            candidates = prompt.split("CANDIDATES (JSON):\n", 1)[1].splitlines()[0]
            call.update(id="both", candidates=json.loads(candidates))
        return call

    @staticmethod
    def runner_result(reply):
        usage = {"input_tokens": 10, "output_tokens": 2}
        return runners.RunnerResult(
            json.dumps(reply), 0, 1.0,
            token_usage=usage, cost_payloads=[dict(usage, total_cost_usd=0.02)],
        )

    def physical(self, family, prompt, workspace, execution_context=None, **kwargs):
        call = self.call_info(prompt)
        call.update(
            family=family, prompt=prompt, execution_context=execution_context,
            model=kwargs.get("model"), effort=kwargs.get("effort"),
        )
        with self.lock:
            self.calls.append(call)
        self.assertEqual(workspace, self.primary)
        self.assertEqual(call["effort"], "max")
        questions = self.question_answers(prompt)
        self.assertTrue(questions, "Duel must have its own context-search questions")
        if call["kind"] == "duel_author":
            finish = call["round"] >= self.finish_round.get(call["id"], 1000)
            artifacts = self.documents[call["id"]]
            for relative in [] if finish else artifacts:
                path = os.path.join(call["directory"], relative)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("Candidate %s, production round %s.\n" % (call["id"], call["round"]))
            reply = {
                "action": "finish" if finish else "revise",
                "artifacts": artifacts,
                "summary": "Finished." if finish else "Revised the documents.",
                "questions": questions,
            }
        else:
            self.assertEqual(call["kind"], "duel_review")
            self.assertEqual({item["id"] for item in call["candidates"]}, {"a", "b"})
            for candidate in call["candidates"]:
                for artifact in candidate["artifacts"]:
                    self.assertFalse(os.path.isabs(artifact))
                    self.assertTrue(os.path.isfile(os.path.join(candidate["directory"], artifact)))
            reply = {
                "scores": {"a": 0.75, "b": 0.65},
                "report": "# Shared review\n\nRound %s: substantiate the weakest premise.\n\n%s\n" % (
                    call["round"], REVIEW_CONTEXT_FINDING,
                ),
                "questions": questions,
            }
        return self.runner_result(reply)

    def completed(self, host, record):
        self._wait(lambda: not host.is_active(record["id"]), "duel did not settle")
        saved = host.store.record(record["id"])
        self.assertIsNotNone(saved["result"], host.lifecycle(record["id"]))
        self.assertEqual(saved["result"]["status"], "success", saved["result"])
        return saved["result"]["native_result"]

    def call_counts(self):
        return Counter((call["kind"], call["id"]) for call in self.calls)

    def assert_max_effort_receipts(self, host, record):
        receipts = [
            event["physical_dispatch"]
            for event in host.store.lifecycle(record["id"])["history"]
            if "physical_dispatch" in event
        ]
        self.assertEqual(len(receipts), 3)
        expected = {
            ("author_candidate" if call["kind"] == "duel_author" else "review_candidate", call["id"]):
            (call["family"], call["model"], "max")
            for call in self.calls
        }
        actual = {}
        for dispatch in receipts:
            self.assertEqual(dispatch["effort"], "max")
            self.assertIsNone(dispatch["prompt_set_fallback"])
            context = dispatch["call_context"]
            actual[(context["job"], context["candidate_id"])] = (
                dispatch["family"], dispatch["model"], dispatch["effort"],
            )
        self.assertEqual(actual, expected)

    def test_one_round_produces_in_parallel_then_reviews_both_together(self):
        author_barrier = threading.Barrier(2)
        self.documents["a"] = ["draft.md", "appendix/evidence.md"]

        def parallel(family, prompt, workspace, **kwargs):
            call = self.call_info(prompt)
            if call["kind"] == "duel_author":
                author_barrier.wait(timeout=5)
            else:
                self.assertEqual(sum(item["kind"] == "duel_author" for item in self.calls), 2)
                self.assertEqual(set(self.checkpoint(record)["rounds"][0]["authors"]), {"a", "b"})
            return self.physical(family, prompt, workspace, **kwargs)

        record, host = self.admit(), self.host(parallel)
        host.start(record, self.config)
        native = self.completed(host, record)
        self.assertEqual(native["stop_reason"], "round_limit")
        self.assertEqual(native["rounds_completed"], 1)
        self.assertEqual(self.call_counts(), Counter({
            ("duel_author", "a"): 1, ("duel_author", "b"): 1,
            ("duel_review", "both"): 1,
        }))
        self.assertEqual({item["id"] for item in native["candidates"]}, {"a", "b"})
        for candidate in native["candidates"]:
            self.assertEqual(candidate["directory"], os.path.realpath(os.path.join(
                self.primary, "implementation", "duel", record["id"], candidate["id"],
            )))
            self.assertEqual(len(candidate["artifacts"]), len(self.documents[candidate["id"]]))
            self.assertFalse(candidate["finished"])
            self.assertEqual(candidate["production_round"], 1)
            self.assertEqual(candidate["review_round"], 1)
            self.assertEqual(candidate["score"], {"a": 0.75, "b": 0.65}[candidate["id"]])
            for path in candidate["artifacts"]:
                self.assertTrue(os.path.isabs(path))
                with open(path, encoding="utf-8") as handle:
                    self.assertIn("production round 1", handle.read())
            with open(candidate["report_path"], encoding="utf-8") as handle:
                self.assertIn("substantiate the weakest premise", handle.read())
        reports = {item["report_path"] for item in native["candidates"]}
        self.assertEqual(len(reports), 1)
        report = Path(reports.pop())
        self.assertEqual(report.name, "review.md")
        self.assertEqual(list(report.parent.iterdir()), [report])
        reviews = native["rounds"][0]["reviews"]
        self.assertEqual(set(reviews), {"a", "b"})
        self.assertEqual(reviews["a"]["call_id"], reviews["b"]["call_id"])
        for call in self.calls:
            self.assertIn(record["order"]["request"]["request"], call["prompt"])
            self.assertIn(self.reference, call["prompt"])
            self.assertEqual(call["execution_context"]["additional"], [{"path": self.additional}])

    def test_finished_candidate_keeps_its_version_while_other_continues(self):
        self.finish_round = {"a": 2}
        record, host = self.admit(max_rounds=3), self.host()
        host.start(record, self.config)
        native = self.completed(host, record)
        self.assertEqual(native["stop_reason"], "round_limit")
        self.assertEqual(native["rounds_completed"], 3)
        self.assertEqual(self.call_counts(), Counter({
            ("duel_author", "a"): 2, ("duel_author", "b"): 3,
            ("duel_review", "both"): 3,
        }))
        candidates = {item["id"]: item for item in native["candidates"]}
        self.assertTrue(candidates["a"]["finished"])
        self.assertFalse(candidates["b"]["finished"])
        for identity, expected_round in (("a", 1), ("b", 3)):
            candidate = candidates[identity]
            self.assertEqual(candidate["production_round"], expected_round)
            self.assertEqual(candidate["review_round"], 3)
            with open(candidate["artifacts"][0], encoding="utf-8") as handle:
                self.assertIn("production round %s" % expected_round, handle.read())
        for call in self.calls:
            if call["kind"] == "duel_review" and call["round"] > 1:
                a = next(item for item in call["candidates"] if item["id"] == "a")
                self.assertTrue(a["finished"])
                self.assertEqual(a["production_round"], 1)
        for call in self.calls:
            if call["kind"] == "duel_author" and call["round"] > 1:
                other = "b" if call["id"] == "a" else "a"
                self.assertIn(candidates[other]["directory"], call["prompt"])
                self.assertIn("reports", call["prompt"])

    def test_custom_output_directory_contains_both_deliveries(self):
        output_directory = os.path.realpath(os.path.join(self.primary, "requested outputs"))
        record, host = self.admit(output_directory=output_directory), self.host()
        host.start(record, self.config)
        native = self.completed(host, record)
        for candidate in native["candidates"]:
            self.assertEqual(candidate["directory"], os.path.join(output_directory, candidate["id"]))
            self.assertEqual(os.path.commonpath([
                candidate["report_path"], os.path.join(output_directory, "reports"),
            ]), os.path.join(output_directory, "reports"))

    def test_joint_reviewer_can_use_the_only_available_family(self):
        self.session = staffing.create_session(
            self.home, session_body(document="matrix", families=["codex"]),
        )["id"]
        record, host = self.admit(), self.host()
        host.start(record, self.config)
        self.completed(host, record)
        reviews = [call for call in self.calls if call["kind"] == "duel_review"]
        self.assertEqual(len(reviews), 1)
        self.assertEqual({call["family"] for call in reviews}, {"codex"})

    def test_default_staffing_uses_one_codex_reviewer_seat_for_both_candidates(self):
        seed = staffing.default_document_seed()
        staffing.save(self.home, seed)
        shutil.copytree(
            Path(__file__).resolve().parents[2] / "prompt_sets" / "literature",
            prompt_sets.prompt_set_dir(self.home, "literature"),
        )
        prompt_sets.load(self.home, "literature")
        for prompt_set in ("default", "literature"):
            for rigor in ("low", "medium", "high"):
                with self.subTest(prompt_set=prompt_set, rigor=rigor):
                    self.calls.clear()
                    self.session = staffing.create_session(self.home, session_body(
                        document="default", rigor=rigor, families=["codex", "claude"],
                        **({"material": "literature"} if prompt_set == "literature" else {}),
                    ))["id"]
                    record = self.admit(prompt_set=prompt_set)
                    host = self.host()
                    host.start(record, self.config)
                    self.completed(host, record)
                    self.assert_max_effort_receipts(host, record)
                    reviews = [call for call in self.calls if call["kind"] == "duel_review"]
                    self.assertEqual({call["id"] for call in reviews}, {"both"})
                    expected_review = staffing.base_staffing(seed, rigor, "review", 1)[:2] + ("max",)
                    self.assertEqual(expected_review[0], "codex")
                    self.assertEqual({
                        (call["family"], call["model"], call["effort"]) for call in reviews
                    }, {expected_review})
                    authors = {call["id"]: call for call in self.calls if call["kind"] == "duel_author"}
                    self.assertEqual(set(authors), {"a", "b"})
                    for identity, index in (("a", 1), ("b", 2)):
                        call = authors[identity]
                        self.assertEqual(
                            (call["family"], call["model"], call["effort"]),
                            staffing.base_staffing(seed, rigor, "brainstorm", index)[:2] + ("max",),
                        )
                    if prompt_set == "literature":
                        for call in self.calls:
                            self.assertIn("LITERATURE:", call["prompt"])
                            role = "author" if call["kind"] == "duel_author" else "review"
                            self.assertIn(role + "_literary_voice", call["prompt"])

    def test_reviewer_rigor_override_applies_equally_without_changing_authors(self):
        seed = staffing.default_document_seed()
        staffing.save(self.home, seed)
        self.session = staffing.create_session(self.home, session_body(
            document="default", rigor="low", families=["codex", "claude"],
        ))["id"]
        record = self.admit(configuration={"max_rounds": 1, "rigor": {"reviewer": "high"}})
        host = self.host()
        host.start(record, self.config)
        self.completed(host, record)
        self.assert_max_effort_receipts(host, record)
        for call in self.calls:
            expected = (
                staffing.base_staffing(seed, "high", "review", 1)
                if call["kind"] == "duel_review" else
                staffing.base_staffing(seed, "low", "brainstorm", {"a": 1, "b": 2}[call["id"]])
            )
            self.assertEqual((call["family"], call["model"], call["effort"]), expected[:2] + ("max",))
        self.assertEqual(self.call_counts(), Counter({
            ("duel_author", "a"): 1, ("duel_author", "b"): 1,
            ("duel_review", "both"): 1,
        }))

    def test_both_finish_before_round_limit_without_repeated_reviews(self):
        self.finish_round = {"a": 2, "b": 2}
        record, host = self.admit(max_rounds=7), self.host()
        host.start(record, self.config)
        native = self.completed(host, record)
        self.assertEqual(native["stop_reason"], "both_finished")
        self.assertEqual(native["rounds_completed"], 2)
        self.assertTrue(all(item["finished"] for item in native["candidates"]))
        self.assertEqual(self.call_counts(), Counter({
            ("duel_author", "a"): 2, ("duel_author", "b"): 2,
            ("duel_review", "both"): 1,
        }))

    def test_context_question_answers_are_discarded_after_validation(self):
        record, host = self.admit(), self.host()
        host.start(record, self.config)
        native = self.completed(host, record)
        self.assertNotIn(QUESTION_SENTINEL, json.dumps(native))
        self.assertNotIn(QUESTION_SENTINEL, json.dumps(self.checkpoint(record)))

    def test_all_three_seats_keep_separate_conversations_even_with_the_same_family(self):
        self.session = staffing.create_session(
            self.home, session_body(document="matrix", families=["codex"]),
        )["id"]
        record, host = self.admit(max_rounds=3), self.host()
        host.start(record, self.config)
        self.completed(host, record)
        references = set()
        store = task_api.duel_checkpoint_store(self.home, record["id"])
        for kind, identity, job in (
            ("duel_author", "a", "author_candidate"),
            ("duel_author", "b", "author_candidate"),
            ("duel_review", "both", "review_candidate"),
        ):
            calls = [
                call for call in self.session_calls
                if (call["kind"], call["id"]) == (kind, identity)
            ]
            self.assertEqual([call["round"] for call in calls], [1, 2, 3])
            self.assertEqual([call["mode"] for call in calls], ["start", "continue", "continue"])
            self.assertEqual({call["family"] for call in calls}, {"codex"})
            self.assertEqual(len({call["session_ref"] for call in calls}), 1)
            reference = calls[0]["session_ref"]
            references.add(reference)
            saved = store.get("conversation:%s:%s" % (job, identity))
            self.assertEqual(saved["family"], "codex")
            self.assertEqual(saved["session_ref"], reference)
        self.assertEqual(len(references), 3)

    def test_new_runner_resumes_all_conversations_with_the_latest_prompts(self):
        record = self.admit(max_rounds=2)

        def pause_after_first_review(family, prompt, workspace, **kwargs):
            result = self.physical(family, prompt, workspace, **kwargs)
            call = self.call_info(prompt)
            if call["kind"] == "duel_review" and call["round"] == 1:
                host.pause(record["id"])
            return result

        host = self.host(pause_after_first_review)
        host.start(record, self.config)
        paused = self._paused(host, record["id"])
        self.assertEqual(len(self.session_calls), 3)
        original = {
            (call["kind"], call["id"]): call["session_ref"]
            for call in self.session_calls
        }
        marker = "Updated live instructions apply to this continuation."
        for kind in ("duel_author", "duel_review"):
            path = Path(prompt_sets.prompt_set_dir(self.home, "default")) / "duel" / (kind + ".json")
            document = json.loads(path.read_text(encoding="utf-8"))
            document["instructions"]["parts"].append({"text": [marker], "variables": []})
            path.write_text(json.dumps(document), encoding="utf-8")
        prompt_sets.load(self.home, "default")

        resumed = self.host()
        resumed.resume(record["id"], self.config, paused["revision"])
        self.completed(resumed, record)
        self.assertEqual(len(self.session_calls), 6)
        for call in self.session_calls[3:]:
            self.assertEqual(call["round"], 2)
            self.assertEqual(call["mode"], "continue")
            self.assertEqual(call["session_ref"], original[(call["kind"], call["id"])])
        for call in self.calls:
            if call["round"] == 2:
                self.assertIn(marker, call["prompt"])
            else:
                self.assertNotIn(marker, call["prompt"])

    def test_codex_accounting_keeps_turn_deltas_after_a_new_host_resumes(self):
        self.session = staffing.create_session(
            self.home, session_body(document="matrix", families=["codex"]),
        )["id"]
        record = self.admit(max_rounds=2)
        test = self

        class CumulativeRunner(runners.SubprocessRunner):
            def __init__(self):
                super().__init__(
                    {"codex": ["codex", "exec", "--output-last-message", "{output_file}"]},
                    {}, participant_process_factory=lambda *args: None,
                )

            def _call_prepared(self, family, prompt, workspace, _template, model, effort,
                               _timeout, execution_context, _control, **kwargs):
                result = test.physical(
                    family, prompt, workspace, model=model, effort=effort,
                    execution_context=execution_context,
                )
                call = test.call_info(prompt)
                result.session_ref = kwargs.get("session_ref") or str(uuid.uuid4())
                result.token_usage = runners.normalize_token_usage({
                    "input_tokens": 10 * call["round"], "output_tokens": 2 * call["round"],
                })
                result.cost_payloads = [dict(result.token_usage)]
                if call["kind"] == "duel_review" and call["round"] == 1:
                    host.pause(record["id"])
                return result

        def new_host():
            return task_api.DirectTaskHost(
                self.home, runner_factory=lambda *_args: CumulativeRunner(), poll_interval=0.001,
            )

        host = new_host()
        host.start(record, self.config)
        paused = self._paused(host, record["id"])
        host = new_host()
        host.resume(record["id"], self.config, paused["revision"])
        self.completed(host, record)
        receipts = [
            event["physical_dispatch"] for event in host.store.lifecycle(record["id"])["history"]
            if "physical_dispatch" in event
        ]
        self.assertEqual(len(receipts), 6)
        for receipt in receipts:
            self.assertEqual(receipt["token_usage"]["total_tokens"], 12)
            self.assertEqual(receipt["cost_payloads"][0]["input_tokens"], 10)
            self.assertEqual(receipt["cost_payloads"][0]["output_tokens"], 2)

    def test_changing_one_seats_family_starts_fresh_without_crossing_conversations(self):
        record = self.admit(max_rounds=3)

        def change_next_author_family(family, prompt, workspace, **kwargs):
            result = self.physical(family, prompt, workspace, **kwargs)
            call = self.call_info(prompt)
            if call["kind"] == "duel_review" and call["round"] < 3:
                document = resolver_doc()
                document["assignment"]["brainstorm"]["1"] = 3 if call["round"] == 1 else 2
                staffing.save(self.home, document)
            return result

        host = self.host(change_next_author_family)
        host.start(record, self.config)
        self.completed(host, record)
        a = [call for call in self.session_calls if call["id"] == "a"]
        self.assertEqual([call["family"] for call in a], ["codex", "claude", "codex"])
        self.assertEqual([call["mode"] for call in a], ["start", "start", "start"])
        self.assertEqual(len({call["session_ref"] for call in a}), 3)
        for identity in ("b", "both"):
            calls = [call for call in self.session_calls if call["id"] == identity]
            self.assertEqual([call["mode"] for call in calls], ["start", "continue", "continue"])
            self.assertEqual(len({call["session_ref"] for call in calls}), 1)
            self.assertTrue({call["session_ref"] for call in a}.isdisjoint(
                call["session_ref"] for call in calls
            ))

    def test_invalid_review_preserves_its_conversation_for_operator_resume(self):
        record = self.admit()
        invalid = threading.Event()

        def malformed_once(family, prompt, workspace, **kwargs):
            result = self.physical(family, prompt, workspace, **kwargs)
            if self.call_info(prompt)["kind"] == "duel_review" and not invalid.is_set():
                invalid.set()
                result.text = "This review does not satisfy the output contract."
            return result

        host = self.host(malformed_once)
        host.start(record, self.config)
        paused = self._paused(host, record["id"])
        self.assertEqual(self.call_counts()[("duel_review", "both")], 1)
        first = next(call for call in self.session_calls if call["id"] == "both")
        saved = task_api.duel_checkpoint_store(self.home, record["id"]).get(
            "conversation:review_candidate:both",
        )
        self.assertEqual(saved["session_ref"], first["session_ref"])
        self.assertEqual(self.checkpoint(record)["rounds"][0]["reviews"], {})

        resumed = self.host()
        resumed.resume(record["id"], self.config, paused["revision"])
        self.completed(resumed, record)
        reviews = [call for call in self.session_calls if call["id"] == "both"]
        self.assertEqual([call["mode"] for call in reviews], ["start", "continue"])
        self.assertEqual(reviews[1]["session_ref"], first["session_ref"])
        self.assertEqual(self.call_counts(), Counter({
            ("duel_author", "a"): 1, ("duel_author", "b"): 1,
            ("duel_review", "both"): 2,
        }))

    def test_review_findings_are_available_to_authors_in_the_next_round(self):
        record = self.admit(max_rounds=2)
        checked_authors = set()

        def read_previous_reviews(family, prompt, workspace, **kwargs):
            call = self.call_info(prompt)
            if call["kind"] == "duel_author" and call["round"] == 2:
                previous = self.checkpoint(record)["candidates"]
                self.assertEqual(len(previous), 2)
                self.assertEqual(len({item["report_path"] for item in previous}), 1)
                for candidate in previous:
                    self.assertEqual(candidate["review_round"], 1)
                    self.assertIn(candidate["report_path"], prompt)
                    with open(candidate["report_path"], encoding="utf-8") as handle:
                        self.assertIn(REVIEW_CONTEXT_FINDING, handle.read())
                with self.lock:
                    checked_authors.add(call["id"])
            return self.physical(family, prompt, workspace, **kwargs)

        host = self.host(read_previous_reviews)
        host.start(record, self.config)
        self.completed(host, record)
        self.assertEqual(checked_authors, {"a", "b"})

    def test_public_task_detail_exposes_both_candidates_and_shared_report(self):
        record, host = self.admit(), self.host()
        self.start_server(host)
        path = "/api/tasks/" + record["id"]
        status, admitted = self.request("GET", path)
        self.assertEqual(status, 200, admitted)
        self.assertIsNone(admitted["duel"])
        host.start(record, self.config)
        native = self.completed(host, record)
        status, completed = self.request("GET", path)
        self.assertEqual(status, 200, completed)
        self.assertEqual(completed["duel"]["phase"], "complete")
        self.assertEqual(completed["duel"]["candidates"], native["candidates"])
        self.assertEqual(completed["duel"]["rounds"], native["rounds"])
        self.assertEqual(completed["duel"]["stop_reason"], "round_limit")
        self.assertNotIn(QUESTION_SENTINEL, json.dumps(completed["duel"]))
        self.assertEqual(len({item["report_path"] for item in native["candidates"]}), 1)
        for candidate in native["candidates"]:
            for item, recorded_path, expected in (
                ("artifact:0", candidate["artifacts"][0], "Candidate %s, production round 1" % candidate["id"]),
                ("report", candidate["report_path"], REVIEW_CONTEXT_FINDING),
            ):
                unit = "duel:%s:%s" % (candidate["id"], item)
                status, document = self.request("GET", path + "/artifact?" + urlencode({"unit": unit}))
                self.assertEqual(status, 200, document)
                self.assertEqual(document["unit"], unit)
                self.assertEqual(document["path"], recorded_path)
                self.assertFalse(document["truncated"])
                self.assertIn(expected, document["content"])
        for unknown in (
            "duel:unknown:artifact:0", "duel:a:artifact:99",
            "duel:a:artifact:../../references/brief.md", self.reference,
        ):
            status, refused = self.request("GET", path + "/artifact?" + urlencode({"unit": unknown}))
            self.assertEqual(status, 404, refused)

    def test_claimed_artifact_must_exist_before_review(self):
        def missing_artifact(family, prompt, workspace, **kwargs):
            result = self.physical(family, prompt, workspace, **kwargs)
            call = self.call_info(prompt)
            if call["kind"] == "duel_author" and call["id"] == "a":
                os.remove(os.path.join(call["directory"], "draft.md"))
            return result

        record, host = self.admit(), self.host(missing_artifact)
        host.start(record, self.config)
        paused = self._paused(host, record["id"])
        self.assertIsNone(host.store.record(record["id"])["result"])
        self.assertIn("draft.md", paused["reason"])
        self.assertEqual(self.call_counts()[("duel_author", "a")], 1)
        self.assertFalse(any(call["kind"] == "duel_review" for call in self.calls))

    def test_failed_review_resumes_without_repeating_accepted_work(self):
        record = self.admit()
        legacy_output = os.path.realpath(os.path.join(self.primary, "duel", record["id"]))
        legacy_record = copy.deepcopy(record)
        legacy_record["order"]["request"]["output_directory"] = legacy_output
        task_api.duel_checkpoint_store(self.home, record["id"]).put(
            "checkpoint", duel.new_checkpoint(legacy_record, self.primary),
        )
        failed = threading.Event()

        def failed_joint_review(family, prompt, workspace, **kwargs):
            call = self.call_info(prompt)
            if call["kind"] == "duel_review" and not failed.is_set():
                self.assertEqual(set(self.checkpoint(record)["rounds"][0]["authors"]), {"a", "b"})
                failed.set()
                with self.lock:
                    self.calls.append(call)
                raise runners.RunnerError("review provider disconnected")
            return self.physical(family, prompt, workspace, **kwargs)

        host = self.host(failed_joint_review)
        host.start(record, self.config)
        paused = self._paused(host, record["id"])
        self.assertTrue(failed.is_set())
        host = self.host(failed_joint_review)
        host.resume(record["id"], self.config, paused["revision"])
        native = self.completed(host, record)
        self.assertEqual(native["stop_reason"], "round_limit")
        self.assertEqual(self.checkpoint(record)["output_directory"], legacy_output)
        self.assertFalse(os.path.exists(os.path.join(self.primary, "implementation", "duel")))
        for candidate in native["candidates"]:
            self.assertEqual(candidate["directory"], os.path.join(legacy_output, candidate["id"]))
            self.assertEqual(os.path.commonpath([
                candidate["report_path"], legacy_output,
            ]), legacy_output)
        self.assertEqual(self.call_counts(), Counter({
            ("duel_author", "a"): 1, ("duel_author", "b"): 1,
            ("duel_review", "both"): 2,
        }))

    def test_accepted_legacy_reviews_are_not_repeated_or_rewritten(self):
        record, host = self.admit(max_rounds=2), self.host()
        checkpoint = duel.new_checkpoint(record, self.primary)
        checkpoint.update(round=2, phase="review", rounds_completed=1)
        checkpoint["rounds"].append({"round": 2, "authors": {}, "reviews": {}})
        for candidate in checkpoint["candidates"]:
            identity = candidate["id"]
            production_round = 1 if identity == "a" else 2
            artifact = Path(candidate["directory"]) / "draft.md"
            artifact.write_text("Legacy candidate " + identity, encoding="utf-8")
            report = Path(checkpoint["output_directory"]) / "reports" / (
                "round-%03d" % production_round
            ) / (identity + ".md")
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("Accepted independent review " + identity, encoding="utf-8")
            candidate.update(
                artifacts=[str(artifact)], production_round=production_round,
                finished=identity == "a", score=0.8, report_path=str(report),
                review_round=production_round,
            )
            checkpoint["rounds"][production_round - 1]["reviews"][identity] = {
                "score": 0.8, "report_path": str(report), "call_id": "legacy-" + identity,
            }
        expected_candidates = copy.deepcopy(checkpoint["candidates"])
        expected_rounds = copy.deepcopy(checkpoint["rounds"])
        task_api.duel_checkpoint_store(self.home, record["id"]).put("checkpoint", checkpoint)
        host.start(record, self.config)
        native = self.completed(host, record)
        self.assertEqual(self.calls, [])
        self.assertEqual(native["candidates"], expected_candidates)
        self.assertEqual(native["rounds"], expected_rounds)
        self.assertEqual(native["stop_reason"], "round_limit")
        for candidate in native["candidates"]:
            self.assertEqual(
                Path(candidate["report_path"]).read_text(encoding="utf-8"),
                "Accepted independent review " + candidate["id"],
            )

    def test_pause_or_stop_waits_for_joint_review_to_settle(self):
        for action in ("pause", "stop"):
            with self.subTest(action=action):
                self.calls.clear()
                ready, release = threading.Event(), threading.Event()
                def held_review(family, prompt, workspace, **kwargs):
                    if self.call_info(prompt)["kind"] == "duel_review":
                        ready.set()
                        if not release.wait(timeout=10):
                            raise runners.RunnerError("test did not release the held review")
                    return self.physical(family, prompt, workspace, **kwargs)

                record, host = self.admit(), self.host(held_review)
                thread = host.start(record, self.config)
                try:
                    self.assertTrue(ready.wait(timeout=5), "the joint review must start")
                    getattr(host, action)(record["id"])
                    self.assertTrue(host.is_active(record["id"]))
                    self.assertIsNone(host.store.record(record["id"])["result"])
                finally:
                    release.set()
                    thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
                if action == "pause":
                    paused = self._paused(host, record["id"])
                    host.runner_factory = lambda *_args: self.session_runner(self.physical)
                    host.resume(record["id"], self.config, paused["revision"])
                    self.completed(host, record)
                else:
                    terminal = self._terminal(host, record["id"])
                    self.assertEqual(terminal["result"]["status"], "failure")
                self.assertEqual(self.call_counts()[("duel_author", "a")], 1)
                self.assertEqual(self.call_counts()[("duel_author", "b")], 1)


if __name__ == "__main__":
    unittest.main()
