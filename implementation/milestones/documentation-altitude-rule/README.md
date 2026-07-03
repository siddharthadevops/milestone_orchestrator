# Documentation Altitude Rule

Status: open.

Planned reviewed release: `v0.8.0`.

## Boundary

S7 hardens the existing no-pseudo-code documentation discipline into an
enforceable altitude rule, self-enforcing against drift in both the author and
the reviewer direction.

## Canonical Basis

- Common process: [`../../../canon/process/README.md`](../../../canon/process/README.md)
- Review runner: [`../../../canon/process/codex-review.md`](../../../canon/process/codex-review.md)
- Local context: [`../../local-context.md`](../../local-context.md)
- Local templates: [`../../../templates/local-state/implementation/milestones/_milestone/slices/01-slice.md`](../../../templates/local-state/implementation/milestones/_milestone/slices/01-slice.md)
- Prior reviewed release: `v0.7.0`

## Reuse Posture

- Checked: the Documentation Discipline section and its existing no-pseudo-code
  paragraph, the S4 thin-skeleton and just-in-time slice-note rules, the review
  runner Prompt Shape checklist and review/seal convergence loop, and the slice
  template `Scope` section.
- Reused or extended: the existing finding/severity/triage machinery, the
  existing seal-finding rule, and existing template guidance; the altitude rule
  extends the current no-pseudo-code paragraph in place.
- New machinery, if any: none; process wording and template guidance only.
- Compatibility: consumers keep the same layout, runners, and commands; the new
  finding direction applies only to documentation phases.
- Local context: this product-neutral canon repo records no support order and
  no sensitive local exclusions.

## Shared Contract

Documentation scope states observable contracts, invariants, and the tests
that pin them; mechanism belongs to implementation unless it pins a named
public or cross-slice contract. Documentation-phase reviews report both
under-specified contracts and over-specified mechanism as findings. Reducing
over-specified mechanism to its unchanged contract is not a substantial scope
or design change. Implementation-phase review rules are untouched.

## Non-Canonical Planning

- Named planning material: Agent99 M28 documentation drift (mechanism-level
  slice notes and long P3 seal tails) discussed with the operator.
- Adopt / Revise / Reject: adopt the reusable altitude rule, the bidirectional
  documentation review check, and the reduction guard; reject slice risk
  classes and proportional review depth (operator decision); reject
  Agent99-specific milestone names, findings, or product behavior in canon
  wording.

## Slices

| Slice | Title | Status | Notes |
|---|---|---|---|
| 01 | Altitude rule, doc-review altitude check, and template guardrail | planned | Publishes reviewed release `v0.8.0`. |

## Work Log

| Unit | Phase | Status | Review | Commit | Notes |
|---|---|---|---|---|---|
| Skeleton | doc | ready | Codex r1 clean; Claude r6 clean; seal a3 clean | | Skeleton sealed `ready`; Slice 01 not drafted. |

## Current Slice

None open. Slice 01 is drafted only after this skeleton seals `ready` and is
committed.

## Continuation

Read the global milestone index, then this README and its latest work-log
entry, and continue from the recorded state.
