# Slice 05 — Slice producer planning and override

## Register 1 — INTENT (lay language)

### What this slice builds

This slice lets a planner and operator choose two producers independently for
each slice: one to draft the slice note and one to implement the slice. A choice
is visible before work starts. Existing and partially completed runs that never
recorded either choice continue to use the familiar single Worker by default.
The planner sees the same executor catalogue that later validates the choices.

The operator can replace either future choice without disturbing the other
while that plan remains installed. A changed replacement plan is complete:
prior overrides disappear, its proposals and Worker defaults become visible,
and the operator may choose again. An ordered task keeps its frozen choice.

### Ownership and boundary

This slice owns the planning shape, independent default resolution, the
operator's pre-order write, and the run projection that makes both effective
choices visible. It also owns the boundary that decides whether a choice is
still prospective or is already frozen into an order.

It does not make Brainstorming run a milestone production step. It does not add
standalone task ordering, panel controls, or task chips. Those remain separate
later slices. Reviews, fixers, and skeleton drafting remain Worker work and do
not inherit either slice-producer choice.

### Dependencies and consumers

This slice depends on the shared TaskExecutor catalogue and configuration rules,
the durable immutable task order, and the default Worker task cutover. It does
not depend on the Brainstorming production adapter.

The immediate consumers are initial and legitimately updated milestone plans,
the two slice-production scheduling boundaries, run-detail projection, and the
authenticated operator write. The current panel continues to ignore producer
metadata; a later slice will render controls from the projection established
here.

### Guarantee posture

- **Strict — independent planning:** the planner-facing plan and effective run
  projection state both prospective producer choices. Each supplied choice is
  validated independently against the shared catalogue. Any absent raw choice
  resolves to Worker without rewriting its source state.
- **Strict — one catalogue:** planner-facing descriptions, examples, and
  configuration choices come from the shared TaskExecutor catalogue; planning
  adds no copied source of executor policy.
- **Best-effort — current-plan override:** an accepted write changes only the
  named future choice while the current plan remains installed. A busy run may
  refuse it. Any changed replacement plan discards all earlier overrides and
  installs only its proposals and Worker defaults; an exact no-op does neither.
  A continuous driver briefly tolerates a lock handoff only when the resulting
  state is unchanged or exactly an adoptable producer-only delta; unrelated
  durable contention is still refused. No slice identity, lineage, retirement
  record, pause, or notice is added.
- **Strict — admission freeze:** an ordered matching task retains its frozen
  choice and causes a later write to be refused. Ordering one production kind
  does not freeze the other.
- **Strict — history:** changing a prospective choice never changes a prior
  task's id, order, configuration, result, accounting, or history. A successor,
  when milestone law permits one, receives a new order from the then-visible
  choice.
- **Best-effort — visibility:** a fresh successful run-detail read exposes both
  effective current-plan choices per slice. That plan is the only replacement
  notice; no response window or panel-freshness promise is added.
- **Optimistic:** none. No client-side tentative selection or merge is added.
- **Eventual:** none. This slice promises neither task completion nor a polling
  deadline.
- **Best-effort:** producer overrides and their projection are convenience
  bookkeeping. Their loss changes no acceptance, seal, or task result.

### Acceptance

- A slice-plan proposal presents two independent, catalogue-valid producer
  choices to its reviewer, and the effective structured projection carries both.
- The planner receives the shared executor definitions and usage guidance that
  govern later validation rather than a planning-only copy.
- Any source or durable plan with neither raw choice, or with only one, resolves
  every missing choice to Worker independently without migration.
- Changing the drafting choice leaves implementation unchanged, and changing
  implementation leaves drafting unchanged.
- A changed replacement plan installs its own pair and makes every earlier
  override inactive; an equal response is a true no-op. Review context includes
  only writes after the latest installed replacement.
- Malformed choices are rejected without changing the previously visible plan.
- An accepted producer write at the between-step lock handoff is adopted by the
  live continuous driver without stopping it; unrelated lock contention remains
  a refusal before work dispatch when it leaves another durable state change.
- Once a matching task is admitted, its order remains unchanged. The other
  producer choice stays eligible for its own future order.
- When milestone law permits a successor after terminal failure, a later
  override is prospective; it does not reopen or mutate the failed task.
- Run detail exposes the effective pair for every slice. The existing unit order,
  titles, review/fix flow, and default Worker behavior remain unchanged.
- Focused tests and the repository's complete suite pass once each at their
  respective gates.

### Non-goals

- No Brainstorming production scheduling, waiting, result consumption, or mixed
  producer end-to-end flow.
- No standalone task API, task list/inspection API, panel selector, or task chip.
- No selectable executor for skeleton drafting, review, delta review, or fixing.
- No second TaskExecutor catalogue, copied configuration defaults, hidden
  runtime routing, eager staffing resolution, or availability probe at selection
  time.
- No data migration, backfill, schema bump, scheduler, queue, task retry policy,
  liveness rule, or parallel selection ledger.
- No mutation or reopening of an admitted or terminal task, and no change to
  task accounting.
- No write outside the primary workspace; the additional project roots remain
  read-only inputs.

### Risks

- Treating the pair as one choice would let ordering a draft accidentally freeze
  implementation, or vice versa.
- Failing to present and project both effective choices would hide the independent
  planning decision even though raw omissions have a valid Worker default.
- Resolving omitted executor defaults while the choice is merely prospective
  would freeze catalogue policy too early and duplicate configuration authority.
- Even a non-blocking service write can win the short lock handoff between
  driver steps. The continuous driver must adopt the resulting producer-only
  delta without turning unrelated durable contention into permission to
  proceed.
- Replaying an old override onto a replacement plan can attach it to an
  unrelated row; replacement must install its own proposal without replay.
- Replacing a prior task's order instead of admitting a successor would erase
  the historical decision and misattribute its result and accounting.
- Rendering controls now would duplicate the later panel slice and couple this
  contract to a temporary UI.

### Reuse Posture

The affected party is the operator choosing how a slice is produced. Without
independent choices, selecting discussion for note drafting can unintentionally
change implementation as well; without a pre-order boundary, the visible choice
can disagree with the admitted order. Both harms are immediately visible but
become expensive to repair once work and accounting exist. The reviewed design
independently requires two prospective choices and immutable admitted history.

Checked and reused are the current initial/design-update slice-plan output and
validation path, the
single TaskExecutor catalogue and configuration resolver, the durable task order
and active-task association, the run's non-blocking mutation boundary, existing
plan-update and override events, and the run-detail slice projection.
The cheapest sufficient option is to extend the existing plan with two values,
resolve raw omissions at read/admission time, and add one task-kind-scoped
write over the existing run surface. The continuous driver reuses its existing
producer-delta validator after a bounded local lock handoff; it proceeds only
when that exact delta appears. The driver, service projection, later production
scheduler, and later panel are the only consumers.

No migration, second catalogue, selector service, or new task ledger is
justified. The lifecycle cost is one small plan validator/resolver, one
best-effort prospective write, and one bounded run-side handoff using the same
delta validation. Existing event order excludes writes before the latest
`slices_updated`; no identity, retirement event, survival rule, or notice is
justified. Omission leaves the
operator unable to make the independently required choice; stronger machinery
would add operating and migration cost without improving the authorized
boundary. The change remains reversible because Worker is the independent
default and all admitted task history stays intact.

### Size posture

The slice is expected to stay under roughly 500 non-mechanical changed lines.
Mechanical updates to existing slice-plan fixtures may be broad but do not count
toward that aim.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's two independent prospective selections,
  Worker defaults, current-plan-scoped override, and immutable admitted-task
  history.
- **Revise:** the original single-producer planning language is applied as two
  choices under the accepted amendment; every absent raw member uses the same
  read/admission Worker default without migration.
- **Reject:** runtime prompt/raw material as design authority, a second selector
  or catalogue, eager availability-based routing, and any panel or production
  behavior assigned to a later slice.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Producer plan shape | Every effective slice plan carries `producer_task_executor`, a map with exactly `draft_slice_note` and `implement`. Each effective member has required `task_executor` and optional `configuration`; every supplied executor-specific configuration is validated by the one TaskExecutor catalogue. The planner receives that same catalogue's descriptions, usage examples, and configuration schema. An absent raw map or member resolves independently to `worker` without migration or byte backfill. | `implementation/milestones/tasks-2/skeleton.md:24-29,103-108,141-151,313,330,333,337,339`; current plan contract `orchestrator/contracts.py:210-232,932-964`; shared catalogue/configuration authority `orchestrator/tasks.py:33-80,135-223` | touch planner catalogue input/instructions, output validation, plan resolution, and compatibility projection; do-not-copy executor descriptions/schemas/defaults, require migration, reject an absent default, or leave an effective member hidden |
| Prospective configuration | Selection-time omission of `configuration` remains omission; validation proves the supplied value is legal, while task admission later freezes the resolved configuration in that task's order. Selection does not resolve staffing or executable availability. | `implementation/milestones/tasks-2/skeleton.md:42-48,93-102,141-151,330-337,340`; `orchestrator/tasks.py:178-252,353-374` | touch shared configuration validation and later order construction; do-not-freeze defaults early, probe staffing/availability, or use `available_agent_configurations` as a selector |
| Producer write | The exact route is `POST /api/runs/<id>/slices/<slice-id>/producer`. Its body has required `task_kind`, required `task_executor`, and optional `configuration`; `task_kind` is exactly `draft_slice_note` or `implement`. Malformed input and unknown executors retain their existing 400 errors; a frozen matching selection returns `task_selection_frozen` (409); and a busy run returns `task_update_busy` (409) rather than queueing the bookkeeping write. A rejected request changes nothing. At a between-step handoff, the continuous driver briefly reacquires and proceeds only if state is unchanged or the existing validator recognizes the complete producer-only delta; other durable contention remains refused. | accepted amendment B8; shared error/configuration authority `orchestrator/tasks.py`; existing run access and POST surface `orchestrator/service.py` | touch one authenticated non-blocking selection write and the existing producer-delta catch-up; do-not-add per-kind routes, a new auth model, a queued service write/supervisor, eager availability, or partial writes |
| Current-plan scope, freeze, and history | A write changes only its named prospective member while that plan remains installed. A changed replacement installs its proposal/default state and cuts off all earlier writes; event sequence after the latest existing `slices_updated` identifies active review overrides without another marker. An equal response is a no-op. Admission freezes only that task and admitted history remains immutable. | accepted amendment B8; immutable record `orchestrator/tasks.py`; history guard `orchestrator/state.py`; current task-kind/unit link `orchestrator/driver.py` | touch replacement installation, review projection, and task-kind freeze; do-not-replay overrides, add row identity/lineage, emit retirement notices, cross-freeze, or mutate admitted history |
| Effective visibility | Planner instructions present both proposals. Run detail projects both effective members for every slice, resolving raw omissions independently, while plan order and identity remain the existing `id`/`title` sequence. Slice 5 does not render or edit panel controls. | `implementation/milestones/tasks-2/skeleton.md:24-29,141-151,305-323,330`; planner seam `orchestrator/prompts.py:1377-1412`; plan consumers `orchestrator/state.py:649-705,2653-2658`; detail read `orchestrator/service.py:1060-1088,3188-3206`; current panel consumer `orchestrator/static/panel.html:3834-3838,3923-3955` | touch planner contract, effective slice projection, and detail cache invalidation; do-not-change execution order, parse the Markdown as state, or add the Slice 8 panel UI here |
| Slice boundary | Only `draft_slice_note` and `implement` use this producer map. `draft_skeleton`, `review_round`, `delta_review`, and `fix_findings` remain Worker tasks. Brainstorming milestone execution is Slice 6; standalone task routes are Slice 7; controls and chips are Slices 8-9; broad successor/cardinality compatibility is Slice 10. | `implementation/milestones/tasks-2/skeleton.md:204-224,305-323,338,342-343`; current kind boundaries `orchestrator/contracts.py:52-100`; current production points `orchestrator/driver.py:6142-6244` | touch planning, the two future production selections, focused tests, and the producer route; do-not-select review/fixer/skeleton executors or pull later scheduling, standalone API, panel, chip, or broad conformance work forward |

### Verification Contract

Focused tests in `orchestrator/tests/test_producer_selection.py` must prove:

1. the skeleton-planning instruction receives the shared catalogue and presents
   both choices; supplied maps reject extra members and malformed executor
   configurations, and their effective projection has exactly the two named
   members;
2. any plan with an absent map, and partial state with either absent member,
   projects independent Worker defaults without rewriting stored bytes;
3. a valid producer POST changes only its named member and is visible on the
   next run-detail read, while every rejected body leaves both members unchanged;
4. the route returns the exact error/status pairs for invalid input, an unknown
   TaskExecutor, a frozen matching choice, and a busy run; an accepted write at
   the lock handoff is adopted without stopping the continuous driver;
5. an admitted matching order is immutable, and ordering one kind does not
   prevent a later override of the other;
6. a terminal predecessor stays unchanged when a later eligible successor
   selection is updated; this slice need not execute that successor; and
7. a changed plan replacement drops every earlier override, excludes those
   writes from review context, and uses only its proposal/default values; an
   equal response preserves current authority without another event; a
   replacement event stays immutable while an already-loaded driver catches up
   a later accepted override; and
8. plan order/titles and Worker-only skeleton/review/fixer behavior remain
   unchanged, with no panel-control or availability-selection behavior.

The focused command is
`python3 -m unittest orchestrator.tests.test_producer_selection`.
Existing plan-contract, durable-task, Worker-cutover, state-summary, and service
tests remain lower-level evidence. Final closure runs exactly
`python3 -m unittest discover -s orchestrator/tests -t .`.

Authorities: `implementation/milestones/tasks-2/skeleton.md:313,320-323,330,340,343`;
validation/order precedents `orchestrator/tests/test_tasks.py:190-313,409-480`;
Worker freeze precedents `orchestrator/tests/test_worker_tasks.py:516-660`;
summary/service precedents `orchestrator/tests/test_state.py:2250-2303` and
`orchestrator/tests/test_service_api.py:598-635,1202-1279`; full suite
`orchestrator/README.md:522-532`.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These five entries are the slice-scoped remainder; enforceability is answered
again for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified immediate consumers:** the skeleton planner, shared TaskExecutor catalogue, and shared slice-plan validator used by initial and authorized design-update outputs; durable per-slice plan/unit enumeration; the draft-note and implementation admission boundaries; run-detail slice projection/cache; and the authenticated run POST surface. **Verified untouched:** current panel rendering, review/fixer/skeleton producer selection, standalone task routes, and task chips remain later or unchanged. | `orchestrator/prompts.py:1377-1412`; `orchestrator/tasks.py:33-80,135-223`; `orchestrator/contracts.py:210-232,932-964,1064-1072`; `orchestrator/state.py:649-705,2653-2658`; `orchestrator/driver.py:2561-2659,4143-4194,6142-6244`; `orchestrator/service.py:1060-1088,3188-3206,3480-3491,4035-4233`; `orchestrator/static/panel.html:3834-3838,3923-3955`; boundary `implementation/milestones/tasks-2/skeleton.md:305-323` |
| pinned_facts | The hard table pins the exact two-key plan/value shapes; independent Worker compatibility defaults; catalogue-owned prospective configuration; the exact producer route/body/error vocabulary; per-kind write/freeze and predecessor immutability; effective run-detail visibility; and the boundary excluding review/fixer/skeleton selection and later slices. | `implementation/milestones/tasks-2/skeleton.md:141-151,305-343`; `implementation/milestones/tasks-2/slices/slice-05.md:Pinned-Facts Table` |
| verification | One focused module pins supplied-plan validation, absent/partial-plan defaults without migration, exact route failures with no mutation, independent writes, admission/write ordering, immutable predecessor orders, effective detail projection, unchanged plan order, and later-slice exclusions. Existing task, Worker, state, and service suites remain lower-level proof; repository discovery is the final gate. | `implementation/milestones/tasks-2/skeleton.md:313,320-323,343`; `orchestrator/tests/test_tasks.py:190-313,409-480`; `orchestrator/tests/test_worker_tasks.py:516-660`; `orchestrator/tests/test_state.py:2250-2303`; `orchestrator/tests/test_service_api.py:598-635`; `orchestrator/README.md:522-532` |
| reuse_posture | **Affected party/harm:** stale override replay can select the wrong producer after replacement, while an accepted write at the lock handoff can otherwise stop the one-shot driver. **Checked/reused:** current plan contract, catalogue resolver, immutable task record, non-blocking lock, existing producer-delta validator, `slices_updated`/override order, summary projection, and run access. **Cheapest sufficient option:** refuse busy writes, briefly reacquire only at a continuous-run handoff, proceed only for the already-valid producer delta, install replacement values directly, detach the existing replacement-event payload from the live plan object, and project only writes after the latest plan update. **Lifecycle:** one bounded local handoff and one defensive copy at installation; no slice identity, retirement event, acknowledgement, pause, supervisor, migration, scheduler, or ledger. Producer bookkeeping remains best-effort. | accepted amendment B8; `orchestrator/tasks.py`; `orchestrator/driver.py`; `orchestrator/service.py` |
| enforceability | Existing validators and summary projection expose the effective pair. Task-kind/unit context plus one-way admission keeps an admitted order immutable. The service lock refuses contention; a continuous driver that briefly loses the between-step handoff proceeds only if state is unchanged or the existing validator recognizes the resulting producer-only delta, so unrelated durable contention is still refused before dispatch. Replacement installs planner values directly, while existing event order makes only writes after the latest `slices_updated` active for review. No stable row identity, replay, retirement event, notification, pause, or liveness promise is authorized. | accepted amendment B8; `orchestrator/contracts.py`; `orchestrator/tasks.py`; `orchestrator/driver.py`; `orchestrator/service.py` |
