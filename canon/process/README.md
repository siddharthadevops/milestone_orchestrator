# Development Process Canon

Status: common canon

This is the shared delivery process for implementation roadmaps. It is AI-led,
review-driven, and slice-by-slice. A consuming project pins this repository and
keeps live project state in its own `implementation/` tree.

## Authority Split

The canon owns process invariants:

- `milestone -> slice` hierarchy.
- one active slice at a time.
- documentation before implementation.
- CLI review convergence and double final seals.
- durable review logs and closure records.
- continuation from recorded local state, not chat memory.

The consuming project owns local state:

- strategic roadmap.
- milestone registry and active continuation.
- milestone work logs.
- `review-log.md` files.
- `closures/`.
- accepted debt and local mandates.

## Required Local Layout

```text
implementation/
  README.md
  roadmap.md
  local-context.md  # local constraints read by the canon; not process authority
  brainstorming/    # non-canonical tracked exploratory planning; may be empty
  _drafts/          # non-canonical implementation-intent guides; may be empty
  process/
    README.md          # local pointer to this canon, plus temporary deviations if any
    codex-review.md    # local pointer to this canon, plus temporary deviations if any
    review-log.md      # only for process-doc reviews
  milestones/
    README.md          # global local registry and active continuation
    <milestone>/
      README.md        # skeleton, work log, current slice, continuation rule
      review-log.md
      slices/
      closures/
  review-work/         # git-ignored mechanical review scratch evidence
```

## Hierarchy

- `milestone`: a meaningful functional outcome.
- `slice`: the smallest reviewable, approvable, and closeable delivery unit.

There is no block level. Keep slices narrow: one clear intent, one reviewable
surface, no unrelated scope.

Plan slices so the expected change diff aims to stay under about 500 changed
lines where practical. Generated, lockfile, and mechanical changes do not count
toward that aim. Do not split cohesive work artificially; if a slice is expected
to exceed the target, record the reason in the slice note.

## Reuse Gate

Before a skeleton, slice note, or implementation proposes new machinery, it must
first check existing project code, existing project contracts, pinned shared
dependencies, and already-approved platform surfaces. Prefer reuse, extension,
wrapping, parameterization, or documentation over parallel machinery.

The local context file records local constraints, not process authority.
Recorded temporary process deviations remain in `implementation/process/README.md` or `implementation/process/codex-review.md`.
Reuse Posture must explain how local context was applied when new machinery is
proposed.

The canon requires milestone skeletons, slice notes, consultations, and implementation decisions to apply local context support order or platform preference constraints before proposing new machinery.
The canon requires reviews to check local context support order or platform preference constraints when the reviewed artifact proposes new machinery.

Every skeleton and slice note must include a short `Reuse Posture` section:

- what was checked.
- what is reused or extended.
- why any new machinery is necessary.
- how the new path stays compatible with existing contracts.
- how local context was applied when new machinery is proposed.

## Non-Canonical Planning

`implementation/brainstorming/` holds tracked exploratory product or architecture
thinking. It is non-canonical planning context: not implementation authority,
not a canonical dependency, and not a replacement for a reviewed milestone or
slice artifact.

`implementation/_drafts/` holds non-canonical implementation-intent guides. A
guide may record direction, sequencing, and risks, but it does not authorize
implementation and does not override sealed artifacts.

A milestone or slice may use brainstorming or `_drafts` only as non-canonical
planning context unless its own reviewed artifact explicitly records how it
will **Adopt / Revise / Reject** the relevant decisions.

`implementation/review-work/` is git-ignored mechanical review scratch for
prompts, findings, seals, adjudications, and process-gate consultation outputs.
It must not hold durable architecture material or implementation guide material.

## Cycle

1. **Milestone skeleton.** Create the milestone `README.md`, `slices/`,
   `closures/`, and `review-log.md`. Skeletons name planned slices, rough slice
   intent, shared contracts, and continuation state. They do not contain slice
   scope, files, tests, risks, or acceptance detail. Do not draft slice notes
   during skeleton work. Review the skeleton until sealed `ready`. Commit the
   sealed skeleton before slice work begins.
2. **Slice documentation.** Draft the slice note: scope, non-goals, expected
   files, dependencies, acceptance criteria, tests, risks, and reuse posture.
   Unopened slice notes are drafted only after the skeleton is sealed `ready`
   and committed. Review until sealed `ready`. Commit the sealed slice note
   before production code begins.
3. **Slice implementation.** Implement only the approved scope. Verify with
   local/focused checks as the artifact changes, run the full official
   verification suite before review, commit the implementation, review through
   the CLI convergence loop until sealed `review_clean`, write the closure,
   update logs, then commit bookkeeping separately.

Work one slice to closure before opening the next. A blocked slice remains the
current slice until it is resolved or explicitly deferred in local state.

## Reviews

Reviews are run by the orchestrator, not supplied by the operator. Use
[`codex-review.md`](codex-review.md) for the common evidence contract.

Each phase uses the review/seal convergence loop in
[`codex-review.md`](codex-review.md):

- run local/focused checks after each artifact modification when they are cheap
  or directly relevant.
- run the full official verification suite recorded in local state before
  normal review begins.
- run normal Codex CLI review rounds until Codex is clean.
- record the normal Codex clean state in the durable review log.
- run normal Claude CLI review rounds until Claude is clean.
- record the normal Claude clean state in the durable review log.
- run the full official verification suite again.
- run full double-seal rounds until clean on an unchanged artifact.

The seal phase may not open until the review log records the normal Codex clean
state followed by the normal Claude clean state for the current artifact phase.
After normal Claude review begins, do not return to normal Codex review for
Claude-driven fixes unless the operator explicitly resets the phase or the fix
substantially changes scope or design. Codex reviews the final post-Claude
artifact as the Codex half of the seal.

Triage every finding as fixed, rejected with rationale, operator-accepted debt,
or blocked for the operator.

`P0` and `P1` findings cannot become debt. `P2` and `P3` debt requires explicit
operator acceptance and must be recorded in local state.

### Seal Findings

A seal finding is still a claim, not a fact. If a seal round finds a valid
issue, verify it against local files, diffs, tests, or commands; fix it; run
relevant local/focused checks; then repeat the full seal round only.

Do not return to normal review rounds after a seal finding unless the fix
substantially changes scope or design. If the full official verification suite
after normal review fails, fix it and restart from the pre-review full
verification step.

### Double Seal

The double final seal uses two independent reviewers on the same unchanged
artifact. Codex remains the mandatory Codex seal half. Claude CLI is the
required non-Codex seal half when Codex is the worker/orchestrator. The other
seal half must run in a fresh independent context, not the thread or agent that
drafted or implemented the artifact.

Both seal halves receive the same review prompt; neither reviewer may see the other half's output.
Share outputs only after both seal halves have completed.

Launch both seal halves concurrently when both required reviewers are available
and the runner can preserve no-peek independence. When a seal is not concurrent,
record the reason. Sequential launch still preserves the same unchanged
artifact, same prompt, and no shared outputs until both halves complete.

When Codex is the worker/orchestrator, the non-Codex seal half must run through
Claude CLI with the command shape in `codex-review.md`. Record the Claude CLI
reviewer, model/settings, command surface, result, and `EXIT=` in the durable
review log.

If the required Claude CLI seal half is unavailable, the seal remains incomplete
unless the operator explicitly authorizes a fallback for that seal attempt.
Fallback authorization mechanics, independence constraints, record fields, and
usable-output evidence live in `codex-review.md`.

### Finding Verification

The rule is simple: reviewer findings are claims, not facts.
The orchestrator owns triage.
Evidence must come from files, diffs, tests, or commands.
Verify every finding before deciding whether it is fixed, rejected, accepted
debt, or blocked for the operator.

Do not triage from memory or chat, and do not treat prior review output as
authority. A prior finding may identify what to inspect, but the decision must
come from the current artifact and direct evidence.

For each finding, record the outcome in the durable review log:

- `fixed`: the finding was valid and corrected, then re-reviewed.
- `rejected`: the finding was invalid, out of scope, or contradicted by the
  reviewed artifact/canon, after the disagreement protocol below.
- `accepted debt`: only `P2`/`P3`, only with explicit operator acceptance.
- `blocked/operator`: the orchestrator cannot resolve the issue under the
  process rules.

### Consultation And Adjudication

The orchestrator adjudicates; reviewers and consulted LLMs do not. When the
orchestrator has a doubt or disagrees with a finding, it must open one
continuous CLI dialogue session with the opposite LLM family when one is
available. If Codex is the orchestrator, use Claude CLI; if Claude is the
orchestrator, use Codex CLI.

Do not start separate consultations per round for the same conceptual issue.
Run at most two dialogue rounds, stopping earlier if agreement is clear.

The consultation/adjudication prompt must include the artifact, the finding or
doubt, the orchestrator's proposed resolution, and the files, diffs, tests, or
commands already checked. The orchestrator then makes the triage decision.

If the opposite CLI family is unavailable, or if the dialogue does not leave a
clear resolution, stop and consult the operator. Do not reject a `P0` or `P1`
finding by orchestrator-only judgment, and never turn `P0`/`P1` into debt.

Consultation and adjudication rounds are evidence, not review rounds. Record
their result in the durable review log and keep any scratch output under
`implementation/review-work/`.

## Reopen Rule

A seal covers an unchanged artifact. A later substantive change to sealed
documentation reopens documentation review. A later substantive change to
sealed implementation reopens implementation review.

Bookkeeping updates do not reopen a phase unless they alter reviewed process
rules or artifact substance.

## End-To-End Mandates

A project may record an end-to-end mandate in local state. The mandate allows
the orchestrator to continue through normal gates without pausing for operator
approval between sealed units.

The mandate does not weaken gates. Skeletons still seal before slice notes,
slice notes still seal before implementation, implementation still verifies
before review, and closures still record the sealed outcome.

Push mandates are local state. Never push unsealed work, unresolved review
states, unrelated local changes, or commits outside the recorded mandate.

## Documentation Discipline

Documentation artifacts are contracts for implementation and review. Keep them
short and executable:

- boundary.
- canonical basis.
- reuse posture.
- scope and non-goals.
- acceptance criteria.
- tests and risks.
- current continuation state.

Durable review logs summarize review state, phase-gate clean states, findings,
triage, seal outcomes, and accepted debt. A phase-gate clean-state entry records
the reviewer family, run id or output path, `EXIT=0`, `VERDICT: 0`, and the
reviewed artifact or ref. Full prompts and reviewer output stay in git-ignored
`implementation/review-work/`.

Skeletons are planning contracts, not slice notes. They keep rough slice intent
and shared invariants, then leave scope, files, tests, risks, and acceptance
detail to the just-in-time slice note.

Avoid pseudo-code, defensive FAQs, repetition, and future milestone chains. If a
document starts specifying control flow that belongs in code, reduce it to
observable contracts, invariants, and tests.

### Altitude Rule

Documentation scope states observable contracts, invariants, and the tests
that pin them. Mechanism — internal names, call ordering, state enumeration,
control flow — belongs to implementation.

The operational test: a statement that can be falsified only by reading the
implementation diff, and not by observing behavior or running a named test,
is mechanism. Reduce it to the contract it protects.

Mechanism-level detail is allowed only where it pins a named public or
cross-slice contract — a signature, an error vocabulary, a seam another slice
or consumer depends on. The artifact must name that pinned contract.

Fix documentation findings at altitude: a valid finding about unspecified
behavior is fixed by recording the observable contract, invariant, or test,
not the mechanism that produces it.

In documentation phases, reducing over-specified mechanism to its unchanged
contract is not a substantial scope or design change: the contract is
unchanged, only its expression compresses. A reduction fix stays in its
current review phase and, during seals, follows the seal-finding rule.
