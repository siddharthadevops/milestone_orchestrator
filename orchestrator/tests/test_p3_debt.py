"""Finding-debt deferral with driver-owned independent classification.

When `p3_reclassify_debt` is on, eligible full- and delta-review findings
receive classification one by one. Ratings below the configured threshold
become tracked debt; only the remaining findings reach the fixer. One blocking
finding never drags accepted debt into its fix cycle. The configurable scope is
phase-dependent (interpreter.defer_scope_for): documentation defaults to P2/P3
and implementation defaults to P1/P2/P3.
"""

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import model_profiles
from orchestrator import profiles
from orchestrator import runners
from orchestrator import staffing as stf
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    DriverTestCase,
    finding,
    fix_ok as legacy_fix_ok,
    init_state,
    make_config,
    ok,
    report as legacy_report,
    step,
    triaged,
    write_file,
)


def report(kind, findings=()):
    return legacy_report(kind, findings)


def fix_ok(*args, **kwargs):
    return legacy_fix_ok(*args, **kwargs)


def no_suite_checkpoint():
    return step(
        contracts.KIND_SUITE_CHECKPOINT,
        {
            "status": "no_suite",
            "kind": contracts.KIND_SUITE_CHECKPOINT,
            "commands": [],
            "results": [],
            "authority": {
                "source": "repository",
                "evidence": [{
                    "path": "docs/skeleton.md",
                    "basis": "No complete suite is configured or declared.",
                }],
            },
        },
        family="codex",
    )


def draft_step():
    return step(
        "draft_skeleton",
        ok("draft_skeleton", artifact="docs/skeleton.md"),
        family="codex",
        side_effect=write_file(
            "docs/skeleton.md",
            canonical_skeleton_document("Calculator core"),
        ),
    )


def canonical_skeleton_document(title="Core"):
    """One valid routed-plan fixture for these legacy lifecycle tests."""
    plan = {
        "slices": [{
            "id": 1,
            "title": title,
            "intent": "Exercise finding-debt routing for one slice.",
            "producer_task_executor": {
                "draft_slice_note": "agent_call",
                "implement": "agent_call",
            },
        }],
    }
    return (
        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
        % json.dumps(plan, separators=(",", ":"))
    )


def homed_draft_step():
    """`draft_step()` for a run the ROUTER staffs.

    The converted `default` document seats `plan 1` on claude whatever the
    run config's own act table says, and after slice 4 that table decides
    no driver call.
    """
    return dict(draft_step(), expect_family="claude")


def unstaffable_document(name="ghosts"):
    """A document whose every family slot names nobody this machine has.

    A session repointed at it resolves `staffing_unavailable` — one of the
    two conditions that still stop a dispatch — without touching the run's
    own configuration.
    """
    document = stf.default_document_seed()
    document["name"] = name
    for slot in document["families"].values():
        slot["name"] = "ghost-%s" % slot["name"]
    return document


def split_classify_document(name="split-classify"):
    """A document whose `classify` role demands two distinct families.

    A document owner may ask the independence seat to be split; on a machine
    with one family the two seats collapse onto it, which is
    `distinct_families_unsatisfiable` — for a rating DISPATCH, and only for
    one.
    """
    document = stf.default_document_seed()
    document["name"] = name
    document["roles"]["classify"] = {"distinct_families": True}
    document["assignment"]["classify"] = {"1": 1, "2": 2}
    return document


def one_review_seat(document):
    """The same document with `review` assigned a SINGLE seat.

    A run whose available families are one cannot honour the converted
    `default`'s split `review` — its two seats both collapse onto that one
    family — so it stops at its first review dispatch with
    `distinct_families_unsatisfiable`. Such a run's single-family debt
    behaviour is observable only where its reviews run at all: under a
    `review` role with one assigned seat, which any declared split honours
    trivially. Nothing else about the document changes.
    """
    document["assignment"]["review"] = {"1": 1}
    return document


def reform_draft_step():
    """draft_step() plus the answered question battery a reform profile
    hard-requires on doc drafts (legacy/profile-less drafts stay bare)."""
    s = draft_step()
    return s


def reclassify(defer_ok, family, reason="verified", risk=None,
               damage=None, side_effect=None):
    # The worker only RATES; deferral is the driver comparing the gated
    # axis to p3_defer_max_risk (risk for legacy, DAMAGE for reform).
    # For test intent, defer_ok=True fakes a "low" rating and False a
    # "high" one; drift_damage rides along (harmless extra key for
    # legacy validation, required under reform).
    lvl = "low" if defer_ok else "high"
    return step("reclassify",
                ok("reclassify",
                   drift_risk=risk or lvl,
                   drift_damage=damage or lvl,
                   reason=reason),
                family=family, side_effect=side_effect)


class TestP3Debt(DriverTestCase):
    def test_single_family_defaults_to_fix_without_classification(self):
        with tempfile.TemporaryDirectory(prefix="orch-single-debt-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            runner = runners.MockRunner([
                draft_step(),
                step(
                    "review_round",
                    report("review_round", [finding("F1", "stale word")]),
                    family="codex",
                ),
            ])
            subject = drv.Driver(path, runner=runner)
            subject.reviewed_work.configure(subject.state["units"][0], {
                "review_breadth": "single",
                "p3_reclassify_debt": True,
            })
            self.step_until(
                subject,
                lambda state: state["units"][0]["status"] == st.U_FIXING,
            )
            unit = st.load(path)["units"][0]
            self.assertEqual([finding["id"] for finding in unit["fix_queue"]], ["F1"])
            self.assertNotIn("reclassify", [call[1] for call in runner.calls])

    def test_single_family_explicit_second_look_rates_fresh_on_same_family(self):
        with tempfile.TemporaryDirectory(prefix="orch-single-debt-") as ws:
            config = make_config(p3_reclassify_debt=True)
            config["acts"] = dict(config["acts"], reclassifier="codex")
            path = init_state(ws, config)
            runner = runners.MockRunner([
                draft_step(),
                step(
                    "review_round",
                    report("review_round", [finding("F1", "stale word")]),
                    family="codex",
                ),
                reclassify(True, family="codex", reason="fresh second look"),
            ])
            subject = drv.Driver(path, runner=runner)
            subject.reviewed_work.configure(subject.state["units"][0], {
                "review_breadth": "single",
                "same_family_second_look": True,
                "p3_reclassify_debt": True,
            })
            self.step_until(subject, lambda state: state["units"][0]["debt"])
            unit = st.load(path)["units"][0]
            self.assertEqual(unit["debt"][0]["cleared_by"], "codex")
            self.assertEqual(
                [round_["family"] for round_ in unit["rounds"]], ["codex"]
            )

    def test_reclassifier_repair_keeps_full_duration_and_identity(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config(p3_reclassify_debt=True)
            cfg["model_defaults"] = {
                "claude": {"model": "claude-opus-5", "effort": "max"}
            }
            path = init_state(ws, cfg)
            mock_runner = runners.MockRunner([
                draft_step(),
                step(
                    "review_round",
                    report("review_round", [finding("F1", "stale word")]),
                    family="codex",
                ),
                step("reclassify", "not json", family="claude"),
                reclassify(True, family="claude", reason="cosmetic"),
            ])
            driver = drv.Driver(path, runner=mock_runner)
            self.step_until(
                driver,
                lambda state: any(
                    event["type"] == "reclassify_recorded"
                    for event in state["events"]
                ),
            )

            state = st.load(path)
            event = next(
                event for event in state["events"]
                if event["type"] == "reclassify_recorded"
            )
            self.assertEqual(event["duration_s"], 0.01)
            self.assertEqual(event["logical_duration_s"], 0.02)
            self.assertEqual(event["model"], "claude-opus-5")
            self.assertEqual(event["effort"], "max")
            malformed = next(
                event for event in state["events"]
                if event["type"] == "worker_malformed"
            )
            self.assertEqual(malformed["model"], "claude-opus-5")
            self.assertEqual(malformed["effort"], "max")
            self.assertAlmostEqual(
                st.summary(state)["units"][0]["work_duration_s"], 0.04
            )

    def test_reclassifier_busy_marker_names_resolved_provider(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            observed = {}

            def capture_marker(workspace):
                import json
                import os
                with open(
                    os.path.join(workspace, ".orchestrator", "current.json"),
                    encoding="utf-8",
                ) as handle:
                    observed.update(json.load(handle))

            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step(
                    "review_round",
                    report("review_round", [finding("F1", "stale word")]),
                    family="codex",
                ),
                reclassify(
                    True,
                    family="claude",
                    reason="cosmetic",
                    side_effect=capture_marker,
                ),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda state: any(
                    event["type"] == "reclassify_recorded"
                    for event in state["events"]
                ),
            )

            self.assertEqual(observed["kind"], contracts.KIND_RECLASSIFY)
            self.assertEqual(observed["family"], "claude")

    def test_reclassifier_crash_preserves_completed_parent_usage(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            driver = drv.Driver(path, runner=runners.MockRunner([]))
            usage = {
                "input_tokens": 90,
                "cached_input_tokens": 30,
                "output_tokens": 10,
                "reasoning_output_tokens": 4,
                "total_tokens": 100,
            }
            self.assertTrue(driver._mark_busy(
                "skeleton-codex-r1",
                contracts.KIND_REVIEW_ROUND,
                "codex",
            ))
            self.assertTrue(driver._update_busy_accounting(
                runners.RunnerResult("{}", 0, 2.0, token_usage=usage)
            ))
            self.assertTrue(driver._mark_busy(
                "skeleton-reclassify-codex-F1",
                contracts.KIND_RECLASSIFY,
                "claude",
                nested=True,
            ))

            recovered = drv.Driver(path, runner=runners.MockRunner([]))
            interrupted = [
                event for event in recovered.state["events"]
                if event["type"] == "worker_interrupted"
            ]
            self.assertEqual(len(interrupted), 2)
            by_kind = {event["kind"]: event for event in interrupted}
            self.assertEqual(
                by_kind[contracts.KIND_REVIEW_ROUND]["token_usage"], usage
            )
            self.assertFalse(
                by_kind[contracts.KIND_REVIEW_ROUND]["token_usage_partial"]
            )
            self.assertTrue(
                by_kind[contracts.KIND_RECLASSIFY]["token_usage_partial"]
            )
            self.assertEqual(
                st.summary(recovered.state)["work_token_usage"], usage
            )
            self.assertTrue(
                st.summary(recovered.state)["work_token_usage_partial"]
            )

    def test_reclassifier_admission_failure_keeps_parent_review_usage(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            runner = runners.MockRunner([
                draft_step(),
                step(
                    "review_round",
                    report("review_round", [finding("F1", "stale word")]),
                    family="codex",
                ),
            ])
            driver = drv.Driver(path, runner=runner)
            self.step_until(
                driver,
                lambda state: state["units"][0]["status"] == st.U_ROUNDS,
            )
            original_mark = driver._mark_busy

            def admit(label, kind, family, model=None, effort=None,
                      nested=False, task_id=None, staffing_fallback=None):
                if kind == contracts.KIND_RECLASSIFY:
                    return False
                return original_mark(
                    label, kind, family, model=model, effort=effort,
                    nested=nested, task_id=task_id,
                    staffing_fallback=staffing_fallback,
                )

            with mock.patch.object(driver, "_mark_busy", side_effect=admit):
                driver.step()

            state = st.load(path)
            parent = [
                event
                for event in state["events"]
                if event["type"] == "worker_unaccepted"
                and event["kind"] == contracts.KIND_REVIEW_ROUND
            ]
            self.assertEqual(len(parent), 1)
            self.assertTrue(parent[0]["token_usage_partial"])
            self.assertTrue(st.summary(state)["work_token_usage_partial"])

    def test_reclassifier_predispatch_failure_keeps_parent_review_usage(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            home = os.path.join(ws, "home")
            model_profiles.ensure_default(home)
            config = make_config(p3_reclassify_debt=True)
            config["model_defaults"] = copy.deepcopy(
                drv.DEFAULT_CONFIG["model_defaults"]
            )
            path = init_state(ws, config)
            usage = {
                "input_tokens": 20,
                "cached_input_tokens": 5,
                "output_tokens": 4,
                "reasoning_output_tokens": 1,
                "total_tokens": 24,
            }

            def unstaff_the_run(_workspace):
                """Leave the run's session with nobody to call at all.

                Run as the review round's own side effect, so it lands
                AFTER that dispatch resolved and before the rating's: the
                review itself is a `review` seat now, and unstaffing before
                its physical dispatch would simply stop the review instead
                of the rating this test is about.
                """
                stf.save(home, unstaffable_document())
                stf.edit_session(
                    home,
                    st.load(path)["staffing_session"],
                    {"document": "ghosts"},
                )

            class UsageRunner(runners.MockRunner):
                def call(inner, *args, **kwargs):
                    result = super().call(*args, **kwargs)
                    if inner.call_meta[-1]["kind"] == contracts.KIND_REVIEW_ROUND:
                        result.token_usage = copy.deepcopy(usage)
                        result.cost_payloads = [copy.deepcopy(usage)]
                    return result

            runner = UsageRunner([
                homed_draft_step(),
                step(
                    "review_round",
                    report("review_round", [finding("F1", "stale word")]),
                    family="codex",
                    side_effect=unstaff_the_run,
                ),
            ])
            subject = drv.Driver(
                path, runner=runner, model_profiles_home=home
            )
            self.step_until(
                subject,
                lambda current: current["units"][0]["status"] == st.U_ROUNDS,
            )
            subject.step()

            current = st.load(path)
            parent = [
                event
                for event in current["events"]
                if event["type"] == "worker_unaccepted"
                and event["kind"] == contracts.KIND_REVIEW_ROUND
            ]
            self.assertEqual(len(parent), 1)
            self.assertEqual(parent[0]["token_usage"], usage)
            self.assertFalse(parent[0]["token_usage_partial"])
            self.assertIsNotNone(
                parent[0]["cost"], (parent[0], runner.call_meta)
            )
            self.assertEqual(parent[0]["duration_s"], 0.01)
            self.assertEqual(
                [call[1] for call in runner.calls],
                [contracts.KIND_DRAFT_SKELETON,
                 contracts.KIND_REVIEW_ROUND],
            )
            self.assertIn(
                stf.STAFFING_UNAVAILABLE, current["failure"]["reason"]
            )
            self.assertFalse(os.path.exists(subject._busy_path()))

    def test_reclassifier_policy_change_before_dispatch_is_not_incident(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            home = os.path.join(ws, "home")
            model_profiles.ensure_default(home)
            current_profile = model_profiles.load(home, "default")
            current_profile["configurations"]["medium"].update({
                "skeletoner": {"agent": "codex"},
                "reclassifier": {"agent": "codex"},
            })
            model_profiles.save(home, current_profile)
            stf.save(home, one_review_seat(stf.default_document_seed()))
            config = make_config(p3_reclassify_debt=True)
            config["families_order"] = ["codex"]
            config["model_defaults"] = copy.deepcopy(
                drv.DEFAULT_CONFIG["model_defaults"]
            )
            path = init_state(ws, config)
            runner = runners.MockRunner([
                draft_step(),
                step(
                    "review_round",
                    report("review_round", [finding("F1", "stale word")]),
                    family="codex",
                ),
            ])
            subject = drv.Driver(
                path, runner=runner, model_profiles_home=home
            )
            self.step_until(
                subject,
                lambda current: current["units"][0]["status"] == st.U_ROUNDS,
            )

            original_mark = subject._mark_busy

            # The edit fires before the rating decision is taken, which is
            # exactly what a single-family run must be indifferent to: the
            # gate reads the families the RUN supplies, not a profile.
            def remove_explicit_rater_after_admission(
                label, kind, family, model=None, effort=None, nested=False,
                task_id=None, staffing_fallback=None,
            ):
                admitted = original_mark(
                    label,
                    kind,
                    family,
                    model=model,
                    effort=effort,
                    nested=nested,
                    task_id=task_id,
                    staffing_fallback=staffing_fallback,
                )
                if admitted and kind == contracts.KIND_REVIEW_ROUND:
                    edited = model_profiles.load(home, "default")
                    edited["configurations"]["medium"].pop(
                        "reclassifier"
                    )
                    model_profiles.save(home, edited)
                return admitted

            with mock.patch.object(
                subject,
                "_mark_busy",
                side_effect=remove_explicit_rater_after_admission,
            ):
                subject.step()

            current = st.load(path)
            ratings = [
                event for event in current["events"]
                if event["type"] == "reclassify_recorded"
            ]
            self.assertEqual(len(ratings), 1)
            self.assertFalse(ratings[0]["defer_ok"])
            self.assertEqual(
                ratings[0]["reason"],
                "no independent reclassifier (single family)",
            )
            self.assertFalse(any(
                event["type"] == "worker_malformed"
                and event.get("kind") == contracts.KIND_RECLASSIFY
                for event in current["events"]
            ))
            self.assertIsNone(current.get("failure"))
            self.assertEqual(
                [call[1] for call in runner.calls],
                [contracts.KIND_DRAFT_SKELETON,
                 contracts.KIND_REVIEW_ROUND],
            )
            self.assertFalse(os.path.exists(subject._busy_path()))
            # The profile edit really happened, and decided nothing: the
            # rater is the seat the run's document assigns, and the run's
            # single family is the only reason no rating was taken.
            self.assertNotIn(
                "reclassifier",
                model_profiles.load(home, "default")["configurations"][
                    "medium"],
            )
            self.assertEqual(subject._staff("classify")[0], "codex")

    def test_doc_round_p3_only_is_deferred_as_debt(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                # codex round: one lone P3 -> claude reclassifies -> defer
                step("review_round",
                     report("review_round", [finding(
                         "F1", "stale word", plain="PLAIN_DEBT_SENTINEL",
                         example="EXAMPLE_DEBT_SENTINEL")]),
                     family="codex"),
                reclassify(True, family="claude", reason="cosmetic, no drift"),
                # codex family advanced; claude round: also a lone P3
                step("review_round",
                     report("review_round", [finding("F1", "typo")]),
                     family="claude"),
                reclassify(True, family="codex", reason="wording only"),
                # both families deferred-clean -> deterministic seal
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            self.assertEqual(mock.script, [])
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_SEALED)
            # No fix episode ever fired.
            self.assertEqual(
                [r for r in unit["rounds"] if r["kind"] == "fix_findings"], [])
            # Two P3s recorded as debt, tagged with who cleared them.
            self.assertEqual(len(unit["debt"]), 2)
            self.assertEqual(unit["debt"][0]["cleared_by"], "claude")
            self.assertEqual(unit["debt"][1]["cleared_by"], "codex")
            # Ledger carries the debt events for operator visibility.
            debt_events = [e for e in state["events"]
                           if e["type"] == "debt_recorded"]
            self.assertEqual(len(debt_events), 2)
            reclassify_events = [
                e for e in state["events"]
                if e["type"] == "reclassify_recorded"
            ]
            self.assertEqual(
                [e.get("source_round") for e in reclassify_events],
                ["skeleton-codex-r1", "skeleton-claude-r1"],
            )
            # Once rated, later reviewers receive only the compact
            # technical fingerprint — never the lay framing used by the
            # reclassifier to calibrate gravity.
            claude_review = [
                prompt for fam, kind, prompt in mock.calls
                if fam == "claude" and kind == "review_round"
            ][0]
            self.assertIn("codex-F1", claude_review)
            self.assertNotIn("PLAIN_DEBT_SENTINEL", claude_review)
            self.assertNotIn("EXAMPLE_DEBT_SENTINEL", claude_review)
            self.assertNotIn("seal_half", [kind for _fam, kind, _p in mock.calls])
            self.assertEqual(unit["seals"][0]["halves"], {})

    def test_delta_p3_is_classified_and_deferred_before_another_fixer(self):
        with tempfile.TemporaryDirectory(prefix="orch-delta-debt-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            fixed_document = canonical_skeleton_document("Calculator core") + (
                "\nThe reviewed wording is now explicit.\n"
            )
            mock_runner = runners.MockRunner([
                draft_step(),
                step(
                    "review_round",
                    report("review_round", [
                        finding("F1", "material defect", severity="P1")
                    ]),
                    family="codex",
                ),
                step(
                    "fix_findings",
                    fix_ok(
                        [triaged("F1", "fixed", severity="P1")],
                        files_changed=["docs/skeleton.md"],
                    ),
                    family="codex",
                    side_effect=write_file(
                        "docs/skeleton.md", fixed_document
                    ),
                ),
                step(
                    "delta_review",
                    report("delta_review", [
                        finding(
                            "F2", "tiny follow-up wording", severity="P2"
                        )
                    ]),
                    family="codex",
                ),
                reclassify(
                    True, family="claude", reason="negligible and visible"
                ),
            ])
            subject = drv.Driver(path, runner=mock_runner)
            self.step_until(
                subject,
                lambda current: bool(current["units"][0].get("debt")),
            )

            current = st.load(path)
            unit = current["units"][0]
            self.assertEqual(mock_runner.script, [])
            self.assertEqual(unit["status"], st.U_PRE_REVIEW_VERIFY)
            self.assertEqual(unit["fix_queue"], [])
            self.assertIsNone(unit["fix_source"])
            self.assertEqual([item["id"] for item in unit["debt"]], [
                "codex-F2"
            ])
            delta_round = [
                round_ for round_ in unit["rounds"]
                if round_["kind"] == contracts.KIND_DELTA_REVIEW
            ][0]
            self.assertTrue(delta_round["deferred_clean"])
            rating = [
                event for event in current["events"]
                if event["type"] == "reclassify_recorded"
                and event["finding_id"] == "codex-F2"
            ][0]
            self.assertEqual(rating["source_round"], delta_round["id"])

    def test_delta_mixture_defers_only_the_low_risk_finding(self):
        with tempfile.TemporaryDirectory(prefix="orch-delta-mixed-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            fixed_document = canonical_skeleton_document("Calculator core") + (
                "\nThe reviewed wording is now explicit.\n"
            )
            mock_runner = runners.MockRunner([
                draft_step(),
                step(
                    "review_round",
                    report("review_round", [
                        finding("F1", "material defect", severity="P1")
                    ]),
                    family="codex",
                ),
                step(
                    "fix_findings",
                    fix_ok(
                        [triaged("F1", "fixed", severity="P1")],
                        files_changed=["docs/skeleton.md"],
                    ),
                    family="codex",
                    side_effect=write_file(
                        "docs/skeleton.md", fixed_document
                    ),
                ),
                step(
                    "delta_review",
                    report("delta_review", [
                        finding(
                            "F2", "tiny follow-up wording", severity="P2"
                        ),
                        finding(
                            "F3", "hidden follow-up defect", severity="P2"
                        ),
                    ]),
                    family="codex",
                ),
                reclassify(True, family="claude", reason="negligible"),
                reclassify(False, family="claude", reason="material drift"),
            ])
            subject = drv.Driver(path, runner=mock_runner)
            self.step_until(
                subject,
                lambda current: current["units"][0]["status"] == st.U_FIXING
                and (current["units"][0].get("fix_source") or {}).get("type")
                == "delta",
            )

            current = st.load(path)
            unit = current["units"][0]
            self.assertEqual(mock_runner.script, [])
            self.assertEqual(
                [item["id"] for item in unit["fix_queue"]], ["F3"]
            )
            self.assertEqual(
                [item["id"] for item in unit["debt"]], ["codex-F2"]
            )
            self.assertEqual(len([
                event for event in current["events"]
                if event["type"] == "reclassify_recorded"
            ]), 2)

    def test_reclassifier_refusal_routes_to_the_fixer(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "looks trivial but isn't")]),
                     family="codex"),
                # claude refuses to defer -> normal fix flow
                reclassify(False, family="claude", reason="hidden drift risk"),
            ])
            driver = drv.Driver(path, runner=mock)
            # Step until the unit enters fixing (the refusal path).
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            unit = state["units"][0]
            self.assertEqual(unit["status"], st.U_FIXING)
            self.assertEqual(unit["debt"], [])
            # The P3 is queued for the fixer, not deferred.
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F1"])

    def test_reform_profile_defers_a_lone_p2_as_debt(self):
        # 3b: a reform profile widens the DOC gate to P2/P3. A lone P2 rated
        # at-or-below the profile threshold defers as tracked debt, and the
        # debt records the finding's REAL severity (P2), not a hardcoded P3.
        strict = profiles.SEEDS["strict"]["profile"]  # threshold "low"
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(
                ws, make_config(p3_reclassify_debt=True, profile=strict))
            mock = runners.MockRunner([
                reform_draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "minor phrasing", severity="P2")]),
                     family="codex"),
                reclassify(True, family="claude", reason="cosmetic",
                           risk="low"),
                step("review_round",
                     report("review_round",
                            [finding("F1", "minor phrasing", severity="P2")]),
                     family="claude"),
                reclassify(True, family="codex", reason="cosmetic",
                           risk="low"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver,
                            lambda s: s["units"][0]["status"] == st.U_SEALED)
            unit = st.load(path)["units"][0]
            self.assertEqual(unit["status"], st.U_SEALED)
            self.assertEqual(
                [r for r in unit["rounds"] if r["kind"] == "fix_findings"], [])
            self.assertEqual(len(unit["debt"]), 2)
            self.assertEqual(unit["debt"][0]["severity"], "P2")

    def test_fixed_reclassifier_rates_even_its_own_family(self):
        # acts.reclassifier = "codex" (operator 2026-07-09: a fixed fast
        # rater beats an 8-minute opposite-family rating of a 4-minute
        # review's findings). The codex-raised P3 is rated BY CODEX —
        # the MockRunner's expect_family proves who was asked — and the
        # explicit policy overrides the same-family degeneracy guard.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config(p3_reclassify_debt=True)
            cfg["acts"] = dict(cfg["acts"], reclassifier="codex")
            path = init_state(ws, cfg)
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
                reclassify(True, family="codex", reason="cosmetic"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(driver, lambda s: s["units"][0].get("debt"))
            state = st.load(path)
            ev = [e for e in state["events"]
                  if e["type"] == "reclassify_recorded"][-1]
            self.assertEqual(ev["reclassifier"], "codex")
            self.assertTrue(ev["defer_ok"])
            self.assertEqual(ev["duration_s"], 0.01)
            # Draft + review + rating are three distinct completed calls.
            self.assertAlmostEqual(
                st.summary(state)["units"][0]["work_duration_s"], 0.03
            )

    def test_config_act_table_does_not_choose_the_rater(self):
        """The document the run's session names does — and it rates even
        when its `classify` seat is the family that raised the finding."""
        with tempfile.TemporaryDirectory(prefix="orch-profile-rater-") as ws:
            home = os.path.join(ws, "home")
            model_profiles.ensure_default(home)
            model_profiles.save(home, {
                "name": "lean",
                "examples": ["lean staffing"],
                "configurations": {"low": {}, "medium": {}, "high": {}},
            })
            config = make_config(p3_reclassify_debt=True)
            # Deliberately at odds with the document's own `classify 1`
            # seat: after the cutover this table decides no driver call.
            config["acts"]["reclassifier"] = {
                "agent": "claude", "effort": "low"
            }
            path = init_state(ws, config)
            with open(
                os.path.join(os.path.dirname(path), "model_profile.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({"name": "lean", "rigor": "medium"}, handle)

            mock_runner = runners.MockRunner([
                homed_draft_step(),
                step(
                    "review_round",
                    report(
                        "review_round", [finding("F1", "stale word")]
                    ),
                    family="codex",
                ),
                reclassify(True, family="codex", reason="assigned seat"),
            ])
            subject = drv.Driver(
                path, runner=mock_runner, model_profiles_home=home
            )
            self.step_until(
                subject,
                lambda current: any(
                    event["type"] == "reclassify_recorded"
                    for event in current["events"]
                ),
            )

            # The run's session points at the converted `lean` document.
            self.assertEqual(
                st.load(path)["staffing_session"],
                stf.read_session(
                    home, st.load(path)["staffing_session"])["id"],
            )
            seat = subject._staff("classify")
            self.assertEqual(seat[0], "codex")
            event = next(
                event for event in st.load(path)["events"]
                if event["type"] == "reclassify_recorded"
            )
            # Rated at the assigned seat, by the family that raised it, and
            # the entry names both.
            self.assertEqual(event["reclassifier"], seat[0])
            self.assertEqual(event["model"], seat[1])
            self.assertEqual(event["effort"], seat[2])
            self.assertTrue(event["defer_ok"])
            self.assertEqual(event["reason"], "assigned seat")
            entry = st.load(path)["units"][0]["debt"][0]
            self.assertEqual(
                (entry["raised_by"], entry["cleared_by"]), ("codex", seat[0])
            )

    def test_current_profile_can_explicitly_choose_same_family_reclassifier(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="orch-profile-rater-") as ws:
            home = os.path.join(ws, "home")
            model_profiles.ensure_default(home)
            current = model_profiles.load(home, "default")
            current["configurations"]["medium"]["reclassifier"] = {
                "agent": "codex",
                "model": "profile-rater",
                "effort": "high",
            }
            model_profiles.save(home, current)
            # The document conversion runs at the first driver start, so
            # this edit is what the run's `classify 1` seat is converted
            # FROM; after that the document alone decides.
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                dict(draft_step(), expect_family="claude"),
                step(
                    "review_round",
                    report(
                        "review_round", [finding("F1", "stale word")]
                    ),
                    family="codex",
                ),
                reclassify(True, family="codex", reason="explicit profile"),
            ])
            driver = drv.Driver(
                path, runner=mock, model_profiles_home=home
            )
            self.step_until(
                driver,
                lambda state: any(
                    event["type"] == "reclassify_recorded"
                    for event in state["events"]
                ),
            )
            event = next(
                event for event in st.load(path)["events"]
                if event["type"] == "reclassify_recorded"
            )
            self.assertEqual(event["reclassifier"], "codex")
            self.assertEqual(event["model"], "profile-rater")
            self.assertEqual(event["effort"], "high")
            self.assertTrue(event["defer_ok"])
    def test_reform_gates_on_damage_not_probability(self):
        # The two-axis decision (operator 2026-07-09): a certain-but-cheap
        # drift defers; an unlikely-but-destructive one is fixed.
        strict = profiles.SEEDS["strict"]["profile"]
        for risk, damage, expect_defer in (
            ("xhigh", "low", True),   # builder WILL trip it; costs pennies
            ("low", "xhigh", False),  # unlikely; catastrophic if it lands
        ):
            with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
                path = init_state(
                    ws, make_config(p3_reclassify_debt=True, profile=strict))
                mock = runners.MockRunner([
                    reform_draft_step(),
                    step("review_round",
                         report("review_round",
                                [finding("F1", "two-axis case")]),
                         family="codex"),
                    reclassify(True, family="claude", risk=risk,
                               damage=damage, reason="two-axis"),
                ])
                driver = drv.Driver(path, runner=mock)
                if expect_defer:
                    self.step_until(
                        driver, lambda s: s["units"][0].get("debt"))
                else:
                    self.step_until(
                        driver,
                        lambda s: s["units"][0]["status"] == st.U_FIXING)
                state = st.load(path)
                unit = state["units"][0]
                ev = [e for e in state["events"]
                      if e["type"] == "reclassify_recorded"][-1]
                self.assertEqual(ev["drift_risk"], risk)
                self.assertEqual(ev["drift_damage"], damage)
                self.assertEqual(ev["defer_ok"], expect_defer)
                if expect_defer:
                    self.assertEqual(unit["debt"][0]["drift_damage"], damage)
                else:
                    self.assertEqual(unit["debt"], [])

    def test_configured_p3_doc_floor_keeps_a_p2_for_the_fixer(self):
        # The severity floor is independently configurable: P3 excludes P2
        # from classification, so it reaches the fixer directly.
        legacy = profiles.SEEDS["legacy"]["profile"]
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(
                ws, make_config(
                    p3_reclassify_debt=True,
                    profile=legacy,
                    doc_reclassify_from="P3",
                ))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "minor phrasing", severity="P2")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            unit = st.load(path)["units"][0]
            self.assertEqual(unit["status"], st.U_FIXING)
            self.assertEqual(unit["debt"], [])

    def test_threshold_decides_over_the_rating(self):
        # A "medium" rating defers under threshold "medium" but is kept
        # under the default "low" — the SAME rating, opposite outcomes:
        # the decision lives in config, not in the worker.
        for threshold, expect_defer in (("medium", True), ("low", False)):
            with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
                cfg = make_config(p3_reclassify_debt=True)
                cfg["p3_defer_max_risk"] = threshold
                path = init_state(ws, cfg)
                script = [
                    draft_step(),
                    step("review_round",
                         report("review_round",
                                [finding("F1", "slightly ambiguous phrase")]),
                         family="codex"),
                    reclassify(True, family="claude",
                               reason="minor ambiguity", risk="medium"),
                ]
                mock = runners.MockRunner(script)
                driver = drv.Driver(path, runner=mock)
                want = st.U_FIXING
                if expect_defer:
                    # advances to the next family's rounds without fixing
                    self.step_until(
                        driver,
                        lambda s: s["units"][0].get("debt"))
                else:
                    self.step_until(
                        driver,
                        lambda s: s["units"][0]["status"] == want)
                state = st.load(path)
                unit = state["units"][0]
                ev = [e for e in state["events"]
                      if e["type"] == "reclassify_recorded"][-1]
                self.assertEqual(ev["drift_risk"], "medium")
                self.assertEqual(ev["threshold"], threshold)
                self.assertEqual(ev["defer_ok"], expect_defer)
                if expect_defer:
                    self.assertEqual(unit["debt"][0]["drift_risk"], "medium")
                    self.assertEqual(unit["fix_queue"], [])
                else:
                    self.assertEqual(unit["debt"], [])
                    self.assertEqual(
                        [f["id"] for f in unit["fix_queue"]], ["F1"])

    def test_mixed_round_keeps_debt_out_of_the_fix_queue(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "real gap", severity="P2"),
                             finding("F2", "stale word")]),
                     family="codex"),
                reclassify(False, family="claude", reason="material gap"),
                reclassify(True, family="claude", reason="wording only"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            unit = state["units"][0]
            self.assertIn("reclassify", [c[1] for c in mock.calls])
            self.assertEqual([d["id"] for d in unit["debt"]], ["codex-F2"])
            # The real P2 is retained; the independently accepted P3 no
            # longer rides along merely because another finding blocked.
            self.assertEqual(
                [f["id"] for f in unit["fix_queue"]], ["F1"])

    def test_mixed_ratings_do_not_discard_accepted_debt(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round",
                            [finding("F1", "cheap wording"),
                             finding("F2", "serious drift")]),
                     family="codex"),
                reclassify(True, family="claude", reason="local correction"),
                reclassify(False, family="claude", reason="cross-slice drift"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            unit = st.load(path)["units"][0]
            self.assertEqual([d["id"] for d in unit["debt"]], ["codex-F1"])
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F2"])

    def test_contesting_a_debt_entry_reopens_it_for_the_fixer(self):
        # The N46 incident: a deferred finding later escalated with new
        # evidence had no legal reference — the contest read as a protocol
        # violation and killed the run, discarding the round's other
        # findings with it. A debt id is now contestable like an
        # adjudicated rejection, and a contesting finding NEVER routes
        # through the reclassifier (no reclassify step is scripted for it:
        # a re-deferral attempt would abort on script exhaustion).
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config(p3_reclassify_debt=True))
            mock = runners.MockRunner([
                draft_step(),
                # codex round: lone P3 -> deferred as debt codex-F1.
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
                reclassify(True, family="claude", reason="cosmetic"),
                # claude round: a P3 CONTESTING that debt with new
                # evidence. P3 is in the doc defer scope, so only the
                # contests guard keeps it away from the reclassifier.
                step("review_round",
                     report("review_round", [finding(
                         "F2",
                         "the deferred wording hides a real dead end",
                         contests={
                             "rejection_id": "codex-F1",
                             "new_evidence": "the shipped state machine "
                                             "makes the path terminal",
                         })]),
                     family="claude"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING
            )
            self.assertEqual(mock.script, [])
            state = st.load(path)
            unit = state["units"][0]
            # The run is alive and the finding reached the fix queue with
            # its contest intact (the pointer-kill guard keys off it).
            self.assertIsNone(state["failure"])
            self.assertEqual(
                [(f["id"], (f.get("contests") or {}).get("rejection_id"))
                 for f in unit["fix_queue"]],
                [("F2", "codex-F1")],
            )
            # The contested deferral is re-opened: the recorded entry
            # stays (debt arrays are immutable history) but it leaves the
            # active view, and the event says who re-opened what.
            self.assertEqual([e["id"] for e in unit["debt"]], ["codex-F1"])
            self.assertEqual(st.active_debt(state, unit), [])
            contested = [e for e in state["events"]
                         if e["type"] == "debt_contested"]
            self.assertEqual(
                [(e["debt_id"], e["contested_by"]) for e in contested],
                [("codex-F1", "F2")],
            )

    def test_reopen_contested_debt_removes_only_the_cited_entry(self):
        state = {
            "units": [
                {
                    "kind": "skeleton", "slice_id": None,
                    "debt": [
                        {"id": "codex-F1", "severity": "P3",
                         "summary": "cited"},
                        {"id": "codex-F2", "severity": "P3",
                         "summary": "unrelated"},
                    ],
                },
            ],
            "events": [],
        }
        reopened = st.reopen_contested_debt(
            state,
            [
                {"id": "F9",
                 "contests": {"rejection_id": "codex-F1",
                              "new_evidence": "proof"}},
                {"id": "F10"},  # no contests: never touches debt
            ],
        )
        self.assertEqual(reopened, ["codex-F1"])
        # History is untouched; the active view retires the entry.
        self.assertEqual(
            [e["id"] for e in state["units"][0]["debt"]],
            ["codex-F1", "codex-F2"],
        )
        self.assertEqual(
            [e["id"] for e in st.active_debt(state, state["units"][0])],
            ["codex-F2"],
        )
        self.assertEqual(st.debt_ids(state), {"codex-F2"})
        # Re-contesting a re-opened entry finds nothing: it is not settled.
        self.assertEqual(
            st.reopen_contested_debt(
                state,
                [{"id": "F12",
                  "contests": {"rejection_id": "codex-F1",
                               "new_evidence": "again"}}],
            ),
            [],
        )
        # A contest naming an adjudicated rejection (not a debt id) leaves
        # the ledger alone.
        self.assertEqual(
            st.reopen_contested_debt(
                state,
                [{"id": "F11",
                  "contests": {"rejection_id": "skeleton-codex-r1/F1",
                               "new_evidence": "proof"}}],
            ),
            [],
        )
        self.assertEqual(
            [e["id"] for e in st.active_debt(state, state["units"][0])],
            ["codex-F2"],
        )

    def test_feature_off_by_default_p3_still_fixes(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = init_state(ws, make_config())  # p3_reclassify_debt absent
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            self.assertNotIn("reclassify", [c[1] for c in mock.calls])
            self.assertEqual(state["units"][0]["fix_queue"][0]["id"], "F1")

    def test_single_family_config_never_defers(self):
        # With one family there is no independent opposite reclassifier, so
        # a P3 must never self-defer — it takes the normal fix path.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            cfg = make_config(p3_reclassify_debt=True,
                              families_order=["codex"], fix_family="codex")
            path = init_state(ws, cfg)
            mock = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            unit = state["units"][0]
            self.assertNotIn("reclassify", [c[1] for c in mock.calls])
            self.assertEqual(unit["debt"], [])
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F1"])

    def test_single_family_homed_run_never_defers_either(self):
        # The same invariant for the run an operator actually gets: HOMED,
        # so the router staffs every call, and supplying one family is the
        # one case the rating is still withheld — no second family can run
        # it, whatever the document's `classify` seat says. Its review runs
        # on that same one family, so it reaches the finding at all.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            home = os.path.join(ws, "home")
            model_profiles.ensure_default(home)
            stf.save(home, one_review_seat(stf.default_document_seed()))
            cfg = make_config(p3_reclassify_debt=True,
                              families_order=["codex"], fix_family="codex")
            path = init_state(ws, cfg)
            mock_runner = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
            ])
            driver = drv.Driver(
                path, runner=mock_runner, model_profiles_home=home
            )
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            unit = st.load(path)["units"][0]
            self.assertNotIn(
                "reclassify", [call[1] for call in mock_runner.calls]
            )
            self.assertEqual(unit["debt"], [])
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F1"])
            # The document does assign a `classify` seat; the run's single
            # family, not the document, is why no rating was taken.
            self.assertEqual(driver._staff("classify")[0], "codex")

    def test_a_withheld_rating_never_asks_the_router_at_all(self):
        # Same single-family run, under a document whose `classify` role
        # demands two distinct families — which one family cannot honour.
        # The rating is withheld for the run's own families, exactly as
        # above, so NO classifier dispatch is due and the surfaced condition
        # has no call to stop: the finding reaches the fix queue and the run
        # does not fail. Only a dispatch that really happens is refused.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            home = os.path.join(ws, "home")
            model_profiles.ensure_default(home)
            stf.save(home, one_review_seat(split_classify_document()))
            cfg = make_config(p3_reclassify_debt=True,
                              families_order=["codex"], fix_family="codex")
            path = init_state(ws, cfg)
            drv.open_run_staffing_session(
                path, home, "split-classify", "medium")
            mock_runner = runners.MockRunner([
                draft_step(),
                step("review_round",
                     report("review_round", [finding("F1", "stale word")]),
                     family="codex"),
            ])
            driver = drv.Driver(
                path, runner=mock_runner, model_profiles_home=home
            )
            self.step_until(
                driver, lambda s: s["units"][0]["status"] == st.U_FIXING)
            state = st.load(path)
            unit = state["units"][0]
            self.assertIsNone(state["failure"])
            self.assertNotIn(
                "reclassify", [call[1] for call in mock_runner.calls]
            )
            self.assertEqual(unit["debt"], [])
            self.assertEqual([f["id"] for f in unit["fix_queue"]], ["F1"])
            # The seat itself is still unsatisfiable — nothing was softened;
            # a dispatch that reached it would be refused.
            with self.assertRaises(drv.StopStep):
                driver._staff("classify")

    def _impl_pending(self, ws, **config_overrides):
        # State with skeleton + slice_doc SEALED and the slice_impl unit
        # pending, ready for its implement draft (mirrors the setup the
        # existing impl-seal test uses, but stops before implement).
        path = init_state(
            ws,
            make_config(
                p3_reclassify_debt=True,
                **config_overrides,
            ),
        )
        write_file(
            "docs/skeleton.md", canonical_skeleton_document("impl")
        )(ws)
        state = st.load(path)
        state["milestone"]["slices"] = [{"id": 1, "title": "impl"}]
        state["units"][0]["status"] = st.U_SEALED
        st.ensure_next_unit(state)["status"] = st.U_SEALED
        impl = st.ensure_next_unit(state)
        self.assertEqual(impl["kind"], "slice_impl")
        st.save(path, state)
        return path

    def test_impl_round_p3_only_is_deferred_as_debt(self):
        # Regression: the debt valve used to be DOC-phase only, so an impl
        # slice whose reviewer supplied an unbounded stream of fresh P3s
        # fix-looped until the round cap FAILED the run (found live
        # 2026-07-12, certification-llm slice_impl-08: 12 claude rounds, all
        # P3, never a clean round). The impl REVIEW ROUND now defers cosmetic
        # P3s as debt just like the doc phase — so a lone-P3 impl round is
        # deferred-clean and advances toward the seal.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = self._impl_pending(ws)
            mock = runners.MockRunner([
                step("implement",
                     ok(
                         "implement",
                         files_changed=["calculator.py"],
                     ),
                     family="codex",
                     side_effect=write_file(
                         "calculator.py", "def add(a, b):\n    return a + b\n")),
                # codex impl round: one lone P3 -> claude reclassifies -> defer
                step("review_round",
                     report("review_round",
                            [finding("F1", "module lacks a docstring")]),
                     family="codex"),
                reclassify(True, family="claude", reason="cosmetic polish"),
                # claude impl round: also a lone P3 -> codex defers
                step("review_round",
                     report("review_round",
                            [finding("F1", "test names could be clearer")]),
                     family="claude"),
                reclassify(True, family="codex", reason="test-naming nit"),
                no_suite_checkpoint(),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda s: s["units"][-1]["status"] == st.U_SEALED,
                max_steps=200)
            self.assertEqual(mock.script, [])
            impl = st.load(path)["units"][-1]
            self.assertEqual(impl["kind"], "slice_impl")
            self.assertEqual(impl["status"], st.U_SEALED)
            # No fix episode ever fired on the impl unit — the P3s deferred.
            self.assertEqual(
                [r for r in impl["rounds"] if r["kind"] == "fix_findings"], [])
            # Both P3s recorded as impl debt for operator visibility.
            self.assertEqual(len(impl["debt"]), 2)
            self.assertEqual({d["cleared_by"] for d in impl["debt"]},
                             {"claude", "codex"})
            self.assertEqual(impl["seals"][0]["halves"], {})

    def test_impl_round_p1_is_classified_and_preserved_as_p1_debt(self):
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = self._impl_pending(ws)
            mock = runners.MockRunner([
                step("implement",
                     ok(
                         "implement",
                         files_changed=["calculator.py"],
                     ),
                     family="codex",
                     side_effect=write_file(
                         "calculator.py", "def add(a, b):\n    return a + b\n")),
                step("review_round",
                     report("review_round", [finding(
                         "F1", "rare implementation edge", severity="P1"
                     )]),
                     family="codex"),
                reclassify(
                    True, family="claude", reason="bounded later repair"
                ),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda state: bool(state["units"][-1].get("debt")),
                max_steps=200,
            )
            impl = st.load(path)["units"][-1]
            self.assertEqual(mock.script, [])
            self.assertEqual(impl["debt"][0]["severity"], "P1")
            self.assertEqual(impl["fix_queue"], [])

    def test_configured_p3_impl_floor_keeps_p2_for_the_fixer(self):
        # A narrower operator floor remains possible per run.
        with tempfile.TemporaryDirectory(prefix="orch-mock-") as ws:
            path = self._impl_pending(ws, impl_reclassify_from="P3")
            mock = runners.MockRunner([
                step("implement",
                     ok(
                         "implement",
                         files_changed=["calculator.py"],
                     ),
                     family="codex",
                     side_effect=write_file(
                         "calculator.py", "def add(a, b):\n    return a + b\n")),
                step("review_round",
                     report("review_round",
                            [finding("F1", "div by zero unhandled",
                                     severity="P2")]),
                     family="codex"),
            ])
            driver = drv.Driver(path, runner=mock)
            self.step_until(
                driver,
                lambda s: s["units"][-1]["status"] == st.U_FIXING,
                max_steps=200)
            impl = st.load(path)["units"][-1]
            self.assertEqual(impl["status"], st.U_FIXING)
            self.assertEqual(impl["debt"], [])
            self.assertNotIn("reclassify", [c[1] for c in mock.calls])
            self.assertEqual([f["id"] for f in impl["fix_queue"]], ["F1"])

if __name__ == "__main__":
    unittest.main()
