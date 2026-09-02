# Slice 12 — Presentation, compatibility, and conformance

## Register 1 — INTENT (lay language)

### What this slice builds

This slice closes the milestone by making complete milestone verification visible
as work in its own right. Each verification appears beside the milestone's
slices, not inside one of them. An operator can see its progress and cost, follow
its findings and review trail, and open the task that owns its final result.

The same task page names reviewed and deep work honestly instead of describing
either as a single agent call. It continues to show the recorded task, not a
panel reconstruction of what probably happened.

This slice also supplies the compact end-to-end proof that the public task
surface and milestone composition agree. It crosses ordering, reviewed results,
deep children, commits, recovery, rethink, verification cadence, prompt use, and
accounting. Existing focused tests remain the detailed authority; the closing
matrix checks that their seams still compose under the current milestone law.

### Ownership and scope

This slice owns the read-only milestone presentation for verification and the
closing conformance matrix. If that matrix exposes a violation of an already
accepted contract, this slice may make the smallest correction at that existing
seam. It does not invent a new execution rule.

Runs keep the law under which they started. Earlier runs continue to show and
execute their in-slice verification history as before. Current runs show the
separate task-backed verification steps they actually admitted. Neither history
is rewritten to resemble the other.

### Guarantee posture

- **Strict:** canonical task identity and terminal result; reviewed-task gate
  ownership; deep parent/child and part identity; prospective compatibility;
  current-content verification gating; prompt-route and logical task cardinality;
  and single-count accounting. Whenever the panel presents one of these facts,
  its source and value must be the canonical record rather than an inference.
- **Best-effort:** card delivery, grouping, polling, chip presence, and display
  freshness. Their loss cannot change execution, acceptance, commits, or totals.
- **Optimistic:** none. No outcome is accepted in anticipation of later proof.
- **Eventual:** none. No queue, redelivery, reconciliation worker, or deadline for
  a stale display is added.

### Dependencies

This slice depends on the completed public reviewed and deep task contracts,
their generic order and inspect surface, reviewed result and Git gate ownership,
deep composition, milestone skeleton and slice composition, rethink
reconciliation, and the sibling five-slice/final verification cadence.

Presentation reuses the current run summary, unit history, task-detail page,
safe text rendering, and run-scoped task read. Conformance extends the existing
cross-surface matrix and focused lifecycle fixtures. No runtime module, public
API, store, process, package, or third-party dependency is introduced.

### Non-goals

- No new task type, route, status, event, error code, result member, task index,
  history record, or compatibility format.
- No new scheduler, queue, retry service, cache, migration, backfill, repair
  ledger, accounting home, or presentation store.
- No change to review breadth, debt, caps, prompts, staffing, size-control
  ownership, suite semantics, seal law, Git operations, reconciliation, Stop,
  liveness, deployment, or product-root behavior.
- No full task records or native results copied into the frequently polled run
  summary, and no task subtotal added to a slice or run total.
- No browser framework or duplicate end-to-end runtime. Existing panel, service,
  state, task, driver, and test seams are reused.
- No defense against malformed fields in trusted orchestrator-emitted relations,
  activation markers, or suite configuration.

### Acceptance criteria

A normal current run presents every milestone-scheduled verification as a peer
milestone item, separate from every slice. Distinct failed and later attempts
remain distinct. The item exposes the owning task's actual state, duration, cost
and partiality, its finding/review/seal history, and a path to the canonical
terminal result. Verification work contributes to milestone totals once and to
no slice subtotal.

Task detail identifies the executor recorded on the order. Opening a milestone
verification uses the same access-controlled task detail as other milestone
tasks; presentation does not copy or reinterpret its result.

A pre-activation fixture retains direct skeleton/slice work and its historical
four-slice/final in-slice verification. A current fixture uses reviewed skeleton,
documentation-first deep slices, separate five-slice/final verification, and no
in-slice complete checkpoint. Neither fixture gains rewritten or backfilled task
history.

The conformance matrix proves public direct ordering, milestone composition,
child-owned commits and results, parent aggregation, crash recovery, both rethink
outcomes, direct Prompt Router calls, no internal call-tasks, applicable size
isolation, cadence/current-content reuse, and one accounting contribution per
physical charge. Physical call uniqueness and display delivery are not asserted.

Focused presentation/conformance checks pass in the implementation child. The
final sibling verification and release checks pass before full conformance is
claimed; no retained test is removed, weakened, or reclassified merely to make
the result green.

### Risks

The main presentation risks are nesting verification under the preceding slice,
showing unit state as task state across a crash window, losing failed attempts,
mislabeling a reviewed task as an agent call, copying a large native result into
the polling summary, or adding verification cost to a slice subtotal.

The main conformance risks are preserving stale direct-unit fixtures after the
new hierarchy activated, duplicating lower-level fixtures into a second runtime,
testing synthetic seals instead of the real gate path, overlooking recovery at
task-result or gate boundaries, or fixing a failing test by weakening an accepted
contract. Compatibility tests must not turn trusted historical state into hostile
input or create a migration requirement.

## Register 2 — PINNED-FACTS TABLE (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Public task surface | Public TaskExecutor ids remain exactly `agent_call`, `brainstorming`, `reviewed_task`, and `deep_task`. They use `GET /api/task-executors`, `GET/POST /api/tasks`, `GET /api/tasks/<id>`, and `POST /api/tasks/<id>/stop`; a milestone-owned detail read is `GET /api/tasks/<id>?run_id=<run-id>`. Terminal statuses remain exactly `success` and `failure`; task request errors remain `unknown_task_executor`, `invalid_task_request`, and `task_unavailable`. No `verification_task`, presentation route, status, or error is added. A rendered task identifies its exact `order.task_executor`; `reviewed_task` and `deep_task` must not be labelled `agent_call`. | milestone surface `implementation/milestones/deep-reviewed-tasks/skeleton.md:147-159`; catalogue/errors `orchestrator/tasks.py:19-21,110-357,459-472`; result statuses `orchestrator/tasks.py:1508-1582`; generic reads/routes `orchestrator/service.py:4529-4540,4650-4701,4901-4916`; current label gap `orchestrator/static/panel.html:5295-5327` | touch the shared panel presenter and conformance tests; do-not-add or special-case a public API, executor, result, or refusal vocabulary |
| Milestone-verification presentation | Each milestone-scheduled top-level `reviewed_task` with `configuration.task_kind: "complete_verification"` has one peer milestone item, never a slice child or slice subtotal. Normal presentation exposes canonical task state, duration, cost and partial flags; the associated verification, findings, reviews, seal, and gate evidence; and the canonical result through the run-scoped task detail. Separate attempts remain separate. Evidence continues to use `verification`, `seal_satisfied`, and `gate_commit`; no presentation event is added. Source fidelity is strict, while delivery/grouping/freshness are best-effort. | assigned outcome `implementation/milestones/deep-reviewed-tasks/skeleton.md:139,157,159`; mandate `implementation/milestones/deep-reviewed-tasks/goal.md:161-174,253-257`; sibling admission `orchestrator/driver.py:4614-4666`; existing compact unit evidence `orchestrator/state.py:2744-2765,2892-3119`; existing history/detail seams `orchestrator/static/panel.html:2939-3159,3884-3975,5295-5382,5433-5486` | touch read-only panel composition and focused projection/panel checks; do-not-nest under a slice, infer a task, poll/copy full native results into run summary, reaggregate cost, or make presentation an execution gate |
| Prospective compatibility | Each boundary activates only when its own marker is present at version `1`: `skeleton_composition_version`, `deep_slice_composition_version`, and `verification_cadence_version`. Absence of a marker preserves that boundary's prior law, so a resumable run initialized between activations may lawfully retain an earlier mixture; a current run carries all three. The old cadence remains `four_slice_checkpoint` and `milestone_final` inside the slice. Stored state, events, commits, and tasks are neither rewritten nor backfilled; an old checkpoint or per-call task is never interpreted as a new parent, child, or sibling verification. | compatibility mandate `implementation/milestones/deep-reviewed-tasks/goal.md:188-208`; version bindings `orchestrator/state.py:136-142`; prospective init `orchestrator/driver.py:15057-15069`; independent composition/cadence branches `orchestrator/driver.py:1917-1983,4397-4411`; existing compatibility proofs `orchestrator/tests/test_milestone_skeleton_composition.py:804-817`, `orchestrator/tests/test_milestone_deep_slice_composition.py:202-227`, `orchestrator/tests/test_milestone_verification_cadence.py:275-288` | touch compatibility and presentation tests plus only a proven branch defect; do-not-migrate, normalize stored bytes, backfill relations, rename old events, or apply a later boundary to an earlier run |
| Composition, result, and commit ownership | A current milestone has one top-level reviewed skeleton task; each logical slice has one `deep_task` whose reviewed documentation child precedes all reviewed implementation-part children; each reviewed child owns its native result, seal, and distinct gate commit. The deep parent aggregates child accounting, returns `native_result: null`, and owns no aggregate commit. Each due complete verification is a top-level reviewed task with no `parent` and its own result/seal/gate. Success is never inferred before the relevant gate. | composition contract `implementation/milestones/deep-reviewed-tasks/skeleton.md:131-139,148,154-157`; reviewed result gate `orchestrator/driver.py:664-731`; deep aggregate `orchestrator/tasks.py:1227-1259`; existing end-to-end child proof `orchestrator/tests/test_milestone_deep_slice_composition.py:97-200`; skeleton anchor proof `orchestrator/tests/test_milestone_skeleton_composition.py:169-211`; verification admission `orchestrator/tests/test_milestone_verification_cadence.py:191-211` | touch the compact cross-surface matrix and only defects it demonstrates; do-not-collapse child gates/results, add a parent commit/charge, parent verification, or accept pre-gate success |
| Recovery and rethink | Durable task order/identity is immutable and result changes only once from `null` to terminal. Recovery reuses an already-admitted open skeleton, deep parent/child, or verification attempt and may repeat only an unrecorded physical call. Under A3, a surviving origin resumes the same phase in the same reviewed child/deep parent; rollback supersession fails affected open records once and a later active slice begins a new documentation-first deep task. No terminal record reopens or requeues. | operator amendment A3; append-only task enforcement `orchestrator/state.py:388-437`; related-child identity `orchestrator/tasks.py:1145-1194`; skeleton crash proof `orchestrator/tests/test_milestone_skeleton_composition.py:551-675`; deep rethink/recovery proof `orchestrator/tests/test_milestone_deep_slice_composition.py:338-505,515-626,628-838`; verification recovery seam `orchestrator/driver.py:4521-4612` | touch recovery conformance and a smallest proven existing-seam correction; do-not-add a retry hierarchy, successor link, physical exactly-once claim, sibling rebuild, or malformed-self-record defense |
| Prompt, size, and accounting cardinality | Every production, review, fix, delta-review, classification, and complete-verification call resolves its one semantic charge directly through Prompt Router and remains evidence inside its owning reviewed task; no internal `agent_call` task is created. Implementation-size control remains exclusive to an implementation `reviewed_task` produced by `agent_call`; direct executors, Brainstorming-produced reviewed work, complete verification, and `deep_task` own none. Explicitly linked physical charges enter their reviewed child once; a deep parent only sums child envelopes, and the run does not add task subtotals again. | prompt boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:151-155`; A1; router grid `orchestrator/prompt_router.py:28-49,77-127`; routed cardinality proof `orchestrator/tests/test_reviewed_call_routing.py:269-401`; size applicability `orchestrator/tasks.py:714-816`; accounting enforcer `orchestrator/tasks.py:1358-1450`; deep accounting proof `orchestrator/tests/test_deep_task_implementation.py:388-437` | touch conformance assertions and only a demonstrated attribution/routing defect; do-not-add a prompt path, call-task layer, size controller, task subtotal, or accounting ledger |
| Verification | Focused command: `python3 -m unittest orchestrator.tests.test_task_conformance orchestrator.tests.test_task_panel orchestrator.tests.test_task_activity`. Add or update checks named `test_milestone_verification_renders_as_task_backed_peer`, `test_public_reviewed_and_deep_ordering_conforms`, `test_milestone_hierarchy_commits_and_totals_conform`, `test_recovery_rethink_prompt_and_size_boundaries_conform`, and `test_pre_activation_and_current_cadence_conform`. They must exercise real retained fixtures and fail on collapse, stale compatibility, duplicate tasks/charges, wrong routing, wrong ownership, or mispresentation. Full evidence is the successful final sibling verification plus `python3 -m unittest orchestrator.tests.suite_checkpoint`, `python3 -m unittest orchestrator.tests.suite_extended`, and `python3 -m unittest orchestrator.tests.test_suite_inventory`; keep those outside the slice implementation child except for the focused command. | assigned conformance `implementation/milestones/deep-reviewed-tasks/skeleton.md:139`; existing reusable matrix `orchestrator/tests/test_task_conformance.py:1-67`; current stale current-law fixture `orchestrator/tests/test_task_conformance.py:69-116`; suite authority and separation `orchestrator/README.md:565-586`; suite partition `orchestrator/tests/suite_manifest.py:14-65,108-128` | touch the existing conformance/panel/activity tests and smallest contract fixes; do-not-add a test-only runtime, weaken/remove/reclassify retained checks for green, or claim an unrun focused, checkpoint, extended, inventory, or final-verification gate |

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Operators currently receive a milestone verification as an unclassified trailing unit rather than a task-backed peer, cannot open its task from the pipeline, and see every non-Brainstorming task described as an agent call. Independently, the existing closing matrix creates current activated slice units without their required deep parent, so it no longer proves the current composition. The realistic harms are misleading verification ownership and undetected duplicate/missing task, gate, or accounting behavior. Presentation and test changes are reversible; spent calls and consumed durable history or commits are not. | required presentation `implementation/milestones/deep-reviewed-tasks/goal.md:171-174`; current fallback rendering and label `orchestrator/static/panel.html:3896-3909,3974-3975,5323-5327,5485-5486`; stale matrix setup `orchestrator/tests/test_task_conformance.py:69-116`; current deep prerequisite `orchestrator/driver.py:4855-4889` |
| machinery | Extend the existing panel's pipeline/task presenter and the existing `test_task_panel`, `test_task_activity`, and `test_task_conformance` surfaces. Reuse `summary.units[*].task_ids`, unit review/verification history, escaped story rendering, `openTaskDetail`, and the run-scoped generic task read. Add no runtime module, API, store, renderer, or dependency. Runtime changes outside presentation are allowed only when a named conformance failure proves an accepted seam is wrong. | compact projection `orchestrator/state.py:2744-2765,2892-3119`; reusable panel/detail `orchestrator/static/panel.html:2939-3159,3884-3975,5295-5382,5433-5486`; task read `orchestrator/service.py:4529-4540`; reusable matrix `orchestrator/tests/test_task_conformance.py:1-67` |
| consumers_touched | The created consumer is the operator-facing milestone verification item. Existing consumers touched are the shared task-detail presenter and three focused test modules. The run summary and access-controlled run/task reads are reused data sources; task execution consumes no presentation value. Exact-id searches across Life, Agent99, life_product_components, and Tutor found no code consumer or alternate reviewed/deep engine, so no product adapter or granted-root edit is created. | panel consumer `orchestrator/static/panel.html:3845-3975,5245-5486`; run/task readers `orchestrator/service.py:3374-3391,4515-4540`; execution-independent projection `orchestrator/state.py:2726-2733`; whole-universe boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:110-123` |
| cheaper_alternative | Cheapest sufficient is to compose the existing compact unit evidence with the existing canonical task detail, correct the shared executor label, and extend the existing conformance matrix with current-law fixtures. Doing nothing leaves the mandated peer presentation absent and the closing matrix stale; documentation alone cannot detect cross-seam task/commit/accounting regressions. A new endpoint, copied result projection, browser framework, or second end-to-end harness duplicates solved machinery. | current unit evidence `orchestrator/state.py:2892-3119`; existing detail and unused run-task opener `orchestrator/static/panel.html:5295-5382,5485-5486`; existing conformance composition helper `orchestrator/tests/test_task_conformance.py:38-67`; assigned outcome `implementation/milestones/deep-reviewed-tasks/skeleton.md:139` |
| cost | Build and review cost is a bounded panel change, five compact conformance cells, fixture alignment, and only seam corrections proven necessary. There is no migration, deployment, daemon, package, persistent data, or product-integration cost. Full checkpoint and extended verification are intentionally expensive release evidence; omission is cheaper now but leaves a cross-surface architectural cut unverified, while source/test changes remain Git-reversible. | standard-library environment `orchestrator/README.md:33-46`; measured suite posture `orchestrator/tests/README.md:21-43`; no-new-machinery boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:110-123`; completion need `implementation/milestones/deep-reviewed-tasks/goal.md:230-257` |
| threat_model | This slice opens no new input boundary. Existing untrusted values displayed are an authenticated caller's task text and model-produced findings, reasons, and native result; existing run access checks and HTML escaping must remain in force. Trusted values are operator/project suite meaning, third-party tool semantics, activation markers, product-emitted task relations/ids, and deterministic state/Git results. No new validator or adversarial test polices those trusted emitters; conformance checks their outcomes and recovery, not imaginary malformed self-input. | run/task access `orchestrator/service.py:4529-4540,4861-4867`; escaped findings/result `orchestrator/static/panel.html:4044-4056,5376-5382`; trusted boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:118-123`; suite ownership `implementation/milestones/deep-reviewed-tasks/slices/slice-10.md:21-31` |
| pinned_facts | The seven hard rows above are the complete bug-level set for this slice: unchanged public surface, peer verification presentation, prospective compatibility, composition/result/commit ownership, recovery/rethink identity, prompt/size/accounting cardinality, and executable verification. Helper names, layout CSS, traversal/control flow, fixture construction, and polling strategy are not pinned. | Slice 12 allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:139`; milestone hard boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:147-159` |
| verification | Five named focused checks cover presentation, public ordering, composed hierarchy and commits, recovery/rethink/prompt/size boundaries, and old/current law. The existing matrix's helper runs lower-level authoritative cases without copying their fixtures. The checkpoint and extended manifests partition all retained tests, and inventory mechanically verifies that partition; final sibling verification owns full current-content closure. | reusable composition helper `orchestrator/tests/test_task_conformance.py:38-67`; existing panel authority `orchestrator/tests/test_task_panel.py:18-219`; existing cadence cases `orchestrator/tests/test_milestone_verification_cadence.py:191-288`; partition mechanism `orchestrator/tests/suite_manifest.py:108-128`; inventory proof `orchestrator/tests/test_suite_inventory.py:9-50` |
| enforceability | Canonical catalogue/order/result validators and append-only task history enforce public identity and terminal fidelity; reviewed success requires seal plus matching gate; related admission enforces one child per parent/phase/part; version markers and absence branches enforce prospective compatibility; Prompt Router's closed route grid plus explicit task links enforce routing/attribution; child-envelope arithmetic and existing run totals enforce single counting. Existing run access, escaped renderers, compact unit evidence, and run-scoped task detail can enforce source-faithful normal presentation, but no mechanism can guarantee its delivery or freshness, so those stay best-effort. The concrete gaps are the absent peer presenter/canonical task link, the wrong shared task label, and the stale current-law conformance fixture; they must close before this slice claims success. | validators/results `orchestrator/tasks.py:410-456,1017-1048,1508-1582`; history `orchestrator/state.py:388-437`; reviewed gate `orchestrator/driver.py:664-731`; related admission `orchestrator/tasks.py:1145-1194`; compatibility branches `orchestrator/driver.py:1917-1983,4397-4411`; routing `orchestrator/prompt_router.py:28-49,77-127`; accounting `orchestrator/tasks.py:1227-1259,1358-1450`; presentation gaps `orchestrator/static/panel.html:3896-3909,3974-3975,5323-5327,5485-5486`; conformance gap `orchestrator/tests/test_task_conformance.py:69-116` |
