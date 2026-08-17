# Slice 09 — Task activity projection and chips

## Register 1 — INTENT (lay language)

### What this slice builds

This slice lets an operator see the tasks that have been ordered, whether each
is still open, succeeded, or failed, and what result and accounting it retained.
The same history covers tasks ordered directly and tasks ordered by a milestone.

Inside a milestone, task chips sit beside the activity already shown for a unit.
A review that asked for help and failed remains visible even after a later review
succeeds, and drafting and implementation remain separate pieces of work. The
operator can open a task to read its frozen order, the staffing answer recorded
at ordering, its terminal reason when any, its native result, and its complete or
partial accounting.

The task view does not hide the work inside an executor. Existing Worker-call
evidence and Brainstorming-session activity remain visible as execution evidence,
not as extra tasks. Verification, seals, repair, reclassification, attached
discussion, and older activity also stay where they are.

### Ownership and boundary

This slice owns a read-only task-history view, the small selected-run projection
that associates milestone tasks with their unit, task chips, and task detail
presentation. It owns no task admission, execution, result transition,
accounting calculation, review rule, retry decision, or access decision.

The durable task record remains the authority. Chips, grouping, labels, and the
last view displayed in the panel are convenience. Losing or delaying any of them
does not change a task, milestone acceptance, a seal, or a result.

### Dependencies and consumers

The contractual dependencies are the durable task history and the existing
standalone list/inspect service. This slice also reuses the already-built Worker
and Brainstorming links, unit chronology, accounting formatters, task-order panel,
and ordinary refresh behavior.

The consumers are operators inspecting direct work and operators following a
milestone. Executors, callers, and milestone law do not consume the projection.

### Guarantee posture

- **Strict — source fidelity:** anything presented as a task comes from one
  accessible canonical task record. The panel does not manufacture tasks from
  labels, unit names, review numbers, session ids, or legacy activity.
- **Strict — detail fidelity:** an available task detail preserves the frozen
  order, order-time staffing snapshot, terminal state and reason, native result,
  duration, tokens, both cost readings, and partial flags without reinterpretation.
  The staffing snapshot is labelled as historical, never as proof of the calls
  actually made.
- **Strict — attribution and totals:** execution evidence is associated with a
  task only through an explicit durable link. Showing a task subtotal and its
  call evidence never adds either amount again to unit or run totals.
- **Best-effort — history, chips, and delivery:** task-to-unit association,
  chip presence, grouping, log/activity visibility, and refresh are convenience.
  A missing link or failed read is not repaired by inference, and a stale or
  absent chip has no execution or acceptance consequence.
- **No eventual guarantee:** there is no deadline, background reconciliation,
  retry, notification, or promise that a closed view will become current.

### Acceptance criteria

- An authorized operator can open task history and inspect both direct and
  milestone task records without ordering another task.
- Open, successful, and failed records are distinguishable. Detail shows the
  frozen order and staffing snapshot, terminal reason where present, opaque
  native result, and complete or explicitly partial accounting.
- A selected milestone shows its task history by unit. A failed review origin
  and a later successful review remain separate, and separate drafting and
  implementation decisions remain separate.
- A task chip opens the canonical record that supplied it; the panel does not
  reconstruct a record from activity or free text.
- Existing call-level evidence remains inspectable and is visibly subordinate to
  execution rather than counted as another task. Actual call staffing comes only
  from that evidence, not from the order-time snapshot.
- Existing verification, seal, repair, reclassification, attached discussion,
  and legacy activity remain present and are not backfilled as tasks.
- Task accounting is display-only here. Existing unit and run total values are
  unchanged by the projection.
- A failed or stale task fetch may leave the last successful view or no chip. No
  execution state, acceptance, result, or seal changes because of that loss.
- Focused projection/panel checks and the repository's complete suite pass at
  their respective gates.

### Non-goals

- No task event ledger, activity store, scheduler, queue, retry controller,
  liveness rule, timeout, notification, or reconciliation worker.
- No new task route, result shape, task status, executor vocabulary, or panel
  copy of task truth.
- No separate stable chip identity, exact chip cardinality, freshness, delivery,
  acknowledgement, or lost-chip test.
- No successor lineage, parent id, retirement event, review-number inference,
  or backfill of legacy activity.
- No inferred actual staffing, profile version, staffing ledger, or use of the
  order snapshot as dispatch evidence.
- No conversion of verification, seals, repair, reclassification, attached
  Brainstorming, deterministic transitions, or retired seal activity into tasks.
- No change to task admission, execution, recovery, native-result meaning,
  accounting homes, milestone gates, or aggregate totals.
- No placement proof, effect inventory, rollback, cleanup, or output-directory
  enforcement beyond the already-built task boundary.

### Risks

- Collapsing records by unit, kind, or review number would erase a failed origin
  when its successor appears.
- Calling historical staffing “used staffing” would misreport Worker or
  profile-backed Brainstorming dispatch after authority changes.
- Inferring ownership for old calls would attach unrelated work and charges to a
  task.
- Replacing old activity chips with task chips would hide verification,
  discussion, repair, or call evidence.
- Adding task subtotals to existing aggregates would charge the same work twice.
- Copying full native results into the frequently refreshed run summary would
  make a convenience view unnecessarily expensive.
- Treating a failed fetch as an empty authoritative history would make completed
  work appear erased.

### Reuse Posture

The affected party is the operator: without this slice, durable tasks exist but
their result, failure history, and relation to the visible milestone are hard to
inspect. The realistic harm is operational confusion, especially when a failed
review is followed by a clean one. It is visible and reversible by inspecting
the durable record directly; missing bookkeeping harms no acceptance or result.
The reviewed milestone independently requires the convenience view and fixes its
best-effort posture.

Checked and reused are the canonical task list and inspect reads, their existing
access filtering, immutable task history, the driver-authored unit and kind in a
milestone order, explicit task links on existing call/activity records, current
unit-history chips, task/session detail patterns, safe JSON rendering, token and
cost formatters, and last-good-view refresh behavior. The cheapest sufficient
addition is one ordered list of task ids in each unit's read projection, additive
exposure of explicit links on existing activity projections, and one shared task
history/detail renderer. The panel and its operators are the only consumers.

No durable event, migration, cache, route, background process, lineage record,
or parallel accounting/staffing projection is justified. The remaining cost is
the read projection, presentation, and focused checks. Omitting those leaves the
required visibility absent; stronger machinery would cost more to build,
operate, migrate, and review while protecting a value explicitly allowed to be
lost.

### Size posture

This slice is expected to exceed about 500 non-mechanical changed lines because
one focused proof must cover the read projection, the existing access-filtered API, task
history/detail presentation, milestone chips, predecessor/successor visibility,
and preservation of existing activity. Runtime machinery must still remain the
small read-only projection and shared renderer above; fixtures and assertions,
not a new subsystem, are the justified excess.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's task-history, native-result/accounting,
  internal-evidence, and additive-chip intent.
- **Revise:** the original planning language suggesting one guaranteed chip per
  task. The reviewed baseline and operator amendment make chips, logs, and
  activity projection best-effort; focused examples prove useful rendering, not
  survival or global cardinality.
- **Reject:** brainstorming and draft material as implementation authority, and
  any task-event ledger, inferred ownership, successor lineage, freshness system,
  or backfill proposed to strengthen bookkeeping.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Canonical task truth and reads | A task remains exactly `{id, order, resolved_staffing, result}`. The panel reads history from `GET /api/tasks` and detail from `GET /api/tasks/<id>`; it does not create another task record or route. `result: null` means open. A terminal result keeps exact `status` (`success` or `failure`), failure-only `reason`, `duration_s`, `token_usage`, `token_usage_partial`, `cost.{api_usd,real_usd}`, `cost_partial`, and opaque `native_result`. | `implementation/milestones/tasks-2/skeleton.md:43-53,143-147,351,355,360`; record/read boundary `orchestrator/tasks.py:559-636,808-877`; routes `orchestrator/service.py:4071-4156,4217-4229` | touch read-only panel history/detail and the selected-run read projection; do-not-change the durable record/result, add a route, parse native results, or synthesize terminal state |
| Selected-run association | `summary.units[*].task_ids` is an admission-order list of canonical ids whose frozen milestone request context names that exact unit. It is the only new unit-level task index. A record with no matching explicit milestone context remains a valid task but is not inferred into a unit. Existing `drafts[*]`, `rounds[*]`, and `brainstormings[*]` expose `task_id` only when their source already carries that explicit link. | planned Slice 9 `implementation/milestones/tasks-2/skeleton.md:337,340-343,356,362`; frozen context `orchestrator/driver.py:2747-2785,5125-5139`; durable order `orchestrator/tasks.py:597-618`; current activity projection `orchestrator/state.py:1833-1903,2321-2625` | touch the read-only run summary and existing activity projections; do-not-copy full task records/native results into the polling summary, infer from unit/kind/label/session, backfill legacy links, or add durable index state |
| Task chips and immutable history | Each rendered task chip names its canonical record's TaskExecutor, milestone task kind, and open/success/failure state. Chip/detail identity is the full task `id`. Durable admission order is retained, so a failed `review_round` or `delta_review` origin and any later review render as distinct records; `draft_slice_note` and `implement` also remain distinct. No predecessor/lineage member is added. | `implementation/milestones/tasks-2/skeleton.md:54-75,143-159,337,356,358`; immutable history `orchestrator/state.py:336-383`; review proof `orchestrator/tests/test_worker_tasks.py:819-893` | touch additive task chips and one shared detail action; do-not-collapse by unit, kind, round number, label, or session, reopen a terminal task, invent lineage, or guarantee chip cardinality |
| Result, accounting, and staffing presentation | Detail renders the canonical frozen order, labels `resolved_staffing` as the order-time snapshot, and preserves terminal reason, duration, token usage, both cost readings, both partial flags, and `native_result` as escaped opaque JSON. Task subtotals are never fed into unit/run aggregation. Actual agent/model/effort may be stated only by existing call/session evidence. | `implementation/milestones/tasks-2/skeleton.md:43-53,76-104,183-184,354-356`; result validator `orchestrator/tasks.py:808-877`; task accounting `orchestrator/tasks.py:667-759`; existing display formatters `orchestrator/static/panel.html:2535-2641` | touch task detail and reuse existing accounting formatters; do-not-flatten native results, call the snapshot actual staffing, add an inferred staffing projection, or re-add task totals |
| Internal and non-task activity | Existing explicitly linked Worker draft/round/attempt evidence and Brainstorming production activity remain inspectable beneath or beside their task; an internal call is never another task. Unlinked legacy activity, attached Brainstorming, post-result reclassification, verification, seals, repair, deterministic transitions, and retired `seal_half` remain non-task activity and keep their present chips/records. | `implementation/milestones/tasks-2/skeleton.md:52-87,212-232,356,362`; explicit record links `orchestrator/state.py:811-883,990-1037`; existing chronology `orchestrator/state.py:2342-2625`; panel chips `orchestrator/static/panel.html:2898-3198` | touch additive links and task grouping only; do-not-remove/relabel current chips, stamp excluded work, normalize a new task-event vocabulary, infer ownership, or count internal calls as tasks |
| Access, freshness, and guarantee level | Existing task list/inspect access filtering remains authoritative. Task history, `task_ids`, chips, grouping, logs, and refresh are best-effort bookkeeping. The panel may retain its last successful view after a failed read; no open or closed view has a freshness, eventual-delivery, survival, notification, or acceptance guarantee. Durable task records remain authority. | `implementation/milestones/tasks-2/skeleton.md:52,143-159,205-210,337,356,360,362`; access filtering `orchestrator/service.py:4071-4156`; current last-good refresh `orchestrator/static/panel.html:2795-2809,3741-3766,4087-4099` | touch current read/poll presentation only; do-not-add retries, acknowledgements, notifications, reconciliation, durable chip state, or execution decisions based on the view |
| Verification | Focused checks prove the normal read projection, canonical history/detail reuse, explicit-link-only activity, distinct failed-review origins and later tasks, separate production tasks, native result/accounting/staffing labels, preserved non-task chips, and unchanged aggregate totals. They do not fault-inject lost bookkeeping or assert universal chip cardinality/freshness. Final closure remains exactly `python3 -m unittest discover -s orchestrator/tests -t .`. | `implementation/milestones/tasks-2/skeleton.md:337,340-343,363`; existing task/API proof `orchestrator/tests/test_tasks.py:415-617,727-760`; `orchestrator/tests/test_task_api.py:690-766`; suite `orchestrator/README.md:522-532` | touch one focused task-activity test surface and the existing panel test; do-not-add a browser dependency, lost-bookkeeping proof, narrower final suite, or Slice 10's broad conformance matrix |

### Verification Contract

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Unit projection is a small ordered index, not another record store | `test_unit_task_ids_follow_frozen_context_and_admission_order` | A unit receives ids in durable task order when the frozen context names it; an unmatched or unlinked record is not inferred; old state with no tasks yields an empty list without mutation. | strict association when evidence exists; best-effort visibility |
| History and detail reuse canonical API truth | `test_task_history_and_detail_use_canonical_records` | Accessible direct and milestone records render from the list result; selecting one reads the inspect result and preserves open/success/failure, frozen order/staffing, reason, native JSON, accounting, and partial flags. Foreign records remain unavailable under existing access decisions. | strict fidelity/access; best-effort delivery |
| Failed reviews and later reviews never collapse | `test_failed_review_origin_and_later_review_have_distinct_chips` | Both review kinds show the failed help-seeking origin and later successful task as different full ids in admission order; predecessor native evidence remains unchanged and no lineage field appears. | strict record identity; best-effort chips |
| Production decisions remain separate | `test_draft_and_implementation_tasks_render_separately` | A slice with note-drafting and implementation tasks exposes both ids and details independently, regardless of whether their TaskExecutors match. | strict identity; best-effort chips |
| Internal evidence and non-task chips survive | `test_task_chips_preserve_linked_calls_and_non_task_activity` | Explicitly linked Worker and Brainstorming production evidence retains its task id and remains inspectable; legacy/unlinked calls, attached discussion, reclassification, verification, repair, seal, and retired seal evidence remain unstamped and visible. | strict attribution/exclusion; best-effort presentation |
| Task presentation cannot change accounting or staffing truth | `test_task_projection_does_not_reaggregate_or_infer_staffing` | Unit/run totals before and after projection are equal; task subtotals are display-only; order staffing is labelled historical; call/session evidence alone supplies actual family/model/effort. | strict |

The focused implementation command is
`python3 -m unittest orchestrator.tests.test_task_activity orchestrator.tests.test_task_panel`.
Existing `orchestrator.tests.test_tasks`, `orchestrator.tests.test_task_api`,
`orchestrator.tests.test_worker_tasks`, and `orchestrator.tests.test_service_api`
remain lower-level authority. Final closure runs exactly
`python3 -m unittest discover -s orchestrator/tests -t .`.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These five entries are the slice-scoped remainder; enforceability is answered
again for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified touched:** the state summary's per-unit read projection; the service's existing access-filtered task list/inspect and run-detail reads; the panel's project/task entry point, selected-run refresh, unit chronology, task/result detail, and token/cost display; and focused state/service/panel tests. **Verified untouched:** task admission and record shape, standalone store and execution host, milestone scheduling/recovery, TaskExecutor adapters, accounting aggregation, review/fix/seal decisions, Brainstorming lifecycle, and all additional roots. | summary `orchestrator/state.py:2321-2714`; task/run reads `orchestrator/service.py:4071-4156,4217-4229,3220-3238`; panel consumers `orchestrator/static/panel.html:2221-2378,2898-3198,3741-4050,5535-5910`; boundary `implementation/milestones/tasks-2/skeleton.md:325-343` |
| pinned_facts | The hard table pins the unchanged canonical record/result and existing reads; exact `summary.units[*].task_ids`; explicit-link-only activity; distinct review and production identities; opaque result/accounting and historical staffing presentation; preservation of non-task activity and totals; and best-effort freshness/cardinality posture. | `implementation/milestones/tasks-2/skeleton.md:43-104,143-159,205-232,337,345-363`; `orchestrator/tasks.py:559-636,667-877`; `orchestrator/state.py:336-383,811-883,990-1037` |
| verification | One focused task-activity module pins unit association, canonical list/detail rendering, distinct failed-review/later-review ids, separate note/implementation ids, explicit linked activity, non-task preservation, and unchanged totals/staffing semantics. The existing task, API, Worker-lifecycle, state-summary, served-panel, and full-discovery suites remain lower-level proof. No test promises that bookkeeping survives every failed fetch or that every durable task always has a chip. | planned verification `implementation/milestones/tasks-2/skeleton.md:337,363`; identity proof `orchestrator/tests/test_worker_tasks.py:819-893,1819-1845`; access proof `orchestrator/tests/test_task_api.py:690-766`; current activity proof `orchestrator/tests/test_state.py:2550-2634`; suite `orchestrator/README.md:522-532` |
| reuse_posture | **Affected party/harm:** operators otherwise cannot comfortably inspect durable task outcomes or distinguish a failed review from its later success; the harm is visibility confusion and is reversible by direct record inspection, while lost bookkeeping changes no result. **Checked/reused:** canonical records and reads, access filtering, frozen milestone context, explicit task links, unit chronology, session activity, safe detail dialog, accounting formatters, and last-good refresh. **Cheapest sufficient option:** ordered task ids in the existing unit projection, additive exposure of existing links, and one shared history/detail renderer. **Remaining machinery/consumer:** read-only projection, chips, and focused checks consumed only by operators. **Lifecycle:** no migration, route, durable event/index, cache, background worker, lineage, staffing/accounting ledger, or reconciliation; omission loses required visibility, while stronger machinery protects only disposable bookkeeping. | reuse boundary `implementation/milestones/tasks-2/skeleton.md:234-306,337,356,362`; existing records/reads `orchestrator/tasks.py:559-636`; `orchestrator/service.py:4071-4156`; current panel seams `orchestrator/static/panel.html:2535-2641,2898-3198,4101-4120` |
| enforceability | **Canonical fidelity/immutability:** closed validators plus append-only task history and list/inspect reads supply the exact record. **Unit association:** the frozen driver-authored context names unit/kind, and only record ids or explicit `task_id` links are projectable; absence remains unowned. **Identity:** unique append-only ids and the null-to-one-result transition keep failed origins and later tasks distinct. **Access:** existing service filtering precedes list/inspect delivery. **Accounting/staffing:** existing task accounting and unit/run aggregators remain separate; per-call/session records, not `resolved_staffing`, carry actual dispatch evidence. **Non-task preservation:** current summary and `unitHistory` already carry verification, seal, repair, reclassification, discussion, and call chips; task rendering is additive. **Freshness/cardinality:** no mechanism can guarantee delivery, survival, or timeliness, so this note promises only best-effort visibility and no eventual convergence. | validators/history `orchestrator/tasks.py:559-636,667-877`; `orchestrator/state.py:336-383`; frozen context/links `orchestrator/driver.py:2747-2808,5125-5282`; access `orchestrator/service.py:4071-4156`; existing aggregation/projection `orchestrator/state.py:1906-2217,2321-2714`; panel activity/refresh `orchestrator/static/panel.html:2898-3198,3741-3766,4087-4099`; bounded guarantee `implementation/milestones/tasks-2/skeleton.md:52,205-210,337,356,362` |
