# Slice 03 — Model-profile selection and override surfaces

## Register 1 — Intent

### What this slice builds

This slice lets an operator use model profiles without editing runtime files.
The panel shows the current catalogue, lets an administrator create a complete
profile or edit the opened profile under its unchanged name, and lets an
authorised run user choose the profile name and rigor that should govern the run
now. The same choice is available when a new run is ordered, so its first call
need not race a later settings edit.

The run settings page keeps the existing act-override editor. A blank ordinary
row follows the current profile; an explicit empty row continues to choose the
structural default; and “Use profile” clears that override. Changing the current
selection, editing its saved profile, or changing an override affects the next
model call. A call already under way finishes with the settings it received.

### Ownership and boundary

This slice owns the panel presentation of the Slice 1 catalogue, the panel and
HTTP surfaces for reading or replacing a run's current selection, and the
optional initial selection on a new run. It connects those controls to Slice
2's current-state resolver and reuses the current override controls.

It does not add another catalogue, validator, resolver, override layer, or
staffing store. It does not change act authority, structural family rules,
strategy profiles, generic execution/accounting/recovery, or calling-product
code. It adds no deletion or rename workflow and no profile-specific origin,
history, attribution, acknowledgement, event, version, snapshot, migration,
recovery, lock, conflict token, retry, rollback, or reconciliation.

### Guarantee posture

- **Strict:** every accepted catalogue, selection, or override replacement
  becomes current atomically; when writes overlap, the atomic replacement that
  completes last is current. The next dispatch reads that committed state.
  Profile Edit can replace only the profile that was opened; its name is
  immutable in that action. Invalid input changes nothing. A launch choice is
  committed before autostart. An already-dispatched call is unchanged. Panel
  actions use the same server contracts as direct API callers.
- **Optimistic:** genuinely overlapping catalogue, selection, or override
  replacements have last-completed-write-wins behavior. There is no merge,
  conflict warning, or lost-update protection.
- **Eventual:** none. Accepted writes are immediately readable; no background
  convergence or delayed delivery is introduced.
- **Best-effort:** abrupt browser, host, or filesystem failure retains the
  repository's existing guarantees only. This slice adds no rollback or
  profile-specific recovery promise.

### Dependencies and consumers

Slice 1 supplies the editable validated catalogue and its HTTP API. Slice 2
supplies the current selection reader, current profile resolution, current
override layer, precedence, and pre-dispatch failure behavior.

The direct consumers touched are the service's run and catalogue endpoints, the
served panel, and the existing runtime resolver that observes accepted writes.
Panel users and API callers observe the surfaces. Granted calling-product
repositories remain read-only and require no change in this slice.

### Non-goals

- No profile deletion, rename, clone, bulk edit, revision token, or merge UI.
- No separate effective-staffing calculator or client-side schema validator.
- No new override fields or rows; the current compact override surface remains
  the panel boundary, including preservation of overrides it does not display.
- No profile-selection history, source labels, provenance, transition notices,
  per-call profile labels, or confirmation/acknowledgement workflow.
- No fallback from an invalid selection or profile, and no automatic repair.
- No change to strategy-profile routes, editability, seals, or presentation.
- No CLI selection editor and no calling-product implementation.

### Acceptance

The slice is accepted when panel and API callers can read the same current
catalogue, create a complete profile, edit an existing profile's current
definition without changing its name, and read or replace a run's current
name-and-rigor selection. Profile Edit cannot create or overwrite a differently
named entry; a different name is a Create operation. An omitted selection reads
as the current default at medium for old and new runs. A valid launch choice is
current before autostart; any later completed write before dispatch still wins.
An omitted launch choice creates no retained selection.

Every surface write is validated before acceptance. A rejected catalogue,
selection, or override write leaves the prior current value unchanged. A
profile edit, selection replacement, and override change each govern the next
dispatch inside an active work unit, while a controlled in-flight call retains
its original settings. Opening or saving the selection/catalogue controls does
not manufacture overrides. Clearing an override restores current-profile
control. The panel shows layer presence only—current profile versus override—
and exposes no model-profile origin or history.

The expected implementation remains below roughly 500 changed lines by reusing
the existing catalogue API, run access checks, JSON editor, override dialog,
atomic replacement pattern, and runtime tests, with one edit-context name guard.
A new form framework, client schema validator, event stream, or concurrency
subsystem would exceed the slice rather than justify exceeding the target.

### Risks

- A launch selector applied after autostart could staff the first call from the
  default. The launch contract pins successful selection before process start.
- A panel could copy displayed profile values into the override layer. Focused
  tests require unchanged override bytes unless the operator edits a row.
- A raw profile editor could mistake a changed name for an edit and target a
  different profile. Edit keeps the opened name fixed; Create owns new names.
- A stale browser can overwrite a newer profile or selection. That is the
  declared optimistic last-write-wins posture, and the current value remains
  immediately visible and replaceable.
- A damaged current selection or selected definition could be presented as
  usable. Current-selection reads validate both and show refusal rather than a
  fallback, without hiding the run's generic monitoring view.
- Model and strategy profiles could be confused. Their labels, routes, payloads,
  and regression tests remain distinct.

### Reuse Posture

Operators and API callers are affected: without these surfaces they must accept
the default for the first call or manipulate runtime files, risking unintended
staffing on the next dispatch. That harm is immediate but normally reversible
before a call starts; an in-flight call is intentionally not rewritten. The
reviewed milestone requires panel/API catalogue and current-selection access.

The checked reusable surfaces are Slice 1's catalogue API and validator, Slice
2's selection reader and resolver, the current run-access and error envelopes,
the shared JSON editor, and the existing partial override route and dialog. The
cheapest sufficient addition is one thin run-selection resource, one optional
launch field, thin panel controls, and an edit-context name guard consumed by
Profile Edit. The runtime resolver consumes the resulting current value; no
other machinery has an authorised consumer. Build, review, and maintenance
remain bounded and the UI and route are reversible; omitting the name guard can
misdirect an edit, while history or concurrency machinery would add permanent
cost and contradict the current-settings contract.

### Planning Material Disposition

- **Adopt:** A1/B1's accepted current-state amendment as carried by the reviewed
  skeleton: current selection plus current definition, last write wins, and
  current override precedence.
- **Revise:** the original goal snapshot's binding, old-run opt-out, retained
  definition, attribution, and provenance expectations; they have no authority
  after A1.
- **Reject:** brainstorming and `_drafts` material as independent authority, and
  any profile-specific history, concurrency, recovery, or migration machinery
  not present in the reviewed skeleton.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Catalogue contract | `GET /api/model-profiles` remains the catalogue read and returns HTTP 200 `{"ok":true,"profiles":[...]}` in name order. `POST /api/model-profiles` remains the sole create/edit operation and returns HTTP 200 `{"ok":true,"profile":{...}}`; the body and response are the complete current source document with exactly `name`, `examples`, and `configurations.low/medium/high`. A create supplies a new name; an edit wholly replaces the existing document under that same name. Profile Edit keeps the opened name immutable and cannot create or target a different entry. GET remains available under the existing member posture; POST remains administrative. | `implementation/milestones/model-profiles/skeleton.md:59-61,103-114`; `orchestrator/model_profiles.py:204-294,314-346`; `orchestrator/service.py:2634-2652,3633-3639,3950-3957`; `orchestrator/tests/test_service_api.py:2105-2249` | touch: add panel consumption and the edit-name guard only; do-not-add another catalogue route, partial save, delete, rename, client schema validator, or strategy-profile coupling |
| Current-selection API | `GET /api/runs/{id}/model-profile` returns HTTP 200 `{"ok":true,"selection":{"name":"<name>","rigor":"<rigor>"}}`. `POST` to the same route wholly replaces the current selection from that exact two-key object and returns the same envelope; rigor is exactly `low`, `medium`, or `high`. Both use existing run access; unknown/inaccessible runs retain HTTP 404/403. Absence is returned as `default@medium` without origin metadata or a write. | current-selection surface allocation `implementation/milestones/model-profiles/skeleton.md:15-18,25-31,60-61,108-113`; existing run-resource/access envelopes `orchestrator/service.py:3415-3425,3768-3806,3966-4012` | touch: add one singular run resource; do-not-touch strategy `POST /api/runs/{id}/profile` or add history/per-unit routes |
| Launch selection | New-run `POST /api/runs` may carry `"model_profile":{"name":"<name>","rigor":"<rigor>"}` where rigor is exactly `low`, `medium`, or `high`. A valid supplied value is current before any autostart dispatch; omission writes no selection and therefore reads as `default@medium`. `attach` rejects this launch field; an attached run can be changed afterward through the current-selection resource. | panel/API ordering outcome `implementation/milestones/model-profiles/goal.md:15-28,48-76`; current-selection/default contract `implementation/milestones/model-profiles/skeleton.md:15-18,70-74`; existing attach/start boundary `orchestrator/service.py:1970-2022,2147-2164` | touch: extend new-run input and panel launch choice; do-not-create a launch snapshot, infer project/profile selection, or combine selection mutation with attach |
| Selection validation and write result | A selection contains exactly `name` and `rigor`; `rigor` is exactly `low`, `medium`, or `high`. POST validates the selected current definition before mutation. Malformed, unknown, invalid, or unavailable input returns HTTP 400 `{"ok":false,"error":<non-empty string>}` and preserves prior bytes; invalid/unavailable persisted state on GET returns the common HTTP 500 error envelope. Each accepted replacement is one atomic whole value; the overlapping atomic replacement that completes last wins without lock, CAS, retry, or rollback. | `orchestrator/model_profiles.py:147-186,257-281`; `implementation/milestones/model-profiles/skeleton.md:25-31,68-95`; common error envelopes `orchestrator/service.py:3799-3806,4005-4012`; replacement capabilities `orchestrator/service.py:2523-2535`; `orchestrator/model_profiles.py:314-346` | touch: reuse validation and atomic replacement; do-not-fallback, merge, retain the prior value as authority, or add concurrency machinery |
| Panel contract | The panel presents one catalogue entry per profile with its examples and three rigor configurations; administrators can create a complete current document or edit the opened document with its name immutable. Launch and run settings present profile name plus rigor from the catalogue/current-selection APIs. The existing override editor remains the only panel override control. Opening/saving catalogue or selection controls does not write `acts`; run selection shows `name@rigor`, and override rows show only layer presence (`current profile`/`override`), never source origin or history. Server errors are shown without a client-side semantic fallback. | `implementation/milestones/model-profiles/skeleton.md:37-45,61,97-99`; catalogue shape `orchestrator/model_profiles.py:9-40,47-64`; existing admin state and shared editor `orchestrator/static/panel.html:1100-1182,5529-5554`; existing override UI `orchestrator/static/panel.html:3614-3654,4072-4183` | touch: extend the served panel and shared editor with the edit-name guard; do-not-add a parallel schema validator/effective resolver, expand override authority, or present provenance/history |
| Override surface and precedence | Existing `GET /api/runs/{id}` act data and `PATCH /api/runs/{id}/acts` remain the panel path. PATCH changes supplied rows only; omission preserves hidden and explicit-empty entries, and `null` clears a supplied row so the current profile governs. A present non-empty override remains a whole-act policy above the profile; an explicit empty remains the structural-default choice. | `implementation/milestones/model-profiles/skeleton.md:75-89,110`; `orchestrator/service.py:2440-2535,3136-3139,4020-4024`; `orchestrator/static/panel.html:4072-4183`; `orchestrator/tests/test_service_api.py:1012-1154,1190-1267` | touch: reuse unchanged; do-not-submit inherited values, erase omitted rows, add origin fields, or bypass act authority |
| Next-call visibility and in-flight stability | A successful profile edit, selection replacement, or override change is visible to the next physical dispatch, including within an active work unit. Dispatch resolves current layers once and passes that result to the provider call; later writes do not alter that call. Invalid current state fails before provider invocation without fallback. | `implementation/milestones/model-profiles/skeleton.md:25-31,70-95`; `orchestrator/driver.py:391-465,549-601`; `orchestrator/runners.py:2934-2998`; `orchestrator/tests/test_model_profile_runtime.py:185-225,1830-1901` | touch: surface writes and integration tests only; do-not-change the resolver, cache content, or restart/cancel an in-flight call |
| Isolation and record vocabulary | No model-profile origin, binding, snapshot, identity/hash, version, event, generation, acknowledgement, attribution, provenance, transition, replay, migration, recovery, or history field/route/UI is added. Ordinary agent/model/effort accounting remains unchanged. Strategy `/api/profiles`, strategy run profile changes, artifact seals, and generic execution/accounting/recovery remain unchanged. | `implementation/milestones/model-profiles/skeleton.md:29-35,48-53,93-101,113-118`; `orchestrator/model_profiles.py:1-7`; ordinary resolved call identity `orchestrator/runners.py:2987-2998` | touch: regression tests for exact schemas and route separation; do-not-touch strategy/runtime record machinery or granted repositories |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_service_api.ModelProfileSurfacesApiTest orchestrator.tests.test_service_api.ModelProfilesApiTest.test_list_create_edit_and_validation_contract orchestrator.tests.test_service_api.ActsApiTest.test_panel_distinguishes_and_preserves_explicit_empty_overrides orchestrator.tests.test_service_api.ActsApiTest.test_panel_blank_rows_advertise_layer_semantics orchestrator.tests.test_model_profile_runtime.CurrentModelProfileRuntimeTest.test_profile_selection_and_override_are_last_write_wins`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Current selection reads and replaces whole | `test_current_selection_default_read_and_whole_replace` | Old/new absent selections read exactly `default@medium`; a valid POST returns and persists only the submitted `name` and `rigor`; the next GET matches. | strict |
| Invalid state is loud and non-mutating | `test_current_selection_refusal_preserves_prior_bytes` | Malformed/unknown selection POST returns 400 and preserves prior bytes; malformed/unavailable stored selection or selected profile makes dedicated GET fail with 500 and no fallback. | strict |
| Launch has no first-call race | `test_launch_selection_precedes_autostart_and_omission_stays_default` | A supplied valid choice exists before the start seam is invoked; omission creates no selection sidecar; invalid input creates no run state; attach refuses the field. | strict |
| Access and route separation hold | `test_current_selection_access_and_strategy_route_separation` | Run members and administrators can read/replace current selection according to existing run access; outsiders receive 403, unknown runs 404; strategy `/profile` and `/api/profiles` envelopes are unchanged. | strict |
| Overlap is last-write-wins | `test_concurrent_selection_replacements_are_atomic_and_last_completion_wins` | Readers observe only complete valid objects, each successful writer commits its own whole object, and the atomic replacement completed last is current; no conflict token or history appears. | strict atomic state; optimistic conflict handling |
| Panel and API are one surface | `test_panel_catalogue_selection_and_override_contract` | Served panel uses the pinned catalogue/selection routes, offers admin create/edit plus launch/live name-and-rigor controls, preserves server errors, and does not write acts when only catalogue/selection controls are saved or expose model-profile origin/history. | strict |
| Profile Edit preserves identity | `test_panel_profile_edit_keeps_opened_name` | Editing one entry cannot change the submitted name, create a differently named entry, or replace another entry; Create still accepts a new valid name. | strict |
| Surface writes govern runtime | existing `test_profile_selection_and_override_are_last_write_wins`, extended to use the public writers | Profile edit, API selection replacement, and API override change each alter the next resolution on one live Driver; the already-captured dispatch tuple remains unchanged. | strict |
| Existing override semantics survive | existing `test_panel_distinguishes_and_preserves_explicit_empty_overrides` and `test_panel_blank_rows_advertise_layer_semantics` | Unchanged rows and hidden overrides survive; clear restores profile control; explicit empty remains structural; inherited values never become overrides. | strict |
| Catalogue behavior is reused | existing `test_list_create_edit_and_validation_contract` plus `test_panel_catalogue_selection_and_override_contract` | Panel create/edit round-trips the exact Slice 1 document and server validation; Edit keeps the opened name while Create accepts new names; member/admin access, loud corruption, and strategy-route isolation remain pinned. | strict for non-overlapping writes |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-524`).

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Existing direct consumers:** the service catalogue/run dispatchers and access gates; the panel's shared JSON editor and act-override settings; and Slice 2's current resolver, which observes selection/profile/override writes. **Human/API consumers:** administrators manage catalogue definitions, while authorised run users read/replace selections and overrides. **Not touched:** strategy consumers and granted calling-product code. | `orchestrator/service.py:2634-2652,3415-3425,3633-3639,3768-3806,3945-4030`; `orchestrator/static/panel.html:3614-3654,4072-4183,5529-5554`; `orchestrator/driver.py:436-465,577-601`; boundary `implementation/milestones/model-profiles/skeleton.md:37-53` |
| pinned_facts | The closed facts are the existing catalogue contract and same-name Edit identity; exact current-selection and launch payloads/envelopes/routes; three legal rigors; validation/error/access behavior; atomic last-completed replacement; panel catalogue/selection behavior; unchanged override semantics; next-call/in-flight behavior; and the no-history/no-strategy-change boundary. | `implementation/milestones/model-profiles/skeleton.md:55-101,103-118`; `orchestrator/model_profiles.py:147-186,204-346`; `orchestrator/service.py:2437-2535,2634-2652`; this note's Pinned-Facts Table |
| verification | The focused API class pins default/read/replace, failure atomicity, launch order, access, overlap, same-name Edit identity, panel wiring, and route isolation. Existing catalogue, override, and resolver tests pin the reused contracts. Full unittest discovery remains the closure gate. | `orchestrator/tests/test_service_api.py:1012-1267,2105-2249`; `orchestrator/tests/test_model_profile_runtime.py:185-225,1830-1901`; `orchestrator/README.md:522-524`; this note's Verification Contract |
| reuse_posture | **Checked/reused:** validated whole catalogue, current selection resolver, atomic whole-file saves, run access/error envelopes, partial acts route/dialog, and shared syntax-only JSON editor. **Cheapest sufficient:** one run selection resource, optional launch field, thin panel controls, and one edit-context name guard; documentation alone cannot make the mandated surface usable. **Remaining machinery/consumer:** the current selection writer read by Slice 2 and the guard consumed by Profile Edit. **Lifecycle:** no migration or background process; additive and reversible, while omitting the guard risks misdirected staffing and history/CAS machinery would cost more while violating A1. | `orchestrator/model_profiles.py:147-186,257-346`; `orchestrator/driver.py:391-465`; `orchestrator/service.py:2437-2535,3415-3425,3799-3806,4005-4030`; `orchestrator/static/panel.html:4072-4183,5529-5554`; authority `implementation/milestones/model-profiles/skeleton.md:43-53,59-61,132-160` |
| enforceability | **Catalogue Edit identity:** Profile Edit retains the opened name and the focused panel test proves no other entry changes. **Selection shape/availability:** `validate_selection` plus `resolve_selection`. **Atomic visibility/LWW:** reuse validated same-directory replacement without cache. **Next-call/in-flight:** existing late dispatch resolver and captured call tuple. **Override non-promotion/clear:** existing PATCH semantics and changed-row dialog. **Access/errors:** existing run/admin gates and common envelopes. **No history/isolation:** exact response/state schemas plus route/UI/event-census regressions. **Launch order:** current selection must be committed before the existing autostart seam. No stronger crash durability, conflict detection, acknowledgement, or recovery guarantee is asserted because no authorised mechanism expresses one. | `orchestrator/model_profiles.py:147-186,314-346`; `orchestrator/service.py:2147-2164,2437-2535,3415-3425,3799-3806,3945-4030`; `orchestrator/driver.py:455-465,549-601`; `orchestrator/runners.py:2934-2998`; `orchestrator/static/panel.html:4072-4183,5529-5554` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Profile Edit preserves the opened identity | Keep the opened catalogue name as the immutable Edit identity while the shared editor handles the remaining complete document. | `test_panel_profile_edit_keeps_opened_name` attempts a changed name and proves neither a new entry nor a different existing entry is written; Create remains distinct. |
| Exact current selection and selected-definition readiness | Reuse `validate_selection` and `resolve_selection` (`orchestrator/model_profiles.py:147-186`), with the dedicated read/write route under existing run access (`orchestrator/service.py:3415-3425`). | Direct API cases cover every shape/rigor/name failure, selected-source corruption, default absence, and prior-byte preservation. |
| Whole, immediate, last-completed replacement | Reuse validation-before-write and unique same-directory atomic replacement (`orchestrator/model_profiles.py:314-346`; `orchestrator/service.py:2523-2535`); the resolver retains no selection cache (`orchestrator/driver.py:436-465`). | Controlled overlapping writers/readers see only whole values, and ordered atomic-completion release pins the winner. |
| Launch selection is current before autostart | The new-run path already completes state setup and registry registration before its autostart seam (`orchestrator/service.py:2147-2164`); the selection write is a required successful precondition of that seam. | A mocked start observes the selection already current; invalid input leaves no state, and omission leaves no sidecar. A later completed pre-dispatch write still wins. |
| Next-call visibility without in-flight mutation | Current layers are read for each dispatch (`orchestrator/driver.py:455-465,549-601`) and copied into call-local values before provider invocation (`orchestrator/runners.py:2934-2998`). | One live driver observes each public write on its next dispatch while a blocked in-flight provider retains its first tuple. |
| Override presence, clear, and hidden-row preservation | Existing strict partial mutation and atomic writer (`orchestrator/service.py:2470-2535`) plus changed-row panel submission (`orchestrator/static/panel.html:4072-4183`). | Existing API/panel tests remain green and a selection-only action leaves `acts` bytes unchanged. |
| Panel/API semantic identity without a parallel validator | The panel consumes the catalogue and selection APIs and reuses the syntax-only JSON editor (`orchestrator/static/panel.html:5529-5554`); server validators remain authoritative (`orchestrator/model_profiles.py:147-346`). | Served-panel contract pins routes/payloads and server-error display; API tests pin semantics and access. |
| No model-profile history/provenance and no strategy drift | Exact two-key selection and three-key catalogue schemas, plus the existing generic call identity only (`orchestrator/model_profiles.py:147-170,204-254`; `orchestrator/runners.py:2987-2998`). | Schema, route, panel-text, state-key, and event-census checks reject added profile metadata/history and recheck strategy envelopes unchanged. |

Any implementation that lets Profile Edit target a name other than the opened
entry, introduces another resolver/store, promotes inherited values into
overrides, starts before a supplied selection is current, silently falls back,
or adds model-profile history/provenance does not deliver this slice.
