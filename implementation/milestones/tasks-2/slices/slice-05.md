# Slice 05 — Slice producer planning and override

## Register 1 — INTENT (lay language)

### What this slice builds

This slice lets a planner and operator choose two producers independently for
each slice: one to draft the slice note and one to implement the slice. A choice
is visible before work starts. Existing and partially completed runs that never
recorded either choice continue to use the familiar single Worker by default.
The planner sees the same executor catalogue that later validates the choices.

The operator can replace either future choice without disturbing the other. If
the matching production task has already been ordered, that task keeps the
choice it was given. A later eligible attempt may use a newly visible choice,
but history is never rewritten.

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
- **Strict — prospective write and freeze:** a successful operator write changes
  only the named future choice. The write and task admission have one observable
  winner: an accepted write governs the later order, while an already ordered
  matching task retains its frozen choice and causes the write to be refused.
  Ordering one production kind does not freeze the other.
- **Strict — history:** changing a prospective choice never changes a prior
  task's id, order, configuration, result, accounting, or history. A successor,
  when milestone law permits one, receives a new order from the then-visible
  choice.
- **Strict — visibility:** a fresh run-detail read exposes both effective choices
  per slice, including independently resolved Worker defaults for old state.
  This is durable read-after-write visibility, not a panel-freshness promise.
- **Optimistic:** none. No client-side tentative selection or merge is added.
- **Eventual:** none. This slice promises neither task completion nor a polling
  deadline.
- **Best-effort:** none. Executor delivery and filesystem effects are outside
  this planning slice.

### Acceptance

- A slice-plan proposal presents two independent, catalogue-valid producer
  choices to its reviewer, and the effective structured projection carries both.
- The planner receives the shared executor definitions and usage guidance that
  govern later validation rather than a planning-only copy.
- Any source or durable plan with neither raw choice, or with only one, resolves
  every missing choice to Worker independently without migration.
- Changing the drafting choice leaves implementation unchanged, and changing
  implementation leaves drafting unchanged.
- Malformed choices are rejected without changing the previously visible plan.
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
- No data migration, backfill, schema bump, scheduler, queue, retry policy,
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
- A non-serialized write could report success after admission had already chosen
  another producer, or could be lost to a later run-state save.
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
and active-task association, the run's serialized mutation boundary, existing
operator-override persistence patterns, and the run-detail slice projection.
The cheapest sufficient option is to extend the existing plan with two values,
resolve raw omissions at read/admission time, and add one task-kind-scoped
write over the existing run surface. The driver, service projection, later
production scheduler, and later panel are the only consumers.

No migration, second catalogue, selector service, or new task ledger is
justified. The lifecycle cost is one small plan validator/resolver, one
prospective write, and focused compatibility/freeze tests. Omission leaves the
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
  Worker defaults, task-kind-scoped override, and immutable task history.
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
| Producer write | The exact route is `POST /api/runs/<id>/slices/<slice-id>/producer`. Its body has required `task_kind`, required `task_executor`, and optional `configuration`; `task_kind` is exactly `draft_slice_note` or `implement`. Missing, unsupported, or malformed request members/configuration return `invalid_task_request` (400); an unknown executor returns `unknown_task_executor` (400); a matching selection already frozen for its current order returns `task_selection_frozen` (409). A rejected request changes nothing. | `implementation/milestones/tasks-2/skeleton.md:141-151,313,330,340`; shared error/configuration authority `orchestrator/tasks.py:16-19,87-132,178-223`; existing run access and POST surface `orchestrator/service.py:3480-3491,4035-4233` | touch the authenticated run route and one selection write; do-not-add per-kind routes, a new auth model, raw operational errors, eager `task_unavailable`, or partial writes |
| Independent freeze and history | The write changes only the named still-prospective member. Admission freezes only that task's selected executor and resolved configuration; it does not freeze the sibling member. Any admitted or terminal predecessor remains value-immutable. A later eligible retry/Resume admits a successor from the then-visible member rather than reopening history. | `implementation/milestones/tasks-2/skeleton.md:42-52,141-151,313,330,336,338-340`; immutable record `orchestrator/tasks.py:353-391`; history guard `orchestrator/state.py:336-383`; current task-kind/unit link `orchestrator/driver.py:2561-2659,2780-2809` | touch the two production admission boundaries and task-kind-scoped freeze check; do-not-cross-freeze, mutate a task order/result, reuse a terminal id, or infer selection from a label |
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
4. the route returns the exact error/status pairs for an invalid task kind,
   malformed configuration, unknown TaskExecutor, and a frozen matching choice;
5. admission and override have a deterministic winner: an accepted pre-order
   write is the value later frozen, an admitted matching order is immutable, and
   ordering one kind does not prevent an override of the other;
6. a terminal predecessor stays unchanged when a later eligible successor
   selection is updated; this slice need not execute that successor; and
7. plan order/titles and Worker-only skeleton/review/fixer behavior remain
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
| reuse_posture | **Affected party/harm:** the operator otherwise cannot choose drafting and implementation independently, and a write racing admission can disagree with the frozen order. **Checked/reused:** current plan contract/prompt, one catalogue resolver, immutable task record, active task-kind/unit link, serialized state mutation, existing operator-override patterns, summary cache/projection, and run access. **Cheapest sufficient option:** two values on the existing plan, read/admission defaults for missing raw values, and one scoped write. **Remaining machinery/consumer:** only the resolver/write/freeze boundary needed by the driver, service, later scheduler, and later panel. **Lifecycle:** no migration, service process, scheduler, ledger, or copied schema; omission is costlier once work exists, while the Worker default and immutable history keep rollback proportional. | `orchestrator/contracts.py:210-232`; `orchestrator/tasks.py:135-252,353-391`; `orchestrator/state.py:336-405,649-705,2653-2658`; `orchestrator/driver.py:1212-1239,2561-2659`; operator-write precedents `orchestrator/service.py:2569-2586,2671-2715`; authority `implementation/milestones/tasks-2/skeleton.md:226-286,313,330` |
| enforceability | **Planning shape and absence:** the existing slice-plan validator can validate supplied members, and the existing summary projection can materialize both effective choices while leaving raw state unchanged; the skeleton review cycle judges whether the Markdown presents both, so no parser or version flag is needed. **One catalogue/configuration:** the detached shared catalogue supplies planning descriptions and its resolver validates the prospective value; common admission later freezes the resolved form. **Independent freeze/history:** the task-kind/unit context identifies the matching scheduling decision; one-way task admission/result plus the append-only history guard prevents rewriting. **Write ordering:** the existing exclusive run-mutation authority can serialize the accepted write against admission; accepted writes are projected through the existing summary/detail cache path. **Scope:** current kind constants and separate production boundaries let tests prove only note/implementation consume the map. No pinned mechanism supports eager availability, panel freshness, liveness, or rewriting an admitted task, so this note promises none. | plan validation `orchestrator/contracts.py:210-232,932-964`; review entry `orchestrator/driver.py:4903-4927,9710-9749`; catalogue/admission `orchestrator/tasks.py:33-80,135-252,353-391`; history and serialization `orchestrator/state.py:336-405`; matching context `orchestrator/driver.py:2561-2659`; projection `orchestrator/state.py:2653-2658`; detail cache `orchestrator/service.py:1060-1088,3188-3206`; bounded contract `implementation/milestones/tasks-2/skeleton.md:141-151,313,330,340` |
