"""Regression tests for the adversarial-review fixes.

Covers, per finding:
- invalidated seal attempts re-verify before the next attempt (the
  tampering delta can never be double-sealed unverified);
- concurrent seal never passes with a crashed/missing half, and failure
  recording happens exactly once, from the main thread;
- milestone_closed is recorded exactly once, and re-running a finished
  state appends nothing;
- worker protocol failures persist the raw outputs of both attempts;
- tool-cache writes by read-only seal halves do not invalidate the half
  (defaults + snapshot_exclude_dirs config);
- verify-fix attempt caps are per verification stage;
- skeleton fix rounds can update the structural slice plan;
- a second driver invocation is refused before any worker call runs
  (staleness check + advisory lock).

All workspaces are tempfile.TemporaryDirectory(); nothing touches the repo.
"""

import json
import os
import tempfile
import unittest

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st
from orchestrator.tests.test_driver_mock import (
    DriverTestCase,
    clean,
    fixed,
    init_state,
    make_config,
    ok,
    skeleton_script,
    doc_script,
    impl_script,
    step,
)


class FamilyRunner(object):
    """Thread-safe scripted runner keyed by (family, kind).

    MockRunner consumes an ordered script, which is racy under the
    concurrent seal (both halves pop the same queue in nondeterministic
    order); this runner is stateless per call and safe for threads.
    """

    def __init__(self, responses, exceptions=None):
        self.responses = dict(responses)
        self.exceptions = dict(exceptions or {})
        self.calls = []

    def call(self, family, prompt, workspace):
        kind = runners.prompt_kind(prompt)
        self.calls.append((family, kind))
        key = (family, kind)
        if key in self.exceptions:
            raise self.exceptions[key]
        resp = self.responses[key]
        text = resp if isinstance(resp, str) else json.dumps(resp)
        return runners.RunnerResult(text, 0, 0.01)


def concurrent_responses(codex_half, claude_half):
    """Responses for a full skeleton unit under seal_concurrent."""
    return {
        ("codex", "draft_skeleton"): ok(
            "draft_skeleton",
            artifact="docs/skeleton.md",
            slices=[{"id": 1, "title": "core"}],
        ),
        ("codex", "review_round"): clean(),
        ("claude", "review_round"): clean(),
        ("codex", "seal_half"): codex_half,
        ("claude", "seal_half"): claude_half,
    }


class TestInvalidatedSealReverifies(DriverTestCase):
    def test_tampered_workspace_must_repass_verification(self):
        """P1: an invalidated attempt used to stay in U_SEALING and the
        next attempt double-sealed the tampered content with zero
        verification of the delta. Now the unit returns to pre-seal
        verification, so a tampering delta that breaks verification can
        never be sealed."""

        def tamper(workspace):
            with open(os.path.join(workspace, "tampered.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write("never reviewed\n")

        def untamper(workspace):
            os.remove(os.path.join(workspace, "tampered.txt"))

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(
                ws, make_config(verification=["test ! -f tampered.txt"])
            )
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step("review_round", clean(), family="codex"),
                step("review_round", clean(), family="claude"),
                # attempt 1: codex half reports clean but tampers
                step("seal_half", ok("seal_half", findings=[]),
                     family="codex", side_effect=tamper),
                step("seal_half", ok("seal_half", findings=[]),
                     family="claude"),
                # re-verification FAILS on the tampered file -> fix call
                step("fix_verification",
                     fixed("fix_verification", "removed tampering artifact"),
                     family="codex", side_effect=untamper),
                # attempt 2: genuinely clean
                step("seal_half", ok("seal_half", findings=[]),
                     family="codex"),
                step("seal_half", ok("seal_half", findings=[]),
                     family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_SEALED
            )
            self.assertEqual(mock.script, [])

            state = st.load(path)
            unit = state["units"][0]
            a1, a2 = unit["seals"]
            self.assertIsNotNone(a1["invalidated"])
            self.assertTrue(a2["passed"])
            # The tampering delta was caught by verification and fixed.
            self.assertIn(
                "fix_verification", [r["kind"] for r in unit["rounds"]]
            )
            self.assertFalse(os.path.exists(os.path.join(ws, "tampered.txt")))
            failed_verifs = [
                e for e in state["events"]
                if e["type"] == "verification" and not e["ok"]
            ]
            self.assertEqual(len(failed_verifs), 1)
            self.assertEqual(failed_verifs[0]["stage"], st.U_PRE_SEAL_VERIFY)


class TestConcurrentSeal(DriverTestCase):
    def test_happy_path_records_both_halves(self):
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config(seal_concurrent=True))
            runner = FamilyRunner(concurrent_responses(
                ok("seal_half", findings=[]), ok("seal_half", findings=[]),
            ))
            driver = drv.Driver(path, runner=runner)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_SEALED
            )
            state = st.load(path)
            seal = state["units"][0]["seals"][0]
            self.assertTrue(seal["passed"])
            self.assertEqual(set(seal["halves"].keys()), {"codex", "claude"})

    def test_crashed_half_fails_run_instead_of_sealing(self):
        """P1: a worker thread dying on a non-StopStep exception used to
        leave halves incomplete and all() over the survivors sealed the
        unit on one half (or zero). Now any crashed half fails the run."""
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config(seal_concurrent=True))
            runner = FamilyRunner(
                concurrent_responses(
                    ok("seal_half", findings=[]),
                    ok("seal_half", findings=[]),
                ),
                exceptions={
                    ("claude", "seal_half"): RuntimeError("boom-claude"),
                },
            )
            driver = drv.Driver(path, runner=runner)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)

            state = st.load(path)
            self.assertIsNotNone(state["failure"])
            self.assertIn("crashed", state["failure"]["reason"])
            self.assertIn("boom-claude", state["failure"]["reason"])
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_FAILED)
            self.assertEqual(unit["seals"], [],
                             "no seal attempt may be recorded from a "
                             "partial set of halves")
            run_failed = [
                e for e in state["events"] if e["type"] == "run_failed"
            ]
            self.assertEqual(len(run_failed), 1)

    def test_both_halves_blocked_records_failure_exactly_once(self):
        """P2: both halves failing used to fail_run+save from both worker
        threads: duplicate run_failed events, clashing seqs, one reason
        overwriting the other. Now the main thread records once, with
        both reasons."""
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config(seal_concurrent=True))
            runner = FamilyRunner(concurrent_responses(
                {"status": "blocked", "kind": "seal_half",
                 "blocked_reason": "blocked-codex"},
                {"status": "blocked", "kind": "seal_half",
                 "blocked_reason": "blocked-claude"},
            ))
            driver = drv.Driver(path, runner=runner)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)

            state = st.load(path)
            reason = state["failure"]["reason"]
            self.assertIn("blocked-codex", reason)
            self.assertIn("blocked-claude", reason)
            run_failed = [
                e for e in state["events"] if e["type"] == "run_failed"
            ]
            self.assertEqual(len(run_failed), 1)
            # Event history is single-writer: seqs are exactly 0..n-1.
            self.assertEqual(
                [e["seq"] for e in state["events"]],
                list(range(len(state["events"]))),
            )


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
    def _drive_seal_with_side_effect(self, ws, config, side_effect):
        path = init_state(ws, config)
        mock = runners.MockRunner([
            skeleton_script()[0],  # draft ok
            step("review_round", clean(), family="codex"),
            step("review_round", clean(), family="claude"),
            step("seal_half", ok("seal_half", findings=[]),
                 family="codex", side_effect=side_effect),
            step("seal_half", ok("seal_half", findings=[]), family="claude"),
        ])
        driver = drv.Driver(path, runner=mock)
        self.step_until(
            driver, lambda s: s["units"][0]["status"] == st.U_SEALED
        )
        self.assertEqual(mock.script, [])
        return st.load(path)

    def test_pytest_cache_write_does_not_invalidate_half(self):
        """P2: a read-only seal half is told to base claims on test runs;
        the pytest cache it writes must not burn a seal attempt."""
        def write_cache(workspace):
            d = os.path.join(workspace, ".pytest_cache", "v", "cache")
            os.makedirs(d)
            with open(os.path.join(d, "lastfailed"), "w",
                      encoding="utf-8") as fh:
                fh.write("{}")

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            state = self._drive_seal_with_side_effect(
                ws, make_config(), write_cache
            )
            seal = state["units"][0]["seals"][0]
            self.assertTrue(seal["passed"])
            self.assertIsNone(seal["invalidated"])
            self.assertFalse(seal["halves"]["codex"]["workspace_modified"])

    def test_snapshot_exclude_dirs_config_is_honored(self):
        def write_custom_cache(workspace):
            d = os.path.join(workspace, ".mytool_cache")
            os.makedirs(d)
            with open(os.path.join(d, "data"), "w", encoding="utf-8") as fh:
                fh.write("cache")

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            state = self._drive_seal_with_side_effect(
                ws,
                make_config(snapshot_exclude_dirs=[".mytool_cache"]),
                write_custom_cache,
            )
            seal = state["units"][0]["seals"][0]
            self.assertTrue(seal["passed"])
            self.assertIsNone(seal["invalidated"])


class TestVerifyFixCapPerStage(DriverTestCase):
    def test_pre_review_attempts_do_not_burn_the_pre_seal_cap(self):
        """P3: one shared counter meant a unit that consumed the cap
        pre-review failed on its FIRST pre-seal verification failure with
        a misleading explanation. Counters are per stage now."""
        marker = "ok_marker"

        def create_marker(workspace):
            with open(os.path.join(workspace, marker), "w",
                      encoding="utf-8") as fh:
                fh.write("ok")

        def remove_marker(workspace):
            os.remove(os.path.join(workspace, marker))

        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(
                ws,
                make_config(
                    verification=["test -f %s" % marker],
                    max_verify_fix_attempts=2,
                ),
            )
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft; no marker yet
                # pre-review: two failing episodes = the full stage cap
                step("fix_verification",
                     fixed("fix_verification", "no fix yet"), family="codex"),
                step("fix_verification",
                     fixed("fix_verification", "created marker"),
                     family="codex", side_effect=create_marker),
                step("review_round", clean(), family="codex"),
                # claude round removes the marker: pre-seal verify fails
                step("review_round", clean(), family="claude",
                     side_effect=remove_marker),
                step("fix_verification",
                     fixed("fix_verification", "recreated marker"),
                     family="codex", side_effect=create_marker),
                step("seal_half", ok("seal_half", findings=[]),
                     family="codex"),
                step("seal_half", ok("seal_half", findings=[]),
                     family="claude"),
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
            # Raw fix outputs kept distinct monotonic names.
            raw_dir = os.path.join(ws, ".orchestrator", "raw")
            for name in ("skeleton-vfix1.txt", "skeleton-vfix2.txt",
                         "skeleton-vfix3.txt"):
                self.assertIn(name, os.listdir(raw_dir))


class TestSkeletonSlicePlanUpdate(DriverTestCase):
    def test_skeleton_fix_round_updates_structural_plan(self):
        """P3: the slice plan was frozen from the pre-review draft JSON;
        a review round that rewrites the skeleton's slice table can now
        report the updated plan and the unit plan follows it."""
        with tempfile.TemporaryDirectory(prefix="orch-fix-") as ws:
            path = init_state(ws, make_config())
            new_plan = [
                {"id": 1, "title": "core"},
                {"id": 2, "title": "follow-up"},
            ]
            mock = runners.MockRunner([
                step(
                    "draft_skeleton",
                    ok(
                        "draft_skeleton",
                        artifact="docs/skeleton.md",
                        slices=[{"id": 1, "title": "core"}],
                    ),
                    family="codex",
                ),
                step(
                    "review_round",
                    ok(
                        "review_round",
                        findings=[{
                            "id": "F1",
                            "severity": "P2",
                            "summary": "slice plan missed the follow-up work",
                            "disposition": "fixed",
                            "consultation": None,
                        }],
                        files_changed=["docs/skeleton.md"],
                        slices=new_plan,
                    ),
                    family="codex",
                ),
                step("review_round", clean(), family="codex"),
                step("review_round", clean(), family="claude"),
                step("seal_half", ok("seal_half", findings=[]),
                     family="codex"),
                step("seal_half", ok("seal_half", findings=[]),
                     family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_SEALED
            )
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
                path, runner=runners.MockRunner([skeleton_script()[0]])
            )
            driver_b = drv.Driver(
                path, runner=runners.MockRunner([skeleton_script()[0]])
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
                path, runner=runners.MockRunner([skeleton_script()[0]])
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
