"""A unit seals when every family is effectively clean on current bytes."""

import os
import tempfile
import unittest

from orchestrator import driver as drv
from orchestrator import profiles
from orchestrator import runners
from orchestrator import state as st

from orchestrator.tests.test_driver_mock import (
    canonical_skeleton_document, make_config, init_state, step, ok, report,
    finding, write_file, fix_ok, triaged,
)


def _rev(fam, findings=0, invalidated=False, deferred=False, rid=None):
    r = {
        "id": rid or ("%s-rev" % fam),
        "family": fam,
        "kind": "review_round",
        "result": {"findings": [{"id": "F", "severity": "P3"}] * findings},
    }
    if invalidated:
        r["invalidated"] = "reviewer edited"
    if deferred:
        r["deferred_clean"] = True
    return r


def _fix(fam="codex"):
    return {"id": "%s-fix" % fam, "family": fam, "kind": "fix_findings",
            "result": {"findings": []}}


def _unit(*rounds):
    return {"rounds": list(rounds)}


FAMS = ("codex", "claude")


class SealPredicateLogicTest(unittest.TestCase):
    def test_both_clean_no_fix_is_satisfied(self):
        u = _unit(_rev("codex", rid="c1"), _rev("claude", rid="k1"))
        self.assertEqual(st.seal_predicate_reviews(u, FAMS), ["c1", "k1"])

    def test_deferred_clean_counts(self):
        u = _unit(_rev("codex", findings=1, deferred=True, rid="c1"),
                  _rev("claude", deferred=True, findings=1, rid="k1"))
        self.assertEqual(st.seal_predicate_reviews(u, FAMS), ["c1", "k1"])

    def test_fix_after_a_review_makes_it_stale(self):
        # codex clean, then claude fixed something (bytes changed), then
        # claude clean — codex's look is now stale.
        u = _unit(_rev("codex", rid="c1"), _rev("claude", findings=1),
                  _fix("claude"), _rev("claude", rid="k2"))
        self.assertIsNone(st.seal_predicate_reviews(u, FAMS))

    def test_re_review_after_the_fix_satisfies(self):
        # Same, but codex ALSO re-reviewed after the fix → both current.
        u = _unit(_rev("codex"), _rev("claude", findings=1), _fix("claude"),
                  _rev("claude", rid="k2"), _rev("codex", rid="c2"))
        self.assertEqual(
            set(st.seal_predicate_reviews(u, FAMS)), {"c2", "k2"})

    def test_a_family_that_never_reviewed_is_unsatisfied(self):
        self.assertIsNone(
            st.seal_predicate_reviews(_unit(_rev("codex")), FAMS))

    def test_dirty_last_review_is_unsatisfied(self):
        u = _unit(_rev("codex"), _rev("claude", findings=1))
        self.assertIsNone(st.seal_predicate_reviews(u, FAMS))

    def test_invalidated_review_ignored(self):
        u = _unit(_rev("codex", rid="c1"),
                  _rev("claude", invalidated=True), _rev("claude", rid="k2"))
        self.assertEqual(st.seal_predicate_reviews(u, FAMS), ["c1", "k2"])

    def test_no_delta_fix_keeps_prior_clean_review_current(self):
        u = _unit(
            _rev("codex", rid="c1"),
            _rev("claude", findings=1),
            _fix("claude"),
            _rev("claude", rid="k2"),
        )
        u["review_cycle_start"] = 0
        self.assertEqual(st.seal_predicate_reviews(u, FAMS), ["c1", "k2"])

    def test_changed_candidate_requires_both_reviews_in_new_cycle(self):
        u = _unit(
            _rev("codex", rid="c1"),
            _rev("claude", findings=1),
            _fix("claude"),
            _rev("codex", rid="c2"),
            _rev("claude", rid="k2"),
        )
        u["review_cycle_start"] = 3
        self.assertEqual(st.seal_predicate_reviews(u, FAMS), ["c2", "k2"])


class SealPredicateDriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-sealpred-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "ws")
        os.makedirs(self.ws)

    def _config(self, profile_name):
        cfg = make_config()
        if profile_name:
            cfg["profile"] = profiles.SEEDS[profile_name]["profile"]
        return cfg

    def _drive(self, cfg, script):
        path = init_state(self.ws, cfg)
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            if driver.state["units"][0]["status"] == st.U_SEALED:
                break   # the skeleton is sealed; that is all these test
            action, _n = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
        return st.load(path), driver

    def _skeleton_clean_no_seal_halves(self):
        # Draft + a clean review per family; NO seal_half steps. The
        # canonical repository document, not reply-carried plan fields,
        # supplies the slice plan.
        draft = ok("draft_skeleton", artifact="docs/skeleton.md")
        return [
            step(
                "draft_skeleton",
                draft,
                family="codex",
                side_effect=write_file(
                    "docs/skeleton.md", canonical_skeleton_document()
                ),
            ),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]

    def test_reform_skeleton_seals_by_predicate(self):
        state, _ = self._drive(
            self._config("strict"),
            self._skeleton_clean_no_seal_halves(),
        )
        sk = state["units"][0]
        self.assertEqual(sk["status"], st.U_SEALED)
        # Sealed with NO seal-half findings recorded, and a seal_satisfied
        # event citing the two clean reviews.
        satisfied = [e for e in state["events"]
                     if e["type"] == "seal_satisfied"]
        self.assertEqual(len(satisfied), 1)
        self.assertEqual(len(satisfied[0]["reviews"]), 2)
        self.assertEqual(sk["seals"][0]["halves"], {})

    def test_changed_bytes_restart_both_reviewers_from_family_zero(self):
        from orchestrator.tests.test_driver_mock import fix_ok, triaged
        script = [
            step("draft_skeleton",
                 ok("draft_skeleton", artifact="docs/skeleton.md"),
                 family="codex",
                 side_effect=write_file(
                     "docs/skeleton.md", canonical_skeleton_document()
                 )),
            step("review_round", report("review_round"), family="codex"),
            step("review_round",
                 report("review_round", [finding("F1", "real gap",
                                                 severity="P1")]),
                 family="claude"),
            step("fix_findings",
                 fix_ok([triaged("F1", "fixed", "real gap",
                                 severity="P1")],
                        files_changed=["docs/skeleton.md"]),
                 family="codex",
                 side_effect=write_file(
                     "docs/skeleton.md",
                     canonical_skeleton_document() + "\nFixed real gap.\n",
                 )),
            step("delta_review", report("delta_review"), family="codex"),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]
        state, driver = self._drive(self._config("strict"), script)
        sk = state["units"][0]
        self.assertEqual(sk["status"], st.U_SEALED)
        self.assertEqual(driver.runner.script, [], "script fully consumed")
        self.assertEqual(sk["seals"][0]["halves"], {})
        reviews = [
            r for r in sk["rounds"] if r["kind"] == "review_round"
        ]
        self.assertEqual(
            [r["family"] for r in reviews],
            ["codex", "claude", "codex", "claude"],
        )
        satisfied = [
            e for e in state["events"] if e["type"] == "seal_satisfied"
        ][0]
        self.assertEqual(
            satisfied["reviews"], [reviews[-2]["id"], reviews[-1]["id"]]
        )

    def test_documentation_does_not_run_configured_full_suite(self):
        cfg = self._config("strict")
        cfg["verification"] = [
            "n=$(cat .orchestrator/verify-count 2>/dev/null || echo 0); "
            "n=$((n+1)); echo $n > .orchestrator/verify-count; "
            "if [ \"$n\" = 1 ]; then echo changed > verified-change.txt; fi"
        ]
        script = self._skeleton_clean_no_seal_halves()
        state, driver = self._drive(cfg, script)
        sk = state["units"][0]
        self.assertEqual(sk["status"], st.U_SEALED)
        self.assertEqual(driver.runner.script, [])
        reviews = [
            r for r in sk["rounds"] if r["kind"] == "review_round"
        ]
        self.assertEqual(
            [r["family"] for r in reviews],
            ["codex", "claude"],
        )
        self.assertEqual(
            sk["seals"][0]["reviews"],
            [reviews[-2]["id"], reviews[-1]["id"]],
        )
        self.assertEqual(
            [e for e in state["events"] if e["type"] == "verification"],
            [],
        )
        self.assertFalse(os.path.exists(
            os.path.join(self.ws, "verified-change.txt")
        ))

    def test_external_edit_between_reviewers_restarts_at_family_zero(self):
        cfg = self._config("strict")
        script = [
            step(
                "draft_skeleton",
                ok(
                    "draft_skeleton",
                    artifact="docs/skeleton.md",
                ),
                family="codex",
                side_effect=write_file(
                    "docs/skeleton.md", canonical_skeleton_document()
                ),
            ),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]
        path = init_state(self.ws, cfg)
        runner = runners.MockRunner(script)
        driver = drv.Driver(path, runner=runner)

        driver.step()  # draft
        driver.step()  # pre-review gate enters reviews without a full suite
        driver.step()  # first Codex approval
        write_file("between-reviews.txt", "new candidate bytes\n")(self.ws)
        driver.step()  # detects the edit before calling Claude

        self.assertEqual(driver.state["units"][0]["status"],
                         st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(len(runner.script), 2)
        for _ in range(20):
            if driver.state["units"][0]["status"] == st.U_SEALED:
                break
            driver.step()

        unit = st.load(path)["units"][0]
        reviews = [
            r for r in unit["rounds"] if r["kind"] == "review_round"
        ]
        self.assertEqual(
            [r["family"] for r in reviews],
            ["codex", "codex", "claude"],
        )
        self.assertEqual(unit["seals"][0]["reviews"],
                         [reviews[-2]["id"], reviews[-1]["id"]])
        self.assertEqual(runner.script, [])

    def test_documentation_does_not_dispatch_configured_checkpoint(self):
        cfg = self._config("strict")
        cfg["verification"] = [
            "n=$(cat .orchestrator/verify-count 2>/dev/null || echo 0); "
            "n=$((n+1)); echo $n > .orchestrator/verify-count; "
            "if [ \"$n\" = 1 ]; then "
            "echo changed > failed-verification-change.txt; exit 1; fi"
        ]
        script = self._skeleton_clean_no_seal_halves()
        state, driver = self._drive(cfg, script)
        unit = state["units"][0]
        reviews = [
            r for r in unit["rounds"] if r["kind"] == "review_round"
        ]
        self.assertEqual(unit["status"], st.U_SEALED)
        self.assertEqual(
            [r["family"] for r in reviews],
            ["codex", "claude"],
        )
        self.assertEqual(unit["seals"][0]["reviews"],
                         [reviews[-2]["id"], reviews[-1]["id"]])
        self.assertEqual(driver.runner.script, [])
        self.assertEqual(
            [e for e in state["events"] if e["type"] == "verification"],
            [],
        )
        self.assertFalse(os.path.exists(
            os.path.join(self.ws, "failed-verification-change.txt")
        ))

    def test_new_amendment_after_reviews_does_not_revalidate_recorded_results(self):
        cfg = self._config("strict")
        script = self._skeleton_clean_no_seal_halves() + [
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ]
        path = init_state(self.ws, cfg)
        runner = runners.MockRunner(script)
        driver = drv.Driver(path, runner=runner)
        for _ in range(4):
            driver.step()
        self.assertEqual(driver.state["units"][0]["status"],
                         st.U_PRE_SEAL_VERIFY)
        write_file(
            ".orchestrator/amendments.json",
            '{"amendments":[{"id":"A1","text":"Require the new rule."}]}',
        )(self.ws)

        driver.step()

        self.assertEqual(driver.state["units"][0]["status"], st.U_SEALED)
        self.assertFalse(any(
            event["type"] == "amendment_seen"
            for event in driver.state["events"]
        ))

        state = st.load(path)
        unit = state["units"][0]
        reviews = [
            r for r in unit["rounds"] if r["kind"] == "review_round"
        ]
        self.assertEqual(unit["status"], st.U_SEALED)
        self.assertEqual(
            [r["family"] for r in reviews],
            ["codex", "claude"],
        )
        self.assertEqual(unit["seals"][0]["reviews"],
                         [reviews[0]["id"], reviews[1]["id"]])

    def test_legacy_also_seals_from_clean_reviews(self):
        script = self._skeleton_clean_no_seal_halves()
        state, driver = self._drive(self._config("legacy"), script)
        self.assertEqual(state["units"][0]["status"], st.U_SEALED)
        self.assertEqual(driver.runner.script, [])
        self.assertIn("seal_satisfied",
                      [e["type"] for e in state["events"]])


if __name__ == "__main__":
    unittest.main()
