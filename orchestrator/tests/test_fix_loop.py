"""Fix-loop mechanics of the reviewer/fixer separation model, via
runners.MockRunner with real file writes in tempdir git workspaces
(replaces the obsolete micro-review tests; shared harness lives in
test_driver_mock).

Covers here:
  (b) dirty review -> fixer -> dirty delta -> fixer again (SAME episode)
      -> green delta -> amend -> same family reviews next; family advance
      only on clean rounds;
  (c) fix-loop cap -> run failed with the 'fix episode' explanation;
  (d) verification failure -> synthetic V1 queued -> fixer -> delta green
      -> amend -> re-verify green; and the per-stage episode cap path;
  (f) review-round tampering: output discarded, workspace restored,
      invalidated round recorded, retried; the cap includes it;
  (g) delta-review tampering -> run fails 'entangled';
  (j) adjudication circuit end to end: rejection with consultation +
      prevention -> registry entry -> a valid `contests` re-raise reaches
      the fixer with the contests visible in the prompt;
  (k) acts resolution: "opposite" / literal / "self" fixer and delta
      families, asserted through the families MockRunner saw.

All git activity happens inside tempfile.TemporaryDirectory workspaces —
NEVER against the canon repository.
"""

import os
import tempfile
import unittest

from orchestrator import driver as drv
from orchestrator import runners
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    DriverTestCase,
    append_file,
    finding,
    fix_ok,
    init_state,
    make_config,
    ok,
    report,
    skeleton_script,
    step,
    triaged,
    write_file,
)


def draft_step():
    """A skeleton draft that writes a real file (wip commit content)."""
    return skeleton_script()[0]


# ---------------------------------------------------------------------------
# (b) delta-dirty loops inside one episode; family advance discipline


class TestFixLoopSameEpisode(DriverTestCase):
    def test_dirty_delta_loops_back_to_fixer_then_same_family_reviews(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "header misstates the goal")]),
                     family="codex"),
                step("fix_findings",
                     fix_ok([triaged("F1", "fixed",
                                     "header misstates the goal")],
                            files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\nGoal restated.\n")),
                # Delta review 1: DIRTY — the fix itself has a defect.
                step("delta_review",
                     report("delta_review",
                            [finding("D1", "the restated goal drops the "
                                     "tests requirement", severity="P2")]),
                     family="codex"),
                # Same episode: the fixer gets EXACTLY the delta findings.
                step("fix_findings",
                     fix_ok([triaged("D1", "fixed",
                                     "the restated goal drops the tests "
                                     "requirement", severity="P2")],
                            files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\n(with unit tests)\n")),
                step("delta_review", report("delta_review"), family="codex"),
                # Back to ROUNDS with the SAME family (codex never went clean).
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])

            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_SEALED)

            # Exact round sequence: one episode with two fixer+delta loops.
            self.assertEqual(
                [(r["id"], r["kind"]) for r in unit["rounds"]],
                [
                    ("skeleton-codex-r1", "review_round"),
                    ("skeleton-codex-r2", "fix_findings"),
                    ("skeleton-codex-r3", "delta_review"),
                    ("skeleton-codex-r4", "fix_findings"),
                    ("skeleton-codex-r5", "delta_review"),
                    ("skeleton-codex-r6", "review_round"),
                    ("skeleton-claude-r1", "review_round"),
                ],
            )
            fixes = [r for r in unit["rounds"] if r["kind"] == "fix_findings"]
            self.assertEqual(fixes[0]["source_round_id"], "skeleton-codex-r1")
            # The second fixer call was re-sourced to the dirty delta.
            self.assertEqual(fixes[1]["source_round_id"], "skeleton-codex-r3")
            self.assertEqual(
                [f["id"] for f in fixes[1]["result"]["findings"]], ["D1"])
            # Same episode: the loop counter reached 2 and only ONE episode
            # was ever opened from rounds.
            self.assertEqual(unit["fix_loop_rounds"], 2)
            transitions = [
                (e["from_status"], e["to_status"])
                for e in state["events"]
                if e["type"] == "unit_transition" and e["unit"] == "skeleton"
            ]
            self.assertEqual(
                transitions.count((st.U_ROUNDS, st.U_FIXING)), 1)
            self.assertEqual(
                transitions.count((st.U_DELTA_REVIEW, st.U_FIXING)), 1)
            self.assertEqual(
                transitions.count((st.U_FIXING, st.U_DELTA_REVIEW)), 2)
            self.assertEqual(
                transitions.count((st.U_DELTA_REVIEW, st.U_ROUNDS)), 1)
            # One green episode => exactly one amend.
            self.assertEqual(
                len([e for e in state["events"] if e["type"] == "amended"]), 1)

            # The review round AFTER the episode ran with the same family
            # (codex); family advance happened only on the clean rounds.
            review_families = [
                c[0] for c in mock.calls if c[1] == "review_round"
            ]
            self.assertEqual(review_families, ["codex", "codex", "claude"])
            family_clean = [e for e in state["events"]
                            if e["type"] == "family_clean"]
            self.assertEqual([e["next_family"] for e in family_clean],
                             ["claude"])
            # The second fixer prompt queued the delta finding.
            fix_prompts = [c[2] for c in mock.calls if c[1] == "fix_findings"]
            self.assertIn("D1", fix_prompts[1])
            self.assertIn("drops the tests requirement", fix_prompts[1])


# ---------------------------------------------------------------------------
# (c) fix-loop cap


class TestFixLoopCap(DriverTestCase):
    def test_non_converging_episode_hits_max_fix_loops(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(max_fix_loops=1))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "header misstates the goal")]),
                     family="codex"),
                step("fix_findings",
                     fix_ok([triaged("F1", "fixed",
                                     "header misstates the goal")],
                            files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\nGoal restated.\n")),
                step("delta_review",
                     report("delta_review",
                            [finding("D1", "still wrong", severity="P2")]),
                     family="codex"),
                # cap check fails BEFORE another fixer call is made
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            self.assert_failed(
                path, driver,
                ["fix episode", "did not converge after 1 fixer+delta loops",
                 "source: delta"],
                unit_key="skeleton",
            )


# ---------------------------------------------------------------------------
# (d) verification failure episodes


class TestVerificationFixEpisode(DriverTestCase):
    def test_synthetic_v1_fix_delta_amend_reverify_green(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(
                ws, make_config(verification=["test -f marker.txt"]))
            mock = runners.MockRunner([
                draft_step(),
                step("fix_findings",
                     fix_ok([triaged("V1", "fixed",
                                     "the verification suite failed",
                                     severity="P1")],
                            files_changed=["marker.txt"]),
                     family="codex",
                     side_effect=write_file("marker.txt", "repaired\n")),
                step("delta_review", report("delta_review"), family="codex"),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)

            driver.step()  # draft
            driver.step()  # pre-review verification fails
            unit = driver.state["units"][0]
            self.assertEqual(unit["status"], st.U_FIXING)
            self.assertEqual(len(unit["fix_queue"]), 1)
            v1 = unit["fix_queue"][0]
            self.assertEqual((v1["id"], v1["severity"]), ("V1", "P1"))
            self.assertIn("verification suite failed", v1["summary"])
            self.assertEqual(unit["fix_source"]["type"], "verification")
            self.assertIsNone(unit["fix_source"]["family"])
            self.assertEqual(unit["fix_source"]["source_round_id"],
                             "skeleton-verify-pre_review-1")
            self.assertEqual(unit["fix_source"]["return_to"],
                             st.U_PRE_REVIEW_VERIFY)

            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])

            # The fixer prompt carried the failing suite output.
            fix_prompt = [c[2] for c in mock.calls
                          if c[1] == "fix_findings"][0]
            self.assertIn("VERIFICATION OUTPUT", fix_prompt)
            self.assertIn("test -f marker.txt", fix_prompt)

            state = st.load(path)
            unit = state["units"][0]
            # Episode closed: counter reset when the stage passed.
            self.assertEqual(unit["verify_fix_attempts"],
                             {"pre_review": 0, "pre_seal": 0})
            self.assertEqual(
                [r["kind"] for r in unit["rounds"]],
                ["fix_findings", "delta_review", "review_round",
                 "review_round"],
            )
            # Order: verify FAIL -> fix -> delta -> amend -> verify OK.
            events = state["events"]

            def index_of(pred):
                for i, e in enumerate(events):
                    if pred(e):
                        return i
                self.fail("event not found")

            i_fail = index_of(lambda e: e["type"] == "verification"
                              and not e["ok"])
            i_fix = index_of(lambda e: e["type"] == "round_recorded"
                             and e["kind"] == "fix_findings")
            i_delta = index_of(lambda e: e["type"] == "round_recorded"
                               and e["kind"] == "delta_review")
            i_amend = index_of(lambda e: e["type"] == "amended")
            i_ok = index_of(lambda e: e["type"] == "verification"
                            and e["ok"] and e["stage"] == st.U_PRE_REVIEW_VERIFY
                            and events.index(e) > i_fail)
            self.assertLess(i_fail, i_fix)
            self.assertLess(i_fix, i_delta)
            self.assertLess(i_delta, i_amend)
            self.assertLess(i_amend, i_ok)

    def test_verification_episode_cap_is_per_stage(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(
                ws,
                make_config(verification=["false"],
                            max_verify_fix_attempts=1),
            )
            mock = runners.MockRunner([
                draft_step(),
                # The fixer makes a real but INEFFECTIVE edit (the suite is
                # `false`, it can never pass): the episode goes green and
                # returns to the stage, which fails again — over the cap.
                # (A fixer claiming 'fixed' while editing NOTHING is now a
                # structural violation of its own; see
                # test_adversarial_fixes.TestPhantomFixEmptyDelta.)
                step("fix_findings",
                     fix_ok([triaged("V1", "fixed",
                                     "the verification suite failed",
                                     severity="P1")],
                            files_changed=["attempted_fix.txt"]),
                     family="codex",
                     side_effect=write_file("attempted_fix.txt",
                                            "did not help\n")),
                step("delta_review", report("delta_review"), family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            self.assert_failed(
                path, driver,
                ["pre-review verification still failing after 1 fix attempts"],
                unit_key="skeleton",
            )
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(unit["verify_fix_attempts"]["pre_review"], 2)
            self.assertEqual([r["kind"] for r in unit["rounds"]],
                             ["fix_findings", "delta_review"])
            fails = [e for e in state["events"]
                     if e["type"] == "verification" and not e["ok"]]
            self.assertEqual(len(fails), 2)


# ---------------------------------------------------------------------------
# (f) review-round tampering


class TestReviewRoundTampering(DriverTestCase):
    def test_tampering_reviewer_output_discarded_restored_and_retried(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                draft_step(),
                # Reports a finding AND edits the workspace: the entire
                # output must be discarded, not queued for fixing.
                step("review_round",
                     report("review_round",
                            [finding("F1", "a finding that must be "
                                     "discarded with the tampered output")]),
                     family="codex",
                     side_effect=write_file("evil.txt", "reviewer edit\n")),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])

            # Restored: the reviewer's edit is gone.
            self.assertFalse(os.path.exists(os.path.join(ws, "evil.txt")))

            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(
                [(r["id"], r["kind"]) for r in unit["rounds"]],
                [
                    ("skeleton-codex-r1", "review_round"),
                    ("skeleton-codex-r2", "review_round"),
                    ("skeleton-claude-r1", "review_round"),
                ],
            )
            invalidated = unit["rounds"][0]
            self.assertIn("reviewer modified the workspace",
                          invalidated["invalidated"])
            # The reported finding was discarded along with the output.
            self.assertEqual(invalidated["result"]["findings"], [])
            self.assertNotIn("invalidated", unit["rounds"][1])
            # No fix episode was opened from the tampered round.
            self.assertNotIn(
                "fix_findings", [r["kind"] for r in unit["rounds"]])
            transitions = [
                (e["from_status"], e["to_status"])
                for e in state["events"]
                if e["type"] == "unit_transition" and e["unit"] == "skeleton"
            ]
            self.assertNotIn((st.U_ROUNDS, st.U_FIXING), transitions)

    def test_invalidated_round_counts_toward_family_cap(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(max_rounds_per_family=1))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round", report("review_round"), family="codex",
                     side_effect=write_file("evil.txt", "reviewer edit\n")),
                # cap check fails BEFORE a retry worker call
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            self.assert_failed(
                path, driver,
                ["max_rounds_per_family=1", "codex", "without a clean round"],
                unit_key="skeleton",
            )
            state = st.load(path)
            rounds = state["units"][0]["rounds"]
            self.assertEqual(len(rounds), 1)
            self.assertIn("reviewer modified the workspace",
                          rounds[0]["invalidated"])


    def test_gitignored_churn_does_not_invalidate_review(self):
        # Live-incident regression (LPC N30): claude reviewers ran the
        # project's build/tests as their prompt instructs, .gitignore'd
        # artifacts (_build/) churned, and the walk-based snapshot
        # invalidated round after round — 150 wasted worker-minutes. With
        # git enabled the tamper universe honors .gitignore, so artifact
        # churn is not tampering.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            with open(os.path.join(ws, ".gitignore"), "w",
                      encoding="utf-8") as fh:
                fh.write("_build/\n")
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                draft_step(),
                step("review_round", report("review_round"), family="codex",
                     side_effect=write_file(
                         os.path.join("_build", "app.beam"), "artifact\n")),
                step("review_round", report("review_round"), family="claude",
                     side_effect=write_file(
                         os.path.join("_build", "app.beam"), "recompiled\n")),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            unit = state["units"][0]
            # Both rounds clean, none invalidated, no extra retry rounds.
            self.assertEqual(len(unit["rounds"]), 2)
            for r in unit["rounds"]:
                self.assertNotIn("invalidated", r)
            # The artifact churn survived (nothing restored over it).
            self.assertTrue(
                os.path.exists(os.path.join(ws, "_build", "app.beam")))

    def test_tamper_invalidation_names_the_changed_files(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                draft_step(),
                step("review_round", report("review_round"), family="codex",
                     side_effect=write_file("evil.txt", "reviewer edit\n")),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            state = st.load(path)
            invalidated = state["units"][0]["rounds"][0]["invalidated"]
            self.assertIn("reviewer modified the workspace", invalidated)
            self.assertIn("evil.txt", invalidated)


# ---------------------------------------------------------------------------
# (g) delta-review tampering


class TestDeltaReviewTampering(DriverTestCase):
    def test_delta_reviewer_edit_fails_run_entangled(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "header misstates the goal")]),
                     family="codex"),
                step("fix_findings",
                     fix_ok([triaged("F1", "fixed",
                                     "header misstates the goal")],
                            files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\nGoal restated.\n")),
                step("delta_review", report("delta_review"), family="codex",
                     side_effect=write_file("evil.txt", "delta edit\n")),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            self.assert_failed(
                path, driver,
                ["delta reviewer (codex) modified the workspace",
                 "entangled with the pending fix delta"],
                unit_key="skeleton",
            )
            # No restore: the fixer's pending work and the tampering are
            # left in place for the operator.
            self.assertTrue(os.path.exists(os.path.join(ws, "evil.txt")))
            with open(os.path.join(ws, "docs", "skeleton.md"),
                      encoding="utf-8") as fh:
                self.assertIn("Goal restated.", fh.read())


# ---------------------------------------------------------------------------
# (j) adjudication circuit end to end


class TestAdjudicationCircuit(DriverTestCase):
    REJECTION_ID = "skeleton-claude-r1/F1"
    NEW_EVIDENCE = "the CLI parser rejects float literals"

    def test_rejection_registry_and_valid_contests_reach_the_fixer(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round",
                     report("review_round",
                            [finding("F1", "goal wording is ambiguous about "
                                     "float support")]),
                     family="claude"),
                # Reject: consultation + prevention edit.
                step("fix_findings",
                     fix_ok([triaged(
                         "F1", "rejected",
                         "goal wording is ambiguous about float support",
                         consultation={"resolution": "opposite family agreed "
                                       "the goal was already float-typed"},
                         prevention={"documented_in": "docs/skeleton.md",
                                     "note": "explicit float note added"},
                     )], files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\nNote: floats supported.\n")),
                step("delta_review", report("delta_review"), family="codex"),
                # A later round re-raises WITH the registry id and genuinely
                # new evidence: passes validation, reaches the fixer.
                step("review_round",
                     report("review_round", [finding(
                         "F2", "float support broken in the parser",
                         severity="P2",
                         contests={"rejection_id": self.REJECTION_ID,
                                   "new_evidence": self.NEW_EVIDENCE})]),
                     family="claude"),
                step("fix_findings",
                     fix_ok([triaged("F2", "fixed",
                                     "float support broken in the parser",
                                     severity="P2")],
                            files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\nParser fixed for floats.\n")),
                step("delta_review", report("delta_review"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])

            state = st.load(path)
            # The fixer CONCEDED the contested finding ('fixed'), so the
            # contested adjudication is OVERTURNED: it left the registry
            # and can no longer be cited in adjudication_ref (a later
            # fixer must not be able to kill a genuine recurrence by
            # pointer with the overturned rationale).
            self.assertEqual(st.registry_ids(state), set())
            self.assertEqual(st.adjudicated_rejections(state), [])

            # Between the rejection and the concession the registry DID
            # hold the entry: the contesting review saw it in its prompt.
            claude_reviews = [c[2] for c in mock.calls
                              if c[0] == "claude" and c[1] == "review_round"]
            self.assertEqual(len(claude_reviews), 3)
            self.assertIn("(none so far in this milestone)", claude_reviews[0])
            self.assertIn("- [%s]" % self.REJECTION_ID, claude_reviews[1])
            self.assertIn("[documented in docs/skeleton.md]",
                          claude_reviews[1])
            # The review AFTER the concession no longer sees settled law.
            self.assertIn("(none so far in this milestone)", claude_reviews[2])

            # The contesting finding reached the fixer with the contests
            # visible in the prompt.
            fix_prompts = [c[2] for c in mock.calls
                           if c[1] == "fix_findings"]
            self.assertEqual(len(fix_prompts), 2)
            self.assertIn(
                "[CONTESTS %s with new evidence: %s]"
                % (self.REJECTION_ID, self.NEW_EVIDENCE),
                fix_prompts[1],
            )

            # The gate ledger reflects the overturn: the conceded
            # adjudication is no longer committed as settled law.
            with open(os.path.join(ws, "docs", "adjudications.md"),
                      encoding="utf-8") as fh:
                adjudications = fh.read()
            self.assertNotIn("[%s]" % self.REJECTION_ID, adjudications)
            self.assertIn("(none)", adjudications)


# ---------------------------------------------------------------------------
# (k) acts resolution


class TestActsResolution(DriverTestCase):
    def _run_skeleton(self, ws, acts, script_tail):
        path = init_state(ws, make_config(acts=acts))
        mock = runners.MockRunner([draft_step()] + script_tail)
        driver = drv.Driver(path, runner=mock)
        self.step_until(driver,
                        lambda s: s["units"][0]["status"] == st.U_SEALED)
        self.assertEqual(mock.script, [])
        return mock

    def test_delta_uses_fixer_family_and_its_review_profile(self):
        acts = {
            "fixer": "opposite",
            # A legacy frozen value must not decouple delta from the fixer.
            "delta_review": "opposite",
            "review_codex": {"model": "gpt-5.6-sol", "effort": "high"},
            "review_claude": {
                "model": "claude-fable-5", "effort": "medium",
            },
            "consultation": "self",
        }
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            mock = self._run_skeleton(ws, acts, [
                step("review_round",
                     report("review_round", [finding("F1", "codex-found")]),
                     family="codex"),
                # origin codex -> fixer claude -> Claude Review profile
                step("fix_findings",
                     fix_ok([triaged("F1", "fixed", "codex-found")],
                            files_changed=["docs/skeleton.md"]),
                     family="claude",
                     side_effect=append_file("docs/skeleton.md", "\nfix1\n")),
                step("delta_review", report("delta_review"), family="claude"),
                step("review_round", report("review_round"), family="codex"),
                step("review_round",
                     report("review_round", [finding("F2", "claude-found")]),
                     family="claude"),
                # origin claude -> fixer codex -> Codex Review profile
                step("fix_findings",
                     fix_ok([triaged("F2", "fixed", "claude-found")],
                            files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md", "\nfix2\n")),
                step("delta_review", report("delta_review"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            fix_delta_calls = [(c[1], c[0]) for c in mock.calls
                               if c[1] in ("fix_findings", "delta_review")]
            self.assertEqual(
                fix_delta_calls,
                [("fix_findings", "claude"), ("delta_review", "claude"),
                 ("fix_findings", "codex"), ("delta_review", "codex")],
            )
            delta_meta = [
                meta for call, meta in zip(mock.calls, mock.call_meta)
                if call[1] == "delta_review"
            ]
            self.assertEqual(
                [(m["model"], m["effort"]) for m in delta_meta],
                [("claude-fable-5", "medium"),
                 ("gpt-5.6-sol", "high")],
            )
            # consultation "self" resolves to the fixer's own family.
            fix_prompts = [c[2] for c in mock.calls
                           if c[1] == "fix_findings"]
            self.assertIn("with the claude family", fix_prompts[0])
            self.assertIn("with the codex family", fix_prompts[1])

    def test_literal_fixer_selects_same_family_delta(self):
        acts = {"fixer": "claude", "delta_review": "self",
                "consultation": "opposite"}
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            mock = self._run_skeleton(ws, acts, [
                step("review_round",
                     report("review_round", [finding("F1", "codex-found")]),
                     family="codex"),
                # fixer pinned to claude; delta "self" = the fixer's family
                step("fix_findings",
                     fix_ok([triaged("F1", "fixed", "codex-found")],
                            files_changed=["docs/skeleton.md"]),
                     family="claude",
                     side_effect=append_file("docs/skeleton.md", "\nfix\n")),
                step("delta_review", report("delta_review"), family="claude"),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            fix_delta_calls = [(c[1], c[0]) for c in mock.calls
                               if c[1] in ("fix_findings", "delta_review")]
            self.assertEqual(
                fix_delta_calls,
                [("fix_findings", "claude"), ("delta_review", "claude")],
            )
            # consultation "opposite" of the claude fixer is codex.
            fix_prompt = [c[2] for c in mock.calls
                          if c[1] == "fix_findings"][0]
            self.assertIn("with the codex family", fix_prompt)


if __name__ == "__main__":
    unittest.main()
