# Slice 05 — Concurrent physical-call control boundary

## Register 1 — INTENT

This slice gives the operator control over several model calls working for the
same task at once. Pausing or stopping that group must reach all its workers.
Finishing one call must not make the task appear safe to resume while another
worker can still do work. Each call keeps its own answer or failure and its own
usage evidence, even when calls finish in a different order.

It extends the task service's existing worker-control boundary. It does not
decide which candidates deserve evaluation or which calls to request. The
evaluation caller supplies that work and its allowed concurrency. Existing tasks
that use one call retain their current behavior.

### Dependencies and non-goals

The boundary depends on existing task ownership, process supervision, worker
results, pricing, and accounting. Its next consumer is the assigned evaluation
work; a small test caller exercises the shared boundary here without publishing
an unfinished creativity executor.

Candidate batching, evaluation validation, live-authority resolution, search
progress, accepted-result checkpoints, and creativity lifecycle composition
remain with their assigned slices. This slice adds no scheduler, task queue,
provider, retry policy, recovery service, accounting ledger, product adapter, or
presentation feature.

### Risks and acceptance

The main risks are losing a sibling's worker evidence, missing a control request
while a call starts or corrects its response, and confusing concurrent charges.
A host can also die while its workers survive. Unknown process liveness must
remain visibly unresolved; there is no promised stopping time or restoration of
worker effects. Already incurred model spend cannot be undone.

Acceptance uses controlled local workers, including real subprocesses for the
survival boundary, and the existing single-call regression fixtures. It requires
observable group control and correct retained evidence, without live model spend.

## Register 2 — PINNED-FACTS TABLE

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Shared delivery boundary | Extend the task-owned `TaskExecutionLease`, runner `ActiveCallControl` / `call_worker`, and `DirectTaskHost` seams for Slice 5. Python 3.9+ standard library only. The cross-slice contract is the **task-owned call group** described in F2–F5; its consumer is the assigned evaluation caller, not a new TaskExecutor. | `implementation/milestones/creativity/skeleton.md:126-129,147,149`; `orchestrator/task_execution.py:21-47`; `orchestrator/runners.py:542-571,2982-3027`; `orchestrator/task_api.py:890-908`; `orchestrator/README.md:46` | touch those existing modules and focused tests; do-not-add a scheduler, provider, or product adapter, or change search, prompts, validators, staffing, configuration/catalogue, service routes, panel, skeleton, or any additional root |
| F2 — Bounded group contract | One task owner can have simultaneous independently identifiable calls under its existing execution lease. The caller's admitted positive bound limits all in-flight physical attempts, including response correction; bound one works, and larger bounds permit actual overlap. No hidden global ceiling. A completed member's result or original error remains associated with that member and can be delivered while another member runs; it does not establish group quiescence. | `implementation/milestones/creativity/skeleton.md:47-48,126-127,144,147`; single-owner lease `orchestrator/task_execution.py:30-59`; per-attempt caller seam `orchestrator/runners.py:2982-3027` | own bounded physical admission and member association; do-not-own candidate batches, a waiting-work queue, child task records, or evaluation acceptance |
| F3 — Whole-group Pause and Stop | Accepted Pause/Stop fences further group work and reaches every in-flight member, including a correction attempt. A call racing with control acceptance either does not start or remains covered by interruption and quiescence; a late control binding cannot escape. Other tasks' workers are unaffected. Pending pause remains `pausing` with `can_resume=false`; Stop retains the operator's cancellation outcome (`failure`), even if a worker prints success. | `implementation/milestones/creativity/skeleton.md:126,146-147`; `orchestrator/task_api.py:215-240,993-1035,1313-1318,1360-1391,2585-2606`; control renewal `orchestrator/runners.py:631-643,3480-3496` | extend group use of existing controls and durable operator intent; do-not-use process-global `kill_active_worker_groups` for a task action or add control routes, statuses, events, or error codes |
| F4 — Physical quiescence | A member's success, error, or completion callback crosses the runner boundary only when its own recorded process group is quiescent. Whole-group settlement, Resume, and workspace reuse/deletion remain blocked while any member is active or its quiescence is unknown, including after host death or a worker leader's exit. Completion of one member cannot remove the protection for another, including a dispatch interrupted before its identity was recorded. Lease acquisition/inspection does not kill a surviving group. | `implementation/milestones/creativity/skeleton.md:104-116,147`; `orchestrator/task_execution.py:1-6,104-168`; `orchestrator/runners.py:187-231,1991-1992,2687-2702`; `orchestrator/task_api.py:961-984,1041-1068,1697-1721`; `orchestrator/service.py:5084-5099` | extend existing durable worker evidence and positive quiescence checks to all members; do-not-substitute thread completion, leader exit, control acknowledgement, or terminal receipt for process quiescence; no automatic recovery or effect rollback |
| F5 — Per-call evidence and accounting | Distinct physical attempts retain distinct identity and caller-supplied job/generation/batch association, actual family/model/effort, `prompt_set_fallback`, duration, tokens, and cost evidence. The existing single response-correction allowance is unchanged. Correction, failure, and interruption retain their incurred usage; concurrent completion cannot overwrite a sibling or charge it twice. Group accounting uses existing pricing/sums once per recorded attempt, preserving `token_usage_partial` and `cost_partial`; duration is summed call time. An aggregate is not an additional charge. This supplies call evidence, not a creativity search checkpoint or terminal composer. | `implementation/milestones/creativity/skeleton.md:89-90,112-116,126-129,147`; `orchestrator/runners.py:2959-3004,3554-3626`; `orchestrator/task_api.py:724-766,1466-1515,2502-2509`; aggregation `orchestrator/tasks.py:1512-1544` | retain existing runner carriers and task accounting authority, with caller context; do-not-add task retries, create a second ledger, invent missing usage, or count a logical result in addition to its physical attempts |
| F6 — Existing consumers remain compatible | Existing single-call callers and previously recorded single-worker lease evidence retain their meaning. In particular, existing direct-call Pause may wait for and retain the active result; using the new group does not rewrite that behavior. Existing `ExecutionBusy` / `TaskControlConflict` boundaries and control API responses remain in force. | `orchestrator/task_execution.py:17-18,71-83,104-124`; `orchestrator/tests/test_task_controls_api.py:270-307,398-412`; `orchestrator/service.py:4992-5008,5033-5039,5064-5067`; `implementation/milestones/creativity/skeleton.md:63-68,139,149` | preserve current worker, reviewed-task, deep-task, and transport contracts; do-not-publish creativity or retrofit unrelated discussion controls |
| F7 — Guarantee posture and trust | **Strict:** F2's bound/association, F3's task-scoped control fence, F4's conditional safety boundary, F5's accounting of recorded calls, and F6's compatibility. **Best-effort:** availability of auxiliary call evidence and provider-reported usage; no provider-side exactly-once, fixed stopping time, sandbox, or restoration guarantee. **Optimistic:** existing live authorities are unchanged; no new transaction across them. **Eventual:** existing panel polling is unchanged and never grants permission to resume. Operator, caller code, emitted context, libraries, and OS APIs are trusted. | `implementation/milestones/creativity/skeleton.md:78-116,160`; auxiliary evidence `orchestrator/task_api.py:2514-2519,2578-2584`; conditional process observation `orchestrator/runners.py:174-219` | test the extension's ownership and bookkeeping; do-not-add malformed-internal-data defenses, dependency policing, new security hardening, or stronger delivery claims |

### Acceptance criteria and tests

T1–T6 are new obligations in `orchestrator/tests/test_task_call_group.py`, not
claims of existing passing tests. Reuse current lease, host, and fake-CLI
fixtures. Observe call starts, outputs, controls, retained records, and process
liveness; no journal layout or thread scheduling order is prescribed.

1. **T1 — `test_group_bound_and_independent_completions` (F2, F4):** offer more
   ready calls than the bound; exercise bounds one and two. Observe the cap and
   actual overlap at two. Finish members out of order: each returns its own
   outcome while the remaining member still prevents group quiescence. No child
   task is admitted.
2. **T2 — `test_group_pause_and_stop_reach_all_members` (F3, F4):** pause and stop
   a task with multiple active workers while a different task remains active.
   Every targeted worker receives control; the other task continues. Resume is
   unavailable until the targeted group is quiet; cancellation cannot publish
   worker success. Exercise both template and live transports.
3. **T3 — `test_group_control_covers_dispatch_and_repair` (F2, F3, F5):** place
   control requests across dispatch/control-binding and response-correction
   boundaries. No later attempt escapes the accepted control. A correction
   remains bounded, identifiable, and interruptible while a sibling runs; the
   first attempt's charge survives. Use the runner's existing correction policy.
4. **T4 — `test_group_quiescence_survives_owner_death` (F4, F6):** run real local
   workers under one owner and kill the owner. Reacquisition stays blocked while
   either worker survives; one member finishing cannot clear the other. Include
   a surviving descendant after leader exit and an actual interrupted dispatch
   before identity recording. Known groups become eligible only once all are
   quiet; unknown dispatch evidence remains unresolved. Cover both transports
   and retained single-worker evidence.
5. **T5 — `test_group_outcome_waits_for_own_quiescence` (F2–F4):** for success and
   failure in both transports, hold one member's process-quiescence observation
   unresolved. Its result/error and completion callback remain withheld, while
   an independently quiet member can deliver its own outcome. Releasing the
   observation delivers the original outcome; Pause/Stop cannot waive the fence
   or trigger another provider call.
6. **T6 — `test_group_accounting_keeps_each_physical_attempt` (F5):** combine
   out-of-order success, operational failure, and interrupted correction with
   distinguishable call context, actual staffing, fallback and usage. Retained
   evidence associates every recorded attempt correctly; aggregate duration,
   tokens and priced costs include each once, including after rereading the
   records. Unknown usage/cost keeps partial flags. Overlapping durations are
   summed call time, not group wall time; no aggregate is charged again.

Acceptance requires T1–T6 plus existing single-call, crash, control, and accounting
regressions. Scope review checks F1. After implementation run:

```sh
python3 -m unittest orchestrator.tests.test_task_call_group orchestrator.tests.test_task_execution orchestrator.tests.test_task_result_quiescence orchestrator.tests.test_task_controls_api orchestrator.tests.test_task_resume_accounting orchestrator.tests.test_task_cancel_recovery orchestrator.tests.test_task_family_quiescence orchestrator.tests.test_runners.TestActiveProviderControl
```

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator can otherwise lose control of sibling evaluation workers, spend more model quota after a control request, or resume into a still-active workspace. Exposure begins with concurrent physical calls and increases the existing host-crash risk; spend and worker effects may be irreversible. The reviewed Slice 5 assignment establishes the need independently of the proposed extension; existing crash tests demonstrate surviving worker writes. | `implementation/milestones/creativity/skeleton.md:126,147`; `orchestrator/tests/test_task_execution.py:248-304` |
| machinery | Extend the existing lease's worker coverage, runner control membership, and host control/accounting integration. These serve bounded concurrent dispatch, whole-group intervention, safe reuse, and attributable spend respectively. Standard-library synchronization is available; no package, provider adapter, public API, scheduler, or separate store is introduced. The current single-worker lease cannot admit a second active worker. | `orchestrator/task_execution.py:104-145`; `orchestrator/task_api.py:890-908,724-766`; `orchestrator/runners.py:542-571,2982-3027`; `implementation/milestones/creativity/skeleton.md:126,147,149` |
| consumers_touched | Verified consumers are `DirectTaskHost`'s direct worker and reviewed runner, both attaching the task lease, and both subprocess transports invoking its spawn/finish hooks. Service control and deletion functions consume the host/lease and must continue to work without route edits. Runtime dispatch has no creativity branch yet: its evaluation caller is the assigned next consumer, exercised here through a test caller. No granted-root client is changed. | `orchestrator/task_api.py:2334-2339,2521-2539,1723-1759`; `orchestrator/runners.py:1820-1831,1991-1992,2477-2487,2687-2688`; `orchestrator/service.py:5006-5008,5033-5039,5064-5067,5084-5099`; `implementation/milestones/creativity/skeleton.md:127` |
| cheaper_alternative | Reuse is the sufficient option: workspace and dependency searches found the existing Python lease/control machinery; all granted roots and their installed dependency sources were also searched. Related Life/Agent99/LPC/Tutor code uses Elixir task streams for database or directory probes, not this durable CLI boundary. Standard-library [bounded synchronization](https://docs.python.org/3.9/library/threading.html#threading.BoundedSemaphore) supplies capacity control; [future cancellation](https://docs.python.org/3.9/library/concurrent.futures.html#concurrent.futures.Future.cancel) cannot interrupt a running worker. Serial execution omits mandated overlap; documentation/configuration alone cannot extend the single-worker record. | `orchestrator/README.md:46`; `orchestrator/task_execution.py:126-145`; `/Users/siddhartha/Development/source/life/apps/life_transport/lib/life_transport/storage/spanner/session_pool.ex:1334-1356`; `/Users/siddhartha/Development/source/life_prod/agent_99/apps/agent_99/lib/agent_99/actor_directory/visible_set.ex:47-58`; `/Users/siddhartha/Development/source/life_prod/life_product_components/elixir/apps/life_product_workspaces/lib/life_product_workspaces.ex:577-585`; `/Users/siddhartha/Development/source/life_prod/tutor/web/vendor/life_product_components/elixir/apps/life_product_workspaces/lib/life_product_workspaces.ex:577-585` |
| cost | Build/maintenance cost is a group extension across three existing seams and focused race/process tests. Review concentrates on shared-consumer regressions and attribution. Existing worker evidence needs compatible interpretation, not a product-data migration. Operations retain current control inspection and bounded local resources; unknown liveness can delay manual Resume indefinitely. Omission either forces serial evaluation or leaves concurrent workers unprotected. The extension is removable before integration, but recorded live-worker protection cannot be discarded. | `implementation/milestones/creativity/skeleton.md:126-129,147`; `orchestrator/task_execution.py:104-164`; `orchestrator/tests/test_task_execution.py:225-238`; `orchestrator/README.md:44-46` |
| threat_model | This slice introduces no untrusted order/text parser. Providers and source authors can influence semantic replies, but their structural admission remains in the existing runner/contracts. Task identity, call context, bounds, configuration, and libraries come from trusted operator/product machinery. The failures handled here are ordinary concurrency, interruption, process survival and unavailable OS observations, not a hostile internal emitter. Worker tool effects retain the existing full-access trust posture; no sandbox or extra internal-data validator is justified. | `implementation/milestones/creativity/skeleton.md:104-116,160`; `orchestrator/runners.py:174-219,2982-3027,3435-3444`; `orchestrator/README.md:631-634` |
| pinned_facts | F1 fixes the shared scope; F2 fixes the bounded call-group seam; F3 fixes task-scoped intervention; F4 fixes per-member delivery and whole-group reuse safety; F5 fixes attribution and recorded accounting; F6 preserves current consumers; F7 limits guarantees and trust. No new persistence schema, scheduling order, error vocabulary, or creativity lifecycle is pinned. | `implementation/milestones/creativity/skeleton.md:63-76,112-116,126-129,147,149`; `orchestrator/task_execution.py:104-168`; `orchestrator/runners.py:2959-3027`; `orchestrator/tests/test_task_controls_api.py:270-307` |
| verification | T1–T6 test the new producer's observable group behavior. Existing real-owner-death, delayed-outcome, repair-control and accounting fixtures supply the surrounding standard; existing single-call tests protect current consumers. New tests use legitimate calls and platform uncertainty, not forged trusted payloads or dependency misbehavior. The command above is implementation acceptance, not a claim that group support already exists. | `orchestrator/tests/test_task_execution.py:114-138,225-319`; `orchestrator/tests/test_task_result_quiescence.py:95-166`; `orchestrator/tests/test_runners.py:3694-3744`; `orchestrator/tests/test_task_resume_accounting.py:115-177` |
| enforceability | F2 is expressible with standard-library bounded admission and the existing per-attempt runner seam. F3 uses durable host control plus `ActiveCallControl.interrupt`/`renew` and the transport's process-group interrupt. F4 extends the existing inherited lease, durable dispatch evidence, and positive group inspection to every member. F5 uses runner physical evidence, existing pricing/sums, and identity-aware task receipt handling; the extension must preserve every member through these paths. F6 is pinned by current consumer regressions; F1 by scope review. F7 adds no stronger delivery claim. These primitives exist; group integration is the work, not already verified behavior. No governing-design contradiction or unenforceable guarantee was found. | bounded admission `/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/threading.py:468-511,532-545`; `orchestrator/task_api.py:209-240,1360-1388,1466-1515,724-766`; `orchestrator/runners.py:631-688,187-231,2504-2509,2959-3027`; `orchestrator/task_execution.py:30-59,85-168`; `orchestrator/tasks.py:1512-1544`; `orchestrator/tests/test_task_controls_api.py:270-307` |
