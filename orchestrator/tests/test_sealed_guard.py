"""Sealed artifacts are read-only for edit-kind calls — mechanically.

Found live (2026-07-10, LPC rich-content impl-02): a fixer materially
rewrote the SEALED slice note to legalize behaviors the sealed version
forbade, then self-declared the note in its expected files. Nothing
detected it — reviewers are snapshot-enforced but fixers hold edit
permissions, and the amend discipline folded the tampering into the wip
commit (so even HEAD was tainted). The guard compares every SEALED
unit's doc artifact against its own GATE COMMIT after each edit-kind
call: a mismatch is restored from the gate, the illegal bytes land in
raw/, and a sealed_artifact_restored event records the violation.
"""

import os
import subprocess
import tempfile
import unittest

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import gitops
from orchestrator import profiles
from orchestrator import runners
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    finding, fix_ok, init_state, make_config, ok, report, step, triaged,
    write_file, append_file,
)
from orchestrator.tests.test_state import make_halves

GOAL = "Build a small CLI calculator (add/sub/mul/div) with unit tests"


def tamper_skeleton(text):
    def _effect(ws):
        with open(os.path.join(ws, "docs", "skeleton.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(text)
    return _effect


class SealedGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-sealed-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "ws")
        os.makedirs(self.ws)

    def _drive(self, script, stop, max_steps=60):
        path = init_state(self.ws, make_config())  # git ENABLED
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(max_steps):
            if stop(st.load(path)):
                break
            action, _n = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
        return st.load(path)

    def _skeleton_sealed_script(self):
        # Draft + clean rounds derive the seal; the skeleton's
        # gate commit pins docs/skeleton.md as canonical.
        return [
            step("draft_skeleton",
                 ok("draft_skeleton", artifact="docs/skeleton.md",
                    slices=[{"id": 1, "title": "Core"}]),
                 family="codex",
                 side_effect=write_file("docs/skeleton.md",
                                        "# Skeleton\n\nSEALED CONTENT\n")),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]

    def test_fixer_rewrite_of_sealed_note_is_restored_and_recorded(self):
        # slice_doc-01: review finds -> the FIXER "fixes" its own note
        # but ALSO rewrites the sealed skeleton. The guard restores the
        # skeleton from its gate; the note edit (own artifact) survives.
        script = self._skeleton_sealed_script() + [
            step("draft_slice_note",
                 ok("draft_slice_note", artifact="docs/slice-01.md"),
                 family="codex",
                 side_effect=write_file("docs/slice-01.md",
                                        "# Slice 01\n\noriginal note\n")),
            step("review_round",
                 report("review_round",
                        [finding("F1", "note imprecise", severity="P2")]),
                 family="codex"),
            step("fix_findings",
                 fix_ok([triaged("F1", "fixed", "note imprecise",
                                 severity="P2")],
                        files_changed=["docs/slice-01.md"]),
                 family="codex",
                 side_effect=lambda ws: (
                     append_file("docs/slice-01.md", "\nlegit fix edit\n")(ws),
                     tamper_skeleton("# Skeleton\n\nREWRITTEN BY FIXER\n")(ws),
                 )),
        ]
        state = self._drive(
            script,
            stop=lambda s: any(e.get("type") == "sealed_artifact_restored"
                               for e in s["events"]),
        )
        evs = [e for e in state["events"]
               if e.get("type") == "sealed_artifact_restored"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["unit"], "skeleton")
        self.assertEqual(evs[0]["artifact"], "docs/skeleton.md")
        # The sealed skeleton is byte-restored to its gate content.
        with open(os.path.join(self.ws, "docs", "skeleton.md"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "# Skeleton\n\nSEALED CONTENT\n")
        # The fixer's LEGITIMATE edit (its own unsealed note) survives.
        with open(os.path.join(self.ws, "docs", "slice-01.md"),
                  encoding="utf-8") as fh:
            self.assertIn("legit fix edit", fh.read())
        # The illegal bytes were kept for forensics.
        raw = os.path.join(self.ws, evs[0]["raw_path"])
        with open(raw, encoding="utf-8") as fh:
            self.assertIn("REWRITTEN BY FIXER", fh.read())

    def test_drafter_tamper_of_sealed_skeleton_is_restored(self):
        # The next unit's DRAFT call also may not touch the sealed
        # skeleton: the guard runs on every edit-kind call.
        script = self._skeleton_sealed_script() + [
            step("draft_slice_note",
                 ok("draft_slice_note", artifact="docs/slice-01.md"),
                 family="codex",
                 side_effect=lambda ws: (
                     write_file("docs/slice-01.md", "# Slice 01\n")(ws),
                     tamper_skeleton("# Skeleton\n\nDRAFT TAMPER\n")(ws),
                 )),
        ]
        state = self._drive(
            script,
            stop=lambda s: any(e.get("type") == "sealed_artifact_restored"
                               for e in s["events"]),
        )
        evs = [e for e in state["events"]
               if e.get("type") == "sealed_artifact_restored"]
        self.assertEqual(len(evs), 1)
        with open(os.path.join(self.ws, "docs", "skeleton.md"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "# Skeleton\n\nSEALED CONTENT\n")

    def test_untouched_sealed_artifacts_record_nothing(self):
        script = self._skeleton_sealed_script() + [
            step("draft_slice_note",
                 ok("draft_slice_note", artifact="docs/slice-01.md"),
                 family="codex",
                 side_effect=write_file("docs/slice-01.md", "# Slice 01\n")),
        ]
        state = self._drive(
            script,
            stop=lambda s: any(u["kind"] == st.UNIT_SLICE_DOC and u.get("draft")
                               for u in s["units"]),
        )
        self.assertEqual(
            [e for e in state["events"]
             if e.get("type") == "sealed_artifact_restored"], [])

    def _git(self, *args):
        return subprocess.run(
            ("git",) + args, cwd=self.ws, capture_output=True,
            text=True, check=True,
        ).stdout.strip()

    def _drift_history(self):
        """Legal post-seal drift (found live 2026-07-10, second
        incident): sealed docs carry edits that were REVIEWED and folded
        into LATER gate commits (pre-guard-era `prevention` edits, and
        repair reseals). The current driver can no longer produce that
        history — the guard itself prevents it — so the pre-guard era is
        fabricated directly: seal skeleton + doc-01 normally, then amend
        the sealed skeleton in a NEW gate commit and point doc-01's gate
        at it, exactly the shape LPC rich-content reached. Returns the
        state path. Baselining each unit on its OWN gate false-fires on
        this shape forever, regressing the legally amended doc."""
        path = init_state(self.ws, make_config())  # git ENABLED
        script = self._skeleton_sealed_script() + [
            step("draft_slice_note",
                 ok("draft_slice_note", artifact="docs/slice-01.md"),
                 family="codex",
                 side_effect=write_file("docs/slice-01.md", "# Slice 01\n")),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(40):
            state = st.load(path)
            doc = next((u for u in state["units"]
                        if u["kind"] == st.UNIT_SLICE_DOC), None)
            if doc is not None and doc["status"] == st.U_SEALED:
                break
            action, _n = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
        state = st.load(path)
        doc = next(u for u in state["units"]
                   if u["kind"] == st.UNIT_SLICE_DOC)
        assert doc["status"] == st.U_SEALED, doc["status"]
        # Pre-guard era: the sealed skeleton drifts inside a newer gate.
        tamper_skeleton("# Skeleton\n\nLEGALLY AMENDED\n")(self.ws)
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "Seal slice 01 note")
        doc["gate_commit"] = self._git("rev-parse", "--short", "HEAD")
        st.save(path, state)
        return path

    def _drive_impl_draft(self, path, impl_effect):
        script = [
            step("implement",
                 ok("implement", files_changed=["calc.py"]),
                 family="codex",
                 side_effect=impl_effect),
        ]
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(10):
            action, _n = driver.step()
            state = st.load(path)
            if any(u["kind"] == st.UNIT_SLICE_IMPL and u.get("draft")
                   for u in state["units"]):
                break
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
        return st.load(path)

    def test_legal_drift_sealed_into_a_later_gate_is_canonical(self):
        path = self._drift_history()
        state = self._drive_impl_draft(
            path, write_file("calc.py", "x = 1\n"))
        self.assertEqual(
            [e for e in state["events"]
             if e.get("type") == "sealed_artifact_restored"], [])
        # The drifted skeleton SURVIVES: the newest gate is the baseline.
        with open(os.path.join(self.ws, "docs", "skeleton.md"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "# Skeleton\n\nLEGALLY AMENDED\n")

    def test_tamper_after_legal_drift_restores_the_newest_gate(self):
        path = self._drift_history()
        state = self._drive_impl_draft(
            path,
            lambda ws: (
                write_file("calc.py", "x = 1\n")(ws),
                tamper_skeleton("# Skeleton\n\nEVIL REWRITE\n")(ws),
            ))
        evs = [e for e in state["events"]
               if e.get("type") == "sealed_artifact_restored"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["unit"], "skeleton")
        # Restored to the LEGALLY AMENDED version (the newest gate), not
        # the skeleton's own original gate content.
        with open(os.path.join(self.ws, "docs", "skeleton.md"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "# Skeleton\n\nLEGALLY AMENDED\n")


class RepairEditabilityAcrossDeltaLoopsTest(unittest.TestCase):
    """A repair cycle's EVERY fix round must declare the unit's own
    artifact editable — not just the first one. Found live (2026-07-11,
    certification-llm): the skeleton's repair fixer edited the doc, the
    delta review queued follow-up findings (re-entering U_FIXING with
    source "delta_review"), and the NEXT fix prompt dropped the
    REOPENED-FOR-REPAIR line — so the fixer, correctly obeying its
    prompt's "skeleton is READ-ONLY" rule, refused its own repair and
    blocked the run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-repair-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "ws")
        os.makedirs(self.ws)

    def test_delta_loop_fix_round_keeps_the_repair_line(self):
        path = init_state(self.ws, make_config())  # git ENABLED
        seal_script = [
            step("draft_skeleton",
                 ok("draft_skeleton", artifact="docs/skeleton.md",
                    slices=[{"id": 1, "title": "Core"}]),
                 family="codex",
                 side_effect=write_file("docs/skeleton.md",
                                        "# Skeleton\n\nORIGINAL\n")),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]
        driver = drv.Driver(path, runner=runners.MockRunner(seal_script))
        for _ in range(20):
            if st.load(path)["units"][0]["status"] == "sealed":
                break
            driver.step()
        state = st.load(path)
        skeleton = state["units"][0]
        self.assertEqual(skeleton["status"], "sealed")

        # Reopen for repair exactly as the driver's gap flow does.
        st.reopen_for_repair(
            state, skeleton,
            {"classification": "fits_remodel", "forced_decision": "d",
             "plain": "p"},
            reason="test repair", reported_by="test",
        )
        self.assertTrue(skeleton.get("under_repair"))
        st.enter_fix_episode(
            state, skeleton,
            [finding("GAP1", "repair the skeleton", severity="P1")],
            "repair", None, "skeleton-gap-repair", st.U_PRE_SEAL_VERIFY,
        )
        st.save(path, state)

        repair_script = [
            # Fix round 1 (source "repair"): edits the skeleton.
            step("fix_findings",
                 fix_ok([triaged("GAP1", "fixed", severity="P1")],
                        files_changed=["docs/skeleton.md"]),
                 side_effect=write_file("docs/skeleton.md",
                                        "# Skeleton\n\nREPAIRED v1\n")),
            # Delta review is DIRTY: queues a follow-up finding, so the
            # unit re-enters U_FIXING with source "delta_review".
            step("delta_review",
                 report("delta_review",
                        [finding("D1", "repair wording incomplete",
                                 severity="P1")])),
            # Fix round 2 — THE regression point: this prompt must still
            # declare docs/skeleton.md editable.
            step("fix_findings",
                 fix_ok([triaged("D1", "fixed", severity="P1")],
                        files_changed=["docs/skeleton.md"]),
                 side_effect=write_file("docs/skeleton.md",
                                        "# Skeleton\n\nREPAIRED v2\n")),
            # Clean delta changes the candidate, so both reviewers approve
            # the repaired bytes before the seal is derived.
            step("delta_review", report("delta_review")),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]
        mock = runners.MockRunner(repair_script)
        driver = drv.Driver(path, runner=mock)
        for _ in range(30):
            state = st.load(path)
            if (state["units"][0]["status"] == "sealed"
                    and not mock.script):
                break
            if state.get("failure"):
                self.fail("run failed: %s" % state["failure"]["reason"])
            driver.step()

        fix_prompts = [p for (_f, kind, p) in mock.calls
                       if kind == "fix_findings"]
        self.assertEqual(len(fix_prompts), 2)
        for i, prompt in enumerate(fix_prompts):
            self.assertIn(
                "REOPENED FOR REPAIR", prompt,
                "fix round %d lost the editability declaration" % (i + 1),
            )
            self.assertIn("docs/skeleton.md", prompt)

        # The reseal ends the repair cycle and clears the flag.
        state = st.load(path)
        skeleton = state["units"][0]
        self.assertEqual(skeleton["status"], "sealed")
        self.assertNotIn("under_repair", skeleton)


def _git(ws, *args):
    return subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True,
        check=True, timeout=60,
    ).stdout.strip()


class GapReopenCommitIsolationTest(unittest.TestCase):
    """Reform §3, git on: a fits_remodel gap reopens the BURIED skeleton for
    repair. Its repair must own a fresh commit — amending HEAD directly would
    rewrite the latest sealed unit's commit (finding 1) — and a builder that
    edited before gapping must not smuggle those edits into it (finding 3)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-gapreopen-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "ws")
        os.makedirs(self.ws)

    def _seal_doc_unit(self, kind, artifact, content, reform=False):
        # Under a reform profile every DOC draft answers the engineering
        # battery as structure; profile-less runs must NOT carry it.
        def _battery(ids):
            return [{"question": q, "answer": "answered: %s" % q,
                     "evidence": ["%s:1" % artifact]} for q in ids]
        if kind == "skeleton":
            draft = ok("draft_skeleton", artifact=artifact,
                       slices=[{"id": 1, "title": "Core"}],
                       **({"battery": _battery(
                           contracts.BATTERY_QUESTIONS_SKELETON)}
                          if reform else {}))
        else:
            draft = ok("draft_slice_note", artifact=artifact,
                       **({"battery": _battery(
                           contracts.BATTERY_QUESTIONS_SLICE_NOTE)}
                          if reform else {}))
        return [
            step("draft_%s" % ("skeleton" if kind == "skeleton"
                               else "slice_note"),
                 draft, family="codex",
                 side_effect=write_file(artifact, content)),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]

    def test_skeleton_reopen_opens_fresh_commit_and_discards_builder_junk(self):
        gap = {
            "classification": "fits_remodel",
            "missing_or_conflict": "this step needs a field no earlier "
                                   "step records",
            "where": "docs/slice-01.md:12",
            "forced_decision": "record the field so this step can read it",
            "plain": "the design never produces a field this step must read",
            "example": "the scorer reads a field never written; it stalls",
        }
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
            + [step("implement",
                    {"status": "gap", "kind": "implement", "gaps": [gap]},
                    family="codex",
                    # A builder that edited scratch files THEN decided to gap.
                    side_effect=write_file("junk.py", "# stray pre-gap edit\n"))]
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))

        head_before = None
        for _ in range(60):
            state = st.load(path)
            if state.get("failure"):
                self.fail("run failed: %s" % state["failure"]["reason"])
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                # slice_doc-01 just sealed and owns HEAD; capture it before
                # the implement call gaps.
                head_before = _git(self.ws, "rev-parse", "HEAD")
                break
            driver.step()
        self.assertIsNotNone(head_before, "never reached pending slice_impl-01")

        driver.step()  # implement -> gap -> discard junk -> reopen skeleton
        state = st.load(path)
        self.assertIsNone(state.get("failure"))
        units = {st.unit_key(u): u for u in state["units"]}

        # Finding 3: the builder's scratch edit was discarded, recorded, and
        # never committed.
        self.assertIn("gap_edits_discarded",
                      [e["type"] for e in state["events"]])
        self.assertFalse(os.path.exists(os.path.join(self.ws, "junk.py")))

        # Finding 1: the skeleton is reopened and a FRESH repair commit is
        # opened for it; HEAD advanced, and the latest sealed unit's commit
        # (head_before) is still reachable — NOT rewritten.
        self.assertEqual(units["skeleton"]["status"], st.U_FIXING)
        self.assertEqual([f["id"] for f in units["skeleton"]["fix_queue"]],
                         ["GAP1"])
        wip = [e for e in state["events"]
               if e["type"] == "wip_commit" and e["unit"] == "skeleton"]
        self.assertTrue(wip, "no fresh repair commit was opened")
        head_after = _git(self.ws, "rev-parse", "HEAD")
        self.assertNotEqual(head_after, head_before, "HEAD did not advance")
        reachable = _git(self.ws, "rev-list", "HEAD").split()
        self.assertIn(head_before, reachable,
                      "the latest sealed unit's commit was rewritten")

    def test_staged_builder_junk_is_discarded_on_gap(self):
        # A builder that `git add`s its scratch work before gapping must not
        # smuggle it past cleanup (round 6): the pre-call snapshot restores the
        # reviewed baseline regardless of what the builder staged.
        def write_and_stage(rel, content):
            def _effect(ws):
                write_file(rel, content)(ws)
                _git(ws, "add", rel)
            return _effect

        gap = {
            "classification": "fits_remodel",
            "missing_or_conflict": "this step needs a field no earlier "
                                   "step records",
            "where": "docs/slice-01.md:12",
            "forced_decision": "record the field so this step can read it",
            "plain": "the design never produces a field this step must read",
            "example": "the scorer reads a field never written; it stalls",
        }
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
            + [step("implement",
                    {"status": "gap", "kind": "implement", "gaps": [gap]},
                    family="codex",
                    side_effect=write_and_stage("junk.py", "# staged\n"))]
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            state = st.load(path)
            if state.get("failure"):
                self.fail("run failed: %s" % state["failure"]["reason"])
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                break
            driver.step()
        driver.step()  # implement -> gap -> discard staged junk -> reopen
        state = st.load(path)
        self.assertIsNone(state.get("failure"))
        self.assertIn("gap_edits_discarded",
                      [e["type"] for e in state["events"]])
        # The staged junk is gone from the worktree AND from git's tracking:
        # the fresh repair commit never adopted it.
        self.assertFalse(os.path.exists(os.path.join(self.ws, "junk.py")))
        self.assertNotIn("junk.py", _git(self.ws, "ls-files").split())

    def test_committed_builder_junk_is_undone_on_gap(self):
        # A builder that COMMITS its scratch work before gapping must not make
        # the repair commit a child of that junk commit (round 8): the pre-call
        # HEAD snapshot is restored, so the junk leaves history entirely.
        def write_and_commit(rel, content):
            def _effect(ws):
                write_file(rel, content)(ws)
                _git(ws, "add", rel)
                _git(ws, "commit", "-q", "-m", "builder junk commit")
            return _effect

        gap = {
            "classification": "fits_remodel",
            "missing_or_conflict": "this step needs a field no earlier "
                                   "step records",
            "where": "docs/slice-01.md:12",
            "forced_decision": "record the field so this step can read it",
            "plain": "the design never produces a field this step must read",
            "example": "the scorer reads a field never written; it stalls",
        }
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
            + [step("implement",
                    {"status": "gap", "kind": "implement", "gaps": [gap]},
                    family="codex",
                    side_effect=write_and_commit("junk.py", "# committed\n"))]
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        head_before = None
        for _ in range(60):
            state = st.load(path)
            if state.get("failure"):
                self.fail("run failed: %s" % state["failure"]["reason"])
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                head_before = _git(self.ws, "rev-parse", "HEAD")
                break
            driver.step()
        driver.step()  # implement -> commit junk -> gap -> undo -> reopen
        state = st.load(path)
        self.assertIsNone(state.get("failure"))
        self.assertIn("gap_edits_discarded",
                      [e["type"] for e in state["events"]])
        # The junk commit and file are gone; the repair commit's parent is the
        # pre-call HEAD, not the builder's junk commit.
        self.assertFalse(os.path.exists(os.path.join(self.ws, "junk.py")))
        self.assertNotIn("junk.py", _git(self.ws, "ls-files").split())
        reachable = _git(self.ws, "log", "--pretty=%s").splitlines()
        self.assertNotIn("builder junk commit", reachable)
        # The fresh repair commit sits directly on the pre-call baseline.
        self.assertEqual(_git(self.ws, "rev-parse", "HEAD~1"), head_before)

    def test_builder_created_branch_and_commits_are_fully_undone(self):
        # A builder that switches to a NEW branch and commits junk there before
        # gapping must be fully undone (round 9 + 11): HEAD back on the original
        # branch, the repair on it, and the builder-created branch (with its
        # junk) removed entirely — a worker-created ref is not legitimate
        # history to keep.
        def switch_and_commit(rel, content):
            def _effect(ws):
                _git(ws, "checkout", "-q", "-b", "release")
                write_file(rel, content)(ws)
                _git(ws, "add", rel)
                _git(ws, "commit", "-q", "-m", "junk on release")
            return _effect

        gap = {
            "classification": "fits_remodel",
            "missing_or_conflict": "this step needs a field no earlier "
                                   "step records",
            "where": "docs/slice-01.md:12",
            "forced_decision": "record the field so this step can read it",
            "plain": "the design never produces a field this step must read",
            "example": "the scorer reads a field never written; it stalls",
        }
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
            + [step("implement",
                    {"status": "gap", "kind": "implement", "gaps": [gap]},
                    family="codex",
                    side_effect=switch_and_commit("junk.py", "# on release\n"))]
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        head_before = orig_branch = None
        for _ in range(60):
            state = st.load(path)
            if state.get("failure"):
                self.fail("run failed: %s" % state["failure"]["reason"])
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                head_before = _git(self.ws, "rev-parse", "HEAD")
                orig_branch = _git(self.ws, "symbolic-ref", "--short", "HEAD")
                break
            driver.step()
        driver.step()  # implement -> switch+commit -> gap -> undo -> reopen
        state = st.load(path)
        self.assertIsNone(state.get("failure"))
        self.assertIn("gap_edits_discarded",
                      [e["type"] for e in state["events"]])
        # HEAD is back on the ORIGINAL branch; the repair commit sits on it,
        # directly atop the pre-call tip.
        self.assertEqual(_git(self.ws, "symbolic-ref", "--short", "HEAD"),
                         orig_branch)
        self.assertEqual(_git(self.ws, "rev-parse", "HEAD~1"), head_before)
        # The builder-created branch is gone, and its junk reaches no ref.
        branches = _git(self.ws, "branch", "--format=%(refname:short)").split()
        self.assertNotIn("release", branches)
        self.assertNotIn("junk on release",
                         _git(self.ws, "log", "--all", "--pretty=%s"))
        self.assertFalse(os.path.exists(os.path.join(self.ws, "junk.py")))

    def test_builder_deleted_branch_is_restored_on_gap(self):
        # The other half (round 11): a builder that DELETES a legitimate branch
        # with unpublished commits before gapping must have it put back.
        gap = {
            "classification": "fits_remodel",
            "missing_or_conflict": "this step needs a field no earlier "
                                   "step records",
            "where": "docs/slice-01.md:12",
            "forced_decision": "record the field so this step can read it",
            "plain": "the design never produces a field this step must read",
            "example": "the scorer reads a field never written; it stalls",
        }
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
            + [step("implement",
                    {"status": "gap", "kind": "implement", "gaps": [gap]},
                    family="codex",
                    # The builder destroys a branch the operator keeps.
                    side_effect=lambda ws: _git(ws, "branch", "-D", "feature"))]
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            state = st.load(path)
            if state.get("failure"):
                self.fail("run failed: %s" % state["failure"]["reason"])
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                break
            driver.step()
        # A legitimate branch the operator keeps, present before the builder
        # runs (the repo now has commits, so branching is well-defined).
        _git(self.ws, "branch", "feature")
        feature_sha = _git(self.ws, "rev-parse", "feature")
        driver.step()  # implement -> delete feature -> gap -> restore feature
        state = st.load(path)
        self.assertIsNone(state.get("failure"))
        self.assertIn("gap_edits_discarded",
                      [e["type"] for e in state["events"]])
        # The deleted branch is restored to its recorded sha.
        self.assertEqual(_git(self.ws, "rev-parse", "feature"), feature_sha)

    def test_crashed_gap_repair_intent_completes_on_restart(self):
        # A crash after the repair INTENT persisted but before the reopen
        # applied must complete on the next driver init, not lose the gap to a
        # re-draft of the reporter (round 14/15).
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            state = st.load(path)
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                break
            driver.step()
        # Simulate the crash mid-transaction: the validated gap is recorded
        # (pending_gap) but NOT yet routed — skeleton still sealed, no repair
        # commit at HEAD. The pre-call snapshot is the current (clean) baseline.
        state = st.load(path)
        state["pending_gap"] = {
            "reporter": "slice_impl-01",
            "gaps": [{"classification": "fits_remodel",
                      "missing_or_conflict": "m", "where": "docs/x.md:1",
                      "forced_decision": "record the field", "plain": "p",
                      "example": "e"}],
            "pre_tree": gitops.snapshot_index_tree(self.ws),
            "pre_head": gitops.head_full_sha(self.ws),
            "pre_sym": gitops.head_symbolic_ref(self.ws),
            "pre_refs": gitops.snapshot_refs(self.ws),
        }
        st.save(path, state)
        head_before = _git(self.ws, "rev-parse", "HEAD")
        # Restart: a fresh driver re-routes the recorded gap on init.
        drv.Driver(path, runner=runners.MockRunner([]))
        state = st.load(path)
        self.assertIsNone(state.get("pending_gap"))
        units = {st.unit_key(u): u for u in state["units"]}
        self.assertEqual(units["skeleton"]["status"], st.U_FIXING)
        self.assertEqual([f["id"] for f in units["skeleton"]["fix_queue"]],
                         ["GAP1"])
        self.assertEqual(units["slice_impl-01"]["gap_repairs"], 1)
        # A fresh repair commit was opened on restart, atop the pre-call tip.
        self.assertNotEqual(_git(self.ws, "rev-parse", "HEAD"), head_before)
        self.assertEqual(_git(self.ws, "rev-parse", "HEAD~1"), head_before)

    def test_builder_cleared_stash_stack_is_fully_restored_on_gap(self):
        # A worker that clears a pre-existing MULTI-entry stash before gapping
        # must have the whole stack restored — the stash is a reflog-backed
        # stack, so restoring only its tip would drop older entries (round 19).
        gap = {
            "classification": "fits_remodel",
            "missing_or_conflict": "a field no earlier step records",
            "where": "docs/slice-01.md:12",
            "forced_decision": "record the field so this step can read it",
            "plain": "the design never produces a field this step must read",
            "example": "the scorer reads a field never written; it stalls",
        }
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
            + [step("implement",
                    {"status": "gap", "kind": "implement", "gaps": [gap]},
                    family="codex",
                    side_effect=lambda ws: _git(ws, "stash", "clear"))]
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            state = st.load(path)
            if state.get("failure"):
                self.fail("run failed: %s" % state["failure"]["reason"])
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                break
            driver.step()
        # Two pre-existing stash entries the operator keeps.
        write_file("docs/skeleton.md", "# Skeleton\n\nSEALED\nfirst\n")(self.ws)
        _git(self.ws, "stash", "push", "-m", "operator stash one")
        write_file("docs/skeleton.md", "# Skeleton\n\nSEALED\nsecond\n")(self.ws)
        _git(self.ws, "stash", "push", "-m", "operator stash two")
        before = _git(self.ws, "reflog", "refs/stash", "--format=%H").split()
        self.assertEqual(len(before), 2)
        driver.step()  # implement -> stash clear -> gap -> rebuild the stack
        state = st.load(path)
        self.assertIsNone(state.get("failure"))
        self.assertIn("gap_edits_discarded",
                      [e["type"] for e in state["events"]])
        # `git stash list` is whole again, in order — not just the tip.
        self.assertEqual(len(_git(self.ws, "stash", "list").splitlines()), 2)
        after = _git(self.ws, "reflog", "refs/stash", "--format=%H").split()
        self.assertEqual(after, before)

    def test_pending_gap_recovery_survives_a_nested_repo(self):
        # A crash after recording the gap but before cleanup can leave worker
        # junk like a nested repo. Without a pre-clean, ensure_repo would reject
        # the workspace and deadlock every resume; the pre-clean removes it so
        # recovery completes (round 17).
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            state = st.load(path)
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                break
            driver.step()
        # Record the gap intent with the clean baseline snapshot (crash before
        # cleanup ran).
        state = st.load(path)
        state["pending_gap"] = {
            "reporter": "slice_impl-01",
            "gaps": [{"classification": "fits_remodel",
                      "missing_or_conflict": "m", "where": "docs/x.md:1",
                      "forced_decision": "record the field", "plain": "p",
                      "example": "e"}],
            "pre_tree": gitops.snapshot_index_tree(self.ws),
            "pre_head": gitops.head_full_sha(self.ws),
            "pre_sym": gitops.head_symbolic_ref(self.ws),
            "pre_refs": gitops.snapshot_refs(self.ws),
        }
        st.save(path, state)
        # ...and a worker-created nested repo left behind.
        nested = os.path.join(self.ws, "vendor", "thing")
        os.makedirs(nested)
        subprocess.run(["git", "init", "-q"], cwd=nested,
                       capture_output=True, text=True, check=True, timeout=60)
        # Restart: the pre-clean removes the nested repo, ensure_repo passes,
        # and the recorded gap routes.
        drv.Driver(path, runner=runners.MockRunner([]))
        state = st.load(path)
        self.assertIsNone(state.get("failure"))
        self.assertIsNone(state.get("pending_gap"))
        self.assertFalse(os.path.exists(nested))
        units = {st.unit_key(u): u for u in state["units"]}
        self.assertEqual(units["skeleton"]["status"], st.U_FIXING)

    def test_stray_repair_commit_from_crash_is_undone_not_stacked(self):
        # A prior attempt that created the repair commit but died before
        # recording the reopen leaves a stray commit at HEAD. On restart the
        # recovery cleanup resets the branch to the recorded pre-call HEAD
        # (undoing the stray), then opens exactly ONE fresh repair commit —
        # never a second stacked one, and never an unrelated same-named commit
        # rewritten (round 10 + 20).
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            state = st.load(path)
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                break
            driver.step()
        clean_head = _git(self.ws, "rev-parse", "HEAD")
        # Record the gap intent against the clean pre-crash baseline...
        state = st.load(path)
        state["pending_gap"] = {
            "reporter": "slice_impl-01",
            "gaps": [{"classification": "fits_remodel",
                      "missing_or_conflict": "m", "where": "docs/x.md:1",
                      "forced_decision": "record the field", "plain": "p",
                      "example": "e"}],
            "pre_tree": gitops.snapshot_index_tree(self.ws),
            "pre_head": gitops.head_full_sha(self.ws),
            "pre_sym": gitops.head_symbolic_ref(self.ws),
            "pre_refs": gitops.snapshot_refs(self.ws),
            "pre_stash": gitops.snapshot_stash(self.ws),
        }
        st.save(path, state)
        # ...then simulate the crashed commit: a stray repair commit at HEAD.
        _git(self.ws, "commit", "-q", "--allow-empty", "-m",
             "wip-repair: skeleton")
        # Restart: cleanup undoes the stray; routing opens one fresh commit.
        drv.Driver(path, runner=runners.MockRunner([]))
        state = st.load(path)
        self.assertIsNone(state.get("failure"))
        self.assertIsNone(state.get("pending_gap"))
        units = {st.unit_key(u): u for u in state["units"]}
        self.assertEqual(units["skeleton"]["status"], st.U_FIXING)
        subjects = _git(self.ws, "log", "HEAD", "--pretty=%s").splitlines()
        self.assertEqual(subjects.count("wip-repair: skeleton"), 1)
        # The one fresh repair commit sits directly on the pre-crash baseline —
        # the stray was undone, not built upon.
        self.assertEqual(_git(self.ws, "rev-parse", "HEAD~1"), clean_head)

    def test_needs_operator_gap_cleans_junk_but_keeps_adopted_baseline(self):
        # A needs_operator gap on the FIRST unit stops for the operator. It
        # must discard the builder's scratch edits (round 5: else a later
        # resumed draft commits them) WITHOUT reverting an adopted repo's
        # staged-but-uncommitted baseline (round 4). Reverting to the INDEX
        # does both: the adopted edit is staged there, the junk is not.
        path = init_state(self.ws, make_config())
        # Prior history, then an adopted edit staged (as ensure_repo does) but
        # NOT yet gate-committed.
        write_file("baseline.txt", "committed\n")(self.ws)
        _git(self.ws, "add", "baseline.txt")
        _git(self.ws, "commit", "-q", "-m", "prior history")
        write_file("baseline.txt", "committed\nadopted edit\n")(self.ws)
        _git(self.ws, "add", "baseline.txt")

        op_gap = {
            "classification": "needs_operator",
            "missing_or_conflict": "the goal names no persistence backend",
            "where": "goal",
            "forced_decision": "the operator must choose the database",
            "plain": "the goal never says where data is stored",
            "example": "cannot pick Postgres vs SQLite without the operator",
        }
        script = [step("draft_skeleton",
                       {"status": "gap", "kind": "draft_skeleton",
                        "gaps": [op_gap]},
                       family="codex",
                       # The builder scribbled junk before deciding to gap.
                       side_effect=write_file("junk.py", "# scratch\n"))]
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(10):
            if st.load(path).get("failure"):
                break
            driver.step()
        state = st.load(path)
        self.assertEqual(state["failure"]["type"], "goal_gap")
        # The adopted (staged) baseline edit SURVIVES.
        with open(os.path.join(self.ws, "baseline.txt"),
                  encoding="utf-8") as fh:
            self.assertIn("adopted edit", fh.read())
        # The builder's scratch junk was discarded and recorded.
        self.assertFalse(os.path.exists(os.path.join(self.ws, "junk.py")))
        self.assertIn("gap_edits_discarded",
                      [e["type"] for e in state["events"]])

    def test_stranded_wave_recovery_retries_the_gate_not_the_old_sha(self):
        # Crash window with git ON: the anchor RESEALED (wave) but its gate
        # commit failed — the anchor still carries its PRE-WAVE gate sha.
        # Startup recovery must detect that the reseal's gate never ran (no
        # gate_commit event after the last sealed transition), RETRY the
        # gate, and close the wave against the NEW sha — closing against
        # the old one would let the guard restore pre-wave documentation.
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED v1\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote v1\n")))
        for _ in range(40):
            state = st.load(path)
            cur = st.current_unit(state)
            if (cur is not None and st.unit_key(cur) == "slice_impl-01"
                    and cur["status"] == st.U_PENDING):
                break
            driver.step()
        state = st.load(path)
        by = {st.unit_key(u): u for u in state["units"]}
        old_gate = by["skeleton"]["gate_commit"]
        self.assertTrue(old_gate)
        # Simulate the wave mid-flight: docs + anchor reopened, the wave's
        # re-documented bytes written and wip-committed, the anchor resealed
        # in state... and the driver died before the gate commit.
        gap = {"classification": "fits_remodel", "forced_decision": "d",
               "plain": "p"}
        st.reopen_for_repair(state, by["slice_doc-01"], gap, "wave",
                             reported_by="slice_impl-01")
        skeleton = by["skeleton"]
        st.reopen_for_repair(state, skeleton, gap, "gap",
                             reported_by="slice_impl-01")
        st.enter_fix_episode(
            state, skeleton,
            [{"id": "G1", "severity": "P1", "summary": "objective"}],
            "repair", None, "skeleton-gap", st.U_PRE_SEAL_VERIFY)
        state["redoc_wave"] = {"anchor": "skeleton",
                               "docs": ["slice_doc-01"],
                               "reporter": "slice_impl-01"}
        st.save(path, state)   # the routing save (reopens persisted first)
        write_file("docs/skeleton.md", "# Skeleton\n\nwave v2\n")(self.ws)
        write_file("docs/slice-01.md", "# Slice 01\n\nnote v2\n")(self.ws)
        gitops.commit_wip(self.ws, "wip-repair: skeleton")
        st.transition_unit(state, skeleton, st.U_DELTA_REVIEW)
        st.transition_unit(state, skeleton, st.U_PRE_SEAL_VERIFY)
        st.transition_unit(state, skeleton, st.U_SEALING)
        st.record_seal_attempt(state, skeleton, make_halves(), True)
        st.transition_unit(state, skeleton, st.U_SEALED)
        st.save(path, state)   # gate_commit still = old_gate; no gate event
        # Startup: retries the gate (new sha), closes the wave against it.
        drv.Driver(path, runner=runners.MockRunner([]))
        state = st.load(path)
        by = {st.unit_key(u): u for u in state["units"]}
        self.assertIsNone(state.get("redoc_wave"))
        new_gate = by["skeleton"]["gate_commit"]
        self.assertNotEqual(new_gate, old_gate)
        self.assertEqual(by["slice_doc-01"]["gate_commit"], new_gate)
        self.assertEqual(by["slice_doc-01"]["status"], st.U_SEALED)
        # The re-documented bytes are what the new gate holds — a later
        # guard pass keeps v2, never restores v1.
        self.assertIn("note v2",
                      gitops.show_file(self.ws, new_gate, "docs/slice-01.md")
                      .decode())

    def test_wave_fixer_edits_co_reopened_note_without_restore(self):
        # RE-DOCUMENTATION WAVE, git on: the anchor's fixer legitimately
        # edits a CO-REOPENED slice note (repairing, so the sealed-artifact
        # guard must not restore it), the wave reseal makes the edited bytes
        # the new gate baseline, and the note reseals with a WAVE record.
        gap = {
            "classification": "fits_remodel",
            "missing_or_conflict": "a field no earlier step records",
            "where": "docs/slice-01.md:12",
            "forced_decision": "record the field so this step can read it",
            "plain": "the design never produces a field this step must read",
            "example": "the scorer reads a field never written; it stalls",
        }
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED v1\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote v1\n")
            + [step("implement",
                    {"status": "gap", "kind": "implement", "gaps": [gap]},
                    family="codex"),
               # The wave's fixer re-documents BOTH the anchor and the note.
               step("fix_findings",
                    fix_ok([triaged("GAP1", "fixed", "re-documented",
                                    severity="P1")],
                           files_changed=["docs/skeleton.md",
                                          "docs/slice-01.md"]),
                    family="codex",
                    side_effect=lambda ws: (
                        write_file("docs/skeleton.md",
                                   "# Skeleton\n\nre-documented v2\n")(ws),
                        write_file("docs/slice-01.md",
                                   "# Slice 01\n\nnote v2 (wave)\n")(ws),
                    )),
               step("delta_review", report("delta_review"), family="codex"),
               step("review_round", report("review_round"), family="codex"),
               step("review_round", report("review_round"), family="claude"),
               # The reporter re-drafts after the wave closed; the guard's
               # post-draft sweep must accept the note's NEW bytes (the wave
               # gate is the baseline now) and restore nothing.
               step("implement", ok("implement", files_changed=["calc.py"]),
                    family="codex",
                    side_effect=write_file("calc.py", "x = 1\n"))]
        )
        path = init_state(self.ws, make_config())
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            state = st.load(path)
            if state.get("failure"):
                self.fail("run failed: %s" % state["failure"]["reason"])
            units = {st.unit_key(u): u for u in state["units"]}
            impl = units.get("slice_impl-01")
            if impl is not None and impl.get("draft"):
                break
            driver.step()
        state = st.load(path)
        units = {st.unit_key(u): u for u in state["units"]}
        # No restore fired — the co-reopened note was legitimately editable
        # during the wave and its new bytes are the baseline afterwards.
        self.assertNotIn("sealed_artifact_restored",
                         [e["type"] for e in state["events"]])
        with open(os.path.join(self.ws, "docs", "slice-01.md"),
                  encoding="utf-8") as fh:
            self.assertIn("note v2 (wave)", fh.read())
        doc = units["slice_doc-01"]
        self.assertEqual(doc["status"], st.U_SEALED)
        self.assertEqual(doc["seals"][-1].get("wave"), "skeleton-a2")
        self.assertEqual(doc.get("gate_commit"),
                         units["skeleton"].get("gate_commit"))
        self.assertIsNone(state.get("redoc_wave"))
        # The wave gate's GENERATED LEDGERS render the truth: the note is
        # sealed with WAVE provenance, never "repairing" or a blank
        # ordinary seal (the note ran no episode of its own).
        from orchestrator import ledgers
        gate = units["skeleton"]["gate_commit"]
        record = gitops.show_file(self.ws, gate,
                                  ledgers.record_path(state)).decode()
        self.assertIn("(wave skeleton-a2)", record)
        self.assertNotIn("| repairing |", record)
        review_log = gitops.show_file(
            self.ws, gate, ledgers.review_log_path(state)).decode()
        self.assertIn("re-documentation wave skeleton-a2", review_log)

    def test_out_of_envelope_gap_still_runs_the_sealed_guard(self):
        # Codex round 6 P1: the out-of-envelope rejection must NOT be a side
        # door around tamper detection. A profile-less (git-on) fixer that
        # edits the SEALED skeleton and then returns a gap is rejected
        # (worker_blocked), but the sealed-artifact guard must run FIRST and
        # restore the tampered bytes.
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED v1\n")
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n")
            + [step("implement", ok("implement", files_changed=["impl.py"]),
                    family="codex", side_effect=write_file("impl.py", "v1\n")),
               step("review_round",
                    report("review_round",
                           [finding("F1", "x", severity="P1")]),
                    family="codex"),
               step("fix_findings",
                    {"status": "gap", "kind": "fix_findings",
                     "gaps": [self._fixer_gap("fits_remodel")]},
                    family="codex",
                    # Tamper: overwrite the sealed skeleton, then gap.
                    side_effect=write_file("docs/skeleton.md",
                                           "# Skeleton\n\nTAMPERED\n"))]
        )
        path = init_state(self.ws, make_config())  # profile-less: no gap sem.
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(40):
            state = st.load(path)
            if state.get("failure"):
                break
            driver.step()
        state = st.load(path)
        self.assertEqual(state["failure"]["type"], "worker_blocked")
        # The guard ran despite the gap rejection: the tamper was restored.
        self.assertIn("sealed_artifact_restored",
                      [e["type"] for e in state["events"]])
        with open(os.path.join(self.ws, "docs", "skeleton.md"),
                  encoding="utf-8") as fh:
            self.assertIn("SEALED v1", fh.read())
            self.assertNotIn("TAMPERED", fh.read())

    def _fixer_gap(self, classification):
        return {
            "classification": classification,
            "missing_or_conflict": "two sealed texts collide",
            "where": "docs/skeleton.md:10 and docs/slice-01.md:12",
            "forced_decision": "reconcile the two sealed contracts",
            "plain": "the design contradicts itself",
            "example": "the impl cannot satisfy both sealed texts at once",
        }

    def _drive_to_gap(self, gap):
        # A REAL flow (git on): impl drafts (writes abandoned.py, commits its
        # own wip), a review finding queues, and the fixer meets a sealed
        # contradiction and GAPS instead of disposing.
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n", reform=True)
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n", reform=True)
            + [step("implement",
                    ok("implement", files_changed=["abandoned.py"]),
                    family="codex",
                    side_effect=write_file("abandoned.py", "old junk\n")),
               step("review_round",
                    report("review_round",
                           [finding("F1", "contradiction", severity="P1")]),
                    family="codex"),
               step("fix_findings",
                    {"status": "gap", "kind": "fix_findings", "gaps": [gap]},
                    family="codex",
                    # The gapping fixer leaves an UNTRACKED scratch file: a bare
                    # reset --hard would keep it and git add -A would fold it
                    # into the wave.
                    side_effect=write_file("scratch_untracked.py", "junk\n"))]
        )
        # The fixer gap is advertised/routed only under a reform profile.
        cfg = make_config()
        cfg["profile"] = profiles.SEEDS["strict"]["profile"]
        path = init_state(self.ws, cfg)
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(30):
            state = st.load(path)
            if state.get("failure") or state.get("redoc_wave"):
                break
            driver.step()
        return path, st.load(path)

    def test_fixer_gap_fits_remodel_unwinds_the_abandoned_slice(self):
        # Defect (codex round 1): the fixer-gap reporter already committed a
        # draft wip; reusing the builder's pre-CALL cleanup left that abandoned
        # work as the wave's parent, contaminating the re-draft. The fix unwinds
        # the reporter's whole slice to the last sealed baseline before the wave
        # commits.
        path, state = self._drive_to_gap(self._fixer_gap("fits_remodel"))
        self.assertIsNone(state.get("failure"))
        units = {st.unit_key(u): u for u in state["units"]}
        self.assertEqual(units["skeleton"]["status"], st.U_FIXING)
        self.assertEqual(units["slice_doc-01"]["status"], st.U_REPAIRING)
        self.assertEqual(units["slice_impl-01"]["status"], st.U_PENDING)
        # The abandoned draft's file is GONE from the worktree...
        self.assertFalse(
            os.path.exists(os.path.join(self.ws, "abandoned.py")))
        # ...the fixer's UNTRACKED scratch is gone too (restore_to_snapshot's
        # clean ran before the reset, so git add -A cannot fold it in)...
        self.assertFalse(
            os.path.exists(os.path.join(self.ws, "scratch_untracked.py")))
        # ...and the reporter's wip is NOT an ancestor of the wave commit
        # (the repair baseline is the last sealed gate, not the abandoned wip).
        log = subprocess.run(
            ["git", "log", "--format=%s", "-5"], cwd=self.ws, text=True,
            capture_output=True, check=True).stdout
        self.assertNotIn("wip: slice_impl-01", log)
        self.assertIn("wip-repair: skeleton", log)
        self.assertIn("gap_edits_discarded",
                      [e["type"] for e in state["events"]])

    def test_fixer_gap_needs_operator_unwinds_and_redrafts(self):
        # A needs_operator fixer gap stops for the operator AND unwinds the
        # reporter's slice to a clean baseline, resetting it to re-draft — so
        # no gapping-call scratch can be laundered into a later commit (codex
        # round 3), and after the operator amends the goal the reporter
        # re-drafts against it from a clean tree.
        path, state = self._drive_to_gap(self._fixer_gap("needs_operator"))
        self.assertEqual(state["failure"]["type"], "goal_gap")
        units = {st.unit_key(u): u for u in state["units"]}
        # The reporter's abandoned draft AND the gapping fixer's untracked
        # scratch are both gone (unwound to the last sealed baseline).
        self.assertFalse(os.path.exists(os.path.join(self.ws, "abandoned.py")))
        self.assertFalse(
            os.path.exists(os.path.join(self.ws, "scratch_untracked.py")))
        self.assertIn("gap_edits_discarded",
                      [e["type"] for e in state["events"]])
        # The reporter re-drafts on resume: it failed FROM pending (reset), so
        # resume restores it to pending — never the skeleton is remodelled here.
        self.assertEqual(units["slice_impl-01"].get("failed_from"),
                         st.U_PENDING)
        self.assertFalse(units["slice_impl-01"].get("has_gap_remodel"))
        st.resume_run(state)
        self.assertEqual(units["slice_impl-01"]["status"], st.U_PENDING)

    def test_fixer_gap_restart_unwinds_idempotently(self):
        # Codex round 2/3: a crash leaves pending_gap(from_fixer) persisted;
        # startup recovery must route it (unwind + goal_gap) without the
        # startup _pre_clean_pending_gap corrupting the repo first, and the
        # unwind must be idempotent.
        script = (
            self._seal_doc_unit("skeleton", "docs/skeleton.md",
                                "# Skeleton\n\nSEALED\n", reform=True)
            + self._seal_doc_unit("slice_doc", "docs/slice-01.md",
                                  "# Slice 01\n\nnote\n", reform=True)
            + [step("implement", ok("implement", files_changed=["impl.py"]),
                    family="codex", side_effect=write_file("impl.py", "v1\n")),
               step("review_round",
                    report("review_round",
                           [finding("F1", "first", severity="P1")]),
                    family="codex"),
               step("fix_findings",
                    fix_ok([triaged("F1", "fixed", "first", severity="P1")],
                           files_changed=["prior_fix.py"]),
                    family="codex",
                    side_effect=write_file("prior_fix.py", "legit prior\n")),
               step("delta_review",
                    report("delta_review",
                           [finding("D1", "second", severity="P1")]),
                    family="codex")]
        )
        cfg = make_config()
        cfg["profile"] = profiles.SEEDS["strict"]["profile"]
        path = init_state(self.ws, cfg)
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(40):
            state = st.load(path)
            u = st.current_unit(state)
            if (u and st.unit_key(u) == "slice_impl-01"
                    and u["status"] == st.U_FIXING
                    and (u.get("fix_queue") or [{}])[0].get("id") == "D1"):
                break
            driver.step()
        # Simulate the crash: the second fixer returned a needs_operator gap
        # (pending_gap persisted with from_fixer) and the driver died before
        # routing. A fresh driver runs startup recovery.
        state = st.load(path)
        state["pending_gap"] = {
            "reporter": "slice_impl-01",
            "gaps": [self._fixer_gap("needs_operator")],
            "pre_tree": gitops.snapshot_index_tree(self.ws),
            "pre_head": gitops.head_full_sha(self.ws),
            "pre_sym": gitops.head_symbolic_ref(self.ws),
            "pre_refs": gitops.snapshot_refs(self.ws),
            "pre_stash": gitops.snapshot_stash(self.ws),
            "from_fixer": True,
        }
        st.save(path, state)
        drv.Driver(path, runner=runners.MockRunner([]))
        state = st.load(path)
        self.assertEqual(state["failure"]["type"], "goal_gap")
        self.assertIsNone(state.get("pending_gap"))
        # Unwound to the clean sealed baseline: the reporter's slice work is
        # gone and the worktree is clean (no dangling accumulated fixes).
        self.assertFalse(os.path.exists(os.path.join(self.ws, "prior_fix.py")))
        self.assertFalse(gitops.has_builder_edits(self.ws))
        # A SECOND startup recovery is a no-op (intent already discharged).
        drv.Driver(path, runner=runners.MockRunner([]))
        self.assertIsNone(st.load(path).get("pending_gap"))


if __name__ == "__main__":
    unittest.main()
