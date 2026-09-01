# Slice 05 — Standalone reviewed-task ordering

## Register 1 — INTENT (lay language)

### What this slice builds

This slice lets an operator or calling product order one reviewed task without
starting a milestone. The order says whether the requested production is a
planning document, a slice document, or implementation work, and may choose the
same producer, review breadth, debt posture, and limits already used by reviewed
milestone work. Leaving those choices alone keeps the normal agent-call producer
and two-family review while inheriting the bound project's effective debt,
convergence, and applicable size defaults.

The public task is one durable piece of work from production through review,
correction, current-content seal, and its own Git gate commit. Its production,
review, correction, classification, and rethink calls remain evidence inside
that task; they do not appear as child agent-call tasks. A successful task returns
the compact reviewed result established in Slice 4. An eligible implementation
cut is returned inside that result; a standalone reviewed task does not invent or
order the remaining parts.

The existing task catalogue, generic task API, project/work-area access checks,
standalone task history, Stop action, and catalogue-generated order form publish
this behavior. Existing direct agent-call and Brainstorming orders keep their
current behavior. There is no private milestone or Agent99 entry point.

### Ownership and consumers

The reviewed-task executor owns exactly one admitted production through its
reviewed result. The shared task service owns admission, visibility, work-area
exclusion, Stop, and the outer task record. Prompt Router and Staffing Router
retain prompt and staffing authority; the existing reviewed lifecycle retains
review, rethink, state, Git, and recovery authority. A standalone request is its
own work authority—it does not create a synthetic milestone or acquire milestone
sequencing, plan reconciliation, closure, liveness, or deployment behavior.

The immediate consumers are the generic service and panel. Milestone composition
and Agent99 consumption remain later callers of the same public contract.

### Guarantee posture

- **Strict:** accepted configuration, including mandatory Git gating, is
  validated and durably resolved before the first physical call. Omitted reviewed
  policy values inherit the effective work-area defaults at admission, including
  bound-project overrides; one public task id exclusively owns one reviewed
  lifecycle and one null-to-terminal result; success requires current review
  evidence, a seal, and that task's gate commit; restart reuses the same open task
  and durable lifecycle facts, while a later id over the same work area starts
  with no prior reviewed evidence; overlapping work remains excluded.
- **Strict:** an operator Stop cannot become success. It closes the running
  standalone reviewed task as a failure under the existing generic Stop contract;
  a service or worker crash is not a Stop and is recovered from the same task.
- **Strict where applicable:** implementation-size control is available only to
  an implementation reviewed task whose producer is `agent_call`. Its observed
  cut and overflow meanings remain those already established.
- **Best-effort:** physical-call uniqueness, provider delivery, live size
  observation, Stop delivery to a process already exiting, and panel freshness
  retain their current process and polling limits.
- **Optimistic / eventual:** none. This slice adds no queue, replication,
  redelivery, exactly-once, or eventual-display promise.

### Dependencies

This slice depends on Slices 1–4: the reusable lifecycle, frozen reviewed policy,
direct routed-call evidence and rethink continuity, and the gate-backed native
result. It reuses the generic task catalogue and result envelope, standalone task
store and host, project/work-area resolution and exclusion, Staffing Router,
Prompt Router, append-only review state, and Git WIP/amend/gate recovery.

It adds no third-party dependency, scheduler, queue, service process, permission
model, prompt path, staffing authority, lifecycle engine, accounting store,
migration lane, or product-root adapter.

### Non-goals

- No `deep_task`, child admission, parent/phase/part authority, aggregation, or
  automatic continuation from an `implementation_cut`.
- No complete-verification semantic job or sibling verification task; Slice 10
  owns that reviewed production.
- No milestone skeleton/slice composition, canonical-plan establishment, design
  repair, reconciliation, cadence, higher-level closure, stop/liveness,
  synchronization, or deployment change.
- No new producer, review family, prompt route, result status, error vocabulary,
  commit layer, retry endpoint, rollback path, or rich reviewed-task projection.
- No size control on a direct `agent_call`, a direct Brainstorming order, or a
  Brainstorming-produced reviewed implementation; no Brainstorming size machinery.
- No rewriting or backfill of existing standalone or milestone task history, no
  defensive validator around trusted orchestrator-emitted lifecycle records, and
  no edit in a granted read-only root.

### Acceptance criteria

The slice is accepted when `reviewed_task` is self-described in the shared
catalogue and one valid order can be placed, inspected, stopped, and recovered
only through the generic task surface and generated panel. Both offered producers
must complete the same reviewed-result boundary for their eligible jobs. The
ordinary reviewed-task configuration enables Git gating; an explicit resolved
disablement and invalid job, producer, policy, size, access, reference, output,
Git-root, or busy-work-area orders must refuse before admission or provider
effects under the existing error vocabulary. An untouched API or panel order
must preserve the bound project's effective reviewed-work defaults in its stored
resolved configuration.

Focused tests must prove current-byte seal and gate-before-success, one outer task
with no internal agent-call task records, exact accounting and native result,
same-id restart through production/WIP/review/rethink/gate crash windows, terminal
Stop behavior, isolation between successive outer ids on one work area,
implementation-cut non-composition, Brainstorming size isolation, and unchanged
direct-task and old-record behavior. The catalogue-generated panel must submit one
ordinary order without replacing project-specific defaults and surface service
refusals verbatim.

### Risks

The main risks are acknowledging an order before its reviewed authority is
durable, letting the outer record and lifecycle state disagree, treating a
restarted reviewed task like a lost one-call task, exposing success before gate
recovery, admitting work that cannot make a gate, reusing an earlier task's
reviewed evidence, or counting internal calls twice. Other risks are hard-coding
policy in the panel, accepting an ineligible producer or size policy, leaking size
control into Brainstorming, accidentally creating a successor from a cut,
overriding project defaults on an untouched order, changing old task recovery, or
letting Stop race into a false success. Exact
admission, lifecycle-parity, successive-order, restart, Stop, cut, and
compatibility tests expose these faults.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Public executor and routes | After this slice the ordered public catalogue ids are exactly `agent_call`, `brainstorming`, `reviewed_task`. `reviewed_task` uses the existing `GET /api/task-executors`, `GET/POST /api/tasks`, `GET /api/tasks/<id>`, and `POST /api/tasks/<id>/stop` surfaces and the catalogue-generated order form. | slice assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:112`; public-route mandate `implementation/milestones/deep-reviewed-tasks/skeleton.md:127`; current routes `orchestrator/service.py:4581-4631,4838-4848` | touch the shared catalogue, generic admission/host, and generated panel; do-not-add a reviewed-task route, private caller path, or `deep_task` early |
| Reviewed-task configuration | `configuration.task_kind` is required and is exactly `draft_skeleton`, `draft_slice_note`, or `implement`. The remaining optional keys are the existing reviewed policy: `producer` (`task_executor` plus optional `configuration`), `review_breadth`, `same_family_second_look`, the applicable `doc_reclassify_from` or `impl_reclassify_from`, `p3_reclassify_debt`, `p3_defer_max_risk`, `max_rounds_per_family`, `max_fix_loops`, `delta_full_review_after_fixes`, and applicable `implementation_size_control`. Admission stores resolved values. Omitted producer, breadth, and second-look choices resolve to `agent_call`, `double`, and `false`. Every omitted debt, cap, and applicable size value inherits the effective work-area configuration at admission: bound-project defaults when present, otherwise the ordinary `P2`/`P1`, `true`, `low`, `12`, `20`, `5`, and `500`/`750` lines with `180`/`600` second graces. An unknown producer executor returns `unknown_task_executor`; malformed fields and job-ineligible combinations return `invalid_task_request`, always before effects. | semantic jobs `orchestrator/contracts.py:53-55`; project-effective configuration `orchestrator/service.py:4098-4108`; reviewed defaults seam `orchestrator/driver.py:2533-2569`; errors and policy `orchestrator/tasks.py:18-20,27-50,352-550`; slice configuration authority `implementation/milestones/deep-reviewed-tasks/skeleton.md:28-46,112` | touch the catalogue schema/resolver and its generated controls; do-not-source policy from free-form context, let the panel or catalogue fallback override effective project defaults, accept the wrong phase field, or mutate project/run defaults |
| Producer and size boundary | `draft_skeleton` permits only `agent_call`; `draft_slice_note` and `implement` permit `agent_call` or `brainstorming`. `reviewed_task` is never its own producer. Only `implement` plus `agent_call` may expose and activate `implementation_size_control`. Brainstorming production has no size monitoring, intervention, grace, interruption, stabilizer, cut, or overflow guarantee. A returned `implementation_cut` stays at `native_result.production_result.implementation_cut` and creates no successor task in this slice. | offered producer validation `orchestrator/tasks.py:352-400,517-549`; amendment pin `implementation/milestones/deep-reviewed-tasks/skeleton.md:41-46,131`; cut preservation `orchestrator/driver.py:618-634` | touch reviewed-task policy activation and tests; do-not-change either direct executor, permit recursive/composite production, move the controller into `agent_call`, add Brainstorming size machinery, or compose a cut |
| Admission and work authority | The admitted common request remains `work_area`, `request`, `context`, `reference_documents`, and optional `output_directory`; it is the durable objective/material supplied to every reviewed phase through Prompt Router, never a caller-built prompt. Project access, readable-root containment, canonical output containment, and `staffing_session` are resolved before the record is acknowledged. Git gating is a required execution condition: the ordinary reviewed-task configuration enables it, while an explicit resolved disablement returns `invalid_task_request` before effects. A reviewed task additionally requires the primary to be the root of its own Git repository, otherwise `primary_not_repo_root`; overlapping live work refuses `work_area_busy`. | request/order contract `orchestrator/tasks.py:232-267,649-725`; sole-prompt boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:48-55,132`; standalone and milestone configuration posture `orchestrator/service.py:4098-4108,1919-1935`; Git toggle and root predicate `orchestrator/driver.py:155,590-599`; `orchestrator/gitops.py:120-152`; exclusion `orchestrator/service.py:4284-4305` | touch only the reviewed-task configuration/preflight, material handoff, and existing shared admission; do-not-treat request text as an assembled prompt, weaken access/path checks, auto-init or adopt a parent repo, add a permission model, or admit reviewed work with Git disabled |
| Identity, calls, and terminal result | One acknowledged outer task id exclusively and durably locates one reviewed lifecycle. Every later id admitted over the same work area starts a fresh production and review history: no terminal, stopped, or forgotten earlier id can supply its seal, gate commit, or accounting. Production, review, fix, delta-review, classification, and rethink calls are evidence, never child `agent_call` tasks. `need_rethink` keeps that task open. Success is the existing generic envelope whose native result is exactly `production_result`, `review_evidence` (`seal_attempt`, `reviews`, `verification_event_seq`), and `gate_commit`; accounting derives once from that task's lifecycle evidence. The task record mutates only from `result: null` to terminal `success` or `failure`. | task ownership `implementation/milestones/deep-reviewed-tasks/goal.md:36-40,75-79`; call identity `implementation/milestones/deep-reviewed-tasks/skeleton.md:48-55,132`; result projection `orchestrator/driver.py:590-634`; terminal envelope/mutation `orchestrator/tasks.py:822-837,1018-1092` | touch the standalone adapter, lifecycle association, and result handoff; do-not-add child tasks, a second result/evidence store, expose `need_rethink`, reuse another outer id's evidence, flatten the native result, double-count calls, or reopen a terminal id |
| Stop and recovery | `POST /api/tasks/<id>/stop` keeps the generic direct-task outcome: an accepted Stop reports `stopping`, can never become success, and closes the reviewed task as `failure` with the operator reason; a later Stop reports `terminal`. Process/service loss is not an operator Stop: startup resumes the same open reviewed task, resolved configuration, review history, pending WIP/gate, and result identity. Logical state and Git effects recover strictly; a physical call whose result was not durably recorded may repeat. | slice assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:112`; current Stop contract `orchestrator/task_api.py:445-474`; route mapping `orchestrator/service.py:4221-4245`; lifecycle gate recovery `orchestrator/driver.py:636-654`; at-least-once limit `orchestrator/state.py:1-17` | touch reviewed-task host control and open-task adoption; do-not-close a crash as a lost one-call task, fabricate success on Stop, admit a replacement id, add a retry route/ledger, or promise physical exactly-once delivery |
| Panel and compatibility boundary | The panel obtains the executor description and all configuration controls from the catalogue, sends one `POST /api/tasks`, disables the order while it is in flight, and displays the canonical stored order/result. Existing direct `agent_call` and `brainstorming` admission, execution, Stop, restart, result, and stored history retain their current law. Existing records are neither rewritten nor backfilled. | generated form `orchestrator/static/panel.html:5674-5769,5786-5832`; canonical detail `orchestrator/static/panel.html:5290-5377`; compatibility mandate `implementation/milestones/deep-reviewed-tasks/skeleton.md:90-103,138` | touch generic rendering only as needed to express the catalogue schema and label `reviewed_task`; do-not-hard-code reviewed policy, infer service decisions locally, add special history, or reinterpret old records |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_reviewed_task_api orchestrator.tests.test_reviewed_result orchestrator.tests.test_reviewed_lifecycle orchestrator.tests.test_reviewed_policy orchestrator.tests.test_reviewed_call_routing orchestrator.tests.test_task_api orchestrator.tests.test_tasks orchestrator.tests.test_task_panel orchestrator.tests.test_driver_implementation_size orchestrator.tests.test_brainstorming_slice_production orchestrator.tests.test_staffing_standalone_cutover`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Catalogue, API, and panel publish one exact contract | new `ReviewedTaskOrderingTest.test_catalogue_api_and_panel_publish_the_same_reviewed_configuration`; new `ReviewedTaskOrderingTest.test_untouched_api_and_panel_orders_inherit_bound_project_reviewed_defaults`; retained `TaskPanelTests.test_one_catalogue_drives_description_and_configuration` | The catalogue has exactly the three Slice 5 ids; API and panel expose the exact job/policy choices above; untouched orders through either surface store the bound project's debt, cap, and applicable size defaults, while the panel sends one generic order with no local executor constants or retry. | strict contract / best-effort display freshness |
| Invalid or unavailable orders have no effects | new `ReviewedTaskOrderingTest.test_invalid_policy_access_paths_git_and_busy_tree_refuse_before_admission` | An unknown producer uses `unknown_task_executor`; malformed/ineligible fields and an explicitly Git-disabled resolved configuration use `invalid_task_request`; a non-own-root repo uses `primary_not_repo_root`; an overlap uses `work_area_busy`; no task record, provider call, or workspace edit is created. | strict |
| Every eligible job and producer reaches standalone reviewed success | new `ReviewedTaskOrderingTest.test_every_eligible_job_producer_pair_reaches_reviewed_result` | Under the ordinary Git-enabled reviewed-task configuration, a standalone generic order for each eligible pair—`draft_skeleton` with `agent_call`, and each of `draft_slice_note` and `implement` with either `agent_call` or `brainstorming`—reaches one current-byte reviewed result with its seal and gate commit under one `reviewed_task` outer id; no producer task record is created. | strict |
| Direct reviewed work reaches the same result boundary | new `ReviewedTaskOrderingTest.test_agent_call_reviewed_task_matches_milestone_lifecycle_and_native_result`; retained `ReviewedResultContractTest.test_success_requires_current_seal_and_gate`; retained `ReviewedCallRoutingTest.test_internal_agent_calls_create_evidence_without_child_tasks` | One outer task supplies the admitted objective, context, references, resolved project safeguards, and staffing session to the established routed phases; it preserves the exact call/evidence sequence, current-byte review, WIP/amend/seal/gate outcome, single-count totals, and Slice 4 native result, with no internal task records. | strict result/evidence; best-effort physical uniqueness |
| Successive reviewed orders remain isolated | new `ReviewedTaskOrderingTest.test_successive_orders_on_one_work_area_have_disjoint_evidence_and_accounting` | After a reviewed task succeeds or is stopped, a later order on the released work area performs its own production and review calls and can succeed only from its own seal and new gate commit. Its totals exclude every earlier task's calls, including when the earlier outer record was deleted through existing generic behavior. | strict |
| Producer and size ownership remain exact | new `ReviewedTaskOrderingTest.test_brainstorming_reviewed_implementation_has_no_size_control`; new `ReviewedTaskOrderingTest.test_agent_call_implementation_cut_returns_without_successor`; retained producer/size isolation modules | Brainstorming-produced implementation rejects size configuration and emits no size events; eligible agent-call implementation retains its observed cut/overflow evidence and returns the cut without admitting another task. | strict applicability and persisted outcomes / best-effort observation |
| Restart recovers one logical task and only current bytes | new `ReviewedTaskOrderingTest.test_restart_reuses_same_task_through_production_rethink_wip_review_and_gate_windows`; new `ReviewedTaskOrderingTest.test_shared_pending_gate_recovery_rejects_downtime_edits_for_both_callers`; retained `ReviewedResultContractTest.test_gate_crash_recovers_before_result_and_successor` | Each crash window leaves one open id and one durable policy/lifecycle; restart resumes or derives its result, adopts landed Git effects, admits no replacement, and exposes no success before the recovered gate. The shared lifecycle invalidates prior review evidence when repository bytes change during downtime, for both standalone and milestone callers. | strict logical recovery and current-content success / best-effort physical uniqueness |
| Stop and compatibility remain honest | new `ReviewedTaskOrderingTest.test_stop_fails_without_success_and_releases_the_work_area`; new `ReviewedTaskOrderingTest.test_existing_direct_tasks_and_old_records_keep_their_recovery_law`; retained direct-task Stop/restart tests | Stop yields the existing states and one terminal failure even if a call exits cleanly; a crash remains recoverable; direct agent-call and Brainstorming behavior and pre-Slice-5 records are unchanged. | strict terminality and compatibility / best-effort interrupt delivery |

Repository-level commands remain:

`python3 -m unittest orchestrator.tests.suite_checkpoint`

`python3 -m unittest orchestrator.tests.suite_extended`

They are the normal checkpoint and architectural complement and must not be
reported as run unless implementation actually executes them
(`orchestrator/README.md:565-586`).

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Operators and calling products can currently order only one agent call or one Brainstorming discussion. Without this slice they cannot obtain one public production-plus-review result and must either start a milestone or manually compose calls, reviews, and commits. That risks stale-byte acceptance, missing review/fix evidence, a false success before Git, and duplicate spend. Code and task records are reversible before publication; spent calls and a consumed false result are not. | assigned need `implementation/milestones/deep-reviewed-tasks/skeleton.md:12-26,112`; current two-entry catalogue `orchestrator/tasks.py:66-125`; current direct host split `orchestrator/task_api.py:580-590` |
| machinery | This slice adds one `reviewed_task` catalogue/configuration contract and one standalone adapter in the existing generic admission/host, plus the generated controls and focused conformance tests. The adapter serves the sole authorised outcome by joining the already-reusable reviewed lifecycle to the existing standalone task record and recovery host. It reuses the existing store, state machine, routers, Git operations, and result envelope; no new runtime module, dependency, process, or store is required. | assigned surface `implementation/milestones/deep-reviewed-tasks/skeleton.md:92-103,112`; lifecycle seam `orchestrator/driver.py:477-710`; existing store/host `orchestrator/task_api.py:49-184,426-590` |
| consumers_touched | Verified runtime consumers touched are the shared catalogue/order validator, generic service admission and Stop path, standalone host/store, and catalogue-generated panel. The reviewed lifecycle, state, Git, routers, and result validator are reused dependencies. The current milestone driver remains a parity consumer of that same lifecycle: enforcing its already-strict current-byte recovery invariant for both callers changes neither milestone composition nor outcome law. Searches across Life, Agent99, life_product_components, and Tutor found no current code consumer of `reviewed_task`; Agent99 remains a later caller of the same generic contract, so no product adapter is created. | service consumers `orchestrator/service.py:4165-4245,4284-4305,4581-4631`; shared current-byte contract `implementation/milestones/deep-reviewed-tasks/slices/slice-04.md:104-107`; panel consumer `orchestrator/static/panel.html:5674-5832`; future-caller boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:24-26` |
| cheaper_alternative | Extending the shared catalogue, store, host, panel, and reviewed lifecycle is cheapest. Documentation or configuration cannot turn one direct model call into current-byte convergence and a gate-backed result. A synthetic one-slice milestone would import plan, cadence, closure, and run state the task does not own; a second lifecycle, store, route, or panel would duplicate solved machinery. Doing nothing leaves the mandated public type absent. | existing reusable lifecycle/result `orchestrator/driver.py:477-710`; existing generic admission/store `orchestrator/tasks.py:649-865`; `orchestrator/task_api.py:49-184`; no-duplicate boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:90-103` |
| cost | Build cost is a bounded adapter plus catalogue schema rendering and restart/Stop/API tests. Review cost is moderate because the outer task record, lifecycle state, Git effects, and host control cross crash boundaries. There is no data migration, daemon, dependency, extra store, or new provider call beyond the selected reviewed policy. Operation pays the existing production/review/fix calls and Git work. Omission costs the public capability and encourages manual, non-recoverable composition; pre-publication changes are reversible, while already-spent calls and published false results are not. | standard-library environment `orchestrator/README.md:3-9,33-46`; existing call/result boundary `orchestrator/driver.py:477-710`; compatibility boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:90-103,138` |
| threat_model | Untrusted inputs handled by this slice are the authenticated caller's executor configuration and common request, selected work-area handles/paths, references/output destination, provider/model JSON, and workspace edits. Existing closed order validation, project access/path containment, own-root Git guards, prompt-bound result contracts, and edit detection guard them. Trusted inputs are catalogue definitions, resolved project defaults, Staffing Router answers, and lifecycle/task records emitted by this product. The note adds no defensive check around malformed trusted emissions; tests exercise their outcomes and recovery instead. | order boundary `orchestrator/tasks.py:178-224,232-267,649-725`; service/path boundary `orchestrator/service.py:4165-4216`; Git guard `orchestrator/gitops.py:120-152`; worker/result boundary `orchestrator/runners.py:2922-2982`; edit boundary `orchestrator/README.md:551-554` |
| pinned_facts | The seven hard rows pin only public or cross-slice deviations that would be bugs: executor/routes, exact job and policy names plus omission parity, producer/size applicability, admission authority/errors, one task/result identity, Stop/recovery semantics, and panel/compatibility. Internal class names, state placement, thread/control flow, polling, and rendering layout remain implementation choices. | slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:112`; milestone hard contracts `implementation/milestones/deep-reviewed-tasks/skeleton.md:127-138`; established names `orchestrator/tasks.py:18-50,450-549` |
| verification | Eight executable rows combine one new standalone reviewed-task module with retained catalogue/panel/API, lifecycle/result, route/evidence, producer/size, Brainstorming, Staffing Router, successive-order isolation, real-Git recovery, Stop, and compatibility goldens. The focused command pins this slice; checkpoint and extended suites remain repository gates and are not claimed without execution. | current result proof `orchestrator/tests/test_reviewed_result.py:115-196,255-323`; current direct Stop/restart proof `orchestrator/tests/test_task_api.py:1035-1074,1178-1218`; suite authority `orchestrator/README.md:565-586` |
| enforceability | The catalogue resolver and closed order validator can enforce the public values; service configuration, access/path/root checks, and the workspace lease can enforce admission; store CAS, task-scoped lifecycle association, and null-to-terminal mutation can enforce exclusive identity; the reviewed lifecycle's seal/result and Git primitives can enforce reviewed success; the existing policy gate can enforce producer/size applicability. Implementation gaps are the reviewed catalogue schema/panel controls, mandatory Git-enabled reviewed-task resolution and preflight, the exclusive standalone lifecycle association/driver branch, and reviewed open-task adoption and Stop handoff. The current-byte check before pending-gate recovery is an existing shared Slice 4 invariant whose implementation gap must be closed once for both standalone and milestone callers, never by a standalone recovery fork. All must pass the named tests before any Slice 5 guarantee is claimed. Physical-call uniqueness and panel freshness have no such mechanism and remain best-effort. | configuration mechanisms `orchestrator/tasks.py:278-324,450-550,649-679`; admission/store mechanisms `orchestrator/service.py:4098-4108,4149-4216,4284-4305`; `orchestrator/task_api.py:128-184`; fingerprint/result mechanisms `orchestrator/driver.py:590-710,1834-1849`; shared pending-gate gap `orchestrator/driver.py:636-654,13321-13360`; present host gaps `orchestrator/task_api.py:525-590`; delivery limit `orchestrator/state.py:1-17` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| One service-authoritative configuration is durable before effects | Closed catalogue/order resolution at `orchestrator/tasks.py:278-324,649-679`; effective project configuration at `orchestrator/service.py:4098-4108`; reviewed-policy validation/defaulting at `orchestrator/tasks.py:450-550`. | **Current gap:** the catalogue and panel cannot yet express a reviewed job plus its full policy. Acceptance requires one service-resolved order whose stored values preserve effective project defaults for omitted choices, honor explicit choices, and survive restart. |
| Invalid, unauthorized, Git-disabled/non-root, or overlapping work has no effects | Common request/path validation at `orchestrator/tasks.py:232-267,696-725`; resolved standalone configuration at `orchestrator/service.py:4098-4108`; access, reference, and work-area exclusion at `orchestrator/service.py:4149-4216,4284-4305`; Git toggle/root predicates at `orchestrator/gitops.py:62-63,120-152`. | **Current gap:** ordinary standalone configuration leaves Git disabled and reviewed-task admission checks neither that effective setting nor its gate-capable root. Acceptance requires a Git-enabled ordinary reviewed order and every named refusal before task persistence, provider dispatch, or workspace edit. |
| One public id owns one reviewed lifecycle and one terminal result | Standalone record CAS at `orchestrator/task_api.py:128-184`; null-to-terminal mutation at `orchestrator/tasks.py:822-837`; append-only lifecycle state at `orchestrator/state.py:1-17`. | **Current gap:** an admitted standalone id has no exclusive reviewed-lifecycle association. Acceptance requires the same id and evidence across every named restart window, with no replacement admission or second result authority; every later id on the released work area must produce, review, gate, and account from fresh lifecycle evidence. |
| Success is current, sealed, gated, and counted once | Same-content fingerprint and result projection at `orchestrator/driver.py:590-634,1834-1849`; unit accounting at `orchestrator/state.py:2495-2514`; Git WIP/amend/gate primitives at `orchestrator/gitops.py:638-694,741-760`. | **Current gaps:** no standalone executor consumes this result, and shared pending-gate recovery at `orchestrator/driver.py:636-654,13321-13360` retains only unit identity, not the reviewed fingerprint required by Slice 4. Acceptance requires one shared recovery behavior for standalone and milestone callers: downtime edits invalidate stale reviews, and no host exit or display projection may synthesize success. |
| Stop is terminal failure; crash is recoverable | Generic host control and Stop result rule at `orchestrator/task_api.py:445-474`; open-task adoption boundary at `orchestrator/task_api.py:525-572`; service Stop route at `orchestrator/service.py:4221-4245`. | **Current gap:** the host has no reviewed-task Stop or adoption behavior. Acceptance requires Stop to win over late clean completion while process loss preserves the open id and resumes its lifecycle. |
| Producer and implementation-size applicability cannot leak | Job-scoped producer and size-policy validation at `orchestrator/tasks.py:352-400,517-549`; lifecycle result preserves a cut at `orchestrator/driver.py:618-634`. | **Current gap:** standalone ordering cannot yet select reviewed producers. Acceptance requires size evidence only for `implement` plus `agent_call`, none for Brainstorming, and no successor from a standalone cut. |
| Existing direct tasks and old records keep their law | Stored-name projection and closed record mutation at `orchestrator/tasks.py:137-159,822-837`; current per-executor host/restart behavior at `orchestrator/task_api.py:525-590`. | Acceptance requires the new id to leave every retained direct-task and pre-Slice-5 recovery golden unchanged; any reinterpretation or backfill is a failure. |
