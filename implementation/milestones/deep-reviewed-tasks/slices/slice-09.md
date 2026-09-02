# Slice 09 — Milestone deep-slice composition

## Register 1 — INTENT (lay language)

### What this slice builds

This slice makes every planned milestone slice one visible deep task. The
milestone admits that task before work on the slice begins. The task delivers
one reviewed slice note, then one reviewed implementation child for every part
that is actually discovered. Each child keeps its own review evidence, seal,
result, accounting, and Git gate; the parent adds no replacement commit.

The approved skeleton still decides which logical slice is due. The deep task
does not become a second planner or a standalone process hidden inside the
milestone. It is the durable task boundary around the milestone's existing
documentation, implementation, repair, and recovery behavior.

If a design discussion changes accepted design, the milestone's existing
reconciliation remains in charge. Work that still belongs to the accepted plan
continues under the same open task identities. Work the accepted plan removes
or invalidates does not resume as if nothing changed; its history stays
immutable, and any replacement slice attempt starts with reviewed documentation
again before implementation. Completed unrelated tasks are not reopened.

### Ownership and consumers

The deep parent owns the slice attempt, child sequence, and aggregate result.
Each reviewed child owns its production-through-gate interior. The milestone
continues to own the canonical plan, accepted-design reconciliation, which
logical slice runs next, run Stop/start, higher-level ledgers and closure,
aggregate run accounting, and deployment posture.

The immediate consumers are milestone execution and recovery, canonical run
task history, generic task reads, and the existing task detail surface. The
standalone deep-task host remains a separate caller of the same public contract.
No granted product repository is changed.

### Guarantee posture

- **Strict:** one active deep-task identity per logical slice attempt; admission
  before effects; one documentation child before sequential implementation
  children; every child succeeds only through its own current-content gate;
  parent success only after the final uncut child; durable recovery identity;
  accepted-plan control over surviving and invalidated attempts; immutable
  terminal history; single-count accounting; and pre-activation compatibility.
- **Best-effort:** physical-call uniqueness, delivery of a process interrupt,
  chips, grouping, navigation, and display freshness. None decides execution,
  recovery, acceptance, or accounting.
- **Optimistic / eventual:** none. This slice adds no queue, redelivery,
  replication, exactly-once call, eventual-display, or deployment promise.

### Dependencies

This slice depends on Slices 1–8: the reusable reviewed lifecycle and policy,
routed call evidence, gate-backed native result, public reviewed and deep task
contracts, durable child relations, sequential part delivery, aggregate deep
result, generic run-task reads, and the reviewed skeleton's canonical-plan
anchor. It reuses the milestone's single-writer state, accepted-plan
reconciliation, run control, accounting, ledgers, and final closure.

It adds no third-party dependency, runtime service, scheduler, queue, event bus,
store, relationship database, prompt path, staffing authority, accounting
ledger, or product adapter.

### Non-goals

- No new public task type, route, result status, error code, or order shape.
- No change to standalone deep-task behavior or use of its standalone host to
  execute milestone work.
- No new design-repair or reconciliation algorithm, no private child lifecycle,
  and no reopening or rewriting of terminal task history.
- No sibling complete-verification task, five-slice cadence, final-verification
  placement, or verification presentation; Slices 10–12 own those outcomes.
- No aggregate deep-task commit and no collapse of child gates into milestone
  closure.
- No size control in the deep parent. Brainstorming-produced implementation is
  never monitored, steered, interrupted, stabilized, or split for size.
- No defensive validation of parent links, frozen policies, generated part
  labels, or terminal envelopes emitted by this product. Tests observe their
  outcomes; they do not corrupt trusted records.
- No migration or backfill of existing runs, no edit in a granted read-only
  root, and no automated push or deployment.

### Acceptance criteria

For a newly activated run, the next accepted logical slice must have one open
deep-task record before its first provider call or workspace edit. The record
must identify that exact accepted slice and freeze both child policies from the
same plan and run authority the milestone will consume. A crash after admission
must recover that record rather than create another attempt.

The documentation child must be admitted first and must reach its own successful
gate before implementation part a exists. Every later implementation child must
be admitted only after its predecessor's successful gate and eligible cut. A
successful child without a cut finishes implementation; only then may the deep
parent succeed, the logical slice close, and the next logical slice begin.

Every child must remain an ordinary public reviewed task with its canonical
parent relationship, native result, review evidence, and gate commit. The deep
parent's terminal accounting must equal the arithmetic aggregate of its children
without recording another physical charge. Milestone totals must continue to
count the underlying calls once, and milestone closure must remain a later,
separate commit.

While a rethink discussion or accepted-plan reconciliation is pending, the deep
parent and current child remain non-successful and no successor child starts. A
surviving origin resumes the same child and semantic phase from accepted
repository state. An open attempt made obsolete by reconciliation closes without
success; if the accepted plan still requires that logical slice, a distinct deep
attempt begins with a distinct documentation child. Already-terminal task
records remain unchanged.

A process Stop must leave open milestone tasks recoverable under the same ids;
run start resumes them. A terminal child failure must prevent later children and
settle the deep parent as failure before the milestone can retry. Any deliberate
retry uses a distinct deep parent and distinct affected children. Direct task
Stop remains unavailable for milestone-owned records; run Stop is the control.

Generic run-task reads must expose the parent and every child. Runs initialized
before this slice's activation must retain their prior separate slice-note and
implementation execution law with no synthetic deep parent, relation, result,
or history rewrite.

### Risks

The main risks are admitting after a paid call, creating two parents for one
attempt, starting implementation before the note gate, routing milestone work
through standalone state, or advancing the plan from a child gate before the
parent is complete. Repair-specific risks are resuming reconciled-out work,
reopening a terminal child, skipping required re-documentation, or losing the
accepted plan's order. Other risks are duplicate charges, an aggregate commit,
size control leaking into the parent or Brainstorming, backfilling old runs, and
turning best-effort presentation into authority. The checks below expose these
faults at task, Git, plan, and accounting boundaries.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Milestone slice parent | Each post-activation logical slice attempt has exactly one canonical record with `order.task_executor: "deep_task"`, durably associated with the accepted slice before any effect. `configuration.documentation` and `configuration.implementation` are fully resolved before admission from that accepted row's `producer_task_executor.draft_slice_note` and `.implement` choices plus the run's reviewed defaults. The recorded and consumed choices must match. | slice assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:117`; milestone/public ownership `implementation/milestones/deep-reviewed-tasks/skeleton.md:70-76,93-104,135-138`; deep resolver `orchestrator/tasks.py:882-905`; accepted producer projection `orchestrator/tasks.py:938-964` | touch prospective milestone slice admission, durable association, and policy handoff; do-not-call `DirectTaskHost`, add another store/route, resolve policy after work starts, or create a private milestone executor |
| Child identities and order | The first child is `reviewed_task` with `configuration.task_kind: "draft_slice_note"` and `parent: {"task_id": <deep-id>, "phase": "documentation", "part": null}`. Only its successful gate may admit the first implementation child, which is `reviewed_task` with `configuration.task_kind: "implement"` and `parent: {"task_id": <deep-id>, "phase": "implementation", "part": "a"}`. Eligible gated cuts admit only sequential code-generated `b`, `c`, … children from the predecessor's exact `remaining_scope`. | composition `implementation/milestones/deep-reviewed-tasks/skeleton.md:60-68,115,117,135-136`; canonical relation `orchestrator/tasks.py:1155-1197`; existing deep orders and cut consumption `orchestrator/task_api.py:887-965,1091-1164`; cut vocabulary `orchestrator/contracts.py:272-293,862-866` | touch in-run related admission and existing milestone unit association; do-not-embed children, infer relations, pre-plan parts, accept worker labels, run parts in parallel, or admit from an ungated result |
| Results, commits, and accounting | Each reviewed child is the sole authority for its native result, review evidence, accounting, seal, and gate commit. The deep parent stays open through every cut and succeeds only after the final uncut implementation child; its public aggregate keeps `native_result: null`, sums child duration/known usage/known cost once, and propagates partiality. It records no physical charge and owns no commit. The next logical slice cannot start before this parent success. | strict ownership `implementation/milestones/deep-reviewed-tasks/skeleton.md:64-68,80-84,117,136`; reviewed result `orchestrator/driver.py:631-681`; public deep aggregate `orchestrator/task_api.py:968-999`; terminal mutation `orchestrator/tasks.py:1183-1197` | touch child-result consumption, parent terminal projection, and milestone next-slice gate; do-not-copy/flatten child native results, replace child gates, count parent/result writes as work, add an aggregate commit, or advance from an intermediate child |
| Rethink, reconciliation, and re-documentation | `need_rethink` leaves the deep parent and originating reviewed child open. Existing accepted-plan reconciliation decides continuity: a surviving origin resumes the same child and interrupted semantic phase; an open removed or invalidated attempt becomes terminal `failure` and does not rerun. If accepted-plan work is still due, it is a distinct deep-task successor whose documentation child gates before implementation. Already-terminal parents/children and their results remain immutable; `accepted_range_reconciliation_closed` remains milestone authority for invalidation/requeue order. | continuity `implementation/milestones/deep-reviewed-tasks/skeleton.md:51-56,60-68,117,138`; terminal law `implementation/milestones/deep-reviewed-tasks/skeleton.md:67-68`; reconciliation close `orchestrator/driver.py:5862-5989`; implementation requeue consequences `orchestrator/state.py:1777-1859` | touch task settlement/association at the reconciliation boundary; do-not-bypass milestone reconciliation, resume obsolete work, reuse a terminal id, mutate historical success, skip successor documentation, or make `need_rethink` a public result |
| Recovery and control | Durable deep-parent association and `(parent.task_id, parent.phase, parent.part)` admit at most one logical record for an attempt. Crash/process Stop recovery observes or resumes those exact open ids. A terminal child failure admits no successor and settles the parent as `failure`; a lawful retry has a distinct parent and affected children. `POST /api/tasks/<id>/stop` for any milestone-owned parent or child remains HTTP `409` with `milestone tasks are stopped through their run`; `POST /api/runs/<run-id>/stop` remains the control. Physical calls remain at-least-once. | composite authority `implementation/milestones/deep-reviewed-tasks/skeleton.md:61-68,80-89,136`; atomic-state/delivery limit `orchestrator/state.py:1-17`; terminal mutation `orchestrator/tasks.py:1183-1197`; task/run Stop ownership `orchestrator/service.py:4277-4301,4901-4916,5110-5118` | touch serialized in-run admission, recovery, failure projection, and prospective retry; do-not-add a retry ledger, reopen records, expose standalone Stop, terminalize merely because the process stopped, or promise exactly-once calls/interruption |
| Size-control boundary | `deep_task` owns no size control. Only an implementation `reviewed_task` whose selected producer is `agent_call` may expose and activate `implementation_size_control`; deep composition consumes only that child's validated `implementation_cut`. Direct `agent_call`, direct Brainstorming, and Brainstorming-produced reviewed implementation remain without size monitoring or continuation. | operator amendment A1 restated at `implementation/milestones/deep-reviewed-tasks/skeleton.md:41-46,132`; applicability `orchestrator/tasks.py:772-805`; existing deep consumption gate `orchestrator/task_api.py:955-965` | touch only consumption of an eligible child's terminal cut; do-not-monitor, steer, interrupt, stabilize, or split at the parent, move the controller into an executor, or add Brainstorming size machinery |
| Public and compatibility boundary | This slice adds no executor id, route, result status, error code, or public event. Parent and children remain readable through `GET /api/tasks?run_id=<run-id>` and `GET /api/tasks/<id>?run_id=<run-id>`; run Stop retains `POST /api/runs/<run-id>/stop`. Runs initialized before deep-slice activation keep the existing direct `slice_doc`/`slice_impl` plan and receive no backfill. Slices 10–12, standalone tasks, convenience presentation, and all granted roots remain unchanged. | allocation/compatibility `implementation/milestones/deep-reviewed-tasks/skeleton.md:117-120,128,139`; generic reads and run Stop route `orchestrator/service.py:4506-4540,4659-4699,5110-5118`; current direct unit plan `orchestrator/state.py:713-757`; current prospective-init seam `orchestrator/driver.py:14159-14165` | touch generic run records and a prospective composition discriminator only; do-not-add deep-specific APIs/events, reinterpret old runs, change verification cadence/presentation, modify standalone behavior, edit granted roots, or automate deployment |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_milestone_deep_slice_composition orchestrator.tests.test_deep_task_implementation orchestrator.tests.test_deep_task_documentation orchestrator.tests.test_milestone_skeleton_composition orchestrator.tests.test_reviewed_call_routing orchestrator.tests.test_plan_reconciliation orchestrator.tests.test_reviewed_result orchestrator.tests.test_task_activity orchestrator.tests.test_verification_chronology`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| One deep parent precedes slice effects | new `MilestoneDeepSliceCompositionTest.test_one_deep_parent_freezes_accepted_slice_authority_before_any_call` | After the skeleton gate, the due slice has one open deep record with the exact accepted identity and resolved two-phase policy before dispatch; no duplicate parent, standalone state, provider call, edit, or premature child exists. | strict |
| Documentation and parts retain public gates | new `MilestoneDeepSliceCompositionTest.test_documentation_gate_then_sequential_part_gates_complete_one_logical_slice` | The exact documentation relation gates part `a`; gated eligible cuts create only `b`, then `c`; the first uncut child completes the parent and only then permits the next logical slice. Every child keeps its native result and distinct gate; no aggregate commit exists. | strict logical sequence / best-effort physical-call uniqueness |
| Parent and run accounting count child evidence once | new `MilestoneDeepSliceCompositionTest.test_parent_result_and_run_totals_share_child_evidence_without_recounting` | Parent arithmetic equals all admitted child results with partiality preserved, while run totals equal the underlying physical evidence once. Result/relation writes add no duration, token, cost, or commit. | strict |
| Accepted design preserves or replaces the correct attempt | new `MilestoneDeepSliceCompositionTest.test_reconciliation_resumes_a_survivor_and_redocuments_an_invalidated_successor` | During rethink/reconciliation no successor starts. A surviving origin resumes the same child/phase. An invalidated open attempt fails without resuming; retained/reintroduced work gets a new deep parent and new documentation child before implementation; terminal historical records are unchanged and accepted plan order wins. | strict outcome / best-effort session delivery |
| Crash, process Stop, failure, and retry preserve identity law | new `MilestoneDeepSliceCompositionTest.test_admission_gate_result_stop_and_retry_windows_preserve_composite_identity` | Before-write failure permits one later admission; after-write and result/gate crash windows reuse exact ids. Process Stop leaves open ids recoverable; terminal child failure starts no successor and fails the parent; deliberate retry uses disjoint ids/evidence. Task Stop retains the milestone `409`. | strict logical recovery and terminality / best-effort interruption and physical-call uniqueness |
| Compatibility and deferred boundaries do not move | new `MilestoneDeepSliceCompositionTest.test_pre_activation_run_keeps_direct_slice_law`; retained standalone deep, skeleton, task-read, rethink, and chronology tests | An older fixture gets no synthetic deep hierarchy. Public/direct task behavior, size applicability, current verification cadence, generic routes, task-result vocabulary, presentation posture, and final closure ownership remain unchanged. | strict compatibility / best-effort presentation |

Repository-level commands remain:

`python3 -m unittest orchestrator.tests.suite_checkpoint`

`python3 -m unittest orchestrator.tests.suite_extended`

They remain separate checkpoint and architectural gates and must not be claimed
as run unless implementation executes them (`orchestrator/README.md:565-586`).

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Milestone operators and task consumers still receive direct documentation and implementation units after the reviewed skeleton; they do not receive one durable task for a logical slice. Without this slice, using the standalone deep host would lose milestone plan/reconciliation authority, while retaining the direct flow leaves no composite identity for recovery or inspection. Exposure begins at every new logical slice; code/state changes are Git-reversible, but duplicate paid calls, wrong-plan work, and published gate commits are not cheaply reversible. | assigned need `implementation/milestones/deep-reviewed-tasks/skeleton.md:18-22,60-68,117`; current direct plan `orchestrator/state.py:713-757`; current milestone step path `orchestrator/driver.py:8642-8677` |
| machinery | No new runtime module, API, or dependency is introduced. The slice extends milestone task admission from the reviewed skeleton to one deep parent per logical slice, reuses canonical parent relations and reviewed-child results, applies the already-delivered deep sequence/aggregate contract inside milestone ownership, and connects terminal/reconciliation outcomes to task records. One prospective law marker and one focused test module are the only new bounded seams needed for compatibility and proof. | current milestone admission seam `orchestrator/driver.py:4057-4264`; reusable deep machinery `orchestrator/task_api.py:887-999,1048-1164`; canonical records `orchestrator/tasks.py:1155-1197`; no-dependency standard `orchestrator/README.md:33-46` |
| consumers_touched | Verified runtime consumers are the milestone driver and state machine, accepted-plan reconciliation, canonical run-task reads, run summary task associations, and the existing generic task detail surface. The created consumers are the already-public deep parent and reviewed children. Exact-id searches across Life, Agent99, life_product_components, and Tutor found no runtime consumer, so no speculative adapter is added and those roots remain read-only. | execution/reconciliation `orchestrator/driver.py:392-409,5862-5989,8621-8677`; generic reads `orchestrator/service.py:4506-4540`; summary association `orchestrator/state.py:2655-2676`; generic task page `orchestrator/static/panel.html:5245-5305` |
| cheaper_alternative | Cheapest sufficient is to compose the milestone over the existing public deep record, reviewed children, relation vocabulary, cut chain, and aggregate arithmetic. Configuration or documentation cannot make admission/recovery durable. Calling the standalone host is cheaper in code but insufficient because milestone plan establishment, reconciliation, run Stop, ledgers, and closure must remain milestone-owned. Doing nothing misses the assigned one-task-per-slice outcome; a second engine/store would duplicate solved machinery. | reuse boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:70-76,91-104,117,138`; existing deep host `orchestrator/task_api.py:887-1164`; milestone ownership `orchestrator/driver.py:5862-5989,13591-13626` |
| cost | Build and review cost is one in-run composite admission/result seam, prospective compatibility marking, reconciliation settlement, and focused crash/repair/accounting tests. There is no migration, daemon, dependency, route, or product rollout. Runtime adds one parent record per attempt but no extra model call or Git gate beyond the mandated children. Omission leaves manual, non-recoverable composition and risks wrong-plan work; source changes are reversible, while call spend and consumed commits are not. | record cost `orchestrator/tasks.py:1155-1197`; existing child-call sequence `orchestrator/task_api.py:1091-1164`; environment standard `orchestrator/README.md:3-9,46` |
| threat_model | This slice adds no caller-supplied field or public request surface. Untrusted values it newly composes are already-contracted model outputs: the reviewed documentation artifact path, eligible implementation-cut text, and accepted repository/plan changes. Existing path containment, cut validation, current-content gates, and committed-plan reconciliation guard those values. Deep ids, parent relations, frozen policies, generated part labels, validated terminal envelopes, and run coordinates are trusted product emissions; no malformed-self-record defense or test is added. | path boundary `orchestrator/tasks.py:1090-1108`; cut boundary `orchestrator/contracts.py:272-293,862-866`; reviewed gate `orchestrator/driver.py:631-681`; committed-plan boundary `orchestrator/plan_reconciliation.py:230-388`; trust posture `implementation/milestones/deep-reviewed-tasks/skeleton.md:99-104` |
| pinned_facts | The seven hard rows pin only deviations that break public or cross-slice behavior: one parent, exact child relations/order, result/commit/accounting ownership, rethink/reconciliation consequences, recovery/control, size ownership, and public/compatibility scope. Internal helper names, traversal, polling, and control-flow structure remain implementation choices. | slice boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:117`; cross-slice pins `implementation/milestones/deep-reviewed-tasks/skeleton.md:132,135-139` |
| verification | Six executable rows add one milestone-composition module and retain the already-passing public deep sequence, reviewed result, skeleton composition, rethink/reconciliation, task projection, and verification-chronology proofs. They observe canonical records, provider-call timing, Git gates, accepted-plan order, terminal results, accounting, and crash/Stop recovery. Repository suites remain separate and unclaimed until implementation runs them. | existing deep proof `orchestrator/tests/test_deep_task_implementation.py:139-224,246-437,627-834`; skeleton proof `orchestrator/tests/test_milestone_skeleton_composition.py:126-219,551-677,803-816`; reconciliation proof `orchestrator/tests/test_plan_reconciliation.py:468-541`; suite authority `orchestrator/README.md:565-586` |
| enforceability | Existing mechanisms enforce the public deep policies, canonical records, direct composite relations/sequence, reviewed child gates, deep arithmetic, single-writer milestone steps, accepted-plan reconciliation, immutable terminal results, generic reads, and run control. Three missing seams are explicit implementation gates: new runs have no deep-slice activation discriminator; milestone slice units have no deep parent/child task association; and milestone gate/reconciliation transitions do not yet settle the corresponding child and parent results. Until those gaps and the named tests land, this slice cannot claim composite identity, parent success, or reconciliation-safe re-documentation. Physical exactly-once delivery, interrupt delivery, and display freshness have no strict mechanism and remain best-effort. | existing mechanisms `orchestrator/tasks.py:882-905,1155-1197`; `orchestrator/task_api.py:171-231,968-999,1091-1164`; `orchestrator/driver.py:631-681,5862-5989,8621-8677`; gaps/current activation `orchestrator/state.py:713-757`; `orchestrator/driver.py:4057-4264,14159-14165`; delivery limit `orchestrator/state.py:1-17` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| One due logical attempt has one deep parent before effects | Canonical admission/result mutation at `orchestrator/tasks.py:1155-1197`; exclusive milestone step at `orchestrator/driver.py:8621-8677`; the skeleton's proven pre-effect task pattern at `orchestrator/driver.py:4068-4095`. | **Current gap:** only the initial skeleton gets an outer task. Acceptance requires a prospective run to admit/reuse one `deep_task` for the due accepted slice before its documentation dispatch and to keep recorded/consumed policy identical. |
| One documentation child then gated sequential implementation children | Existing relation lookup/admission at `orchestrator/task_api.py:171-231`; public deep child orders/cut gate at `orchestrator/task_api.py:887-965`; reviewed success at `orchestrator/driver.py:631-681`. | **Current gap:** milestone units have no parent/phase/part task relations. Acceptance requires the existing milestone lifecycle to publish/reuse those canonical relations and withhold every successor until the predecessor result is gate-backed. |
| Parent result preserves child commits and counts once | Public deep arithmetic at `orchestrator/task_api.py:968-999`; child accounting association at `orchestrator/tasks.py:1229-1321`; milestone physical-evidence totals at `orchestrator/state.py:2318-2528`. | **Current gap:** milestone slice completion discards the reviewed result and has no deep parent result. Acceptance requires terminal parent projection from child results only, with no parent charge or aggregate commit and no next logical slice before success. |
| Accepted design continues only current accepted-plan work | Reconciliation observation/close at `orchestrator/plan_reconciliation.py:230-388`; `orchestrator/driver.py:5862-5989`; immutable reset/requeue consequences at `orchestrator/state.py:1777-1859`. | **Current gap:** reconciliation knows milestone units and legacy source carriers, not the new deep/reviewed task hierarchy. Acceptance requires it to preserve a surviving open identity, terminalize an obsolete open attempt, and make any retained/reintroduced attempt start with a new documentation child without rewriting terminal history. |
| Size and delivery posture do not strengthen | Applicability at `orchestrator/tasks.py:772-805`; eligible cut consumption at `orchestrator/task_api.py:955-965`; at-least-once limit at `orchestrator/state.py:1-17`. | No controller or delivery machinery is added. Focused tests inspect logical records and gate order, never repository monitoring by the parent, Brainstorming size behavior, physical exactly-once calls, or guaranteed interrupt delivery. |
| Old-run law and control remain explicit | Current prospective skeleton marker at `orchestrator/driver.py:14159-14165`; direct unit plan at `orchestrator/state.py:713-757`; milestone task/run Stop split at `orchestrator/service.py:4277-4301,2585-2613`. | **Current gap:** Slice 8-era runs cannot be distinguished from runs authorized for deep-slice composition. Acceptance requires a prospective discriminator; absence preserves direct slice law, generic reads, and run-owned control without backfill. |
