# Milestone Tasks — Pluggable Slice Execution

Mandate: the frozen launch snapshot in `implementation/milestones/tasks-2/goal.md`.
This is a thin planning contract; slice notes will pin each bounded surface just
before it is built.

## Register 1 — Intent (lay language)

### Goal restatement

A milestone remains the manager of the work: it decides the order, checks the
result, runs reviews and fixes, keeps the history, and seals accepted work. A
**task** is the one piece of content work it hands to a **TaskExecutor**. The
existing one-worker call remains the default TaskExecutor. Brainstorming becomes
the second choice, so a slice that benefits from discussion can be produced by a
bounded group whose lead applies the agreed work.

Tasks also stand on their own. An operator or calling product can order the same
kind of task without creating a milestone, then observe the same description,
frozen order, result, and accounting record. The task layer carries the native
result back unchanged; the caller remains responsible for understanding it and
for any milestone-specific acceptance rule.

Producer choice is a separate planning axis, not a strategy decision. Strategy
says how work is judged; producer choice says who creates it. Each slice has
independent prospective choices for drafting its note and implementing its
work. A planner proposes both, and the operator may replace either only before
that respective task is ordered while the current plan remains installed. A
changed replacement plan discards prior overrides and exposes only its own
proposals and defaults. There is no hidden runtime routing or slice lineage.

### Ownership

This milestone owns the small TaskExecutor catalogue, the common request and
result contracts, one durable record per ordered task, the Worker and
Brainstorming adapters, both slice-production selections, and matching API/panel
surfaces. The current milestone is bootstrapped entirely by Worker tasks because
the selector does not exist at launch; a real test milestone proves a later
slice can run through Brainstorming end to end.

### Guarantee posture

- **Strict on admission and cardinality:** an admitted order freezes its task
  identity, request, chosen TaskExecutor, order-time `resolved staffing`,
  Brainstorming round/closure choices when applicable, and inherited execution
  context in one durable logical task record. Resolved staffing is the immutable
  historical snapshot of what admission resolved, not automatically a dispatch
  input; executor activity records the agent, model, and effort each physical
  call actually used. The record may remain non-terminal while
  execution is pending or running, including while its executor is stopped or
  recovering. If it becomes terminal, it has exactly one success/failure
  result. Task-chip and activity projections are best-effort bookkeeping;
  executor-internal calls remain inspectable evidence, not additional tasks.
- **Strict on `need_rethink` identity and terminality:** `need_rethink` is valid
  Worker help-seeking, never success; its failure means the invocation lacked
  its contracted result, not that the milestone failed. `draft_slice_note`,
  `implement`, and `fix_findings` are continuable: one task spans its attached
  discussion, continuation, and repeated rethink until completion or durable
  abandonment; provider-session reuse is mechanism, not identity. Recoverable
  stops, inspection failures, and crashes leave it open while durable wait,
  handoff, or continuation state remains usable.
  Existing transitions that abandon continuation fail it: failed attachment,
  detaching a missing or terminal session, disagreement or failed adoption
  routed elsewhere, or choosing origin retry or another action. Re-entry then
  admits a successor; no timeout or new recovery judgment applies.
  `review_round` and `delta_review` are not continuable: validated
  `need_rethink` fails that invocation with its native result, raw evidence,
  and complete known accounting. Its discussion remains non-task activity;
  any later review has a new task id, frozen order, durable record, and
  best-effort chip projection, with the
  handoff only as context and existing no-clobber review naming retained.
  Retired `seal_half` waits remain legacy seal activity with no task backfill.
  Every failure records its most specific terminal cause; the opaque native
  result retains the request and finding, while Brainstorming remains authority
  for its session reference.
- **Strict on Worker attribution:** a Worker task owns every accounting-bearing
  record for a call or attempt used to obtain or classify that scheduling
  decision's Worker outcome, including origins, continuations, malformed or
  repair attempts, interruption and stabilization, unaccepted calls, and
  in-call failure classification. The durable call marker receives the task id
  before dispatch and carries it into later and recovery records. A legacy
  marker without a task id remains on legacy unit/run paths; ownership is never
  inferred or backfilled from unit, kind, or label. Existing accounting homes
  and exclusions still apply, so each charge enters its task once and existing
  unit/run aggregation once; partial flags mean missing evidence only.
  Attached Brainstorming and post-result reclassification stay unstamped and
  outside Worker execution. This is linkage, not a parallel ledger.
- **Strict on staffing authority:** Worker retains its present call-time
  resolution: current profile state when a resolver exists, otherwise the
  configured defaults read when the Worker call begins. Profile-backed
  Brainstorming builds seats from the current profile at session start, carries
  the current-profile locator, and retains per-dispatch resolution. Neither path
  uses the order snapshot as dispatch pins or fallback; later authority changes
  may affect actual calls without changing that snapshot. Direct,
  profile-independent Brainstorming instead resolves complete Initial Position,
  Contrary Position, and Dante seat pins from configured family order, model
  defaults, and executable availability before task admission; those frozen
  pins are its static dispatch binding. The adapter supplies them through the
  existing create body, and session admission validates and binds them without
  rotation or replacement. Failure to resolve that binding is
  `task_unavailable` before task admission. Task and session admission remain
  distinct, so an admitted task may wait before its session exists; later
  availability loss or session refusal is its durable failure, never silent
  restaffing, and the caller may place a new order.
- **Strict on the default milestone path:** a Worker task used by a milestone
  records the exact initial prompt the milestone already builds and returns the native
  response unchanged. An absent producer map or either absent task-kind key
  independently means Worker, including for existing resumable runs. Worker
  slice-note drafting keeps its valid native `artifact` declaration as the
  unit's note path, including legitimate non-default paths.
  Milestone sequencing, review/fix cycles, verification, seals, and totals keep
  their present behavior.
- **Strict on live Worker authority episodes:** the milestone keeps every Worker
  order immutable while taking one live authority snapshot before each initial,
  crash/Resume, rethink-continuation, or fresh cutoff-stabilization dispatch.
  The prompt and safeguard extensions use that same snapshot; contract repair
  and in-place transport/protocol retry inherit it. A later episode appends one
  driver-owned authority block to the admitted prompt. Successfully parsed
  mutable operator amendments, including an explicit empty set, are complete
  and revoke omissions; an absent, unreadable, or malformed file is incomplete
  and revokes nothing. Accepted Brainstorming design amendments remain
  append-only. Amendment authority is derived from its durable source: mutable
  file entries remain operator law regardless of payload labels, while adopted
  and migrated design events remain lower design authority. The current
  safeguard set replaces rather than unions with the prior set. Standing-law
  failure stops before dispatch, while a synchronously
  validated durable carrier or recorded Worker result is consumed without
  another refresh or revalidation. Whole-review evidence binds candidate and
  execution-plan inputs, not the hot authority that separately governs each
  review episode, so Resume refreshes the same open review task and later hot
  changes do not invalidate completed approvals. A non-null pre-B6 fingerprint
  that included hot authority is an ordinary mismatch and restarts; it is never
  reconstructed or translated. The supported older shape with no binding but
  `family_index > 0` also restarts at family zero before dispatch, while an
  absent binding at family zero binds normally. Sealing still requires one
  matching binding on every effective clean review.
  Direct Worker orders remain static. Strategy/battery and other non-safeguard
  validation, roots/destination, producer, task identity, and accounting remain
  frozen, including strategy-owned post-result review deferral. Attached
  Brainstorming remains independent non-Worker activity and reads current
  project context when its session starts. Refresh adds no authority ledger,
  request rewrite, or successor task.
- **Strict structural parity, best-effort producer bookkeeping:** the API and panel use one catalogue and one
  canonical task projection; this does not promise that the panel is current.
  Each catalogue entry carries the same machine-readable executor-configuration
  schema used to validate orders, including visible defaults and finite choices;
  the panel derives its controls from that schema rather than copying them.
  The skeleton and panel expose both prospective slice choices. A slice-level
  producer write names exactly `draft_slice_note` or `implement` and changes
  only that still-unordered choice while the current plan remains installed.
  A busy run may refuse the write. A changed replacement installs its own
  proposal/default values and makes all prior writes inactive; an exact no-op
  preserves them. Existing event sequence, not a durable slice identity,
  identifies active review overrides. Admission freezes only that task. A terminal
  failure never reopens or mutates the task. An explicit retry, or the existing
  milestone Resume re-entering its failed scheduling point, admits a successor
  under that task kind's then-visible choice while retaining immutable history.
  The installed replacement is the only notice; no pause, acknowledgement,
  retirement event, survival rule, or notification is added.
- **Strict on the slice-note handoff:** Brainstorming has no `artifact`
  declaration. Before ordering it for `draft_slice_note`, milestone law resolves
  the current run-layout note path and names that path as a required effect in
  the target-free request. Success records the same path on the unit; it never
  inherits a prior Worker's declaration, and subsequent review and
  implementation read the recorded path. This request/handoff rule adds no
  generic result member or presence, byte-change, or freshness gate: the
  Brainstorming effect seam enforces the named effect, Worker keeps its current
  behavior, and ordinary note review still judges it against the current goal
  and skeleton before implementation.
- **Executor effects retain their inherited posture:** Worker calls retain
  their existing at-least-once crash boundary: a crash after provider or
  workspace effects but before the result is durably saved may repeat those
  effects on resume.
  A Brainstorming task succeeds only when the lead's agreed effects called for
  by the target-free request have landed in the writable work area; completing
  its private target or transcript alone is not successful production, and one
  request may affect multiple files. Brainstorming otherwise retains its own
  retry and recovery semantics: one production task spans its bounded session
  and native recovery until terminal success or failure, and a later retry is a
  successor. B2 continuation and `need_rethink` apply only to Worker production.
  Admission or execution may fail before any external effect, and neither
  executor promises exactly-once effects or rollback. Each executor accounting
  record attached to the task contributes once to task and run totals;
  unavailable accounting stays explicitly partial rather than being inferred.
- **Strict destination instruction, bounded enforcement:** when
  `output_directory` is supplied, it is the requested destination for task
  effects, not advice. Admission canonicalizes it inside the writable primary
  workspace, forwards it unchanged as inherited context to the selected
  TaskExecutor, and keeps beneath it every path task machinery derives from
  that field. For Worker, forwarding ends at that executor-context boundary:
  the caller-owned complete request is transported verbatim, and the field is
  not separately injected into physical initial, repair, continuation,
  stabilization, or recovery calls. A request that also calls
  for an effect outside that root is contradictory; the caller must omit the
  field or choose a common containing directory. Readable references outside
  it do not become destinations. When it is absent, effects may land wherever
  the work area and request require.
  Full-access execution means task success is not proof of compliance. Worker
  native claims remain evidence, not confinement, and no generic placement
  failure is synthesized. An out-of-root effect violates the request but may
  survive success, failure, interruption, or recovery. Milestone review may
  reject observed noncompliance; a standalone caller owns stronger acceptance
  and receives no cleanup guarantee. Task-record and evidence stores remain
  unchanged.
- **Observed state, not freshness:** the panel renders the canonical task
  projection returned for the view it is actively polling. The goal imposes no
  time bound: an unselected run or standalone task with no open view need not
  refresh, and closing the panel or losing a successful service, transport, or
  projection fetch may leave displayed state stale. The durable task record is
  authority; the panel is not.

### Boundary and non-goals

- No new scheduler, queue, permission system, sandbox, task retry policy,
  idempotency promise, artifact inventory, or domain taxonomy.
- No task-specific verification policy. Strategy and milestone law continue to
  choose gates and convergence rules.
- Brainstorming is selectable here only for the independent slice-note drafting
  and slice-implementation production tasks. Skeleton drafting, reviews, and
  fixers remain Worker tasks; alternative executors for them are future work.
- Deterministic transitions, shell verification, seals, and reclassification do
  not become tasks. Existing activity and legacy Brainstorming records remain.
- Reference documents may come from inherited readable roots, but the request
  never authorizes effects outside the resolved writable workspace. When
  `output_directory` is supplied, an effect requested outside it is a
  contradiction, not an exception. The instruction does not create filesystem
  isolation. The four additional roots granted to this run are inputs only and
  are never destinations.
- `available_agent_configurations` describes possibilities; it is not a hidden
  selector. The Brainstorming seat shape and its one shared static-resolution
  rule remain executor-private. Add no parallel staffing ledger, profile
  version, inferred actual-staffing projection, or public create-body field.

### Reuse Posture

The affected party is the operator or calling product that currently has only
one producer, especially when a document or strategy needs deliberation. The
harm is repeated unsuitable drafting and review cost; it is exposed whenever
producer choice matters, but is normally reversible before a milestone seals.
The mandate independently requires the choice.

Producer overrides are best-effort current-plan bookkeeping. The existing
non-blocking service write refuses contention. If an accepted write owns the
short between-step handoff, the continuous driver briefly reacquires and
proceeds only when state is unchanged or the existing validator recognizes the
resulting producer-only delta; unrelated durable contention remains refused.
Changed replacement installation uses its supplied plan directly, and existing
event order makes only writes after the latest `slices_updated` active for
review. This is sufficient without replay, stable slice identity, retirement
events, acknowledgement, pause, or notice.

The existing worker scheduling points and full-access call seam,
structured-output validation, immutable milestone history, accounting
aggregation, Brainstorming lifecycle and adapter, resolved work-area and
path-canonicalization checks, whole-workspace review/recovery snapshots, per-call
staffing evidence, activity projections, Worker declaration-first note-path
handoff, run-layout path resolver, attached-rethink continuation state, and
milestone Resume re-entry were checked and will be extended. Neither native
Worker claims nor the snapshots establish causal placement for every requested
effect across full-access execution and recovery. Turning them into a success
boundary would require causal output evidence or filesystem confinement, both
outside this milestone.
One common task-admission boundary serves direct and milestone orders,
including both independent slice-production scheduling points. It canonicalizes
any supplied destination once before the order is frozen; the scheduling points
supply requests, and the selected adapter receives that canonical value without
re-resolving it. The
three continuable Worker kinds carry one identity through
their durable wait and continuation until completion or an existing abandonment
transition; review rethink fails its
origin and any later review is a successor. Resume or other re-entry after
terminal failure preserves that failed record and admits a successor. Existing
call markers gain only a task-id link so all accounting-bearing attempts for one
Worker decision reuse current accounting homes and exclusions without a
parallel ledger or inferred legacy ownership. Current dispatch resolvers remain
authority. The private-target
Brainstorming lifecycle remains discussion authority; one bounded adapter seam
must additionally apply its agreed target-free effects before reporting task
success, without introducing an artifact inventory. For Brainstorming note
drafting, milestone law reuses the run-layout resolver to name and record the
required note effect; Worker keeps its native declaration handoff. This adds no
generic result member or new acceptance/freshness gate. The only new staffing
seam is one Brainstorming-owned rule that resolves the existing private seat
shape for a direct profile-independent order. Documentation, configuration, or
doing nothing cannot provide direct ordering, two independently frozen slice
choices, a durable first-class record, or Brainstorming production. The cheapest
sufficient addition is one generic contract/record layer with two thin adapters,
durable task-id linkage on the existing call marker, two keys on the one
per-slice selection map, a non-blocking best-effort write, sequence-filtered
review projection, bounded reuse of the existing producer-delta validator at a
continuous-run lock handoff, one catalogue configuration schema, reuse of the
note-path handoff, one admission-owned destination canonicalization and
derived-path contract with unchanged propagation through either adapter, that
bounded effect seam, the one shared static-resolution rule, and shared
projections. Its consumers are the driver, local service, panel, and direct API
callers. Build and maintenance
span ten narrow slices; there is no data rewrite, parallel scheduler, task retry
policy, artifact ledger, freshness mechanism, staffing ledger, profile version,
configuration duplicate, or new
sandbox, and independent Worker defaults make the change reversible. Omission
preserves the motivating limitation and its repeated human and model cost;
omitting the schema makes valid Brainstorming choices undiscoverable, omitting
destination validation or propagation leaves the destination instruction unsafe
or undisclosed to the executor, and omitting the linkage leaves Worker failures
and charges unattributable to
their task.

### Planning material disposition

- **Adopt:** the existing worker, Brainstorming, access, accounting, and panel
  seams identified by the frozen mandate.
- **Revise:** the planning question about strategy placement is settled as two
  independent per-slice producer choices, one for note drafting and one for
  implementation, because task execution and gate policy have different
  owners. Resolved staffing is immutable order-time history while each executor
  retains its declared dispatch authority. `output_directory` remains a strict
  request instruction, while task-layer enforcement is limited to admission,
  forwarding to the selected TaskExecutor context, and paths derived from that
  field; executor-wide placement needs causal evidence or confinement outside
  this milestone. Worker derives no production path from the field today and
  gains no parallel provider-call channel for it.
- **Reject:** the live planning copy as authority, any later drift from the
  frozen mandate, and any caller-facing Brainstorming target requirement.

### Planned slices

| id | slice | bootstrap producer | intent |
|---:|---|---|---|
| 1 | Task contracts and catalogue | Worker | Define the common request, self-description, result envelope, and the built-in Worker and Brainstorming entries. |
| 2 | Durable task orders and accounting | Worker | Persist one frozen logical order, including its historical staffing snapshot, and terminal result; at the shared admission boundary, validate and canonicalize any supplied `output_directory` inside the writable primary workspace, freeze and forward that value, and own the common containment contract for paths task machinery derives from it; link existing Worker call/accounting records by task id, preserve partial accounting, and expose one canonical task record without backfilling legacy markers. |
| 3 | Worker executor and default milestone cutover | Worker | Put every current draft, implementation, review, and fixer invocation through the transport-only Worker adapter while preserving call-time staffing, native responses, milestone behavior, and the slice-note `artifact` declaration handoff. Keep the admitted canonical `output_directory` as frozen inherited context without a separate transport. Keep continuable rethink calls under one task through completion or abandonment; fail non-continuable review origins and admit later reviews separately. Refresh live operator amendments and safeguards once per milestone Worker episode, with matched prompt/validation authority, immutable order bytes, static direct orders, and no authority ledger or request rewrite. Keep pre-B6 non-null review hashes as ordinary mismatches and restart supported unbound advanced-family state before dispatch. |
| 4 | Brainstorming executor adapter | Worker | Adapt the common request to the existing independent Brainstorming service, privately satisfy its legacy target need, apply the agreed target-free writable-work-area effects before success, and return its native result and complete accounting. Forward the admitted canonical `output_directory` unchanged and keep Brainstorming paths derived from it beneath it; construct note drafting with no directory or one containing its planned path. Prove profile-backed launch forwards current-profile authority without snapshot pins, profile-independent launch supplies frozen seat pins through the existing create body, and Brainstorming note drafting materializes and records its pre-resolved run-layout path. |
| 5 | Slice producer planning and override | Worker | Add the visible two-key `producer_task_executor` map, independent Worker defaults, and a best-effort `task_kind`-scoped pre-order write. Refuse busy writes, adopt an accepted producer-only delta at the continuous-run handoff, freeze only an admitted task, and let every changed replacement plan discard prior overrides without slice identity or notices. |
| 6 | Brainstorming slice production | Worker | Let the milestone independently order, wait for, and consume Brainstorming note-drafting or implementation tasks. Prove both mixed choices end to end, replace any predecessor note path before ordinary review, preserve target-free multi-file effects, and admit a successor when Resume retries a terminal producer failure. |
| 7 | Standalone task API | Worker | Expose the shared catalogue plus direct order, list, and inspect surfaces under existing project/work-area access, routing direct orders through the shared admission contract. |
| 8 | Task ordering and selection panel | Worker | Show self-described choices, direct ordering, and both independent pre-order slice overrides over the shared API contract. |
| 9 | Task activity projection and chips | Worker | Best-effort render task history, native result/accounting, failed review origins, successors, internal calls, and non-task activity without making chip presence/cardinality an execution guarantee. |
| 10 | Compatibility and cardinality conformance | Worker | Prove old-run defaults, independent drafting/implementation choices and successors without review/fixer spillover, native results, repeated rethink and every abandonment, distinct post-rethink reviews, frozen choices, target-free effects, Worker attribution and legacy exclusions, totals, and durable task cardinality across both TaskExecutors. Prove an out-of-root native claim does not synthesize terminal failure or authorize that effect, while existing partial-effect behavior remains. |

Order: 1 → 2 → 3; 4 follows 1–2; 5 follows 1–3; 6 follows 4–5; 7 follows
2–4; 8 follows 5–7; 9 follows 2 and 7; 10 follows all preceding slices. Every
slice carries focused tests for its own contract; Slice 10 adds cross-surface
end-to-end coverage. Final closure uses the repository's full suite.

## Register 2 — Pinned Facts (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Vocabulary and built-ins | Record/API vocabulary is exactly `task` and `TaskExecutor`. Built-in TaskExecutor ids are `worker` and `brainstorming`; `worker` is the default. | `implementation/milestones/tasks-2/goal.md:21-31,83-90` | touch the shared catalogue and adapters; do-not-introduce a competing job/execution-type vocabulary |
| Producer axis | A new slice plan carries `producer_task_executor` as a map with exactly two independent keys: `draft_slice_note` and `implement`. Each value has `task_executor` and optional executor-specific `configuration`; the planner proposes and the skeleton/panel show both. An absent map or key independently resolves to `worker`. An operator override is best-effort and active only while its current plan remains installed. A changed replacement installs only its own proposals/defaults and makes all prior writes inactive; an exact no-op preserves them. Admission freezes only that task and terminal history remains immutable. | accepted amendments B3 and B8; operator amendment A1 | touch slice planning, replacement installation, current review projection, both production scheduling points, and the task-kind-scoped write; do-not-replay overrides, add slice identity/lineage/notices, queue busy writes, cross-freeze choices, mutate admitted history, or select skeleton/review/fixer executors from this map |
| Order envelope | An order has exact members `task_executor`, `request`, and optional executor-specific `configuration`. The durable record freezes the resolved configuration, order-time staffing snapshot, and execution context; these do not alter the common request shape. The staffing snapshot is immutable history, not automatically a dispatch input. | `implementation/milestones/tasks-2/goal.md:73-81,126-160`; accepted amendment B1 | touch order validation and the one durable record; do-not-put executor-specific fields into the common request or use the snapshot as an undeclared runtime fallback |
| Common request | Exact members are `work_area`, `request`, `context`, ordered `reference_documents`, and optional `output_directory`. `work_area` and `output_directory` are inherited execution context. Worker admission retains the complete caller-owned initial prompt verbatim; later milestone Worker episodes may append the single driver-owned live-authority block without rewriting the durable request. Direct orders remain static. There is no artifact target or domain taxonomy. | `implementation/milestones/tasks-2/goal.md:126-152`; accepted amendments B5 and B6 | touch the generic request validator, Worker episode boundary, and adapters; do-not-expose Brainstorming `target_path`, re-resolve caller authority inside a TaskExecutor, add a second durable request form, or add a parallel `output_directory` channel |
| Self-description | Every catalogue entry has exact members `id`, `name`, `description`, `operating_mode`, `usage_examples`, `available_agent_configurations`, and `configuration_schema`; each usage example is under ten words and staffing composes with model profiles. `configuration_schema` is the sole order-configuration descriptor: Worker exposes `{}`, while Brainstorming exposes exactly `max_rounds: {type: "integer", minimum: 1, default: 10}` and `closure_policy: {type: "choice", choices: ["unanimity", "majority"], default: "unanimity"}`. Available agent configurations remain descriptive, not a selector. | `implementation/milestones/tasks-2/goal.md:91-105,154-160`; accepted amendment B1 | touch one catalogue, its order validator, and API/panel consumers; do-not-duplicate defaults or choices, duplicate model-profile definitions, or infer an order choice from descriptive staffing configurations |
| Runtime staffing authority | Worker uses current-profile resolution when attached, otherwise configured defaults read when its call begins. Profile-backed Brainstorming builds its launch seats from the then-current profile and preserves the current-profile locator for per-dispatch resolution; neither path consumes the order snapshot. Direct profile-independent Brainstorming freezes complete Initial Position, Contrary Position, and Dante pins resolved from configured family order, model defaults, and executable availability. The adapter supplies those pins through the existing create body; session admission validates and binds them without rotation or replacement. Existing executor activity is the sole evidence of actual call staffing. | accepted amendment B1; `orchestrator/driver.py:455-594,2733-2788`; `orchestrator/brainstorming_lifecycle.py:629-686,2326-2423` | touch the two adapters and one Brainstorming-owned static resolver; do-not-add a staffing ledger, profile version, inferred projection, silent restaffing, or public seat-selection field |
| Task result | Exact generic members are `status` (`success` or `failure`), `reason` (required on failure), `duration_s`, `token_usage`, `token_usage_partial`, `cost` (`api_usd`, `real_usd`), `cost_partial`, and opaque `native_result`. Partial figures survive failure. Worker `need_rethink` is never success; failure records the most specific terminal cause and preserves its request and finding in the native result, while Brainstorming owns any session reference. | `implementation/milestones/tasks-2/goal.md:105-111,227-229`; `orchestrator/state.py:1874-1936`; accepted amendment B2 | touch the generic result validator/record and caller adapters; do-not-flatten, reinterpret, or discard native results or duplicate Brainstorming references in free text |
| Logical cardinality and execution posture | One admitted scheduling decision creates one task id and one frozen durable task record; a terminal record has exactly one immutable success/failure result. Its activity/chip projection is best-effort bookkeeping. Worker tasks for `draft_slice_note`, `implement`, and `fix_findings` retain identity through attached discussion, continuation, and repeated rethink until completion or an existing abandonment. `review_round` and `delta_review` fail their help-seeking origins and later reviews use successor tasks. Brainstorming production spans its bounded session and native recovery; later retry is a successor. Worker accounting-bearing attempts link through the durable pre-dispatch marker; unstamped legacy/non-task activity is never inferred or backfilled, and existing homes prevent duplicate aggregation. | operator amendment A1; accepted amendments B2 and B3 | touch scheduling identity, call-marker linkage, terminal routing, best-effort projection, and accounting attribution; do-not-apply Worker continuation to Brainstorming, reopen terminal tasks, merge reviews, infer legacy ownership, or add liveness, exactly-once, chip guarantees, or duplicate accounting |
| Brainstorming order choices | Exact configurable names are `max_rounds` and `closure_policy`; their valid shapes, choices, and initial defaults `10` and `unanimity` come from the catalogue's `configuration_schema`. An omitted `configuration` or omitted member uses that default; supplied members are validated against the same schema. The resolved values and any pre-order caller changes are visible, frozen alongside the staffing snapshot, and passed unchanged to the existing service. Staffing dispatch authority follows the separate pinned fact above. | `implementation/milestones/tasks-2/goal.md:154-160,221-223`; `orchestrator/contracts.py:87-93`; `orchestrator/brainstorming_milestone.py:419-446`; accepted amendment B1 | touch the shared schema validator, Brainstorming adapter, and catalogue consumers; do-not-copy defaults or choices, infer majority/tie-break, or surface its private target |
| Milestone task boundaries | Slice-note drafting and implementation are separate selectable production tasks, each with its own request, id, frozen order, result, accounting, and best-effort chip projection. Skeleton drafting, each fixer invocation, and each whole-artifact or delta review invocation remain Worker tasks; neither slice selection affects them. A rethink handoff never merges its failed review origin with a later fresh review, and B2 continuation applies only to Worker production. The enclosing review/fix cycle is never a task. | operator amendment A1; accepted amendments B2 and B3 | touch both slice-production scheduling points and current Worker task references; do-not-spill selection into skeleton/review/fixer work or move sequencing, invalidation, caps, review convergence, or sealing into TaskExecutors |
| Default compatibility and live authority | The milestone builds and admits today’s complete initial prompt, including destination context that work needs before ordering; Worker returns the native result unchanged. Each milestone Worker episode takes one live operator-amendment/safeguard snapshot, uses it for both prompt authority and safeguard validation, and appends one authority block on later episodes without rewriting the order. Repair and in-place retry inherit the episode snapshot; a fresh stabilization or crash redispatch refreshes, while a validated durable carrier does not. Amendment authority follows durable source, not a payload label. The task's frozen strategy owns post-result review deferral; attached Brainstorming separately reads current project context at session start. Whole-review evidence uses the existing hash form over immutable candidate/scope/ordered-command evidence. A non-null pre-B6 authority-coupled hash is an ordinary mismatch; no translation or backfill occurs. At review entry, absent binding plus advanced family progress restarts at family zero before dispatch, while absent binding at family zero binds and continues. Pre-seal and seal recovery require the matching binding and matching effective clean rounds. The separately frozen `output_directory` reaches the Worker TaskExecutor as inherited routing context but is never re-injected into provider calls. An absent producer map or key independently defaults to Worker, so old/default and resumable runs retain transitions, gates, review/fix behavior, aggregate accounting, and current per-dispatch staffing authority without migration. Worker drafting keeps its valid `artifact` declaration as the unit note path. | `implementation/milestones/tasks-2/goal.md:128-136,230-234`; `orchestrator/state.py:720-760`; accepted amendments B1, B3, B5, B6, and B7 | touch the milestone episode boundary, existing review-entry comparison, selection default, and declaration handoff; do-not-reconstruct/translate fingerprints, rebuild or rewrite the admitted prompt, refresh direct orders, change frozen strategy/battery/roots/destination, add an authority ledger/cache/provider lookup, or require migration |
| Public HTTP surface | Exact routes are `GET /api/task-executors`, `GET /api/tasks`, `POST /api/tasks`, `GET /api/tasks/<id>`, and `POST /api/runs/<id>/slices/<slice-id>/producer`. `GET /api/task-executors` returns the shared catalogue including each exact `configuration_schema`; both ordering writes validate their optional `configuration` against that same schema. The producer write requires exact `task_kind` (`draft_slice_note` or `implement`), plus `task_executor` and optional `configuration`; missing or other task kind is `invalid_task_request` (400). Other errors are `unknown_task_executor` (400), `task_selection_frozen` (409), `task_update_busy` (409), and `task_unavailable` (503). A busy producer write is refused rather than queued. Inability to resolve a direct profile-independent Brainstorming binding is `task_unavailable` before task admission, while later availability loss or session refusal becomes the admitted task's durable failure. | this skeleton, Planned slices 5, 7, and 8; accepted amendments B1, B3, and B8; operator amendment A1 | touch shared service/access and panel consumers; do-not-create separate routes per task kind, queue/supervise bookkeeping, duplicate configuration authority, cross-freeze selections, silently restaff, or expose raw operational errors |
| Access and effects | Reuse the resolved primary/additional-root context and existing project access. References may be read where granted. A supplied `output_directory` is the requested destination for task effects; requesting an effect outside it is contradictory. Admission canonicalizes the directory inside the writable primary workspace, forwards it unchanged to either TaskExecutor as inherited context, and keeps beneath it paths task machinery derives from the field. For Worker, that forwarding creates no separate physical-call channel or current production path derived from the field; the caller-owned complete request remains the provider instruction. Full-access executor success does not prove compliance: Worker native claims are evidence only, and an out-of-root effect remains a request violation even though it does not by itself change terminal status and may survive any outcome. References outside the writable primary workspace are never destinations. Brainstorming success still requires every effect named by the target-free request rather than only its private target or transcript, without claiming universal placement proof. For Brainstorming slice-note drafting, milestone law resolves and records the current run-layout note path, requires that effect in the request, and pairs it with no `output_directory` or one containing that path; it never inherits a predecessor Worker's declaration. This is request/handoff construction, not a generic result field or additional acceptance gate. | `implementation/milestones/tasks-2/goal.md:112-152,197-203`; `orchestrator/README.md:508-511`; `orchestrator/runners.py:1973-1992`; `orchestrator/gitops.py:944-958`; `orchestrator/brainstorming_coordination.py:546-574,696-789`; `orchestrator/driver.py:5495-5520,6707-6714`; `orchestrator/ledgers.py:72-76`; accepted amendments B3, B4, and B5 | touch common task-admission destination validation/canonicalization, unchanged TaskExecutor-context propagation, containment of paths genuinely derived from the field, Brainstorming effect application, and the existing note-path handoff; do-not-add a Worker prompt directive, serializer, environment variable, task-id lookup, `output_directory_violation`, generic placement gate, permissions, sandbox, causal effect evidence, exhaustive effect inventory, selective rollback, caller target, presence/byte-change/freshness gate, or edits to Life, Agent99, LPC, or Tutor additional roots |
| Non-task activity | Deterministic transitions, shell verification, seals, post-result reclassification, attached or pre-existing unwrapped Brainstorming activity, and retired `seal_half` waits remain non-task records. Their chip/activity views are best-effort. They receive no Worker task stamp or backfill, and no parallel public task-event vocabulary is added. | operator amendment A1; accepted amendment B2 | touch additive task references/projections; do-not-remove or relabel durable activity, infer task ownership, guarantee chips, or double-count accounting |
| Verification | Each slice has focused behavioral tests. Slice 1 pins the exact Worker-empty and Brainstorming configuration schemas. Slices 7 and 8 prove the API and panel share that schema. Slice 2 proves shared destination admission and the derived-path primitive. Slice 3 proves the Worker path cannot bypass admission, the order and TaskExecutor receive the canonical destination unchanged, and no separate destination transport appears. It also proves live authority once per initial, crash/Resume, rethink-continuation, legacy-continuation, and fresh stabilization episode; a whole-review Resume retains its open task while completed approvals remain bound only to immutable evidence; matched safeguard prompt/validation and repair inheritance; complete empty operator-set revocation versus incomplete-read preservation; source-derived amendment tiers and append-only accepted design amendments; current project context for attached design discussions; frozen strategy-owned result routing; pre-dispatch standing-law failure; authority- and profile-free consumption of validated carriers; ordinary seal recovery without current evidence; advanced unbound review progress restarting before dispatch and then sealing after one fresh pass; and unchanged order bytes, frozen strategy/battery, task id, and accounting. Slice 3 retains staffing, declaration-handoff, continuation/abandonment, review-successor, attribution, legacy, reclassification, and retired-seal proofs. Slice 5 additionally proves current-plan-local overrides, an accepted-write lock handoff without driver termination, immutable replacement events during live catch-up, and the B8 no-op/rejection/default cases. Slices 4–10 prove Brainstorming staffing/effects, selection, mixed producers, public surfaces, chips, old-run defaults, successors, and cross-surface accounting without a universal placement claim. Existing lifecycle tests remain lower-level proof. Closure additionally runs exactly `python3 -m unittest discover -s orchestrator/tests -t .`. | `implementation/milestones/tasks-2/goal.md:112-160,191-203,230-240`; `orchestrator/README.md:522-548`; accepted amendments B1–B8 | touch common admission, the milestone Worker episode boundary, existing review-entry comparison, selection/default/handoff, adapter/effects, Resume/compatibility/cardinality/attribution tests, and existing lifecycle coverage; do-not-add override identity/replay/notice, a destination provider channel, fingerprint translation, prompt parser/rebuilder, authority ledger/cache/provider lookup, alternate retry/recovery policy, generic placement gate, causal effect evidence, freshness, staffing proof system, or narrower final suite |

### Question Battery

| question | answer | evidence |
|---|---|---|
| victim | Operators and calling products need independent drafting/implementation choices and discoverable Brainstorming controls. A stale override replay can select a producer from an earlier plan, while an accepted bookkeeping write can stop the one-shot run if its lock handoff is treated as unrelated contention. Losing bookkeeping alone harms nobody and changes no acceptance, seal, or result. If destination admission or forwarding is omitted, an outside or ambiguous supplied destination can be accepted before chargeable execution; full-access placement remains best-effort after that boundary. | accepted amendments B3, B4, B5, and B8 |
| machinery | Add the generic task contract, durable scheduling record, existing Worker-marker link, thin adapters, two-key producer map, shared projections, one private Brainstorming staffing rule, and the already-authorized live-authority/review guards. Reuse the existing producer-delta validator for the bounded continuous-run lock handoff, reuse existing events to scope overrides after the latest plan update, and detach replacement-event payloads from mutable live plan objects. Reuse one common destination canonicalization and derived-path primitive; add no identity, replay, notice, provider channel, placement gate, or proof. | accepted amendments B1–B8 |
| consumers | Verified current consumers are the milestone driver’s draft/implement, fixer, and review scheduling points, the durable run summary, and the local service/panel chronology. Operators and future calling products consume the new direct API; no unverified external code consumer is assumed. | `orchestrator/driver.py:5469-5528,7072-7115,8831-8882`; `orchestrator/state.py:2315-2504`; `orchestrator/static/panel.html:2820-3052`; `implementation/milestones/tasks-2/goal.md:71-81` |
| cheaper_alternative | Reuse current scheduling, Worker call/repair, authority rendering, durable carriers, review comparison, accounting, event order, path containment, and note handoff. Refuse busy producer writes; at an accepted-write handoff, briefly reacquire and proceed only for the already-valid producer delta; install replacements directly; and detach their history payloads. The caller-owned initial Worker request already carries model-visible destination instruction; a second channel still would not prove placement. Identity/notification, confinement, causal evidence, and cleanup would add lifecycle cost without improving the authorized boundary. | accepted amendments B1–B8 |
| cost | Build remains ten bounded slices with no migration. Producer bookkeeping adds two values, one non-blocking write, one bounded reuse of existing delta validation at the continuous-run handoff, sequence filtering, and detached history copying; destination handling reuses one admission/derived-path primitive and adds no provider channel or placement gate. Existing task links, episode authority, and review guard retain their prior cost. | this skeleton; accepted amendments B1–B8 |
| threat_model | Validate closed task/result/configuration shapes, inherited project access, canonical destination containment, and paths task machinery derives from the field. The trusted caller owns free-text destination intent. `output_directory` is a strict request instruction but not a security or success-proof boundary: tasks add no filesystem confinement, causal effect evidence, physical Worker transport channel, or cleanup layer. | accepted amendments B4 and B5; existing project access and contract validators |
| enforceability | Shared validators enforce value shapes and destination admission; project access retains authority. Producer writes are best-effort and non-blocking; the continuous driver proceeds after a contested handoff only when state is unchanged or the existing validator recognizes the resulting producer-only delta. Replacement plans are self-contained, detached replacement events preserve append-only catch-up history, and event order scopes review overrides. Episode authority, review restart/seal predicates, admitted task history, staffing evidence, Brainstorming effects, and accounting retain their existing authorities. Destination placement beyond admission and task-derived paths remains best-effort. | accepted amendments B1–B8 |
