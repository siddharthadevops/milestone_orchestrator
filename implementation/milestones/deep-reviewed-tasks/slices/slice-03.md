# Slice 03 — Routed calls and rethink continuity

## Register 1 — INTENT (lay language)

### What this slice builds

This slice makes one reviewed piece of work the visible owner of all the calls
needed to produce and review it. Each production, review, correction,
delta-review, and debt-rating call uses the existing Prompt Router. Selecting a
producer chooses an offered route; it does not create a second prompt system.

Those calls are evidence within the reviewed work, not a trail of internal
agent-call tasks. A person who explicitly orders a public agent call still gets
an ordinary durable agent-call task. Removing the internal task wrappers does
not remove raw replies, review rounds, timing, usage, cost, or failure evidence.

When an eligible call reports a real design contradiction, the reviewed work
stays open while the existing repository-backed Brainstorming resolves it. An
agreement continues the same reviewed work at the phase that asked for the
rethink when that origin survives accepted-plan reconciliation. If the accepted
plan removes or supersedes the origin, reconciliation controls the next work and
the obsolete phase does not rerun. No agreement or an operationally failed
discussion fails the originating work. A terminal task is never reopened.

### Ownership and consumers

The reviewed-work lifecycle owns sequence and continuation. Prompt Router owns
prompt selection and assembly; Staffing Router owns agents, models, effort, and
review families; Brainstorming owns its discussion and repository agreement.
The milestone driver remains the only runtime caller in this slice.

This slice prepares the call boundary later public reviewed tasks will use. It
does not yet publish either new task type, public result, or standalone order.

### Guarantee posture

- **Strict:** every offered reviewed-work call uses its exact Prompt Router
  route; internal agent-call attempts remain evidence rather than task records;
  accepted evidence and accounting remain attached once to the originating
  work; and rethink success resumes a surviving origin or yields to accepted-plan
  reconciliation, while rethink failure fails the origin.
- **Best-effort:** physical-call uniqueness, provider delivery, Brainstorming
  launch/inspection, and prompt/activity display freshness retain their current
  crash, provider, and polling limits. A crash may repeat a physical call.
- **Optimistic / eventual:** none. This slice adds no compare-and-set workflow,
  queue, retry-delivery, replication, or eventual-display promise.

### Dependencies

This slice depends on Slices 1 and 2's reviewed-work lifecycle and frozen
producer policy, the existing author/judgment/session adapters, Prompt Router,
the current unit/round/event evidence and accounting projections, and the
repository-backed Brainstorming rethink handoff. It adds no dependency, daemon,
store, ledger, migration, or product-root adapter.

### Non-goals

- No prompt template, prompt fragment, caller-built prompt, alternate router,
  route fallback, new producer, semantic job, review family, or staffing rule.
- No `reviewed_task` or `deep_task` catalogue entry, public API or panel change,
  reviewed native result, standalone ordering, or deep-task composition.
- No change to current-byte review, fix/debt decisions, seal, WIP/amend/gate,
  canonical-plan consequences, reconciliation, or milestone sequencing.
- No change to direct `agent_call` or `brainstorming` task behavior. Size control
  remains owned only by eligible agent-call-produced implementation reviewed
  work; Brainstorming and direct task orders gain none.
- No sibling verification cadence, merge-repair task, synchronization task,
  compatibility rewrite/backfill, or edit in a granted read-only root.

### Acceptance criteria

The slice is accepted when the complete offered call matrix is observed through
Prompt Router, an agent-call-produced reviewed cycle creates no internal
agent-call task records or child-task links, and the same cycle retains complete
evidence and single-count totals. Explicit standalone agent-call ordering must
remain unchanged. Focused cases must also show every eligible rethink origin
remaining open while waiting; after agreement, surviving origins re-enter the
same phase while origins removed or superseded by reconciliation do not rerun;
and discussion failure fails the origin without reopening a terminal record.
Existing default-lifecycle, route, Brainstorming-producer, and size-isolation
goldens must remain satisfied.

### Risks

The main risks are keeping a hidden non-router prompt path, losing evidence when
task wrappers disappear, counting one call in both task and reviewed-work
accounting, treating `need_rethink` as terminal success or failure too early,
resuming a different phase or one removed by the accepted plan, or accidentally
changing explicitly ordered tasks. Route spies, exact history assertions,
restart cases, and accounting comparisons make those failures visible.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Offered reviewed-work route matrix | Agent-call production routes are exactly `draft_skeleton@skeleton`, `draft_slice_note@slice_doc`, and `implement@slice_impl`. Agent-call judgment routes are exactly `review_round@skeleton`, `review_round@slice_doc`, `review_round@slice_impl`, `fix_findings@skeleton`, `fix_findings@slice_doc`, `fix_findings@slice_impl`, `delta_review@skeleton`, `delta_review@slice_doc`, `delta_review@slice_impl`, and `reclassify@doc`. Brainstorming is offered only for `draft_slice_note@slice_doc` and `implement@slice_impl`; attached rethink uses `rethink` with originating artifact type `document` or `implementation`. Skeleton production, review, fix, delta review, and reclassification are not Brainstorming producer jobs. | offered producers `orchestrator/tasks.py:22-31,352-379`; canonical routes `orchestrator/prompt_router.py:28-49,77-127` | touch the reviewed-work integrations with the existing routes; do-not-add a combination, make skeleton Brainstorming-produced, or bring `suite_checkpoint@workspace` or `merge_repair@workspace` into this boundary |
| One prompt authority | Every physical attempt in the matrix is resolved by Prompt Router; its rendered prompt and reply validator come from the same resolved charge. Contract correction is another physical attempt and resolves fresh. Prompt-set rung fallback remains the router's existing behavior; there is no non-router prompt fallback or agent-call-task-mediated prompt path. | author boundary `orchestrator/author_calls.py:23-27,228-276`; judgment boundary `orchestrator/judgment_calls.py:27-40,499-548`; session-seat boundary `orchestrator/session_calls.py:22-26,467-510`; fresh correction boundary `orchestrator/driver.py:2096-2132,2314-2349`; `orchestrator/runners.py:2952-2959,3424-3444`; milestone rule `implementation/milestones/deep-reviewed-tasks/skeleton.md:48-55,132` | touch call invocation and conformance tests; do-not-copy prompt assembly, mount fragments in the lifecycle, or let a stored task request become prompt authority |
| Call evidence is not an agent-call task | A reviewed-work production, review, fix, delta-review, or reclassification attempt creates no child `agent_call` task record and no evidence link to such a child. Only an explicit public `agent_call` order creates that durable task. Existing task history remains immutable and is not rewritten or backfilled. | mandate `implementation/milestones/deep-reviewed-tasks/goal.md:30-32,87-99`; milestone pin `implementation/milestones/deep-reviewed-tasks/skeleton.md:48-55,132`; explicit task admission `orchestrator/tasks.py:798-837`; direct host `orchestrator/task_api.py:580-590` | touch reviewed-work dispatch, evidence links, and milestone task projections; do-not-change direct-task admission/result behavior, delete historical task records, forbid later origin-owned attribution, or move implementation-size control into `agent_call` |
| Evidence and accounting survive the identity change | Completed and failed calls retain their existing raw/result, kind, family/model/effort, duration, usage/cost and partiality, and routed-fallback evidence in the originating draft, round, or event history. Unit and run totals count each retained physical charge once; unknown usage or cost remains partial rather than zero. No second evidence or accounting store is added. | draft evidence `orchestrator/state.py:858-941`; round evidence `orchestrator/state.py:1060-1097`; unit/run aggregation `orchestrator/state.py:2335-2458`; crash-safe call accounting `orchestrator/driver.py:4536-4608` | touch only child-task attribution and consumers that assumed every call had a child task id; do-not-drop raw/accounting evidence, infer another owner, duplicate charges, or strengthen physical delivery |
| `need_rethink` control vocabulary | Eligible origins are exactly `draft_slice_note`, `implement`, `review_round`, `delta_review`, and `fix_findings`. The control payload is `status: need_rethink` plus one non-empty `problem`; mounted question answers remain the outer call contract. It carries no `kind`, finding, target, request, result mode, work claim, or task result. `draft_skeleton` and `reclassify` cannot request it. | eligible kinds `orchestrator/contracts.py:87-100`; problem-only contract `orchestrator/prompt_contracts.py:33-39,200-217,582-594`; origin adapter `orchestrator/brainstorming_milestone.py:111-137` | touch only origin association and continuation; do-not-add a target, reconstruct a finding, expose session controls, or create another rethink vocabulary |
| Rethink continuity and terminality | `need_rethink` leaves the originating reviewed work in progress while one ordinary repository-backed Brainstorming resolves the problem. Agreement returns a surviving origin to its interrupted semantic phase from current repository state. If accepted-plan reconciliation removes or supersedes the origin, that work does not rerun and the accepted plan controls what follows. No agreement, missing/lost session, or operational terminal failure fails the origin. No path reopens a terminal task record. | mandate `implementation/milestones/deep-reviewed-tasks/goal.md:101-105`; milestone pins `implementation/milestones/deep-reviewed-tasks/skeleton.md:51-55,133,137`; durable wait and handoff `orchestrator/driver.py:6680-6722,7932-8003`; reconciliation retirement `orchestrator/driver.py:5470-5597`; repository session `orchestrator/brainstorming_milestone.py:269-340,417-421` | touch origin terminalization and phase re-entry; do-not-return `need_rethink` as a public success/failure result, admit a successor reviewed task, force reconciled-out work to rerun, reopen a terminal id, or bypass existing design-repair/reconciliation law |
| Slice boundary and direct-task isolation | Slice 3 adds no public TaskExecutor id, route, panel field, or public error code. The catalogue remains exactly `agent_call` and `brainstorming` here. Direct orders retain their task records and neither direct executor gains size control; reviewed implementation size control remains applicable only when its selected producer is `agent_call`. | slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:41-55,110-112`; current catalogue `orchestrator/tasks.py:66-125`; direct dispatch `orchestrator/task_api.py:580-590` | touch no public ordering surface; do-not-publish Slice 4/5 results or task types early, add a private milestone/Agent99 route, or add Brainstorming size machinery |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_reviewed_call_routing orchestrator.tests.test_reviewed_lifecycle orchestrator.tests.test_reviewed_policy orchestrator.tests.test_author_call_cutover orchestrator.tests.test_judgment_call_cutover orchestrator.tests.test_session_call_cutover orchestrator.tests.test_session_repository_seal orchestrator.tests.test_plan_reconciliation orchestrator.tests.test_worker_tasks orchestrator.tests.test_task_activity orchestrator.tests.test_brainstorming_slice_production orchestrator.tests.test_driver_implementation_size orchestrator.tests.test_tasks orchestrator.tests.test_task_api`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Every offered call uses its exact canonical route | new `ReviewedCallRoutingTest.test_offered_matrix_routes_every_reviewed_attempt`; retained `AuthorCallPreparationTest.test_only_the_three_direct_author_jobs_are_admitted`; retained `JudgmentCallPreparationTest.test_exact_judgment_route_matrix_uses_one_bound_charge`; retained `SessionCallCutoverTest.test_session_charge_matrix_mounts_exact_seat_law` | A lifecycle attempt reaches `prompt_router.resolve` with the exact job/executor/artifact coordinates above, and prompt plus validator are one bound charge; no unoffered pair dispatches. | strict |
| Internal calls are evidence, while explicit agent calls remain tasks | new `ReviewedCallRoutingTest.test_internal_agent_calls_create_evidence_without_child_tasks`; updated `TaskActivityProjectionTests.test_internal_call_activity_has_evidence_without_task_chips`; retained `WorkerTaskCutoverTest.test_worker_adapter_preserves_request_native_result_and_accounting`; retained `DurableTaskRecordsTest.test_admission_freezes_one_task_and_terminal_result` | A complete agent-call-produced reviewed cycle adds no child task record or child-task link; its convenience activity projection shows evidence without task identity. An explicit direct order still has one immutable admission and terminal result. | strict identity / best-effort activity display |
| Removing child-task links loses or duplicates no charge | new `ReviewedCallRoutingTest.test_internal_call_evidence_and_totals_survive_without_child_task_ids` | Success, blocked/protocol failure, correction, classification, and rethink-origin attempts retain their ordinary evidence; unit/run totals match retained call evidence without double counting and unknown values stay partial. | strict evidence/accounting; best-effort physical uniqueness |
| Successful rethink continues only a surviving origin and phase | new `ReviewedCallRoutingTest.test_rethink_success_reenters_surviving_origins_and_does_not_reenter_a_reconciled_out_origin`; retained `RepositorySealTest.test_repository_rethink_reenters_fresh_without_application`; retained `PlanReconciliationTests.test_rethink_session_freezes_even_when_b_deletes_its_owner` | Each eligible origin stays non-terminal while waiting. Without origin-removing reconciliation, accepted repository state causes a fresh call of the same semantic phase under the same reviewed-work origin. If reconciliation removes or supersedes the origin, obsolete work does not rerun and scheduling follows the accepted plan. No internal successor task is admitted. | strict outcome; best-effort session delivery |
| Failed rethink fails the origin and never reopens terminal state | new `ReviewedCallRoutingTest.test_rethink_failure_fails_origin_without_reopening`; updated abandonment/recovery cases in `WorkerTaskCutoverTest` | No agreement, missing/lost session, and operational failure produce originating-work failure; historical terminal call records remain immutable, and no terminal reviewed id is reused. | strict terminality |
| Producer and size boundaries do not move | retained `ReviewedProducerPolicyTest.test_brainstorming_implementation_refuses_size_control_before_freeze`; retained `DriverImplementationSizeTest.test_size_choices_apply_only_to_implementation`; update the stale `BrainstormingSliceProductionTest.test_brainstorming_implementation_never_activates_size_control` fixture to the same A1 contract; retained `TaskContractsTest.test_catalogue_has_exact_builtins_and_self_description` | Brainstorming-produced implementation neither accepts nor activates size control, direct tasks are unchanged, and the catalogue still exposes only the two pre-publication executors. | strict |

Repository-level commands remain:

`python3 -m unittest orchestrator.tests.suite_checkpoint`

`python3 -m unittest orchestrator.tests.suite_extended`

They are the normal checkpoint and architectural complement and must not be
reported as run unless implementation actually executes them
(`orchestrator/README.md:565-586`).

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator and later reviewed-task callers need one production-plus-review identity. Today the milestone exposes each internal agent call as a task and marks a rethink-origin task failed before a successful discussion can continue the work. That fragments task history, makes the future parent appear to fail mid-success, and risks duplicate attribution. Repository edits are reversible; spent calls, immutable terminal history, and a falsely reported task outcome are not. | required boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:48-55,110,132-133`; current internal admission `orchestrator/driver.py:3973-4089`; current early terminalization `orchestrator/driver.py:6553-6565` |
| machinery | The slice extends the existing reviewed-work lifecycle with one direct call/evidence boundary and origin-owned rethink continuation. It reuses `author_calls`, `judgment_calls`, `session_calls`, Prompt Router, the current physical-call runner/marker, state evidence, and repository Brainstorming. No public API, dependency, process, schema family, or store is introduced. Each reused part serves route authority, evidence retention, or continuation—the three authorised outcomes. | lifecycle seam `orchestrator/driver.py:435-641`; direct-call seam `orchestrator/driver.py:4684-4764`; existing adapters `orchestrator/author_calls.py:228-276`; `orchestrator/judgment_calls.py:499-548`; `orchestrator/session_calls.py:467-510` |
| consumers_touched | Verified changed consumers are the reviewed-work lifecycle and its milestone driver caller. Existing draft/round/event evidence, aggregate accounting, unit activity, and run-task projections must consume calls without treating them as task records. The standalone task host is a retained comparison, not a changed consumer. Searches across Life, Agent99, life_product_components, and Tutor found no code consumer of these task ids or route names, so no product adapter is added. | lifecycle caller `orchestrator/driver.py:8251-8263`; evidence and accounting readers `orchestrator/state.py:858-941,1060-1097,2335-2458`; activity links `orchestrator/state.py:2617-2638,2682-2713,2804-2915`; run-task projection `orchestrator/service.py:4447-4458`; direct host `orchestrator/task_api.py:580-590` |
| cheaper_alternative | The cheapest sufficient option is to invoke the already-routed call adapters through the existing physical-call seam without supplying task attribution, then retain evidence in the existing state records. Merely hiding task chips leaves false terminal records and duplicate attribution; documentation alone cannot change runtime identity; a new call engine, queue, or evidence store duplicates solved machinery. | optional task attribution in call seam `orchestrator/driver.py:4684-4724`; optional evidence links `orchestrator/state.py:858-941,1060-1097`; current task admission to remove from this path `orchestrator/driver.py:3973-4089` |
| cost | Build cost is a bounded lifecycle/admission change plus route, rethink, evidence, and compatibility tests. There is no migration or new operating service; provider-call volume, Prompt Router work, Git work, and Brainstorming work remain unchanged. Maintenance falls because one reviewed identity owns its evidence. Omission leaves the mandated public type with internally failed children and misleading accounting; the code change is reversible before public publication, but already-spent calls and terminal history are not. | no-dependency environment `orchestrator/README.md:3-9,33-46`; assigned slice `implementation/milestones/deep-reviewed-tasks/skeleton.md:110`; current call/task split `orchestrator/driver.py:3973-4089,4684-4764` |
| threat_model | This slice adds no remote/API input. Semantic job, route, artifact type, unit identity, and session charge are trusted product-emitted coordinates and receive no new defensive wrapper. Untrusted inputs remain provider/model replies and repository edits; the bound reply contract enforces the problem-only rethink shape and existing project safeguards enforce edit scope. Route-matrix tests prove our integration, not defend against imagined malformed self-emission. | trusted route derivation `orchestrator/driver.py:2070-2094,2233-2243`; untrusted reply boundary `orchestrator/prompt_contracts.py:200-217,582-594`; edit boundary `orchestrator/README.md:548-554` |
| pinned_facts | The seven hard rows pin only deviations that alter behavior or a cross-slice contract: exact offered routes, sole prompt authority, call-versus-task identity, retained evidence/accounting, exact rethink vocabulary, rethink terminality, and the public/direct-task boundary. No internal class name, storage layout, control-flow order, or new error vocabulary is made contractual. | slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:110-112`; prompt/rethink pins `implementation/milestones/deep-reviewed-tasks/skeleton.md:132-133`; exact route and rethink authorities `orchestrator/prompt_router.py:28-49,77-127`; `orchestrator/contracts.py:87-100` |
| verification | Six executable rows combine one new lifecycle integration matrix with retained direct-author, judgment, session-seat, repository-rethink, reconciliation, explicit-task, Brainstorming-size, and default-lifecycle goldens. The focused command pins this slice; checkpoint and extended suites remain repository gates and cannot be claimed without execution. | current route proofs `orchestrator/tests/test_author_call_cutover.py:673-677`; `orchestrator/tests/test_judgment_call_cutover.py:234-248`; `orchestrator/tests/test_session_call_cutover.py:148-192`; surviving-origin proof `orchestrator/tests/test_session_repository_seal.py:437-488`; removed-origin proof `orchestrator/tests/test_plan_reconciliation.py:468-541`; suite authority `orchestrator/README.md:565-586` |
| enforceability | Prompt Router's closed maps and the three bound adapters enforce route/prompt authority; the bound reply contract enforces the problem-only rethink vocabulary. Existing optional task attribution, draft/round/events, crash marker, and aggregation can enforce evidence-only single counting. Repository Brainstorming wait and sealed-range handoff can enforce same-phase continuation for surviving work; accepted-range reconciliation already retires an origin removed or superseded by the accepted plan. Catalogue/policy validation enforces the unchanged direct-task and size boundaries. Two current gaps are implementation gates rather than promises: reviewed calls still always admit an `agent_call` task, and rethink terminalizes that call before attaching the discussion. The standalone host keeps explicit direct orders separate. Physical uniqueness remains unenforceable and therefore best-effort under the stated at-least-once law. | route mechanisms `orchestrator/prompt_router.py:77-127,424-460`; rethink contract `orchestrator/prompt_contracts.py:200-217,582-594`; evidence mechanisms `orchestrator/state.py:858-941,1060-1097,2335-2458`; direct/size boundary `orchestrator/tasks.py:66-125,450-549`; gaps `orchestrator/driver.py:3973-4089,6553-6565`; continuation `orchestrator/driver.py:5470-5597,6680-6722,7932-8003`; standalone host `orchestrator/task_api.py:580-590`; delivery limit `orchestrator/state.py:1-17` |
