"""Focused executable evidence for the Slice 08 milestone adapter."""

import builtins
import copy
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming as bs
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_lifecycle as lifecycle
from orchestrator import brainstorming_milestone as adapter
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st
from orchestrator import verifiers
from orchestrator.tests.test_driver_fixes import make_config


def closing_summary():
    return {
        "reason": "The bounded milestone result is agreed.",
        "unresolved_objections": [],
        "affected_parties": "The milestone workers using the result.",
        "damage_altitude": "A bounded and reversible consequence.",
        "proportionality": "The discussion matched the decision.",
        "escalation_evidence": None,
        "open_questions": [],
    }


def report_finding(fid="F1"):
    return {
        "id": fid,
        "severity": "P1",
        "summary": "One design choice is unresolved.",
        "validity": {
            "permitted_baseline": "the design makes the choice explicit",
            "actual_outcome": "the choice is not settled",
            "incremental_harm": "the current judgment cannot finish",
            "exceeds_baseline": True,
        },
        "plain": "The reviewer cannot judge the work until one choice is made.",
        "example": "A reviewer checks one behavior but two outcomes are allowed.",
        "contests": None,
    }


def fixer_validity(exceeds=True):
    return {
        "affected_party": "the user relying on the declared behavior",
        "observable_damage": (
            "the declared behavior is unavailable"
            if exceeds else "no damage beyond the permitted behavior"
        ),
        "violated_guarantee": (
            "the explicit behavior guarantee"
            if exceeds else "no guarantee is violated"
        ),
        "permitted_baseline": "the documented behavior",
        "incremental_harm": (
            "the outcome exceeds the baseline"
            if exceeds else "no harm beyond the baseline"
        ),
        "exceeds_baseline": exceeds,
    }


def failure_gap():
    return {
        "classification": "fits_remodel",
        "missing_or_conflict": "the design choice remains unresolved",
        "where": "implementation/milestones/example/skeleton.md:1",
        "forced_decision": "state which behavior the implementation must use",
        "proposal": None,
        "plain": "The implementation cannot finish without one design choice.",
        "example": "A builder must choose A or B but neither is selected.",
    }


def rethink(
    kind,
    finding=None,
    target="proposals/rethink.md",
    rounds=10,
    result_mode="proposal",
):
    value = {
        "status": "need_rethink",
        "kind": kind,
        "request": "Choose which compatible behavior should be used.",
        "finding": copy.deepcopy(finding or {"id": "BUILD", "summary": "choice"}),
        "target_path": target,
        "max_rounds": rounds,
        "result_mode": result_mode,
    }
    if kind in contracts.RETHINK_CONTINUATION_KINDS:
        value["failure_gap"] = failure_gap()
    return value


class _FakeProcess:
    def __init__(self, pid):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout=None):
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode


class _LaunchFactory:
    def __init__(self, before_return=None):
        self.before_return = before_return
        self.calls = []
        self._pid = 700000

    def __call__(self, home, session_id):
        self._pid += 1
        process = _FakeProcess(self._pid)
        self.calls.append((home, session_id, process))
        if self.before_return is not None:
            self.before_return()
        return lifecycle.GatedLaunch(
            process,
            lambda: None,
            process.terminate,
        )


class _MutatingExecution:
    def __init__(self, target):
        self.target = target
        self.calls = 0

    def exchange_quiescent(
        self,
        session_id,
        participant_id,
        prompt,
        execution_context,
        before_repair=None,
    ):
        self.calls += 1
        with open(self.target, "wb") as handle:
            handle.write(("invalid-%d" % self.calls).encode("ascii"))
        result = runners.RunnerResult("", 0, 0.01)
        result.worker_quiescent = True
        return {
            "kind": "discussion_turn",
            "markdown": "invalid mutation %d" % self.calls,
        }, result


class BrainstormingMilestoneAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="brainstorming-adapter-")
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.workspace = os.path.join(self.tmp.name, "workspace")
        os.makedirs(self.home)
        os.makedirs(os.path.join(self.workspace, "proposals"))
        os.makedirs(os.path.join(self.workspace, "docs"))
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
            "model_defaults": {},
            "worker_stall_window_s": 0,
            "worker_stall_min_cpu_s": 0,
        }
        self.context = {
            "workspace_path": self.workspace,
            "project": None,
            "work_area": None,
            "primary": {
                "path": self.workspace,
                "ref": "primary",
                "writable": True,
            },
            "additional": [],
        }
        self.addCleanup(self._clear_fake_children)

    def _clear_fake_children(self):
        with lifecycle._CHILDREN_LOCK:
            for pid, (home, _session_id, _process) in list(
                lifecycle._CHILDREN.items()
            ):
                if home == os.path.abspath(self.home):
                    lifecycle._CHILDREN.pop(pid, None)

    @staticmethod
    def _roster(interlocutor_first=False):
        lead = {"id": "lead", "role": "initial_position", "delivery": "llm"}
        critic = {
            "id": "critic",
            "role": "contrary_position",
            "delivery": "llm",
        }
        return [critic, lead] if interlocutor_first else [lead, critic]

    def _body(self, target, rounds=17, interlocutor_first=False):
        return {
            "request": {
                "workspace_path": self.workspace,
                "target_path": target,
                "request": "Choose which compatible behavior should be used.",
                "context": {
                    "brief": "Resolve one focused milestone design request.",
                    "references": ["docs/context.md"],
                    "source_payload": {"id": "F1", "summary": "choice"},
                },
                "max_rounds": rounds,
            },
            "participants": self._roster(interlocutor_first),
            "closure_policy": "unanimity",
        }

    def _create(self, target, *, rounds=17, launcher=None):
        return lifecycle.create_resolved_session(
            self.home,
            self._body(target, rounds),
            "milestone:test:impl:8",
            self.context,
            self.config,
            launcher=launcher or _LaunchFactory(),
        )

    def test_need_rethink_signal_is_closed_eligible_and_non_completing(self):
        for kind in contracts.RETHINK_KINDS:
            finding = (
                report_finding()
                if kind in contracts.REPORT_KINDS
                else {"id": "BUILD", "summary": "choice"}
            )
            value = rethink(kind, finding=finding)
            self.assertIs(
                contracts.validate_worker_output(
                    value,
                    kind,
                    require_plain=kind in contracts.REPORT_KINDS,
                ),
                value,
            )
            self.assertEqual(value["max_rounds"], 10)

        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                rethink(contracts.KIND_IMPLEMENT)
                | {"files_changed": ["already-finished.py"]},
                contracts.KIND_IMPLEMENT,
            )
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                rethink(contracts.KIND_DRAFT_SKELETON),
                contracts.KIND_DRAFT_SKELETON,
            )
        for bad_target in (
            "/absolute.md",
            "../outside.md",
            "proposals/../answer.md",
            ".",
        ):
            with self.assertRaises(contracts.ContractError):
                contracts.validate_worker_output(
                    rethink(contracts.KIND_IMPLEMENT, target=bad_target),
                    contracts.KIND_IMPLEMENT,
                )
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                rethink(contracts.KIND_IMPLEMENT, rounds=0),
                contracts.KIND_IMPLEMENT,
            )
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                rethink(contracts.KIND_IMPLEMENT, rounds=3),
                contracts.KIND_IMPLEMENT,
            )
        amendment = rethink(
            contracts.KIND_FIX_FINDINGS,
            finding=report_finding(),
            rounds=10,
            result_mode="design_amendment",
        )
        self.assertIs(
            contracts.validate_worker_output(
                amendment, contracts.KIND_FIX_FINDINGS
            ),
            amendment,
        )
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                rethink(
                    contracts.KIND_REVIEW_ROUND,
                    finding=report_finding(),
                    result_mode="design_amendment",
                ),
                contracts.KIND_REVIEW_ROUND,
                require_plain=True,
            )
        outside_goal = copy.deepcopy(amendment)
        outside_goal["failure_gap"]["classification"] = "needs_operator"
        self.assertIs(
            contracts.validate_worker_output(
                outside_goal, contracts.KIND_FIX_FINDINGS
            ),
            outside_goal,
        )
        modern = copy.deepcopy(amendment)
        modern.pop("failure_gap")
        self.assertIs(
            contracts.validate_worker_output(
                modern, contracts.KIND_FIX_FINDINGS
            ),
            modern,
        )
        with self.assertRaisesRegex(
            contracts.ContractError, "requires failure_gap"
        ):
            contracts.validate_worker_output(
                modern,
                contracts.KIND_FIX_FINDINGS,
                require_failure_gap=True,
            )
        self.assertIs(
            contracts.validate_worker_output(
                amendment,
                contracts.KIND_FIX_FINDINGS,
                require_failure_gap=True,
            ),
            amendment,
        )
        too_long = copy.deepcopy(amendment)
        too_long["max_rounds"] = 11
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                too_long, contracts.KIND_FIX_FINDINGS
            )
        self.assertIn(
            "Any materializable workspace artifact may be selected as the source",
            contracts.CONTRACT_TEXT,
        )
        self.assertIn(
            "including one also named in context, a generated milestone "
            "record, or",
            contracts.CONTRACT_TEXT,
        )

    def test_rethink_session_creation_captures_unaccepted_target_baseline(self):
        target = os.path.join(self.workspace, "proposals", "existing.md")
        with open(target, "wb") as handle:
            handle.write(b"before launch")

        def change_before_capture():
            with open(target, "wb") as handle:
                handle.write(b"state at creation")

        created = self._create(
            "proposals/existing.md",
            launcher=_LaunchFactory(change_before_capture),
        )
        progress = bs.coordination_projection(created["state"])
        self.assertIsNone(progress["accepted_target_revision"])
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        baseline = store.read_target_revision(
            created["id"], progress["recovery_baseline_revision"]
        )
        self.assertEqual(
            bs.target_revision_content(baseline),
            (True, b"state at creation"),
        )

        absent = self._create(
            "proposals/absent.md", launcher=_LaunchFactory()
        )
        absent_progress = bs.coordination_projection(absent["state"])
        absent_record = store.read_target_revision(
            absent["id"], absent_progress["recovery_baseline_revision"]
        )
        self.assertEqual(bs.target_revision_content(absent_record), (False, b""))
        self.assertIsNone(absent_progress["accepted_target_revision"])

    def test_target_admission_requires_existing_parent_without_creating_it(self):
        missing_parent = os.path.join(
            self.workspace, "missing", "parent"
        )
        launcher = _LaunchFactory()
        with self.assertRaises(lifecycle.PublicLifecycleError) as refused:
            self._create(
                "missing/parent/proposal.md",
                launcher=launcher,
            )
        self.assertEqual(refused.exception.status, 400)
        self.assertEqual(refused.exception.code, lifecycle.INVALID_REQUEST)
        self.assertEqual(launcher.calls, [])
        self.assertFalse(os.path.exists(missing_parent))
        self.assertFalse(os.path.exists(lifecycle.registry_path(self.home)))

    def test_request_and_target_admission_has_no_fixed_global_quota(self):
        created = []
        for index in range(9):
            created.append(
                self._create(
                    "proposals/session-%d.md" % index,
                    rounds=17 + index,
                    launcher=_LaunchFactory(),
                )
            )
        self.assertEqual(len(created), 9)
        self.assertTrue(
            all(item["state"]["status"] == "running" for item in created)
        )

        store = bs.SessionStore(lifecycle.state_directory(self.home))
        for index in range(18):
            store._write_target_revision(
                created[0]["id"],
                bs.make_target_revision(
                    True, ("revision-%d" % index).encode("ascii"), 0o644
                ),
            )

        large = b"x" * (8 * 1024 * 1024 + 1)
        large_target = os.path.join(
            self.workspace, "proposals", "large.md"
        )
        with open(large_target, "wb") as handle:
            handle.write(large)
        large_session = self._create(
            "proposals/large.md",
            rounds=33,
            launcher=_LaunchFactory(),
        )
        large_records = [
            store.read_target_revision(
                large_session["id"],
                large_session["state"]["recovery_baseline_revision"],
            )
        ]
        for suffix in (b"a", b"b", b"c"):
            record = bs.make_target_revision(True, large + suffix, 0o644)
            large_records.append(
                store._write_target_revision(large_session["id"], record)
            )
        retained_bytes = sum(
            len(bs.target_revision_content(record)[1])
            for record in large_records
        )
        self.assertGreater(retained_bytes, 32 * 1024 * 1024)

    def test_actual_creation_unavailability_removes_partial_session_state(self):
        target = os.path.join(self.workspace, "proposals", "unavailable.md")
        with open(target, "wb") as handle:
            handle.write(b"baseline")
        launcher = _LaunchFactory()
        baseline = coordination.capture_target(target)

        def fail_after_revision(store, session_id, expected, target_revision):
            store._write_target_revision(session_id, target_revision)
            raise OSError("injected durable initialization failure")

        with (
            mock.patch.object(
                bs.SessionStore,
                "initialize_coordination",
                autospec=True,
                side_effect=fail_after_revision,
            ),
            self.assertRaises(lifecycle.PublicLifecycleError) as refused,
        ):
            self._create(
                "proposals/unavailable.md",
                launcher=launcher,
            )
        self.assertEqual(refused.exception.status, 503)
        session_id = launcher.calls[0][1]
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        self.assertIsNone(store.read(session_id))
        with self.assertRaises(bs.HistoryRewriteError):
            store.read_target_revision(session_id, baseline["revision"])
        registry = lifecycle._load_registry(self.home)
        self.assertEqual(registry["sessions"], [])

    def test_invalid_target_mutation_allows_one_correction_then_fails_coherently(
        self,
    ):
        target = os.path.join(self.workspace, "proposals", "mutation.md")
        with open(target, "wb") as handle:
            handle.write(b"accepted baseline")
        roster = [
            {
                "id": "critic",
                "role": "contrary_position",
                "delivery": "llm",
                "executor_ref": "critic-executor",
                "model_family": "claude",
            },
            {
                "id": "lead",
                "role": "initial_position",
                "delivery": "llm",
                "executor_ref": "lead-executor",
                "model_family": "codex",
            },
        ]
        request = self._body(
            "proposals/mutation.md", interlocutor_first=True
        )["request"]
        store = bs.SessionStore(os.path.join(self.tmp.name, "mutation-state"))
        created = store.create(
            "mutation-session",
            request,
            bs.resolve_run_config(roster, "unanimity", roster),
            roster,
        )
        running = store.transition(
            "mutation-session", created.revision, "running"
        )
        store.initialize_coordination(
            "mutation-session",
            running.revision,
            coordination.capture_target(target),
        )
        execution = _MutatingExecution(target)
        subject = coordination.BrainstormingCoordinator(store, execution)
        terminal = subject.run_next_turn(
            "mutation-session", self.context
        )
        self.assertEqual(execution.calls, 2)
        self.assertEqual(terminal.state["status"], "failure")
        self.assertEqual(terminal.state["result"]["outcome"], "failure")
        self.assertEqual(terminal.state["completed_turns"], [])
        self.assertEqual(terminal.state["rounds_used"], 0)
        self.assertIsNone(terminal.state["accepted_target_revision"])
        self.assertIsNone(store.read_turn_attempt("mutation-session"))
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"accepted baseline")

        restarted = store.create(
            "mutation-restart",
            request,
            bs.resolve_run_config(roster, "unanimity", roster),
            roster,
        )
        restarted = store.transition(
            "mutation-restart", restarted.revision, "running"
        )
        baseline = coordination.capture_target(target)
        restarted = store.initialize_coordination(
            "mutation-restart", restarted.revision, baseline
        )
        with coordination._open_target_parent(target) as (
            _descriptor,
            _name,
            parent_identity,
        ):
            first_attempt = {
                "token": "first-attempt",
                "participant_id": "critic",
                "completed_turn_count": 0,
                "target_revision": None,
                "quiescent": False,
                "target_parent": parent_identity,
            }
        store.begin_turn_attempt("mutation-restart", first_attempt)
        self.assertTrue(
            store.mark_turn_attempt_envelope_repair(
                "mutation-restart", first_attempt["token"]
            )
        )
        store.mark_turn_attempt_quiescent(
            "mutation-restart", first_attempt["token"]
        )
        self.assertFalse(
            store.mark_turn_attempt_target_mutation(
                "mutation-restart", first_attempt["token"]
            )
        )
        second_attempt = {
            **first_attempt,
            "token": "second-attempt",
        }
        store.restart_turn_attempt("mutation-restart", second_attempt)
        self.assertTrue(
            store.read_turn_attempt("mutation-restart")[
                "envelope_repair_used"
            ]
        )
        self.assertFalse(
            store.mark_turn_attempt_envelope_repair(
                "mutation-restart", second_attempt["token"]
            )
        )
        store.mark_turn_attempt_quiescent(
            "mutation-restart", second_attempt["token"]
        )
        self.assertTrue(
            store.mark_turn_attempt_target_mutation(
                "mutation-restart", second_attempt["token"]
            )
        )
        with open(target, "wb") as handle:
            handle.write(b"second invalid mutation")
        coordination.restore_target(target, baseline)
        after_crash = coordination.BrainstormingCoordinator(
            bs.SessionStore(os.path.join(self.tmp.name, "mutation-state")),
            _MutatingExecution(target),
        ).prepare("mutation-restart")
        self.assertEqual(after_crash.state["status"], "failure")
        self.assertEqual(after_crash.state["completed_turns"], [])
        self.assertIsNone(store.read_turn_attempt("mutation-restart"))

    def test_target_revision_and_recovery_never_probe_vcs_or_repository_metadata(
        self,
    ):
        target = os.path.join(self.workspace, "proposals", "no-vcs.md")
        with open(target, "wb") as handle:
            handle.write(b"baseline")
        git_dir = os.path.join(self.workspace, ".git")
        os.makedirs(git_dir)
        with open(os.path.join(git_dir, "HEAD"), "w", encoding="utf-8") as handle:
            handle.write("ref: refs/heads/main\n")

        real_open = builtins.open
        real_os_open = os.open
        real_stat = os.stat
        real_lstat = os.lstat

        def reject_metadata(path, *args, **kwargs):
            if "/.git/" in os.path.abspath(os.fspath(path)) + "/":
                raise AssertionError("repository metadata was inspected")
            return real_open(path, *args, **kwargs)

        def reject_os_open(path, *args, **kwargs):
            if "/.git/" in os.path.abspath(os.fspath(path)) + "/":
                raise AssertionError("repository metadata was inspected")
            return real_os_open(path, *args, **kwargs)

        def reject_stat(path, *args, **kwargs):
            if "/.git/" in os.path.abspath(os.fspath(path)) + "/":
                raise AssertionError("repository metadata was inspected")
            return real_stat(path, *args, **kwargs)

        def reject_lstat(path, *args, **kwargs):
            if "/.git/" in os.path.abspath(os.fspath(path)) + "/":
                raise AssertionError("repository metadata was inspected")
            return real_lstat(path, *args, **kwargs)

        store = bs.SessionStore(os.path.join(self.tmp.name, "no-vcs-state"))
        roster = [
            {
                "id": "lead",
                "role": "initial_position",
                "delivery": "llm",
                "executor_ref": "lead-executor",
                "model_family": "codex",
            },
            {
                "id": "critic",
                "role": "contrary_position",
                "delivery": "llm",
                "executor_ref": "critic-executor",
                "model_family": "claude",
            },
        ]
        created = store.create(
            "no-vcs-session",
            self._body("proposals/no-vcs.md")["request"],
            bs.resolve_run_config(roster, "unanimity", roster),
            roster,
        )
        running = store.transition(
            "no-vcs-session", created.revision, "running"
        )
        with (
            mock.patch.object(builtins, "open", side_effect=reject_metadata),
            mock.patch.object(os, "open", side_effect=reject_os_open),
            mock.patch.object(os, "stat", side_effect=reject_stat),
            mock.patch.object(os, "lstat", side_effect=reject_lstat),
            mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError("VCS process")
            ),
            mock.patch.object(
                subprocess, "run", side_effect=AssertionError("VCS process")
            ),
        ):
            baseline = coordination.capture_target(target)
            initialized = store.initialize_coordination(
                "no-vcs-session", running.revision, baseline
            )
            accepted = store.record_completed_turn(
                "no-vcs-session",
                initialized.revision,
                "lead",
                "Accept the current bytes.",
                baseline,
            )
            with real_open(
                os.path.join(git_dir, "HEAD"), "w", encoding="utf-8"
            ) as handle:
                handle.write("unrelated repository change\n")
            with real_open(target, "wb") as handle:
                handle.write(b"drift")
            reconciled = coordination.BrainstormingCoordinator(
                store, None
            ).prepare("no-vcs-session")
        self.assertEqual(
            reconciled.state["accepted_target_revision"],
            accepted.state["accepted_target_revision"],
        )
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"baseline")

    def test_adapter_builds_exact_request_roster_and_execution_context(self):
        docs_dir = "implementation/milestones/example"
        os.makedirs(os.path.join(self.workspace, docs_dir))
        references = []
        for name in ("skeleton.md", "slice.md"):
            path = os.path.join(self.workspace, docs_dir, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(name)
            references.append(os.path.relpath(path, self.workspace))
        project_home = os.path.join(self.home, "projects")
        os.makedirs(project_home)
        project = {
            "directory": project_home,
            "project": "orchestrators",
            "work_area": "implementation",
            "primary": copy.deepcopy(self.context["primary"]),
            "additional": [
                {
                    "path": os.path.join(self.tmp.name, "evidence"),
                    "ref": "evidence",
                    "writable": False,
                }
            ],
        }
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": docs_dir,
            "project": project,
        }
        signal = rethink(
            contracts.KIND_REVIEW_ROUND,
            finding=report_finding(),
            target="proposals/translated.md",
            rounds=23,
        )
        captured = {}

        def capture(
            home,
            body,
            caller,
            context,
            config,
            owned_target_path=None,
        ):
            captured.update(
                {
                    "home": home,
                    "body": copy.deepcopy(body),
                    "caller": caller,
                    "context": copy.deepcopy(context),
                    "config": config,
                    "owned_target_path": owned_target_path,
                }
            )
            return {"id": "session", "state": {"status": "created"}}

        with mock.patch.object(
            lifecycle, "create_resolved_session", side_effect=capture
        ):
            adapter.create_session(
                state,
                self.config,
                "impl:8",
                signal,
                references,
            )
        request = captured["body"]["request"]
        self.assertEqual(request["request"], signal["request"])
        self.assertEqual(
            request["target_path"], captured["owned_target_path"]
        )
        self.assertTrue(os.path.isabs(request["target_path"]))
        self.assertFalse(
            adapter._path_overlap(request["target_path"], self.workspace)
        )
        self.assertFalse(os.path.exists(request["target_path"]))
        self.assertEqual(
            request["max_rounds"], contracts.MILESTONE_BRAINSTORMING_ROUNDS
        )
        self.assertEqual(
            request["context"]["source_payload"], signal["finding"]
        )
        self.assertEqual(request["context"]["references"], references)
        self.assertEqual(
            captured["body"]["participants"],
            [
                {"id": "initial-position", "role": "initial_position", "delivery": "llm"},
                {
                    "id": "contrary-position",
                    "role": "contrary_position",
                    "delivery": "llm",
                },
                {
                    "id": "dante",
                    "role": "common_sense",
                    "delivery": "external",
                    "external_provider": "narrator",
                },
            ],
        )
        self.assertEqual(captured["body"]["closure_policy"], "unanimity")
        self.assertEqual(captured["context"], adapter.execution_context(state))
        self.assertIs(captured["config"], self.config)
        self.assertEqual(captured["home"], self.home)

    def test_adapter_pins_lead_and_counterpart_profiles(self):
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": "docs",
        }
        captured = {}

        def capture(
            home,
            body,
            caller,
            context,
            config,
            owned_target_path=None,
        ):
            captured["participants"] = copy.deepcopy(body["participants"])
            return {"id": "session", "state": {"status": "created"}}

        with (
            mock.patch.object(adapter, "service_home", return_value=self.home),
            mock.patch.object(
                lifecycle, "create_resolved_session", side_effect=capture
            ),
        ):
            adapter.create_session(
                state,
                self.config,
                "slice_impl-08",
                rethink(contracts.KIND_IMPLEMENT),
                [],
                lead_profile={
                    "agent": "codex",
                    "model": "gpt-5.6-sol",
                    "effort": "max",
                },
                counterpart_profile={
                    "agent": "claude",
                    "model": "claude-opus-5",
                    "effort": "max",
                },
            )

        self.assertEqual(
            captured["participants"],
            [
                {
                    "id": "initial-position",
                    "role": "initial_position",
                    "delivery": "llm",
                    "model_family": "codex",
                    "model": "gpt-5.6-sol",
                    "effort": "max",
                },
                {
                    "id": "contrary-position",
                    "role": "contrary_position",
                    "delivery": "llm",
                    "model_family": "claude",
                    "model": "claude-opus-5",
                    "effort": "max",
                },
                {
                    "id": "dante",
                    "role": "common_sense",
                    "delivery": "external",
                    "external_provider": "narrator",
                    "model_family": "codex",
                    "model": "gpt-5.6-sol",
                    "effort": "max",
                },
            ],
        )

    def test_adapter_rejects_incomplete_participant_profile_before_materializing(self):
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": "docs",
        }
        before = set(os.listdir(self.home))
        with (
            mock.patch.object(adapter, "service_home", return_value=self.home),
            self.assertRaises(adapter.AdapterError),
        ):
            adapter.create_session(
                state,
                self.config,
                "slice_impl-08",
                rethink(contracts.KIND_IMPLEMENT),
                [],
                lead_profile={"agent": "codex", "model": "gpt-5.6-sol"},
            )
        self.assertEqual(set(os.listdir(self.home)), before)

    def test_guarantee_calibration_uses_an_isolated_complete_skeleton(self):
        skeleton_rel = "docs/skeleton.md"
        skeleton = os.path.join(self.workspace, skeleton_rel)
        original = (
            "# Skeleton\n\n"
            "## Guarantees\n\n"
            "- Workspace authority is strict.\n"
        )
        with open(skeleton, "w", encoding="utf-8") as handle:
            handle.write(original)
        state = {
            "name": "run",
            "goal": "Deliver the bounded workspace capability.",
            "workspace": self.workspace,
            "docs_dir": "docs",
        }
        captured = {}

        def capture(
            home,
            body,
            caller,
            context,
            config,
            owned_target_path=None,
        ):
            captured.update(
                {
                    "body": copy.deepcopy(body),
                    "caller": caller,
                    "context": copy.deepcopy(context),
                    "target": owned_target_path,
                }
            )
            return {"id": "calibration", "state": {"status": "created"}}

        lead = {
            "agent": "codex",
            "model": "gpt-5.6-sol",
            "effort": "max",
        }
        counterpart = {
            "agent": "claude",
            "model": "claude-opus-5",
            "effort": "max",
        }
        with (
            mock.patch.object(adapter, "service_home", return_value=self.home),
            mock.patch.object(
                lifecycle, "create_resolved_session", side_effect=capture
            ),
        ):
            adapter.create_guarantee_calibration_session(
                state,
                self.config,
                "skeleton",
                skeleton_rel,
                lead,
                counterpart,
                references=["docs/context.md"],
                authority_context={"amendments": []},
            )

        request = captured["body"]["request"]
        self.assertEqual(
            request["max_rounds"], adapter.GUARANTEE_CALIBRATION_MAX_ROUNDS
        )
        self.assertEqual(
            request["request"], adapter.GUARANTEE_CALIBRATION_REQUEST
        )
        self.assertIn("affected party", request["context"]["brief"])
        self.assertIn("complete agreed skeleton", request["context"]["brief"])
        self.assertIn("slice table", request["context"]["brief"])
        self.assertEqual(
            request["context"]["source_payload"],
            {
                "goal": state["goal"],
                "authority_context": {"amendments": []},
            },
        )
        self.assertEqual(
            request["context"]["references"],
            ["docs/context.md", skeleton_rel],
        )
        self.assertEqual(request["context"]["amendments"], [])
        self.assertEqual(captured["caller"],
                         "milestone:run:skeleton:guarantee-calibration")
        self.assertEqual(request["target_path"], captured["target"])
        self.assertFalse(adapter._path_overlap(captured["target"], self.workspace))
        with open(captured["target"], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), original)
        with open(captured["target"], "w", encoding="utf-8") as handle:
            handle.write("# Complete agreed skeleton\n")
        with open(skeleton, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), original)
        self.assertEqual(
            captured["body"]["participants"],
            [
                {
                    "id": "initial-position",
                    "role": "initial_position",
                    "delivery": "llm",
                    "model_family": "codex",
                    "model": "gpt-5.6-sol",
                    "effort": "max",
                },
                {
                    "id": "contrary-position",
                    "role": "contrary_position",
                    "delivery": "llm",
                    "model_family": "claude",
                    "model": "claude-opus-5",
                    "effort": "max",
                },
                {
                    "id": "dante",
                    "role": "common_sense",
                    "delivery": "external",
                    "external_provider": "narrator",
                    "model_family": "codex",
                    "model": "gpt-5.6-sol",
                    "effort": "max",
                },
            ],
        )

    def test_guarantee_calibration_requires_an_existing_regular_skeleton(self):
        state = {
            "name": "run",
            "goal": "goal",
            "workspace": self.workspace,
            "docs_dir": "docs",
        }
        profile = {
            "agent": "codex",
            "model": "gpt-5.6-sol",
            "effort": "max",
        }
        with mock.patch.object(
            adapter, "service_home", return_value=self.home
        ):
            with self.assertRaises(adapter.AdapterError):
                adapter.create_guarantee_calibration_session(
                    state,
                    self.config,
                    "skeleton",
                    "docs/missing.md",
                    profile,
                    profile,
                )

    def test_design_amendment_uses_a_fresh_target_and_source_as_context(self):
        source = os.path.join(self.workspace, "docs", "sealed.md")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("sealed source\n")
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": "docs",
        }
        signal = rethink(
            contracts.KIND_IMPLEMENT,
            target="docs/sealed.md",
            rounds=10,
            result_mode="design_amendment",
        )
        captured = {}

        def capture(
            home,
            body,
            caller,
            context,
            config,
            owned_target_path=None,
        ):
            captured["body"] = copy.deepcopy(body)
            captured["target"] = owned_target_path
            return {"id": "session", "state": {"status": "created"}}

        authority = {
            "goal": "Build the adapter.",
            "amendments": [{"id": "A1", "text": "Keep it bounded."}],
            "project_context": None,
        }
        with (
            mock.patch.object(adapter, "service_home", return_value=self.home),
            mock.patch.object(
                lifecycle, "create_resolved_session", side_effect=capture
            ),
        ):
            adapter.create_session(
                state,
                self.config,
                "slice_impl-08",
                signal,
                [],
                authority_context=authority,
            )
        self.assertEqual(os.path.basename(captured["target"]), "amendment.md")
        with open(captured["target"], encoding="utf-8") as handle:
            self.assertEqual(
                handle.read(), adapter.DESIGN_AMENDMENT_PLACEHOLDER
            )
        payload = captured["body"]["request"]["context"]
        self.assertIn("preferably under 3,000 characters", payload["brief"])
        self.assertIn("never omit necessary meaning", payload["brief"])
        self.assertIn("docs/sealed.md", payload["references"])
        self.assertEqual(payload["source_payload"]["finding"], signal["finding"])
        self.assertEqual(
            payload["source_payload"]["failure_gap"], signal["failure_gap"]
        )
        self.assertEqual(
            payload["source_payload"]["authority_context"], authority
        )
        self.assertEqual(payload["amendments"], authority["amendments"])

        modern_signal = copy.deepcopy(signal)
        modern_signal.pop("failure_gap")
        captured.clear()
        with (
            mock.patch.object(adapter, "service_home", return_value=self.home),
            mock.patch.object(
                lifecycle, "create_resolved_session", side_effect=capture
            ),
        ):
            adapter.create_session(
                state,
                self.config,
                "slice_impl-08",
                modern_signal,
                [],
                authority_context=authority,
            )
        modern_payload = captured["body"]["request"]["context"][
            "source_payload"
        ]
        self.assertEqual(modern_payload["finding"], signal["finding"])
        self.assertNotIn("failure_gap", modern_payload)

    def test_project_bound_prompts_keep_owned_target_outside_primary_root(self):
        source = os.path.join(self.workspace, "proposals", "prompted.md")
        with open(source, "wb") as handle:
            handle.write(b"materialized proposal")
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": "implementation/milestones/example",
            "project": {
                "directory": os.path.join(self.home, "projects"),
                "project": "orchestrators",
                "work_area": "implementation",
                "primary": copy.deepcopy(self.context["primary"]),
                "additional": [],
            },
        }
        with (
            mock.patch.object(adapter, "service_home", return_value=self.home),
            mock.patch.object(
                lifecycle,
                "_launch_lifecycle_process",
                side_effect=_LaunchFactory(),
            ),
        ):
            created = adapter.create_session(
                state,
                self.config,
                "impl:8",
                rethink(
                    contracts.KIND_REVIEW_ROUND,
                    finding=report_finding(),
                    target="proposals/prompted.md",
                ),
                [],
            )
        session_id = created["id"]
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        snapshot = store.read(session_id)
        baseline = store.read_target_revision(
            session_id, snapshot.state["recovery_baseline_revision"]
        )
        accepted = store.record_completed_turn(
            session_id,
            snapshot.revision,
            "initial-position",
            "Accept the materialized proposal.",
            baseline,
        )
        accepted_target = store.read_target_revision(
            session_id, accepted.state["accepted_target_revision"]
        )
        record = lifecycle._record_by_id(self.home, session_id)
        lead, interlocutor, _dante = accepted.state["run_config"][
            "participants"
        ]
        prompts = (
            coordination.build_turn_prompt(
                accepted.state,
                lead,
                1,
                accepted_target,
                record["execution_context"],
            ),
            coordination.build_turn_prompt(
                accepted.state,
                interlocutor,
                1,
                accepted_target,
                record["execution_context"],
            ),
            coordination.build_closure_proposal_prompt(
                accepted.state,
                accepted_target,
                record["execution_context"],
            ),
            coordination.build_closure_vote_prompt(
                accepted.state,
                interlocutor,
                accepted_target,
                closing_summary(),
                record["execution_context"],
            ),
        )
        target = accepted.state["request"]["target_path"]
        self.assertFalse(adapter._path_overlap(target, self.workspace))
        for prompt in prompts:
            self.assertIn("target_path: %s" % target, prompt)
            self.assertIn(
                "PRIMARY ROOT %s — caller context" % self.workspace,
                prompt,
            )
            self.assertIn(
                "It does not constrain target_path location",
                prompt,
            )
            self.assertNotIn(
                "target must remain inside this writable root",
                prompt,
            )

    def test_owned_target_override_does_not_change_standalone_admission(self):
        owned_parent = os.path.join(self.tmp.name, "owned-target")
        os.makedirs(owned_parent)
        owned_target = os.path.join(owned_parent, "proposal.md")
        with open(owned_target, "w", encoding="utf-8") as handle:
            handle.write("materialized proposal\n")
        body = self._body(owned_target)
        refused_launcher = _LaunchFactory()
        with self.assertRaises(lifecycle.PublicLifecycleError) as refused:
            lifecycle.create_resolved_session(
                self.home,
                body,
                "standalone:test",
                self.context,
                self.config,
                launcher=refused_launcher,
            )
        self.assertEqual(refused.exception.status, 400)
        self.assertEqual(refused_launcher.calls, [])

        accepted = lifecycle.create_resolved_session(
            self.home,
            body,
            "milestone:test",
            self.context,
            self.config,
            launcher=_LaunchFactory(),
            owned_target_path=owned_target,
        )
        self.assertEqual(
            accepted["state"]["request"]["target_path"], owned_target
        )
        self.assertEqual(
            lifecycle._record_by_id(self.home, accepted["id"])[
                "execution_context"
            ],
            self.context,
        )

    def test_terminal_handoff_names_retained_acceptance_not_live_drift(self):
        source = os.path.join(self.workspace, "proposals", "handoff.md")
        with open(source, "wb") as handle:
            handle.write(b"launch baseline")
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": "implementation/milestones/example",
        }
        with (
            mock.patch.object(adapter, "service_home", return_value=self.home),
            mock.patch.object(
                lifecycle,
                "_launch_lifecycle_process",
                side_effect=_LaunchFactory(),
            ),
        ):
            created = adapter.create_session(
                state,
                self.config,
                "impl:8",
                rethink(
                    contracts.KIND_REVIEW_ROUND,
                    finding=report_finding(),
                    target="proposals/handoff.md",
                ),
                [],
            )
        target = created["state"]["request"]["target_path"]
        self.assertFalse(adapter._path_overlap(target, self.workspace))
        with open(source, "rb") as handle:
            self.assertEqual(handle.read(), b"launch baseline")
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"launch baseline")
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        snapshot = store.read(created["id"])
        with open(target, "wb") as handle:
            handle.write(b"accepted proposal")
        accepted = coordination.capture_target(target)
        snapshot = store.record_completed_turn(
            created["id"],
            snapshot.revision,
            "initial-position",
            "Produce the proposal.",
            accepted,
        )
        retained = store.read_target_revision(
            created["id"],
            snapshot.state["accepted_target_revision"],
        )
        snapshot = store.record_completed_turn(
            created["id"],
            snapshot.revision,
            "contrary-position",
            "The proposal is coherent.",
            accepted,
        )
        snapshot = store.record_completed_turn(
            created["id"],
            snapshot.revision,
            "dante",
            "Dante accepts the proportionate proposal.",
            accepted,
        )
        ballot = {
            "after_completed_rounds": 1,
            "target_revision": snapshot.state[
                "accepted_target_revision"
            ],
            "votes": [
                {"participant_id": "initial-position", "vote": "accept"},
                {"participant_id": "contrary-position", "vote": "accept"},
            ],
            "approved": True,
        }
        result = {
            "outcome": "success",
            "target_ref": target,
            "transcript_ref": snapshot.state["transcript_ref"],
            "rounds_used": 1,
        }
        closing = {
            "reason": "The bounded proposal was accepted.",
            "unresolved_objections": [],
            "affected_parties": "The milestone workers using the proposal.",
            "damage_altitude": "A bounded and reversible design decision.",
            "proportionality": "The discussion matched the decision.",
            "escalation_evidence": None,
            "open_questions": [],
        }
        ballot["closing_summary"] = closing
        store.close_with_ballot(
            created["id"],
            snapshot.revision,
            ballot,
            result,
            closing,
        )
        with mock.patch.object(adapter, "service_home", return_value=self.home):
            handoff = adapter.terminal_handoff(state, created["id"])
            self.assertEqual(
                set(handoff),
                {
                    "session_id",
                    "result",
                    "accepted_target_revision",
                    "retained_target",
                    "work_duration_s",
                    "work_token_usage",
                    "work_token_usage_partial",
                },
            )
            self.assertEqual(handoff["work_duration_s"], 0)
            self.assertEqual(
                handoff["accepted_target_revision"],
                retained["revision"],
            )
            with open(target, "rb") as handle:
                self.assertEqual(handle.read(), b"accepted proposal")
            with open(source, "rb") as handle:
                self.assertEqual(handle.read(), b"launch baseline")
            expanded = adapter.prompt_handoff(state, handoff)
            self.assertEqual(
                expanded["retained_target"],
                {
                    "exists": True,
                    "encoding": "utf-8",
                    "content": "accepted proposal",
                },
            )
            self.assertEqual(
                adapter.terminal_handoff(state, created["id"]),
                handoff,
            )
            with open(target, "wb") as handle:
                handle.write(b"unaccepted live drift")
            self.assertEqual(
                adapter.terminal_handoff(state, created["id"]),
                handoff,
            )
            self.assertEqual(
                adapter.prompt_handoff(state, handoff)["retained_target"][
                    "content"
                ],
                "accepted proposal",
            )

    def test_operational_terminal_is_not_a_domain_handoff(self):
        target = os.path.join(
            self.workspace, "proposals", "operational.md"
        )
        with open(target, "wb") as handle:
            handle.write(b"baseline")
        created = self._create(
            "proposals/operational.md", launcher=_LaunchFactory()
        )
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        coordinator = coordination.BrainstormingCoordinator(store, None)
        self.assertTrue(
            lifecycle._safe_operational_failure(
                store, coordinator, created["id"]
            )
        )
        terminal = store.read(created["id"])
        self.assertEqual(terminal.state["status"], "failure")
        self.assertEqual(
            terminal.state["failure_origin"], "operational"
        )
        self.assertEqual(
            terminal.state["history"][-1]["failure_origin"],
            "operational",
        )
        with (
            mock.patch.object(
                adapter, "service_home", return_value=self.home
            ),
            self.assertRaises(adapter.OperationalTerminalError),
        ):
            adapter.terminal_handoff(
                {"workspace": self.workspace}, created["id"]
            )

        stopped_launcher = _LaunchFactory()
        stopped = self._create(
            "proposals/stopped.md", launcher=stopped_launcher
        )
        store.append_activity(stopped["id"], {
            "id": "activity-before-stop",
            "action_id": "turn-before-stop",
            "provider_attempt": 1,
            "at": "2026-07-29T10:00:00+0200",
            "started_at": 100.0,
            "duration_s": 3.5,
            "kind": "discussion_turn",
            "stage": "discussion",
            "round": 1,
            "participant_id": "lead",
            "model_family": "codex",
            "model": None,
            "effort": None,
            "status": "completed",
        })
        stopped_launcher.calls[0][2].terminate()
        with mock.patch.object(
            adapter, "service_home", return_value=self.home
        ):
            self.assertIsNone(
                adapter.terminal_handoff(
                    {"workspace": self.workspace}, stopped["id"]
                )
            )

    def test_materialized_target_survives_operational_failure(self):
        source = os.path.join(
            self.workspace, "proposals", "failed-session.md"
        )
        with open(source, "wb") as handle:
            handle.write(b"retained baseline")
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": "implementation/milestones/example",
        }
        with (
            mock.patch.object(adapter, "service_home", return_value=self.home),
            mock.patch.object(
                lifecycle,
                "_launch_lifecycle_process",
                side_effect=_LaunchFactory(),
            ),
        ):
            created = adapter.create_session(
                state,
                self.config,
                "impl:8",
                rethink(
                    contracts.KIND_REVIEW_ROUND,
                    finding=report_finding(),
                    target="proposals/failed-session.md",
                ),
                [],
            )
        target = created["state"]["request"]["target_path"]
        store = bs.SessionStore(lifecycle.state_directory(self.home))
        coordinator = coordination.BrainstormingCoordinator(store, None)
        self.assertTrue(
            lifecycle._safe_operational_failure(
                store, coordinator, created["id"]
            )
        )
        with mock.patch.object(
            adapter, "service_home", return_value=self.home
        ):
            with self.assertRaises(adapter.OperationalTerminalError):
                adapter.terminal_handoff(state, created["id"])
        with open(source, "rb") as handle:
            self.assertEqual(handle.read(), b"retained baseline")
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"retained baseline")

    def test_adapter_materializes_targets_without_repository_path_taxonomy(self):
        docs_dir = "implementation/milestones/example"
        os.makedirs(os.path.join(self.workspace, docs_dir))
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": docs_dir,
        }
        git_dir = os.path.join(self.workspace, ".git")
        os.makedirs(git_dir)
        git_head = os.path.join(git_dir, "HEAD")
        with open(git_head, "w", encoding="utf-8") as handle:
            handle.write("ref: refs/heads/main\n")
        os.makedirs(os.path.join(self.workspace, ".orchestrator"))
        os.makedirs(
            os.path.join(
                self.workspace,
                "implementation",
                "milestones",
                "other-milestone",
            )
        )
        requested_targets = [
            ".git/HEAD",
            ".orchestrator/state.json",
            "implementation/milestones/example/skeleton.md",
            "implementation/milestones/other-milestone/skeleton.md",
        ]
        for requested_target in requested_targets:
            source = os.path.join(self.workspace, requested_target)
            os.makedirs(os.path.dirname(source), exist_ok=True)
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("requested source\n")
            with self.subTest(requested_target=requested_target):
                self.assertEqual(
                    adapter.validate_target(
                        state,
                        rethink(
                            contracts.KIND_REVIEW_ROUND,
                            finding=report_finding(),
                            target=requested_target,
                        ),
                        [],
                    ),
                    source,
                )
                with mock.patch.object(
                    adapter, "service_home", return_value=self.home
                ):
                    _work_area, materialized = adapter._materialize_target(
                        state,
                        rethink(
                            contracts.KIND_REVIEW_ROUND,
                            finding=report_finding(),
                            target=requested_target,
                        ),
                        [],
                    )
                self.assertFalse(
                    adapter._path_overlap(materialized, self.workspace)
                )
                with open(materialized, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), "requested source\n")
        reference = os.path.join(self.workspace, "docs", "context.md")
        with open(reference, "w", encoding="utf-8") as handle:
            handle.write("context")
        self.assertEqual(
            adapter.stable_references(
                state,
                [os.path.relpath(reference, self.workspace)],
                os.path.relpath(reference, self.workspace),
            ),
            [os.path.relpath(reference, self.workspace)],
        )
        outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(outside)
        outside_parent = os.path.join(
            self.workspace, "proposals", "outside-parent"
        )
        os.symlink(outside, outside_parent)
        with self.assertRaises(adapter.AdapterError):
            adapter.validate_target(
                state,
                rethink(
                    contracts.KIND_REVIEW_ROUND,
                    finding=report_finding(),
                    target="proposals/outside-parent/proposal.md",
                ),
                [],
            )
        accepted = adapter.validate_target(
            state,
            rethink(
                contracts.KIND_REVIEW_ROUND,
                finding=report_finding(),
                target="proposals/separate.md",
            ),
            [os.path.relpath(reference, self.workspace)],
        )
        self.assertEqual(
            accepted,
            os.path.join(self.workspace, "proposals", "separate.md"),
        )

        source = os.path.join(self.workspace, "proposals", "active.md")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("source proposal\n")
        captured_targets = []

        def capture_create(
            home,
            body,
            caller,
            context,
            config,
            owned_target_path=None,
        ):
            captured_targets.append(owned_target_path)
            return {"id": "session-%d" % len(captured_targets), "state": {}}

        with (
            mock.patch.object(adapter, "service_home", return_value=self.home),
            mock.patch.object(
                lifecycle,
                "create_resolved_session",
                side_effect=capture_create,
            ),
        ):
            for _index in range(2):
                adapter.create_session(
                    state,
                    self.config,
                    "impl:8",
                    rethink(
                        contracts.KIND_REVIEW_ROUND,
                        finding=report_finding(),
                        target="proposals/active.md",
                    ),
                    [],
                )
        self.assertEqual(len(set(captured_targets)), 2)
        self.assertTrue(
            all(
                not adapter._path_overlap(target, self.workspace)
                for target in captured_targets
            )
        )

    def test_adapter_materializes_readable_hard_linked_source(self):
        source = os.path.join(self.workspace, "proposals", "linked.md")
        alias = os.path.join(self.workspace, "proposals", "alias.md")
        with open(source, "wb") as handle:
            handle.write(b"requested source")
        os.link(source, alias)
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": "implementation/milestones/example",
        }

        with mock.patch.object(
            adapter, "service_home", return_value=self.home
        ):
            work_area, materialized = adapter._materialize_target(
                state,
                rethink(
                    contracts.KIND_REVIEW_ROUND,
                    finding=report_finding(),
                    target="proposals/linked.md",
                ),
                [],
            )

        self.assertTrue(os.path.isdir(work_area))
        with open(materialized, "rb") as handle:
            self.assertEqual(handle.read(), b"requested source")
        self.assertEqual(os.stat(materialized).st_nlink, 1)
        self.assertTrue(os.path.samefile(source, alias))

    def test_owned_target_root_revalidates_every_placement_fallback(self):
        source = os.path.join(self.workspace, "proposals", "fallback.md")
        with open(source, "wb") as handle:
            handle.write(b"requested source")
        state = {
            "name": "run",
            "workspace": self.workspace,
            "docs_dir": "implementation/milestones/example",
        }
        service_inside = os.path.join(self.workspace, "service-home")
        temporary_inside = os.path.join(self.workspace, "temporary-files")
        with (
            mock.patch.object(
                adapter, "service_home", return_value=service_inside
            ),
            mock.patch.object(
                adapter.tempfile,
                "gettempdir",
                return_value=temporary_inside,
            ),
        ):
            work_area, materialized = adapter._materialize_target(
                state,
                rethink(
                    contracts.KIND_REVIEW_ROUND,
                    finding=report_finding(),
                    target="proposals/fallback.md",
                ),
                [],
            )
        self.assertFalse(adapter._path_overlap(work_area, self.workspace))
        self.assertFalse(adapter._path_overlap(materialized, self.workspace))
        with open(materialized, "rb") as handle:
            self.assertEqual(handle.read(), b"requested source")


class MilestoneDriverRethinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="milestone-rethink-")
        self.addCleanup(self.tmp.cleanup)
        self.workspace = self.tmp.name
        os.makedirs(os.path.join(self.workspace, "proposals"))

    def _state_path(self, status=st.U_PENDING, workspace=None, config=None):
        workspace = workspace or self.workspace
        config = copy.deepcopy(config or make_config())
        if (config.get("git") or {}).get("enabled"):
            subprocess.run(
                ["git", "init", "-q"],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=True,
            )
        state = st.new_state("Build the adapter.", workspace, config)
        st.append_event(state, "initialized", goal=state["goal"])
        state["milestone"]["slices"] = [{"id": 8, "title": "Adapter"}]
        skeleton = st._new_unit(st.UNIT_SKELETON, None)
        skeleton["status"] = st.U_SEALED
        note = st._new_unit(st.UNIT_SLICE_DOC, 8)
        note["status"] = st.U_SEALED
        unit = st._new_unit(st.UNIT_SLICE_IMPL, 8)
        unit["status"] = status
        state["units"] = [skeleton, note, unit]
        path = drv.default_state_path(workspace)
        st.save(path, state)
        return path

    def _slice_doc_path(self, workspace=None, config=None):
        path = self._state_path(workspace=workspace, config=config)
        state = st.load(path)
        note = next(
            unit for unit in state["units"]
            if st.unit_key(unit) == "slice_doc-08"
        )
        note["status"] = st.U_PENDING
        note["artifact"] = None
        note["draft"] = None
        st.save(path, state)
        return path

    @staticmethod
    def _created():
        return {
            "id": "brainstorming-session",
            "state": {
                "completed_turns": [],
                "rounds_used": 0,
                "recovery_baseline_revision": "baseline-revision",
                "accepted_target_revision": None,
            },
        }

    @staticmethod
    def _handoff(outcome="success"):
        result = {
            "outcome": outcome,
            "target_ref": "/retained/brainstorming-work-area/target.md",
            "transcript_ref": "/retained/chat.md",
            "rounds_used": 1,
        }
        if outcome == "failure":
            result["reason"] = "No coherent proposal was produced."
        return {
            "session_id": "brainstorming-session",
            "result": result,
            "accepted_target_revision": (
                "accepted-revision" if outcome == "success" else None
            ),
            **(
                {
                    "retained_target": {
                        "exists": True,
                        "encoding": "utf-8",
                        "content": "accepted proposal",
                    }
                }
                if outcome == "success"
                else {}
            ),
        }

    def test_ordinary_results_and_provider_failures_create_no_brainstorming_target_state(
        self,
    ):
        config = make_config(
            error_classifier=False,
            infra_retry_backoff_s=[],
        )

        def assert_no_brainstorming(path, runner):
            with (
                mock.patch.object(adapter, "create_session") as create,
                mock.patch.object(
                    coordination,
                    "capture_target",
                    side_effect=AssertionError(
                        "ordinary worker outcome observed a proposal target"
                    ),
                ),
                mock.patch.object(
                    drv.Driver,
                    "_classify_failure",
                    return_value=("unknown", None, None),
                ),
            ):
                drv.Driver(path, runner=runner).step()
            create.assert_not_called()

        class OrdinaryOnlyRunner(runners.MockRunner):
            def supports_session_continuation(self, family, ambient=False):
                return False

            def start_session(self, *args, **kwargs):
                raise AssertionError(
                    "ordinary output must keep working without continuation"
                )

        ordinary_path = self._state_path(config=config)
        ordinary_runner = OrdinaryOnlyRunner(
            [{
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": {
                    "status": "ok",
                    "kind": contracts.KIND_IMPLEMENT,
                    "files_changed": [],
                },
            }]
        )
        assert_no_brainstorming(
            ordinary_path,
            ordinary_runner,
        )
        self.assertEqual(ordinary_runner.session_calls, [])
        self.assertFalse(
            os.path.exists(
                os.path.join(self.workspace, "proposals", "rethink.md")
            )
        )

        malformed_workspace = os.path.join(self.tmp.name, "malformed")
        os.makedirs(os.path.join(malformed_workspace, "proposals"))
        malformed_path = self._state_path(
            workspace=malformed_workspace, config=config
        )
        assert_no_brainstorming(
            malformed_path,
            runners.MockRunner(
                [
                    {
                        "expect_kind": contracts.KIND_IMPLEMENT,
                        "response": "not a contract",
                    },
                    {
                        "expect_kind": contracts.KIND_IMPLEMENT,
                        "response": "still not a contract",
                    },
                ]
            ),
        )

        unavailable_workspace = os.path.join(self.tmp.name, "unavailable")
        os.makedirs(os.path.join(unavailable_workspace, "proposals"))
        unavailable_path = self._state_path(
            workspace=unavailable_workspace, config=config
        )

        def provider_unavailable(_workspace):
            raise runners.RunnerError("provider unavailable")

        assert_no_brainstorming(
            unavailable_path,
            runners.MockRunner(
                [{
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "side_effect": provider_unavailable,
                    "response": "",
                }]
            ),
        )

    def test_rethink_pause_recovery_uses_recorded_session_without_advancing(self):
        path = self._state_path()
        signal = rethink(contracts.KIND_IMPLEMENT)
        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": signal,
                },
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_IMPLEMENT,
                        "files_changed": [],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            first = drv.Driver(path, runner=runner)
            action, _note = first.step()
        self.assertEqual(action.type, drv.A_DRAFT)
        paused = st.load(path)
        unit = st.current_unit(paused)
        self.assertEqual(unit["status"], st.U_PENDING)
        self.assertIsNone(unit["draft"])
        self.assertEqual(unit["rounds"], [])
        self.assertEqual(
            runner.session_calls,
            [("start", "codex", "mock-session-1")],
        )

        with mock.patch.object(adapter, "terminal_handoff", return_value=None):
            waiting = drv.Driver(path, runner=runner)
            waiting.step()
        still_paused = st.load(path)
        self.assertEqual(
            st.current_unit(still_paused)["brainstorming_wait"]["session_id"],
            "brainstorming-session",
        )
        self.assertEqual(len(runner.calls), 1)

        handoff = self._handoff()
        handoff["work_duration_s"] = 2.5
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=handoff
        ):
            resumed = drv.Driver(path, runner=runner)
            resumed.step()
        returned = st.load(path)
        self.assertEqual(st.current_unit(returned)["status"], st.U_PENDING)
        self.assertNotIn(
            "brainstorming_wait", st.current_unit(returned)
        )
        self.assertEqual(
            runner.session_calls[-1],
            ("continue", "codex", "mock-session-1"),
        )
        self.assertEqual(
            [
                event["duration_s"]
                for event in returned["events"]
                if event["type"] == "brainstorming_work_recorded"
            ],
            [2.5],
        )

        completed = drv.Driver(path, runner=runner)
        completed.step()
        unit = st.current_unit(st.load(path))
        self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertIsNotNone(unit["draft"])
        self.assertEqual(len(runner.calls), 2)

    def test_retried_rethink_counts_reused_raw_path_again(self):
        path = self._state_path()
        runner = runners.MockRunner([
            {
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": rethink(contracts.KIND_IMPLEMENT),
            },
            {
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": rethink(contracts.KIND_IMPLEMENT),
            },
        ])
        durable_before_create = []

        def fail_create(*_args, **_kwargs):
            durable_before_create.extend(
                event for event in st.load(path)["events"]
                if event["type"] == "brainstorming_origin_recorded"
            )
            raise adapter.AdapterError("creation unavailable")

        with mock.patch.object(
            adapter,
            "create_session",
            side_effect=fail_create,
        ):
            _action, note = drv.Driver(path, runner=runner).step()
        self.assertIn("run failed", note)
        self.assertEqual(len(durable_before_create), 1)

        failed = st.load(path)
        st.resume_run(failed)
        st.save(path, failed)
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()

        resumed = st.load(path)
        origins = [
            event for event in resumed["events"]
            if event["type"] == "brainstorming_origin_recorded"
        ]
        self.assertEqual(len(origins), 2)
        self.assertEqual(origins[0]["raw_path"], origins[1]["raw_path"])
        self.assertEqual(
            st.summary(resumed)["work_duration_s"], 0.02
        )

    def test_successful_rethink_attachment_survives_outer_step_crash(self):
        path = self._state_path()
        runner = runners.MockRunner([{
            "expect_kind": contracts.KIND_IMPLEMENT,
            "response": rethink(contracts.KIND_IMPLEMENT),
        }])
        driver = drv.Driver(path, runner=runner)
        original_save = driver._save
        saves = []

        def crash_on_outer_save():
            saves.append(len(saves) + 1)
            if len(saves) == 3:
                raise KeyboardInterrupt()
            original_save()

        with (
            mock.patch.object(
                adapter, "create_session", return_value=self._created()
            ),
            mock.patch.object(driver, "_save", side_effect=crash_on_outer_save),
            self.assertRaises(KeyboardInterrupt),
        ):
            driver.step()

        durable = st.load(path)
        wait = st.current_unit(durable)["brainstorming_wait"]
        self.assertEqual(wait["session_id"], "brainstorming-session")
        self.assertEqual(
            [
                event["type"] for event in durable["events"]
                if event["type"].startswith("brainstorming_")
            ],
            ["brainstorming_origin_recorded", "brainstorming_wait_started"],
        )

    def test_run_waits_for_brainstorming_and_continues_without_manual_start(self):
        path = self._state_path()
        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": rethink(contracts.KIND_IMPLEMENT),
                },
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_IMPLEMENT,
                        "files_changed": [],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()

        with (
            mock.patch.object(
                adapter,
                "terminal_handoff",
                side_effect=[None, None, self._handoff()],
            ) as inspect,
            mock.patch.object(drv.time, "sleep") as sleep,
        ):
            code = drv.Driver(path, runner=runner).run(max_steps=2)

        self.assertEqual(code, 3)
        self.assertEqual(inspect.call_count, 3)
        self.assertEqual(
            sleep.call_args_list,
            [
                mock.call(drv.BRAINSTORMING_POLL_INTERVAL_S),
                mock.call(drv.BRAINSTORMING_POLL_INTERVAL_S),
            ],
        )
        unit = st.current_unit(st.load(path))
        self.assertNotIn("brainstorming_wait", unit)
        self.assertNotIn("brainstorming_resume", unit)
        self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(
            runner.session_calls,
            [
                ("start", "codex", "mock-session-1"),
                ("continue", "codex", "mock-session-1"),
            ],
        )

    def test_run_detects_brainstorming_process_failure_while_waiting(self):
        path = self._state_path()
        runner = runners.MockRunner(
            [{
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": rethink(contracts.KIND_IMPLEMENT),
            }]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()

        with (
            mock.patch.object(
                adapter,
                "terminal_handoff",
                side_effect=[
                    None,
                    adapter.OperationalTerminalError(
                        "participant execution failed",
                        work_duration_s=4.0,
                    ),
                ],
            ),
            mock.patch.object(drv.time, "sleep") as sleep,
        ):
            code = drv.Driver(path, runner=runner).run(max_steps=2)

        self.assertEqual(code, 2)
        sleep.assert_called_once_with(drv.BRAINSTORMING_POLL_INTERVAL_S)
        state = st.load(path)
        self.assertEqual(
            state["failure"]["type"], "brainstorming_operational"
        )
        self.assertNotIn(
            "brainstorming_wait", st.current_unit(state)
        )
        self.assertEqual(st.summary(state)["work_duration_s"], 4.01)

    def test_run_discards_deleted_brainstorming_and_retries_origin(self):
        path = self._state_path()
        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": rethink(contracts.KIND_IMPLEMENT),
                },
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_IMPLEMENT,
                        "files_changed": [],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()

        missing = lifecycle.PublicLifecycleError(
            404, lifecycle.UNKNOWN_SESSION
        )
        with mock.patch.object(
            adapter, "terminal_handoff", side_effect=missing
        ):
            code = drv.Driver(path, runner=runner).run(max_steps=2)

        self.assertEqual(code, 3)
        state = st.load(path)
        unit = st.current_unit(state)
        self.assertNotIn("brainstorming_wait", unit)
        self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertIsNone(state["failure"])
        self.assertIn(
            "brainstorming_missing_detached",
            [event["type"] for event in state["events"]],
        )
        self.assertEqual(
            runner.session_calls,
            [
                ("start", "codex", "mock-session-1"),
                ("start", "codex", "mock-session-2"),
            ],
        )

    def test_run_observes_brainstorming_started_on_last_allowed_step(self):
        path = self._state_path()
        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": rethink(contracts.KIND_IMPLEMENT),
                },
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_IMPLEMENT,
                        "files_changed": [],
                    },
                },
            ]
        )

        with (
            mock.patch.object(
                adapter, "create_session", return_value=self._created()
            ),
            mock.patch.object(
                adapter,
                "terminal_handoff",
                side_effect=[None, self._handoff()],
            ) as inspect,
            mock.patch.object(drv.time, "sleep") as sleep,
        ):
            code = drv.Driver(path, runner=runner).run(max_steps=1)

        self.assertEqual(code, 3)
        self.assertEqual(inspect.call_count, 2)
        sleep.assert_called_once_with(drv.BRAINSTORMING_POLL_INTERVAL_S)
        unit = st.current_unit(st.load(path))
        self.assertNotIn("brainstorming_wait", unit)
        self.assertIn("brainstorming_resume", unit)
        self.assertEqual(
            runner.session_calls,
            [
                ("start", "codex", "mock-session-1"),
                ("continue", "codex", "mock-session-1"),
            ],
        )

    def test_run_reports_terminal_failure_on_last_allowed_step(self):
        path = self._state_path()
        runner = runners.MockRunner(
            [{
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": rethink(contracts.KIND_IMPLEMENT),
            }]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()

        with mock.patch.object(
            adapter,
            "terminal_handoff",
            side_effect=adapter.OperationalTerminalError(
                "participant execution failed"
            ),
        ):
            code = drv.Driver(path, runner=runner).run(max_steps=1)

        self.assertEqual(code, 2)
        state = st.load(path)
        self.assertEqual(
            state["failure"]["type"], "brainstorming_operational"
        )
        self.assertNotIn(
            "brainstorming_wait", st.current_unit(state)
        )

    def test_slice_note_drafter_rethink_continues_the_origin_session(self):
        path = self._slice_doc_path()
        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_DRAFT_SLICE_NOTE,
                    "response": rethink(contracts.KIND_DRAFT_SLICE_NOTE),
                },
                {
                    "expect_kind": contracts.KIND_DRAFT_SLICE_NOTE,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_DRAFT_SLICE_NOTE,
                        "artifact": "docs/slice-08.md",
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()

        paused = st.current_unit(st.load(path))
        self.assertEqual(paused["kind"], st.UNIT_SLICE_DOC)
        self.assertEqual(paused["status"], st.U_PENDING)
        self.assertIsNone(paused["draft"])

        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(path, runner=runner).step()
        drv.Driver(path, runner=runner).step()

        note = next(
            unit for unit in st.load(path)["units"]
            if st.unit_key(unit) == "slice_doc-08"
        )
        self.assertEqual(note["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(
            note["draft"]["result"]["artifact"], "docs/slice-08.md"
        )
        self.assertEqual(
            runner.session_calls,
            [
                ("start", "codex", "mock-session-1"),
                ("continue", "codex", "mock-session-1"),
            ],
        )

    def test_slice_note_rethink_failure_stops_without_redocumenting(self):
        path = self._slice_doc_path()
        runner = runners.MockRunner(
            [{
                "expect_kind": contracts.KIND_DRAFT_SLICE_NOTE,
                "response": rethink(contracts.KIND_DRAFT_SLICE_NOTE),
            }]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()
        with mock.patch.object(
            adapter,
            "terminal_handoff",
            return_value=self._handoff("failure"),
        ):
            drv.Driver(path, runner=runner).step()

        state = st.load(path)
        note = next(
            unit for unit in state["units"]
            if st.unit_key(unit) == "slice_doc-08"
        )
        skeleton = next(
            unit for unit in state["units"]
            if st.unit_key(unit) == "skeleton"
        )
        self.assertEqual(note["status"], st.U_FAILED)
        self.assertIsNone(note["draft"])
        self.assertNotIn("brainstorming_wait", note)
        self.assertEqual(skeleton["status"], st.U_SEALED)
        self.assertEqual(
            state["failure"]["type"], "brainstorming_no_agreement"
        )
        self.assertFalse(
            any(event["type"] == "gap_reported" for event in state["events"])
        )

    def test_implementer_and_fixer_continue_exact_origin_session(self):
        implement_workspace = os.path.join(self.tmp.name, "same-implement")
        os.makedirs(os.path.join(implement_workspace, "proposals"))
        implement_path = self._state_path(workspace=implement_workspace)
        implement_runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": rethink(contracts.KIND_IMPLEMENT),
                },
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_IMPLEMENT,
                        "files_changed": [],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(implement_path, runner=implement_runner).step()
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(implement_path, runner=implement_runner).step()
        drv.Driver(implement_path, runner=implement_runner).step()
        self.assertEqual(
            implement_runner.session_calls,
            [
                ("start", "codex", "mock-session-1"),
                ("continue", "codex", "mock-session-1"),
            ],
        )
        self.assertEqual(
            st.current_unit(st.load(implement_path))["status"],
            st.U_PRE_REVIEW_VERIFY,
        )

        fixer_workspace = os.path.join(self.tmp.name, "same-fixer")
        os.makedirs(os.path.join(fixer_workspace, "proposals"))
        git_config = make_config(
            git={"enabled": True},
            snapshot_exclude_dirs=[],
            error_classifier=False,
            infra_retry_backoff_s=[],
        )
        fixer_path = self._state_path(
            status=st.U_FIXING,
            workspace=fixer_workspace,
            config=git_config,
        )
        fixer_state = st.load(fixer_path)
        fixer_unit = st.current_unit(fixer_state)
        finding = report_finding()
        fixer_unit["fix_queue"] = [copy.deepcopy(finding)]
        fixer_unit["fix_source"] = {
            "type": "round",
            "origin_type": "round",
            "family": "claude",
            "source_round_id": "round-1",
            "return_to": st.U_ROUNDS,
        }
        st.save(fixer_path, fixer_state)

        def apply_fix(workspace):
            with open(
                os.path.join(workspace, "fixed.txt"), "w", encoding="utf-8"
            ) as handle:
                handle.write("fixed\n")

        fixed_finding = {
            "id": finding["id"],
            "severity": finding["severity"],
            "summary": "The unresolved choice is now implemented.",
            "validity": fixer_validity(True),
            "disposition": "fixed",
            "consultation": None,
            "prevention": None,
            "adjudication_ref": None,
        }
        fixer_runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_FIX_FINDINGS,
                    "response": rethink(
                        contracts.KIND_FIX_FINDINGS, finding=finding
                    ),
                },
                {
                    "expect_kind": contracts.KIND_FIX_FINDINGS,
                    "side_effect": apply_fix,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_FIX_FINDINGS,
                        "findings": [fixed_finding],
                        "files_changed": ["fixed.txt"],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(fixer_path, runner=fixer_runner).step()
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(fixer_path, runner=fixer_runner).step()
        drv.Driver(fixer_path, runner=fixer_runner).step()
        self.assertEqual(
            fixer_runner.session_calls,
            [
                ("start", "codex", "mock-session-1"),
                ("continue", "codex", "mock-session-1"),
            ],
        )
        self.assertEqual(
            st.current_unit(st.load(fixer_path))["status"],
            st.U_DELTA_REVIEW,
        )

    def test_suite_repair_rethink_continuation_keeps_suite_contract(self):
        command = "python3 -m unittest discover -s tests"
        path = self._state_path(
            status=st.U_FIXING,
            config=make_config(verification=[command]),
        )
        state = st.load(path)
        unit = st.current_unit(state)
        signal = report_finding("V1")
        unit["fix_queue"] = [copy.deepcopy(signal)]
        unit["fix_source"] = {
            "type": "verification",
            "origin_type": "verification",
            "family": None,
            "source_round_id": "slice_impl-08-verify-pre_seal-1",
            "return_to": st.U_PRE_SEAL_VERIFY,
        }
        unit["verify_fix_attempts"]["pre_seal"] = 1
        st.save(path, state)
        runner = runners.MockRunner([
            {
                "expect_kind": contracts.KIND_FIX_FINDINGS,
                "response": rethink(
                    contracts.KIND_FIX_FINDINGS,
                    finding=signal,
                ),
            },
            {
                "expect_kind": contracts.KIND_FIX_FINDINGS,
                "response": {
                    "status": "ok",
                    "kind": contracts.KIND_FIX_FINDINGS,
                    "findings": [],
                    "files_changed": [],
                },
            },
        ])

        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(path, runner=runner).step()
        drv.Driver(path, runner=runner).step()

        continuation = runner.calls[1][2]
        self.assertIn("FULL-SUITE REPAIR CONTINUES", continuation)
        self.assertIn(command, continuation)
        self.assertIn("SUITE FAILURE JUDGMENT", continuation)
        self.assertIn("affected party", continuation)
        self.assertIn("findings` must be empty", continuation)
        self.assertNotIn("FIX DECISION TABLE", continuation)
        state = st.load(path)
        unit = st.current_unit(state)
        self.assertIsNone(state["failure"])
        self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(unit["rounds"][-1]["result"]["findings"], [])
        self.assertTrue(any(
            event["type"] == "verification"
            and event.get("fixer_certified") is True
            for event in state["events"]
        ))
        self.assertEqual(
            runner.session_calls,
            [
                ("start", "codex", "mock-session-1"),
                ("continue", "codex", "mock-session-1"),
            ],
        )

    def test_fixer_amendment_continues_and_closes_without_phantom_bytes(self):
        workspace = os.path.join(self.tmp.name, "amendment-fixer")
        os.makedirs(os.path.join(workspace, "proposals"))
        config = make_config(
            git={"enabled": True},
            snapshot_exclude_dirs=[],
            error_classifier=False,
            infra_retry_backoff_s=[],
        )
        path = self._state_path(
            status=st.U_FIXING, workspace=workspace, config=config
        )
        state = st.load(path)
        unit = st.current_unit(state)
        finding = report_finding()
        unit["fix_queue"] = [copy.deepcopy(finding)]
        unit["fix_source"] = {
            "type": "round",
            "origin_type": "round",
            "family": "claude",
            "source_round_id": "round-1",
            "return_to": st.U_ROUNDS,
        }
        st.save(path, state)
        fixed = {
            "id": finding["id"],
            "severity": finding["severity"],
            "summary": "The accepted amendment settles the choice.",
            "validity": fixer_validity(True),
            "disposition": "fixed",
            "consultation": None,
            "prevention": None,
            "adjudication_ref": None,
        }
        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_FIX_FINDINGS,
                    "response": rethink(
                        contracts.KIND_FIX_FINDINGS,
                        finding=finding,
                        rounds=10,
                        result_mode="design_amendment",
                    ),
                },
                {
                    "expect_kind": contracts.KIND_FIX_FINDINGS,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_FIX_FINDINGS,
                        "findings": [fixed],
                        "files_changed": [],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()
        handoff = self._handoff()
        handoff["retained_target"]["content"] = (
            "    # Indented amendment\n\n"
            + " ".join(["Necessary semantic detail."] * 180)
            + "\n\n"
        )
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=handoff
        ):
            drv.Driver(path, runner=runner).step()
        drv.Driver(path, runner=runner).step()
        drv.Driver(path, runner=runner).step()

        state = st.load(path)
        unit = st.current_unit(state)
        adopted = [
            event for event in state["events"]
            if event["type"] == "brainstorming_design_amendment_adopted"
        ]
        self.assertEqual(len(adopted), 1)
        self.assertEqual(adopted[0]["amendment_id"], "B1")
        merged = drv.Driver(path, runner=runner)._amendments(
            record_seen=False
        )
        self.assertEqual(merged[-1]["authority"], "brainstorming_design")
        self.assertEqual(merged[-1]["text"], handoff["retained_target"]["content"])
        self.assertIn(handoff["retained_target"]["content"], runner.calls[1][2])
        self.assertEqual(unit["status"], st.U_ROUNDS)
        self.assertEqual(unit["fix_queue"], [])
        self.assertEqual(
            unit["rounds"][-1]["design_amendment_finding_id"], finding["id"]
        )
        self.assertFalse(
            any(event["type"] == "phantom_fix_retry" for event in state["events"])
        )
        self.assertIn(
            "ACCEPTED BRAINSTORMING DESIGN AMENDMENTS", runner.calls[1][2]
        )
        self.assertEqual(
            runner.session_calls,
            [
                ("start", "codex", "mock-session-1"),
                ("continue", "codex", "mock-session-1"),
            ],
        )

    def test_current_and_legacy_amendment_placeholders_are_not_adopted(self):
        path = self._state_path()
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        unit = st.current_unit(driver.state)
        wait = {
            "signal": {
                "finding": {"id": "F1"},
                "target_path": "proposals/rethink.md",
            }
        }
        for placeholder in adapter.DESIGN_AMENDMENT_PLACEHOLDERS:
            handoff = self._handoff()
            handoff["retained_target"]["content"] = placeholder
            with self.subTest(placeholder=placeholder), self.assertRaises(
                adapter.AdapterError
            ):
                driver._adopt_brainstorming_design_amendment(
                    unit, wait, handoff
                )

    def test_continuation_receives_current_amendments_and_project_law(self):
        path = self._state_path()
        policy = {
            "id": "current-guard",
            "version": 2,
            "enabled": True,
            "scope": {
                "kinds": [contracts.KIND_IMPLEMENT],
                "unit_kinds": [st.UNIT_SLICE_IMPL],
            },
            "prompt": "Record the currently binding implementation check.",
            "contract": {
                "field": "current_audit",
                "required": True,
                "entry": {"note": {"type": "string"}},
                "checks": [{"kind": "non_empty", "field": "note"}],
            },
        }
        extension = verifiers.compile_policy(policy)
        project_context = {
            "project": "orchestrators",
            "work_area": "implementation",
            "primary": {"path": self.workspace},
            "additional": [],
            "reuse_sources": None,
            "safeguards": [policy],
        }
        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": rethink(contracts.KIND_IMPLEMENT),
                },
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_IMPLEMENT,
                        "files_changed": [],
                        "current_audit": [{"note": "checked current law"}],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()

        resumed = drv.Driver(path, runner=runner)
        amendments_path = resumed._amendments_path()
        os.makedirs(os.path.dirname(amendments_path), exist_ok=True)
        with open(amendments_path, "w", encoding="utf-8") as handle:
            handle.write(
                '{"amendments":[{"id":"A-live","text":'
                '"Use the newly selected behavior."}]}'
            )
        with (
            mock.patch.object(
                adapter, "terminal_handoff", return_value=self._handoff()
            ),
            mock.patch.object(
                resumed,
                "_project_prompt_inputs",
                return_value=(
                    project_context,
                    [extension],
                    [self.workspace],
                ),
            ),
        ):
            resumed.step()

        continuation_prompt = runner.calls[1][2]
        self.assertIn("OPERATOR AMENDMENTS", continuation_prompt)
        self.assertIn(
            "[A-live] Use the newly selected behavior.", continuation_prompt
        )
        self.assertIn("PROJECT CONTEXT", continuation_prompt)
        self.assertIn("SAFEGUARD current-guard v2", continuation_prompt)
        self.assertIn("REQUIRED OUTPUT FIELD 'current_audit'", continuation_prompt)
        self.assertEqual(
            runner.session_calls[-1],
            ("continue", "codex", "mock-session-1"),
        )

    def test_ordinary_rethink_supplies_current_amendments_to_brainstorming(self):
        path = self._state_path()
        runner = runners.MockRunner([
            {
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": rethink(contracts.KIND_IMPLEMENT),
            }
        ])
        driver = drv.Driver(path, runner=runner)
        amendments_path = driver._amendments_path()
        os.makedirs(os.path.dirname(amendments_path), exist_ok=True)
        with open(amendments_path, "w", encoding="utf-8") as handle:
            handle.write(
                '{"amendments":[{"id":"A-live","text":'
                '"Use the selected behavior."}]}'
            )
        captured = {}

        def create(*args, **kwargs):
            captured.update(copy.deepcopy(kwargs))
            return self._created()

        with mock.patch.object(adapter, "create_session", side_effect=create):
            driver.step()

        self.assertEqual(
            captured["authority_context"]["amendments"],
            [{"id": "A-live", "text": "Use the selected behavior."}],
        )
        self.assertNotIn("project_context", captured["authority_context"])

    def test_failure_stops_without_fabricating_gap_or_review_result(
        self,
    ):
        path = self._state_path()
        runner = runners.MockRunner(
            [{
                "expect_kind": contracts.KIND_IMPLEMENT,
                "response": rethink(contracts.KIND_IMPLEMENT),
            }]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()
        with mock.patch.object(
            adapter,
            "terminal_handoff",
            return_value=self._handoff("failure"),
        ):
            drv.Driver(path, runner=runner).step()
        state = st.load(path)
        reported = [
            event for event in state["events"]
            if event["type"] == "gap_reported"
        ]
        self.assertEqual(reported, [])
        impl = next(
            unit for unit in state["units"]
            if st.unit_key(unit) == "slice_impl-08"
        )
        self.assertIsNone(impl["draft"])
        self.assertEqual(impl["status"], st.U_FAILED)
        self.assertEqual(
            state["failure"]["type"], "brainstorming_no_agreement"
        )

        review_workspace = os.path.join(self.tmp.name, "review")
        os.makedirs(os.path.join(review_workspace, "proposals"))
        review_path = self._state_path(
            status=st.U_ROUNDS, workspace=review_workspace
        )
        review_state = st.load(review_path)
        finding = report_finding()
        review_runner = runners.MockRunner(
            [{
                "expect_kind": contracts.KIND_REVIEW_ROUND,
                "response": rethink(
                    contracts.KIND_REVIEW_ROUND, finding=finding
                ),
            }]
        )
        st.save(review_path, review_state)
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(review_path, runner=review_runner).step()
        with mock.patch.object(
            adapter,
            "terminal_handoff",
            return_value=self._handoff("failure"),
        ):
            drv.Driver(review_path, runner=review_runner).step()
        failed_review = st.load(review_path)
        review_unit = st.current_unit(failed_review)
        self.assertEqual(review_unit["status"], st.U_FAILED)
        self.assertEqual(review_unit["fix_queue"], [])
        self.assertEqual(review_unit["rounds"], [])
        self.assertEqual(
            failed_review["failure"]["type"],
            "brainstorming_no_agreement",
        )

        operational_workspace = os.path.join(
            self.tmp.name, "operational-wait"
        )
        os.makedirs(os.path.join(operational_workspace, "proposals"))
        operational_path = self._state_path(
            workspace=operational_workspace
        )
        operational_runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": rethink(contracts.KIND_IMPLEMENT),
                },
                {
                    "expect_kind": contracts.KIND_IMPLEMENT,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_IMPLEMENT,
                        "files_changed": [],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(
                operational_path, runner=operational_runner
            ).step()
        with mock.patch.object(
            adapter,
            "terminal_handoff",
            side_effect=adapter.OperationalTerminalError(
                "participant execution failed"
            ),
        ):
            drv.Driver(
                operational_path, runner=operational_runner
            ).step()
        operational_state = st.load(operational_path)
        self.assertEqual(
            operational_state["failure"]["type"],
            "brainstorming_operational",
        )
        self.assertFalse(
            st.current_unit(operational_state).get("brainstorming_wait")
        )
        self.assertFalse(
            any(
                event["type"] == "gap_reported"
                for event in operational_state["events"]
            )
        )
        st.resume_run(operational_state)
        st.save(operational_path, operational_state)
        drv.Driver(
            operational_path, runner=operational_runner
        ).step()
        retried = st.load(operational_path)
        self.assertEqual(
            st.current_unit(retried)["status"], st.U_PRE_REVIEW_VERIFY
        )
        self.assertEqual(
            operational_runner.session_calls,
            [
                ("start", "codex", "mock-session-1"),
                ("start", "codex", "mock-session-2"),
            ],
        )

    def test_review_and_delta_restart_fresh(self):
        path = self._state_path(status=st.U_ROUNDS)
        finding = report_finding()
        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_REVIEW_ROUND,
                    "response": rethink(
                        contracts.KIND_REVIEW_ROUND, finding=finding
                    ),
                },
                {
                    "expect_kind": contracts.KIND_REVIEW_ROUND,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_REVIEW_ROUND,
                        "findings": [],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(path, runner=runner).step()
        self.assertEqual(len(runner.calls), 1)
        drv.Driver(path, runner=runner).step()
        state = st.load(path)
        self.assertEqual(len(st.current_unit(state)["rounds"]), 1)
        self.assertIn(
            "BRAINSTORMING RETURN (FRESH REVIEW REQUIRED)",
            runner.calls[1][2],
        )
        self.assertEqual(runner.session_calls, [])

        tamper_workspace = os.path.join(self.tmp.name, "review-tamper")
        os.makedirs(os.path.join(tamper_workspace, "proposals"))
        tamper_config = make_config(
            git={"enabled": True},
            snapshot_exclude_dirs=[],
            error_classifier=False,
            infra_retry_backoff_s=[],
        )
        tamper_path = self._state_path(
            status=st.U_ROUNDS,
            workspace=tamper_workspace,
            config=tamper_config,
        )

        def tamper(workspace):
            with open(
                os.path.join(workspace, "reviewer-edit.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("invalid reviewer edit\n")

        tamper_runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_REVIEW_ROUND,
                    "response": rethink(
                        contracts.KIND_REVIEW_ROUND, finding=finding
                    ),
                },
                {
                    "expect_kind": contracts.KIND_REVIEW_ROUND,
                    "side_effect": tamper,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_REVIEW_ROUND,
                        "findings": [],
                    },
                },
                {
                    "expect_kind": contracts.KIND_REVIEW_ROUND,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_REVIEW_ROUND,
                        "findings": [],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(tamper_path, runner=tamper_runner).step()
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(tamper_path, runner=tamper_runner).step()
        drv.Driver(tamper_path, runner=tamper_runner).step()
        retained_after_invalid = st.current_unit(st.load(tamper_path))
        self.assertIn(
            "brainstorming_review_handoff", retained_after_invalid
        )
        drv.Driver(tamper_path, runner=tamper_runner).step()
        self.assertNotIn(
            "brainstorming_review_handoff",
            st.current_unit(st.load(tamper_path)),
        )
        self.assertTrue(
            all(
                "BRAINSTORMING RETURN (FRESH REVIEW REQUIRED)" in call[2]
                for call in tamper_runner.calls[1:]
            )
        )

        delta_workspace = os.path.join(self.tmp.name, "delta")
        os.makedirs(os.path.join(delta_workspace, "proposals"))
        delta_config = make_config(
            git={"enabled": True},
            snapshot_exclude_dirs=[],
            error_classifier=False,
            infra_retry_backoff_s=[],
        )
        delta_path = self._state_path(
            status=st.U_DELTA_REVIEW,
            workspace=delta_workspace,
            config=delta_config,
        )
        delta_state = st.load(delta_path)
        delta_unit = st.current_unit(delta_state)
        delta_unit["fix_queue"] = [copy.deepcopy(finding)]
        delta_unit["fix_source"] = {
            "type": "round",
            "origin_type": "round",
            "family": "claude",
            "source_round_id": "round-1",
            "return_to": st.U_ROUNDS,
        }
        st.save(delta_path, delta_state)
        delta_runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_DELTA_REVIEW,
                    "response": rethink(
                        contracts.KIND_DELTA_REVIEW, finding=finding
                    ),
                },
                {
                    "expect_kind": contracts.KIND_DELTA_REVIEW,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_DELTA_REVIEW,
                        "findings": [],
                    },
                },
            ]
        )
        delta_driver = drv.Driver(delta_path, runner=delta_runner)
        with open(
            os.path.join(delta_workspace, "delta.txt"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("pending fix\n")
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            delta_driver.step()
        self.assertEqual(
            st.current_unit(st.load(delta_path))["rounds"], []
        )
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(delta_path, runner=delta_runner).step()
        drv.Driver(delta_path, runner=delta_runner).step()
        self.assertIn(
            "BRAINSTORMING RETURN (FRESH REVIEW REQUIRED)",
            delta_runner.calls[1][2],
        )
        self.assertIn(
            "does not change the\n"
            "ordinary prompt's review subject or scope",
            delta_runner.calls[1][2],
        )
        self.assertIn(
            "Review ONLY the uncommitted changes",
            delta_runner.calls[1][2],
        )
        self.assertNotIn(
            "milestone artifact named by the",
            delta_runner.calls[1][2],
        )
        self.assertEqual(delta_runner.session_calls, [])

    def test_retired_seal_handoff_is_migrated_to_an_ordinary_review(self):
        path = self._state_path(status=st.U_PRE_SEAL_VERIFY)
        state = st.load(path)
        unit = st.current_unit(state)
        unit["brainstorming_review_handoff"] = {
            "kind": "seal_half",
            "handoff": self._handoff(),
            "source_finding": report_finding(),
        }
        st.save(path, state)

        drv.Driver(path, runner=runners.MockRunner([])).step()

        migrated = st.load(path)
        current = st.current_unit(migrated)
        self.assertEqual(current["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(
            current["brainstorming_review_handoff"]["kind"],
            contracts.KIND_REVIEW_ROUND,
        )
        self.assertEqual(current["family_index"], 0)
        self.assertTrue(any(
            event["type"] == "brainstorming_review_handoff_migrated"
            for event in migrated["events"]
        ))

    def test_retired_seal_handoff_survives_pending_delta_as_review_context(self):
        from orchestrator.tests.test_driver_mock import fix_ok, triaged, write_file

        workspace = os.path.join(self.tmp.name, "retired-seal-delta")
        os.makedirs(os.path.join(workspace, "proposals"))
        config = make_config(
            git={"enabled": True},
            snapshot_exclude_dirs=[],
            error_classifier=False,
            infra_retry_backoff_s=[],
        )
        path = self._state_path(
            status=st.U_DELTA_REVIEW,
            workspace=workspace,
            config=config,
        )
        state = st.load(path)
        unit = st.current_unit(state)
        unit["fix_queue"] = [report_finding()]
        unit["fix_source"] = {
            "type": "seal",
            "origin_type": "seal",
            "family": "codex",
            "source_round_id": "slice_impl-08-seal-a1",
            "return_to": st.U_PRE_SEAL_VERIFY,
        }
        unit["brainstorming_review_handoff"] = {
            "kind": "seal_half",
            "handoff": self._handoff(),
            "source_finding": report_finding(),
        }
        st.save(path, state)
        pending_path = os.path.join(workspace, "pending-fix.txt")
        with open(
            pending_path,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("baseline\n")
        subprocess.run(
            ["git", "add", "pending-fix.txt"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            [
                "git", "-c", "user.name=Test", "-c",
                "user.email=test@example.invalid", "commit", "-qm",
                "baseline",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        with open(pending_path, "w", encoding="utf-8") as handle:
            handle.write("pending fix\n")
        runner = runners.MockRunner([
            {
                "expect_kind": contracts.KIND_DELTA_REVIEW,
                "response": {
                    "status": "ok",
                    "kind": contracts.KIND_DELTA_REVIEW,
                    "findings": [report_finding("D1")],
                },
            },
            {
                "expect_kind": contracts.KIND_FIX_FINDINGS,
                "response": fix_ok([
                    triaged("D1", "fixed", "delta defect", severity="P1")
                ], files_changed=["pending-fix.txt"]),
                "side_effect": write_file("pending-fix.txt", "fixed\n"),
            },
            {
                "expect_kind": contracts.KIND_DELTA_REVIEW,
                "response": {
                    "status": "ok",
                    "kind": contracts.KIND_DELTA_REVIEW,
                    "findings": [],
                },
            },
        ])

        driver = drv.Driver(path, runner=runner)
        for _ in range(3):
            driver.step()

        resumed = st.load(path)
        current = st.current_unit(resumed)
        self.assertEqual(current["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(
            current["brainstorming_review_handoff"]["kind"],
            contracts.KIND_REVIEW_ROUND,
        )
        self.assertEqual(current["family_index"], 0)
        self.assertEqual(len(runner.calls), 3)
        for call in (runner.calls[0], runner.calls[2]):
            self.assertNotIn(
                "BRAINSTORMING RETURN (FRESH REVIEW REQUIRED)", call[2]
            )

    def test_delta_brainstorming_temporarily_reserves_whole_review_handoff(self):
        workspace = os.path.join(self.tmp.name, "reserved-review-delta")
        os.makedirs(os.path.join(workspace, "proposals"))
        config = make_config(
            git={"enabled": True},
            snapshot_exclude_dirs=[],
            error_classifier=False,
            infra_retry_backoff_s=[],
        )
        path = self._state_path(
            status=st.U_DELTA_REVIEW,
            workspace=workspace,
            config=config,
        )
        state = st.load(path)
        unit = st.current_unit(state)
        unit["fix_queue"] = [report_finding("D2")]
        unit["fix_source"] = {
            "type": "round",
            "origin_type": "round",
            "family": "codex",
            "source_round_id": "slice_impl-08-codex-r1",
            "return_to": st.U_PRE_REVIEW_VERIFY,
        }
        original_handoff = {
            "kind": contracts.KIND_REVIEW_ROUND,
            "handoff": self._handoff(),
            "source_finding": report_finding("R1"),
        }
        unit["brainstorming_review_handoff"] = copy.deepcopy(
            original_handoff
        )
        st.save(path, state)
        pending_path = os.path.join(workspace, "pending-fix.txt")
        with open(pending_path, "w", encoding="utf-8") as handle:
            handle.write("baseline\n")
        subprocess.run(
            ["git", "add", "pending-fix.txt"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            [
                "git", "-c", "user.name=Test", "-c",
                "user.email=test@example.invalid", "commit", "-qm",
                "baseline",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        with open(pending_path, "w", encoding="utf-8") as handle:
            handle.write("pending fix\n")
        runner = runners.MockRunner([
            {
                "expect_kind": contracts.KIND_DELTA_REVIEW,
                "response": rethink(
                    contracts.KIND_DELTA_REVIEW,
                    finding=report_finding("D2"),
                ),
            },
            {
                "expect_kind": contracts.KIND_DELTA_REVIEW,
                "response": {
                    "status": "ok",
                    "kind": contracts.KIND_DELTA_REVIEW,
                    "findings": [],
                },
            },
        ])

        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()
        paused = st.current_unit(st.load(path))
        self.assertEqual(
            paused["brainstorming_review_handoff"], original_handoff
        )
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(path, runner=runner).step()
        nested = st.current_unit(st.load(path))[
            "brainstorming_review_handoff"
        ]
        self.assertEqual(nested["kind"], contracts.KIND_DELTA_REVIEW)
        self.assertEqual(nested["reserved_handoff"], original_handoff)

        drv.Driver(path, runner=runner).step()

        resumed = st.current_unit(st.load(path))
        self.assertEqual(resumed["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(
            resumed["brainstorming_review_handoff"], original_handoff
        )
        self.assertIn(
            "BRAINSTORMING RETURN (FRESH REVIEW REQUIRED)",
            runner.calls[-1][2],
        )

    def test_retired_seal_wait_success_restarts_as_ordinary_review(self):
        path = self._state_path(status=st.U_SEALING)
        state = st.load(path)
        unit = st.current_unit(state)
        unit["brainstorming_wait"] = {
            "session_id": "brainstorming-session",
            "signal": {"finding": report_finding()},
            "references": [],
            "origin": {
                "unit": st.unit_key(unit),
                "kind": "seal_half",
                "family": "codex",
            },
        }
        st.save(path, state)

        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(path, runner=runners.MockRunner([])).step()

        resumed = st.load(path)
        current = st.current_unit(resumed)
        self.assertEqual(current["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertNotIn("brainstorming_wait", current)
        self.assertEqual(
            current["brainstorming_review_handoff"]["kind"],
            contracts.KIND_REVIEW_ROUND,
        )
        self.assertEqual(current["family_index"], 0)

    def test_retired_seal_wait_failure_stops_without_synthetic_fix(self):
        path = self._state_path(status=st.U_SEALING)
        state = st.load(path)
        unit = st.current_unit(state)
        source_finding = report_finding()
        unit["brainstorming_wait"] = {
            "session_id": "brainstorming-session",
            "signal": {"finding": copy.deepcopy(source_finding)},
            "references": [],
            "origin": {
                "unit": st.unit_key(unit),
                "kind": "seal_half",
                "family": "codex",
            },
        }
        st.save(path, state)

        with mock.patch.object(
            adapter,
            "terminal_handoff",
            return_value=self._handoff("failure"),
        ):
            drv.Driver(path, runner=runners.MockRunner([])).step()

        resumed = st.load(path)
        current = st.current_unit(resumed)
        self.assertEqual(current["status"], st.U_FAILED)
        self.assertNotIn("brainstorming_wait", current)
        self.assertEqual(current["family_index"], 0)
        self.assertEqual(current["fix_queue"], [])
        self.assertEqual(
            resumed["failure"]["type"], "brainstorming_no_agreement"
        )

    def test_fresh_review_uses_retained_content_without_target_monitoring(self):
        workspace = os.path.join(self.tmp.name, "retained-target-review")
        os.makedirs(os.path.join(workspace, "proposals"))
        config = make_config(
            git={"enabled": True},
            snapshot_exclude_dirs=[],
            error_classifier=False,
            infra_retry_backoff_s=[],
        )
        path = self._state_path(
            status=st.U_ROUNDS,
            workspace=workspace,
            config=config,
        )
        finding = report_finding()

        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_REVIEW_ROUND,
                    "response": rethink(
                        contracts.KIND_REVIEW_ROUND, finding=finding
                    ),
                },
                {
                    "expect_kind": contracts.KIND_REVIEW_ROUND,
                    "response": {
                        "status": "ok",
                        "kind": contracts.KIND_REVIEW_ROUND,
                        "findings": [copy.deepcopy(finding)],
                    },
                },
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()
        with mock.patch.object(
            adapter, "terminal_handoff", return_value=self._handoff()
        ):
            drv.Driver(path, runner=runner).step()
        with mock.patch.object(
            coordination,
            "capture_target",
            side_effect=AssertionError(
                "ordinary review must not monitor the retained proposal target"
            ),
        ):
            drv.Driver(path, runner=runner).step()
        reviewed = st.current_unit(st.load(path))
        self.assertEqual(len(reviewed["rounds"]), 1)
        self.assertEqual(
            [queued["id"] for queued in reviewed["fix_queue"]],
            [finding["id"]],
        )
        self.assertNotIn(
            "brainstorming_review_handoff",
            reviewed,
        )
        self.assertIn(
            "does not change the\n"
            "ordinary prompt's review subject or scope",
            runner.calls[1][2],
        )
        self.assertIn('"source_finding": {', runner.calls[1][2])
        self.assertIn('"content": "accepted proposal"', runner.calls[1][2])

    def test_fixer_discussion_failure_preserves_queue_and_stops(self):
        path = self._state_path(status=st.U_FIXING)
        state = st.load(path)
        unit = st.current_unit(state)
        finding = report_finding()
        unit["fix_queue"] = [copy.deepcopy(finding)]
        unit["fix_source"] = {
            "type": "round",
            "origin_type": "round",
            "family": "claude",
            "source_round_id": "round-1",
            "return_to": st.U_ROUNDS,
        }
        st.save(path, state)
        runner = runners.MockRunner(
            [
                {
                    "expect_kind": contracts.KIND_FIX_FINDINGS,
                    "response": rethink(
                        contracts.KIND_FIX_FINDINGS, finding=finding
                    ),
                }
            ]
        )
        with mock.patch.object(
            adapter, "create_session", return_value=self._created()
        ):
            drv.Driver(path, runner=runner).step()
        with (
            mock.patch.object(
                adapter,
                "terminal_handoff",
                return_value=self._handoff("failure"),
            ),
            mock.patch.object(
                drv.Driver,
                "_handle_gap",
                side_effect=AssertionError(
                    "an ineligible fixer must not enter gap cleanup"
                ),
            ),
        ):
            drv.Driver(path, runner=runner).step()
        stopped = st.load(path)
        stopped_unit = st.current_unit(stopped)
        self.assertEqual(
            stopped["failure"]["type"], "brainstorming_no_agreement"
        )
        self.assertEqual(stopped_unit["failed_from"], st.U_FIXING)
        self.assertEqual(stopped_unit["fix_queue"], [finding])
        self.assertNotIn("brainstorming_wait", stopped_unit)
        self.assertIsNone(stopped.get("pending_gap"))
        self.assertFalse(
            any(
                event["type"] in ("gap_reported", "gap_edits_discarded")
                for event in stopped["events"]
            )
        )

    def test_fixer_amendment_reuses_brainstorming_revision_and_design_correction(
        self,
    ):
        path = self._state_path(status=st.U_FIXING)
        state = st.load(path)
        unit = st.current_unit(state)
        finding = report_finding()
        unit["fix_queue"] = [finding]
        unit["fix_source"] = {
            "type": "round",
            "origin_type": "round",
            "family": "codex",
            "source_round_id": "r1",
            "return_to": st.U_ROUNDS,
        }
        st.save(path, state)
        driver = drv.Driver(path, runner=runners.MockRunner([]))
        note_unit = driver._find_unit(st.UNIT_SLICE_DOC, 8)
        note_unit["artifact"] = "note.md"
        note_unit["gate_commit"] = "note-gate"
        note = os.path.join(self.workspace, "note.md")
        with open(note, "wb") as handle:
            handle.write(b"corrected note")
        authority = bs.make_target_revision(True, b"proposal", 0o644)
        handoff = self._handoff()
        declaration = {
            "artifact": "note.md",
            "brainstorming_authority": {
                "session_id": handoff["session_id"],
                "accepted_target_revision": handoff[
                    "accepted_target_revision"
                ],
            },
            "contradiction": "the sealed note omits the accepted choice",
            "resolution": "record the accepted choice in the note",
        }
        with (
            mock.patch.object(
                drv.gitops, "show_file", return_value=b"sealed note"
            ),
            mock.patch.object(
                adapter, "retained_revision", return_value=authority
            ),
        ):
            candidate, error = driver._start_design_correction(
                unit,
                declaration,
                ["note.md"],
                {
                    "mode": "offer",
                    "artifact": "note.md",
                    "note_unit": st.unit_key(note_unit),
                    "authority_gate": "gate",
                },
                "refs",
                "sym",
                "head",
                "tree",
                "worktree",
                "stash",
                brainstorming_handoff=handoff,
            )
            self.assertIsNone(error)
            self.assertEqual(
                candidate["brainstorming_authority"],
                declaration["brainstorming_authority"],
            )
            self.assertIsNone(
                driver._design_correction_integrity_error(candidate)
            )
            review_context = driver._design_correction_review_context(
                candidate
            )
            self.assertEqual(
                review_context["retained_authority_content"], "proposal"
            )
            self.assertEqual(
                review_context["retained_authority_encoding"], "utf-8"
            )

        remodel = driver._design_correction_gap(
            candidate, "remodel", "the goal already requires this choice"
        )
        operator = driver._design_correction_gap(
            candidate, "needs_operator", "the goal must choose"
        )
        self.assertEqual(remodel["classification"], "fits_remodel")
        self.assertEqual(operator["classification"], "needs_operator")

        retry_candidate = copy.deepcopy(candidate)
        with (
            mock.patch.object(drv.gitops, "restore_to_snapshot"),
            mock.patch.object(drv.gitops, "restore_index_tree"),
        ):
            driver._rollback_design_correction(
                unit, "ordinary retry finding", retry_candidate
            )
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertIsNone(unit["design_correction"])

        ratify_candidate = copy.deepcopy(candidate)
        unit["design_correction"] = ratify_candidate
        with mock.patch.object(
            drv.gitops,
            "ratify_note_correction",
            return_value=("ratified-note", "amended-implementation"),
        ):
            driver._ratify_design_correction(
                unit,
                ratify_candidate,
                {
                    "decision": "ratify",
                    "reason": "the retained proposal uniquely settles the note",
                },
                st.U_ROUNDS,
            )
        self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(st.current_family(driver.state, unit), "codex")
        self.assertEqual(note_unit["status"], st.U_SEALED)
        self.assertEqual(note_unit["gate_commit"], "ratified-note")
        self.assertIsNone(driver.state.get("redoc_wave"))

        wrong = copy.deepcopy(declaration)
        wrong["brainstorming_authority"]["accepted_target_revision"] = "other"
        with mock.patch.object(
            drv.gitops, "show_file", return_value=b"sealed note"
        ):
            _candidate, error = driver._start_design_correction(
                unit,
                wrong,
                ["note.md"],
                {
                    "mode": "offer",
                    "artifact": "note.md",
                    "note_unit": st.unit_key(note_unit),
                    "authority_gate": "gate",
                },
                "refs",
                "sym",
                "head",
                "tree",
                "worktree",
                "stash",
                brainstorming_handoff=handoff,
            )
        self.assertIn("does not match", error)


if __name__ == "__main__":
    unittest.main()
