# Reviewed Tasks and Deep Tasks

Mandate: the frozen launch snapshot in
`implementation/milestones/deep-reviewed-tasks/goal.md`.
This is the planning contract for the milestone; slice notes will define each
bounded implementation surface when that slice starts.

## Register 1 — Intent (lay language)

### What this builds

An operator or calling product can order one **reviewed task** and receive one
production that has passed the complete existing review discipline, is sealed
on its current contents, and owns its gate commit. The same public type covers
document, implementation, and complete-verification work; the order identifies
the semantic job without creating domain-specific task types.

An operator or calling product can also order one **deep task** for a coherent,
slice-sized outcome. It first completes reviewed documentation, then completes
reviewed implementation. If implementation is cut into coherent parts, every
part remains a visible reviewed task with its own evidence, accounting, seal,
and gate commit.

Milestones and Agent99 are callers of the same catalogue and order contract.
They receive no private executor variant. Existing agent-call and Brainstorming
tasks remain available independently.

### Review behavior

The current review system moves as one unit: goal and design material, project
context, material, prompt-set and staffing authority, operator and accepted
amendments, family order and restarts, reviewer/fixer separation, whole and
delta review, finding validation, fixes, debt and independent rating, ledgers
and citations, caps, evidence freshness, rethink, size cuts, recovery,
WIP/amend history, deterministic seal, and gate commit retain their present
meaning. An untouched reviewed order uses two distinct review families and
today's debt behavior. An explicit cheaper order uses exactly one family; it
cannot defer debt unless the operator also chooses the established same-family
independent second look.

Every physical production, review, fix, delta-review, or classification call is
evidence inside the reviewed task. It is not another task unless a caller
explicitly orders the public agent-call type. Prompt Router remains the only
prompt authority. A rethink keeps the reviewed task open, continues the same
phase after successful Brainstorming, and fails that task if Brainstorming
fails.

### Composition and ownership

A deep task admits one reviewed documentation child and then one reviewed child
for each implementation part discovered in sequence. The durable parent,
phase, part, and admitted child identity decide recovery; once a child exists,
recovery observes or resumes it instead of placing the same child again. A
parent aggregates child results without counting their calls twice and never
replaces the children's commits with an aggregate commit. Documentation and
implementation expose their own review, debt, and cap choices; reducing those
choices never removes implementation review. Terminal children remain
immutable, and a lawful retry is a distinct successor.

This milestone owns the reusable reviewed-work lifecycle, the two public task
types, their generic ordering and presentation, and milestone composition over
them. Milestone law still owns sequencing, canonical-plan establishment,
higher-level closure and ledgers, design-repair waves, reconciliation,
aggregate run accounting, stop and liveness, deployment, and the five-slice
and final verification cadence. Reclassification remains an internal routed
call; merge repair and synchronization remain direct operations.

### Guarantee posture

- **Strict:** explicit task admission and terminality; selected one- or
  two-family convergence; current-content evidence; one reviewed-task seal and
  gate commit before success; durable child identity; no duplicate admission
  for an already-recorded phase and part; child-first accounting; milestone
  verification gating; and old-run compatibility.
- **Best-effort:** chips, grouping, convenience projections, and display
  freshness. Losing them cannot change execution, acceptance, or accounting.
- **No optimistic or eventual promise is added:** recovery uses durable state
  already written, but this milestone adds no exactly-once, retry-delivery, or
  eventual-UI guarantee.

### Reuse and exclusions

The implementation extends the existing generic catalogue, order/result
record, direct API, generated form, Prompt Router, review state machine,
implementation-part cut, Git WIP/amend/gate operations, and accounting
projections. No granted product root contains another reviewed/deep task engine
to adopt. No additional root is edited.

There is no new scheduler, queue, event bus, notification system, permission
model, prompt path, staffing authority, model router, cache, rollback layer,
migration lane, task taxonomy, accounting store, or verification-only task
type. Internally emitted child records are trusted product machinery; tests
prove their outcomes and recovery, not defensive handling of imaginary
self-malformed emissions.

## Canonical slice plan
```json
{"slices":[
  {"id":1,"title":"Default reviewed-lifecycle parity","intent":"Expose the current production-through-review-and-gate lifecycle as one reusable reviewed-work boundary, with an untouched order preserving existing authority, history, recovery, and outcomes.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":2,"title":"Producer, review breadth, debt, and caps","intent":"Expose the catalogue-supported producer for the semantic job, one- or two-family breadth, applicable debt posture, existing convergence caps, and implementation size controls as per-order choices while keeping two distinct families and current debt behavior as the default.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":3,"title":"Routed calls and rethink continuity","intent":"Route every reviewed-work call directly through Prompt Router, support each offered semantic-job and producer combination, retain calls as evidence rather than child agent-call tasks, and keep the originating task open across rethink.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":4,"title":"Reviewed seal, gate, result, and recovery","intent":"Close reviewed work only from current review evidence and its own deterministic seal and gate commit; preserve WIP/amend recovery and return review evidence plus commit identity in the native result.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":5,"title":"Standalone reviewed-task ordering","intent":"Publish reviewed_task through the shared catalogue, generic task API, and catalogue-generated panel so direct callers receive the same configuration, durable result, stop behavior, and recovery boundary as milestone callers.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":6,"title":"Deep documentation and child authority","intent":"Publish deep_task and deliver its reviewed documentation child first, recording parent, phase, and admitted child as durable authority that recovery reuses without a private child entry point.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":7,"title":"Deep implementation-part delivery","intent":"Materialize every discovered implementation part sequentially as a reviewed-task child, preserve every child commit and native result, and aggregate child accounting without recounting physical charges or adding an aggregate commit.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":8,"title":"Milestone skeleton composition","intent":"Order the milestone skeleton as one reviewed task, establish the canonical plan only from its sealed result, and retain milestone-owned closure, reconciliation, stop, and deployment behavior.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":9,"title":"Milestone deep-slice composition","intent":"Order each logical slice as one deep task while preserving accepted-design repair and re-documentation consequences, sequential implementation parts, and every reviewed child gate.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":10,"title":"Sibling complete-verification task","intent":"Run complete repository verification as an independently orderable reviewed task whose failures enter its fix and rerun discipline, whose changes are reviewed, and whose unchanged success still owns a seal and gate commit.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":11,"title":"Five-slice and final verification cadence","intent":"Replace new runs' in-slice checkpoint with a sibling verification task after every five completed logical slices and at final current-content closure, reusing an already-current checkpoint and blocking later work until success.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}},
  {"id":12,"title":"Presentation, compatibility, and conformance","intent":"Show each milestone verification separately with its task evidence; preserve old runs and history under their original law; and prove public ordering, composition, commit ownership, recovery, prompt cardinality, cadence, and single-count accounting end to end.","producer_task_executor":{"draft_slice_note":"agent_call","implement":"agent_call"}}
]}
```

## Register 2 — Pinned facts (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Public TaskExecutor ids and routes | Add exactly `reviewed_task` and `deep_task`; retain `agent_call` and `brainstorming`. All four use the existing generic catalogue and task routes: `GET /api/task-executors`, `GET/POST /api/tasks`, and `GET /api/tasks/<id>`. | `implementation/milestones/deep-reviewed-tasks/goal.md:16-32`; `orchestrator/service.py:4581-4631,4838-4840` | touch the shared catalogue, admission host, API, and generated panel; do-not-add per-type routes or a private Agent99/milestone entry point |
| Reviewed-task success | `reviewed_task` succeeds only after convergence on current contents, a deterministic seal, and its own gate commit; its native result preserves review evidence and commit identity. Public task results remain terminal `success` or `failure`. | `implementation/milestones/deep-reviewed-tasks/goal.md:34-40,75-79`; `orchestrator/tasks.py:780-806` | touch the reusable lifecycle and native result; do-not-report success from production, reviews, or seal alone |
| Review breadth and debt | Default is exactly two distinct families; explicit single-family walks exactly one. Double-family failure never degrades. Single-family debt deferral is off unless the operator explicitly selects the existing same-family second look. | `implementation/milestones/deep-reviewed-tasks/goal.md:42-55`; `orchestrator/staffing.py:1930-1987`; `orchestrator/driver.py:11955-11962` | touch per-order policy and the family set supplied to convergence; do-not-move family selection or staffing authority out of Staffing Router |
| Review-cycle meaning | Authority and amendments, family restart/order, whole and delta reviews, fix and escalation, caps, debt and reclassification, evidence invalidation, size cuts, rethink, recovery, and WIP/amend/seal/gate behavior retain their existing meaning. | `implementation/milestones/deep-reviewed-tasks/goal.md:57-73`; `orchestrator/state.py:806-850,1110-1236` | touch ownership and reuse seams; do-not-simplify, fork, or replace the lifecycle while extracting it |
| Prompt and physical-call boundary | Every production, review, fix, delta-review, and classification call submits its semantic charge directly to Prompt Router. Every offered semantic-job/producer pair has an explicit route. These calls are evidence, not child `agent_call` task records; only an explicit public order creates a task. | `implementation/milestones/deep-reviewed-tasks/goal.md:87-99`; `orchestrator/prompt_router.py:28-49,77-127` | touch the route grid and call adapters; do-not-add prompt fragments, caller-built prompts, fallback routing, or an internal agent-call task layer |
| Rethink terminality | `need_rethink` is internal control. It leaves the originating reviewed/deep task open, resumes its interrupted phase after successful Brainstorming, fails it after failed Brainstorming, and never reopens a terminal record. | `implementation/milestones/deep-reviewed-tasks/goal.md:101-105`; `orchestrator/tasks.py:584-599` | touch the existing handoff and recovery path; do-not-terminalize the reviewed parent on a successful rethink or reuse a terminal id |
| Deep-task composition and commits | One documentation `reviewed_task` precedes one or more sequential implementation-part `reviewed_task` children. Documentation and implementation expose separate breadth, debt, and cap choices; focused checks stay with the child that needs them. There is no bare implementation leg, milestone-wide suite slot, or aggregate replacement commit. | `implementation/milestones/deep-reviewed-tasks/goal.md:107-130`; `orchestrator/state.py:606-747` | touch composition over public reviewed-task admission and the existing part cut; do-not-pre-plan parts, collapse gates, or add a verification child |
| Composite authority and accounting | The durable parent, semantic phase, discovered part, and admitted child id are the sole admission/recovery authority. A serialized parent transition admits at most one child for a recorded phase/part. Children own results and accounting; parents aggregate those values without recording any physical charge again. | `implementation/milestones/deep-reviewed-tasks/goal.md:132-148`; `orchestrator/task_api.py:128-145`; this skeleton, `Register 1 — Guarantee posture` | touch the canonical task record/store and existing aggregation; do-not-add a relationship store, inferred linkage, duplicate ledger, or exactly-once delivery promise |
| Milestone verification | Skeleton is one reviewed task; each logical slice is one deep task; complete verification is a sibling reviewed task after five completed logical slices and at final current-content closure. It does not count as a slice, and later work waits for success. Its separate panel item exposes task status, duration, cost, findings, review evidence, and result. No `verification_task` type exists. | `implementation/milestones/deep-reviewed-tasks/goal.md:150-174`; `orchestrator/driver.py:53,1451-1467` | touch new-run milestone scheduling, current-byte certification, and projection; do-not-retain an in-slice checkpoint for new runs or duplicate a current final verification |
| Ownership boundary | Milestone law retains sequencing, canonical-plan establishment, higher-level closure and ledgers, design repair, reconciliation, aggregate run accounting, stop, liveness, and deployment. Reclassification stays a direct routed call; merge repair and synchronization stay direct operations. | `implementation/milestones/deep-reviewed-tasks/goal.md:176-186` | touch only reviewed-cycle ownership and milestone composition; do-not-create hidden task types for ratings, repair, or sync |
| Compatibility and projections | Resumable runs finish under their original law; existing history is neither rewritten nor backfilled. Task records and parent/child authority are strict; chips, grouping, and convenience projections are best-effort. | `implementation/milestones/deep-reviewed-tasks/goal.md:188-208,223-224`; `orchestrator/state.py:2595-2634` | touch prospective activation and additive readers; do-not-reinterpret old checkpoints/per-call tasks or make display state an execution gate |

## Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Operators, milestones, and calling products currently cannot order one production-plus-review result or one reviewed documentation-plus-implementation result. Without this, callers either remain milestone-bound or must reconstruct the lifecycle, risking false success, duplicate child work, lost commit boundaries, and double-counted spend. Repository bytes are reversible through Git; spent calls and a falsely accepted result are not. The current catalogue and host independently confirm that only one-call and Brainstorming executors exist. | `implementation/milestones/deep-reviewed-tasks/goal.md:16-40,230-257`; `orchestrator/tasks.py:41-100`; `orchestrator/task_api.py:580-590` |
| machinery | New machinery is one reusable owner for the existing reviewed lifecycle plus durable composition for reviewed/deep tasks. It exists only to make the mandated complete cycle and child sequence public and recoverable. Configuration or documentation alone is insufficient because the current lifecycle is driver-owned and the direct host branches only between the two existing executors. | `implementation/milestones/deep-reviewed-tasks/goal.md:57-85,107-148`; `orchestrator/state.py:184-228,806-850`; `orchestrator/task_api.py:580-590` |
| consumers | Verified current consumers are the generic service routes, catalogue-generated order form and task detail, milestone task history/projection, and the driver. The granted product roots contain no current code consumer of these ids, so this plan adds no speculative Agent99 adapter; Agent99 is a future caller of the same mandated contract. | `orchestrator/service.py:4284-4305,4581-4631`; `orchestrator/static/panel.html:5688-5767,5784-5813`; `orchestrator/state.py:2613-2634`; `implementation/milestones/deep-reviewed-tasks/goal.md:25-28` |
| cheaper_alternative | Cheapest sufficient is to extend the generic catalogue/order/result/store and panel, extract rather than rewrite the current review lifecycle, and reuse Prompt Router, the family-aware seal predicate, Git WIP/amend/gate operations, implementation cuts, and existing accounting. Doing nothing misses both public types; wrappers or configuration cannot provide durable child authority or move the cycle out of the milestone; a second engine/store would duplicate solved machinery. | `orchestrator/tasks.py:202-204,411-440,560-599`; `orchestrator/state.py:1110-1236`; `orchestrator/gitops.py:638-694`; `orchestrator/state.py:606-747`; `implementation/milestones/deep-reviewed-tasks/goal.md:210-224` |
| cost | Delivery is twelve narrow slices. Build and review cost is highest at lifecycle extraction and milestone cutover; runtime retains the existing physical calls and Git work, adding canonical task/relationship writes and parent aggregation. There is no daemon, dependency, migration, or parallel store. Old history stays untouched, and pre-activation code changes are reversible; omission leaves the mandated ordering and cadence unavailable. | this skeleton, `Canonical slice plan`; `orchestrator/README.md:3-9,46`; `implementation/milestones/deep-reviewed-tasks/goal.md:188-214` |
| threat_model | Untrusted inputs are authenticated API order payloads, paths/configuration supplied at that boundary, model-result JSON, and worker edits. Existing closed request/order validators, project access/path containment, and result contracts guard those inputs. Trusted inputs are the frozen operator mandate, product-emitted child intent, stored prompt/staffing/configuration authority, and deterministic state/Git machinery. This plan adds no defense that polices those trusted emitters; child uniqueness is an atomic state invariant required for recovery, not malformed-self-input hardening. | `orchestrator/tasks.py:207-242,411-440,458-514,780-846`; `orchestrator/service.py:4165-4215`; `orchestrator/README.md:548-551`; this skeleton, `Register 1 — Reuse and exclusions` |
| enforceability | Existing mechanisms express most guarantees: task admission plus null-to-terminal mutation enforce identity/terminality; selected family lists feed the current same-content seal predicate; Staffing Router can refuse an unsatisfied distinct-family dispatch; immutable implementation cuts derive sequential parts; Git WIP/amend/gate operations and pending-gate recovery enforce commit closure; task-id accounting links charges once. The missing enforceable seams are the reusable lifecycle boundary, serialized phase/part child admission, reviewed native result, and sibling verification scheduling; slices 1, 4, 6, 10, and 11 must add them before their guarantees can be claimed. UI freshness remains deliberately unenforced. | `orchestrator/tasks.py:560-599,630-746`; `orchestrator/state.py:606-747,1110-1236`; `orchestrator/staffing.py:1930-1987`; `orchestrator/gitops.py:638-694`; `orchestrator/driver.py:12590-12664`; this skeleton, `Canonical slice plan` |
