# Slice 01 Closure - Altitude Rule, Doc-Review Altitude Check, And Template Guardrail

Status: closed

## Reviewed Implementation

- Reviewed implementation commit: `5c0b6e5`
- Planned reviewed tag: `v0.8.0`
- Review state: `review_clean`

## Delivered

- Named the Altitude Rule in Documentation Discipline: documentation scope
  states observable contracts, invariants, and the tests that pin them;
  mechanism belongs to implementation; with the falsifiability test, the
  pinned-contract exception, and the fix direction for documentation
  findings.
- Added the documentation-phase reduction guard to the Altitude Rule and to
  the review runner's convergence section: reducing over-specified mechanism
  to its unchanged contract is not a substantial scope or design change.
- Required documentation-phase review prompts (skeleton, slice documentation,
  process-doc) to run the altitude check in both directions, with
  over-specified mechanism `P3` by default and `P2` when acceptance criteria
  or tests anchor to mechanism instead of observable behavior.
- Added the altitude guardrail to the slice template `Scope` section.
- Advanced public pinning and `VERSION` to reviewed release `v0.8.0`.

## Verification

- Full official suite passed before normal review: `git diff --check`.
- Normal review: Codex r2 `VERDICT: 0`; Claude r2 `VERDICT: 0`.
- Full official suite passed after normal review: `git diff --check`.
- Implementation seal a1: Codex `VERDICT: 0`; Claude `VERDICT: 0`.

## Review Findings

- Codex r1 `F01 [P2]` fixed: continuation-state staleness in Current Slice.
- Claude r1 `F01 [P3]` rejected after the Codex-dialogue adjudication: the
  named subsection satisfies the sealed intent ("the rejection stands").

## Accepted Debt

None.

## Follow-Ups

- Create and push annotated tag `v0.8.0` on the final release commit.
- Consuming repositories pick up the rule at their next canon repin.
