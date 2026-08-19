# Milestone skeleton — Staffing Router: one authority for agent, model, and effort

Mandate: the frozen launch snapshot `implementation/milestones/staffing-router/goal.md`.
This is a thin planning contract; slice notes pin each bounded surface just
before it is built. Two registers: lay intent first, then the small hard table.

## Register 1 — Intent (lay language)

### Goal restatement

Every call the orchestrator makes to an agent CLI — from a milestone, from a
Brainstorming discussion, from a standalone task, from a calling product, or
from the operator's git alignment of a work area — gets its **agent, model, and
effort** from one place: a **staffing router** inside the orchestrator process.
The owner of a piece of work opens a **session** that names a **staffing
document**, a **rigor**, optionally a default **material**, and the families
present on this machine; every executor working under that owner asks the
session at each call, passing the **role** (the process step), the **seat
index**, the **round**, and optionally a material and a brief. The answer is
exactly `agent`, `model`, `effort`. Nothing else decides staffing.

Today seven mechanisms decide (model profile at each dispatch; profile-backed
Brainstorming seats; standalone tasks from the first configured family; static
Brainstorming pins at admission; review family rotation; structurally derived
review/consultation/classifier families; git-sync from the first family). Only the
profile-backed paths let the operator choose deliberately. This milestone collapses all of them into one
rule with one document shape: numbered family slots with model and effort
ladders, a per-rigor tuning table of ranks, a per-role seat assignment, an
owner-defined material vocabulary with overrides, and typed rules (only
`step_up`). Everything that selects is a number; rigor picks only the tuning
table.

Resolution never fails for an incomplete input: an unbound family collapses to
the first available slot, an out-of-range rank saturates, an unknown material
or a missing seat falls back, an unreadable session or document resolves as the
default document with the available families and the per-call marker says so.
Only two conditions are surfaced: no family at all, and a `distinct_families`
role that the available families cannot honour (checked at session creation
and again before each dispatch it affects). Sessions and documents are edited
live; a change reaches the next call and never rewrites a call already made.

Choices are made where they belong: in a milestone the planner proposes a
material per slice from the document's material catalogue, the skeleton table
shows it, and the operator may override it before the task is ordered; for
standalone work the panel or the calling product opens the session with the
operator's document, rigor, and material — never seats. The `worker`
TaskExecutor is renamed `agent_call`; old records still read.

### Ownership

Owned here: the staffing document (schema, loud save-time validation, store,
seeded `default`, one-time conversion of today's profiles), sessions and the
resolver with its rules and fallbacks, the cutover of every consumer (milestone
driver, Brainstorming seats both attached and standalone, standalone task host,
git-sync), the product-neutral session/document/resolve API and the panel
surfaces, the planner material channel, the rename, compatibility derivation
for resumable runs, and focused tests.

Not owned here: any daemon, lifecycle, recovery, liveness, ledger, snapshot
validation, or identity scheme for staffing; cost ceilings, budgets, or a
scheduler; a new permission system; an expression language or rule engine;
milestone review law (which family reviews which round, convergence, sealing);
Agent99 adaptation; a domain taxonomy for roles or an enum of materials in code.

### Boundary and non-goals

- The router is a table plus a handful of typed rules in the orchestrator's own
  process, with its own records and routes. It selects staffing only.
- Roles are the closed process-step vocabulary; materials are the document
  owner's words. No LLM selects staffing at dispatch inside a milestone: the
  planner proposes a material, the operator disposes.
- Bookkeeping (session record, per-call marker, `resolved_staffing` on orders,
  projections) is best-effort: a lost or stale entry changes no acceptance,
  seal, or result. Whenever a design or review is about to add machinery so
  that a staffing value outlives every path, the answer is "best-effort" and
  stop.
- Milestone law about *which* seat is used (review rotation and caps, sealing,
  delta review by the fixer's family) stays in its consumers as seat choice
  among the seats the document assigns to the role; the router only staffs the
  seat asked for and honours `distinct_families` when a role declares it.
  Today's structural derivations — opposite-family consultation, the failure
  classifier's and the counterpart's opposite family, `self` — are defaults,
  not laws the router or a document must be able to serve: conversion writes
  each once as an explicit assignment (`consult 1`, `brainstorm 2`, and
  `classify 1`, which the failure classifier shares with the reclassifier),
  the document owner may reassign it (A3), a seat the document does not
  assign collapses to that role's index 1, and the marker shows who ran. A
  document is valid when complete (Register 2, Document shape); no family
  relationship beyond a declared `distinct_families` is
  validated or surfaced, a `distinct_families` role with one assigned seat is
  trivially honoured (as a single-family `families_order` reviews with one
  family today), and the two surfaced conditions stay the only ones.
- The four additional roots granted to this run are read-only evidence.

### Guarantee posture

- **Strict — save-time validation:** an invalid document or session write is
  refused loudly before any byte changes; a stored document is always complete
  for resolution.
- **Strict — resolution answers:** every request the resolver admits — one
  naming a session and a role — returns a staffing except the two surfaced
  conditions; collapse and saturation replace failure. The resolve route's
  `404 unknown_staffing_session` and `400 invalid_staffing_request` are
  admission errors before resolution, not a third staffing condition.
- **Strict — live change:** each call reads the current session and document;
  the last completed write governs the next call; a dispatched call is not
  altered. No snapshot, freeze, or history has authority. A session override
  outranks the document for the role it names — the goal's own precedence; it
  is explicit configuration on the session record, written and cleared by a
  completed session save through the session store, the slice 5 route, or the
  slice 8 panel, read live at each call and never a copy that ages.
- **Best-effort — inputs and bookkeeping:** session record and document are
  inputs; an unreadable input resolves as the default document (the store's
  `default`, else the in-code seed — the floor itself never fails) with the
  available families and the marker records the fallback; markers,
  projections, `resolved_staffing`, and the planner's material proposal are
  bookkeeping.
- **Strict — resume continuity (run amendment A2):** a run that resumes
  without a staffing session gets one that **references** the document named
  by its selected profile — converted profiles keep their names — at its
  selected rigor, with the families derived for that run today, or the
  `default` document when that name has none. Nothing else is derived: the
  `acts.json` literals are not carried into the session, the document's own
  numbers apply from the next call, and the operator edits the session if he
  wants something else; what ran shows in the marker at the bookkeeping level
  declared above — accurate when written, with nothing here promising one
  survives. Resume is never failed or blocked for compatibility; no document
  is written or mutated at resume; the derivation reads `model_profile.json`
  for the name and rigor and no other file, and neither profile files nor act
  sidecars are edited or deleted.
  What this entry promises is the reference, not next-call parity: a role
  whose act overlay differed from the document staffs from the document until
  the operator edits the session, which is one visible, per-call reversible
  difference and needs no machinery to carry an old literal. Anything admitted
  before the cutover keeps what it was admitted with; stored `worker` reads as
  `agent_call`.

### Skeleton decisions (the goal leaves these to the skeleton)

- **Profiles convert once; no adapter.** The document store converts each
  existing profile into a document of the same name, missing-only, at
  catalogue initialization (which runs at each service and driver start, as
  `model_profiles.ensure_default` does, so a profile created later is
  converted at the next start). A stored profile always sources the document
  of its own name, `default` included; the in-code seed supplies `default`
  only where no `default` profile exists, so that an unconfigured run's
  `default@medium` staffs every seat as today from the conversion's reference
  (below): exactly, for every seat whose family today is fixed or turns on
  another document seat (`consult 1` on `fix 1`, `brainstorm 2` on
  `brainstorm 1`); one of today's answers, for the failure classifier, whose
  family today turns on the call that failed and which shares the
  reclassifier's `classify 1`, and for `consult` only where a profile's
  `plan` and `fix` families differ (a drift-alarm test pins that conversion
  against the live defaults, seat by seat from that reference).
  The distinction is not
  theoretical: this machine's stored `default` differs from the in-code seed
  in all three rigors — `implementer` and `skeletoner` at `medium` are
  `codex`/`gpt-5.6-sol`/`max` there against the seed's
  `claude`/`claude-fable-5`/`max` — and four runs hold `default@medium` in
  their selection sidecar, so seeding over the stored profile would flip the
  agent and the model under those four runs on every implement call — a
  conversion defect, not a compatibility exception. Profile files are read, never edited or
  deleted. Structural derivations (`opposite`, `self`, "caller's effort") become
  explicit numbers in the converted document. Conversion is a normalization
  into the document's shape, not a lossless copy: assignment is
  rigor-independent by the goal, so a profile policy that names no single
  family for the document to hold — a family that differs by rigor, or
  `self`/`opposite` relative to a call's origin — converts to one assignment
  from the profile's `medium` configuration (the default rigor and the drift
  alarm's pin), applied to the reference today's resolution uses. Where that
  reference is another document seat, the policy is applied to that converted
  seat, never to the first-family fallback: `brainstorm 2` takes the family
  opposite `brainstorm 1`'s (the profile's `implement` family at `medium`),
  as today's counterpart derivation does; `consult 1` applies the profile's
  `consultation` policy to the converted `fix 1` family, as today's
  consultant derives from the fixer's resolved family. Where a profile's
  `plan` family differs from its `fix` family (the in-code seed), the
  skeleton fix's consultation, referenced today on the skeletoner, takes the
  fixer's answer: one of today's two, never both. `classify 1` carries the
  profile's `reclassifier` policy — fixed `codex` in the in-code seed and in
  both stored profiles, so the debt-deferral rater converts exactly; the
  failure classifier, which has no profile act today and takes the family
  opposite the call that failed, shares that seat and so reproduces one of
  its two answers. Every other `self`/`opposite` policy, whose origin today
  is the family that raised the finding or none, resolves through today's
  act resolution with no origin: `self` to the first family, `opposite` to
  the second. Each rigor's tuning reproduces that rigor's model and effort
  where the profile staffs that family; the marker shows what ran and the
  operator edits the document to change it. Conversion never fails or skips
  a valid profile, and the operator rewrites none by hand. Each converted
  family slot
  carries its family's whole vocabulary on its ladders — every model and
  effort of that family, not only the values a profile happened to use — so
  amendment A1's order is written once and `step_up` has rungs above today's
  choice to climb into; the ranks are then chosen to reproduce today's
  staffing. Ladders run
  weakest→strongest by **capability as the operator judges it**, never by
  price even where the two coincide, because `step_up` exists to add
  intelligence when work is stuck — more effort, then a more capable model —
  and never to change cost. No source declares that order today: the panel's
  lists are display order and profiles are flat, so the conversion writes the
  operator's stated order (run amendment A1: `gpt-5.6-luna` <
  `gpt-5.6-terra` < `gpt-5.6-sol`; `claude-sonnet-5` < `claude-opus-5` <
  `claude-fable-5`), which is operator data in the document, reordered by a
  document save and by nobody else, not a code constant. A rung the operator
  would place differently moves `step_up` and saturation only, never a derived
  call, and the drift alarm pins today's effective staffing rather than rung
  order. After the driver cutover the
  profile catalogue and the `model_profile.json`/`acts.json` sidecars are no
  longer dispatch inputs; `model_profile.json` supplies only the name and
  rigor a resuming run's session references, and `acts.json` decides no
  staffing — the run summary and run detail still read it so the acts dialog
  can show it until slice 8 retires that surface, and no slice edits or
  deletes it.
- **Roles map onto today's acts** for conversion and cutover: `plan` ←
  skeletoner, `draft` ← drafter, `implement` ← implementer, `fix` ← fixer,
  `classify` ← reclassifier and the failure classifier, `review` seats ←
  review_codex/review_claude, `brainstorm 1/2/3` ← Initial Position / Contrary
  Position (brainstorming_counterpart) / Dante, `consult` ← consultation,
  `sync` ← git alignment.
- **Seat and round conventions** are consumer facts passed in: `review i` is
  the i-th review seat of the current cycle with `round` its 1-based round count
  in that cycle; `brainstorm i` is roster position i with the discussion round;
  every other role uses index 1 and round 1 unless the consumer counts repeats.
- **One module, one store.** `orchestrator/staffing.py` owns documents,
  sessions, and resolution; records live in the service home. A milestone run binds exactly one
  session id in its run state at launch (or at first resume without one); the
  driver, the Brainstorming lifecycle child, and the standalone host locate it
  through the home the service already passes. Standalone orders, Brainstorming
  creation, and git-sync carry the owner's session id as inherited context.
- **Standalone `agent_call` orders name their role** through the executor's
  configuration schema (default `implement`); milestone orders set it from the
  task kind. `brief` is passed best-effort and read by no rule.
- **Transitional posture:** consumers cut over one slice at a time; a panel
  control that still writes a retired input is inert for already cut-over
  consumers until the panel slice replaces it. Concretely for the profile
  editor between slices 4 and 8: once a profile's document exists the file's
  contents decide no run's staffing, since a resume reads only the selected
  name and rigor — changing *which* profile a run selects still names the
  document its first resume references, and a profile created later gets its
  document at the next service or driver start; after slice 8 the editor is
  gone and the document is the only channel. Slice notes name what is
  transitional. This repository is the implementation source; the run driving
  this milestone executes from a separate checkout.

### Planning material disposition

- **Adopt:** the frozen goal, including its mandatory resolution paragraph and
  boundaries; the live brainstorming copy is byte-identical to the snapshot.
- **Revise:** conversion versus adapter is settled as one-time conversion;
  `resolved_staffing` remains as best-effort bookkeeping rather than being
  dropped (cheapest); the illustration's numbers are illustrative — the seeded
  document is pinned by behaviour (today's effective staffing), not by those
  literals.
- **Reject:** any later drift of the live goal copy; `_drafts` holds no material
  for this goal.

### Reuse Posture

Affected party: operators and calling products whose standalone tasks,
Brainstorming sessions, and git alignments cannot be staffed deliberately, and
whose milestone staffing is spread over seven rules; realistic harm is work
running at an unintended family, model, or effort (visible cost and quality),
reversible per call but repeated; the mandate is the independent authority.
Checked and reused: the model-profile store pattern (validated load/save/list,
missing-only seed, atomic replace), the one dispatch resolver hook and marker
retarget on every physical call, the pre-dispatch busy marker and standalone
task marker, accounting from the marker, the Brainstorming per-dispatch
`current_resolver` seam expecting `{agent, model, effort}`, the executor
configuration schema and panel schema-derived controls, the slice producer
channel and its best-effort override write, project access, and the existing
test suite. Cheapest sufficient option: one router module (documents, sessions,
resolver) replacing the layered act resolver and the three ad-hoc first-family
paths, plus routes, a material key on the slice plan, and the rename; cheaper
options (extending profiles to standalone paths, or an adapter over profiles)
keep two vocabularies and structural derivations and cannot give products a
session. Justified machinery and its consumers: the router (driver,
Brainstorming lifecycle, standalone host, git-sync, service/panel, future
products); no ledger, snapshot, identity, notification, or scheduler is
justified. Lifecycle cost: ten bounded slices, one deterministic conversion,
one file read per call as today, one module to maintain instead of four paths;
omission keeps the misstaffing and blocks the product-neutral API; profile
files stay untouched and old records readable, so the change is reversible.

### Planned slices

| id | slice | note producer | implementation producer | intent |
|---:|---|---|---|---|
| 1 | Rename `worker` to `agent_call` | worker | worker | The public TaskExecutor id, catalogue entry, order and producer values, panel labels, and docs say `agent_call`; stored records and slice plans that say `worker` still read as `agent_call`. |
| 2 | Staffing document store | worker | worker | The document schema (families with ladders, per-rigor tuning ranks, per-role seat assignment, materials with usage phrases, per-material overrides, typed rules), loud validation on save, list/load/save, the seeded `default` reproducing today's `default@medium`, and one-time missing-only conversion of existing profiles. |
| 3 | Sessions and resolution | worker | worker | Session records (work area, available families, document reference, rigor, default material, overrides in the document's shape), open/read/edit, and the resolver: material precedence, collapse, saturation, `step_up`, default-document fallback with marker note, and the two surfaced conditions; the resolution-matrix tests. |
| 4 | Milestone driver cutover and run binding | brainstorming | worker | Every driver-made call (plan, draft, implement, fix, classify, consult, review seats and rounds, delta review) resolves through the run's session with the `distinct_families` pre-dispatch check; launch opens the run's session from `staffing` (the panel's launch selector lists documents) and resume derives one for runs without; profile/acts sidecars and the loud dispatch failure retire as dispatch inputs; the marker records fallbacks. |
| 5 | Staffing API | worker | worker | Product-neutral routes to list/save documents, create/read/edit a session, and resolve a request under existing caller identity and project access; the run summary exposes the run's session. |
| 6 | Brainstorming cutover | worker | worker | Milestone-attached seats resolve `brainstorm 1..3` (and `classify`) through the run's session per dispatch; standalone sessions resolve through the caller's session; roster rotation and static pins yield to the router for new sessions while pre-cutover pins keep. |
| 7 | Standalone tasks and work-area alignment | worker | worker | `agent_call` orders carry a role and an owner session; the direct host resolves each call through it; git-sync resolves `sync` through the caller's session; `resolved_staffing` becomes best-effort bookkeeping. |
| 8 | Panel: documents, sessions, standalone choices | worker | worker | Document editor, per-run session controls replacing the model-profile selector and acts dialog, standalone ordering exposing document, rigor, and material (never seats), Brainstorming and git-sync carrying the session; the model-profile and acts routes retire. |
| 9 | Planner material channel | worker | worker | Planning prompts carry the session document's material catalogue; the planner proposes a `material` per slice; the skeleton table shows it; the operator overrides it prospectively through the slice channel; both production tasks of the slice pass it. |
| 10 | Compatibility and conformance | worker | worker | End to end: `step_up` fires on the configured round with the escalated marker; a document or rigor change mid-run applies to the next call; unreadable inputs fall back visibly and never fail a dispatch; surfaced conditions at creation and before dispatch; resumable runs derive; pre-cutover records keep; `worker` records read; no other staffing path remains. |

Order: 1 → 2 → 3 → 4 → 5; 6 and 7 follow 4 and may run in either order; 8
follows 5–7; 9 follows 8; 10 follows all. Each slice carries focused tests for
its own contract; closure runs the repository's full suite. Slice 4 may exceed
the ~500-line aim; its note records why.

## Register 2 — Pinned facts (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Role vocabulary | Exactly `plan`, `draft`, `implement`, `fix`, `classify`, `review`, `brainstorm`, `consult`, `sync`; closed in code; each role may declare `distinct_families` in the document's `roles`; the seeded default sets it `true` only for `review`. | `goal.md:85-101`; act sources `orchestrator/model_profiles.py:53-64` | touch the router and every consumer's role choice; do-not-add domain words, per-role code enums beyond this list, or a router-side derivation of families |
| Request and response | Request `session`, `role`, `index` (default 1), `round` (default 1), optional `material`, optional `brief`; response exactly `agent`, `model`, `effort`. In-process the Brainstorming seat seam already consumes that dict shape. | `goal.md:77-83`; `orchestrator/brainstorming_execution.py:56-81` | touch the resolver and consumers; do-not-return anything else, keep router history, or read `brief` in this milestone |
| Document shape | Exactly `name`, `families` (numbered slots: `name`, `models` ladder weakest→strongest, `efforts` ladder in the family's vocabulary), `roles`, `materials` (name → `examples`), `tuning` (rigor → slot → role → `[model_rank, effort_rank]`, 1-based), `assignment` (role → index → slot), `overrides` (material → `assignment` and rarely `tuning`), `rules` (typed entries; only `step_up` with `role`, `min_round`). Rigors stay exactly `low`, `medium`, `high`. Validated loudly on save; complete means every role has an assignment for index 1 and every rigor × slot × role has a tuning pair, so a stored document always resolves. Names case-insensitively unique. | `goal.md:103-127`; `orchestrator/model_profiles.py:49,204-255,314-346` | touch the new store; do-not-add an expression language, a rule engine, a second rule type, or a document version/snapshot |
| Session record | `work_area`, `families` (names available here, supplied by the owner), `document` (name reference, never a copy), `rigor`, optional default `material`, optional `overrides` in the document's own shape; editable live: `document`, `rigor`, `material`, `overrides`; no snapshot or freeze. Session overrides apply above material overrides above base. | `goal.md:55-75` | touch the session store and every owner; do-not-copy the document, freeze at order time, or add session lifecycle/recovery |
| Resolution order | Material named in the request, else the session default, else base assignment gives the slot; slot family not in the session's families collapses to the lowest-numbered slot whose family is available; a missing seat resolves as that role's index 1; unknown material as absent; `tuning[rigor][slot][role]` gives ranks; a rank beyond a ladder saturates to that family's top; `step_up` for its role at `round >= min_round`: effort rank + 1, else next model at its first effort, saturating at the top; the marker records what ran. Never fails for these. | `goal.md:178-190,121-127` | touch the resolver only; do-not-fail, freeze, or gate on any of these |
| Mandatory fallback | If the session or the document cannot be read at dispatch (absent or unreadable alike), resolve as the default document with the available families: an unreadable document keeps the session's rigor and families; an unreadable session resolves as `default@medium` with the consumer's configured families; an unreadable `default` resolves from the in-code seed, so the floor never fails. The marker gains `staffing_fallback: "default_document"`; the dispatch is never failed, blocked, or retried on that account. Today's loud dispatch failure retires for dispatch; save-time validation stays loud. | `goal.md:191-197`; retiring `orchestrator/driver.py:7996-8026` (`_fail_model_profile_resolution`, `_act_profile`) | touch the resolver seam and markers; do-not-reintroduce a failure, freeze, or validation gate for unreadable inputs |
| Surfaced conditions | Only two, as the error tokens `staffing_unavailable` (no family available; HTTP 503) and `distinct_families_unsatisfiable` (HTTP 409 on resolve; reported as a live projection on session create/read; refused at each affected dispatch). Milestone law decides what a consumer does with them. The resolve route's 404 and 400 reject a request before resolution and are not surfaced conditions. | `goal.md:199-204` | touch the resolver, API, and consumers' handling; do-not-add a third surfaced condition |
| Live change | Every dispatch reads the current session and document (as `_read_current_profile_layers` reads profiles today); a change applies to the next call of every session referencing the document and never rewrites a call already made. | `goal.md:206-211`; `orchestrator/driver.py:461-470`; `orchestrator/runners.py:2940-2962` (`resolve_dispatch`/`on_dispatch`) | touch the resolver read; do-not-cache across calls or add generations/acknowledgements |
| Marker is the record | The pre-dispatch busy marker (`family`, `model`, `effort`, retargeted on each physical call), the standalone task marker, Brainstorming turn records, and the git-sync outcome record what actually ran; accounting prices from them; `resolved_staffing` on orders is best-effort bookkeeping, never dispatch input. | `orchestrator/driver.py:3052-3110`; `orchestrator/task_api.py:143-166,298-307`; `orchestrator/gitsync.py:212-221`; `orchestrator/tasks.py:600-620`; `goal.md:206-211,250-258` | touch marker fields additively; do-not-add a staffing ledger, event stream, or projection guarantee |
| Consumers cut over | Driver: `_act_profile`/`_dispatch_for_act`/`_structural_dispatch`/`_skeletoner_profile`/`_review_profile`/`_delta_review_profile`/`_brainstorming_profiles`/`_classify_failure`/reclassifier resolver/`_consultation_command` and `current_model_call.consultation_command`; Brainstorming: `_runtime_and_roster`, `resolve_static_participants`, the per-dispatch `current_resolver`, `brainstorming_tasks.resolve_staffing`; standalone: `task_api.worker_staffing`/`_dispatch`/`_run_worker`; service: git-sync family choice, direct task admission, launch `model_profile`. All resolve through one module, `orchestrator/staffing.py` (documents, sessions, resolver). After slice 10 none of these reads profiles, `families_order[0]`, or defaults to staff a call. | `orchestrator/driver.py:8008-8123,8217-8241,8152-8192,3712-3737,10034-10066,1344-1377`; `orchestrator/current_model_call.py:15-65`; `orchestrator/brainstorming_lifecycle.py:497-746,747-793,2528-2549`; `orchestrator/brainstorming_tasks.py:107-132`; `orchestrator/task_api.py:94-128,169-171,289-317`; `orchestrator/service.py:3468-3491,4011-4016,2015-2033` | touch each seam in its slice; do-not-leave a parallel staffing channel |
| Review law unchanged | Review rotation, per-family round caps, cycle restarts, the seal predicate, and delta review by the fixer's family stay milestone law, now keyed by each review seat's resolved family: the cycle iterates the review seats the session's document assigns, in index order (the router module exposes, as document reads over a session and never as part of the resolve response, a role's assigned seat indices AND the family each of those seats runs on — the second so rotation and the seal predicate can describe the cycle without dispatching, since a declared `distinct_families` the session cannot honour refuses a dispatch and not a read), and sealing requires one clean same-byte review per assigned review seat's family; `distinct_families` on `review` is checked before each review dispatch. Adding a family slot changes no assignment. | `orchestrator/state.py:887-892`; `orchestrator/driver.py:10296-10329,9638-9645`; `goal.md:238-240,175-176` | touch only the seat→family source; do-not-move convergence or sealing into the router |
| Rename | Catalogue id `agent_call` (name "Agent call"), default producer `agent_call`, order `task_executor` `agent_call`; new API input accepts only `agent_call`; stored records, slice plans, and task orders saying `worker` read as `agent_call`. | `goal.md:227-231`; `orchestrator/tasks.py:41-56,86-88,292-303`; `orchestrator/driver.py:2782-2794`; `orchestrator/task_api.py:281` | touch catalogue, validators, driver order, host, panel, prompts, docs; do-not-rewrite stored records |
| Standalone role and session | `agent_call` `configuration_schema` gains `role` (`type: choice`, the nine roles, default `implement`), superseding the tasks-2 pin that the Worker schema is empty; milestone orders set it from the task kind; Brainstorming uses `brainstorm`, git-sync `sync`. Orders, Brainstorming creation, and git-sync carry the owner's `staffing_session` as inherited context; the direct host and git-sync resolve each call through it. | `orchestrator/tasks.py:41-56`; `orchestrator/task_api.py:94-128,289-317`; `orchestrator/service.py:3468-3491`; `goal.md:72-75,222-226` | touch the catalogue schema, order bodies, host, and sync; do-not-expose seats or add a second staffing field |
| Public HTTP surface | New: `GET /api/staffing/documents`, `POST /api/staffing/documents` (create or wholly replace; 400 `invalid_staffing_document`; admin like `/api/model-profiles` today), `POST /api/staffing/sessions`, `GET /api/staffing/sessions/<id>`, `POST /api/staffing/sessions/<id>` (edit selection), `POST /api/staffing/sessions/<id>/resolve` (`{role, index?, round?, material?, brief?}` → `{agent, model, effort}`; 404 `unknown_staffing_session`, 400 `invalid_staffing_request`), `POST /api/runs/<id>/slices/<slice-id>/material` (`{material}` or null; prospective; 409 `task_update_busy`). Changed bodies: `POST /api/runs` takes `staffing: {document, rigor, material?}` instead of `model_profile`; `POST /api/tasks`, `POST /api/brainstorming/sessions`, `POST /api/projects/<slug>/git-sync` take optional `staffing_session` (absent = default document at `medium` with the configured families, marker-visible). Retired in slice 8: `GET/POST /api/model-profiles`, `GET/POST /api/runs/<id>/model-profile`, `POST/PATCH /api/runs/<id>/acts`. Access reuses caller identity and project access. | this skeleton (slices 4, 5, 7, 8, 9); `orchestrator/service.py:4290-4294,4450-4456,4606-4609,4665-4676,2015-2033,3468-3491`; `goal.md:244-249` | touch the service router and panel; do-not-add a permission system or per-executor route families |
| Planner material channel | Slice plan gains optional `material` (a string; unknown names collapse at resolution); the planning prompt block lists the session document's materials with usage phrases beside the TaskExecutor catalogue; the skeleton table shows the material; the write is prospective and best-effort like producer overrides; the milestone passes it in the router request of both `draft_slice_note` and `implement` tasks of that slice. | `goal.md:213-221,282-283`; `orchestrator/prompts.py:1433-1451`; `orchestrator/contracts.py:210-241`; `orchestrator/tasks.py:277-303` | touch plan validation, prompt block, driver requests, override write, panel; do-not-let an LLM select staffing at dispatch |
| Compatibility derivation | Run amendment A2, and the whole rule: at resume a run without a bound session opens one from its `model_profile.json` selection (absent = `default@medium`) — the session **references** the document of that profile's name at that rigor with the run's `families_order`, and the `default` document when no document carries that name. Nothing else is derived: `acts.json` literals are not carried into the session and no override is written from them, the document's own numbers apply from the next call, the marker records what ran as best-effort bookkeeping, and the operator edits the session to change it. No document is written or mutated at resume, and resume is never failed or blocked for compatibility. Pre-cutover Brainstorming pins (`dispatch_authority: static`) and standalone `resolved_staffing` keep. The derivation reads `model_profile.json` alone (name and rigor); `acts.json` is no staffing input, though the run summary and detail keep surfacing it for the acts dialog until slice 8; profile files and act sidecars are never edited or deleted. | `goal.md:259-270`; `orchestrator/driver.py:397-457`; `orchestrator/brainstorming_tasks.py:24-27,160-192`; `orchestrator/model_profiles.py:363-421` | touch derivation once at resume; do-not-migrate stored state, rewrite records, fail resume, carry act literals into the session, write a document at resume, or add machinery to represent an old literal |
| Verification | Slice 2 pins the drift alarm (the converted `default` reproducing today's stored `default@medium` seat by seat from the conversion's reference — `consult 1` against today's answer for the converted `fix 1` family as caller, one origin rather than both as today's alarm compares; `classify 1` against today's `reclassifier` resolution), that a converted profile whose fixer is the second family (the shape of this machine's `claude-lead`) seats `consult 1` on that fixer's opposite and never on the first-family fallback, and amendment A1's ladder order on each converted family. Slice 3 pins the resolution matrix (unbound family, out-of-range rank, material overrides, missing seat, `step_up`, fallback, both surfaced conditions); slices 4, 6, and 7 pin each executor seam with a captured-request test proving the seam asks the router; slice 9 pins the material channel; slice 10 pins live change, compatibility, the rename, and "no other path". Closure runs exactly `python3 -m unittest discover -s orchestrator/tests -t .`. | `goal.md:291-294`; `orchestrator/README.md:524`; `orchestrator/tests/test_model_profiles.py:435-491` (`_staffing_snapshot`, today's both-origin drift alarm); `orchestrator/tests/test_model_profile_runtime.py:186,1190,1351` (live-change test pattern); `orchestrator/static/panel.html:5286-5293` (`MODEL_OPTS`/`EFFORT_OPTS`, the family vocabularies the conversion ladders) | touch focused tests per slice; do-not-narrow the final suite |

## Question Battery

| question | answer | evidence |
|---|---|---|
| victim | Operators and calling products: standalone tasks, standalone Brainstorming, and git-sync are staffed from the first configured family and its defaults with no way to choose, and milestone staffing is spread over seven rules with different freezing; the harm is work running at an unintended family, model, or effort — visible in cost and quality, reversible per call, repeated on every order. The mandate independently records the case (a goal review that ran below configured effort because it was standalone) and requires one authority. | `goal.md:16-35`; `orchestrator/task_api.py:94-128`; `orchestrator/service.py:3468-3491`; `orchestrator/brainstorming_lifecycle.py:497-746` |
| machinery | One router module (validated document store with conversion, session store, resolver with `step_up`, fallback, and two surfaced conditions), its routes, a `material` key on the slice plan with the planning-prompt catalogue block, `staffing_session`/`role` on existing order bodies, and the rename. It serves the authorized outcome "one place decides"; it must exist because no current seam covers standalone tasks, static Brainstorming, and git-sync, and the goal fixes the document/session shape. No ledger, snapshot, identity, notification, or scheduler. | `goal.md:53-127,233-258`; `orchestrator/model_profiles.py:257-346` (store pattern reused); `orchestrator/runners.py:2940-2962` (resolver hook reused) |
| consumers | Verified: the driver's dispatch resolvers and consultation subprocess; the Brainstorming lifecycle's roster, static pins, and per-dispatch seat resolver; the direct task host and its admission; the service's git-sync and launch; the panel's launch selector, acts dialog, and catalogue fetch. No product code in the granted read-only roots calls the orchestrator API (checked by search); Agent99 is later work. | `orchestrator/driver.py:8008-8123,8152-8192,3712-3737,1344-1377`; `orchestrator/current_model_call.py:15-65`; `orchestrator/brainstorming_lifecycle.py:497-746,747-793,2528-2549`; `orchestrator/brainstorming_tasks.py:107-132`; `orchestrator/task_api.py:94-128,289-317`; `orchestrator/service.py:2015-2033,3468-3491,4011-4016`; `orchestrator/static/panel.html:691-697,4459,5850` |
| cheaper_alternative | Doing nothing keeps seven rules and undeliberate standalone staffing. Extending model profiles to the three ad-hoc paths is cheaper to build but keeps the act vocabulary, structural derivations, and no materials, rules, or product session — the mandate requires the document/session shape. An adapter over profiles keeps two vocabularies forever; a one-time deterministic conversion is cheaper to operate and review. `resolved_staffing` is kept as bookkeeping rather than removed because removal costs edits and buys nothing. | `goal.md:24-35,103-127,268-270`; `orchestrator/model_profiles.py:1-41,363-421` |
| cost | Ten bounded slices; one deterministic missing-only conversion instead of operator rewriting; one file read per call as profiles already do; one module replaces the layered resolver and three ad-hoc paths, lowering maintenance; review cost is one narrow surface per slice. Omission keeps the misstaffing and blocks the product-neutral API. Reversible: profile files untouched, old records and `worker` values readable, sessions derivable. | `goal.md:259-270`; `orchestrator/driver.py:461-470` (per-call read today); this skeleton, Planned slices |
| threat_model | Trusted: the operator at the local panel (127.0.0.1, no auth by design), calling products holding existing project access, and operator-authored documents and sessions; the router adds no permission system. Untrusted-shaped input: the planner's structured `slices` (`material`, producer) and API bodies, which existing contract validators shape-check; an unknown material collapses. No network-untrusted input reaches the router. | `orchestrator/service.py:178-183` (trust model), `3301` (`require_project_access`), `4606-4609` (admin write); `orchestrator/contracts.py:210-241`; `goal.md:244-249` |
| enforceability | Save-time validation: the store's `save` (as `model_profiles.save`). Always-answers, collapse, saturation, `step_up`, fallback, and the two surfaced conditions: the one resolver function under the slice-3 matrix tests. Live change: per-call read through the existing `resolve_dispatch` hook, proven by editing between calls as today's runtime tests do. Marker record: existing `_mark_busy`/`_retarget_busy` and task/sync markers. Review law: unchanged state/driver predicates. Rename: catalogue id plus read-time alias tests. "No other path remains": removal of the profile-based resolvers and first-family paths plus captured-request tests per seam. No asserted guarantee lacks a mechanism; nothing here promises freshness or survival beyond a per-call read. | `orchestrator/model_profiles.py:314-346`; `orchestrator/runners.py:2940-2962`; `orchestrator/driver.py:3052-3110,461-470`; `orchestrator/tests/test_model_profile_runtime.py:186,1190,1351`; `orchestrator/state.py:887-892`; `goal.md:178-211` |
