"""The gap-report contract (build-driven review reform §3): a draft/
implement worker may return status "gap" with a mandatory, structured
`gaps` array instead of finishing. Reviewers may not. A gap carries no
artifact claim, and gaps never ride an `ok`.
"""

import unittest

from orchestrator import contracts as c
from orchestrator import interpreter as it
from orchestrator import profiles
from orchestrator import prompts


def _gap(**over):
    g = {
        "target": "skeleton",
        "missing_or_conflict": "the transport discards the field",
        "where": "docs/skeleton.md:42",
        "forced_decision": "carry the field, or drop the feature",
        "plain": "the plan says use a field the pipes throw away",
        "example": "participant B's conflict code never reaches the UI",
    }
    g.update(over)
    return g


def _impl(**over):
    o = {"status": "gap", "kind": "implement", "gaps": [_gap()]}
    o.update(over)
    return o


class GapContractTest(unittest.TestCase):
    def test_valid_gap_on_each_builder_kind(self):
        for kind in ("draft_skeleton", "draft_slice_note", "implement"):
            out = {"status": "gap", "kind": kind, "gaps": [_gap()]}
            self.assertIs(c.validate_worker_output(out, kind), out)

    def test_proposal_optional_and_nullable(self):
        c.validate_worker_output(_impl(gaps=[_gap(proposal=None)]), "implement")
        c.validate_worker_output(
            _impl(gaps=[_gap(proposal="carry it in the envelope header")]),
            "implement")
        with self.assertRaises(c.ContractError):
            c.validate_worker_output(_impl(gaps=[_gap(proposal="")]), "implement")

    def test_reviewer_kinds_may_not_report_a_gap(self):
        for kind in ("review_round", "delta_review", "seal_half",
                     "reclassify", "fix_findings"):
            with self.assertRaises(c.ContractError):
                c.validate_worker_output(
                    {"status": "gap", "kind": kind, "gaps": [_gap()]}, kind)

    def test_gap_requires_nonempty_gaps(self):
        with self.assertRaises(c.ContractError):
            c.validate_worker_output(_impl(gaps=[]), "implement")

    def test_each_required_field_enforced(self):
        for field in c.GAP_REQUIRED_FIELDS:
            bad = _gap()
            del bad[field]
            with self.assertRaises(c.ContractError):
                c.validate_worker_output(_impl(gaps=[bad]), "implement")

    def test_gap_carries_no_artifact_claim(self):
        for claim in ("artifact", "files_changed", "slices"):
            with self.assertRaises(c.ContractError):
                c.validate_worker_output(
                    _impl(**{claim: ["something"]}), "implement")

    def test_gaps_never_ride_a_non_gap_status(self):
        with self.assertRaises(c.ContractError):
            c.validate_worker_output(
                {"status": "ok", "kind": "implement", "files_changed": [],
                 "gaps": [_gap()]}, "implement")

    def test_ok_and_blocked_still_validate_unchanged(self):
        c.validate_worker_output(
            {"status": "ok", "kind": "draft_slice_note", "artifact": "n.md"},
            "draft_slice_note")
        c.validate_worker_output(
            {"status": "blocked", "kind": "implement",
             "blocked_reason": "cannot proceed"}, "implement")

    def test_gaps_is_a_reserved_output_key(self):
        self.assertIn("gaps", c.COMMON_OUTPUT_KEYS)


class GapPromptGatingTest(unittest.TestCase):
    """The gap exit is advertised ONLY when a reform profile governs — legacy
    and profile-less builders never see it (so they never return a gap, and
    stay bit-identical)."""

    SLICE = {"id": 1, "title": "Calculator core"}

    def _skeleton(self, gap_enabled):
        return prompts.build_draft_skeleton(
            "codex", "/ws", "goal", gap_enabled=gap_enabled)

    def _implement(self, gap_enabled):
        return prompts.build_implement(
            "codex", "/ws", "goal", self.SLICE, "n.md", [],
            gap_enabled=gap_enabled)

    def test_gap_block_absent_by_default(self):
        self.assertNotIn("GAP EXIT", self._skeleton(False))
        self.assertNotIn("GAP EXIT", self._implement(False))

    def test_gap_block_present_when_enabled(self):
        for text, target in ((self._skeleton(True), '"goal"'),
                             (self._implement(True), "slice_doc-NN")):
            self.assertIn("GAP EXIT", text)
            self.assertIn("stop-report-repair-resume", text)
            self.assertIn(target, text)

    def test_gap_semantics_predicate(self):
        self.assertFalse(it.gap_semantics({"config": {}}))
        legacy = {"config": {"profile": profiles.SEEDS["legacy"]["profile"]}}
        self.assertFalse(it.gap_semantics(legacy))
        for name in ("strict", "light"):
            st = {"config": {"profile": profiles.SEEDS[name]["profile"]}}
            self.assertTrue(it.gap_semantics(st))


if __name__ == "__main__":
    unittest.main()
