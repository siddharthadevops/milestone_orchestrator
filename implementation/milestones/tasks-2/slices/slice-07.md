# Slice 07 — Standalone task API

## Register 1 — INTENT (lay language)

### What this slice builds

This slice lets an operator or another product order the same work unit a
milestone uses, without first creating a milestone. The caller chooses Worker
or Brainstorming, supplies one common request, receives a durable task id, and
can list or inspect the record while the work is open and after it finishes.
The same catalogue explains both choices and their configurable options.

Ordering is a handoff, not a long-running HTTP conversation. A successful
order response means the task was durably accepted; it does not mean the work
succeeded. Worker performs one caller-authored request. Brainstorming owns its
bounded discussion and applies the agreement through its existing production
boundary. In both cases the task record keeps the executor's native result and
truthful known accounting for the caller to judge.

### Ownership and boundary

This slice owns the four public task routes, direct-order access resolution,
the durable home and bounded execution handoff for standalone orders, and the
shared read projection for authorized task records. It joins those surfaces to
the catalogue, admission, Worker, and Brainstorming contracts already built.
It does not create another task shape or interpret results for the caller.

A direct Worker request is intentionally not a hidden milestone invocation.
There is no task kind, milestone strategy, review, fixer, seal, or structured
Worker result contract. The caller's request text is the complete model-facing
instruction; context, references, and destination remain common task context,
not material for a second prompt builder. A direct Brainstorming request still
uses the existing adapter's private discussion target and post-agreement
production boundary.

### Dependencies and consumers

This slice depends on the reviewed catalogue and closed contracts, common
durable admission and destination handling, the transport-only Worker adapter,
the profile-independent Brainstorming staffing and lifecycle adapter, existing
project/work-area resolution, and the service's authentication and JSON
envelope. Its immediate consumers are operators, calling products, and the
next slice's panel. Existing milestone scheduling remains a producer of the
same canonical task records and is otherwise unchanged.

### Guarantee posture

- **Strict — API and admission:** the routes, response envelopes, catalogue,
  order shape, error vocabulary, access decision, resolved work area, frozen
  order, historical staffing snapshot, and one task id are deterministic. A
  successful order response means the open record is durable before execution
  handoff.
- **Strict — visibility:** a successful list or inspect response contains the
  canonical durable records currently readable by that caller. Project members
  see only records bound to projects they may access; project-less records are
  administrative. A terminal result is immutable.
- **Strict — executor boundary:** Worker sends the caller-authored request text
  unchanged and treats returned text as opaque native output; it does not infer
  a milestone result kind or run contract repair. Its task id is durable on the
  call marker before dispatch, and that marker records the actual call-time
  staffing and accounting. Brainstorming freezes the visible configuration and
  static staffing before admission, then preserves its native session result
  and production-effect boundary.
- **Optimistic — execution and recovery:** after durable admission the service
  starts the selected existing executor without a queue. Normal completion or
  an observed failure terminalizes the record. Brainstorming retains its native
  same-task session recovery. A service crash can leave a direct Worker task
  open because this slice adds no replay or abandonment judgment.
- **Best-effort — effects and delivery:** executor effects can precede lost
  completion evidence and are neither confined nor rolled back. The destination
  instruction is strict, but placement beyond admission and task-derived paths
  remains unproved. Logs, later chips, and other convenience projections are
  not acceptance authority.
- **No eventual guarantee:** no deadline, automatic retry, queue, or promise
  that every admitted task eventually becomes terminal is added.

### Acceptance

- The catalogue read returns the shared two choices and their configuration
  schemas without a route-local copy.
- Direct ordering accepts one closed common order, resolves and authorizes its
  work area, uses common admission, returns one open canonical task, and starts
  the selected executor without waiting for completion.
- A direct Worker invocation sends its `request` string unchanged, records raw
  returned text as opaque `native_result`, links the pre-dispatch call marker to
  its task id, and records actual staffing plus complete or explicitly partial
  duration, token, and two-reading cost evidence.
- A direct Brainstorming order resolves its complete static seat binding before
  admission, freezes supplied/default round and closure choices, and reaches
  success only after the existing agreement-effect boundary completes.
- Invalid orders admit nothing. Unknown executors, malformed common requests or
  configurations, unavailable static Brainstorming staffing, forbidden access,
  and unknown task identities retain the pinned public classifications.
- List and inspect return the same canonical record shape for authorized direct
  and registered milestone tasks; open and terminal results are visible without
  reinterpretation.
- Supplied destinations use common primary-root canonicalization. Declared
  references cannot enlarge the resolved readable roots. No additional
  placement success or failure is synthesized from filesystem scanning or
  native claims.
- Focused API tests and the repository's complete suite pass once each at their
  respective gates.

### Non-goals

- No scheduler, queue, priority, concurrency policy, idempotency key, automatic
  retry, Worker continuation, task cancellation, deletion, or new start/resume
  route.
- No milestone, strategy, review, fixer, verification, seal, or task-kind
  semantics for a direct order.
- No panel controls or task chips; those remain Slices 8 and 9.
- No second catalogue, order/result schema, staffing ledger, accounting ledger,
  artifact inventory, executor-specific public route, or exposed Brainstorming
  target field.
- No Worker prompt decoration from `context`, `reference_documents`, or
  `output_directory`; callers put every model-facing instruction in `request`.
- No filesystem sandbox, universal reference/effect confinement, placement
  proof, freshness gate, rollback, cleanup, or exactly-once effects.
- No write to a declared additional root and no edit to the granted Life,
  Agent99, LPC, or Tutor repositories.

### Risks

- Returning before durable admission could lose an acknowledged task; waiting
  for terminal completion would turn ordering into a fragile long HTTP call.
- A second Worker prompt builder could silently change direct caller intent or
  pretend `output_directory` is independently model-visible.
- Treating arbitrary Worker text as a milestone result kind could fabricate
  success or trigger an unauthorized repair retry.
- Trusting caller-supplied roots could let a project member expand readable or
  writable authority beyond the declared work area.
- Admitting Brainstorming before static staffing resolves could leave a record
  with no lawful dispatch binding; restaffing later would rewrite its decision.
- Retrying an order whose response was lost creates a second task and may repeat
  effects; no idempotency claim exists.
- Treating an orphaned open Worker task as failed or retryable would add a new
  recovery judgment the milestone forbids.
- Merging internal calls or Brainstorming session totals twice would overstate
  task accounting.

### Reuse Posture

The affected parties are operators and calling products that currently cannot
order a first-class task without milestone machinery. The realistic harm is an
unavailable required surface, or—if added carelessly—an acknowledged-but-lost
order, foreign work-area access, rewritten caller intent, or duplicate charges.
The reviewed goal independently requires direct ordering and durable results.

Checked and reused are the shared catalogue and validators, common admission
and one-way result transition, destination primitive, Worker pass-through and
durable call-marker/accounting linkage,
Brainstorming static staffing/session/effect adapter, current work-area resolver,
project membership filtering, service JSON/error envelope, atomic locked record
writes, runner accounting, and existing executor child/recovery boundaries. The
cheapest sufficient addition is one thin route coordinator, one durable home
for standalone canonical records, and one immediate per-order execution handoff.
The service, later panel, and direct callers are the only new consumers.

No queue, scheduler, task-kind protocol, prompt renderer, result translator,
retry controller, activity ledger, or placement checker is justified. The new
durable home has bounded schema and operating cost and reuses the existing
atomic-write pattern; the execution handoff has no migration and no background
policy beyond starting the selected adapter. Omitting either loses an accepted
order or leaves it permanently unexecuted. Stronger recovery would add ongoing
supervision and replay ambiguity for effects that may already have landed, so
the open-record limitation is explicit and reversible by a new caller order.

### Size posture

This slice is expected to exceed about 500 non-mechanical changed lines. The
public routes are small, but focused proof must cover durable asynchronous
handoff, both real adapter boundaries, access filtering across direct and
milestone records, reload/terminal races, and exact error mapping. The runtime
change must still remain one coordinator and one record home rather than grow a
parallel orchestrator.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton, the existing task/admission/adapters, and
  current service access, record, and executor-lifecycle seams.
- **Revise:** the pre-Slice-7 absence of a direct Worker execution host becomes
  one immediate service-owned handoff; it is not a scheduler, queue, or retry
  policy. Direct Worker output is raw native text because no result kind exists.
- **Reject:** `brainstorming` and `_drafts` material as authority, plus any
  proposal for per-kind routes, a second prompt, durable supervision, or a new
  activity/accounting ledger.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Public routes and envelopes | Exact routes are `GET /api/task-executors`, `GET /api/tasks`, `POST /api/tasks`, and `GET /api/tasks/<id>`. Success uses the service envelope: catalogue `{ok:true, task_executors:[...]}`, list `{ok:true, tasks:[...]}`, and create/inspect `{ok:true, task:{...}}`; create returns `201`, reads return `200`. The record value is the canonical task record, not a route-specific translation. | `implementation/milestones/tasks-2/skeleton.md:335-343,360`; existing JSON envelope `orchestrator/service.py:3862-3888,4383-4390` | touch the shared service router and one canonical projection; do-not-add executor-specific, start, retry, cancel, delete, or activity routes, or wrap native results differently |
| Catalogue authority | `GET /api/task-executors` returns `tasks.task_executor_catalogue()` unchanged: exactly `worker`, then `brainstorming`, with every exact self-description member and `configuration_schema`. The same schema resolves and validates `POST /api/tasks`; no API-local defaults or choices exist. | `implementation/milestones/tasks-2/skeleton.md:353,360`; `orchestrator/tasks.py:40-87,142-145,186-229` | touch catalogue exposure only; do-not-copy schemas, infer from `available_agent_configurations`, or create another selector |
| Direct order and work area | The POST body is exactly the common order: required `task_executor` and `request`, optional `configuration`; the nested request has required `work_area`, `request`, `context`, ordered `reference_documents`, and optional `output_directory`. For a project-bound direct order, `work_area` is exactly `{project, work_area}`; the route authorizes those handles and replaces the selector with the current resolved project context before common admission. An administrator may instead use the existing project-less shape `{workspace_path, primary, additional}`, with equal existing absolute workspace/primary paths and an ordered list of existing absolute additional roots. Unsupported work-area members are `invalid_task_request`; caller paths never enlarge project authority. | `implementation/milestones/tasks-2/skeleton.md:351-352,360-361`; closed validators `orchestrator/tasks.py:106-183,449-476`; resolution/access `orchestrator/driver.py:10838-10960`; project-less precedent `orchestrator/driver.py:2658-2667`; `orchestrator/service.py:3298-3332`; `orchestrator/access.py:42-70` | touch API pre-admission resolution and shared admission; do-not-trust caller roots, add members beside the common order, retain the selector in the frozen record, or add TaskExecutor-side authority lookup |
| Admission and errors | Valid work-area resolution precedes shared destination canonicalization and durable admission. A `201` response contains the newly admitted record with `result: null`; execution outcome is observed later. Shape/configuration failures are `invalid_task_request` (400), an unknown id is `not found` (404), foreign access is `forbidden` (403), an unknown executor is `unknown_task_executor` (400), and unresolved static Brainstorming staffing is `task_unavailable` (503) before any record. Other project/work-area refusals retain their existing public reason and status. No raw operational exception becomes a public task error. | `implementation/milestones/tasks-2/skeleton.md:43-52,95-104,360`; `orchestrator/tasks.py:16-20,449-508,576-597`; `orchestrator/brainstorming_tasks.py:107-157`; service errors `orchestrator/service.py:223-227,274-281,4054-4062` | touch error translation, atomic admission, and immediate execution handoff; do-not-admit before static staffing, return terminal success from POST, expose exceptions, or add an idempotency promise |
| List, inspect, and access | List and inspect read canonical direct and registered-milestone task records. List filters before projection: administrators see all registered records, project members only records bound to accessible projects, and project-less records remain administrative. Inspect applies the same record-level decision. Reads neither refresh nor mutate tasks and make no panel-freshness promise. | `implementation/milestones/tasks-2/skeleton.md:18-22,143-159,205-210,335`; record reads `orchestrator/tasks.py:538-553`; access precedents `orchestrator/service.py:3510-3520,3764-3817` | touch authorized aggregation and record lookup; do-not-add origin-specific public shapes, leak foreign records, mutate on read, backfill legacy activity, or add polling/freshness machinery |
| Direct Worker execution and attribution | A direct Worker task has no milestone kind or authoritative structured result. Its one physical call receives exactly `order.request.request`; `context`, references, and `output_directory` are not injected into a second prompt. The task id is durable on the existing call-marker shape before dispatch. Profile-less Worker staffing still resolves from configured defaults when the call begins; the marker records actual family/model/effort, while the order snapshot remains historical. Successful transport records raw returned text as opaque `native_result`; failure records the most specific available reason and truthful complete/partial marker accounting. Unvalidated text merely resembling `need_rethink`, `artifact`, or `files_changed` remains opaque. | `implementation/milestones/tasks-2/skeleton.md:18-22,76-87,105-112,185-204,351-352,355-356,359`; pass-through/accounting `orchestrator/tasks.py:556-573,646-753`; call marker `orchestrator/driver.py:3070-3084`; raw runner seam `orchestrator/runners.py:1269-1280` | touch one direct Worker host, pre-dispatch marker, and generic result mapping; do-not-use the snapshot as dispatch pins, call milestone validators, parse a hidden kind, contract-repair, decorate/rebuild the prompt, refresh live authority, or add continuation/another ledger |
| Direct Brainstorming execution | Direct Brainstorming is profile-independent. Before task admission it resolves and freezes complete static seat pins plus schema-resolved `max_rounds` and `closure_policy`; failure to resolve a binding is `task_unavailable`. The adapter forwards those pins and configuration unchanged to the existing service. The admitted task spans its bounded session and native recovery, uses the pins without rotation/restaffing, and becomes successful only after the existing post-agreement effect boundary completes. Its native result remains opaque and its physical-call accounting contributes once. | `implementation/milestones/tasks-2/skeleton.md:88-104,170-184,353-357`; `orchestrator/brainstorming_tasks.py:107-192,225-262,450-623,832-894,1103-1223` | touch direct admission/launch association and terminal handoff; do-not-use a current profile, expose a target/seat selector, silently restaff, flatten the result, or add another session/effect/accounting layer |
| Durable record and execution posture | One accepted scheduling decision creates one id and exact record `{id, order, resolved_staffing, result}`. The order and staffing snapshot never change; `result` moves only from null to one validated terminal value. POST hands execution off without waiting. Normal completion/failure terminalizes; a service interruption may leave a direct Worker record open. Re-ordering creates a new task id and may repeat effects; no lineage record is added. | `implementation/milestones/tasks-2/skeleton.md:43-53,170-184,205-210,356`; `orchestrator/tasks.py:538-615`; append-only precedent `orchestrator/state.py:243-277`; atomic-write precedent `orchestrator/registry.py:65-91` | touch a standalone canonical record home and per-order host; do-not-reopen terminal records, infer failure/retry on restart, promise eventual/exactly-once effects, or create a queue/scheduler |
| References, destination, and slice boundary | Declared references may resolve only beneath the authorized primary/additional roots; additional roots remain non-destinations. Common admission canonicalizes a supplied `output_directory` inside the primary root and every task-derived path stays beneath it. Free-text contradiction, native claims, and undeclared effects do not synthesize placement failure, authorization, cleanup, or rollback. Slice 7 adds no panel/chips and does not alter the producer route; those remain Slices 8-9, with broad cross-surface conformance in Slice 10. | `implementation/milestones/tasks-2/skeleton.md:185-232,335-343,361`; `orchestrator/tasks.py:479-535`; full-access limit `orchestrator/README.md:508-511` | touch declared-reference access validation and reuse common destination admission; do-not-add `output_directory_violation`, scan/parse effects, inject a Worker directive, write additional roots, or pull panel/chip/conformance scope forward |

### Verification Contract

Focused tests in `orchestrator/tests/test_task_api.py` must prove:

1. `test_catalogue_route_reuses_shared_schema` asserts exact route status,
   envelope, catalogue order/fields, and equality with the shared catalogue;
   changing a schema default changes validation and exposure together;
2. `test_direct_order_resolves_access_before_admission` covers member/admin,
   exact project-bound and administrator-only project-less work-area shapes,
   current resolved roots, unsupported/forged members, foreign projects,
   missing work areas, malformed JSON/order/configuration, unknown executor,
   inside/additional/outside declared references, and outside destination,
   proving every refusal admits nothing and no caller path expands the frozen
   context;
3. `test_post_returns_durable_open_task_before_completion` blocks each fake
   executor after handoff, observes `201` with `result: null`, reloads and
   inspects the same id, then releases it and observes one terminal transition;
4. `test_direct_worker_preserves_raw_request_result_and_accounting` blocks
   before dispatch, changes a profile-less default, and proves the immutable
   snapshot differs from the actual family/model/effort recorded on a durable
   task-id marker. With `output_directory` omitted, it also captures the exact
   caller-authored physical prompt, proves no structured-result repair, and
   checks raw text plus complete and partial failure accounting;
5. `test_direct_brainstorming_freezes_and_runs_static_order` covers defaults and
   supplied round/closure choices, pre-admission `task_unavailable`, frozen seat
   pins, unchanged create-body forwarding, one session, effect-before-success,
   native-result opacity, accounting, and same-id native recovery without
   restaffing;
6. `test_task_list_and_inspect_apply_record_access` seeds direct and milestone,
   open and terminal, project-bound and project-less records; it proves the
   canonical record shape, member filtering, admin visibility, foreign refusal,
   unknown-id `404`, and no mutation on reads; and
7. `test_direct_interruption_adds_no_retry_or_liveness_claim` proves an
   interrupted Worker may remain open, a new POST receives a different id, and
   no executor-specific/start/retry/cancel/delete route exists. Slice 10 retains
   the out-of-root native-claim and partial-effect conformance proofs.

Lower-level contract, admission, Worker, Brainstorming-adapter, service-access,
and lifecycle suites remain authoritative beneath the focused module. The
focused command is `python3 -m unittest orchestrator.tests.test_task_api`.
Final closure runs exactly
`python3 -m unittest discover -s orchestrator/tests -t .`.

Authorities: `implementation/milestones/tasks-2/skeleton.md:335-343,351-363`;
contract/admission precedents `orchestrator/tests/test_tasks.py:85-313,408-638`;
Brainstorming adapter precedents
`orchestrator/tests/test_brainstorming_tasks.py:431-906`; access precedents
`orchestrator/tests/test_service_projects.py:315-435`; full suite
`orchestrator/README.md:522-532`.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These five entries are the slice-scoped remainder; enforceability is answered
again for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified immediate consumers:** the authenticated service router and JSON envelope; project/work-area resolution and membership filtering; the shared catalogue/order/admission/record surface; Worker call marker, raw runner, and accounting projection; the static Brainstorming admission/session/effect adapter; registered milestone task states for read-only aggregation; and direct operators/calling products. **Verified untouched:** milestone scheduling and producer writes, panel controls, task chips, reviews, fixes, verification, and seals. | `orchestrator/service.py:3298-3332,3510-3520,3764-3817,3824-4281,4351-4390`; `orchestrator/tasks.py:142-229,449-753`; `orchestrator/driver.py:3070-3084`; `orchestrator/brainstorming_tasks.py:107-192,450-623,832-894,1103-1223`; boundary `implementation/milestones/tasks-2/skeleton.md:325-343` |
| pinned_facts | The hard table pins the four routes and exact envelopes; one shared catalogue/schema; the closed direct order and authoritative work-area resolution; status/error mapping; access-filtered canonical reads across direct and milestone origins; raw untyped Worker execution; static Brainstorming execution; one immutable record with optimistic handoff; bounded reference/destination enforcement; and the later-slice boundary. | `implementation/milestones/tasks-2/skeleton.md:18-22,43-53,88-104,143-232,335-363`; `orchestrator/tasks.py:40-87,449-615`; `orchestrator/service.py:3298-3332,3764-3817` |
| verification | One focused service module pins catalogue/schema parity, access-before-admission, durable non-blocking handoff, raw Worker prompt/result/accounting, static Brainstorming configuration/staffing/effects/recovery, access-filtered list/inspect across both origins, exact errors, and the no-retry/no-liveness boundary. Existing task, adapter, lifecycle, access, and full-discovery suites remain lower-level and closure proof. | `implementation/milestones/tasks-2/skeleton.md:335-343,360-363`; `orchestrator/tests/test_tasks.py:85-313,408-638`; `orchestrator/tests/test_brainstorming_tasks.py:431-906`; `orchestrator/tests/test_service_projects.py:315-435`; `orchestrator/README.md:522-532` |
| reuse_posture | **Affected party/harm:** direct callers currently lack the required API; a careless implementation can lose an acknowledged order, expand work-area access, alter prompts, or duplicate accounting. **Checked/reused:** catalogue/validators, admission/terminal transition, destination check, Worker pass-through and call marker, Brainstorming static lifecycle/effects, binding resolution, access filtering, service envelopes, atomic locked writes, runner accounting, and child/recovery seams. **Cheapest sufficient option:** one route coordinator, one standalone canonical record home, and one immediate per-order host. **Remaining machinery/consumer:** only those three seams, consumed by service/API and later panel. **Lifecycle:** no migration/queue/scheduler/retry/prompt renderer/result translator/ledger; omission makes direct ordering absent or inert, while stronger replay is costly and unsafe after partial effects. | `orchestrator/tasks.py:142-229,449-753`; `orchestrator/driver.py:3070-3084,10838-10960`; `orchestrator/service.py:3298-3332,3764-3817,4383-4390`; `orchestrator/registry.py:65-91`; `orchestrator/brainstorming_tasks.py:107-157,450-623,1103-1223`; authority `implementation/milestones/tasks-2/skeleton.md:234-306,335,360-363` |
| enforceability | **Route/schema:** deterministic router branches plus the shared closed validators/catalogue. **Access:** authenticated identity, project membership, and current work-area resolution run before admission/projection. **Acknowledgement/durability:** locked atomic write precedes `201`; canonical admission freezes detached values and the one-way result transition rejects rewrites. **Worker:** the task-linked durable marker precedes the raw pass-through call and records actual staffing/accounting; no kind validator runs. **Brainstorming:** pre-admission static resolver, frozen pins/configuration, one-session lock, and effect completion gate. **Destination/reference:** current roots plus real-path containment enforce only declared references, admission, and task-derived paths. No pinned mechanism proves service-crash recovery, eventual completion, universal placement, rollback, cleanup, exactly-once effects, or view freshness, so this note promises none. | `orchestrator/access.py:42-70`; `orchestrator/service.py:3298-3332,3824-3860,4351-4390`; `orchestrator/driver.py:3070-3084,10838-10960`; `orchestrator/tasks.py:106-229,449-753`; `orchestrator/registry.py:65-91`; `orchestrator/brainstorming_tasks.py:107-192,450-623,1103-1223`; bounded authority `implementation/milestones/tasks-2/skeleton.md:76-87,170-210,360-363` |
