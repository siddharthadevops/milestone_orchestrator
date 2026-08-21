# Slice 01 — Rename `worker` to `agent_call`

## Register 1 — INTENT (lay language)

### What this slice builds

The orchestrator publishes a short catalogue of the ways work can be handed to
it. One of those entries is called "Worker" today, and the word has become
ambiguous: everything the orchestrator runs is a worker call, so a name that
means "one contracted call to an agent CLI" should say exactly that. This slice
renames that one catalogue entry to `agent_call`, with the display name "Agent
call", and changes nothing about what it does.

The rename is public. The catalogue an operator sees in the panel, the choice a
calling product sends over HTTP, the choice a planner writes for each slice, and
the value the orchestrator stores on a milestone order all say `agent_call`
afterwards. The panel and the planner prompt read the catalogue itself, so the
labels follow without anybody editing a label.

The one thing that must not break is the past. Work already recorded — orders
sitting in run state, including two that have not finished yet, and slice plans
that named the old choice, including this milestone's own plan — says `worker`
on disk. Those bytes are never rewritten. They are read as `agent_call`
instead: an old order still runs, an old plan still projects, a run summary
still renders. Going the other way, a caller sending the retired word to the
service as a *new* request is refused rather than quietly accepted, so the
retired spelling cannot re-enter through the front door.

This slice also leaves alone a word that merely looks the same. "Worker" is
still the ordinary English name for an LLM CLI call throughout the system —
worker incidents, worker stalls, worker-authored text, the recorded event names
for an interrupted or malformed call. None of that is the catalogue id, and
none of it is renamed here; renaming recorded event names would rewrite the
meaning of history for no benefit.

### Ownership and boundary

This slice owns exactly one vocabulary change and its compatibility rule: the
catalogue entry's id, display name and self-description; the projected default
producer choice; the value written onto a milestone order; what the two
service write bodies accept; and the read rule that turns a stored `worker`
into `agent_call` everywhere a stored value is projected or routed.

It owns no behaviour. Nothing about how a call is staffed, dispatched, stored,
resumed, or accounted changes. The entry's configuration stays empty; the
`role` key that this executor eventually carries belongs to a later slice and
must not appear here.

### Guarantee posture

- **Strict — catalogue and acceptance.** The catalogue's inventory, order,
  first-entry default, closed entry fields and empty configuration are
  deterministic. A retired id in a new service write body is refused with the
  existing unknown-executor classification before anything is stored.
- **Strict — read compatibility.** Every path that reads an already-stored
  executor value — a durable task order, a durable slice plan, a plan returned
  by an agent — yields `agent_call` and never raises for the retired spelling.
  Stored bytes are unchanged by reading them.
- **Best-effort — none added.** This slice introduces no new bookkeeping. The
  staffing snapshot frozen on a record keeps whatever posture it already has;
  this slice only changes which key a *new* record writes it under.
- **Optimistic / eventual — none.** There is no concurrency, replication, or
  convergence in this slice.

### Dependencies and consumers

This is the first slice of the milestone and depends on no earlier one. It
depends on the existing task catalogue, contract validation, durable run state
and standalone task store as they stand today.

Its consumers are the ones that already name this executor: the milestone
driver when it admits a production task, the standalone task host when it
routes a stored record to the right runtime, the service's task and
slice-producer write routes, the run summary's slice projection, the planner
prompt's catalogue block, and the panel's executor picker and producer labels.
Every later slice of this milestone inherits the new name; none of them
depends on this slice for anything else.

### Non-goals

- No staffing document, session, resolver, ladder, rigor, material, or rule.
- No `role` configuration key, no `staffing_session` field, no new route.
- No change to how any call is staffed, dispatched, resumed, or priced.
- No migration, rewrite, or deletion of stored records, plans, events, or
  sidecar files; no census of old runs.
- No rename of the generic "worker" concept: worker calls, worker incidents,
  worker stall configuration, recorded `worker_*` event names, and internal
  function names stay as they are.
- No second catalogue entry, no alias entry, no reordering, and no change to
  the entry's configuration schema.
- No edit to the granted read-only roots.

### Acceptance

The slice is accepted when focused tests prove all of the following. The
catalogue is still exactly two ordered entries whose first is `agent_call`,
carrying the display name, the closed field set, the usage-example limits and
an empty configuration; the projected default producer for both production task
kinds is `agent_call`; a milestone-admitted order carries `agent_call`; and the
service refuses `worker` in a new task order body and in a slice-producer write
body with the existing unknown-executor classification and status.

Compatibility is proven on the shapes that exist on this machine, not on
invented ones: a durable slice plan that stores the retired spelling projects
`agent_call` while its stored bytes stay byte-identical, and a durable task
order that stores it still routes and still executes.

The expected change is well under the roughly 500-line target: one catalogue
entry, one read rule, a handful of literal comparisons, and test updates. The
test-file updates are mechanical replacements of a literal and do not count
toward the target.

### Risks

- **Silent acceptance instead of refusal.** A read rule broad enough to cover
  stored values could also make the service accept the retired word on new
  requests, which the design forbids. The acceptance tests assert the refusal
  and the projection separately, so one cannot satisfy the other.
- **Compatibility applied too late.** The projection that completes a slice
  plan runs on every run summary; if the read rule is missed there, every
  affected run's summary raises instead of rendering. The compatibility test
  drives a real run over a stored old plan rather than calling the validator
  directly.
- **Over-reach into the generic word.** A blanket search-and-replace would hit
  recorded event names and stall configuration and would rewrite the meaning of
  stored history. The pinned table names those surfaces as do-not-touch.
- **In-flight plans naming the retired spelling.** A later agent could return a
  slice plan echoing the old word from the design table. Read normalization
  covers that case deliberately, so it degrades to the correct value rather
  than failing a run; the orchestrator driving this milestone runs from a
  separate checkout, so this slice cannot break the run that builds it.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Catalogue entry | The catalogue stays exactly two ordered entries; the first is `id: "agent_call"`, `name: "Agent call"`, and remains the catalogue default. Its `description`, `operating_mode` and `available_agent_configurations` say "agent call" and no longer say "Worker"; the closed entry fields and the under-ten-word usage examples are unchanged. Its `configuration_schema` stays exactly `{}`. | `implementation/milestones/staffing-router/skeleton.md:320`; `implementation/milestones/staffing-router/goal.md:229-231`; `orchestrator/tasks.py:42-56`; the tasks-2 empty-schema pin `implementation/milestones/tasks-2/slices/slice-01.md:108` | touch this one entry; do-not-add a `role` key (skeleton.md:321 gives it to slice 7), an alias entry, a third entry, or a reordering |
| Default producer projection | The projected default producer selection for both `draft_slice_note` and `implement` is `{"task_executor": "agent_call"}`. The projection stays read-time: it never writes into the durable slice plan. | `orchestrator/tasks.py:292-303`; read-time-compatibility precedent `orchestrator/state.py:2703-2706` | touch the projected default; do-not-materialize the default into stored plans |
| Order value | An order the milestone driver admits carries `task_executor: "agent_call"`, and the driver's own production-task checks compare against `agent_call`. | `implementation/milestones/staffing-router/skeleton.md:320`; `orchestrator/driver.py:2782-2794`; `orchestrator/driver.py:2682-2683` | touch the driver's order construction and its executor checks; do-not-change which task kinds admit an order |
| New API input | `POST /api/tasks` (order `task_executor`) and `POST /api/runs/<id>/slices/<slice-id>/producer` (`task_executor`) accept `agent_call` only. `worker` in either body is refused as `unknown_task_executor`, mapped to HTTP 400, before anything is stored. | `implementation/milestones/staffing-router/skeleton.md:320` ("new API input accepts only `agent_call`"); `orchestrator/tasks.py:209-215,482-486`; `orchestrator/service.py:3908-3910,4626-4639` | touch the two write validators; do-not-accept the retired id on a write, and do-not-invent a new error code |
| Read compatibility | A `task_executor` value read from an already-stored or agent-returned structure — a durable task order, a durable `producer_task_executor` map, or a plan returned in contract JSON — reads as `agent_call` when it says `worker`, and never raises. This covers the two stored shapes that exist here: 107 durable task orders (2 of them still open) across three run states, and 31 stored producer selections across two run states, including this milestone's own slice 1. Stored bytes are never rewritten. | `implementation/milestones/staffing-router/goal.md:231`; `implementation/milestones/staffing-router/skeleton.md:320`; validation seam `orchestrator/contracts.py:230-237`; projection seam `orchestrator/state.py:2703-2706`; routing seams `orchestrator/task_api.py:281`, `orchestrator/tasks.py:590-591`; live evidence `implementation/milestones/staffing-router/.run/state.json:15-21` | touch read, projection and routing paths; do-not-rewrite, migrate, or delete a stored record, plan, or event |
| Record staffing key | A newly admitted record keys this executor's frozen staffing snapshot by the executor id, so it reads `agent_call`; the goal names API values in the rename and this value is returned by the task read route. Records already stored keep the `worker` key and are never rewritten. No production path reads that key, so no reader alias is added. | `implementation/milestones/staffing-router/goal.md:230`; write sites `orchestrator/driver.py:2795-2803`, `orchestrator/task_api.py:127,170`; API visibility `orchestrator/service.py:4265-4273` | touch the write and its two in-module readers; do-not-add a reader alias, migrate a record, or change the snapshot's contents |
| Surfaces that follow the catalogue | The panel's executor picker renders each entry's `name` and `id` from the fetched catalogue, the slice producer control prints the projected `task_executor` verbatim, and the planner prompt serializes the same catalogue object. No panel string and no prompt string is edited by hand for this rename. | `orchestrator/static/panel.html:5835-5837,5930-5937`; `orchestrator/prompts.py:1439-1457` | touch nothing in these surfaces; do-not-hardcode either id in the panel or the prompt |
| Untouched vocabulary | The generic word "worker" is not the executor id and is not renamed: worker-call prose and internals, the recorded accounting event names `worker_interrupted` / `worker_malformed` / `worker_unaccepted`, worker-stall configuration, and internal function names. | `orchestrator/runners.py:1-10`; `orchestrator/tasks.py:33-38`; `orchestrator/README.md:463-464`; `implementation/milestones/staffing-router/skeleton.md:320` ("do-not-rewrite stored records") | do-not-touch: renaming a recorded event name would rewrite the meaning of stored history |
| Slice boundary | This slice adds no staffing document, session, resolver, `role` configuration key, `staffing_session` field, or route, and changes no staffing, dispatch, resume, or accounting behaviour. | `implementation/milestones/staffing-router/skeleton.md:289-298` (slice table and order), `:321` | touch vocabulary and its compatibility rule only; do-not-pull a later slice forward |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_tasks orchestrator.tests.test_task_conformance orchestrator.tests.test_producer_selection orchestrator.tests.test_task_api`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Catalogue inventory and entry are closed under the new name | `test_catalogue_has_exact_builtins_and_self_description` (`orchestrator/tests/test_tasks.py:85-91`) | Catalogue ids are exactly `["agent_call", "brainstorming"]`; the first entry is the default; the closed field set, non-empty text, under-ten-word examples and the empty `configuration_schema` all still hold; no entry text says "Worker". | strict |
| Default producer projects the new id | `test_absent_and_partial_maps_project_defaults_without_migration` (`orchestrator/tests/test_producer_selection.py:300`) | An absent or partial producer map projects `agent_call` for the omitted kind while the durable plan is unchanged. | strict |
| A stored old plan still runs and still projects | `test_old_plan_defaults_to_worker_without_migration` (`orchestrator/tests/test_task_conformance.py:99-146`), renamed for the new value | A durable plan whose stored selection is `worker` drives a real driver step, admits an order projected as `agent_call`, and leaves `milestone.slices` byte-identical before and after. | strict |
| A stored old order still routes and executes | new check in `orchestrator/tests/test_task_api.py` | A record admitted with the stored `worker` order value is routed to the agent-call runtime and executes; no exception is raised for the retired spelling. | strict |
| The retired id is refused on new writes | new check in `orchestrator/tests/test_task_api.py` and `orchestrator/tests/test_producer_selection.py` | `POST /api/tasks` with `task_executor: "worker"` and a producer write body with `task_executor: "worker"` both return HTTP 400 `unknown_task_executor`, and neither stores anything. | strict |
| The generic vocabulary is untouched | existing suite, unchanged | Recorded `worker_*` accounting event names and worker-stall configuration keep their current spelling; their existing assertions pass unmodified. | strict |

The repository closure gate is unchanged:
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:524`; `implementation/milestones/staffing-router/skeleton.md:325`).

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These entries are the slice-scoped remainder. Enforceability is answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified in code, touched here:** the milestone driver's production-task admission and its executor checks; the standalone task host's record routing and its execution gate; the service's direct-order resolution and its two write bodies; the run summary's slice projection. **Verified catalogue-driven, therefore not edited:** the panel executor picker, the panel producer label, and the planner prompt block, all of which render the catalogue or the projected value. **Verified unaffected:** the generic worker-call machinery in the runners, which never names the executor id. | `orchestrator/driver.py:2682-2683,2782-2794`; `orchestrator/task_api.py:281,127,170`; `orchestrator/service.py:4011-4012,4626-4639`; `orchestrator/state.py:2703-2706`; `orchestrator/static/panel.html:5835-5837,5930-5937`; `orchestrator/prompts.py:1439-1457`; `orchestrator/runners.py:1-10` |
| pinned_facts | The catalogue entry's id, name, self-description and empty configuration; the projected default producer; the driver-written order value; `agent_call`-only acceptance on the two service write bodies with the existing `unknown_task_executor` / HTTP 400 classification; read normalization of `worker` on stored orders, stored plans and returned plans with stored bytes untouched; the new record staffing key with old records kept; and the do-not-touch generic vocabulary. | `implementation/milestones/staffing-router/skeleton.md:320,321,289-298`; `implementation/milestones/staffing-router/goal.md:229-231`; `orchestrator/tasks.py:42-56,209-215,292-303,482-486`; `implementation/milestones/tasks-2/slices/slice-01.md:108` |
| verification | The focused six-row matrix above: catalogue equality; default projection; a real driver step over a stored old plan asserting byte-stable durable state; routing and execution of a stored old order; HTTP 400 `unknown_task_executor` on both write bodies; and the untouched generic vocabulary proven by the existing suite passing unmodified. Compatibility is exercised over the shapes that actually exist on this machine (107 stored orders, 2 open; 31 stored producer selections), not invented ones. | `orchestrator/tests/test_tasks.py:85-91`; `orchestrator/tests/test_task_conformance.py:99-146`; `orchestrator/tests/test_producer_selection.py:300`; `orchestrator/tests/test_task_api.py:76,268`; `implementation/milestones/staffing-router/.run/state.json:15-21`; closure `orchestrator/README.md:524` |
| reuse_posture | **Affected party / harm:** operators and calling products reading an ambiguous catalogue name; the harm is naming confusion, not misbehaviour, and it is fully reversible. **Authority:** the goal's Rename section and the skeleton's Rename row. **Checked and reused:** the single catalogue as the sole id authority, the existing `unknown_task_executor` classification and its 400 mapping, the existing read-time compatibility projection precedent that completes old plans without migrating them, the catalogue-driven panel controls, and the catalogue-serialized planner prompt block. **Cheapest sufficient option:** rename the one catalogue entry and add one read normalization at the existing catalogue lookup; a compatibility adapter, an alias catalogue entry, a schema version, or a state migration would each be more machinery for the same result. **Machinery remaining and its consumer:** the read normalization, consumed by the run summary projection, the driver, and the standalone host. **Lifecycle cost:** no migration, no operational state, one small rule to maintain; omission leaves either an ambiguous public name or broken old runs. | `orchestrator/tasks.py:86-88,209-215`; `orchestrator/state.py:2703-2706`; `orchestrator/service.py:3908-3910`; `orchestrator/static/panel.html:5835-5837`; `orchestrator/prompts.py:1439-1457`; `implementation/milestones/staffing-router/goal.md:229-231` |
| enforceability | Every guarantee this note asserts has a mechanism that already exists. Catalogue closure: exact-list equality over the single catalogue projection. Acceptance refusal: the catalogue-membership check that already raises `unknown_task_executor`, mapped to 400 by the existing task-error mapping. Read compatibility: the same catalogue lookup, which every stored-value path already funnels through, plus the byte-stability assertion pattern the existing compatibility test uses. Panel and prompt correctness: no mechanism is needed because neither surface holds the id — both render the catalogue. Untouched vocabulary: enforced by the existing suite's assertions on recorded event names. **No guarantee is asserted for anything this slice cannot express:** it promises nothing about staffing, dispatch, delivery, freshness, or the survival of a bookkeeping value. | `orchestrator/tasks.py:86-88,156-158,209-215,482-486`; `orchestrator/service.py:3908-3910`; `orchestrator/contracts.py:230-237`; `orchestrator/state.py:2703-2706`; `orchestrator/tests/test_task_conformance.py:99-146`; `orchestrator/tests/test_tasks.py:85-91` |

### Reuse Posture

The affected parties are operators reading the panel's catalogue and calling
products choosing an executor over HTTP. Without the rename they keep a name
that means "any LLM call" for a choice that means one contracted agent call;
the harm is confusion at every order, not misbehaviour, and it is exposed
continuously but reversible at any time. The independent authority is the
goal's Rename section, carried into the skeleton's Rename row.

Checked and reused: the single built-in catalogue as the only id authority, so
one edit propagates everywhere; the existing `unknown_task_executor`
classification and its established 400 mapping, so no new error vocabulary is
needed; the repository's existing read-time compatibility rule, which already
completes old durable slice plans at projection without migrating their bytes;
the panel's catalogue-driven picker and its verbatim producer label; and the
planner prompt block that serializes the catalogue.

The cheapest sufficient option is renaming that one entry and normalizing the
retired spelling at the existing catalogue lookup on read. Documentation alone
is insufficient because the id is an executable value in stored orders and
plans. An alias catalogue entry, a compatibility adapter, a schema version, or
a durable migration would each cost more to build, operate and review while
producing the same observable result, and a migration would additionally
rewrite records the skeleton forbids touching. The machinery that remains is
one read normalization, consumed by the run summary projection, the milestone
driver and the standalone task host. Its lifecycle cost is one small rule with
no operational state and no migration step; omission would either keep the
ambiguous public name or break every run holding a stored old value.

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| The catalogue is closed, ordered, and its first entry is the default | Exact-list equality over the single detached catalogue projection (`orchestrator/tasks.py:156-158`), which is the only id authority (`orchestrator/tasks.py:86-88`). | The catalogue check asserts the exact id list, the closed field set, the empty configuration, and that no entry text says "Worker". |
| A new write cannot use the retired id | Catalogue membership already raises `unknown_task_executor` for an unknown id (`orchestrator/tasks.py:209-215,482-486`), mapped to HTTP 400 by the existing task-error mapping (`orchestrator/service.py:3908-3910`). | Both write bodies are asserted to return 400 `unknown_task_executor` and to leave state unchanged. |
| A stored retired value still reads, routes and projects | The same catalogue lookup that every stored-value path funnels through (`orchestrator/contracts.py:230-237`; `orchestrator/tasks.py:292-303`; `orchestrator/task_api.py:281`), plus the established read-time projection that leaves durable bytes alone (`orchestrator/state.py:2703-2706`). | A real driver step over a stored old plan asserts the projected value and byte-identical durable state; a stored old order is asserted to route and execute. |
| Panel and prompt surfaces agree with the catalogue | Neither surface holds the id: the picker renders `name` and `id` from the fetched catalogue and the producer control prints the projected value (`orchestrator/static/panel.html:5835-5837,5930-5937`); the prompt serializes the catalogue object (`orchestrator/prompts.py:1439-1457`). | No hand-edited label is introduced; changing the catalogue is the only way to change either surface. |
| Stored history keeps its meaning | Recorded accounting event names are stored vocabulary read from durable state (`orchestrator/tasks.py:33-38`), and the skeleton forbids rewriting stored records (`implementation/milestones/staffing-router/skeleton.md:320`). | The existing suite's assertions on those names pass unmodified; no rename touches them. |

There is deliberately no enforcement row for staffing, dispatch, resume,
accounting, delivery, or freshness: this slice asserts no guarantee about any
of them.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's slice 1 boundary and its Rename row,
  including run amendments A1–A3, none of which this slice's surface engages.
- **Revise:** no baseline decision. This note settles two points the Rename row
  leaves to the slice: which paths count as "new API input" that must refuse the
  retired id (the two service write bodies), and that the record staffing key a
  *new* record writes follows the executor id, on the goal's own "API values"
  authority, while stored records keep theirs.
- **Reject:** brainstorming and `_drafts` material as authority; any staffing,
  session, `role`, or route work belonging to a later slice; and any migration
  or rewrite of stored records, plans, events, or profile sidecars.

Authority: `implementation/milestones/staffing-router/skeleton.md:3-5,289-298,320`;
`implementation/milestones/staffing-router/goal.md:227-231`.
