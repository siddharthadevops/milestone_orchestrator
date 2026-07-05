"""Regressions for the PROCESS AUTHORITY section of every worker prompt.

Live incident: a codex seal_half worker on a real run returned status
"blocked" because a MANUAL-era review log vendored inside the workspace
(review-log.md pending checkboxes + the old textual canon's "record
VERDICT before sealing" rule) contradicted the orchestrator's durable
ledger, which had legitimately opened the sealing phase. The ledger
(.orchestrator/state.json) is the SOLE process truth; repo-resident
process documents must never govern a run.

The fix appended a PROCESS AUTHORITY section to _access_block(), which
every one of the 7 prompt builders inherits. These tests pin:
  (1) all 7 builders emit the section and its load-bearing phrases;
  (2) report-only builders still carry REPORT-ONLY and edit builders
      still carry the workspace-edit line (access model intact);
  (3) the incident regression: seal_half prompts carry the authority
      phrases and contain NO instruction to record verdicts in repo
      logs — the only VERDICT mention is the bookkeeping BAN;
  (4) existing invariants: the adjudicated-rejections registry block is
      injected in review/delta/seal/fix only, and the consultation
      protocol block appears only in fix prompts.
"""

import unittest

from orchestrator import contracts, prompts

FAMILY = "codex"
WORKSPACE = "/tmp/ws"
GOAL = "One-call workspace discovery"
UNIT = "slice 1 (core)"
SLICE = {"id": 1, "title": "core"}
FINDINGS = [{"id": "R1-F1", "severity": "P2", "summary": "off-by-one"}]

EDIT_BUILDERS = (
    "draft_skeleton",
    "draft_slice_note",
    "implement",
    "fix_findings",
)
REPORT_BUILDERS = ("review_round", "delta_review", "seal_half")
REGISTRY_BUILDERS = ("review_round", "delta_review", "seal_half", "fix_findings")

# Phrases that carry the fix's weight. Multi-line phrases are asserted on
# a whitespace-normalized form so they survive the prompt's line wrapping.
AUTHORITY_HEADING = "PROCESS AUTHORITY"
AUTHORITY_PHRASES_RAW = (
    "SOLE source of truth",
    "never for process-state concerns",
)
AUTHORITY_PHRASES_NORMALIZED = (
    "never re-derive or second-guess process state",
    "do NOT govern this run",
    "never perform their bookkeeping",
    "supersedes any instruction file in or above the workspace",
    "is NOT a reportable defect",
)


def normalized(text):
    """Collapse all whitespace runs (including the prompt's hard wraps)
    to single spaces, so multi-line phrases can be asserted whole."""
    return " ".join(text.split())


def build_all():
    """Every one of the 7 builders, invoked with representative
    arguments. Keys are the builder kinds from contracts."""
    return {
        "draft_skeleton": prompts.build_draft_skeleton(FAMILY, WORKSPACE, GOAL),
        "draft_slice_note": prompts.build_draft_slice_note(
            FAMILY, WORKSPACE, GOAL, SLICE, "docs/skeleton.md"
        ),
        "implement": prompts.build_implement(
            FAMILY, WORKSPACE, GOAL, SLICE, "docs/slice-01.md", ["make test"]
        ),
        "review_round": prompts.build_review_round(
            FAMILY, WORKSPACE, GOAL, UNIT, "docs/slice-01.md", []
        ),
        "delta_review": prompts.build_delta_review(
            FAMILY, WORKSPACE, GOAL, UNIT, "diff --git a/x b/x\n", []
        ),
        "seal_half": prompts.build_seal_half(
            FAMILY, WORKSPACE, GOAL, UNIT, "docs/slice-01.md", []
        ),
        "fix_findings": prompts.build_fix_findings(
            FAMILY,
            WORKSPACE,
            GOAL,
            UNIT,
            FINDINGS,
            [],
            "claude",
            ["claude", "-p"],
        ),
    }


class TestProcessAuthorityInEveryBuilder(unittest.TestCase):
    """(1) All 7 builders emit PROCESS AUTHORITY with its load-bearing
    phrases — the section lives in _access_block, which every builder
    includes, so a regression in any one builder means the block was
    dropped or bypassed."""

    def test_all_seven_builders_are_covered(self):
        built = build_all()
        self.assertEqual(sorted(built), sorted(contracts.KINDS))
        self.assertEqual(sorted(REPORT_BUILDERS), sorted(contracts.REPORT_KINDS))
        self.assertEqual(sorted(EDIT_BUILDERS), sorted(contracts.EDIT_KINDS))

    def test_every_builder_emits_process_authority_heading(self):
        for name, prompt in build_all().items():
            with self.subTest(builder=name):
                self.assertIn(AUTHORITY_HEADING, prompt)

    def test_every_builder_emits_load_bearing_phrases(self):
        for name, prompt in build_all().items():
            flat = normalized(prompt)
            for phrase in AUTHORITY_PHRASES_RAW:
                with self.subTest(builder=name, phrase=phrase):
                    self.assertIn(phrase, prompt)
            for phrase in AUTHORITY_PHRASES_NORMALIZED:
                with self.subTest(builder=name, phrase=phrase):
                    self.assertIn(phrase, flat)

    def test_ledger_named_as_sole_truth(self):
        # The section must point at the durable ledger by name, not just
        # assert authority abstractly.
        for name, prompt in build_all().items():
            with self.subTest(builder=name):
                self.assertIn(".orchestrator/state.json", prompt)

    def test_blocked_reserved_for_true_impossibility(self):
        # The block must forbid process-state blocking without redefining
        # "blocked" away from the contract's per-finding semantics.
        for name, prompt in build_all().items():
            flat = normalized(prompt)
            with self.subTest(builder=name):
                self.assertIn(
                    'is NEVER grounds for "blocked"', flat
                )
                self.assertIn(
                    "Block only when your own task is truly impossible", flat
                )
                self.assertIn(
                    'the per-finding "blocked" disposition keeps its '
                    "contract meaning",
                    flat,
                )


class TestAccessModelStillIntact(unittest.TestCase):
    """(2) The PROCESS AUTHORITY append must not have disturbed the
    access model: report-only builders keep the REPORT-ONLY ban, edit
    builders keep the workspace-edit line, and neither leaks into the
    other side."""

    REPORT_ONLY_LINE = (
        "REPORT-ONLY: do not create, edit, delete, or move any file"
    )
    EDIT_LINE = "Edit permissions INSIDE the workspace only"

    def test_report_builders_carry_report_only(self):
        built = build_all()
        for name in REPORT_BUILDERS:
            with self.subTest(builder=name):
                self.assertIn(self.REPORT_ONLY_LINE, built[name])
                self.assertNotIn(self.EDIT_LINE, built[name])

    def test_edit_builders_carry_workspace_edit_line(self):
        built = build_all()
        for name in EDIT_BUILDERS:
            with self.subTest(builder=name):
                self.assertIn(self.EDIT_LINE, built[name])
                self.assertNotIn(self.REPORT_ONLY_LINE, built[name])

    def test_authority_section_follows_access_section(self):
        # PROCESS AUTHORITY is appended inside the ACCESS block; it must
        # come after the access rules, so a worker reads its edit/report
        # constraints before the authority override.
        for name, prompt in build_all().items():
            with self.subTest(builder=name):
                self.assertLess(
                    prompt.index("ACCESS"), prompt.index(AUTHORITY_HEADING)
                )


class TestSealHalfOverridesVendoredCanonBookkeeping(unittest.TestCase):
    """(3) The incident regression. A seal_half worker blocked a run
    because a vendored manual canon demanded 'record normal Codex
    VERDICT: 0 ... in the durable log before any seal phase opens' and
    the milestone's review-log.md still had pending checkboxes. The
    seal_half prompt must carry the authority phrases AND contain no
    instruction to record verdicts in repo logs — the only VERDICT
    mention allowed is the bookkeeping BAN itself."""

    def build(self):
        return prompts.build_seal_half(
            FAMILY, WORKSPACE, GOAL, UNIT, "docs/slice-01.md", []
        )

    def test_seal_half_carries_authority_phrases(self):
        prompt = self.build()
        flat = normalized(prompt)
        self.assertIn(AUTHORITY_HEADING, prompt)
        for phrase in AUTHORITY_PHRASES_RAW:
            self.assertIn(phrase, prompt)
        for phrase in AUTHORITY_PHRASES_NORMALIZED:
            self.assertIn(phrase, flat)

    def test_no_instruction_to_record_verdicts_in_repo_logs(self):
        prompt = self.build()
        flat = normalized(prompt)
        # No affirmative bookkeeping instructions from the manual era.
        for forbidden in (
            "record normal Codex VERDICT",
            "record normal Claude VERDICT",
            "record VERDICT",
            "Seal Attempts",
            "tick the checkbox",
        ):
            self.assertNotIn(forbidden.lower(), flat.lower())

    def test_review_log_named_only_as_generated_ledger(self):
        # The block deliberately names docs/review-log.md when enumerating
        # the driver-generated ledgers (so workers can tell it apart from
        # manual-era logs); every mention must be that enumeration, never
        # a bare review-log.md a worker could read as the manual one.
        flat = normalized(self.build())
        start = 0
        while True:
            idx = flat.find("review-log.md", start)
            if idx == -1:
                break
            self.assertEqual(
                flat[max(0, idx - 5): idx],
                "docs/",
                "bare review-log.md mention at offset %d: ...%s..."
                % (idx, flat[max(0, idx - 60): idx + 20]),
            )
            start = idx + 1

    def test_every_verdict_mention_is_inside_the_bookkeeping_ban(self):
        # Case-sensitive on purpose: uppercase VERDICT is the manual
        # canon's affirmative log-line style ('VERDICT: 0'); the ledger
        # bullet's lowercase 'their verdicts' describes ledger content
        # and is legitimate.
        prompt = self.build()
        flat = normalized(prompt)
        ban = "never perform their bookkeeping"
        start = 0
        occurrences = 0
        while True:
            idx = flat.find("VERDICT", start)
            if idx == -1:
                break
            occurrences += 1
            window = flat[max(0, idx - 300): idx]
            self.assertIn(
                ban,
                window,
                "VERDICT mentioned outside the bookkeeping ban at "
                "offset %d: ...%s..." % (idx, flat[max(0, idx - 80): idx + 40]),
            )
            start = idx + 1
        # The ban itself names the artifact ('writing VERDICT lines'),
        # so at least one banned mention must exist.
        self.assertGreaterEqual(occurrences, 1)


class TestExistingPromptInvariants(unittest.TestCase):
    """(4) Pre-fix invariants that must survive: the registry block is
    injected in review/delta/seal/fix prompts only, and the consultation
    protocol appears only in fix prompts."""

    # CONTRACT_TEXT (appended to every prompt) also says "ADJUDICATED
    # REJECTIONS" when describing the output rules, so presence/absence
    # of the injected registry BLOCK is keyed on its own renderings:
    # the empty-registry placeholder (build_all passes empty registries)
    # and the non-empty header line.
    EMPTY_REGISTRY_MARKER = "(none so far in this milestone)"
    NONEMPTY_REGISTRY_MARKER = (
        "ADJUDICATED REJECTIONS (milestone-wide; settled unless NEW evidence)"
    )
    CONSULTATION_MARKER = "CONSULTATION PROTOCOL"

    def test_registry_block_in_review_delta_seal_fix(self):
        built = build_all()
        for name in REGISTRY_BUILDERS:
            with self.subTest(builder=name):
                self.assertIn(self.EMPTY_REGISTRY_MARKER, built[name])

    def test_registry_block_absent_from_draft_and_implement(self):
        built = build_all()
        for name in ("draft_skeleton", "draft_slice_note", "implement"):
            with self.subTest(builder=name):
                self.assertNotIn(self.EMPTY_REGISTRY_MARKER, built[name])
                self.assertNotIn(self.NONEMPTY_REGISTRY_MARKER, built[name])

    def test_consultation_block_only_in_fix(self):
        built = build_all()
        self.assertIn(self.CONSULTATION_MARKER, built["fix_findings"])
        for name in built:
            if name == "fix_findings":
                continue
            with self.subTest(builder=name):
                self.assertNotIn(self.CONSULTATION_MARKER, built[name])

    def test_registry_entries_rendered_when_present(self):
        registry = [
            {
                "id": "ADJ-1",
                "unit": UNIT,
                "severity": "P3",
                "summary": "settled finding",
                "rationale": "checked against real code",
            }
        ]
        prompt = prompts.build_seal_half(
            FAMILY, WORKSPACE, GOAL, UNIT, "docs/slice-01.md", registry
        )
        self.assertIn("ADJ-1", prompt)
        self.assertIn("settled finding", prompt)


if __name__ == "__main__":
    unittest.main()
