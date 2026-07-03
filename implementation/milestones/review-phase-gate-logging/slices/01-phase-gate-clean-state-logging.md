# Slice 01 - Phase-Gate Clean-State Logging

Status: ready - documentation sealed.

## Scope

- Require durable review logs to record normal Codex clean and normal Claude
  clean as explicit phase-gate states before seal opens.
- Clarify that once normal Claude review begins, Claude-driven fixes continue in
  the Claude normal-review phase; normal Codex review reopens only on explicit
  operator reset or a substantial scope/design change.
- Update the milestone review-log template so new milestones record these clean
  gates with enough evidence to prevent drift.

## Non-Goals

- No automation, runner script, or parser change.
- No weakening of double-seal independence, unchanged-artifact seal rules,
  worktree snapshots, no-edit prompts, or Claude CLI requirements.
- No product-specific wording in the canon.
- No rewrite of historical milestone logs.

## Reuse Posture

- Checked: S5 convergence formula, durable review-log description, seal finding
  loop rules, and the milestone review-log template.
- Reused or extended: existing review families, durable review logs, seal phase,
  and template-local guidance.
- New machinery, if any: no tooling; wording only.
- Compatibility: existing repositories can adopt this at the next canon pin
  without changing review scratch layout or commands.
- Local context: this product-neutral canon repo records no support order and no
  sensitive local exclusions.

## Non-Canonical Planning

- Named planning material: Agent99 M28 process drift discussed by the operator.
- Adopt / Revise / Reject: adopt the reusable phase-gate logging requirement and
  Claude-phase no-drift-back rule; reject Agent99-specific details.
- Notes: this slice clarifies S5; it does not reopen S5's reviewed release.

## Dependencies

- Milestone skeleton sealed and committed: `17f7525`.
- Prior reviewed release: `v0.6.0`.

## Slice Size

Expected change is small, under the 500 changed-line target.

## Expected Files

- `canon/process/README.md`
- `canon/process/codex-review.md`
- `templates/local-state/implementation/milestones/_milestone/review-log.md`
- `implementation/milestones/review-phase-gate-logging/README.md`
- `implementation/milestones/review-phase-gate-logging/review-log.md`
- `implementation/milestones/README.md`
- `implementation/roadmap.md`
- Slice closure files at close.

## Acceptance Criteria

1. The common process says seal cannot open until the durable review log records
   normal Codex clean followed by normal Claude clean for the current artifact
   phase.
2. The review runner gives the same gate as an ordered checklist with the fields
   required for each clean-state entry.
3. The review runner says Claude-driven normal-review fixes stay in the Claude
   phase, with only operator reset or substantial scope/design change reopening
   normal Codex review.
4. The milestone review-log template asks new milestones to record these clean
   gates before seal.
5. The wording remains product-neutral and preserves existing seal evidence.

## Tests

- `git diff --check`

## Risks

- **Over-constraining legitimate resets.** Mitigation: keep explicit operator
  reset and substantial scope/design change as the two normal-Codex re-entry
  paths.
- **Bookkeeping churn.** Mitigation: require only phase-gate clean-state entries,
  not a new phase wrapper for every review round.

## Review

This slice note sealed `ready` and must be committed before implementation
begins.
