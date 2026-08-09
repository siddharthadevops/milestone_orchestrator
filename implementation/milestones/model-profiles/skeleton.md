# Milestone skeleton — Model Profiles and the Strategy Configurator

Goal (mandate): `implementation/milestones/model-profiles/goal.md`. Operator
amendment A1 and the accepted current-state resolver amendment supersede the
goal's model-profile binding, snapshot, attribution, provenance, and historical
semantics. Strategy configuration is unchanged.

## Intent (lay register)

Two reusable, named choices replace repeated manual configuration:

1. A **model profile** describes the kind and rigor of current work. Each
   editable catalogue entry has a name, short examples, and complete
   `low`/`medium`/`high` configurations over the existing configurable acts.
   A run has one current `{name, rigor}` selection. Immediately before each
   model dispatch, the runtime reads that selection and the selected profile's
   current saved definition. No selection means `default@medium` for every run.
   Current per-act overrides remain above the profile.
2. A **strategy configuration** describes how the run reviews and challenges
   its work. The configurator presents known decisions with their actual
   support status: active, reserved and visibly non-operative, or invalid and
   rejected. It configures existing machinery; it does not create dormant
   machinery.

Both catalogues are editable operator-owned definitions. Model profiles are
current settings: the last completed profile edit, selection replacement, or
override write visible to the resolver governs the next call, including within
an active unit. A call already dispatched finishes with the settings supplied
to that dispatch. No run or unit freezes or retains an earlier model-profile
selection, definition, identity, or staffing, and no model-profile history,
attribution, provenance, transition, or recovery record is added.

The old first-use seal for strategy profiles is retired independently. Strategy
runs continue to retain the exact strategy content they resolved, as required
by Slices 4–6; A1 changes model profiles only.

**Consumers.** The driver and its independently supervised milestone
Brainstorming turns consume the current model selection, current saved profile,
and current override layer at dispatch. The operator and calling products
consume the same catalogue and current-selection semantics through panel and
HTTP API.

**Owned here.** The model-profile catalogue and seeded default; current-state
profile-to-act resolution and creation override routing; selection and
catalogue surfaces; the strategy decision catalogue and configurator; and
retirement of strategy first-use seals and misleading presentation.

**Not owned here.** Cost/budget controls; coupling the two axes; artifact
sealing, family rotation, or review-derived seals; new model/effort identifiers;
new review machinery; profile-specific versioning, snapshots, events, history,
replay, migration, recovery, locking, CAS, retry, rollback, or reconciliation;
calling-product implementation; or runtime support for reserved strategy
decisions.

## Planned slices

| # | Slice | Intent (one line) |
|---|---|---|
| 1 | Model-profile store and seeded default | Editable validated catalogue with name, examples, three rigors, the missing-only `default`, and list/create/edit API. |
| 2 | Current profile resolution and override authority | A thin resolver reads current selection + current definition for each call, applies current overrides, seeds/validates the active catalogue at execution entrypoints, and single-homes creation overrides. |
| 3 | Model-profile selection and override surfaces | Panel + API catalogue create/read/edit and current-selection read/replace, reusing existing override controls without provenance or history UI. |
| 4 | Strategy editability without first-use seals | Editing a used strategy stops being refused; creation and active-run change both retain resolved strategy content + identity; no surface labels an editable definition `sealed`. |
| 5 | Strategy decision catalogue and validation | One shared decision inventory with active/reserved status and legal values; unknown/invalid rejected loudly; `strict`/`light` reproducible; `legacy` fenced. |
| 6 | Strategy configurator panel | Build and edit a strategy configuration decision-by-decision over the Slice 5 catalogue, with API-identical semantics. |

Order: 1→2→3 sequential; 4 independent; 5 after 4; 6 after 5.

## Shared invariants (strict)

- **Current-state resolution:** before each model dispatch, read the run's
  current selection and the selected profile's current saved definition. An
  absent selection resolves `default@medium`, for old and new runs alike. A
  valid write visible to that read affects that call; a dispatched call is not
  altered.
- **Precedence:** current per-act override > current profile entry > existing
  structural rule or shipped/config default > family default. Each override is
  a whole-act policy; omitted fields never merge from the profile.
- **Creation semantics:** project defaults, launch input, and CLI config retain
  today's merge order and partial/empty behavior. Surface-act winners are
  written only to the live `acts.json` override layer; shipped entries remain
  in baseline config. Unknown or legacy creation keys stay tolerated in merged
  config and never become active overrides. A higher object after a lower
  non-object whole-map replacement contains only its own explicit winners; a
  final non-object whole-map replacement suppresses all surface profile entries.
- **Authority ceiling:** profile and live-override inputs may set only fields
  the act honors. Reviews keep fixed families, delta review derives from the
  fixer, the brainstorming counterpart remains opposite the lead, and
  consultation keeps derived model/effort. Invalid input is refused, never
  silently accepted or used to bypass structural rules.
- **Loud current-state failure:** an unavailable, malformed, unknown, or invalid
  current selection/profile fails before provider dispatch; there is no
  fallback and no repair of operator data.
- **No model-profile history:** no snapshot/content hash, binding, generation,
  acknowledgement, origin, attribution, provenance, transition, replay,
  migration, or profile-specific recovery state has authority or is added.
  Stale fields from the withdrawn implementation are ignored.
- **Truthful surfaces:** panel and API expose the same names, legal values,
  validation, support status, current selection, and semantics. Model-profile
  surfaces display no origin or history.
- **Strategy isolation:** strategy configuration retention, artifact seals,
  generic execution/accounting/recovery, and Slices 4–6 are unchanged.

## Pinned facts

| fact | value | authority / seam | posture |
|---|---|---|---|
| Configurable acts | `skeletoner`, `drafter`, `implementer`, `fixer`, `reclassifier` accept family policy or `{agent, model, effort}`; `review_codex`, `review_claude`, `brainstorming_counterpart` accept `{model, effort}` only; `consultation` accepts family policy only. | `orchestrator/model_profiles.py`; existing structural resolvers in `orchestrator/driver.py` | extend validation, do not expand authority |
| Current selection | One atomic current `{name, rigor}` value; absence means `default@medium`. Last completed write wins; no event or prior value is retained. | current selection sidecar beside run state; Slice 3 owns read/replace surfaces | Slice 2 reads only; Slice 3 writes |
| Current profile | Load and validate the selected saved document at every act resolution used for a dispatch; never use retained content. | `model_profiles.load`; `_act_profile` | single resolver seam |
| Per-act override channel | `acts.json` beside state; re-read at act resolution. Creation surface entries are projected here in project-default then launch order and removed from baseline config; explicit per-act empties are retained at creation. Mid-run empty values clear entries. | existing acts route + creation merge seam | reuse one live layer, no origin metadata |
| Seeded default | Missing-only `default`; every execution entrypoint seeds absence and validates an existing file. Its initial `medium` matches current shipped staffing. | Slice 1 `ensure_default`; CLI/service entrypoints | startup initialization, never per-call fallback |
| Rigor and examples | Exactly `low`, `medium`, `high`; each example is non-empty and at most five words. Unknown selection fails. | Slice 1 validator | unchanged |
| Model-profile API | Slice 1 keeps `GET/POST /api/model-profiles`; Slice 3 adds current-selection read/replace and panel controls. | service route surface | no history/provenance routes |
| Executor vocabulary | Existing installed model identifiers and efforts only; no new identifier registry. | current runner/panel vocabulary | unchanged |
| Active strategy decisions | `stages[0].loop`, `p3_defer_max_risk`, `p3_reclassify_debt`, and `doc_register`; `compat` remains only the legacy fence. | `orchestrator/interpreter.py` | unchanged |
| Reserved strategy decisions | `fuser_discard`, `final_open_pass`; retained and visibly non-operative. | strategy profile/interpreter catalogue | no runtime machinery |
| Strategy editability | Retire stored-strategy first-use save refusal and `sealed` presentation; keep run-side retained strategy content and verification. | strategy store, service, panel, interpreter | Slices 4–6 unchanged |
| Artifact seals and rotation | Run-artifact seals, family rotation, and deterministic review-derived seals remain unchanged. | existing driver/state machinery | do not touch |

## Question battery

| question | answer |
|---|---|
| victim | Operators and calling products otherwise repeat staffing by hand, while stale definitions or stale selection snapshots can dispatch the wrong current model. Strategy users also face blocked legal edits and misleading support labels. |
| machinery | Model profiles add one validated catalogue, one current-selection value, and one extension of the existing act resolver. Strategy work adds only the already-authorized catalogue/status and editability changes. No model-profile history machinery is justified. |
| consumers | Driver act resolution, run creation, the existing acts route, Slice 3 panel/API surfaces, and the existing strategy surfaces. Generic execution/accounting records continue to store only their ordinary resolved family/model/effort. |
| cheaper alternative | Hand-written config does not provide reusable named choices. The cheapest sufficient runtime is current reads through `_act_profile` plus the existing `acts.json`; snapshots, event ledgers, generations, and parallel resolvers add cost while contradicting A1. |
| cost | Six bounded slices, no migration and no new process. Per-call profile reads are the deliberate cost of last-write-wins semantics. |
| threat model | Inputs come from already-authorized local operators/calling products. Validation provides honest failure and structural authority, not a new trust boundary. |
| enforceability | Validated current selection + `model_profiles.load` + `_act_profile` enforce current reads and precedence; the atomic override/selection writers enforce last-completed-write semantics; existing structural resolvers enforce fixed/derived seats; focused tests edit selection/profile/overrides between resolutions and prove the next result changes while old snapshot fields do not. |

## Reuse posture

Reuse Slice 1's loader/validator and missing-only seed, `_act_profile` as the
single runtime seam, `acts.json` and its atomic service write, the established
creation merge order, the physical-invocation hook, and existing fixed/derived
act resolvers. The thin additions are a current-selection reader, current
catalogue home supplied by CLI/service execution entrypoints, and a
late-resolution wrapper for the fixer-owned consultation subprocess that
carries the caller act and its structural origin. Related lead/counterpart
derivation shares one ephemeral read. These are consumed directly at dispatch
and later by Slice 3's current-selection surfaces. Milestone Brainstorming
receives its run state and catalogue only as child-launch inputs; service
restart can obtain them from the existing generic run/session attachment. A
project-less run reuses the active entrypoint home for both that attachment and
its lifecycle, including when the home is non-default; no second registry or
retained locator is added. The lifecycle record retains neither input. An
unattached milestone restart refuses before launch rather than reusing its
creation-time roster; standalone Brainstorming remains profile-independent.

The catalogue does not alter Git behavior. The normal registry home is outside
the run workspace; an explicitly chosen workspace-local home has ordinary
repository staging, commit, and recovery semantics and receives no
profile-specific exclusion, preservation, refusal, or cleanup path.

Do not add a source archive, binding table, content identity, event stream,
generation counter, acknowledgement, provenance view, migration, watcher,
synchronizer, or profile-specific recovery path. Their lifecycle cost has no
authorized consumer; their omission is required so current settings remain
last-write-wins.
