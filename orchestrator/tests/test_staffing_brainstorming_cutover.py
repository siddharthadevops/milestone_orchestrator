"""Focused executable evidence for staffing-router slice 06.

Brainstorming stops choosing the intelligence behind its own automatic
seats. Every one of them — the three roster seats, the failure classifier
and the agreed production effect — asks the owner's staffing session
immediately before its physical call, and what actually ran is what the
activity says.
"""

import copy
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from unittest import mock

from orchestrator import access, brainstorming, contracts, driver, runners
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import brainstorming_milestone
from orchestrator import brainstorming_tasks as tasks
from orchestrator import service, staffing
from orchestrator import state as st


# Two families with an explicit-reference CLI seam, so the lifecycle's own
# family discovery accepts both. `/bin/echo` never runs: the tests that stop
# at, or before, the pre-provider resolution reach no command at all, and the
# two that physically dispatch swap these commands for the scripted CLI
# `provider_config` writes.
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
_UNSET = object()


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


def llm_roster():
    """The two staffed seats a ballot and a production effect both use."""
    return [
        {"id": "initial-position", "role": "initial_position",
         "delivery": "llm"},
        {"id": "contrary-position", "role": "contrary_position",
         "delivery": "llm"},
    ]


def closing_summary():
    return {
        "reason": "The participants completed the bounded discussion.",
        "unresolved_objections": [],
        "affected_parties": "The people using the requested target.",
        "damage_altitude": "A bounded and reversible consequence.",
        "proportionality": "The discussion matched the decision.",
        "escalation_evidence": None,
        "open_questions": [],
    }


# One scripted CLI standing in for every provider family, so the tests that
# have to see a call ACTUALLY RUN dispatch a real process: it answers each
# prompt kind the discussion, its closure ballot, the failure classifier and
# the production effect send, and records the family, model and effort its
# own argv carried.
FAKE_CLI = '''\
#!/usr/bin/env python3
import json
import os
import sys
import uuid

args = sys.argv[1:]
prompt = sys.stdin.read()
codex = bool(args and args[0] == "exec")
state_dir = args[args.index("--state-dir") + 1]
output_path = (
    args[args.index("--output-last-message") + 1]
    if "--output-last-message" in args else None
)
if "You are classifying a FAILED AI-CLI worker call" in prompt:
    kind = "classifier"
    answer = {
        "error_type": "busy",
        "resume_at": None,
        "evidence": "the scripted provider refused one call",
    }
elif "production_completion" in prompt:
    kind = "production_effect"
    answer = {"kind": "production_completion", "completed": True}
elif 'kind: "closure_proposal"' in prompt:
    kind = "closure_proposal"
    answer = {
        "kind": "closure_proposal",
        "propose": True,
        "closing_summary": %(summary)s,
    }
elif 'kind "closure_vote"' in prompt:
    kind = "closure_vote"
    answer = {"kind": "closure_vote", "vote": "accept"}
else:
    kind = "discussion_turn"
    answer = {"kind": "discussion_turn", "markdown": "Accepted turn."}

with open(os.path.join(state_dir, "calls.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "family": "codex" if codex else "claude",
        "model": args[args.index("--model") + 1],
        "effort": args[args.index("--effort") + 1],
        "kind": kind,
    }) + "\\n")

# Refused BEFORE any output, so the call is a runner failure rather than
# an unreadable envelope: nothing on stdout, nothing in the output file.
refusal = os.path.join(state_dir, "refuse-" + kind)
if os.path.exists(refusal):
    os.unlink(refusal)
    sys.stderr.write("the scripted provider declined this call\\n")
    sys.exit(7)

if codex:
    print(json.dumps({
        "type": "thread.started",
        "thread_id": str(uuid.uuid4()),
    }), flush=True)

rendered = json.dumps(answer)
if output_path:
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(rendered)
else:
    print(rendered, flush=True)
''' % {"summary": repr(closing_summary())}


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
            "material": material,
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

    def roster(self, participants=None, config=None, material=_UNSET):
        """Build one router-backed runtime and run config."""
        binding = (
            lifecycle._staffing_binding(self.home, self.session)
            if material is _UNSET else
            lifecycle._staffing_binding(self.home, self.session, material)
        )
        runtime, run_config, eligible = lifecycle._runtime_and_roster(
            CONFIG if config is None else config,
            participants or milestone_roster(),
            "unanimity",
            self.workspace,
            staffing_binding=binding,
        )
        return runtime, run_config, eligible

    def durable(
        self,
        session_id,
        participants=None,
        staffing_session=True,
        staffing_material=_UNSET,
    ):
        runtime, run_config, eligible = self.roster(
            participants, material=staffing_material
        )
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
            if staffing_material is not _UNSET:
                record["staffing_material"] = staffing_material
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

    def executors(self, record, recorder=None, dispatching=False,
                  supplied=None):
        with mock.patch.object(
            staffing, "resolve", side_effect=recorder or staffing.resolve
        ):
            return lifecycle._participant_execution(
                self.store,
                record,
                lifecycle._spawn_participant if dispatching else None,
                staffing_binding=lifecycle._record_staffing_binding(
                    self.home, record, supplied
                ),
            )

    # -- the seams that physically dispatch ------------------------------

    def provider_config(self):
        """One CONFIG whose commands are a scripted CLI that really runs."""
        self.provider_state = os.path.join(self.tmp.name, "provider")
        os.makedirs(self.provider_state, exist_ok=True)
        cli = os.path.join(self.tmp.name, "fake-participant-cli")
        with open(cli, "w", encoding="utf-8") as handle:
            handle.write(FAKE_CLI)
        os.chmod(cli, 0o755)
        config = copy.deepcopy(CONFIG)
        config["commands"] = {
            "codex": [
                cli, "exec", "--state-dir", self.provider_state,
                "--model", "{model}", "--effort", "{effort}",
                "--output-last-message", "{output_file}",
            ],
            "claude": [
                cli, "-p", "--state-dir", self.provider_state,
                "--model", "{model}", "--effort", "{effort}",
            ],
        }
        return config

    def provider_calls(self, kind=None):
        """What the scripted CLI was actually invoked with, in order."""
        path = os.path.join(self.provider_state, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            calls = [json.loads(line) for line in handle if line.strip()]
        return [
            call for call in calls
            if kind is None or call["kind"] == kind
        ]

    def refuse_next(self, kind):
        """Make the scripted CLI fail its next call of *kind*, once."""
        with open(
            os.path.join(self.provider_state, "refuse-%s" % kind), "wb"
        ) as handle:
            handle.write(b"")

    def register(self, record):
        """Persist one record in the real registry this home serves."""
        with lifecycle._locked_registry(self.home):
            document = lifecycle._load_registry(self.home)
            document["sessions"] = [
                item for item in document["sessions"]
                if item["id"] != record["id"]
            ] + [copy.deepcopy(record)]
            lifecycle._save_registry(self.home, document)
        return lifecycle._record_by_id(self.home, record["id"])

    def stored_bytes(self, session_id):
        """The stored record's own bytes, with only its pid factored out."""
        document = json.loads(
            pathlib.Path(lifecycle.registry_path(self.home)).read_bytes()
        )
        record = next(
            item for item in document["sessions"] if item["id"] == session_id
        )
        record.pop("pid", None)
        return json.dumps(record, sort_keys=True)

    def dispatched(
        self,
        session_id,
        participants=None,
        caller=None,
        static_pins=None,
        max_rounds=1,
        staffing_material=_UNSET,
    ):
        """One registry-backed session whose seats dispatch real processes.

        Router-backed unless *static_pins* names a pre-cutover roster, in
        which case the record carries no staffing mark at all — exactly the
        two stored shapes the compatibility boundary separates.
        """
        runtime, run_config, eligible = lifecycle._runtime_and_roster(
            self.provider_config(),
            static_pins or participants or llm_roster(),
            "unanimity",
            self.workspace,
            static_binding=static_pins is not None,
            staffing_binding=(
                None if static_pins is not None
                else (
                    lifecycle._staffing_binding(self.home, self.session)
                    if staffing_material is _UNSET else
                    lifecycle._staffing_binding(
                        self.home, self.session, staffing_material
                    )
                )
            ),
        )
        target_path = os.path.join(self.workspace, "%s.md" % session_id)
        with open(target_path, "wb") as handle:
            handle.write(b"initial target")
        created = self.store.create(
            session_id,
            {
                "workspace_path": self.workspace,
                "target_path": target_path,
                "request": "Choose the compatible option to adopt.",
                "context": {"brief": "Resolve one bounded design request."},
                "max_rounds": max_rounds,
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
            coordination.capture_target(target_path),
        )
        record = {
            "id": session_id,
            "caller": caller or "milestone:run:slice_impl-02-b",
            "project": None,
            "work_area": None,
            "target_path": target_path,
            "target_identity": lifecycle._target_identity(target_path),
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
        if static_pins is None:
            record["staffing_session"] = self.session
            if staffing_material is not _UNSET:
                record["staffing_material"] = staffing_material
        return self.register(lifecycle._validate_record(record))

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
              "index": 1, "round": 1, "material": None}],
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

    def test_slice_material_reaches_agent_call_and_brainstorming_production(
        self,
    ):
        """Both producer choices carry one admitted material end to end."""
        document = staffing.default_document_seed()
        document["name"] = "production-materials"
        document["materials"] = {
            "analysis": {"examples": ["Understand the problem."]},
            "delivery": {"examples": ["Apply the agreed change."]},
        }

        def seats(slot):
            return {
                "assignment": {
                    "draft": {"1": slot},
                    "implement": {"1": slot},
                    "brainstorm": {"1": slot, "2": slot, "3": slot},
                    "classify": {"1": slot},
                }
            }

        document["overrides"] = {
            "analysis": seats(1),
            "delivery": seats(2),
        }
        staffing.save(self.home, document)
        staffing.edit_session(
            self.home, self.session, {"document": document["name"]}
        )

        request = {
            "work_area": {
                "workspace_path": self.workspace,
                "primary": self.workspace,
                "additional": [],
            },
            "request": "Produce the slice's requested artifact.",
            "context": {"unit": "slice-1"},
            "reference_documents": [],
        }
        producer_maps = (
            {
                contracts.KIND_DRAFT_SLICE_NOTE: "brainstorming",
                contracts.KIND_IMPLEMENT: "agent_call",
            },
            {
                contracts.KIND_DRAFT_SLICE_NOTE: "agent_call",
                contracts.KIND_IMPLEMENT: "brainstorming",
            },
        )
        owner = types.SimpleNamespace(
            model_profiles_home=self.home,
            state={"staffing_session": self.session},
        )
        resolver_owner = types.SimpleNamespace()
        resolver_owner._staffing_resolution = (
            lambda role, index=1, round=1, material=None: staffing.resolve(
                self.home,
                self.session,
                role,
                index=index,
                round=round,
                material=material,
                families=list(CONFIG["families_order"]),
            )
        )
        brainstorming_selection = None
        agent_roles = []
        recorder = _Recorder()
        with mock.patch.object(staffing, "resolve", side_effect=recorder):
            for producer_map in producer_maps:
                plan = {
                    "id": 1,
                    "title": "One",
                    "material": "analysis",
                    "producer_task_executor": {
                        kind: {"task_executor": executor}
                        for kind, executor in producer_map.items()
                    },
                }
                for kind, role in (
                    (contracts.KIND_DRAFT_SLICE_NOTE, "draft"),
                    (contracts.KIND_IMPLEMENT, "implement"),
                ):
                    admitted_request = copy.deepcopy(request)
                    admitted_request["context"]["task_kind"] = kind
                    order = tasks.tasks.validate_order(
                        tasks.tasks.producer_order(plan, kind, admitted_request)
                    )
                    self.assertEqual(
                        tasks.tasks.order_staffing_material(order), "analysis"
                    )
                    if order["task_executor"] == "agent_call":
                        driver._RoleDispatch(
                            resolver_owner,
                            role,
                            material=tasks.tasks.order_staffing_material(order),
                        )()
                        agent_roles.append(role)
                    else:
                        selection = driver.Driver._brainstorming_staffing(
                            owner, order
                        )
                        self.assertEqual(selection, {
                            "session": self.session,
                            "material": "analysis",
                        })
                        brainstorming_selection = selection

            self.assertEqual(sorted(agent_roles), ["draft", "implement"])

            # Create through the real lifecycle boundary. The registry, not
            # the mutable slice plan, becomes every later call's carrier.
            target = os.path.join(self.workspace, "production-material.md")
            with open(target, "wb") as handle:
                handle.write(b"initial target")
            body = {
                "request": {
                    "workspace_path": self.workspace,
                    "target_path": target,
                    "request": "Agree the bounded production approach.",
                    "context": {"brief": "One production task."},
                    "max_rounds": 1,
                },
                "participants": llm_roster(),
                "closure_policy": "unanimity",
            }
            config = self.provider_config()
            launch = lifecycle.GatedLaunch(
                process=types.SimpleNamespace(
                    pid=999999, poll=lambda: None
                ),
                release=mock.Mock(),
                abort=mock.Mock(),
            )
            with mock.patch.object(lifecycle, "_track_child"):
                created = lifecycle.create_resolved_session(
                    self.home,
                    body,
                    "task-profile:material-task",
                    {
                        "workspace_path": self.workspace,
                        "project": None,
                        "work_area": None,
                        "primary": None,
                        "additional": [],
                    },
                    config,
                    launcher=lambda _home, _session_id: launch,
                    owned_target_path=target,
                    staffing_selection=brainstorming_selection,
                )
            session_id = created["id"]
            record = lifecycle._record_by_id(self.home, session_id)
            self.assertEqual(record["staffing_material"], "analysis")

            subject = self.executors(record, recorder, dispatching=True)
            lead_ref = self.store.read(session_id).state["run_config"][
                "participants"
            ][0]["executor_ref"]
            lead = subject.executors[lead_ref]
            lead.prepare_dispatch(1)
            first = (lead.model_family, lead.model, lead.effort)

            # Prospective edit: the admitted discussion remains on analysis.
            task_state = {"milestone": {"slices": [plan]}, "events": []}
            tasks.tasks.update_slice_material(
                task_state, 1, {"material": "delivery"}
            )
            lead.prepare_dispatch(1)
            self.assertEqual(
                (lead.model_family, lead.model, lead.effort), first
            )

            # Staffing is still live: changing what ANALYSIS means reaches
            # the next call without retargeting the task to DELIVERY.
            document["overrides"]["analysis"] = seats(2)
            staffing.save(self.home, document)
            lead.prepare_dispatch(2)
            second = (lead.model_family, lead.model, lead.effort)
            self.assertNotEqual(first, second)

            classified = {}

            def classify(_exc, **kwargs):
                classified["answer"] = kwargs["resolve_dispatch"]()
                return "unknown", None, "test"

            with mock.patch.object(
                lifecycle.errclass,
                "classify_worker_failure",
                side_effect=classify,
            ):
                subject.failure_classifier(
                    session_id,
                    {"id": "initial-position"},
                    lead,
                    RuntimeError("mystery"),
                )
            self.assertEqual(classified["answer"][0], second[0])

            # A stopped process restarts from the durable registry fields.
            lifecycle._clear_pid(self.home, session_id, 999999)
            launched = self.restart(
                session_id,
                lambda _record: (_ for _ in ()).throw(
                    AssertionError("a marked record consulted its owner")
                ),
            )
            launched.assert_called_once_with(
                self.home, session_id, staffing_session=self.session
            )
            restarted_record = lifecycle._record_by_id(self.home, session_id)
            self.assertEqual(
                restarted_record["staffing_material"], "analysis"
            )
            restarted = self.executors(
                restarted_record, recorder, dispatching=True
            )
            restarted_lead = restarted.executors[lead_ref]
            restarted_lead.prepare_dispatch(2)
            self.assertEqual(
                (restarted_lead.model_family,
                 restarted_lead.model,
                 restarted_lead.effort),
                second,
            )

            # The agreed production effect reopens the same durable binding.
            self.agree(session_id, restarted_record, subject=restarted)
            self.store.begin_task_effect_attempt(session_id, {
                "task_id": "material-task",
                "token": "material-effect-1",
                "started_at": time.time(),
            })
            completion, _result = lifecycle.apply_production_effect(
                self.home,
                session_id,
                lambda _record: None,
                tasks._production_prompt({
                    "request": {"request": "Apply the agreement."},
                    "agreement": {"closing_summary": closing_summary()},
                }),
                tasks.validate_production_completion,
                participant_process_factory=lifecycle._spawn_participant,
            )
            self.assertTrue(completion["completed"])

        self.assertTrue(recorder.requests)
        self.assertEqual(
            {item["material"] for item in recorder.requests}, {"analysis"}
        )
        self.assertIn("classify", {item["role"] for item in recorder.requests})

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
            runtime["executors"][lead["executor_ref"]],
            {"model_family": self.answer(1)[0]},
        )
        self.assertEqual(
            runtime["model_defaults"], {"codex": {}, "claude": {}}
        )

        # Inert includes discovery: a family the operator configured with
        # no default at all is still a family this machine can run, because
        # the document supplies the model and the effort. Dropping every
        # default changes neither the seats nor the set they resolve
        # against.
        # A value the router never reads cannot refuse the create either.
        # `POST /api/projects/<slug>` accepts any JSON-plain object as a
        # project default, so a generic settings editor can leave a
        # non-object under this retired key; every discussion in the
        # project would otherwise be unavailable over a value none of them
        # uses.
        for retired in ({}, True, "opus", ["opus"], 1):
            with self.subTest(model_defaults=retired):
                undefaulted = copy.deepcopy(CONFIG)
                undefaulted["model_defaults"] = retired
                bare, bare_config, _bare_eligible = self.roster(
                    config=undefaulted
                )
                self.assertEqual(
                    bare["families_order"], runtime["families_order"]
                )
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

    def test_every_physical_call_kind_records_what_actually_ran(self):
        """Closure, the classifier and the production effect, end to end.

        Every call below is dispatched by the seam that owns it — the
        coordinator's own turn and ballot control, the failure classifier
        behind a refused call, and the production entry a task takes after
        the agreement — against a scripted CLI that really runs. So each
        entry names the family, model and effort the router had just
        answered for that seat, and the argv that ran says the same.
        """
        record = self.dispatched("kinds")
        subject = self.executors(record, dispatching=True)
        coordinator = coordination.BrainstormingCoordinator(
            self.store, subject
        )
        context = record["execution_context"]
        seats = [self.answer(1, 1), self.answer(2, 1)]

        # Round one. The contrary seat's first physical call is refused, so
        # the classifier's own LLM stage runs behind the failure it caused.
        coordinator.run_next_turn("kinds", context)
        self.refuse_next("discussion_turn")
        with self.assertRaises(coordination.OperationalRetryPending):
            coordinator.run_next_turn("kinds", context)
        classifier = self.store.read_activity("kinds")["events"][-1]
        self.assertEqual(
            (classifier["kind"], classifier["stage"],
             classifier["participant_id"]),
            ("classifier", "classification", "recovery-classifier"),
        )
        self.assertEqual(
            (classifier["model_family"], classifier["model"],
             classifier["effort"]),
            self.answer(1, role="classify"),
        )
        self.assertEqual(
            self.provider_calls("classifier"),
            [{
                "family": classifier["model_family"],
                "model": classifier["model"],
                "effort": classifier["effort"],
                "kind": "classifier",
            }],
        )
        coordinator.prepare("kinds", cancel_operational_retry=True)
        coordinator.run_next_turn("kinds", context)

        # Closure: the Initial Position proposes and the Contrary Position
        # votes, both as seat calls of the round just completed.
        terminal = coordinator.run_closure("kinds", context)
        self.assertEqual(terminal.state["status"], "success")
        events = [
            event for event in self.store.read_activity("kinds")["events"]
            if event["kind"] == "closure"
        ]
        self.assertEqual(
            [(event["stage"], event["round"]) for event in events],
            [("proposal", 1), ("vote", 1)],
        )
        self.assertEqual(
            [(event["model_family"], event["model"], event["effort"])
             for event in events],
            seats,
        )
        for stage, seat in (("closure_proposal", 0), ("closure_vote", 1)):
            self.assertEqual(
                [(call["family"], call["model"], call["effort"])
                 for call in self.provider_calls(stage)],
                [seats[seat]],
            )

        # The agreed production effect, through the lifecycle entry a task
        # takes: it finds the stored record, picks the Initial Position
        # lead itself, and resolves that seat afresh at the closed round.
        self.store.begin_task_effect_attempt("kinds", {
            "task_id": "task-1",
            "token": "effect-1",
            "started_at": time.time(),
        })
        completion, _result = lifecycle.apply_production_effect(
            self.home,
            "kinds",
            lambda _record: None,
            tasks._production_prompt({
                "request": {"request": "Produce the agreed effects."},
                "agreement": {"closing_summary": closing_summary()},
            }),
            tasks.validate_production_completion,
            participant_process_factory=lifecycle._spawn_participant,
        )
        self.assertTrue(completion["completed"])
        production = self.store.read_activity("kinds")["events"][-1]
        self.assertEqual(
            (production["kind"], production["stage"],
             production["participant_id"], production["round"]),
            ("production_effect", "production", "initial-position", 1),
        )
        self.assertEqual(
            (production["model_family"], production["model"],
             production["effort"]),
            seats[0],
        )
        self.assertEqual(
            [(call["family"], call["model"], call["effort"])
             for call in self.provider_calls("production_effect")],
            [seats[0]],
        )

        # A synthetic recovery entry evidences NO provider call, so it keeps
        # null staffing rather than inventing the roster's.
        recovered = tasks._recover_effect_attempt(
            self.store, "kinds", "task-1",
            {"state": self.store.read("kinds").state},
        )
        self.assertIsNotNone(recovered)
        synthetic = self.store.read_activity("kinds")["events"][-1]
        self.assertEqual(
            (synthetic["kind"], synthetic["participant_id"]),
            ("production_effect", tasks._RECOVERED_EFFECT_PARTICIPANT),
        )
        self.assertEqual(
            (synthetic["model_family"], synthetic["model"],
             synthetic["effort"]),
            (None, None, None),
        )
        self.assertEqual(
            brainstorming.validate_activity_event(synthetic)["model_family"],
            None,
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

    def seat_staffing(self, subject, run_config):
        return [
            (
                subject.executors[seat["executor_ref"]].model_family,
                subject.executors[seat["executor_ref"]].model,
                subject.executors[seat["executor_ref"]].effort,
            )
            for seat in run_config["participants"]
        ]

    def agree(self, session_id, record, subject=None, supplied=None):
        """Run one whole discussion to its accepted agreement."""
        subject = subject or self.executors(
            record, dispatching=True, supplied=supplied
        )
        coordinator = coordination.BrainstormingCoordinator(
            self.store, subject
        )
        context = record["execution_context"]
        for _seat in self.store.read(session_id).state["run_config"][
            "participants"
        ]:
            coordinator.run_next_turn(session_id, context)
        terminal = coordinator.run_closure(session_id, context)
        self.assertEqual(terminal.state["status"], "success")
        return subject

    def ran(self, session_id):
        """What every stored activity entry of *session_id* says ran."""
        return [
            (event["model_family"], event["model"], event["effort"])
            for event in self.store.read_activity(session_id)["events"]
        ]

    def test_pre_cutover_brainstorming_bindings_resume_without_rewrite(self):
        """The compatibility boundary, in both stored shapes.

        A stored explicit `static` binding restarts and completes on its
        own pins, through the real registry and real provider calls. An
        attached `current_profile` record is NOT a pin: its next call takes
        the owning run's session. Neither stored record moves a byte.
        """
        pinned = [
            {"id": "initial-position", "role": "initial_position",
             "delivery": "llm", "model_family": "codex",
             "model": "gpt-5.6-luna", "effort": "low"},
            {"id": "contrary-position", "role": "contrary_position",
             "delivery": "llm", "model_family": "claude",
             "model": "claude-sonnet-5", "effort": "medium"},
        ]
        pins = [("codex", "gpt-5.6-luna", "low"),
                ("claude", "claude-sonnet-5", "medium")]
        static = self.dispatched(
            "static", static_pins=pinned, caller="task:standalone-7"
        )
        before = self.stored_bytes("static")

        # Nothing about this record is router-backed, so a supplied session
        # — the owner's, or a launcher's answer — reaches nothing.
        self.assertFalse(lifecycle._router_staffed(static))
        self.assertIsNone(
            lifecycle._record_staffing_binding(self.home, static, self.session)
        )

        # The stored record restarts through the registry that holds it,
        # and the launcher is handed no staffing session to resolve with.
        launched = self.restart("static", lambda _record: self.session)
        launched.assert_called_once_with(
            self.home, "static", staffing_session=None
        )
        self.assertEqual(self.stored_bytes("static"), before)

        # And it COMPLETES on those pins: a full round and its closure
        # ballot, every call a real process, without one router question.
        with mock.patch.object(
            staffing, "resolve",
            side_effect=AssertionError("a static binding asked the router"),
        ):
            subject = self.agree("static", static)
        self.assertEqual(
            self.seat_staffing(
                subject, self.store.read("static").state["run_config"]
            ),
            pins,
        )
        self.assertEqual(self.ran("static"), pins + pins)
        self.assertEqual(
            [(call["family"], call["model"], call["effort"])
             for call in self.provider_calls()],
            pins + pins,
        )
        self.assertEqual(self.stored_bytes("static"), before)

        # A stored static TASK keeps the same boundary: its frozen seats
        # are the create body, and the owner's session is not forwarded.
        # The record is minted the only way one still can be — through an
        # admission carrying no selection at all — which is exactly the
        # shape every pre-cutover direct order left behind.
        task_state = {}
        order = {
            "task_executor": "brainstorming",
            "request": {
                "work_area": {
                    "workspace_path": self.workspace,
                    "primary": self.workspace,
                    "additional": [],
                },
                "request": "Resolve one bounded request.",
                "context": {"brief": "Resolve one bounded request."},
                "reference_documents": [],
            },
        }
        admitted = tasks.admit_task(
            task_state, order, CONFIG, self.workspace
        )
        stored_task = json.dumps(admitted, sort_keys=True)
        self.assertEqual(
            admitted["resolved_staffing"]["dispatch_authority"], "static"
        )
        with mock.patch.object(
            lifecycle, "create_resolved_session",
            return_value={"id": "bs-static", "state": {"status": "running"}},
        ) as create:
            tasks.start_task(
                task_state, admitted["id"], CONFIG, self.home,
                staffing_selection={"session": self.session},
            )
        self.assertTrue(create.call_args.kwargs["static_binding"])
        self.assertNotIn("staffing_selection", create.call_args.kwargs)
        self.assertEqual(
            create.call_args.args[1]["participants"],
            admitted["resolved_staffing"]["participants"],
        )

        # Its agreed production effect is one more call of the same frozen
        # seats, through the adapter's own effect entry.
        frozen = [
            seat for seat in admitted["resolved_staffing"]["participants"]
            if seat["delivery"] == "llm"
        ]
        owned = self.dispatched(
            "static-task",
            static_pins=frozen,
            caller="task:" + admitted["id"],
        )
        owned_before = self.stored_bytes("static-task")
        with mock.patch.object(
            staffing, "resolve",
            side_effect=AssertionError("a static task asked the router"),
        ):
            self.agree("static-task", owned)
            self.store.begin_task_effect_attempt("static-task", {
                "task_id": admitted["id"],
                "token": "static-effect-1",
                "started_at": time.time(),
            })
            effect = tasks.apply_agreed_effects(
                self.home,
                "static-task",
                admitted["id"],
                {
                    "request": {"request": "Produce the agreed effects."},
                    "agreement": {"closing_summary": closing_summary()},
                },
                "static",
                participant_process_factory=lifecycle._spawn_participant,
            )
        self.assertTrue(effect["completed"], effect)
        lead = (frozen[0]["model_family"], frozen[0]["model"],
                frozen[0]["effort"])
        self.assertEqual(
            [(call["family"], call["model"], call["effort"])
             for call in self.provider_calls("production_effect")],
            [lead],
        )
        self.assertEqual(self.stored_bytes("static-task"), owned_before)
        self.assertEqual(
            json.dumps(
                tasks.tasks.task_record(task_state, admitted["id"]),
                sort_keys=True,
            ),
            stored_task,
        )

        # The attached profile-backed shape: no mark either, but its calls
        # follow the owning run's session rather than any pin.
        attached = self.dispatched(
            "attached-profile",
            static_pins=pinned,
            caller=lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX
            + admitted["id"],
        )
        attached_before = self.stored_bytes("attached-profile")
        self.assertTrue(lifecycle._router_staffed(attached))
        self.assertEqual(
            lifecycle._record_staffing_binding(
                self.home, attached, self.session
            ),
            {"home": os.path.abspath(self.home), "session": self.session},
        )
        self.agree("attached-profile", attached, supplied=self.session)
        answers = [self.answer(1, 1), self.answer(2, 1)]
        self.assertEqual(self.ran("attached-profile"), answers + answers)
        self.assertNotIn(pins[0], self.ran("attached-profile"))
        self.assertEqual(
            self.stored_bytes("attached-profile"), attached_before
        )

        # And the boundary is closed on the other side: the live direct
        # order path admits NO legacy authority any more. A Brainstorming
        # task ordered through the service since the cutover is
        # router-backed holding no session of its own, so it freezes no
        # family, model or effort at admission and nothing distinguishes
        # it from an attached task except which session answers it.
        with mock.patch.object(
            service.driver, "load_config",
            side_effect=lambda _path=None: copy.deepcopy(CONFIG),
        ):
            _order, direct, _primary, _project = (
                service._resolve_direct_task_order(
                    self.home,
                    {"email": "operator@example.com", "admin": True},
                    copy.deepcopy(order),
                )
            )
        self.assertEqual(direct["dispatch_authority"], "current_profile")
        self.assertEqual(
            direct["participants"], brainstorming_milestone._participants()
        )
        for seat in direct["participants"]:
            for field in ("model_family", "model", "effort"):
                self.assertNotIn(field, seat)

    def restart(self, session_id, resolve_staffing_session):
        """Explicitly restart one stopped stored record.

        Only the child process is stood in for: the record is read from,
        and written back to, the registry this home actually serves, so a
        restart that rewrote it would be visible in its stored bytes.
        """
        launch = mock.Mock()
        launch.process.pid = 4242
        launch.process.poll.return_value = None

        with mock.patch.object(
            lifecycle, "_launch_lifecycle_process", return_value=launch
        ) as launched, mock.patch.object(
            lifecycle, "_track_child"
        ):
            lifecycle.start_session(
                self.home,
                session_id,
                lambda _record: None,
                resolve_staffing_session=resolve_staffing_session,
            )
        return launched

    def test_restart_forwards_the_same_live_reference(self):
        record = self.durable("restart", staffing_session=False)
        record.pop("staffing_session", None)
        self.register(lifecycle._validate_record(record))
        before = self.stored_bytes("restart")

        # A pre-cutover attached record carries no mark, so the launcher's
        # answer is the only source it has.
        launched = self.restart("restart", lambda _record: self.session)
        launched.assert_called_once_with(
            self.home, "restart", staffing_session=self.session
        )
        # Nothing about the stored record changed.
        self.assertEqual(self.stored_bytes("restart"), before)
        self.assertNotIn("staffing_session", json.loads(before))

        # A MARKED record is its own authority, so the launcher's lookup is
        # not consulted at all — and cannot veto the restart by failing.
        # This is the one an owning run that was deregistered, moved or is
        # no longer waiting on the discussion would take.
        marked = self.register(self.durable("marked-restart"))

        def unreachable(_record):
            raise RuntimeError("the owning run cannot be reached")

        launched = self.restart("marked-restart", unreachable)
        launched.assert_called_once_with(
            self.home, "marked-restart", staffing_session=self.session
        )


class OwnerSessionInheritanceTest(unittest.TestCase):
    """One inherited staffing session, on both entry paths.

    Attached work — a design rethink, a guarantee calibration, an agreed
    production effect — carries the run's own bound id and never a second
    one. A standalone caller names a session they may already read, or names
    none and takes the default document; either way the durable record says
    the router staffs it.
    """

    maxDiff = None
    MEMBER = "jdcf1710@gmail.com"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bs-owner-session-")
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.workspace = os.path.join(self.tmp.name, "workspace")
        self.run_workspace = os.path.join(self.tmp.name, "run-workspace")
        os.makedirs(self.home)
        os.makedirs(os.path.join(self.workspace, "docs"))
        os.makedirs(self.run_workspace)
        self.config = copy.deepcopy(driver.DEFAULT_CONFIG)
        self.config.update(copy.deepcopy(CONFIG))
        self.processes = []
        self.addCleanup(self._reap)
        config_patch = mock.patch.object(
            lifecycle.driver,
            "load_config",
            side_effect=lambda _path=None: copy.deepcopy(self.config),
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)
        # A real service over an isolated home: it seeds the staffing
        # catalogue exactly as a served home holds it.
        self.server = service.make_server(self.home, 0)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    # -- fixtures --------------------------------------------------------

    def _reap(self):
        for process in self.processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _sleeper_launcher(self, _home, _session_id, staffing_session=None):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.processes.append(process)
        return lifecycle.GatedLaunch(process, lambda: None, lambda: None)

    def _request(self, method, path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method=method
        )
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def _member_headers(self, email):
        return {
            "Host": "example.ngrok-free.dev",
            access.REMOTE_HEADER: access.REMOTE_MARKER,
            access.USER_HEADER: email,
        }

    def _ready_project(self, slug, users=None):
        service.create_project(self.home, {"slug": slug})
        if users is not None:
            service.update_project_users(self.home, slug, {"users": users})
        view = service.declare_work_area(self.home, slug, {
            "name": "main",
            "primary_path": self.workspace,
            "additional_paths": [],
        })
        record = view["record"]
        self.assertTrue(service._work_area_store(self.home, slug).confirm(
            "main",
            record["primary"],
            record["additional"],
            service._executor_id(self.home),
        ).ok)

    def _payload(self, target, staffing_session=None, project=None,
                 include_staffing=True):
        path = os.path.join(self.workspace, "docs", target)
        with open(path, "wb") as handle:
            handle.write(b"initial target")
        body = {
            "request": {
                "workspace_path": self.workspace,
                "target_path": "docs/%s" % target,
                "request": "Select the bounded result to accept.",
                "context": {"brief": "Resolve one bounded request."},
                "max_rounds": 1,
            },
            "participants": [
                {"id": "lead", "role": "initial_position", "delivery": "llm"},
                {"id": "critic", "role": "contrary_position",
                 "delivery": "llm"},
            ],
            "closure_policy": "unanimity",
        }
        if include_staffing:
            body["staffing_session"] = staffing_session
        if project is not None:
            body["project"] = project
            body["work_area"] = "main"
        return body

    def _open_staffing_session(self, work_area):
        return staffing.create_session(self.home, {
            "work_area": work_area,
            "families": list(CONFIG["families_order"]),
            "document": staffing.DEFAULT_DOCUMENT_NAME,
            "rigor": "medium",
        })["id"]

    def _staffing_session_files(self):
        directory = staffing.staffing_sessions_dir(self.home)
        return sorted(os.listdir(directory)) if os.path.isdir(directory) else []

    def _seats(self, session):
        """The families the router gives roster seats 1 and 2 of *session*."""
        return [
            staffing.resolve(
                self.home, session, "brainstorm", index=index,
                families=list(CONFIG["families_order"]),
            ).answer["agent"]
            for index in (1, 2)
        ]

    def _run_driver(self):
        """One milestone run holding exactly one bound staffing session."""
        state_path = driver.init_run(
            "owner session",
            self.run_workspace,
            config=copy.deepcopy(self.config),
            model_profiles_home=self.home,
        )
        run_state = st.load(state_path)
        self.owner = self._open_staffing_session(
            {"workspace_path": self.run_workspace}
        )
        st.bind_staffing_session(run_state, self.owner)
        run_state["milestone"]["slices"] = [{"id": 1, "title": "One"}]
        st.save(state_path, run_state)
        return driver.Driver(
            state_path,
            runner=runners.MockRunner([]),
            model_profiles_home=self.home,
        )

    # -- the acceptance row ----------------------------------------------

    def test_attached_and_standalone_sessions_inherit_one_staffing_session(
        self,
    ):
        self._attached_entries_carry_the_runs_exact_id()
        self._standalone_create_authorizes_and_defaults()

    def _attached_entries_carry_the_runs_exact_id(self):
        run = self._run_driver()
        # The one seam every attached entry reads.
        self.assertEqual(run._brainstorming_staffing(), {"session": self.owner})

        # 1. A design rethink's independent discussion.
        unit = st.current_unit(run.state)
        skeleton = run._skeleton_artifact()
        os.makedirs(
            os.path.join(self.run_workspace, os.path.dirname(skeleton)),
            exist_ok=True,
        )
        with open(
            os.path.join(self.run_workspace, skeleton), "w", encoding="utf-8"
        ) as handle:
            handle.write("# skeleton\n")
        design_unit = {
            "kind": "slice_doc", "slice_id": 1, "status": "running",
            "artifact": None, "rounds": [],
        }
        run.state["units"].append(design_unit)
        captured = {}

        def created(*_args, **kwargs):
            captured.setdefault("design", kwargs.get("staffing_selection"))
            return {
                "id": "bs-design",
                "state": {
                    "completed_turns": [],
                    "rounds_used": 0,
                    "recovery_baseline_revision": "revision-1",
                    "accepted_target_revision": None,
                },
            }

        with mock.patch.object(
            brainstorming_milestone, "create_session", side_effect=created
        ):
            run._start_rethink(
                design_unit,
                contracts.KIND_DRAFT_SLICE_NOTE,
                "codex",
                "gpt-5.6-sol",
                "high",
                {
                    "status": "need_rethink",
                    "kind": contracts.KIND_DRAFT_SLICE_NOTE,
                    "request": "Settle one bounded design question.",
                    "finding": {"summary": "one contradiction"},
                    "target_path": skeleton,
                    "max_rounds": 20,
                    "result_mode": "design_amendment",
                },
                types.SimpleNamespace(
                    duration_s=1.0, token_usage=None, cost=None,
                    session_ref="provider-session-1",
                ),
                os.path.join(self.run_workspace, "raw.txt"),
                "raw",
            )

        # 2. The guarantee calibration held against a drafted skeleton.
        run.config["guarantee_calibration"] = {"enabled": True}
        unit["artifact"] = skeleton

        def calibration(*_args, **kwargs):
            captured.setdefault(
                "calibration", kwargs.get("staffing_selection")
            )
            return {"id": "bs-calibration"}

        with mock.patch.object(
            brainstorming_milestone,
            "create_guarantee_calibration_session",
            side_effect=calibration,
        ):
            run._start_guarantee_calibration(unit)

        # 3. The agreed production task: admission, start and the effect.
        request = {
            "work_area": {
                "workspace_path": self.run_workspace,
                "primary": self.run_workspace,
                "additional": [],
            },
            "request": "Produce the slice note.",
            "context": {"task_kind": contracts.KIND_DRAFT_SLICE_NOTE},
            "reference_documents": [],
        }
        production_unit = {
            "kind": "slice_doc", "slice_id": 1, "status": "running",
            "artifact": None, "rounds": [],
        }
        run.state["units"].append(production_unit)
        run.state["milestone"]["slices"][0]["producer_task_executor"] = {
            "draft_slice_note": {"task_executor": "brainstorming"},
            "implement": {"task_executor": "brainstorming"},
        }

        def started(_state, _task_id, _config, _home, staffing_selection=None):
            captured.setdefault("start", staffing_selection)
            return {"id": "bs-production", "state": {"status": "running"}}

        def finished(_state, _task_id, _home, _session_id, effects):
            captured.setdefault("effect_call", effects)
            return None

        def effects(_home, _session_id, _task_id, _request,
                    dispatch_authority=None, staffing_selection=None):
            captured.setdefault("effect", staffing_selection)
            captured.setdefault("authority", dispatch_authority)
            return {"completed": True}

        with mock.patch.object(
            driver.Driver,
            "_brainstorming_production_request",
            return_value=(request, None),
        ), mock.patch.object(
            tasks, "start_task", side_effect=started
        ), mock.patch.object(
            tasks, "finish_task", side_effect=finished
        ), mock.patch.object(
            tasks, "apply_agreed_effects", side_effect=effects
        ):
            record, _planned = run._admit_brainstorming_production(
                production_unit, contracts.KIND_DRAFT_SLICE_NOTE
            )
            captured["admit"] = record["resolved_staffing"]
            run._start_brainstorming_production(
                production_unit, contracts.KIND_DRAFT_SLICE_NOTE
            )
            run._do_brainstorming_production_wait(
                production_unit, production_unit["brainstorming_wait"]
            )
            captured["effect_call"]({"agreement": "accepted"})

        # Every attached entry named the run's ONE session, and the admitted
        # task froze no seat of its own to compete with it.
        self.assertEqual(
            [
                captured["design"], captured["calibration"],
                captured["start"], captured["effect"],
            ],
            [
                {"session": self.owner},
                {"session": self.owner},
                {"session": self.owner, "material": None},
                {"session": self.owner, "material": None},
            ],
        )
        self.assertEqual(captured["authority"], "current_profile")
        self.assertEqual(
            captured["admit"]["dispatch_authority"], "current_profile"
        )
        for seat in captured["admit"]["participants"]:
            for field in ("model_family", "model", "effort"):
                self.assertNotIn(field, seat)

        # And ONE channel: an owner that resolved its own roots names its
        # session as the argument beside them. A body that also carried one
        # could disagree with it, so the resolved create refuses rather
        # than letting the argument win silently.
        body = self._payload("resolved.md", staffing_session=self.owner)
        with self.assertRaises(lifecycle.PublicLifecycleError) as refused:
            lifecycle.create_resolved_session(
                self.home,
                body,
                "milestone:owner",
                {
                    "workspace_path": self.run_workspace,
                    "project": None,
                    "work_area": None,
                    "primary": {"path": self.run_workspace},
                    "additional": [],
                },
                copy.deepcopy(self.config),
                staffing_selection={"session": self.owner},
            )
        self.assertEqual(
            (refused.exception.status, refused.exception.code),
            (400, lifecycle.INVALID_REQUEST),
        )

    def _standalone_create_authorizes_and_defaults(self):
        owner = self._open_staffing_session(
            {"workspace_path": self.workspace}
        )

        # A session the caller may already read is honoured, and the
        # discussion's seats are that session's own answers.
        with mock.patch.object(
            lifecycle,
            "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ):
            status, body = self._request(
                "POST",
                "/api/brainstorming/sessions",
                self._payload("named.md", staffing_session=owner),
            )
        self.assertEqual(status, 201, body)
        named = lifecycle._record_by_id(self.home, body["session"]["id"])
        self.assertEqual(named["staffing_session"], owner)
        self.assertEqual(
            [
                seat["model_family"]
                for seat in body["session"]["state"]["run_config"][
                    "participants"
                ]
            ],
            self._seats(owner),
        )

        # An unknown id and another project's id are refused with the
        # session route's own classifications, and neither creates anything.
        registry_before = pathlib.Path(
            lifecycle.registry_path(self.home)
        ).read_bytes()
        status, unknown = self._request(
            "POST",
            "/api/brainstorming/sessions",
            self._payload("unknown.md", staffing_session="stf-" + "0" * 32),
        )
        self.assertEqual(
            (status, unknown["error"]),
            (404, service.UNKNOWN_STAFFING_SESSION),
            unknown,
        )
        self._ready_project("alpha", users=[self.MEMBER])
        service.create_project(self.home, {"slug": "beta"})
        foreign = self._open_staffing_session(
            {"project": "beta", "work_area": "main"}
        )
        status, refused = self._request(
            "POST",
            "/api/brainstorming/sessions",
            self._payload(
                "foreign.md", staffing_session=foreign, project="alpha"
            ),
            headers=self._member_headers(self.MEMBER),
        )
        self.assertEqual(
            (status, refused["error"]), (403, service.FORBIDDEN), refused
        )
        self.assertEqual(
            pathlib.Path(lifecycle.registry_path(self.home)).read_bytes(),
            registry_before,
        )

        # Omitting the reference is the DEFAULT document, not the retired
        # roster: the record carries the mark with no session behind it, and
        # nobody opened a second staffing session to represent it.
        opened = self._staffing_session_files()
        for label, body_kwargs in (
            ("absent", {"include_staffing": False}),
            ("explicit null", {"staffing_session": None}),
        ):
            with self.subTest(reference=label):
                with mock.patch.object(
                    lifecycle,
                    "_launch_lifecycle_process",
                    side_effect=self._sleeper_launcher,
                ):
                    status, created = self._request(
                        "POST",
                        "/api/brainstorming/sessions",
                        self._payload(
                            "default-%s.md" % label.split()[0], **body_kwargs
                        ),
                    )
                self.assertEqual(status, 201, created)
                record = lifecycle._record_by_id(
                    self.home, created["session"]["id"]
                )
                self.assertIn("staffing_session", record)
                self.assertIsNone(record["staffing_session"])
                self.assertTrue(lifecycle._router_staffed(record))
                self.assertEqual(
                    [
                        seat["model_family"]
                        for seat in created["session"]["state"]["run_config"][
                            "participants"
                        ]
                    ],
                    self._seats(None),
                )
        self.assertEqual(self._staffing_session_files(), opened)

        # An explicit restart keeps the same live reference: the record is
        # its own authority, so no owner lookup is consulted for it.
        stored = copy.deepcopy(named)
        with mock.patch.object(
            lifecycle, "_process_alive", return_value=False
        ), mock.patch.object(
            lifecycle, "_launch_lifecycle_process",
            side_effect=self._sleeper_launcher,
        ) as relaunched:
            lifecycle.start_session(
                self.home,
                named["id"],
                lambda _record: None,
                resolve_staffing_session=self._unreachable_owner,
            )
        self.assertEqual(
            relaunched.call_args.kwargs, {"staffing_session": owner}
        )
        restarted = lifecycle._record_by_id(self.home, named["id"])
        self.assertEqual(
            dict(restarted, pid=None), dict(stored, pid=None)
        )

    @staticmethod
    def _unreachable_owner(_record):
        raise AssertionError("a marked record consults no owner lookup")


if __name__ == "__main__":
    unittest.main()
