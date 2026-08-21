# Slice 08 — Panel: documents, sessions, standalone choices

## Register 1 — INTENT (lay language)

### What this slice builds

This slice makes the staffing router the panel's only place for choosing who
does agent work. The operator can inspect the staffing-document catalogue, and
an administrator can edit a whole document. A person who may work on a run can
open that run's live staffing session and change its document, rigor, default
material, or explicit overrides. Those changes govern the next call; opening a
dialog changes nothing.

Ordering a standalone Agent call or Brainstorming task, starting a standalone
Brainstorming discussion, and syncing a work area each expose the same three
choices: document, rigor, and optional material. The panel opens a session for
the chosen work area and gives that session to the existing operation. It never
offers a review seat, Brainstorming seat, round, model, effort, or family as a
standalone staffing choice. The Agent-call role remains the separate process
choice already generated from the TaskExecutor catalogue.

The dedicated Brainstorming form still owns its roster, closure policy, round
limit, request, and references. It stops assigning agent, model, or effort to
roster positions; the session staffs each automatic position when it actually
runs. The git-sync dialog keeps all of its present safety warning and outcome
behaviour and adds only the shared staffing choice.

The model-profile catalogue, per-run model-profile chooser, launch-time acts
grid, and per-run acts dialog leave the panel. Their public write/read routes
also retire. Existing profile files, selection sidecars, act sidecars, and old
records are not migrated, rewritten, or deleted: old-run resume compatibility
still reads only the selected profile name and rigor as already decided.

### Ownership and boundary

Owned here: the document catalogue/editor; the run-session card and editor;
the shared standalone document/rigor/material control; session handoff from the
three standalone entry points, including the one read-only families fact that
handoff records; removal of legacy staffing controls and routes; truthful panel
wording; and focused UI/API contract tests.

Not owned here: the document or session schema, session binding, resolution,
fallback, review rotation or sealing, Brainstorming execution, task hosting,
git safety or outcome law, planner materials, accounting, or any new access
rule. This slice adds no session list, delete, clone, expiry, history, manual
resolve console, cache, retry, rollback, or second staffing field.

### Guarantee posture

- **Strict — accepted configuration:** document and session writes use the
  existing server validation and atomic records. A successful response is the
  complete stored document or current session selection; a refusal changes no
  bytes.
- **Optimistic — concurrent edits:** documents and sessions have no version or
  compare-and-set. Each valid save lands whole, and the last completed save is
  what the next call reads.
- **Strict — accepted handoff:** once a standalone operation is accepted, it
  carries the exact session id returned for its displayed choices. The existing
  consumer resolves through that id at its physical call.
- **Best-effort — the two-request composition:** opening the session and
  submitting the standalone operation are two ordinary requests. The operation
  is never sent if session creation fails. If the second request is refused, the
  inert session may remain; there is no rollback, retry, cleanup lifecycle, or
  eventual-delivery promise.
- **Best-effort — presentation:** catalogue cards, split-family warnings, and
  staffing shown in task or run detail are views that gate nothing. Omission or
  staleness of a derived bookkeeping projection never changes a call, result,
  seal, or accounting. This bounds authority, not obligation: a successful read
  still renders the catalogue, session and warning surfaces Acceptance requires,
  and the checks below pin them.

### Dependencies and consumers

This slice depends on the document and session stores, the staffing API, the
effective per-project configuration the service already derives for standalone
work, the run's id-only session projection, and the session-aware standalone
consumers delivered by slices 2–7. Direct consumers are the single panel page,
the service's project view, its legacy route dispatch and run-detail
projection, the Brainstorming catalogue description, and focused panel/service
tests.

Planner material controls remain outside this slice; they need no second
document editor, session store, or standalone handoff.

### Acceptance

- The document catalogue is readable from the panel; administrators can save a
  whole document, server refusals remain visible, and model/effort ladder array
  order is preserved exactly as operator data.
- A bound run shows its live session, including a non-blocking warning for each
  unsatisfied distinct-family role. Every authorized session owner can change
  or clear the editable selection and overrides, including while a run is live.
- An unbound old run is shown as unbound rather than being silently rebound; an
  unreadable session is shown as unavailable while dispatch fallback remains
  untouched.
- Direct tasks, task-owned Brainstorming, dedicated Brainstorming, and git-sync
  expose document, rigor, and optional material, open one session for the
  selected work area, and carry its id through the existing field.
- Each standalone session records, as a machine fact, the same effective
  configured family order the service already staffs that project's standalone
  work from, read from the service rather than held in the browser: a project
  whose defaults reorder or replace that order is recorded with its own order,
  and a project whose order cannot be read submits no operation.
- No standalone form exposes or submits a staffing seat, family, model, effort,
  index, or round. Dedicated Brainstorming participant entries carry roster
  facts, not staffing pins.
- The model-profile and acts controls are absent. Their retired routes answer as
  absent routes, and existing profile/sidecar bytes remain unchanged.
- A failed session create submits no work. A failure after session creation is
  shown once, admits no duplicate work, and triggers no retry or rollback.

### Risks and non-goals

- A whole-document JSON editor is intentionally less guided than a parallel
  form-level schema. Syntax is checked in the browser; the server remains the
  only semantic validator. This avoids a second schema that can drift.
- A run may reference a document or material no longer in the current
  catalogue. Opening the editor must preserve and show that value until the
  user changes it; it must not silently select `default` or clear the material.
- Standalone session creation records the selected work area's effective
  configured families as a machine fact, not as another user choice. The panel
  owns no family list: the fact is derived by the service exactly as the
  standalone consumers derive the families they staff from, so a deployment or
  project configured with other families cannot be misstaffed by a browser
  constant that has drifted.
- No route or UI deletes old profile, selection, acts, session, or document
  files. No legacy literal becomes a session override.
- Accepted amendment B1's non-dispatch review-family read, the two surfaced
  conditions, the round cap, convergence, and sealing are inherited unchanged.
- This slice is expected to exceed the approximate 500-changed-line aim. It
  removes several hundred lines of legacy catalogue, acts, and seat-staffing UI
  while adding four connected panel entry points and focused proofs. Splitting
  the retirement from the replacement would temporarily leave a visible
  parallel staffing channel; coherent implementation cuts remain acceptable.

### Reuse Posture

Affected parties are operators and calling products using the panel: without
this slice they can configure the router through the API but the panel still
shows inert profile/acts choices and cannot deliberately staff standalone work.
The realistic harm is a visible quality or cost mismatch on each call; the next
call is reversible by editing the session, but the mistake repeats until then.

Checked and reused: the staffing document/session routes and their access
checks, the run's session-id projection, project/work-area selectors, the shared
JSON editor and JSON request helper, schema-derived Agent-call role control, and
the existing `staffing_session` field on task, Brainstorming, and git-sync
requests. The cheapest sufficient option is one shared selection-and-handoff
surface plus deletion of the old controls and routes. Because the session
records the family order the resolver then reads, that order needs exactly one
producer: the effective per-project configuration the service already computes
for standalone work rides read-only on the project view the forms load. This is
a projection of existing configuration rather than a new source — the
alternatives are a browser-side family list, which is the second configuration
authority this milestone exists to end, or changing the session-create contract,
which belongs to slice 5. The only new lasting record is the ordinary session
consumed by the selected operation; there is no new store, route family, ACL,
validator, transaction, cache, migration, or cleanup service. An unused
session after a refused second request is low-cost and inert; transactional
machinery would cost more to build and operate than that reversible omission
harm.

### Planning Material Disposition

- **Adopt:** the reviewed slice-8 boundary and amendments A1–A3. Capability
  ladder order stays operator-authored data; old-run resume derives no
  overrides; every authorized session owner may edit overrides.
- **Adopt as inherited, not touched:** accepted amendment B1. This panel slice
  neither reads review-cycle families nor changes dispatch refusal placement.
- **Revise:** the transitional model-profile and acts panel is replaced by the
  already-public document/session contracts; standalone forms create and pass a
  session instead of choosing seats or posting inert pins, on families the
  service derives rather than the browser.
- **Reject:** planning prose or old UI as staffing authority; a new session
  catalogue/lifecycle; client-side schema duplication; transactional handoff;
  new permissions; sidecar migration or deletion; and any panel-derived
  override on resume.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Staffing-document panel | The panel reads `GET /api/staffing/documents`. Every authorized viewer may inspect the returned whole documents; only the existing service administrator is offered save controls. Saving syntax-valid JSON sends one whole document to `POST /api/staffing/documents`; `400 invalid_staffing_document` remains verbatim and leaves prior bytes unchanged. Array order, especially each model and effort ladder, round-trips exactly: capability order is operator data and the panel never sorts or prices it. The browser copies no document schema beyond JSON syntax. | `implementation/milestones/staffing-router/skeleton.md:196-205,290,311,322`; route/store `orchestrator/service.py:2044-2051,2113-2126,4618-4630,4965-4975`; order-preserving atomic store `orchestrator/staffing.py:692-760`; reusable editor `orchestrator/static/panel.html:6968-6993` | touch the standing catalogue button/dialog and focused tests; do-not change the schema/store/routes, add patch/delete/version semantics, auto-reorder ladders, or add a client semantic validator |
| Per-run session controls | Run settings use only `summary.staffing_session`; when present they read `GET /api/staffing/sessions/<id>` and show `document`, `rigor`, optional `material`, full optional `overrides`, read-only work-area/family facts, and the live `distinct_families_unsatisfiable` list. Save uses `POST /api/staffing/sessions/<id>` for exactly the four editable fields; explicit null clears material or overrides. Every caller already authorized for the session may save, including during a live run. Opening never writes or normalizes an absent document/material. An absent binding is shown as awaiting A2 resume derivation; an unreadable id shows the route's refusal and is not rebound or repaired. | A3 as restated at `implementation/milestones/staffing-router/skeleton.md:105-111`; A2 at `implementation/milestones/staffing-router/skeleton.md:118-136,324`; session shape `implementation/milestones/staffing-router/skeleton.md:312`; id-only projection `orchestrator/state.py:2830-2837`; access/view/edit `orchestrator/service.py:2143-2205,2226-2238,4631-4640,4985-5000` | touch the run settings card and shared editor; do-not bind/rebind a run, copy a document, gate on the warning, restrict override authors to administrators/operators, or add list/delete/history |
| Standalone session choice and handoff | The direct-task form, dedicated Brainstorming form, and git-sync dialog each expose `document`, `rigor`, and optional `material` from the live document catalogue. Before the existing operation request, the panel creates one session with that selection, the selected `{project, work_area}`, and the same effective configured `families_order` that work in that project uses; families are not a control. That order reaches the panel as one read-only fact on the project view the forms already load for their selectors, derived by the service's existing project-defaults merge — the same effective configuration the direct host and git-sync staff from — so the browser holds no family name, no default order and no fallback of its own; a selected project the view cannot supply that fact for submits no operation, exactly as a catalogue failure does. A successful create's `session.id` is sent as the operation's sole top-level `staffing_session`. Blank material is omitted. Catalogue or session-create failure submits no operation and is shown verbatim. | `implementation/milestones/staffing-router/skeleton.md:42-47,225-233,295-296,321-322`; owner supplies the families `implementation/milestones/staffing-router/goal.md:57-61,213-225`; project view and the effective per-project merge `orchestrator/service.py:333-365,4224-4234`; consumers staffing from that same merge `orchestrator/task_api.py:200-224`, `orchestrator/service.py:3778-3797`; session `families` as a resolution input `orchestrator/staffing.py:1346-1359,1975-1994`; create route `orchestrator/service.py:2208-2223,4976-4984`; existing task, Brainstorming and sync consumers `orchestrator/service.py:4291-4342,4824-4848,3734-3803` | touch the three dialogs, their existing request bodies, and one derived read-only families fact on the project view; do-not expose seats/families/models/efforts/index/round as a control, keep a client-side family list or default order, add another staffing field, derive an override, or change consumer execution |
| Standalone roles and Brainstorming roster | Agent-call `role` remains the catalogue-derived nine-choice control with default `implement`; staffing controls do not replace or override it. Dedicated Brainstorming keeps participant roles/order, external Dante, closure and round controls, but panel-created participant entries omit `model_family`, `model`, and `effort`; every automatic call is staffed at its persisted roster index through the supplied session. Catalogue wording says the session is authoritative, not profiles or roster pins. | role schema `orchestrator/tasks.py:41-65`; current schema-driven panel `orchestrator/static/panel.html:5885-5933`; Brainstorming request/session field `orchestrator/brainstorming_lifecycle.py:440-452,1744-1777`; slice-6 authority `implementation/milestones/staffing-router/slices/slice-06.md:167-172`; stale wording/control seams `orchestrator/tasks.py:68-93`, `orchestrator/static/panel.html:845-854,6203-6263,6453-6491` | touch truthful catalogue prose and the dedicated form's participant payload; do-not change role/roster/closure law, expose seat staffing, or reopen slice 6's dispatch and legacy-record rules |
| Legacy surface retirement and compatibility | Retire `GET/POST /api/model-profiles`, `GET/POST /api/runs/<id>/model-profile`, and `POST/PATCH /api/runs/<id>/acts`; for an otherwise accessible request they answer the ordinary `404 {"ok": false, "error": "not found"}`. Remove the Model profiles catalogue/editor, per-run profile chooser, launch acts grid, per-run acts dialog, their API calls, and the `acts` member supplied only for that dialog from run detail. Stored model-profile documents, `model_profile.json`, `acts.json`, old task/run records, conversion, and A2's name/rigor selection read remain byte-untouched. No act literal becomes an override. | retirement list `implementation/milestones/staffing-router/skeleton.md:208-214,234-242,296,322,324`; current routes `orchestrator/service.py:4618-4622,4796-4802,4965-4968,5069-5077,5095-5107`; current projection/UI `orchestrator/service.py:3518-3536`, `orchestrator/static/panel.html:625-628,698-779,1060-1135,1280-1330,3789-3796,3906-3930,4547-4861`; A2 `implementation/milestones/staffing-router/skeleton.md:118-136` | touch route dispatch, run detail, panel and obsolete focused tests; do-not delete/edit/migrate stored files or records, remove conversion/resume readers, or change the `worker` read alias |
| Write and delivery posture | Document/session writes are strict validate-before-atomic-replace and optimistic last-completed-write-wins under races. Standalone selection is two requests: no operation request before a successful session create; no automatic retry, rollback, deletion, or idempotency layer; a second-request refusal may leave one inert session and never admits duplicate work. Panel projections are best-effort. No eventual guarantee is asserted. | store mechanisms `orchestrator/staffing.py:718-760,1452-1549`; API adapters `orchestrator/service.py:2113-2126,2208-2238`; existing one-shot panel requests `orchestrator/static/panel.html:5983-6041,6431-6512,6546-6551`; best-effort boundary `implementation/milestones/staffing-router/skeleton.md:72-76,112-117` | touch one shared handoff and pending/error states; do-not add a transaction, compensating delete, retry, queue, cache, acknowledgement, reconciliation, or delivery claim |
| Slice boundary | Existing document/session/resolve contracts, run binding and A2 resume derivation, standalone hosts, git-sync safety/outcome law, Brainstorming dispatch, B1's third non-dispatch review-family read, review caps/convergence/sealing, planner material channel, markers/accounting, and the two surfaced conditions do not change. No granted read-only root is edited. | `implementation/milestones/staffing-router/skeleton.md:59-63,291-303,313-325`; B1-restated review boundary `implementation/milestones/staffing-router/skeleton.md:315,319`; existing consumers `orchestrator/task_api.py:276-355`, `orchestrator/brainstorming_execution.py:451-487`, `orchestrator/service.py:3734-3825` | touch panel presentation, the legacy route dispatch/detail projection, the project view's derived families fact, catalogue prose and focused tests only; do-not change `orchestrator/staffing.py`, the document/session/resolve contracts, driver/review law, provider calls, task results, git outcomes, or planner contracts |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_staffing_panel orchestrator.tests.test_staffing_api orchestrator.tests.test_staffing_standalone_cutover orchestrator.tests.test_task_panel orchestrator.tests.test_service_projects`

The repository's official closure command remains:

`python3 -m unittest discover -s orchestrator/tests -t .`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Documents are edited whole and ladder order is operator-owned | new `test_document_editor_uses_whole_api_and_preserves_ladder_order` in `orchestrator/tests/test_staffing_panel.py` | Member inspection and administrator editing use only the document routes; a deliberately non-alphabetic ladder round-trips unchanged; invalid JSON stays client-side, invalid semantics show `invalid_staffing_document`, and prior bytes match; no client schema/sort/price rule exists. | strict write / optimistic race |
| Run settings are one live session under A3 | new `test_run_session_controls_read_edit_clear_and_warn` | A bound run loads its exact session, preserves absent catalogue values on open, shows an unsatisfied-role warning without blocking, and saves document/rigor/material/overrides; null clears both optional fields. A project member may edit; a foreign member may not. Edits between two calls reach only the second. | strict / optimistic race |
| Unbound and unreadable runs are not repaired by the panel | new `test_run_session_controls_do_not_bind_or_repair` | An unbound summary causes no session POST and says resume will derive; an unreadable id shows `unknown_staffing_session`; opening/closing either view changes no run/session/profile/acts bytes. | strict no-write / best-effort view |
| Every standalone entry point carries its displayed session | new `test_standalone_forms_create_and_carry_one_session` | With default and project-overridden family orders, the direct task, task-owned Brainstorming, dedicated Brainstorming, and git-sync each create a session with the selected work area/document/rigor/material and pass its returned id in the existing field; accepted execution resolves through it. Each stored session's `families` equal the order the service derives for that project — the same one the existing standalone consumers staff from — in both cases, and a project whose derived order the view cannot supply submits no operation rather than falling back to an order the browser supplies. | strict accepted handoff |
| Standalone controls never become seat staffing | new `test_standalone_forms_expose_no_seat_staffing` | The common controls contain only document/rigor/material; Agent-call role still comes from the catalogue; dedicated Brainstorming participants carry role/delivery/id but no family/model/effort; changing roster size changes no staffing input shape. | strict |
| Two-call failure and legacy retirement stay bounded | new `test_handoff_failure_and_legacy_routes_are_bounded` | A refused session create sends no operation; a refused second request sends once, is shown verbatim and triggers neither retry nor rollback. Every retired route is 404 for an accessible target, all retired controls/API strings are absent, run detail omits `acts`, and sentinel profile/sidecar/old-record bytes remain identical. | best-effort composition / strict retirement |
| Adjacent contracts remain intact | existing suites in the focused command, including the project view's own suite `orchestrator/tests/test_service_projects.py` | Session access/override authorship, exact route tokens, live edits, task/Brainstorming/git session consumption, schema-derived role controls, native results and git outcomes remain green with only intentional panel/retirement expectation changes. The project view changes by exactly one addition: every successful project entry gains the read-only families fact, and because the listing, project creation, single-project read and defaults update all return that same entry, all four responses gain that one field and nothing else, while fail-closed error entries, their reasons, refusal statuses, work-area shapes and every other project route keep their exact present bytes. | inherited postures |

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These rows are the slice-scoped remainder; enforceability is answered again for
the contracts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | Verified direct consumers: the standing catalogue controls, launch/run settings, direct-task form, dedicated Brainstorming form, git-sync dialog and their shared JSON/request helpers in the single panel; the service's model-profile/acts route branches, its run-detail `acts` projection and the project view that now carries the derived families fact; the Brainstorming TaskExecutor's public staffing description; and focused panel/API expectations. Existing router, driver/review cycle, task host, Brainstorming provider boundary, git runner and planner are consumers of already-carried sessions and are not changed. | panel surfaces `orchestrator/static/panel.html:617-629,636-790,792-926,951-971,1060-1135,1280-1330,2160-2240,3780-3930,4547-4861,5708-6041,6188-6512`; service `orchestrator/service.py:3518-3536,4618-4639,4796-4802,4965-5008,5069-5107`; catalogue `orchestrator/tasks.py:41-93`; untouched consumers `orchestrator/task_api.py:276-355`, `orchestrator/brainstorming_execution.py:451-487`, `orchestrator/service.py:3734-3825` |
| pinned_facts | The bug-level facts are: whole-document edit under admin access with operator-preserved ladder order; one live per-run session editable by every authorized owner with split warnings non-blocking; the same document/rigor/material session choice and sole id handoff at every standalone entry point, recording the service-derived family order and no browser constant; no standalone seat/family/model/effort choice and no Brainstorming participant pins; exact retirement of the profile/acts routes and controls without touching old bytes or A2; two-request best-effort composition with no retry/rollback; and the adjacent-slice no-touch boundary. | `implementation/milestones/staffing-router/skeleton.md:95-136,196-214,225-242,290-325`; `implementation/milestones/staffing-router/goal.md:213-225,244-258`; document/session enforcement `orchestrator/staffing.py:692-760,1416-1549`; current legacy routes `orchestrator/service.py:4618-4622,4796-4802,4965-4968,5069-5077,5095-5107` |
| verification | The seven-row Verification Contract names focused checks for whole-document order/refusal, live authorized session editing and clearing, unbound/unreadable no-write behaviour, all four standalone handoffs under default/custom family orders with the recorded families equal to the service's own derivation, the absence of seat staffing, bounded two-call failure, legacy 404/byte preservation, and adjacent suites. The project view's own suite is in the focused command because this slice adds a fact to every successful project entry: its whole-entry expectations, on each of the four routes that return an entry, change by that one addition and nothing else. Existing API, standalone-cutover and schema-driven panel tests provide the executable fixtures; closure retains the official full suite. | existing API fixtures `orchestrator/tests/test_staffing_api.py:195-746`; project view expectations `orchestrator/tests/test_service_projects.py:899-914,985-998,999-1024,1046-1052`; standalone fixtures `orchestrator/tests/test_staffing_standalone_cutover.py:298-506,509-782,784-1114,1116-1402`; panel pattern `orchestrator/tests/test_task_panel.py:8-118`; official suite `orchestrator/README.md:533-535`; this note, Verification Contract |
| reuse_posture | Affected parties are panel operators and products ordering standalone work; omission leaves visible inert choices and repeated per-call misstaffing, while a bad edit is visible and reversible on the next call. Checked and reused: document/session APIs and access, id-only run projection, project defaults/work-area facts and the effective per-project configuration already computed for standalone work, common selectors, shared syntax-only JSON editor, one-shot JSON helper, catalogue-derived role field, and the three existing `staffing_session` consumers. Cheapest sufficient is one shared selection/handoff plus deletion; one ordinary inert session is the only residual cost when call two fails. No store, route family, ACL, schema copy, transaction, retry, migration, cache, ledger or cleanup machinery is justified. | milestone proportionality `implementation/milestones/staffing-router/skeleton.md:258-283,296`; API/access `orchestrator/service.py:2044-2272`; project facts `orchestrator/service.py:333-365,4224-4234`; reused panel seams `orchestrator/static/panel.html:5501-5768,5885-5933,6546-6551,6968-6993`; existing consumers `orchestrator/service.py:3734-3803,4291-4342,4824-4848` |
| enforceability | Whole/byte-stable document and session writes are enforced by validate-before-atomic-replace; ladder order by JSON array preservation; A3 by stored-work-area project authorization; live/non-gating session views by the existing session GET/edit/projection; exact standalone handoff by session create plus the already-closed `staffing_session` request fields, with the recorded families produced by the service's existing per-project merge rather than a client copy; no-seat behaviour by the closed task configuration and Brainstorming participant payload; retirement by removing route branches and panel calls while byte-snapshot tests guard old files. Races are only optimistic, the two-call bundle is only best-effort, and views are only best-effort; no transaction, delivery, survival, cleanup or freshness-after-response guarantee is asserted. | stores `orchestrator/staffing.py:718-760,1416-1549`; access/view `orchestrator/service.py:2143-2238`; closed task/session fields `orchestrator/tasks.py:248-284,527-590`, `orchestrator/brainstorming_lifecycle.py:440-452`; one-shot consumers `orchestrator/service.py:3734-3803,4291-4342,4824-4848`; current retirement targets `orchestrator/service.py:4618-4622,4796-4802,4965-4968,5069-5077,5095-5107` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| A document edit is whole, byte-stable on refusal, and preserves ladder order | The existing route and validate-before-atomic-replace store at `orchestrator/service.py:2113-2126` and `orchestrator/staffing.py:718-760`; JSON arrays are not sorted by the store. | Save a document with deliberately unusual ladder order; compare response/store, then refuse an invalid replacement and compare prior bytes. |
| Every authorized run owner can edit one live session without a split warning becoming a gate | Stored-work-area authorization and live view/edit at `orchestrator/service.py:2143-2238`; the id-only run projection at `orchestrator/state.py:2830-2837`. | Exercise member/foreign/admin identities, a running call on either side of an edit, both null clears, and an unsatisfied split. |
| Every accepted standalone operation carries the session built from its displayed choices, on the project's own configured families | Session create at `orchestrator/service.py:2208-2223,4976-4984`; closed task/Brainstorming/sync fields at `orchestrator/tasks.py:248-284,527-590`, `orchestrator/brainstorming_lifecycle.py:440-452`, and `orchestrator/service.py:3734-3803`; the families the session records are the service's existing per-project effective configuration at `orchestrator/service.py:4224-4234`, surfaced read-only on the project view the forms already load, so the one authority the resolver reads (`orchestrator/staffing.py:1975-1994`) has one producer. | Capture both requests for all four paths, inspect the stored session and operation body, then capture the consumer's live resolution; repeat under a project defaults override that changes the family order, and once more with that fact withheld: the recorded order tracks the service in the first and no operation is submitted in the second. |
| Standalone choices contain no seat staffing | The schema-generated Agent-call role control at `orchestrator/static/panel.html:5885-5933` and the closed Brainstorming create payload at `orchestrator/brainstorming_lifecycle.py:440-452` can express role/roster separately from `staffing_session`. | Inspect controls and submitted JSON; vary role and roster size while asserting no family/model/effort/index/round field appears. |
| A partial handoff cannot duplicate work or claim atomicity | The panel's awaited one-shot request pattern at `orchestrator/static/panel.html:5983-6041,6431-6512,6546-6551`; there is no session delete/transaction route. | Fail call one and count zero operation calls; fail call two and count exactly one, no retry/delete, with the refusal visible and the inert session permitted. |
| Retired public inputs disappear without rewriting compatibility bytes | The removable route branches at `orchestrator/service.py:4618-4622,4796-4802,4965-4968,5069-5077,5095-5107`; A2 preserves the selection read at `orchestrator/driver.py:443-459`; files are independent of route removal. | Assert 404 for each method on an accessible target, absence from panel/run detail, and byte identity for model profiles, selection/acts sidecars and old records before/after. |
