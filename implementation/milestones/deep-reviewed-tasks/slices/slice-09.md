# Slice 09 — Milestone deep-slice composition

## Register 1 — INTENT (lay language)

### What this slice builds

For newly activated runs, a planned slice begins as one visible deep task. It
completes a reviewed slice note before reviewed implementation begins. If size
control discovers implementation parts, those parts run in order and each keeps
its own review, evidence, accounting, seal, and gate. The deep parent summarizes
that initial delivery without adding another commit or charge.

The milestone remains the planner and recovery owner. It decides which accepted
slice is due, controls the run, reconciles accepted plan changes, and closes the
milestone. This slice only gives its existing slice work durable public task
identities; it does not run the standalone deep-task host inside a milestone.

### Reconciliation keeps the sealed note

Accepted-plan reconciliation already keeps a retained slice's identity and
sealed note while requeueing its implementation. That behavior does not change.
If the prior deep parent or implementation child is terminal, its result stays
historical and immutable. The rebuild gets a distinct implementation reviewed
task associated with the same requeued milestone unit. It is a sibling retry,
not a child of the terminal deep task and not a new documentation-bearing deep
task.

This gives rebuilt work a lawful task identity without paying for an unrelated
documentation cycle. A removed slice gets no successor. A genuinely new slice
id still starts through the ordinary deep-task documentation gate. The existing
reconciliation barrier, rather than a task-history rewrite, decides which old
implementation gates no longer count for current progress.

### Observable acceptance

Before initial slice effects, one deep parent exists with the exact accepted
slice and both child policies frozen. Its documentation child gates the first
implementation child; a gated eligible cut alone admits the next part. The deep
parent succeeds only after the final uncut implementation child succeeds.

Before a retained implementation rebuild performs an effect, one new sibling
reviewed task exists for the requeued unit. No new documentation task, call, or
gate is created. Open superseded tasks settle without success; terminal records
do not change. The sibling owns only its rebuild evidence and gate, while run
totals continue to count each physical call once.

Runs activated before this slice keep their existing direct slice law. Public
task names, routes, result statuses, run Stop behavior, size-control ownership,
verification cadence, presentation work, and all granted product roots remain
unchanged.

### Reuse and exclusions

The implementation reuses the canonical in-run task history, public reviewed
and deep task contracts, existing child relations, reviewed lifecycle, accepted
plan requeue/barrier, Git gates, and accounting projection. Searches across the
workspace and every granted root found no second deep/reviewed engine or product
consumer to wire.

No scheduler, queue, service, store, retry ledger, new relationship kind,
migration, prompt path, accounting home, task type, route, result status, error
code, aggregate commit, reconciliation algorithm, or documentation retry is
added. Slices 10–12 still own verification composition, cadence, presentation,
and final conformance.

## Register 2 — PINNED FACTS (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Initial slice identity | A post-activation slice's initial delivery has one canonical record with `order.task_executor: "deep_task"`, associated with the accepted slice before any provider call or workspace edit. Its resolved `configuration.documentation` and `.implementation` exactly match the accepted row's producer choices plus the run's reviewed defaults. | assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:120-134`; composition `implementation/milestones/deep-reviewed-tasks/skeleton.md:18-25,63-71`; deep policy resolver `orchestrator/tasks.py:882-905`; accepted producer resolver `orchestrator/tasks.py:938-964` | touch prospective in-run admission, association, and policy handoff; do-not-call `DirectTaskHost`, add another store, or resolve a different policy at execution |
| Initial child sequence | The first child is `reviewed_task` with `configuration.task_kind: "draft_slice_note"` and `parent: {"task_id": <deep-id>, "phase": "documentation", "part": null}`. Its successful gate alone admits implementation part `a`, also `reviewed_task`, with `configuration.task_kind: "implement"` and `parent.phase: "implementation"`. Only an eligible gated `implementation_cut` admits sequential `b`, `c`, and later parts. | deep law `implementation/milestones/deep-reviewed-tasks/skeleton.md:63-71,149-150`; relation enforcement `orchestrator/task_api.py:171-231`; existing orders and cut gate `orchestrator/task_api.py:887-965` | touch canonical related admission and milestone unit association; do-not-embed children, pre-plan parts, run parts in parallel, or admit from an ungated result |
| Reconciled implementation successor | When accepted-plan reconciliation retains a slice id and requeues its same implementation unit, further work is one distinct sibling `reviewed_task` with `configuration.task_kind: "implement"`, no `parent` relation to the historical deep task, and `request.context.unit` naming that requeued unit. It is admitted after the reconciliation barrier and before a rebuild effect. No documentation task/call/gate runs. Removed ids get no successor; new ids start with the initial deep sequence. | governing refinement `implementation/milestones/deep-reviewed-tasks/skeleton.md:73-81,151`; current retained-id requeue `orchestrator/state.py:1777-1859`; reconciliation close/order `orchestrator/driver.py:5941-5989`; current task-to-unit projection `orchestrator/state.py:2655-2676` | touch settlement and reviewed-task association at the milestone reconciliation boundary; do-not-reopen a task, attach a child to a terminal parent, create a successor deep task, redraft the retained note, or change which unit reconciliation requeues |
| Results, gates, and accounting | Initial children keep their native results and gate commits. The deep parent aggregates only those children, records `native_result: null`, no physical charge, and no commit. A reconciliation sibling owns its later result, evidence, charge, and gate separately. Historical terminal results never change; barrier-invalidated gates do not advance the current plan; run totals count every physical charge once. | ownership `implementation/milestones/deep-reviewed-tasks/skeleton.md:63-81,93-103,150-151`; terminal mutation `orchestrator/tasks.py:1183-1197`; deep aggregation `orchestrator/task_api.py:968-999`; current barrier `orchestrator/state.py:1418-1522` | touch parent/result projection and the milestone advancement gate; do-not-flatten results, recount a charge, add an aggregate commit, or treat historical task success as current plan success |
| Size-control boundary | Only an implementation `reviewed_task` produced by `agent_call` may activate `implementation_size_control`. The initial deep parent and a reconciliation sibling merely consume their own eligible implementation result. Direct `agent_call`, direct Brainstorming, and Brainstorming-produced reviewed implementation remain without size monitoring, intervention, interruption, stabilization, or size-cut guarantees. | operator amendment A1; milestone law `implementation/milestones/deep-reviewed-tasks/skeleton.md:44-49,146`; applicability `orchestrator/tasks.py:772-805`; cut consumption `orchestrator/task_api.py:955-965` | touch no controller; do-not-move size behavior into `deep_task`, reconciliation, `agent_call`, or Brainstorming |
| Public and compatibility boundary | This slice adds no executor id, route, order field, result status, error code, or public event. Generic task reads and run Stop remain the public surfaces; direct task Stop for milestone-owned records remains HTTP `409` with `milestone tasks are stopped through their run`. Pre-activation runs receive no synthetic hierarchy or task backfill. | public/compatibility law `implementation/milestones/deep-reviewed-tasks/skeleton.md:27-29,105-118,142,154`; task Stop `orchestrator/service.py:4277-4301`; history immutability `orchestrator/state.py:366-414` | touch only prospective milestone composition and additive generic reads; do-not-change direct/standalone tasks, old runs, Slices 10–12, granted roots, or deployment |
| Verification | Focused command: `python3 -m unittest orchestrator.tests.test_milestone_deep_slice_composition orchestrator.tests.test_deep_task_implementation orchestrator.tests.test_deep_task_documentation orchestrator.tests.test_plan_reconciliation orchestrator.tests.test_reconciliation_call orchestrator.tests.test_reviewed_result orchestrator.tests.test_driver_implementation_size`. New checks named `test_initial_delivery_gates_documentation_and_parts`, `test_retained_reconciliation_uses_sibling_reviewed_successor_without_redocumentation`, `test_removed_and_new_slice_reconciliation_preserve_identity_law`, and `test_results_accounting_stop_recovery_and_compatibility` must pass. Repository checkpoint and extended suites remain separate gates and are unclaimed until run. | existing deep proofs `orchestrator/tests/test_deep_task_implementation.py:139-224,246-437`; current requeue proofs `orchestrator/tests/test_state.py:2297-2355`; reconciliation close proof `orchestrator/tests/test_reconciliation_call.py:191-264`; suite authority `orchestrator/README.md:565-586` | touch one focused milestone-composition test module and retained tests; do-not-claim physical exactly-once behavior, display freshness, or unrun repository suites |
