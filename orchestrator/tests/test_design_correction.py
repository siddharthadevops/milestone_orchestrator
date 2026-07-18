"""Small own-note correction lane for cooperative implementation fixers."""

import os
import tempfile
import unittest

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import gitops
from orchestrator import profiles
from orchestrator import runners
from orchestrator import state as st
from orchestrator.tests.test_driver_mock import (
    append_file,
    battery_entries,
    finding,
    fix_ok,
    init_state,
    make_config,
    ok,
    report,
    step,
    triaged,
    write_file,
)


class DesignCorrectionTest(unittest.TestCase):
    NOTE = "docs/slice-01.md"
    SKELETON = "docs/skeleton.md"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-design-fix-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "ws")
        os.makedirs(self.ws)

    def _config(self):
        config = make_config()
        config["profile"] = profiles.SEEDS["strict"]["profile"]
        return config

    def _prefix(self):
        return [
            step(
                "draft_skeleton",
                ok(
                    "draft_skeleton",
                    artifact=self.SKELETON,
                    slices=[{"id": 1, "title": "Window"}],
                    battery=battery_entries(
                        contracts.BATTERY_QUESTIONS_SKELETON
                    ),
                ),
                family="codex",
                side_effect=write_file(
                    self.SKELETON,
                    "# Window\n\nThe authoritative maximum is 30.\n",
                ),
            ),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
            step(
                "draft_slice_note",
                ok(
                    "draft_slice_note",
                    artifact=self.NOTE,
                    battery=battery_entries(
                        contracts.BATTERY_QUESTIONS_SLICE_NOTE
                    ),
                ),
                family="codex",
                side_effect=write_file(
                    self.NOTE,
                    "# Slice 01\n\nRequest the page size directly (50).\n",
                ),
            ),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
            step(
                "implement",
                ok("implement", files_changed=["impl.py", "test_impl.py"]),
                family="codex",
                side_effect=lambda workspace: (
                    write_file("impl.py", "limit = 50\n")(workspace),
                    write_file("test_impl.py", "assert limit == 30\n")(
                        workspace
                    ),
                ),
            ),
            step(
                "review_round",
                report(
                    "review_round",
                    [finding("SIZE", "note contradicts the maximum", "P1")],
                ),
                family="codex",
            ),
        ]

    def _correction(self, artifact=None):
        return {
            "artifact": artifact or self.NOTE,
            "authority_artifact": self.SKELETON,
            "contradiction": "the note requests 50 but the maximum is 30",
            "resolution": "clamp the request to 30",
        }

    def _fix_step(self, artifact=None):
        return step(
            "fix_findings",
            fix_ok(
                [triaged("SIZE", "fixed", "note contradicts the maximum", "P1")],
                files_changed=[artifact or self.NOTE, "impl.py", "test_impl.py"],
                design_correction=self._correction(artifact),
            ),
            family="codex",
            side_effect=lambda workspace: (
                append_file(
                    artifact or self.NOTE,
                    "Correction: clamp the requested size to 30.\n",
                )(workspace),
                write_file("impl.py", "limit = 30\n")(workspace),
            ),
        )

    @staticmethod
    def _fixer_gap(classification):
        return {
            "status": "gap",
            "kind": "fix_findings",
            "gaps": [{
                "classification": classification,
                "missing_or_conflict": "the remaining behavior needs redesign",
                "where": "docs/slice-01.md",
                "forced_decision": "reconcile the remaining contract",
                "plain": "the next fix cannot fit the current contract",
                "example": "the cleanup would change the public behavior",
            }],
        }

    @staticmethod
    def _verdict(decision, findings=()):
        return ok(
            "delta_review",
            findings=list(findings),
            design_correction_verdict={
                "decision": decision,
                "reason": "the skeleton uniquely fixes the maximum at 30",
            },
        )

    def _drive(self, script, stop, limit=80):
        path = init_state(self.ws, self._config())
        mock = runners.MockRunner(script)
        driver = drv.Driver(path, runner=mock)
        for _ in range(limit):
            state = st.load(path)
            if stop(state):
                return path, state, driver, mock
            action, _note = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                return path, st.load(path), driver, mock
        self.fail("driver did not reach the expected correction state")

    def test_clean_independent_verdict_ratifies_and_final_gate_freezes_note(self):
        script = self._prefix() + [
            self._fix_step(),
            step("delta_review", self._verdict("ratify"), family="codex"),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]
        _path, state, _driver, mock = self._drive(
            script,
            lambda value: value["milestone"]["status"] == st.M_CLOSED,
        )
        units = {st.unit_key(unit): unit for unit in state["units"]}
        impl = units["slice_impl-01"]
        note = units["slice_doc-01"]
        self.assertIsNone(state.get("failure"))
        self.assertEqual(impl["design_correction"]["phase"], "ratified")
        self.assertEqual(note["gate_commit"], impl["gate_commit"])
        self.assertEqual(mock.script, [])
        with open(os.path.join(self.ws, self.NOTE), encoding="utf-8") as fh:
            self.assertIn("clamp the requested size to 30", fh.read())

    def test_retry_reuses_existing_dirty_delta_loop(self):
        retry_finding = finding("D1", "the regression assertion is incomplete", "P1")
        script = self._prefix() + [
            self._fix_step(),
            step(
                "delta_review",
                self._verdict("retry", [retry_finding]),
                family="codex",
            ),
            step(
                "fix_findings",
                fix_ok(
                    [triaged("D1", "fixed", retry_finding["summary"], "P1")],
                    files_changed=["test_impl.py"],
                ),
                family="codex",
                side_effect=write_file(
                    "test_impl.py", "assert min(50, 30) == 30\n"
                ),
            ),
            step("delta_review", self._verdict("ratify"), family="codex"),
        ]
        _path, state, _driver, mock = self._drive(
            script,
            lambda value: (
                (st.current_unit(value) or {}).get("design_correction", {}).get(
                    "phase"
                ) == "ratified"
            ),
        )
        self.assertIsNone(state.get("failure"))
        fix_prompts = [
            prompt for _family, kind, prompt in mock.calls
            if kind == "fix_findings"
        ]
        self.assertIn("ONE-SHOT OWN-NOTE CORRECTION", fix_prompts[-2])
        self.assertIn(
            "sealed note provisionally EDITABLE", fix_prompts[-2]
        )
        self.assertIn(
            "OWN-NOTE CORRECTION declared elsewhere", fix_prompts[-2]
        )
        self.assertIn("CORRECTION IN PROGRESS", fix_prompts[-1])
        self.assertIn(
            "note remains EDITABLE", fix_prompts[-1]
        )

    def test_rejected_correction_after_dirty_delta_preserves_prior_fix(self):
        retry_finding = finding("D1", "the regression assertion is incomplete")
        script = self._prefix() + [
            step(
                "fix_findings",
                fix_ok(
                    [triaged("SIZE", "fixed", "clamp the request", "P1")],
                    files_changed=["impl.py"],
                ),
                family="codex",
                side_effect=write_file("impl.py", "limit = 30\n"),
            ),
            step(
                "delta_review",
                report("delta_review", [retry_finding]),
                family="codex",
            ),
            step(
                "fix_findings",
                fix_ok(
                    [triaged("D1", "fixed", retry_finding["summary"], "P1")],
                    files_changed=[self.SKELETON, "test_impl.py"],
                    design_correction=self._correction(self.SKELETON),
                ),
                family="codex",
                side_effect=lambda workspace: (
                    append_file(
                        self.SKELETON, "Correction: wrong target.\n"
                    )(workspace),
                    write_file(
                        "test_impl.py", "assert min(50, 30) == 30\n"
                    )(workspace),
                ),
            ),
        ]
        _path, state, _driver, mock = self._drive(
            script,
            lambda value: any(
                event.get("type") == "design_correction_rolled_back"
                for event in value["events"]
            ),
        )
        self.assertIsNone(state.get("failure"))
        fix_prompts = [
            prompt for _family, kind, prompt in mock.calls
            if kind == "fix_findings"
        ]
        self.assertIn("ONE-SHOT OWN-NOTE CORRECTION", fix_prompts[0])
        self.assertIn("ONE-SHOT OWN-NOTE CORRECTION", fix_prompts[1])
        with open(os.path.join(self.ws, "impl.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "limit = 30\n")

    def test_ratified_note_remains_canonical_during_later_fixes(self):
        late = finding("LATE", "implementation cleanup remains", "P1")
        script = self._prefix() + [
            self._fix_step(),
            step("delta_review", self._verdict("ratify"), family="codex"),
            step(
                "review_round",
                report("review_round", [late]),
                family="codex",
            ),
            step(
                "fix_findings",
                fix_ok(
                    [triaged("LATE", "fixed", late["summary"], "P1")],
                    files_changed=["impl.py"],
                ),
                family="codex",
                side_effect=write_file("impl.py", "limit = min(50, 30)\n"),
            ),
        ]
        _path, state, _driver, _mock = self._drive(
            script,
            lambda value: (
                (st.current_unit(value) or {}).get("status")
                == st.U_DELTA_REVIEW
            ),
        )
        self.assertIsNone(state.get("failure"))
        units = {st.unit_key(unit): unit for unit in state["units"]}
        note_gate = units["slice_doc-01"]["gate_commit"]
        self.assertIsNone(gitops.show_file(self.ws, note_gate, "impl.py"))
        with open(os.path.join(self.ws, self.NOTE), encoding="utf-8") as fh:
            self.assertIn("clamp the requested size to 30", fh.read())

    def test_later_fixer_remodel_keeps_the_ratified_note(self):
        late = finding("LATE", "implementation cleanup remains", "P1")
        script = self._prefix() + [
            self._fix_step(),
            step("delta_review", self._verdict("ratify"), family="codex"),
            step(
                "review_round",
                report("review_round", [late]),
                family="codex",
            ),
            step(
                "fix_findings",
                self._fixer_gap("fits_remodel"),
                family="codex",
            ),
        ]
        _path, state, _driver, _mock = self._drive(
            script,
            lambda value: bool(value.get("redoc_wave")),
        )
        units = {st.unit_key(unit): unit for unit in state["units"]}
        self.assertEqual(units["slice_impl-01"]["status"], st.U_PENDING)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "impl.py")))
        with open(os.path.join(self.ws, self.NOTE), encoding="utf-8") as fh:
            self.assertIn("clamp the requested size to 30", fh.read())

    def test_later_fixer_operator_gap_keeps_the_ratified_note(self):
        late = finding("LATE", "implementation cleanup remains", "P1")
        script = self._prefix() + [
            self._fix_step(),
            step("delta_review", self._verdict("ratify"), family="codex"),
            step(
                "review_round",
                report("review_round", [late]),
                family="codex",
            ),
            step(
                "fix_findings",
                self._fixer_gap("needs_operator"),
                family="codex",
            ),
        ]
        _path, state, _driver, _mock = self._drive(
            script,
            lambda value: bool(value.get("failure")),
        )
        units = {st.unit_key(unit): unit for unit in state["units"]}
        self.assertEqual(state["failure"]["type"], "goal_gap")
        self.assertEqual(
            units["slice_impl-01"].get("failed_from"), st.U_PENDING
        )
        self.assertFalse(os.path.exists(os.path.join(self.ws, "impl.py")))
        with open(os.path.join(self.ws, self.NOTE), encoding="utf-8") as fh:
            self.assertIn("clamp the requested size to 30", fh.read())

    def test_resume_rechecks_authority_before_ratification(self):
        path, state, _driver, _mock = self._drive(
            self._prefix() + [self._fix_step()],
            lambda value: (
                (st.current_unit(value) or {}).get("design_correction", {}).get(
                    "phase"
                ) == "proposed"
            ),
        )
        self.assertIsNone(state.get("failure"))
        append_file(
            self.SKELETON, "Changed while the run was stopped.\n"
        )(self.ws)
        resumed = drv.Driver(
            path,
            runner=runners.MockRunner([
                step(
                    "delta_review",
                    self._verdict("ratify"),
                    family="codex",
                )
            ]),
        )
        resumed.step()
        state = st.load(path)
        unit = st.current_unit(state)
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertIsNone(unit.get("design_correction"))
        self.assertFalse(any(
            event.get("type") == "design_correction_ratified"
            for event in state["events"]
        ))
        with open(os.path.join(self.ws, self.SKELETON), encoding="utf-8") as fh:
            self.assertNotIn("Changed while", fh.read())

    def test_retry_cannot_ratify_a_note_reverted_to_its_original_text(self):
        retry_finding = finding("D1", "the regression assertion is incomplete")
        script = self._prefix() + [
            self._fix_step(),
            step(
                "delta_review",
                self._verdict("retry", [retry_finding]),
                family="codex",
            ),
            step(
                "fix_findings",
                fix_ok(
                    [triaged("D1", "fixed", retry_finding["summary"], "P1")],
                    files_changed=[self.NOTE, "test_impl.py"],
                ),
                family="codex",
                side_effect=lambda workspace: (
                    write_file(
                        self.NOTE,
                        "# Slice 01\n\nRequest the page size directly (50).\n",
                    )(workspace),
                    write_file("test_impl.py", "assert limit == 30\n")(
                        workspace
                    ),
                ),
            ),
            step("delta_review", self._verdict("ratify"), family="codex"),
        ]
        _path, state, _driver, _mock = self._drive(
            script,
            lambda value: any(
                event.get("type") == "design_correction_rolled_back"
                for event in value["events"]
            ),
        )
        unit = st.current_unit(state)
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertIsNone(unit.get("design_correction"))
        self.assertFalse(any(
            event.get("type") == "design_correction_ratified"
            for event in state["events"]
        ))
        with open(os.path.join(self.ws, self.NOTE), encoding="utf-8") as fh:
            self.assertNotIn("Correction:", fh.read())

    def test_wrong_note_is_rolled_back_and_permission_is_consumed(self):
        script = self._prefix() + [self._fix_step(self.SKELETON)]
        _path, state, driver, _mock = self._drive(
            script,
            lambda value: any(
                event.get("type") == "design_correction_rolled_back"
                for event in value["events"]
            ),
        )
        unit = st.current_unit(state)
        self.assertIsNone(state.get("failure"))
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertTrue(unit["design_correction_attempted"])
        self.assertIsNone(unit.get("design_correction"))
        self.assertIsNone(driver._design_correction_offer(unit))
        with open(os.path.join(self.ws, self.SKELETON), encoding="utf-8") as fh:
            self.assertNotIn("Correction:", fh.read())

    def test_remodel_verdict_uses_existing_gap_router(self):
        script = self._prefix() + [
            self._fix_step(),
            step("delta_review", self._verdict("remodel"), family="codex"),
        ]
        _path, state, _driver, _mock = self._drive(
            script,
            lambda value: bool(value.get("redoc_wave")),
        )
        units = {st.unit_key(unit): unit for unit in state["units"]}
        self.assertIsNone(state.get("failure"))
        self.assertEqual(units["skeleton"]["status"], st.U_FIXING)
        self.assertEqual(units["slice_doc-01"]["status"], st.U_REPAIRING)
        self.assertEqual(units["slice_impl-01"]["status"], st.U_PENDING)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "impl.py")))
        with open(os.path.join(self.ws, self.NOTE), encoding="utf-8") as fh:
            self.assertNotIn("Correction:", fh.read())


class DesignCorrectionContractTest(unittest.TestCase):
    def test_verdict_shape_enforces_clean_ratify_and_actionable_retry(self):
        base = {"status": "ok", "kind": "delta_review"}
        contracts.validate_worker_output(
            {
                **base,
                "findings": [],
                "design_correction_verdict": {
                    "decision": "ratify",
                    "reason": "one authority uniquely resolves it",
                },
            },
            "delta_review",
            require_design_correction_verdict=True,
        )
        for decision, findings in (("ratify", [finding("F", "bug")]),
                                   ("retry", [])):
            with self.subTest(decision=decision):
                with self.assertRaises(contracts.ContractError):
                    contracts.validate_worker_output(
                        {
                            **base,
                            "findings": findings,
                            "design_correction_verdict": {
                                "decision": decision,
                                "reason": "invalid combination",
                            },
                        },
                        "delta_review",
                        require_design_correction_verdict=True,
                    )
