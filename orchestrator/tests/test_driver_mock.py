"""Full-lifecycle driver tests via runners.MockRunner (no subprocesses).

Covers: the happy path mirroring the calculator fake-LLM scenario, every
documented failure path (blocked worker, blocked finding disposition, round
cap, seal cap, verify-fix cap, seal-half tampering, protocol violation),
decide() totality after every step, and resume from a state file mid-flow.

One test is EXPECTED TO FAIL against the current source and documents a
genuine bug: a seal_half worker that returns status "blocked" is treated as
a clean half and the unit seals, while README.md ("Blocked -> stop with
explanation") and the seal_half prompt ("the run will stop") promise the run
ends with the explanation recorded. See
TestSealHalfBlocked.test_seal_half_blocked_status_should_fail_run.
"""

import copy
import os
import tempfile
import unittest

from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st

GOAL = "Build a small CLI calculator (add/sub/mul/div) with unit tests"

SEAL_FINDING = {
    "id": "S1",
    "severity": "P3",
    "summary": "workspace lacks a README describing CLI usage",
}


def make_config(**overrides):
    """Minimal frozen config; commands are never spawned (MockRunner)."""
    cfg = {
        "families_order": ["codex", "claude"],
        "fix_family": None,
        "commands": {"codex": ["fake-codex"], "claude": ["fake-claude"]},
        "timeouts": {},
        "verification": [],
        "verification_timeout": 60,
        "max_rounds_per_family": 6,
        "max_seal_attempts": 4,
        "max_verify_fix_attempts": 2,
        "seal_concurrent": False,
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
    return ok(kind, findings=[], files_changed=[])


def fixed(kind, summary, severity="P3"):
    return ok(
        kind,
        findings=[
            {
                "id": "F1",
                "severity": severity,
                "summary": summary,
                "disposition": "fixed",
                "consultation": None,
            }
        ],
        files_changed=[],
    )


def step(kind, response, family=None, side_effect=None):
    s = {"expect_kind": kind, "response": response}
    if family is not None:
        s["expect_family"] = family
    if side_effect is not None:
        s["side_effect"] = side_effect
    return s


def skeleton_script():
    """Mirror of the fake_llm skeleton unit: codex finding then clean,
    claude clean, seal a1 clean on both halves."""
    return [
        step(
            "draft_skeleton",
            ok(
                "draft_skeleton",
                artifact="docs/skeleton.md",
                slices=[{"id": 1, "title": "Calculator core"}],
            ),
            family="codex",
        ),
        step(
            "review_round",
            fixed("review_round", "skeleton lacked explicit non-goals"),
            family="codex",
        ),
        step("review_round", clean(), family="codex"),
        step("review_round", clean(), family="claude"),
        step("seal_half", ok("seal_half", findings=[]), family="codex"),
        step("seal_half", ok("seal_half", findings=[]), family="claude"),
    ]


def doc_script():
    """Mirror of the fake_llm slice-note unit: clean + clean, seal pass."""
    return [
        step(
            "draft_slice_note",
            ok("draft_slice_note", artifact="docs/slice-01.md"),
            family="codex",
        ),
        step("review_round", clean(), family="codex"),
        step("review_round", clean(), family="claude"),
        step("seal_half", ok("seal_half", findings=[]), family="codex"),
        step("seal_half", ok("seal_half", findings=[]), family="claude"),
    ]


def impl_script():
    """Mirror of the fake_llm impl unit minus the verification-failure leg
    (verification is [] here): codex finding then clean, claude clean,
    seal a1 fails on a claude finding, seal_fix, seal a2 passes."""
    return [
        step(
            "implement",
            ok("implement", files_changed=["calculator.py", "test_calculator.py"]),
            family="codex",
        ),
        step(
            "review_round",
            fixed("review_round", "calculator module lacked a docstring"),
            family="codex",
        ),
        step("review_round", clean(), family="codex"),
        step("review_round", clean(), family="claude"),
        step("seal_half", ok("seal_half", findings=[]), family="codex"),
        step("seal_half", ok("seal_half", findings=[SEAL_FINDING]), family="claude"),
        step(
            "seal_fix",
            fixed("seal_fix", SEAL_FINDING["summary"]),
            family="codex",
        ),
        step("seal_half", ok("seal_half", findings=[]), family="codex"),
        step("seal_half", ok("seal_half", findings=[]), family="claude"),
    ]


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


class TestHappyPath(DriverTestCase):
    def test_full_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner(
                skeleton_script() + doc_script() + impl_script()
            )
            driver = drv.Driver(path, runner=mock)
            actions, final = self.drive(driver)

            self.assertEqual(final.type, drv.A_DONE)
            self.assertEqual(mock.script, [], "mock script fully consumed")

            expected_actions = (
                # skeleton
                [drv.A_DRAFT, drv.A_VERIFY]
                + [drv.A_REVIEW_ROUND] * 3
                + [drv.A_VERIFY, drv.A_SEAL_ATTEMPT]
                # slice doc
                + [drv.A_DRAFT, drv.A_VERIFY]
                + [drv.A_REVIEW_ROUND] * 2
                + [drv.A_VERIFY, drv.A_SEAL_ATTEMPT]
                # slice impl
                + [drv.A_DRAFT, drv.A_VERIFY]
                + [drv.A_REVIEW_ROUND] * 3
                + [drv.A_VERIFY, drv.A_SEAL_ATTEMPT]
                + [drv.A_SEAL_FIX, drv.A_VERIFY, drv.A_SEAL_ATTEMPT]
            )
            self.assertEqual([a for a, _ in actions], expected_actions)

            state = st.load(path)  # persisted, not just in-memory
            self.assertEqual(state["milestone"]["status"], st.M_CLOSED)
            self.assertIsNone(state["failure"])
            self.assertEqual(
                state["milestone"]["slices"],
                [{"id": 1, "title": "Calculator core"}],
            )

            # Final unit sequence and statuses.
            self.assertEqual(
                [(u["kind"], u["slice_id"], u["status"]) for u in state["units"]],
                [
                    (st.UNIT_SKELETON, None, st.U_SEALED),
                    (st.UNIT_SLICE_DOC, 1, st.U_SEALED),
                    (st.UNIT_SLICE_IMPL, 1, st.U_SEALED),
                ],
            )
            skeleton, doc, impl = state["units"]
            self.assertEqual(skeleton["artifact"], "docs/skeleton.md")
            self.assertEqual(doc["artifact"], "docs/slice-01.md")
            self.assertIsNone(impl["artifact"])  # implement carries no artifact

            # Rounds bookkeeping.
            self.assertEqual(
                [(r["id"], r["kind"]) for r in skeleton["rounds"]],
                [
                    ("skeleton-codex-r1", "review_round"),
                    ("skeleton-codex-r2", "review_round"),
                    ("skeleton-claude-r1", "review_round"),
                ],
            )
            self.assertEqual(len(skeleton["rounds"][0]["result"]["findings"]), 1)
            self.assertEqual(
                [(r["id"], r["kind"]) for r in impl["rounds"]],
                [
                    ("slice_impl-01-codex-r1", "review_round"),
                    ("slice_impl-01-codex-r2", "review_round"),
                    ("slice_impl-01-claude-r1", "review_round"),
                    ("slice_impl-01-codex-r3", "seal_fix"),
                ],
            )

            # Seal records complete on every unit.
            for unit in state["units"]:
                self.assertTrue(unit["seals"])
                last = unit["seals"][-1]
                self.assertTrue(last["passed"])
                self.assertIsNone(last["invalidated"])
                for seal in unit["seals"]:
                    self.assertEqual(
                        set(seal["halves"].keys()), {"codex", "claude"}
                    )
                    for half in seal["halves"].values():
                        self.assertEqual(
                            set(half.keys()),
                            {"result", "raw_path", "duration_s",
                             "workspace_modified"},
                        )
                        self.assertEqual(half["result"]["kind"], "seal_half")
                        self.assertFalse(half["workspace_modified"])
                        self.assertTrue(
                            os.path.exists(os.path.join(ws, half["raw_path"])),
                            "raw output missing: %s" % half["raw_path"],
                        )

            # Impl unit: a1 failed on the claude finding, a2 passed.
            self.assertEqual(len(impl["seals"]), 2)
            a1, a2 = impl["seals"]
            self.assertEqual((a1["attempt"], a1["passed"], a1["invalidated"]),
                             (1, False, None))
            self.assertEqual(
                len(a1["halves"]["claude"]["result"]["findings"]), 1
            )
            self.assertEqual(
                len(a1["halves"]["codex"]["result"]["findings"]), 0
            )
            self.assertEqual((a2["attempt"], a2["passed"], a2["invalidated"]),
                             (2, True, None))
            self.assertIsNotNone(impl["closed_record"])
            self.assertEqual(impl["closed_record"]["slice_id"], 1)

            # Event ordering sanity.
            events = state["events"]
            self.assertEqual([e["seq"] for e in events],
                             list(range(len(events))))
            types = [e["type"] for e in events]
            self.assertEqual(types[0], "initialized")
            self.assertEqual(types.count("milestone_closed"), 1)
            self.assertEqual(types.count("slice_closed"), 1)
            self.assertLess(types.index("slice_closed"),
                            types.index("milestone_closed"))
            self.assertEqual(
                [e["unit"] for e in events if e["type"] == "unit_opened"],
                ["slice_doc-01", "slice_impl-01"],
            )

            def indices(unit, etype):
                return [
                    i
                    for i, e in enumerate(events)
                    if e["type"] == etype and e.get("unit") == unit
                ]

            for uk in ("skeleton", "slice_doc-01", "slice_impl-01"):
                draft_i = indices(uk, "draft_recorded")
                round_i = indices(uk, "round_recorded")
                seal_i = indices(uk, "seal_attempt")
                self.assertEqual(len(draft_i), 1)
                self.assertLess(draft_i[0], round_i[0])
                self.assertLess(round_i[0], seal_i[0])
            # Impl: the seal_fix round sits between attempt 1 and attempt 2.
            impl_seals = indices("slice_impl-01", "seal_attempt")
            sealfix_round = indices("slice_impl-01", "round_recorded")[-1]
            self.assertEqual(len(impl_seals), 2)
            self.assertLess(impl_seals[0], sealfix_round)
            self.assertLess(sealfix_round, impl_seals[1])


class TestFailurePaths(DriverTestCase):
    def _assert_failed(self, path, driver, reason_substrings, unit_key=None):
        state = st.load(path)
        self.assertIsNotNone(state["failure"])
        for sub in reason_substrings:
            self.assertIn(sub, state["failure"]["reason"])
        self.assertEqual(state["milestone"]["status"], st.M_FAILED)
        if unit_key is not None:
            self.assertEqual(state["failure"]["unit"], unit_key)
            for u in state["units"]:
                if st.unit_key(u) == unit_key:
                    self.assertEqual(u["status"], st.U_FAILED)
                    break
            else:
                self.fail("unit %s not found" % unit_key)
        # run() on a failed state exits 2 without further worker calls.
        self.assertEqual(driver.run(), 2)
        # The explanation is also in the event log.
        run_failed = [e for e in state["events"] if e["type"] == "run_failed"]
        self.assertTrue(run_failed)
        for sub in reason_substrings:
            self.assertIn(sub, run_failed[-1]["reason"])

    def test_worker_blocked_status_fails_run(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                step(
                    "draft_skeleton",
                    {
                        "status": "blocked",
                        "kind": "draft_skeleton",
                        "blocked_reason": "goal is contradictory; need operator",
                    },
                    family="codex",
                ),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self._assert_failed(
                path,
                driver,
                ["draft_skeleton worker blocked",
                 "goal is contradictory; need operator"],
                unit_key="skeleton",
            )

    def test_blocked_disposition_finding_fails_run(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step(
                    "review_round",
                    ok(
                        "review_round",
                        findings=[
                            {
                                "id": "F1",
                                "severity": "P0",
                                "summary": "spec requires both X and not-X",
                                "disposition": "blocked",
                                "consultation": None,
                            }
                        ],
                        files_changed=[],
                    ),
                    family="codex",
                ),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self._assert_failed(
                path,
                driver,
                ["blocked findings", "spec requires both X and not-X"],
                unit_key="skeleton",
            )

    def test_codex_never_clean_hits_round_cap(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(max_rounds_per_family=2))
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step("review_round",
                     fixed("review_round", "defect 1"), family="codex"),
                step("review_round",
                     fixed("review_round", "defect 2"), family="codex"),
                # cap check fails BEFORE a third worker call
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            self.assertEqual(len(state["units"][0]["rounds"]), 2)
            self._assert_failed(
                path,
                driver,
                ["max_rounds_per_family=2", "codex", "without a clean round"],
                unit_key="skeleton",
            )

    def test_seal_findings_forever_hit_seal_cap(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(max_seal_attempts=2))
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step("review_round", clean(), family="codex"),
                step("review_round", clean(), family="claude"),
                # attempt 1: codex half keeps finding the same defect
                step("seal_half",
                     ok("seal_half", findings=[SEAL_FINDING]), family="codex"),
                step("seal_half", ok("seal_half", findings=[]), family="claude"),
                step("seal_fix",
                     fixed("seal_fix", SEAL_FINDING["summary"]), family="codex"),
                # attempt 2: still "finding" it
                step("seal_half",
                     ok("seal_half", findings=[SEAL_FINDING]), family="codex"),
                step("seal_half", ok("seal_half", findings=[]), family="claude"),
                step("seal_fix",
                     fixed("seal_fix", SEAL_FINDING["summary"]), family="codex"),
                # cap check fails BEFORE attempt 3 runs any half
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            seals = state["units"][0]["seals"]
            self.assertEqual(len(seals), 2)
            self.assertFalse(any(s["passed"] for s in seals))
            self._assert_failed(
                path,
                driver,
                ["max_seal_attempts=2", "skeleton"],
                unit_key="skeleton",
            )

    def test_failing_verification_hits_verify_fix_cap(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(
                ws,
                make_config(verification=["exit 1"], max_verify_fix_attempts=1),
            )
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step(
                    "fix_verification",
                    fixed("fix_verification", "claimed a fix, changed nothing"),
                    family="codex",
                ),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(
                [r["kind"] for r in unit["rounds"]], ["fix_verification"]
            )
            # Per-stage counters: both failures were pre-review.
            self.assertEqual(
                unit["verify_fix_attempts"], {"pre_review": 2, "pre_seal": 0}
            )
            failed_verifications = [
                e for e in state["events"]
                if e["type"] == "verification" and not e["ok"]
            ]
            self.assertEqual(len(failed_verifications), 2)
            self._assert_failed(
                path,
                driver,
                ["verification still failing after 1 fix attempts"],
                unit_key="skeleton",
            )

    def test_protocol_violation_junk_twice_fails_run(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                step("draft_skeleton", "utter junk, not JSON at all"),
                step("draft_skeleton", "still prose with no object in sight"),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            # Exactly two calls: original + one repair retry.
            self.assertEqual(len(mock.calls), 2)
            self.assertIn("REPAIR:", mock.calls[1][2])
            self._assert_failed(
                path,
                driver,
                ["draft_skeleton call failed",
                 "contract-violating output twice"],
                unit_key="skeleton",
            )


class TestSealTampering(DriverTestCase):
    def test_tampering_half_invalidates_attempt_then_clean_attempt_seals(self):
        def tamper(workspace):
            with open(os.path.join(workspace, "tampered.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write("sneaky edit during a read-only seal half\n")

        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step("review_round", clean(), family="codex"),
                step("review_round", clean(), family="claude"),
                # attempt 1: codex half reports clean but EDITS the workspace
                step("seal_half", ok("seal_half", findings=[]),
                     family="codex", side_effect=tamper),
                step("seal_half", ok("seal_half", findings=[]),
                     family="claude"),
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
            self.assertEqual(unit["status"], st.U_SEALED)
            self.assertEqual(len(unit["seals"]), 2)

            a1, a2 = unit["seals"]
            # Attempt 1: recorded, invalidated, not passed — despite both
            # halves reporting zero findings.
            self.assertFalse(a1["passed"])
            self.assertIsNotNone(a1["invalidated"])
            self.assertIn("seal half codex modified the workspace",
                          a1["invalidated"])
            self.assertTrue(a1["halves"]["codex"]["workspace_modified"])
            self.assertFalse(a1["halves"]["claude"]["workspace_modified"])
            self.assertEqual(a1["halves"]["codex"]["result"]["findings"], [])

            # No seal_fix happened (invalidation is not the findings path),
            # but the tampered workspace went back through pre-seal
            # verification before attempt 2 was allowed to double-seal it.
            self.assertNotIn(
                "seal_fix", [r["kind"] for r in unit["rounds"]]
            )
            skeleton_transitions = [
                (e["from_status"], e["to_status"])
                for e in state["events"]
                if e["type"] == "unit_transition" and e["unit"] == "skeleton"
            ]
            self.assertNotIn(
                (st.U_SEALING, st.U_SEAL_FIX), skeleton_transitions
            )
            self.assertIn(
                (st.U_SEALING, st.U_PRE_SEAL_VERIFY), skeleton_transitions
            )
            self.assertEqual(
                skeleton_transitions.count((st.U_SEALING, st.U_SEALED)), 1
            )
            # Event order: invalid attempt -> verification -> attempt 2.
            seal_idx = [
                i for i, e in enumerate(state["events"])
                if e["type"] == "seal_attempt"
            ]
            self.assertEqual(len(seal_idx), 2)
            verifs_between = [
                e for e in state["events"][seal_idx[0]:seal_idx[1]]
                if e["type"] == "verification"
                and e["stage"] == st.U_PRE_SEAL_VERIFY
            ]
            self.assertTrue(
                verifs_between,
                "no pre-seal verification ran between the invalidated "
                "attempt and the next one",
            )

            # Attempt 2: clean and passed.
            self.assertTrue(a2["passed"])
            self.assertIsNone(a2["invalidated"])
            self.assertFalse(a2["halves"]["codex"]["workspace_modified"])
            self.assertFalse(a2["halves"]["claude"]["workspace_modified"])


class TestResume(DriverTestCase):
    def test_resume_mid_flow_completes_and_preserves_history(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())

            # Phase 1: run only the skeleton unit, then stop.
            mock1 = runners.MockRunner(skeleton_script())
            driver1 = drv.Driver(path, runner=mock1)
            self.step_until(
                driver1, lambda s: s["units"][0]["status"] == st.U_SEALED
            )
            self.assertEqual(mock1.script, [])

            mid = st.load(path)
            self.assertEqual(mid["milestone"]["status"], st.M_OPEN)
            self.assertEqual(len(mid["units"]), 2)  # skeleton + opened doc
            self.assertEqual(mid["units"][1]["status"], st.U_PENDING)
            events_before = copy.deepcopy(mid["events"])
            skeleton_before = copy.deepcopy(mid["units"][0])

            # Phase 2: a brand-new Driver over the same state file with a
            # fresh MockRunner continuing the script.
            mock2 = runners.MockRunner(doc_script() + impl_script())
            driver2 = drv.Driver(path, runner=mock2)
            _actions, final = self.drive(driver2)
            self.assertEqual(final.type, drv.A_DONE)
            self.assertEqual(mock2.script, [])

            state = st.load(path)
            self.assertEqual(state["milestone"]["status"], st.M_CLOSED)
            self.assertEqual(
                [u["status"] for u in state["units"]],
                [st.U_SEALED, st.U_SEALED, st.U_SEALED],
            )
            # Pre-resume history is intact: events are a strict prefix and
            # the sealed skeleton unit is byte-identical.
            self.assertEqual(
                state["events"][: len(events_before)], events_before
            )
            self.assertGreater(len(state["events"]), len(events_before))
            self.assertEqual(state["units"][0], skeleton_before)


class TestSealHalfBlocked(DriverTestCase):
    def test_seal_half_blocked_status_should_fail_run(self):
        """README.md: '`status: "blocked"` or a `blocked` disposition ends
        the run; the reason is in `state.failure` and the events'. The
        seal_half prompt likewise promises 'the run will stop'. Historically
        _do_seal_attempt never called _check_worker_blocked on half outputs,
        so a blocked half (no findings key) looked CLEAN and the unit sealed
        on it; run_half now checks each half output for blocked status.
        """
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step("review_round", clean(), family="codex"),
                step("review_round", clean(), family="claude"),
                step(
                    "seal_half",
                    {
                        "status": "blocked",
                        "kind": "seal_half",
                        "blocked_reason": "artifact unreadable; cannot review",
                    },
                    family="codex",
                ),
                # Present in case a correct driver still runs the second
                # half before stopping; a correct driver may also leave it
                # unconsumed.
                step("seal_half", ok("seal_half", findings=[]),
                     family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            try:
                _actions, final = self.drive(driver, max_steps=30)
            except AssertionError as exc:
                self.fail(
                    "KNOWN SOURCE BUG: a blocked seal_half was treated as a "
                    "clean half and the unit sealed; the driver went on past "
                    "the seal instead of stopping the run (%s)" % exc
                )
            self.assertEqual(
                final.type,
                drv.A_FAILED,
                "a blocked seal_half must end the run per README",
            )
            state = st.load(path)
            self.assertIsNotNone(state["failure"])
            self.assertIn("blocked", state["failure"]["reason"])
            self.assertIn(
                "artifact unreadable; cannot review",
                state["failure"]["reason"],
            )
            self.assertNotEqual(state["units"][0]["status"], st.U_SEALED)


if __name__ == "__main__":
    unittest.main()
