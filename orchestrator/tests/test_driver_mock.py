"""Full-lifecycle driver tests via runners.MockRunner (no LLM subprocesses)
for the reviewer/fixer separation model.

MockRunner side effects perform REAL file writes inside tempdir workspaces
and the configs are git-enabled (commands are dummies, never spawned), so
wip commits, fix deltas, amends, snapshots-based tampering detection and
gate commits are exercised against real git repos. All git activity happens
inside tempfile.TemporaryDirectory workspaces — NEVER against the canon
repository.

Covers here:
  (a) the full happy lifecycle mirroring the calculator fake-LLM scenario
      (unit sequence, statuses, exact round kind/id sequences including
      fix_findings and delta_review records, derived seal records, gate_commit
      fields, ledgers, milestone closed);
  (i) fixer coverage violation / rejected-without-consultation protocol
      failure / unknown adjudication_ref / unknown contests reference;
  (l) git-disabled legacy path (fix returns directly, no delta/amend);
  (m) resume mid-flow with a fresh Driver; decide() totality at every step.

The fix-loop mechanics themselves — delta-dirty loops, caps, verification
episodes, review/delta tampering, the adjudication circuit, acts
resolution — live in test_fix_loop.py, which imports this module's helpers.
"""

import copy
import os
import subprocess
import tempfile
import unittest

from orchestrator import contracts, driver as drv
from orchestrator import runners
from orchestrator import state as st

GOAL = "Build a small CLI calculator (add/sub/mul/div) with unit tests"

GATE_MSG_INIT = "Initialize milestone workspace"
GATE_MSG_SKELETON = "Seal milestone skeleton"
GATE_MSG_NOTE = "Seal slice 01 note"
GATE_MSG_IMPL = "Seal slice 01 implementation and close"
GATE_MSG_CLOSE = "Close milestone"

# Verification used by the happy path: passes until calculator.py exists,
# then requires the div_fixed marker the fixer writes (mirrors the fake
# scenario's deliberate div bug forcing the verification-fix path).
VERIFY_CMD = "[ ! -f calculator.py ] || [ -f div_fixed ]"


# ---------------------------------------------------------------------------
# Shared helpers (imported by test_fix_loop.py)


def make_config(**overrides):
    """Git-enabled frozen config; commands are never spawned (MockRunner)."""
    cfg = {
        "families_order": ["codex", "claude"],
        "fix_family": None,
        "commands": {"codex": ["fake-codex"], "claude": ["fake-claude"]},
        "timeouts": {},
        "verification": [],
        "verification_timeout": 60,
        "max_rounds_per_family": 6,
        "max_verify_fix_attempts": 2,
        "git": {"enabled": True},
        "acts": {"skeletoner": "codex", "fixer": "codex", "delta_review": "codex",
                 "consultation": "opposite"},
        "max_fix_loops": 6,
        "snapshot_exclude_dirs": [],
        # Deterministic tests: no LLM classifier fallback, no sleeps.
        "error_classifier": False,
        "infra_retry_backoff_s": [],
    }
    cfg.update(overrides)
    return cfg


def git_init_workspace(workspace):
    """The operator's deliberate `git init`. ensure_repo no longer
    auto-inits (the ledger repo must be created on purpose), so every
    git-enabled harness workspace gets its repo up front — exactly what
    run_demo.sh does before `driver init`."""
    subprocess.run(
        ["git", "init", "-q"],
        cwd=workspace, capture_output=True, text=True, check=True, timeout=60,
    )


def init_state(workspace, config, goal=GOAL):
    """Create the on-disk state file the way `driver init` does. For
    git-enabled configs the workspace is first made a repo deliberately
    (ensure_repo refuses non-repo workspaces)."""
    if (config.get("git") or {}).get("enabled"):
        git_init_workspace(workspace)
    state = st.new_state(goal, workspace, config)
    st.append_event(state, "initialized", goal=goal)
    path = drv.default_state_path(workspace)
    st.save(path, state)
    return path


def ok(kind, **extra):
    payload = {"status": "ok", "kind": kind}
    payload.update(extra)
    return payload


def report(kind, findings=()):
    """A report-only response (review_round / delta_review)."""
    return ok(kind, findings=list(findings))


def validity(exceeds=True):
    return {
        "permitted_baseline": "the documented behavior",
        "actual_outcome": "the observed behavior",
        "incremental_harm": (
            "the observed behavior breaks the documented behavior"
            if exceeds else "no harm beyond the documented behavior"
        ),
        "exceeds_baseline": exceeds,
    }


def finding(fid, summary, severity="P3", contests=None, plain=None,
            example=None):
    # Every test finding carries the lay mirror by default: optional in
    # the base contract, hard-required under a reform profile.
    f = {"id": fid, "severity": severity, "summary": summary,
         "validity": validity(True),
         "plain": plain or ("plain: %s" % summary),
         "example": example or ("example: %s" % summary)}
    if contests is not None:
        f["contests"] = contests
    return f


def battery_entries(ids):
    """A valid battery payload for reform-profile doc drafts."""
    return [{"question": q, "answer": "answered: %s" % q,
             "evidence": ["docs/x.md:1"]} for q in ids]


def triaged(fid, disposition, summary="triaged finding", severity="P3",
            consultation=None, prevention=None, adjudication_ref=None):
    entry = {
        "id": fid,
        "severity": severity,
        "summary": summary,
        "disposition": disposition,
        "consultation": consultation,
        "validity": validity(disposition in ("fixed", "blocked")),
    }
    if prevention is not None:
        entry["prevention"] = prevention
    if adjudication_ref is not None:
        entry["adjudication_ref"] = adjudication_ref
    return entry


def fix_ok(entries, files_changed=(), **extra):
    return ok(
        "fix_findings",
        findings=list(entries),
        files_changed=list(files_changed),
        **extra
    )


def step(kind, response, family=None, side_effect=None):
    s = {"expect_kind": kind, "response": response}
    if family is not None:
        s["expect_family"] = family
    if side_effect is not None:
        s["side_effect"] = side_effect
    return s


def write_file(rel, content):
    """Side effect factory: write `content` at a workspace-relative path."""

    def effect(workspace):
        path = os.path.join(workspace, rel)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    return effect


def append_file(rel, content):
    """Side effect factory: append `content` to a workspace-relative path."""

    def effect(workspace):
        with open(os.path.join(workspace, rel), "a", encoding="utf-8") as fh:
            fh.write(content)

    return effect


def multi(*effects):
    def effect(workspace):
        for e in effects:
            e(workspace)

    return effect


def git_subjects(workspace):
    """Commit subjects, oldest first. Only ever used on tempdir repos."""
    out = subprocess.run(
        ["git", "log", "--format=%h %s", "--reverse"],
        cwd=workspace, capture_output=True, text=True, check=True,
    ).stdout
    entries = []
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        entries.append((sha, subject))
    return entries


class DriverTestCase(unittest.TestCase):
    """Shared drive helpers that also verify decide() totality."""

    def drive(self, driver, max_steps=200):
        """Step until DONE/FAILED; decide() must be total after every step."""
        actions = []
        for _ in range(max_steps):
            action = drv.decide(driver.state)
            if action.type in (drv.A_DONE, drv.A_FAILED):
                if action.type == drv.A_DONE:
                    driver.run()  # closes the milestone when all units sealed
                return actions, action
            act, note = driver.step()
            actions.append((act, note))
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

    def assert_failed(self, path, driver, reason_substrings, unit_key=None):
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


# ---------------------------------------------------------------------------
# Scripts mirroring the calculator fake-LLM scenario


def skeleton_script():
    """codex finding -> fix -> delta clean -> codex clean; claude finding ->
    reject (consultation + prevention edit) -> delta clean; claude stubborn
    duplicate -> rejected_adjudicated by pointer (no edit, no delta call);
    claude clean; deterministic seal."""
    return [
        step(
            "draft_skeleton",
            ok("draft_skeleton", artifact="docs/skeleton.md",
               slices=[{"id": 1, "title": "Calculator core"}]),
            family="codex",
            side_effect=write_file(
                "docs/skeleton.md",
                "# Calculator milestone\n\nGoal: CLI calculator with tests.\n",
            ),
        ),
        step("review_round",
             report("review_round",
                    [finding("F1", "skeleton lacks explicit non-goals")]),
             family="codex"),
        step("fix_findings",
             fix_ok([triaged("F1", "fixed", "skeleton lacks explicit non-goals")],
                    files_changed=["docs/skeleton.md"]),
             family="codex",
             side_effect=append_file(
                 "docs/skeleton.md",
                 "\n## Non-goals\n\nNo scientific functions.\n")),
        step("delta_review", report("delta_review"), family="codex"),
        step("review_round", report("review_round"), family="codex"),
        step("review_round",
             report("review_round",
                    [finding("F1",
                             "goal wording is ambiguous about float support")]),
             family="claude"),
        step("fix_findings",
             fix_ok([triaged(
                 "F1", "rejected",
                 "goal wording is ambiguous about float support",
                 consultation={
                     "resolution": "opposite family agreed the goal was "
                     "already float-typed by the CLI contract"},
                 prevention={"documented_in": "docs/skeleton.md",
                             "note": "explicit float-support note added"},
             )], files_changed=["docs/skeleton.md"]),
             family="codex",
             side_effect=append_file(
                 "docs/skeleton.md",
                 "\nNote: operations are defined over floats.\n")),
        step("delta_review", report("delta_review"), family="codex"),
        step("review_round", report("review_round"), family="codex"),
        step("review_round",
             report("review_round",
                    [finding("F1",
                             "goal wording is ambiguous about float support")]),
             family="claude"),
        # Killed by pointer: no edit, so the delta step closes with no call.
        step("fix_findings",
             fix_ok([triaged(
                 "F1", "rejected_adjudicated",
                 "goal wording is ambiguous about float support",
                 adjudication_ref="skeleton-claude-r1/F1")]),
             family="codex"),
        step("review_round", report("review_round"), family="claude"),
    ]


def doc_script():
    """Slice note: both reviewers clean, then deterministic seal."""
    return [
        step(
            "draft_slice_note",
            ok("draft_slice_note", artifact="docs/slice-01.md"),
            family="codex",
            side_effect=write_file(
                "docs/slice-01.md",
                "# Slice 01 - Calculator core\n\nContracts: add/sub/mul/div.\n",
            ),
        ),
        step("review_round", report("review_round"), family="codex"),
        step("review_round", report("review_round"), family="claude"),
    ]


def impl_script():
    """div bug -> verification fails -> V1 fix episode; docstring round
    finding -> fix; claude README finding -> fix; both reviewers then clean."""
    return [
        step(
            "implement",
            ok("implement",
               files_changed=["calculator.py", "test_calculator.py"]),
            family="codex",
            side_effect=multi(
                write_file("calculator.py",
                           "def div(a, b):\n    return a * b  # BUG\n"),
                write_file("test_calculator.py", "# tests\n"),
            ),
        ),
        # pre-review verification fails (calculator.py without div_fixed)
        step("fix_findings",
             fix_ok([triaged("V1", "fixed",
                             "the verification suite failed", severity="P1")],
                    files_changed=["calculator.py", "div_fixed"]),
             family="codex",
             side_effect=multi(
                 write_file("calculator.py",
                            "def div(a, b):\n    return a / b\n"),
                 write_file("div_fixed", "verification repaired\n"),
             )),
        step("delta_review", report("delta_review"), family="codex"),
        # re-verify green -> rounds
        step("review_round",
             report("review_round",
                    [finding("F1", "calculator module lacks a docstring")]),
             family="codex"),
        step("fix_findings",
             fix_ok([triaged("F1", "fixed",
                             "calculator module lacks a docstring")],
                    files_changed=["calculator.py"]),
             family="codex",
             side_effect=write_file(
                 "calculator.py",
                 '"""Tiny CLI calculator."""\n\ndef div(a, b):\n'
                 "    return a / b\n")),
        step("delta_review", report("delta_review"), family="codex"),
        step("review_round", report("review_round"), family="codex"),
        step("review_round",
             report("review_round",
                    [finding("S1",
                             "workspace lacks a README describing CLI usage")]),
             family="claude"),
        step("fix_findings",
             fix_ok([triaged(
                 "S1", "fixed",
                 "workspace lacks a README describing CLI usage")],
                 files_changed=["README.md"]),
             family="codex",
             side_effect=write_file("README.md", "# Calculator\n\nUsage.\n")),
        step("delta_review", report("delta_review"), family="codex"),
        step("review_round", report("review_round"), family="codex"),
        step("review_round", report("review_round"), family="claude"),
    ]


# ---------------------------------------------------------------------------
# (a) full happy lifecycle


class TestHappyLifecycle(DriverTestCase):
    def test_full_lifecycle_mirrors_fake_scenario(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(verification=[VERIFY_CMD]))
            mock = runners.MockRunner(
                skeleton_script() + doc_script() + impl_script()
            )
            driver = drv.Driver(path, runner=mock)
            actions, final = self.drive(driver)

            self.assertEqual(final.type, drv.A_DONE)
            self.assertEqual(mock.script, [], "mock script fully consumed")

            expected_actions = (
                # skeleton
                [drv.A_DRAFT, drv.A_VERIFY,
                 drv.A_REVIEW_ROUND, drv.A_FIX, drv.A_DELTA_REVIEW,
                 drv.A_VERIFY,
                 drv.A_REVIEW_ROUND,
                 drv.A_REVIEW_ROUND, drv.A_FIX, drv.A_DELTA_REVIEW,
                 drv.A_VERIFY,
                 drv.A_REVIEW_ROUND, drv.A_REVIEW_ROUND,
                 drv.A_FIX, drv.A_DELTA_REVIEW,
                 drv.A_REVIEW_ROUND,
                 drv.A_VERIFY]
                # slice doc
                + [drv.A_DRAFT, drv.A_VERIFY,
                   drv.A_REVIEW_ROUND, drv.A_REVIEW_ROUND,
                   drv.A_VERIFY]
                # slice impl
                + [drv.A_DRAFT, drv.A_VERIFY,
                   drv.A_FIX, drv.A_DELTA_REVIEW, drv.A_VERIFY,
                   drv.A_REVIEW_ROUND, drv.A_FIX, drv.A_DELTA_REVIEW,
                   drv.A_VERIFY,
                   drv.A_REVIEW_ROUND, drv.A_REVIEW_ROUND,
                   drv.A_FIX, drv.A_DELTA_REVIEW,
                   drv.A_VERIFY, drv.A_REVIEW_ROUND,
                   drv.A_REVIEW_ROUND, drv.A_VERIFY]
            )
            self.assertEqual([a.type for a, _ in actions], expected_actions)

            state = st.load(path)  # persisted, not just in-memory
            self.assertEqual(state["milestone"]["status"], st.M_CLOSED)
            self.assertIsNone(state["failure"])
            self.assertEqual(state["milestone"]["slices"],
                             [{"id": 1, "title": "Calculator core"}])

            # Unit sequence and terminal statuses.
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
            self.assertIsNone(impl["artifact"])  # implement carries none

            # Exact round id/kind/family sequences, fix + delta included.
            self.assertEqual(
                [(r["id"], r["kind"], r["family"]) for r in skeleton["rounds"]],
                [
                    ("skeleton-codex-r1", "review_round", "codex"),
                    ("skeleton-codex-r2", "fix_findings", "codex"),
                    ("skeleton-codex-r3", "delta_review", "codex"),
                    ("skeleton-codex-r4", "review_round", "codex"),
                    ("skeleton-claude-r1", "review_round", "claude"),
                    ("skeleton-codex-r5", "fix_findings", "codex"),
                    ("skeleton-codex-r6", "delta_review", "codex"),
                    ("skeleton-codex-r7", "review_round", "codex"),
                    ("skeleton-claude-r2", "review_round", "claude"),
                    ("skeleton-codex-r8", "fix_findings", "codex"),
                    ("skeleton-claude-r3", "review_round", "claude"),
                ],
            )
            self.assertEqual(
                [(r["id"], r["kind"]) for r in doc["rounds"]],
                [("slice_doc-01-codex-r1", "review_round"),
                 ("slice_doc-01-claude-r1", "review_round")],
            )
            self.assertEqual(
                [(r["id"], r["kind"], r["family"]) for r in impl["rounds"]],
                [
                    ("slice_impl-01-codex-r1", "fix_findings", "codex"),
                    ("slice_impl-01-codex-r2", "delta_review", "codex"),
                    ("slice_impl-01-codex-r3", "review_round", "codex"),
                    ("slice_impl-01-codex-r4", "fix_findings", "codex"),
                    ("slice_impl-01-codex-r5", "delta_review", "codex"),
                    ("slice_impl-01-codex-r6", "review_round", "codex"),
                    ("slice_impl-01-claude-r1", "review_round", "claude"),
                    ("slice_impl-01-codex-r7", "fix_findings", "codex"),
                    ("slice_impl-01-codex-r8", "delta_review", "codex"),
                    ("slice_impl-01-codex-r9", "review_round", "codex"),
                    ("slice_impl-01-claude-r2", "review_round", "claude"),
                ],
            )

            # Fixer records carry their source round ids.
            fixes = {r["id"]: r for r in skeleton["rounds"] + impl["rounds"]
                     if r["kind"] == "fix_findings"}
            self.assertEqual(fixes["skeleton-codex-r2"]["source_round_id"],
                             "skeleton-codex-r1")
            self.assertEqual(fixes["skeleton-codex-r5"]["source_round_id"],
                             "skeleton-claude-r1")
            self.assertEqual(fixes["skeleton-codex-r8"]["source_round_id"],
                             "skeleton-claude-r2")
            self.assertEqual(fixes["slice_impl-01-codex-r1"]["source_round_id"],
                             "slice_impl-01-verify-pre_review-1")
            self.assertEqual(fixes["slice_impl-01-codex-r4"]["source_round_id"],
                             "slice_impl-01-codex-r3")
            self.assertEqual(fixes["slice_impl-01-codex-r7"]["source_round_id"],
                             "slice_impl-01-claude-r1")

            # Reviewer findings carry no disposition; fixer rounds carry
            # exactly the queued ids.
            for r in skeleton["rounds"] + impl["rounds"]:
                for f in r["result"].get("findings", []):
                    if r["kind"] == "fix_findings":
                        self.assertIn("disposition", f)
                    else:
                        self.assertNotIn("disposition", f)
            self.assertEqual(
                [f["id"] for f in
                 fixes["slice_impl-01-codex-r7"]["result"]["findings"]],
                ["S1"],
            )

            # Seal records complete on every unit.
            for unit in state["units"]:
                self.assertTrue(unit["seals"])
                last = unit["seals"][-1]
                self.assertTrue(last["passed"])
                self.assertIsNone(last["invalidated"])
                self.assertEqual(len(unit["seals"]), 1)
                self.assertEqual(unit["seals"][0]["halves"], {})

            self.assertIsNotNone(impl["closed_record"])
            self.assertEqual(impl["closed_record"]["slice_id"], 1)

            # Gate commits: canonical history, one clean commit per unit.
            subjects = git_subjects(ws)
            self.assertEqual(
                [s for _, s in subjects],
                [GATE_MSG_INIT, GATE_MSG_SKELETON, GATE_MSG_NOTE,
                 GATE_MSG_IMPL, GATE_MSG_CLOSE],
            )
            by_subject = {s: sha for sha, s in subjects}
            self.assertEqual(skeleton["gate_commit"], by_subject[GATE_MSG_SKELETON])
            self.assertEqual(doc["gate_commit"], by_subject[GATE_MSG_NOTE])
            self.assertEqual(impl["gate_commit"], by_subject[GATE_MSG_IMPL])
            gate_events = [e for e in state["events"] if e["type"] == "gate_commit"]
            self.assertEqual(
                [(e["unit"], e["message"], e["sha"]) for e in gate_events],
                [
                    ("skeleton", GATE_MSG_SKELETON, skeleton["gate_commit"]),
                    ("slice_doc-01", GATE_MSG_NOTE, doc["gate_commit"]),
                    ("slice_impl-01", GATE_MSG_IMPL, impl["gate_commit"]),
                    (None, GATE_MSG_CLOSE, by_subject[GATE_MSG_CLOSE]),
                ],
            )
            # Nothing uncommitted after the close (ledgers folded in).
            porcelain = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ws, capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(porcelain, "")

            # The adjudication registry survived and hit the ledgers.
            self.assertEqual(st.registry_ids(state), {"skeleton-claude-r1/F1"})
            with open(os.path.join(ws, "docs", "adjudications.md"),
                      encoding="utf-8") as fh:
                adjudications = fh.read()
            self.assertIn("[skeleton-claude-r1/F1]", adjudications)
            self.assertIn("opposite family agreed", adjudications)
            self.assertIn("docs/skeleton.md", adjudications)
            self.assertIn("explicit float-support note added", adjudications)

            # Verification bookkeeping: the impl div bug failed exactly once
            # and the per-stage counter reset on the pass.
            verifs = [e for e in state["events"] if e["type"] == "verification"]
            self.assertEqual([e["ok"] for e in verifs if e["unit"] == "skeleton"],
                             [True, True, True, True])
            self.assertEqual(
                [e["ok"] for e in verifs if e["unit"] == "slice_impl-01"],
                [False, True, True, True, True],
            )
            self.assertEqual(impl["verify_fix_attempts"],
                             {"pre_review": 0, "pre_seal": 0})

            # Event ordering sanity.
            events = state["events"]
            self.assertEqual([e["seq"] for e in events], list(range(len(events))))
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
            # Amends: skeleton 2 green episodes, impl 3.
            amends = [e["unit"] for e in events if e["type"] == "amended"]
            self.assertEqual(amends, ["skeleton", "skeleton",
                                      "slice_impl-01", "slice_impl-01",
                                      "slice_impl-01"])
            wips = [e["unit"] for e in events if e["type"] == "wip_commit"]
            self.assertEqual(wips, ["skeleton", "slice_doc-01", "slice_impl-01"])


class TestOperatorAmendmentsFlow(DriverTestCase):
    """Amendments dropped into .orchestrator/amendments.json mid-run reach
    every subsequent worker prompt and leave an amendment_seen ledger
    event exactly once per id."""

    def test_amendments_reach_prompts_and_ledger(self):
        import json as _json
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            os.makedirs(os.path.join(ws, ".orchestrator"), exist_ok=True)
            with open(os.path.join(ws, ".orchestrator", "amendments.json"),
                      "w", encoding="utf-8") as fh:
                _json.dump({"amendments": [
                    {"id": "A1", "text": "No hot-path changes.",
                     "at": "2026-07-05T13:00:00+0200"},
                ]}, fh)
            mock = runners.MockRunner([
                skeleton_script()[0],
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            # Every worker prompt carried the amendment.
            self.assertEqual(len(mock.calls), 3)
            for _fam, _kind, prompt in mock.calls:
                self.assertIn("OPERATOR AMENDMENTS", prompt)
                self.assertIn("No hot-path changes.", prompt)
            # Ledger trail: exactly one amendment_seen for A1.
            state = st.load(path)
            seen = [e for e in state["events"]
                    if e["type"] == "amendment_seen"]
            self.assertEqual(
                [e["amendment_id"] for e in seen], ["A1"])

    def test_missing_or_corrupt_file_means_no_amendments(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            os.makedirs(os.path.join(ws, ".orchestrator"), exist_ok=True)
            with open(os.path.join(ws, ".orchestrator", "amendments.json"),
                      "w", encoding="utf-8") as fh:
                fh.write("{not json")
            mock = runners.MockRunner([skeleton_script()[0]])
            driver = drv.Driver(path, runner=mock)
            driver.step()
            _fam, _kind, prompt = mock.calls[0]
            self.assertNotIn("OPERATOR AMENDMENTS", prompt)


class TestSuiteDiscoveryProtocol(DriverTestCase):
    """Zero-config verification: the implementer's suite_command arms the
    mechanical gates for implementation units; doc units stay cheap; the
    discovery and every gate run land in the ledger."""

    def test_discovered_suite_arms_impl_gates_only(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(verification=[]))
            impl = impl_script()
            # The discovered command IS the demo's verification predicate,
            # so discovery must drive the exact verify-fail -> fix -> green
            # machinery the configured path drives.
            impl[0]["response"]["suite_command"] = VERIFY_CMD
            mock = runners.MockRunner(
                skeleton_script() + doc_script() + impl
            )
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_DONE)
            self.assertEqual(mock.script, [])

            state = st.load(path)
            self.assertEqual(state["suite_command"], VERIFY_CMD)
            discoveries = [e for e in state["events"]
                           if e["type"] == "suite_discovered"]
            self.assertEqual([e["command"] for e in discoveries],
                             [VERIFY_CMD])

            # Gates: doc units ran nothing; impl gates ran the discovery.
            ver = [e for e in state["events"] if e["type"] == "verification"]
            self.assertTrue(ver)
            for e in ver:
                if e["unit"].startswith("slice_impl"):
                    self.assertEqual(e["commands"], [VERIFY_CMD], e)
                else:
                    self.assertEqual(e["commands"], [], e)

            # Reviewers of the impl unit are told the machine ran the
            # suite; doc reviewers are not.
            for fam, kind, prompt in mock.calls:
                if kind == "review_round":
                    has = "VERIFICATION STATUS" in prompt
                    if "slice 1 implementation" in prompt:
                        self.assertTrue(has, kind)
                    else:
                        self.assertFalse(has, kind)

    def test_later_discovery_does_not_replace_established_suite(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(verification=[]))
            state = st.load(path)

            self.assertTrue(st.set_discovered_suite(state, "mix precommit"))
            self.assertFalse(st.set_discovered_suite(state, "mix test"))
            self.assertEqual(state["suite_command"], "mix precommit")

            ignored = [
                event for event in state["events"]
                if event["type"] == "suite_discovery_ignored"
            ]
            self.assertEqual(len(ignored), 1)
            self.assertEqual(ignored[0]["command"], "mix test")
            self.assertEqual(ignored[0]["established"], "mix precommit")

    def test_suite_fix_overrides_stale_config_verification(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            stale = "python3 -m unittest discover -s orchestrator/tests"
            corrected = stale + " -t ."
            path = init_state(ws, make_config(verification=[stale]))
            state = st.load(path)
            st.set_discovered_suite(state, corrected)
            state["units"][0]["rounds"].append({
                "id": "skeleton-codex-r2",
                "family": "codex",
                "kind": contracts.KIND_FIX_FINDINGS,
                "result": {
                    "status": "ok",
                    "kind": contracts.KIND_FIX_FINDINGS,
                    "suite_command": corrected,
                    "suite_command_finding_id": "F1",
                    "findings": [
                        {"id": "F1", "severity": "P1",
                         "summary": "wrong suite",
                         "disposition": "fixed"},
                    ],
                    "files_changed": [],
                },
            })
            st.save(path, state)
            driver = drv.Driver(path, runner=runners.MockRunner([]))
            self.assertEqual(
                driver._verification_commands(driver.state["units"][0]),
                [corrected],
            )


class TestUncleanStopRepair(DriverTestCase):
    """A driver killed mid-call leaves its in-flight marker; the next
    startup repairs safely: restore_clean only where the pre-call tree
    was provably HEAD, a KILLED NOTICE where legitimate work is mixed."""

    def _marker(self, ws, kind, label="x-call"):
        import json as _json
        os.makedirs(os.path.join(ws, ".orchestrator"), exist_ok=True)
        with open(os.path.join(ws, ".orchestrator", "current.json"), "w",
                  encoding="utf-8") as fh:
            _json.dump({"label": label, "kind": kind, "family": "codex",
                        "started_at": 0}, fh)

    def _dirty(self, ws):
        with open(os.path.join(ws, "junk-from-dead-worker.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("partial write\n")

    def test_killed_reviewer_in_rounds_restores_clean_tree(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([skeleton_script()[0]])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_ROUNDS,
                max_steps=6,
            )
            # Simulate: reviewer killed mid-call after editing.
            self._dirty(ws)
            self._marker(ws, "review_round")
            driver2 = drv.Driver(path, runner=runners.MockRunner([]))
            self.assertFalse(os.path.exists(
                os.path.join(ws, "junk-from-dead-worker.md")))
            state = st.load(path)
            self.assertTrue([e for e in state["events"]
                             if e["type"] == "unclean_stop_restored"])
            self.assertFalse(os.path.exists(
                os.path.join(ws, ".orchestrator", "current.json")))

    def test_killed_fixer_fresh_episode_restores(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                skeleton_script()[0],
                step("review_round",
                     report("review_round",
                            [finding("F1", "needs non-goals")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING,
                max_steps=8,
            )
            self._dirty(ws)
            self._marker(ws, "fix_findings")
            drv.Driver(path, runner=runners.MockRunner([]))
            self.assertFalse(os.path.exists(
                os.path.join(ws, "junk-from-dead-worker.md")))
            state = st.load(path)
            self.assertTrue([e for e in state["events"]
                             if e["type"] == "unclean_stop_restored"])

    def test_killed_fixer_mid_loop_gets_notice_not_restore(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                skeleton_script()[0],
                step("review_round",
                     report("review_round",
                            [finding("F1", "needs non-goals")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING,
                max_steps=8,
            )
            # Simulate a mid-loop kill: legitimate prior work exists.
            state = st.load(path)
            state["units"][0]["fix_loop_rounds"] = 2
            st.save(path, state)
            self._dirty(ws)
            self._marker(ws, "fix_findings")
            drv.Driver(path, runner=runners.MockRunner([]))
            # Legitimate-looking dirt untouched; notice flag set.
            self.assertTrue(os.path.exists(
                os.path.join(ws, "junk-from-dead-worker.md")))
            state = st.load(path)
            self.assertTrue(state["units"][0].get("killed_fix_notice"))
            self.assertTrue([e for e in state["events"]
                             if e["type"] == "unclean_stop_noticed"])

    def test_clean_marker_from_verification_is_ignored(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            self._marker(ws, "verification")
            drv.Driver(path, runner=runners.MockRunner([]))
            state = st.load(path)
            self.assertFalse([e for e in state["events"]
                              if e["type"].startswith("unclean_stop")])


class TestDocsDirCollision(DriverTestCase):
    def test_reused_name_uniquifies_the_slug(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            git_init_workspace(ws)
            os.makedirs(
                os.path.join(ws, "implementation", "milestones", "my-feat"))
            cfg = make_config(
                docs_dir="implementation/milestones/{slug}")
            path = drv.init_run("goal", ws, config=cfg, name="My Feat")
            state = st.load(path)
            self.assertEqual(
                state["docs_dir"], "implementation/milestones/my-feat-2")

    def test_fixed_docs_dir_collision_refused(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            git_init_workspace(ws)
            os.makedirs(os.path.join(ws, "implementation", "m1"))
            cfg = make_config(docs_dir="implementation/m1")
            with self.assertRaises(FileExistsError):
                drv.init_run("goal", ws, config=cfg, name="x")

    def test_escaping_docs_dir_rejected(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            git_init_workspace(ws)
            cfg = make_config(docs_dir="../outside/{slug}")
            with self.assertRaises(ValueError):
                drv.init_run("goal", ws, config=cfg, name="x")


class TestActProfiles(DriverTestCase):
    """Per-act leadership: who drafts/implements/fixes, with which
    model/effort — configured at launch (config acts) and hot-editable
    mid-run via .orchestrator/acts.json."""

    def test_skeletoner_act_routes_family_and_model(self):
        import json as _json
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config()
            cfg["acts"] = dict(cfg["acts"])
            # The skeleton draft runs the `skeletoner` act, not `drafter`.
            cfg["acts"]["skeletoner"] = {
                "agent": "claude", "model": "sonnet", "effort": "high",
            }
            path = init_state(ws, cfg)
            script = skeleton_script()
            script[0]["expect_family"] = "claude"
            mock = runners.MockRunner([script[0]])
            driver = drv.Driver(path, runner=mock)
            driver.step()
            meta = mock.call_meta[0]
            self.assertEqual(meta["family"], "claude")
            self.assertEqual(meta["model"], "sonnet")
            self.assertEqual(meta["effort"], "high")
            state = st.load(path)
            d = state["units"][0]["draft"]
            self.assertEqual((d["family"], d["model"], d["effort"]),
                             ("claude", "sonnet", "high"))

    def test_family_defaults_fill_when_act_has_no_override(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config()
            cfg["model_defaults"] = {"claude": {"model": "opus",
                                                "effort": "max"}}
            cfg["acts"] = dict(cfg["acts"])
            cfg["acts"]["skeletoner"] = "claude"
            path = init_state(ws, cfg)
            script = skeleton_script()
            script[0]["expect_family"] = "claude"
            mock = runners.MockRunner([script[0]])
            drv.Driver(path, runner=mock).step()
            meta = mock.call_meta[0]
            self.assertEqual((meta["model"], meta["effort"]),
                             ("opus", "max"))

    def test_each_review_family_has_its_own_model(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config()
            cfg["acts"] = dict(cfg["acts"])
            cfg["acts"].update({
                # Deliberately wrong agent fields prove family rotation is
                # fixed: these acts tune model/effort only.
                "review_codex": {
                    "agent": "claude", "model": "gpt-5.6-terra",
                    "effort": "high",
                },
                "review_claude": {
                    "agent": "codex", "model": "claude-sonnet-5",
                    "effort": "medium",
                },
            })
            path = init_state(ws, cfg)
            mock = runners.MockRunner([
                skeleton_script()[0],
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)

            by_call = {
                (family, kind): meta
                for (family, kind, _prompt), meta
                in zip(mock.calls, mock.call_meta)
            }
            self.assertEqual(
                (by_call[("codex", "review_round")]["model"],
                 by_call[("codex", "review_round")]["effort"]),
                ("gpt-5.6-terra", "high"),
            )
            self.assertEqual(
                (by_call[("claude", "review_round")]["model"],
                 by_call[("claude", "review_round")]["effort"]),
                ("claude-sonnet-5", "medium"),
            )

            unit = st.load(path)["units"][0]
            reviews = [r for r in unit["rounds"]
                       if r["kind"] == contracts.KIND_REVIEW_ROUND]
            self.assertEqual(
                [(r["family"], r["model"], r["effort"]) for r in reviews],
                [("codex", "gpt-5.6-terra", "high"),
                 ("claude", "claude-sonnet-5", "medium")],
            )
            self.assertEqual(unit["seals"][0]["halves"], {})

    def test_hot_review_model_rebinds_the_next_delta_review(self):
        import json as _json
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config()
            cfg["model_defaults"] = {
                "codex": {"model": "gpt-5.5", "effort": "xhigh"},
                "claude": {"model": "claude-opus-5", "effort": "max"},
            }
            path = init_state(ws, cfg)
            mock = runners.MockRunner(skeleton_script()[:4])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda state: st.current_unit(state)["status"]
                == st.U_DELTA_REVIEW,
            )

            # The operator changes the Codex review model while the run is
            # alive. The immediately following delta review must pick it up;
            # no driver restart and no mutation of the frozen config.
            with open(os.path.join(os.path.dirname(path), "acts.json"),
                      "w", encoding="utf-8") as fh:
                _json.dump({
                    "review_codex": {
                        "model": "gpt-5.6-luna", "effort": "low",
                    },
                }, fh)
            driver.step()

            self.assertEqual(mock.calls[-1][1], contracts.KIND_DELTA_REVIEW)
            self.assertEqual(
                (mock.call_meta[-1]["model"], mock.call_meta[-1]["effort"]),
                ("gpt-5.6-luna", "low"),
            )
            delta = st.load(path)["units"][0]["rounds"][-1]
            self.assertEqual(delta["kind"], contracts.KIND_DELTA_REVIEW)
            self.assertEqual(
                (delta["model"], delta["effort"]),
                ("gpt-5.6-luna", "low"),
            )

    def test_hot_overlay_rebinds_fixer_mid_run(self):
        import json as _json
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            script = skeleton_script()
            mock = runners.MockRunner(script[:2])
            driver = drv.Driver(path, runner=mock)
            driver.step()  # draft
            driver.step()  # verify gate
            driver.step()  # codex review (finding queued)
            # Operator hot-edits the fixer act before the fix call.
            os.makedirs(os.path.join(ws, ".orchestrator"), exist_ok=True)
            with open(os.path.join(ws, ".orchestrator", "acts.json"),
                      "w", encoding="utf-8") as fh:
                _json.dump({"fixer": {"agent": "claude",
                                      "model": "haiku",
                                      "effort": "low"}}, fh)
            fam, model, effort = driver._act_profile(
                "fixer", "codex", default_family="codex")
            self.assertEqual((fam, model, effort),
                             ("claude", "haiku", "low"))
            # And a corrupt overlay degrades to config, never crashes.
            with open(os.path.join(ws, ".orchestrator", "acts.json"),
                      "w", encoding="utf-8") as fh:
                fh.write("{broken")
            fam, model, effort = driver._act_profile(
                "fixer", "codex", default_family="codex")
            self.assertEqual(fam, "codex")


class TestFixerProtocolFailures(DriverTestCase):
    def _dirty_round_prefix(self):
        return [
            skeleton_script()[0],  # draft ok
            step("review_round",
                 report("review_round",
                        [finding("F1", "skeleton lacks explicit non-goals")]),
                 family="codex"),
        ]

    def test_fixer_coverage_violation_fails_run(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner(self._dirty_round_prefix() + [
                step("fix_findings",
                     fix_ok([triaged("X9", "fixed", "some invented finding")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            self.assert_failed(
                path, driver,
                ["triage must cover exactly the queued findings",
                 "queued=['F1']", "got=['X9']"],
                unit_key="skeleton",
            )

    def test_unavailable_consultation_retries_the_same_fix_episode(self):
        retry = {
            "status": "retry",
            "kind": contracts.KIND_FIX_FINDINGS,
            "retry_reason": contracts.RETRY_CONSULTATION_UNAVAILABLE,
            "notes": "opposite family did not return a clear result",
        }
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner(
                self._dirty_round_prefix()
                + [step("fix_findings", retry, family="codex")]
            )
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)

            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(state["failure"]["type"], "unknown")
            self.assertIn("consultation unavailable",
                          state["failure"]["reason"])
            self.assertEqual(unit["status"], st.U_FAILED)
            self.assertEqual(unit["failed_from"], st.U_FIXING)
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F1"])
            self.assertFalse([
                r for r in unit["rounds"]
                if r["kind"] == contracts.KIND_FIX_FINDINGS
            ])
            self.assertTrue(unit.get("killed_fix_notice"))

            st.resume_run(state)
            self.assertEqual(unit["status"], st.U_FIXING)
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F1"])
            self.assertIsNone(state["failure"])

    def test_rejected_without_consultation_is_protocol_error(self):
        bad = fix_ok([triaged("F1", "rejected",
                              "skeleton lacks explicit non-goals",
                              consultation=None)])
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner(self._dirty_round_prefix() + [
                step("fix_findings", bad, family="codex"),
                step("fix_findings", bad, family="codex"),  # repair retry
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            # Exactly one repair retry happened.
            fix_calls = [c for c in mock.calls if c[1] == "fix_findings"]
            self.assertEqual(len(fix_calls), 2)
            self.assertIn("REPAIR:", fix_calls[1][2])
            self.assert_failed(
                path, driver,
                ["fix_findings call failed",
                 "contract-violating output twice",
                 "consultation"],
                unit_key="skeleton",
            )
            # Raw texts of both violating attempts were persisted.
            raw_dir = os.path.join(ws, ".orchestrator", "raw")
            protoerrs = [n for n in os.listdir(raw_dir) if "protoerr" in n]
            self.assertEqual(len(protoerrs), 2)

    def test_rejected_adjudicated_with_unknown_ref_fails_run(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner(self._dirty_round_prefix() + [
                step("fix_findings",
                     fix_ok([triaged("F1", "rejected_adjudicated",
                                     "skeleton lacks explicit non-goals",
                                     adjudication_ref="ghost/F9")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            self.assert_failed(
                path, driver,
                ["rejected_adjudicated with unknown", "ghost/F9"],
                unit_key="skeleton",
            )

    def test_contests_with_unknown_rejection_id_fails_run(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step("review_round",
                     report("review_round", [finding(
                         "F1", "re-raising a settled point",
                         contests={"rejection_id": "nope/F1",
                                   "new_evidence": "made-up evidence"})]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            _actions, final = self.drive(driver)
            self.assertEqual(final.type, drv.A_FAILED)
            self.assertEqual(mock.script, [])
            self.assert_failed(
                path, driver,
                ["contests unknown adjudication", "nope/F1"],
                unit_key="skeleton",
            )


# ---------------------------------------------------------------------------
# (l) git disabled: the legacy direct-return path


class TestGitDisabledLegacyPath(DriverTestCase):
    def test_fix_episode_restarts_reviews_without_delta_or_amend(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(git={"enabled": False}))
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft (writes docs/skeleton.md)
                step("review_round",
                     report("review_round",
                            [finding("F1", "skeleton lacks non-goals")]),
                     family="codex"),
                step("fix_findings",
                     fix_ok([triaged("F1", "fixed",
                                     "skeleton lacks non-goals")],
                            files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\n## Non-goals\n")),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])

            # No repo was ever created, no delta review ever ran.
            self.assertFalse(os.path.exists(os.path.join(ws, ".git")))
            self.assertEqual(
                [c for c in mock.calls if c[1] == "delta_review"], [])

            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(
                [r["kind"] for r in unit["rounds"]],
                ["review_round", "fix_findings", "review_round",
                 "review_round"],
            )
            transitions = [
                (e["from_status"], e["to_status"])
                for e in state["events"]
                if e["type"] == "unit_transition" and e["unit"] == "skeleton"
            ]
            # Without Git there is no delta artefact, but changed bytes still
            # invalidate prior approvals and restart mechanical verification.
            self.assertIn((st.U_FIXING, st.U_PRE_REVIEW_VERIFY), transitions)
            self.assertNotIn(
                st.U_DELTA_REVIEW,
                [t for pair in transitions for t in pair],
            )
            types = [e["type"] for e in state["events"]]
            self.assertNotIn("wip_commit", types)
            self.assertNotIn("amended", types)
            self.assertNotIn("gate_commit", types)
            self.assertIsNone(unit["gate_commit"])


# ---------------------------------------------------------------------------
# git enabled without a deliberately created ledger repo: run refused


class TestGitEnabledNonRepoWorkspace(DriverTestCase):
    def test_missing_ledger_repo_fails_run_with_the_git_error(self):
        # Flip of the old auto-init behavior: ensure_repo no longer
        # initializes a repo for a git-enabled run. Driver construction
        # records the terminal failure (before any worker call) with the
        # GitError explanation, and no repo materializes behind the refusal.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            state = st.new_state(GOAL, ws, make_config())
            st.append_event(state, "initialized", goal=GOAL)
            path = drv.default_state_path(ws)
            st.save(path, state)  # deliberately NO git init
            mock = runners.MockRunner([])
            driver = drv.Driver(path, runner=mock)
            self.assert_failed(
                path, driver,
                ["git unavailable",
                 "is not the root of a git repository",
                 "create the ledger repo deliberately"],
            )
            self.assertEqual(mock.calls, [])  # no worker call was made
            self.assertFalse(os.path.exists(os.path.join(ws, ".git")))


# ---------------------------------------------------------------------------
# (m) resume mid-flow


class TestResume(DriverTestCase):
    def test_new_driver_mid_fix_episode_continues_to_close(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())

            # Phase 1: stop mid-flow, INSIDE an open fix episode.
            mock1 = runners.MockRunner([
                skeleton_script()[0],
                step("review_round",
                     report("review_round",
                            [finding("F1", "skeleton lacks non-goals")]),
                     family="codex"),
            ])
            driver1 = drv.Driver(path, runner=mock1)
            self.step_until(driver1,
                            lambda s: s["units"][0]["status"] == st.U_FIXING)
            self.assertEqual(mock1.script, [])

            mid = st.load(path)
            self.assertEqual(mid["units"][0]["fix_queue"][0]["id"], "F1")
            events_before = copy.deepcopy(mid["events"])
            rounds_before = copy.deepcopy(mid["units"][0]["rounds"])

            # Phase 2: a brand-new Driver over the same state file (fresh
            # ensure_repo: the baseline must NOT be re-staged) continues the
            # episode and the rest of the milestone.
            mock2 = runners.MockRunner([
                step("fix_findings",
                     fix_ok([triaged("F1", "fixed",
                                     "skeleton lacks non-goals")],
                            files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\n## Non-goals\n")),
                step("delta_review", report("delta_review"), family="codex"),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ] + doc_script() + [
                step("implement",
                     ok("implement", files_changed=["calculator.py"]),
                     family="codex",
                     side_effect=write_file("calculator.py",
                                            "def div(a, b):\n"
                                            "    return a / b\n")),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ])
            driver2 = drv.Driver(path, runner=mock2)
            _actions, final = self.drive(driver2)
            self.assertEqual(final.type, drv.A_DONE)
            self.assertEqual(mock2.script, [])

            state = st.load(path)
            self.assertEqual(state["milestone"]["status"], st.M_CLOSED)
            self.assertEqual([u["status"] for u in state["units"]],
                             [st.U_SEALED, st.U_SEALED, st.U_SEALED])
            # Pre-resume history intact: events are a strict prefix and the
            # recorded rounds were never rewritten.
            self.assertEqual(state["events"][: len(events_before)],
                             events_before)
            self.assertGreater(len(state["events"]), len(events_before))
            self.assertEqual(
                state["units"][0]["rounds"][: len(rounds_before)],
                rounds_before,
            )
            self.assertEqual(
                [s for _, s in git_subjects(ws)],
                [GATE_MSG_INIT, GATE_MSG_SKELETON, GATE_MSG_NOTE,
                 GATE_MSG_IMPL, GATE_MSG_CLOSE],
            )


if __name__ == "__main__":
    unittest.main()
