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
        "classification": "fits_remodel",
        "missing_or_conflict": "the transport discards the field",
        "where": "docs/skeleton.md:42",
        "forced_decision": "carry the field so downstream can read it",
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

    def test_classification_is_a_closed_enum(self):
        # Both codes validate.
        for code in c.GAP_CLASSIFICATIONS:
            c.validate_worker_output(
                _impl(gaps=[_gap(classification=code)]), "implement")
        # Anything else — including the retired target vocabulary — fails.
        for bad in ("skeleton", "goal", "slice_doc-01", "remodel", ""):
            with self.assertRaises(c.ContractError):
                c.validate_worker_output(
                    _impl(gaps=[_gap(classification=bad)]), "implement")

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
        # The worker classifies (needs_operator everywhere; fits_remodel for
        # builders below the skeleton) — it never picks a routing target.
        skel, impl = self._skeleton(True), self._implement(True)
        for text in (skel, impl):
            self.assertIn("GAP EXIT", text)
            self.assertIn("stop-report-repair-resume", text)
            self.assertIn("needs_operator", text)
            self.assertIn("DOES FIXING THIS FIT", text)
            # The retired target vocabulary is gone.
            self.assertNotIn("slice_doc-NN", text)
            # gap is disambiguated from blocked so a builder never routes an
            # in-goal design hole to the operator via "blocked" (finding 4).
            self.assertIn("A gap is NOT a \"blocked\"", text)
        # fits_remodel is offered to the implementer, not to the skeleton
        # drafter (the design authority writes in-goal design, never gaps it).
        self.assertIn("fits_remodel", impl)
        self.assertNotIn("fits_remodel", skel)

    def test_remodel_scope_authority_reaches_full_and_delta_reviews(self):
        # An impl folding in a skeleton-assigned upstream fix must be judged
        # against the CURRENT skeleton in BOTH the full round and the fix
        # delta — otherwise the delta reviewer rejects it as out-of-note
        # (finding 5). Doc kinds never get the block.
        full_impl = prompts.build_review_round(
            "codex", "/ws", "goal", "slice_impl-01", "calc.py", [],
            unit_kind="slice_impl")
        delta_impl = prompts.build_delta_review(
            "codex", "/ws", "goal", "slice_impl-01", "diff\n", [],
            unit_kind="slice_impl")
        for text in (full_impl, delta_impl):
            self.assertIn("SCOPE AUTHORITY", text)
            self.assertIn("authorized by the CURRENT sealed SKELETON", text)
            # The reviewer's authority ordering matches the implementer's, so
            # a remodel-assigned change over a stale own-note is not flagged.
            self.assertIn("GOAL > current SKELETON", text)
            self.assertIn("OUTRANKS this unit's own", text)
        delta_doc = prompts.build_delta_review(
            "codex", "/ws", "goal", "slice_doc-01", "diff\n", [],
            unit_kind="slice_doc")
        self.assertNotIn("SCOPE AUTHORITY", delta_doc)

    def test_redraft_after_remodel_exposes_the_skeleton_assignment(self):
        # A re-draft (gap_repairs>0) must READ the remodelled skeleton — the
        # slice note is unchanged, so without this the prompt is byte-identical
        # and the implementer re-gaps until gap_stall (finding 2, round 4).
        base = prompts.build_implement(
            "codex", "/ws", "goal", self.SLICE, "n.md", [],
            gap_enabled=True, skeleton_path="docs/skeleton.md",
            remodeled=False)
        redraft = prompts.build_implement(
            "codex", "/ws", "goal", self.SLICE, "n.md", [],
            gap_enabled=True, skeleton_path="docs/skeleton.md",
            remodeled=True)
        self.assertNotIn("REMODEL ASSIGNMENT", base)
        self.assertIn("REMODEL ASSIGNMENT", redraft)
        self.assertIn("docs/skeleton.md", redraft)
        # The implementer's authority ordering matches the reviewer's, so the
        # remodel over a stale own-note is not an unresolvable conflict.
        # (wrap-safe fragments: the full sentence spans a line break)
        self.assertIn("current SKELETON > this slice's own note", redraft)
        self.assertIn("OVERRIDES any conflicting clause", redraft)

    def test_gap_semantics_predicate(self):
        self.assertFalse(it.gap_semantics({"config": {}}))
        legacy = {"config": {"profile": profiles.SEEDS["legacy"]["profile"]}}
        self.assertFalse(it.gap_semantics(legacy))
        for name in ("strict", "light"):
            st = {"config": {"profile": profiles.SEEDS[name]["profile"]}}
            self.assertTrue(it.gap_semantics(st))


if __name__ == "__main__":
    unittest.main()
