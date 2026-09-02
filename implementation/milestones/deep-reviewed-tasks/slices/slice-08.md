# Slice 08 — Milestone skeleton composition

## Register 1 — INTENT (lay language)

### What this slice builds

This slice makes the milestone begin with one visible reviewed task for its
skeleton. The task is admitted before any model work, carries the existing
planning and review discipline, and owns the evidence, seal, result, and Git
gate for that skeleton. Individual production, review, correction, and rating
calls remain evidence inside it rather than becoming smaller tasks.

The draft plan is only a candidate while that task is open. Reviews and fixes
may change it, but no slice schedule becomes authoritative from those interim
bytes. Only the skeleton that has passed review on current contents and reached
its task gate can establish the milestone's plan and allow later work to start.

The milestone remains the coordinator. It decides what follows the approved
plan, handles later plan reconciliation and design repair, owns run stop/start,
closure, final bookkeeping, and deployment discipline, and may fail even when
an individual task result is sound. A process stop keeps an open task available
for restart. A terminal task is never reopened; a deliberate retry after a
terminal failure is a distinct attempt.

### Ownership and consumers

The reviewed task owns only the production-through-gate interior and its native
result. The milestone owns the canonical-plan anchor and projection, the move to
the next milestone step, reconciliation, aggregate run accounting, liveness,
and final closure. Its task is stored with the run and is observable through the
existing generic task reads; it is not executed through the standalone task
host or a second lifecycle state.

The immediate consumers are the milestone driver, canonical run state, generic
run-task reads, and existing run summary. Later slice composition can consume
the same contract. None of the granted product roots is changed.

### Guarantee posture

- **Strict:** one logical skeleton attempt has one durable reviewed-task id;
  admission precedes effects; success requires current-content evidence, seal,
  and that task's gate; the first plan anchor and slice projection derive from
  that gated commit; no later milestone unit starts earlier; task terminality,
  single-count accounting, run control ownership, and pre-activation run
  compatibility are preserved.
- **Best-effort:** physical-call uniqueness, delivery of a process interrupt,
  task chips, grouping, navigation, and display freshness. None can decide plan
  authority, task success, recovery, or accounting.
- **Optimistic / eventual:** none. This slice adds no queue, redelivery,
  replication, exactly-once call, eventual-display, or deployment promise.

### Dependencies

This slice depends on Slices 1–5: the reusable reviewed lifecycle and policy,
direct routed-call evidence, gate-backed native result, public reviewed-task
contract, canonical task record, and generic reads. It reuses the milestone's
existing skeleton unit and goal/amendment authority, canonical-plan validator
and Git anchor, single-writer state boundary, pending-gate recovery, run
reconciliation, stop/start, ledger generation, and final commit.

Slices 6–7 remain unchanged standalone composite consumers. This slice adds no
third-party dependency, runtime module, service process, store, scheduler,
queue, route, prompt path, accounting ledger, or product adapter.

### Non-goals

- No logical slice is converted to a deep task; Slice 9 owns that composition
  and its accepted-design repair and re-documentation consequences.
- No sibling complete-verification task, five-slice/final cadence, independent
  verification presentation, or end-to-end compatibility matrix; Slices 10–12
  own those outcomes.
- No standalone task host, private lifecycle state, milestone-specific task
  route, `skeleton_task` executor, parent-task fiction, or second plan store.
- No change to Prompt Router, Staffing Router, review/fix/delta semantics,
  current-content sealing, task result vocabulary, canonical plan schema,
  reconciliation algorithm, run accounting, or final closure commit.
- No implementation-size control. Skeleton work is documentation and its
  producer remains the job-supported agent call; direct executors,
  Brainstorming, and implementation children are untouched.
- No defensive parser or corruption test for task ids, resolved policy, result
  association, or plan-link metadata emitted by this product. Their outcomes
  are tested; only model output and edits are treated as untrusted here.
- No migration or backfill of existing runs, no edit in a granted read-only
  root, and no automated push or deployment action.

### Acceptance criteria

For a newly activated milestone, the skeleton's reviewed-task record must be
durable before the first physical call. It must use the public reviewed-task
executor with the skeleton semantic job, the run's admitted work area,
objective, staffing session, and fully resolved documentation policy. The
policy recorded on the task and the policy consumed by the lifecycle must be
the same decision. The record remains open while work proceeds. No internal
agent-call task record may be created.

Until that task has a successful gate-backed result, the run must have no first
canonical-plan anchor, no authoritative slice projection, no admitted slice
unit, and no initial-plan reconciliation. A producer result, WIP commit, clean
review, fix, deterministic seal without its gate, or valid-looking plan table is
insufficient. Reviews and fixes may replace candidate plan bytes without making
them scheduling authority.

When the task succeeds, its native result must retain the producer result,
current review evidence, and gate commit. The first canonical-plan anchor must
resolve to that same commit, and the milestone slice projection must be parsed
from the skeleton file at that commit. The existing
`canonical_plan_established` event must name that accepted revision. Only after
the result and anchor agree may the milestone admit its next unit. Recording the
task result or plan projection must add no physical charge and no second
skeleton or aggregate commit.

An unrecovered model/protocol failure, exhausted review/correction cap, or gate
failure must not establish a plan or start a slice. A terminal skeleton-task failure remains immutable and
fails the run; any later operator-authorized attempt uses a distinct task and
cannot reuse the failed task's review evidence or charges as its own. By contrast, a process crash
or run Stop before terminality must preserve the same open task id and resume
its durable lifecycle. Recovery around task admission, the gate, result
recording, and plan anchoring must converge without a duplicate logical task or
another accepted gate. Physical calls may repeat only under the existing
at-least-once limit.

Milestone task inspection must continue through the generic task reads. Direct
task Stop must continue to refuse a milestone-owned task; run Stop remains the
control surface. Later accepted plan changes must still enter the existing
milestone reconciliation path, and milestone close must remain a separate final
commit after all planned work. Runs started before activation must continue
under their recorded law without a synthetic skeleton task, result, or plan
event.

### Risks

The principal risks are admitting the task after a paid call, anchoring the
producer's first table before review, anchoring a different revision than the
task gate, opening a slice while either authority is missing, losing the task id
at a crash window, or counting the same calls in both task and run totals.
Other risks are sending a milestone task through the standalone host, exposing
direct-task Stop, reopening a terminal record on Resume, taskifying
reconciliation or closure, backfilling old runs, or making display grouping an
execution gate. The focused contracts below expose each fault.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Skeleton task identity | Each newly activated logical skeleton attempt is one canonical task record with `order.task_executor: "reviewed_task"` and `order.configuration.task_kind: "draft_skeleton"`. `draft_skeleton` permits only the `agent_call` producer. Its fully resolved policy is durable before any physical call, its result starts `null`, and internal production/review/fix/delta/classification calls create no child `agent_call` records. A normal successful skeleton therefore contributes exactly one task id. | slice assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:116`; call boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:128-133`; public job/producer contract `orchestrator/tasks.py:23-36,145-189,613-640,843-878`; record admission `orchestrator/tasks.py:1154-1197` | touch in-run milestone admission, lifecycle association, and result handoff; do-not-use `DirectTaskHost`, add a private state/store/route, create a parent-task fiction, admit per-call tasks, or let recorded and consumed policy differ |
| First canonical-plan authority | Before skeleton-task success, `milestone.canonical_plan_anchor` is absent, `milestone.slices` remains empty, no slice unit is admitted, and no initial-plan reconciliation opens. Success installs `canonical_plan_anchor.path` for the skeleton and a full `canonical_plan_anchor.revision` resolving to the same commit as `task.result.native_result.gate_commit`; `milestone.slices` is the validated projection of the skeleton file at that revision. `canonical_plan_established.accepted_revision` names that full revision and occurs only at this boundary. | assigned outcome `implementation/milestones/deep-reviewed-tasks/skeleton.md:72-76,116,137-138`; canonical parser/anchor `orchestrator/canonical_plan.py:291-302,809-846`; reviewed success gate `orchestrator/driver.py:625-669`; current early-anchor seam to replace `orchestrator/driver.py:2304-2359` | touch only the initial reviewed-result-to-plan handoff and next-unit gate; do-not-anchor from producer JSON, WIP, review, seal alone, mutable worktree bytes, or a different commit; do-not run initial-plan edits through accepted-plan reconciliation |
| Result, evidence, and accounting | Successful native result remains exactly `production_result`, `review_evidence` (`seal_attempt`, `reviews`, `verification_event_seq`), and `gate_commit`. The canonical task result mutates once from `null` to terminal `success` or `failure`. The task and run each project the same retained physical evidence without recording a charge for the task result, plan projection, or milestone parent; run totals count every physical charge once. | result law `implementation/milestones/deep-reviewed-tasks/skeleton.md:129,133,136`; exact result projection `orchestrator/driver.py:625-669`; null-to-terminal mutation `orchestrator/tasks.py:1182-1197,1378-1452`; unit accounting `orchestrator/state.py:2503-2522` | touch outer task attribution and terminal projection; do-not-flatten or rename native fields, copy evidence into a new store, count a result as work, replace the task gate, or promise physical exactly-once delivery |
| Milestone ownership and control | Plan establishment, later accepted-range reconciliation, next-step sequencing, higher-level closure/ledgers, aggregate run accounting, run Stop/start, and deployment posture remain milestone law. `GET /api/tasks?run_id=<run-id>` and `GET /api/tasks/<task-id>?run_id=<run-id>` expose the canonical record. `POST /api/tasks/<task-id>/stop` for it remains HTTP `409` with `milestone tasks are stopped through their run`; `POST /api/runs/<run-id>/stop` remains the control. The task gate is not the later `Close milestone` commit, and pushing remains operator-owned. | ownership pin `implementation/milestones/deep-reviewed-tasks/skeleton.md:70-76,116,138`; run-task reads `orchestrator/service.py:4506-4540,4659-4699`; Stop ownership `orchestrator/service.py:4277-4301,5110-5118`; gate/closure owners `orchestrator/driver.py:13317-13345,13457-13476`; push posture `orchestrator/README.md:646-653` | touch milestone composition and generic record projection only as required; do-not-route through standalone Stop, add a task route/error/status, turn reconciliation/repair/sync/closure into child tasks, collapse commits, or automate deployment |
| Recovery, terminality, and compatibility | Crash or process Stop while the task is open reuses its exact id, resolved policy, current evidence, and pending Git gate. A terminal task is immutable; a deliberate post-failure attempt has a distinct id and disjoint review evidence and charge ownership. Runs started before prospective activation finish under their original direct-skeleton law and receive no backfilled task, result, relation, or reinterpretation; their old-law events retain their original meaning. Logical identity is strict; unrecorded physical calls remain at-least-once. | strict/compatibility posture `implementation/milestones/deep-reviewed-tasks/skeleton.md:60-68,80-89,139`; terminal mutation `orchestrator/tasks.py:1182-1197`; pending-gate recovery `orchestrator/driver.py:671-712,13366-13384`; delivery limit `orchestrator/state.py:1-17` | touch prospective new-run activation and in-run task recovery; do-not-reopen a terminal record, infer success after a crash, admit a duplicate for an open attempt, migrate old state/history, or strengthen delivery semantics |
| Slice and size boundary | This slice adds no executor id, public route, result status, error code, prompt job, event vocabulary, dependency, or product integration. It uses the existing `canonical_plan_established` event. Skeleton documentation cannot expose or activate `implementation_size_control`; Slices 9–12 remain unimplemented here. | slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:41-46,116-120,128,132`; size applicability `orchestrator/tasks.py:774-805`; current catalogue `orchestrator/tasks.py:106-190`; no-dependency standard `orchestrator/README.md:33-46` | touch only skeleton composition, focused tests, and prospective compatibility marking; do-not-change direct executors, `deep_task`, size machinery, slice composition, verification cadence/presentation, granted roots, or third-party packages |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_milestone_skeleton_composition orchestrator.tests.test_reviewed_lifecycle orchestrator.tests.test_reviewed_result orchestrator.tests.test_reviewed_call_routing orchestrator.tests.test_canonical_plan orchestrator.tests.test_plan_reconciliation orchestrator.tests.test_task_activity orchestrator.tests.test_service_api`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| One public reviewed identity precedes all skeleton effects | new `MilestoneSkeletonCompositionTest.test_one_reviewed_skeleton_task_is_durable_before_any_call` | A new run records one open `reviewed_task` with semantic job `draft_skeleton`, the exact resolved policy and run authority, before dispatch. Every routed lifecycle call is evidence of that outer id, no child agent-call task exists, and generic run-task reads return the canonical record. | strict identity / best-effort physical-call uniqueness and display |
| Candidate plans remain non-authoritative until the gate | new `MilestoneSkeletonCompositionTest.test_draft_reviews_and_fix_do_not_anchor_or_open_slices` | A producer table and a review-driven replacement leave the first anchor absent, projection empty, later units absent, and reconciliation unopened through production, WIP, reviews, fixes, and seal preparation. | strict |
| Task gate establishes the exact final plan once | new `MilestoneSkeletonCompositionTest.test_task_gate_result_anchors_the_same_commit_and_final_table` | After the gate, the task has the exact reviewed native result; the anchor and event resolve that gate commit; projection equals the committed final table rather than the producer's earlier table; only then can the next unit appear; no charge or extra commit is created. | strict |
| Failure, Stop, and crash windows preserve lawful identity | new `MilestoneSkeletonCompositionTest.test_failure_stop_restart_and_anchor_crash_windows_preserve_task_law` | Pre-gate semantic failure yields terminal task/run failure and no plan; run Stop leaves an open id recoverable; recovery around admission, gate, result, and anchor creates no duplicate. A retry after terminal failure has a distinct id and excludes prior review evidence and charges. | strict logical recovery / best-effort interrupt and physical-call uniqueness |
| Milestone owners remain outside the reviewed task | new `MilestoneSkeletonCompositionTest.test_run_control_reconciliation_and_final_closure_remain_milestone_owned`; retained plan-reconciliation and service Stop tests | Task Stop returns the existing 409 while run Stop controls the process; later accepted plan change still uses reconciliation; final closure remains separate; no hidden task or new route/event/status appears. | strict control and commit ownership / best-effort interrupt delivery |
| Compatibility and downstream boundaries do not move | new `MilestoneSkeletonCompositionTest.test_pre_activation_run_finishes_without_task_backfill`; retained reviewed lifecycle/result/routing, canonical-plan, task-activity, and direct-task API tests | A pre-activation fixture keeps its original skeleton flow and history. New skeleton composition leaves direct tasks, standalone/deep tasks, size applicability, later slice scheduling law, and convenience presentation unchanged. | strict compatibility / best-effort presentation |

Repository-level commands remain:

`python3 -m unittest orchestrator.tests.suite_checkpoint`

`python3 -m unittest orchestrator.tests.suite_extended`

They remain separate checkpoint and architectural gates and must not be claimed
as run unless implementation executes them (`orchestrator/README.md:565-586`).

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Milestone operators and task consumers currently see a reviewed skeleton unit but no outer task record or native task result, while the first producer call installs the canonical plan before review. A crash or later correction can therefore leave durable scheduling authority naming unsealed bytes, and consumers cannot inspect one task identity for the skeleton's evidence and gate. Repository/state changes are Git-reversible; paid calls, a consumed premature plan, and published commit authority are not cheaply reversible. | assigned need `implementation/milestones/deep-reviewed-tasks/skeleton.md:116,137-138`; current early establishment `orchestrator/driver.py:2304-2359`; verified missing task identity `orchestrator/tests/test_reviewed_call_routing.py:394-401` |
| machinery | No new runtime module, API, dependency, process, or store is introduced. This slice joins the existing in-run task admission/result record to the existing skeleton lifecycle, carries one outer identity through routed evidence, and moves first plan establishment to the existing gate-backed result. The existing canonical parser/anchor then projects the plan; milestone advancement remains its current caller. One focused test module is the only new test machinery. | reusable lifecycle/result `orchestrator/driver.py:512-669`; in-run task record `orchestrator/tasks.py:1111-1197`; plan anchor `orchestrator/canonical_plan.py:809-846`; milestone advancement `orchestrator/driver.py:13317-13345` |
| consumers_touched | Verified runtime consumers touched are the milestone driver and canonical run state. Existing generic run-task list/detail functions and run summary consume the new canonical record without a product adapter; reconciliation, ledgers, and final closure remain downstream consumers of the resulting anchor/gate. Exact-id searches over source code in Life, Agent99, life_product_components, and Tutor found no `reviewed_task` or `deep_task` consumer, so all granted roots remain read-only. | lifecycle caller `orchestrator/driver.py:8371-8429`; run task consumers `orchestrator/service.py:4411-4431,4506-4540`; summary association `orchestrator/state.py:2647-2668`; milestone gate consumers `orchestrator/plan_reconciliation.py:192-200` |
| cheaper_alternative | Cheapest sufficient is to admit one record in the run's existing task history, execute the already-selected skeleton unit through `ReviewedWorkLifecycle`, consume its existing native result, and call the existing canonical-plan anchor only at that boundary. Relabelling the unit or adding a chip leaves no terminal task authority and retains the premature anchor. Running `DirectTaskHost` would duplicate state/lifecycle and detach milestone plan, reconciliation, and closure ownership. Doing nothing violates the slice assignment. | existing task/lifecycle seams `orchestrator/tasks.py:1154-1197`; `orchestrator/driver.py:512-669`; current discarded result `orchestrator/driver.py:8404-8417`; standalone state boundary not to duplicate `orchestrator/task_api.py:586-667` |
| cost | Build and review cost is one bounded in-run admission/result/anchor handoff plus failure, Stop, crash, accounting, and compatibility tests. Runtime adds one small task record and no provider call, Git operation, daemon, dependency, or migration; the same skeleton work and one existing gate run. Maintenance adds one composition boundary. Omission retains premature authority and blocks milestone use of the public task contract. Source changes are reversible; call spend and externally consumed authority are not. | standard-library environment `orchestrator/README.md:3-9,33-46`; record/result cost `orchestrator/tasks.py:1154-1197`; existing call volume/lifecycle `orchestrator/driver.py:512-669` |
| threat_model | This slice adds no caller-supplied field. The newly relevant untrusted inputs are the model-produced skeleton result and the workspace edits it claims; the existing result contract validates the slice list, and the canonical parser validates the committed plan block before it can become authority. Existing report-only/current-byte/Git gates constrain review evidence and edits. The run-emitted task id, resolved policy, task association, validated result envelope, and anchor link are trusted product machinery; tests observe their outcomes and do not inject malformed self-records. | model-result validation `orchestrator/contracts.py:841-849`; plan validation `orchestrator/canonical_plan.py:291-302`; current-byte result gate `orchestrator/driver.py:625-669`; edit boundary `orchestrator/README.md:551-554`; trusted-emission boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:99-104` |
| pinned_facts | The six hard rows pin only deviations that break public or cross-slice behavior: the outer task identity, first sealed-plan boundary, result/accounting ownership, milestone control, recovery/compatibility, and the later-slice/size exclusion. Exact public names, event, routes, error, and native-result fields are retained; helper names, polling, storage traversal, and control-flow ordering remain implementation choices. | slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:116`; hard contracts `implementation/milestones/deep-reviewed-tasks/skeleton.md:128-139`; existing names `orchestrator/tasks.py:19-36,145-189`; `orchestrator/service.py:4277-4301,4659-4699` |
| verification | Six executable rows add one skeleton-composition module and retain lifecycle/result, direct-call evidence, canonical-plan, reconciliation, task-read/activity, service-control, and compatibility proofs. They observe durable records, committed plan bytes and revisions, task/run results, charges, task counts, events, Stop responses, and injected crash windows. The focused command pins this slice; repository suites remain separate and unclaimed until run. | current parity proof `orchestrator/tests/test_reviewed_lifecycle.py:68-170`; result/recovery proof `orchestrator/tests/test_reviewed_result.py:115-196`; plan proof `orchestrator/tests/test_canonical_plan.py:341-388,478-535`; suite authority `orchestrator/README.md:565-586` |
| enforceability | Existing mechanisms can enforce closed task configuration, pre-effect admission, null-to-terminal result mutation, current-content reviewed success, canonical plan parsing and Git pinning, single-writer state, pending-gate recovery, generic run-task reads, milestone Stop, reconciliation, and final closure. Three missing seams are explicit implementation gates: the milestone currently admits no outer skeleton task and discards the lifecycle result; first-author completion currently anchors before review; and new versus resumable old runs have no explicit prospective composition-law discriminator. Until those seams exist and the named tests pass, this slice cannot claim task identity, sealed-only plan authority, or compatibility. Physical-call uniqueness, interrupt delivery, and display freshness lack strict mechanisms and remain best-effort. | existing enforcement `orchestrator/tasks.py:843-878,1154-1197`; `orchestrator/driver.py:625-712,8371-8429`; `orchestrator/canonical_plan.py:809-846`; `orchestrator/state.py:1-17`; gaps `orchestrator/driver.py:2304-2359,8404-8417`; current initialization `orchestrator/state.py:138-181` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| One skeleton attempt has one outer task before effects and one terminal result | Closed reviewed configuration at `orchestrator/tasks.py:613-640,843-878`; append-only admission and null-to-terminal mutation at `orchestrator/tasks.py:1154-1197`; the run's single-writer boundary at `orchestrator/state.py:1-17`. | **Current gap:** milestone execution has no outer skeleton admission, and `Driver.step` discards the lifecycle result at `orchestrator/driver.py:8404-8417`. Acceptance requires one durable association before dispatch, result consumption after the gate, and no internal agent-call task records. Product-emitted association fields are trusted; tests prove correct outcomes rather than malformed-self-record handling. |
| The first canonical plan can come only from the task's gated commit | Reviewed success is unavailable before the current seal and Git gate at `orchestrator/driver.py:625-669`; committed plan validation and full-revision pinning exist at `orchestrator/canonical_plan.py:291-302,809-846`; next-unit advancement already follows the gate at `orchestrator/driver.py:13332-13345`. | **Current gap:** initial author completion anchors and projects at `orchestrator/driver.py:2304-2359`. Acceptance must keep candidate plan changes non-authoritative through the review cycle and establish the first anchor only when the durable task result names that gate. |
| Task and run evidence are retained and counted once | Unit evidence/accounting exists at `orchestrator/state.py:2200-2266,2343-2500,2503-2522`; task-linked accounting exists at `orchestrator/tasks.py:1228-1320`; result recording creates no accounting event at `orchestrator/tasks.py:1182-1197`. | Associate every newly accepted physical evidence record with the outer attempt or its bounded lifecycle without admitting a child task. Tests must compare task totals, unit/run totals, and physical evidence; they must not assert physical exactly-once delivery. |
| Stop, reconciliation, advancement, and closure stay milestone-owned | Milestone task Stop refusal is at `orchestrator/service.py:4277-4301`; run Stop is at `orchestrator/service.py:2585-2613`; reconciliation dispatch remains a direct driver action at `orchestrator/driver.py:8399-8417`; gate advancement and final closure are at `orchestrator/driver.py:13317-13345,13457-13476`. | Wire the task boundary inside those owners. Do not invoke the standalone host, add an orchestration task, or make task/control projections decide run execution. |
| Recovery preserves open identity, terminal immutability, and old-run law | Pending-gate fingerprint recovery exists at `orchestrator/driver.py:671-712`; terminal mutation refuses a second result at `orchestrator/tasks.py:1182-1197`; state persistence exposes the at-least-once limit at `orchestrator/state.py:1-17`. | **Current gap:** `new_state` has no explicit prospective skeleton-composition law field at `orchestrator/state.py:138-181`. Acceptance needs new runs to opt into this law while old states remain untouched; an open attempt is reused, while any operator retry after terminal task failure uses a distinct identity and fresh review evidence rather than reopening it. |
| Scope and guarantee posture cannot silently widen | Job-scoped producer and size applicability are enforced at `orchestrator/tasks.py:613-640,774-805`; the catalogue and routes already expose all accepted ids at `orchestrator/tasks.py:106-190` and `orchestrator/service.py:4649-4699`; physical delivery limits are explicit at `orchestrator/state.py:1-17`. | Add no executor, route, status, event, dependency, size controller, deep-slice composition, verification cadence, product adapter, or strict delivery/display claim. Retained focused tests pin the unchanged surfaces. |
