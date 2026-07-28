"""Focused regression coverage for full-suite boundary chronology.

The full suite is a boundary proof, not a review-loop heartbeat:

* documentation goes straight to reviews and runs the suite only at final;
* an implementation verifies its untouched baseline before drafting, unless
  the immediately available final proof covers the exact bytes and commands;
* review/fix cycles use focused checks and return to whole-artifact reviews;
* only an actual, stable, non-vacuous green final run is reusable.

These tests intentionally live apart from the historical action-sequence
fixtures so the new contract is pinned before those fixtures are rewritten.
"""

import os
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
    triaged,
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


def _skeleton_step():
    return step(
        contracts.KIND_DRAFT_SKELETON,
        ok(
            contracts.KIND_DRAFT_SKELETON,
            artifact="docs/skeleton.md",
            slices=[{"id": 1, "title": "Core"}],
        ),
        family="codex",
        side_effect=write_file(
            "docs/skeleton.md", "# Milestone\n\nOne implementation slice.\n"
        ),
    )


def _doc_step():
    return step(
        contracts.KIND_DRAFT_SLICE_NOTE,
        ok(
            contracts.KIND_DRAFT_SLICE_NOTE,
            artifact="docs/slice-01.md",
        ),
        family="codex",
        side_effect=write_file(
            "docs/slice-01.md", "# Slice 01\n\nImplement the core.\n"
        ),
    )


def _impl_step():
    return step(
        contracts.KIND_IMPLEMENT,
        ok(contracts.KIND_IMPLEMENT, files_changed=["core.py"]),
        family="codex",
        side_effect=write_file("core.py", "VALUE = 1\n"),
    )


def _clean_docs_script():
    return [
        _skeleton_step(),
        step(contracts.KIND_REVIEW_ROUND,
             report(contracts.KIND_REVIEW_ROUND), family="codex"),
        step(contracts.KIND_REVIEW_ROUND,
             report(contracts.KIND_REVIEW_ROUND), family="claude"),
        _doc_step(),
        step(contracts.KIND_REVIEW_ROUND,
             report(contracts.KIND_REVIEW_ROUND), family="codex"),
        step(contracts.KIND_REVIEW_ROUND,
             report(contracts.KIND_REVIEW_ROUND), family="claude"),
    ]


class TestVerificationChronology(DriverTestCase):
    def _to_impl_pending(self, workspace, config, tail=None):
        path = init_state(workspace, config)
        mock = runners.MockRunner(_clean_docs_script() + list(tail or []))
        driver = drv.Driver(path, runner=mock)
        self.step_until(
            driver,
            lambda state: (
                st.current_unit(state) is not None
                and st.current_unit(state)["kind"] == st.UNIT_SLICE_IMPL
                and st.current_unit(state)["status"] == st.U_PENDING
            ),
            max_steps=30,
        )
        return path, mock, driver

    @staticmethod
    def _verification_events(state, boundary=None):
        events = [
            event for event in state["events"]
            if event["type"] == "verification"
        ]
        if boundary is not None:
            events = [
                event for event in events
                if event.get("boundary") == boundary
            ]
        return events

    def test_documentation_skips_pre_review_suite_and_runs_only_final(self):
        counter = "docs-suite-count"
        command = _counter_command(counter)
        with tempfile.TemporaryDirectory(prefix="orch-verify-boundary-") as ws:
            path = init_state(ws, make_config(verification=[command]))
            mock = runners.MockRunner(_clean_docs_script())
            driver = drv.Driver(path, runner=mock)

            # Skeleton draft and its compatibility verify waypoint open the
            # review cycle without executing the suite.
            self.assertEqual(driver.step()[0].type, drv.A_DRAFT)
            self.assertEqual(driver.step()[0].type, drv.A_VERIFY)
            self.assertEqual(_count(ws, counter), 0)
            driver.step()  # Codex
            driver.step()  # Claude
            self.assertEqual(_count(ws, counter), 0)
            self.assertEqual(driver.step()[0].type, drv.A_VERIFY)  # final
            self.assertEqual(_count(ws, counter), 1)

            # Slice documentation follows the same chronology.
            self.assertEqual(driver.step()[0].type, drv.A_DRAFT)
            self.assertEqual(driver.step()[0].type, drv.A_VERIFY)
            self.assertEqual(_count(ws, counter), 1)
            driver.step()  # Codex
            driver.step()  # Claude
            self.assertEqual(_count(ws, counter), 1)
            self.assertEqual(driver.step()[0].type, drv.A_VERIFY)  # final
            self.assertEqual(_count(ws, counter), 2)
            self.assertEqual(mock.script, [])

            state = st.load(path)
            actual = self._verification_events(state)
            self.assertEqual(
                [(event["unit"], event["boundary"]) for event in actual],
                [("skeleton", "final"), ("slice_doc-01", "final")],
            )
            self.assertTrue(all(event["ok"] for event in actual))
            deferred = [
                event for event in state["events"]
                if event["type"] == "verification_deferred"
            ]
            self.assertEqual(
                [event["unit"] for event in deferred],
                ["skeleton", "slice_doc-01"],
            )

    def test_impl_reuses_exact_final_proof_across_driver_restarts(self):
        counter = "reuse-suite-count"
        command = _counter_command(counter)
        with tempfile.TemporaryDirectory(prefix="orch-verify-reuse-") as ws:
            path, mock, _driver = self._to_impl_pending(
                ws,
                make_config(verification=[command]),
                tail=[_impl_step()],
            )
            self.assertEqual(_count(ws, counter), 2)

            # A fresh process can reuse the durable doc-final proof.
            resumed = drv.Driver(path, runner=mock)
            action, _note = resumed.step()
            self.assertEqual(action.type, drv.A_VERIFY)
            self.assertEqual(_count(ws, counter), 2)

            persisted = st.load(path)
            impl = st.current_unit(persisted)
            baseline = self._verification_events(persisted, "baseline")[-1]
            previous_final = self._verification_events(persisted, "final")[-1]
            self.assertTrue(baseline["reused"])
            self.assertEqual(baseline["reused_from_seq"], previous_final["seq"])
            self.assertEqual(
                impl["baseline_verification"]["candidate_fingerprint"],
                previous_final["candidate_after"],
            )
            self.assertEqual(impl["baseline_verification"]["commands"],
                             [command])

            # The baseline marker itself is durable across another restart;
            # the next step drafts instead of paying for the suite again.
            resumed_again = drv.Driver(path, runner=mock)
            action, _note = resumed_again.step()
            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertEqual(_count(ws, counter), 2)
            self.assertEqual(mock.script, [])

    def test_canonical_index_ignores_only_its_generated_block(self):
        command = _counter_command("canonical-index-count")
        config = make_config(
            verification=[command],
            docs_dir="implementation/milestones/{slug}",
        )
        with tempfile.TemporaryDirectory(prefix="orch-verify-index-") as ws:
            path, mock, _driver = self._to_impl_pending(
                ws, config, tail=[_impl_step()]
            )
            self.assertEqual(_count(ws, "canonical-index-count"), 2)

            # The documentation gate rewrote the generated index block after
            # the final suite. That mechanical projection alone must not make
            # the exact doc-final proof unusable.
            action, _note = drv.Driver(path, runner=mock).step()
            self.assertEqual(action.type, drv.A_VERIFY)
            self.assertEqual(_count(ws, "canonical-index-count"), 2)
            baseline = self._verification_events(
                st.load(path), "baseline"
            )[-1]
            self.assertTrue(baseline["reused"])

    def test_operator_prose_in_canonical_index_invalidates_reuse(self):
        command = _counter_command("index-prose-count")
        config = make_config(
            verification=[command],
            docs_dir="implementation/milestones/{slug}",
        )
        with tempfile.TemporaryDirectory(prefix="orch-verify-index-prose-") as ws:
            path, mock, _driver = self._to_impl_pending(
                ws, config, tail=[_impl_step()]
            )
            index_path = os.path.join(
                ws, "implementation", "milestones", "README.md"
            )
            with open(index_path, encoding="utf-8") as handle:
                current = handle.read()
            with open(index_path, "w", encoding="utf-8") as handle:
                handle.write("Operator-owned introduction.\n\n" + current)

            action, _note = drv.Driver(path, runner=mock).step()
            self.assertEqual(action.type, drv.A_VERIFY)
            self.assertEqual(_count(ws, "index-prose-count"), 3)
            baseline = self._verification_events(
                st.load(path), "baseline"
            )[-1]
            self.assertFalse(baseline.get("reused", False))

    def test_changed_bytes_prevent_final_proof_reuse(self):
        counter = "bytes-suite-count"
        command = _counter_command(counter)
        with tempfile.TemporaryDirectory(prefix="orch-verify-bytes-") as ws:
            path, mock, _driver = self._to_impl_pending(
                ws, make_config(verification=[command]), tail=[_impl_step()]
            )
            self.assertEqual(_count(ws, counter), 2)
            write_file("operator-change.txt", "changed\n")(ws)

            resumed = drv.Driver(path, runner=mock)
            action, _note = resumed.step()
            self.assertEqual(action.type, drv.A_VERIFY)
            self.assertEqual(_count(ws, counter), 3)
            baseline = self._verification_events(
                st.load(path), "baseline"
            )[-1]
            self.assertFalse(baseline.get("reused", False))
            self.assertNotEqual(
                baseline["candidate_after"],
                self._verification_events(st.load(path), "final")[-1][
                    "candidate_after"
                ],
            )

    def test_changed_bytes_after_reuse_are_rechecked_before_draft(self):
        counter = "race-suite-count"
        command = _counter_command(counter)
        with tempfile.TemporaryDirectory(prefix="orch-verify-race-") as ws:
            path, mock, _driver = self._to_impl_pending(
                ws, make_config(verification=[command]), tail=[_impl_step()]
            )
            drv.Driver(path, runner=mock).step()  # durable reuse
            self.assertEqual(_count(ws, counter), 2)
            write_file("between-baseline-and-draft.txt", "changed\n")(ws)

            resumed = drv.Driver(path, runner=mock)
            action, note = resumed.step()
            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertIn("baseline changed", note)
            self.assertEqual(len(mock.calls), 6)  # implementer not called

            action, _note = drv.Driver(path, runner=mock).step()
            self.assertEqual(action.type, drv.A_VERIFY)
            self.assertEqual(_count(ws, counter), 3)

    def test_changed_commands_prevent_final_proof_reuse(self):
        command_a = _counter_command("suite-a-count")
        command_b = _counter_command("suite-b-count")
        with tempfile.TemporaryDirectory(prefix="orch-verify-command-") as ws:
            path = init_state(ws, make_config(verification=[]))
            state = st.load(path)
            st.set_discovered_suite(state, command_a)
            st.save(path, state)
            mock = runners.MockRunner(_clean_docs_script() + [_impl_step()])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda current: (
                    st.current_unit(current)["kind"] == st.UNIT_SLICE_IMPL
                ),
                max_steps=30,
            )
            self.assertEqual(_count(ws, "suite-a-count"), 2)

            state = st.load(path)
            self.assertTrue(
                st.set_discovered_suite(state, command_b, replace=True)
            )
            st.save(path, state)
            action, _note = drv.Driver(path, runner=mock).step()
            self.assertEqual(action.type, drv.A_VERIFY)
            self.assertEqual(_count(ws, "suite-a-count"), 2)
            self.assertEqual(_count(ws, "suite-b-count"), 1)
            baseline = self._verification_events(
                st.load(path), "baseline"
            )[-1]
            self.assertFalse(baseline.get("reused", False))
            self.assertEqual(baseline["commands"], [command_b])

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

    def test_failures_and_mutating_runs_are_not_reusable(self):
        for label, invalid in (
            ("failed", {"ok": False, "stable": True}),
            ("mutating", {"ok": True, "stable": False}),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix="orch-verify-invalid-"
            ) as ws:
                path, mock, _driver = self._to_impl_pending(
                    ws, make_config(verification=[]), tail=[_impl_step()]
                )
                command = _counter_command("invalid-suite-count")
                state = st.load(path)
                st.set_discovered_suite(state, command, replace=True)
                st.save(path, state)
                probe = drv.Driver(path, runner=mock)
                fingerprint = probe._verification_candidate_fingerprint()
                state = st.load(path)
                st.append_event(
                    state,
                    "verification",
                    unit="slice_doc-01",
                    stage=st.U_PRE_SEAL_VERIFY,
                    boundary="final",
                    commands=[command],
                    candidate_before=fingerprint,
                    candidate_after=fingerprint,
                    vacuous=None,
                    **invalid
                )
                st.save(path, state)

                action, _note = drv.Driver(path, runner=mock).step()
                self.assertEqual(action.type, drv.A_VERIFY)
                self.assertEqual(_count(ws, "invalid-suite-count"), 1)
                baseline = self._verification_events(
                    st.load(path), "baseline"
                )[-1]
                self.assertFalse(baseline.get("reused", False))

    def test_vacuous_final_does_not_count_as_reusable_proof(self):
        with tempfile.TemporaryDirectory(prefix="orch-verify-vacuous-") as ws:
            path, mock, _driver = self._to_impl_pending(
                ws, make_config(verification=[]), tail=[_impl_step()]
            )
            finals = self._verification_events(st.load(path), "final")
            self.assertTrue(finals)
            self.assertTrue(all(event.get("vacuous") for event in finals))

            action, _note = drv.Driver(path, runner=mock).step()
            self.assertEqual(action.type, drv.A_VERIFY)
            baseline = self._verification_events(
                st.load(path), "baseline"
            )[-1]
            self.assertTrue(baseline.get("vacuous"))
            self.assertFalse(baseline.get("reused", False))
            self.assertNotIn("reused_from_seq", baseline)

    def test_pending_impl_with_recorded_draft_recovers_without_second_call(self):
        with tempfile.TemporaryDirectory(prefix="orch-verify-old-pending-") as ws:
            path, mock, _driver = self._to_impl_pending(
                ws, make_config(verification=[])
            )
            state = st.load(path)
            impl = st.current_unit(state)
            impl["draft"] = {
                "kind": contracts.KIND_IMPLEMENT,
                "family": "codex",
                "result": {"files_changed": ["core.py"]},
            }
            st.save(path, state)
            calls_before = len(mock.calls)

            action, note = drv.Driver(path, runner=mock).step()
            self.assertEqual(action.type, drv.A_DRAFT)
            self.assertIn("recorded draft recovered", note)
            self.assertEqual(st.load(path)["units"][-1]["status"],
                             st.U_PRE_REVIEW_VERIFY)
            self.assertEqual(len(mock.calls), calls_before)

    def test_final_failure_fixes_then_rereviews_before_reusing_success(self):
        marker = "suite-green.marker"
        command = "test -f %s" % marker
        script = [
            _skeleton_step(),
            step(contracts.KIND_REVIEW_ROUND,
                 report(contracts.KIND_REVIEW_ROUND), family="codex"),
            step(contracts.KIND_REVIEW_ROUND,
                 report(contracts.KIND_REVIEW_ROUND), family="claude"),
            step(
                contracts.KIND_FIX_FINDINGS,
                fix_ok([], files_changed=[marker]),
                family="codex",
                side_effect=write_file(marker, "green\n"),
            ),
            step(contracts.KIND_DELTA_REVIEW,
                 report(contracts.KIND_DELTA_REVIEW), family="codex"),
            step(contracts.KIND_REVIEW_ROUND,
                 report(contracts.KIND_REVIEW_ROUND), family="codex"),
            step(contracts.KIND_REVIEW_ROUND,
                 report(contracts.KIND_REVIEW_ROUND), family="claude"),
        ]
        with tempfile.TemporaryDirectory(prefix="orch-verify-final-fix-") as ws:
            path = init_state(ws, make_config(verification=[command]))
            mock = runners.MockRunner(script)
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda state: state["units"][0]["status"] == st.U_SEALED,
                max_steps=30,
            )
            self.assertEqual(mock.script, [])
            state = st.load(path)
            final = self._verification_events(state, "final")
            self.assertEqual(
                [event["ok"] for event in final], [False, True, True]
            )
            self.assertTrue(final[1].get("fixer_certified"))
            self.assertFalse(final[1].get("reused"))
            self.assertTrue(final[2].get("reused"))

            reviews = [
                round_info for round_info in state["units"][0]["rounds"]
                if round_info["kind"] == contracts.KIND_REVIEW_ROUND
            ]
            self.assertEqual(
                [round_info["family"] for round_info in reviews],
                ["codex", "claude", "codex", "claude"],
            )
            fixes = [
                round_info for round_info in state["units"][0]["rounds"]
                if round_info["kind"] == contracts.KIND_FIX_FINDINGS
            ]
            self.assertEqual(len(fixes), 1)
            self.assertEqual(
                fixes[0]["source_round_id"],
                "skeleton-verify-pre_seal-1",
            )
            deferred = [
                event for event in state["events"]
                if event["type"] == "verification_deferred"
            ]
            # One deferral after the draft and one after the accepted fix;
            # neither executes the full suite.
            self.assertEqual(len(deferred), 2)


if __name__ == "__main__":
    unittest.main()
