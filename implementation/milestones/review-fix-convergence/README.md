# Review Fix Convergence

Status: open.

Planned reviewed release: `v0.9.0`.

## Boundary

S8 canonizes review fix-convergence discipline so review rounds converge by
whole-artifact passes instead of per-finding relaunches.

## Canonical Basis

- Common process: [`../../../canon/process/README.md`](../../../canon/process/README.md)
- Review runner: [`../../../canon/process/codex-review.md`](../../../canon/process/codex-review.md)
- Local context: [`../../local-context.md`](../../local-context.md)
- Local templates: [`../../../templates/local-state/implementation/milestones/_milestone/review-log.md`](../../../templates/local-state/implementation/milestones/_milestone/review-log.md)
- Prior reviewed release: `v0.8.0`

## Reuse Posture

- Checked: the Reviews section, Review/Seal Convergence, Prompt Shape,
  Documentation Discipline, and the milestone review-log template.
- Reused or extended: the existing reviewer sequence, finding-verification
  rule, durable review log, and double-seal evidence contract.
- New machinery, if any: none; process wording and template fields only.
- Compatibility: consumers keep the same gates, seal counts, no-edit prompts,
  worktree checks, and `VERDICT: 0` convergence criterion.
- Local context: this product-neutral canon repo records no support order and
  no sensitive local exclusions.

## Shared Contract

Verified findings from a review round are fixed in one batched pass, then the
orchestrator self-reviews the pending diff before relaunching that reviewer.
Review prompts require exhaustive passes, and review logs pre-print the
evidence fields needed for clean states and seal halves. This changes review
cadence and evidence shape, not reviewer authority or pass/fail criteria.

## Non-Canonical Planning

- Named planning material: Agent99 M28 Slice 04 documentation-phase review
  tail; LPC M34 skeleton convergence; Life M163 review lanes; operator
  pre-automation self-review practice.
- Adopt / Revise / Reject: adopt batched fixes, pre-relaunch self-review,
  reviewer exhaustiveness, and pre-printed review-log evidence fields.
  Reject severity-based early exit from normal rounds, slice risk classes,
  proportional review depth, and automation/tooling.
- Notes: the planning material informs process discipline only; canon wording
  remains product-neutral.

## Slices

| Slice | Title | Status | Notes |
|---|---|---|---|
| 01 | Batched fixes, pre-relaunch self-review, exhaustive prompts, and evidence fields | ready | Slice note sealed `ready`. |

## Work Log

| Unit | Phase | Status | Review | Commit | Notes |
|---|---|---|---|---|---|
| Skeleton | doc | ready | Codex r1 clean; Claude r3 clean; seal a1 clean | 98c17f5 | Skeleton sealed `ready`. |
| Slice 01 | doc | ready | Codex r5 clean; Claude r2 clean; seal a3 clean | | Slice note sealed `ready`. |

## Current Slice

Slice 01 implementation after the sealed-note commit.

## Continuation

Commit the sealed Slice 01 note, then implement only the approved scope.
