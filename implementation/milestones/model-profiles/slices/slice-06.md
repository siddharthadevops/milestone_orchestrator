# Slice 06 — Strategy configurator panel

## Register 1 — Intent

### What this slice builds

This slice gives operators a normal form for creating, inspecting, and editing
review strategies. Instead of writing JSON, they choose one legal value for
each known strategy decision. Active choices are presented as operative;
reserved choices are clearly marked as retained but non-operative.

The form produces a complete set of catalogued decisions. Opening and saving
either canonical starting strategy without changes preserves its complete
meaning. Existing partial custom strategies remain inspectable, but the form
does not silently guess their missing decisions: the operator must choose those
values before saving a complete replacement.

The compatibility strategy remains selectable and inspectable, not a template
or set of composable controls. The panel may edit its descriptive metadata only
while carrying its semantic content through unchanged; the existing API remains
the authority for whether that content is valid.

### Ownership and boundary

This slice owns the strategy catalogue panel, its decision controls, and
truthful support labels in the existing launch and active-run strategy pickers.
It owns only the browser mapping between the already-published catalogue and
the already-existing whole-document save operation.

It does not add a strategy route, store, validator, decision, legal value, or
runtime consumer. It does not change how a run retains or adopts a strategy,
how concurrent edits settle, or how active decisions behave. Model profiles,
artifact seals, review flow, generic execution/accounting/recovery, and calling
products are outside this slice.

### Guarantee posture

- **Strict:** the panel obtains decision names, legal values, and support status
  from the same catalogue used by the API validator. A panel-created strategy
  contains every catalogued decision. Create is unavailable and submits nothing
  when its name exactly matches a strategy in the fetched catalogue; Edit is
  the panel operation that replaces an existing exact name. Without a later
  overlapping write, a successful save is immediately reflected by a fresh
  catalogue read. Existing non-decision content survives an edit, canonical
  strategies round-trip exactly, and every surface that shows a reserved choice
  calls it non-operative.
- **Optimistic:** concurrent whole-document edits may overwrite one another;
  the current file is one complete accepted replacement, with no completion-
  order promise. There is no merge, lock, conflict warning, CAS, retry,
  rollback, or lost-update protection.
- **Eventual:** this slice introduces none. Catalogue reads and saves are
  synchronous. The existing active-run strategy-change boundary remains
  unchanged.
- **Best-effort:** transport interruption and abrupt host/filesystem failure
  retain the repository's existing durability and recovery posture. A failed
  load or save remains visibly failed; the panel supplies no cached or inferred
  strategy as fallback.

### Dependencies and consumers

Slice 4 supplies editable whole-document strategy storage and retained run
semantics. Slice 5 supplies the shared decision inventory, support status,
legal values, validation, canonical seeds, and compatibility fence.

The direct consumer changed here is the served panel: catalogue viewers,
administrators creating or editing definitions, new-run selectors, and
active-run strategy changes. The existing strategy API and store receive the
same whole documents as before. Granted calling-product repositories remain
read-only and need no change.

### Non-goals

- No free-form JSON strategy editor or second client-side strategy schema.
- No new or renamed strategy decision, value, status, route, or error code.
- No execution support for reserved choices and no new review machinery.
- No strategy delete, rename, clone, template, history, provenance, migration,
  lock, CAS, merge, retry, rollback, or reconciliation feature.
- No automatic completion or rewrite of an existing partial definition.
- No change to strategy selection, retained content/identity, or transition
  delivery.
- No model-profile, override, artifact-seal, family-rotation, accounting,
  recovery, or calling-product change.

### Acceptance

The slice is accepted when an authenticated catalogue reader can inspect every
strategy and its decisions, while only an administrator is offered create/edit
actions. Creating a strategy uses ordinary fields plus one choice for every
catalogued decision; no semantic JSON authoring is required. Create is blocked
without submitting when the entered name already exists in the fetched
catalogue. Saving is also blocked until every choice is explicit, then the
existing API either accepts the whole document or returns an error that remains
visible in the open form.

Editing preserves the opened identity and any valid non-decision stage content.
Opening and saving each canonical composable strategy unchanged yields the same
complete semantic content and identity. A partial custom strategy shows its
missing decisions as unresolved and leaves its source untouched until the
operator explicitly completes and saves it. The compatibility strategy remains
inspectable and selectable, offers no composable semantic controls, and cannot
seed or become an ordinary composed strategy. A metadata-only save carries its
semantic content back unchanged and accepts the server's judgment.

The catalogue view, launch selector, and active-run change dialog all use the
same support status. Reserved choices are visibly non-operative wherever their
values appear. A catalogue load failure disables strategy authoring and remains
visible rather than producing stale controls. Existing API validation, access,
run retention, active-run delivery, and strategy runtime tests remain green.

The expected implementation remains below roughly 500 changed lines. It is one
panel surface plus focused tests over existing API helpers and modal patterns;
no backend, storage, migration, or dependency work is justified.

### Risks

- A hard-coded panel inventory could drift from validation. The panel contract
  and test require every rendered decision and option to come from one fetched
  catalogue response.
- Flattening the nested stage decision could discard valid fixed stage content.
  Canonical round-trip tests compare the complete semantic object and identity.
- Filling omissions automatically could change a partial custom strategy
  without an operator decision. An incomplete-edit test requires explicit
  completion and byte preservation before save.
- Reserved choices could still look operative in launch or repoint summaries.
  A presentation test covers the catalogue, launch, and active-run surfaces.
- Treating compatibility content as a template would bypass its fence. The
  configurator test refuses composition while preserving metadata edits.
- Sending derived display fields back as source could pollute the stored
  document. Exact request-shape tests separate editable fields from derived
  identity.
- Closing the form on a rejected save could suggest success. Failure tests keep
  the form open, show the server error, and confirm the prior definition.
- Treating Create as another label for whole-document replacement could erase
  a loaded reusable definition. The Create test requires a new fetched name and
  proves that a known exact name submits nothing; overlapping catalogue changes
  remain under the optimistic save posture.

### Reuse Posture

The affected party is the operator: without this slice they must author
strategy JSON and may still see reserved settings described as if they worked.
That harm is local and reversible before selection, but it can create a false
review expectation once a strategy is chosen. The reviewed skeleton requires a
decision-by-decision configurator and truthful support status.

The checked reusable surfaces are the shared decision inventory and validator,
whole-document strategy read/save API, atomic store, canonical source content,
compatibility fence, access gates, panel request/error helpers, catalogue cards,
and modal patterns. The cheapest sufficient option is one response-driven panel
form that posts to the existing save route and reuses the same fetched status in
launch and repoint summaries. The fetched profile names also supply the
new-name check for Create; Edit alone submits a loaded exact name, without a new
route or stronger concurrency promise. The only new machinery is reversible
browser UI consumed by operators; it has no migration, service, or operating
cost. Omitting it preserves manual JSON, misleading labels, and ordinary Create
replacement of a loaded definition, while a new route, schema, store, browser
test framework, or concurrency system would cost more without an authorised
outcome.

### Planning Material Disposition

- **Adopt:** the non-canonical planning outcome that strategies are configured
  through known decisions, active/reserved status is truthful everywhere, and
  canonical composable strategies reproduce their complete content.
- **Revise:** any planning implication that fixed stage structure is another
  operator decision; it is preserved when present but is not added to the
  composable inventory. Partial source documents are completed only by explicit
  operator choices.
- **Reject:** planning material as independent authority, free-form strategy
  authoring as the panel experience, compatibility cloning, a new panel-side
  compatibility fence, and implementation of dormant reserved machinery.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Strategy catalogue API | Reuse `GET /api/profiles`: HTTP 200 `{"ok":true,"profiles":[...],"decisions":[...]}`; stored corruption remains HTTP 500 `{"ok":false,"error":<non-empty string>}`. Reuse administrative `POST /api/profiles`: HTTP 200 `{"ok":true,"profile":{...}}`; invalid input remains HTTP 400 and non-admin mutation HTTP 403 with the common non-empty error envelope. Overlapping accepted saves may overwrite one another but expose only a complete replacement; no completion-order promise is added. No route is added. | slice allocation `implementation/milestones/model-profiles/skeleton.md:63-66,97-101,115-117`; views/save `orchestrator/service.py:2613-2646`; access/routes/errors `orchestrator/service.py:3652-3660,3698-3703,4026-4029,4088-4095`; atomic save `orchestrator/profiles.py:246-285`; member access `orchestrator/tests/test_service_projects.py:353-392` | touch: panel consumption only; do-not-touch route, envelope, access gate, store, or validator |
| Decision controls | Render exactly the six returned decisions: active `stages[0].loop` = `family_until_clean`; active `p3_defer_max_risk` = `low`/`medium`/`high`/`xhigh`; active `p3_reclassify_debt` = `false`/`true`; active `doc_register` = `dense`/`lay+hard-table`; reserved `fuser_discard` = `evidence`/`evidence+concur`; reserved `final_open_pass` = `false`/`true`. Names, order, values, and status come from `decisions[]`, not a panel copy. Reserved controls remain selectable and say non-operative. | `implementation/milestones/model-profiles/skeleton.md:19-23,63-64,115-116`; shared inventory `orchestrator/profiles.py:44-71`; exact test `orchestrator/tests/test_profiles.py:270-287`; API projection `orchestrator/service.py:3698-3703` | touch: response-driven controls and labels; do-not-hard-code another semantic inventory or imply reserved execution |
| Configurator document | Create posts exactly editable source fields `{name, version, description, profile}` and requires one explicit legal value for every returned decision. It is unavailable and posts nothing when `name` exactly matches any profile in the fetched catalogue; Edit is the replacement path for an existing exact name. Edit keeps the opened `name`, preserves `version`/`description` unless changed, preserves valid non-decision stage content already present, and never posts derived `hash` or legacy `sealed`. Missing decisions in a partial source remain unresolved until explicitly chosen; opening/cancelling or a rejected save changes no source. | complete/configurator authority `implementation/milestones/model-profiles/skeleton.md:19-23,25-35,64,97-101`; source/view split `orchestrator/profiles.py:7-24,161-188,246-285`; API view `orchestrator/service.py:2613-2646`; partial validation `orchestrator/tests/test_profiles.py:310-370` | touch: dedicated fields and decision controls; do-not-use the shared raw-JSON textarea, auto-fill omissions, replace a fetched name through Create, rename on Edit, submit display identity, or add a client schema |
| Canonical and fixed content | Opening and saving `strict` or `light` unchanged preserves the complete semantic object and semantic hash, including an existing fixed `stages[0].actions[0].scope: "open"`. That fixed action is preserved content, not a seventh control and not manufactured for a new configuration. | `implementation/milestones/model-profiles/skeleton.md:63-64,115-116`; fixed/content authority `orchestrator/profiles.py:26-29,96-128,333-376`; round-trip proof `orchestrator/tests/test_profiles.py:289-307`; non-composability API test `orchestrator/tests/test_service_api.py:2370-2380` | touch: lossless edit mapping; do-not-expose or duplicate the fixed action as a decision |
| Legacy fence | `legacy` remains selectable and inspectable but is absent from the composable decision inventory. The panel offers no semantic decision editor, Create-from, or clone path. A metadata-only save carries the fetched semantic content unchanged and relies on the existing POST validator; Slice 6 adds no compatibility rule. | `implementation/milestones/model-profiles/skeleton.md:63-64,115-116`; catalogue/fence seams `orchestrator/profiles.py:44-71,131-188,378-399`; existing regression `orchestrator/tests/test_profiles.py:394-408`; HTTP selection fence `orchestrator/tests/test_service_api.py:2498-2520` | touch: truthful read-only semantic presentation and metadata form; do-not-compose, clone, alter semantic content in the panel, or add another fence |
| Panel surfaces and isolation | A member-visible strategy catalogue exposes inspect controls; create/edit controls are admin-only. The catalogue, launch selector, and active-run repoint summary use the fetched support status, and any shown reserved value is marked non-operative. Existing launch `profile` input and `POST /api/runs/{id}/profile` payload/behavior are unchanged. Model profiles, run-retained strategy records, runtime decisions, artifact seals, and granted repositories are untouched. | panel/API parity `implementation/milestones/model-profiles/skeleton.md:37-53,64,97-101,117-118`; access pattern `orchestrator/static/panel.html:1203-1221`; current launch/repoint surfaces `orchestrator/static/panel.html:616-619,4452-4546,4802-4851`; request/error helpers `orchestrator/static/panel.html:2314-2318,5305-5310`; run route `orchestrator/service.py:2718-2751,4042-4083` | touch: catalogue entry point, configurator, and truthful summaries; do-not-change selection payloads, run semantics, model-profile UI, backend runtime, or other repositories |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_service_api.StrategyConfiguratorPanelTest orchestrator.tests.test_service_api.ProfilesDecisionApiTest orchestrator.tests.test_service_api.ProfilesApiTest.test_creation_racing_edit_retains_one_complete_definition orchestrator.tests.test_profiles.StrategyDecisionCatalogueTest orchestrator.tests.test_profiles.StrategyDecisionValidationTest orchestrator.tests.test_profiles.TestEditability.test_used_profile_edit_replaces_content_without_first_use_mutation`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| One API-driven form | `test_configurator_uses_catalogue_inventory_and_access` | The served panel offers catalogue inspection to a member and mutation only to an admin; each response decision appears once with only its returned values/status, and no strategy semantic JSON textarea or second inventory is present. | strict |
| Create emits one complete new source document | `test_configurator_create_posts_complete_decisions` | With all choices explicit and a name absent from the fetched catalogue, Create posts only `name`, `version`, `description`, and a semantic object containing every returned decision; the existing POST accepts it and the next GET returns matching content/hash. An exact fetched name leaves Create unavailable, submits no request, and preserves that definition. Save also remains unavailable while any choice is unresolved. | strict for fetched state; optimistic conflict handling |
| Edit preserves identity and non-decision content | `test_configurator_edit_preserves_opened_name_and_stage_content` | Editing one value replaces that opened definition only; its fixed valid stage content survives, derived fields are not submitted, and cancel changes nothing. | strict |
| Canonical strategies round-trip | `test_configurator_strict_and_light_round_trip_exactly` plus existing `test_strict_and_light_decision_round_trip_is_semantically_exact` | Opening and saving each canonical composable strategy unchanged yields identical semantic content and the same semantic hash, including fixed open-stage content. | strict |
| Partial sources are not silently completed | `test_configurator_partial_edit_requires_explicit_completion` | Missing decisions render unresolved; opening, cancelling, or attempting incomplete Save leaves source bytes unchanged; after explicit choices, the accepted replacement contains every catalogue decision. | strict |
| Legacy stays fenced | `test_configurator_legacy_is_metadata_only` plus existing `test_legacy_is_selectable_equivalent_and_not_composable` | Legacy semantic controls and clone paths are absent; a metadata edit posts the fetched semantic content unchanged, and the existing server remains the sole validity authority. | strict |
| Reserved status is truthful everywhere | `test_strategy_surfaces_mark_reserved_values_non_operative` | Catalogue cards, launch hints, and active-run repoint hints use the fetched status and never describe `fuser_discard` or `final_open_pass` as operative. Existing reserved no-effect regression remains green. | strict |
| Failures are visible and non-mutating | `test_configurator_load_and_save_failures_do_not_fallback` | A failed GET shows its server error and offers no stale authoring controls; a rejected POST leaves the form open, shows the error, and preserves the prior definition. | strict response; best-effort transport |
| Concurrent edits keep existing posture | existing `test_used_profile_edit_replaces_content_without_first_use_mutation` and `test_creation_racing_edit_retains_one_complete_definition` | Each accepted save is a complete definition and readers/retained bindings obtain one complete value; overlapping saves have no merge, warning, or relative-completion guarantee. | optimistic conflict handling; strict whole value |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-524`).

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Direct:** the served panel's catalogue, launch selector, and active-run repoint dialog; the existing strategy GET/POST receives their reads and saves. **People:** authenticated members inspect/select and service administrators create/edit. **Untouched:** strategy store/runtime semantics, model profiles, seals, and granted repositories. | `orchestrator/static/panel.html:616-619,1203-1221,4452-4546,4802-4851`; `orchestrator/service.py:2613-2646,3698-3703,4026-4029,4042-4083`; boundary `implementation/milestones/model-profiles/skeleton.md:37-53,64-66` |
| pinned_facts | The closed facts are the existing route/envelopes/access; the exact six-entry response-driven inventory; complete new-name-only Create and same-name lossless Edit with no JSON authoring; explicit completion of partials; exact canonical round-trip; metadata-only legacy handling; truthful reserved labels on all panel strategy surfaces; and isolation from runtime/model-profile/seal work. | `implementation/milestones/model-profiles/skeleton.md:19-23,55-66,97-118`; `orchestrator/profiles.py:44-71,96-188,246-285,333-399`; this note's Pinned-Facts Table |
| verification | One focused panel/API class pins access, response-driven controls, complete new-name-only Create, lossless Edit, partial handling, legacy, truthful status, and visible failures. Existing catalogue/validation/API tests pin the reused inventory, server refusal, canonical identity, reserved no-effect behavior, and fence. Full unittest discovery is the closure gate. | `orchestrator/tests/test_profiles.py:270-408`; `orchestrator/tests/test_service_api.py:1937-1964,2056-2091,2354-2406,2498-2606`; `orchestrator/README.md:522-524`; this note's Verification Contract |
| reuse_posture | **Checked/reused:** shared inventory/validator, fetched profile names, whole read/save, atomic replacement, canonical content/hash, legacy fence, access gates, request/error helpers, catalogue cards, and modal patterns. **Cheapest sufficient:** one API-driven form whose Create action rejects a fetched exact name, plus a shared status renderer; documentation alone cannot replace hand-authored JSON or fix the live labels. **New machinery/consumer:** reversible panel controls used only by operators. **Lifecycle:** no backend, dependency, migration, service, or stronger concurrency scheme; omission preserves misleading/manual operation and ordinary Create replacement of a loaded definition, while parallel schema/routes/browser framework/concurrency machinery cost more without authority. | `orchestrator/profiles.py:44-71,161-188,246-285`; `orchestrator/service.py:2613-2646,3698-3703,4026-4029`; `orchestrator/static/panel.html:1096-1107,1203-1221,2314-2318,4357-4378,5305-5310`; authority `implementation/milestones/model-profiles/skeleton.md:43-53,64-66,132-160` |
| enforceability | **Inventory/status/options:** one shared catalogue is already serialized by GET and server validation. **Completeness/no JSON:** the only new mechanism is a required control generated for each returned decision; focused served-panel/API tests compare its submitted key/value set to that same response. **Lossless edit/canonical identity:** GET supplies full content/hash and existing semantic hashing checks the result. **Invalid/non-mutating:** server validation precedes atomic replacement and panel errors use the existing throwing request helper. **Legacy:** existing server fence plus metadata-only UI; no panel-side fence. **Access:** existing member read/admin write gates. **Concurrency:** existing atomic whole replacement, with no stronger guarantee. **Isolation:** unchanged runtime/retention regressions. No unexpressible stronger guarantee is asserted. | `orchestrator/profiles.py:44-71,74-188,246-303`; `orchestrator/service.py:2613-2646,3652-3660,3698-3703,4026-4029,4088-4095`; `orchestrator/static/panel.html:1203-1221,2314-2318,5305-5310`; `orchestrator/tests/test_profiles.py:270-408`; `orchestrator/tests/test_service_api.py:1937-1964,2056-2091,2354-2606` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Panel inventory, options, and status cannot drift from the API | The shared catalogue is the exact `decisions` member of the existing GET (`orchestrator/profiles.py:44-71`; `orchestrator/service.py:3698-3703`). | The panel test compares rendered controls and submitted values with a fetched response, including boolean types and reserved labels. |
| Panel-created documents are complete and new without a parallel validator | The fetched closed inventory supplies the required control set and fetched profiles supply existing exact names; existing document validation remains authoritative (`orchestrator/profiles.py:86-188`). | Create stays disabled for unresolved controls or an exact fetched name. The panel test proves the existing-name case submits nothing and preserves the definition; the new-name case compares submitted semantic keys with the fetched inventory and then exercises the real POST. |
| Edits preserve source identity and fixed valid content | GET carries the complete semantic content and derived hash (`orchestrator/service.py:2613-2629`); the store hashes semantic content and atomically replaces one named file (`orchestrator/profiles.py:74-83,246-285`). | Same-name edit and canonical round-trip checks compare complete semantic objects/hashes and verify cancel/rejection byte preservation. |
| Partial profiles are never silently completed | Existing validation deliberately accepts known partial content (`orchestrator/profiles.py:131-158`; `orchestrator/tests/test_profiles.py:320-370`), so the panel must represent absence explicitly rather than infer values. | A partial source remains byte-identical until every missing decision is explicitly chosen and a successful POST completes it. |
| Legacy cannot become composable through the panel | The shared inventory excludes compatibility content while the response supplies its source for inspection (`orchestrator/profiles.py:44-71,131-188`). | The panel exposes no semantic edit/clone path, posts unchanged semantic content for metadata edits, and leaves all validity decisions to the existing server. |
| Errors and access stay truthful | POST retains the service admin gate and common error envelope (`orchestrator/service.py:3652-3660,4026-4029,4088-4095`); the panel request helper throws the server error (`orchestrator/static/panel.html:2314-2318`). | Member/admin tests pin offered actions and HTTP outcomes; failure tests require visible errors, an open form, and unchanged source. |
| Existing strategy/runtime behavior remains isolated | Launch and repoint keep their current payloads and retained-pair route (`orchestrator/static/panel.html:4505-4546,4802-4851`; `orchestrator/service.py:2718-2751`). | Existing creation, repoint, reserved no-effect, interpreter, model-profile, and artifact-seal regressions remain in the focused/full gates. |

Any implementation that adds another strategy schema or route, uses free-form
semantic JSON, hard-codes decision status/values, silently fills a partial
source, replaces a fetched existing name through Create, loses canonical or
fixed content, composes `legacy`, presents reserved content as operative,
weakens access/errors, or alters runtime/model-profile/artifact-seal behavior
does not deliver this slice.
