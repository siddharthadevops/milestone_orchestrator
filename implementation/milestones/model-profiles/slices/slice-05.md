# Slice 05 — Strategy decision catalogue and validation

## Register 1 — Intent

### What this slice builds

This slice gives operators and API clients one truthful inventory of the
choices that may appear in a review strategy. It says which choices govern the
runtime today, which are preserved for later work but do nothing today, and
which values are legal. The same inventory validates reusable strategy
documents, so a misspelling or unsupported value cannot be saved or selected as
if it worked.

The existing strict and light starting strategies remain reproducible in full,
including their non-operative content. The legacy strategy remains selectable
for compatibility, but it is not a building block for a new strategy.

### Ownership and boundary

This slice owns the shared decision inventory, closed validation of strategy
content, truthful decision status in the existing strategy API, and loud
failure at the existing save and selection boundaries. It also corrects the
shipped strategy descriptions so fresh catalogues do not describe reserved
protection as active.

It does not build the decision-by-decision panel editor; Slice 6 consumes this
catalogue for that work. It does not make reserved choices operative, alter
review flow, change run-retained strategy semantics, or change model profiles.

### Guarantee posture

- **Strict:** the catalogue, validator, and API agree on decision names,
  support status, and legal values. Every present decision is validated before
  a catalogue save or new run selection succeeds. Invalid input does not change
  a saved definition, create a run, or replace a run's strategy. Reserved
  content round-trips without loss and is never reported as operative.
- **Optimistic:** concurrent whole-document edits retain Slice 4's last
  completed replacement behavior. This slice adds no merge, lock, conflict
  warning, or lost-update protection.
- **Eventual:** none is introduced. Catalogue validation is synchronous, and
  this slice leaves Slice 4's active-run delivery contract unchanged.
- **Best-effort:** abrupt host or filesystem failure keeps the existing store
  and generic recovery posture. There is no strategy-catalogue repair,
  migration, retry, rollback, or reconciliation process.

### Dependencies and consumers

Slice 4 supplies editable whole-document storage and self-contained run
retention. The existing strategy store supplies atomic replacement and semantic
identity. The existing service supplies catalogue, run-creation, and active-run
replacement boundaries. The interpreter and driver are the verified consumers
that distinguish active decisions from reserved content.

Directly affected consumers are strategy-store callers, the existing strategy
API, new-run selection, and active-run replacement. The current panel may keep
reading the profile list unchanged; Slice 6 will consume the added inventory to
build the editor and align all panel presentation. Granted calling-product
repositories remain read-only and require no change.

### Non-goals

- No strategy constructor or decision-editing panel.
- No execution support for reserved stage actions, fuser discard policy, or a
  final open pass.
- No new review loop, stage, action, fuser, evaluator, risk scale, or seal rule.
- No change to retained strategy identity, active-run transition records,
  artifact seals, family rotation, accounting, or generic recovery.
- No model-profile catalogue, selection, override, resolver, or history work.
- No migration or rewriting of retained run history and no parallel catalogue
  or validation service.

### Acceptance

The slice is accepted when the existing strategy catalogue response carries one
machine-readable decision inventory and the same inventory governs validation.
Every catalogued value is accepted, while an unknown semantic key, a wrong
type, an unsupported value, or a malformed stage envelope is rejected before a
save or selection changes state. A directly damaged stored catalogue entry is
reported as an error rather than disappearing from the list.

Existing custom strategies may remain partial: omission is not an invented
decision and retains the current interpreter/default behavior. Every decision
that is present must be known and valid. The later configurator will emit
complete documents; this slice does not migrate partial operator-owned files.

Decomposing and rebuilding each canonical strict and light seed through the
catalogue yields its complete semantic content and semantic identity. Reserved
values survive save, list, selection, and retained-content resolution, but
changing them cannot alter current runtime decisions. The legacy seed remains
behaviorally equivalent to a profile-less run and cannot be composed into a
new strategy.

The expected implementation remains below roughly 500 changed lines. It
centralizes existing values and extends existing validation and response
surfaces; no new store, route, process, or runtime engine is justified.

### Risks

- Duplicating values between validation, API, and the seeds would let those
  surfaces drift. Exact inventory and seed round-trip tests compare them.
- Silently skipping a damaged file would make an invalid strategy look deleted.
  The listing test requires the existing error envelope instead.
- Treating reserved fields as active would promise protection the runtime does
  not provide. Status and no-effect tests pin the distinction.
- Over-validating omitted decisions would unnecessarily strand existing valid
  partial profiles. Compatibility tests preserve omission semantics while
  rejecting explicit bad content.
- Letting compatibility content into ordinary profiles would bypass the legacy
  fence. Exact legacy-shape and non-composability tests close that path.
- Expanding validation into retained history would rewrite Slice 4's authority.
  Existing retained records are neither migrated nor reinterpreted.

### Reuse Posture

The affected party is the operator or API client: today unsupported fields can
be saved as silent no-ops, reserved fields are presented like active controls,
and a damaged stored file can vanish from a listing. The harm is misleading but
local and reversible before a run; once selected, a false strategy claim can
govern review expectations. The reviewed milestone requires truthful support
status, exact seed reproduction, and loud refusal.

The checked reusable surfaces are the existing strategy document validator and
atomic whole-save, semantic hash and retained pair, seed constants, catalogue
GET/POST, creation and repoint resolution, and the interpreter/driver read
sites. The cheapest sufficient option is one data catalogue reused by
validation and the existing GET response, plus focused regressions over those
boundaries. Slice 6 consumes that same response. No new route, store, watcher,
ledger, migration, or runtime consumer is warranted. Centralizing a few values
has small build and review cost; omission preserves silent misconfiguration,
while stronger lifecycle or concurrency machinery costs more than the readily
reversible local harm.

### Planning Material Disposition

- **Adopt:** the planning distinction between active controls and content kept
  only for future machinery, and exact reproduction of the two canonical
  starting strategies.
- **Revise:** earlier planning that described reserved fuser, action, or final
  pass behavior as if it already executed; those values remain content only.
- **Reject:** planning material as independent authority, future stage/fuser
  machinery, and any model-profile binding or history semantics superseded by
  the operator amendments.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Decision catalogue | `stages[0].loop`: active, `family_until_clean`; `p3_defer_max_risk`: active, `low`/`medium`/`high`/`xhigh`; `p3_reclassify_debt`: active, boolean; `doc_register`: active, `dense`/`lay+hard-table`; `stages[0].actions[0].scope`: reserved, `open`; `fuser_discard`: reserved, `evidence`/`evidence+concur`; `final_open_pass`: reserved, boolean. These seven entries are the complete composable inventory. | status authority `implementation/milestones/model-profiles/skeleton.md:19-23,63,115-116`; risk scale `orchestrator/contracts.py:67`; current defaults and consumers `orchestrator/driver.py:228,235,345-358,8922-8927`; seed content `orchestrator/profiles.py:196-239`; register consumer `orchestrator/interpreter.py:94-103`; fixed stage action `orchestrator/profiles.py:213-217,234-237` | touch: centralize these names, statuses, and values; do-not-add another decision, value, risk level, or reserved runtime consumer |
| Semantic validation | A non-legacy `profile` remains a non-empty subset of the seven entries. Every present entry has the catalogued type/value. Explicit `stages` is exactly one non-empty stage containing either or both catalogued stage decisions: when present, `loop` is `family_until_clean`; when present, `actions` is exactly one `open` action. No extra stage/action fields are valid. Omission of either nested decision retains existing defaults and is not a hidden catalogue value. Any other semantic key or nested content is invalid. | closed-inventory requirement `implementation/milestones/model-profiles/skeleton.md:19-23,63,115-116`; current partial-document seam `orchestrator/profiles.py:61-88`; omission behavior `orchestrator/interpreter.py:52-65,68-103` | touch: replace permissive semantic validation with catalogue validation; do-not-require completeness, invent defaults, or migrate partial documents |
| Legacy fence | Only the profile named `legacy` may carry `compat`, and its semantic content is exactly `compat: true` plus the canonical `family_until_clean`/`open` stage. It remains selectable but is excluded from composition. Description/version edits remain ordinary metadata edits. | `implementation/milestones/model-profiles/skeleton.md:63,115`; intent authority `implementation/milestones/model-profiles/goal.md:162-165`; canonical seed `orchestrator/profiles.py:240-260`; fence consumers `orchestrator/interpreter.py:106-125,144-158` | touch: validate the existing fence; do-not-offer `compat` as a decision, clone legacy into a new configuration, or alter legacy execution |
| Catalogue API and failure | `GET /api/profiles` remains HTTP 200 `{"ok":true,"profiles":[...],"decisions":[...]}` and each decision entry is `{"key":"...","status":"...","values":[...]}`, where `status` is exactly `active` or `reserved`. `POST /api/profiles` keeps its current request, admin gate, HTTP 200 profile envelope, and HTTP 400 non-empty error envelope. Invalid stored content makes GET fail through the existing HTTP 500 non-empty error envelope instead of being omitted. No new route is added. | API parity `implementation/milestones/model-profiles/goal.md:157-170`; existing GET/POST routes `orchestrator/service.py:3698-3699,4022-4025`; current views/save `orchestrator/service.py:2613-2646`; analogous loud-listing seam `orchestrator/service.py:2649-2656`; silent-skip seam `orchestrator/profiles.py:108-121`; common errors `orchestrator/service.py:4084-4091` | touch: extend the existing GET and stop silent omission; do-not-add a catalogue route, error code, or alternate validator |
| Save and selection refusal | Unknown/invalid content fails before mutation. Rejected catalogue POST is HTTP 400 and preserves the prior file; rejected `POST /api/runs` selection is HTTP 400 and creates no run state; rejected `POST /api/runs/{id}/profile` is HTTP 400 and writes no replacement. Reserved legal content is retained exactly in the existing semantic content/hash pair. | `implementation/milestones/model-profiles/skeleton.md:63,97-101,115-117`; save/resolve seams `orchestrator/profiles.py:95-166`; creation gate `orchestrator/service.py:1991-2004`; repoint gate `orchestrator/service.py:2718-2751`; route errors `orchestrator/service.py:4077-4091` | touch: reuse validation at every existing catalogue read; do-not-add fallback, repair, partial write, or new transition state |
| Canonical seeds and isolation | Catalogue decomposition/recomposition preserves the complete semantic content and semantic hash of `strict` and `light`, including all three reserved entries. Fresh seed descriptions call reserved protection non-operative. Existing operator-edited source descriptions are not rewritten. Strategy runtime behavior, retained records, model-profile machinery, artifact seals, and granted repositories are unchanged. | `implementation/milestones/model-profiles/skeleton.md:33-35,48-53,63,100-101,115-118`; canonical seeds `orchestrator/profiles.py:196-260`; identity `orchestrator/profiles.py:53-58`; legacy equivalence gate `orchestrator/tests/test_profile_equivalence.py:172-236` | touch: catalogue constants, fresh seed copy, and validation/API tests; do-not-rewrite stored definitions or retained runs, change interpretation, or touch model-profile/seal/calling-product code |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_profiles.StrategyDecisionCatalogueTest orchestrator.tests.test_profiles.StrategyDecisionValidationTest orchestrator.tests.test_service_api.ProfilesDecisionApiTest orchestrator.tests.test_interpreter.RoundsLoopTest orchestrator.tests.test_interpreter.EffectiveConfigTest orchestrator.tests.test_interpreter.DocRegisterTest orchestrator.tests.test_profile_equivalence.ProfileEquivalenceTest`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| One exact inventory | `test_exact_decision_keys_statuses_and_values` | GET and the validator expose exactly the seven pinned entries with identical status and values. | strict |
| Closed validation with omission compatibility | `test_known_partial_profiles_validate_and_bad_present_content_fails` | Every legal value and known partial document saves, including loop-only and fixed-action-only stage subsets; unknown keys, wrong types/values, an empty stage list or envelope, multi-stage shapes, extra nested fields, and malformed actions fail without changing prior bytes. | strict |
| Loud catalogue damage | `test_invalid_stored_profile_fails_listing_instead_of_disappearing` | One directly damaged stored document makes GET return 500 with a non-empty error; it is not omitted from a successful shorter list. | strict |
| Existing selection gates reuse validation | `test_invalid_strategy_never_creates_or_repoints_a_run` | Creation and active-run replacement each return 400 for an invalid stored strategy and leave run state/replacement bytes absent or unchanged. | strict |
| Seeds reproduce exactly | `test_strict_and_light_decision_round_trip_is_semantically_exact` | Extracting then rebuilding all seven decisions yields each canonical seed's complete semantic object and the same semantic hash. | strict |
| Reserved means preserved, not executed | `test_reserved_content_round_trips_without_runtime_effect` | Reserved values survive save/list/resolve; supported variations of the reserved fields do not change current loop, effective config, document register, or driver decision, and the API reports them as reserved. | strict |
| Legacy remains fenced | `test_legacy_is_selectable_equivalent_and_not_composable` | The canonical legacy document validates and keeps existing profile-less equivalence; `compat` in any other name or legacy with non-fence semantic content is rejected. | strict |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-524`).

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Direct:** strategy load/list/save/resolve, the existing catalogue GET/POST, and the creation/repoint callers that select a current reusable strategy. **Verified downstream:** interpreter/driver reads establish which decisions are active; Slice 6 and the current panel consume the same GET response but this slice builds no editor. **Untouched:** retained run-transition semantics, model profiles, artifact seals, and granted repositories. | `orchestrator/profiles.py:61-166`; `orchestrator/service.py:1991-2004,2613-2646,2718-2751,3698-3699,4022-4025`; `orchestrator/interpreter.py:24-29,52-114`; boundary `implementation/milestones/model-profiles/skeleton.md:55-66,100-118` |
| pinned_facts | The bug-level facts are the exact seven-entry inventory and legal values; closed validation of every present decision; the exact legacy fence; extension of existing `GET /api/profiles` with `decisions`; unchanged POST/selection routes and error envelopes; exact strict/light semantic round-trip; loud stored corruption; and isolation from runtime, retained history, model profiles, seals, and calling products. | `implementation/milestones/model-profiles/skeleton.md:55-66,97-118`; values `orchestrator/profiles.py:196-260`; routes `orchestrator/service.py:3698-3699,4022-4025,4077-4091`; this note's Pinned-Facts Table |
| verification | Focused catalogue/validator/API tests pin the exact inventory, legal partials, invalid-value non-mutation, loud listing failure, creation/repoint refusal, seed equivalence, reserved no-effect behavior, and the legacy fence. Existing interpreter and end-to-end legacy-equivalence tests prove the reused runtime classification; full unittest discovery is the closure gate. | current validation tests `orchestrator/tests/test_profiles.py:140-198`; API boundary tests `orchestrator/tests/test_service_api.py:1926-1935,2056-2091,2176-2241`; loud-listing precedent `orchestrator/tests/test_service_api.py:2563-2576`; consumer tests `orchestrator/tests/test_interpreter.py:50-115,225-335`; equivalence `orchestrator/tests/test_profile_equivalence.py:172-236`; suite `orchestrator/README.md:522-524` |
| reuse_posture | **Checked/reused:** validated atomic strategy storage, semantic hash/retained pair, seeds, existing catalogue route, creation/repoint resolution, and interpreter/driver consumers. **Cheapest sufficient:** one data catalogue drives validation and extends the existing GET; known partials remain legal and Slice 6 reuses the response. **Remaining machinery/consumer:** only catalogue data and stricter checks, consumed by store/API now and the panel next. **Lifecycle:** no route/store/migration/background work; omission preserves silent no-ops, while runtime engines, locks, and migration would add cost without authority. | `orchestrator/profiles.py:53-166,196-272`; `orchestrator/service.py:1991-2004,2613-2646,2718-2751`; `orchestrator/interpreter.py:24-29,52-114`; authority `implementation/milestones/model-profiles/skeleton.md:43-53,63-66,115-118` |
| enforceability | **Inventory/parity:** one catalogue value is serialized by existing GET and consumed by validation. **Loud failure/non-mutation:** validation runs before existing atomic save, creation, and repoint writes; listing propagates rather than catches invalid content. **Seed fidelity:** existing semantic hash compares full reconstructed objects. **Active status:** existing interpreter/driver read sites and behavior tests. **Reserved status:** catalogue reports `reserved`, exact JSON retention preserves values, and no-effect tests hold current runtime outputs. **Legacy:** exact shape validation plus the existing equivalence suite. No stronger concurrency, migration, crash recovery, or future reserved execution is promised. | `orchestrator/profiles.py:53-166`; `orchestrator/service.py:1991-2004,2613-2646,2718-2751,3698-3699,4022-4025`; `orchestrator/interpreter.py:24-29,52-114`; `orchestrator/driver.py:345-358,8502-8506,8922-8927`; `orchestrator/tests/test_profile_equivalence.py:172-236` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Catalogue, validation, and API cannot drift | A single catalogue value can feed strategy validation and the existing profile view/list response (`orchestrator/profiles.py:61-121`; `orchestrator/service.py:2613-2646`). | Exact-set tests compare API entries, accepted values, and rejected values without maintaining a second expected implementation map. |
| Invalid content cannot become a new governing choice | Existing save, creation, and repoint paths all cross strategy load/validation before their atomic writes (`orchestrator/profiles.py:95-166`; `orchestrator/service.py:1991-2004,2718-2751`). | Store and HTTP tests snapshot prior file/state/overlay bytes around every rejection class. |
| Stored corruption is loud | The strategy listing can reuse the model-catalogue behavior that propagates validation failure through the common GET error envelope (`orchestrator/profiles.py:108-121`; `orchestrator/service.py:2649-2656,3698-3699,4084-4091`). | A directly damaged file makes GET fail with a non-empty error and never yields a shortened success response. |
| Active and reserved labels are truthful | Existing interpreter and driver reads identify current consumers; the catalogue carries the support status; semantic storage/hash retain all fields (`orchestrator/interpreter.py:24-29,52-114`; `orchestrator/driver.py:345-358,8502-8506,8922-8927`; `orchestrator/profiles.py:53-58`). | Consumer tests vary active values; reserved tests preserve values while holding current runtime outputs unchanged. |
| Strict and light remain exactly reproducible | The canonical seed objects and semantic hash already provide complete expected content and identity (`orchestrator/profiles.py:53-58,196-239`). | Catalogue decompose/recompose tests compare full objects and hashes, including the fixed reserved action. |
| Legacy stays a compatibility fence | The exact legacy seed plus `compat` consumers and the end-to-end equivalence suite express the fence (`orchestrator/profiles.py:240-260`; `orchestrator/interpreter.py:106-125,144-158`; `orchestrator/tests/test_profile_equivalence.py:172-236`). | Validation rejects `compat` outside exact legacy content; existing equivalence remains green. |

Any implementation that duplicates the inventory, silently drops invalid stored
content, accepts an unknown or unsupported present decision, labels reserved
content operative, changes reserved runtime behavior, loses seed content,
composes legacy, adds a new route or runtime engine, or alters model-profile,
retained-history, or artifact-seal behavior does not deliver this slice.
