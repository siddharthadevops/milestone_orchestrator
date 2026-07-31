"""Focused regression coverage for scheduled full-suite verification.

The complete suite is a milestone-level checkpoint, not a per-unit tax:

* skeleton and slice documentation never run it;
* implementation starts directly, without a baseline suite;
* every four completed logical slices run it once;
* the milestone's final logical slice always runs it;
* sequential implementation parts count as one logical slice.

Review rounds continue to use only their focused checks.  These tests pin the
deterministic scheduling and retain the existing full-suite repair coverage.
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
    DriverTestCase,
    fix_ok,
    init_state,
    make_config,
    ok,
    report,
    step,
    write_file,
)


def _counter_command(name):
    return (
        "n=$(cat .orchestrator/%s 2>/dev/null || echo 0); "
        "n=$((n+1)); printf '%%s' \"$n\" > .orchestrator/%s"
        % (name, name)
    )


def _count(workspace, name):
    path = os.path.join(workspace, ".orchestrator", name)
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as handle:
        return int(handle.read() or "0")


def _slices(count):
    return [
        {"id": slice_id, "title": "Feature %02d" % slice_id}
        for slice_id in range(1, count + 1)
    ]


def _skeleton_step(slice_count):
    return step(
        contracts.KIND_DRAFT_SKELETON,
        ok(
            contracts.KIND_DRAFT_SKELETON,
            artifact="docs/skeleton.md",
            slices=_slices(slice_count),
        ),
        family="codex",
        side_effect=write_file(
            "docs/skeleton.md",
            "# Milestone\n\n%d implementation slices.\n" % slice_count,
        ),
    )


def _doc_step(slice_id):
    path = "docs/slice-%02d.md" % slice_id
    return step(
        contracts.KIND_DRAFT_SLICE_NOTE,
        ok(contracts.KIND_DRAFT_SLICE_NOTE, artifact=path),
        family="codex",
        side_effect=write_file(
            path,
            "# Slice %02d\n\nImplement feature %02d.\n"
            % (slice_id, slice_id),
        ),
    )


def _impl_step(slice_id, part=None, cut=None):
    suffix = "_%s" % part if part else ""
    path = "feature_%02d%s.py" % (slice_id, suffix)
    result = ok(contracts.KIND_IMPLEMENT, files_changed=[path])
    if cut is not None:
        result["implementation_cut"] = {
            "cut_scope": cut[0],
            "remaining_scope": cut[1],
        }
    return step(
        contracts.KIND_IMPLEMENT,
        result,
        family="codex",
        side_effect=write_file(
            path,
            "SLICE = %d\nPART = %r\n" % (slice_id, part or "whole"),
        ),
    )


def _clean_reviews():
    return [
        step(
            contracts.KIND_REVIEW_ROUND,
            report(contracts.KIND_REVIEW_ROUND),
            family="codex",
        ),
        step(
            contracts.KIND_REVIEW_ROUND,
            report(contracts.KIND_REVIEW_ROUND),
            family="claude",
        ),
    ]


def _clean_milestone_script(slice_count, split_slice=None):
    script = [_skeleton_step(slice_count)] + _clean_reviews()
    for slice_id in range(1, slice_count + 1):
        script.append(_doc_step(slice_id))
        script.extend(_clean_reviews())
        if slice_id == split_slice:
            script.append(
                _impl_step(
                    slice_id,
                    "a",
                    ("coherent core", "remaining wiring and integration"),
                )
            )
            script.extend(_clean_reviews())
            script.append(
                _impl_step(
                    slice_id,
                    "b",
                    ("remaining wiring", "final integration"),
                )
            )
            script.extend(_clean_reviews())
            script.append(_impl_step(slice_id, "c"))
            script.extend(_clean_reviews())
        else:
            script.append(_impl_step(slice_id))
            script.extend(_clean_reviews())
    return script


class TestVerificationChronology(DriverTestCase):
    @staticmethod
    def _verification_events(state):
        return [
            event
            for event in state["events"]
            if event["type"] == "verification"
        ]

    @staticmethod
    def _unit(state, key):
        return next(unit for unit in state["units"] if st.unit_key(unit) == key)

    def test_documentation_runs_no_full_suite_and_impl_starts_directly(self):
        counter = "docs-suite-count"
        command = _counter_command(counter)
        with tempfile.TemporaryDirectory(prefix="orch-verify-docs-") as ws:
            path = init_state(ws, make_config(verification=[command]))
            mock = runners.MockRunner(
                [_skeleton_step(1)]
                + _clean_reviews()
                + [_doc_step(1)]
                + _clean_reviews()
                + [_impl_step(1)]
            )
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda state: (
                    st.current_unit(state) is not None
                    and st.current_unit(state)["kind"] == st.UNIT_SLICE_IMPL
                    and st.current_unit(state)["status"] == st.U_PENDING
                ),
                max_steps=20,
            )

            self.assertEqual(_count(ws, counter), 0)
            self.assertEqual(self._verification_events(st.load(path)), [])
            deferred = [
                event
                for event in st.load(path)["events"]
                if event["type"] == "verification_deferred"
                and event.get("boundary") == "slice_checkpoint"
            ]
            self.assertEqual(
                [event["unit"] for event in deferred],
                ["skeleton", "slice_doc-01"],
            )
            self.assertEqual(drv.decide(driver.state).type, drv.A_DRAFT)

            action, _note = driver.step()
            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertEqual(_count(ws, counter), 0)
            self.assertNotIn(
                "baseline_verification", st.current_unit(st.load(path))
            )
            self.assertEqual(mock.script, [])

    def test_every_four_logical_slices_and_final_with_split_parts(self):
        counter = "cadence-suite-count"
        command = _counter_command(counter)
        with tempfile.TemporaryDirectory(prefix="orch-verify-cadence-") as ws:
            path = init_state(ws, make_config(verification=[command]))
            mock = runners.MockRunner(
                _clean_milestone_script(5, split_slice=4)
            )
            driver = drv.Driver(path, runner=mock)

            _actions, final = self.drive(driver, max_steps=120)

            self.assertEqual(final.type, drv.A_DONE)
            self.assertEqual(mock.script, [])
            self.assertEqual(_count(ws, counter), 2)
            state = st.load(path)
            events = self._verification_events(state)
            self.assertEqual(
                [
                    (
                        event["unit"],
                        event.get("cadence"),
                        event.get("boundary"),
                    )
                    for event in events
                ],
                [
                    (
                        "slice_impl-04-c",
                        "four_slice_checkpoint",
                        "final",
                    ),
                    ("slice_impl-05", "milestone_final", "final"),
                ],
            )
            self.assertTrue(all(event["ok"] for event in events))
            self.assertTrue(all(not event.get("reused") for event in events))
            self.assertFalse(any(
                event.get("boundary") == "baseline" for event in events
            ))

            split_closures = [
                event["unit"]
                for event in state["events"]
                if event["type"] == "slice_closed"
                and event.get("slice_id") == 4
            ]
            self.assertEqual(
                split_closures,
                ["slice_impl-04", "slice_impl-04-b", "slice_impl-04-c"],
            )
            self.assertFalse(any(
                event["unit"] in {"slice_impl-04", "slice_impl-04-b"}
                for event in events
            ))

            for event in events:
                last_review_seq = max(
                    candidate["seq"]
                    for candidate in state["events"]
                    if candidate["type"] == "round_recorded"
                    and candidate.get("unit") == event["unit"]
                    and candidate.get("kind")
                    == contracts.KIND_REVIEW_ROUND
                )
                self.assertGreater(event["seq"], last_review_seq)

    def test_milestone_final_runs_before_four_slices(self):
        counter = "short-final-suite-count"
        command = _counter_command(counter)
        with tempfile.TemporaryDirectory(prefix="orch-verify-short-") as ws:
            path = init_state(ws, make_config(verification=[command]))
            mock = runners.MockRunner(_clean_milestone_script(3))
            driver = drv.Driver(path, runner=mock)

            _actions, final = self.drive(driver, max_steps=80)

            self.assertEqual(final.type, drv.A_DONE)
            self.assertEqual(mock.script, [])
            self.assertEqual(_count(ws, counter), 1)
            events = self._verification_events(st.load(path))
            self.assertEqual(
                [
                    (event["unit"], event.get("cadence"))
                    for event in events
                ],
                [("slice_impl-03", "milestone_final")],
            )

    def test_checkpoint_counter_restarts_after_each_four_slices(self):
        with tempfile.TemporaryDirectory(prefix="orch-verify-repeat-") as ws:
            path = init_state(ws, make_config())
            driver = drv.Driver(path, runner=runners.MockRunner([]))
            driver.state["milestone"]["slices"] = _slices(9)
            driver.state["units"] = [
                st._new_unit(st.UNIT_SLICE_IMPL, slice_id)
                for slice_id in range(1, 10)
            ]

            for slice_id in (1, 2, 3):
                st.append_event(
                    driver.state, "slice_closed",
                    unit="slice_impl-%02d" % slice_id,
                )
            self.assertEqual(
                driver._full_verification_cadence(driver.state["units"][3]),
                "four_slice_checkpoint",
            )
            st.append_event(
                driver.state, "verification", unit="slice_impl-04",
                ok=True, stable=True, cadence="four_slice_checkpoint",
            )
            self.assertEqual(
                driver._full_verification_cadence(driver.state["units"][3]),
                "four_slice_checkpoint",
            )
            st.append_event(
                driver.state, "slice_closed", unit="slice_impl-04",
            )
            self.assertIsNone(
                driver._full_verification_cadence(driver.state["units"][4])
            )

            for slice_id in (5, 6, 7):
                st.append_event(
                    driver.state, "slice_closed",
                    unit="slice_impl-%02d" % slice_id,
                )
            self.assertEqual(
                driver._full_verification_cadence(driver.state["units"][7]),
                "four_slice_checkpoint",
            )
            st.append_event(
                driver.state, "verification", unit="slice_impl-08",
                ok=True, stable=True, cadence="four_slice_checkpoint",
            )
            st.append_event(
                driver.state, "slice_closed", unit="slice_impl-08",
            )
            self.assertEqual(
                driver._full_verification_cadence(driver.state["units"][8]),
                "milestone_final",
            )

    def test_reused_scheduled_checkpoint_restarts_counter(self):
        with tempfile.TemporaryDirectory(prefix="orch-verify-reused-") as ws:
            path = init_state(ws, make_config())
            driver = drv.Driver(path, runner=runners.MockRunner([]))
            driver.state["milestone"]["slices"] = _slices(13)
            driver.state["units"] = [
                st._new_unit(st.UNIT_SLICE_IMPL, slice_id)
                for slice_id in range(1, 14)
            ]
            for slice_id in (1, 2, 3):
                st.append_event(
                    driver.state, "slice_closed",
                    unit="slice_impl-%02d" % slice_id,
                )
            st.append_event(
                driver.state, "verification", unit="slice_impl-04",
                ok=True, stable=True, cadence="four_slice_checkpoint",
            )
            st.append_event(
                driver.state, "slice_closed", unit="slice_impl-04",
            )
            for slice_id in (5, 6, 7):
                st.append_event(
                    driver.state, "slice_closed",
                    unit="slice_impl-%02d" % slice_id,
                )
            st.append_event(
                driver.state, "verification", unit="slice_impl-08",
                ok=True, stable=True, reused=True,
                cadence="four_slice_checkpoint",
            )
            st.append_event(
                driver.state, "slice_closed", unit="slice_impl-08",
            )

            self.assertIsNone(
                driver._full_verification_cadence(driver.state["units"][8])
            )
            for slice_id in (9, 10, 11):
                st.append_event(
                    driver.state, "slice_closed",
                    unit="slice_impl-%02d" % slice_id,
                )
            self.assertEqual(
                driver._full_verification_cadence(driver.state["units"][11]),
                "four_slice_checkpoint",
            )

    def test_review_evidence_preserves_command_boundaries(self):
        split = ["export ORCH_FLAG=1", 'test "$ORCH_FLAG" = 1']
        joined = ['export ORCH_FLAG=1 && test "$ORCH_FLAG" = 1']
        with tempfile.TemporaryDirectory(prefix="orch-review-commands-") as ws:
            path = init_state(ws, make_config(verification=split))
            driver = drv.Driver(path, runner=runners.MockRunner([]))
            unit = st.current_unit(driver.state)

            split_fingerprint = driver._review_evidence_fingerprint(unit)
            driver.config["verification"] = joined
            joined_fingerprint = driver._review_evidence_fingerprint(unit)

            self.assertNotEqual(split_fingerprint, joined_fingerprint)

    def test_due_suite_failure_fixes_then_rereviews_before_seal(self):
        marker = "suite-green.marker"
        command = "test -f %s" % marker
        script = _clean_milestone_script(1) + [
            step(
                contracts.KIND_FIX_FINDINGS,
                fix_ok([], files_changed=[marker]),
                family="codex",
                side_effect=write_file(marker, "green\n"),
            ),
            step(
                contracts.KIND_DELTA_REVIEW,
                report(contracts.KIND_DELTA_REVIEW),
                family="codex",
            ),
        ] + _clean_reviews()
        with tempfile.TemporaryDirectory(prefix="orch-verify-final-fix-") as ws:
            path = init_state(ws, make_config(verification=[command]))
            mock = runners.MockRunner(script)
            driver = drv.Driver(path, runner=mock)

            _actions, final = self.drive(driver, max_steps=40)

            self.assertEqual(final.type, drv.A_DONE)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            events = self._verification_events(state)
            self.assertEqual([event["ok"] for event in events], [False, True, True])
            self.assertEqual(events[0].get("cadence"), "milestone_final")
            self.assertTrue(events[1].get("fixer_certified"))
            self.assertFalse(events[1].get("reused"))
            self.assertTrue(events[2].get("reused"))
            self.assertEqual(events[2].get("cadence"), "milestone_final")
            self.assertFalse(any(
                event.get("boundary") == "baseline" for event in events
            ))

            impl = self._unit(state, "slice_impl-01")
            reviews = [
                round_info
                for round_info in impl["rounds"]
                if round_info["kind"] == contracts.KIND_REVIEW_ROUND
            ]
            self.assertEqual(
                [round_info["family"] for round_info in reviews],
                ["codex", "claude", "codex", "claude"],
            )
            fixes = [
                round_info
                for round_info in impl["rounds"]
                if round_info["kind"] == contracts.KIND_FIX_FINDINGS
            ]
            self.assertEqual(len(fixes), 1)
            self.assertEqual(
                fixes[0]["source_round_id"],
                "slice_impl-01-verify-pre_seal-1",
            )
            review_events = [
                event
                for event in state["events"]
                if event["type"] == "round_recorded"
                and event.get("unit") == "slice_impl-01"
                and event.get("kind") == "review_round"
            ]
            self.assertGreater(events[-1]["seq"], review_events[-1]["seq"])

    def test_due_suite_fixer_commit_is_folded_into_reviewed_wip(self):
        marker = "suite-green.marker"
        command = (
            "test -f %s && test -z \"$(git status --porcelain)\"" % marker
        )

        def commit_repair(workspace):
            write_file(marker, "green\n")(workspace)
            subprocess.run(
                ["git", "add", "-A"],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            subprocess.run(
                ["git", "commit", "-qm", "fixer-owned repair"],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )

        script = _clean_milestone_script(1) + [
            step(
                contracts.KIND_FIX_FINDINGS,
                fix_ok([], files_changed=[marker]),
                family="codex",
                side_effect=commit_repair,
            ),
            step(
                contracts.KIND_DELTA_REVIEW,
                report(contracts.KIND_DELTA_REVIEW),
                family="codex",
            ),
        ] + _clean_reviews()
        with tempfile.TemporaryDirectory(prefix="orch-verify-commit-fix-") as ws:
            path = init_state(ws, make_config(verification=[command]))
            mock = runners.MockRunner(script)
            driver = drv.Driver(path, runner=mock)

            _actions, final = self.drive(driver, max_steps=40)

            self.assertEqual(final.type, drv.A_DONE)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            self.assertFalse(any(
                event["type"] == "phantom_fix_retry"
                for event in state["events"]
            ))
            folded = [
                event
                for event in state["events"]
                if event["type"] == "fixer_commits_folded"
            ]
            self.assertEqual(len(folded), 1)
            self.assertEqual(folded[0]["commit_count"], 1)
            impl = self._unit(state, "slice_impl-01")
            reviews = [
                round_info
                for round_info in impl["rounds"]
                if round_info["kind"] == contracts.KIND_REVIEW_ROUND
            ]
            self.assertEqual(
                [round_info["family"] for round_info in reviews],
                ["codex", "claude", "codex", "claude"],
            )
            self.assertTrue(os.path.isfile(os.path.join(ws, marker)))
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=ws,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                ).stdout,
                "",
            )
            subjects = subprocess.run(
                ["git", "log", "--format=%s"],
                cwd=ws,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout
            self.assertNotIn("fixer-owned repair", subjects)


if __name__ == "__main__":
    unittest.main()
