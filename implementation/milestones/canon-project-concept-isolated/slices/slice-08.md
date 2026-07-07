# Slice 08 — Panel Operator Surface

Status: draft — pending review.

Milestone: canon-project-concept-isolated. This slice is the **human half**
of the operator surface: the panel gains the standing project, work-area,
and safeguard surfaces over Slice 7's sealed API, and the service gains the
ONE API piece Slice 7 explicitly deferred here — the safeguard editor's
authoring endpoints (policy upsert/delete; slice-07 Non-Goals: "put/delete —
the safeguard editor's API — lands with the editor in the panel slice",
`slices/slice-07.md:373`–`:376`). It closes fixture invariant **I8**'s last
open half: of I8's priced cost — "policy serialization, versioning, scope
matching, contract merging, UI editing" — everything but *UI editing* sealed
with Slices 3/4/6; this slice ships the editing. It also makes the goal's
storage doctrine literally true: the project record is "Operator-owned,
service-level (projects span repos), **panel-editable**" (goal `:43`–`:44`),
and "The current panel is the prototype of agent_99's human milestone
surface, not a temporary operator hack" (goal `:74`–`:75`).

Numbering reconciliation (per sealed slice-07 `:20`–`:32`): the run ledger
titles THIS unit "Panel operator surface" — the sealed skeleton's table row
9 (`skeleton.md:176`); what earlier sealed notes call "Slice 9" or "the
panel slice" lands here. The ledger's next slice ("Built-in reuse-audit
safeguard") is skeleton row 10, named below as "the reuse-audit slice",
number-free.

The compatibility target is the frozen goal contract
(`implementation/brainstorming/project-concept.md`, frozen at `45f6968`),
read read-only: the panel surface pins — "Project CRUD + safeguard editor
(like the amendments card, but standing)" (`:359`), "Launch flow resolves
and displays the project for the chosen workspace" (`:360`), "run status
carries the project name" (`:361`) — plus deliverable (5)'s service/panel
line (`:286`–`:288`) and the dual-authorship doctrine (`:72`–`:75`). Policy
semantics are SEALED and consumed as-is: the object shape and validation
vocabulary (slice-03), enforcement (slice-04), rendering and
`project_safeguard_seen` (slice-06), and slice-03's explicit "No automatic
policy versioning" non-goal — `version` is operator intent, stored verbatim.
The route composition, the delete liveness gate, and the concrete UI
surfaces are this slice's design, consistent with those pins and pinned by
tests.

Like every slice since 4, the change is **additive and inert until used**:
project-less panel flows (launch by path, run cards, amendments, acts) are
untouched, the service change is route-layer only, and no sealed module's
semantics move.

## Scope (observable contracts)

Six contracts. Contract A is falsifiable by named tests. Contracts B–F are
the panel's operator-observable behavior: this repo has no JS test harness,
so they are pinned at the levels the stack can observe — the served page's
structural markers (AC6) and the API contracts every control calls (A plus
Slice 7's sealed routes) — and the panel JS itself is ordinary reviewable
content. Route paths, verbs, request/response shapes, and reason tokens
below are public API for the panel and later machine consumers; handler
names, JS structure, and page layout are the implementation's choice.

### A. Policy authoring API (the safeguard editor's service half)

Both routes follow Slice 7's sealed conventions: the top-level
`{"ok": true, ...}` / `{"ok": false, "error": reason}` envelope; the
project-bound gates of every project route (syntactically invalid slug →
400 `invalid_project`; valid-but-undeclared → 404 `unknown_project`;
declared-but-missing store file → 500 `missing_store`, never a silent
re-create — a write must not resurrect a lost store); store-level failures
refuse 5xx-class with their machine-readable reason token (the sealed
read's own reason where it owns the read, the service's store tokens where
the service opens the store); sealed reason tokens ride VERBATIM (no
string-matching for the panel). Policy ids share the sealed
fragment grammar (`kvstore.validate_fragment`, `kvstore.py:96`: non-blank,
no `/`, no control characters — spaces legal) and ride as URL-encoded path
segments; every sealed-valid id round-trips.

- **`POST /api/projects/<slug>/policies`** — body is the FULL sealed policy
  object `{id, version, enabled, scope, prompt, contract}` (raw, never
  wrapped) → 200 `{"ok": true, "policy": <the stored validated value>}`.
  This is an UPSERT through sealed `PolicyStore.put` (`projects.py:183`):
  create and overwrite are the same operation, identity is the body's own
  `id` (the sealed validator owns id/shape agreement), and an overwrite
  replaces the stored object WHOLESALE. Validation refusals ride verbatim
  as 400: `invalid_policy` (bad id) and `malformed_policy` (bad
  shape/scope/contract — the sealed vocabulary, `projects.py:30`–`:31`).
  The service adds NO validation of its own and never reshapes the object.
  Two consequences pinned by tests:
  - **Version rides verbatim** — no auto-bump, no derivation (sealed
    slice-03 non-goal): a re-put with the same `version` reads back with
    that version; a re-put with a bumped `version` reads back bumped. The
    envelope's control revision stays INTERNAL to the store — the response
    carries only the domain object, because control revision ⟂ domain
    version is the frozen storage rule and exposing both invites exactly
    the confusion slice-03 separates.
  - **A valid re-put over a malformed stored entry succeeds** and replaces
    it (the sealed put validates the NEW value and never reads the old) —
    this is the API-level recovery for one corrupt policy entry, consistent
    with greenfield's no-repair reads: nothing tolerant-reads the old
    value; it is replaced whole.
- **`DELETE /api/projects/<slug>/policies/<id>`** → 200
  `{"ok": true, "policy": {"id": <id>, "deleted": true}}`, only for a LIVE
  policy. The gate is one sealed read first: an unknown, tombstoned, or
  never-written id refuses 404 `unknown_policy` and WRITES NOTHING — the
  raw envelope delete happily tombstones never-written keys
  (`kvstore.py:549`) and listings include tombstones by the frozen contract
  (`skeleton.md:128`–`:130`), so an ungated delete of a typo'd id would
  "succeed" and mint a junk tombstone key every listing carries forever. A
  malformed stored value at the id refuses 5xx `malformed_policy` and
  writes nothing (fail-closed; the recovery is the re-put above). A live
  policy's delete tombstones its key through the sealed envelope delete:
  the id then leaves the project entry's `policy` list and its key reads
  `exists?: false`.
- **No new read surface.** The safeguard editor reads policies from the
  assembled ProjectEntry (`GET /api/projects` / `GET /api/projects/<slug>`,
  sealed slice-03 read model exposed by Slice 7) — one read model, no
  parallel.
- **The delete guard becomes API-reachable end-to-end**: a policy created
  through this route blocks `DELETE /api/projects/<slug>` with 409
  `project_in_use` (slice-07's sealed guard) until deleted through this
  route. Slice 7's tests could only seed that guard through the store
  directly (`test_service_projects.py:1489`); the whole lifecycle is now
  drivable over HTTP.

### B. The standing projects surface (panel)

- **Standing, not run-scoped**: reachable from the panel's main screen
  without selecting a run, and usable when zero runs exist. Project
  configuration outlives every run — the surface must not live behind one.
- **Lists every declared project** from `GET /api/projects`: slug,
  defaults, work areas, and policies (via C/D). A broken project renders
  its error marker `{slug, error: {reason}}` DISTINGUISHABLY, reason token
  shown verbatim, while healthy projects render normally beside it —
  fail-closed per project, never all-or-nothing, never repaired
  (slice-07 A).
- **Create / edit / delete**: create takes a slug plus optional defaults
  (JSON object); defaults edit replaces the object, clear sends null
  (slice-07's update contract); delete asks for confirmation (the panel's
  existing `confirm()` posture for destructive acts) and surfaces refusals.
  EVERY refusal token (`invalid_project`, `project_exists`,
  `invalid_defaults`, `project_in_use`, store errors) surfaces verbatim in
  the surface's error line — never swallowed, never translated.
- **Mutations reflect without a page reload** (the surface re-reads after
  each operation), and the 2s runs poll NEVER resets an in-progress edit in
  any surface this slice adds — the acts-dialog precedent (edits live
  outside the polled container, `panel.html:713`–`:714`) is the named
  pattern.

### C. Work-area operations within a project (panel)

- **Declare** (the Body-declare role): name, optional display name, primary
  path — reusing the existing directory picker (`openPicker`,
  `panel.html:794`) — and zero or more additional paths, posted to Slice
  7's declare route. The created record shows at version 1 `pending`.
- **The card renders the full public record truthfully**: name, display
  name, status (`pending`/`ready`/`unavailable`), version, primary root,
  additional roots. The operator SEES reconcile state: after the first
  bound launch the area reads `ready` at version 2 on the surface's next
  read — no local interpretation, the record is the display.
- **Relabel** (display name) and **delete** (confirm; the name leaves the
  surface and is re-declarable fresh) through the sealed routes.
- **Reuse-source meta is panel-editable**: per work area the sealed value
  `{reuse_sources: [{root, inventory, registry, consumption}]}` is viewable
  and editable as raw JSON, posted raw to the meta route. The panel parses
  the operator's JSON for syntax only and NEVER reshapes or semantically
  validates it — the sealed shape rides verbatim both ways. This is the
  human authoring surface for the roles slice-06 renders into PROJECT
  CONTEXT and the reuse-audit slice consumes.
- All work-area refusals surface their sealed tokens verbatim.

### D. The safeguard editor (panel)

"Like the amendments card, but standing" (goal `:359`): where the
amendments card (`panel.html:489`–`:497`) edits run-scoped free text that
dies with the run, this editor makes project-scoped, versioned policy
OBJECTS operator-editable — standing law, I8's UI-editing half.

- **Lists each policy** from the project entry: id, version, enabled state,
  scope (worker kinds × unit kinds), and the prompt text or a preview; the
  full stored JSON is viewable.
- **Create / edit as the full JSON document**: create seeds the sealed
  shape's exact top-level keys; edit seeds the CURRENT stored object;
  submit posts the operator's JSON as-is to A after a client-side SYNTAX
  parse only. The panel performs no semantic validation and no reshaping —
  the sealed validator is the ONLY validator (a client-side schema copy
  would be a parallel validator: the duplication class this milestone
  exists to kill). Sealed refusal tokens surface verbatim in the editor's
  error line.
- **Version is operator intent, surfaced as such**: the editor never
  auto-bumps. Its hint text states the two standing rules the operator
  needs at the point of edit: a substance change should bump `version` so
  every run re-records the safeguard (`project_safeguard_seen` re-records
  per `(id, version)` — slice-06), and run-scoped amendments WIN over
  project safeguards on conflict (the frozen precedence), so the operator
  knows which knob is which.
- **Enable/disable is one step**: a per-policy toggle that round-trips the
  stored object with ONLY `enabled` flipped, version untouched — flipping
  visibility is not a substance change, and the compatibility concept is
  agent_99's "effective capability set is the enabled, in-scope" policies.
- **Delete** with confirmation → A's delete; an unknown id's verbatim 404
  token surfaces.

### E. Launch flow: binding and the resolved project (panel)

- The launch dialog offers launching against a declared
  `(project, work area)` as an alternative to the bare workspace path.
  BOTH modes stay first-class; the path mode's fields and behavior are
  untouched.
- Choices load from `GET /api/projects` when the form opens: declared
  projects, each with its live work areas and their status. A `pending`
  area is offered — launch validation IS the reconcile (slice-07 C); the
  first launch takes it to `ready`.
- Selecting both **displays the resolved target before launch**: the work
  area's primary root — the repo the run will execute in — beside the two
  path-free handles. This is the goal's "Launch flow resolves and displays
  the project" (`:360`) in the direction the sealed contracts support: the
  panel DISPLAYS what the sealed handle-driven seam resolves; it never
  re-derives resolution.
- Submitting a bound launch posts `{project, work_area}` WITHOUT a
  workspace path (it derives from `primary.path` — slice-07 C);
  name/goal/goal_doc/acts/config/autostart ride exactly as today.
- Every launch refusal — `unknown_work_area`, `malformed_work_area`,
  `missing_primary_path`, `primary_not_repo_root`,
  `missing_additional_root`, `workspace_mismatch`, `descriptor_mismatch`,
  `conflict`, the 409 attach hint — surfaces verbatim in the form's
  existing error line (`#formError`), with no token translation and no
  string-matching in the panel.

### F. Bound-run visibility (panel)

- A bound run shows its two path-free handles `{project, work_area}` in
  BOTH the runs-list row and the run-detail header, beside the workspace
  path — the goal's "run status carries the project name" (`:361`) surfaced
  to the human; the API has carried the handles since slice-07 E.
- A project-less run renders exactly as today.

## Non-Goals

- **No concrete safeguard content and no reuse-audit template.** The
  editor is fully generic; the built-in reuse-audit policy is the
  reuse-audit slice's (slice-03's rule: no concrete safeguard content
  ships before it). Nothing here hardcodes any policy id, prompt, or
  contract field.
- **No policy-semantics changes.** Scope matching, contract merge,
  enforcement, prompt rendering, and seen-event semantics are sealed
  (Slices 3/4/6); this slice writes and deletes policy objects, nothing
  more.
- **No new read model and no client-side validation.** Policy reads ride
  the assembled ProjectEntry; the panel never revalidates or reshapes
  sealed values (work-area records, meta, policies).
- **No automatic versioning, no version derivation, no policy edit
  history.** Version is operator intent (sealed slice-03 non-goal); git and
  the ledger's `project_safeguard_seen` trail are the history — the KV
  holds only descriptors.
- **No new HTTP verbs.** The service's verb surface stays GET/POST/DELETE
  (the existing handler convention); upsert rides POST like every existing
  update route.
- **No JS framework, build step, or external asset.** `panel.html` stays
  one self-contained file, matching the stdlib-only service doctrine.
- **No path→project resolution or membership hints in the launch form.**
  Binding is handle-driven by the sealed init seam; a path-matching hint
  has no pinned consumer (recorded under Proportionality).
- **No digest, no `primary_root` alias, no SCHEMAS doc** — the machine-api
  milestone's (skeleton Non-Goals). `run:<run_id>/digest` stays unwritten.
- **No changes to `webapp.py` or `static/index.html`** (the old read-only
  dashboard) and **no semantic changes to sealed modules**: `projects.py`,
  `workareas.py`, `kvstore.py`, `driver.py`, `state.py`, `prompts.py`,
  `contracts.py`, `verifiers.py`, `runners.py`, `gitops.py`, `registry.py`
  are consumed as-is; `service.py` gains only the route layer of A.
- **No trust-model change** (localhost-only, no auth), **no mid-run
  rebinding, no work-area health monitoring** (slice-07 non-goals stand).
- **No migrations, compat shims, or tolerant readers** (greenfield, I12).

## Expected Files

- `orchestrator/static/panel.html` (edit) — contracts B/C/D/E/F: the
  standing projects surface, work-area cards, safeguard editor, launch
  binding, bound-run handles.
- `orchestrator/service.py` (edit) — contract A: the `policies` branches in
  the existing `projects_api` dispatcher plus the module docstring's route
  table; nothing else.
- `orchestrator/tests/test_service_projects.py` (edit) — the A matrix and
  the served-page markers, on the same threaded `make_server(home, 0)` /
  isolated-tempdir harness; splitting a new test module instead is the
  implementation's choice if size demands.

## Dependencies

- **Slice 7** (sealed) — everything the panel calls: the project/work-area
  routes and their envelope, gates, and verbatim token mapping
  (`service.py:28`–`:50`, `:168`, `:182`, `:209`); ProjectEntry /
  WorkAreaView shapes; the launch binding and its refusal seam
  (`:1126`–`:1233`); the guarded project delete (`:312`–`:361`); run-status
  handles (`:1042`–`:1055`); and its recorded deferral of A to this slice
  (`slices/slice-07.md:369`–`:376`).
- **Slice 3** (`orchestrator/projects.py`, sealed) — `PolicyStore`
  put/read/list_policies/delete (`:183`, `:187`, `:204`, `:237`), the
  validation vocabulary (`:29`–`:32`), the policy shape (`:19`), and the
  no-auto-versioning doctrine its note pins.
- **Slice 1** (`orchestrator/kvstore.py`, sealed) — the envelope delete's
  never-written-key behavior (`:549`) and tombstones-in-listings
  (`skeleton.md:128`–`:130`): together the rationale for A's liveness gate;
  the fragment grammar (`:96`).
- **Slice 6** (sealed, context) — `project_safeguard_seen` re-records per
  `(id, version)` and amendments-win precedence: the two facts D's hint
  text surfaces.
- **Slice 2** (sealed, context) — the public work-area record domain C
  renders and the sealed meta shape C edits.
- The existing panel machinery this slice extends: the `api()`/`esc()`
  helpers, dialog and `confirm()` conventions, the directory picker
  (`panel.html:794`), the `#formError` pattern (`:151`, `:919`), the
  amendments card as D's model (`:489`–`:497`), the outside-the-poll edit
  rule (`:713`–`:714`), the runs list and detail header F extends
  (`:401`–`:406`, `:457`–`:462`), and `test_root_serves_panel`
  (`test_service_api.py:114`) as the served-page marker precedent.
- The frozen goal read read-only (`:43`–`:44`, `:72`–`:75`, `:286`–`:288`,
  `:357`–`:366`) and the pricing fixture (**I8** — the UI-editing half;
  **I12** greenfield).
- Consumers arriving later: the reuse-audit slice (ships the built-in
  template this editor enables and parameterizes), the machine-api
  milestone (machine consumers of the same routes).

## Reuse Posture

- **Checked (this repo):** the whole panel (`static/panel.html`) — the
  amendments card, acts dialog, launch form, picker, error patterns, poll
  and its edit-preservation precedent; the service's `projects_api`
  dispatcher, project gates, token maps, and `_raise_store_error`;
  sealed `PolicyStore` and the envelope primitives; slice-07's tests
  (policies seeded via the store — the API gap this slice closes);
  confirmed no `policies` route exists and nothing else writes `policy:`
  keys in production code.
- **Checked (contract sources, read-only):** the frozen goal's panel
  lines and deliverable (5); fixture I8's cost enumeration; slice-03's
  no-auto-versioning and slice-06's seen semantics as the version-hint
  ground truth.
- **Reused / extended:** A rides the EXISTING dispatcher, gates, envelope,
  and error mapping — two new branches, no parallel router; every policy
  write/read/delete goes through sealed `PolicyStore` (no parallel
  validator, writer, or read model); the panel surfaces reuse the existing
  dialog, picker, confirm, error-line, and re-render-preservation
  patterns; the safeguard editor is deliberately shaped on the amendments
  card; F extends the existing row/header rendering with fields the API
  already serves.
- **New machinery, and why (the I8 gap, not parallels):** the two policy
  routes + the delete liveness gate (no authoring API exists — slice-07's
  recorded deferral); the three panel surfaces and launch-binding UI (no
  UI exists; the goal pins "panel-editable" and the fixture prices "UI
  editing"). Nothing duplicates an existing facility.
- **Compatibility:** sealed tokens and shapes ride verbatim end-to-end; no
  new KV family, key, or namespace knob (the grammar is untouched); the
  routes keep the path-free handle vocabulary the future agent_99 adapter
  consumes.

## Proportionality (amendment A1)

The projects/work-area CRUD surfaces, the safeguard editor, the launch
binding UI, and the handle display are pinned by I8 and the frozen goal's
panel lines — not re-derived. New mechanism beyond the pinned invariants,
one line each:

- **Policy authoring routes (A).** VICTIM: the operator — standing
  safeguards are un-authorable (the reuse-audit slice ships a template with
  nothing to enable it through; slice-07 recorded this slice as the
  deferral target). COST: two dispatcher branches over the sealed store.
- **Delete liveness gate (A).** VICTIM: the operator's listings — an
  ungated delete of a typo'd id "succeeds" and mints a junk tombstone key
  that every listing carries forever (tombstones-in-listings is frozen).
  COST: one sealed read per delete.
- **Enable/disable toggle (D).** VICTIM: the operator running the
  highest-frequency safeguard operation (the effective set is the enabled,
  in-scope policies) by hand-editing a JSON document each flip —
  error-prone edits to standing law. COST: one client-side flip through
  the same route.
- **Meta JSON editor (C).** VICTIM: slice-06's rendered roles and the
  reuse-audit slice — without it `reuse_sources` stays authorable only by
  hand-rolled curl against a goal that pins the record as panel-editable.
  COST: one textarea form over the existing meta route.
- **Version-bump + precedence hint text (D).** Copy, not mechanism; it
  prevents silently-unrecorded safeguard changes. COST: two sentences.

Nothing is SPECULATIVE and nothing requires operator approval. Deliberately
NOT built, with reasons: a per-policy GET route (the assembled entry is the
one read model; a second source can drift); path→project membership hints
in the launch form (binding is handle-driven by the sealed seam; no pinned
consumer names the hint); a schema-driven policy form builder (an order of
magnitude more UI than a JSON editor over one sealed shape); a client-side
validation mirror (a parallel validator — the milestone's target failure
class); policy edit history (git + the ledger already record it); a PUT
verb (the service's verb set is a standing convention).

## Acceptance Criteria

1. **Policy upsert (A, I8).** Posting a valid sealed policy object to
   `POST /api/projects/<slug>/policies` returns 200 with the stored
   validated value under `policy`; the id then appears in the project
   entry's `policy` list with that exact object; re-posting a changed
   object under the same id overwrites it wholesale; the response carries
   no envelope control revision.
2. **Version rides verbatim (A).** A re-put with the same `version` reads
   back unchanged; a re-put with a bumped `version` reads back bumped;
   nothing auto-bumps — including a put that changes only `enabled`
   (the toggle's API path: flip stored, version untouched).
3. **Policy refusals (A).** A bad id refuses 400 `invalid_policy`; a bad
   shape (missing/extra key, unknown scope kind, non-positive version)
   refuses 400 `malformed_policy`; an invalid slug 400 `invalid_project`;
   an undeclared slug 404 `unknown_project`; a declared project with a
   missing store file 500 `missing_store` and the put writes nothing; all
   tokens verbatim.
4. **Policy delete and its gate (A).** Deleting a live policy returns
   `{"id", "deleted": true}`, removes it from the project entry, and its
   key reads tombstoned; deleting an unknown, never-written, or
   already-deleted id refuses 404 `unknown_policy` AND writes nothing (the
   store's key listing is unchanged); a malformed stored policy refuses
   5xx `malformed_policy` and writes nothing, while a valid re-put over it
   succeeds and replaces it; an id containing spaces round-trips
   URL-encoded.
5. **Guard reachability (A).** Creating a policy through the API makes
   `DELETE /api/projects/<slug>` refuse 409 `project_in_use`; deleting the
   policy through the API unblocks it — the standing-law lifecycle is
   drivable end-to-end over HTTP.
6. **Served panel carries the surfaces (B–F).** `GET /` serves a page
   containing the standing projects surface, the safeguard editor, and the
   launch-binding controls (load-bearing element hooks and the
   `/api/projects` route string present — the `test_root_serves_panel`
   posture), with the pre-existing markers intact.
7. **Additivity.** Project-less panel flows are untouched: the entire
   pre-existing suite passes unmodified, and no production path writes any
   new key family (the grammar is unchanged; only `policy:` keys are
   written, through the sealed builder).
8. **Suite green.** `python3 -m unittest discover -s orchestrator/tests
   -t .` passes.

## Tests / Verification

In `orchestrator/tests/test_service_projects.py` (standard library only;
the threaded `make_server(home, 0)` isolated-tempdir harness of the
existing file):

- **Upsert matrix** — create, read-back-in-entry, wholesale overwrite,
  no-control-revision response, verbatim `invalid_policy` /
  `malformed_policy` / project-gate refusals, URL-encoded id round-trip
  (AC1, AC3, AC4's encoding leg).
- **Version discipline** — same-version rewrite, bumped-version rewrite,
  enabled-only flip preserving version (AC2).
- **Delete matrix** — live delete + tombstoned readback + entry removal;
  the no-write pin for unknown/tombstoned ids (key-listing snapshot equal
  before and after the 404); malformed-entry delete refusal vs re-put
  recovery (AC4).
- **Guard lifecycle** — API-created policy blocks project delete, API
  delete unblocks (AC5).
- **Served-page markers** — the three surfaces' hooks plus existing
  markers (AC6).
- **Regression** — the pre-existing suite unmodified (AC7).

Full slice verification: `python3 -m unittest discover -s orchestrator/tests
-t .` (AC8).

Panel interaction behavior beyond the served markers (form flows, verbatim
token display, poll-vs-edit preservation) has no automated harness in this
repo; it is pinned by the API contracts above and reviewed as content —
reviewers exercise the reviewable JS against contracts B–F.

## Risks

- **A client-side validation or schema mirror** would fork the sealed
  vocabulary — the exact duplication class the milestone exists to kill.
  Contract D's syntax-only rule and Reuse Posture guard it; a reviewer
  finding semantic validation in `panel.html` is a P1 duplication finding.
- **Auto-bumping `version` (or leaking the control revision into the
  editor)** would corrupt operator intent and the `(id, version)` seen
  semantics — a safeguard could change substance with no run ever
  re-recording it, or re-record spuriously on every save. AC1/AC2 are
  load-bearing.
- **An ungated policy delete** mints junk tombstones that every listing
  carries forever (frozen listing semantics). AC4's no-write pin is
  load-bearing.
- **Swallowed or translated refusal tokens** in the panel would blind the
  operator and reinvent string-matching — the failure slice-05's error
  seam was built to prevent. The verbatim-token ACs and the `#formError`
  pattern guard it.
- **Rendering the new surfaces inside the polled container** would clobber
  operator edits every 2s; the acts-dialog precedent is the named pattern,
  and contract B pins the observable rule.
- **Hardcoding any concrete safeguard** into the editor would pre-empt the
  reuse-audit slice's template and violate slice-03's no-content rule.
- **Degrading the path launch mode** (required binding fields, changed
  defaults) would strand project-less runs — including this milestone's
  own. AC7 is load-bearing.

## Line budget

Expected to EXCEED the ~500 changed-line target, for a recorded structural
reason: the panel is a single self-contained file with no framework, so
three standing surfaces (projects, work areas, safeguards) plus the launch
binding are hand-rolled markup and JS in `panel.html`, and the A matrix —
upsert/version/delete-gate/guard tests the reuse-audit slice and the fusion
story depend on — carries the test bulk. The production service half stays
thin: two dispatcher branches and one liveness gate over sealed seams.
