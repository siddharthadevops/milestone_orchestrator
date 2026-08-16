# Slice 02 — Durable task orders and accounting

## Register 1 — INTENT (lay language)

### What this slice builds

This slice gives every accepted task order one durable identity and one durable
history. The caller can stop and return later without the order silently changing:
the chosen producer, request, resolved configuration, inherited work area, and the
staffing answer captured at ordering time remain the same. When the task eventually
finishes, its success or failure is recorded once and cannot be replaced.

The staffing snapshot answers “what did ordering resolve then?” It does not decide
which agent a later physical call must use. The executors retain their existing
dispatch authority in later slices.

When a caller supplies an output directory, admission turns it into one canonical
destination inside the writable primary workspace before freezing the order. The
same destination is then available to either selected TaskExecutor as inherited
context. This does not promise that it independently crosses every physical
provider call. Task-owned paths genuinely derived from that destination must remain
beneath it. This is not a filesystem sandbox and does not prove where a full-access
producer actually wrote.

Worker costs remain where they are already recorded. A task id links those existing
records to their task so task accounting can be shown without charging the same
work again. Historical records without a task id remain historical; nothing guesses
their owner.

### Ownership and boundary

This slice owns shared task admission, durable task identity, immutable frozen-order
history, one-time terminal result recording, destination canonicalization, the
common derived-path boundary, and explicit Worker-record attribution.

It does not run either TaskExecutor. It does not choose runtime staffing, attach
Brainstorming sessions, implement rethink continuation or abandonment, select a
slice producer, expose an HTTP route, render a task chip, or change milestone
sequencing. Those later consumers receive the durable record built here.

### Guarantee posture

- **Strict — admission and history:** a refused order leaves no task. Each accepted
  scheduling decision receives a distinct id and one detached, frozen order and
  staffing snapshot. A task remains open until one validated success or failure is
  recorded; terminal data is immutable. Concurrent task-record mutations are
  serialized: every accepted admission and terminal result remains in the durable
  history, and competing terminalizations can accept only the first result.
- **Strict — destination boundary:** a supplied output directory is canonicalized
  against the caller-resolved writable primary workspace before admission. An
  outside destination is refused. The canonical value is frozen for the selected
  TaskExecutor as inherited context. Any path task machinery derives from the
  field remains beneath the admitted destination; no physical Worker-call channel
  is created here.
- **Strict — attribution and arithmetic:** new Worker records belong to a task only
  through an explicit task id carried from the pre-dispatch marker. Known duration,
  token, and cost values contribute once; missing evidence sets the matching partial
  flag. Existing unit and run totals still count the underlying record once and do
  not add the task subtotal.
- **Optimistic:** none. No provisional write or optimistic merge policy is
  introduced; accepted mutations are serialized instead.
- **Eventual:** none. No polling, replication, or convergence promise is introduced.
- **Best-effort:** executor-wide effect placement remains outside what this slice can
  prove. There is no cleanup, rollback, freshness, or exactly-once-effects promise.

### Dependencies and consumers

The slice depends on Slice 1's closed order and result contracts. It extends the
existing exclusive state-mutation authority, atomic state/history boundary, Worker
in-flight marker and recovery trail, path-containment check, and accounting
normalization rather than replacing them.

The production consumers touched now are durable state persistence, Worker call
marking and crash recovery, and the existing unit/run accounting projection. The
Worker and Brainstorming adapters, direct API, panel, and task chips are not cut over
here.

### Non-goals

- No Worker or Brainstorming dispatch, session lifecycle, continuation, abandonment,
  successor admission, retry, liveness, or timeout policy.
- No producer-selection map or milestone scheduling-point cutover.
- No task API, panel control, activity chip, or public task-event vocabulary.
- No staffing selector, runtime pin, fallback, profile version, or staffing ledger.
- No legacy-marker inference, migration, or backfill.
- No parallel accounting ledger and no change to existing unit/run charge ownership.
- No `output_directory_violation`, generic placement gate, causal output evidence,
  filesystem confinement, artifact inventory, presence/freshness check, cleanup, or
  rollback.
- No write to an additional read-only root and no authority inferred from a reference
  document or from request prose.

### Acceptance

The slice is accepted when focused tests prove that admission creates exactly one
durable frozen record, equivalent orders are still separate scheduling decisions,
invalid admission creates none, and a terminal result can be recorded once only.
Reloading preserves the exact accepted record. A focused concurrent test must also
prove that two accepted admissions both survive, an admission cannot erase a
simultaneous terminal result, and competing terminalizations preserve exactly the
first accepted result.

The same tests must prove destination handling for both built-in TaskExecutors,
including omitted, relative, absolute-inside, outside, additional-root, and symlink
escape cases; task-owned derived paths cannot escape the admitted root. They must
also prove task-id survival through Worker marker recovery, correct known and partial
task accounting, unchanged unit/run totals, and exclusion of legacy, attached
Brainstorming, reclassification, and retired seal activity.

The production machinery should remain compact, but the total focused delta is
expected to exceed the roughly 500 changed-line target. The reason is the required
proof breadth in this one reviewed slice: durable transition cases, path and symlink
boundaries for both executors, and attribution/recovery/partial-accounting exclusions.
Executor integration and end-to-end repetition remain in their owning slices.

### Risks

- Mutable caller objects could rewrite history unless the admitted values are
  detached before persistence.
- Atomic replacement prevents torn state but cannot alone prevent two writers from
  accepting the same prior state and losing one accepted mutation.
- A lexical-only path check could accept a symlink escape; canonical containment
  cases must cover existing ancestors and missing final directories.
- Counting both an existing record and its task subtotal would overstate run cost;
  only the existing accounting home may feed unit/run totals.
- Guessing ownership from a unit, kind, or reused label would rewrite legacy history;
  only an explicit task id establishes ownership.
- Treating the staffing snapshot as dispatch configuration would freeze authority
  that the accepted design deliberately leaves current at call time.
- Treating successful admission as effect confinement would promise a boundary that
  full-access execution cannot enforce.

### Reuse Posture

The affected parties are operators and calling products that need reliable task
history and truthful costs. Without this slice, an order can have no durable identity,
overlapping writers can erase an accepted order or terminal result, recovery attempts
cannot be attributed safely, and a requested destination can leave the writable root.
Lost task history can orphan execution and accounting, and misattribution is hard to
repair once history is shown; a refused destination is visible and reversible before
work begins. The reviewed skeleton and accepted amendments independently require
these outcomes.

Checked and reused are the existing task validators, canonical JSON detachment,
the exclusive per-state mutation lock, atomic state replacement and append-only
checks, real-path containment, the durable Worker call marker, its crash-recovery
records, and the current duration/token/cost homes and normalizers. The cheapest
sufficient option is one admission boundary, one minimal durable record, one optional
task-id link on those existing homes, and reuse of that lock around each task-record
read-modify-write. The only new machinery is the record transition and task subtotal
projection consumed by later adapters and views; no second lock or compare-and-swap
protocol is added. It adds no data rewrite, scheduler, service, or ledger;
maintenance is limited to one record contract and one explicit link. Omitting the
lock reuse would let accepted task history disappear; omitting either addition would
leave frozen history or accounting unprovable. All remain additive and require no
legacy rewrite.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's Slice 2 boundary and accepted amendments
  B1, B2, B4, and B5.
- **Revise:** no baseline decision; this note narrows the slice to admission,
  persistence, destination enforcement that is actually observable, and accounting
  linkage.
- **Reject:** generated run prompts/raw outputs and any brainstorming or `_drafts`
  material as authority; no such material supplies an additional requirement here.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Canonical task record | One successful admission creates one new task `id`. The durable record freezes the detached, validated `order`, an executor-resolved JSON-plain `resolved_staffing` snapshot, and `result: null`. The order already contains the frozen execution context at `order.request.work_area`. Terminalization replaces null with exactly one detached, validated generic result; no terminal field may later change. Two identical orders are two scheduling decisions and therefore two ids. Concurrent task-record mutations share the existing exclusive per-state mutation authority: every accepted admission and terminal result remains after reload, and competing terminalizations accept exactly one result. Failed validation or persistence admits no task. | `implementation/milestones/tasks-2/skeleton.md:42-52,274-275,295,299-300`; order/result validators `orchestrator/tasks.py:210-237,271-340`; atomic/history boundary `orchestrator/state.py:233-342`; exclusive state-mutation authority `orchestrator/driver.py:1198-1220` | touch shared admission, durable task history, one-time result transition, and the existing exclusive mutation seam; do-not-write the task collection outside that seam, add an idempotency key or second lock, reopen a terminal task, interpret `native_result`, duplicate execution context, or use the staffing snapshot as runtime authority |
| Destination admission | `output_directory` remains optional. When present, admission resolves a relative value from the caller-resolved writable primary workspace, canonicalizes it to an absolute real path, and refuses anything outside that primary root with `invalid_task_request`; an additional readable root is not a destination. The canonical value replaces the supplied value in the frozen order and is identical for `worker` and `brainstorming`. The directory need not pre-exist and admission does not create it. Omission preserves omission. | `implementation/milestones/tasks-2/skeleton.md:147-162,181-186,274,305,307`; error vocabulary `orchestrator/tasks.py:14-16`; existing containment primitive `orchestrator/kvstore.py:687-703`; resolved execution-context precedent `orchestrator/brainstorming_milestone.py:86-102` | touch the one shared admission boundary; do-not-canonicalize separately in adapters, accept an additional root, require presence, create directories, add `output_directory_violation`, or infer a destination from prose/references |
| Derived-path boundary and limit | When `output_directory` is present, every path task machinery derives from that field must canonicalize beneath the admitted directory; an escaping absolute, parent, or symlinked path is refused before that machinery uses it. This proves only task-derived paths. A native claim or actual out-of-root executor effect remains a request violation but does not synthesize task failure, authorization, confinement, detection, or cleanup. | `implementation/milestones/tasks-2/skeleton.md:147-162,181-186,262-265,305,307,319`; existing real-path containment `orchestrator/kvstore.py:687-703` | touch one reusable derived-path check; do-not-scan the workspace, parse native output as placement proof, add an effect inventory/gate, or claim universal enforcement |
| Worker ownership link | The exact linkage member is `task_id`. It is written to the durable Worker call marker before provider dispatch and carried unchanged into every accounting-bearing record for that task's origin, continuation, repair/malformed attempt, interruption/stabilization, unaccepted call, in-call failure classification, and recovery. A record or marker without `task_id` is legacy and has no task owner; ownership is never inferred from unit, kind, family, or label. Attached Brainstorming work, post-result reclassification, and retired `seal_half` activity remain unstamped. | `implementation/milestones/tasks-2/skeleton.md:53-85,170-180,274,300,306-307`; marker and recovery seams `orchestrator/driver.py:2076-2155,2415-2505,2587-2659`; existing exclusions/homes `orchestrator/state.py:1785-1862,2043-2062,2221-2261` | touch the current marker, its recovery copies, draft/round records, and existing Worker accounting events; do-not-add a linkage event/ledger, infer or backfill ids, stamp attached Brainstorming/reclassification/seal activity, or make executor-internal calls tasks |
| Accounting contribution | Task duration, token usage, and both cost readings are derived once from the task-id-linked existing accounting homes. Known values remain summed even when another record is missing; `token_usage_partial` and `cost_partial` mean evidence is missing, never zero. The terminal Worker result uses that task subtotal. Existing unit/run aggregation continues to traverse the original homes once and never adds the task result or subtotal. | `implementation/milestones/tasks-2/skeleton.md:74-85,132-146,274,299-300,307`; existing accounting homes and normalizers `orchestrator/state.py:1785-1862,1874-1936,1939-2096`; at-least-once boundary `orchestrator/README.md:541-548` | touch a task-filtered projection over existing homes and preserve partial flags; do-not-create charges, treat unknown as zero, add diagnostic duplicates, or re-add a task subtotal to unit/run totals |
| Slice boundary | Slice 2 supplies record/admission/linkage primitives and focused proofs only. Worker dispatch and rethink lifecycle belong to Slice 3; Brainstorming execution/staffing to Slice 4; selection to Slice 5; direct routes to Slice 7; panel/chips to Slices 8-9; cross-surface conformance to Slice 10. Old state with no task collection or task-id markers loads as empty/unattributed without migration. | `implementation/milestones/tasks-2/skeleton.md:269-287,300,304,306-307`; current task module boundary `orchestrator/tasks.py:1-5` | touch compatible state reads and the focused task test surface; do-not-cut over scheduling, add routes/UI, alter current dispatch, migrate old state, or edit additional roots |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_tasks`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Admission creates frozen one-task history | `test_admission_freezes_one_task_and_terminal_result` | Invalid input leaves no record; each valid admission has a distinct id; mutation of source order/staffing/result cannot change stored values; reload preserves them; the first validated terminal result succeeds and every later replacement is refused. | strict |
| Concurrent mutations preserve accepted history | `test_concurrent_task_mutations_preserve_accepted_history` | Concurrent admissions both remain after reload; an accepted admission and terminal result both remain; competing terminalizations accept one result and the durable winner is never replaced. | strict |
| Destination authority is shared and bounded | `test_output_directory_admission_for_both_executors` | Omission stays absent; relative and absolute-inside paths become the same canonical absolute value for both built-ins; outside, additional-root, and symlink escapes return `invalid_task_request` without a record; a missing final directory is neither created nor refused. | strict |
| Task-derived paths cannot escape | `test_output_directory_derived_path_boundary` | Children canonicalize beneath the frozen destination; absolute, parent, and symlink escapes are refused; the check makes no assertion about native claims or unrelated executor effects. | strict |
| Worker ownership survives failure and recovery | `test_worker_task_id_survives_marker_and_recovery_records` | The id exists before dispatch, survives nested classification and stale-marker recovery, and reaches every exercised accounting home unchanged; no second task or ownership record appears. | strict |
| Accounting is truthful and once-only | `test_task_accounting_reuses_existing_homes_once` | Origin/continuation, repair, malformed, interruption/stabilization, unaccepted, and classifier records sum once; known lower bounds survive missing evidence with the correct partial flags; unit/run totals are unchanged when the task subtotal is projected. | strict |
| Legacy and non-task activity remain excluded | `test_legacy_and_non_task_activity_stay_unattributed` | Matching labels/units without `task_id`, attached Brainstorming, reclassification, and retired seal records contribute to their existing homes only and never appear in a task subtotal. Old state with no task collection loads without rewrite. | strict |

The repository closure gate remains exactly
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-532`). This slice claims no executor delivery or UI
behavior.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These rows are the slice-scoped remainder. Enforceability is answered again for
the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified production consumers:** atomic/append-only milestone state; the Worker's durable in-flight marker, nested call accounting, and stale-marker recovery; draft/round/event accounting homes; and the derived unit/run summary. **Verified focused consumer:** the existing task contract test module. No service route, panel, TaskExecutor adapter, or producer scheduler is touched in this slice. | `orchestrator/state.py:233-342,706-770,877-918,1785-2096,2200-2310`; `orchestrator/driver.py:2076-2155,2415-2505,2587-2724`; `orchestrator/tests/test_tasks.py:53-380`; `implementation/milestones/tasks-2/skeleton.md:274-285` |
| pinned_facts | One id and frozen record per admitted scheduling decision; serialized preservation of concurrent accepted mutations; one immutable terminal result; historical-only `resolved_staffing`; `invalid_task_request` for an outside destination; one admission-owned canonical destination and derived-path boundary; exact `task_id` attribution with no inference/backfill; once-only known/partial task arithmetic without re-adding its subtotal; and the no-dispatch/no-route/no-chip boundary. | `implementation/milestones/tasks-2/skeleton.md:42-102,132-162,274,295,299-307`; `orchestrator/tasks.py:14-16,210-237,271-340`; `orchestrator/driver.py:1198-1220` |
| verification | Seven focused checks pin frozen admission/terminality, concurrent preservation, both-executor destination behavior, derived-path containment, marker/recovery linkage, once-only partial accounting, and legacy/non-task exclusions. Existing state and driver lifecycle tests remain regression evidence, and repository unittest discovery remains the final closure gate. | `implementation/milestones/tasks-2/skeleton.md:284-287,307`; `orchestrator/README.md:522-532`; existing task-test surface `orchestrator/tests/test_tasks.py:53-380`; marker-recovery precedent `orchestrator/tests/test_driver_mock.py:757-883,1150-1225` |
| reuse_posture | **Affected party/harm:** task callers lose immutable history or truthful attribution; an unchecked destination can leave the writable root. **Checked/reused:** Slice 1 validators/JSON detachment, the exclusive per-state mutation lock, state atomicity/history, real-path containment, current call marker/recovery, and existing accounting homes/normalizers. **Cheapest sufficient option:** one admission/record transition under that existing lock, plus optional `task_id` on existing homes and a filtered subtotal; no second lock or compare-and-swap protocol. **Remaining machinery/consumer:** later adapters and views consume those primitives. **Lifecycle:** additive, no migration/backfill/operation, small maintenance surface; omission can lose accepted history or leave durable ambiguity and potentially double-counted or unattributed work, while legacy exclusion stays reversible. | `orchestrator/tasks.py:106-121,210-237,271-340`; `orchestrator/state.py:233-342,1785-2096`; `orchestrator/kvstore.py:687-703`; `orchestrator/driver.py:1198-1220,2076-2155,2415-2505`; `implementation/milestones/tasks-2/skeleton.md:192-252` |
| enforceability | Frozen inputs/results are enforceable by the existing closed validators and canonical JSON detachment plus a one-way task transition serialized by the existing exclusive per-state mutation authority before atomic append-only persistence. Destination guarantees are enforceable by real-path canonicalization and primary-root containment; derived paths reuse the same check. Worker ownership is enforceable because `task_id` is persisted before dispatch and copied by existing marker/recovery seams; a task-filtered traversal over the existing accounting homes enforces once-only totals and explicit partial flags while the unchanged unit/run traversal ignores task subtotals. Legacy and non-task exclusions are enforceable by requiring the explicit link and by closed eligible homes. No universal placement, cleanup, runtime-staffing, delivery, freshness, retry, or liveness guarantee is asserted because this slice has no mechanism for one. | `orchestrator/tasks.py:106-121,210-237,271-340`; `orchestrator/state.py:233-342,1785-2096`; `orchestrator/kvstore.py:687-703`; `orchestrator/driver.py:1198-1220,2076-2155,2415-2505,2587-2659`; `implementation/milestones/tasks-2/skeleton.md:86-102,147-168,300,305,319` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| One detached frozen order and staffing snapshot per id | Slice 1's closed order validator and canonical JSON copy feed the existing exclusive per-state mutation boundary, followed by atomic save and a task-aware one-way history check (`orchestrator/tasks.py:106-121,210-237`; `orchestrator/driver.py:1198-1220`; `orchestrator/state.py:233-342`). | Admit twice from the same mutable sources, mutate those sources, reload, and prove two distinct unchanged records. Concurrently admit two orders and prove both accepted ids survive. Attempts to alter frozen fields fail persistence. |
| At most one immutable terminal result | The existing generic result validator (`orchestrator/tasks.py:271-340`) feeds the same serialized one-way task history transition; only null-to-result is legal. | Persist success and failure examples separately, then refuse status, reason, accounting, native-result, or whole-result replacement after terminalization. Race distinct terminal results and prove exactly one is accepted and remains durable alongside concurrent admissions. |
| Supplied destination is canonical and inside only the writable primary root | `os.path.realpath` behavior composed with the existing root check (`orchestrator/kvstore.py:687-703`) and caller-resolved primary context (`orchestrator/brainstorming_milestone.py:86-102`). | Cover relative, absolute, missing-tail, parent, additional-root, and symlink cases for both TaskExecutor ids; invalid cases create no task. |
| Every task-owned path derived from the destination stays beneath it | The same canonical containment check runs against the already-admitted destination, not against all readable roots (`orchestrator/kvstore.py:687-703`). | Child paths resolve; parent/absolute/symlink escapes refuse before use. No native-output or workspace scan is part of the check. |
| Worker attempts retain explicit ownership through crashes and nested classification | The current marker is durably replaced before dispatch and preserves nested/pending call fields; stale recovery copies marker facts into accounting events (`orchestrator/driver.py:2076-2155,2415-2505,2587-2659`). | Instrument dispatch, nesting, completion, and stale recovery; every new accounting record has the original `task_id`, while an unstamped marker remains legacy. |
| Task totals are once-only and honestly partial without changing unit/run totals | Reuse the current accounting homes, duration normalization, token/cost validators, partial propagation, and one traversal (`orchestrator/state.py:1785-2096`); filter task projection only by explicit eligible `task_id` links. | Mixed complete/partial records produce the known subtotal and partial flags once. Adding/projecting the task record leaves the pre-existing unit/run summary byte-for-byte equal. |
| Staffing snapshot cannot become dispatch authority in this slice | The record layer only detaches and persists `resolved_staffing`; Slice 2 has no TaskExecutor dispatch consumer (`orchestrator/tasks.py:1-5`; `implementation/milestones/tasks-2/skeleton.md:86-102,274-276`). | Focused tests prove snapshot immutability only. Runtime staffing assertions are deliberately absent until the adapter-owned tests in Slices 3 and 4. |

There is deliberately no enforcement row for universal effect placement, native
claim truth, cleanup, rollback, executor delivery, runtime staffing, retries,
liveness, API availability, panel freshness, or chips: this slice asserts none of
those guarantees.
