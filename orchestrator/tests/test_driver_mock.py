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
      fix_findings and delta_review records, seal records, gate_commit
      fields, ledgers, milestone closed);
  (e) seal findings from BOTH halves merged with family-prefixed ids;
  (h) seal-half tampering: attempt invalidated, workspace restored, next
      attempt runs;
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

from orchestrator import driver as drv
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
        "max_seal_attempts": 4,
        "max_verify_fix_attempts": 2,
        "seal_concurrent": False,
        "git": {"enabled": True},
        "acts": {"fixer": "codex", "delta_review": "codex",
                 "consultation": "opposite"},
        "max_fix_loops": 6,
        "snapshot_exclude_dirs": [],
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
    """A report-only response (review_round / delta_review / seal_half)."""
    return ok(kind, findings=list(findings))


def finding(fid, summary, severity="P3", contests=None):
    f = {"id": fid, "severity": severity, "summary": summary}
    if contests is not None:
        f["contests"] = contests
    return f


def triaged(fid, disposition, summary="triaged finding", severity="P3",
            consultation=None, prevention=None, adjudication_ref=None):
    entry = {
        "id": fid,
        "severity": severity,
        "summary": summary,
        "disposition": disposition,
        "consultation": consultation,
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
    claude clean; double seal clean."""
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
        step("seal_half", report("seal_half"), family="codex"),
        step("seal_half", report("seal_half"), family="claude"),
    ]


def doc_script():
    """Slice note: clean everywhere, seal first try."""
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
        step("seal_half", report("seal_half"), family="codex"),
        step("seal_half", report("seal_half"), family="claude"),
    ]


def impl_script():
    """div bug -> verification fails -> V1 fix episode; docstring round
    finding -> fix; seal a1 claude README finding -> fix; seal a2 passes."""
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
        step("review_round", report("review_round"), family="claude"),
        # seal a1: claude half reports the missing README
        step("seal_half", report("seal_half"), family="codex"),
        step("seal_half",
             report("seal_half",
                    [finding("S1",
                             "workspace lacks a README describing CLI usage")]),
             family="claude"),
        step("fix_findings",
             fix_ok([triaged(
                 "claude-S1", "fixed",
                 "[claude seal half] workspace lacks a README")],
                 files_changed=["README.md"]),
             family="codex",
             side_effect=write_file("README.md", "# Calculator\n\nUsage.\n")),
        step("delta_review", report("delta_review"), family="codex"),
        step("seal_half", report("seal_half"), family="codex"),
        step("seal_half", report("seal_half"), family="claude"),
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
                 drv.A_REVIEW_ROUND,
                 drv.A_REVIEW_ROUND, drv.A_FIX, drv.A_DELTA_REVIEW,
                 drv.A_REVIEW_ROUND, drv.A_FIX, drv.A_DELTA_REVIEW,
                 drv.A_REVIEW_ROUND,
                 drv.A_VERIFY, drv.A_SEAL_ATTEMPT]
                # slice doc
                + [drv.A_DRAFT, drv.A_VERIFY,
                   drv.A_REVIEW_ROUND, drv.A_REVIEW_ROUND,
                   drv.A_VERIFY, drv.A_SEAL_ATTEMPT]
                # slice impl
                + [drv.A_DRAFT, drv.A_VERIFY,
                   drv.A_FIX, drv.A_DELTA_REVIEW, drv.A_VERIFY,
                   drv.A_REVIEW_ROUND, drv.A_FIX, drv.A_DELTA_REVIEW,
                   drv.A_REVIEW_ROUND, drv.A_REVIEW_ROUND,
                   drv.A_VERIFY, drv.A_SEAL_ATTEMPT,
                   drv.A_FIX, drv.A_DELTA_REVIEW,
                   drv.A_VERIFY, drv.A_SEAL_ATTEMPT]
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
                    ("skeleton-claude-r2", "review_round", "claude"),
                    ("skeleton-codex-r7", "fix_findings", "codex"),
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
                ],
            )

            # Fixer records carry their source round ids.
            fixes = {r["id"]: r for r in skeleton["rounds"] + impl["rounds"]
                     if r["kind"] == "fix_findings"}
            self.assertEqual(fixes["skeleton-codex-r2"]["source_round_id"],
                             "skeleton-codex-r1")
            self.assertEqual(fixes["skeleton-codex-r5"]["source_round_id"],
                             "skeleton-claude-r1")
            self.assertEqual(fixes["skeleton-codex-r7"]["source_round_id"],
                             "skeleton-claude-r2")
            self.assertEqual(fixes["slice_impl-01-codex-r1"]["source_round_id"],
                             "slice_impl-01-verify-pre_review-1")
            self.assertEqual(fixes["slice_impl-01-codex-r4"]["source_round_id"],
                             "slice_impl-01-codex-r3")
            self.assertEqual(fixes["slice_impl-01-codex-r7"]["source_round_id"],
                             "slice_impl-01-seal-a1")

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
                ["claude-S1"],
            )

            # Seal records complete on every unit.
            for unit in state["units"]:
                self.assertTrue(unit["seals"])
                last = unit["seals"][-1]
                self.assertTrue(last["passed"])
                self.assertIsNone(last["invalidated"])
                for seal in unit["seals"]:
                    self.assertEqual(set(seal["halves"]), {"codex", "claude"})
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

            # Impl: a1 failed on the claude finding, a2 passed.
            self.assertEqual(len(impl["seals"]), 2)
            a1, a2 = impl["seals"]
            self.assertEqual((a1["attempt"], a1["passed"], a1["invalidated"]),
                             (1, False, None))
            self.assertEqual(len(a1["halves"]["claude"]["result"]["findings"]), 1)
            self.assertEqual(len(a1["halves"]["codex"]["result"]["findings"]), 0)
            self.assertEqual((a2["attempt"], a2["passed"], a2["invalidated"]),
                             (2, True, None))
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
                             [True, True])
            self.assertEqual(
                [e["ok"] for e in verifs if e["unit"] == "slice_impl-01"],
                [False, True, True, True],
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


# ---------------------------------------------------------------------------
# (e) seal findings from both halves merged for the fixer


class TestSealFindingsMerged(DriverTestCase):
    def test_both_halves_merge_with_family_prefixed_ids(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                # a1: BOTH halves report findings
                step("seal_half",
                     report("seal_half",
                            [finding("S1", "missing usage docs")]),
                     family="codex"),
                step("seal_half",
                     report("seal_half",
                            [finding("S2", "missing error handling note")]),
                     family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda s: (s["units"][0].get("fix_source") or {}).get("type")
                == "seal",
            )
            unit = driver.state["units"][0]
            self.assertEqual(unit["status"], st.U_FIXING)
            self.assertEqual(
                unit["fix_queue"],
                [
                    {"id": "codex-S1", "severity": "P3",
                     "summary": "[codex seal half] missing usage docs",
                     "contests": None},
                    {"id": "claude-S2", "severity": "P3",
                     "summary": "[claude seal half] missing error handling note",
                     "contests": None},
                ],
            )
            self.assertEqual(unit["fix_source"]["source_round_id"],
                             "skeleton-seal-a1")
            self.assertEqual(unit["fix_source"]["return_to"],
                             st.U_PRE_SEAL_VERIFY)

            # Continue: fixer covers exactly the merged ids, delta green,
            # re-verify, second attempt passes.
            mock.script.extend([
                step("fix_findings",
                     fix_ok([
                         triaged("codex-S1", "fixed",
                                 "[codex seal half] missing usage docs"),
                         triaged("claude-S2", "fixed",
                                 "[claude seal half] missing error handling"),
                     ], files_changed=["docs/skeleton.md"]),
                     family="codex",
                     side_effect=append_file("docs/skeleton.md",
                                             "\nUsage + error notes.\n")),
                step("delta_review", report("delta_review"), family="codex"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])

            state = st.load(path)
            unit = state["units"][0]
            a1, a2 = unit["seals"]
            self.assertFalse(a1["passed"])
            self.assertIsNone(a1["invalidated"])
            self.assertTrue(a2["passed"])

            # The fixer prompt carried both family-prefixed findings.
            fix_calls = [c for c in mock.calls if c[1] == "fix_findings"]
            self.assertEqual(len(fix_calls), 1)
            prompt = fix_calls[0][2]
            self.assertIn("codex-S1", prompt)
            self.assertIn("claude-S2", prompt)
            self.assertIn("[codex seal half] missing usage docs", prompt)
            self.assertIn("[claude seal half] missing error handling note",
                          prompt)

            # Re-verify between the failed attempt and the passing one.
            events = state["events"]
            seal_idx = [i for i, e in enumerate(events)
                        if e["type"] == "seal_attempt"]
            self.assertEqual(len(seal_idx), 2)
            verifs_between = [
                e for e in events[seal_idx[0]:seal_idx[1]]
                if e["type"] == "verification"
                and e["stage"] == st.U_PRE_SEAL_VERIFY
            ]
            self.assertTrue(verifs_between,
                            "no pre-seal re-verify before attempt 2")


# ---------------------------------------------------------------------------
# (h) seal half tampering


class TestSealHalfTampering(DriverTestCase):
    def test_tampering_half_invalidates_attempt_restores_and_retries(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            mock = runners.MockRunner([
                skeleton_script()[0],  # draft ok
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                # a1: codex half reports clean but EDITS the workspace
                step("seal_half", report("seal_half"), family="codex",
                     side_effect=write_file("tampered.txt", "sneaky\n")),
                step("seal_half", report("seal_half"), family="claude"),
                # a2: genuinely clean
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])

            # The workspace was mechanically restored.
            self.assertFalse(os.path.exists(os.path.join(ws, "tampered.txt")))

            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(len(unit["seals"]), 2)
            a1, a2 = unit["seals"]
            self.assertFalse(a1["passed"])
            self.assertIn("seal half codex modified the workspace",
                          a1["invalidated"])
            self.assertTrue(a1["halves"]["codex"]["workspace_modified"])
            self.assertFalse(a1["halves"]["claude"]["workspace_modified"])
            self.assertEqual(a1["halves"]["codex"]["result"]["findings"], [])
            self.assertTrue(a2["passed"])
            self.assertIsNone(a2["invalidated"])

            # The unit stayed in U_SEALING between attempts (no fix episode,
            # no re-verify: the invalidated attempt is retried wholesale).
            transitions = [
                (e["from_status"], e["to_status"])
                for e in state["events"]
                if e["type"] == "unit_transition" and e["unit"] == "skeleton"
            ]
            self.assertEqual(
                transitions.count((st.U_SEALING, st.U_SEALED)), 1)
            self.assertNotIn((st.U_SEALING, st.U_FIXING), transitions)
            self.assertNotIn(
                "fix_findings", [r["kind"] for r in unit["rounds"]])


# ---------------------------------------------------------------------------
# (i) fixer protocol enforcement


class TestSealInFlightMarker(DriverTestCase):
    """Seal halves must write the cosmetic in-flight marker
    (.orchestrator/current.json) like every other worker call, so the
    panel can show WHO is sealing and for how long — the double seal is
    the longest phase and used to run with no live counter at all."""

    def test_sequential_seal_halves_write_and_clear_marker(self):
        import json as _json
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())
            seen = []

            def probe(workspace):
                marker = os.path.join(
                    workspace, ".orchestrator", "current.json")
                try:
                    with open(marker, "r", encoding="utf-8") as fh:
                        seen.append(_json.load(fh))
                except OSError:
                    seen.append(None)

            mock = runners.MockRunner([
                skeleton_script()[0],
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex",
                     side_effect=probe),
                step("seal_half", report("seal_half"), family="claude",
                     side_effect=probe),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            self.assertEqual(len(seen), 2)
            for rec in seen:
                self.assertIsNotNone(
                    rec, "no in-flight marker during a seal half")
                self.assertEqual(rec["kind"], "seal_half")
                self.assertIn("started_at", rec)
            self.assertEqual([r["family"] for r in seen],
                             ["codex", "claude"])
            # Cleared once the attempt is over.
            self.assertFalse(os.path.exists(
                os.path.join(ws, ".orchestrator", "current.json")))

    def test_concurrent_seal_writes_attempt_level_marker(self):
        import json as _json
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(seal_concurrent=True))
            seen = []

            def probe(workspace):
                marker = os.path.join(
                    workspace, ".orchestrator", "current.json")
                try:
                    with open(marker, "r", encoding="utf-8") as fh:
                        seen.append(_json.load(fh))
                except OSError:
                    seen.append(None)

            mock = runners.MockRunner([
                skeleton_script()[0],
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex",
                     side_effect=probe),
                step("seal_half", report("seal_half"), family="claude",
                     side_effect=probe),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(len(seen), 2)
            for rec in seen:
                self.assertIsNotNone(
                    rec, "no in-flight marker during concurrent seal")
                self.assertEqual(rec["kind"], "seal_half")
                # Attempt-level marker: one record for both halves, no
                # per-family attribution (threads must not race on it).
                self.assertIsNone(rec["family"])
            self.assertFalse(os.path.exists(
                os.path.join(ws, ".orchestrator", "current.json")))


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
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            # Every worker prompt carried the amendment.
            self.assertEqual(len(mock.calls), 5)
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
                if kind in ("review_round", "seal_half"):
                    has = "VERIFICATION STATUS" in prompt
                    if "slice 1 implementation" in prompt:
                        self.assertTrue(has, kind)
                    else:
                        self.assertFalse(has, kind)


class TestActProfiles(DriverTestCase):
    """Per-act leadership: who drafts/implements/fixes, with which
    model/effort — configured at launch (config acts) and hot-editable
    mid-run via .orchestrator/acts.json."""

    def test_drafter_act_routes_family_and_model(self):
        import json as _json
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config()
            cfg["acts"] = dict(cfg["acts"])
            cfg["acts"]["drafter"] = {
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
            cfg["acts"]["drafter"] = "claude"
            path = init_state(ws, cfg)
            script = skeleton_script()
            script[0]["expect_family"] = "claude"
            mock = runners.MockRunner([script[0]])
            drv.Driver(path, runner=mock).step()
            meta = mock.call_meta[0]
            self.assertEqual((meta["model"], meta["effort"]),
                             ("opus", "max"))

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
    def test_fix_episode_returns_directly_without_delta_or_amend(self):
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
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
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
            # The fix episode went straight back to rounds.
            self.assertIn((st.U_FIXING, st.U_ROUNDS), transitions)
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
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
            ] + doc_script() + [
                step("implement",
                     ok("implement", files_changed=["calculator.py"]),
                     family="codex",
                     side_effect=write_file("calculator.py",
                                            "def div(a, b):\n"
                                            "    return a / b\n")),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half"), family="codex"),
                step("seal_half", report("seal_half"), family="claude"),
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
