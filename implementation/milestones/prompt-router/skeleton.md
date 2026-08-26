# Milestone skeleton — Prompt Router and session overhaul

Mandate: the frozen launch snapshot `implementation/milestones/prompt-router/goal.md`,
as updated for this run by accepted design amendment B1. This is a thin planning
contract; slice notes pin each bounded surface just before implementation.

## Register 1 — Intent (lay language)

### Goal restatement

The operator and every orchestrated worker should receive one prompt assembled
for the work actually being done, instead of a large prompt assembled by many
call sites. A named, editable prompt set supplies the wording; one router selects
the work instructions, discussion-role instructions, questions, and reply
contract. A completed edit is visible to the next call without prompt versions,
snapshots, migrations, or coordination ceremonies.

The same project repository is the place where every worker and Brainstorming
seat does its work. Discussion readiness is anchored to repository revisions;
there is no separate proposal area or later application call.

The skeleton carries the sole slice plan in one canonical JSON block. Physical
calls and Brainstorming seats may change that block through their ordinary
repository edits; no route, flag, state field, panel action, or reply field
grants plan authority. Valid changes are anchored, projected into run state,
reviewed, and, when they disturb built history, recovered through the existing
block-derived account and one LLM-owned structural-repair handoff.

### Ownership and boundaries

Owned here: prompt-set storage and resolution, assembled prompt service,
registered reply validation, run prompt-set binding, milestone and Brainstorming
consumer cutover, the canonical-plan block boundary and projection,
repository-backed session agreement, plan diff and frozen reconciliation, the
complete-suite checkpoint, prompt traces, activation compatibility, and
conformance tests.

Not owned here:

- prompt versions, caches, edit notifications, or prompt migration bookkeeping;
- a material catalogue or real material-specific prompt layer;
- a new staffing role, model/effort routing, rigor rule, or permission system;
- a non-agent plan writer, plan mutation API, planning discriminator, reply
  `slices` transport, Markdown parser, or dual plan authority;
- an embedded Git implementation; every task is assumed to have system Git;
- Brainstorming execution for reviews, fixes, ratings, or suite checkpoints;
- migration of pre-activation runs into the new schema.

The panel may show projected plan state and select the prompt set, but it does
not mutate producers or materials. No worker invokes another LLM; all model
calls, including finding classification, are dispatched by the driver. Prompt
prose is trusted authoring content; code enforces registered reply obligations
and structural boundaries, not whether the prose means what its author intended.

### Planning-context disposition

**Adopts** accepted amendment B1 and the adapted corpus as its conversion source.
**Revises** the corpus and original goal where B1 explicitly retires plan
controls, optional producer planning, reply `slices`, split rethink routes, and
legacy resume. **Uses** older analysis and captures only as historical evidence.

### Guarantee posture

- **Strict per router-served physical call:** before dispatch, resolution selects
  one complete readable rung, rejects missing required job payloads, assembles
  applicable variables, and records the exact prompt. Accepted replies validate
  exactly the registered mounted or appended sections and all mounted question
  answers. There is no worker-owned model-call exception.
- **Strict canonical plan boundary:** exactly one `## Canonical slice plan`
  heading and its immediately following fenced JSON object are authoritative.
  The first valid block establishes the anchor and immediately refreshes the
  projected run plan before producer selection or work ordering.
  Before dispatch, the block must match the last validated anchor unless an
  accepted-range reconciliation is open; other drift blocks to the operator
  without re-baselining or automatic restoration. A proportional pre-call
  snapshot of governed Git-visible work-tree bytes under existing exclusions,
  the index tree, HEAD identity/tip, and the canonical anchor defines rollback.
  Unrelated refs, reflogs, stash, and other Git plumbing are outside the
  guarantee. After every physical call or seat turn, a source-neutral observer
  compares the block with the anchor. Unchanged bytes keep the anchor without
  revalidation; valid changes follow the ordinary plan path. Invalid changes by
  editing calls, seats, or suite checkpoints restore their declared snapshot;
  invalid changes by trusted report-only judgments instead enter terminal
  failure without judgment-specific restoration. `draft_skeleton` is accepted
  only with a valid block. Later valid changes refresh the projected run plan
  before plan diff, producer selection, or work ordering.
- **Strict read-only seat and suite boundaries with one plan exception:**
  ordinary mutation by a read-only seat or suite checkpoint is rejected and
  restored. If that actor produced a valid canonical-plan change, only that
  block is reinserted and committed; every other mutation is discarded, and its
  readiness or checkpoint result does not count. A later unchanged seat turn or
  checkpoint is required.
- **Trusted report-only judgments:** `review_round`, `delta_review`, and
  `reclassify` prompts require an unchanged work tree, index, and HEAD, and that
  instruction is trusted. Apart from source-neutral canonical-block observation,
  the driver does not police or restore their mutations, isolate a changed block,
  invalidate an otherwise valid judgment because bytes changed, or rerun for
  that reason. An unchanged block consumes the judgment; one valid change follows
  the ordinary plan path; an invalid change enters terminal failure before result
  adoption without judgment-specific restoration, correction, or retry.
- **Strict repository transitions:** explicit revisions anchor committed editing
  turns, readiness, delta review, canonical-plan state, accepted direct-call
  ranges, wipe boundaries, and reconciliation. A direct plan-changing call's
  accepted range contains only its committed pre-call to surviving post-call
  delta and leaves HEAD at `accepted_revision`. Only a computed wipe boundary
  opens reconciliation: its original old plan/run boundaries, source range, and
  opening account are persisted and scheduling freezes. The driver performs no
  repository surgery and durably marks one `merge_repair` handoff from
  `accepted_revision`; the LLM owns the run-owned surgery and final same-branch
  commit. The final account is recomputed from the persisted original boundaries
  and replaces the opening account without a second repair. Finite revision and
  clean-state checks close reconciliation atomically without repository edits;
  an interruption, blocked result, unsupported history, or failed check leaves
  the frozen LLM-left state for manual recovery or restart.
- **Strict checkpoint gate:** a failed suite checkpoint cannot be deferred or
  reclassified; no seal passes until a fresh unchanged attempt returns `passed`
  or `no_suite`.
- **Best-effort prompt edit visibility, strict whole-set fallback:** each dispatch
  reads prompt files afresh. A complete same-rung combination may be assembled
  even if concurrent saves never exposed it atomically; an unreadable combination
  falls as one rung and reports that fall beside the answer. A dispatched prompt
  is fixed, and cross-call prompt content has no consistency, monotonicity, or
  convergence guarantee.

### Reuse Posture

Operators and workers bear wrong instructions, rejected outputs, lost review
time, and incorrect recovery work; repository bytes are reversible, spent calls
are not. Reused are the binding corpus, staffing's fresh whole-rung resolution,
task charges, validators, exact prompt traces, proportional Git
capture/restore/commit
primitives, review seals, and suite cadence. B1 also reuses the skeleton itself
as the plan document and existing run state only as a projection. Trusted
report-only judgments reuse only the source-neutral block observer and add no
mutation-policing or restoration machinery. The cheapest sufficient design is
one prompt router plus exact canonical-block extraction and Git anchoring; a new
planning discriminator, mutation service, parser, fallback, migration, or
second store has no authorised consumer. The driver,
Brainstorming coordinator, service/panel projection, and worker runner consume
the remaining machinery. Build and review cost is bounded; runtime adds fresh
document reads and existing Git operations, without a daemon or dual authority.

## Canonical slice plan
```json
{"slices":[
  {"id":1,"title":"Prompt-set store and seed fallback","intent":"Store the shipped corpus as default; validate and resolve one fresh whole set through named, stored-default, and in-code-seed rungs without mixing, repair, or hidden fallback.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":2,"title":"Charge resolver and assembled JSON","intent":"Convert the canonical-plan prompt corpus, generated seed, and goldens; retire optional producer planning and reply slices; resolve canonical charges into one inlined JSON prompt with material layering and declared substitutions.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":3,"title":"Registered contracts, QUESTIONS, and plan boundary","intent":"Register reply contracts and mounted question answers; extract, validate, anchor, and project the canonical plan; block unexplained pre-dispatch drift before any consumer cutover.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":4,"title":"Prompt-set binding and operator surface","intent":"Bind a named prompt set at launch, expose prompt-set selection and read-only plan projection, and keep absent legacy binding on default until activation retires legacy runs.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":5,"title":"Milestone author-call cutover","intent":"Serve skeleton, slice-note, and implementation author calls through the router and canonical-plan boundary; remove producer/material mutation controls and author reply-plan transport in the same cut.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":6,"title":"Milestone judgment-call cutover","intent":"Serve review, delta review, fixing, and driver-owned rating through their canonical jobs and plan boundary; prohibit worker-initiated model calls, classify eligible findings from both full and delta reviews, and retire judgment reply-plan transport.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":7,"title":"Session charge and seat composition","intent":"Admit only planned producer sessions and the single orchestrator-opened rethink session; compose author, contrary, and questioner turns from tagged job law and seat coordinates with applicable QUESTIONS.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":8,"title":"Repository-backed session turns","intent":"Run sessions in the project repository, commit editing turns, restore ordinary read-only mutations, and preserve only a valid canonical-plan block change under the narrow read-only exception.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":9,"title":"Anchored readiness and session seal","intent":"Close when discussion seats are ready on one current commit, invalidate readiness after any new commit, derive delivery from Git, and apply nothing at close.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":10,"title":"Plan identity and wipe boundary","intent":"Derive plan changes only from anchored canonical blocks; compute a wipe boundary; persist the original old plan and run boundaries, source range, and opening wipe, requeue, and checkpoint account; then freeze scheduling.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":11,"title":"Accepted-range reconciliation","intent":"From accepted_revision, hand off the sole merge_repair attempt; validate its clean same-branch linear result; recompute the final account from the persisted original boundaries; and close atomically without driver repository edits.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":12,"title":"Read-only suite checkpoint","intent":"Run configured or evidence-discovered complete suites once in a read-only agent call, restore ordinary mutation, preserve a valid block-only plan edit, and require a fresh unchanged rerun.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":13,"title":"Checkpoint cadence, failure, and activation","intent":"Schedule checkpoints every four completed logical slices and at close, repair non-deferrable failures, invalidate unwound anchors, and refuse pre-activation run schemas after the drained cutover.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":14,"title":"Legacy retirement and end-to-end conformance","intent":"Remove parallel prompt, plan-control, reply-plan, compatibility, and write-fence lanes; prove every physical call and canonical-plan boundary; bump the schema only after all cutovers and a driver drain.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}}
]}
```

## Register 2 — Pinned facts (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Routing identity | The prompt routing key is `(job, executor, material)`; callers pass one canonical `kind@unit` job id whole, and session dispatch also supplies `(role, lead)`. Brainstorming supports the two producer jobs plus one orchestrator-opened `rethink` session carrying its finding, evidence, target, and ordinary context; `rethink@doc` and `rethink@impl` are retired. For `rethink` only, the originating target also supplies a required artifact type (`document` or `implementation`) that mounts the existing target-type craft units without changing the job id or granting edit or plan authority. | accepted amendment B1; `goal.md:133-148` | touch one router, the existing target-type slots, and call adapters; do-not-add planning coordinates, caller-selected target types, raw options, or fragment selectors |
| Canonical plan | This file contains exactly one canonical-plan heading and one immediately following fenced JSON object rooted `{"slices":[...]}`. Each array item has exactly `id`, `title`, `intent`, optional `material`, and `producer_task_executor` with exactly the two accepted executor ids and no configuration. Array order is delivery. Dispatch supplies configuration outside the plan and writes its job role last. | accepted amendment B1; this skeleton, `Canonical slice plan` | touch this block through ordinary repository edits; do-not-add a duplicate plan, defaulted producer, configuration, parser, or parallel authority |
| Plan boundary and projection | The first valid block establishes the Git anchor and immediately refreshes run state; `draft_skeleton` is accepted only when it validates. Later pre-dispatch bytes must match the anchor except during accepted-range reconciliation. Every physical call or seat turn is compared with it; a valid changed block refreshes run state as the existing slice shape with each producer projected as `{"task_executor": current_id}` and configuration omitted before plan diff or scheduling. Retained producer spellings use read-time compatibility only; new or changed spellings validate prospectively. | accepted amendment B1 | touch block extraction, validation, anchoring, and projection; do-not-use a route, reply, panel control, or state flag as author authority |
| Prompt-set storage and freshness | `prompt_sets/<set>/{shared,milestone,brainstorming}/…` resolves named set → stored `default` → in-code seed. A malformed file or missing canonical route makes the whole set unreadable; every physical call reads afresh and never mixes rungs. | `goal.md:60-85`; accepted amendment B1 | touch the service-home store and resolver; do-not-add versions, snapshots, caches, migrations, or edit events |
| Material and variables | Every non-empty material id layers an exact override over a complete base; no match is silent inheritance. Required job payloads fail, while absent run-service variables may drop their units. No optional producer-planning unit or planning discriminator exists: `draft_skeleton` alone receives catalogue-backed plan creation. | `goal.md:44-59,318-322`; accepted amendment B1 | touch resolution, corpus conversion, and fixtures; do-not-invent unknown-material failure or a planner selector |
| Served prompt boundary | The router returns assembled JSON with variable declarations. Consumers substitute values and may append only registered contract sections; they never read prompt files. Fallback information stays beside the prompt. Replies never carry `slices`. | `goal.md:17-22,85-91,350-355`; accepted amendment B1 | touch service API and consumers; do-not-leave a string-builder path or reply-plan lane |
| Contract registry | Each section id selects prose and, for the registered subset, its validator. Validate exactly registered assembled ids and mounted questions. Stored unknown ids are served and ignored; consumer-appended unknown ids are refused. | `goal.md:93-109` | touch the section registry and worker validation; do-not-build a second resolution path or content-policing engine |
| Target output vocabulary | Runtime output uses `questions`, with one non-empty answer per mounted id, at most 300 characters each. Target `need_rethink` is `finding` plus `target_path`; producer configuration, reply `slices`, implementer/fixer suite reporting, and planning authority fields retire. | `goal.md:116-145`; accepted amendment B1 | touch prompt contracts and validators; do-not-retain superseded fields or compatibility adapters after cutover |
| Session eligibility and roles | Brainstorming runs only the two planned producer steps and the single orchestrator-opened `rethink` session. Initial Position is the ordinary editor; contrary and questioner seats are read-only except for the canonical-block-only preservation rule. | `goal.md:185-197,323-332`; accepted amendment B1 | touch session admission and dispatch; do-not-add review, fix, rating, or suite sessions |
| Plan recovery | Slice id is identity and array order is delivery. Deletion or forbidden historical divergence selects the earliest prior boundary and computes an opening wipe/requeue/checkpoint account from the original old plan and run boundaries. Only a computed `wipe_boundary` opens reconciliation and freezes scheduling; the accepted-revision block remains the plan, anchor, and projection. The driver leaves HEAD at `accepted_revision`, performs no rewind/apply/merge/conflict resolution, and marks the sole `merge_repair` handoff immediately before dispatch. Its LLM owns all run-owned surgery and the final same-branch commit. Recompute one final account from the persisted original boundaries to the final block; this replaces the opening account and no further delta starts another repair. Success is limited to routed-output, branch, cleanliness, canonical-block, linear-history, ancestry, and invalidation checks, followed by atomic state/ledger close without repository edits. Failure leaves the frozen LLM-left state for manual recovery or restart. | operator amendment A3; accepted amendment B2 | touch block-derived diff, frozen reconciliation state, one handoff, and finite final checks; do-not-derive before/after from run state, mutate the repository in the driver, add retry/fallback machinery, or run a second repair |
| Read-only seat, suite, and trusted-judgment boundaries | Ordinary governed mutation by a read-only seat or suite checkpoint is restored. A valid plan-block change is reinserted alone and committed, invalidating that seat's readiness or the checkpoint status. Failed suite evidence remains non-deferrable until a fresh unchanged `passed` or `no_suite`. Separately, `review_round`, `delta_review`, and `reclassify` trust their report-only prompt instruction: only the source-neutral canonical-block observer runs after them; no judgment-specific mutation policing, restoration, block-only reinsertion, invalidation, or rerun occurs. | `goal.md:149-180,187-226`; accepted amendments B1 and B3 | touch seat/checkpoint snapshot and rerun gates plus source-neutral judgment plan observation; do-not-apply the seat/checkpoint mutation boundary to trusted judgments |
| Activation compatibility | After all cutovers and a driver drain, increment `state.SCHEMA_VERSION` and refuse pre-activation runs. Prompt reply transport, producer defaults, and legacy validators/adapters retire together; there is no fallback or migration. | accepted amendment B1 | touch activation guard and retirement tests; do-not-resume or rewrite legacy history under the new runtime |
| Retirements and untouched systems | Retire prompt builders/scrubber, old battery plumbing, split rethink routes, optional producer planning, reply `slices`, producer/material mutation controls, `plan_authoring_authorized`, `_continuation_may_plan_slices`, `design_update` as authority, matching-file-delta rejection, design-document fences, substring prompt tests, and old compatibility lanes. Each reply transport remains until its call-owning boundary lands. Staffing, rigor, model routing, and caller-authored standalone orders remain untouched. | `goal.md:294-335`; accepted amendment B1 | touch only replacement and cutover surfaces; do-not-expand into staffing, model routing, or embedded Git |

## Question Battery

| question | answer | evidence |
|---|---|---|
| victim | Operators, workers, and downstream repositories suffer wrong instructions, rejected replies, discarded work, or corrupted work ordering. Git can reverse bytes, but spent calls are irreversible; B1 independently requires one document-backed plan. | `goal.md:15-22,185-282`; accepted amendment B1 |
| machinery | Machinery is limited to the prompt store/router, validators, prompt-set binding, canonical-block extraction/anchoring/projection, repository-backed sessions and recovery, and suite checkpoint. Each serves a named contract; plan controls and reply transport are removed. | `goal.md:13-109,149-310`; accepted amendment B1 |
| consumers | Verified consumers are milestone dispatch, Brainstorming coordination, service/panel projection, prompt recording, plan ordering, and Git recovery. | `orchestrator/driver.py:4649-4695,7664-7712,9980-10033`; `orchestrator/brainstorming_execution.py:577-680`; `orchestrator/service.py:2301-2471`; `orchestrator/runners.py:1754-1767` |
| cheaper_alternative | Reusing the skeleton block, existing state projection, prompt seams, and Git primitives is cheaper than adding a planning discriminator, mutation API, Markdown parser, migration, or second authority. Documentation alone cannot enforce dispatch drift, rollback, or accepted ranges. | accepted amendment B1; `orchestrator/gitops.py:730-824,944-981` |
| cost | Fourteen bounded slices convert prompt and plan consumers without a daemon or data migration. Runtime adds fresh reads, exact-block comparison, and existing Git operations; activation deliberately rejects legacy runs instead of carrying permanent compatibility machinery. | accepted amendment B1; this skeleton, `Canonical slice plan` |
| threat_model | Workers control reply JSON and repository edits; malformed prompt sets and invalid plan blocks fail at their boundaries. Operator prompt prose, configured suite commands, compile-time registration, and the report-only repository instruction served to trusted judgments are trusted. The seat/checkpoint block-only exception preserves no unrelated mutation. | `goal.md:79-85,95-109,171-226`; accepted amendments B1 and B3 |
| enforceability | Whole-rung resolution, closed reply validation, existing target-type prompt slots, exact traces, proportional worktree/index/HEAD/anchor capture and restoration for editing calls, seats, and checkpoints, source-neutral canonical-block comparison for trusted judgments, and state transition gates cover the asserted guarantees. The design promises no judgment-specific mutation policing for trusted report-only calls, unrelated-ref, reflog, stash, or Git-plumbing recovery, semantic policing, prompt snapshot publication, automatic plan restoration, or legacy migration. | `implementation/brainstorming/prompt-router/adapted-kinds/brainstorming/discussion_turn.json:69-98`; `orchestrator/contracts.py:898-1059`; `orchestrator/runners.py:1663-1676,2735-2775`; `orchestrator/canonical_plan.py:317-353`; `orchestrator/gitops.py:787-872`; operator amendment A1; accepted amendments B1 and B3 |
