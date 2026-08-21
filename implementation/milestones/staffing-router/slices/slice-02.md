# Slice 02 — Staffing document store

## Register 1 — INTENT (lay language)

### What this slice builds

Today the orchestrator decides who does a piece of work from a **model
profile**: a named file that says, for each rigor, which agent family runs each
process step and with which model and effort. This slice builds the thing that
replaces it — the **staffing document** — and the store that keeps it. Nothing
reads a document yet; this slice only makes documents exist and makes them
correct.

A staffing document is deliberately made of numbers. It lists the agent
families as numbered slots, each with two ladders: its models, ordered from the
least to the most capable, and its effort levels. A tuning table then says, for
each rigor and each family slot and each process step, which rung of each ladder
to use. An assignment table says which family slot sits in each seat. Materials
are the owner's own words for kinds of work, each with a few usage phrases, and
overrides say what a material changes. Rules are a short typed list. Because
everything that selects is a number, a document can be read, diffed and edited
without knowing anything about how resolution works.

The store keeps documents the way the profile store already keeps profiles:
list, load, and a whole-document create-or-replace whose save refuses an invalid
document **loudly, before a single byte changes**, so a stored document is always
complete. A damaged stored document makes listing fail rather than quietly
presenting a shorter catalogue.

Nobody rewrites their profiles by hand. When the orchestrator starts, it
converts each profile it finds into a document of the **same name**, once.
Conversion is missing-only: a document that already exists — a converted one the
operator has since edited, or one written by hand — is never overwritten. The
profile files themselves are only read; they are never edited, moved or deleted,
and they keep deciding every call's staffing until a later slice cuts the
consumers over.

Conversion is a **normalization**, not a copy. A profile can say things a
document has no way to hold — "the family opposite whoever is calling", "the
caller's own effort", a family that differs from rigor to rigor — because a
document's assignment is one table for all rigors. Those become explicit
numbers, taken from the profile's `medium` configuration and from the same
reference today's resolution uses, so the converted document staffs each seat
the way that profile staffs it today. Where today's answer depends on who was
calling, the document holds one of those answers, not both. The resulting
document is complete: every seat has a family and every rigor / family / step
cell has a pair of rungs, including the cells a profile never used, which take
that family's ordinary defaults.

Two things the ladders add. First, a converted family carries its **whole
vocabulary** — every model and every effort that family has — not only the
values the profile happened to use, so that a later "step up when work is stuck"
rule has rungs above today's choice to climb into. Second, the ladder order is
the **operator's**: least capable to most capable as he judges it, never by
price, even where the two happen to agree. That order is written once, as
operator data inside the document, and only an operator's save reorders it.

What this slice deliberately does not do: nothing in the system asks a document
for anything. Every call the orchestrator makes is staffed exactly as it is
staffed today. The documents appear beside the profiles and wait.

### Ownership and boundary

This slice owns the document schema and its validation, the store (list, load,
whole-document save), the in-code `default` seed, and the one-time missing-only
conversion of existing profiles together with the start-up initialization that
runs it — the same initialization moment at which the profile store already
seeds its own `default`.

It owns no staffing behaviour. There is no session, no resolver, no route, no
panel surface, no marker field, and no change to how any call is staffed,
dispatched, resumed or priced. The document is inert data until the next slices
give it readers.

### Guarantee posture

- **Strict — save-time validation.** An invalid document is refused before any
  byte changes and the previously stored document stays byte-identical. A
  stored document is always complete: every role has an assignment for index 1
  and every rigor / slot / role has a tuning pair, so it can be resolved without
  consulting anything else.
- **Strict — loud store.** One damaged stored document makes listing fail
  instead of returning a silently shortened catalogue; document names are
  case-insensitively unique.
- **Strict — conversion.** Conversion is deterministic and reproduces the
  profile's staffing seat by seat at every rigor, on the reference the design
  fixes. It never fails and never skips a *valid* profile.
- **Strict — the `default` floor.** After initialization a valid `default`
  document exists: converted from the stored `default` profile when one exists,
  otherwise from the in-code seed. A stored `default` is never seeded over.
- **Optimistic — concurrent whole-document saves.** There is no compare-and-set
  and no version: two saves of the same name each land atomically and the last
  completed one wins, exactly as the profile store behaves today.
- **Best-effort — none added.** This slice introduces no marker, projection, or
  bookkeeping value, and promises nothing about freshness or survival.
- **Eventual — none.** There is no replication, queue, or convergence here.

### Dependencies and consumers

This slice follows slice 1 in the milestone's order but has no functional
dependency on it: it neither uses nor changes the executor id. What it does
depend on is existing and unchanged — the model-profile store as a **read-only
input**, the driver's shipped configuration (its family order, its per-family
model and effort defaults, and its act policies) and the act-resolution seams
that define what "today's staffing" means, and the panel's per-family model and
effort vocabularies.

The consumers it touches are the three places where the profile catalogue is
already initialized: the driver's start-up readiness check, run creation, and
service start-up. Each gains the staffing catalogue initialization beside the
profile seed. No dispatch path, route, or panel surface is touched.

Its consumers downstream are later slices only: the resolver, the driver
cutover, the API, and the panel each read documents through this module.

### Non-goals

- No session record, no resolver, and none of the resolver's behaviour:
  collapse, saturation, `step_up` arithmetic, material precedence, the default
  document fallback, or the two surfaced conditions.
- No route, no panel surface, no marker field, no `resolved_staffing` change.
- No planner material channel and no material vocabulary invented for the
  operator.
- No retirement of the model profile, the acts sidecar, or any dispatch path;
  they keep deciding staffing until their own slices.
- No read of a document by anything that staffs a call, including the per-role
  seat-index read the review cycle will need, which belongs with its consumer.
- No migration, rewrite, or deletion of stored records or profile files, and no
  census of existing runs.
- No document version, snapshot, sealing, identity, or lifecycle; no second rule
  type; no expression language or rule engine.
- No edit to the granted read-only roots.

### Acceptance

The slice is accepted when focused tests prove all of the following. A document
whose shape departs from the closed schema — an unknown key, a missing rigor, a
role without an index-1 assignment, a missing tuning cell, an unknown rule type,
a rank that is not a positive integer, an empty ladder — is refused on save and
leaves the previously stored document byte-identical; a whole-document replace
wholly replaces; a differently cased name is refused; and one damaged stored
file makes listing raise.

Conversion is proven against the profiles that exist rather than invented ones,
and the seat-by-seat drift alarm runs over each of those shapes rather than one:
the profile store's own seeded `default`; a profile shaped like this machine's
stored `default`, whose plan, draft, implement and fix acts all sit on the first
family and which pins a `brainstorming_counterpart` effort the seed pins at no
rigor, plus at one rigor a counterpart model — the one seat whose model a
profile may pin and no profile stored here pins; and a profile shaped like this
machine's `claude-lead`, whose `medium` fixer sits on the second family. Each
converts to a document whose staffing equals today's effective staffing seat by
seat at every rigor, measured through the real resolution seams. The
`claude-lead` shape additionally seats the consultation on that fixer's
opposite family and never on the no-origin first-family fallback; every
converted family slot carries its whole vocabulary
in the operator's order; a second initialization leaves an edited document and
every profile file byte-identical; a profile added later is converted at the next
initialization; and a damaged profile is skipped without failing initialization.

That today's staffing is unchanged is proven by the existing model-profile and
runtime suites passing unmodified.

**Size.** This slice is expected to exceed the ~500 changed-line aim, and the
reason is structural rather than scope creep: the closed schema's validation *is*
the slice's strict guarantee and cannot be separated from the shape it validates;
the conversion must fill every rigor / slot / role cell to produce the complete
document the guarantee promises; and the drift alarm compares every seat at every
rigor for each converted profile shape. Splitting the schema from its validation
would ship a store whose stated posture is unenforced, and splitting the
conversion off would leave no `default` document at all. The slice is already
reduced by everything it defers: no resolver, no session, no route, no panel.

### Risks

- **Conversion silently changing today's staffing.** A wrong reference for one
  seat is invisible until a real call runs at the wrong family, and conversion is
  missing-only, so a wrong document is not corrected by a later start. The
  seat-by-seat drift alarm at all three rigors, measured through the real
  resolution seams rather than by re-deriving them, is the guard, and it runs
  over each profile shape that exists rather than the seed alone: a defect can be
  specific to a configuration the seed does not carry — an act pinned on the
  other family, the `brainstorming_counterpart` effort the seed never pins, or
  the counterpart model the panel offers and no profile stored here uses — and
  would otherwise pass every named check. The `claude-lead`-shaped case
  additionally pins the single seat whose naive derivation differs from the
  correct one.
- **Ladder order copied from the panel.** The panel's model lists are ordered
  strongest first for display. Copied verbatim they would invert the operator's
  order and make "step up" climb downwards. The ladder check asserts the
  operator's order explicitly and separately asserts that the ladder covers the
  panel's vocabulary for that family.
- **Two copies of the family vocabulary.** The panel keeps its own lists until a
  later slice retires the profile editor, so the vocabulary exists twice. The
  answer is a static check that the converted ladders and the panel's lists name
  the same models and efforts — not a new sharing mechanism.
- **Start-up becoming louder than it is today.** Reading every profile at
  initialization could turn a damaged non-`default` profile into a start-up
  failure that does not exist today. The rule is skip and continue, asserted with
  a damaged profile present.
- **Overwriting the operator's edits.** A conversion that ran unconditionally
  would silently revert an edited document at the next start. Missing-only is
  asserted by a second initialization over an edited document.
- **Incomplete tuning.** Cells a profile never staffed are exactly the cells a
  later collapse lands on; leaving them out would produce a document that
  validates in principle but cannot answer. Completeness is enforced on save and
  the conversion fills unused cells with that family's ordinary defaults.

## Register 2 — PINNED FACTS (hard register)

**Base staffing** is used below as a pure lookup in a stored document:
`assignment[role][index]` gives the slot, `families[slot].name` the family, and
`tuning[rigor][slot][role]` gives the two 1-based rungs on that slot's `models`
and `efforts` ladders. It uses no session, no material, no rule and no fallback,
so it is computable from the document alone and needs nothing this slice defers.

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Module and store | `orchestrator/staffing.py` owns documents; records live in the service home in their own directory, beside `model_profiles/` and never inside it. The model-profile store is a read-only input: profile files are read, never edited, moved or deleted. | `implementation/milestones/staffing-router/skeleton.md:225-226,162`; store pattern `orchestrator/model_profiles.py:77-82,257-294,314-346` | touch the new module and its directory; do-not-write, move, or delete any file under `model_profiles/`, and do-not-add a second store |
| Document shape | Exactly `name`, `families` (numbered slots: `name`, `models` ladder weakest→strongest, `efforts` ladder in that family's vocabulary), `roles`, `materials` (name → `examples`), `tuning` (rigor → slot → role → `[model_rank, effort_rank]`, 1-based), `assignment` (role → index → slot), `overrides` (material → `assignment`, rarely `tuning`), `rules` (typed; only `step_up` with `role` and `min_round`). Rigors exactly `low`, `medium`, `high`; roles exactly the nine of the closed vocabulary. Complete means every role has an assignment for index 1 and every rigor × slot × role has a tuning pair. Names case-insensitively unique. Validated loudly on save, before any byte changes. | `implementation/milestones/staffing-router/skeleton.md:311,309`; `implementation/milestones/staffing-router/goal.md:103-127`; reused validator shape `orchestrator/model_profiles.py:204-254,314-346` | touch the new schema; do-not-add a version, snapshot, sealing flag, document-level `examples`, a second rule type, or an expression language |
| Ladder order (amendment A1) | Models weakest→strongest by capability as the operator judges it, never by price: `gpt-5.6-luna` < `gpt-5.6-terra` < `gpt-5.6-sol`; `claude-sonnet-5` < `claude-opus-5` < `claude-fable-5`. Efforts `low` < `medium` < `high` < `xhigh` < `max`. A converted slot carries its family's whole vocabulary, not only the values the profile used. The order is operator data in the document, reordered only by a document save. | run amendment A1; `implementation/milestones/staffing-router/skeleton.md:190-205`; vocabulary `orchestrator/static/panel.html:5286-5293` (models listed strongest-first for display), CLI verification `orchestrator/driver.py:88-94` | touch the conversion's ladder construction; do-not-copy the panel's display order, do-not-order by `orchestrator/pricing.py:121-134`, and do-not-treat the written order as a code constant |
| Conversion trigger and posture | At catalogue initialization — the moment the profile store already seeds its `default`, which runs at each service and driver start — every readable, valid stored profile gains a document of the same name. Missing-only: an existing document of that name is never rewritten, so a profile created later is converted at the next start. A profile that cannot be read or validated is skipped: it produces no document and does not fail initialization. Conversion never fails and never skips a valid profile. | `implementation/milestones/staffing-router/skeleton.md:140-144,162,189-190`; adjudicated `implementation/milestones/staffing-router/adjudications.md` `[skeleton-codex-r1/SR-SKEL-002]`; call sites `orchestrator/driver.py:746`, `orchestrator/driver.py:11132`, `orchestrator/service.py:5018`; missing-only pattern `orchestrator/model_profiles.py:409-421` | touch the three initialization sites; do-not-fail initialization for a damaged profile, do-not-overwrite an existing document, and do-not-make conversion a repair or migration step |
| Conversion reproduces today | For every rigor, the converted document's base staffing for each seat equals today's effective staffing for that seat's reference act under the same profile, per the Conversion Reference below. Assignment is rigor-independent and taken from the profile's `medium` configuration; each rigor's tuning reproduces that rigor's model and effort where the profile staffs that family. Where today's answer depends on the caller, the document holds one of them: the failure classifier shares `classify 1` with the reclassifier, and `consult 1` is resolved with the converted `fix 1` family as origin. | `implementation/milestones/staffing-router/skeleton.md:163-190,215-220,325`; `implementation/milestones/staffing-router/goal.md:103-127` | touch the conversion; do-not-invent a per-rigor assignment, do-not-carry both origins, and do-not-preserve a policy string in the document |
| Unstaffed cells and unknown values | A rigor × slot × role cell the profile does not staff carries that family's ordinary defaults today (`model_defaults`), which is what a call on that family resolves to when nothing is pinned. A model or effort a profile names that its family's vocabulary does not carry is appended after that family's known rungs, so the converted staffing still reproduces exactly and A1's order of the named models is untouched; a seat whose act names a family the configuration has no slot for — a profile that cannot run today either — seats on slot 1. Nothing here fails. | `orchestrator/driver.py:99-102`; filling seam `orchestrator/driver.py:8049-8053`; representable because the profile store applies no vocabulary whitelist `orchestrator/model_profiles.py:85-96`; `implementation/milestones/staffing-router/skeleton.md:189-196` | touch the conversion's fill rules; do-not-fail, drop a value, or silently substitute a different model |
| The `default` floor | After initialization a valid `default` document always exists: converted from the stored `default` profile when one exists — `default` included, never seeded over — otherwise from the in-code seed, which is the conversion of the profile store's own `default` seed, so an unconfigured run's `default@medium` staffs every seat as today. | `implementation/milestones/staffing-router/skeleton.md:145-162`; profile seed `orchestrator/model_profiles.py:363-421`; today's drift alarm `orchestrator/tests/test_model_profiles.py:481-492` | touch the in-code seed; do-not-seed over a stored `default`, and do-not-pin the goal's illustrative literals instead of the behaviour |
| What conversion does not write | No materials, no overrides, no rules: a profile carries nothing that maps to them and inventing an owner vocabulary is not conversion. The closed shape has no document-level `examples`, so a profile's clue strings do not convert. `roles` carries all nine roles with `distinct_families` true only for `review`. | `implementation/milestones/staffing-router/skeleton.md:311,309`; `implementation/milestones/staffing-router/goal.md:117-127,97-101`; cross-family review law `orchestrator/state.py:887-892` | touch the conversion's empty blocks; do-not-seed a material catalogue, a `step_up` rule, or a second `distinct_families` role |
| Slice boundary | Nothing reads a document to staff a call in this slice: no session, resolver, route, panel surface, marker field, or seat-index document read. `model_profile.json` and `acts.json` remain the dispatch inputs until slice 4, and every call is staffed exactly as today. | `implementation/milestones/staffing-router/skeleton.md:290,291,292,300-303,319` | touch documents and their initialization only; do-not-pull the resolver, a session, a route, or a consumer cutover forward |

### Conversion Reference

What each converted seat must reproduce, verified in code. Assignment comes from
the profile's `medium` configuration; each rigor's tuning comes from that rigor's.

| document seat | today's reference | authority (file:line) |
|---|---|---|
| `plan 1` | the `skeletoner` act as a skeleton dispatch resolves it, with the skeleton's own family and effort re-asserted and the model filled from the resolved family | `orchestrator/driver.py:8106-8127,8036-8053` |
| `draft 1` | the `drafter` act, model and effort filled from the resolved family's defaults | `orchestrator/driver.py:8082-8083,8042-8053` |
| `implement 1` | the `implementer` act, filled the same way | `orchestrator/driver.py:8084-8085,8042-8053` |
| `fix 1` | the `fixer` act with `codex` as its default family and no origin | `orchestrator/driver.py:8086-8095` |
| `classify 1` | the `reclassifier` act; the failure classifier shares this seat and so reproduces one of its two answers | `orchestrator/driver.py:8247-8253`; `implementation/milestones/staffing-router/skeleton.md:179-184` |
| `review 1`, `review 2` | the fixed review families in configured order, each with `review_<family>`'s model and effort filled from that family's defaults | `orchestrator/driver.py:8221-8234`; `orchestrator/driver.py:59` |
| `brainstorm 1` | the Brainstorming lead: the `implementer` act filled from its family's defaults | `orchestrator/driver.py:8156-8164` |
| `brainstorm 2` | the counterpart: the family opposite `brainstorm 1`'s, with the profile's `brainstorming_counterpart` model and effort where it pins them — otherwise that family's default model and the lead's effort | `orchestrator/driver.py:8166-8187` |
| `brainstorm 3` | Dante, pinned from the lead profile | `orchestrator/brainstorming_milestone.py:301-317` |
| `consult 1` | the consultation the fixer runs: the `consultation` policy resolved with the converted `fix 1` family as origin, the consulted family's default model, and the fixer's effort | `orchestrator/current_model_call.py:15-65`; `orchestrator/driver.py:1344-1352` |
| `sync 1` | work-area git alignment: the first configured family with that family's defaults | `orchestrator/service.py:3468-3473` |
| any other rigor × slot × role cell | that family's ordinary defaults today | `orchestrator/driver.py:99-102,8049-8053` |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_staffing_documents orchestrator.tests.test_model_profiles orchestrator.tests.test_model_profile_runtime`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| The document shape is closed and completeness is enforced on save | new `test_document_shape_is_closed_and_complete` (`orchestrator/tests/test_staffing_documents.py`) | An unknown top-level key, a missing or extra rigor, an unknown role, a role without an index-1 assignment, a missing rigor × slot × role tuning cell, a rank that is not a positive integer, an empty ladder, and a rule whose type is not `step_up` are each refused; after every refused save the previously stored document is byte-identical. | strict |
| The store creates, wholly replaces, lists and loads loudly | new `test_store_create_replace_list_and_damage`, mirroring `orchestrator/tests/test_model_profiles.py:212-270` | A same-name save wholly replaces with no key-wise merge; loading an unknown name raises; one damaged stored file makes listing raise instead of shortening the catalogue; a differently cased name is refused before writing. | strict |
| Conversion reproduces today's staffing seat by seat, for every profile shape that exists | new `test_conversion_matches_current_effective_staffing`, using the real-driver comparison surface of `orchestrator/tests/test_model_profiles.py:423-492` | For each of the three profile shapes the Acceptance names — the profile store's `default` seed, a stored-`default`-shaped profile (plan, draft, implement and fix on the first family, with a `brainstorming_counterpart` effort pinned and, at one rigor, a counterpart model pinned) and a `claude-lead`-shaped one — and for each of `low`, `medium`, `high`, that profile's converted document's base staffing for every seat of the Conversion Reference equals the same seat resolved by a real `Driver` over the shipped configuration carrying that rigor's profile configuration; no seat is compared as a `None` placeholder. The in-code document seed equals the conversion of the profile store's `default` seed. | strict |
| The one seat a naive conversion gets wrong | new `test_second_family_fixer_seats_consult_on_its_opposite` | A profile shaped like this machine's `claude-lead` — `medium` fixer on the second configured family — converts `consult 1` onto that fixer's opposite family, and not onto the family the no-origin fallback would pick. | strict |
| Ladders carry the whole vocabulary in the operator's order | new `test_ladders_are_whole_vocabulary_in_operator_order` | Every converted family slot's `models` is exactly `["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]` or `["claude-sonnet-5", "claude-opus-5", "claude-fable-5"]` and its `efforts` exactly `["low", "medium", "high", "xhigh", "max"]`, whatever the profile used; the same models and efforts appear in the panel's per-family lists, read from `orchestrator/static/panel.html` as `orchestrator/tests/test_task_panel.py:9-13` reads it. | strict |
| Initialization is missing-only and only reads profiles | new `test_initialization_is_missing_only_and_reads_profiles` | A second initialization leaves an edited document byte-identical; every profile file is byte-identical before and after; a profile written between the two initializations gets its document at the second. | strict |
| A damaged profile does not fail initialization | new `test_damaged_profile_is_skipped` | With an unreadable and a structurally invalid non-`default` profile present, initialization completes, writes no document for either, and still yields a valid `default` document. | strict |
| Today's staffing is unchanged | existing `orchestrator/tests/test_model_profiles.py` and `orchestrator/tests/test_model_profile_runtime.py`, unmodified | Both pass unmodified, including `test_default_medium_matches_current_effective_staffing` (`orchestrator/tests/test_model_profiles.py:481`). | strict |

The repository closure gate is unchanged:
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:524`; `implementation/milestones/staffing-router/skeleton.md:325`).

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These entries are the slice-scoped remainder. Enforceability is answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified in code, touched here:** the three places that already initialize the profile catalogue — the driver's start-up readiness check, run creation, and service start-up — each gains staffing catalogue initialization beside the existing profile seed. **Verified read-only, therefore not edited:** the model-profile store, which conversion reads; the driver's shipped configuration and act-resolution seams, which define what conversion must reproduce; the panel's family vocabulary lists, which the ladder check reads statically. **Verified not touched:** every dispatch path — driver act resolution, the Brainstorming seat resolver, the standalone task host, git alignment — none of which learns of documents in this slice. | `orchestrator/driver.py:746`; `orchestrator/driver.py:11132`; `orchestrator/service.py:5018`; `orchestrator/model_profiles.py:257-294,409-421`; `orchestrator/driver.py:99-102,167-203,8012-8056`; `orchestrator/static/panel.html:5286-5293`; untouched seams `orchestrator/driver.py:8032-8056`, `orchestrator/brainstorming_tasks.py:107-132`, `orchestrator/task_api.py:94-128`, `orchestrator/service.py:3468-3473` |
| pinned_facts | The closed document shape with its 1-based ranks and its completeness rule; loud save-time validation leaving prior bytes intact; the loud store and case-insensitive names; amendment A1's ladder order and whole-vocabulary ladders; conversion at catalogue initialization, missing-only, never editing a profile, skipping a damaged one, never failing; seat-by-seat reproduction on the Conversion Reference with assignment taken from `medium`; the fill rules for unstaffed cells and unknown values; the `default` floor; the blocks conversion leaves empty; and the boundary that nothing reads a document to staff a call. | `implementation/milestones/staffing-router/skeleton.md:140-205,215-220,225-226,290,309,311,319,325`; `implementation/milestones/staffing-router/goal.md:103-127`; run amendment A1; `implementation/milestones/staffing-router/adjudications.md` `[skeleton-codex-r1/SR-SKEL-002]` |
| verification | The eight-row matrix above: schema closure and completeness with byte-stable refusal; store replace / list / load / case collision; the seat-by-seat drift alarm at all three rigors for each profile shape that exists — the seed and the two stored shapes — measured through a real `Driver` rather than a re-derivation, plus the seed-equals-conversion identity; the `claude-lead`-shaped consultation seat; A1's ladder order together with a static vocabulary agreement check against the panel; missing-only initialization with byte-identical profile files; a damaged profile skipped without failing initialization; and the existing model-profile and runtime suites passing unmodified to show today's staffing is untouched. | `orchestrator/tests/test_model_profiles.py:212-270,423-492,481`; `orchestrator/tests/test_model_profile_runtime.py:186,1190,1351`; `orchestrator/tests/test_task_panel.py:9-13`; `orchestrator/README.md:524` |
| reuse_posture | **Affected party / harm:** operators, who otherwise rewrite every profile by hand into a new shape, and every later slice, which has nothing to read; the harm is misstaffed work if conversion drifts, visible per call and reversible by a document edit. **Authority:** the skeleton's conversion decision and its slice-2 row, and amendment A1 for the ladder order. **Checked and reused:** the model-profile store's whole pattern — validate-before-write, atomic same-directory replacement, loud listing, case-insensitive name uniqueness, missing-only seeding — reused rather than reinvented; the driver's shipped configuration and its act-resolution seams as the conversion reference and as the drift alarm's comparison surface, rather than a second copy of today's rules; the existing real-`Driver` equivalence-test harness; the existing static panel-reading test pattern. **Cheapest sufficient option:** one module holding schema, store and conversion, and one call at the three existing initialization sites. Cheaper options were rejected on evidence: documentation alone leaves no document to resolve; an adapter over profiles keeps two vocabularies forever and was already settled against; a migration script would need operator action and could not convert a profile created later. **New machinery and its consumer:** the document schema and store, consumed by slices 3–9; the conversion, consumed by every operator with a stored profile; and one small in-code table of each family's model and effort vocabulary, needed because that vocabulary exists today only in panel JavaScript, consumed by the conversion and the seed and guarded against divergence by a static check rather than by a new sharing mechanism. **Lifecycle cost weighed:** one module and one deterministic conversion that runs at start-up and does nothing on the second run; no operational state, no migration, no scheduled work. Omission blocks the whole milestone; the change is reversible because profile files stay untouched and deleting the document directory restores the prior state exactly. | `orchestrator/model_profiles.py:257-294,314-346,409-421`; `orchestrator/tests/test_model_profiles.py:212-270,423-492`; `orchestrator/tests/test_task_panel.py:9-13`; `orchestrator/static/panel.html:5286-5293`; `orchestrator/driver.py:99-102,8012-8056`; `implementation/milestones/staffing-router/skeleton.md:140-144,250-254,258-283` |
| enforceability | Every guarantee this note asserts has a mechanism that already exists in the repository, listed row by row in the Enforceability Gate below: save-time validation, atomic replacement and byte-stable refusal by the profile store's `save` pattern; completeness by the same validator, which is also what makes base staffing a total lookup; loud listing and case-insensitive uniqueness by the profile store's list and case-variant patterns; missing-only conversion by the existing existence-guard seeding pattern; seat-by-seat reproduction by the existing real-`Driver` equivalence harness, which measures today's answer through the resolution seams themselves; ladder order by direct assertion plus a static read of the panel's lists. **No guarantee is asserted that this slice cannot express:** it promises nothing about resolution, dispatch, sessions, markers, freshness, delivery, or the survival of any value, and it introduces no best-effort bookkeeping whose posture would need one. | `orchestrator/model_profiles.py:284-294,297-311,314-346,409-421`; `orchestrator/tests/test_model_profiles.py:212-270,423-492`; `orchestrator/tests/test_task_panel.py:9-13`; `orchestrator/driver.py:8012-8056,99-102` |

### Reuse Posture

The affected parties are the operator, who would otherwise hand-rewrite two
stored profiles into a shape he has never edited, and every later slice of this
milestone, which has nothing to read until documents exist. The realistic harm is
not the absence of a file but a conversion that drifts: work then runs at an
unintended family, model or effort, which is visible in cost and quality,
reversible by one document edit, and repeated on every call until edited. The
independent authority is the skeleton's conversion decision, its slice-2 row, and
run amendment A1 for the ladder order.

Checked and reused rather than rebuilt: the model-profile store's entire
pattern — validation before any byte changes, atomic same-directory replacement
so a refused document leaves the prior definition untouched, loud listing that
refuses to present a shortened catalogue, case-insensitive name uniqueness, and
missing-only seeding guarded by an existence check; the driver's shipped
configuration and its act-resolution seams, used as the conversion's reference
*and* as the drift alarm's comparison surface, so today's answer is measured
rather than re-derived; the existing real-`Driver` equivalence harness that the
current drift alarm already uses; and the existing pattern of reading
`panel.html` statically in a test.

The cheapest sufficient option is one module holding the schema, the store and
the conversion, plus one call at the three initialization sites that already seed
the profile catalogue. Documentation alone is insufficient because the document
is executable data every later slice reads. An adapter over profiles was already
settled against and keeps two vocabularies forever. A migration script is more
expensive to operate — it needs an operator action and cannot convert a profile
created later — while a start-up conversion is idempotent after its first run.

The machinery that remains is the schema and store, consumed by slices 3 through
9; the conversion, consumed by every operator holding a stored profile; and one
small in-code table naming each family's models and efforts, which is genuinely
new because that vocabulary lives today only in the panel's JavaScript. It is
consumed by the conversion and the seed, and the divergence it creates is met
with a static agreement check rather than a new sharing mechanism, because
retiring the panel's copy belongs to the panel slice. Lifecycle cost is one
module, no operational state, no migration, and a conversion that does nothing
on every start after the first; omission blocks the milestone, and the change is
reversible because profile files are untouched and removing the document
directory restores the prior state exactly.

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| An invalid document is refused before any byte changes and the prior one survives | Validate-then-atomically-replace, exactly as `orchestrator/model_profiles.py:314-346` does, with the refusal asserted against unchanged prior bytes as `orchestrator/tests/test_model_profiles.py:238-246` does. | Each malformed shape is asserted to raise and to leave the stored document byte-identical. |
| A stored document is always complete | The same validator: completeness — every role's index 1 assigned, every rigor × slot × role tuned — is a save-time condition, which is what makes base staffing a total lookup without the resolver. | Missing assignment and missing tuning cells are asserted to be refused. |
| A damaged store fails loudly instead of looking shorter | The loud-listing pattern that loads and validates every candidate and raises on the first invalid one (`orchestrator/model_profiles.py:284-294`). | Broken JSON, an invalid document, and a file naming another document are each asserted to make listing raise. |
| Names are case-insensitively unique | The explicit case-variant check taken before writing (`orchestrator/model_profiles.py:297-311,325-329`). | A differently cased create is asserted to be refused with nothing written. |
| Conversion is missing-only and never edits a profile | The existence-guard seeding pattern (`orchestrator/model_profiles.py:417-421`), plus the fact that conversion opens profile files read-only. | A second initialization is asserted to leave an edited document and every profile file byte-identical. |
| Conversion reproduces today's staffing seat by seat | The real-`Driver` equivalence harness (`orchestrator/tests/test_model_profiles.py:423-433,435-479`), which resolves through the production seams (`orchestrator/driver.py:8012-8056,8106-8127,8156-8187,8221-8253`, `orchestrator/current_model_call.py:15-65`) rather than restating them. | Every seat at every rigor is asserted equal for each of the three converted profile shapes — the seed and the two stored shapes — with no `None` placeholder accepted on either side. |
| Ladders carry the operator's order and the whole vocabulary | Direct assertion of the two model ladders and the effort ladder, plus a static read of the panel's per-family lists (`orchestrator/static/panel.html:5286-5293`) using the established pattern at `orchestrator/tests/test_task_panel.py:9-13`. | The exact ordered ladders are asserted, and the model and effort sets are asserted to match the panel's lists for that family. |
| Today's staffing is unchanged by this slice | The existing model-profile and runtime suites, which already pin today's effective staffing and its live-change behaviour (`orchestrator/tests/test_model_profiles.py:481`; `orchestrator/tests/test_model_profile_runtime.py:186,1190,1351`). | Both suites pass unmodified; no dispatch seam is edited. |

There is deliberately no enforcement row for resolution, sessions, markers,
delivery, or freshness: this slice asserts no guarantee about any of them.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's slice-2 row, its conversion decision, its
  document-shape and verification rows, and run amendments A1 and A3; the
  adjudicated settlement that conversion is a normalization which never fails
  and never requires a hand rewrite.
- **Revise:** no baseline decision. This note settles four points the skeleton
  leaves to the slice: that catalogue initialization is wired at the three sites
  where the profile catalogue is already seeded; that a damaged profile is
  skipped rather than failing initialization; that a rigor × slot × role cell the
  profile does not staff carries that family's ordinary defaults today; and that a
  model or effort outside a family's known vocabulary is appended after its known
  rungs, leaving A1's order of the named models untouched.
- **Reject:** brainstorming and `_drafts` material as authority; the goal
  illustration's literal numbers as a pin, the behaviour being the pin; any
  resolver, session, route, panel, marker, or consumer cutover work belonging to
  a later slice; and any edit, migration or deletion of profile files, act
  sidecars, or stored records.

Authority: `implementation/milestones/staffing-router/skeleton.md:3-5,140-226,285-303,309,311,319,325`;
`implementation/milestones/staffing-router/goal.md:103-127`; run amendments A1 and A3.
