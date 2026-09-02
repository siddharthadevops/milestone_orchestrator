# Slice 09 — Milestone deep-slice composition

## Register 1 — INTENT (lay language)

### What this slice builds

For newly activated runs, each planned slice is one visible deep task. It
completes a reviewed slice note before reviewed implementation begins. If an
eligible size cut discovers implementation parts, those parts run in order and
each keeps its own review, evidence, accounting, seal, and gate. The deep parent
summarizes the delivery without adding another commit or charge.

The milestone remains the planner and recovery owner. It decides which accepted
slice is due, controls the run, reconciles accepted plan changes, and closes the
milestone. This slice gives that existing work durable public task identities;
it does not run a second planner or the standalone deep-task host.

### Rethink continues the open task

`need_rethink` interrupts a physical call inside the current reviewed child. It
does not complete, retry, or replace that child. The child and its deep parent
stay open while Brainstorming resolves the product-design problem.

If the accepted plan retains the current slice, the same child resumes the same
production, review, or fix phase in a fresh physical call. The accepted
repository state is now the governing material and current bytes, but it is not
review evidence or a gate. Ordinary freshness and convergence rules decide what
must be reviewed again. For an implementation origin, the already successful
documentation child remains sealed, so there is no second documentation task,
call, or gate.

The continuing child keeps the producer and review policy frozen in its admitted
order. Accepted design can change what the task builds; it does not rewrite the
task order or create another identity. Later implementation parts arise only
from the existing eligible size-cut sequence and remain children of the same
open deep task.

If the accepted plan removes the current slice, the origin does not resume and
the milestone follows its existing reconciliation outcome. Terminal history is
never reopened. A genuinely new slice starts with its own ordinary deep task and
reviewed documentation child.

### Observable acceptance

Before slice effects, one deep parent exists for the accepted slice. Its
documentation child gates implementation part `a`; an eligible gated cut alone
admits `b`, `c`, or later parts. The parent succeeds only after the final uncut
implementation child succeeds.

Across a successful retained-slice rethink, the parent id and originating child
id do not change, the next physical call has the interrupted semantic phase, and
no documentation child is added. Failed Brainstorming fails the open origin. A
removed origin receives no continuation call. Every physical call remains
accounted once, including the spent call that raised `need_rethink`.

Runs activated before this slice keep their existing direct slice law. Public
task names, routes, result statuses, run Stop behavior, size-control ownership,
verification cadence, presentation work, and all granted product roots remain
unchanged.

### Reuse and exclusions

The implementation reuses canonical task history, public reviewed/deep task
contracts, existing child relations, the reviewed lifecycle, accepted-plan
reconciliation, Git gates, and accounting. Searches across the workspace and
every granted root found no second deep/reviewed engine or product consumer to
wire.

No scheduler, queue, service, store, retry ledger, new relationship kind,
migration, prompt path, accounting home, task type, route, result status, error
code, aggregate commit, reconciliation algorithm, or documentation retry is
added. Slices 10–12 still own verification composition, cadence, presentation,
and final conformance.

## Register 2 — PINNED FACTS (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Slice identity | A post-activation planned slice has one canonical `deep_task` record associated before any provider call or workspace edit. Its resolved documentation and implementation policies are frozen from the accepted slice order and reviewed defaults. | `implementation/milestones/deep-reviewed-tasks/goal.md:150-159`; `orchestrator/tasks.py:882-904`; `orchestrator/task_api.py:887-912` | touch prospective milestone admission and association; do-not-call the standalone host, add another store, or resolve a second parent policy |
| Child sequence | The first child is one documentation `reviewed_task`; its successful gate alone admits implementation part `a`. Only an eligible gated `implementation_cut` admits sequential parts `b`, `c`, or later. Every child owns its result and gate; the parent adds neither charge nor commit. | `implementation/milestones/deep-reviewed-tasks/goal.md:107-148`; relation enforcement `orchestrator/task_api.py:171-231`; existing sequence `orchestrator/task_api.py:887-965,1135-1163` | touch canonical child association and milestone advancement; do-not-embed children, pre-plan parts, run parts in parallel, or flatten their results |
| Retained rethink | `need_rethink` leaves the originating `reviewed_task` and enclosing `deep_task` open. When the accepted plan retains the current slice, the same child id resumes its interrupted semantic phase from accepted current bytes in a fresh physical call. Its admitted order, including producer and review policy, is unchanged; current-byte rules refresh evidence. No additional documentation task or gate is created. | operator amendment A2; `implementation/milestones/deep-reviewed-tasks/goal.md:101-105`; frozen task order `orchestrator/state.py:366-401`; retained-unit requeue `orchestrator/state.py:1777-1859` | touch reconciliation settlement and same-task continuation; do-not-terminalize or replace the survivor, mutate its order, create a sibling task, or rerun documentation |
| Removed and terminal work | If the accepted plan removes the current slice, its origin does not resume. Failed Brainstorming fails the open origin. Terminal parent and child results are immutable and are never reopened; a genuinely new slice follows the ordinary documentation-first deep sequence. | operator amendment A2; terminal identity `implementation/milestones/deep-reviewed-tasks/goal.md:132-148`; reconciliation close `orchestrator/driver.py:5862-5989` | touch existing removed-origin settlement; do-not-create a replacement hierarchy solely because rethink occurred or reinterpret legacy history |
| Size-control boundary | Only an implementation `reviewed_task` produced by `agent_call` may activate `implementation_size_control`. The deep parent only consumes an eligible child cut. Direct `agent_call`, direct Brainstorming, and Brainstorming-produced reviewed implementation have no size monitoring, intervention, interruption, stabilization, or cut guarantee. | operator amendment A1; applicability `orchestrator/tasks.py:772-805`; cut consumption `orchestrator/task_api.py:955-965` | touch no controller; do-not-move size behavior into `deep_task`, reconciliation, `agent_call`, or Brainstorming |
| Public and compatibility boundary | This slice adds no executor id, route, order field, result status, error code, or public event. Generic task reads and run Stop remain the public surfaces; direct Stop of milestone-owned tasks remains HTTP `409` with `milestone tasks are stopped through their run`. Pre-activation runs receive no synthetic hierarchy or task backfill. | `implementation/milestones/deep-reviewed-tasks/skeleton.md:105-118,142-154`; task Stop `orchestrator/service.py:4277-4301`; history immutability `orchestrator/state.py:366-414` | touch only prospective milestone composition and additive generic reads; do-not-change standalone tasks, old runs, Slices 10–12, granted roots, or deployment |
| Verification | Focused command: `python3 -m unittest orchestrator.tests.test_milestone_deep_slice_composition orchestrator.tests.test_deep_task_implementation orchestrator.tests.test_deep_task_documentation orchestrator.tests.test_plan_reconciliation orchestrator.tests.test_reconciliation_call orchestrator.tests.test_reviewed_call_routing orchestrator.tests.test_reviewed_result orchestrator.tests.test_driver_implementation_size`. New checks named `test_slice_delivery_gates_documentation_and_parts`, `test_retained_rethink_resumes_same_child_and_phase_without_redocumentation`, `test_removed_rethink_origin_does_not_resume_or_reopen_terminal_history`, `test_rethink_continuation_preserves_order_and_counts_physical_calls_once`, and `test_pre_activation_run_keeps_direct_slice_law` must pass. Checkpoint and extended suites remain separate gates and are unclaimed until run. | existing deep proofs `orchestrator/tests/test_deep_task_implementation.py:139-224,246-437`; existing rethink proof `orchestrator/tests/test_reviewed_call_routing.py:585-740`; reconciliation proof `orchestrator/tests/test_plan_reconciliation.py:468-541`; suite authority `orchestrator/README.md:565-586` | touch one focused milestone-composition module and retained tests; do-not-claim physical exactly-once behavior, display freshness, or unrun repository suites |
