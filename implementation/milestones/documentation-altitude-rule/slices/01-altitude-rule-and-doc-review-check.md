# Slice 01 - Altitude Rule, Doc-Review Altitude Check, And Template Guardrail

Status: ready - documentation sealed.

Reviewed against the sealed S7 skeleton ([`../README.md`](../README.md)).

## Scope

- Common process, Documentation Discipline: name the altitude rule.
  Documentation scope states observable contracts, invariants, and the tests
  that pin them; mechanism belongs to implementation. The rule carries:
  - the falsifiability test: a statement falsifiable only by reading the
    implementation diff, not by observing behavior or running a named test,
    is mechanism and is reduced to the contract it protects;
  - the pinned-contract exception: mechanism-level detail is allowed only
    where it pins a named public or cross-slice contract, and the artifact
    names that contract;
  - the fix direction: a valid documentation finding about unspecified
    behavior is fixed by recording the observable contract, invariant, or
    test, not the mechanism that produces it;
  - the reduction guard: reducing over-specified mechanism to its unchanged
    contract is not a substantial scope or design change; a reduction fix
    stays in its current review phase and follows the seal-finding rule
    during seals.
- Review runner, Prompt Shape: documentation-phase prompts (skeleton, slice
  documentation, process-doc) require the altitude check in both directions —
  under-specified contracts and over-specified mechanism are both findings —
  with over-specified mechanism `P3` by default and `P2` when acceptance
  criteria or tests anchor to mechanism instead of observable behavior.
- Review runner, Review/Seal Convergence: state the reduction guard alongside
  the existing substantially-changes-scope-or-design clauses, explicitly
  scoped to documentation phases (the shared section also governs
  implementation-phase seals, which this slice leaves untouched).
- Slice template: the `Scope` section carries the altitude guardrail inline.

## Non-Goals

- No slice risk classes or review-depth proportionality (operator-rejected).
- No change to implementation-phase review rules, double-seal independence,
  unchanged-artifact seal rules, worktree snapshots, no-edit prompts, or
  quota rules.
- No automation or line-count enforcement.
- No rewrite of historical milestone documentation or sealed artifacts.

## Reuse Posture

- Checked: the Documentation Discipline no-pseudo-code paragraph, the Prompt
  Shape checklist, the scope/design re-entry clauses in Seal Findings and
  Review/Seal Convergence, and the slice template `Scope` section.
- Reused or extended: the existing severity ladder, finding/triage machinery,
  and seal-finding rule; the altitude rule extends the no-pseudo-code
  paragraph in place.
- New machinery, if any: none; process wording and template guidance only.
- Compatibility: consumers keep the same layout, runners, and commands; the
  new finding direction is scoped to documentation phases, so implementation
  reviews see no new finding class.
- Local context: this product-neutral canon repo records no support order and
  no sensitive local exclusions.

## Non-Canonical Planning

- Named planning material: Agent99 M28 documentation drift discussed with the
  operator.
- Adopt / Revise / Reject: per the sealed skeleton — adopt the altitude rule,
  the bidirectional documentation review check, and the reduction guard;
  reject slice risk classes, proportional review depth, and product-specific
  wording.

## Dependencies

- Milestone skeleton sealed and committed: `39992db`.
- Prior reviewed release: `v0.7.0`.

## Slice Size

Expected change is small, well under the 500 changed-line target.

## Expected Files

- `canon/process/README.md`
- `canon/process/codex-review.md`
- `templates/local-state/implementation/milestones/_milestone/slices/01-slice.md`
- Milestone README, review log, global registry, roadmap, `VERSION`, and the
  root `README.md` pin example; closure files at close.

## Acceptance Criteria

1. Documentation Discipline states the altitude rule with the falsifiability
   test, the pinned-contract exception, the fix direction, and the reduction
   guard.
2. The review runner also states the reduction guard in its shared
   convergence section, naming documentation phases explicitly.
3. The review runner Prompt Shape requires the bidirectional altitude check
   for skeleton, slice documentation, and process-doc phases only, with the
   severity guidance (`P3` default; `P2` when acceptance criteria or tests
   anchor to mechanism).
4. The slice template `Scope` section carries the guardrail.
5. Implementation-phase review rules are textually unchanged (diff-verified);
   the additions to shared sections are exactly two, both
   documentation-phase-scoped — the Prompt Shape altitude bullet and the
   convergence reduction guard; and the wording stays product-neutral.

## Tests

- `git diff --check`
- Diff inspection against acceptance criterion 5.

## Risks

- **Altitude findings leaking into implementation reviews.** Mitigation: the
  Prompt Shape bullet names the documentation phases explicitly.
- **Reduction guard misused to dodge genuine scope changes.** Mitigation: the
  guard applies only while every contract, acceptance criterion, and test is
  unchanged; any fix that changes one stays substantive under the existing
  rules.
- **Over-reduction of genuinely needed contracts.** Mitigation: the check is
  bidirectional; under-specified contracts remain findings of equal standing.

## Review

This slice note must seal `ready` before implementation begins.
