# `need_rethink`: one explained problem, resolved in the repository

Status: non-canonical implementation intervention — operator decision
(2026-08-27).

## Problem

The milestone worker currently has to choose one `target_path` when it returns
`need_rethink`. The driver validates that path, uses it to classify the
Brainstorming as document or implementation work, presents it as the primary
target, and records it with the session.

That is the wrong abstraction for a rethink. A design contradiction may live
across the skeleton, one or more slice notes, code, tests, and existing project
contracts. Requiring one path makes the reporting worker arbitrarily reduce
the problem to one file. It can also select the wrong craft instructions merely
by choosing a document instead of a code path.

The repository-backed Brainstorming already delivers a committed Git range,
not one file. Its charge must therefore be the complete problem, not a worker-
selected artifact.

## Decision

Remove `target_path` from the milestone `need_rethink` contract end to end.

- The originating agent neither chooses nor returns a target path.
- The driver neither derives nor invents a replacement path.
- The driver opens Brainstorming from the complete `problem` plus the milestone
  context it already owns.
- The Brainstorming request, durable state, routed seat prompts, transcript,
  events, and handoff receive no `target_path` for a rethink.
- The Initial Position resolves the contradiction by editing whichever
  repository files the resolution requires. Contrary Position and Dante
  remain read-only and judge whether that repository state resolves it.
- The Brainstorming's terminal result is authoritative. Success continues the
  work that returned `need_rethink`; failure or no agreement stops the
  milestone for the operator.
- The driver does not independently prove that the resolution changed files or
  solved the problem. If the session changes the canonical slice plan, the
  existing plan-comparison and reconciliation path still handles that observed
  change.

Do not replace `target_path` with `target_paths`, a guessed path, a parsed path,
the skeleton path, the workspace root, or a synthetic target file. The
explained problem is the charge; Git is the delivery boundary.

## Meaning of `need_rethink`

For the worker, `need_rethink` is a non-completing result for this condition:

> A confirmed contradiction in the governing design prevents completion of
> this order, while the MANDATE itself remains workable.

It is not required merely because an editing call changes the skeleton or
another design document. An agent that is authorized to write may make an
ordinary evidence-backed design edit when its current order can resolve the
matter directly. `need_rethink` is for the point where the agent determines
that the current order should stop and the problem should be resolved through
Brainstorming.

Ordinary defects that the current prompt can handle through its normal success
route remain ordinary work. A broken or out-of-mandate operator requirement
remains `blocked`; Brainstorming does not acquire authority to change the
MANDATE.

## Worker prompt instructions

Every eligible assembled prompt must receive the decision before the output
shape. A bare schema is not an instruction. The adapter mounts this instruction
and its registered output-contract section after selecting the route; prompt
sets do not each own a copy of the `need_rethink` envelope.

### Shared instruction for every eligible kind

Use this wording in `draft_slice_note`, `implement`, `review_round`,
`delta_review`, and `fix_findings`:

> **NEED_RETHINK**
>
> Use `need_rethink` when a confirmed contradiction in the governing design
> prevents you from completing this order, while the MANDATE itself remains
> workable. In `problem`, explain what prevents completion and why, including
> the evidence needed to understand it. Do not propose a direction or claim
> completion.

The `need_rethink` section itself requires only `status` and `problem`.
The examples also contain `questions` because these prompts currently mount
that separate contract section. Any field explicitly required by another
mounted section remains required; this is not a global allow-list. `kind`,
`finding`, and `target_path` are specifically retired from `need_rethink` and
must not be accepted as extensions.

`problem` is written for the rethink; it is not a renamed copy of ordinary
work output. For example: `This project has no database access, but the
required persistence depends on it.`

### `draft_slice_note`

Append:

> If drafting the slice exposes this condition, return `need_rethink` instead
> of an artifact or slice-plan claim.

Output:

```json
{
  "status": "need_rethink",
  "problem": "<what prevents completion, why, and the supporting evidence>",
  "questions": [
    { "id": "<mounted question id>", "answer": "<answer with explanation>" }
  ]
}
```

### `implement`

Append:

> If implementation exposes this condition, return `need_rethink` instead of
> claiming files changed or an implementation cut.

Output:

```json
{
  "status": "need_rethink",
  "problem": "<what prevents completion, why, and the supporting evidence>",
  "questions": [
    { "id": "<mounted question id>", "answer": "<answer with explanation>" }
  ]
}
```

### `review_round`

Append:

> If one confirmed problem meets the `NEED_RETHINK` rule, return it through
> `need_rethink` and explain the actual obstacle in `problem`, instead of
> completing the review with a `findings` list. A problem that does not meet
> that rule remains an ordinary finding. You are report-only in either case.

Output:

```json
{
  "status": "need_rethink",
  "problem": "<what prevents completion, why, and the supporting evidence>",
  "questions": [
    { "id": "<mounted question id>", "answer": "<answer with explanation>" }
  ]
}
```

### `delta_review`

Use the same decision as `review_round`, applied only to a problem established
within the delta-review scope:

> If one confirmed in-scope problem meets the `NEED_RETHINK` rule, return it
> through `need_rethink` and explain the actual obstacle in `problem`, instead
> of completing the delta review with a `findings` list. A problem that does
> not meet that rule remains an ordinary finding. You are report-only in either
> case.

Output:

```json
{
  "status": "need_rethink",
  "problem": "<what prevents completion, why, and the supporting evidence>",
  "questions": [
    { "id": "<mounted question id>", "answer": "<answer with explanation>" }
  ]
}
```

### `fix_findings`

Append:

> If the queued work exposes the `NEED_RETHINK` condition, return
> `need_rethink` and explain the actual obstacle in `problem`. Do not copy a
> queued finding or give it a disposition in the same reply.

Output:

```json
{
  "status": "need_rethink",
  "problem": "<what prevents completion, why, and the supporting evidence>",
  "questions": [
    { "id": "<mounted question id>", "answer": "<answer with explanation>" }
  ]
}
```

### Kinds without this exit

`draft_skeleton` keeps no `need_rethink` exit: it owns the initial design, and
an impossible or contradictory MANDATE is `blocked` to the operator.
`reclassify`, `suite_checkpoint`, `merge_repair`, `discussion_turn`, and
`questioner_turn` also keep their existing contracts and do not gain this
exit.

## Brainstorming prompt

A rethink session receives no target field or target wording. Its task text is:

> **TASK**
>
> Resolve the problem below. Work directly in the project Git repository. Make
> whatever repository changes are necessary so the problem no longer prevents
> the work from continuing; clarifying the governing documentation may be the
> complete solution. Return `ready` only after the complete resolution is
> present in the repository.
>
> **PROBLEM**
>
> {{rethink_problem}}

Its sources are:

- the Brainstorming chat;
- the complete source problem;
- the current repository;
- the goal, skeleton, governing slice note, current unit artifact, operator
  amendments, and project context already known to the driver, when present.

The seat prompts must not say `target`, `target document`, `primary target`,
`target state`, or ask a participant to focus edits on one path. The Initial
Position edits the repository; the other seats inspect the same repository and
remain read-only. Readiness anchors to the accepted repository revision.

The driver selects document versus implementation craft from the originating
unit's existing route (`skeleton`/`slice_doc` versus `slice_impl`). It never
infers craft from the problem text or from a path. Review, delta-review, and
fixer origins use the same unit type that selected their original prompt.

## Runtime and contract cut

Implementation must make one coherent cut:

1. Define one runtime-owned registered `need_rethink` instruction and output
   section and inject it into every eligible assembled call. It requires
   `status` and non-empty textual `problem`; mounted questions and other
   contract sections keep their own independent requirements. Prompt sets may
   add their ordinary result sections but do not declare or override this
   branch. The driver obtains the origin kind from the call it dispatched,
   never from the reply. A modern `need_rethink` reply containing `kind`,
   `finding`, or `target_path` is invalid; there is no dual schema.
2. Remove every older rethink instruction, worker-output validator, and
   rendered contract still reachable by a new call. A selected prompt set that
   still mounts one of the retired rethink sections is incompatible with the
   route and follows the existing whole-rung fallback; the runtime neither
   rewrites that set nor combines both contracts. Retire the old finding-bearing
   `request + target_path + max_rounds` rethink envelope rather than leaving a
   second accepted stack. `finding` and `target_path` remain reserved retired
   fields on a `need_rethink` reply so surplus-field tolerance cannot silently
   accept them.
3. Remove report-finding validation, exact queued-finding matching, target
   validation, and target materialization from the milestone rethink origin
   adapter. Use the internally recorded origin kind and validate only non-empty
   textual `problem` plus fields required by the assembled contract. The
   machine does not judge the explanation's content or length.
4. Pass the exact `problem` string to the session as `rethink_problem`. Do not
   pass the triggering review finding, queued finding, finding id, severity,
   disposition, or finding list. Remove source-finding bookkeeping and
   finding-based rethink fallback/authorization; the ordinary fix queue remains
   unchanged until the fresh fixer call after a successful resolution.
5. Build stable references solely from the current milestone context. Evidence
   may naturally cite any paths, but the driver neither parses nor promotes
   those citations into control data.
6. Derive the rethink craft axis from the current unit type, not a file suffix.
7. Only after the session charge has been validated as both `rethink` and
   repository-backed, admit the session without `target_path`. That branch
   skips generic target-path validation, target materialization/parent
   creation, `target_identity`, target-in-use exclusion, and target cleanup.
   Standalone and producer Brainstorming sessions retain every one of those
   target-backed rules.
8. The rethink service record omits `target_path` and `target_identity`; its
   terminal result omits `target_ref`. Do not fill any of them with the
   workspace, skeleton, repository root, or another placeholder. Generic
   target-backed sessions retain those fields.
9. Remove target-specific values and wording from routed rethink seat calls.
   Repository authority is the current accepted Git revision; file presence is
   not session authority.
10. Remove `target_path` from rethink wait records, events, handoffs, failure
   routing, panel projections, and any modern target-authorization branch.
11. Preserve operational ownership without reintroducing a target: a live
    repository-scoped rethink conflicts with sync or another overlapping
    repository mutation by using the session's existing execution-context
    workspace. This is lifecycle ownership only; it is never shown to a seat as
    a target or used to narrow the problem.
12. The panel renders a repository-scoped rethink without a target card, target
    path, target content, or target-change label. It shows the accepted Git
    revision/range and the ordinary transcript/session information instead.
13. Treat the Brainstorming's terminal result as the decision. On success,
    dispatch the kind that returned `need_rethink` again from the beginning
    against the repository as it now stands. On failure or no agreement, stop
    the milestone for the operator. Do not add a second check for changed
    files, a non-empty diff, a new commit, or the semantic adequacy of the
    resolution; success at an unchanged Git revision is still success.
14. Preserve the existing repository checkpoint, per-turn commit when edits
    exist, read-only seat enforcement, Git-range seal when a range exists,
    canonical-plan observation for actual plan changes, reconciliation,
    fresh-origin rerun, accounting, and failure-to-operator behavior.

### Prompt-set activation

The cut is incomplete if code injects the new envelope while the stored
`default` still contains instructions or sections asking agents for the old
one. Remove those retired fragments from the adapted JSON corpus, built-in
seed, generated prompt captures, and the actual stored `default` used by the
deployment. Do not copy the new envelope into every prompt set: the runtime
mounts it after route selection. Do not rely on missing-only `ensure_default`
to rewrite an existing corpus. Activation is one explicit replacement of the
deployed `default`, not a runtime migration or compatibility reader.

A named prompt set remains usable when its selected route is compatible and
receives the same injected section. If it still mounts a retired rethink
fragment, route validation rejects that whole rung and the existing resolver
uses the updated `default`; it is not edited or translated. Already-dispatched
calls retain the prompt they received; calls after activation receive only the
problem-only contract.

No compatibility lane is added. New calls use the new prompt and contract;
the implementation does not translate, infer, or preserve an old target.

## Proof

Focused coverage must establish:

1. Every eligible assembled prompt receives the runtime-mounted instruction,
   explains when to use `need_rethink`, requires its own focused `problem`
   explanation, and exposes the problem-only base shape without explaining
   orchestration machinery.
2. No eligible prompt's `need_rethink` instruction/envelope, and no routed
   rethink seat prompt, contains `target_path` or equivalent single-file
   language. Legitimate target wording in the prompt's ordinary work route is
   unchanged.
3. Each eligible kind requires `status + problem`, also satisfies its
   separately mounted question/extension contracts, and rejects `kind`,
   `finding`, and `target_path`.
4. Fixer rethink accepts an independently written problem explanation, does not
   copy or disposition any queued finding, and leaves the queue unchanged for
   the fresh fixer call after resolution.
5. A document-unit and implementation-unit rethink receive their correct craft
   law without inspecting a path or parsing the problem.
6. A cross-file problem opens one repository-backed Brainstorming whose lead
   can change multiple files; when it does, the accepted result retains the
   exact committed range `A..B`.
7. Brainstorming success at either a changed or unchanged Git revision causes
   the originating kind to run fresh. Brainstorming failure or no agreement
   stops the milestone for the operator, with no independent driver judgment
   of the proposed resolution.
8. An actual skeleton change still invokes existing plan comparison and
   reconciliation before the originating kind runs fresh.
9. No-agreement and operational failures still stop with their existing
   operator-visible failure; they do not fabricate a target or retry as an
   ordinary worker success.
10. Repository-scoped rethink service records/results omit `target_path`,
   `target_identity`, and `target_ref`, while retaining the accepted Git
   revision and range.
11. Sync and other overlapping repository mutations remain blocked while a
    repository-scoped rethink is active, using the existing workspace context
    rather than a target field.
12. The panel renders an active and completed target-free rethink without
    dereferencing a target and shows its Git authority instead.
13. The stored `default` actually serves the new wording after activation and
    every eligible call receives the runtime-injected envelope. A compatible
    named set receives the same injection; a named set retaining a retired
    rethink section falls back as one whole rung and cannot silently serve the
    old request.
14. Target-backed standalone and producer Brainstorming behavior remains
    unchanged.

## Non-goals

- No universal parser or semantic validator for problem prose.
- No path extraction, path catalogue, target list, or inferred edit scope.
- No new authorization or write fence: existing role permissions remain the
  authority.
- No change to finding classification, severity, debt, or fixer disposition
  semantics.
- No redesign of standalone Brainstorming tasks that genuinely own a target.
- No backward-compatibility machinery for old `need_rethink` envelopes.
