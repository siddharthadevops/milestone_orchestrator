"""The engineering question battery as a structured contract gate on DOC
units (build-driven review reform §4, REALIZATION 3-4), plus the reform's
plain/example hard-require on review findings.

Covers: contracts.validate_battery shape checks (presence is machine-
checked; substance stays review work); validate_worker_output threading
(the battery is demanded only on status=="ok" doc drafts when a
battery_questions gate is set — gap and blocked outputs are exempt, a gap
finishes nothing; require_plain hardens the optional plain/example fields
on every report kind); the "battery" output-key reservation;
interpreter.reform_active / battery_questions gating (the battery is NOT
a dial — every reform profile carries it, implementation units never do);
driver lifecycle under the seed profiles (a battery-less strict draft
burns the single repair retry and fails the run; a valid battery lands in
the recorded draft result with zero state.py changes; legacy drafts stay
battery-free with no retry consumed; a plain/example-less review finding
fails a strict run); and prompt gating (battery blocks appear only when a
battery is passed — battery=None keeps every builder byte-identical, and
the diff-scoped delta review is never battery-aware).
"""

import os
import tempfile
import unittest

from orchestrator import contracts as c
from orchestrator import driver as drv
from orchestrator import interpreter as it
from orchestrator import profiles
from orchestrator import prompts
from orchestrator import runners
from orchestrator import state as st

# NOTE: test_driver_mock.finding() now injects the plain/example lay
# mirror by default (every scripted test finding validates under a reform
# profile). These tests exercise findings WITHOUT that mirror, so they
# construct finding dicts locally instead of importing the helper.
from orchestrator.tests.test_driver_mock import (
    make_config, init_state, step, ok, report,
)

SLICE = {"id": 1, "title": "Calculator core"}
UNIT = "the milestone skeleton"

# The load-bearing first lines of the three battery prompt blocks. The
# review marker is NOT a substring of the draft marker (the parenthesis
# closes right after "gate"), so each assertion is exact.
DRAFT_MARKER = "QUESTION BATTERY (structured gate; mandatory in this run)"
OUTPUT_MARKER = "BATTERY OUTPUT (mandatory in this run):"
REVIEW_MARKER = "QUESTION BATTERY (structured gate)"
SETTLED_RULE = "re-litigating answered questions"


def battery_entries(ids):
    return [
        {"question": q, "answer": "answered: %s" % q,
         "evidence": ["docs/x.md:1"]}
        for q in ids
    ]


def skeleton_ok(**extra):
    o = {"status": "ok", "kind": "draft_skeleton",
         "artifact": "docs/skeleton.md",
         "slices": [{"id": 1, "title": "Core"}]}
    o.update(extra)
    return o


def note_ok(**extra):
    o = {"status": "ok", "kind": "draft_slice_note",
         "artifact": "docs/slice-01.md"}
    o.update(extra)
    return o


def _gap():
    return {
        "classification": "needs_operator",
        "missing_or_conflict": "two goal sentences collide",
        "where": "verbatim: 'floats everywhere' vs 'integers only'",
        "forced_decision": "pick one arithmetic domain",
        "plain": "the goal contradicts itself about numbers",
        "example": "add(0.5, 0.5) is either 1.0 or a rejected input",
    }


def bare_finding(fid="F1", severity="P1"):
    """A finding WITHOUT the plain/example lay mirror (the fields the
    reform hard-requires; optional pre-reform)."""
    return {
        "id": fid,
        "severity": severity,
        "summary": "the doc boundary is unstated",
        "validity": {
            "permitted_baseline": "the documented boundary is explicit",
            "actual_outcome": "the boundary is unstated",
            "incremental_harm": "implementers cannot tell where to stop",
            "exceeds_baseline": True,
        },
    }


def full_finding(fid="F1", severity="P1"):
    f = bare_finding(fid, severity)
    f["plain"] = "the doc never says where the feature stops"
    f["example"] = "a reader adds scientific functions nobody asked for"
    return f


def _profile_state(name=None):
    cfg = {}
    if name:
        cfg["profile"] = profiles.SEEDS[name]["profile"]
    return {"config": cfg}


class ValidateBatteryTest(unittest.TestCase):
    def _ids(self):
        return c.BATTERY_QUESTIONS_SKELETON

    def test_valid_battery_passes_for_both_question_sets(self):
        for ids in (c.BATTERY_QUESTIONS_SKELETON,
                    c.BATTERY_QUESTIONS_SLICE_NOTE):
            c.validate_battery(battery_entries(ids), ids, "t")

    def test_question_order_is_free(self):
        ids = self._ids()
        c.validate_battery(
            list(reversed(battery_entries(ids))), ids, "t")

    def test_missing_question_fails(self):
        ids = self._ids()
        with self.assertRaises(c.ContractError):
            c.validate_battery(battery_entries(ids)[:-1], ids, "t")

    def test_duplicate_question_fails(self):
        ids = self._ids()
        bat = battery_entries(ids) + battery_entries(ids[:1])
        with self.assertRaises(c.ContractError):
            c.validate_battery(bat, ids, "t")

    def test_unknown_question_id_fails(self):
        ids = self._ids()
        bat = battery_entries(ids) + battery_entries(("invented",))
        with self.assertRaises(c.ContractError):
            c.validate_battery(bat, ids, "t")

    def test_empty_or_non_string_answer_fails(self):
        ids = self._ids()
        for bad in ("", 7, None):
            bat = battery_entries(ids)
            bat[0]["answer"] = bad
            with self.assertRaises(c.ContractError):
                c.validate_battery(bat, ids, "t")

    def test_answer_clip_boundary(self):
        ids = self._ids()
        bat = battery_entries(ids)
        bat[0]["answer"] = "a" * c.BATTERY_ANSWER_CLIP
        c.validate_battery(bat, ids, "t")
        bat[0]["answer"] = "a" * (c.BATTERY_ANSWER_CLIP + 1)
        with self.assertRaises(c.ContractError):
            c.validate_battery(bat, ids, "t")

    def test_empty_evidence_list_fails(self):
        ids = self._ids()
        bat = battery_entries(ids)
        bat[0]["evidence"] = []
        with self.assertRaises(c.ContractError):
            c.validate_battery(bat, ids, "t")

    def test_empty_evidence_entry_fails(self):
        ids = self._ids()
        bat = battery_entries(ids)
        bat[0]["evidence"] = [""]
        with self.assertRaises(c.ContractError):
            c.validate_battery(bat, ids, "t")

    def test_evidence_clip_boundary(self):
        ids = self._ids()
        bat = battery_entries(ids)
        bat[0]["evidence"] = ["e" * c.BATTERY_EVIDENCE_CLIP]
        c.validate_battery(bat, ids, "t")
        bat[0]["evidence"] = ["e" * (c.BATTERY_EVIDENCE_CLIP + 1)]
        with self.assertRaises(c.ContractError):
            c.validate_battery(bat, ids, "t")

    def test_non_list_battery_fails(self):
        for bad in ({"question": "victim"}, "victim", None, 7):
            with self.assertRaises(c.ContractError):
                c.validate_battery(bad, self._ids(), "t")

    def test_non_object_entry_fails(self):
        with self.assertRaises(c.ContractError):
            c.validate_battery(["victim"], self._ids(), "t")


class ValidateWorkerOutputBatteryTest(unittest.TestCase):
    def test_gated_ok_draft_requires_the_battery_key(self):
        for out, ids in (
            (skeleton_ok(), c.BATTERY_QUESTIONS_SKELETON),
            (note_ok(), c.BATTERY_QUESTIONS_SLICE_NOTE),
        ):
            with self.assertRaises(c.ContractError):
                c.validate_worker_output(
                    out, out["kind"], battery_questions=ids)

    def test_gated_ok_draft_with_battery_passes(self):
        sk = skeleton_ok(
            battery=battery_entries(c.BATTERY_QUESTIONS_SKELETON))
        self.assertIs(
            c.validate_worker_output(
                sk, "draft_skeleton",
                battery_questions=c.BATTERY_QUESTIONS_SKELETON),
            sk)
        note = note_ok(
            battery=battery_entries(c.BATTERY_QUESTIONS_SLICE_NOTE))
        self.assertIs(
            c.validate_worker_output(
                note, "draft_slice_note",
                battery_questions=c.BATTERY_QUESTIONS_SLICE_NOTE),
            note)

    def test_battery_content_is_validated_not_just_present(self):
        bat = battery_entries(c.BATTERY_QUESTIONS_SKELETON)[:-1]
        with self.assertRaises(c.ContractError):
            c.validate_worker_output(
                skeleton_ok(battery=bat), "draft_skeleton",
                battery_questions=c.BATTERY_QUESTIONS_SKELETON)

    def test_wrong_question_set_fails(self):
        # A slice note answering the skeleton's questions has answered
        # the wrong battery.
        bat = battery_entries(c.BATTERY_QUESTIONS_SKELETON)
        with self.assertRaises(c.ContractError):
            c.validate_worker_output(
                note_ok(battery=bat), "draft_slice_note",
                battery_questions=c.BATTERY_QUESTIONS_SLICE_NOTE)

    def test_ungated_batteryless_draft_passes_unchanged(self):
        # Pre-reform behavior: no gate, no battery demanded.
        c.validate_worker_output(skeleton_ok(), "draft_skeleton")
        c.validate_worker_output(
            skeleton_ok(), "draft_skeleton", battery_questions=None)
        c.validate_worker_output(
            note_ok(), "draft_slice_note", battery_questions=None)

    def test_gap_output_is_exempt(self):
        # A gap finishes nothing; it owes no battery.
        for kind, ids in (
            ("draft_skeleton", c.BATTERY_QUESTIONS_SKELETON),
            ("draft_slice_note", c.BATTERY_QUESTIONS_SLICE_NOTE),
        ):
            out = {"status": "gap", "kind": kind, "gaps": [_gap()]}
            c.validate_worker_output(out, kind, battery_questions=ids)

    def test_gap_may_not_claim_a_battery(self):
        # Exempt from OWING a battery, not licensed to CLAIM one — a
        # battery is finished work and a gap finishes nothing.
        for kind, ids in (
            ("draft_skeleton", c.BATTERY_QUESTIONS_SKELETON),
            ("draft_slice_note", c.BATTERY_QUESTIONS_SLICE_NOTE),
        ):
            out = {"status": "gap", "kind": kind, "gaps": [_gap()],
                   "battery": battery_entries(ids)}
            with self.assertRaises(c.ContractError):
                c.validate_worker_output(out, kind, battery_questions=ids)
            # Gated or not — the guard is on the gap branch itself.
            with self.assertRaises(c.ContractError):
                c.validate_worker_output(out, kind)

    def test_blocked_output_is_exempt(self):
        for kind, ids in (
            ("draft_skeleton", c.BATTERY_QUESTIONS_SKELETON),
            ("draft_slice_note", c.BATTERY_QUESTIONS_SLICE_NOTE),
        ):
            out = {"status": "blocked", "kind": kind,
                   "blocked_reason": "cannot proceed"}
            c.validate_worker_output(out, kind, battery_questions=ids)

    def test_battery_is_a_reserved_output_key(self):
        # Reserved against project contract-extension collisions — on the
        # doc kinds only; implementation units carry no battery.
        self.assertIn("battery", c.reserved_output_keys("draft_skeleton"))
        self.assertIn(
            "battery", c.reserved_output_keys("draft_slice_note"))
        self.assertNotIn("battery", c.reserved_output_keys("implement"))


class RequirePlainTest(unittest.TestCase):
    def _out(self, kind, findings):
        return {"status": "ok", "kind": kind, "findings": findings}

    def test_bare_finding_passes_pre_reform(self):
        for kind in c.REPORT_KINDS:
            c.validate_worker_output(
                self._out(kind, [bare_finding()]), kind)
            c.validate_worker_output(
                self._out(kind, [bare_finding()]), kind,
                require_plain=False)

    def test_bare_finding_fails_when_required(self):
        for kind in c.REPORT_KINDS:
            with self.assertRaises(c.ContractError):
                c.validate_worker_output(
                    self._out(kind, [bare_finding()]), kind,
                    require_plain=True)

    def test_missing_or_empty_field_fails_when_required(self):
        for field in ("plain", "example"):
            gone = full_finding()
            del gone[field]
            empty = full_finding()
            empty[field] = ""
            for f in (gone, empty):
                with self.assertRaises(c.ContractError):
                    c.validate_worker_output(
                        self._out("review_round", [f]), "review_round",
                        require_plain=True)

    def test_full_finding_passes_when_required(self):
        for kind in c.REPORT_KINDS:
            c.validate_worker_output(
                self._out(kind, [full_finding()]), kind,
                require_plain=True)

    def test_clean_report_passes_when_required(self):
        for kind in c.REPORT_KINDS:
            c.validate_worker_output(
                self._out(kind, []), kind, require_plain=True)


class BatteryInterpreterTest(unittest.TestCase):
    def test_reform_active_predicate(self):
        self.assertFalse(it.reform_active(_profile_state()))
        self.assertFalse(it.reform_active(_profile_state("legacy")))
        for name in ("strict", "light"):
            self.assertTrue(it.reform_active(_profile_state(name)))

    def test_every_reform_profile_carries_the_battery(self):
        # The battery is NOT a dial (spec §4): strict and light alike
        # carry it on doc units; implementation units never do.
        for name in ("strict", "light"):
            state = _profile_state(name)
            self.assertEqual(
                it.battery_questions(state, st.UNIT_SKELETON),
                c.BATTERY_QUESTIONS_SKELETON)
            self.assertEqual(
                it.battery_questions(state, st.UNIT_SLICE_DOC),
                c.BATTERY_QUESTIONS_SLICE_NOTE)
            self.assertIsNone(
                it.battery_questions(state, st.UNIT_SLICE_IMPL))

    def test_legacy_and_profile_less_have_no_battery(self):
        for state in (_profile_state(), _profile_state("legacy")):
            for kind in (st.UNIT_SKELETON, st.UNIT_SLICE_DOC,
                         st.UNIT_SLICE_IMPL):
                self.assertIsNone(it.battery_questions(state, kind))


class BatteryDriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-battery-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, "ws")
        os.makedirs(self.ws)

    def _config(self, profile_name):
        cfg = make_config()
        cfg["git"] = {"enabled": False}
        cfg["profile"] = profiles.SEEDS[profile_name]["profile"]
        return cfg

    def _drive(self, cfg, script):
        path = init_state(self.ws, cfg)
        driver = drv.Driver(path, runner=runners.MockRunner(script))
        for _ in range(60):
            if driver.state["units"][0]["status"] in (
                st.U_SEALED, st.U_FAILED,
            ):
                break
            action, _note = driver.step()
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
        return st.load(path), driver

    def _skeleton_draft(self, **extra):
        return ok("draft_skeleton", artifact="docs/skeleton.md",
                  slices=[{"id": 1, "title": "Core"}], **extra)

    def test_strict_batteryless_draft_burns_retry_then_fails(self):
        bad = self._skeleton_draft()  # no battery
        state, driver = self._drive(self._config("strict"), [
            step("draft_skeleton", bad, family="codex"),
            step("draft_skeleton", bad, family="codex"),  # repair retry
        ])
        self.assertEqual(driver.runner.script, [])
        drafts = [p for _f, k, p in driver.runner.calls
                  if k == "draft_skeleton"]
        self.assertEqual(len(drafts), 2)
        self.assertIn("REPAIR:", drafts[1])
        self.assertIsNotNone(state["failure"])
        for sub in ("draft_skeleton call failed",
                    "contract-violating output twice", "battery"):
            self.assertIn(sub, state["failure"]["reason"])
        self.assertEqual(state["milestone"]["status"], st.M_FAILED)
        self.assertEqual(state["units"][0]["status"], st.U_FAILED)

    def test_strict_draft_battery_recorded_and_unit_seals(self):
        bat = battery_entries(c.BATTERY_QUESTIONS_SKELETON)
        state, driver = self._drive(self._config("strict"), [
            step("draft_skeleton", self._skeleton_draft(battery=bat),
                 family="codex"),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ])
        self.assertIsNone(state["failure"])
        sk = state["units"][0]
        self.assertEqual(sk["status"], st.U_SEALED)
        # The battery landed in the ledger through the recorded draft
        # result — no state.py plumbing of its own.
        self.assertEqual(sk["draft"]["result"]["battery"], bat)
        self.assertEqual(driver.runner.script, [])
        # The driver threaded the battery into the prompts it built.
        draft_prompt = driver.runner.calls[0][2]
        self.assertIn(DRAFT_MARKER, draft_prompt)
        self.assertIn(OUTPUT_MARKER, draft_prompt)
        for _fam, kind, prompt in driver.runner.calls[1:]:
            self.assertEqual(kind, "review_round")
            self.assertIn(REVIEW_MARKER, prompt)

    def test_legacy_batteryless_draft_passes_with_no_retry(self):
        path = init_state(self.ws, self._config("legacy"))
        driver = drv.Driver(
            path,
            runner=runners.MockRunner([
                step("draft_skeleton", self._skeleton_draft(),
                     family="codex"),
            ]),
        )
        action, _note = driver.step()
        self.assertEqual(action.type, drv.A_DRAFT)
        # Script length is the proof: one call, no repair retry consumed.
        self.assertEqual(driver.runner.script, [])
        self.assertEqual(len(driver.runner.calls), 1)
        state = st.load(path)
        self.assertIsNone(state["failure"])
        self.assertEqual(
            state["units"][0]["draft"]["result"]["status"], "ok")
        prompt = driver.runner.calls[0][2]
        self.assertNotIn("QUESTION BATTERY", prompt)
        self.assertNotIn("BATTERY OUTPUT", prompt)
        self.assertNotIn("REPAIR:", prompt)

    def test_strict_review_findings_require_plain_and_example(self):
        bat = battery_entries(c.BATTERY_QUESTIONS_SKELETON)
        bare = report("review_round", [bare_finding()])
        state, driver = self._drive(self._config("strict"), [
            step("draft_skeleton", self._skeleton_draft(battery=bat),
                 family="codex"),
            step("review_round", bare, family="codex"),
            step("review_round", bare, family="codex"),  # repair retry
        ])
        self.assertEqual(driver.runner.script, [])
        reviews = [p for _f, k, p in driver.runner.calls
                   if k == "review_round"]
        self.assertEqual(len(reviews), 2)
        self.assertIn("REPAIR:", reviews[1])
        self.assertIsNotNone(state["failure"])
        for sub in ("review_round call failed",
                    "contract-violating output twice", "plain"):
            self.assertIn(sub, state["failure"]["reason"])
        self.assertEqual(state["milestone"]["status"], st.M_FAILED)
        # The SAME finding with both fields present validates.
        good = report("review_round", [full_finding()])
        c.validate_worker_output(good, "review_round", require_plain=True)


class BatteryPromptGatingTest(unittest.TestCase):
    def _skeleton(self, battery):
        return prompts.build_draft_skeleton(
            "codex", "/ws", "goal", battery=battery)

    def _note(self, battery):
        return prompts.build_draft_slice_note(
            "codex", "/ws", "goal", SLICE, "docs/skeleton.md",
            battery=battery)

    def _review(self, build, battery):
        return build(
            "codex", "/ws", "goal", UNIT, "docs/skeleton.md", [],
            unit_kind="skeleton", battery=battery)

    def test_draft_skeleton_carries_the_battery_blocks(self):
        text = self._skeleton(c.BATTERY_QUESTIONS_SKELETON)
        self.assertIn(DRAFT_MARKER, text)
        self.assertIn(OUTPUT_MARKER, text)
        for q in c.BATTERY_QUESTIONS_SKELETON:
            self.assertIn(q, text)

    def test_draft_skeleton_without_battery_carries_neither(self):
        text = self._skeleton(None)
        self.assertNotIn("QUESTION BATTERY", text)
        self.assertNotIn("BATTERY OUTPUT", text)

    def test_draft_slice_note_carries_blocks_and_inheritance(self):
        text = self._note(c.BATTERY_QUESTIONS_SLICE_NOTE)
        self.assertIn(DRAFT_MARKER, text)
        self.assertIn(OUTPUT_MARKER, text)
        for q in c.BATTERY_QUESTIONS_SLICE_NOTE:
            self.assertIn(q, text)
        # The inheritance sentence names the skeleton: the slice-note
        # battery is the slice-scoped remainder, never a re-answer.
        norm = " ".join(text.split()).lower()
        i = norm.find("inherited")
        self.assertNotEqual(i, -1, "no inherited-battery sentence")
        self.assertIn("skeleton", norm[max(0, i - 200):i + 200])

    def test_draft_slice_note_without_battery_carries_neither(self):
        text = self._note(None)
        self.assertNotIn("QUESTION BATTERY", text)
        self.assertNotIn("BATTERY OUTPUT", text)

    def test_review_and_seal_carry_the_review_block(self):
        for build in (prompts.build_review_round, prompts.build_seal_half):
            text = self._review(build, c.BATTERY_QUESTIONS_SKELETON)
            self.assertIn(REVIEW_MARKER, text)
            self.assertIn(SETTLED_RULE, text)
            for q in c.BATTERY_QUESTIONS_SKELETON:
                self.assertIn(q, text)

    def test_review_and_seal_without_battery_carry_nothing(self):
        for build in (prompts.build_review_round, prompts.build_seal_half):
            text = self._review(build, None)
            self.assertNotIn("QUESTION BATTERY", text)
            self.assertNotIn(SETTLED_RULE, text)

    def test_delta_review_is_never_battery_aware(self):
        # Diff-scoped: the delta reviewer judges a fix delta, not the
        # artifact's battery — its builder takes no battery argument.
        # Guard the QUESTION battery specifically: the SEVERITY battery
        # is a different instrument (severity-scoring guidance) that
        # legitimately rides every finding-producing prompt, deltas
        # included.
        text = prompts.build_delta_review(
            "codex", "/ws", "goal", UNIT, "diff --git a/x b/x\n", [],
            unit_kind="skeleton")
        self.assertNotIn("QUESTION BATTERY", text)
        self.assertNotIn("question battery", text)
        self.assertNotIn(SETTLED_RULE, text)


class ThreatModelAndEnforceabilityTest(unittest.TestCase):
    """The two questions added after the LPC rich-content failure
    (2026-07-10): a sealed note asserted a security guarantee no pinned
    mechanism could enforce and never named the attacker, so the design
    gap surfaced at the CODE phase (100+ rounds) instead of the DOC
    phase (one battery answer). These tests pin the lesson."""

    def test_threat_model_is_skeleton_level(self):
        self.assertIn("threat_model", c.BATTERY_QUESTIONS_SKELETON)
        # Inherited by notes like the rest of the skeleton battery —
        # never re-answered per slice.
        self.assertNotIn("threat_model", c.BATTERY_QUESTIONS_SLICE_NOTE)

    def test_enforceability_is_asked_at_both_doc_levels(self):
        # The skeleton answers it for the design's guarantees; every
        # note re-answers it for the facts IT pins — the one exemption
        # from the inherit-don't-re-answer rule.
        self.assertIn("enforceability", c.BATTERY_QUESTIONS_SKELETON)
        self.assertIn("enforceability", c.BATTERY_QUESTIONS_SLICE_NOTE)

    def test_descriptions_carry_the_load_bearing_clauses(self):
        threat = prompts.BATTERY_QUESTION_DESCRIPTIONS["threat_model"]
        self.assertIn("attacker", threat)
        self.assertIn("TRUSTED", threat)
        enf = prompts.BATTERY_QUESTION_DESCRIPTIONS["enforceability"]
        self.assertIn("mechanism", enf)
        # The clause that would have caught slice-02 line 31: an
        # unenforceable guarantee is reported as a gap, not written down.
        self.assertIn("design gap to report", enf)
        self.assertIn("never a promise", enf)

    def test_note_drafter_sees_the_double_level_exception(self):
        text = prompts.build_draft_slice_note(
            "codex", "/ws", "goal", SLICE, "docs/skeleton.md",
            battery=c.BATTERY_QUESTIONS_SLICE_NOTE)
        norm = " ".join(text.split())
        self.assertIn("Exception: enforceability is answered at BOTH", norm)


if __name__ == "__main__":
    unittest.main()
