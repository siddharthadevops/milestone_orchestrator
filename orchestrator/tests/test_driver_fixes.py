"""Regression tests for adversarial-review fixes that survived the
review/fix-separation redesign.

Covers, per finding:
- milestone_closed is recorded exactly once, and re-running a finished
  state appends nothing;
- a worker protocol failure persists its raw output before failing closed;
- tool-cache writes by read-only reviewers do not invalidate the round
  (defaults + snapshot_exclude_dirs config);
- a second driver invocation is refused before any worker call runs
  (staleness check + advisory lock);
- an invalid canonical slice plan fails closed instead of silently
  collapsing the unit plan.

Deliberately self-contained (no imports from other test modules): local
helpers script the NEW protocol — reviewers report findings without
dispositions; fixers triage exactly the queued ids.

All workspaces are tempfile.TemporaryDirectory(); nothing touches the repo.
"""

import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import profiles
from orchestrator import runners
from orchestrator import state as st
from orchestrator.tests.test_driver_mock import prompt_response

GOAL = "Build a small CLI calculator (add/sub/mul/div) with unit tests"


def make_config(**overrides):
    """Minimal frozen config; commands are never spawned (mock runners)."""
    cfg = {
        "families_order": ["codex", "claude"],
        "fix_family": None,
        "commands": {"codex": ["fake-codex"], "claude": ["fake-claude"]},
        "timeouts": {},
        "verification": [],
        "verification_timeout": 60,
        "max_rounds_per_family": 6,
        "git": {"enabled": True},
        "max_verify_fix_attempts": 2,
        "acts": {"skeletoner": "codex", "fixer": "codex", "delta_review": "codex",
                 "consultation": "opposite"},
        "max_fix_loops": 4,
    }
    cfg.update(overrides)
    return cfg


def init_state(workspace, config, goal=GOAL):
    """Create the on-disk state file the way `driver init` does."""
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=workspace,
        check=True,
    )
    state = st.new_state(goal, workspace, config)
    st.append_event(state, "initialized", goal=goal)
    path = drv.default_state_path(workspace)
    st.save(path, state)
    with open(
        os.path.join(os.path.dirname(path), "amendments.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump({"amendments": []}, handle)
    return path


def ok(kind, **extra):
    payload = {"status": "ok", "kind": kind}
    payload.update(extra)
    return payload


def clean(kind="review_round"):
    """A clean report-only round (reviewers return findings, nothing else)."""
    return ok(kind, findings=[])


def reported(kind, summary, fid="F1", severity="P2"):
    """A reviewer finding: NO disposition (whoever detects never fixes)."""
    return ok(
        kind,
        findings=[{
            "id": fid,
            "severity": severity,
            "summary": summary,
            "validity": {
                "permitted_baseline": "the documented behavior",
                "actual_outcome": "the observed behavior",
                "incremental_harm": "the observed behavior breaks it",
                "exceeds_baseline": True,
            },
        }],
    )


def fixer_validity(exceeds=True):
    return {
        "affected_party": "the concrete user or system component",
        "observable_damage": (
            "the declared behavior is observably broken"
            if exceeds else "no damage beyond the allowed behavior"
        ),
        "violated_guarantee": (
            "the exact declared behavior"
            if exceeds else "no declared guarantee is violated"
        ),
        "permitted_baseline": "the documented behavior",
        "incremental_harm": (
            "the observed behavior exceeds that baseline"
            if exceeds else "no harm beyond the documented behavior"
        ),
        "exceeds_baseline": exceeds,
    }


def fix_fixed(*ids, **extra):
    """A fixer triage conceding every queued finding as fixed."""
    return ok(
        "fix_findings",
        findings=[
            {
                "id": fid,
                "severity": "P1",
                "summary": "queued finding %s addressed" % fid,
                "disposition": "fixed",
                "validity": fixer_validity(True),
            }
            for fid in ids
        ],
        files_changed=[],
        **extra
    )


def step(kind, response, family=None, side_effect=None):
    if isinstance(response, dict) and not callable(response):
        response = prompt_response(response)
    s = {"expect_kind": kind, "response": response}
    if family is not None:
        s["expect_family"] = family
    if side_effect is not None:
        s["side_effect"] = side_effect
    return s


def draft_skeleton_step(slices=None):
    plan = []
    for item in slices or [{"id": 1, "title": "core"}]:
        plan.append({
            "id": item["id"],
            "title": item["title"],
            "intent": item.get("intent") or "Deliver the bounded slice.",
            "producer_task_executor": {
                "draft_slice_note": "agent_call",
                "implement": "agent_call",
            },
        })

    def write_skeleton(workspace):
        path = os.path.join(workspace, "docs", "skeleton.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                % json.dumps({"slices": plan})
            )

    return step(
        "draft_skeleton",
        ok(
            "draft_skeleton",
            artifact="docs/skeleton.md",
        ),
        family="codex",
        side_effect=write_skeleton,
    )


def clean_reviews():
    return [
        step("review_round", clean(), family="codex"),
        step("review_round", clean(), family="claude"),
    ]


def skeleton_script():
    return [draft_skeleton_step()] + clean_reviews()


def doc_script():
    def write_note(workspace):
        with open(
            os.path.join(workspace, "docs", "slice-01.md"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("# Slice 1\n")

    return [
        step(
            "draft_slice_note",
            ok("draft_slice_note", artifact="docs/slice-01.md"),
            family="codex",
            side_effect=write_note,
        ),
    ] + clean_reviews()


def impl_script():
    def write_implementation(workspace):
        with open(
            os.path.join(workspace, "calculator.py"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("def add(a, b): return a + b\n")

    return [
        step(
            "implement",
            ok("implement", files_changed=["calculator.py"]),
            family="codex",
            side_effect=write_implementation,
        ),
    ] + clean_reviews() + [suite_checkpoint_step()]


def suite_checkpoint_step():
    return step(
        "suite_checkpoint",
        {
            "status": "no_suite",
            "kind": "suite_checkpoint",
            "commands": [],
            "results": [],
            "authority": {
                "source": "repository",
                "evidence": [{
                    "path": "docs/skeleton.md",
                    "basis": "No complete suite is configured or declared.",
                }],
            },
        },
        family="codex",
    )


class DriverTestCase(unittest.TestCase):
    """Shared drive helpers that also verify decide() totality."""

    def drive(self, driver, max_steps=200):
        """Step until DONE/FAILED; decide() must be total after every step."""
        actions = []
        for _ in range(max_steps):
            action = drv.decide(driver.state)
            if action.type in (drv.A_DONE, drv.A_FAILED):
                return actions, action
            act, note = driver.step()
            actions.append((act.type, note))
            after = drv.decide(driver.state)  # totality: never raises
            self.assertIsInstance(after, drv.Action)
        self.fail("driver did not reach a terminal action in %d steps" % max_steps)

    def step_until(self, driver, pred, max_steps=100):
        for _ in range(max_steps):
            if pred(driver.state):
                return
            action = drv.decide(driver.state)
            self.assertNotIn(
                action.type,
                (drv.A_DONE, drv.A_FAILED),
                "terminal action before predicate was satisfied: %r" % action,
            )
            driver.step()
            self.assertIsInstance(drv.decide(driver.state), drv.Action)
        self.fail("predicate never satisfied within %d steps" % max_steps)


class TestPauseAfterSeal(DriverTestCase):
    """Operator safe pause: with control.json's stop_after_seal set, the
    run loop exits cleanly (code 4) right after the next unit seals — the
    one point where worktree == HEAD == reviewed — instead of proceeding.
    One-shot: honoring the order clears the flag; a plain re-run resumes
    and finishes the milestone."""

    def _control_path(self, state_path):
        return os.path.join(os.path.dirname(state_path), "control.json")

    def test_pause_fires_after_first_seal_and_resume_completes(self):
        with tempfile.TemporaryDirectory(prefix="orch-pause-") as ws:
            path = init_state(ws, make_config())
            with open(self._control_path(path), "w") as fh:
                json.dump({"stop_after_seal": True}, fh)
            mock = runners.MockRunner(
                skeleton_script() + doc_script() + impl_script()
            )
            driver = drv.Driver(path, runner=mock)
            self.assertEqual(driver.run(), 4)
            state = st.load(path)
            # Exactly the skeleton sealed; nothing further ran.
            sealed = [st.unit_key(u) for u in state["units"]
                      if u["status"] == st.U_SEALED]
            self.assertEqual(sealed, ["skeleton"])
            paused = [e for e in state["events"]
                      if e["type"] == "paused_after_seal"]
            self.assertEqual(len(paused), 1)
            self.assertEqual(paused[0]["units"], ["skeleton"])
            # The doc/impl scripts are untouched: the pause consumed no
            # extra worker calls.
            self.assertEqual(len(mock.script),
                             len(doc_script()) + len(impl_script()))
            # One-shot: the flag cleared when honored...
            with open(self._control_path(path)) as fh:
                self.assertNotIn("stop_after_seal", json.load(fh))
            # ...so a plain re-run resumes and completes the milestone.
            again = drv.Driver(path, runner=mock)
            self.assertEqual(again.run(), 0)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            self.assertEqual(state["milestone"]["status"], "closed")
            self.assertEqual(
                len([e for e in state["events"]
                     if e["type"] == "paused_after_seal"]), 1)

    def test_no_flag_means_no_pause(self):
        with tempfile.TemporaryDirectory(prefix="orch-pause-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner(
                skeleton_script() + doc_script() + impl_script()
            )
            self.assertEqual(drv.Driver(path, runner=mock).run(), 0)
            state = st.load(path)
            self.assertEqual(
                [e for e in state["events"]
                 if e["type"] == "paused_after_seal"], [])


class TestMilestoneCloseIdempotent(DriverTestCase):
    def test_milestone_closed_recorded_exactly_once(self):
        """P2: run()'s A_DONE branch re-called maybe_close_milestone with
        no already-closed guard: two milestone_closed events per normal
        run, plus one more per extra `run` invocation."""
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner(
                skeleton_script() + doc_script() + impl_script()
            )
            driver = drv.Driver(path, runner=mock)
            self.assertEqual(driver.run(), 0)
            self.assertEqual(mock.script, [])

            def closed_count():
                state = st.load(path)
                return len(
                    [e for e in state["events"]
                     if e["type"] == "milestone_closed"]
                )

            self.assertEqual(closed_count(), 1)
            # Re-running a finished workspace appends nothing.
            for _ in range(3):
                again = drv.Driver(path, runner=runners.MockRunner([]))
                self.assertEqual(again.run(), 0)
            self.assertEqual(closed_count(), 1)


class TestRunStepLimitTerminalObservation(unittest.TestCase):
    def queue_profile_swap(self, driver):
        profile = {"p3_defer_max_risk": "low"}
        ref = {
            "name": "replacement",
            "version": 1,
            "hash": profiles.semantic_hash(profile),
        }
        with open(driver._profile_swap_path(), "w", encoding="utf-8") as fh:
            json.dump({"ref": ref, "profile": profile}, fh)
        return ref

    def test_last_allowed_action_reports_terminal_success(self):
        with tempfile.TemporaryDirectory(prefix="orch-step-limit-") as ws:
            path = init_state(ws, make_config())
            driver = drv.Driver(path, runner=runners.MockRunner([]))
            replacement_refs = []

            def close_on_step():
                replacement_refs.append(self.queue_profile_swap(driver))
                with driver._exclusive():
                    driver._assert_not_stale()
                    st.current_unit(driver.state)["status"] = st.U_SEALED
                    driver._save()
                return drv.Action(drv.A_SEAL_ATTEMPT), None

            driver.step = close_on_step
            self.assertEqual(driver.run(max_steps=1), 0)
            state = st.load(path)
            self.assertEqual(state["milestone"]["status"], st.M_CLOSED)
            self.assertEqual(
                [e["to"] for e in state["events"]
                 if e["type"] == "profile_changed"],
                replacement_refs,
            )

    def test_last_allowed_action_reports_terminal_failure(self):
        with tempfile.TemporaryDirectory(prefix="orch-step-limit-") as ws:
            path = init_state(ws, make_config())
            driver = drv.Driver(path, runner=runners.MockRunner([]))
            replacement_refs = []

            def fail_on_step():
                replacement_refs.append(self.queue_profile_swap(driver))
                with driver._exclusive():
                    driver._assert_not_stale()
                    st.fail_run(
                        driver.state,
                        "terminal failure on final allowed action",
                        unit=st.current_unit(driver.state),
                        type_="orchestrator",
                    )
                    driver._save()
                return drv.Action(drv.A_VERIFY), "run failed"

            driver.step = fail_on_step
            self.assertEqual(driver.run(max_steps=1), 2)
            state = st.load(path)
            self.assertEqual(
                [e["to"] for e in state["events"]
                 if e["type"] == "profile_changed"],
                replacement_refs,
            )


class TestProtocolFailureRawOutputs(DriverTestCase):
    def test_raw_texts_saved_on_protocol_violation(self):
        """The rejected reply is preserved before the run fails closed."""
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                step("draft_skeleton", "utter junk, not JSON at all"),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)

            raw_dir = os.path.join(ws, ".orchestrator", "raw")
            with open(os.path.join(raw_dir, "skeleton-draft-protoerr1.txt"),
                      encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "utter junk, not JSON at all")


class TestSnapshotCacheExclusions(DriverTestCase):
    def _drive_review_with_side_effect(self, ws, config, side_effect):
        path = init_state(ws, config)
        mock = runners.MockRunner([
            draft_skeleton_step(),
            step("review_round", clean(), family="codex",
                 side_effect=side_effect),
            step("review_round", clean(), family="claude"),
        ])
        driver = drv.Driver(path, runner=mock)
        self.step_until(
            driver, lambda s: s["units"][0]["status"] == st.U_SEALED
        )
        self.assertEqual(mock.script, [])
        return st.load(path)

    def test_pytest_cache_write_does_not_invalidate_round(self):
        """A reviewer's test cache must not invalidate its clean round."""
        def write_cache(workspace):
            d = os.path.join(workspace, ".pytest_cache", "v", "cache")
            os.makedirs(d)
            with open(os.path.join(d, "lastfailed"), "w",
                      encoding="utf-8") as fh:
                fh.write("{}")

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            state = self._drive_review_with_side_effect(
                ws, make_config(), write_cache
            )
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_SEALED)
            self.assertNotIn("invalidated", unit["rounds"][0])

    def test_snapshot_exclude_dirs_config_is_honored(self):
        def write_custom_cache(workspace):
            d = os.path.join(workspace, ".mytool_cache")
            os.makedirs(d)
            with open(os.path.join(d, "data"), "w", encoding="utf-8") as fh:
                fh.write("cache")

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            state = self._drive_review_with_side_effect(
                ws,
                make_config(snapshot_exclude_dirs=[".mytool_cache"]),
                write_custom_cache,
            )
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_SEALED)
            self.assertNotIn("invalidated", unit["rounds"][0])


class TestConcurrentInvocationRefused(DriverTestCase):
    @staticmethod
    def _waiting_driver(workspace):
        path = init_state(workspace, make_config())
        document = st.load(path)
        st.current_unit(document)["brainstorming_wait"] = {
            "session_id": "session-1",
            "signal": {
                "status": "need_rethink",
                "problem": "The governing plan needs focused repair.",
            },
            "origin": {"unit": "skeleton", "kind": "implement"},
        }
        st.save(path, document)
        return path, drv.Driver(path, runner=runners.MockRunner([]))

    def test_stale_driver_refuses_before_any_worker_call(self):
        """P3: two driver invocations on the same state both used to run
        side-effectful worker calls, with divergence detected only at save
        time. A stale driver now refuses BEFORE calling any worker."""
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            driver_a = drv.Driver(
                path, runner=runners.MockRunner([draft_skeleton_step()])
            )
            driver_b = drv.Driver(
                path, runner=runners.MockRunner([draft_skeleton_step()])
            )
            driver_a.step()  # advances the on-disk state
            with self.assertRaises(drv.ConcurrentRunError):
                driver_b.step()
            self.assertEqual(
                driver_b.runner.calls, [],
                "the stale driver must not have called any worker",
            )
            # driver_a is unaffected and still consistent with disk.
            self.assertEqual(
                st.load(path)["events"], driver_a.state["events"]
            )

    @unittest.skipIf(drv.fcntl is None, "fcntl unavailable on this platform")
    def test_held_lock_refuses_step(self):
        import fcntl as fcntl_mod

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            driver = drv.Driver(
                path, runner=runners.MockRunner([draft_skeleton_step()])
            )
            fh = open(path + ".lock", "a+")
            try:
                fcntl_mod.flock(fh.fileno(), fcntl_mod.LOCK_EX)
                with self.assertRaises(drv.ConcurrentRunError):
                    driver.step()
                self.assertEqual(driver.runner.calls, [])
            finally:
                fh.close()
            # Lock released: the same driver proceeds normally.
            action, _note = driver.step()
            self.assertEqual(action.type, drv.A_DRAFT)

    @unittest.skipIf(drv.fcntl is None, "fcntl unavailable on this platform")
    def test_pending_brainstorming_poll_does_not_contend_with_child_write(self):
        import fcntl as fcntl_mod

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path, driver = self._waiting_driver(ws)
            fh = open(path + ".lock", "a+")
            try:
                fcntl_mod.flock(fh.fileno(), fcntl_mod.LOCK_EX)
                with mock.patch.object(
                    drv.brainstorming_milestone,
                    "inspect_session",
                    return_value={"state": {"status": "running"}},
                ):
                    action, note = driver.step()
            finally:
                fh.close()

            self.assertEqual(action.type, drv.A_BRAINSTORM_WAIT)
            self.assertEqual(
                note, "waiting for Brainstorming session session-1"
            )
            self.assertEqual(driver.runner.calls, [])

    @unittest.skipIf(drv.fcntl is None, "fcntl unavailable on this platform")
    def test_terminal_brainstorming_poll_still_refuses_a_held_lock(self):
        import fcntl as fcntl_mod

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path, driver = self._waiting_driver(ws)
            fh = open(path + ".lock", "a+")
            try:
                fcntl_mod.flock(fh.fileno(), fcntl_mod.LOCK_EX)
                with mock.patch.object(
                    drv.brainstorming_milestone,
                    "inspect_session",
                    return_value={"state": {"status": "success"}},
                ):
                    with self.assertRaises(drv.ConcurrentRunError):
                        driver.step()
            finally:
                fh.close()
            self.assertEqual(driver.runner.calls, [])

    @unittest.skipIf(drv.fcntl is None, "fcntl unavailable on this platform")
    def test_inspection_error_waits_for_child_lock_then_fails_typed(self):
        import fcntl as fcntl_mod

        failures = (
            (
                "unavailable",
                lambda: drv.brainstorming_lifecycle.PublicLifecycleError(
                    503, drv.brainstorming_lifecycle.UNAVAILABLE
                ),
            ),
            ("runtime", lambda: RuntimeError("inspection broke")),
        )
        for label, failure in failures:
            with self.subTest(failure=label), tempfile.TemporaryDirectory(
                prefix="orch-fix-"
            ) as ws:
                path, driver = self._waiting_driver(ws)
                fh = open(path + ".lock", "a+")
                with (
                    mock.patch.object(
                        drv.brainstorming_milestone,
                        "inspect_session",
                        side_effect=lambda *_args, **_kwargs: failure(),
                    ),
                    mock.patch.object(drv.time, "sleep"),
                ):
                    try:
                        fcntl_mod.flock(fh.fileno(), fcntl_mod.LOCK_EX)
                        action, note = driver.step()
                    finally:
                        fh.close()

                    self.assertEqual(action.type, drv.A_BRAINSTORM_WAIT)
                    self.assertEqual(
                        note, "waiting for Brainstorming session session-1"
                    )
                    self.assertIsNone(st.load(path)["failure"])

                    action, note = driver.step()

                self.assertEqual(action.type, drv.A_BRAINSTORM_WAIT)
                self.assertIn("run failed", note)
                persisted = st.load(path)
                self.assertEqual(
                    persisted["failure"]["type"],
                    "brainstorming_operational",
                )
                self.assertEqual(driver.runner.calls, [])

    def test_pending_brainstorming_poll_does_not_hide_stale_state(self):
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path, driver = self._waiting_driver(ws)
            changed = st.load(path)
            st.append_event(changed, "unrelated_driver_update")
            st.save(path, changed)

            with mock.patch.object(
                drv.brainstorming_milestone,
                "inspect_session",
                return_value={"state": {"status": "running"}},
            ) as inspection:
                with self.assertRaises(drv.ConcurrentRunError):
                    driver.step()

            inspection.assert_not_called()
            self.assertEqual(driver.runner.calls, [])


class TestDuplicateSliceIdsEndToEnd(DriverTestCase):
    def test_duplicate_slice_ids_fail_the_run_not_the_plan(self):
        """P1: a contract-valid skeleton with duplicate slice ids used to
        collapse the unit plan and close the milestone with a slice
        silently dropped. The contract now rejects it; a worker that
        insists twice fails the run with the explanation recorded."""
        plan = {
            "slices": [
                {
                    "id": 1,
                    "title": "core",
                    "intent": "Deliver core.",
                    "producer_task_executor": {
                        "draft_slice_note": "agent_call",
                        "implement": "agent_call",
                    },
                },
                {
                    "id": 1,
                    "title": "totally different second slice",
                    "intent": "Deliver a different slice.",
                    "producer_task_executor": {
                        "draft_slice_note": "agent_call",
                        "implement": "agent_call",
                    },
                },
            ]
        }

        def write_duplicate_plan(workspace):
            path = os.path.join(workspace, "docs", "skeleton.md")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                    % json.dumps(plan)
                )

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                step(
                    "draft_skeleton",
                    ok("draft_skeleton", artifact="docs/skeleton.md"),
                    side_effect=write_duplicate_plan,
                ),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            state = st.load(path)
            self.assertIn(
                "duplicate canonical slice id", state["failure"]["reason"]
            )
            self.assertEqual(state["milestone"]["slices"], [])
            self.assertNotEqual(state["milestone"]["status"], st.M_CLOSED)


if __name__ == "__main__":
    unittest.main()
