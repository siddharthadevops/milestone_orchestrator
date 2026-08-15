# Slice 03 — Worker executor and default milestone cutover

## Register 1 — INTENT (lay language)

### What this slice builds

This slice makes the existing one-worker producer a first-class task without
changing how milestones work. Every current drafting, implementation, review,
and fixing call is ordered through the Worker TaskExecutor. The milestone still
writes the complete instruction, judges the answer, runs its normal gates, and
owns sequencing; Worker only carries that instruction to the selected worker and
brings the native answer back.

An accepted order is recorded before work starts. The historical staffing answer
captured then remains visible, while the physical call still uses the profile or
defaults that are current when that call begins. A later staffing change can
therefore change the call without rewriting what ordering recorded.

Asking for design help is not a completed task. Drafting a slice note,
implementing a slice, and fixing findings keep one task identity through the
attached discussion, the return to the worker, and repeated requests for help.
Recoverable interruption leaves that task open. If the run abandons that
continuation, the task fails and any later attempt is a new task. Reviews are
different: a review that asks for help has failed to deliver its review; the
discussion is separate context and the later fresh review is a new task.

Worker-produced slice notes keep their declared path, including legitimate
non-default layouts. Existing milestone reviews and implementation consume that
recorded path exactly as before.

### Ownership and boundary

This slice owns the Worker TaskExecutor integration, default Worker ordering at
all six current content-call boundaries, Worker task completion/failure, and the
durable association that lets recovery continue the right open task. It also owns
the Worker side of destination forwarding, rethink task identity, and the
declaration-first slice-note handoff.

It does not add a new producer selector, direct HTTP endpoint, panel control,
task chip, Brainstorming production executor, scheduler, or acceptance policy.
Attached design discussions remain the existing independent activity; only a
later production slice can select Brainstorming as the producer.

### Guarantee posture

- **Strict — default cutover and compatibility:** each current Worker content
  invocation has one durable task order. Worker receives the milestone's existing
  complete instruction, and the milestone receives the same native response and
  follows the same transitions, gates, reviews, fixes, seals, and aggregate
  accounting, apart from additive task history and explicit attribution.
- **Strict — staffing authority:** ordering freezes a historical staffing
  snapshot. Every physical Worker call resolves from the current profile when
  one exists, otherwise from defaults current when that call begins. The snapshot
  is never a dispatch pin or fallback.
- **Strict — task identity and terminality:** successful completion records one
  immutable success. A continuable help-seeking path stays open through repeated
  discussion and Worker continuation; an abandonment records one immutable
  failure and re-entry creates a successor. A review help request fails its
  origin immediately, and a later review is distinct.
- **Strict — destination handling:** a supplied destination reaches Worker only
  after common admission has canonicalized it inside the writable primary
  workspace. Worker receives that admitted value unchanged, and any path task
  machinery derives from it stays beneath it. Omission preserves current work-area
  behavior.
- **Strict — evidence and accounting:** every accounting-bearing Worker attempt
  for the scheduling decision carries its task identity. Known evidence is
  counted once; unavailable evidence remains partial. Attached discussions,
  post-result reclassification, and legacy unstamped activity remain outside the
  Worker task.
- **Optimistic:** none. This slice adds no provisional merge or client-side
  assumption.
- **Eventual:** none. It promises no polling, freshness, timeout, or eventual
  completion.
- **Best-effort — effects:** full-access Worker effects retain their existing
  at-least-once crash boundary. Task success is not proof of destination
  compliance, and there is no exactly-once delivery, rollback, cleanup, or
  confinement promise.

### Dependencies and consumers

The slice depends on Slice 1's closed Worker catalogue/request/result contracts
and Slice 2's durable admission, terminal-result, destination, attribution, and
accounting primitives. It extends the current prompt builders, Worker call seam,
call-time staffing resolvers, durable rethink handoff, draft/round records, and
review no-clobber evidence rather than replacing them.

The production consumers touched are the milestone's skeleton draft, slice-note
draft, implementation, fixer, whole-review, and delta-review scheduling points;
their rethink/recovery paths; and the existing draft/round records that downstream
milestone logic already consumes. Service routes, the panel, and task-chip
projection are not touched in this slice.

### Non-goals

- No Brainstorming TaskExecutor, static Brainstorming staffing rule, producer
  selection map, standalone task route, panel control, or task chip.
- No change to prompt ownership, Worker output schemas, milestone sequencing,
  review/fix convergence, verification, sealing, or strategy.
- No task for attached Brainstorming, post-result reclassification, deterministic
  transitions, shell verification, or retired seal activity.
- No scheduler, queue, retry policy, liveness rule, timeout, migration, legacy
  ownership inference, or parallel ledger.
- No runtime staffing pin, profile version, fallback from the order snapshot, or
  inferred actual-staffing projection.
- No destination-based prompt rewrite, `output_directory_violation`, generic
  placement gate, causal output evidence, filesystem sandbox, scan, cleanup,
  rollback, artifact inventory, presence check, byte-change check, or freshness
  check.
- No write outside the primary workspace; the four additional roots remain
  read-only inputs.

### Acceptance

Focused tests must prove the Worker order/dispatch/result boundary, default
milestone compatibility across all six content kinds, call-time staffing after an
order-time default change, destination validation and unchanged forwarding,
non-default slice-note declaration handoff, continuable success and repeated
rethink, every abandonment path, distinct failed review origins and fresh review
successors, recovery attribution, and the legacy/reclassification/seal exclusions.
The tests must compare the native Worker object and existing milestone outcome,
not merely assert that a call occurred.

The focused command is:

`python3 -m unittest orchestrator.tests.test_worker_tasks`

The repository closure gate remains exactly:

`python3 -m unittest discover -s orchestrator/tests -t .`

This slice is expected to exceed the roughly 500 changed-line target. The
production change should stay compact; the excess is the required behavioral
matrix across six scheduling boundaries, repeated continuation, every specified
abandonment, recovery, staffing, destination, handoff, and exclusion cases.
Splitting that proof would leave the default cutover only partly reviewable.

### Risks

- Creating a new task on each continuation would fragment one scheduling
  decision and its accounting; reusing a terminal task would rewrite history.
- Leaving a task open after continuation is abandoned would show work that can no
  longer finish; terminalizing a recoverable wait would create needless
  successors.
- Merging a review's help request into its later review would hide the failed
  origin and could overwrite its raw evidence.
- Using the frozen staffing snapshot at dispatch would make later profile/default
  changes ineffective and misstate actual staffing.
- Rebuilding or decorating the prompt in Worker would drift the default path.
- Treating a native path claim as confinement would promise an unenforceable
  boundary; failing a task solely for such a claim would invent a new acceptance
  rule.
- Adding task subtotals to existing unit/run totals would double-charge work;
  guessing ownership would rewrite legacy history.

### Reuse Posture

The affected parties are operators and existing resumable milestones. Without
this cutover they cannot observe one durable task for current Worker work; a
partial cutover can lose task identity across recovery, fragment rethink work, or
double-count cost. Those harms are visible in history and billing and are hard to
repair after the fact, while a pre-dispatch refusal is exposed and reversible.
The reviewed skeleton independently requires the cutover and its compatibility
posture.

Checked and reused are the complete prompt builders, the one validated Worker
call seam, live profile/default dispatch resolution, the durable call marker and
accounting homes, Slice 2 admission/result transitions, the current attached
discussion wait/resume state, immutable draft/round history, no-clobber raw
storage, and the existing slice-note declaration handoff. The cheapest sufficient
option is a thin Worker adapter plus one explicit durable active-task association
at the existing scheduling points; all call, result, continuation, and accounting
behavior remains in its current owner. The adapter and association are consumed
by the milestone now and by later direct ordering/projection slices. Build and
review cost is chiefly the compatibility matrix; migration cost is none, and
operating cost is one task record, active reference, and terminal transition per
invocation. Maintenance adds no service, scheduler, retry policy, ledger,
staffing stack, or acceptance gate. The additive Worker-default cutover is
reversible without rewriting retained task history. Omitting the association
makes recovery ambiguous; stronger machinery would buy guarantees this milestone
neither requires nor can enforce and would be harder to reverse.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's Slice 3 boundary and the incorporated
  staffing, rethink, producer-handoff, and destination amendments.
- **Revise:** no baseline decision. This note assigns chip rendering to its
  planned later slice while this slice establishes the distinct durable task
  identities that projection will consume.
- **Reject:** brainstorming or `_drafts` material as authority, any hidden Worker
  result kind, and any interpretation of a destination as confinement or success
  proof.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Worker cutover set | The TaskExecutor id is exactly `worker`, with resolved `configuration: {}`. The six milestone Worker task kinds cut over here are exactly `draft_skeleton`, `draft_slice_note`, `implement`, `fix_findings`, `review_round`, and `delta_review`. Worker remains the unconditional default until the later producer map exists, and remains the independent absent-map/key default afterward. | `implementation/milestones/tasks-2/skeleton.md:103-121,175-180,275,302-303`; catalogue `orchestrator/tasks.py:32-47`; kind sets `orchestrator/contracts.py:52-86` | touch those six existing scheduling points and their task references; do-not-task reclassification, verification, deterministic transitions, attached Brainstorming, or `seal_half`, and do-not-add a hidden selector |
| Transport and native result | The milestone still constructs the complete existing prompt and supplies it as the common request's `request`; the Worker adapter adds no second prompt builder. The existing caller-specific validator still judges the returned Worker object. A terminal task uses generic `status: success|failure` and preserves the complete JSON-plain Worker response as opaque `native_result` whenever one was returned; it is not flattened or reinterpreted by the task layer. | `implementation/milestones/tasks-2/skeleton.md:103-110,132-146,275,299,303`; `implementation/milestones/tasks-2/goal.md:105-111,126-152`; existing call/validation seam `orchestrator/runners.py:2842-2884,3051-3066`; task result validator `orchestrator/tasks.py:528-597` | touch one thin adapter and caller handoff; do-not-change prompt ownership, native Worker schemas, repair behavior, or milestone acceptance |
| Runtime staffing split | `resolved_staffing` is immutable order-time history. Each physical Worker call uses current-profile resolution when configured, otherwise the family/model/effort defaults read when that call begins; neither initial, repair, continuation, nor recovery dispatch may use the snapshot as pins or fallback. Existing per-call family/model/effort evidence is actual-staffing authority. | `implementation/milestones/tasks-2/skeleton.md:42-48,86-102,275,298,303`; current resolution `orchestrator/driver.py:455-601,6821-6905,6961-6963`; physical-dispatch seam `orchestrator/runners.py:2934-2998` | touch Worker admission snapshot resolution and pass current dispatch authority through the adapter; do-not-pin, cache, infer, version, or add a staffing ledger |
| Destination boundary | `output_directory` remains optional. The Worker path must enter through shared admission: an outside value is refused as `invalid_task_request`; a valid value is canonicalized inside the writable primary workspace before freezing, reaches Worker unchanged, and bounds every path task machinery derives from it. Omission preserves current work-area behavior. A native out-of-root claim or effect is not authorized, but does not by itself synthesize task failure or cleanup. | `implementation/milestones/tasks-2/skeleton.md:147-162,181-186,275,305,307`; shared admission/derived-path enforcement `orchestrator/tasks.py:16-17,255-311,332-353`; full-access limit `orchestrator/README.md:508-511` | touch adapter entry/forwarding and any Worker path derived from the field; do-not-recanonicalize in the adapter, rewrite the prompt, add a placement gate, scan, confinement, or rollback |
| Continuable Worker identity | Exactly `draft_slice_note`, `implement`, and `fix_findings` are continuable. One admitted task spans origin, attached discussion, Worker continuation, and repeated validated `need_rethink` until success or durable abandonment. `need_rethink` is never success. Recoverable stop, inspection failure, or crash leaves the task open while its durable wait/handoff/continuation remains usable. Failed attachment; detachment of a missing or terminal session; no agreement; failed adoption/routing elsewhere; or choosing origin retry/another action records one failure with the most specific cause. That failure says the invocation lacked its contracted result, not that the milestone itself failed; its opaque native result retains the request and finding, while Brainstorming remains sole authority for its session reference. Re-entry admits a successor; no timeout or new recovery judgment is added. | `implementation/milestones/tasks-2/skeleton.md:53-73,275,299-300,307`; exact kind split `orchestrator/contracts.py:79-93`; current durable handoff carriers `orchestrator/driver.py:3927-4138,4500-4771,4800-5064`; immutable result transition `orchestrator/tasks.py:356-399` | touch the existing scheduling/wait/resume/abandonment boundaries and preserve one explicit task reference; do-not-create a session-based identity, duplicate a session reference in failure prose, reopen a terminal task, or add liveness/retry policy |
| Review rethink identity | `review_round` and `delta_review` are not continuable. Their validated `need_rethink` response immediately terminalizes the origin task as failure while preserving the native request/finding, raw evidence, and complete known Worker accounting. The attached discussion is unstamped non-task activity. Any later review is a new task with a new id and frozen order; the handoff is context only, and reused review numbering must use existing no-clobber raw naming so predecessor evidence remains intact. | `implementation/milestones/tasks-2/skeleton.md:65-73,275,300,302,307`; report-kind split `orchestrator/contracts.py:79-93,722-813`; current fresh-review handoff `orchestrator/driver.py:4140-4177,5066-5099,8083-8139,8929-8981`; no-clobber primitive `orchestrator/driver.py:1304-1324` | touch both review scheduling points, origin terminalization, and raw persistence; do-not-continue the origin provider session, merge task ids, stamp the discussion, or overwrite predecessor raw evidence |
| Worker attribution and exclusions | The exact link is `task_id`, placed in the durable call marker before dispatch and retained through every accounting-bearing attempt used to obtain or classify the task's Worker outcome, including continuation, contract repair/malformed output, size interruption/stabilization, unaccepted calls, in-call failure classification, and recovery. Each charge enters the task once and existing unit/run totals once. A missing link stays legacy; attached Brainstorming, post-result reclassification, and retired `seal_half` activity remain unstamped and outside the task. | `implementation/milestones/tasks-2/skeleton.md:74-85,132-146,170-180,275,300,306-307`; marker/call evidence `orchestrator/driver.py:2438-2541,2735-2752,2771-2806,3088-3239`; accounting projection `orchestrator/tasks.py:402-494`; retired seal boundary `orchestrator/driver.py:4219-4255` | touch task-id propagation and terminal task accounting; do-not-infer/backfill ownership, stamp excluded activity, create a ledger, or re-add task subtotals to unit/run totals |
| Worker note handoff and default compatibility | A successful Worker `draft_slice_note` keeps its valid native `artifact` declaration as that unit's note path, including a legitimate non-default path; later review and implementation read the recorded path. Existing and resumable runs need no selection migration: their next eligible scheduling decision defaults to Worker, while old unstamped calls remain legacy. Milestone transitions, gates, review/fix behavior, seals, and aggregate totals otherwise remain unchanged. | `implementation/milestones/tasks-2/skeleton.md:103-110,122-131,275,303,307`; native declaration validation `orchestrator/contracts.py:932-966`; current handoff `orchestrator/state.py:811-883`; note lookup `orchestrator/driver.py:6782-6788`; current scheduling `orchestrator/driver.py:5501-5871` | touch additive task ordering and retain the declaration handoff; do-not-force the run-layout default over a valid Worker path, migrate history, or change downstream gates |
| Slice boundary | Slice 3 supplies the Worker adapter, default milestone cutover, lifecycle/compatibility proofs, and task identities only. Brainstorming production is Slice 4; selection is Slice 5; direct routes are Slice 7; controls and chips are Slices 8-9; cross-surface conformance is Slice 10. | `implementation/milestones/tasks-2/skeleton.md:269-287` | touch only Worker integration and focused tests; do-not-pull later API, UI, selection, Brainstorming-production, or chip scope forward |

### Verification Contract

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Worker is a transport-only task | `test_worker_adapter_preserves_request_native_result_and_accounting` | The adapter receives the already-built request unchanged; the milestone's native Worker object is preserved in `native_result`; one terminal result contains the existing known/partial Worker subtotal; no duplicate unit/run charge appears. | strict |
| All default scheduling points cut over without drift | `test_default_milestone_worker_cutover_preserves_all_six_kinds` | Skeleton draft, note draft, implementation, fixer, whole review, and delta review each admit one Worker task before dispatch, carry its id, preserve their prior accepted state transition, and create no task for reclassification or deterministic work. | strict |
| Destination handling cannot be bypassed | `test_worker_order_destination_is_admitted_once_and_forwarded_unchanged` | Omitted destination preserves current behavior; relative/absolute-inside values reach Worker as the common canonical value; outside/additional-root/symlink escapes fail before a call; and a representative Worker task-derived child cannot escape. The check makes no assertion about native claims or actual executor effects. | strict for admission/forwarding/derived paths; best-effort for actual effects |
| Call-time defaults remain authority | `test_profileless_worker_uses_default_changed_after_admission` | Admission under default A freezes A in `resolved_staffing`; changing the configured default to B before execution makes the physical call and per-call evidence use B while the frozen snapshot remains A. Initial, repair, and continuation dispatches never read the snapshot. | strict |
| Worker note paths remain declaration-first | `test_worker_note_keeps_nondefault_artifact_declaration` | A valid non-default `artifact` becomes the note unit's recorded path and is the exact path later review and implementation consume; no run-layout replacement or new presence/freshness gate appears. | strict |
| Continuable help-seeking retains one task | `test_continuable_worker_rethink_repeats_and_completes_one_task` | Note drafting, implementation, and fixing each retain one id through origin, attached discussion, continuation, repeated rethink, and success; only Worker attempts carry the id and the terminal native result/accounting are complete. | strict |
| Every abandonment closes the continuable task | `test_continuable_worker_abandonments_fail_and_reentry_succeeds_new_task` | Failed attachment, missing/terminal detachment, no agreement, failed adoption/routing, and origin retry/other-action cases each record one specific immutable failure whose native signal retains its request/finding without duplicating Brainstorming's session reference; recoverable inspection/stops remain open; re-entry creates a distinct successor without changing the predecessor. | strict |
| Review help-seeking fails origin and restarts fresh | `test_review_rethink_preserves_failed_origin_and_distinct_successor` | Whole and delta review origins fail on validated `need_rethink` with native request/finding, raw, and accounting intact; discussion work has no task id; a later review uses a new task and fresh provider call, carries handoff only as context, and cannot overwrite predecessor raw evidence. | strict |
| Recovery and exclusions stay truthful | `test_worker_task_recovery_and_legacy_exclusions` | A crash or resumable dispatch failure preserves the explicit open task and task id across later attempts; legacy unstamped markers are never claimed; attached Brainstorming, reclassification, and `seal_half` remain outside task accounting. | strict identity/accounting; best-effort effects |

Existing lifecycle tests remain lower-level evidence for prompt validation,
continuation/fresh-review behavior, and retired-seal migration
(`orchestrator/tests/test_brainstorming_milestone_adapter.py:2448-2576,3120-3263`),
while Slice 2's focused task tests remain the admission, immutability,
destination, attribution, and accounting foundation
(`orchestrator/tests/test_tasks.py:415-727,727-954`).

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These rows are the slice-scoped remainder. Enforceability is answered again for
the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified production consumers:** the skeleton/note/implementation draft scheduler, fixer scheduler, whole-review and delta-review schedulers; the attached-rethink wait/resume and fresh-review handoff; Worker call-time dispatch and marker/accounting; and draft/round records. **Not touched:** service routes, panel, task-chip projection, Brainstorming production, and selection. | draft scheduler `orchestrator/driver.py:5501-5871`; fixer `orchestrator/driver.py:7149-7415,7645-7690`; delta review `orchestrator/driver.py:7877-8139`; whole review `orchestrator/driver.py:8847-8981`; rethink `orchestrator/driver.py:3927-4138,4500-5099`; records `orchestrator/state.py:811-883,990-1037`; slice boundary `implementation/milestones/tasks-2/skeleton.md:269-287` |
| pinned_facts | Exact Worker id/empty configuration and six-kind cutover; transport-only prompt/native-result parity; historical snapshot versus call-time staffing; shared destination admission/forwarding/derived-path boundary without placement proof; continuable versus review rethink identity and terminality; exact `task_id` ownership/exclusions; declaration-first note path; and the later-slice boundary are pinned in the hard-register table. | `implementation/milestones/tasks-2/skeleton.md:53-121,147-162,170-180,269-307`; `orchestrator/tasks.py:32-47,255-311,332-399,528-597`; `orchestrator/contracts.py:52-93` |
| verification | Nine focused checks pin transport/native/accounting parity, all six default scheduling points, destination behavior, call-time default changes, non-default note handoff, continuable success/repeated rethink, every abandonment and successor, failed review origins/fresh successors/no-clobber evidence, and recovery/exclusions. Existing lifecycle tests remain the lower-level proof; repository unittest discovery is the final gate. | verification assignment `implementation/milestones/tasks-2/skeleton.md:284-287,307`; existing task tests `orchestrator/tests/test_tasks.py:415-954`; existing rethink tests `orchestrator/tests/test_brainstorming_milestone_adapter.py:2448-2576,2978-3263`; suite `orchestrator/README.md:522-532` |
| reuse_posture | **Affected party/harm:** operators and resumable runs otherwise lack coherent Worker task history; a partial cutover can fragment identity or cost. **Checked/reused:** current prompt builders, validated call/repair seam, live dispatch resolver, call marker/accounting, Slice 2 task transitions, durable rethink carriers, immutable draft/round history, no-clobber raw storage, and note declaration handoff. **Cheapest sufficient option:** one thin adapter plus one explicit active-task association at existing scheduling points. **Remaining machinery/consumer:** milestone calls consume it now; later direct API/chips consume the same records. **Lifecycle:** no migration/service/scheduler/ledger; operation adds one record/reference/terminal transition per invocation; tests dominate build/review cost; omission leaves recovery ambiguous and stronger machinery buys no authorized guarantee. | `orchestrator/runners.py:2842-3084`; `orchestrator/driver.py:1304-1324,2438-2541,2771-3107,3927-4138`; `orchestrator/tasks.py:332-494`; `orchestrator/state.py:811-883,990-1045`; `implementation/milestones/tasks-2/skeleton.md:192-252,275` |
| enforceability | One immutable task/result is enforced by shared admission plus the append-only one-way transition. Prompt/native parity is pinned by passing the existing built request through the current validator and comparing the full native object. Fresh dispatch resolution and per-call evidence enforce the staffing split. Shared canonicalization/containment enforce only destination admission, forwarding, and task-derived paths. Durable wait/resume state plus an explicit task association enforces continuable identity; terminal task immutability enforces successors, while fresh-review handoff and no-clobber storage enforce review separation. Existing `task_id` marker propagation/accounting homes enforce ownership and exclusions; `record_draft` enforces the note declaration handoff. No effect-placement, exactly-once, rollback, liveness, freshness, or chip guarantee is asserted here because this slice has no mechanism for one. | task transitions `orchestrator/tasks.py:332-399`; append-only guard `orchestrator/state.py:274-380`; Worker validation/dispatch `orchestrator/runners.py:2842-2884,2934-3059`; destination `orchestrator/tasks.py:255-311`; rethink carriers `orchestrator/driver.py:3927-4138,4500-5099`; raw no-clobber `orchestrator/driver.py:1304-1324`; attribution `orchestrator/driver.py:2438-2541,2735-2752`; handoff `orchestrator/state.py:811-883`; effect limit `orchestrator/README.md:508-511,543-548` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| One Worker task per scheduling decision, durable before dispatch, with one immutable terminal result | Shared task admission/result transitions and append-only task history (`orchestrator/tasks.py:332-399`; `orchestrator/state.py:274-380`) composed with one explicit durable reference at each existing scheduling point. | Crash before and after dispatch, reload, and prove the same open id resumes; accept one result only; after abandonment/re-entry prove predecessor immutability and successor identity. |
| Existing prompt and native response cross Worker unchanged | Existing prompt builders feed the validated call seam (`orchestrator/driver.py:5501-5617,7149-7285,8063-8082,8911-8928`; `orchestrator/runners.py:2842-2884,3051-3066`) and the generic result keeps opaque JSON (`orchestrator/tasks.py:528-597`). | Capture adapter input against the pre-adapter builder result and compare the complete validated native object before and after task wrapping for all six kinds. |
| Physical Worker staffing remains current while the snapshot stays historical | Fresh per-dispatch resolution and result identity (`orchestrator/driver.py:455-601,6821-6913,6961-6963`; `orchestrator/runners.py:2934-2998`) are separate from immutable task order fields (`orchestrator/state.py:336-379`). | Freeze A, change default to B, dispatch and repair/continue, then prove activity says B and order still says A. No test supplies snapshot values to dispatch. |
| Destination validation/forwarding/derived-path containment, and no stronger placement claim | Shared admission and derived-path canonicalization (`orchestrator/tasks.py:255-311,332-353`) enforce the bounded claim; full-access execution is explicitly detection-based (`orchestrator/README.md:508-511`). | Refuse outside/additional/symlink cases before dispatch; compare the one frozen canonical value at Worker; and reject an escaping derived child. Make no native-output or actual-effect placement assertion; Slice 10 owns that compatibility proof. |
| Continuable rethink keeps one task until success or an existing abandonment | Current durable wait/origin/resume carriers preserve the provider handoff and task link (`orchestrator/driver.py:3927-4138,4500-4771,4800-5064`); the task result's null/terminal transition supplies open versus abandoned history (`orchestrator/tasks.py:356-399`). | Exercise success, repeated rethink, recoverable stop/inspection/crash, and each named abandonment. Assert one id while recoverable and a terminal predecessor plus distinct successor after abandonment. |
| Review rethink cannot merge with or overwrite a later review | Report kinds are disjoint from continuable kinds (`orchestrator/contracts.py:79-93`); the existing review handoff requires a fresh call (`orchestrator/driver.py:4140-4177,5066-5099,8083-8139,8929-8981`); no-clobber storage preserves reused numbering (`orchestrator/driver.py:1304-1324`). | For both review kinds, preserve the failed task/native/raw/accounting, run the discussion unstamped, then prove a new task/provider call and unchanged predecessor evidence. |
| All Worker attempts are attributed once; legacy and non-Worker activity are excluded | Pre-dispatch marker linkage and propagation (`orchestrator/driver.py:2438-2541,2735-2752,2771-2806,3088-3239`) feed the existing filtered accounting projection (`orchestrator/tasks.py:402-494`). | Cover origin/continuation/repair/malformed/interruption/stabilization/unaccepted/classifier/recovery records; compare task and unit/run totals; prove unstamped legacy, attached Brainstorming, reclassification, and retired seal records never enter the task. |
| Worker drafting preserves its valid declared note path | Native draft validation requires `artifact`; draft recording stores it as unit authority and later lookup prefers it (`orchestrator/contracts.py:941-952`; `orchestrator/state.py:811-883`; `orchestrator/driver.py:6782-6788`). | Return a legitimate non-default path, then capture that exact path in the subsequent review and implementation inputs. |

There is deliberately no enforcement row for universal effect placement,
authorization inferred from a native claim, exactly-once effects, rollback,
cleanup, liveness, timeout, panel freshness, or chips: this slice asserts none of
those guarantees.
