"""Driver-level checks for the lightweight design-update rethink path."""

import os
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming_milestone
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import gitops
from orchestrator import runners
from orchestrator import state as st


class _Captured(RuntimeError):
    pass


def _unit(kind, slice_id, status, artifact=None):
    return {
        "kind": kind,
        "slice_id": slice_id,
        "status": status,
        "artifact": artifact,
        "rounds": [],
        "seals": [],
        "family_index": 0,
    }


class DesignUpdateRethinkTest(unittest.TestCase):
    PATHS = [
        "docs/skeleton.md",
        "docs/slice-01.md",
        "docs/slice-02.md",
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="design-update-")
        self.addCleanup(self.tmp.cleanup)
        self.workspace = self.tmp.name
        for path in self.PATHS:
            self._write(path, "current %s\n" % path)

    def _write(self, relpath, text):
        path = os.path.join(self.workspace, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    @staticmethod
    def _config(modern=True, git=False):
        config = {
            "families_order": ["codex", "claude"],
            "commands": {"codex": [], "claude": []},
            "git": {"enabled": git},
            "max_fix_loops": 6,
            "max_rounds_per_family": 6,
            "delta_full_review_after_fixes": 0,
        }
        if modern is not None:
            config["rethink_design_updates"] = modern
        return config

    def _state(self, current_status=st.U_FIXING):
        skeleton = _unit(
            st.UNIT_SKELETON, None, st.U_SEALED, self.PATHS[0]
        )
        note_1 = _unit(
            st.UNIT_SLICE_DOC, 1, st.U_SEALED, self.PATHS[1]
        )
        current = _unit(
            st.UNIT_SLICE_IMPL, 1, current_status, "src/current.py"
        )
        note_2 = _unit(
            st.UNIT_SLICE_DOC, 2, st.U_PENDING, self.PATHS[2]
        )
        return {
            "workspace": self.workspace,
            "config": {"families_order": ["codex", "claude"]},
            "milestone": {
                "status": st.M_OPEN,
                "slices": [
                    {"id": 1, "title": "one"},
                    {"id": 2, "title": "two"},
                ],
            },
            "units": [skeleton, note_1, current, note_2],
            "events": [],
            "failure": None,
        }, current

    def _driver(self, state, modern=True, git=False):
        driver = object.__new__(drv.Driver)
        driver.state = state
        driver.config = self._config(modern=modern, git=git)
        driver.workspace = self.workspace
        driver.state_path = os.path.join(self.workspace, "state.json")
        return driver

    @staticmethod
    def _signal(kind, failure=None):
        signal = {
            "status": "need_rethink",
            "kind": kind,
            "question": "Which in-goal design should govern?",
            "finding": {"id": "F1", "summary": "the design conflicts"},
            "target_path": "docs/skeleton.md",
            "max_rounds": 5,
            "result_mode": contracts.RETHINK_RESULT_DESIGN_AMENDMENT,
        }
        if failure is not None:
            signal["failure_gap"] = failure
        return signal

    @staticmethod
    def _handoff(outcome):
        return {
            "session_id": "brainstorming-1",
            "accepted_target_revision": 2,
            "result": {"outcome": outcome},
            "retained_target": {
                "exists": True,
                "encoding": "utf-8",
                "content": "Use the existing contract consistently.",
            },
        }

    def _wait(self, unit, kind=contracts.KIND_IMPLEMENT, failure=None):
        return {
            "session_id": "brainstorming-1",
            "signal": self._signal(kind, failure=failure),
            "references": list(self.PATHS),
            "origin": {
                "unit": st.unit_key(unit),
                "kind": kind,
                "family": "codex",
                "model": "gpt-5.6-sol",
                "effort": "max",
                "raw_name": "slice_impl-01-draft",
                "provider_session_ref": "codex-thread-7",
                "duration_s": 1.0,
                "pre_snapshot": {},
            },
        }

    def test_accepted_amendment_authorizes_existing_design_and_resumes_session(
        self,
    ):
        state, unit = self._state(st.U_FIXING)
        driver = self._driver(state, modern=True)
        unit["brainstorming_wait"] = self._wait(unit)
        driver._project_prompt_inputs = mock.Mock(
            return_value=(None, [], [])
        )
        driver._amendments = mock.Mock(
            return_value=[{
                "id": "B1",
                "text": "Use the existing contract consistently.",
                "authority": "brainstorming_design",
            }]
        )
        continued = {
            "status": "ok",
            "kind": contracts.KIND_IMPLEMENT,
            "files_changed": ["src/current.py"],
        }
        worker_result = runners.RunnerResult("{}", 0, 0.2)
        driver._call = mock.Mock(
            return_value=(continued, worker_result, "raw/continued.txt")
        )
        handoff = self._handoff("success")

        with mock.patch.object(
            brainstorming_milestone, "terminal_handoff", return_value=handoff
        ), mock.patch.object(
            brainstorming_milestone, "prompt_handoff", return_value=handoff
        ):
            note = driver._do_brainstorming_wait()

        self.assertEqual(
            driver._editable_design_paths(unit), self.PATHS
        )
        self.assertEqual(
            unit["design_update"]["amendment"],
            "Use the existing contract consistently.",
        )
        call = driver._call.call_args
        prompt = call.args[1]
        self.assertEqual(call.kwargs["session_ref"], "codex-thread-7")
        self.assertEqual(call.kwargs["model"], "gpt-5.6-sol")
        self.assertEqual(call.kwargs["effort"], "max")
        for path in self.PATHS:
            self.assertIn(path, prompt)
        self.assertNotIn("design_correction", prompt)
        self.assertIn("origin conversation continued", note)
        self.assertEqual(
            unit["brainstorming_resume"]["output"], continued
        )
        event_types = [event["type"] for event in state["events"]]
        self.assertIn("brainstorming_design_amendment_adopted", event_types)
        self.assertIn("brainstorming_design_update_authorized", event_types)
        self.assertIn("brainstorming_builder_continued", event_types)

    def test_brainstorming_work_is_recorded_once(self):
        state, unit = self._state(st.U_FIXING)
        driver = self._driver(state, modern=True)

        driver._record_brainstorming_work(unit, "brainstorming-1", 12.5)
        driver._record_brainstorming_work(unit, "brainstorming-1", 12.5)

        events = [
            event for event in state["events"]
            if event["type"] == "brainstorming_work_recorded"
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["duration_s"], 12.5)

    def test_guard_allows_design_docs_but_still_restores_other_work(self):
        state, current = self._state(st.U_FIXING)
        # Move the current pointer to slice 2 so slice 1 implementation is a
        # completed historical unit covered by the guard.
        old_impl = state["units"][2]
        old_impl["status"] = st.U_SEALED
        old_impl["artifact"] = "src/old.py"
        old_impl["gate_commit"] = "gate-1"
        state["units"][3]["status"] = st.U_SEALED
        current = _unit(st.UNIT_SLICE_IMPL, 2, st.U_FIXING, "src/new.py")
        state["units"].append(current)
        for design in state["units"][:2] + [state["units"][3]]:
            design["gate_commit"] = "gate-1"
        current["design_update"] = {"editable_paths": list(self.PATHS)}
        self._write("src/old.py", "changed code\n")
        for path in self.PATHS:
            self._write(path, "changed design\n")
        driver = self._driver(state, modern=True, git=True)
        driver._save_raw = mock.Mock(return_value="raw/violation.txt")

        with mock.patch.object(
            gitops, "newest_commit", return_value="gate-1"
        ), mock.patch.object(
            gitops, "show_file", return_value=b"canonical code\n"
        ) as show_file:
            restored = driver._enforce_sealed_artifacts(
                "fix", editable_sealed=driver._editable_design_paths(current)
            )

        self.assertEqual(restored, ["src/old.py"])
        with open(os.path.join(self.workspace, "src/old.py"), "rb") as handle:
            self.assertEqual(handle.read(), b"canonical code\n")
        for path in self.PATHS:
            with open(os.path.join(self.workspace, path), encoding="utf-8") \
                    as handle:
                self.assertEqual(handle.read(), "changed design\n")
        self.assertEqual(show_file.call_count, 1)

    def test_second_amendment_keeps_earlier_changed_paths(self):
        state, unit = self._state(st.U_FIXING)
        driver = self._driver(state, modern=True)
        unit["design_update"] = {
            "editable_paths": [self.PATHS[0]],
            "changed_paths": [self.PATHS[0]],
        }
        handoff = self._handoff("success")
        event = {"amendment_id": "B2", "text": "Second agreement"}

        driver._activate_design_update(unit, handoff, event)

        self.assertEqual(unit["design_update"]["changed_paths"], [self.PATHS[0]])
        self.assertEqual(unit["design_update"]["editable_paths"], self.PATHS)

    def test_amendment_can_insert_only_one_future_slice(self):
        state, unit = self._state(st.U_FIXING)
        driver = self._driver(state, modern=True)
        driver._save = mock.Mock()
        unit["design_update"] = {"editable_paths": list(self.PATHS)}
        output = {
            "slices": [
                {"id": 1, "title": "one"},
                {"id": 2, "title": "two"},
                {"id": 3, "title": "three"},
                {"id": 4, "title": "four"},
            ]
        }

        with self.assertRaisesRegex(drv.StopStep, "at most one"):
            driver._maybe_update_slices(unit, output)

        self.assertEqual(state["milestone"]["slices"][-1]["id"], 2)

    def test_modern_discussion_failure_stops_without_historical_gap_route(self):
        state, unit = self._state(st.U_FIXING)
        driver = self._driver(state, modern=True)
        unit["brainstorming_wait"] = self._wait(unit)
        driver._save = mock.Mock()
        driver._handle_gap = mock.Mock()

        with mock.patch.object(
            brainstorming_milestone,
            "terminal_handoff",
            return_value=self._handoff("failure"),
        ):
            with self.assertRaisesRegex(
                drv.StopStep, "ended without agreement"
            ):
                driver._do_brainstorming_wait()

        driver._handle_gap.assert_not_called()
        self.assertNotIn("brainstorming_wait", unit)
        self.assertEqual(state["failure"]["type"], "brainstorming_no_agreement")
        self.assertEqual(unit["status"], st.U_FAILED)

    def test_historical_discussion_failure_keeps_gap_repair_route(self):
        state, unit = self._state(st.U_FIXING)
        driver = self._driver(state, modern=None)
        failure = {
            "classification": "fits_remodel",
            "missing_or_conflict": "the old design is incomplete",
        }
        unit["brainstorming_wait"] = self._wait(unit, failure=failure)
        driver._handle_gap = mock.Mock(return_value="historical gap routed")

        with mock.patch.object(
            brainstorming_milestone,
            "terminal_handoff",
            return_value=self._handoff("failure"),
        ):
            note = driver._do_brainstorming_wait()

        self.assertEqual(note, "historical gap routed")
        self.assertFalse(driver._modern_design_updates())
        routed = driver._handle_gap.call_args.args[1]
        self.assertEqual(routed, {"gaps": [failure]})

    def test_historical_discussion_without_failure_gap_stops_cleanly(self):
        state, unit = self._state(st.U_FIXING)
        driver = self._driver(state, modern=None)
        wait = self._wait(unit, failure=None)
        wait["signal"].pop("failure_gap", None)
        unit["brainstorming_wait"] = wait
        driver._save = mock.Mock()

        with mock.patch.object(
            brainstorming_milestone,
            "terminal_handoff",
            return_value=self._handoff("failure"),
        ):
            with self.assertRaisesRegex(
                drv.StopStep, "missing legacy failure gap"
            ):
                driver._do_brainstorming_wait()

        self.assertEqual(state["failure"]["type"], "worker_protocol")

    def _prepare_prompt_driver(self, status):
        state, unit = self._state(status)
        unit["design_update"] = {
            "editable_paths": list(self.PATHS),
            "changed_paths": list(self.PATHS),
        }
        driver = self._driver(state, modern=True)
        driver._goal_for = mock.Mock(return_value="goal")
        driver._unit_desc = mock.Mock(return_value="slice implementation")
        driver._artifact = mock.Mock(return_value="src/current.py")
        driver._registry = mock.Mock(return_value=[])
        driver._amendments = mock.Mock(return_value=[])
        driver._debt = mock.Mock(return_value=[])
        driver._governing = mock.Mock(return_value="docs/slice-01.md")
        driver._wave_doc_paths = mock.Mock(return_value=None)
        driver._project_prompt_inputs = mock.Mock(
            return_value=(None, [], [])
        )
        driver._brainstorming_review_handoff = mock.Mock(return_value=None)
        return driver, unit

    @staticmethod
    def _capture_call(mocked):
        captured = {}

        def stop(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            raise _Captured()

        mocked.side_effect = stop
        return captured

    def test_scope_reaches_fixer_delta_and_full_review_without_special_verdict(
        self,
    ):
        prompts_seen = []

        fixer, fix_unit = self._prepare_prompt_driver(st.U_FIXING)
        fix_unit["fix_queue"] = [{
            "id": "F1", "severity": "P2", "summary": "claim"
        }]
        fix_unit["fix_source"] = {
            "type": "round", "family": "claude", "return_to": st.U_ROUNDS
        }
        fixer._act_profile = mock.Mock(return_value=("codex", None, None))
        fixer._resolve_act = mock.Mock(return_value="claude")
        fixer._snapshot = mock.Mock(return_value={})
        fixer._take_brainstorming_resume = mock.Mock(return_value=None)
        fixer._call = mock.Mock()
        fix_capture = self._capture_call(fixer._call)
        with self.assertRaises(_Captured):
            fixer._do_fix()
        prompts_seen.append(fix_capture["args"][1])

        delta, delta_unit = self._prepare_prompt_driver(st.U_DELTA_REVIEW)
        delta_unit["fix_source"] = {
            "type": "verification",
            "origin_type": "verification",
            "return_to": st.U_PRE_REVIEW_VERIFY,
        }
        delta_unit["rounds"] = [{
            "kind": contracts.KIND_FIX_FINDINGS, "family": "codex"
        }]
        delta._delta_review_profile = mock.Mock(
            return_value=("codex", None, None)
        )
        delta._report_call = mock.Mock()
        delta_capture = self._capture_call(delta._report_call)
        with mock.patch.object(gitops, "worktree_diff", return_value="diff"):
            with self.assertRaises(_Captured):
                delta._do_delta_review()
        prompts_seen.append(delta_capture["args"][2])
        self.assertNotIn(
            "require_design_correction_verdict",
            delta_capture["kwargs"].get("validate_opts") or {},
        )

        review, review_unit = self._prepare_prompt_driver(st.U_ROUNDS)
        review._review_evidence_inputs = mock.Mock(
            return_value=("fingerprint", None, [], [], [])
        )
        review._record_amendments_seen = mock.Mock()
        review._review_profile = mock.Mock(return_value=(None, None))
        review._report_call = mock.Mock()
        review_capture = self._capture_call(review._report_call)
        with self.assertRaises(_Captured):
            review._do_review_round()
        prompts_seen.append(review_capture["args"][2])

        for prompt in prompts_seen:
            for path in self.PATHS:
                self.assertIn(path, prompt)
            self.assertNotIn("design_correction", prompt)
            self.assertNotIn("design_correction_verdict", prompt)
            self.assertNotIn("RE-DOCUMENTATION", prompt)
            self.assertNotIn("RE-DOCUMENTER", prompt)


if __name__ == "__main__":
    unittest.main()
