"""Focused executable evidence for staffing-router slice 06.

Brainstorming stops choosing the intelligence behind its own automatic
seats. Every one of them — the three roster seats, the failure classifier
and the agreed production effect — asks the owner's staffing session
immediately before its physical call, and what actually ran is what the
activity says.
"""

import contextlib
import copy
import os
import tempfile
import time
import types
import unittest
from unittest import mock

from orchestrator import brainstorming
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import staffing


# Two families with an explicit-reference CLI seam, so the lifecycle's own
# family discovery accepts both. `/bin/echo` never runs here: every test
# below stops at, or before, the pre-provider resolution.
CONFIG = {
    "families_order": ["codex", "claude"],
    "commands": {
        "codex": [
            "/bin/echo", "exec", "--model", "{model}", "--effort",
            "{effort}", "--output-last-message", "{output_file}",
        ],
        "claude": [
            "/bin/echo", "-p", "--model", "{model}", "--effort", "{effort}",
        ],
    },
    "model_defaults": {
        "codex": {"model": "gpt-5.6-sol", "effort": "max"},
        "claude": {"model": "claude-fable-5", "effort": "max"},
    },
    "timeouts": {},
}


def milestone_roster():
    """The standard milestone roster, with no seat pinned by anybody."""
    return [
        {"id": "initial-position", "role": "initial_position",
         "delivery": "llm"},
        {"id": "contrary-position", "role": "contrary_position",
         "delivery": "llm"},
        {"id": "dante", "role": "common_sense", "delivery": "external",
         "external_provider": "narrator"},
    ]


class _Recorder:
    """Capture every router request the discussion makes."""

    def __init__(self):
        self.requests = []
        self._real = staffing.resolve

    def __call__(self, home, session, role, index=1, round=1, material=None,
                 brief=None, families=()):
        self.requests.append({
            "session": session,
            "role": role,
            "index": index,
            "round": round,
        })
        return self._real(
            home, session, role, index=index, round=round,
            material=material, brief=brief, families=families,
        )


class _NoProviderRunner:
    """Fail loudly if a refused dispatch ever reaches a provider."""

    def __init__(self, started):
        self.started = started

    def supports_session_continuation(self, family):
        return True

    def start_session(self, *args, **kwargs):
        self.started.append("start")
        raise AssertionError("a refused dispatch started a provider")

    def continue_session(self, *args, **kwargs):
        self.started.append("continue")
        raise AssertionError("a refused dispatch continued a provider")


class BrainstormingCutoverTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.workspace = os.path.join(self.tmp.name, "workspace")
        os.makedirs(self.workspace, exist_ok=True)
        os.makedirs(os.path.join(self.home, "brainstorming"), exist_ok=True)
        staffing.ensure_documents(self.home)
        self.session = staffing.create_session(self.home, {
            "work_area": {"workspace_path": self.workspace},
            "families": list(CONFIG["families_order"]),
            "document": staffing.DEFAULT_DOCUMENT_NAME,
            "rigor": "medium",
        })["id"]
        self.store = brainstorming.SessionStore(
            lifecycle.state_directory(self.home)
        )

    # -- helpers ---------------------------------------------------------

    def answer(self, index, round_number=1, role="brainstorm", session=None):
        resolved = staffing.resolve(
            self.home,
            self.session if session is None else session,
            role,
            index=index,
            round=round_number,
            families=list(CONFIG["families_order"]),
        ).answer
        return resolved["agent"], resolved["model"], resolved["effort"]

    def roster(self, participants=None, config=None):
        """Build one router-backed runtime and run config."""
        runtime, run_config, eligible = lifecycle._runtime_and_roster(
            CONFIG if config is None else config,
            participants or milestone_roster(),
            "unanimity",
            self.workspace,
            staffing_binding=lifecycle._staffing_binding(
                self.home, self.session
            ),
        )
        return runtime, run_config, eligible

    def durable(self, session_id, participants=None, staffing_session=True):
        runtime, run_config, eligible = self.roster(participants)
        created = self.store.create(
            session_id,
            {
                "workspace_path": self.workspace,
                "target_path": os.path.join(self.workspace, "decision.md"),
                "request": "Choose the compatible option to adopt.",
                "context": {"brief": "Resolve one bounded design request."},
                "max_rounds": 3,
            },
            run_config,
            eligible,
        )
        running = self.store.transition(
            session_id, created.revision, "running"
        )
        self.store.initialize_coordination(
            session_id,
            running.revision,
            brainstorming.make_target_revision(False, b"", None),
        )
        record = {
            "id": session_id,
            "caller": "milestone:run:slice_impl-02-b",
            "project": None,
            "work_area": None,
            "target_path": os.path.join(self.workspace, "decision.md"),
            "target_identity": {"device": 1, "inode": 1, "tail": []},
            "pid": None,
            "created_at": "2026-08-19T08:00:00+0000",
            "runtime": runtime,
            "execution_context": {
                "workspace_path": self.workspace,
                "project": None,
                "work_area": None,
                "primary": None,
                "additional": [],
            },
        }
        if staffing_session:
            record["staffing_session"] = self.session
        return lifecycle._validate_record(record)

    def narrator_turn(self, session_id):
        """Make Dante's round-1 turn the durable next action."""
        target = brainstorming.make_target_revision(False, b"", None)
        ready = self.store.read(session_id)
        for participant_id in ("initial-position", "contrary-position"):
            ready = self.store.record_completed_turn(
                session_id,
                ready.revision,
                participant_id,
                "%s has spoken." % participant_id,
                target,
            )
        request = ready.state["request"]
        return self.store.publish_external_intervention(session_id, {
            "token": "%s-narrator-turn" % session_id,
            "participant_id": "dante",
            "action_kind": "discussion_turn",
            "completed_turn_count": 2,
            "round": 1,
            "target_revision": ready.state["accepted_target_revision"],
            "input": {
                "request": request["request"],
                "context": request["context"],
                "workspace_path": request["workspace_path"],
                "target_path": request["target_path"],
                "transcript_ref": ready.state["transcript_ref"],
            },
            "created_at": 100.0,
            "provider_attempt": 0,
            "provider_quiescent": True,
            "response": None,
        })

    def executors(self, record, recorder=None):
        with mock.patch.object(
            staffing, "resolve", side_effect=recorder or staffing.resolve
        ):
            return lifecycle._participant_execution(
                self.store,
                record,
                None,
                staffing_binding=lifecycle._staffing_binding(
                    self.home, record.get("staffing_session")
                ),
            )

    # -- acceptance ------------------------------------------------------

    def test_every_automatic_seat_asks_the_router_for_its_own_index(self):
        record = self.durable("seats")
        recorder = _Recorder()
        subject = self.executors(record, recorder)
        binding_refs = [
            participant.get("executor_ref")
            or participant.get("external_ref")
            for participant in self.store.read("seats").state[
                "run_config"
            ]["participants"]
        ]

        with mock.patch.object(staffing, "resolve", side_effect=recorder):
            for position, ref in enumerate(binding_refs, start=1):
                subject.executors[ref].prepare_dispatch(position)

        # Initial Position is roster seat 1, Contrary Position 2, Dante 3 —
        # and the round each call carries is the discussion round, never a
        # provider attempt.
        self.assertEqual(
            [(item["role"], item["index"], item["round"])
             for item in recorder.requests],
            [("brainstorm", 1, 1), ("brainstorm", 2, 2), ("brainstorm", 3, 3)],
        )
        self.assertEqual(
            {item["session"] for item in recorder.requests}, {self.session}
        )
        self.assertEqual(
            [(subject.executors[ref].model_family,
              subject.executors[ref].model,
              subject.executors[ref].effort)
             for ref in binding_refs],
            [self.answer(1, 1), self.answer(2, 2), self.answer(3, 3)],
        )

    def test_a_manual_participant_asks_the_router_nothing(self):
        roster = milestone_roster()
        roster[2] = {
            "id": "operator", "role": "common_sense",
            "delivery": "external", "external_provider": "manual",
        }
        record = self.durable("manual", roster)
        recorder = _Recorder()
        subject = self.executors(record, recorder)

        self.assertNotIn(
            "brainstorming-external-operator", subject.executors
        )
        self.assertEqual(recorder.requests, [])

    def test_the_classifier_seat_is_classify_one_and_only_when_called(self):
        record = self.durable("classifier")
        recorder = _Recorder()
        subject = self.executors(record, recorder)
        lead = subject.executors[
            self.store.read("classifier").state["run_config"][
                "participants"
            ][0]["executor_ref"]
        ]
        captured = {}

        def classify(_exc, **kwargs):
            # The deterministic stage never reaches a provider; only the
            # LLM stage's own hook resolves anything.
            captured["before"] = list(recorder.requests)
            captured["answer"] = kwargs["resolve_dispatch"]()
            return "unknown", None, "test"

        with mock.patch.object(staffing, "resolve", side_effect=recorder), \
                mock.patch.object(
                    lifecycle.errclass, "classify_worker_failure",
                    side_effect=classify):
            subject.failure_classifier(
                "classifier", {"id": "initial-position"}, lead,
                RuntimeError("mystery"),
            )

        self.assertEqual(captured["before"], [])
        self.assertEqual(
            recorder.requests,
            [{"session": self.session, "role": "classify",
              "index": 1, "round": 1}],
        )
        self.assertEqual(captured["answer"], self.answer(1, role="classify"))

    def test_a_completed_edit_reaches_the_next_call(self):
        record = self.durable("live")
        subject = self.executors(record)
        lead_ref = self.store.read("live").state["run_config"][
            "participants"
        ][0]["executor_ref"]
        lead = subject.executors[lead_ref]

        lead.prepare_dispatch(1)
        first = (lead.model_family, lead.model, lead.effort)

        # A session edit and a document save between two calls: the second
        # call runs the new answers, and nothing rewrites the first.
        document = staffing.load(self.home, staffing.DEFAULT_DOCUMENT_NAME)
        document["assignment"]["brainstorm"]["1"] = (
            2 if document["assignment"]["brainstorm"]["1"] == 1 else 1
        )
        staffing.save(self.home, document)
        staffing.edit_session(self.home, self.session, {"rigor": "low"})

        lead.prepare_dispatch(1)
        second = (lead.model_family, lead.model, lead.effort)

        self.assertNotEqual(first, second)
        self.assertEqual(second, self.answer(1, 1))

    def test_retired_selectors_decide_nothing_for_a_router_session(self):
        # A caller-pinned seat, the family rotation and the configured
        # model defaults are all inert: the document decides.
        pinned = milestone_roster()
        pinned[0]["model_family"] = "claude"
        pinned[0]["model"] = "pinned-model"
        pinned[0]["effort"] = "low"
        runtime, run_config, _eligible = self.roster(pinned)
        lead = run_config["participants"][0]

        self.assertEqual(lead["model_family"], self.answer(1)[0])
        self.assertEqual(
            (
                runtime["executors"][lead["executor_ref"]]["model"],
                runtime["executors"][lead["executor_ref"]]["effort"],
            ),
            self.answer(1)[1:],
        )
        self.assertEqual(
            runtime["model_defaults"], {"codex": {}, "claude": {}}
        )

        # Inert includes discovery: a family the operator configured with
        # no default at all is still a family this machine can run, because
        # the document supplies the model and the effort. Dropping every
        # default changes neither the seats nor the set they resolve
        # against.
        undefaulted = copy.deepcopy(CONFIG)
        undefaulted["model_defaults"] = {}
        bare, bare_config, _bare_eligible = self.roster(
            config=undefaulted
        )
        self.assertEqual(bare["families_order"], runtime["families_order"])
        self.assertEqual(
            [seat.get("model_family")
             for seat in bare_config["participants"]],
            [seat.get("model_family")
             for seat in run_config["participants"]],
        )
        self.assertEqual(bare["executors"], runtime["executors"])

    def test_same_family_seats_are_allowed_without_a_declared_split(self):
        document = staffing.load(self.home, staffing.DEFAULT_DOCUMENT_NAME)
        document["assignment"]["brainstorm"] = {"1": 1, "2": 1, "3": 1}
        staffing.save(self.home, document)

        runtime, run_config, _eligible = self.roster()

        self.assertEqual(
            {seat["model_family"] for seat in run_config["participants"]
             if seat["delivery"] == "llm"},
            {"codex"},
        )
        self.assertTrue(run_config["same_family_fallback"])
        self.assertEqual(runtime["families_order"], ["codex", "claude"])

    def test_a_surfaced_condition_stops_the_call_before_any_provider(self):
        record = self.durable("condition")
        subject = self.executors(record)
        lead_ref = self.store.read("condition").state["run_config"][
            "participants"
        ][0]["executor_ref"]
        lead = subject.executors[lead_ref]

        # Counted across each condition, exactly as the gate asks: nothing
        # below may reach a provider.
        started = []
        for executor in subject.executors.values():
            executor.runner = _NoProviderRunner(started)
        coordinator = coordination.BrainstormingCoordinator(
            self.store, subject
        )

        # Dante is a router-staffed seat too, and his dispatch runs through
        # the external-intervention seam rather than the worker attempt.
        # Both sessions are built while the document still answers.
        narrator_record = self.durable("narrated")
        narrator = self.executors(narrator_record)
        for executor in narrator.executors.values():
            executor.runner = _NoProviderRunner(started)
        pending = coordination.ExternalInterventionPending(
            self.narrator_turn("narrated")
        )

        # `brainstorm` declares a split this session cannot honour once its
        # seats share one family.
        document = staffing.load(self.home, staffing.DEFAULT_DOCUMENT_NAME)
        document["assignment"]["brainstorm"] = {"1": 1, "2": 1, "3": 1}
        document["roles"]["brainstorm"] = {"distinct_families": True}
        staffing.save(self.home, document)

        # Through the coordinator, which has already admitted this turn's
        # durable worker: the condition stops the call, and retiring the
        # never-dispatched attempt fabricates no activity for it.
        with self.assertRaises(staffing.StaffingConditionError) as split:
            coordinator.run_next_turn(
                "condition", record["execution_context"]
            )
        self.assertEqual(
            split.exception.code, staffing.DISTINCT_FAMILIES_UNSATISFIABLE
        )
        self.assertEqual(started, [])
        self.assertIsNone(self.store.read_turn_attempt("condition"))
        projection = lifecycle._activity_projection(
            self.store, record, self.store.read("condition").state
        )
        self.assertEqual(projection["activity"], [])
        # No call ran, so this discussion's cost and tokens stay known.
        self.assertFalse(projection["work_cost_partial"])
        self.assertFalse(projection["work_token_usage_partial"])

        # Seat 3 answers to the same law through its own seam: retiring the
        # claimed-but-never-started narrator attempt fabricates nothing.
        with self.assertRaises(staffing.StaffingConditionError) as narrated:
            lifecycle._wait_for_external_response(
                self.store,
                narrator,
                narrator_record,
                pending,
                narrator_record["execution_context"],
            )
        self.assertEqual(
            narrated.exception.code, staffing.DISTINCT_FAMILIES_UNSATISFIABLE
        )
        self.assertEqual(started, [])
        narrated_projection = lifecycle._activity_projection(
            self.store, narrator_record, self.store.read("narrated").state
        )
        self.assertEqual(narrated_projection["activity"], [])
        self.assertFalse(narrated_projection["work_cost_partial"])
        self.assertFalse(narrated_projection["work_token_usage_partial"])
        # The durable mark describes only the claim it was written for, so
        # the next claim of the same turn owes its accounting again.
        refused = self.store.read_external_intervention("narrated")
        self.assertTrue(refused["dispatch_refused"])
        self.assertTrue(refused["provider_quiescent"])
        reclaimed = self.store.claim_external_intervention(
            "narrated", pending.intervention["token"]
        )
        self.assertNotIn("dispatch_refused", reclaimed)
        self.assertEqual(reclaimed["provider_attempt"], 2)

        # No family at all is the other one, and it is equally pre-provider.
        staffing.edit_session(self.home, self.session, {"rigor": "medium"})
        lead.families = ()
        lead.current_resolver.families = ()
        with mock.patch.object(
            staffing, "_selection_for",
            return_value=(staffing._Selection(
                families=(), rigor="medium", material=None, overrides=None,
                document=staffing.DEFAULT_DOCUMENT_NAME), False),
        ):
            with self.assertRaises(
                staffing.StaffingConditionError
            ) as nobody:
                coordinator.run_next_turn(
                    "condition", record["execution_context"]
                )
        self.assertEqual(
            nobody.exception.code, staffing.STAFFING_UNAVAILABLE
        )
        self.assertEqual(started, [])
        self.assertEqual(
            (self.store.read_activity("condition") or {}).get("events", []),
            [],
        )
        self.assertIsNone(self.store.read_turn_attempt("condition"))

    def test_activity_records_what_ran_and_the_default_fallback(self):
        record = self.durable("evidence")
        subject = self.executors(record)
        participants = self.store.read("evidence").state["run_config"][
            "participants"
        ]
        lead = subject.executors[participants[0]["executor_ref"]]
        self.store.begin_turn_attempt("evidence", {
            "token": "action-1",
            "participant_id": "initial-position",
            "completed_turn_count": 0,
            "quiescent": False,
            "target_revision": None,
            "target_parent": {
                "device": 1, "inode": 1, "path": self.workspace,
            },
        })

        lead.prepare_dispatch(1)
        event = subject._record_activity(
            "evidence", participants[0], lead, time.time(),
            result=types.SimpleNamespace(
                duration_s=1.0, text="ok", token_usage=None,
                cost_payloads=None, prompt_path=None),
        )
        self.assertEqual(
            (event["model_family"], event["model"], event["effort"]),
            self.answer(1, 1),
        )
        self.assertNotIn("staffing_fallback", event)

        # An unreadable session answers on the default document and the
        # entry says so, rather than failing the call.
        os.unlink(staffing._session_path(self.home, self.session))
        lead.prepare_dispatch(1)
        self.store.finish_turn_attempt("evidence", "action-1")
        self.store.begin_turn_attempt("evidence", {
            "token": "action-2",
            "participant_id": "initial-position",
            "completed_turn_count": 0,
            "quiescent": False,
            "target_revision": None,
            "target_parent": {
                "device": 1, "inode": 1, "path": self.workspace,
            },
        })
        fell_back = subject._record_activity(
            "evidence", participants[0], lead, time.time(),
            result=types.SimpleNamespace(
                duration_s=1.0, text="ok", token_usage=None,
                cost_payloads=None, prompt_path=None),
        )
        self.assertEqual(
            fell_back["staffing_fallback"],
            brainstorming.STAFFING_FALLBACK_DEFAULT_DOCUMENT,
        )
        self.assertEqual(
            brainstorming.validate_activity_event(fell_back)[
                "staffing_fallback"
            ],
            "default_document",
        )

    def test_old_activity_without_the_field_still_validates(self):
        event = {
            "id": "activity-old", "action_id": "a", "provider_attempt": 1,
            "at": "2026-08-01T00:00:00+0000", "started_at": 1.0,
            "duration_s": 1.0, "kind": "discussion_turn",
            "stage": "discussion", "round": 1,
            "participant_id": "initial-position", "model_family": "codex",
            "model": "gpt-5.6-sol", "effort": "max", "status": "completed",
        }
        checked = brainstorming.validate_activity_event(event)
        self.assertNotIn("staffing_fallback", checked)

    def test_the_record_mark_distinguishes_a_default_from_a_pre_cutover(self):
        omitted = self.durable("omitted", staffing_session=False)
        omitted.pop("staffing_session", None)
        omitted["staffing_session"] = None
        omitted = lifecycle._validate_record(omitted)
        self.assertTrue(lifecycle._router_staffed(omitted))
        self.assertIsNone(lifecycle.record_staffing_session(omitted))

        legacy = self.durable("legacy", staffing_session=False)
        legacy["caller"] = "task:standalone-1"
        legacy = lifecycle._validate_record(legacy)
        self.assertNotIn("staffing_session", legacy)
        self.assertFalse(lifecycle._router_staffed(legacy))
        self.assertIsNone(
            lifecycle._record_staffing_binding(self.home, legacy, "supplied")
        )

        # A pre-cutover ATTACHED record carries no mark either, and takes
        # the session its owning run supplies at launch.
        attached = self.durable("attached", staffing_session=False)
        attached.pop("staffing_session", None)
        attached = lifecycle._validate_record(attached)
        self.assertTrue(lifecycle._router_staffed(attached))
        self.assertEqual(
            lifecycle._record_staffing_binding(
                self.home, attached, self.session
            ),
            {"home": os.path.abspath(self.home), "session": self.session},
        )
        # And a record that carries the mark is its own authority.
        marked = self.durable("marked")
        self.assertEqual(
            lifecycle._record_staffing_binding(
                self.home, marked, "some-other-session"
            )["session"],
            self.session,
        )

    def restart(self, record, resolve_staffing_session):
        """Explicitly restart one stopped record; return the launch mock."""
        document = {"sessions": [dict(record, pid=None)]}
        launch = mock.Mock()
        launch.process.pid = 4242
        snapshot = types.SimpleNamespace(state={"status": "running"})
        store = mock.Mock()
        store.read.return_value = snapshot

        with mock.patch.object(
            lifecycle, "_record_by_id", return_value=record
        ), mock.patch.object(
            lifecycle, "_locked_registry",
            return_value=contextlib.nullcontext(),
        ), mock.patch.object(
            lifecycle, "_load_registry", return_value=document
        ), mock.patch.object(
            lifecycle, "_process_alive", return_value=False
        ), mock.patch.object(
            lifecycle, "_launch_lifecycle_process", return_value=launch
        ) as launched, mock.patch.object(
            lifecycle.brainstorming, "SessionStore", return_value=store
        ), mock.patch.object(
            lifecycle, "_save_registry"
        ), mock.patch.object(
            lifecycle, "_track_child"
        ), mock.patch.object(
            lifecycle, "_projection", return_value={}
        ):
            lifecycle.start_session(
                self.home,
                record["id"],
                lambda _record: None,
                resolve_staffing_session=resolve_staffing_session,
            )
        return launched

    def test_restart_forwards_the_same_live_reference(self):
        record = self.durable("restart", staffing_session=False)
        record.pop("staffing_session", None)
        record = lifecycle._validate_record(record)

        # A pre-cutover attached record carries no mark, so the launcher's
        # answer is the only source it has.
        launched = self.restart(record, lambda _record: self.session)
        launched.assert_called_once_with(
            self.home, "restart", staffing_session=self.session
        )
        # Nothing about the stored record changed.
        self.assertNotIn("staffing_session", record)

        # A MARKED record is its own authority, so the launcher's lookup is
        # not consulted at all — and cannot veto the restart by failing.
        # This is the one an owning run that was deregistered, moved or is
        # no longer waiting on the discussion would take.
        marked = self.durable("marked-restart")

        def unreachable(_record):
            raise RuntimeError("the owning run cannot be reached")

        launched = self.restart(marked, unreachable)
        launched.assert_called_once_with(
            self.home, "marked-restart", staffing_session=self.session
        )


if __name__ == "__main__":
    unittest.main()
