# Slice 04 — Prompt-set binding and operator surface

## Register 1 — INTENT (lay language)

### What this slice builds

This slice lets the person launching a milestone choose which named prompt set
the run will use. If no choice is supplied, the run binds to `default`. The
choice belongs to the run for its lifetime; later edits to that named set may
change the wording seen by later calls, but they do not change the run's chosen
name.

The service and panel also show the chosen name and the run's current slice
plan. The plan is shown in delivery order and is a view of the reviewed plan,
not a second place to author it. The prompt-set chooser lists names only: it
does not claim that a set is currently readable, preview fallback, or expose
prompt contents.

Older run state that predates this field continues to mean `default` during
this transitional slice without being rewritten. The later activation cut
refuses those old schemas; this slice adds no migration.

### Ownership and boundary

Owned here are the launch-time prompt-set choice, its durable run binding, the
read-only prompt-set name catalogue, the run-detail projection of that binding
and the current slice plan, and the corresponding launch/detail panel views.
Both API and command-line creation use the same binding rule.

This slice does not send a router prompt to a worker. It does not choose a
fallback rung at launch, edit prompt files, accept a plan change, or create a
new plan writer. The existing producer and material controls remain fully on
their legacy path until Slice 5 removes those controls and their reply
transport together.

### Guarantee posture

- **Strict — run binding.** Every new run records one syntactically valid
  `prompt_set` name. Omission records `default`; an invalid supplied value is
  refused before run state, registry entry, or autostart exists. The binding
  cannot be changed after creation.
- **Strict — attach and legacy meaning.** Attach adopts the stored binding and
  refuses a supplied replacement. A pre-binding state reads and projects as
  `default` without gaining a new field or event.
- **Strict per successful read — operator projection.** One summary read returns
  the requested binding and the current state-backed plan; plan array order
  remains delivery order. These read surfaces do not resolve prompt contents or
  write plan state.
- **Best-effort — catalogue and panel freshness.** Each catalogue request lists
  the bindable names visible then. The panel refreshes from service reads, but
  there is no notification, snapshot, monotonicity, or convergence promise
  across views.
- **Optimistic / eventual delivery — none.** This slice dispatches no worker,
  queues no update, and promises no prompt or plan delivery.

### Dependencies and consumers

Slice 1 supplies the service-home namespace, name grammar, total fallback, and
fresh-read posture. Slice 3 supplies the validated, configuration-free plan
projection and delivery order. Existing run creation, state summary, run-detail
API, and panel launch/pipeline views are the consumer seams extended here.

The first runtime consumer of the binding is Slice 5's author-call cutover.
Until that cutover, current workers, prompt traces, reply validation, and plan
mutation behavior remain unchanged.

### Non-goals

- No worker, reviewer, fixer, Brainstorming seat, or suite call uses the router.
- No prompt-set content read or write API, editor, clone, rename, deletion,
  health check, or fallback preview.
- No validation that a chosen set presently exists or is readable; that would
  defeat the already-authorized per-call fallback.
- No current-run rebinding, binding event, version, snapshot, cache, watcher,
  retry, migration, or schema-version bump.
- No canonical-plan extraction, anchoring, post-call comparison, acceptance,
  restoration, diff, wipe, or reconciliation beyond Slice 3's existing seams.
- No retirement, weakening, or projection-only conversion of the current
  producer/material routes, panel controls, or reply `slices` transport.
- No change to staffing, rigor, model routing, standalone orders, or any
  granted read-only repository.

### Acceptance and size

Acceptance is the focused contract below. It proves explicit and default
bindings across API and CLI creation, refusal without effects, attach behavior,
byte-stable legacy defaulting, a names-only catalogue, exact service projection,
delivery-order panel rendering, and the absence of any prompt resolution or new
plan writer. Existing prompt-set and canonical-plan tests keep fallback and plan
authority unchanged; existing task-control tests prove Slice 5 work has not
been pulled forward.

The implementation is expected to remain below about 500 non-mechanical
changed lines. The cheapest cut extends existing creation, summary, catalogue,
and panel seams and adds one table-driven focused module; no new service or
state subsystem is justified.

### Risks

The material risks are storing a resolved fallback name instead of the requested
binding, rejecting a missing but syntactically valid name at launch, silently
rebinding an attached run, materializing compatibility state, presenting a
catalogue name as a health verdict, sorting the plan by id instead of delivery
order, or partially disabling legacy controls before their Slice 5 cutover.
Tests separate requested names from available/readable sets, compare legacy
bytes, use non-numeric plan order, and keep the existing control tests green.

### Reuse Posture

Operators and later prompt consumers are affected. A wrong binding can give a
worker the wrong instructions and waste an irreversible call; before Slice 5,
exposure is limited to a visibly wrong stored choice and a run can be relaunched.
The reviewed skeleton and original goal establish the outcome.

This workspace, its dependencies, and every granted read-only root were checked;
no second prompt-set binding or plan-projection system is available to reuse.
Reused are the prompt store's name and fallback rules, the existing atomic run
state and creation boundary, the existing run summary/detail routes, the panel's
catalogue/launch patterns, and Slice 3's state projection. The cheapest
sufficient option is one immutable string in run state, one names-only read,
and extensions to the existing launch and detail views. Resolving or validating
set contents at launch is both costlier and contrary to per-call fallback.

The only new machinery is the small catalogue read and binding validation/
projection consumed by the panel now and by routed calls later. Lifecycle cost
is one directory-name read when a chooser opens and one string per run. A
second store, event stream, edit API, health model, or migration would cost more
to build, operate, and review than the reversible pre-cutover harm warrants.

### Planning-context disposition

**Adopts** the reviewed skeleton and accepted amendment B1. **Uses** the original
goal only for the launch default, served-only boundary, and operator visibility
that the skeleton leaves concise. **Revises** the goal's permanent legacy-resume
promise exactly as B1 requires: missing binding means `default` only until the
schema activation refuses old runs. **Rejects** older brainstorming and
`_drafts` material as implementation authority.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Run binding | The public and durable field is `prompt_set`, a top-level run-state string matching `^[A-Za-z0-9_-]+$`. `POST /api/runs` and `orchestrator init --prompt-set` bind the supplied name; omission binds `default`. A syntactically valid name is accepted even when absent or currently unreadable, because fallback occurs per physical call. The binding is write-once and adds no event. | `implementation/milestones/prompt-router/skeleton.md:49-53,96-101,124,145`; `implementation/milestones/prompt-router/goal.md:60-85`; name/default seam `orchestrator/prompt_sets.py:24-26,62-86`; creation seams `orchestrator/service.py:2301-2516`, `orchestrator/driver.py:12801-12925,13170-13180` | touch state creation/history guard, the two launch adapters, and focused tests; do-not-resolve a set at launch, bind the fallback rung, add a setter/event, or mutate prompt files |
| Prompt-set catalogue | `GET /api/prompt-sets` returns an object with exactly `ok` and `prompt_sets`: `ok` is `true`; `prompt_sets` contains unique bindable names with `default` first and all other currently present valid directory names in lexical order. It is authenticated, read-only, name-only, and does not parse or expose documents, health, provenance, or fallback. | operator surface `implementation/milestones/prompt-router/skeleton.md:49-53,124`; storage/freshness `implementation/milestones/prompt-router/skeleton.md:96-101,145`; existing read-catalogue seam `orchestrator/service.py:2071-2077,4663-4676`; store/name seam `orchestrator/prompt_sets.py:24-26,62-86` | touch one store listing, one GET adapter, and the launch chooser; do-not-add prompt CRUD, content serving, a validity snapshot, cache, or notification |
| Launch refusal and attach | A supplied invalid `prompt_set` returns HTTP 400 before state, registry, or autostart effects. Attach refuses the key even when its value is `null`; without it, attach adopts the stored binding. A state with no binding reads and projects as `default` without a write, event, migration, or schema bump. | binding/default `implementation/milestones/prompt-router/skeleton.md:124`; activation `implementation/milestones/prompt-router/skeleton.md:133,153`; accepted amendment B1, activation paragraph; current pre-effect validation/attach boundary `orchestrator/service.py:2301-2375,2444-2516`; atomic creation `orchestrator/driver.py:12909-12935` | touch launch validation, the compatibility reader, summary, and append-only guard; do-not-rewrite attached/legacy state or activate the new schema |
| Operator projection | `GET /api/runs/<id>` exposes the requested name as `summary.prompt_set` and the state-backed plan as `summary.slices`. For a canonical projection, every slice retains `id`, `title`, `intent`, optional `material`, and exactly the two configuration-free producer objects; response and panel preserve array delivery order rather than sorting by id. The panel shows the prompt-set binding and plan values without inventing a second plan source. | canonical projection `implementation/milestones/prompt-router/skeleton.md:69-80,118-136,143-144`; Slice 4 intent `implementation/milestones/prompt-router/skeleton.md:124`; projection seam `orchestrator/canonical_plan.py:217-267,308-338`; summary/detail seams `orchestrator/state.py:2770-2781`, `orchestrator/service.py:1096-1119,3407-3424,4815-4822`; current panel order `orchestrator/static/panel.html:3822-3963` | touch summary/detail and their panel rendering; do-not-read the skeleton in the browser, reorder the array, project configuration, or create a plan-write route |
| Transitional control boundary | This slice adds no plan mutation path and does not reinterpret an existing write as projection-only. The current producer/material HTTP writers, state replay, panel editors, and reply `slices` transport remain together and successful until Slice 5 removes them in one cut. | accepted amendment B1, “Slice 05 installs…” paragraph; assigned order `implementation/milestones/prompt-router/skeleton.md:124-126,154`; current writers `orchestrator/service.py:2878-2935,5064-5113`; current editors `orchestrator/static/panel.html:5772-5969` | touch only the read projection and plan display; do-not-retire, hide, no-op, or otherwise partially cut over legacy controls |
| No runtime call cutover | Binding/list/detail operations invoke no prompt resolution, worker dispatch, reply validation, or prompt trace. Slice 5 is the first live author-call consumer; judgment and session consumers remain later. | assigned cutovers `implementation/milestones/prompt-router/skeleton.md:124-128`; current author builders `orchestrator/driver.py:7664-7714`; current fixer builder `orchestrator/driver.py:9974-10035`; exact trace seam `orchestrator/runners.py:1663-1676,1754-1757` | touch launch/state/service/panel surfaces only; do-not-move a physical call, change trace contents, or retire a current builder/validator |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_prompt_set_binding orchestrator.tests.test_prompt_sets orchestrator.tests.test_canonical_plan orchestrator.tests.test_state orchestrator.tests.test_run_init orchestrator.tests.test_service_api orchestrator.tests.test_task_panel`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| New runs bind one requested name without resolving it | new `test_new_run_binding_defaults_validates_and_never_resolves` | API and CLI creation persist an explicit valid name; omission persists `default`; a syntactically valid missing and malformed set still launch; a resolution spy is untouched; invalid type, blank, path-like, dotted, spaced, and Unicode names return 400 and leave no state, registry entry, or autostart call. | strict |
| Binding is stable across attach and legacy reads | new `test_attach_and_legacy_binding_are_read_only` | Attach with any `prompt_set` key, including null, is refused without change; bare attach preserves an explicit name. Removing the key from a fixture makes state/summary readers return `default`; a detail poll leaves exact bytes unchanged, and an unrelated state save preserves key absence. A later attempted binding mutation fails the history guard. | strict |
| The catalogue is deterministic but makes no health claim | new `test_prompt_set_catalogue_is_names_only_and_fresh` | The GET response has only `ok` and `prompt_sets`; `default` is first, valid stored names are unique/lexical, invalid entries are absent, and a malformed valid-name set remains listed. Adding/removing a name changes the next response without parsing or editing any member. | strict response / best-effort cross-read freshness |
| Run detail exposes one coherent read-only projection | new `test_run_detail_projects_binding_and_canonical_plan_in_delivery_order` | Detail returns `summary.prompt_set` and the exact canonical projection in non-numeric array order with intent/material and configuration-free producers; GET leaves state bytes unchanged and exposes no plan-authoring field or route. | strict per response |
| The panel selects and displays the same facts | new `test_panel_prompt_set_selector_and_plan_projection_are_server_driven` | The launch form loads `/api/prompt-sets`, defaults to `default`, posts one `prompt_set`, and the Binding/Pipeline views render `summary.prompt_set` and `summary.slices` in returned order, including intent, without copied name grammar, health claims, or a prompt-set editor. | strict shape / best-effort view freshness |
| Earlier boundaries and transitional controls stay intact | existing `orchestrator.tests.test_prompt_sets`, `orchestrator.tests.test_canonical_plan`, and `orchestrator.tests.test_task_panel` | Whole-set fallback/freshness, configuration-free canonical projection, current producer/material writes and control-specific assertions retain their reviewed results; no current worker prompt or trace assertion changes for this slice. | strict compatibility |

The repository's official full suite remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:544-546`). It belongs to the scheduled checkpoint, not
this slice's focused implementation gate.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These are the slice-scoped remainder. Enforceability is answered again for the
facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified touched:** run-state creation/history/summary; CLI init; service `POST /api/runs`, new `GET /api/prompt-sets`, and existing run detail; the panel launch form, Binding view, and Pipeline order; focused state/service/panel tests. **Verified read-only dependency:** Slice 1's prompt-set store and Slice 3's projection. **Verified untouched:** current milestone/Brainstorming dispatch, validators, traces, staffing/model routing, standalone orders, and every granted external root. | state `orchestrator/state.py:133-178,274-333,2770-2781`; init `orchestrator/driver.py:12801-12925,13170-13180`; service `orchestrator/service.py:2301-2516,3407-3424,4656-4676,4815-4822,4995-5002`; panel `orchestrator/static/panel.html:601-674,3680-3963,5054-5120`; untouched dispatch `orchestrator/driver.py:7664-7714,9974-10035` |
| pinned_facts | The exact `prompt_set` field/name grammar/default and write-once binding; names-only `GET /api/prompt-sets`; 400 no-effect refusal and attach/legacy behavior; `summary.prompt_set` plus delivery-ordered `summary.slices`; the Slice 5 legacy-control boundary; and zero runtime-call cutover. | `implementation/milestones/prompt-router/skeleton.md:49-53,69-80,96-101,124-128,143-145,153-154`; launch intent `implementation/milestones/prompt-router/goal.md:60-91`; accepted amendment B1, Slice 05 and activation paragraphs |
| verification | The six checks above separate requested binding from stored/readable rungs; mutate every public name/input case; prove no-effect refusal, attach immutability, legacy byte stability, deterministic fresh catalogue listing, exact detail/panel projection and order, and unchanged earlier fallback, plan, and control behavior. The focused command names all touched modules; the official full suite remains the later checkpoint command. | verification table above; current fallback proof `orchestrator/tests/test_prompt_sets.py:207-265`; current anchor/projection proof `orchestrator/tests/test_canonical_plan.py:262-368`; current launch/detail proof `orchestrator/tests/test_service_api.py:497-645`; official suite `orchestrator/README.md:544-546` |
| reuse_posture | Affected parties are operators and later calls; a wrong name can waste a future call, while pre-cutover state/display errors are visible and relaunchable. Searches of this workspace, dependencies, and all granted roots found no parallel binding. Reused are the store grammar/fallback, atomic state/init, existing launch/detail and catalogue patterns, panel form/pipeline, and canonical projection. Cheapest sufficient is one state string, one names-only GET, and existing-view extensions; no resolution-at-launch, CRUD, health model, event, migration, or second store is justified. Remaining cost is one chooser directory read and one string per run. | store/fallback `orchestrator/prompt_sets.py:24-26,62-86,477-550`; atomic state/init `orchestrator/state.py:233-240,410-450`, `orchestrator/driver.py:12909-12935`; catalogue/launch/detail `orchestrator/service.py:2071-2077,2301-2516,3407-3424`; panel `orchestrator/static/panel.html:4298-4350,5054-5120`; projection `orchestrator/canonical_plan.py:217-267` |
| enforceability | Every asserted invariant has an expressible seam: store name validation; pre-effect launch validation and atomic creation; append-only state comparison for write-once binding; absent-key compatibility projection without mutation; names-only catalogue enumeration; atomic summary/detail reads; canonical projection and array order; and static/behavioral tests proving no dispatch and retained legacy controls. No set-health, cross-read consistency, notification, automatic convergence, prompt delivery, plan acceptance, or migration guarantee is asserted. | name/fallback `orchestrator/prompt_sets.py:62-86,531-550`; launch boundary `orchestrator/service.py:2301-2516`; state persistence `orchestrator/state.py:233-240,274-333,410-450`; projection `orchestrator/canonical_plan.py:217-267,308-338`, `orchestrator/state.py:2770-2781`; current controls `orchestrator/service.py:2878-2935,5064-5113` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Every new run has one valid, immutable requested binding and invalid input has no launch effects | The one stored-name grammar/default is at `orchestrator/prompt_sets.py:24-26,62-86`; service validation already precedes creation at `orchestrator/service.py:2301-2375`; state creation/claim is atomic at `orchestrator/state.py:410-450` and `orchestrator/driver.py:12909-12935`; the existing append-only comparison lives at `orchestrator/state.py:274-333`. | Exercise API and CLI defaults/explicit names, spy on resolution/autostart, mutate each invalid input, then try to change a persisted binding through an ordinary save. |
| Attach cannot rebind, and missing legacy binding means default without materialization | The attach path rejects launch-owned fields before adopting state at `orchestrator/service.py:2354-2395`; `default` is the single store constant at `orchestrator/prompt_sets.py:24-26`; state reads and atomic saves are at `orchestrator/state.py:233-240,435-450`. | Attach explicit and absent fixtures; compare the legacy file before and after summary/detail and an unrelated save, including key presence, events, and schema version. |
| The prompt-set catalogue is name-only, deterministic, and fresh per GET | The store root/name boundary is `orchestrator/prompt_sets.py:62-86`; the existing thin sorted catalogue adapter and GET shape are at `orchestrator/service.py:2071-2077,4663-4676`. | Mix valid, invalid, missing, and malformed directories; assert exact response keys/order, no document reads or writes, then change names and repeat the GET. |
| Detail and panel expose the binding and canonical plan without reordering or authoring it | Canonical projection is detached and configuration-free at `orchestrator/canonical_plan.py:217-267`; accepted projection lands in state at `orchestrator/canonical_plan.py:308-338`; summary/detail read through `orchestrator/state.py:2770-2781` and `orchestrator/service.py:1096-1119,3407-3424`; the panel consumes that array at `orchestrator/static/panel.html:3822-3963`. | Anchor a deliberately non-numeric plan, fetch detail, render the panel, and compare every displayed/projected field and order while asserting unchanged state bytes and no new plan endpoint. |
| No current physical call or legacy plan-control path moves in this slice | Current author/fixer prompts are still built at `orchestrator/driver.py:7664-7714,9974-10035`; exact recording is `orchestrator/runners.py:1663-1676,1754-1757`; legacy writers/editors are `orchestrator/service.py:2878-2935,5064-5113` and `orchestrator/static/panel.html:5772-5969`. | Resolution/runner spies stay untouched throughout launch/list/detail tests, current prompt/trace tests stay byte-compatible, and existing producer/material API/panel tests remain green. |

There is deliberately no enforcement row for prompt-set readability, fallback
visibility at launch, cross-read catalogue consistency, panel notification,
worker delivery, plan-change acceptance, legacy migration, or activation: this
slice asserts none of them.
