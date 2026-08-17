# Slice 10 — Compatibility and cardinality conformance

## Register 1 — INTENT (lay language)

### What this slice builds

This slice adds the final proof that the task system introduced by the earlier
slices still behaves like the old milestone when no new producer is chosen, and
that choosing a different producer changes only the intended production step.
It adds no new way to schedule or execute work.

For operators, the important promise is that one decision to do a piece of work
has one durable task history. A producer may make several calls, pause for a
discussion, recover, or ask for help repeatedly without those internal episodes
pretending to be more tasks. Once that task ends, its history does not change;
trying again is new work with a new history.

The proof covers both built-in producers, direct and milestone ordering, old
runs that never stored producer choices, the separate drafting and implementation
choices, and the Worker-owned review and fixing stages. It also checks that the
native outcome and known accounting survive success and failure without being
added twice to milestone totals.

Effect handling keeps its deliberately modest boundary. Brainstorming must
finish the production effects requested after agreement, but neither producer
gains filesystem confinement, rollback, or exactly-once effects. A Worker's
claim that it changed a path outside the requested destination is evidence of a
request violation, not permission and not enough by itself for the task layer to
invent a different terminal result.

### Ownership and boundary

This slice owns a compact cross-surface conformance matrix and any smallest
correction that matrix proves necessary at an already-owned seam. It does not
own a new record, selector, adapter, route, panel control, scheduler, recovery
policy, accounting home, or effect detector.

The durable record is the cardinality authority. Activity chips, logs, grouping,
and producer overrides remain convenience views or inputs; their loss never
changes acceptance, a seal, or a task result. The matrix checks useful normal
projection without turning that bookkeeping into a survival guarantee.

### Dependencies and consumers

This slice follows all nine earlier slices. It depends on their common contract,
durable history, Worker and Brainstorming execution paths, independent producer
selection, direct ordering, task views, explicit call attribution, and existing
milestone totals.

The observable consumers are direct callers, milestone operators, and the
existing review/fix flow that receives production results. The repository test
suite consumes the conformance matrix. No additional repository, external
service, or application contract is introduced.

### Guarantee posture

- **Strict — durable cardinality:** every admitted scheduling decision has one
  unique durable record. An open record may acquire one terminal result; a
  terminal record and its frozen order never change.
- **Strict — compatibility and isolation:** missing producer choices preserve
  the Worker path without migration. Drafting and implementation resolve and
  freeze independently, and neither choice changes skeleton, review, or fixer
  production.
- **Strict — continuation and succession:** continuable Worker work retains one
  task through repeated help-seeking and recoverable continuation. An existing
  abandonment ends it; re-entry creates a successor. A review that asks for help
  ends its origin task, and any later review is distinct. Brainstorming recovery
  likewise stays in its open production task and never reopens a terminal one.
- **Strict — result and accounting fidelity:** each executor's native outcome is
  retained without generic reinterpretation. Explicitly linked calls contribute
  once to their task and once to existing milestone totals; missing evidence is
  partial, while legacy and non-task work is not guessed into a task.
- **Strict at the admitted boundary; best-effort for full-access placement:** a
  supplied destination is validated and frozen, and task-owned derived paths stay
  beneath it. Actual effects may repeat or survive any outcome, and native path
  claims do not prove placement, authorization, cleanup, or rollback.
- **Best-effort — bookkeeping and delivery:** producer overrides, chips, logs,
  grouping, and refresh remain convenience. There is no eventual-delivery,
  liveness, or exact chip-cardinality promise.

### Acceptance criteria

- An old or resumable plan with no recorded producer choices runs its next note
  and implementation work through the existing Worker behavior without rewriting
  the stored plan.
- Opposite mixed producer choices both work end to end. Each production stage
  freezes only its own choice, and a terminal retry uses a distinct task while
  preserving the predecessor.
- Skeleton drafting, whole and delta reviews, and each fixer invocation remain
  Worker work even when both slice-production choices select Brainstorming.
- Repeated Worker help-seeking for drafting, implementation, or fixing retains
  one task until success or one of the already-defined abandonment outcomes.
  Every abandonment is covered; recoverable waiting stays open and re-entry after
  failure creates a new task.
- Whole and delta reviews that ask for help retain a failed origin with native and
  raw evidence; their discussions remain non-task activity, and later reviews
  have different task identities.
- Both producers preserve their native results, complete or truthful partial
  accounting, and one durable task despite their internal calls or recovery.
- Worker call, repair, interruption, stabilization, classification, and recovery
  evidence is attributed only through its explicit task link. Old unstamped
  records, attached discussion, reclassification, and retired seal work remain
  outside task accounting.
- Task subtotals do not change the existing unit or run totals. Successful and
  failed Brainstorming production also contributes through one existing total
  home.
- Brainstorming production remains target-free to its caller and does not succeed
  on discussion alone. Failed effects may leave partial work. A Worker native
  out-of-destination path claim alone neither authorizes the effect nor changes
  the executor's terminal result.
- Normal task views can show the distinct histories without collapsing them, but
  no test requires bookkeeping to survive every fetch, plan replacement, or UI
  lifetime.
- The focused conformance checks and the repository's complete suite pass at
  their respective gates.

### Non-goals

- No migration or backfill for old plans, old call markers, task history, chips,
  or producer overrides.
- No stable slice identity, producer lineage, override replay, retirement event,
  notification, acknowledgement window, or lost-bookkeeping test.
- No new task kind, TaskExecutor, selector, route, task status, result member,
  session reference, or activity vocabulary.
- No scheduler, queue, automatic retry, timeout, liveness rule, successor link,
  or exactly-once execution promise.
- No staffing ledger, profile version, inferred actual staffing, or use of an
  order-time snapshot as undeclared dispatch authority.
- No generic effect inventory, native-result parser, placement gate, confinement,
  cleanup, selective rollback, or destination-specific error.
- No changes to milestone sequencing, review convergence, verification, seals,
  reclassification, or existing accounting homes.
- No writes to the read-only additional roots.

### Risks

- Counting calls, discussions, or effect attempts as tasks would inflate history
  and obscure the scheduling decision the operator actually made.
- Reusing a terminal identity would rewrite evidence; creating a new identity for
  each recoverable episode would fragment one decision and its accounting.
- Applying one producer choice to both production stages, reviews, or fixers would
  turn a prospective choice into hidden routing.
- Migrating an old plan merely to materialize defaults would create needless state
  churn and could make historical bookkeeping look authoritative.
- Inferring ownership from labels or unit names could attach legacy cost to the
  wrong task, while re-adding task subtotals would double-count it.
- Treating a native path claim as confinement evidence would promise a boundary
  that full-access execution cannot enforce; treating it as authorization would
  weaken the caller's request.
- A broad new end-to-end harness could duplicate earlier fixtures and become more
  expensive than the behavior it protects.

### Reuse Posture

The affected parties are operators and direct callers. Without this closing
proof, individually correct surfaces can still compose into duplicate tasks,
producer spillover, rewritten history, or double-counted work. Those failures
are immediately visible once inspected but may be costly or impossible to repair
after durable history or a seal exists. The reviewed milestone independently
requires compatibility and cardinality conformance.

Checked and reused are the existing old-state/default projection, task admission
and one-way result transition, active-task association, Worker continuation and
review handoff, Brainstorming session/effect recovery, producer ordering, direct
task host, explicit call links, unit/run aggregators, canonical task reads, and
their focused tests. The cheapest sufficient option is a compact conformance
matrix that composes these real seams and reuses the focused suites as lower-level
evidence. A failing case may justify only the smallest correction at the seam
whose existing contract is violated.

No new runtime machinery is justified. The remaining cost is test fixtures,
cross-surface assertions, and review. It has no migration, deployment, operating,
or data-retention cost. Omitting the matrix leaves integration drift undetected;
adding a ledger, migration, replay system, or effect monitor would impose ongoing
cost for outcomes that are either already enforceable by existing state or
explicitly best-effort and reversible.

### Size posture

This slice is expected to remain under about 500 non-mechanical changed lines.
Its runtime default is no change: one compact conformance test surface should
reuse existing fixtures and contracts, with only a proportional correction if a
test exposes a real violation.

### Planning Material Disposition

- **Adopt:** the current reviewed skeleton and the contracts already sealed by
  Slices 1–9.
- **Revise:** the original goal's guaranteed one-chip wording. The reviewed
  baseline and operator amendment make chips and similar bookkeeping best-effort;
  only durable task cardinality is strict.
- **Reject:** `implementation/brainstorming`, `implementation/_drafts`, and any
  generated planning copy as authority, plus any new machinery proposed only to
  make bookkeeping or effect placement guarantee-grade.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Default compatibility | An absent `producer_task_executor` map or either absent key independently resolves to `worker` without mutating or migrating the stored plan. The milestone-built Worker request and opaque native result retain their existing behavior. | `implementation/milestones/tasks-2/skeleton.md:105-112,338,359`; default projection `orchestrator/tasks.py:277-315`; scheduling consumer `orchestrator/driver.py:6634-6741`; existing proof `orchestrator/tests/test_producer_selection.py:300-335`; `orchestrator/tests/test_worker_tasks.py:516-553` | touch compatibility/conformance tests and only a proven existing seam defect; do-not-migrate, backfill, rewrite old state, or add a selector |
| Producer isolation and freeze | Only `draft_slice_note` and `implement` read `producer_task_executor`; each resolves, freezes, fails, and admits a successor independently. `draft_skeleton`, `review_round`, `delta_review`, and `fix_findings` remain `worker`. A terminal predecessor stays immutable and its successor uses the then-visible selection. | `implementation/milestones/tasks-2/skeleton.md:143-180,338,350,358`; exact eligible kinds `orchestrator/tasks.py:23-26,358-467`; milestone admission `orchestrator/driver.py:2711-2808`; existing proof `orchestrator/tests/test_producer_selection.py:930-1065` | touch the cross-surface producer/successor matrix; do-not-cross-freeze choices, route ancillary work, reopen a terminal task, add lineage, or strengthen override delivery |
| Durable task cardinality | One admitted scheduling decision creates one unique record with exact members `id`, `order`, `resolved_staffing`, and `result`. New records are open; only the first valid null-to-terminal transition is allowed. Executor calls, sessions, discussions, recovery, and effect attempts are evidence, not additional tasks. | `implementation/milestones/tasks-2/skeleton.md:43-53,170-184,356`; admission/result `orchestrator/tasks.py:559-639`; history enforcement `orchestrator/state.py:336-383`; standalone store `orchestrator/task_api.py:22-91` | touch the conformance matrix across milestone/direct and Worker/Brainstorming records; do-not-add child tasks, mutable order fields, a second result, or a parallel task store |
| Worker help-seeking identity | `draft_slice_note`, `implement`, and `fix_findings` retain one task through discussion, continuation, and repeated `need_rethink` until success or durable abandonment. Failed attachment; missing or terminal-session detachment; disagreement or failed adoption/routing; and origin retry or another action fail the task with its original signal and known accounting. Recoverable waiting stays open; re-entry admits a successor. `review_round` and `delta_review` instead fail the origin immediately, leave discussion unstamped, and any later review is a new task with predecessor raw evidence intact. | `implementation/milestones/tasks-2/skeleton.md:54-87,356,358`; origin terminality `orchestrator/driver.py:4518-4744`; existing matrix `orchestrator/tests/test_worker_tasks.py:662-893` | touch closing identity/cardinality proof; do-not-add timeouts, a new abandonment judgment, session-derived identity, review continuation, inferred ownership, or task-stamped discussion |
| Native result, attribution, and totals | The generic terminal envelope keeps exact `status`, failure-only `reason`, `duration_s`, `token_usage`, `token_usage_partial`, `cost.{api_usd,real_usd}`, `cost_partial`, and opaque `native_result`. Worker accounting-bearing attempts enter a task only through explicit `task_id`; each charge remains in that task once and its existing unit/run home once. Unstamped legacy calls, attached Brainstorming, post-result reclassification, and retired `seal_half` remain excluded from task attribution. | `implementation/milestones/tasks-2/skeleton.md:76-87,183-184,355-356,362`; result/accounting `orchestrator/tasks.py:670-777,811-880`; aggregate homes `orchestrator/state.py:1906-2217`; existing proof `orchestrator/tests/test_tasks.py:727-1202` | touch result/accounting conformance assertions; do-not-flatten native results, infer or backfill links, duplicate Brainstorming session references, add a ledger, or re-add task subtotals |
| Effects and destination limit | Common admission alone validates and freezes optional `output_directory`; paths task machinery derives from it stay beneath it. Worker transports the caller-owned request unchanged. Brainstorming receives a target-free request and can succeed only after its production-effect completion. A Worker native out-of-root claim is evidence of an unauthorized request violation but alone neither synthesizes failure nor authorizes, proves, cleans up, or rolls back the effect. Partial effects may survive any outcome; Worker effects retain the existing at-least-once crash boundary. | `implementation/milestones/tasks-2/skeleton.md:170-204,361`; admission/Worker transport `orchestrator/tasks.py:500-597`; Brainstorming completion `orchestrator/brainstorming_tasks.py:1109-1229`; full-access/at-least-once boundary `orchestrator/README.md:508-511,541-548`; existing partial-effect proof `orchestrator/tests/test_brainstorming_slice_production.py:423-492` | touch the bounded conformance cases only; do-not-add `output_directory_violation`, parse native paths as placement proof, expose `target_path`, scan effects, confine, clean up, roll back, or write additional roots |
| Bookkeeping posture | Producer overrides, task/unit association, chips, activity grouping, logs, and refresh are best-effort convenience. Their presence, cardinality, survival, and delivery are not task, acceptance, seal, or result guarantees, and lost bookkeeping gets no fault-injection proof. Durable records remain authority. | operator amendment A1; `implementation/milestones/tasks-2/skeleton.md:52-53,143-159,205-210,356,362`; existing projection proof `orchestrator/tests/test_task_activity.py:97-312` | touch only normal conformance observation; do-not-add durable view state, identity, replay, notice, acknowledgement, reconciliation, freshness, or lost-value tests |
| Verification | A compact Slice 10 module proves the cross-surface matrix below while earlier focused modules remain the lower-level authority. Final closure runs exactly `python3 -m unittest discover -s orchestrator/tests -t .`. | planned Slice 10 `implementation/milestones/tasks-2/skeleton.md:338,340-343,363`; suite `orchestrator/README.md:522-532` | touch one focused conformance test surface and proportional existing-seam fixes only; do-not-duplicate all earlier suites, add a test-only runtime, or narrow the final command |

### Verification Contract

Focused checks in `orchestrator/tests/test_task_conformance.py` must prove:

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Old/default plans remain compatible | `test_old_plan_defaults_to_worker_without_migration` | A plan with no producer map and one with only one key leave their stored slice-plan bytes unchanged; each missing production choice runs as Worker with the same caller-built request, native result, milestone transition, and aggregate totals. | strict |
| Independent choices and successors do not spill | `test_mixed_producer_successors_freeze_independently_without_spillover` | Both opposite mixed choices complete; each production order freezes only itself; terminal retry creates a distinct record from the then-visible choice; skeleton, whole/delta review, and fixer orders remain Worker; Brainstorming callers see no public target. | strict identity/selection; best-effort chips |
| Continuable Worker cardinality covers every terminal route | `test_worker_rethink_cardinality_and_abandonment_matrix` | All three continuable kinds keep one id through repeated rethink and recoverable waiting; every already-defined abandonment records one immutable failure with native signal/accounting intact, and re-entry uses a different id. | strict |
| Review help-seeking never merges histories | `test_review_rethink_origin_and_successor_are_distinct` | Whole and delta review each retain a failed origin, unstamped discussion, and a later task with a different id and raw record; Resume cannot reuse or change the predecessor. | strict task history; best-effort projection |
| Both executors preserve one native result and one accounting home | `test_executor_cardinality_native_results_and_totals_conform` | Direct and milestone Worker/Brainstorming cases each have one durable task per order, no child tasks for physical calls or sessions, opaque native success/failure, truthful partial flags, explicit Worker attribution, legacy exclusions, and—where milestone totals exist—unchanged totals after task projection. | strict |
| Effect and destination limits remain calibrated | `test_out_of_root_claim_and_partial_effects_do_not_strengthen_success` | A successful Worker native claim outside its admitted destination remains the same terminal success with the opaque claim intact; no destination-specific status, reason, event, cleanup, or rollback is synthesized. The check treats the claim only as request-violation evidence and makes no placement or authorization assertion. Worker crash and Brainstorming effect failure may leave partial effects, and discussion alone cannot make Brainstorming succeed. | strict result fidelity; best-effort placement; at-least-once Worker effects |

The focused implementation command is
`python3 -m unittest orchestrator.tests.test_task_conformance`. Existing
`orchestrator.tests.test_tasks`, `orchestrator.tests.test_worker_tasks`,
`orchestrator.tests.test_brainstorming_tasks`,
`orchestrator.tests.test_brainstorming_slice_production`,
`orchestrator.tests.test_producer_selection`, `orchestrator.tests.test_task_api`,
and `orchestrator.tests.test_task_activity` remain lower-level authority. Final
closure runs exactly `python3 -m unittest discover -s orchestrator/tests -t .`.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These five entries are the slice-scoped remainder; enforceability is answered
again for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified observed consumers:** the milestone driver's two production branches and Worker-only skeleton/review/fixer scheduling; the direct task host/store for both executors; the durable state summary and task projection; and the existing focused test suites. **Verified untouched:** public schemas/routes, panel controls, Brainstorming's independent service contract, milestone review/seal law, additional repositories, and project access. Runtime edits are allowed only if the conformance matrix proves an existing seam violates its sealed contract. | milestone consumers `orchestrator/driver.py:2711-2808,5151-5370,6595-6741,8300-9020,9196-9550,10225-10530`; direct consumers `orchestrator/task_api.py:22-91,226-405`; projection `orchestrator/state.py:1833-2217,2321-2714`; boundary `implementation/milestones/tasks-2/skeleton.md:325-343` |
| pinned_facts | The hard table pins old-plan independent Worker defaults; production-only selection and successor isolation; the exact one-record/one-result durable boundary; continuable versus review rethink cardinality; opaque native results, explicit Worker attribution, legacy exclusions, and single-home totals; target-free Brainstorming effects and the bounded destination posture; best-effort bookkeeping; and the focused/full verification commands. | `implementation/milestones/tasks-2/skeleton.md:43-210,325-363`; `orchestrator/tasks.py:23-39,277-315,358-777,811-880`; `orchestrator/state.py:336-383,1906-2217` |
| verification | One compact conformance module crosses the seams for old/default plans, both mixed producer orders and terminal successors, every continuable abandonment, distinct post-rethink reviews, both executors' native result/cardinality/accounting, explicit/legacy attribution, target-free effects, partial effects, and the out-of-root native-claim limit. The existing focused modules remain the detailed branch proof, and repository discovery is the final gate. No check asserts lost-bookkeeping survival or universal effect placement. | planned scope `implementation/milestones/tasks-2/skeleton.md:338,340-343,363`; existing identity proof `orchestrator/tests/test_worker_tasks.py:662-893`; producer/effect proof `orchestrator/tests/test_brainstorming_slice_production.py:224-515,772-815`; attribution proof `orchestrator/tests/test_tasks.py:727-1202`; direct proof `orchestrator/tests/test_task_api.py:197-394,548-684`; suite `orchestrator/README.md:522-532` |
| reuse_posture | **Affected party/harm:** operators and direct callers can otherwise receive duplicate/fragmented histories, hidden producer spillover, or double-counted work; durable mistakes may be irreversible after seal. **Checked/reused:** default projection, admission/result transition, active-task reuse, rethink/review handoffs, Brainstorming recovery/effects, producer ordering, direct host/store, explicit attribution, aggregate accounting, canonical reads, and focused suites. **Cheapest sufficient option:** one compact cross-surface matrix using those real seams; documentation alone cannot catch composition regressions, while another ledger/harness/migration is unnecessary. **Remaining machinery/consumer:** test fixtures and assertions consumed by CI/review, plus only the smallest proven seam correction. **Lifecycle:** no migration, deployment, service, scheduler, cache, replay, or monitor; omission risks durable corruption, while stronger machinery protects best-effort values or duplicates current authority. | reuse authority `implementation/milestones/tasks-2/skeleton.md:234-306,338,363`; records `orchestrator/tasks.py:559-777`; rethink proof `orchestrator/tests/test_worker_tasks.py:662-893`; mixed/effect proof `orchestrator/tests/test_brainstorming_slice_production.py:224-515`; accounting proof `orchestrator/tests/test_tasks.py:954-1202` |
| enforceability | **Defaults/isolation:** the two-key resolver and production-kind allow-list select independently, while all other kinds enter Worker admission. **Cardinality/immutability:** UUID admission, the open-to-one-result transition, append-only history validation, and standalone atomic store enforce one record/result. **Continuation/successors:** the durable active-task/wait carriers reuse open ids; terminal removal plus fresh admission creates successors; review origins terminalize before discussion. **Result/accounting:** the closed result validator, explicit marker `task_id`, filtered task subtotal, and existing unit/run homes preserve opacity and prevent inferred duplication. **Effects/destination:** common canonicalization and the derived-path primitive enforce only admission/task-derived paths; Brainstorming's effect-completion gate enforces its completion signal. No mechanism proves full-access placement, authorization from a native claim, cleanup, exactly-once effects, bookkeeping delivery, or eventual freshness, so this note promises none and tests only the calibrated best-effort boundary. | defaults/isolation `orchestrator/tasks.py:23-26,277-315,358-467`; admission/history `orchestrator/tasks.py:559-639`; `orchestrator/state.py:336-383`; direct store `orchestrator/task_api.py:22-91`; continuation/review `orchestrator/driver.py:2669-2808,4518-4744`; result/accounting `orchestrator/tasks.py:670-880`; destination/effects `orchestrator/tasks.py:500-597`; `orchestrator/brainstorming_tasks.py:1109-1229`; bounded authority `implementation/milestones/tasks-2/skeleton.md:185-210,356,361-363` |
