"""Focused proof for the Brainstorming TaskExecutor adapter."""

import copy
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from orchestrator import brainstorming as bs
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import brainstorming_tasks as adapter
from orchestrator import tasks


def usage(amount):
    return {
        "input_tokens": amount,
        "cached_input_tokens": 0,
        "output_tokens": amount,
        "reasoning_output_tokens": 0,
        "total_tokens": amount * 2,
    }


def effect(completed=True, amount=3, **changes):
    value = {
        "completed": completed,
        "duration_s": float(amount),
        "token_usage": usage(amount),
        "token_usage_partial": False,
        "cost": {"api_usd": amount / 10.0, "real_usd": 0.0},
        "cost_partial": False,
    }
    if not completed:
        value["reason"] = "the agreed production effects did not complete"
    value.update(changes)
    return value


class EffectStore:
    def __init__(self):
        self.attempt = None
        self.activity = {"schema_version": 1, "events": []}

    def read_task_effect_attempt(self, _session_id):
        return copy.deepcopy(self.attempt)

    def begin_task_effect_attempt(self, _session_id, attempt):
        if self.attempt is not None:
            raise bs.HistoryRewriteError("effect attempt already exists")
        self.attempt = bs.validate_task_effect_attempt(attempt)
        return copy.deepcopy(self.attempt)

    def finish_task_effect_attempt(self, _session_id, token):
        if self.attempt is not None and self.attempt["token"] != token:
            raise bs.HistoryRewriteError("effect attempt token changed")
        self.attempt = None

    def read_activity(self, _session_id):
        return copy.deepcopy(self.activity)

    def append_activity(self, _session_id, event):
        checked = bs.validate_activity_event(event)
        self.activity["events"].append(checked)
        return copy.deepcopy(self.activity)


class BrainstormingTaskAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="brainstorming-tasks-")
        self.addCleanup(self.tmp.cleanup)
        self.workspace = os.path.join(self.tmp.name, "workspace")
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(os.path.join(self.workspace, "out"))
        os.makedirs(self.home)
        subprocess.run(["git", "init", "-q", self.workspace], check=True)
        subprocess.run(
            ["git", "-C", self.workspace, "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", self.workspace, "config", "user.name", "Test"],
            check=True,
        )
        seed = os.path.join(self.workspace, "seed.txt")
        with open(seed, "w", encoding="utf-8") as handle:
            handle.write("seed\n")
        subprocess.run(["git", "-C", self.workspace, "add", "seed.txt"], check=True)
        subprocess.run(
            ["git", "-C", self.workspace, "commit", "-qm", "seed"],
            check=True,
        )
        self.effect_store = EffectStore()
        self.config = {
            "families_order": ["codex", "claude"],
            "commands": {
                "codex": [
                    sys.executable,
                    "exec",
                    "--output-last-message",
                    "{output_file}",
                ],
                "claude": [sys.executable, "-p"],
            },
            "timeouts": {},
            "model_defaults": {
                "codex": {"model": "codex-default", "effort": "high"},
                "claude": {"model": "claude-default", "effort": "medium"},
            },
            "worker_stall_window_s": 0,
            "worker_stall_min_cpu_s": 0,
        }

    def request(self, **changes):
        value = {
            "work_area": {
                "workspace_path": self.workspace,
                "primary": self.workspace,
                "additional": [],
            },
            "request": "Create out/first.md and out/second.md.",
            "context": {"goal": "one bounded task"},
            "reference_documents": ["docs/reference.md"],
        }
        value.update(changes)
        return value

    def order(self, request=None, **configuration):
        return {
            "task_executor": "brainstorming",
            "request": request or self.request(),
            "configuration": configuration,
        }

    def projection(
        self,
        task_id,
        status="success",
        duration=2.0,
        token_amount=2,
        partial=False,
    ):
        native = {
            "outcome": status,
            "target_ref": "/private/agreement.md",
            "transcript_ref": "/private/chat.md",
            "rounds_used": 2,
        }
        if status == "failure":
            native["reason"] = "No bounded agreement was reached."
        return {
            "caller": "task:" + task_id,
            "process": "stopped",
            "state": {
                "status": status,
                "result": native,
                "accepted_target_revision": (
                    "accepted-revision" if status == "success" else None
                ),
            },
            "work_duration_s": duration,
            "work_token_usage": None if partial else usage(token_amount),
            "work_token_usage_partial": partial,
            "work_cost": (
                None
                if partial
                else {"api_usd": token_amount / 10.0, "real_usd": 0.0}
            ),
            "work_cost_partial": partial,
        }

    def retain_task_session(self, record, session_id, activity_amount=4,
                            target_path=None):
        work_area, target = adapter._private_target(
            self.workspace, self.home, record["id"]
        )
        self.addCleanup(lambda: shutil.rmtree(work_area, ignore_errors=True))
        body = adapter._creation_body(
            record,
            adapter._frozen_participants(record),
            target,
            self.workspace,
        )
        if target_path is not None:
            body["request"]["target_path"] = target_path
        _runtime, run_config, eligible = lifecycle._runtime_and_roster(
            self.config,
            body["participants"],
            body["closure_policy"],
            self.workspace,
            static_binding=True,
        )
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        store.create(session_id, body["request"], run_config, eligible)
        store.append_activity(session_id, {
            "id": "activity-retained",
            "action_id": "retained-discussion",
            "provider_attempt": 1,
            "at": "2026-08-16T12:00:00+0000",
            "started_at": 1.0,
            "duration_s": float(activity_amount),
            "kind": "discussion_turn",
            "stage": "discussion",
            "round": 1,
            "participant_id": body["participants"][0]["id"],
            "model_family": "codex",
            "model": "codex-default",
            "effort": "high",
            "status": "completed",
            "token_usage": usage(activity_amount),
            "cost": {
                "api_usd": activity_amount / 10.0,
                "real_usd": 0.0,
            },
        })
        return store, work_area

    def test_attached_launch_carries_the_owner_session_and_pins_no_seat(self):
        state = {}
        selection = {"session": "staffing-session-1"}
        request = self.request(output_directory="out")
        order = self.order(
            request, max_rounds=24, closure_policy="majority"
        )
        order["prompt_set"] = "operator"
        record = adapter.admit_task(
            state,
            order,
            self.config,
            self.workspace,
            staffing_selection=selection,
        )
        with mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
            return_value={"id": "bs-profile", "state": {"status": "running"}},
        ) as create:
            created = adapter.start_task(
                state,
                record["id"],
                self.config,
                self.home,
                staffing_selection=selection,
            )

        self.assertEqual(created["id"], "bs-profile")
        body = create.call_args.args[1]
        self.assertEqual(body["request"]["max_rounds"], 24)
        self.assertEqual(body["closure_policy"], "majority")
        self.assertEqual(body["prompt_set"], "operator")
        self.assertEqual(
            record["order"]["brainstorming_mode"], "repository_review"
        )
        historical = copy.deepcopy(record)
        historical["order"].pop("prompt_set")
        historical_body = adapter._creation_body(
            historical,
            body["participants"],
            "/private/agreement.md",
            self.workspace,
        )
        self.assertEqual(historical_body["prompt_set"], "default")
        # Nothing about the intelligence is frozen here: every seat resolves
        # through the owner's session immediately before its own call.
        for seat in body["participants"]:
            for field in ("model_family", "model", "effort"):
                self.assertNotIn(field, seat)
        self.assertEqual(
            record["resolved_staffing"]["participants"],
            adapter.milestone._participants(),
        )
        self.assertEqual(
            create.call_args.kwargs["staffing_selection"], selection
        )
        self.assertEqual(
            create.call_args.args[2],
            lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX + record["id"],
        )
        self.assertNotIn("target_path", record["order"]["request"])
        self.assertNotIn("target_path", body["request"])
        charge = body["request"]["context"]["source_payload"][
            "session_charge"
        ]
        self.assertEqual(
            charge["job"], adapter.prompt_router.STANDALONE_REPOSITORY_SESSION_JOB
        )
        self.assertEqual(charge["repository"]["mode"], "standalone_task")
        self.assertEqual(
            body["request"]["context"]["source_payload"]["output_directory"],
            os.path.realpath(os.path.join(self.workspace, "out")),
        )
        self.assertIsNone(record["result"])

    def test_direct_launch_preserves_text_context(self):
        selection = {"session": None}
        task_context = "Use only the named manuscript."
        state = {}
        record = adapter.admit_task(
            state,
            self.order(self.request(context=task_context)),
            self.config,
            self.workspace,
            staffing_selection=selection,
        )
        with mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
            return_value={"id": "bs-direct", "state": {"status": "running"}},
        ) as create:
            created = adapter.start_task(
                state,
                record["id"],
                self.config,
                self.home,
                staffing_selection=selection,
            )

        self.assertEqual(created["id"], "bs-direct")
        body = create.call_args.args[1]
        self.assertFalse(body["create_target_parents"])
        self.assertEqual(
            body["request"]["context"]["source_payload"]["task_context"],
            task_context,
        )
        bs.validate_request(body["request"])
        projection = self.projection(record["id"], status="failure")
        projection["caller"] = (
            lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX + record["id"]
        )
        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-direct",
                None,
                effect_store=self.effect_store,
            )
        self.assertEqual(terminal["result"]["status"], "failure")

    def test_direct_launch_does_not_trust_caller_named_session_charge(self):
        selection = {"session": None}
        supplied = {
            "session_charge": {
                "job": "implement@slice_impl",
                "repository": {"pre_session_commit": "0" * 40},
            }
        }
        state = {}
        order = self.order(self.request(context=copy.deepcopy(supplied)))
        order["brainstorming_mode"] = "repository_review"
        record = tasks.admit_task(
            state,
            order,
            adapter.resolve_staffing(
                self.config, self.workspace, staffing_selection=selection
            ),
            primary_workspace=self.workspace,
        )
        with mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
            return_value={"id": "bs-direct", "state": {"status": "running"}},
        ) as create:
            adapter.start_task(
                state,
                record["id"],
                self.config,
                self.home,
                staffing_selection=selection,
            )

        source = create.call_args.args[1]["request"]["context"]["source_payload"]
        self.assertEqual(source["task_context"], supplied)
        self.assertEqual(
            source["session_charge"]["job"],
            adapter.prompt_router.STANDALONE_REPOSITORY_SESSION_JOB,
        )
        self.assertNotEqual(
            source["session_charge"]["repository"]["pre_session_commit"],
            "0" * 40,
        )

    def test_direct_repository_success_is_the_reviewed_result(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        base = subprocess.run(
            ["git", "-C", self.workspace, "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        native = {
            "outcome": "success",
            "transcript_ref": "/private/chat.md",
            "rounds_used": 2,
        }
        projection = {
            "caller": "task:" + record["id"],
            "process": "stopped",
            "state": {
                "status": "success",
                "result": native,
                "accepted_target_revision": base,
                "request": {
                    "workspace_path": self.workspace,
                    "context": {
                        "source_payload": {
                            "session_charge": {
                                "repository": {
                                    "mode": "standalone_task",
                                    "pre_session_commit": base,
                                }
                            }
                        }
                    },
                },
            },
            "work_duration_s": 2.0,
            "work_token_usage": usage(2),
            "work_token_usage_partial": False,
            "work_cost": {"api_usd": 0.2, "real_usd": 0.0},
            "work_cost_partial": False,
        }
        apply_effects = mock.Mock(
            side_effect=AssertionError("reviewed repository work must not rerun")
        )
        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-reviewed-direct",
                apply_effects,
            )

        apply_effects.assert_not_called()
        result = terminal["result"]
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["native_result"]["session_id"], "bs-reviewed-direct")
        self.assertEqual(result["native_result"]["source_base_revision"], base)
        self.assertEqual(result["native_result"]["accepted_revision"], base)

    def test_repository_delivery_drift_fails_the_task_without_rerunning_work(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        accepted = subprocess.run(
            ["git", "-C", self.workspace, "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        with open(
            os.path.join(self.workspace, "after-session.txt"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("later work\n")
        subprocess.run(
            ["git", "-C", self.workspace, "add", "after-session.txt"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", self.workspace, "commit", "-qm", "later work"],
            check=True,
        )
        projection = {
            "caller": "task:" + record["id"],
            "process": "stopped",
            "state": {
                "status": "success",
                "result": {
                    "outcome": "success",
                    "transcript_ref": "/private/chat.md",
                    "rounds_used": 1,
                },
                "accepted_target_revision": accepted,
                "request": {
                    "workspace_path": self.workspace,
                    "context": {"source_payload": {"session_charge": {
                        "repository": {
                            "mode": "standalone_task",
                            "pre_session_commit": accepted,
                        }
                    }}},
                },
            },
            "work_duration_s": 1.0,
            "work_token_usage": None,
            "work_token_usage_partial": True,
            "work_cost": None,
            "work_cost_partial": True,
        }
        effect = mock.Mock(
            side_effect=AssertionError("drift must not rerun repository work")
        )
        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ):
            terminal = adapter.finish_task(
                state, record["id"], self.home, "bs-drifted", effect
            )

        effect.assert_not_called()
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertIn("HEAD no longer equals", terminal["result"]["reason"])
        self.assertEqual(
            terminal["result"]["native_result"]["session_id"], "bs-drifted"
        )

    def test_pre_cutover_task_charge_starts_without_carrying_old_material(self):
        request = self.request(context={
            "task_kind": "implement",
            "session_charge": {
                "job": "implement@slice_impl",
                "prompt_set": "operator",
                "values": {},
                "amendments_path": os.path.join(
                    self.workspace, "amendments.json"
                ),
                "accepted_amendments": [],
                "repository": {
                    "state_path": os.path.join(self.workspace, "state.json"),
                    "skeleton_path": "docs/skeleton.md",
                    "pre_session_commit": "0" * 40,
                },
            },
        })
        order = self.order(request)
        order["prompt_set"] = "default"
        record = adapter.admit_task(
            {}, order, self.config, self.workspace
        )
        self.assertEqual(record["order"]["prompt_set"], "operator")
        legacy = copy.deepcopy(record)
        legacy["order"]["prompt_set"] = "default"
        legacy["order"]["staffing_material"] = "analysis"
        legacy["order"]["request"]["context"]["session_charge"][
            "material"
        ] = "code"

        body = adapter._creation_body(
            legacy,
            adapter._frozen_participants(legacy),
            "/private/agreement.md",
            self.workspace,
        )

        charge = body["request"]["context"]["source_payload"][
            "session_charge"
        ]
        self.assertEqual(body["prompt_set"], "operator")
        self.assertNotIn("material", charge)
        self.assertEqual(
            legacy["order"]["request"]["context"]["session_charge"][
                "material"
            ],
            "code",
        )
        bs.validate_request(body["request"])

    def test_participant_transcript_includes_caller_task_context(self):
        state = {}
        task_context = {
            "goal": "preserve the caller's bounded background",
            "constraints": ["reuse the existing adapter"],
        }
        record = adapter.admit_task(
            state,
            self.order(self.request(context=task_context)),
            self.config,
            self.workspace,
        )
        body = adapter._creation_body(
            record,
            adapter._frozen_participants(record),
            "/private/agreement.md",
            self.workspace,
        )
        _runtime, run_config, _eligible = lifecycle._runtime_and_roster(
            self.config,
            body["participants"],
            body["closure_policy"],
            self.workspace,
            static_binding=True,
        )
        session_state = bs.new_session_state(
            body["request"], run_config, "/private/chat.md"
        )

        transcript = bs.render_transcript(session_state)

        self.assertIn("Caller-supplied task context", transcript)
        self.assertIn(task_context["goal"], transcript)
        self.assertIn(task_context["constraints"][0], transcript)

    def test_static_order_freezes_complete_pins_and_unavailability_boundaries(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        staffing = record["resolved_staffing"]
        self.assertEqual(staffing["dispatch_authority"], "static")
        self.assertEqual(
            [seat["model_family"] for seat in staffing["participants"]],
            ["codex", "claude", "codex"],
        )
        for seat in staffing["participants"]:
            self.assertTrue(seat["model"])
            self.assertTrue(seat["effort"])

        changed = copy.deepcopy(self.config)
        changed["commands"]["codex"] = [
            sys.executable,
            "exec",
            "--model",
            "{model}",
            "--output-last-message",
            "{output_file}",
        ]
        changed["model_defaults"]["codex"]["model"] = None
        runtime, run_config, _eligible = lifecycle._runtime_and_roster(
            changed,
            staffing["participants"],
            "unanimity",
            self.workspace,
            static_binding=True,
        )
        self.assertEqual(
            runtime["executors"]["brainstorming-codex-initial-position"]["model"],
            "codex-default",
        )
        participant = next(
            item
            for item in run_config["participants"]
            if item["role"] == "contrary_position"
        )

        class Store:
            def read(_self, _session_id):
                return mock.Mock(state={
                    "run_config": run_config,
                    "participant_sessions": {},
                    "request": {"workspace_path": self.workspace},
                })

            def read_activity(_self, _session_id):
                return None

        participant_execution = lifecycle._participant_execution(
            Store(),
            {"id": "static-session", "runtime": runtime},
            None,
        )
        with mock.patch.object(
            lifecycle.errclass,
            "classify_worker_failure",
            return_value=("unknown", None, "test"),
        ) as classify:
            participant_execution.failure_classifier(
                "static-session",
                participant,
                participant_execution.executors[participant["executor_ref"]],
                RuntimeError("participant failed"),
            )
        self.assertEqual(classify.call_args.kwargs["opposite_family"], "codex")
        self.assertEqual(
            classify.call_args.kwargs["classifier_model"], "codex-default"
        )
        # Direct (static) seats run at the top effort, and the failure
        # classifier borrows the opposite seat's effort.
        self.assertEqual(
            classify.call_args.kwargs["classifier_effort"],
            adapter.DIRECT_BRAINSTORMING_EFFORT,
        )
        with self.assertRaises(lifecycle.PublicLifecycleError):
            lifecycle._runtime_and_roster(
                changed,
                staffing["participants"],
                "unanimity",
                self.workspace,
            )
        with mock.patch.object(
            adapter.lifecycle,
            "resolve_static_participants",
            side_effect=AssertionError("static launch selected staffing again"),
        ), mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
            return_value={"id": "bs-static", "state": {"status": "running"}},
        ) as create:
            adapter.start_task(
                state,
                record["id"],
                changed,
                self.home,
                staffing_selection={"session": "ambient-owner-session"},
            )
        self.assertEqual(
            create.call_args.args[1]["participants"], staffing["participants"]
        )
        self.assertEqual(create.call_args.args[2], "task:" + record["id"])
        self.assertTrue(create.call_args.kwargs["static_binding"])
        self.assertNotIn("staffing_selection", create.call_args.kwargs)

        unavailable_state = {}
        unavailable = copy.deepcopy(self.config)
        unavailable["families_order"] = []
        with self.assertRaises(tasks.TaskRequestError) as caught:
            adapter.admit_task(
                unavailable_state, self.order(), unavailable, self.workspace
            )
        self.assertEqual(caught.exception.code, tasks.TASK_UNAVAILABLE)
        self.assertEqual(tasks.task_records(unavailable_state), [])

        late_state = {}
        late = adapter.admit_task(
            late_state, self.order(), self.config, self.workspace
        )
        with mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
            side_effect=lifecycle.PublicLifecycleError(
                503, lifecycle.UNAVAILABLE
            ),
        ):
            self.assertIsNone(
                adapter.start_task(late_state, late["id"], self.config, self.home)
            )
        terminal = tasks.task_record(late_state, late["id"])
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertIn(lifecycle.UNAVAILABLE, terminal["result"]["reason"])

    def test_profile_authority_loss_before_session_durably_fails_task(self):
        state = {}
        selection = {"session": "staffing-session-1"}
        record = adapter.admit_task(
            state,
            self.order(),
            self.config,
            self.workspace,
            staffing_selection=selection,
        )

        with mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
        ) as create:
            self.assertIsNone(
                adapter.start_task(
                    state, record["id"], self.config, self.home
                )
            )

        create.assert_not_called()
        result = tasks.task_record(state, record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertIn("owner's staffing session", result["reason"])

    def test_profile_authority_loss_returns_running_owned_session(self):
        state = {}
        selection = {"session": "staffing-session-1"}
        record = adapter.admit_task(
            state,
            self.order(),
            self.config,
            self.workspace,
            staffing_selection=selection,
        )
        projection = self.projection(record["id"], status="running")
        projection["state"]["result"] = None
        projection["process"] = "running"
        caller = lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX + record["id"]
        projection["caller"] = caller

        def inspect(_home, _session_id, authorize):
            authorize({"caller": caller})
            return projection

        with mock.patch.object(
            adapter.lifecycle,
            "list_sessions",
            return_value=[{"id": "bs-profile-owned"}],
        ), mock.patch.object(
            adapter.lifecycle, "inspect_session", side_effect=inspect
        ), mock.patch.object(
            adapter.lifecycle, "start_session"
        ) as start:
            self.assertIs(
                adapter.start_task(
                    state, record["id"], self.config, self.home
                ),
                projection,
            )

        start.assert_not_called()
        self.assertIsNone(tasks.task_record(state, record["id"])["result"])

    def test_profile_authority_loss_fails_stopped_owned_session(self):
        state = {}
        selection = {"session": "staffing-session-1"}
        record = adapter.admit_task(
            state,
            self.order(),
            self.config,
            self.workspace,
            staffing_selection=selection,
        )
        projection = self.projection(record["id"], status="running")
        projection["state"]["result"] = None
        caller = lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX + record["id"]
        projection["caller"] = caller

        with mock.patch.object(
            adapter.lifecycle,
            "list_sessions",
            return_value=[{"id": "bs-profile-owned"}],
        ), mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ), mock.patch.object(
            adapter.lifecycle, "start_session"
        ) as start:
            self.assertIsNone(
                adapter.start_task(
                    state, record["id"], self.config, self.home
                )
            )

        start.assert_not_called()
        result = tasks.task_record(state, record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertIn("owner's staffing session", result["reason"])
        self.assertEqual(result["duration_s"], 2.0)

    def test_profile_authority_loss_preserves_terminal_native_failure(self):
        state = {}
        selection = {"session": "staffing-session-1"}
        record = adapter.admit_task(
            state,
            self.order(),
            self.config,
            self.workspace,
            staffing_selection=selection,
        )
        projection = self.projection(
            record["id"], status="failure", duration=6, token_amount=6
        )
        caller = lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX + record["id"]
        projection["caller"] = caller

        def inspect(_home, _session_id, authorize):
            authorize({"caller": caller})
            return projection

        with mock.patch.object(
            adapter.lifecycle,
            "list_sessions",
            return_value=[{"id": "bs-profile-owned"}],
        ), mock.patch.object(
            adapter.lifecycle, "inspect_session", side_effect=inspect
        ), mock.patch.object(
            adapter.lifecycle, "start_session"
        ) as start:
            recovered = adapter.start_task(
                state, record["id"], self.config, self.home
            )
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-profile-owned",
                None,
                effect_store=self.effect_store,
            )

        self.assertIs(recovered, projection)
        start.assert_not_called()
        result = terminal["result"]
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "No bounded agreement was reached.")
        self.assertEqual(result["duration_s"], 6.0)
        self.assertEqual(result["token_usage"], usage(6))
        self.assertEqual(result["cost"], {"api_usd": 0.6, "real_usd": 0.0})
        self.assertEqual(result["native_result"], projection["state"]["result"])

    def test_effect_completion_preserves_native_result_and_complete_accounting(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        projection = self.projection(
            record["id"], duration=7.0, token_amount=7
        )
        seen = []
        transcript = bs.SessionStore(
            lifecycle.state_directory(self.home)
        ).transcript_ref("bs-success")

        def inspect_under_transcript_lock(*_args, **_kwargs):
            with bs._exclusive_transcript(transcript):
                return projection

        self.assertNotEqual(
            adapter._task_lifecycle_lock(
                self.workspace, self.home, record["id"]
            ),
            transcript,
        )
        with mock.patch.object(
            adapter.lifecycle,
            "inspect_session",
            side_effect=inspect_under_transcript_lock,
        ), mock.patch.object(
            adapter,
            "_retained_agreement",
            return_value={
                "exists": True,
                "encoding": "utf-8",
                "content": "agreed production approach",
            },
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-success",
                lambda request: seen.append(request) or effect(amount=3),
                effect_store=self.effect_store,
            )

        self.assertEqual(seen[0]["request"], record["order"]["request"])
        self.assertNotIn("session_id", seen[0])
        result = terminal["result"]
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["native_result"], projection["state"]["result"])
        self.assertEqual(result["duration_s"], 10.0)
        self.assertEqual(result["token_usage"], usage(10))
        self.assertEqual(result["cost"], {"api_usd": 1.0, "real_usd": 0.0})
        self.assertFalse(result["token_usage_partial"])
        self.assertFalse(result["cost_partial"])

    def test_profile_loss_after_agreement_records_authority_failure(self):
        state = {}
        selection = {"session": "staffing-session-1"}
        record = adapter.admit_task(
            state,
            self.order(),
            self.config,
            self.workspace,
            staffing_selection=selection,
        )
        projection = self.projection(record["id"])
        caller = lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX + record["id"]
        projection["caller"] = caller

        def unavailable(
            _home,
            _session_id,
            authorize,
            *_args,
            **_kwargs,
        ):
            authorize({"caller": caller})
            raise lifecycle.PublicLifecycleError(503, lifecycle.UNAVAILABLE)

        def apply(effect_request):
            with mock.patch.object(
                adapter.brainstorming,
                "SessionStore",
                return_value=self.effect_store,
            ), mock.patch.object(
                adapter.lifecycle,
                "apply_production_effect",
                side_effect=unavailable,
            ):
                return adapter.apply_agreed_effects(
                    self.home,
                    "bs-profile-effect",
                    record["id"],
                    effect_request,
                    dispatch_authority="current_profile",
                    staffing_selection=None,
                )

        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ), mock.patch.object(
            adapter,
            "_retained_agreement",
            return_value={"exists": True, "encoding": "utf-8", "content": "plan"},
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-profile-effect",
                apply,
                effect_store=self.effect_store,
            )

        result = terminal["result"]
        self.assertEqual(result["status"], "failure")
        self.assertEqual(
            result["reason"],
            "production lead failed: the owner's staffing session "
            "is unavailable",
        )
        self.assertEqual(result["native_result"], projection["state"]["result"])
        self.assertEqual(result["token_usage"], usage(2))
        self.assertTrue(result["token_usage_partial"])

    def test_effect_failure_is_terminal_and_keeps_native_and_partial_effects(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        projection = self.projection(record["id"])
        partial_path = os.path.join(self.workspace, "out", "partial.md")

        def fail_effect(_request):
            with open(partial_path, "w", encoding="utf-8") as handle:
                handle.write("partial effect\n")
            return effect(
                completed=False,
                amount=1,
                token_usage=None,
                token_usage_partial=True,
                cost=None,
                cost_partial=True,
            )

        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ), mock.patch.object(
            adapter,
            "_retained_agreement",
            return_value={"exists": True, "encoding": "utf-8", "content": "plan"},
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-effect-failure",
                fail_effect,
                effect_store=self.effect_store,
            )
        result = terminal["result"]
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["native_result"], projection["state"]["result"])
        self.assertEqual(result["duration_s"], 3.0)
        self.assertTrue(result["token_usage_partial"])
        self.assertTrue(result["cost_partial"])
        self.assertTrue(os.path.isfile(partial_path))

    def test_effect_exception_keeps_elapsed_time_and_specific_cause(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        projection = self.projection(record["id"], duration=2.0)

        def fail_effect(_request):
            raise RuntimeError("workspace write was refused")

        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ), mock.patch.object(
            adapter,
            "_retained_agreement",
            return_value={"exists": True, "encoding": "utf-8", "content": "plan"},
        ), mock.patch.object(
            adapter.time, "time", side_effect=[100.0, 103.5]
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-effect-exception",
                fail_effect,
                effect_store=self.effect_store,
            )

        result = terminal["result"]
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["duration_s"], 5.5)
        self.assertIn("workspace write was refused", result["reason"])
        self.assertTrue(result["token_usage_partial"])
        self.assertTrue(result["cost_partial"])
        event = self.effect_store.activity["events"][0]
        self.assertEqual(event["duration_s"], 3.5)
        self.assertIn("workspace write was refused", event["error"])

    def test_native_failure_skips_effects_and_keeps_session_accounting(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        projection = self.projection(record["id"], status="failure", duration=4)
        apply_effects = mock.Mock(side_effect=AssertionError("effects after failure"))
        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-native-failure",
                apply_effects,
                effect_store=self.effect_store,
            )
        self.assertFalse(apply_effects.called)
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(
            terminal["result"]["native_result"], projection["state"]["result"]
        )
        self.assertEqual(terminal["result"]["duration_s"], 4.0)

    def test_slice_note_materializes_and_records_current_planned_path(self):
        planned = os.path.join("out", "slice-04.md")
        prepared = adapter.prepare_slice_note_request(
            self.request(output_directory="out"), planned
        )
        self.assertIn(planned, prepared["request"])
        with self.assertRaises(tasks.TaskRequestError):
            adapter.prepare_slice_note_request(
                self.request(output_directory="out"), "elsewhere/slice-04.md"
            )
        self.assertIn(
            planned,
            adapter.prepare_slice_note_request(self.request(), planned)["request"],
        )

        state = {}
        record = adapter.admit_task(
            state, self.order(prepared), self.config, self.workspace
        )
        projection = self.projection(record["id"])

        def materialize(effect_request):
            self.assertEqual(
                effect_request["request"]["output_directory"],
                os.path.realpath(os.path.join(self.workspace, "out")),
            )
            with open(
                os.path.join(self.workspace, planned), "w", encoding="utf-8"
            ) as handle:
                handle.write("# Slice 04\n")
            return effect()

        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ), mock.patch.object(
            adapter,
            "_retained_agreement",
            return_value={"exists": True, "encoding": "utf-8", "content": "plan"},
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-note",
                materialize,
                effect_store=self.effect_store,
            )
        unit = {"artifact": "legacy/predecessor.md"}
        self.assertEqual(
            adapter.record_slice_note_handoff(unit, terminal, planned), planned
        )
        self.assertEqual(unit["artifact"], planned)
        self.assertTrue(os.path.isfile(os.path.join(self.workspace, planned)))

    def test_launch_without_session_id_recovers_the_task_owned_session(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        running = self.projection(record["id"], status="running")
        running["state"]["result"] = None
        running["process"] = "running"
        with mock.patch.object(
            adapter.lifecycle,
            "list_sessions",
            side_effect=[[], [{"id": "bs-owned"}]],
        ), mock.patch.object(
            adapter.lifecycle,
            "inspect_session",
            return_value=running,
        ), mock.patch.object(
            adapter.lifecycle,
            "start_session",
            return_value=running,
        ), mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
            return_value={"id": "bs-owned", "state": {"status": "running"}},
        ) as create:
            first = adapter.start_task(
                state, record["id"], self.config, self.home
            )
            recovered = adapter.start_task(
                state, record["id"], self.config, self.home
            )
        self.assertEqual(first["id"], "bs-owned")
        self.assertIs(recovered, running)
        create.assert_called_once()

    def test_purged_session_residue_cannot_create_a_replacement(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        work_area, target_parent, _target = adapter._private_target_paths(
            self.workspace, self.home, record["id"]
        )
        os.makedirs(target_parent)
        self.addCleanup(lambda: shutil.rmtree(work_area, ignore_errors=True))

        with mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
            side_effect=AssertionError("a purged session must not be replaced"),
        ):
            self.assertIsNone(
                adapter.start_task(
                    state, record["id"], self.config, self.home
                )
            )

        result = tasks.task_record(state, record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertIn("deleted", result["reason"])
        self.assertTrue(result["token_usage_partial"])
        self.assertTrue(result["cost_partial"])

    def test_stop_in_progress_refuses_restart_and_keeps_task_open(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        stopped = self.projection(
            record["id"], status="running", duration=4, token_amount=4
        )
        stopped["state"]["result"] = None
        stopped["process"] = "stopped"
        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=stopped
        ), mock.patch.object(
            adapter.lifecycle,
            "start_session",
            side_effect=lifecycle.PublicLifecycleError(
                409, lifecycle.STOP_INCOMPLETE
            ),
        ):
            with self.assertRaises(lifecycle.PublicLifecycleError) as raised:
                adapter.start_task(
                    state,
                    record["id"],
                    self.config,
                    self.home,
                    session_id="bs-stopping",
                )
        self.assertEqual(raised.exception.code, lifecycle.STOP_INCOMPLETE)
        self.assertIsNone(tasks.task_record(state, record["id"])["result"])

    def test_resume_start_refusal_terminalizes_with_known_accounting(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        stopped = self.projection(
            record["id"], status="running", duration=4, token_amount=4
        )
        stopped["state"]["result"] = None
        stopped["process"] = "stopped"
        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=stopped
        ), mock.patch.object(
            adapter.lifecycle,
            "start_session",
            side_effect=lifecycle.PublicLifecycleError(
                503, lifecycle.UNAVAILABLE
            ),
        ):
            resumed = adapter.start_task(
                state,
                record["id"],
                self.config,
                self.home,
                session_id="bs-stopped",
            )
        self.assertIsNone(resumed)
        result = tasks.task_record(state, record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertIn(lifecycle.UNAVAILABLE, result["reason"])
        self.assertEqual(result["duration_s"], 4.0)
        self.assertEqual(result["token_usage"], usage(4))

    def test_recovery_lock_failure_keeps_task_open_for_owned_session(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        projection = self.projection(record["id"], status="running")
        projection["id"] = "bs-owned"
        projection["process"] = "running"
        projection["state"]["result"] = None
        refused_lock = mock.MagicMock()
        refused_lock.__enter__.side_effect = OSError("lock store unavailable")
        available_lock = mock.MagicMock()

        with mock.patch.object(
            adapter.brainstorming,
            "_exclusive_transcript",
            side_effect=[refused_lock, available_lock],
        ), mock.patch.object(
            adapter.lifecycle,
            "list_sessions",
            return_value=[{"id": "bs-implicitly-owned"}],
        ) as discover, mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ), mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
            side_effect=AssertionError("owned session must not be replaced"),
        ):
            with self.assertRaises(lifecycle.PublicLifecycleError) as raised:
                adapter.start_task(
                    state, record["id"], self.config, self.home
                )
            self.assertEqual(raised.exception.code, lifecycle.UNAVAILABLE)
            self.assertIsNone(tasks.task_record(state, record["id"])["result"])
            discover.assert_not_called()
            resumed = adapter.start_task(
                state, record["id"], self.config, self.home
            )

        self.assertIs(resumed, projection)
        self.assertIsNone(tasks.task_record(state, record["id"])["result"])
        discover.assert_called_once()

    def test_forgotten_session_fails_task_with_retained_accounting(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        session_id = "bs-forgotten-task-session"
        self.retain_task_session(record, session_id)

        with mock.patch.object(
            adapter.lifecycle,
            "create_resolved_session",
            side_effect=AssertionError("deleted session must not be replaced"),
        ):
            self.assertIsNone(
                adapter.start_task(
                    state, record["id"], self.config, self.home
                )
            )
        result = tasks.task_record(state, record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertIn("deleted", result["reason"])
        self.assertEqual(result["duration_s"], 4.0)
        self.assertEqual(result["token_usage"], usage(4))
        self.assertEqual(result["cost"], {"api_usd": 0.4, "real_usd": 0.0})

    def _retained_target_projection(self, relative):
        record = adapter.admit_task(
            {}, self.order(), self.config, self.workspace,
        )
        target = os.path.join(self.workspace, "out", "retained.md")
        recorded_target = "out/retained.md" if relative else target
        session_id = "bs-forgotten-workspace-target"
        store, _work_area = self.retain_task_session(
            record, session_id, target_path=recorded_target,
        )
        before = store.read(session_id)
        self.assertEqual(before.state["request"]["target_path"], recorded_target)
        # Recovery resolves stored request identity only; an unmounted work
        # area must not prevent importing the retained session's accounting.
        os.rename(self.workspace, self.workspace + "-unmounted")
        projection = adapter._retained_projection(
            self.home, session_id, "task:" + record["id"], target,
        )
        self.assertEqual(projection["process"], "stopped")
        self.assertEqual(projection["work_duration_s"], 4.0)
        self.assertEqual(projection["work_token_usage"], usage(4))
        self.assertFalse(projection["work_token_usage_partial"])
        self.assertEqual(projection["work_cost"], {"api_usd": 0.4, "real_usd": 0.0})
        self.assertFalse(projection["work_cost_partial"])
        with self.assertRaisesRegex(adapter.AdapterError, "mismatch"):
            adapter._retained_projection(
                self.home, session_id, "task:" + record["id"],
                os.path.join(self.workspace, "out", "wrong-target.md"),
            )
        self.assertEqual(store.read(session_id), before)

    def test_retained_relative_target_resolves_from_workspace_and_preserves_accounting(self):
        self._retained_target_projection(relative=True)

    def test_retained_absolute_target_keeps_identity_and_rejects_wrong_target(self):
        self._retained_target_projection(relative=False)

    def test_forgotten_inflight_effect_marks_retained_accounting_partial(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        session_id = "bs-forgotten-inflight-effect"
        store, _work_area = self.retain_task_session(record, session_id)
        store.begin_task_effect_attempt(session_id, {
            "task_id": record["id"],
            "token": "lost-effect-attempt",
            "started_at": 2.0,
        })

        self.assertIsNone(
            adapter.start_task(
                state, record["id"], self.config, self.home
            )
        )

        result = tasks.task_record(state, record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["token_usage"], usage(4))
        self.assertEqual(result["cost"], {"api_usd": 0.4, "real_usd": 0.0})
        self.assertTrue(result["token_usage_partial"])
        self.assertTrue(result["cost_partial"])

    def test_unknown_explicit_session_terminalizes_with_partial_accounting(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        with mock.patch.object(
            adapter.lifecycle,
            "inspect_session",
            side_effect=lifecycle.PublicLifecycleError(
                404, lifecycle.UNKNOWN_SESSION
            ),
        ):
            self.assertIsNone(adapter.start_task(
                state,
                record["id"],
                self.config,
                self.home,
                session_id="bs-deleted",
            ))
        result = tasks.task_record(state, record["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertTrue(result["token_usage_partial"])
        self.assertTrue(result["cost_partial"])

    def test_effect_activity_survives_crash_before_task_result(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        projection = self.projection(
            record["id"], duration=7.0, token_amount=7
        )
        applied = mock.Mock(return_value=effect(amount=3))
        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ), mock.patch.object(
            adapter,
            "_retained_agreement",
            return_value={"exists": True, "encoding": "utf-8", "content": "plan"},
        ), mock.patch.object(
            adapter.tasks,
            "record_task_result",
            side_effect=RuntimeError("crash after durable effect activity"),
        ), self.assertRaises(RuntimeError):
            adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-crash",
                applied,
                effect_store=self.effect_store,
            )
        self.assertIsNone(tasks.task_record(state, record["id"])["result"])
        self.assertEqual(len(self.effect_store.activity["events"]), 1)

        recovered_projection = copy.deepcopy(projection)
        recovered_projection["activity"] = copy.deepcopy(
            self.effect_store.activity["events"]
        )
        recovered_projection["work_duration_s"] = 10.0
        recovered_projection["work_token_usage"] = usage(10)
        recovered_projection["work_cost"] = {
            "api_usd": 1.0,
            "real_usd": 0.0,
        }
        with mock.patch.object(
            adapter.lifecycle,
            "inspect_session",
            return_value=recovered_projection,
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-crash",
                mock.Mock(side_effect=AssertionError("effect repeated")),
                effect_store=self.effect_store,
            )
        self.assertEqual(applied.call_count, 1)
        self.assertEqual(terminal["result"]["duration_s"], 10.0)
        self.assertEqual(terminal["result"]["token_usage"], usage(10))
        self.assertFalse(terminal["result"]["token_usage_partial"])

    def test_effect_failure_reason_cannot_impersonate_recovery(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        projection = self.projection(record["id"])
        attempt = {
            "task_id": record["id"],
            "token": "reported-failure",
            "started_at": 1.0,
        }
        reported = effect(
            completed=False,
            reason=adapter._RECOVERED_EFFECT_ERROR,
        )
        projection["activity"] = [
            adapter._effect_activity_event(
                reported, attempt, projection, "execution"
            )
        ]
        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-reported-failure",
                mock.Mock(side_effect=AssertionError("effect repeated")),
                effect_store=self.effect_store,
            )
        self.assertEqual(terminal["result"]["status"], "failure")
        self.assertEqual(
            terminal["result"]["reason"], adapter._RECOVERED_EFFECT_ERROR
        )

    def test_concurrent_finisher_does_not_replace_a_live_effect_attempt(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        concurrent_state = copy.deepcopy(state)
        projection = self.projection(record["id"])
        first_started = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()
        replacement_started = threading.Event()
        results = {}
        errors = []

        def first_effect(_request):
            first_started.set()
            if not release_first.wait(2.0):
                raise AssertionError("first effect was not released")
            return effect(amount=3)

        def replacement_effect(_request):
            replacement_started.set()
            return effect(amount=5)

        def live_projection(*_args, **_kwargs):
            current = copy.deepcopy(projection)
            current["activity"] = copy.deepcopy(
                self.effect_store.activity["events"]
            )
            if current["activity"]:
                current["work_duration_s"] = 5.0
                current["work_token_usage"] = usage(5)
                current["work_cost"] = {
                    "api_usd": 0.5,
                    "real_usd": 0.0,
                }
            return current

        def finish(label, task_state, effect_callback, entered=None):
            if entered is not None:
                entered.set()
            try:
                results[label] = adapter.finish_task(
                    task_state,
                    record["id"],
                    self.home,
                    "bs-concurrent-effect",
                    effect_callback,
                    effect_store=self.effect_store,
                )
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with mock.patch.object(
            adapter.lifecycle, "inspect_session", side_effect=live_projection
        ), mock.patch.object(
            adapter,
            "_retained_agreement",
            return_value={
                "exists": True,
                "encoding": "utf-8",
                "content": "plan",
            },
        ):
            first = threading.Thread(
                target=finish,
                args=("first", state, first_effect),
            )
            second = threading.Thread(
                target=finish,
                args=(
                    "second",
                    concurrent_state,
                    replacement_effect,
                    second_entered,
                ),
            )
            first.start()
            self.assertTrue(first_started.wait(1.0))
            second.start()
            self.assertTrue(second_entered.wait(1.0))
            self.assertFalse(replacement_started.wait(0.1))
            release_first.set()
            first.join(2.0)
            second.join(2.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results["first"], results["second"])
        self.assertEqual(len(self.effect_store.activity["events"]), 1)
        self.assertIsNone(self.effect_store.attempt)

    def test_effect_marker_and_activity_use_durable_session_storage(self):
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        session_id = "bs-effect-durability"
        store._store.cas(
            bs._activity_key(session_id),
            None,
            {"schema_version": 1, "events": []},
        )
        attempt = {
            "task_id": "task-effect-durability",
            "token": "effect-token",
            "started_at": 1.0,
        }
        store.begin_task_effect_attempt(session_id, attempt)
        reopened = bs.SessionStore(lifecycle.state_directory(self.home))
        self.assertEqual(
            reopened.read_task_effect_attempt(session_id), attempt
        )
        event = adapter._effect_activity_event(
            effect(amount=2),
            attempt,
            {"state": {"result": {"rounds_used": 1}}},
            "execution",
        )
        reopened.append_activity(session_id, event)
        reopened.finish_task_effect_attempt(session_id, attempt["token"])
        final = bs.SessionStore(lifecycle.state_directory(self.home))
        self.assertIsNone(final.read_task_effect_attempt(session_id))
        self.assertEqual(final.read_activity(session_id)["events"], [event])

    def test_recovered_effect_attempt_can_start_a_replacement(self):
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        session_id = "bs-effect-replacement"
        store._store.cas(
            bs._activity_key(session_id),
            None,
            {"schema_version": 1, "events": []},
        )
        first = {
            "task_id": "task-effect-replacement",
            "token": "interrupted-effect",
            "started_at": 1.0,
        }
        store.begin_task_effect_attempt(session_id, first)

        recovered = adapter._recover_effect_attempt(
            store,
            session_id,
            first["task_id"],
            {"state": {"result": {"rounds_used": 1}}},
        )
        replacement = adapter._begin_effect_attempt(
            store, session_id, first["task_id"]
        )

        self.assertFalse(recovered["completed"])
        self.assertTrue(recovered["token_usage_partial"])
        self.assertEqual(
            store.read_activity(session_id)["events"][0]["participant_id"],
            adapter._RECOVERED_EFFECT_PARTICIPANT,
        )
        self.assertNotEqual(replacement["token"], first["token"])
        self.assertEqual(
            store.read_task_effect_attempt(session_id), replacement
        )

    def test_malformed_effect_keeps_independently_valid_accounting(self):
        state = {}
        record = adapter.admit_task(
            state, self.order(), self.config, self.workspace
        )
        malformed = effect(amount=5)
        malformed["unexpected"] = "invalid completion member"
        projection = self.projection(record["id"])
        with mock.patch.object(
            adapter.lifecycle, "inspect_session", return_value=projection
        ), mock.patch.object(
            adapter,
            "_retained_agreement",
            return_value={"exists": True, "encoding": "utf-8", "content": "plan"},
        ):
            terminal = adapter.finish_task(
                state,
                record["id"],
                self.home,
                "bs-malformed-effect",
                lambda _request: malformed,
                effect_store=self.effect_store,
            )
        result = terminal["result"]
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["duration_s"], 7.0)
        self.assertEqual(result["token_usage"], usage(7))
        self.assertEqual(result["cost"], {"api_usd": 0.7, "real_usd": 0.0})
        self.assertFalse(result["token_usage_partial"])
        self.assertFalse(result["cost_partial"])


if __name__ == "__main__":
    unittest.main()
