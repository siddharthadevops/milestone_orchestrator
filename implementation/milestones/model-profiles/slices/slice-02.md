# Slice 2 — Profile resolution, binding, and attribution

## Register 1 — Intent (lay language)

### What this slice builds

This slice makes a chosen model profile govern real work. When a work unit is
about to use a model for the first time, the run keeps the exact profile choice
and staffing it resolved. Editing the reusable profile later cannot change that
unit's past or silently restaff its remaining calls. A later unit can pick up the
edited definition, and an explicit change affects the next call rather than a
call already in progress.

An operator's explicit choice for one act still wins over the profile. Choices
made when the run was created become the same clearable overrides as choices
made later, without changing their present result. Every model call remains
auditable: a reader can recover who ran, with which model and effort, under
which profile choice, and whether an explicit override contributed.

This is for operators, calling products, and people auditing run history. It
owns runtime resolution, retained bindings, override precedence and origin, and
call attribution. It does not build the profile picker or editor in the panel.

### Guarantee posture

- **Strict:** a unit's first act resolution binds one exact source snapshot;
  precedence is act-wide and deterministic; a later choice is prospective;
  source edits never rewrite a binding or call record; every new call is
  attributable; invalid or unavailable selections never fall back; and runs
  created before this feature keep their former staffing.
- **Optimistic:** none. There is no conflict token or promise that two
  simultaneous operator edits will both survive.
- **Eventual:** none. A completed binding or change is effective at the named
  act boundary; there is no background convergence.
- **Best-effort:** ordering between genuinely overlapping operator writes and
  survival through abrupt filesystem or host loss are not strengthened here.
  A successfully recorded binding and history remain strict.

### Dependencies and consumers

This slice depends on Slice 1's validated, editable catalogue and seeded
default. It also depends on the existing run initializer, act-override file,
single act-resolution path, state ledger, call accounting, and frozen
Brainstorming seats.

The direct consumers are the driver paths that choose workers, the run-state
history and summaries that report them, the existing run-creation and act-edit
services, and the Brainstorming lifecycle when it receives model-profile-backed
seats. No granted calling-product checkout is changed; those products remain
future API consumers.

### Non-goals

- No panel catalogue, picker, editor, inherited/override presentation, or
  clear-control work; those are Slice 3.
- No new run-creation or mid-run profile-selection HTTP route in this slice.
- No profile deletion, source versions, retained older source documents,
  watcher, background synchronizer, migration job, or concurrency protocol.
- No new act, model, effort, family, cost, budget, or risk vocabulary.
- No change to review strategy, strategy-profile editability or seals, review
  stages, family rotation, artifact seals, or calling-product implementation.

### Acceptance

The slice is accepted when new unselected work binds the current default at its
middle rigor on the unit's first act resolution; a named choice binds the exact
selected source; two units in one run can retain different choices; a source
edit changes only later bindings; and an explicit change affects the next act
resolution without changing an in-flight or recorded call. A model call outside
any persisted unit resolves and retains the run's current choice for that call.

It must also prove the complete precedence chain, including whole-act
overrides, partial entries, relative policies, and an explicit empty creation
override. Run-creation choices from every existing channel must produce the
same staffing as before while becoming single-homed, attributable, and
clearable. Fixed and derived seats must remain fixed or derived.

Every successful, failed, repaired, interrupted, or nested model call must lead
to history from which its resolved staffing, bound selection (or pre-feature
no-selection origin), and contributing override can be recovered. A pre-feature
state must produce its former choices without reading the model-profile
catalogue.

The implementation is expected to exceed the roughly 500 changed-line target
modestly. The reason is test breadth: three creation channels, explicit-empty
compatibility, old-state equivalence, mutable-source boundaries, and all direct
and nested call-record classes must be pinned. Runtime machinery should still
remain one extended resolver and one binding/attribution contract; the excess
does not justify another store, resolver, migration, or process.

### Risks

- Re-reading mutable source content after a unit binds would silently restaff
  work. Snapshot and source-edit tests close that path.
- Moving creation-time choices could change today's partial or empty-entry
  behavior. Cross-channel equivalence tests compare the exact effective seats.
- Recording only successful drafts and reviews would hide paid failures,
  classifiers, consultations, or discussion turns. The attribution matrix
  covers every existing call-record class.
- Treating the absence of new state as an implicit default would migrate old
  runs accidentally. A legacy fixture must prove zero catalogue access.
- Concurrent operator writes can still overwrite one another. Adding revision
  or coordination machinery is disproportionate until an independent need
  requires it.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Binding and prospective change | A feature-enabled run with no explicit choice resolves `default` at `medium`. A persisted unit's first act resolution appends `model_profile_bound`; a later explicit choice that takes effect appends `model_profile_changed`. Each retained binding identifies `name` + `rigor` and the exact resolved configuration/content identity. A bound unit never follows later source edits; the next unbound unit may. A call outside any unit resolves the run's current selection at that call and retains it in the call's attribution. A change never alters an active or recorded call. When a new binding/change must resolve source content, an unknown, missing, corrupt, or incomplete source fails before provider dispatch with no fallback. | `implementation/milestones/model-profiles/skeleton.md:55-63,119-125,137-141,151,154-155`; source validation `orchestrator/model_profiles.py:153-222`; append-only event capability `orchestrator/state.py:233-246,330-356` | touch: bind and retain at act resolution; do-not-bind at run creation, retain only a mutable reference, or revalidate old bindings against the source |
| Resolution precedence | Per act, the strict order is explicit operator override > the bound profile's selected rigor entry > the act's existing assignment or structural derivation > family default. An override entry is the whole act policy: its missing fields never merge from the profile. A creation-supplied `null`, `""`, or `{}` is an explicit empty policy that suppresses the profile and resolves from structural derivations/family defaults until that override is cleared. Relative `self`/`opposite` policies resolve from the effective originating act. | `implementation/milestones/model-profiles/skeleton.md:86-113,147-150`; current single seam `orchestrator/driver.py:5948-5988`; fixed/derived resolution `orchestrator/driver.py:6040-6071,6096-6120,6239-6248` | touch: extend the one resolver; do-not-field-merge an override with a profile or add a parallel resolution path |
| Override origin and creation compatibility | `acts.json` beside state is the sole persisted override layer and presence is provenance. `POST /api/runs/<id>/acts` accepts exactly the configurable surface, clears omitted/empty submitted entries, and returns HTTP 400 with a non-empty error without changing the prior file for an unknown act or disallowed field. For new runs, surface-act entries supplied by project `defaults.acts`, launch `config.acts`, or CLI `--config` are stored here only, with launch winning project defaults; shipped `DEFAULT_CONFIG` entries remain in config. Creation keeps today's tolerant result: a legacy/unknown non-surface key does not refuse launch or enter the override layer, and a creation-time empty surface entry is retained as the explicit empty policy rather than treated as a mid-run clear. | `implementation/milestones/model-profiles/skeleton.md:88-108,149`; current path/route `orchestrator/service.py:2367-2434,3764-3804`; creation merge paths `orchestrator/service.py:1818-1839,1996-2013`; CLI/config merge `orchestrator/driver.py:270-292,8460-8464,8573-8579`; merge-order test `orchestrator/tests/test_run_init.py:568-583` | touch: single-home explicit creation entries and make the existing override route authority-strict; do-not-reject or activate legacy creation keys |
| Configurable authority | The surface is exactly `skeletoner`, `drafter`, `implementer`, `fixer`, `reclassifier`, `review_codex`, `review_claude`, `brainstorming_counterpart`, and `consultation`. The first five accept family policy or `agent`/`model`/`effort`; the two reviews and counterpart accept only `model`/`effort`; consultation accepts only family policy. Review families, delta-review derivation, opposite-family counterpart, and consultation model/effort derivation remain structural. | `implementation/milestones/model-profiles/skeleton.md:114-118,147-153`; validated surface `orchestrator/model_profiles.py:49-70,99-150`; structural consumers `orchestrator/driver.py:6040-6071,6096-6120,6239-6248` | touch: apply the same authority matrix to profile and hot-override inputs; do-not-add fields, acts, identifiers, or movable structural seats |
| Call attribution and immutable history | Every new model call record must directly carry, or immutably reference, the fully resolved `agent`/family, `model`, `effort`, the bound model-profile `name` + `rigor` + content identity for feature-enabled work, and the exact contributing override when one exists (including an explicit empty policy). A pre-feature call instead remains explicitly attributable to no model-profile selection and never fabricates one. This covers accepted drafts/implementations, reviews, fixes, delta reviews, reclassification and error-classifier calls, Brainstorming seats/turns, repaired/malformed attempts, and interrupted calls. Existing records are never backfilled or rewritten. | `implementation/milestones/model-profiles/skeleton.md:126-141,166`; draft/round records `orchestrator/state.py:706-770,877-918`; durable call marker/incidents `orchestrator/driver.py:1523-1641,1904-1965,2402-2448,2474-2518,7768-7789`; frozen discussion seats/activity `orchestrator/brainstorming_lifecycle.py:629-670,2163-2204` | touch: extend existing records or their immutable binding reference; do-not-derive historical attribution from current mutable source or invent a selection for old work |
| Compatibility and slice boundary | A state created before model-profile enablement never reads the catalogue and resolves exactly through its persisted config and existing acts behavior. Slice 2 adds no `model_profile` key to `POST /api/runs`, no `POST /api/runs/<id>/model-profile`, and no panel selection/presentation; those selection surfaces are Slice 3. `GET/POST /api/model-profiles`, strategy profiles, strategy interpretation, review machinery, family rotation, artifact seals, cost accounting, and the executor vocabulary remain behaviorally unchanged. | `implementation/milestones/model-profiles/skeleton.md:31-46,66-79,137-138,156-166`; existing state creation/load `orchestrator/state.py:123-168,223-230`; current model-profile routes `orchestrator/service.py:2533-2551,3442-3454,3735-3755` | touch: additive new-run runtime capability only; do-not-migrate old state or pull Slice 3/strategy work forward |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_model_profile_runtime orchestrator.tests.test_run_init.TestDefaultsPrecedence orchestrator.tests.test_service_api.ActsApiTest orchestrator.tests.test_model_profiles`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Unit-open binding retains mutable source content | `test_unit_binding_snapshots_source_and_allows_two_unit_choices` | First resolution records `model_profile_bound`; editing the source does not change that unit; a later unit binds the edited or newly selected content and retains a distinct identity. | strict |
| Explicit change is prospective and loud | `test_profile_change_applies_to_next_resolution_only` | An already-started call keeps its original attribution; the next resolution uses the new choice and records one `model_profile_changed`; unknown/corrupt content dispatches no provider call and does not rewrite the prior binding. | strict |
| Precedence is act-wide | `test_precedence_whole_act_partial_relative_and_empty_override` | The complete matrix yields override > profile > existing rule > family default; missing override fields never leak from the profile; relative and explicit-empty cases match the pinned result. | strict |
| Creation channels preserve behavior and provenance | `test_creation_acts_are_single_homed_without_staffing_drift` | Project defaults, launch config, and CLI config preserve their former effective staffing, merge winner, partial/empty behavior, and legacy-key tolerance while surface entries appear only in the override layer. | strict |
| Authority ceilings remain structural | `test_profile_and_override_authority_matrix_share_one_result` | Every allowed form resolves; hot-route unknown/disallowed input returns 400 without mutation; counterpart is supported; fixed review, delta, counterpart, and consultation derivations cannot be bypassed even by malformed stored data. | strict |
| Old states do not opt in | `test_pre_feature_state_is_identical_and_never_reads_catalogue` | A fixture without the feature marker produces the same all-act staffing snapshot as the current path while a failing catalogue spy records zero reads. | strict |
| Every model call is attributable | `test_call_attribution_matrix_survives_source_and_override_edits` | Accepted, failed, repaired, interrupted, nested-classifier, consultation, Brainstorming, and outside-unit records resolve to exact staffing, selection identity (or explicit pre-feature no-selection origin), and contributing override after both source and override files are changed. | strict |
| Runtime reporting matches dispatch | `test_summary_choice_equals_next_call_without_intervening_change` | Under unchanged persisted inputs, the run summary's effective choice equals the next call's recorded attribution; a mismatch is permitted only after a recorded intervening choice/override change. | strict |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-524`).

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **direct runtime consumers:** the driver's one act-resolution seam and every worker-call path; state draft/round/event history and summary projection; service run initialization plus the existing acts route; and Brainstorming's frozen executor/activity records. **verified boundary:** current granted product checkouts have no model-profile route/symbol consumer and are not edited; panel selection and the two new selection routes stay in Slice 3. | `orchestrator/driver.py:4689-4717,5948-6128,6230-6248,7101-7161,7614-7789,7866-7917`; `orchestrator/state.py:706-770,877-918,2200-2214,2330-2432`; `orchestrator/service.py:1781-1889,1911-2048,2367-2434`; `orchestrator/brainstorming_lifecycle.py:629-670,2163-2204`; `implementation/milestones/model-profiles/skeleton.md:34-46,70-72` |
| pinned_facts | **closed facts:** `default`@`medium`; unit-first-resolution and prospective-change semantics; exact event names; retained content identity; strict precedence and whole-act override behavior; `acts.json` single-homing and creation-channel compatibility; the nine-act authority matrix; exhaustive immutable call attribution; no catalogue reads for pre-feature state; and no Slice 3/strategy expansion. | this note, Pinned-Facts Table; `implementation/milestones/model-profiles/skeleton.md:55-63,81-166` |
| verification | The focused runtime matrix pins binding, mutable-source independence, two-unit divergence, prospective change, precedence, all three creation channels, empty overrides, authority ceilings, old-state equivalence with zero catalogue reads, exhaustive call attribution, and summary-to-dispatch fidelity. The repository discovery command remains the final regression gate. | this note, Verification Contract; `implementation/milestones/model-profiles/skeleton.md:71,81-166`; full-suite authority `orchestrator/README.md:522-524` |
| reuse_posture | **checked/reused:** Slice 1's loader/validator, the existing `_act_profile` seam, `acts.json` and its atomic route write, creation merge order, append-only state/events, durable call markers, draft/round records, and Brainstorming's frozen seat/activity records. **cheapest sufficient:** extend those seams with one retained binding/attribution shape. Documentation alone cannot make staffing or history true; a parallel resolver, source-version store, migration, watcher, or synchronization service adds lifecycle cost without authority. The remaining additive state is consumed by the driver, audit/summary readers, and Slice 3. | `orchestrator/model_profiles.py:153-222`; `orchestrator/driver.py:5948-5988`; `orchestrator/service.py:2367-2434`; `orchestrator/state.py:233-246,330-356,706-770,877-918`; `orchestrator/brainstorming_lifecycle.py:629-670`; `implementation/milestones/model-profiles/skeleton.md:180-197` |
| enforceability | **binding/history:** validated loads plus content identity, append-only events, and atomic state save. **precedence/provenance:** the one act resolver plus key-preserving override reads and creation-time single-homing. **prospective behavior:** act-boundary reads and a persisted transition before provider dispatch. **authority:** the shared nine-act validator plus structural fixed/derived resolvers. **attribution:** the durable call marker, immutable draft/round/event records, and frozen Brainstorming bindings. **legacy:** an additive marker written only by new-state initialization; absence takes the existing config-only path. **fidelity:** state reports retained effective choices rather than re-reading mutable sources. No asserted guarantee requires prompt discipline or an unavailable mechanism. | this note, Enforceability Gate; `orchestrator/model_profiles.py:153-222`; `orchestrator/state.py:123-168,233-246,305-356,706-770,877-918`; `orchestrator/driver.py:1904-1965,5948-6128`; `orchestrator/brainstorming_lifecycle.py:629-670` |

### Reuse Posture

Operators and history readers are affected. Without this slice, a reusable
definition can drift away from the work attributed to it, creation-time choices
have no uniform origin, and later surfaces cannot truthfully explain why a model
ran. The harm occurs on every new call, is moderate to high when the wrong model
handles sensitive work, and is reversible only before that call; the reviewed
baseline independently requires binding, precedence, and attribution
(`implementation/milestones/model-profiles/skeleton.md:37-46,81-141`).

Checked and reused: the validated source loader
(`orchestrator/model_profiles.py:153-222`), the existing single resolution seam
and structural seats (`orchestrator/driver.py:5948-6128`), the override file and
atomic route write (`orchestrator/service.py:2367-2434`), creation merge order
(`orchestrator/driver.py:8460-8464`), append-only atomic state
(`orchestrator/state.py:233-246,305-356`), durable call accounting and immutable
records (`orchestrator/driver.py:1904-1965`; `orchestrator/state.py:706-770,877-918`),
and frozen Brainstorming seats (`orchestrator/brainstorming_lifecycle.py:629-670`).

The cheapest sufficient option is one retained binding/attribution shape feeding
the existing resolver and records. New machinery is limited to the new-run
selection/binding projection and its consumers: driver dispatch, audit/summary
readers, and Slice 3's later surfaces. A second resolver, source-version archive,
migration, watcher, or background synchronizer would cost more to build,
operate, maintain, and review while weakening the simple mutable-source rule.
The test-heavy size excess is justified by omission cost; the runtime addition
is bounded, additive, and reversible.

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Exact unit binding and source-edit independence | `model_profiles.load` supplies one validated source (`orchestrator/model_profiles.py:206-222`); canonical content identity can reuse `profiles.semantic_hash` (`orchestrator/profiles.py:53-58`); `append_event` plus atomic append-only `save` retain it (`orchestrator/state.py:233-246,330-356`). | Persist `model_profile_bound` before the first provider dispatch; edit/delete the source, restart, and prove the unit still resolves from retained content. |
| Prospective explicit change | The current overlay pattern is atomically replaced by the service and re-read at act boundaries (`orchestrator/service.py:2428-2434`; `orchestrator/driver.py:5948-5959`); the state ledger can retain the applied transition. | Hold a call open, change selection, prove that call keeps its original record and the next resolution appends one `model_profile_changed` before dispatch. |
| Strict precedence and override provenance | `_act_profile` is the one resolution seam (`orchestrator/driver.py:5961-5988`); creation merge order is centralized (`orchestrator/driver.py:270-292,8460-8464`); the override reader preserves per-key presence (`orchestrator/service.py:2367-2378`). | Exhaust the profile-present/omitted, override-present/empty/cleared, partial, and relative-policy matrix for every authority class. |
| Fixed/derived authority ceiling | Slice 1's closed act matrix rejects dead fields (`orchestrator/model_profiles.py:49-70,99-150`); review, delta, counterpart, and consultation resolvers structurally impose their families and derived fields (`orchestrator/driver.py:6040-6071,6096-6120,6239-6248`). | Feed malformed stored/override data as well as route input; dispatch either refuses or still uses the structural seat, never the forbidden value. |
| Exact attribution for every call outcome | The durable marker records resolved staffing before a call (`orchestrator/driver.py:1904-1965`); accepted work lands in immutable draft/round records (`orchestrator/state.py:706-770,877-918`); failures and classifiers already have ledger events (`orchestrator/driver.py:1523-1641,2402-2518,7768-7789`); Brainstorming freezes seats and records activity (`orchestrator/brainstorming_lifecycle.py:629-670,2163-2204`). | After mutating source and override files, resolve each call-record class through its direct fields or immutable binding reference and compare it with the captured dispatch. |
| Pre-feature compatibility | `new_state` is the sole initializer for new state (`orchestrator/state.py:123-168`); `load` accepts older documents without inventing fields (`orchestrator/state.py:223-230`); the current all-act equivalence helper already compares fully resolved seats (`orchestrator/tests/test_model_profiles.py:320-397`). | Load a pre-feature fixture with a catalogue loader that fails if called; its complete staffing snapshot must equal the existing path and the spy must remain untouched. |
| Summary-to-dispatch fidelity | Existing history summaries consume recorded family/model/effort (`orchestrator/state.py:2200-2214,2330-2432`); the same retained binding that feeds `_act_profile` can supply selection/override provenance without rereading source. | Under unchanged state, compare the reported effective choice with the next captured call; allow divergence only when an intervening change event exists. |

Any implementation that silently falls back, reconstructs history from mutable
source, duplicates resolution, or relies on prompt discipline does not deliver
this slice.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's unit-open binding, in-place editable source,
  prospective change, precedence, and attribution decisions.
- **Revise:** no planning decision independently; this note only makes the
  Slice 2 boundary executable.
- **Reject:** brainstorming and `_drafts` material as authority, including
  per-slice pre-assignment machinery or any mechanism not carried into the
  reviewed skeleton.

Authority: `implementation/milestones/model-profiles/skeleton.md:48-64,66-79`.
