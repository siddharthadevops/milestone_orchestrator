# Slice 07 — Standalone tasks and work-area alignment

## Register 1 — INTENT (lay language)

### What this slice builds

Standalone work stops choosing its own intelligence from the first available
agent family. A calling product can attach the staffing session it owns to a
task order, and the task asks that live session immediately before its agent
call. When no session is supplied, the normal default staffing answers and the
call's evidence says so.

An Agent-call order also says what process step the call performs. A direct
order defaults to implementation work; milestone-owned orders carry the role
of the milestone step that created them. The caller chooses the role, not a
seat. Multi-seat policy remains with the consumers that already own it.

The same rule now covers the operator-requested alignment of a git work area.
The alignment uses the caller's accessible staffing session, or visible default
staffing when none is supplied, without changing the operation's existing
safety refusals or its meaning of aligned versus stopped.

A new order records whether it deliberately uses default staffing, so it cannot
be confused with work admitted before this cutover. Older standalone work keeps
the staffing authority already recorded on it and is neither rewritten nor
silently moved to the default.

### Ownership and boundary

Owned here: the inherited session field on task orders and git-alignment
requests; the Agent-call role choice; live resolution for the direct Agent-call
host and git alignment; forwarding the same session to the already-cut-over
standalone Brainstorming adapter; actual-call and fallback evidence; legacy
standalone-task compatibility; and focused tests.

Not owned here: staffing documents, session storage or editing, the resolver's
rules, milestone review law, Brainstorming's roster or lifecycle, work-area
ownership and git safety law, task scheduling or recovery, planner materials,
the panel controls, product adapters, or any new permission system, store,
queue, retry, cache, ledger or event stream.

### Guarantee posture

- **Strict — call selection.** Every new standalone Agent call and every git
  alignment that reaches an agent uses the current router answer for its role.
  Neither first-family defaults nor order-time bookkeeping can staff it. A
  surfaced staffing condition prevents that provider call.
- **Strict — inherited context and access.** A named session must already be
  accessible to the caller. Omitting it deliberately chooses visible default
  staffing and creates no session. Any authorized session owner, including a
  calling product, may supply it.
- **Strict — live change.** The last completed session or document write governs
  the physical call. Admission does not freeze a later dispatch, and a call
  already made is unchanged.
- **Strict — compatibility.** A pre-cutover standalone record keeps its stored
  dispatch authority. New default-backed records are distinguishable from old
  field-absent records, and neither shape is migrated or rewritten.
- **Optimistic — concurrent configuration.** Existing atomic, last-completed
  session and document saves remain the only concurrency rule; there is no
  version, acknowledgement or dispatch barrier.
- **Best-effort — evidence.** The task marker, git-alignment outcome and the
  Agent-call `resolved_staffing` snapshot are bookkeeping. A written marker or
  outcome identifies its call accurately; the admission snapshot may be stale
  by design. Loss, staleness or delivery failure changes no task or git result
  and triggers no reconciliation.
- **Eventual — none.** Nothing is replicated, queued or reconciled by this
  slice.

### Dependencies and consumers

This slice depends on the closed role vocabulary, live session resolver,
default-document fallback, session access checks, and the run's existing single
session binding. It reuses the direct task store and host, the Brainstorming
adapter's session-selection seam, the git-alignment runner and safety lease, and
their existing activity and accounting forms.

Direct consumers are milestone Agent-call order creation, the public standalone
task endpoint, both executors hosted by a direct task, explicit restart of a
task-owned Brainstorming session, and the project git-alignment endpoint. The
panel remains transitional until its own slice.

### Acceptance

The slice is accepted when focused tests show that:

- the Agent-call catalogue exposes the closed role choice with its default, a
  direct order stores that role and an explicit supplied-or-default session
  context, and each milestone Agent-call order records the role and session of
  the step that owns it;
- a named task session is checked with existing caller and project access
  before admission; an unknown or inaccessible session is refused without a
  task record, while omission or explicit null admits no new session record;
- the direct host asks the router once at the physical call with the stored
  role, first seat, first round and the task text as its brief; session and
  document edits after admission affect that call, while `resolved_staffing`,
  first-family defaults and producer configuration cannot select it;
- default or later-unreadable session/document input still makes the direct
  call, and its marker carries the actual family, model and effort plus the
  default-document fallback; either surfaced condition makes the task terminal
  with its public token and creates neither a provider call nor a call marker;
- failure to write either phase of the best-effort task marker cannot replace a
  native task outcome;
- a new standalone Brainstorming order forwards its supplied or explicit-null
  session context at admission, start, explicit restart and agreed production,
  while a pre-cutover static task keeps its pins;
- a pre-cutover Agent-call or retired Worker record with no session field runs
  its stored staffing snapshot without byte changes; and
- git alignment checks its existing work-area safety first, then resolves
  `sync` for its one physical call; named-session access, live edits, fallback,
  the two surfaced-condition statuses, actual-call evidence and the absence of
  a provider call on refusal are all pinned without changing alignment outcome
  law.

The implementation is expected to stay within the approximately 500
changed-line aim. It extends existing order, host, resolver-adapter and outcome
seams; the largest share should be focused integration tests rather than new
runtime machinery.

### Risks and non-goals

- Treating an omitted new session exactly like a legacy missing field would
  silently move old work from its recorded staffing to today's default.
- Reading `resolved_staffing` or the current first family at dispatch would
  restore the parallel authority this milestone removes. Tests poison both.
- Resolving git staffing before the existing ownership refusal could surface an
  irrelevant staffing error for a call that was never eligible to run.
- A marker write must not become a new availability gate merely because it is
  attempted before the provider call.
- No task retry, cancellation, liveness, migration or new route is added. No
  git mandate, work-area lease, alignment verdict, Brainstorming lifecycle,
  panel surface, planner channel, review reader or granted read-only root is
  changed.

### Reuse Posture

The affected parties are operators and calling products ordering standalone
work or git alignment. Without this cutover, a call can run at an unintended
family, model or effort, producing visible quality or cost harm on every order;
the choice is visible per call and reversible on the next call, but git work may
already have been performed. The reviewed slice is the independent authority.

Checked and reused: the task catalogue's schema-driven choice validation, the
closed order and immutable record, the existing direct host call boundary, the
session access reader and live resolver, the task marker and accounting, the
Brainstorming adapter's current-session selection, and git alignment's project
authorization, work-area resolution, ownership lease, runner and outcome. The
cheapest sufficient option is one inherited order/request field, one role
choice, an explicit null on new default-backed orders, and adapters at the two
existing physical-call boundaries. The null distinction is the only new
compatibility machinery and is consumed by direct execution and restart. A new
store, route family, ACL, scheduler, retry, cache, ledger or migration would add
lifecycle cost without improving the authorized outcome. The retained cost is
one live read per physical call and one small immutable field; omission repeats
misstaffing, while old records remain untouched and the cutover is locally
reversible.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Task session context | `POST /api/tasks` and the closed task order accept optional top-level `staffing_session`. Each newly admitted standalone order stores the key: an accessible session id when supplied, `null` when omitted or explicitly null. Each new milestone Agent-call order stores its run's bound id or null. A named direct id reuses the session route's `404 unknown_staffing_session` and `403 forbidden` results before admission; every caller passing that access check may supply it, with no creator or work-area-equality rule. Null creates no session and resolves as `default@medium` with the host's configured families. A missing key is reserved for pre-cutover in-scope records. | `implementation/milestones/staffing-router/skeleton.md:225-233,295,321-324`; `implementation/milestones/staffing-router/goal.md:72-75,222-225,244-249`; access seam `orchestrator/service.py:2140-2202`; current closed order `orchestrator/tasks.py:517-542` | touch the shared order validator, direct admission and milestone Agent-call order builders; do-not add a second staffing field, create a session implicitly, persist caller identity, require one creator, or rewrite old orders |
| Agent-call role | `agent_call.configuration_schema.role` is `type: choice`, choices exactly `plan`, `draft`, `implement`, `fix`, `classify`, `review`, `brainstorm`, `consult`, `sync`, default `implement`; an invalid value is 400 `invalid_task_request`. A direct call uses index 1 and round 1 and exposes no seat input. Milestone orders record their physical role: draft skeleton and a skeleton fix = `plan`; slice-note draft = `draft`; implementation = `implement`; other fixes = `fix`; full and delta review = `review`. A prospective producer configuration cannot override the milestone-owned role. | `implementation/milestones/staffing-router/skeleton.md:215-224,231-233,309,321`; driver request map `implementation/milestones/staffing-router/slices/slice-04.md:270`; role source `orchestrator/staffing.py:94-99`; choice validator and token `orchestrator/tasks.py:17-21,238-274`; milestone role seam `orchestrator/driver.py:8626-8650`; kinds `orchestrator/contracts.py:52-80` | touch the catalogue schema and order construction; do-not add roles, expose seat or round controls, or let an LLM or producer selection choose a milestone dispatch role |
| Direct physical call | A new session-backed Agent-call task resolves live immediately before its one provider call with its order's `staffing_session`, configured role, index 1, round 1, no request material, and its request text as best-effort `brief`. The answer's `agent`, `model`, and `effort` are the only dispatch staffing. An unreadable input answers on the mandatory fallback; `staffing_unavailable` or `distinct_families_unsatisfiable` instead produces a terminal task failure naming that token, with no provider call or call marker. | `implementation/milestones/staffing-router/skeleton.md:100-117,295,310,313-318,321`; resolver `orchestrator/staffing.py:2001-2044`; current host boundary `orchestrator/task_api.py:276-355` | touch the direct host's staffing adapter and refusal mapping; do-not resolve at admission as authority, cache, retry, fabricate a call, add a condition, or use first-family/profile defaults to staff the call |
| Task evidence and compatibility | The task marker records the actual `family`, `model`, `effort` and, on fallback, `staffing_fallback: "default_document"`; both marker writes are best-effort and never replace the native result. The `resolved_staffing.agent_call` snapshot remains best-effort order bookkeeping and is neither an admission gate nor dispatch input for a new Agent-call order. A pre-cutover order lacking `staffing_session` keeps its recorded authority: Agent-call snapshots under `agent_call` or retired `worker`, and Brainstorming's recorded static/current-profile distinction. Old records execute without rewrite. | run amendment A2; `implementation/milestones/staffing-router/skeleton.md:72-76,112-117,295,317,320,324`; marker seam `orchestrator/task_api.py:143-166,291-355`; standalone append/result writers `orchestrator/task_api.py:22-91`, `orchestrator/tasks.py:649-687`; milestone history guard `orchestrator/state.py:336-365`; retired-record proof `orchestrator/tests/test_task_api.py:290-332` | touch marker fields additively and add only the new-vs-legacy read distinction; do-not migrate records, make Agent-call bookkeeping authoritative, gate an outcome on marker persistence, reopen slice 6's Brainstorming authority discriminator, or remove the read-time `worker` alias |
| Standalone Brainstorming handoff | A newly admitted direct Brainstorming task carries the same supplied id or explicit null through admission, start, explicit restart and agreed production. Its automatic calls continue to obey slice 6. A pre-cutover static task has no new field and keeps its pins. | `implementation/milestones/staffing-router/skeleton.md:225-230,294-295,321-324`; prior boundary `implementation/milestones/staffing-router/slices/slice-06.md:47-50,167-172`; existing adapter `orchestrator/brainstorming_tasks.py:92-167,439-491`; restart seam `orchestrator/service.py:4056-4097` | touch the direct host and task-owned restart handoff; do-not reopen Brainstorming roles, roster, activity, lifecycle, recovery or legacy-pin law |
| Git-alignment call | `POST /api/projects/<slug>/git-sync` accepts required `work_area` plus optional `staffing_session` (omitted or null means default); a named id must pass the existing session-access check. Existing project-admin authorization, work-area validation, ownership exclusion, prompt, runner and `aligned`/`stopped`/`unknown` outcome law stay. Only when a physical call is eligible, resolve `sync`, index 1, round 1 live; 503 `staffing_unavailable` and 409 `distinct_families_unsatisfiable` invoke no provider. The returned `sync` object records actual `family`, `model`, `effort` and optional `staffing_fallback: "default_document"`. | `implementation/milestones/staffing-router/skeleton.md:215-224,295,315,317,321-322`; condition statuses and session access `orchestrator/service.py:2077-2082,2190-2202`; project-admin gate `orchestrator/service.py:4498-4512`; current sync seam `orchestrator/service.py:3731-3793`; outcome `orchestrator/gitsync.py:147-221` | touch the existing request adapter and call staffing; do-not alter git safety/lease/verdict law, resolve a refused call, create a task or session, add another staffing field, or add persistence/retry |
| Slice boundary | Router/document/session contracts, milestone dispatch and review law, Brainstorming internals, the panel, planner material, retired profile/acts routes and compatibility derivation remain unchanged. Accepted amendment B1's third non-dispatch review-family read is inherited and untouched. | `implementation/milestones/staffing-router/skeleton.md:59-63,294-303,319,322-325`; prior Brainstorming boundary `implementation/milestones/staffing-router/slices/slice-06.md:167-172` | touch only task-order context/role, direct-host and restart adapters, git-sync staffing/evidence, and focused tests; do-not edit generated ledgers or any granted read-only root |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_staffing_standalone_cutover orchestrator.tests.test_task_api orchestrator.tests.test_tasks orchestrator.tests.test_worker_tasks orchestrator.tests.test_gitsync orchestrator.tests.test_staffing_sessions orchestrator.tests.test_staffing_brainstorming_cutover`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Orders carry one session and the right role | new `test_task_orders_carry_one_session_and_owned_role` in `orchestrator/tests/test_staffing_standalone_cutover.py` | Catalogue choices/default are exact; supplied, omitted and explicit-null direct orders persist an id or null; all milestone Agent-call kinds persist the run session and the pinned role map, including a skeleton fix and both review kinds; producer configuration cannot replace that role. | strict |
| Direct staffing is live and exclusive | new `test_direct_agent_call_resolves_live_and_ignores_snapshot` | Captured resolution is role/index/round/brief exactly; edits after admission change the provider call; poisoning first-family defaults and `resolved_staffing` does not, and an admission-time snapshot failure cannot refuse the order. | strict |
| Fallback, conditions and marker posture are visible | new `test_direct_fallback_conditions_and_marker_posture` | Omitted, absent and unreadable inputs dispatch on default and write the exact fallback field; each surfaced condition yields its token with no provider/marker; failing either marker write still preserves the native task result. | strict selection / best-effort evidence |
| New and old task authorities do not cross | new `test_direct_task_compatibility_boundary_is_field_presence` | New supplied/null Brainstorming orders carry their selection through start, explicit restart and effect; a missing-field static Brainstorming task keeps pins; missing-field `agent_call` and `worker` fixtures use their stored snapshot; no fixture bytes change. | strict |
| Git alignment asks only for an eligible physical call | new `test_git_sync_resolves_live_after_ownership_checks` | Unknown/foreign named sessions are refused through existing access; busy/unusable work areas make no staffing request; supplied and null sessions resolve `sync 1` round 1 at the call, edits are live, fallback is returned, both condition statuses invoke no runner, and existing verdict fields remain equal. | strict selection / best-effort response evidence |
| Existing task, Brainstorming and git law remains | existing suites in the focused command | Task validation/admission/result/accounting, task-owned Brainstorming, staffing resolution, work-area exclusion, git mandate and outcome tests pass with only the intentional order-schema expectation changes. | strict |

The repository closure gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:533-535`; `implementation/milestones/staffing-router/skeleton.md:325`).

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These are the slice-scoped remainder. Enforceability is answered again for the
facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | Verified direct consumers: the shared TaskExecutor catalogue, configuration/order validator and durable admission; milestone Agent-call order construction; standalone task work-area/access resolution and admission; the direct host's Agent-call and Brainstorming branches; explicit restart of a task-owned Brainstorming session; project git-sync authorization, work-area exclusion and physical runner; and the task marker/accounting and git outcome views. The router, Brainstorming internals, review cycle, planner and panel are reused or untouched. | `orchestrator/tasks.py:41-56,238-274,517-542,627-670`; `orchestrator/driver.py:2937-3025,8626-8650`; `orchestrator/task_api.py:94-171,226-416`; `orchestrator/service.py:3731-3793,4011-4097,4188-4327,4498-4512,4768-4800`; `orchestrator/gitsync.py:184-221` |
| pinned_facts | One optional top-level session field persisted as id/null on new standalone and milestone Agent-call orders; existing session-access classifications and unrestricted authorized authorship; the exact Agent-call role schema/default and milestone role map; live direct resolution at `role 1`, round 1 with brief; the two conditions and default fallback; actual marker fields with best-effort persistence; the Agent-call staffing snapshot demoted for new work but retained for missing-field legacy work; the existing Brainstorming handoff; live `sync 1` staffing and outcome evidence; and the adjacent-slice no-touch boundary. | run amendments A2 and A3; `implementation/milestones/staffing-router/skeleton.md:225-233,295,309-325`; `implementation/milestones/staffing-router/goal.md:72-75,206-211,222-225`; `orchestrator/staffing.py:94-99,1582-1622,2001-2044` |
| verification | The six-row Verification Contract pins exact order context and milestone roles, live direct-call request capture and exclusion of old selectors, fallback/condition/marker behaviour, the new-versus-legacy authority boundary across both executors, git resolution only for an eligible call, and unchanged adjacent suites. Existing tests supply the task marker, retired-record, Brainstorming session-selection and git outcome seams; closure keeps the official full suite. | `orchestrator/tests/test_task_api.py:224-332,395-452,945-993`; `orchestrator/tests/test_worker_tasks.py:516-545,602-644`; `orchestrator/tests/test_staffing_brainstorming_cutover.py:1473-1778`; `orchestrator/tests/test_gitsync.py:38-68,179-228`; `orchestrator/README.md:533-535` |
| reuse_posture | Affected parties are callers of standalone work and git alignment; omission repeats visible per-call quality/cost misstaffing and may let git work occur under the wrong intelligence, while the next call remains editable. Reused: catalogue validation, immutable orders, direct host, session access and resolver, marker/accounting, Brainstorming's existing selection handoff, and git authorization/lease/runner/outcome. Cheapest sufficient is one inherited field, one role choice, an explicit-null legacy discriminator and adapters at two call boundaries. The discriminator is consumed by direct execution/restart; no store, route family, ACL, scheduler, retry, cache, ledger or migration remains to operate. Lifecycle cost is one live read per call and one immutable field, weighed against repeated harm; old bytes remain untouched. | `implementation/milestones/staffing-router/skeleton.md:258-283,295,317-324`; `orchestrator/tasks.py:238-274,517-542,649-670`; `orchestrator/task_api.py:226-355`; `orchestrator/brainstorming_tasks.py:92-167,439-491`; `orchestrator/service.py:3650-3793,2140-2202` |
| enforceability | The shared choice/order validators can enforce the exact role and session field; session reads enforce existing caller/project access; append/result-only task writers, the milestone history guard and explicit null distinguish new defaults from old missing-field records; `staffing.resolve` enforces live role/index/round answers, fallback and the only two tokens; the host's pre-provider boundary and marker writer can enforce no call on refusal and actual-call evidence without making writes authoritative; the existing Brainstorming selection callbacks enforce handoff; and the git lease plus runner boundary enforce resolution only for an eligible call and preserve verdict law. Focused tests capture requests, provider calls, record bytes, marker failures and outcomes. No persistence, notification, retry, cache-coherence or eventual-delivery guarantee is asserted. | `orchestrator/tasks.py:238-274,517-542,649-687`; `orchestrator/task_api.py:22-91,291-355`; `orchestrator/service.py:2140-2202,3650-3793`; `orchestrator/state.py:336-365`; `orchestrator/staffing.py:1975-2044`; `orchestrator/brainstorming_tasks.py:439-491`; `orchestrator/gitsync.py:147-221` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| New standalone and milestone Agent-call orders carry one session context and exact role | Closed configuration/order validation and append-only admission in `orchestrator/tasks.py:238-274,517-542,649-670`, the standalone store in `orchestrator/task_api.py:22-91`, session authorization in `orchestrator/service.py:2140-2202`, milestone history comparison in `orchestrator/state.py:336-365`, and the existing milestone role source in `orchestrator/driver.py:8626-8650`. | Exercise id, omitted, null, unknown and foreign direct sessions; assert stored order bytes and every milestone Agent-call role/session, then attempt a producer-role override. |
| A new direct call is staffed live and exclusively | One `staffing.resolve` answer in `orchestrator/staffing.py:2001-2044` can replace the first-family selector at the pre-provider boundary in `orchestrator/task_api.py:291-320`; the current config resolver in `orchestrator/service.py:4188-4198,4303-4310` supplies fallback families and transport only. | Edit session/document after admission, poison the snapshot/default selector, capture the resolve request and provider arguments, and assert one call. |
| Fallback calls are marked and surfaced conditions make no call | The resolver's typed result and tokens in `orchestrator/staffing.py:1582-1622,2001-2044`, plus the marker boundary in `orchestrator/task_api.py:291-355`. | Break each input, raise each condition, count provider calls, inspect marker presence/fields, and inject failure into both marker writes. |
| Legacy standalone authority survives without migration | Field presence in the order distinguishes new id/null records from old records; the append/result-only writers in `orchestrator/task_api.py:22-91` and `orchestrator/tasks.py:649-687` preserve old order bytes, `orchestrator/tasks.py:97-119` supplies the retired executor alias, and the frozen snapshots already sit in `resolved_staffing`. | Load byte snapshots for pre-field `agent_call`, `worker` and static Brainstorming records; execute/restart each and compare bytes before and after. |
| Standalone Brainstorming receives the task's one selection | Existing selection-aware admission/start/effect callbacks in `orchestrator/brainstorming_tasks.py:92-167,439-491` and task-owned restart in `orchestrator/service.py:4056-4097`. | Capture the selection at admission, initial start, explicit restart and agreed effect for id/null; repeat with an old static record. |
| Git alignment resolves only for the call it will make | Existing project-admin gate and ownership lease in `orchestrator/service.py:3650-3793,4498-4512`, router answer in `orchestrator/staffing.py:2001-2044`, and runner/outcome seam in `orchestrator/gitsync.py:147-221`. | Refuse busy/unusable areas before resolution; then capture `sync 1`, edits, fallback and both conditions while holding existing verdict output constant. |

There is deliberately no enforcement row for marker or outcome survival,
notification, retries, history, reconciliation, cache coherence, or eventual
delivery: this slice asserts none of them.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's slice-7, standalone-session, marker,
  compatibility and public-body boundaries; amendments A2 and A3; and slice
  6's prepared standalone Brainstorming session-selection seam.
- **Revise:** only the still-live first-family selectors and authoritative
  admission snapshot at the direct Agent-call and git-alignment consumers. The
  existing task and git lifecycles remain.
- **Reject:** `_drafts` or other planning prose as authority;
  session/work-area equality, a creator restriction, and any new store, route,
  ACL, snapshot, cache, retry, queue, ledger, migration or adjacent cutover.
  Amendment A1's capability ladders and accepted amendment B1's third review
  read are inherited as no-touch dependencies.

Authority: `implementation/milestones/staffing-router/skeleton.md:118-136,225-256,295-325`;
current deferred boundaries
`implementation/milestones/staffing-router/slices/slice-04.md:280` and
`implementation/milestones/staffing-router/slices/slice-06.md:47-50,167-172`.
