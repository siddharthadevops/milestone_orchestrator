"""Fix-loop mechanics of the reviewer/fixer separation model, via
runners.MockRunner with real file writes in tempdir git workspaces
(replaces the obsolete micro-review tests; shared harness lives in
test_driver_mock).

Covers here:
  (b) dirty review -> fixer -> dirty delta -> fixer again (SAME episode)
      -> green delta -> amend -> reviews restart from Codex; family advance
      only on clean rounds;
  (c) fix-loop cap -> run failed with the 'fix episode' explanation;
  (d) due implementation verification failure -> full-suite fixer -> delta green -> amend
      -> fresh reviews -> exact fixer result reused without rerunning tests;
  (f) review-round tampering: output discarded, workspace restored,
      invalidated round recorded, retried; the cap includes it;
  (g) delta-review tampering -> run fails 'entangled';
  (j) adjudication circuit end to end: direct rejection + prevention ->
      registry entry -> a valid `contests` re-raise reaches
      the fixer with the contests visible in the prompt;
  (k) acts resolution: "opposite" / literal / "self" fixer and delta
      families, plus the ban on worker-dispatched model calls.

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


def init_final_impl_state(workspace, config):
    """Start directly at the final implementation boundary.

    Verification-fixer tests do not need to replay skeleton and slice-note
    reviews.  Those units are documentation and deliberately run no full
    suite under the current contract.
    """
    path = init_state(workspace, config)
    os.makedirs(os.path.join(workspace, "docs"), exist_ok=True)
    write_file("docs/skeleton.md", "# Skeleton\n")(workspace)
    write_file("docs/slice-01.md", "# Slice 01\n")(workspace)
    state = st.load(path)
    state["milestone"]["slices"] = [{"id": 1, "title": "Core"}]
    skeleton = state["units"][0]
    skeleton["artifact"] = "docs/skeleton.md"
    skeleton["status"] = st.U_SEALED
    note = st.ensure_next_unit(state)
    note["artifact"] = "docs/slice-01.md"
    note["status"] = st.U_SEALED
    st.ensure_next_unit(state)
    st.save(path, state)
    return path


def implement_step():
    return step(
        "implement",
        ok("implement", files_changed=["core.txt"]),
        family="codex",
        side_effect=write_file("core.txt", "implemented\n"),
    )


# ---------------------------------------------------------------------------
# (b) delta-dirty loops inside one episode; family advance discipline


class TestFixLoopSameEpisode(DriverTestCase):
    def test_candidate_change_grants_each_family_a_fresh_round_budget(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(max_rounds_per_family=1))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step(
                    "review_round",
                    report("review_round", [finding("F1", "later defect")]),
                    family="claude",
                ),
                step(
                    "fix_findings",
                    fix_ok(
                        [triaged("F1", "fixed", "later defect")],
                        files_changed=["docs/skeleton.md"],
                    ),
                    family="codex",
                    side_effect=append_file("docs/skeleton.md", "\nfixed\n"),
                ),
                step("delta_review", report("delta_review"), family="codex"),
                # The old reviews belong to the obsolete candidate.  Even
                # with a one-round cap, both families get one fresh look.
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda state: state["units"][0]["status"] == st.U_SEALED,
            )
            self.assertEqual(mock.script, [])
            self.assertIsNone(driver.state["failure"])
            self.assertEqual(
                [
                    call[0]
                    for call in mock.calls
                    if call[1] == "review_round"
                ],
                ["codex", "claude", "codex", "claude"],
            )

    def test_dirty_delta_loops_then_restarts_reviews_from_codex(self):
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
                # Changed bytes invalidate all prior approvals, so the full
                # review cycle restarts from Codex.
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
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
            fix_prompts = [
                prompt for (_family, kind, prompt) in mock.calls
                if kind == "fix_findings"
            ]
            self.assertEqual(len(fix_prompts), 2)
            for prompt in fix_prompts:
                self.assertIn(
                    '"permitted_baseline": "the documented behavior"', prompt
                )
                self.assertIn(
                    '"incremental_harm": "the observed behavior breaks the '
                    'documented behavior"',
                    prompt,
                )
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
                transitions.count(
                    (st.U_DELTA_REVIEW, st.U_PRE_REVIEW_VERIFY)
                ),
                1,
            )
            # One green episode => exactly one amend.
            self.assertEqual(
                len([e for e in state["events"] if e["type"] == "amended"]), 1)

            # The review round AFTER the episode restarted with Codex;
            # family advance happened only on the clean rounds.
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
# Review delta budget: checkpoint after N fixes, same family reviews whole WIP


class TestDeltaFullReviewCheckpoint(DriverTestCase):
    def test_second_fix_skips_delta_and_restarts_reviews_from_codex(self):
        self.assertEqual(drv.DEFAULT_CONFIG["delta_full_review_after_fixes"], 5)
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(
                ws, make_config(delta_full_review_after_fixes=2)
            )
            mock = runners.MockRunner([
                draft_step(),
                # Codex is already clean; Claude is the active reviewer whose
                # dirty round opens the fix episode.
                step("review_round", report("review_round"), family="codex"),
                step(
                    "review_round",
                    report("review_round", [finding("F1", "first defect")]),
                    family="claude",
                ),
                step(
                    "fix_findings",
                    fix_ok(
                        [triaged("F1", "fixed", "first defect")],
                        files_changed=["docs/skeleton.md"],
                    ),
                    family="codex",
                    side_effect=append_file("docs/skeleton.md", "\nfix1\n"),
                ),
                step(
                    "delta_review",
                    report("delta_review", [finding("D1", "delta defect")]),
                    family="codex",
                ),
                step(
                    "fix_findings",
                    fix_ok(
                        [triaged("D1", "fixed", "delta defect")],
                        files_changed=["docs/skeleton.md"],
                    ),
                    family="codex",
                    side_effect=append_file("docs/skeleton.md", "\nfix2\n"),
                ),
                # No second delta call: fix #2 is amended and the changed
                # candidate is reviewed afresh from the first family.
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda state: (
                    state["units"][0]["status"] == st.U_FIXING
                    and any(
                        round_["kind"] == "delta_review"
                        for round_ in state["units"][0]["rounds"]
                    )
                ),
            )
            # Resume deliberately resets this soft loop budget. The review
            # checkpoint must still see fix #2 from append-only history.
            driver.state["units"][0]["fix_loop_rounds"] = 0
            st.save(path, driver.state)
            self.step_until(
                driver,
                lambda state: state["units"][0]["status"] == st.U_SEALED,
            )
            self.assertEqual(mock.script, [])

            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(
                [call[1] for call in mock.calls],
                [
                    "draft_skeleton", "review_round", "review_round",
                    "fix_findings", "delta_review", "fix_findings",
                    "review_round", "review_round",
                ],
            )
            self.assertEqual(
                [call[0] for call in mock.calls if call[1] == "review_round"],
                ["codex", "claude", "codex", "claude"],
            )
            deltas = [
                round_ for round_ in unit["rounds"]
                if round_["kind"] == "delta_review"
            ]
            self.assertEqual(len(deltas), 1)
            self.assertEqual(len(deltas[0]["result"]["findings"]), 1)
            checkpoint = [
                event for event in state["events"]
                if event["type"] == "delta_checkpoint"
            ]
            self.assertEqual(len(checkpoint), 1)
            self.assertEqual(checkpoint[0]["fixes"], 2)
            self.assertEqual(checkpoint[0]["dirty_deltas"], 1)
            self.assertEqual(
                checkpoint[0]["return_to"], st.U_PRE_REVIEW_VERIFY
            )
            self.assertEqual(checkpoint[0]["review_family"], "codex")
            self.assertEqual(
                len([e for e in state["events"] if e["type"] == "amended"]),
                1,
            )

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
# (f) the rejection registry across review rounds


class TestRejectionRegistry(DriverTestCase):
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
                # Reject directly, with a prevention edit that makes the
                # already-correct contract easier to read.
                step("fix_findings",
                     fix_ok([triaged(
                         "F1", "rejected",
                         "goal wording is ambiguous about float support",
                         prevention={"documented_in": "docs/skeleton.md",
                                     "note": "explicit float note added"},
                     )], files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\nNote: floats supported.\n")),
                step("delta_review", report("delta_review"), family="codex"),
                step("review_round", report("review_round"), family="codex"),
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
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
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
            self.assertNotIn("ADJUDICATED REJECTIONS", claude_reviews[0])
            self.assertIn("ADJUDICATED REJECTIONS", claude_reviews[1])
            self.assertIn(
                '"id": "%s"' % self.REJECTION_ID, claude_reviews[1]
            )
            self.assertIn(
                '"documented_in": "docs/skeleton.md"',
                claude_reviews[1],
            )
            # The review AFTER the concession no longer sees settled law.
            self.assertNotIn("ADJUDICATED REJECTIONS", claude_reviews[2])

            # The contesting finding reached the fixer with the contests
            # visible in the prompt.
            fix_prompts = [c[2] for c in mock.calls
                           if c[1] == "fix_findings"]
            self.assertEqual(len(fix_prompts), 2)
            self.assertIn(
                '"rejection_id": "%s"' % self.REJECTION_ID,
                fix_prompts[1],
            )
            self.assertIn(
                '"new_evidence": "%s"' % self.NEW_EVIDENCE,
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
    def _run_skeleton(self, ws, acts, script_tail, draft_family="codex",
                      config=None):
        # The skeleton draft runs the `skeletoner` act; callers whose
        # skeletoner resolves to a non-codex family override draft_family so
        # the scripted draft expects the right worker.
        path = init_state(ws, config or make_config(acts=acts))
        draft = dict(draft_step())
        draft["expect_family"] = draft_family
        mock = runners.MockRunner([draft] + script_tail)
        driver = drv.Driver(path, runner=mock)
        self.step_until(driver,
                        lambda s: s["units"][0]["status"] == st.U_SEALED)
        self.assertEqual(mock.script, [])
        return mock

    def test_delta_uses_fixer_family_and_its_review_profile(self):
        acts = {
            "fixer": "opposite",
            # This scenario fixes a skeleton, which runs `skeletoner`; mirror
            # the fixer policy onto it so the fixer-family rotation and the
            # delta-follows-fixer profile are what's under test.
            "skeletoner": "opposite",
            # A legacy frozen value must not decouple delta from the fixer.
            "delta_review": "opposite",
            "review_codex": {"model": "gpt-5.6-sol", "effort": "high"},
            "review_claude": {
                "model": "claude-fable-5", "effort": "medium",
            },
        }
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            mock = self._run_skeleton(ws, acts, draft_family="claude", script_tail=[
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
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
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
            fix_prompts = [c[2] for c in mock.calls
                           if c[1] == "fix_findings"]
            for prompt in fix_prompts:
                self.assertIn(
                    "Never invoke, spawn, or consult another LLM", prompt
                )
                self.assertNotIn("CONSULTATION PROTOCOL", prompt)

    def test_literal_fixer_selects_same_family_delta(self):
        acts = {"fixer": "claude", "skeletoner": "claude",
                "delta_review": "self"}
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            mock = self._run_skeleton(ws, acts, draft_family="claude", script_tail=[
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
            ])
            fix_delta_calls = [(c[1], c[0]) for c in mock.calls
                               if c[1] in ("fix_findings", "delta_review")]
            self.assertEqual(
                fix_delta_calls,
                [("fix_findings", "claude"), ("delta_review", "claude")],
            )
            fix_prompt = [c[2] for c in mock.calls
                          if c[1] == "fix_findings"][0]
            self.assertIn("Never invoke, spawn, or consult another LLM",
                          fix_prompt)
            self.assertNotIn("CONSULTATION PROTOCOL", fix_prompt)

    def test_fix_prompt_forbids_worker_dispatched_model_calls(self):
        acts = {"fixer": "claude", "skeletoner": "claude",
                "delta_review": "self"}
        config = make_config(
            acts=acts,
            commands=drv.DEFAULT_CONFIG["commands"],
            model_defaults=drv.DEFAULT_CONFIG["model_defaults"],
        )
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            mock = self._run_skeleton(
                ws, acts, draft_family="claude", config=config,
                script_tail=[
                    step("review_round",
                         report("review_round", [finding("F1", "found")]),
                         family="codex"),
                    step("fix_findings",
                         fix_ok([triaged("F1", "fixed", "found")],
                                files_changed=["docs/skeleton.md"]),
                         family="claude",
                         side_effect=append_file(
                             "docs/skeleton.md", "\nfix\n")),
                    step("delta_review", report("delta_review"),
                         family="claude"),
                    step("review_round", report("review_round"),
                         family="codex"),
                    step("review_round", report("review_round"),
                         family="claude"),
                ])
            fix_prompt = [c[2] for c in mock.calls
                          if c[1] == "fix_findings"][0]
            normalized_prompt = " ".join(fix_prompt.split())
            self.assertIn("Never invoke, spawn, or consult another LLM",
                          fix_prompt)
            self.assertIn("deterministic driver dispatches model calls",
                          normalized_prompt)
            self.assertNotIn("CONSULTATION PROTOCOL", fix_prompt)
            self.assertNotIn("current_model_call.py", fix_prompt)
            self.assertNotIn("Command (prompt on stdin)", fix_prompt)

    def test_skeleton_fix_routes_through_skeletoner_not_fixer(self):
        # Routing check with the two acts set to DIFFERENT families: the
        # skeleton fix must resolve `skeletoner`, never the general `fixer`.
        acts = {
            "fixer": "codex",
            "skeletoner": {"agent": "claude", "model": "claude-fable-5",
                           "effort": "max"},
        }
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            mock = self._run_skeleton(ws, acts, draft_family="claude",
                                      script_tail=[
                step("review_round",
                     report("review_round", [finding("F1", "defect")]),
                     family="codex"),
                step("fix_findings",
                     fix_ok([triaged("F1", "fixed", "defect")],
                            files_changed=["docs/skeleton.md"]),
                     family="claude",
                     side_effect=append_file("docs/skeleton.md", "\nfix\n")),
                step("delta_review", report("delta_review"), family="claude"),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ])
            fix_meta = [m for c, m in zip(mock.calls, mock.call_meta)
                        if c[1] == "fix_findings"][0]
            # skeletoner (claude/fable-5), not fixer (codex).
            self.assertEqual(fix_meta["family"], "claude")
            self.assertEqual(fix_meta["model"], "claude-fable-5")

    def test_model_only_skeletoner_override_keeps_claude_default(self):
        # A panel override that customizes ONLY the model sends
        # {"model": X} with no agent/effort -- merge_config replaces the
        # whole act entry, dropping the DEFAULT_CONFIG agent=claude and
        # effort=max. Both the skeleton DRAFT and its FIX must still run on
        # the skeleton's default CLAUDE family at max effort, never fall
        # back to the codex fix-family (which cannot run a claude model) or
        # to claude's family effort.
        acts = {"skeletoner": {"model": "claude-opus-5"}}
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            mock = self._run_skeleton(ws, acts, draft_family="claude",
                                      script_tail=[
                step("review_round",
                     report("review_round", [finding("F1", "defect")]),
                     family="codex"),
                step("fix_findings",
                     fix_ok([triaged("F1", "fixed", "defect")],
                            files_changed=["docs/skeleton.md"]),
                     family="claude",
                     side_effect=append_file("docs/skeleton.md", "\nfix\n")),
                step("delta_review", report("delta_review"), family="claude"),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ])
            # call[0] is the skeleton draft.
            self.assertEqual(mock.calls[0][1], "draft_skeleton")
            self.assertEqual(
                (mock.call_meta[0]["family"], mock.call_meta[0]["model"],
                 mock.call_meta[0]["effort"]),
                ("claude", "claude-opus-5", "max"),
            )
            fix_meta = [m for c, m in zip(mock.calls, mock.call_meta)
                        if c[1] == "fix_findings"][0]
            self.assertEqual(
                (fix_meta["family"], fix_meta["model"], fix_meta["effort"]),
                ("claude", "claude-opus-5", "max"),
            )


if __name__ == "__main__":
    unittest.main()
