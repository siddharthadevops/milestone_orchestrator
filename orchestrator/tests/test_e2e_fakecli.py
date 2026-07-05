"""End-to-end test: the calculator scenario with REAL subprocesses.

Builds the same config as examples/calculator/run_demo.sh (worker commands
run python3 on examples/calculator/fake_llm.py; verification is
"python3 run_checks.py"; git gates enabled; fixer and delta reviews pinned
to codex like the demo), then drives the flow exclusively through the CLI
entrypoints (`python3 -m orchestrator.driver init/run/status --json`) with
cwd at the repo root, exactly like an operator would.

The scenario exercises the review/fix separation model end to end:
  skeleton: codex reported finding -> fixer fixes -> clean delta -> amend;
    claude reported finding -> fixer REJECTS (consultation + prevention);
    claude stubbornly re-raises without contests -> fixer kills it by
    pointer (rejected_adjudicated citing skeleton-claude-r1/F1); claude
    clean; double seal passes.
  slice note: clean everywhere.
  implementation: deliberate div bug -> pre-review verification fails ->
    fix episode; codex docstring finding -> fix episode; seal a1 fails on
    the claude README finding -> fix episode -> seal a2 passes; milestone
    closes.

The run happens once in setUpClass; each test asserts one aspect.

With git enabled the workspace (a TemporaryDirectory OUTSIDE this canon
repository) becomes its OWN git repo: one amended commit per unit
finalized under the canonical gate message, generated ledgers (including
docs/adjudications.md) folded into every gate, and — the incident this
suite regression-proofs — the ENCLOSING canon repository is never touched
by the run.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from orchestrator import state as st

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FAKE_LLM = os.path.join(
    REPO, "orchestrator", "examples", "calculator", "fake_llm.py"
)
GOAL = "Build a small CLI calculator (add/sub/mul/div) with unit tests"

ADJ_ID = "skeleton-claude-r1/F1"

# The five canonical gate messages, newest first (git log order). Wip
# commits are amended away: nothing else may appear in the history.
GATE_MESSAGES = [
    "Close milestone",
    "Seal slice 01 implementation and close",
    "Seal slice 01 note",
    "Seal milestone skeleton",
    "Initialize milestone workspace",
]


def _git(repo, *args):
    """Git helper: the one deliberate `init` on the temp workspace in
    setUpClass, read-only queries (status/log/ls-tree/show/rev-parse)
    everywhere else."""
    return subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestCalculatorE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="orch-e2e-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.work = os.path.join(cls.tmp.name, "work")
        os.makedirs(cls.work)
        # The operator's deliberate ledger repo: ensure_repo no longer
        # auto-inits, so a git-enabled run requires the workspace to
        # already be the root of its own repository (run_demo.sh does
        # exactly this before `driver init`).
        _git(cls.work, "init", "-q")

        # Incident regression baseline: the enclosing canon repo before the
        # run. The run must leave both the worktree status and HEAD alone.
        cls.canon_status_before = _git(REPO, "status", "--porcelain").stdout
        cls.canon_head_before = _git(REPO, "log", "-1", "--format=%H").stdout

        # Same shape as examples/calculator/run_demo.sh's generated config.
        config = {
            "commands": {
                "codex": ["python3", FAKE_LLM, "--workspace", "{workspace}"],
                "claude": ["python3", FAKE_LLM, "--workspace", "{workspace}"],
            },
            "timeouts": {"codex": 60, "claude": 60},
            "verification": ["python3 run_checks.py"],
            "max_rounds_per_family": 6,
            "max_seal_attempts": 4,
            "git": {"enabled": True},
            "acts": {
                "fixer": "codex",
                "delta_review": "codex",
                "consultation": "opposite",
            },
            "max_fix_loops": 4,
        }
        cfg_path = os.path.join(cls.tmp.name, "demo-config.json")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)

        cls.p_init = cls._cli(
            "init", "--goal", GOAL, "--workspace", cls.work,
            "--config", cfg_path,
        )
        cls.p_run = cls._cli("run", "--workspace", cls.work)
        cls.p_status = cls._cli("status", "--workspace", cls.work, "--json")
        try:
            cls.parsed_summary = json.loads(cls.p_status.stdout)
        except ValueError:
            cls.parsed_summary = None

        cls.canon_status_after = _git(REPO, "status", "--porcelain").stdout
        cls.canon_head_after = _git(REPO, "log", "-1", "--format=%H").stdout

    @classmethod
    def _cli(cls, *args):
        return subprocess.run(
            [sys.executable, "-m", "orchestrator.driver"] + list(args),
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=300,
        )

    # -- helpers ------------------------------------------------------------

    def summary(self):
        self.assertEqual(
            self.p_status.returncode, 0,
            "status failed: %s" % self.p_status.stderr,
        )
        self.assertIsNotNone(
            self.parsed_summary,
            "status --json did not print valid JSON:\n%s" % self.p_status.stdout,
        )
        return self.parsed_summary

    def unit(self, key):
        for u in self.summary()["units"]:
            if u["unit"] == key:
                return u
        self.fail("unit %s not in status summary" % key)

    def disk_state(self):
        return st.load(os.path.join(self.work, ".orchestrator", "state.json"))

    def state_unit(self, key):
        """The full on-disk unit record (summary() omits e.g. gate_commit)."""
        for u in self.disk_state()["units"]:
            if st.unit_key(u) == key:
                return u
        self.fail("unit %s not in on-disk state" % key)

    def fix_rounds(self, unit):
        return [r for r in unit["rounds"] if r["kind"] == "fix_findings"]

    def git_work(self, *args):
        proc = _git(self.work, *args)
        self.assertEqual(
            proc.returncode, 0,
            "git %s failed in workspace: %s" % (" ".join(args), proc.stderr),
        )
        return proc.stdout

    def _diag(self, proc):
        return "exit=%d\nstdout:\n%s\nstderr:\n%s" % (
            proc.returncode, proc.stdout, proc.stderr,
        )

    # -- CLI surface ----------------------------------------------------------

    def test_cli_exit_codes_and_output(self):
        self.assertEqual(self.p_init.returncode, 0, self._diag(self.p_init))
        self.assertIn("initialized:", self.p_init.stdout)
        self.assertEqual(self.p_run.returncode, 0, self._diag(self.p_run))
        self.assertIn("milestone closed", self.p_run.stdout)
        self.assertEqual(self.p_status.returncode, 0,
                         self._diag(self.p_status))

    def test_milestone_closed_and_all_units_sealed(self):
        summ = self.summary()
        self.assertEqual(summ["milestone_status"], "closed")
        self.assertIsNone(summ["failure"])
        self.assertIsNone(summ["current_unit"])
        self.assertIsNone(summ["current_unit_status"])
        self.assertEqual(
            [(u["unit"], u["status"]) for u in summ["units"]],
            [
                ("skeleton", "sealed"),
                ("slice_doc-01", "sealed"),
                ("slice_impl-01", "sealed"),
            ],
        )
        self.assertEqual(
            summ["slices"], [{"id": 1, "title": "Calculator core"}]
        )

    def test_status_json_matches_summary_shape(self):
        summ = self.summary()
        self.assertEqual(
            set(summ.keys()),
            {
                "goal",
                "workspace",
                "milestone_status",
                "slices",
                "current_unit",
                "current_unit_status",
                "current_family",
                "created_epoch",
                "last_event_epoch",
                "failure",
                "units",
                "events_total",
                "last_events",
            },
        )
        self.assertEqual(summ["goal"], GOAL)
        self.assertEqual(summ["workspace"], self.work)
        self.assertIsInstance(summ["events_total"], int)
        self.assertIsInstance(summ["last_events"], list)
        self.assertLessEqual(len(summ["last_events"]), 30)
        self.assertGreaterEqual(summ["events_total"], len(summ["last_events"]))
        for u in summ["units"]:
            self.assertEqual(
                set(u.keys()),
                {"unit", "status", "artifact", "rounds", "seals"},
            )
        # The CLI's JSON is exactly state.summary() over the on-disk state.
        self.assertEqual(summ, st.summary(self.disk_state()))

    # -- the known-good baseline: round counts and kind sequences -------------

    def test_skeleton_round_sequence(self):
        skeleton = self.unit("skeleton")
        self.assertEqual(len(skeleton["rounds"]), 10)
        self.assertEqual(
            [(r["id"], r["kind"]) for r in skeleton["rounds"]],
            [
                ("skeleton-codex-r1", "review_round"),
                ("skeleton-codex-r2", "fix_findings"),
                ("skeleton-codex-r3", "delta_review"),
                ("skeleton-codex-r4", "review_round"),
                ("skeleton-claude-r1", "review_round"),
                ("skeleton-codex-r5", "fix_findings"),
                ("skeleton-codex-r6", "delta_review"),
                ("skeleton-claude-r2", "review_round"),
                ("skeleton-codex-r7", "fix_findings"),
                ("skeleton-claude-r3", "review_round"),
            ],
        )
        # Reviewers report; the last round of each family is clean.
        self.assertEqual(skeleton["rounds"][0]["findings"], 1)
        self.assertEqual(skeleton["rounds"][-1]["findings"], 0)
        self.assertEqual(
            [(s["attempt"], s["passed"]) for s in skeleton["seals"]],
            [(1, True)],
        )

    def test_doc_unit_is_clean_everywhere(self):
        doc = self.unit("slice_doc-01")
        self.assertEqual(
            [(r["id"], r["kind"], r["findings"]) for r in doc["rounds"]],
            [
                ("slice_doc-01-codex-r1", "review_round", 0),
                ("slice_doc-01-claude-r1", "review_round", 0),
            ],
        )
        self.assertEqual(
            [(s["attempt"], s["passed"]) for s in doc["seals"]], [(1, True)]
        )

    def test_impl_round_sequence(self):
        impl = self.unit("slice_impl-01")
        self.assertEqual(len(impl["rounds"]), 9)
        self.assertEqual(
            [(r["id"], r["kind"]) for r in impl["rounds"]],
            [
                ("slice_impl-01-codex-r1", "fix_findings"),
                ("slice_impl-01-codex-r2", "delta_review"),
                ("slice_impl-01-codex-r3", "review_round"),
                ("slice_impl-01-codex-r4", "fix_findings"),
                ("slice_impl-01-codex-r5", "delta_review"),
                ("slice_impl-01-codex-r6", "review_round"),
                ("slice_impl-01-claude-r1", "review_round"),
                ("slice_impl-01-codex-r7", "fix_findings"),
                ("slice_impl-01-codex-r8", "delta_review"),
            ],
        )

    def test_review_findings_carry_no_disposition(self):
        # Whoever detects never fixes: report rounds record findings
        # without dispositions; triage lives only in fix_findings rounds.
        for key in ("skeleton", "slice_doc-01", "slice_impl-01"):
            unit = self.state_unit(key)
            for r in unit["rounds"]:
                if r["kind"] in ("review_round", "delta_review"):
                    for f in r["result"].get("findings", []):
                        self.assertIsNone(
                            f.get("disposition"),
                            "reviewer finding %s in %s carries a disposition"
                            % (f.get("id"), r["id"]),
                        )

    # -- verification-failure fix episode --------------------------------------

    def test_div_bug_verification_failure_went_through_the_fix_loop(self):
        impl = self.state_unit("slice_impl-01")
        vfix = self.fix_rounds(impl)[0]
        self.assertEqual(vfix["id"], "slice_impl-01-codex-r1")
        self.assertEqual(vfix["family"], "codex")
        self.assertEqual(
            vfix["source_round_id"], "slice_impl-01-verify-pre_review-1"
        )
        self.assertEqual(
            [(f["id"], f["disposition"]) for f in vfix["result"]["findings"]],
            [("V1", "fixed")],
        )
        # Exactly one verification failure, at the pre-review stage.
        events = self.disk_state()["events"]
        failed = [
            e for e in events if e["type"] == "verification" and not e["ok"]
        ]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["stage"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(failed[0]["unit"], "slice_impl-01")

    def test_div_bug_was_fixed_in_workspace(self):
        calc_path = os.path.join(self.work, "calculator.py")
        self.assertTrue(os.path.exists(calc_path))
        with open(calc_path, "r", encoding="utf-8") as fh:
            calc = fh.read()
        self.assertIn("return a / b", calc)
        self.assertNotIn("BUG: should divide", calc)
        # The codex impl review finding produced the module docstring fix.
        self.assertTrue(calc.startswith('"""Tiny CLI calculator'))
        # The seal-finding fix episode wrote the README the claude seal
        # half demanded.
        self.assertTrue(os.path.exists(os.path.join(self.work, "README.md")))

    # -- adjudicated rejections -------------------------------------------------

    def test_rejection_dispositions_in_state(self):
        skeleton = self.state_unit("skeleton")
        fixes = self.fix_rounds(skeleton)
        self.assertEqual(
            [
                (r["id"], r["source_round_id"],
                 r["result"]["findings"][0]["disposition"])
                for r in fixes
            ],
            [
                ("skeleton-codex-r2", "skeleton-codex-r1", "fixed"),
                ("skeleton-codex-r5", "skeleton-claude-r1", "rejected"),
                ("skeleton-codex-r7", "skeleton-claude-r2",
                 "rejected_adjudicated"),
            ],
        )
        rejected = fixes[1]["result"]["findings"][0]
        self.assertTrue(rejected["consultation"]["resolution"])
        self.assertEqual(
            rejected["prevention"]["documented_in"], "docs/skeleton.md"
        )
        # The stubborn duplicate died by pointer: the exact registry ref,
        # zero new consultations.
        duplicate = fixes[2]["result"]["findings"][0]
        self.assertEqual(duplicate["adjudication_ref"], ADJ_ID)
        self.assertIsNone(duplicate["consultation"])

    def test_adjudication_registry_derived_from_state(self):
        state = self.disk_state()
        entries = st.adjudicated_rejections(state)
        self.assertEqual([e["id"] for e in entries], [ADJ_ID])
        entry = entries[0]
        self.assertEqual(entry["unit"], "skeleton")
        self.assertEqual(entry["severity"], "P3")
        self.assertIn("float", entry["summary"])
        self.assertTrue(entry["rationale"])
        self.assertEqual(
            entry["prevention"]["documented_in"], "docs/skeleton.md"
        )
        self.assertEqual(st.registry_ids(state), {ADJ_ID})

    def test_prevention_edit_lives_in_the_skeleton_document(self):
        with open(
            os.path.join(self.work, "docs", "skeleton.md"), encoding="utf-8"
        ) as fh:
            skeleton_md = fh.read()
        self.assertIn("## Non-goals", skeleton_md)  # the conceded fix
        self.assertIn("float", skeleton_md)         # the prevention edit

    def test_adjudications_ledger_committed_at_the_gate(self):
        adjudications = self.git_work("show", "HEAD:docs/adjudications.md")
        self.assertIn("<!-- GENERATED by the orchestrator", adjudications)
        self.assertIn("# Adjudicated Rejections", adjudications)
        self.assertIn("## [%s]" % ADJ_ID, adjudications)
        self.assertIn("- unit: skeleton", adjudications)
        self.assertIn("opposite family agreed", adjudications)
        self.assertIn(
            "- prevention: docs/skeleton.md (explicit float-support note "
            "added)",
            adjudications,
        )

    # -- seals ------------------------------------------------------------------

    def test_impl_unit_seal_a1_failed_then_a2_passed(self):
        impl = self.unit("slice_impl-01")
        self.assertEqual(
            [(s["attempt"], s["passed"], s["invalidated"])
             for s in impl["seals"]],
            [(1, False, None), (2, True, None)],
        )
        self.assertEqual(impl["seals"][0]["findings"],
                         {"codex": 0, "claude": 1})
        self.assertEqual(impl["seals"][1]["findings"],
                         {"codex": 0, "claude": 0})
        # The seal-finding fix episode returned to pre-seal verification:
        # its fix round cites the seal attempt as its source.
        seal_fix = self.fix_rounds(self.state_unit("slice_impl-01"))[-1]
        self.assertEqual(seal_fix["source_round_id"], "slice_impl-01-seal-a1")
        self.assertEqual(
            [(f["id"], f["disposition"]) for f in seal_fix["result"]["findings"]],
            [("claude-S1", "fixed")],
        )

    # -- raw worker outputs -------------------------------------------------------

    def test_raw_worker_outputs_exist(self):
        raw_dir = os.path.join(self.work, ".orchestrator", "raw")
        self.assertTrue(os.path.isdir(raw_dir))
        expected = [
            "skeleton-draft.txt",
            "skeleton-codex-r1.txt",
            "skeleton-claude-r1.txt",
            "skeleton-claude-r2.txt",
            "skeleton-claude-r3.txt",
            "skeleton-fix1.txt",
            "skeleton-fix2.txt",
            "skeleton-fix3.txt",
            "skeleton-delta1.txt",
            "skeleton-delta2.txt",
            "skeleton-seal-a1-codex.txt",
            "skeleton-seal-a1-claude.txt",
            "slice_doc-01-draft.txt",
            "slice_impl-01-draft.txt",
            "slice_impl-01-fix1.txt",
            "slice_impl-01-fix2.txt",
            "slice_impl-01-fix3.txt",
            "slice_impl-01-delta1.txt",
            "slice_impl-01-delta2.txt",
            "slice_impl-01-delta3.txt",
            "slice_impl-01-seal-a1-claude.txt",
            "slice_impl-01-seal-a2-codex.txt",
            "slice_impl-01-seal-a2-claude.txt",
        ]
        present = set(os.listdir(raw_dir))
        for name in expected:
            self.assertIn(name, present)
            path = os.path.join(raw_dir, name)
            self.assertGreater(os.path.getsize(path), 0,
                               "%s is empty" % name)
        # Raw outputs are the workers' verbatim JSON replies.
        with open(os.path.join(raw_dir, "slice_impl-01-seal-a1-claude.txt"),
                  "r", encoding="utf-8") as fh:
            half = json.loads(fh.read())
        self.assertEqual(half["kind"], "seal_half")
        self.assertEqual(len(half["findings"]), 1)

    # -- git gates ------------------------------------------------------------

    def test_workspace_is_its_own_repo_with_canonical_gate_commits(self):
        # The workspace repo root is the workspace itself (nested-repo
        # protection would have hard-failed otherwise).
        toplevel = self.git_work("rev-parse", "--show-toplevel").strip()
        self.assertEqual(
            os.path.realpath(toplevel), os.path.realpath(self.work)
        )
        # Exactly the five canonical gate messages, in gate order: wip
        # commits were amended away, no patch stacking.
        subjects = self.git_work("log", "--format=%s").strip().splitlines()
        self.assertEqual(subjects, GATE_MESSAGES)
        # Each sealed unit recorded the short sha of ITS gate commit.
        sha_by_subject = {}
        for line in self.git_work("log", "--format=%h %s").strip().splitlines():
            sha, subject = line.split(" ", 1)
            sha_by_subject[subject] = sha
        for unit_key, subject in (
            ("skeleton", "Seal milestone skeleton"),
            ("slice_doc-01", "Seal slice 01 note"),
            ("slice_impl-01", "Seal slice 01 implementation and close"),
        ):
            self.assertEqual(
                self.state_unit(unit_key)["gate_commit"],
                sha_by_subject[subject],
                "gate_commit mismatch for %s" % unit_key,
            )
        # The workspace ends clean: everything reviewable is committed.
        self.assertEqual(self.git_work("status", "--porcelain"), "")

    def test_amend_discipline_events(self):
        events = self.disk_state()["events"]
        # One wip commit per unit.
        wips = [e for e in events if e["type"] == "wip_commit"]
        self.assertEqual(
            [e["unit"] for e in wips],
            ["skeleton", "slice_doc-01", "slice_impl-01"],
        )
        # One amend per green fix episode: two on the skeleton, three on
        # the implementation (verification fix, docstring fix, seal fix).
        amends = [e for e in events if e["type"] == "amended"]
        self.assertEqual(
            [e["unit"] for e in amends],
            ["skeleton", "skeleton",
             "slice_impl-01", "slice_impl-01", "slice_impl-01"],
        )
        # Gate commits: three unit gates plus the milestone close.
        gates = [e for e in events if e["type"] == "gate_commit"]
        self.assertEqual(
            [(e["unit"], e["message"]) for e in gates],
            [
                ("skeleton", "Seal milestone skeleton"),
                ("slice_doc-01", "Seal slice 01 note"),
                ("slice_impl-01", "Seal slice 01 implementation and close"),
                (None, "Close milestone"),
            ],
        )

    def test_ledgers_committed_and_orchestrator_dir_ignored(self):
        files = set(
            self.git_work("ls-tree", "-r", "--name-only", "HEAD")
            .strip()
            .splitlines()
        )
        self.assertIn("docs/MILESTONE.md", files)
        self.assertIn("docs/review-log.md", files)
        self.assertIn("docs/adjudications.md", files)
        self.assertIn("docs/closures/slice-01.md", files)
        # Runtime bookkeeping never enters a gate commit.
        self.assertFalse(
            [f for f in files if f.startswith(".orchestrator")],
            ".orchestrator/ leaked into a gate commit",
        )
        with open(os.path.join(self.work, ".gitignore"),
                  "r", encoding="utf-8") as fh:
            self.assertIn(".orchestrator/", fh.read())
        # The committed ledgers are the generated views of the final state.
        milestone_md = self.git_work("show", "HEAD:docs/MILESTONE.md")
        self.assertIn("<!-- GENERATED by the orchestrator", milestone_md)
        self.assertIn("Status: **closed**", milestone_md)
        review_log = self.git_work("show", "HEAD:docs/review-log.md")
        self.assertIn("# Review Log", review_log)
        self.assertIn("fix_findings", review_log)
        self.assertIn("delta_review", review_log)
        self.assertIn("1 rejected_adjudicated", review_log)

    # -- incident regression: the enclosing canon repo is untouched ------------

    def test_enclosing_canon_repo_untouched(self):
        # The first demo run polluted the enclosing canon repository when
        # the workspace was nested inside it. The workspace here is a
        # TemporaryDirectory outside the canon repo AND gitops hard-fails
        # every mutating op on a non-root workspace; either way, the canon
        # repo must be byte-for-byte unaffected by the whole run.
        self.assertEqual(self.canon_status_before, self.canon_status_after,
                         "canon repo worktree status changed during the run")
        self.assertEqual(self.canon_head_before, self.canon_head_after,
                         "canon repo HEAD changed during the run")


if __name__ == "__main__":
    unittest.main()
