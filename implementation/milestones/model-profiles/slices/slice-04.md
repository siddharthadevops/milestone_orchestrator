# Slice 04 — Strategy editability without first-use seals

## Register 1 — Intent

### What this slice builds

This slice lets an operator correct or refine a reusable strategy after it has
already been used. Choosing a strategy no longer freezes that reusable
definition, and a legal later edit is not refused merely because a run used an
earlier form of it.

Runs remain stable. A run keeps the complete strategy and identity it resolved
when it was created. An explicit strategy change on an active run likewise keeps
the complete strategy and identity resolved for that change. Editing the
reusable source alone never changes an existing run; the operator must explicitly
change that run. Work already decided under the previous strategy remains
historical fact, while later strategy decisions use the retained replacement and
the run records that explicit transition.

The panel and API stop describing an editable strategy definition as `sealed`.
This says nothing about reviewed artifacts: their seals continue unchanged.

### Ownership and boundary

This slice owns removal of the strategy store's first-use edit refusal and
first-use mutation, truthful strategy presentation, and self-contained retention
at run creation and explicit active-run change. It preserves the existing
strategy identity and active-run change surfaces.

It does not change which strategy decisions exist, which are active or reserved,
or which values are legal; Slice 5 owns that catalogue. It does not build the
decision-by-decision editor; Slice 6 owns that panel. It does not change model
profiles, model calls, artifact seals, family rotation, review-derived seals, or
generic execution, accounting, and recovery.

### Guarantee posture

- **Strict:** a successful strategy save is immediately readable and may replace
  a definition used before. First use does not mutate the reusable definition.
  Every successful run creation or explicit active-run change retains one
  self-consistent identity-and-content pair. Later source edits cannot change or
  invalidate that retained pair. Invalid input changes neither the reusable
  definition nor the run. Strategy surfaces do not present reusable definitions
  as sealed. Artifact-seal behavior is unchanged.
- **Optimistic:** concurrent operator edits have no merge, conflict warning, or
  lost-update protection. A run binding racing an edit may retain either complete
  valid definition, but never a mixed identity/content pair. No ordering stronger
  than completed observable writes is promised.
- **Eventual:** an accepted active-run change is durable and visible immediately,
  then becomes operative at the next strategy boundary unless superseded by a
  later explicit change. The driver records the transition when it becomes
  operative; there is no background synchronizer.
- **Best-effort:** abrupt host or filesystem failure keeps the repository's
  existing durability and recovery posture. This slice adds no strategy-specific
  retry, rollback, repair, or recovery promise.

### Dependencies and consumers

The existing strategy store supplies validation, semantic identity, seed
handling, and whole-document replacement. The existing service supplies
catalogue read/save, run creation, run detail, and active-run strategy change.
The existing interpreter and driver consume retained strategy content and the
existing run ledger records an applied transition. The served panel consumes
catalogue and run-detail views.

The direct consumers touched are those strategy-store, service, interpreter,
driver, and panel surfaces. Operators and API callers observe the result. The
granted calling-product repositories remain read-only and need no change.

### Non-goals

- No model-profile change and no current-settings semantics for strategies.
- No strategy decision inventory, new legal values, or reserved-decision runtime.
- No decision-by-decision strategy editor.
- No automatic rebinding when a reusable definition changes.
- No source archive, version catalogue, clone workflow, migration, lock, CAS,
  merge, separate event stream, retry, rollback, or reconciliation subsystem.
- No rewrite of earlier run decisions or completed run history.
- No weakening or renaming of artifact seals, family rotation, or deterministic
  review-derived seals.

### Acceptance

The slice is accepted when a valid strategy definition can be edited under the
same name before or after any number of uses, through the existing API, without
a first-use refusal or first-use mutation. Existing stored seal metadata, if
present, has no authority, needs no migration, does not block the edit, and is
not presented by the API or panel.

A new run retains the exact complete strategy content and its matching identity.
An explicit strategy change on a run does the same, including for a run with no
prior strategy. In both cases a later edit of
the reusable source leaves the retained run strategy, identity, and behavior
unchanged. A subsequent explicit run change may select the edited definition and
affects only later strategy decisions. When the replacement becomes operative,
the run records the explicit transition and retains enough content to interpret
its earlier and later strategy without consulting the mutable source. Every
accepted retained pair is internally consistent; malformed or unknown input is
refused without altering prior state.

The current strategy catalogue and run-change routes, access posture, and error
envelopes remain the public surface. Their strategy views contain no `sealed`
field or label. The panel no longer says that active-run behavior is deferred to
future implementation. Existing model-profile and artifact-seal regression
tests remain green.

The expected implementation remains below roughly 500 changed lines. It removes
seal enforcement and presentation, reuses the existing retained creation record,
and extends the existing active-run record with the same complete content; no
parallel store, migration, or background process is justified.

### Risks

- Reading the mutable catalogue after binding would let a later edit silently
  change an existing run. Independence tests edit the source after both creation
  and active-run change.
- Resolving identity and content from different source moments could retain a
  mismatched pair. A controlled edit race must yield one complete valid pair.
- Removing the edit refusal while leaving first-use mutation or a `sealed` API
  field would preserve the misleading contract. Store-byte and exact-view tests
  pin both removals.
- An active-run change that retains only identity would become dependent on the
  mutable source. Its test requires complete retained content and observable
  future strategy behavior.
- A run change applied without its transition record would make later history
  ambiguous. The boundary test requires the retained pair and transition to land
  together before later strategy decisions proceed.
- Broadly replacing “seal” concepts could weaken reviewed-artifact guarantees.
  Focused artifact-seal tests remain unchanged and in the slice gate.

### Reuse Posture

The affected party is the operator: today a legitimate correction can be
refused after first use, forcing needless clones, while a misleading seal label
suggests the definition is immutable. The inverse harm is more serious: if
editability made a run follow mutable source content, prior or active work could
change strategy without an explicit choice. The reviewed skeleton requires both
editability and retained run independence.

The checked reusable surfaces are the validated strategy store and semantic
hash, the creation-time retained content and identity, the existing active-run
change resource, the interpreter's embedded-content verification and consumers,
the existing append-only run ledger, and the panel catalogue/run-detail views.
The cheapest sufficient response is to remove seal authority and presentation,
reuse one self-consistent retained pair for creation, and add that same complete
pair to the existing run-change record. The existing strategy interpreter
consumes it and the existing ledger records one applied transition; no second
store or history system has an authorised consumer. The change is subtractive
apart from one retained content value and one existing-ledger event, has no
migration or operating service, and is readily reviewable. Omitting retention or
the transition risks silent strategy drift or ambiguous history; adding archives,
versions, or concurrency machinery costs more without an authorised outcome.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's strategy-only outcome: editable reusable
  definitions, self-contained run retention, explicit active-run changes, and
  truthful presentation.
- **Revise:** older brainstorming language that required first-use seals,
  immutable used definitions, cloning to edit, or validation against the later
  mutable source.
- **Reject:** brainstorming and `_drafts` material as independent authority, and
  any attempt to pull Slice 5's decision catalogue or Slice 6's configurator into
  this slice.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Strategy catalogue edit | `GET /api/profiles` remains HTTP 200 `{"ok":true,"profiles":[...]}`. Administrative `POST /api/profiles` remains the sole create/whole-edit operation and returns HTTP 200 `{"ok":true,"profile":{...}}`; invalid input remains HTTP 400 with the common non-empty error envelope. A valid same-name edit succeeds regardless of prior use. Selecting a strategy never mutates its reusable source. | `implementation/milestones/model-profiles/skeleton.md:25-35,62,117`; goal intent `implementation/milestones/model-profiles/goal.md:115-141`; routes/access `orchestrator/service.py:3715-3716,4039-4042`; current refusal seam `orchestrator/profiles.py:124-148,168-189` | touch: retire first-use mutation/refusal while reusing validation and whole save; do-not-add another route, clone requirement, migration, or catalogue history |
| Strategy surface shape | Catalogue GET/POST views expose `name`, `version`, stored `description`, `hash`, and complete `profile`; they expose no `sealed` key. Stored descriptions round-trip exactly, including `legacy`; no seed text masks an operator edit. Launch and active-run selectors contain no `sealed` label. POST tolerates an incoming legacy `sealed` member but ignores it as authority and omits it from the response. Legacy stored seal metadata is inert and may remain on disk until an ordinary edit. | `implementation/milestones/model-profiles/skeleton.md:25-35,97-101,117`; current view/label seams `orchestrator/service.py:2624-2665`; `orchestrator/static/panel.html:4453-4529` | touch: API view, exact stored description, and strategy labels; do-not-bulk-rewrite stored files or relabel artifact seals |
| Retained strategy identity | A retained strategy identity is exactly `{name, version, hash}` and `hash` matches the complete retained semantic `profile` content through the existing semantic-identity contract. Verification compares retained identity with retained content, never with the later mutable catalogue source. | retention authority `implementation/milestones/model-profiles/skeleton.md:33-35,62,100-101,117`; identity seam `orchestrator/profiles.py:53-58,181-203`; embedded verification `orchestrator/interpreter.py:180-203` | touch: reuse semantic identity and redirect verification to the retained pair; do-not-add source archives, generations, or revalidation against current source |
| Run creation retention | Successful run creation with a strategy retains one complete, self-consistent content-and-identity pair before the run is returned or started. A concurrent catalogue edit may make that pair the complete earlier or later definition, never a mixture. Later source edits do not change or invalidate it. Unknown or malformed selections remain HTTP 400 and create no run state. | `implementation/milestones/model-profiles/skeleton.md:62,117`; goal intent `implementation/milestones/model-profiles/goal.md:120-132`; existing creation seam `orchestrator/service.py:1992-2010,2149-2157`; creation tests `orchestrator/tests/test_service_api.py:1909-1947` | touch: make existing retained creation resolution self-consistent and non-sealing; do-not-read mutable source as run authority after acceptance |
| Active-run strategy change | `POST /api/runs/{id}/profile` keeps body `{"profile":"<name>"}`, existing run access, HTTP 200 `{"ok":true,"profile_swap":...}`, HTTP 400 for malformed/unknown profile, and HTTP 404 for unknown run. Success retains the target's complete content plus matching identity as one prospective run record, whether or not the run had a base strategy. Unless superseded, it governs from the next strategy boundary; prior decisions are unchanged. Application appends exactly one generic-ledger event with `type: "profile_changed"`, `from` (prior retained identity or `null`), `to` (replacement identity), and `profile` (complete replacement semantic content). Later source edits have no effect until another explicit change. | `implementation/milestones/model-profiles/skeleton.md:62,117`; goal intent `implementation/milestones/model-profiles/goal.md:120-141,219-222`; existing route/record seams `orchestrator/service.py:2572-2621,2737-2768,4055-4058,4094-4096`; named pickup seam `orchestrator/service.py:2579-2585,2737-2747`; generic ledger `orchestrator/state.py:352-356`; interpreter consumers `orchestrator/interpreter.py:32-105`; `orchestrator/driver.py:352,718-722,3243,4656,5172,5382-5383` | touch: extend the existing run-change record, bounded driver pickup, and generic ledger; do-not-add automatic source following, retrospective rewrite, or a second transition system |
| Isolation | A1/B1 current-state semantics apply only to model profiles. Model-profile catalogue/selection/override behavior, strategy decision support status, generic execution/accounting/recovery, and calling-product repositories are untouched. Artifact seals, family rotation, and deterministic review-derived seals retain their existing behavior and vocabulary. | `implementation/milestones/model-profiles/skeleton.md:3-6,33-35,48-53,100-101,115-118`; artifact-seal gate `orchestrator/state.py:1000-1043`; regression `orchestrator/tests/test_seal_predicate.py:144-159` | touch: strategy store/service/panel/interpreter only; do-not-touch model-profile machinery, strategy decision catalogue, artifact-seal machinery, or granted repositories |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_profiles.TestEditability orchestrator.tests.test_service_api.ProfilesApiTest orchestrator.tests.test_interpreter.GoverningProfileTest orchestrator.tests.test_interpreter.EffectiveConfigTest orchestrator.tests.test_seal_predicate.SealPredicateDriverTest`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Used definitions remain editable | `test_used_profile_edit_replaces_content_without_first_use_mutation` | Create and active-run use leave catalogue bytes unchanged; a later valid same-name semantic edit returns 200 and is immediately listed; legacy `sealed:true` storage does not block it. | strict |
| Rejected edits are non-mutating | `test_invalid_strategy_edit_preserves_prior_definition` | Invalid POST returns 400 with a non-empty error and leaves the prior complete definition readable. | strict |
| Creation retains an independent pair | `test_creation_retains_content_and_identity_across_source_edit` | The retained content hashes to the retained identity; editing the source afterward changes neither run detail nor interpreted behavior and causes no divergence failure. | strict |
| Binding races cannot mix identity and content | `test_creation_racing_edit_retains_one_complete_definition` | A controlled edit during creation yields either the complete before-edit pair or complete after-edit pair, never a cross-pair. | strict retained pair; optimistic edit ordering |
| Active changes retain, govern, and record | `test_profile_swap_retains_content_and_governs_future_decisions` | The existing POST works with or without a base profile; run detail reports the new identity, the next strategy boundary appends one exact `profile_changed` event and uses retained content, prior decisions remain unchanged, and a later source edit has no effect. | strict pair/transition; eventual boundary delivery |
| Strategy surfaces are truthful | `test_strategy_views_and_panel_have_no_sealed_presentation` | Catalogue response entries have no `sealed` key; an edited `legacy` description round-trips exactly; launch/repoint labels and explanatory text contain no editable-definition seal claim or “later phase” disclaimer. | strict |
| Artifact seals are isolated | existing `test_reform_skeleton_seals_by_predicate` plus the focused `SealPredicateDriverTest` class | Reviewed units still seal from the same current-byte predicate and no strategy edit or run change mutates artifact-seal records. | strict |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-524`).

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Direct code consumers:** the strategy store; service catalogue, run-creation, run-detail, and active-change resources; the panel's launch/repoint labels; and the interpreter/driver decisions that consume retained content. **People/API consumers:** administrators edit definitions and authorised run users select or replace strategy. **Not touched:** model-profile consumers, strategy-catalogue work reserved to Slices 5–6, artifact-seal machinery, and granted repositories. | `orchestrator/profiles.py:53-58,61-203`; `orchestrator/service.py:1992-2010,2149-2157,2572-2665,2737-2768,3715-3716,4039-4042,4094-4096`; `orchestrator/static/panel.html:3712-3723,4453-4545`; `orchestrator/interpreter.py:32-105,180-203`; boundary `implementation/milestones/model-profiles/skeleton.md:33-53,62-66` |
| pinned_facts | The closed facts are edit-after-use through the existing catalogue route; no first-use source mutation; no `sealed` API/panel presentation; exact retained `{name,version,hash}` plus complete content; self-consistent creation and active-change retention; the exact `profile_changed` transition at the next strategy boundary; current validation/access/error envelopes; and isolation from model profiles, decision-catalogue work, and artifact seals. | `implementation/milestones/model-profiles/skeleton.md:25-35,55-66,100-118`; intent trace `implementation/milestones/model-profiles/goal.md:115-141,219-222`; named existing seam `orchestrator/service.py:2579-2585,2737-2747`; this note's Pinned-Facts Table |
| verification | Focused store/API tests replace obsolete seal/refusal expectations and pin editability, non-mutation, exact response shape, retained-pair independence, active-run behavior and transition, and controlled binding races. Existing interpreter and artifact-seal tests pin reused consumption and isolation. Full unittest discovery remains the closure gate. | obsolete expectations `orchestrator/tests/test_profiles.py:1-12,44-107`; current API coverage `orchestrator/tests/test_service_api.py:1893-2064`; interpreter checks `orchestrator/tests/test_interpreter.py:17-124`; artifact isolation `orchestrator/tests/test_seal_predicate.py:144-159`; suite `orchestrator/README.md:522-524`; this note's Verification Contract |
| reuse_posture | **Checked/reused:** validated strategy load/save, semantic hash, creation snapshot, run-change resource, embedded verification/interpreter, generic append-only ledger, API access/errors, and panel selectors. **Cheapest sufficient:** remove seal authority/presentation and retain the same complete pair on the existing active-change record. **Remaining machinery/consumer:** one self-consistent resolution result, one retained-content value consumed by the interpreter, and one `profile_changed` record in the existing ledger. **Lifecycle:** no migration/background service; small persistent cost per applied change, while omission permits refused edits, mutable-source drift, or ambiguous history and archives/versioning/locks would add unjustified cost. | `orchestrator/profiles.py:53-58,61-203`; `orchestrator/service.py:1955-1971,2149-2157,2572-2665,2737-2768`; `orchestrator/interpreter.py:32-105,180-203`; `orchestrator/state.py:352-356`; authority `implementation/milestones/model-profiles/skeleton.md:43-53,62,117-118,132-160` |
| enforceability | **Editability/non-mutation:** remove sealing from the validated whole-save/reference seam and test catalogue bytes across use. **Retained independence:** existing semantic hash, embedded content, and retained-pair verification. **Active change:** existing singular run resource and run-side record feed bounded driver pickup, existing interpreter/driver consumers, and one generic-ledger `profile_changed` event. **Surface truth:** exact API-key and served-panel text assertions. **Failure/access:** current validation, admin/run gates, and common 400/404 envelopes. **Isolation:** existing artifact-seal suite and model-profile route regressions. The note promises no concurrent-edit winner, merge, crash durability, or recovery beyond mechanisms already present. | `orchestrator/profiles.py:61-148,181-203`; `orchestrator/service.py:1955-1971,1992-2010,2149-2157,2579-2585,2624-2665,2737-2768,3715-3716,4039-4042,4055-4058,4094-4096`; `orchestrator/state.py:352-356`; `orchestrator/static/panel.html:4453-4545`; `orchestrator/interpreter.py:32-105,180-203`; `orchestrator/tests/test_seal_predicate.py:144-159` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Prior use never blocks or mutates a reusable definition | Reuse strategy validation and whole replacement while retiring the first-use mutation/refusal paths (`orchestrator/profiles.py:61-148,168-189`). | Store and API tests compare source bytes across use, then edit a legacy used definition under the same name. |
| Every accepted run record has matching identity and content | Reuse one validated source read plus `semantic_hash` (`orchestrator/profiles.py:53-58,95-105`) to materialise the retained pair; verify the retained pair internally (`orchestrator/interpreter.py:180-203`). | Creation, active-change, later-source-edit, and controlled-race tests assert the retained hash/content pair and behavior. |
| Source edits never re-govern a run implicitly | Creation already embeds content (`orchestrator/service.py:1955-1971`); the existing active-change record is the only run-change seam (`orchestrator/service.py:2572-2621,2737-2768`). Strategy consumers read retained content (`orchestrator/interpreter.py:32-105`). | Tests edit the selected source after each binding and prove run detail, interpreter results, and retained bytes stay unchanged until another POST. |
| Active-run changes are prospective and observable | Existing `POST /api/runs/{id}/profile`, run access gate, run-detail projection, driver pickup seam, generic `append_event`, and interpreter/driver consumers (`orchestrator/service.py:2572-2621,2737-2768,4055-4058,4094-4096`; `orchestrator/state.py:352-356`; `orchestrator/driver.py:352,3243,4656,5172,5382-5383`). | A run with prior recorded decisions changes strategy; the next strategy boundary appends exactly one `profile_changed` record with the retained replacement, later decisions use it, and prior records remain byte-identical. |
| Editable strategies are presented truthfully | Remove `sealed` and the `legacy` seed-description substitution from `_profile_view`, remove the seal suffix from `profileLabel` (`orchestrator/service.py:2624-2640`; `orchestrator/static/panel.html:4458-4461`), and remove deferred-behavior copy (`orchestrator/static/panel.html:3712-3723,1005-1014`). | Exact response-schema, edited-description, and served-panel assertions reject the key, label, masked edit, or obsolete disclaimer. |
| Invalid operations preserve prior state | Existing validation precedes catalogue/run mutation (`orchestrator/profiles.py:61-105,124-148`; `orchestrator/service.py:1992-2010,2737-2760`) and common route envelopes map failures (`orchestrator/service.py:4039-4042,4094-4108`). | Invalid document, missing name, unknown strategy, unknown run, and corrupt retained-pair cases assert status and unchanged bytes. |
| Artifact seals and model profiles remain independent | Existing artifact-seal predicate/tests and separate model-profile routes (`orchestrator/state.py:1000-1043`; `orchestrator/tests/test_seal_predicate.py:144-159`; `orchestrator/service.py:3715-3721,4039-4046,4087-4096`). | Focused isolation tests plus full discovery remain green with no changed artifact-seal or model-profile fixtures. |

Any implementation that makes a run follow later source edits, retains identity
without matching content, omits the applied `profile_changed` transition, keeps a
first-use edit refusal or `sealed` presentation, weakens artifact seals, or builds
Slice 5/6 functionality does not deliver this slice.
