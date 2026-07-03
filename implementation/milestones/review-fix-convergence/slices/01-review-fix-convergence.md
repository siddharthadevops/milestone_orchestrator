# Slice 01 - Batched Fixes, Pre-Relaunch Self-Review, Exhaustive Prompts, And Evidence Fields

Status: ready - documentation sealed.

Reviewed against the sealed S8 skeleton ([`../README.md`](../README.md)).

## Scope

- Common process and review runner: preserve existing triage outcomes, and
  require findings triaged as fixed from one review round to be corrected in
  one whole-artifact pass before the reviewer is relaunched.
- Common process and review runner: require a pre-relaunch self-review of the
  pending diff that checks finding coverage, phase-rule compliance, and stale
  surrounding surfaces. The self-review is orchestration only, not a review
  round or substitute for reviewer convergence, and is recorded as one line in
  the round's existing fix entry.
- Review runner Prompt Shape: require this sentence in every review prompt:
  "Do not stop at the first finding: report every defect you can verify in a complete pass of the artifact and the code it cites. An exhaustive pass with zero findings is a valid outcome."
- Milestone review-log template: pre-print minimal evidence fields for normal
  clean states and seal halves, including seal-half worktree validity.

## Non-Goals

- No change to gates, seal counts, seal independence, no-edit prompts,
  worktree checks, or the `VERDICT: 0` convergence criterion.
- No change to accepted-debt or blocked/operator triage outcomes.
- No review evidence is produced by the orchestrator self-review, and it
  cannot replace normal review or seal rounds.
- No automation, scripts, or command-runner behavior changes; process, prompt,
  and template wording only.
- No consuming repository repins.

## Reuse Posture

- Checked: Reviews, Finding Verification, Review/Seal Convergence, Prompt
  Shape, Documentation Discipline, and the milestone review-log template.
- Reused or extended: existing reviewer order, finding triage, verification
  bracketing, durable review-log evidence, and double-seal metadata.
- New machinery, if any: none; textual process rules and template fields only.
- Compatibility: consumers keep the same runner commands, gates, seal
  independence, worktree snapshots, and closure requirements.
- Local context: this product-neutral canon repo records no support order and
  no sensitive local exclusions.

## Non-Canonical Planning

- Named planning material: Agent99 M28 Slice 04 documentation-phase review
  tail; LPC M34 skeleton convergence; Life M163 review lanes; operator
  pre-automation self-review practice.
- Adopt / Revise / Reject: adopt batched fixes, pre-relaunch self-review,
  reviewer exhaustiveness, and pre-printed evidence fields; reject
  severity-based early exit from normal rounds, slice risk classes,
  proportional review depth, and automation/tooling.
- Notes: planning material names evidence only; canon wording stays
  product-neutral.

## Dependencies

- Milestone skeleton sealed and committed: `98c17f5`.
- Prior reviewed release: `v0.8.0`.

## Slice Size

Expected change is small, well under the 500 changed-line target.

## Expected Files

- `canon/process/README.md`
- `canon/process/codex-review.md`
- `templates/local-state/implementation/milestones/_milestone/review-log.md`
- Milestone README and review log; closure and release bookkeeping at close.

## Acceptance Criteria

1. The process canon and review runner preserve existing triage outcomes and
   require one batched whole-artifact fix pass for findings triaged as fixed
   from a review round before relaunching that reviewer.
2. The process canon and review runner require pre-relaunch self-review of the
   pending diff for finding coverage, phase-rule compliance, and stale
   surrounding surfaces; define it as orchestration rather than review
   evidence; and require the one-line self-review record inside the round's
   existing fix entry.
3. Prompt Shape requires the reviewer-exhaustiveness sentence verbatim.
4. The milestone review-log template pre-prints clean-state and seal-half
   evidence fields: reviewer family, run id or output path, `EXIT`,
   `VERDICT`, reviewed artifact/ref; seal halves additionally include
   model/settings, command surface, and worktree invalidation status.
5. Gate behavior is textually unchanged: reviewer rounds still converge to
   `VERDICT: 0`, double seal and independence rules remain intact, and
   worktree/no-edit requirements are not weakened.

## Tests

- `git diff --check`
- Diff inspection against acceptance criteria 1-5.

## Risks

- **Self-review mistaken for a new gate or reviewer round.** Mitigation: scope
  and acceptance require it to be orchestration only.
- **Template fields becoming prose-heavy.** Mitigation: acceptance pins fields,
  not explanatory text.
- **Exhaustiveness wording changing prompt meaning.** Mitigation: acceptance
  requires the exact sentence.

## Review

This slice note must seal `ready` before implementation begins.
