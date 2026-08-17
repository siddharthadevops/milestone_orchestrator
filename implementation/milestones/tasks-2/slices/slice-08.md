# Slice 08 — Task ordering and selection panel

## Register 1 — INTENT (lay language)

### What this slice builds

This slice gives operators one simple panel surface for choosing who produces
work. A project member can order a standalone task, read what Worker and
Brainstorming are for, and set the options that the selected executor actually
offers. A milestone page also shows two choices for every slice: who drafts its
note and who implements it. Either choice can be changed independently while
that work is still prospective.

The panel is a client of the APIs already built. It does not keep its own list
of executor types, defaults, or allowed choices. It shows the catalogue and the
current run view it most recently received, submits an operator decision, and
lets the service accept or refuse it. A successful direct order shows the
accepted task id; ongoing task history and chips belong to the next slice.

### Ownership and boundary

This slice owns the task-order form, the executor descriptions and
configuration controls in that form, and the two producer controls shown with
each milestone slice. Standalone ordering in the panel is project-bound: the
operator chooses one declared work area rather than typing workspace authority.
The administrative project-less API remains available to machine callers but
does not need a second panel mode.

The slice does not own admission, access, producer freezing, task execution,
results, accounting, or replacement-plan semantics. It does not turn the
existing standalone Brainstorming-session form into a task form: direct
Brainstorming tasks stay target-free and expose neither seats nor a private
target. Review and fixer producers remain Worker-only and receive no selector.

### Dependencies and consumers

The slice depends on the shared TaskExecutor catalogue, standalone task API,
project/work-area binding, effective two-key slice projection, producer write,
and the panel's existing project menu, form, escaping, error, and refresh
patterns. Its consumers are project members ordering direct tasks and operators
choosing the next note or implementation producer for a visible run.

### Guarantee posture

- **Strict — catalogue parity:** after a successful catalogue read, every
  executor description, selectable id, option default, finite choice, and
  minimum shown by the task surfaces comes from that response. Empty schemas
  produce no configuration controls. Available staffing descriptions are
  explanatory only and never become a seat selector.
- **Strict — submitted decisions:** one explicit standalone submit sends one
  project-bound common order to the existing task route. One producer submit
  names exactly one slice and exactly one of note drafting or implementation;
  it never changes the sibling choice. The service remains the authority for
  validation, access, admission, freezing, and refusal.
- **Strict — acknowledged view:** a successful direct response displays its
  returned task id. Producer values shown as confirmed come only from a
  successful producer response or run read; the panel invents neither success
  nor a sibling value.
- **Optimistic — HTTP delivery:** the panel disables a submit while that
  request is in flight and never retries a write automatically. A lost response
  may hide an accepted direct task or producer write; another operator submit
  is a new decision and may create a second task.
- **Best-effort — producer bookkeeping and visibility:** the two producer
  values are the latest successfully fetched effective plan. A changed
  replacement plan may discard either override, including one on an apparently
  unchanged row; the replacement view is the only notice. Polling, error
  banners, and controls carry no freshness, survival, acknowledgement-window,
  or eventual-delivery guarantee.
- **Best-effort — effects:** an optional output directory remains a destination
  instruction, but the panel adds no placement proof, confinement, cleanup, or
  success rule.

### Acceptance criteria

- A project member can open a direct task form from a visible project, select a
  declared work area and TaskExecutor, enter request and context text, maintain
  ordered reference documents, optionally name an output directory, and submit
  the executor configuration generated from the current catalogue schema.
- The selected executor's name, description, operating mode, usage examples,
  available staffing description, and configuration controls are visible
  before submission. Worker shows no executor configuration; Brainstorming's
  visible fields and values come from the shared schema rather than panel
  constants.
- The panel submits the closed common order once per explicit action, displays
  the returned task id on acceptance, and shows the service's refusal token on
  failure without translating it or claiming that a task was admitted.
- Every planned slice visibly shows separate current choices for note drafting
  and implementation. Editing either uses the same catalogue-driven selector
  and posts only that exact task kind and its selected executor configuration.
- A successful producer write displays only service-confirmed values. Frozen,
  busy, malformed, unknown, or unavailable choices remain unchanged in the
  panel until a later successful response says otherwise, and their service
  error is visible.
- A later plan replacement is rendered as received, with no replay, lost-value
  notice, stable slice identity, or per-row survival exception.
- Focused panel checks, the existing task API tests, the existing producer
  selection tests, and the repository's complete suite pass at their respective
  gates.

### Non-goals

- No task list, task detail page, task/activity chips, internal-call display,
  accounting view, result polling, or freshness mechanism; those belong to
  Slice 9.
- No new API route, catalogue, schema, validator, task projection, durable
  panel state, scheduler, queue, retry policy, notification, or producer
  identity/lineage record.
- No bulk producer write, cross-freezing, selector for skeleton/review/fixer
  work, runtime auto-routing, or inference from usage examples or staffing
  descriptions.
- No panel mode for project-less administrative orders and no caller-authored
  workspace roots.
- No Brainstorming target, seat, agent, model, or effort picker; no change to
  the existing standalone-session form.
- No Worker prompt decoration, filesystem placement gate, causal effect proof,
  confinement, rollback, or cleanup.

### Risks

- Copying executor names or Brainstorming defaults into the page would let the
  panel disagree with admission after one catalogue change.
- A combined producer editor could overwrite the sibling choice or turn one
  task's freeze into a slice-wide freeze.
- Predicting frozen or busy state from unit appearance would race the durable
  service decision; refusal must remain authoritative.
- Automatically retrying a lost direct-order response could create a second
  task and repeat effects.
- Treating a replacement as the same slice because its number or title looks
  familiar would wrongly preserve best-effort bookkeeping.
- Adding task history now would duplicate the projection and chip work owned by
  Slice 9.

### Reuse Posture

The affected parties are project members who currently cannot order a generic
task in the panel and operators who cannot see or change the two already-built
slice producer choices. The realistic harm is wrong or unavailable selection;
it is exposed before a task is ordered and normally reversible by another
prospective choice. A lost direct-order acknowledgement is less reversible
because effects may already have begun, so the panel must not retry it.

Checked and reused are the shared catalogue and schema validator, direct order
route and access resolution, effective slice projection, task-kind-scoped
producer route, project/work-area selectors, ordered-reference form pattern,
escaping, common JSON/error helper, modal isolation from polling, and ordinary
run refresh. The cheapest sufficient option is one catalogue-driven executor
presenter/configuration editor reused by the direct-order and producer dialogs,
plus two small per-slice launch points. The panel and its operators are the only
new consumers; no server or durable-state machinery is justified.

This adds no dependency, migration, cache, background process, or operating
policy. Its lifecycle cost is bounded to one shared renderer and focused panel
checks. Omitting that renderer would duplicate configuration authority; adding
a browser-only task registry, automatic retry, or override-survival machinery
would cost more while violating later-slice or best-effort boundaries.

### Size posture

The slice should stay under about 500 non-mechanical changed lines by reusing
one executor/configuration editor and the existing project binding and API
helpers. If the panel needs a second catalogue, task registry, or server
coordinator to fit the design, the implementation has exceeded this slice.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton and the already-built API, projection,
  project binding, and panel interaction seams.
- **Revise:** none; the narrow panel design needs no change to the reviewed
  baseline.
- **Reject:** `implementation/brainstorming` and `implementation/_drafts` as
  authority. No unresolved decision is imported from them.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Catalogue-driven presentation | Panel executor choices come from `GET /api/task-executors` and expose each returned `id`, `name`, `description`, `operating_mode`, `usage_examples`, `available_agent_configurations`, and `configuration_schema`. Configuration controls are generated only from that schema; `{}` renders none, `integer` uses its `minimum` and `default`, and `choice` uses its returned `choices` and `default`. Staffing descriptions remain read-only prose. | `implementation/milestones/tasks-2/skeleton.md:143-148,353`; catalogue `orchestrator/tasks.py:41-88,156-158`; route `orchestrator/service.py:4212-4216` | touch one shared panel presenter/editor; do-not-hard-code executor ids, `max_rounds`, `closure_policy`, defaults, choices, staffing seats, or a second catalogue |
| Direct panel order | The panel offers project-bound direct ordering and POSTs exactly `{task_executor, request, configuration?}` to `POST /api/tasks`; `request` contains exactly `{work_area:{project,work_area}, request, context, reference_documents, output_directory?}` and preserves reference order. The selected schema supplies configuration; a successful `201` displays the returned `task.id`. Project-less administrative ordering remains API-only. | `implementation/milestones/tasks-2/skeleton.md:18-22,335-343,351-352,360`; validators `orchestrator/tasks.py:161-196,207-251,470-495`; admission `orchestrator/service.py:3980-4050,4428-4430` | touch the project menu, one direct-order dialog, and existing form helpers; do-not-add a task kind, caller roots, Brainstorming target/seats, second prompt, auto-retry, or terminal-result wait |
| Independent producer controls | Every projected slice shows `draft_slice_note` and `implement` separately from `summary.slices[*].producer_task_executor`. A save POSTs exactly one `{task_kind, task_executor, configuration?}` to `POST /api/runs/<id>/slices/<slice-id>/producer`; only exact task kinds `draft_slice_note` and `implement` are offered. Confirmed display values come only from that response's two-key map or a later run summary. | `implementation/milestones/tasks-2/skeleton.md:148-169,336,350,360`; projection `orchestrator/state.py:2653-2666`; write contract `orchestrator/tasks.py:377-467`; route `orchestrator/service.py:4572-4594` | touch slice headers and one reused producer dialog; do-not-bulk-write, infer routing, cross-freeze, or offer skeleton/review/fixer selectors |
| Refusal and retry posture | The panel surfaces service error text unchanged. Relevant task tokens remain `invalid_task_request`, `unknown_task_executor`, `task_unavailable`, `task_selection_frozen`, and `task_update_busy`; producer freezing/busyness is decided by the service. Each explicit submit has at most one POST and no automatic retry. | `implementation/milestones/tasks-2/skeleton.md:360`; tokens `orchestrator/tasks.py:17-25`; service mapping `orchestrator/service.py:2724-2748`; panel API helper `orchestrator/static/panel.html:2411-2419` | touch in-dialog pending/error/accepted states; do-not-predict durable state, translate refusal tokens, synthesize admission, or retry a lost response |
| Best-effort view and override lifetime | The panel renders the latest successful catalogue/run payload it has. A changed replacement plan may discard every earlier producer write; the new plan is the notice. An exact no-op replacement preserves authority. No panel state, identity, lineage, notice, pause, acknowledgement window, or eventual/freshness claim is added. | `implementation/milestones/tasks-2/skeleton.md:143-169,205-210,350`; existing refresh/stale behavior `orchestrator/static/panel.html:2719-2733,3665-3679,4006-4017` | touch only transient form state and refreshed rendering; do-not-persist choices in browser/service UI state, replay writes, compare row lineage, or add notifications |
| Slice boundary | Slice 8 adds ordering and prospective selection only. Task records, results, accounting, internal calls, and activity chips remain Slice 9; existing standalone Brainstorming sessions and milestone execution remain unchanged. | `implementation/milestones/tasks-2/skeleton.md:212-232,336-343`; current project menu/session surface `orchestrator/static/panel.html:2244-2280`; current task reads `orchestrator/service.py:4217-4229` | touch `orchestrator/static/panel.html` and focused panel tests; do-not-change task/producer service semantics, state, execution adapters, session forms, unit history, or additional repositories |
| Verification | Focused panel checks pin one shared catalogue renderer, schema-derived controls, the exact project-bound direct body and single POST, accepted-id/error display, two separately written producer kinds, and absence of task chips/automatic retries. Existing API tests remain the behavioral authority for catalogue parity, admission, route errors, independent writes, defaults, freezing, busy refusal, and successors. Final closure remains `python3 -m unittest discover -s orchestrator/tests -t .`. | `implementation/milestones/tasks-2/skeleton.md:363`; existing panel contract checks `orchestrator/tests/test_service_api.py:124-220`; task API proof `orchestrator/tests/test_task_api.py:116-222,347-394`; producer proof `orchestrator/tests/test_producer_selection.py:300-378,889-977`; suite `orchestrator/README.md:522-532` | touch one focused panel test surface and retain lower-level suites; do-not-add a second test-only catalogue, browser dependency, narrower final suite, or Slice 9 chip assertions |

### Verification Contract

Focused panel checks must prove these observable cases:

1. a synthetic catalogue renders every self-description field and derives empty,
   integer, and choice configuration controls without named executor/configuration
   constants in the task UI;
2. a project/work-area order preserves request/context text, ordered references,
   optional destination, and schema-selected configuration in one `POST /api/tasks`,
   then displays the returned id or the exact refusal without retry;
3. a run summary renders both producer kinds for every slice and editing one
   emits one exact producer POST, then displays only the returned or later-read
   two-key map;
4. `task_selection_frozen`, `task_update_busy`, invalid, unknown, and unavailable
   responses keep the last confirmed view and remain visible; and
5. no task list, result polling, or task chip enters this slice.

The focused implementation command is
`python3 -m unittest orchestrator.tests.test_task_panel`. Lower-level
`orchestrator.tests.test_task_api`,
`orchestrator.tests.test_producer_selection`, and
`orchestrator.tests.test_service_api` remain authoritative beneath it. Final
closure runs exactly `python3 -m unittest discover -s orchestrator/tests -t .`.

Authorities: `implementation/milestones/tasks-2/skeleton.md:325-363`;
`orchestrator/tasks.py:41-88,156-304,377-529`;
`orchestrator/service.py:2724-2748,3980-4050,4212-4229,4428-4430,4572-4594`;
`orchestrator/state.py:2653-2666`.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These five entries are the slice-scoped remainder; enforceability is answered
again for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified touched:** the shared panel page's project menu, project/work-area binding, modal/form/error helpers, run-detail slice rendering, and refresh path consume the existing catalogue, direct-order, run-summary, and producer APIs. **Verified untouched:** task admission/records/executors, milestone scheduling, standalone Brainstorming session creation, unit history/chips, review/fix/seal paths, and all additional roots. | `orchestrator/static/panel.html:2244-2280,2411-2419,2719-2740,3665-4017,5366-5451,5812-5817`; `orchestrator/service.py:3980-4050,4212-4229,4428-4430,4572-4594`; boundary `implementation/milestones/tasks-2/skeleton.md:325-343` |
| pinned_facts | The hard table pins one API-owned catalogue and schema renderer; the exact project-bound direct body and single-submit acknowledgement; two visible, independently written producer kinds; exact refusal/no-retry posture; replacement-plan and stale-view best effort; the Slice 9 boundary; and the focused/full verification commands. | `implementation/milestones/tasks-2/skeleton.md:143-169,205-232,325-363`; `orchestrator/tasks.py:17-25,41-88,161-304,377-495`; `orchestrator/service.py:4212-4229,4428-4430,4572-4594` |
| verification | The new focused panel module pins catalogue-derived presentation, direct form serialization and acknowledgement/refusal, independent producer serialization, and absence of auto-retry/chips. Existing task API, producer selection, served-panel, and full-discovery suites retain semantic coverage underneath. | `implementation/milestones/tasks-2/skeleton.md:336,360,363`; `orchestrator/tests/test_task_api.py:116-222,347-394`; `orchestrator/tests/test_producer_selection.py:300-378,889-977`; `orchestrator/tests/test_service_api.py:124-220`; `orchestrator/README.md:522-532` |
| reuse_posture | **Affected party/harm:** project members lack direct panel ordering and operators lack visible independent producer controls; wrong selection is prospective and reversible, while a retried lost direct order can duplicate effects. **Checked/reused:** shared catalogue/schema, direct access/admission route, effective summary, producer write/refusals, project/work-area binding, ordered-reference pattern, modal isolation, escaping/error helper, and refresh. **Cheapest sufficient option:** one catalogue-driven presenter/editor reused by one task form and one producer dialog. **Remaining machinery/consumer:** panel-only controls and focused checks, consumed by operators. **Lifecycle:** no dependency, migration, cache, server change, registry, scheduler, retry, or notice; omission leaves required panel actions unavailable, while stronger machinery violates best-effort and Slice 9 boundaries. | `orchestrator/tasks.py:156-304,377-495`; `orchestrator/service.py:2724-2748,3980-4050`; `orchestrator/static/panel.html:2244-2280,2411-2419,5366-5451,5812-5817`; authority `implementation/milestones/tasks-2/skeleton.md:234-306,336,360-363` |
| enforceability | **Catalogue/configuration:** the shared catalogue response plus closed schema validator are the only accepted values; the panel renderer consumes those fields. **Direct order/access:** project handles are resolved and authorized before common admission, which validates configuration and destination. **Producer independence/freezing/busy:** effective summary exposes both keys; the closed task-kind write, exclusive mutation, and admission-state check accept or refuse one key. **Acknowledgement/error:** existing JSON helper accepts only `ok:true` and otherwise surfaces the service token; submit state prevents a client-side duplicate while in flight. **Replacement/freshness:** current summary and poll/stale guards can show only observed state, so override survival, timely refresh, and delivery remain best-effort. No mechanism proves response delivery, eventual completion, effect placement, rollback, or chip cardinality here, so this note promises none. | `orchestrator/tasks.py:156-304,377-529`; `orchestrator/service.py:2724-2748,3980-4050,4212-4229,4428-4430,4572-4594`; `orchestrator/state.py:2653-2666`; `orchestrator/static/panel.html:2411-2419,2719-2733,3665-3679,4006-4017`; bounded authority `implementation/milestones/tasks-2/skeleton.md:143-210,350-363` |
