"""Regression tests for adversarial-review fixes that survived the
review/fix-separation redesign.

Covers, per finding:
- milestone_closed is recorded exactly once, and re-running a finished
  state appends nothing;
- worker protocol failures persist the raw outputs of both attempts;
- tool-cache writes by read-only reviewers do not invalidate the round
  (defaults + snapshot_exclude_dirs config);
- verify-fix attempt caps are per verification stage (verification
  failures queue a synthetic V1 finding for a fix_findings episode);
- skeleton fix rounds can update the structural slice plan;
- a second driver invocation is refused before any worker call runs
  (staleness check + advisory lock);
- a contract-valid skeleton with duplicate slice ids fails the run
  instead of silently collapsing the unit plan.

Deliberately self-contained (no imports from other test modules): local
helpers script the NEW protocol — reviewers report findings without
dispositions; fixers triage exactly the queued ids.

All workspaces are tempfile.TemporaryDirectory(); nothing touches the repo.
"""

import json
import os
import tempfile
import unittest

from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st

GOAL = "Build a small CLI calculator (add/sub/mul/div) with unit tests"


def make_config(**overrides):
    """Minimal frozen config; commands are never spawned (mock runners).
    Git stays disabled: fix episodes return directly without delta reviews,
    which keeps these regressions independent of gitops."""
    cfg = {
        "families_order": ["codex", "claude"],
        "fix_family": None,
        "commands": {"codex": ["fake-codex"], "claude": ["fake-claude"]},
        "timeouts": {},
        "verification": [],
        "verification_timeout": 60,
        "max_rounds_per_family": 6,
        "max_verify_fix_attempts": 2,
        "acts": {"skeletoner": "codex", "fixer": "codex", "delta_review": "codex",
                 "consultation": "opposite"},
        "max_fix_loops": 4,
    }
    cfg.update(overrides)
    return cfg


def init_state(workspace, config, goal=GOAL):
    """Create the on-disk state file the way `driver init` does."""
    state = st.new_state(goal, workspace, config)
    st.append_event(state, "initialized", goal=goal)
    path = drv.default_state_path(workspace)
    st.save(path, state)
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
                "consultation": None,
                "validity": {
                    "permitted_baseline": "the documented behavior",
                    "actual_outcome": "the observed behavior",
                    "incremental_harm": "the observed behavior breaks it",
                    "exceeds_baseline": True,
                },
            }
            for fid in ids
        ],
        files_changed=[],
        **extra
    )


def step(kind, response, family=None, side_effect=None):
    s = {"expect_kind": kind, "response": response}
    if family is not None:
        s["expect_family"] = family
    if side_effect is not None:
        s["side_effect"] = side_effect
    return s


def draft_skeleton_step(slices=None):
    return step(
        "draft_skeleton",
        ok(
            "draft_skeleton",
            artifact="docs/skeleton.md",
            slices=slices or [{"id": 1, "title": "core"}],
        ),
        family="codex",
    )


def clean_reviews():
    return [
        step("review_round", clean(), family="codex"),
        step("review_round", clean(), family="claude"),
    ]


def skeleton_script():
    return [draft_skeleton_step()] + clean_reviews()


def doc_script():
    return [
        step(
            "draft_slice_note",
            ok("draft_slice_note", artifact="docs/slice-01.md"),
            family="codex",
        ),
    ] + clean_reviews()


def impl_script():
    return [
        step(
            "implement",
            ok("implement", files_changed=["calculator.py"]),
            family="codex",
        ),
    ] + clean_reviews()


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


class _FailingRunner(object):
    """Raises scripted exceptions, then succeeds with scripted responses."""

    def __init__(self, failures, then=None):
        self.failures = list(failures)
        self.then = list(then or [])
        self.calls = 0

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None):
        self.calls += 1
        self.profiles = getattr(self, "profiles", [])
        self.profiles.append((family, model, effort))
        if self.failures:
            raise self.failures.pop(0)
        import json as _json
        return runners.RunnerResult(_json.dumps(self.then.pop(0)), 0, 1.0)


class TestTypedInfraFailures(DriverTestCase):
    def test_quota_failure_is_typed_with_resume_at(self):
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            runner = _FailingRunner([
                runners.WorkerProtocolError(
                    "no valid JSON object found in worker output",
                    raw_texts=["You've hit your usage limit. "
                               "Your limit resets at 00:10."],
                ),
            ])
            driver = drv.Driver(path, runner=runner)
            driver.step()  # step swallows StopStep; the failure is recorded
            state = st.load(path)
            self.assertEqual(state["failure"]["type"], "quota")
            self.assertIsNotNone(state["failure"]["resume_at"])

    def test_login_failure_typed_without_resume(self):
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            runner = _FailingRunner([
                runners.WorkerProtocolError(
                    "no valid JSON object found in worker output",
                    raw_texts=["Not logged in · Please run /login"],
                ),
            ])
            driver = drv.Driver(path, runner=runner)
            driver.step()
            state = st.load(path)
            self.assertEqual(state["failure"]["type"], "login")
            self.assertIsNone(state["failure"]["resume_at"])

    def test_classifier_call_carries_its_family_profile(self):
        # The classifier runs on the OPPOSITE family, whose command
        # template may carry {model}/{effort}. Calling it without them
        # raised "command template uses {model} but no value was resolved"
        # before the CLI was ever reached, so the whole LLM fallback stage
        # was dead and EVERY unmatched failure degraded to `unknown`
        # (found live 2026-07-19). This pins the driver call site, not
        # just errclass.
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            cfg = make_config(
                infra_retry_backoff_s=[],
                error_classifier=True,
                model_defaults={
                    "codex": {"model": "gpt-5.6-sol", "effort": "xhigh"},
                    "claude": {"model": "claude-fable-5", "effort": "high"},
                },
            )
            path = init_state(ws, cfg)
            runner = _FailingRunner(
                [runners.RunnerError(
                    "family codex exited 1 with no output; stderr tail: "
                    "an unrecognizable banner")],
                then=[{"error_type": "busy", "resume_at": None,
                       "evidence": "transient"}],
            )
            driver = drv.Driver(path, runner=runner)
            driver.step()
            state = st.load(path)
            # It reached the CLI at all, and as the opposite family.
            self.assertEqual(state["failure"]["type"], "busy")
            classify_calls = [p for p in runner.profiles if p[0] == "claude"]
            self.assertEqual(
                classify_calls, [("claude", "claude-fable-5", "high")]
            )

    def test_classifier_io_is_persisted_and_evidence_recorded(self):
        # An LLM-classified failure must leave an auditable trail: the
        # classifier's prompt+response saved as a raw, plus its verdict in
        # the failure record. Regression: the canon at-capacity strand was
        # unauditable because the classifier's I/O was discarded.
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            cfg = make_config(infra_retry_backoff_s=[],  # no retry sleeps
                              error_classifier=True)     # exercise the LLM
            path = init_state(ws, cfg)
            runner = _FailingRunner(
                [runners.RunnerError(
                    "family codex exited 1 with no output; stderr tail: "
                    "a novel banner patterns do not recognize")],
                then=[{"error_type": "busy", "resume_at": None,
                       "evidence": "opposite family judged it transient"}],
            )
            driver = drv.Driver(path, runner=runner)
            driver.step()
            state = st.load(path)
            self.assertEqual(state["failure"]["type"], "busy")
            self.assertEqual(state["failure"]["classify_evidence"],
                             "opposite family judged it transient")
            raw_dir = os.path.join(ws, ".orchestrator", "raw")
            classify_raws = [f for f in os.listdir(raw_dir) if "classify" in f]
            self.assertTrue(classify_raws, os.listdir(raw_dir))
            with open(os.path.join(raw_dir, classify_raws[0]),
                      encoding="utf-8") as _fh:
                body = _fh.read()
            self.assertIn("CLASSIFIER PROMPT", body)
            self.assertIn("busy", body)  # the classifier's actual reply

    def test_network_blip_retried_in_place_then_succeeds(self):
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            cfg = make_config(infra_retry_backoff_s=[0, 0])
            path = init_state(ws, cfg)
            skeleton = {
                "status": "ok", "kind": "draft_skeleton",
                "artifact": "docs/skeleton.md",
                "slices": [{"id": 1, "title": "core"}],
            }
            runner = _FailingRunner(
                [
                    runners.RunnerError("fetch failed: ECONNRESET"),
                    runners.RunnerError("fetch failed: ECONNRESET"),
                ],
                then=[skeleton],
            )
            # The draft must write its artifact for the wip commit.
            import os as _os
            _os.makedirs(_os.path.join(ws, "docs"), exist_ok=True)
            with open(_os.path.join(ws, "docs", "skeleton.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("# skeleton\n")
            driver = drv.Driver(path, runner=runner)
            driver.step()
            state = st.load(path)
            self.assertIsNone(state["failure"])
            retries = [e for e in state["events"]
                       if e["type"] == "infra_retry"]
            self.assertEqual(
                [e["failure_type"] for e in retries],
                ["network", "network"],
            )
            self.assertEqual(runner.calls, 3)

    def test_network_failure_beyond_retries_is_typed(self):
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            cfg = make_config(infra_retry_backoff_s=[])
            path = init_state(ws, cfg)
            runner = _FailingRunner([
                runners.RunnerError("could not connect: ENOTFOUND api"),
            ])
            driver = drv.Driver(path, runner=runner)
            driver.step()
            state = st.load(path)
            self.assertEqual(state["failure"]["type"], "network")
            self.assertIsNotNone(state["failure"]["resume_at"])


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


class TestProtocolFailureRawOutputs(DriverTestCase):
    def test_raw_texts_saved_on_protocol_violation(self):
        """P3: on WorkerProtocolError the worker's raw output was never
        written to .orchestrator/raw — exactly the case where the operator
        needs to see what the model actually said."""
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                step("draft_skeleton", "utter junk, not JSON at all"),
                step("draft_skeleton", "still prose with no object in sight"),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)

            raw_dir = os.path.join(ws, ".orchestrator", "raw")
            with open(os.path.join(raw_dir, "skeleton-draft-protoerr1.txt"),
                      encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "utter junk, not JSON at all")
            with open(os.path.join(raw_dir, "skeleton-draft-protoerr2.txt"),
                      encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(), "still prose with no object in sight"
                )


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


class TestVerifyFixCapPerStage(DriverTestCase):
    # Fails on invocations 1, 2 (pre-review) and 4 (pre-seal); passes on
    # 3 and 5. Counter lives in the workspace; deterministic because
    # verification runs are strictly sequential.
    VER_CMD = (
        "python3 -c \"import os,sys; p='.orchestrator/vcount'; "
        "n=int(open(p).read()) if os.path.exists(p) else 0; n+=1; "
        "open(p,'w').write(str(n)); sys.exit(0 if n in (3,5) else 1)\""
    )

    def test_pre_review_attempts_do_not_burn_the_pre_seal_cap(self):
        """P3: one shared counter meant a unit that consumed the cap
        pre-review failed on its FIRST pre-seal verification failure with
        a misleading explanation. Counters are per stage now. Under the
        redesign, each verification failure queues the synthetic V1
        finding for a fix_findings episode."""
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(
                ws,
                make_config(
                    verification=[self.VER_CMD],
                    max_verify_fix_attempts=2,
                ),
            )
            mock = runners.MockRunner([
                draft_skeleton_step(),
                # pre-review: two failing episodes = the full stage cap
                step("fix_findings", fix_fixed("V1"), family="codex"),
                step("fix_findings", fix_fixed("V1"), family="codex"),
                step("review_round", clean(), family="codex"),
                step("review_round", clean(), family="claude"),
                # pre-seal: one failing episode of its own
                step("fix_findings", fix_fixed("V1"), family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            # With the old cumulative counter the run FAILED at the first
            # pre-seal verification failure (3 > 2) before ever sealing.
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_SEALED
            )
            self.assertEqual(mock.script, [])

            state = st.load(path)
            self.assertIsNone(state["failure"])
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_SEALED)
            # Each stage's counter reset when its verification passed.
            self.assertEqual(
                unit["verify_fix_attempts"],
                {"pre_review": 0, "pre_seal": 0},
            )
            # Every fix episode cites its own synthetic verification source.
            fixes = [r for r in unit["rounds"] if r["kind"] == "fix_findings"]
            self.assertEqual(
                [r["source_round_id"] for r in fixes],
                [
                    "skeleton-verify-pre_review-1",
                    "skeleton-verify-pre_review-2",
                    "skeleton-verify-pre_seal-1",
                ],
            )
            failed = [
                e for e in state["events"]
                if e["type"] == "verification" and not e["ok"]
            ]
            self.assertEqual(
                [e["stage"] for e in failed],
                [st.U_PRE_REVIEW_VERIFY, st.U_PRE_REVIEW_VERIFY,
                 st.U_PRE_SEAL_VERIFY],
            )
            # Raw fix outputs kept distinct monotonic names.
            raw_dir = os.path.join(ws, ".orchestrator", "raw")
            for name in ("skeleton-fix1.txt", "skeleton-fix2.txt",
                         "skeleton-fix3.txt"):
                self.assertIn(name, os.listdir(raw_dir))


class TestSkeletonSlicePlanUpdate(DriverTestCase):
    def test_skeleton_fix_round_updates_structural_plan(self):
        """P3: the slice plan was frozen from the pre-review draft JSON.
        Under the redesign the reviewer only REPORTS the gap; the fixer
        (which has edit permissions on the skeleton document) reports the
        updated plan and the structural unit plan follows it."""
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            new_plan = [
                {"id": 1, "title": "core"},
                {"id": 2, "title": "follow-up"},
            ]
            mock = runners.MockRunner([
                draft_skeleton_step(slices=[{"id": 1, "title": "core"}]),
                step(
                    "review_round",
                    reported("review_round",
                             "slice plan missed the follow-up work"),
                    family="codex",
                ),
                step(
                    "fix_findings",
                    fix_fixed("F1", slices=new_plan),
                    family="codex",
                ),
                step("review_round", clean(), family="codex"),
                step("review_round", clean(), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_SEALED
            )
            self.assertEqual(mock.script, [])
            state = st.load(path)
            self.assertEqual(state["milestone"]["slices"], new_plan)
            updates = [
                e for e in state["events"] if e["type"] == "slices_updated"
            ]
            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0]["slices"], new_plan)
            # The structural plan drives unit creation for BOTH slices.
            self.assertEqual(
                st.planned_units(state),
                [
                    (st.UNIT_SKELETON, None),
                    (st.UNIT_SLICE_DOC, 1),
                    (st.UNIT_SLICE_IMPL, 1),
                    (st.UNIT_SLICE_DOC, 2),
                    (st.UNIT_SLICE_IMPL, 2),
                ],
            )


class TestConcurrentInvocationRefused(DriverTestCase):
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


class TestDuplicateSliceIdsEndToEnd(DriverTestCase):
    def test_duplicate_slice_ids_fail_the_run_not_the_plan(self):
        """P1: a contract-valid skeleton with duplicate slice ids used to
        collapse the unit plan and close the milestone with a slice
        silently dropped. The contract now rejects it; a worker that
        insists twice fails the run with the explanation recorded."""
        dup = ok(
            "draft_skeleton",
            artifact="docs/skeleton.md",
            slices=[
                {"id": 1, "title": "core"},
                {"id": 1, "title": "totally different second slice"},
            ],
        )
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                step("draft_skeleton", dup),
                step("draft_skeleton", dup),  # repair retry, same junk
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            state = st.load(path)
            self.assertIn("duplicate slice id", state["failure"]["reason"])
            self.assertEqual(state["milestone"]["slices"], [])
            self.assertNotEqual(state["milestone"]["status"], st.M_CLOSED)


if __name__ == "__main__":
    unittest.main()
