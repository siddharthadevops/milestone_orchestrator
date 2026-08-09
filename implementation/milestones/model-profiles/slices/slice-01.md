# Slice 01 — Model-profile store and seeded default

## Register 1 — Intent

### What this slice builds

This slice gives operators and calling products one dependable catalogue of
reusable model profiles. Each profile names a kind of work, carries compact
matching examples, and contains a staffing choice for each of the three rigors:
low, medium, and high. A caller can list the catalogue and create or edit a
complete definition through the HTTP API.

The catalogue starts with an ordinary profile named `default`. Its medium
choice preserves the staffing a new run receives today. The seed is a starting
definition, not protected product data: the operator may edit it, and later
service starts never replace that edit. This slice stores that source; Slice 2
reads its current content at resolution time.

### Ownership and boundary

This slice owns the model-profile document, its validation, persistent
create/edit/list behavior, the missing-only `default` seed, and the catalogue's
HTTP surface. It keeps model staffing separate from review strategy.

It does not select a profile for a run, resolve an act from one, change
overrides, add panel controls, or migrate existing runs. It adds no binding,
snapshot, attribution, provenance, or history machinery. It does not alter
strategy configurations or their routes, seals, seeds, or runtime
interpretation.

### Guarantee posture

- **Strict:** a successful non-overlapping save is complete, immediately
  listable, and survives a normal service restart; invalid input changes
  nothing; a successfully initialized service has a valid `default`; existing
  seed edits are never overwritten; `default` at medium is behaviorally equal
  to today's default staffing.
- **Optimistic:** none. The API introduces no revision token or lost-update
  detection.
- **Eventual:** none. A successful response reports committed catalogue state;
  no background convergence is promised.
- **Best-effort:** ordering between genuinely overlapping edits and persistence
  through abrupt host or filesystem failure are not promised. No runtime call
  delivery is part of this slice.

### Dependencies and consumers

This is the first model-profile slice and has no earlier-slice dependency. It
depends only on the current act configuration vocabulary, the current default
staffing, local persistent storage, and the existing service's route and error
envelope.

Its current runtime consumer is the HTTP service: startup ensures the seed and
GET/POST serve the catalogue. API callers can observe the result immediately.
No existing driver, panel, or granted calling-product code consumes model
profiles yet. Slices 2 and 3 are the declared later consumers of this store.

### Non-goals

- No run-creation or mid-run model-profile selection.
- No profile-to-act resolution, precedence, current selection, or runtime call
  integration.
- No per-act override or `acts.json` change.
- No panel catalogue or editor.
- No deletion, rename, clone, source-version history, conflict token, or bulk
  transaction API.
- No executor probing and no new model, effort, family, cost, or risk
  vocabulary.
- No change to strategy-profile storage, strategy routes, strategy seals,
  artifact seals, review machinery, or existing-run staffing.

### Acceptance

The slice is accepted when a complete profile can be created, listed, replaced
under the same name, and read after a normal restart; every malformed or
incomplete document is refused without altering the prior definition; no bad
stored definition silently disappears from a listing; startup creates
`default` only when absent; an operator edit of `default` survives another
startup; and a focused equivalence check proves the seeded medium choice yields
the same effective staffing as today's defaults for every configurable act,
including fixed and derived seats.

The expected implementation is below the roughly 500-line changed-code target:
one narrow store/validator, two route branches, one seed hook, and focused
tests. A migration, generic configuration framework, or concurrency subsystem
would exceed this slice rather than justify exceeding the target.

### Risks

- A permissive document could accept a field no act honors. Closed schema and
  authority-matrix tests make that a rejected input instead of a silent no-op.
- The seed could drift when current defaults change. The behavioral equivalence
  check makes that drift visible in the test suite.
- An invalid edit could destroy the last good definition. Validation-before-
  commit and an unchanged-prior-value test pin the failure behavior.
- A damaged stored file could vanish from the catalogue and create false
  confidence. Listing fails visibly instead of skipping it.
- Two administrators can still overwrite one another if they save
  concurrently. Adding revision machinery is disproportionate here; callers
  receive no concurrency guarantee, and a later need can add one reversibly.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Model-profile document | The stored and API-visible source document has exactly `name`, `examples`, and `configurations`. `name` is a non-empty alphanumeric/`-`/`_` key. `examples` is a required ordered array of non-empty strings; every item is at most five whitespace-separated words. `configurations` has exactly `low`, `medium`, and `high`; each value is an act map and may omit acts. There is no source `version`, `sealed`, or implicit fourth rigor. | `implementation/milestones/model-profiles/skeleton.md:13-19,61-63,70,151-153`; `implementation/milestones/model-profiles/goal.md:48-76`; name precedent `orchestrator/profiles.py:61-75` | touch: add one closed model-profile schema; do-not-add descriptive/version/seal lifecycle machinery |
| Per-rigor act vocabulary | An act map may name only `skeletoner`, `drafter`, `implementer`, `review_codex`, `review_claude`, `fixer`, `consultation`, `reclassifier`, and `brainstorming_counterpart`. `skeletoner`, `drafter`, `implementer`, `fixer`, and `reclassifier` accept a family-policy string or a non-empty object containing only `agent`, `model`, and/or `effort`. `review_codex`, `review_claude`, and `brainstorming_counterpart` accept a non-empty object containing only `model` and/or `effort`. `consultation` accepts only a family-policy string. Every carried value is a non-empty string. Omitted acts retain the existing act-specific assignment/derivation and then family default; no profile field expands an act's authority. | `implementation/milestones/model-profiles/skeleton.md:86-118,147-153`; `orchestrator/service.py:2361-2363,2394-2426`; `implementation/milestones/model-profiles/goal.md:57-66` | touch: validate this exact surface; do-not-touch fixed/derived family rules or accept dead fields |
| Identifier posture | The seed uses only the installed model and effort vocabulary. The store adds no identifiers and no executor-availability whitelist stricter than today's short-string act input; structural act/field validation is still strict. | `implementation/milestones/model-profiles/skeleton.md:147,153,157`; `orchestrator/driver.py:77-91`; `orchestrator/static/panel.html:4349-4356` | do-not-touch executor identifiers or turn catalogue persistence into capability probing |
| Catalogue API | `GET /api/model-profiles` returns HTTP 200 with `{"ok":true,"profiles":[...]}` sorted by name. `POST /api/model-profiles` is the sole create/edit operation: a complete valid body creates or wholly replaces the definition under its `name`, returns HTTP 200 with `{"ok":true,"profile":{...}}`, and is administrative under the existing service access posture. There is no PUT, PATCH, DELETE, rename, or per-name route in this slice. | `implementation/milestones/model-profiles/skeleton.md:70,156`; existing route/envelope/access pattern `orchestrator/service.py:3427-3428,3721-3724`; `orchestrator/README.md:323-324` | touch: add the two route branches; do-not-touch `/api/profiles` |
| Loud rejection and save visibility | Malformed, incomplete, unknown-key, unknown-act, or disallowed-field POST input returns HTTP 400 with `{"ok":false,"error":<non-empty string>}` and leaves any prior definition unchanged. A persisted invalid document makes catalogue GET fail with HTTP 500; it is never silently omitted. A successful non-overlapping save replaces one whole definition before returning. No new named error-code vocabulary is introduced. | `implementation/milestones/model-profiles/skeleton.md:70,151-153,178`; `orchestrator/service.py:2391-2426,3772-3779`; atomic-save precedent `orchestrator/profiles.py:131-148`; silent-skip behavior not to copy `orchestrator/profiles.py:108-121` | touch: validate before whole replacement and surface stored corruption; do-not-fallback, partially merge, or skip invalid definitions |
| Seeded default | Successful service initialization ensures one profile named `default` only when absent. All three rigors exist. The initial `medium` configuration is behaviorally identical to `DEFAULT_CONFIG` acts plus `model_defaults` resolution for every configurable act and applicable fixed/derived context. Re-running seed initialization never changes any existing `default`, including an operator edit. Absence of a selection means current `default@medium` once Slice 2 integrates the runtime; no run consults the seed in this slice. | `implementation/milestones/model-profiles/skeleton.md`; `orchestrator/driver.py`; missing-only seed precedent `orchestrator/profiles.py`; startup seam `orchestrator/service.py` | touch: add a strict missing-only model seed and equivalence gate; do-not-overwrite or change `DEFAULT_CONFIG` |
| Slice boundary | Slice 1 stops at the source catalogue and API. It emits no binding/change events and retains no snapshot or attribution: current runtime resolution is Slice 2; current-selection and override presentation is Slice 3; strategy work is Slices 4-6. Existing `/api/profiles`, `/api/runs`, `acts.json`, driver act resolution, panel behavior, and strategy seals remain behaviorally unchanged in this slice. | `implementation/milestones/model-profiles/skeleton.md`; `implementation/milestones/model-profiles/goal.md` as superseded by A1 for model profiles | touch only the additive catalogue/store/API/test surfaces; do-not-pull later slices forward |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_model_profiles orchestrator.tests.test_service_api.ModelProfilesApiTest`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| The source schema is closed and complete | `test_document_contract_and_three_rigors` | A valid document with all three rigor maps round-trips; a missing/extra top-level key, missing/extra rigor, invalid name, malformed examples, or example over five words is rejected. | strict |
| Act entries cannot exceed existing authority | `test_per_act_authority_matrix` | Every allowed string/object form is accepted; unknown acts/fields, empty entries, agent on fixed reviews or counterpart, and model/effort on consultation are rejected; omitted acts remain legal. | strict |
| Create/edit/list is whole and loud | `test_store_create_edit_list_and_failure_atomicity` | Names list in order; a valid same-name save wholly replaces the prior source; invalid edit leaves it equal to the prior source; one invalid stored document makes listing fail instead of dropping it. | strict for non-overlapping calls |
| The seed is editable but never re-seeded | `test_default_seed_is_missing_only` | First initialization creates `default` with all three rigors; after a valid edit, another initialization preserves the edited document exactly; an invalid existing source is reported rather than healed. | strict |
| The compatibility seed matches current staffing | `test_default_medium_matches_current_effective_staffing` | Across all nine configurable acts and both origin families where relevant, the seeded medium choice produces the same agent/model/effort or derived policy as current `DEFAULT_CONFIG` plus `model_defaults`, including review, counterpart, and consultation constraints. | strict |
| The HTTP contract matches the store | `test_list_create_edit_and_validation_contract` | GET and valid POST return the pinned 200 envelopes; POST is administrative; invalid POST returns the pinned 400 envelope without mutation; stored corruption yields 500; strategy `/api/profiles` responses remain unchanged. | strict |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-524`). Slice 2 adds current runtime resolution for
old and new runs; this slice does not claim that integration.

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **current production consumers:** service initialization and the HTTP GET/POST dispatcher. **new direct consumer:** API callers reading or editing the catalogue. **verified absent:** the current driver, panel, and granted calling-product repositories contain no model-profile route or selection consumer; Slices 2-3 own those integrations. Existing strategy-profile consumers remain unchanged. | `orchestrator/service.py:3411-3429,3708-3724,4061-4069`; `implementation/milestones/model-profiles/skeleton.md:34-40,66-75` |
| pinned_facts | **closed facts:** exact source fields; exact three rigors; five-word examples; the nine-act authority matrix; no stricter executor-id whitelist; exact GET/POST route and envelopes; HTTP 400 input rejection with no mutation; loud stored-corruption failure; missing-only editable `default`; medium staffing equivalence; and the no-runtime/no-strategy boundary. | this note, Pinned-Facts Table; `implementation/milestones/model-profiles/skeleton.md` |
| verification | **focused:** the named store and API checks cover schema, authority, atomic failure, seed preservation, default equivalence, status/envelopes, access, and strategy-route non-regression. **full:** repository unittest discovery remains the closure gate. Current runtime resolution for old and new runs is explicitly deferred to Slice 2. | this note, Verification Contract; `implementation/milestones/model-profiles/skeleton.md`; `orchestrator/README.md:522-524` |
| reuse_posture | **checked:** strategy-profile validation/whole-file persistence/missing-only seeds, service route/error envelopes, act-edit vocabulary, current staffing defaults, and their tests. **reused:** those proven shapes and tests as patterns, without sharing strategy lifecycle or storage. **cheapest sufficient:** one separate model-profile store plus two additive route branches; documentation/configuration alone cannot provide the mandated reusable API catalogue. **cost:** no migration/process, bounded maintenance, additive and reversible; omission blocks Slices 2-3 and preserves repetitive setup. | `orchestrator/profiles.py:61-88,95-148,278-286`; `orchestrator/service.py:2361-2433,3427-3428,3721-3724`; `orchestrator/tests/test_profiles.py:110-168`; `implementation/milestones/model-profiles/skeleton.md:37-46,70-72,175-197` |
| enforceability | **schema/authority:** pre-write validator over the pinned closed matrix. **whole save:** validate first, then existing same-directory replacement pattern. **seed:** missing-only ensure at service initialization, with failure visible. **API:** existing dispatcher/ApiError envelopes. **medium equivalence:** a behavioral comparison against current act-resolution defaults. **separation:** additive namespace plus regression checks for `/api/profiles`, `/api/runs`, acts, and panel. No promise is made for concurrent-edit ordering, crash durability, selection, binding, or call delivery because this slice has no mechanism for them. | this note, Enforceability Gate; `orchestrator/profiles.py:61-88,131-148,278-286`; `orchestrator/service.py:3411-3429,3708-3724,3772-3779,4061-4069`; `orchestrator/driver.py:88-91,156-193,5961-6120` |

### Reuse Posture

Operators and API callers are affected: without a catalogue they keep repeating
seat-level setup, and later runtime/panel slices have no reusable authority.
The exposure is every new model-profile use; the realistic harm is
misconfiguration and blocked reuse, moderate and reversible before calls run.
The reviewed skeleton independently requires the catalogue and seed
(`implementation/milestones/model-profiles/skeleton.md:37-40,70-72`).

Checked and reused as patterns: strategy-profile validation, whole-file replace,
and missing-only seeding (`orchestrator/profiles.py:61-88,124-148,278-286`);
the existing GET/POST and error envelopes
(`orchestrator/service.py:3427-3428,3721-3724,3772-3779`); the current act shape
(`orchestrator/service.py:2361-2426`); and the default staffing authority
(`orchestrator/driver.py:88-91,141-193`). The cheapest sufficient response is a
separate narrow model-profile store and additive routes. Reusing the strategy
store itself would couple independent axes and import its different schema and
seal lifecycle; documentation or configuration alone would not provide the
mandated catalogue API. The remaining machinery is consumed by the service now
and Slices 2-3 later. It adds no migration or process, has one schema and seed to
maintain, and is cheap to remove; omission blocks the authorised outcome.

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Exact source shape, three rigors, and five-word examples | Extend the existing explicit required-key/type validator pattern (`orchestrator/profiles.py:61-88`) with the closed schema pinned above. | Invalid-matrix cases fail before any file exists or changes. |
| Per-act authority ceiling without new identifier probing | Validate keys/fields against the current act matrix and reuse the current short-string input posture (`orchestrator/service.py:2361-2426`); fixed/derived production enforcement remains in `orchestrator/driver.py:6040-6120`. | The authority-matrix test covers every permitted act form and each forbidden field class. |
| Whole accepted save; failed edit preserves the prior source | Validate before using the existing same-directory whole-file replacement capability (`orchestrator/profiles.py:124-148`). | Reload after valid save equals the complete new source; reload after invalid save equals the complete old source. |
| Invalid persisted content never silently disappears | A listing loads and validates every candidate; unlike the current skip branch (`orchestrator/profiles.py:108-121`), any invalid candidate propagates to the service's 500 envelope (`orchestrator/service.py:3772-3779`). | Corrupt-one-file API test observes 500 and no shortened successful list. |
| Missing-only editable seed and visible initialization failure | Reuse the missing-only ensure pattern (`orchestrator/profiles.py:278-286`) at the existing service startup seam (`orchestrator/service.py:4061-4069`), without swallowing model-seed failure. | First start creates; edit plus restart preserves bytes; invalid existing seed prevents successful initialization rather than being replaced. |
| Seeded medium is current-staffing equivalent | The seed is compared against `DEFAULT_CONFIG` and the current act-resolution surfaces (`orchestrator/driver.py:88-91,141-193,5961-6120`). | The named equivalence test covers all nine acts plus the origin/caller contexts needed by fixed and derived seats. |
| Exact HTTP surface and no strategy regression | Additive branches follow the current `/api/profiles` response/access pattern (`orchestrator/service.py:3427-3428,3721-3724`) and common error handler (`orchestrator/service.py:3772-3779`). | API test pins both model-profile routes and rechecks the strategy route unchanged. |

Any implementation that relies on prompt discipline, silent skipping, fallback,
or later-slice behavior for one of these rows has not delivered this slice.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's decisions, including its incorporation of
  the goal's completed brainstorming outcome.
- **Revise:** no planning decision independently; slice-local schema and API
  exactness are the narrow realization of the reviewed Slice 1 boundary.
- **Reject:** brainstorming and `_drafts` material as authority, including any
  mechanism or per-slice assignment not carried into the reviewed skeleton.

Authority: `implementation/milestones/model-profiles/skeleton.md:48-64,66-79`.
