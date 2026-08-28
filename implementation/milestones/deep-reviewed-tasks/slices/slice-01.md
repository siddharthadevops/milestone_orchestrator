# Slice 01 — Default reviewed-lifecycle parity

## Register 1 — INTENT (lay language)

### What this slice builds

This slice separates the orchestrator's existing production-through-review
lifecycle from milestone sequencing so the same lifecycle can later serve a
standalone reviewed task. The milestone remains its first and only runtime
caller in this slice. To an operator running a milestone, nothing changes: the
same producer works, the same reviewers and fixer converge, the same evidence
is retained, and the same reviewed bytes seal and reach their existing Git gate.

This is an ownership cut, not a new review system. It reuses the current
production, review, fix, delta-review, debt, verification, seal, Git, accounting,
staffing, Prompt Router, and recovery seams. One selected production's reviewed
cycle belongs inside the reusable boundary; choosing the next milestone unit,
establishing or repairing the plan, reconciling slices, closing the milestone,
and deploying remain milestone work.

### Who this serves

The immediate consumer is the existing milestone driver. The eventual
beneficiaries are operators and products that need `reviewed_task` without a
second, weaker copy of milestone review. This slice deliberately creates no new
operator control: its value is that later public ordering can reuse behavior
already proven in milestones.

### Guarantee posture

- **Strict — default behavioral parity.** Given the same persisted run,
  workspace, authority, worker outcomes, and operator actions, the milestone
  observes the same physical-call order, validation decisions, review/fix/debt
  outcomes, persisted evidence, stop/failure result, seal, and Git history.
- **Strict — current-content closure.** Accepted byte changes invalidate prior
  whole reviews; closure cites the current cycle's effective-clean reviews and,
  when the existing cadence requires it, current verification evidence.
- **Strict — durable accepted history.** Existing atomic writes, append-only
  rounds/events/seals, WIP/amend records, and pending-WIP/pending-gate recovery
  remain the authority after restart.
- **Best-effort — physical-call uniqueness.** Delivery retains its inherited
  at-least-once execution: a completed call whose result was not saved may be
  replayed. This slice adds no exactly-once or retry-delivery promise.
- **Optimistic / eventual — none.** There is no new compare-and-set workflow,
  queue, replication, convergence timer, notification, or UI-freshness promise.

### Dependencies and consumers

There is no earlier-slice dependency. The slice depends on the existing state
machine, worker-result validation, Prompt Router and Staffing Router authority,
task-linked call evidence, review evidence fingerprint, Git WIP/amend/gate
operations, and milestone adapter. It adds no third-party dependency, store,
schema version, migration, service process, or public API.

The milestone driver is the only runtime consumer changed. The service keeps
launching the same driver command and continues to read the same state. The task
catalogue, direct task host, panel, Agent99, and every granted read-only root are
untouched.

### Non-goals

- No public `reviewed_task` or `deep_task`, catalogue entry, order schema,
  service route, panel control, or native reviewed-task result.
- No per-order producer, review-breadth, debt, cap, or implementation-size
  choice; Slice 2 owns those choices.
- No new Prompt Router route and no change from the current physical
  `agent_call` task records; Slice 3 owns that call boundary and rethink
  continuity for reviewed tasks.
- No new reviewed-task seal/result/recovery contract; Slice 4 owns that public
  closure. This slice only preserves the milestone's current seal and recovery.
- No deep-task composition, parent/child record, accounting aggregation, or
  standalone ordering.
- No change to the current four-slice/final in-slice verification cadence; the
  later sibling-verification slice owns the five-slice replacement.
- No change to milestone plan establishment, design repair, reconciliation,
  higher-level closure, aggregate ledgers/accounting, stop, liveness, sync, or
  deployment.
- No defensive validation of trusted lifecycle inputs emitted by the
  orchestrator itself, and no edit in a granted read-only repository.

### Acceptance criteria

The slice is accepted when the current milestone path uses one reusable
reviewed-work boundary and all externally inspectable lifecycle facts remain
unchanged. A focused parity test must exercise that boundary as one unit of work;
the retained lifecycle tests remain the golden for call sequence, persisted
history, current-byte review, fix/debt behavior, recovery, verification, and Git
commits. No assertion may be weakened merely to accommodate the extraction.

### Risks

The principal risk is hidden milestone coupling: an extraction could reorder a
call, lose hot authority, duplicate a task or commit after restart, accept stale
review evidence, or advance milestone scheduling from the reusable component.
A second risk is implementing later slices early by changing task identity,
routes, results, or cadence while moving the lifecycle. Exact golden outcomes,
restart cases, and unchanged catalogue/cadence checks expose those failures.

### Reuse posture

The workspace, its dependencies, and all granted roots were searched. They
contain no second reviewed-work engine to adopt. The existing lifecycle is the
asset to reuse; the independent Brainstorming lifecycle demonstrates the local
pattern of separating reusable execution from a thin task adapter. The cheapest
sufficient change is therefore one internal reviewed-work boundary consumed by
the milestone, not a wrapper around a synthetic milestone and not a duplicate
state machine.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Slice boundary | Introduce one repository-internal reviewed-work lifecycle boundary for one selected production through its existing seal/gate outcome. The milestone driver is its only runtime consumer in Slice 1; milestone sequencing and closure remain outside it. No module or symbol name is a public contract. | `implementation/milestones/deep-reviewed-tasks/skeleton.md:48-66,99`; current combined dispatcher `orchestrator/driver.py:355-399,7715-7759` | touch the lifecycle ownership seam and milestone delegation; do-not-create a second engine, synthetic milestone, public entry point, or milestone scheduler inside the boundary |
| Default authority and convergence | The boundary consumes the current run's goal/design material, project context, material, complete amendment set, prompt/staffing authority, review-seat order, debt policy, and caps exactly as the milestone does now. Untouched defaults still use the two assigned review families and current debt behavior; accepted candidate changes restart whole review at the first seat. | `implementation/milestones/deep-reviewed-tasks/skeleton.md:28-46,99-100`; authority fingerprint `orchestrator/driver.py:1511-1553`; review seats `orchestrator/driver.py:9491-9555`; restart/advance `orchestrator/state.py:1110-1153` | touch only who owns progression; do-not-cache authority, choose families in the lifecycle, simplify reviewer/fixer separation, or expose Slice 2 policy |
| Persisted parity | Existing schema version `3`, unit kinds/statuses, unit fields, task links, round/event/seal history, failure behavior, and projections retain their current shapes and meanings. Agent-call productions and every review/fix/delta call retain their existing `agent_call` task records; a Brainstorming-selected production retains its existing Brainstorming task record. | state vocabulary `orchestrator/state.py:44-79,184-228`; guarded transitions `orchestrator/state.py:806-855`; current task admission `orchestrator/driver.py:3536-3699,7053-7097`; Slice 3 owner `implementation/milestones/deep-reviewed-tasks/skeleton.md:101` | touch no persisted schema or reader; do-not-migrate/backfill history, invent lifecycle statuses/events, remove call task records, or reinterpret resumable runs |
| Current-byte seal and Git gate | A seal is available only from the current cycle's last effective-clean whole review for every assigned family and the current review-evidence fingerprint. With existing Git gating enabled, production opens one WIP, accepted fixes amend it, and the deterministic gate records `gate_commit`; Git-disabled behavior remains unchanged. No reviewed-task native result is added here. | seal predicate `orchestrator/state.py:1195-1236`; deterministic closure `orchestrator/driver.py:11506-11556`; WIP/amend/gate operations `orchestrator/gitops.py:638-694,741-749`; Git toggle and Slice 4 owner `orchestrator/driver.py:151-155`; `implementation/milestones/deep-reviewed-tasks/skeleton.md:102` | touch delegation around the existing mechanisms; do-not-seal stale evidence, add a seal worker, add another commit layer, force a new Git policy, or implement Slice 4's result |
| Recovery and delivery | Pending WIP and pending gate intent continue to be persisted before Git effects and recovered without opening later work first. State saves stay atomic and append-only. Physical worker calls retain inherited at-least-once semantics; no exactly-once, eventual-delivery, or retry ledger is promised. | state guarantees `orchestrator/state.py:1-17`; WIP recovery `orchestrator/driver.py:6944-6968,7277-7320`; step delivery `orchestrator/driver.py:7715-7759`; gate recovery `orchestrator/driver.py:12582-12664` | touch recovery only as needed to call the same lifecycle boundary; do-not-add a queue, deduplication store, retry service, compatibility lane, or stronger delivery claim |
| Public and downstream boundary | For Slice 1 the catalogue remains exactly `agent_call`, `brainstorming`; `GET /api/task-executors`, `GET/POST /api/tasks`, and `GET /api/tasks/<id>` retain their current behavior. Prompt Router's current route table, rethink behavior, direct-task host, panel, and four-slice/final in-slice verification stay unchanged. | catalogue `orchestrator/tasks.py:41-100,202-204`; routes `orchestrator/service.py:4581-4631,4833-4840`; current prompt routes `orchestrator/prompt_router.py:28-49`; current cadence `orchestrator/driver.py:52-53,1451-1467`; downstream owners `implementation/milestones/deep-reviewed-tasks/skeleton.md:100-109` | touch none of these surfaces; do-not-add executor ids/routes/errors, alter physical-call identity or rethink, publish standalone work, compose deep tasks, or change verification cadence |

### Verification Contract

Focused commands:

`python3 -m unittest orchestrator.tests.test_reviewed_lifecycle orchestrator.tests.test_driver_mock orchestrator.tests.test_fix_loop orchestrator.tests.test_seal_predicate orchestrator.tests.test_worker_tasks orchestrator.tests.test_session_repository_seal`

`python3 -m unittest orchestrator.tests.test_verification_chronology orchestrator.tests.test_driver_implementation_size orchestrator.tests.test_p3_debt orchestrator.tests.test_tasks orchestrator.tests.test_task_api`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| One reusable boundary owns one existing reviewed cycle | new `test_default_boundary_matches_milestone_lifecycle_golden` in `orchestrator.tests.test_reviewed_lifecycle` | The reusable boundary and milestone entry exercise the same scripted production and yield the same physical-call sequence, unit/round/seal/event evidence, failure/stop outcome, and Git gate; the boundary does not choose or advance another milestone unit. | strict |
| Full default lifecycle remains unchanged | retained `TestHappyLifecycle.test_full_lifecycle_covers_final_verification_failure` | The exact unit sequence, review/fix/delta rounds, verification repair, seal citations, WIP/amend/gate events, clean worktree, and milestone closure remain the existing golden. | strict |
| Candidate changes and debt cannot counterfeit convergence | retained `SealPredicateDriverTest.test_changed_bytes_restart_both_reviewers_from_family_zero`; retained `TestFixLoopSameEpisode.test_dirty_delta_loops_then_restarts_reviews_from_codex`; retained `TestP3Debt.test_doc_round_p3_only_is_deferred_as_debt` | Changed bytes force fresh whole reviews; dirty deltas return to the fixer; only current effective-clean reviews satisfy the seal; debt classification retains its existing eligibility and evidence. | strict |
| Authority and recovery remain current at their established boundaries | retained `WorkerTaskCutoverTest.test_recovery_refreshes_authority_without_rewriting_order`; retained `TestResume.test_new_driver_mid_fix_episode_continues_to_close` | A resumed physical call uses current episode authority without rewriting admitted history, and an interrupted fix episode continues to the same terminal evidence. | strict history / best-effort call uniqueness |
| Rethink and size-cut outcomes retain their meaning | retained `RepositorySealTest.test_repository_rethink_reenters_fresh_without_application`; retained `DriverImplementationSizeTest.test_delivered_soft_steer_records_metrics_on_part_a_cut` | Successful rethink re-enters the interrupted production fresh under the same milestone unit, and a controlled implementation cut retains its existing part/evidence outcome; neither becomes a new public task behavior in this slice. | strict parity |
| WIP and gate crash windows do not admit later work | retained `DriverImplementationSizeTest.test_failed_wip_commit_is_retried_before_reviews_open`; retained `DriverImplementationSizeTest.test_failed_part_a_gate_is_retried_before_part_b_can_open` | Recovery completes or fails the recorded WIP/gate before review or successor work can progress, with no duplicate accepted commit. | strict persisted effects |
| Later-slice surfaces remain absent | retained `TaskContractsTest.test_catalogue_has_exact_builtins_and_self_description`; retained verification chronology module | Catalogue ids remain exactly the current two, direct API behavior stays unchanged, and complete verification still follows the current four-slice/final in-slice chronology. | strict compatibility |

Repository-level commands remain:

`python3 -m unittest orchestrator.tests.suite_checkpoint`

`python3 -m unittest orchestrator.tests.suite_extended`

They are the normal checkpoint and architectural complement respectively
(`orchestrator/README.md:562-577`).

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The mandate's operator and calling products need one production that carries its full review discipline without being milestone-owned. Current milestone users are not in an incident—the existing path works—but without this extraction later public reviewed work must either remain unavailable or copy a large lifecycle. A copied path can accept different bytes, replay different calls, or produce a different commit; repository changes are reversible, but spent calls and a falsely accepted result are not. | need and caller authority `implementation/milestones/deep-reviewed-tasks/goal.md:16-40`; current lifecycle hard-wiring `orchestrator/driver.py:355-399,7715-7759` |
| machinery | This slice introduces one internal reviewed-work lifecycle component, one milestone use of that component, and focused parity coverage. It adds no public API, dependency, store, schema, or process. The component exists only to own the already-authorised production-through-gate outcome once, leaving milestone coordination outside. | assigned outcome `implementation/milestones/deep-reviewed-tasks/skeleton.md:48-66,81-94,99`; current component seams `orchestrator/state.py:806-855`; `orchestrator/gitops.py:638-749` |
| consumers_touched | Verified directly touched runtime consumer: the milestone driver's action path. State, Git, worker-task evidence, and verification remain reused dependencies. The service is an unchanged indirect consumer because it launches the same driver command. The direct task host currently branches only between `agent_call` and Brainstorming and is not touched. Searches across Life, Agent99, life_product_components, and Tutor found no code consumer of `reviewed_task`, `deep_task`, or a reusable review engine; those roots remain read-only. | driver dispatch `orchestrator/driver.py:355-399,7715-7759`; service launch `orchestrator/service.py:2566-2567`; direct host `orchestrator/task_api.py:580-590` |
| cheaper_alternative | Reusing and separating the existing lifecycle is cheapest. Documentation or configuration cannot make driver-owned progression reusable. Doing nothing blocks the later public type; a thin adapter over a synthetic milestone would retain milestone sequencing and state, while a new engine would duplicate solved review/Git machinery. The analogous Brainstorming task adapter is thin because its lifecycle is already independent—the pattern to reuse, not another engine to invent. | current milestone-shaped state `orchestrator/state.py:19-25,160-169`; combined driver boundary `orchestrator/driver.py:355-399,7715-7759`; existing thin adapter `orchestrator/brainstorming_tasks.py:1-24` |
| cost | Build cost is a bounded architectural extraction plus parity tests; review cost is broader because the behavior has many recovery edges. There is no data migration, new call, daemon, dependency, or operating loop, so runtime and operational cost should remain unchanged. Maintenance cost falls by giving later callers one lifecycle. Omission is reversible now but forces later duplication or blocks the mandate; any parity failure is also reversible before public activation. | no-new-machinery boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:81-94`; current call/state costs `orchestrator/driver.py:7715-7759`; existing schema `orchestrator/state.py:44-79` |
| threat_model | No new remote or product-supplied input enters in this slice. The internal host context—selected unit, operator authority, prompt/staffing configuration, and orchestrator-emitted task links—is trusted and receives no new defensive schema. Existing untrusted inputs remain worker/model JSON and worker edits; the existing output contracts, project extensions, current-byte fingerprint, and own-root Git checks continue to guard them. | worker validation boundary `orchestrator/runners.py:2922-2982`; report/fix contracts `orchestrator/contracts.py:874-924,1014-1030`; current-byte binding `orchestrator/driver.py:1511-1553`; Git root guard `orchestrator/gitops.py:139-152` |
| pinned_facts | The six hard rows above pin the single internal boundary, unchanged default authority/convergence, exact persisted compatibility, current-byte seal/Git behavior, inherited recovery/delivery posture, and the absence of every downstream public/cadence change. No internal class, function, or file name is pinned because none is a public or cross-slice behavior. | this note, `Pinned-Facts Table`; slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:96-110` |
| verification | The focused contract combines one new boundary-parity test with the existing full lifecycle golden, seal/fix/debt cases, hot-authority recovery, WIP/gate crash windows, catalogue/API compatibility, and verification chronology. Both repository suite partitions remain required for this architectural extraction; neither may be represented as run unless actually executed during implementation. | lifecycle golden `orchestrator/tests/test_driver_mock.py:577-841`; seal tests `orchestrator/tests/test_seal_predicate.py:145-204`; recovery cases `orchestrator/tests/test_driver_implementation_size.py:581-633,1972-2031`; suite authority `orchestrator/README.md:562-577` |
| enforceability | Existing state transitions, result validators, review fingerprints, seal predicate, atomic append-only save, and Git WIP/amend/gate operations can enforce every parity invariant. The one missing mechanism is an independently invocable reviewed-work boundary: current dispatch is still owned by `Driver.step`. That is the design gap this slice must close, and the new parity test must exercise it. No public success, exactly-once delivery, or eventual behavior is claimed before later mechanisms exist. | missing seam `orchestrator/driver.py:7715-7759`; state enforcement `orchestrator/state.py:1-17,806-855,1110-1236`; Git enforcement `orchestrator/driver.py:7277-7320,12582-12664` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| One reviewed cycle is reusable without owning milestone sequencing | **Current design gap:** the action/handler table is inside `Driver.step` at `orchestrator/driver.py:7715-7759`; state already exposes guarded per-unit progression at `orchestrator/state.py:806-855`. | Add the internal boundary, make the milestone consume it, and pass the new boundary-versus-milestone golden without a test-only runtime. |
| Default calls, authority, and accepted history remain identical | Current authority snapshot/fingerprint is at `orchestrator/driver.py:1511-1553`; call dispatch/persistence is at `orchestrator/driver.py:3536-3699,7715-7759`; immutable rounds are recorded at `orchestrator/state.py:1060-1126`. | Compare exact calls and persisted evidence under the retained happy lifecycle, fix/debt, hot-authority, and resume fixtures. |
| Only current effective-clean reviews can seal | Candidate changes reset the cycle at `orchestrator/state.py:1110-1126`; `seal_predicate_reviews` rejects missing, dirty, invalidated, or fingerprint-stale evidence at `orchestrator/state.py:1195-1236`; deterministic closure rechecks it at `orchestrator/driver.py:11506-11556`. | Mutate accepted bytes and resume from pre-seal; require fresh family evidence before the existing seal event. |
| WIP/amend/gate effects remain recoverable and singular | Pending WIP is persisted and adopted at `orchestrator/driver.py:6944-6968,7277-7320`; Git provides WIP, amend, and gate operations at `orchestrator/gitops.py:638-694,741-749`; pending gate is consumed before successor work at `orchestrator/driver.py:12582-12664`. | Retain the WIP and gate crash-window tests and compare commit/event identity, not merely terminal status. |
| No stronger delivery or public-surface guarantee leaks into Slice 1 | The current step contract states at-least-once calls at `orchestrator/driver.py:7715-7720`; the catalogue and API expose only the existing types/routes at `orchestrator/tasks.py:41-100` and `orchestrator/service.py:4581-4631,4833-4840`. | Require unchanged delivery wording, exact two-id catalogue, route tests, and current verification chronology. |
