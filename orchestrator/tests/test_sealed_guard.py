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
from orchestrator import runners
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    finding, fix_ok, init_state, make_config, ok, report, step, triaged,
    write_file, append_file,
)

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
        # Draft + clean rounds + double seal: the skeleton SEALS and its
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
            step("seal_half", report("seal_half"), family="codex"),
            step("seal_half", report("seal_half"), family="claude"),
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
            step("seal_half", report("seal_half"), family="codex"),
            step("seal_half", report("seal_half"), family="claude"),
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


if __name__ == "__main__":
    unittest.main()
