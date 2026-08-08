# Milestone skeleton — Model Profiles and the Strategy Configurator

Goal (mandate): `implementation/milestones/model-profiles/goal.md`. This skeleton is
the implementation authority that refines it. Two registers: the intent register
carries no file:line precision; the pinned-facts table is where exactness lives.

## Intent (lay register)

**What is being built.** Two reusable, named choices an operator or a calling
product picks when ordering work, instead of filling every seat by hand and
hand-writing strategy JSON:

1. A **model profile** says what kind of work this is and how much model effort
   it warrants. It is a catalogue entry with a name (`documentation`, `core`, …),
   short matching examples, and three complete staffing configurations — rigor
   `low`, `medium`, `high` — each assigning the agent, model, and effort fields
   the existing acts already let an operator set. Picking name + rigor staffs the
   acts in one gesture. Explicit per-act operator overrides stay available on
   top and keep winning until cleared.
2. A **strategy configuration** says how the run reviews and challenges its
   work. A configurator presents the known strategy decisions with their real
   support status — active (has a runtime consumer and governs), reserved
   (kept losslessly, visibly non-operative), unknown/invalid (rejected loudly,
   never a silent no-op) — and produces the complete strategy document. It
   configures machinery that exists; it does not build dormant machinery.

Both are ordinary editable operator-owned definitions. The old "seals on first
use" rule for strategy profiles is retired. What protects history instead: every
run retains the exact configuration content it resolved at each binding, so
later edits of a reusable source affect only future bindings and can never
rewrite, restaff, or fail earlier work. Runs created before this feature keep
their staffing untouched and never consult the new editable default.

**Who consumes it.** The operator at the panel, and calling products through the
HTTP API — same names, values, validation, support status, and semantics on both.

**What this milestone owns.** The model-profile catalogue and its seeded
default; profile→act resolution, binding, retention, and per-call attribution;
the strategy decision catalogue with truthful status; retiring the first-use
seal and its presentation; the panel and API surfaces for both axes.

**What it does NOT own.** Cost or budget controls; any coupling between the two
axes; artifact sealing, family rotation, and the review-derived seal (untouched);
new risk vocabulary; new model/effort identifiers; new review machinery or
stages; the calling product's implementation; implementing today-reserved
strategy decisions (explicit later work).

### Planning context (non-canonical input)

`implementation/brainstorming/model-profiles-and-strategy-configurator/` is the
drafting history of this same goal; every agreement it reached is already in the
frozen goal, and this skeleton **adopts** them through the goal text. Of its
skeleton-delegated open questions, this skeleton decides:

- **Binding point** (decided): the model-profile selection binds per persisted
  work unit, at unit open — the unit's first act resolution. A run carries one
  current selection; changing it is prospective, so two units in one run
  diverge simply by changing the selection between their bindings. No per-slice
  pre-assignment machinery. A call outside any unit resolves the run's current
  selection at that call.
- **Edit representation** (decided): edits modify the stored definition in
  place under its name — no mandatory version advance, no retained older source
  documents. History lives in the run-retained snapshots, not in the source.
- Implementing reserved strategy decisions stays out of scope by the goal.

## Planned slices

| # | Slice | Intent (one line) |
|---|-------|-------------------|
| 1 | Model-profile store and seeded default | The catalogue document (name, examples, three complete rigors of per-act staffing), validation with loud rejection, the editable seeded `default`, list/create/edit API. |
| 2 | Profile resolution, binding, and attribution | The driver resolves selection→acts under the pinned precedence, binds and retains at unit open, attributes every call, applies changes prospectively, leaves pre-feature runs untouched. |
| 3 | Model-profile selection and override surfaces | Panel + API: catalogue presentation (one entry per kind with its three rigors and examples), launch and mid-run selection, inherited-vs-override provenance with clearing. |
| 4 | Strategy editability without first-use seals | Editing a used strategy stops being refused; creation and active-run change both retain resolved content + identity; no surface labels an editable definition `sealed`. |
| 5 | Strategy decision catalogue and validation | One shared decision inventory with active/reserved status and legal values; unknown/invalid rejected loudly (including no silent drop from listings); `strict`/`light` reproducible by complete canonical content; `legacy` fenced; existing surfaces show the same truthful status. |
| 6 | Strategy configurator panel | Build and edit a strategy configuration decision-by-decision over the slice-5 catalogue, same names/values/validation/status as the API. |

Order: 1→2→3 sequential; 4 independent; 5 after 4; 6 after 5. Each slice's
scope, files, tests, risks, and acceptance live in its just-in-time slice note;
the goal's completion list distributes across those slices' focused tests.

## Shared invariants (guarantee posture)

All **strict** — deviation is a bug; the pinned table names each enforcement
mechanism:

- **Precedence**: explicit per-act operator override > selected profile's rigor
  configuration > the act's existing act-specific assignment or derivation >
  family default. A per-act entry the operator supplied at creation through any
  channel — the launch payload's config, a project's standing `defaults.acts`,
  or a CLI `--config` file — is an explicit per-act operator override, the
  per-act winner picked by today's creation merge order (launch config over
  project defaults); DEFAULT_CONFIG's shipped act entries are not — they are
  the seeded default's content — so an implicitly bound default never restaffs
  an act the operator staffed at creation. The override layer is the only
  persisted home of an operator-supplied entry for an act on the configurable
  surface: for those acts the merged config's acts keep only DEFAULT_CONFIG's
  shipped entries, so clearing an override always
  exposes the profile-governed resolution — even for an act the selected
  rigor configuration does not staff — never a retained copy of the cleared
  value. An override composes at act granularity: the operator's entry is
  that act's whole policy, and a field it does not carry resolves by the
  entry's own form — relative rules and family defaults, never the
  profile's fields; the profile affects only acts not currently overridden.
  A creation-supplied explicit clear (JSON `null`/`""`/`{}`) for a surface
  act is the limiting case: an explicit override carrying the empty per-act
  policy, so the act resolves entirely by its derivations and family
  defaults — exactly where that cleared entry lands today — whatever profile
  is selected, until the operator clears the override itself.
  Act granularity is what keeps a partially filled creation row — the panel
  submits only the fields the operator set — resolving exactly as it does
  today, whatever profile is selected. Relative policies
  (`self`/`opposite`) still in force resolve from the effective originating
  act.
- **Authority ceiling**: a profile or override sets only the fields that act's
  resolution functionally honors — never moves a structurally fixed family,
  never replaces a structurally derived policy with a literal family, never
  sets a field the act derives from elsewhere; attempts are input errors, not
  accepted no-ops.
- **Bind once, retain resolved content**: every binding — explicit selection,
  implicit default at binding, every explicit change of active work, on both
  axes — retains the resolved content and its identity in run state; a mutable
  reference alone is never that record; earlier work is never revalidated
  against later source content.
- **Prospective only**: a change binds at the next act resolution or recorded
  transition; never an active call, never completed work.
- **Override provenance**: an override exists only where the operator
  explicitly set one; showing or re-saving inherited values creates none;
  origin is distinguishable and an override is clearable.
- **Effective-choice fidelity**: wherever a surface reports an act's effective
  agent/model/effort or its provenance, the report equals what act resolution
  produces from the same persisted state the report read; a report-to-call
  divergence arises only from a recorded intervening change by an authorized
  principal — the prospective-change model at work, not a violation.
- **Truthful presentation**: names, legal values, validation, active/reserved
  status, and resulting semantics — and the absence of `sealed` labels — are
  identical on panel and API.
- **Pre-feature compatibility**: runs created before this feature resolve acts
  exactly as today and never consult the new default.
- **Attribution** (strict for new calls): every call records resolved
  agent/model/effort plus the selection in force and any contributing override;
  recorded history is never rewritten.

## Pinned facts

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Configurable acts | the eight ACT_KEYS acts plus `brainstorming_counterpart`; per act, exactly the fields act resolution honors — full {agent, model, effort} for `skeletoner, drafter, implementer, fixer, reclassifier`; model/effort only for `review_codex, review_claude` (fixed family) and `brainstorming_counterpart` (derived family; honored today from creation config, while the override route still rejects the key and must gain it); family policy only for `consultation` (model/effort derived); a field an act's resolution does not honor is an input error for profiles and overrides alike, never an accepted no-op; no expansion of any act's fields | orchestrator/service.py:2361-2362; orchestrator/driver.py:6040-6071; orchestrator/tests/test_guarantee_calibration.py:204-222; orchestrator/driver.py:836-851,6242-6248; goal.md:18-20,62,185-186,202-203 | touch: profiles and the override channel configure exactly this honored surface |
| Structurally fixed / derived seats | `review_codex`→codex, `review_claude`→claude (agent rejected and ignored); delta review always fixer's family + that family's review profile; brainstorming counterpart always opposite of lead (a same-family pin is not honored and drops the pinned model; a pinned effort survives); consultation model always the consulted family's default, effort always the consulting caller's | orchestrator/service.py:2363,2401-2404,2419-2424; orchestrator/driver.py:6096-6109; orchestrator/driver.py:6111-6120; orchestrator/driver.py:6040-6071; orchestrator/driver.py:836-851,6242-6248 | do-not-touch |
| Per-act override channel | `acts.json` beside state via `POST /api/runs/<id>/acts`; holds only explicit entries; driver re-reads before every act resolution; per-act entries the operator supplies at creation — the launch payload's config `acts` (the panel form submits only operator-filled rows), a project's standing `defaults.acts`, a CLI `--config` file's `acts` — enter this same override layer at creation — a creation-supplied explicit clear (`null`/`""`/`{}`) for a surface act included, preserved as the explicit empty per-act policy rather than dropped by the mid-run route's clear vocabulary, which keeps meaning remove-the-override — and do not also remain in the state's merged config acts — which for surface acts keep only DEFAULT_CONFIG's shipped entries, so a cleared override cannot resurface from the config layer — merged in today's order (launch config over project defaults) so today's per-act winner keeps governing and provenance and clearing are uniform; DEFAULT_CONFIG's shipped act entries never enter it: they stay in config acts. Input-error strictness is the profile store's and the override route's contract, not the creation channels': creation keeps today's acceptance — a creation-supplied act key outside the Configurable-acts surface (a legacy `delta_review`, an unknown key) never refuses the launch and never enters the override layer; it stays in the merged config acts, non-operative exactly as today | orchestrator/driver.py:5948-5959; orchestrator/service.py:2380-2433,3762-3764; creation channels: bound launch orchestrator/service.py:1818-1820,1878-1881 (the panel's only path — it requires a project, orchestrator/static/panel.html:4461-4466; acts form 4436-4451,4485-4489), project defaults orchestrator/service.py:1828-1829, project-less API launch orchestrator/service.py:2008-2012, CLI orchestrator/driver.py:286-292,8573-8579; merge order orchestrator/driver.py:8460-8464 pinned by orchestrator/tests/test_run_init.py:568-583; override act-granularity goal.md:90-94; legacy-key tolerance orchestrator/driver.py:6111-6117 | touch: becomes the override layer above profiles; presence in this file = provenance; creation acts re-route here and out of merged config acts — the destination asserted by orchestrator/tests/test_run_init.py:568-583 moves with them, and so does the run summary's rounds-time review-model report (orchestrator/state.py:2510-2516 reads merged config acts alone and feeds the run-list model, orchestrator/service.py:1451, orchestrator/static/panel.html:2488-2513): it must resolve launch-set review entries from their new home or Effective-choice fidelity breaks for the whole rounds phase; the panel's effective-acts view (orchestrator/static/panel.html:3554-3563) merges the overlay over this same config-acts base and must make the matching move with slice 3's override surfaces: its base layer reports the profile-governed resolution, and a launch-set entry is not presented with the mid-run hot-edit marker (orchestrator/static/panel.html:3585) |
| Resolution seam | `_act_profile` is the single per-act resolution point the precedence extends | orchestrator/driver.py:5961-5988 | touch: extend here, not in parallel |
| Rigor set | exactly `low`,`medium`,`high`; incomplete profile rejected at create/edit; unknown name or rigor rejected at selection; no fallback | goal.md:48-52,74-76 | new contract |
| Examples | each example ≤ 5 words | goal.md:53-56 | new contract |
| Per-rigor act entry shape | the vocabulary `set_acts` accepts today ({agent, model, effort} object, or a family string where permitted), restricted per act to the Configurable-acts surface; today's silent acceptance of dead `consultation` model/effort does not carry into profiles or the override channel — such a field is an input error | orchestrator/service.py:2394-2426; goal.md:62 | new contract (reused shape, per-act field restriction) |
| Seeded default | profile `default`; unselected work binds `default`@`medium`; that configuration reproduces DEFAULT_CONFIG acts + model_defaults resolution exactly; because operator-supplied acts from every creation channel rank above it as overrides, a run created with per-act staffing or explicit clears — launch payload, project `defaults.acts`, or CLI `--config` — and no model-profile choice resolves exactly as today | orchestrator/driver.py:88-91,156-193; goal.md:78-84 | new contract |
| Model-profile binding events | binding at unit open and explicit change are ledger events `model_profile_bound` / `model_profile_changed`, retention carrying resolved content + identity | goal.md:81-84,120-126; event mechanism orchestrator/state.py:752 | new contract |
| Model-profile API routes | `GET/POST /api/model-profiles`; selection at creation in `POST /api/runs` payload key `model_profile` {name, rigor}; mid-run change `POST /api/runs/<id>/model-profile` | route surface orchestrator/service.py:3418-3475,3733-3767; goal.md:25-26 | new contract |
| Executor vocabulary | models `claude-fable-5/claude-opus-5/claude-sonnet-5`, `gpt-5.6-sol/-terra/-luna`; efforts `low|medium|high|xhigh|max`; no new identifiers, no stricter id validation than today's | orchestrator/static/panel.html:4349-4356; orchestrator/driver.py:77-84; goal.md:181-182 | do-not-touch |
| Active strategy decisions | `stages[0].loop` (`family_until_clean`), dials `p3_defer_max_risk`+`p3_reclassify_debt`, `doc_register` — each an operative configurator control; `compat` is not in this inventory — it is the legacy fence's marker (below), never an offered control | orchestrator/interpreter.py:29,43-56,85-94 | do-not-touch: consumers unchanged |
| Reserved strategy decisions | `fuser_discard`, `final_open_pass` — recognized content, no runtime consumer; round-trip losslessly; marked non-operative everywhere shown | orchestrator/interpreter.py:26-29; orchestrator/profiles.py:225-226,246-247 (their only producers) | touch: status marking only, no machinery |
| Presentation to correct | `profileDials` renders the reserved fields as governing dials in the new-run selector and repoint dialog | orchestrator/static/panel.html:4170-4178 | touch: fix in place |
| Seal machinery to retire | sealed-content save refusal; seal-on-first-reference; required `sealed` flag; `· sealed` label and API `sealed` field | orchestrator/profiles.py:74-75,133-142,168-189; orchestrator/static/panel.html:4135; orchestrator/service.py:2500 | touch: retire blocking + presentation; run-side snapshot verification stays (orchestrator/driver.py:395) |
| Strategy binding retention | creation embeds content + ref (`config.profile`/`profile_ref`, internally verified); the active-run change today stores a ref-only overlay and must instead retain resolved content + identity and record transition event `profile_changed` | orchestrator/service.py:2049-2057; orchestrator/interpreter.py:32-41,180-203; orchestrator/service.py:2532-2541 vs 2556-2562 | touch: extend the swap path |
| No divergence revalidation | `verify_reference` (source-vs-ref divergence failure) has no production caller and must gain none; a legal source edit never fails earlier work | orchestrator/profiles.py:192-203 | do-not-touch (keep unused / retire) |
| Legacy fence | `legacy` stays a selectable compatibility choice; never a component of a new configuration — composing it is rejected. Its defining marker `compat` has runtime consumers yet is not an active decision — it is the fence itself: no surface offers it as an operative control, and declaring `compat` in any new or edited configuration other than the `legacy` artifact itself is rejected as composing legacy; the `legacy` seed write and edits saved under its own name remain legal and retain `compat` losslessly — a `legacy` save that omits or alters the marker is rejected loudly, so no legal edit path silently unfences `legacy` | orchestrator/profiles.py:257-274,278-286; orchestrator/interpreter.py:97-105,135-149; goal.md:149-150,163-165 | new enforcement |
| Artifact seals & rotation | run-artifact sealing, family rotation, deterministic review-derived seal unchanged | goal.md:177-178 | do-not-touch |
| Attribution records | drafts and rounds already record resolved family/model/effort (resolved before recording); extend with selection + contributing override; existing event shapes never rewritten | orchestrator/driver.py:2141-2143; orchestrator/state.py:729-738,877-907 | touch: extend |

## Question battery

| question | answer | evidence |
|---|---|---|
| victim | Operators and calling products staff every run seat-by-seat and hand-write strategy JSON; auditors read run history. Without this: repetitive error-prone setup; a used strategy cannot legally be edited (real refusal in the store), forcing clones; the panel asserts reserved decisions govern and labels editable definitions sealed — false confidence and avoided legal edits. Exposure: every new run; moderate, operational, reversible before new calls run. Independent authority: the operator mandate and the brainstorming closure's affected-parties record. | orchestrator/static/panel.html:4436-4451; orchestrator/profiles.py:133-142; orchestrator/static/panel.html:4170-4178; orchestrator/interpreter.py:26-29; orchestrator/static/panel.html:4135; goal.md:13-33; implementation/brainstorming/model-profiles-and-strategy-configurator/chat-bs-73c42856b088db46eb06f5de52ed63e3.md:302-308 |
| machinery | New: model-profile catalogue + seeded default; unit-open binding with retained resolved content; per-call selection/override attribution; strategy decision catalogue with active/reserved status; seal retirement with retained-content bindings on the active-run change path. Each serves an authorised outcome: reusable named choices on panel+API; editability without history damage; truthful configurator. It must exist because today a named reusable staffing choice cannot be expressed at all — only raw config acts at launch and per-run hot edits — and nothing retains what governed once sources become editable (the runtime swap stores a ref only). | goal.md:13-27,115-141,143-170; orchestrator/driver.py:156-193,5948-5959; orchestrator/service.py:2556-2562 |
| consumers | Driver act resolution consumes profile output at the single seam `_act_profile` (callers include the brainstorming/review/delta profiles); the panel consumes the catalogue and act form; state summary and panel consume attribution; calling products consume the HTTP API routes; run creation consumes strategy refs/snapshots and the driver verifies them at load. | orchestrator/driver.py:5961-5988,6040-6120,395; orchestrator/static/panel.html:4120-4126,4343-4356; orchestrator/state.py:2354-2415; orchestrator/service.py:3418-3475,3733-3767,2049-2057 |
| cheaper_alternative | (a) Documentation of hand-config: gives no binding, retention, or provenance and leaves the sealed-edit refusal and false labels in place — insufficient. (b) Reusing the strategy-profile store for model profiles: violates the no-coupling boundary and needs different validation — rejected; but its patterns (semantic-hash identity, snapshot-at-binding, hot-read overlay, the set_acts vocabulary) are reused, which is the cheapest sufficient path. (c) Doing nothing: the mandate's named harms persist. Chosen: extend existing seams; new machinery only where nothing can express the outcome. | orchestrator/profiles.py:133-142; orchestrator/static/panel.html:4135,4170-4178; goal.md:175-176; orchestrator/profiles.py:53-58; orchestrator/service.py:2049-2057,2394-2426; orchestrator/driver.py:5948-5959 |
| cost | Build: six bounded slices, each aiming under ~500 reviewable changed lines. Migration: none — pre-feature runs stay bit-identical (the profile-less equivalence gate is precedent) and seeds are never overwritten. Operation: no new processes. Maintenance: the decision catalogue must flip a status when a later phase gives a reserved decision a consumer — accepted, cheaper than implementing dormant machinery, which the goal forbids. Omission cost: the victim harms recur every run. Reversibility: additive surfaces and restorable seal checks — high. | orchestrator/interpreter.py:8-9; orchestrator/profiles.py:278-286; goal.md:158-160,191-227 |
| threat_model | No untrusted input is handled. The operator and calling products are trusted principals already able to edit run config, acts.json, and profiles through the same access-gated service that runs workers; validation here exists for input-error honesty (reject, never fall back), not to defend a trust boundary — and the milestone creates no new one. | orchestrator/service.py:3736 (require_run_access), 2380-2433; goal.md:74-76,167-170 |
| enforceability | Precedence + authority ceiling → the single resolution seam `_act_profile` extended (an override entry is the whole per-act policy — the overlay's existing entry-granular replacement), plus structural driver enforcement that holds even against bad data (fixed review families, derived delta review, opposite counterpart, derived consultation model/effort) and input rejection in the set_acts pattern. Override provenance/clearing → creation acts single-homed in the override layer (for surface acts, merged config acts keep only shipped entries), so presence is provenance — a creation-supplied explicit clear included, present as the empty per-act policy — and a cleared key falls through to profile-governed resolution. Completeness/unknown rejection → store validation in the `profiles._validate` pattern with ApiError 400. Bind-once retention → the existing embed-snapshot + internal-hash-verify mechanism generalized, with `st.append_event` ledger records. Prospective-only → the overlay re-read before every act resolution plus event-recorded transitions. Attribution → record_draft/record_round fields already carrying values resolved in `_call`. Effective-choice fidelity → the effective view is served by the same resolution logic the driver's seam uses (the `_act_profile` single-seam pin extended to its service-side reader), with contract tests comparing a reported effective choice against the next call's recorded attribution under unchanged inputs. Panel/API truth parity → one API-served catalogue consumed by the panel (precedent: the panel already loads strategy profiles from `/api/profiles`, not a local copy). Default-equivalence → the `test_profile_equivalence` gate precedent. No asserted guarantee lacks a pinned mechanism. | orchestrator/driver.py:5961-5988,6096-6109,6111-6120,6057-6067,836-851; orchestrator/service.py:2394-2426; orchestrator/profiles.py:61-88; orchestrator/service.py:2049-2057; orchestrator/driver.py:395; orchestrator/state.py:752,729-738,877-907; orchestrator/driver.py:2141-2143,5948-5952; orchestrator/static/panel.html:4138-4148; orchestrator/interpreter.py:8-9 |

## Reuse posture

Affected party: operators, calling products, and history auditors (mandate,
goal.md:13-33); realistic harm: misconfigured staffing, blocked legal edits,
false UI claims — moderate, reversible before new calls, authority-established.
Checked and reused: the `_act_profile` resolution seam (orchestrator/driver.py:5961-5988),
the acts.json overlay and its `set_acts` vocabulary (orchestrator/service.py:2380-2433),
snapshot-at-binding + semantic-hash identity (orchestrator/service.py:2049-2057;
orchestrator/profiles.py:53-58), the `append_event` ledger (orchestrator/state.py:752),
existing API routing and the panel's served-catalogue pattern
(orchestrator/static/panel.html:4138-4148), and the seed store
(orchestrator/profiles.py:210-286). Cheapest sufficient option: extend those
seams. Machinery still justified, with consumers: the model-profile store and
catalogue (panel, API, driver), unit-open binding retention (attribution, panel,
audit), and the strategy decision catalogue (configurator panel + API + existing
selectors). Lifecycle cost is bounded to six slices and one status flip per
later-activated reserved decision; omission leaves the mandated harms in place;
every change is reversible or additive.
