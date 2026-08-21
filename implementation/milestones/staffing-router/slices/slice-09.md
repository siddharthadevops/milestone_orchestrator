# Slice 09 — Planner material channel

## Register 1 — INTENT (lay language)

### What this slice builds

This slice lets milestone planning describe the kind of work each slice contains
without choosing an agent, model, or effort. Whenever a planning call may create
or replace the slice plan, it sees the current staffing document's material
names and their usage phrases beside the existing catalogue of ways to produce
the work. The planner may attach one material name to each slice. The same name
appears in the structured plan and in that slice's row of the skeleton table.

A material is a proposal about the work, not staffing selected by an LLM. The
staffing router remains the only authority that turns the slice's material,
role, seat, round, live session, and live document into an agent, model, and
effort. Omitting the slice material leaves the session's default material in
force. A stale or unknown name never blocks work; the router applies its
existing unknown-material rule.

The material belongs to the slice and covers its two production tasks: drafting
the slice note and implementing the slice. Each task takes the slice's current
material when that task is ordered. A later edit does not retarget an already
ordered task, including a Brainstorming task that makes several calls; it
governs the next production task or later replacement task ordered for that
slice. Every physical agent call made by either kind of producer asks the router
with the material that task took.

The run view shows the material beside the existing producer choices. An
authorized caller can write another string or clear the slice material through
the slice's material endpoint. A successful write is prospective. A write that
collides with a driver step is refused once and is neither queued nor retried.

### Ownership and boundary

Owned here: the material catalogue in every slice-plan-authoring prompt; the
optional material field in a structured slice plan and its visible skeleton
column; read-time projection of that field; the prospective slice write and
panel control; task-local propagation through both production executors; and
focused contract, route, panel, restart, and captured-request tests.

Not owned here: material names or usage phrases, document/session validation,
session default material, material overrides inside a staffing document,
resolution precedence, family/model/effort choice, task roles, producer choice,
non-production calls, review rotation or sealing, markers or accounting, new
access rules, or compatibility migration. This slice adds no material store,
snapshot, version, acknowledgement, queue, retry, cache, ledger, or history UI.

### Guarantee posture

- **Strict — readable planning input.** A successfully assembled plan-authoring
  prompt contains exactly the material names and usage phrases validated from
  the session's referenced document at that prompt boundary. A later document
  edit reaches the next such prompt, not one already dispatched.
- **Best-effort — unreadable planning input and proposal.** If the session or
  its referenced document cannot be read for prompt guidance, planning proceeds
  with an empty material catalogue. This does not alter or pre-empt the router's
  mandatory dispatch fallback. A planner proposal is bookkeeping and decides no
  acceptance, review, seal, result, or accounting outcome by itself.
- **Strict — admitted production task.** The current slice material, including
  its absence, is fixed on each production task when that task is accepted. All
  physical calls of that task use that value; an accepted later slice edit can
  affect only a later task.
- **Strict — resolution meaning.** A material string is passed as the router's
  existing optional request material. Live session/document reads, material
  precedence, unknown-name handling, fallbacks, surfaced conditions, and the
  three-key staffing answer remain unchanged.
- **Optimistic / best-effort — prospective writes.** Valid writes serialize
  against task admission and last accepted write wins. Lock contention returns
  `task_update_busy`; no compare-and-set, retry, queue, rollback, or eventual
  delivery is promised. A successful view renders the stored value, but panel
  presentation itself gates nothing.

### Dependencies and consumers

This slice follows the document/session/resolver, driver, API, Brainstorming,
standalone-task, and panel cuts in slices 2–8. It reuses their live document,
single-session, per-dispatch, frozen-task-order, producer-selection, run-summary,
mutation-lock, and catalogue-driven panel seams.

Direct consumers are the planner that authors or repairs a slice plan; the
structured plan validator and run summary; the milestone driver when it admits
`draft_slice_note` and `implement`; Agent-call and Brainstorming production
hosts at their physical router calls and restarts; the run's slice controls;
and focused tests. Outside an admitted Brainstorming production task, fixers,
classifiers, consultations, reviews, git-sync, and standalone work remain
consumers only of their session default material.

### Acceptance

- Every prompt permitted to return a complete or updated slice plan carries the
  live readable material catalogue, including each usage phrase, beside the
  shared TaskExecutor catalogue. An unreadable catalogue does not fail the run.
- A slice-plan entry accepts an omitted material or a string. The string is
  preserved verbatim in state and summary and is distinguished as an explicit
  write in later plan-review context; non-strings are refused. It is not checked
  against the live catalogue. A later authorized complete plan replacement
  resets earlier write authority exactly as it does for producer choices.
- The planner instruction requires one visible material column in the skeleton
  table; a proposed string agrees with the structured slice entry, while an
  omitted proposal remains visibly empty and means "use the session default."
- `POST /api/runs/<id>/slices/<slice-id>/material` accepts exactly
  `{material: <string>}` or `{material: null}`. A string replaces the current
  slice value and null clears it. Existing run access applies. Malformed writes
  change nothing; lock contention returns `409 task_update_busy` and queues
  nothing.
- The panel shows the current slice material and can set or clear it without
  editing the skeleton artifact, staffing document, or session default. It
  displays refusals verbatim and sends no automatic retry.
- The material in force when each `draft_slice_note` or `implement` task is
  admitted is sent on every router request that physically staffs that task,
  whether its producer is Agent call or Brainstorming and after a restart.
- Changing the slice material after one production task is admitted leaves all
  calls of that task on its admitted value and governs the next production task.
  An unknown or later-removed name still dispatches under existing resolver law.
- Skeleton drafting, fixes, classification, consultation, review, delta review,
  git-sync, and standalone orders gain no slice-material input. Automatic calls
  inside a Brainstorming production task retain that task's material regardless
  of their internal role.

The expected implementation stays around the roughly 500-changed-line aim by
extending the existing producer channel and task-local staffing context. No
parallel store, public document-read seam, route family, or lifecycle is
justified.

### Risks and non-goals

- Validating a proposal against the current catalogue would turn a harmless
  document rename into a stopped plan or write. Shape validation therefore
  checks only string-or-absence, plus that the string is storable as UTF-8;
  the router remains responsible for meaning.
- Reading the slice plan again during an active Brainstorming discussion would
  let a prospective edit split one task across materials. The task admission
  boundary and restart proof pin one value for the whole task.
- Treating the planner's word as staffing would bypass the router. Captured
  requests prove the word is only one router input and that the returned agent,
  model, and effort still come from live resolution.
- Reusing the session's default material instead of the slice value would make
  the new channel inert. Tests use a document where the two materials resolve
  differently.
- Expanding the field to fixes, reviews, or standalone work would change their
  already-reviewed ownership. Negative captured-request checks keep the cut to
  the two production kinds.
- Prompt guidance is a boundary snapshot, not a subscription. There is no
  freshness promise after the planning call starts and no recovery catalogue
  invented when the selected document is unreadable.

### Reuse Posture

Affected parties are planners and authorized run owners. Without this slice the
planner cannot see the operator-authored vocabulary and the two production tasks
cannot consistently ask for the material chosen for their slice; the realistic
harm is a reversible quality or cost mismatch on those calls, repeated until a
session or document is edited. The reviewed goal and skeleton independently
require the channel.

Checked and reused: the validated `materials` mapping and its usage phrases; the
validated session/document reads; the existing prompt block that serializes the
TaskExecutor catalogue; optional slice-plan projection; the producer update's
run lock, state handoff, summary and panel row; frozen task orders; the Agent-call
pre-dispatch resolver; Brainstorming's persisted session binding and live seat
resolver; and the router's existing optional `material` parameter and unknown
name rule.

The cheapest sufficient option is one optional string on the existing slice
plan, one sibling prospective write, and a task-local copy carried through the
two existing production paths. Documentation alone is insufficient because the
router request would remain empty; changing the session default is too broad
because it affects every call; and reading the mutable plan at each call breaks
the prospective task boundary. The only lasting machinery still justified is
the task-local material carrier, consumed by Agent-call dispatch and by a
Brainstorming production task across its calls and restart. It adds no new
store or cleanup duty: ordinary task/session retention owns its lifetime.
Omission risks repeated misstaffing; clearing the slice value reverses the
choice for later tasks, while accepted task records remain immutable.

### Planning Material Disposition

- **Adopt:** the reviewed slice-9 boundary, amendments A1–A3, and the goal's
  planner-proposes/authorized-caller-disposes split. Capability ladders,
  old-run derivation, and session-override authorship remain untouched.
- **Adopt as inherited, not touched:** accepted amendment B1. This slice neither
  changes the three review-law document reads nor moves
  `distinct_families_unsatisfiable` away from affected dispatches.
- **Revise:** no reviewed design decision. This note settles only the
  prospective boundary: material is fixed per accepted production task, so an
  edit may govern the second task without retargeting the first task's remaining
  Brainstorming calls.
- **Reject:** brainstorming and `_drafts` prose as authority; catalogue
  membership validation on a plan or write; a copied catalogue, material store,
  per-call plan lookup, session-default rewrite, non-production propagation,
  delivery machinery, or any staffing choice outside the router.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Planner catalogue and plan shape | Every prompt that may create or replace the slice plan lists the current readable session document's `materials` as name → `examples` beside the TaskExecutor catalogue and instructs the author to show one material column in the skeleton table. Each structured slice has optional `material`: when present it is a string and is preserved verbatim; it is never catalogue-membership validated. Omission means no request material and leaves the session default in force. If guidance cannot read the session/document, the catalogue block is empty and planning continues. | `implementation/milestones/staffing-router/skeleton.md:42-47,69-71,112-117,297,323`; `implementation/milestones/staffing-router/goal.md:213-221`; material shape `orchestrator/staffing.py:335-359,554-575`; prompt/plan seams `orchestrator/prompts.py:1439-1457`, `orchestrator/contracts.py:215-246` | touch the shared plan-authoring prompt block, driver prompt input and slice validation/projection; do-not add a second catalogue, validate a plan against mutable catalogue membership, fail planning on an unreadable guide, or let the prompt select agent/model/effort |
| Visible proposal and projection | The planner's material string appears in both its structured slice entry and the skeleton table's material column. Current plan projections retain optional `material` beside `id`, `title`, and `producer_task_executor`; old plans with no field remain valid and byte-unchanged. An explicit operator write changes the prospective state/panel projection, not the reviewed skeleton artifact, and later plan-review context identifies it as an override. A later authorized complete slice-plan replacement cuts off earlier override authority exactly as for producer choices. | `implementation/milestones/staffing-router/skeleton.md:42-47,297,323`; current detached plan/summary `orchestrator/tasks.py:343-366`, `orchestrator/state.py:2762-2773`; plan installation and override cutoff `orchestrator/driver.py:4600-4653`, `orchestrator/tasks.py:369-406` | touch structured-plan validation, summary/prompt review projection and panel display; do-not migrate old plans, materialize an absent default, or edit an artifact from the HTTP route |
| Prospective material route | `POST /api/runs/<id>/slices/<slice-id>/material` takes exactly `{"material": <string-or-null>}`. A string sets the slice value; null removes it. The existing run-access check applies. A successful write is visible on the next summary and governs only later admitted production tasks. Malformed input is a 400 `invalid_task_request` with no mutation; lock contention is 409 `task_update_busy`, with no queue/retry. No new public event name is pinned. | `implementation/milestones/staffing-router/skeleton.md:322-323`; existing access/route dispatch `orchestrator/service.py:4860-4882`; producer mutation precedent `orchestrator/service.py:2878-2902`; lock/adoption `orchestrator/driver.py:1433-1474,1486-1544` | touch one sibling slice route, the shared prospective mutation handoff and panel control; do-not add ACLs, compare-and-set, queue, retry, rollback, artifact edit, session edit, or event API |
| Per-task production material | For exactly `draft_slice_note` and `implement`, task admission takes the slice's then-current optional material. Every physical router request made by that accepted task passes the same value, for either `agent_call` or `brainstorming` and after restart. A later slice write never changes an admitted task; it may govern the sibling production task or a later replacement task. The material name is task context, not frozen agent/model/effort: every physical call still resolves the live session and document. | `implementation/milestones/staffing-router/goal.md:215-221`; `implementation/milestones/staffing-router/skeleton.md:105-117,297,310,316,323`; production kinds/order `orchestrator/tasks.py:23-26,409-425`; frozen records `orchestrator/tasks.py:696-717`, `orchestrator/state.py:336-366`; Agent-call admission/dispatch `orchestrator/driver.py:814-838,2937-3035,6947-7250,8664-8679,8774-8787`; Brainstorming seam `orchestrator/driver.py:5390-5504`, `orchestrator/brainstorming_lifecycle.py:525-575` | touch production admission and both existing per-dispatch/restart carriers; do-not read mutable slice state during a task, freeze staffing, add a second session/document copy, or send slice material on any other task kind |
| Resolver meaning unchanged | The task's string is the existing optional `material` request input. A requested known material outranks the session default; an unknown name is ignored and the session default is tried before base. Unknown material never becomes an error or a surfaced condition. The resolver still returns exactly `agent`, `model`, `effort`, reads live, and writes nothing. | `implementation/milestones/staffing-router/skeleton.md:100-117,310,313,315-316`; request admission and meaning `orchestrator/staffing.py:1655-1668,1746-1760,2001-2044` | touch only callers passing the optional input; do-not change precedence, fallback, condition/error vocabulary, answer shape, or router state |
| Panel and delivery posture | Each run slice shows one material value beside its two independent producer choices and permits set/clear through the material route. Successful response/refresh updates the view; errors are shown verbatim. Valid writes are optimistic last-accepted-write-wins; busy/refused writes are best-effort and are never retried. No eventual delivery or view-freshness guarantee exists. | `implementation/milestones/staffing-router/skeleton.md:72-76,112-117,297,322-323`; current slice projection/control `orchestrator/static/panel.html:3762-3771,5485-5531`; one-shot refusal posture `orchestrator/static/panel.html:5533-5600` | touch the existing slice row and one-shot request state; do-not add polling, retry, acknowledgement, history, notification, or a second material control |
| Slice boundary | Document/session schemas and stores, session default/override authorship, resolver internals, A2 compatibility, B1's three review-law reads, role/seat/round law, producer selection, markers/accounting, non-production and standalone dispatches, and all granted read-only roots remain unchanged. The planner catalogue reuses validated session/document reads and adds no fourth public document-read seam. | `implementation/milestones/staffing-router/skeleton.md:59-63,118-136,291-303,309-325`; B1 boundary `implementation/milestones/staffing-router/skeleton.md:315,319`; current reads `orchestrator/staffing.py:2046-2122`; current no-material driver baseline `orchestrator/tests/test_staffing_driver_cutover.py:317-339` | touch only prompt/plan/route/panel and the two production material carriers; do-not reopen adjacent slices, add a public material-catalogue API, or edit generated ledgers/read-only roots |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_producer_selection orchestrator.tests.test_prompts orchestrator.tests.test_staffing_driver_cutover orchestrator.tests.test_staffing_brainstorming_cutover orchestrator.tests.test_task_panel`

The repository's official closure command remains:

`python3 -m unittest discover -s orchestrator/tests -t .`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Planner sees the live vocabulary and structured plans preserve it | new `test_planning_prompts_and_slice_contract_carry_material_catalogue` in `orchestrator/tests/test_producer_selection.py` | A document with two material names and multiple ordered usage phrases appears exactly in initial and later plan-authoring prompts beside the TaskExecutor catalogue; a completed document edit reaches the later prompt. Omitted/string plans validate and project byte-stably; bool/list/null-present values fail; an unknown string validates. Unreadable guidance yields an empty block without failing prompt assembly. | strict readable snapshot / best-effort unreadable guide |
| Proposal is required visibly in the skeleton contract | new `test_planner_instruction_pairs_material_column_with_structured_plan` in `orchestrator/tests/test_prompts.py` | The plan-authoring instruction requires the material in both each structured slice and a visible skeleton-table column, distinguishes omission as session default, and never asks for family/model/effort. | strict prompt contract |
| Slice writes are prospective, clearable, and bounded | new `test_material_route_sets_clears_and_respects_task_boundary` in `orchestrator/tests/test_producer_selection.py` | Set and unknown-string set return success and project; review context identifies the explicit write; null removes the field; malformed bodies are 400 `invalid_task_request` and byte-stable; a held run lock returns 409 `task_update_busy`; no request retries. An accepted write after draft admission leaves that frozen order unchanged and is adopted for implementation admission; a later authorized complete plan replacement resets prior override authority. | strict accepted state / optimistic best-effort write |
| Both production executors pass one admitted value | new `test_slice_material_reaches_agent_call_and_brainstorming_production` spanning the existing driver and Brainstorming cutover fixtures | Draft uses Brainstorming under material A; an accepted slice edit while it is active does not change later turns or its restart; implementation uses Agent call under material B. Every physical router request of each task carries its own admitted value and ran on the router answer. Reversing the producer choices proves the channel is independent of executor selection. | strict task boundary / strict live resolution |
| Unknown names and adjacent calls retain existing law | new `test_unknown_slice_material_degrades_and_nonproduction_calls_stay_unset` in `orchestrator/tests/test_staffing_driver_cutover.py` | Removing the proposed name after admission still dispatches through the session default/base without a new error. The driver's skeleton draft, fix, failure/debt classification, consult and full/delta review requests, plus standalone and sync requests, receive no slice material; automatic calls inside a Brainstorming production task retain that task's material. Existing condition, marker and accounting assertions remain green. | strict resolver law / strict boundary |
| Panel has one prospective material control | new `test_each_slice_material_is_visible_settable_and_clearable` in `orchestrator/tests/test_task_panel.py` | The slice row renders its current value beside both producer choices, set and clear call only the material route, success updates from confirmed state, failures render verbatim, and the UI contains no retry/poll/session-edit/artifact-edit path. | best-effort view / strict request shape |

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These rows are the slice-scoped remainder; enforceability is answered again for
the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | Verified direct consumers: plan-authoring prompt assembly; structured slice validation, installation, effective projection and review context; prospective slice mutation and the driver's live handoff; Agent-call and Brainstorming production admission/physical dispatch/restart; the run summary and slice controls; and their focused tests. Verified untouched consumers outside a Brainstorming production task: driver-level fixes/classifiers/consultations, review/seal law, standalone tasks, git-sync and accounting, which have no slice-material source. | prompt/plan `orchestrator/prompts.py:1400-1457`, `orchestrator/contracts.py:215-246`, `orchestrator/driver.py:4600-4653,6755-6794,6980-7050`; mutation `orchestrator/service.py:2878-2902,4860-4882`, `orchestrator/driver.py:1486-1544`; production `orchestrator/driver.py:814-838,2937-3035,5390-5504,6947-7250,8664-8679,8774-8787`, `orchestrator/brainstorming_lifecycle.py:525-575`; untouched standalone host `orchestrator/task_api.py:202-226`; panel `orchestrator/static/panel.html:3762-3771,5485-5600` |
| pinned_facts | The bug-level facts are: readable plan prompts contain names plus usage phrases and unreadable guidance is non-blocking; each slice has optional string material shown in structured plan and skeleton table without membership validation; old omissions stay byte-stable; the exact set/clear route is prospective and returns `task_update_busy` on collision; each admitted note/implementation task freezes one material name across Agent-call or Brainstorming physical calls and restart while staffing stays live; unknown names degrade under existing resolver law; and no adjacent call or review law gains the field. | `implementation/milestones/staffing-router/skeleton.md:42-47,69-76,95-117,297,310,313,315-316,322-325`; `implementation/milestones/staffing-router/goal.md:213-221,282-293`; resolver enforcement `orchestrator/staffing.py:1655-1668,1746-1760,2001-2044` |
| verification | The six-row Verification Contract pins the prompt catalogue and visible-column instruction, string/omission/unknown/non-string contract matrix, old-plan byte stability, set/clear/malformed/busy route matrix, accepted-write handoff, both producer choices across restart, unknown-name degradation, absence from adjacent calls, and the one-shot panel. Existing captured router fixtures and immutable task-history checks are extended rather than replaced; closure retains the official full suite. | current planner/override tests `orchestrator/tests/test_producer_selection.py:132-192,300-392,1005-1056`; current router capture `orchestrator/tests/test_staffing_driver_cutover.py:212-227,260-339`; Brainstorming capture/restart fixtures `orchestrator/tests/test_staffing_brainstorming_cutover.py:169-185,1241-1292`; panel pattern `orchestrator/tests/test_task_panel.py:53-83`; official suite `orchestrator/README.md:537` |
| reuse_posture | Affected parties are planners and authorized run owners; omission causes repeated but next-task-reversible quality/cost mismatch. Authority is the reviewed planner-material decision. Checked and reused: validated document materials/session reads, shared planning catalogue block, optional slice plan, producer mutation lock/handoff/summary/panel, immutable task order, the driver's Agent-call dispatch, Brainstorming persisted binding/live seat resolver, and router material semantics. Cheapest sufficient is one optional string, one sibling prospective write, and one task-local carrier; documentation leaves router requests empty, a session edit is too broad, and live plan reads split active tasks. The carrier is consumed only by the two production paths and dies with ordinary task/session retention; no store, migration, cache, retry, ledger, snapshot or cleanup machinery remains. | authority `implementation/milestones/staffing-router/skeleton.md:297,323`; materials/store `orchestrator/staffing.py:335-359,648-698,1471-1490`; producer reuse `orchestrator/tasks.py:343-425,479-525`; immutable task `orchestrator/tasks.py:696-717`, `orchestrator/state.py:336-366`; dispatch reuse `orchestrator/driver.py:814-838,2937-3035,5390-5504,6947-7250,8774-8787`, `orchestrator/brainstorming_lifecycle.py:525-575` |
| enforceability | Exact readable catalogue is enforceable by the validated document `materials` map read at prompt assembly; string-or-absence and byte-stable projection by slice validation plus detached plan installation; accepted prospective writes by the existing exclusive mutation and driver adoption boundary; per-task stability by immutable admitted orders and Brainstorming's durable binding/restart path; physical use by the driver's Agent-call resolver and Brainstorming's live seat resolver; unknown-name behaviour by `_material_in_force`; and the no-adjacent-call boundary by captured-request tests. Unreadable guidance, refused writes and panel views are deliberately best-effort. No guarantee is asserted for post-dispatch prompt freshness, delivery/retry, view freshness, proposal survival, or staffing frozen beyond one physical resolver answer. | `orchestrator/staffing.py:335-359,648-681,1471-1490,1746-1760,2001-2044`; `orchestrator/contracts.py:215-246`; `orchestrator/tasks.py:358-366,696-717`; `orchestrator/state.py:336-366`; `orchestrator/driver.py:814-838,1433-1544,2937-3035,6947-7250,8774-8787`; `orchestrator/brainstorming_lifecycle.py:153-219,525-575` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| A plan-authoring prompt receives the current readable material names and usage phrases | Whole-document validation fixes the mapping at `orchestrator/staffing.py:335-359,554-575`; the existing shared planning block serializes its TaskExecutor neighbour at `orchestrator/prompts.py:1439-1457`; session/document reads are validated at `orchestrator/staffing.py:648-681,1471-1490`. | Assemble initial and later plan prompts around a document edit; compare the exact mapping, then make either input unreadable and assert an empty catalogue without a stopped run. |
| A structured slice carries only an optional string and old omissions remain valid | The shared slice validator and detached projection at `orchestrator/contracts.py:215-246` and `orchestrator/tasks.py:358-366`, installed only after validation at `orchestrator/driver.py:4600-4653,7343-7357`. | Exercise omitted/string/unknown/non-string/null-present values and compare source bytes before/after projection. |
| An accepted slice write governs only later task admissions | The existing non-blocking exclusive mutation and adoptable between-step handoff at `orchestrator/service.py:2878-2902` and `orchestrator/driver.py:1433-1544`; task records are immutable after append at `orchestrator/tasks.py:696-717` and `orchestrator/state.py:336-366`. | Set, clear, refuse malformed/busy writes, then write between note and implementation admissions and compare both frozen orders plus the next summary. |
| Every physical call of either production executor uses its task's admitted material while staffing stays live | The driver's Agent-call dispatch resolver runs at every physical call at `orchestrator/driver.py:814-838,6947-7250,8774-8787`; Brainstorming resolves every seat call at `orchestrator/brainstorming_lifecycle.py:525-575` and already persists its session mark across restart at `orchestrator/brainstorming_lifecycle.py:153-219`. | Capture router requests for both producer choices, edit the slice during a multi-call discussion, restart it, and assert one material per task but live document staffing per physical call. |
| Unknown material cannot create a new failure | Request admission accepts every string at `orchestrator/staffing.py:1655-1668`; `_material_in_force` falls through unknown names at `orchestrator/staffing.py:1746-1760`; `resolve` keeps exactly its input error plus two conditions at `orchestrator/staffing.py:2001-2044`. | Remove/rename a task's material before dispatch and assert the session default/base answer and unchanged error vocabulary. |
| Slice material reaches no adjacent call | Production kinds are closed at `orchestrator/tasks.py:23-26`; current driver capture covers the wider role set at `orchestrator/tests/test_staffing_driver_cutover.py:260-339`. | Assert only physical `draft_slice_note` and `implement` task calls carry the field; all other captured roles and standalone/sync suites remain unchanged. |

No enforceability gap remains: strict claims have a closed validator, immutable
task boundary, mutation lock, or physical captured-request seam; the surfaces
without such a mechanism are explicitly best-effort.
