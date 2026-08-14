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
that respective task is ordered. There is no hidden runtime routing. Later
TaskExecutors join the same contract without creating a new milestone flow.

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
  recovering. Throughout, it has one canonical task-chip projection; if it
  becomes terminal, it has exactly one success/failure result.
  Executor-internal calls remain inspectable evidence, not additional tasks.
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
  any later review has a new task id, frozen order, record, and chip, with the
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
  receives the exact prompt the milestone already builds and returns the native
  response unchanged. An absent producer map or either absent task-kind key
  independently means Worker, including for existing resumable runs. Worker
  slice-note drafting keeps its valid native `artifact` declaration as the
  unit's note path, including legitimate non-default paths.
  Milestone sequencing, review/fix cycles, verification, seals, and totals keep
  their present behavior.
- **Strict structural parity:** the API and panel use one catalogue and one
  canonical task projection; this does not promise that the panel is current.
  Each catalogue entry carries the same machine-readable executor-configuration
  schema used to validate orders, including visible defaults and finite choices;
  the panel derives its controls from that schema rather than copying them.
  The skeleton and panel expose both prospective slice choices. A slice-level
  producer write names exactly `draft_slice_note` or `implement` and changes
  only that still-unordered choice; admission freezes only that task. A terminal
  failure never reopens or mutates the task. An explicit retry, or the existing
  milestone Resume re-entering its failed scheduling point, admits a successor
  under that task kind's then-visible choice while retaining immutable history.
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
  workspace, forwards it to the selected TaskExecutor, and keeps beneath it
  every path task machinery derives from that field. A request that also calls
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

- No new scheduler, queue, permission system, sandbox, retry policy,
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
re-resolving it. The three continuable Worker kinds carry one identity through
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
per-slice selection map, one catalogue configuration schema, reuse of the
note-path handoff, one admission-owned destination canonicalization and
derived-path contract with unchanged propagation through either adapter, that
bounded effect seam, the one shared static-resolution rule, and shared
projections. Its consumers are the driver, local service, panel, and direct API
callers. Build and maintenance
span ten narrow slices; there is no data rewrite, parallel scheduler, retry
policy, artifact ledger, freshness mechanism, staffing ledger, profile version,
configuration duplicate, or new
sandbox, and independent Worker defaults make the change reversible. Omission
preserves the motivating limitation and its repeated human and model cost;
omitting the schema makes valid Brainstorming choices undiscoverable, omitting
destination validation or
propagation leaves the destination instruction unsafe or undisclosed to the
executor,
and omitting the linkage leaves Worker failures and charges unattributable to
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
  forwarding, and paths derived from that field; executor-wide placement needs
  causal evidence or confinement outside this milestone.
- **Reject:** the live planning copy as authority, any later drift from the
  frozen mandate, and any caller-facing Brainstorming target requirement.

### Planned slices

| id | slice | bootstrap producer | intent |
|---:|---|---|---|
| 1 | Task contracts and catalogue | Worker | Define the common request, self-description, result envelope, and the built-in Worker and Brainstorming entries. |
| 2 | Durable task orders and accounting | Worker | Persist one frozen logical order, including its historical staffing snapshot, and terminal result; at the shared admission boundary, validate and canonicalize any supplied `output_directory` inside the writable primary workspace, freeze and forward that value, and own the common containment contract for paths task machinery derives from it; link existing Worker call/accounting records by task id, preserve partial accounting, and expose one canonical task record without backfilling legacy markers. |
| 3 | Worker executor and default milestone cutover | Worker | Put every current draft, implementation, review, and fixer invocation through the transport-only Worker adapter while preserving call-time staffing, native responses, milestone behavior, and the slice-note `artifact` declaration handoff. Forward the admitted canonical `output_directory` unchanged and keep Worker paths derived from it beneath it without treating native claims as placement proof. Keep continuable rethink calls under one task through completion or abandonment; fail non-continuable review origins and admit later reviews separately. Prove a profile-less default changed after admission governs the call while the snapshot stays unchanged. |
| 4 | Brainstorming executor adapter | Worker | Adapt the common request to the existing independent Brainstorming service, privately satisfy its legacy target need, apply the agreed target-free writable-work-area effects before success, and return its native result and complete accounting. Forward the admitted canonical `output_directory` unchanged and keep Brainstorming paths derived from it beneath it; construct note drafting with no directory or one containing its planned path. Prove profile-backed launch forwards current-profile authority without snapshot pins, profile-independent launch supplies frozen seat pins through the existing create body, and Brainstorming note drafting materializes and records its pre-resolved run-layout path. |
| 5 | Slice producer planning and override | Worker | Add the visible two-key `producer_task_executor` map, independent Worker defaults, and a `task_kind`-scoped pre-order operator write that freezes only the selected drafting or implementation task. |
| 6 | Brainstorming slice production | Worker | Let the milestone independently order, wait for, and consume Brainstorming note-drafting or implementation tasks. Prove both mixed choices end to end, replace any predecessor note path before ordinary review, preserve target-free multi-file effects, and admit a successor when Resume retries a terminal producer failure. |
| 7 | Standalone task API | Worker | Expose the shared catalogue plus direct order, list, and inspect surfaces under existing project/work-area access, routing direct orders through the shared admission contract. |
| 8 | Task ordering and selection panel | Worker | Show self-described choices, direct ordering, and both independent pre-order slice overrides over the shared API contract. |
| 9 | Task activity projection and chips | Worker | Show exactly one task chip and its native result/accounting, including immutable failed review origins and distinct successors, while retaining inspectable internal calls and every non-task activity chip. |
| 10 | Compatibility and cardinality conformance | Worker | Prove old-run defaults, independent drafting/implementation choices and successors without review/fixer spillover, native results, repeated rethink and every abandonment, distinct post-rethink reviews, frozen choices, target-free effects, Worker attribution and legacy exclusions, totals, and task/chip cardinality across both TaskExecutors. Prove an out-of-root native claim does not synthesize terminal failure or authorize that effect, while existing partial-effect behavior remains. |

Order: 1 → 2 → 3; 4 follows 1–2; 5 follows 1–3; 6 follows 4–5; 7 follows
2–4; 8 follows 5–7; 9 follows 2 and 7; 10 follows all preceding slices. Every
slice carries focused tests for its own contract; Slice 10 adds cross-surface
end-to-end coverage. Final closure uses the repository's full suite.

## Register 2 — Pinned Facts (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Vocabulary and built-ins | Record/API vocabulary is exactly `task` and `TaskExecutor`. Built-in TaskExecutor ids are `worker` and `brainstorming`; `worker` is the default. | `implementation/milestones/tasks-2/goal.md:21-31,83-90` | touch the shared catalogue and adapters; do-not-introduce a competing job/execution-type vocabulary |
| Producer axis | A new slice plan carries `producer_task_executor` as a map with exactly two independent keys: `draft_slice_note` and `implement`. Each value has `task_executor` and optional executor-specific `configuration`; the planner proposes and the skeleton/panel show both. An absent map or key independently resolves to `worker`. A visible operator override is legal only before that task kind's order; admission freezes only that task. A terminal task stays immutable, while retry or Resume reads the then-visible selection for its successor. | `implementation/milestones/tasks-2/goal.md:162-189,195-196`; accepted amendment B3 | touch slice planning, run projection, both production scheduling points, and the task-kind-scoped override; do-not-route silently, cross-freeze the two choices, mutate a terminal task, or select skeleton/review/fixer executors from this map |
| Order envelope | An order has exact members `task_executor`, `request`, and optional executor-specific `configuration`. The durable record freezes the resolved configuration, order-time staffing snapshot, and execution context; these do not alter the common request shape. The staffing snapshot is immutable history, not automatically a dispatch input. | `implementation/milestones/tasks-2/goal.md:73-81,126-160`; accepted amendment B1 | touch order validation and the one durable record; do-not-put executor-specific fields into the common request or use the snapshot as an undeclared runtime fallback |
| Common request | Exact members are `work_area`, `request`, `context`, ordered `reference_documents`, and optional `output_directory`. `work_area` is the already-resolved inherited execution context. There is no artifact target or domain taxonomy. | `implementation/milestones/tasks-2/goal.md:126-152` | touch the generic request validator and adapters; do-not-expose Brainstorming `target_path` or re-resolve caller authority inside a TaskExecutor |
| Self-description | Every catalogue entry has exact members `id`, `name`, `description`, `operating_mode`, `usage_examples`, `available_agent_configurations`, and `configuration_schema`; each usage example is under ten words and staffing composes with model profiles. `configuration_schema` is the sole order-configuration descriptor: Worker exposes `{}`, while Brainstorming exposes exactly `max_rounds: {type: "integer", minimum: 1, default: 10}` and `closure_policy: {type: "choice", choices: ["unanimity", "majority"], default: "unanimity"}`. Available agent configurations remain descriptive, not a selector. | `implementation/milestones/tasks-2/goal.md:91-105,154-160`; accepted amendment B1 | touch one catalogue, its order validator, and API/panel consumers; do-not-duplicate defaults or choices, duplicate model-profile definitions, or infer an order choice from descriptive staffing configurations |
| Runtime staffing authority | Worker uses current-profile resolution when attached, otherwise configured defaults read when its call begins. Profile-backed Brainstorming builds its launch seats from the then-current profile and preserves the current-profile locator for per-dispatch resolution; neither path consumes the order snapshot. Direct profile-independent Brainstorming freezes complete Initial Position, Contrary Position, and Dante pins resolved from configured family order, model defaults, and executable availability. The adapter supplies those pins through the existing create body; session admission validates and binds them without rotation or replacement. Existing executor activity is the sole evidence of actual call staffing. | accepted amendment B1; `orchestrator/driver.py:455-594,2733-2788`; `orchestrator/brainstorming_lifecycle.py:629-686,2326-2423` | touch the two adapters and one Brainstorming-owned static resolver; do-not-add a staffing ledger, profile version, inferred projection, silent restaffing, or public seat-selection field |
| Task result | Exact generic members are `status` (`success` or `failure`), `reason` (required on failure), `duration_s`, `token_usage`, `token_usage_partial`, `cost` (`api_usd`, `real_usd`), `cost_partial`, and opaque `native_result`. Partial figures survive failure. Worker `need_rethink` is never success; failure records the most specific terminal cause and preserves its request and finding in the native result, while Brainstorming owns any session reference. | `implementation/milestones/tasks-2/goal.md:105-111,227-229`; `orchestrator/state.py:1874-1936`; accepted amendment B2 | touch the generic result validator/record and caller adapters; do-not-flatten, reinterpret, or discard native results or duplicate Brainstorming references in free text |
| Logical cardinality and execution posture | One admitted scheduling decision creates one task id, one frozen durable task record, and one canonical task-chip projection; a terminal record has exactly one immutable success/failure result. Worker tasks for `draft_slice_note`, `implement`, and `fix_findings` retain that identity through attached discussion, continuation, and repeated rethink until completion or an existing transition durably abandons continuation. Recoverable durable state may remain non-terminal; abandonment fails it and later re-entry admits a successor without adding a timeout or recovery rule. `review_round` and `delta_review` are not continuable: validated `need_rethink` fails the origin with its native result, raw evidence, and complete known accounting; attached discussion is non-task activity and any later review is a new task whose handoff is context only. A Brainstorming production task spans its bounded session and native recovery until terminal success/failure; later retry admits a successor. Retired `seal_half` waits remain legacy non-task activity. Every accounting-bearing Worker attempt for the scheduling decision belongs to its task through the durable pre-dispatch call marker; markers without a task id remain legacy and are never inferred or backfilled. Existing accounting homes/exclusions ensure each charge contributes once to its task and once to existing unit/run totals; partial means evidence is missing. Attached Brainstorming and post-result reclassification are unstamped. Executor-internal Brainstorming participant calls remain evidence, not tasks. | `implementation/milestones/tasks-2/goal.md:33-37,39-48,172-178,191-203,224-234`; `orchestrator/state.py:1086-1173,2224-2250`; `orchestrator/driver.py:4078-4130,4594-5031,7990-8050,8831-8890`; `orchestrator/README.md:543-548`; accepted amendments B2 and B3 | touch scheduling-point task identity, call-marker linkage, terminal routing, projection, and accounting attribution; do-not-apply Worker rethink continuation to Brainstorming, reopen terminal tasks, merge fresh reviews, infer legacy ownership, stamp attached Brainstorming/reclassification, or add liveness, exactly-once, duplicate chips, or duplicate aggregate accounting |
| Brainstorming order choices | Exact configurable names are `max_rounds` and `closure_policy`; their valid shapes, choices, and initial defaults `10` and `unanimity` come from the catalogue's `configuration_schema`. An omitted `configuration` or omitted member uses that default; supplied members are validated against the same schema. The resolved values and any pre-order caller changes are visible, frozen alongside the staffing snapshot, and passed unchanged to the existing service. Staffing dispatch authority follows the separate pinned fact above. | `implementation/milestones/tasks-2/goal.md:154-160,221-223`; `orchestrator/contracts.py:87-93`; `orchestrator/brainstorming_milestone.py:419-446`; accepted amendment B1 | touch the shared schema validator, Brainstorming adapter, and catalogue consumers; do-not-copy defaults or choices, infer majority/tie-break, or surface its private target |
| Milestone task boundaries | Slice-note drafting and implementation are separate selectable production tasks, each with its own request, id, frozen order, result, accounting, and chip. Skeleton drafting, each fixer invocation, and each whole-artifact or delta review invocation remain Worker tasks; neither slice selection affects them. A rethink handoff never merges its failed review origin with a later fresh review, and B2 continuation applies only to Worker production. The enclosing review/fix cycle is never a task. | `implementation/milestones/tasks-2/goal.md:39-48,172-178`; accepted amendments B2 and B3 | touch both slice-production scheduling points and current Worker task references; do-not-spill selection into skeleton/review/fixer work or move sequencing, invalidation, caps, review convergence, or sealing into TaskExecutors |
| Default compatibility | The milestone builds today’s complete prompt; Worker transports it verbatim and returns the native result unchanged. An absent producer map or key independently defaults to Worker, so old/default and existing resumable runs retain transitions, gates, review/fix behavior, aggregate accounting, and current per-dispatch staffing authority without migration. Worker drafting keeps its valid `artifact` declaration as the unit note path, preserving legacy layouts and legitimate non-default paths. A profile-less default changed after task admission but before the Worker call governs that call without rewriting the order snapshot. | `implementation/milestones/tasks-2/goal.md:128-136,230-234`; `orchestrator/state.py:720-760`; `orchestrator/driver.py:455-594,2733-2788,5469-5528,5700-5798,6707-6714`; accepted amendments B1 and B3 | touch the transport, selection-default, and declaration handoff seams plus compatibility tests; do-not-add a second prompt builder, pin dispatches from the snapshot, replace valid Worker paths, or require migration |
| Public HTTP surface | Exact routes are `GET /api/task-executors`, `GET /api/tasks`, `POST /api/tasks`, `GET /api/tasks/<id>`, and `POST /api/runs/<id>/slices/<slice-id>/producer`. `GET /api/task-executors` returns the shared catalogue including each exact `configuration_schema`; both ordering writes validate their optional `configuration` against that same schema. The producer write requires exact `task_kind` (`draft_slice_note` or `implement`), plus `task_executor` and optional `configuration`; missing or other task kind is `invalid_task_request` (400). Other admission errors are `unknown_task_executor` (400), `task_selection_frozen` (409), and `task_unavailable` (503). The write changes only that still-unordered selection. Inability to resolve a direct profile-independent Brainstorming binding is `task_unavailable` before task admission, while later availability loss or session refusal becomes the admitted task's durable failure. | `implementation/milestones/tasks-2/goal.md:73-81,154-160,214-229`; this skeleton, Planned slices 5, 7, and 8; accepted amendments B1 and B3 | touch shared service/access and panel consumers; do-not-create separate routes per task kind, duplicate configuration authority, cross-freeze selections, silently restaff, or expose raw operational errors |
| Access and effects | Reuse the resolved primary/additional-root context and existing project access. References may be read where granted. A supplied `output_directory` is the requested destination for task effects; requesting an effect outside it is contradictory. Admission canonicalizes the directory inside the writable primary workspace, forwards it to either executor, and keeps beneath it paths task machinery derives from the field. Full-access executor success does not prove compliance: Worker native claims are evidence only, and an out-of-root effect remains a request violation even though it does not by itself change terminal status and may survive any outcome. References outside the writable primary workspace are never destinations. Brainstorming success still requires every effect named by the target-free request rather than only its private target or transcript, without claiming universal placement proof. For Brainstorming slice-note drafting, milestone law resolves and records the current run-layout note path, requires that effect in the request, and pairs it with no `output_directory` or one containing that path; it never inherits a predecessor Worker's declaration. This is request/handoff construction, not a generic result field or additional acceptance gate. | `implementation/milestones/tasks-2/goal.md:112-152,197-203`; `orchestrator/README.md:508-511`; `orchestrator/runners.py:1973-1992`; `orchestrator/gitops.py:944-958`; `orchestrator/brainstorming_coordination.py:546-574,696-789`; `orchestrator/driver.py:5495-5520,6707-6714`; `orchestrator/ledgers.py:72-76`; accepted amendments B3 and B4 | touch common task-admission destination validation/canonicalization, unchanged propagation through both adapters, containment of paths derived from the field, Brainstorming effect application, and the existing note-path handoff; do-not-add `output_directory_violation`, a generic placement gate, permissions, a sandbox, causal effect evidence, an exhaustive effect inventory, selective rollback, a caller target, a presence/byte-change/freshness gate, or edits to Life, Agent99, LPC, or Tutor additional roots |
| Non-task activity | Deterministic transitions, shell verification, seals, post-result reclassification, attached or pre-existing unwrapped Brainstorming activity, and retired `seal_half` waits retain their records/chips. They receive no Worker task stamp or backfill. Task records are canonical; no parallel public task-event vocabulary is added. | `implementation/milestones/tasks-2/goal.md:201-210`; `orchestrator/state.py:2224-2314`; `orchestrator/static/panel.html:2906-3052`; accepted amendment B2 | touch additive task references/projections; do-not-remove, relabel as tasks, infer task ownership, or double-count existing non-task activity |
| Verification | Each slice has focused behavioral tests. Slice 1 pins the exact Worker-empty and Brainstorming configuration schemas. Slices 7 and 8 prove the API exposes that shared schema and the panel derives editable round/policy controls and defaults from it without copied configuration authority. Slice 2 proves the shared admission seam rejects a destination outside the writable primary workspace, canonicalizes a valid destination once before freezing the order, and exposes that same value to either executor. Slices 3 and 4 each exercise its executor's ordering path and prove that admission validation and canonicalization cannot be bypassed: the path rejects an outside destination, canonicalizes a valid destination before freezing, forwards the admitted value unchanged, keeps its own paths derived from the field beneath it, and preserves current work-area behavior when the field is omitted. These per-adapter proofs neither duplicate canonicalization authority nor make a universal effect-placement claim. Slice 3 also proves a profile-less Worker default changed after admission governs dispatch while the snapshot stays unchanged; unchanged Worker/default drafting preserves its declaration-first note-path handoff; continuable Worker success and repeated rethink retain one task; every existing abandonment fails it and re-entry creates an immutable successor; failed review origins retain native/raw/accounting evidence while later reviews use distinct ids/chips and no-clobber names; and retired `seal_half` activity remains outside tasks. Slice 4 proves profile-backed Brainstorming forwards the locator without snapshot pins, profile-independent Brainstorming supplies frozen pins, a successful adapter result requires effects named by the request rather than only its private target, and Brainstorming note drafting uses a compatible directory choice while materializing and recording its planned run-layout path. Slice 5 proves both proposed keys are visible, independently writable and frozen, with absent-key Worker defaults and exact `task_kind` validation. Slice 6 proves both mixed producer choices end to end, replaces any predecessor note path before ordinary review, and proves that Resume after terminal producer failure admits a successor from only the corresponding current selection while preserving the failed task. Slices 2, 3, 9, and 10 prove Worker attribution across origin/continuation, repair or malformed attempts, interruption/stabilization, unaccepted calls, in-call failure classification, and recovery; legacy markers and reclassification remain excluded. Slice 10 also proves an out-of-root native claim alone neither synthesizes terminal failure nor authorizes the effect, while preserving partial-effect behavior. It repeats old-run defaults, independent producer successors with no skeleton/review/fixer spillover, continuation, abandonment, review-successor, terminal-successor, ownership, and exclusion proofs across task boundaries and asserts one task record, one chip, and one task contribution per scheduling decision without re-adding its subtotal to existing unit/run totals. Existing lifecycle tests remain the lower-level behavioral proof. Closure additionally runs exactly `python3 -m unittest discover -s orchestrator/tests -t .` and proves the completion cases in the mandate. | `implementation/milestones/tasks-2/goal.md:112-160,191-203,230-240`; `orchestrator/brainstorming_coordination.py:546-574,696-789`; `orchestrator/state.py:720-760,1086-1173,2224-2250`; `orchestrator/driver.py:4078-4130,4594-5031,5495-5520,6707-6714,7990-8050,8831-8890`; `orchestrator/ledgers.py:72-76`; `orchestrator/README.md:522-548`; accepted amendments B1, B2, B3, and B4 | touch common admission destination validation/canonicalization, adapter propagation and derived-path containment, selection/default/handoff, adapter/effects, Resume/compatibility/cardinality/attribution tests, and existing lifecycle coverage; do-not-add a generic placement gate, causal effect evidence, an exhaustive effect inventory, selective rollback, freshness, a parallel task ledger, staffing proof system, liveness rule, or a narrower final suite |

### Question Battery

| question | answer | evidence |
|---|---|---|
| victim | Operators and calling products cannot currently choose discussion independently for slice-note drafting or implementation; unsuitable content steps are forced through one worker, causing avoidable redrafting and model/human cost. Without the catalogue schema they also cannot discover valid Brainstorming controls from the shared source. If destination validation or forwarding is omitted, a supplied `output_directory` is not delivered as the requested destination; if a full-access executor violates that instruction, misplaced work requires discovery, relocation, or repetition. Milestone review may catch it, while a standalone caller owns stronger acceptance. | `implementation/milestones/tasks-2/goal.md:50-59,73-81,126-160`; `orchestrator/driver.py:5469-5528`; accepted amendments B3 and B4 |
| machinery | Add only a generic TaskExecutor catalogue/request/result contract, including one compact configuration schema and the optional resolved destination, one frozen task record per scheduling decision, task-id linkage on the existing durable Worker call marker, Worker and Brainstorming adapters, two keys on one slice selection map, reuse of existing path canonicalization and note-path handoff seams, one bounded Brainstorming effect seam, shared API/panel projections, and one Brainstorming-owned rule for resolving the existing private seat shape on direct profile-independent orders. The shared admission boundary canonicalizes the supplied destination once; each adapter receives and forwards that value unchanged and keeps any path it derives from the field beneath that root. Native claims and whole-workspace snapshots remain evidence rather than a causal placement gate. Reuse durable rethink state for continuable Worker identity, current review restart and Resume for successors after terminal failure, existing accounting homes/exclusions, current dispatch resolvers, and per-call staffing evidence; add no `output_directory_violation`, causal output evidence, duplicated configuration source, scheduler, sandbox, retry policy, liveness or freshness rule, parallel ledger, exhaustive effect inventory, selective rollback, staffing ledger, or profile version. | `implementation/milestones/tasks-2/goal.md:61-87,112-160,191-203,212-240`; `orchestrator/README.md:508-511`; `orchestrator/runners.py:1973-1992`; `orchestrator/gitops.py:944-958`; `orchestrator/brainstorming_coordination.py:546-574,696-789`; `orchestrator/state.py:720-760,1086-1173,2224-2250`; `orchestrator/driver.py:4078-4130,4594-5031,5495-5520,6707-6714`; accepted amendments B1, B2, B3, and B4 |
| consumers | Verified current consumers are the milestone driver’s draft/implement, fixer, and review scheduling points, the durable run summary, and the local service/panel chronology. Operators and future calling products consume the new direct API; no unverified external code consumer is assumed. | `orchestrator/driver.py:5469-5528,7072-7115,8831-8882`; `orchestrator/state.py:2315-2504`; `orchestrator/static/panel.html:2820-3052`; `implementation/milestones/tasks-2/goal.md:71-81` |
| cheaper_alternative | Reuse and wrap the current scheduling boundaries and central Worker call, carrying continuable identity through existing durable rethink state while keeping restarted reviews distinct. Put a task id on the existing call marker and reuse current accounting homes/exclusions instead of adding a ledger or inferring legacy ownership. Represent both slice choices as two keys on one existing plan projection, publish and validate configuration from one catalogue schema, canonicalize the optional destination once at shared task admission, pass the frozen value to either adapter, contain only paths task machinery derives from it, and reuse the Worker declaration/run-layout note-path handoff. Existing native contracts and snapshots cannot establish causal placement across full-access execution and recovery; promoting them would create a misleading partial gate, while honest enforcement needs new causal evidence or confinement outside the milestone. Reuse current review restart and Resume for successors, current dispatch resolvers, per-call staffing evidence, the Brainstorming adapter, access checks, and accounting/projection seams. Its target-only edit boundary still needs one bounded effect-application seam, and direct profile-independent Brainstorming needs only one executor-owned static-resolution rule. No second selector, configuration source, generic result field, scheduler, sandbox, exhaustive effect inventory, selective rollback, freshness gate, or staffing stack is needed. | `orchestrator/driver.py:455-594,2733-2788,3873-4058,4078-4130,4488-5031,5495-5520,6707-6714`; `orchestrator/brainstorming_milestone.py:338-371,579-609`; `orchestrator/brainstorming_coordination.py:546-574,696-789`; `orchestrator/state.py:720-760,1086-1173,2224-2250`; `implementation/milestones/tasks-2/goal.md:61-69,112-160,191-203`; accepted amendments B1, B2, B3, and B4 |
| cost | Build and review cost is ten bounded slices. Migration cost is no data rewrite or backfill; operational cost is one durable record/projection per scheduling decision, two small prospective values per new slice, and one task-id link on new Worker call markers. Maintenance adds one contract/projection family, the small configuration schema, one admission canonicalization with adapter propagation and the shared derived-path rule, one existing note-path handoff, one bounded Brainstorming effect seam, and one private Brainstorming staffing rule, with no new placement gate, causal evidence, retry, liveness, freshness, sandbox, selective-rollback, or parallel-ledger policy. Omission retains unsuitable-producer cost, undiscoverable controls, an unsafe or undisclosed destination instruction, ambiguous selection scope, and unattributable Worker failures or charges. Stronger placement acceptance remains a standalone-caller responsibility unless a later scope adds causal evidence or confinement. | `this skeleton, Planned slices, Guarantee posture, and Reuse Posture`; `implementation/milestones/tasks-2/goal.md:112-160,191-203,230-240`; `orchestrator/README.md:543-548`; accepted amendments B1, B2, B3, and B4 |
| threat_model | A caller with local or authenticated API reach can supply malformed task values or path-escaping reference/output paths; a provider can return malformed native output. Validate those shapes, inherited access, canonical destination containment, paths task machinery derives from the field, and native results. The operator, product code, resolved catalogue/configuration, and full-access TaskExecutor are trusted choices. `output_directory` is a strict request instruction but not a security or success-proof boundary: tasks add no remote auth, filesystem confinement, causal effect evidence, or cleanup layer. | `orchestrator/README.md:77-82,323-324,511`; `orchestrator/service.py:3480-3500,3889-3927`; `orchestrator/brainstorming_lifecycle.py:276-475`; `orchestrator/contracts.py:108-157`; accepted amendment B4 |
| enforceability | Exact request, result, and catalogue configuration shapes are enforceable through shared validators and catalogue-backed API/panel tests. For `output_directory`, the enforceable task-layer boundary is admission canonicalization inside the writable primary workspace, forwarding to the selected TaskExecutor, and containment of paths task machinery derives from the field. The destination instruction remains authoritative, but task success cannot prove universal placement under the frozen native contracts and full-access execution; native claims remain evidence, and an out-of-root claim alone neither authorizes the effect nor synthesizes failure. Independent two-key selection and freezing use the plan and task references; Worker/Brainstorming note paths use the existing declaration/run-layout handoff and effect seam; frozen history, continuable identity, abandonment failure, and successor identity use durable state; Worker ownership uses a pre-dispatch task id on the existing call marker and existing accounting exclusions; actual staffing uses current dispatch authority and existing per-call evidence; direct profile-independent Brainstorming uses frozen complete seat pins; and totals use existing normalizers and one traversal. Slices 1–10 pin catalogue/API/panel parity, the bounded destination behavior, selection scope, note-path handoff, mixed choices, continuation and abandonment, distinct review successors, ownership exclusions, both Brainstorming staffing seams, effect application, native results, and old-run defaults. | `orchestrator/contracts.py:108-157,210-232`; `orchestrator/README.md:508-511`; `orchestrator/runners.py:1973-1992`; `orchestrator/gitops.py:944-958`; `orchestrator/state.py:233-342,706-770,1086-1173,1874-2095,2224-2250`; `orchestrator/driver.py:455-594,2733-2799,4078-4130,4488-5031,5495-5520,6707-6714`; `orchestrator/brainstorming_coordination.py:546-574,696-789`; accepted amendments B1, B2, B3, and B4 |
