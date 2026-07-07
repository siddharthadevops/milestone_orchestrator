# Slice 07 — Service API: Project/Work-Area CRUD + Launch Binding

Status: draft — pending review.

Milestone: canon-project-concept-isolated. This slice is the **operator
activation** of the machinery Slices 1–6 sealed: the service gains the
standing project surface — project and work-area CRUD over the sealed
stores, plus `GET /api/projects` — and the launch flow learns to bind a run
to `(project, work_area)`: the operator surface plays the Body's **declare**
role (declare → `pending`), the launcher's validation plays the executor's
**reconcile** role (validate the declared roots against the real filesystem
→ `ready`), and Slice 5's sealed project-bound init creates the run. Run
status carries the project name, and the enveloped `run:<run_id>/status`
projection — the one non-reserved `run:*` family — gets its writer. This
closes fixture invariant **I2**'s service gap ("current service launch
still takes workspace as a path", evidence `orchestrator/service.py:337`)
and **I1**'s launch-flow half, and drives I3's reconcile version semantics
and I6's bounded projection writes through the sealed stores.

Numbering reconciliation (load-bearing for readers of earlier notes): the
run ledger's slice list titles THIS unit "Service API: project/work-area
CRUD + launch binding" and follows it with "Panel operator surface" and
"Built-in reuse-audit safeguard". The sealed skeleton details the same work
as table rows 7 AND 8 (`skeleton.md:174`–`:175`) — row 7 (CRUD +
`GET /api/projects`, I2) and row 8 (launch binding + status projection +
project name in run status, I1); skeleton rows 9/10 are the ledger's
slices 8/9. Earlier sealed notes reference the skeleton table: what
slice-05/slice-06 call "Slice 7" (CRUD; reconcile-to-ready) and "Slice 8"
(launch binding; `run:<run_id>/status`; refusal→400 mapping;
passing the persisted defaults) BOTH land here; their "Slice 9" (panel) and
"Slice 10" (reuse-audit) are the next two ledger slices. Below, "the panel
slice" and "the reuse-audit slice" name those, number-free.

The compatibility target is the frozen goal contract
(`implementation/brainstorming/project-concept.md`, frozen at `45f6968`),
read read-only: the storage doctrine "Operator-owned, service-level
(projects span repos), panel-editable" (`:43`–`:44`); the launch shape
(`:61`–`:63`); the local state machine — "the panel playing the Body's
declare role and the launcher's validation playing the executor's reconcile
role (e.g. \"primary.path is a git repo root\" → ready)" (`:126`–`:129`);
local authority — "this machine is the writer of record; after fusion the
server copy is a visibility mirror" (`:130`–`:135`); "The datastore … holds
only descriptors and projections … re-declare work areas, re-pump
projections" (`:136`–`:141`); deliverable (5) verbatim (`:286`–`:288`); and
the service surface — "`GET /api/projects`; run status carries the project
name" (`:359`–`:361`). Those shapes are adopted, never re-derived. The
endpoint composition, the concrete validation set, the projection's
writer/value/lifecycle, the service-convention rung in the config
precedence, and the guarded project delete are this slice's design,
consistent with those pins and pinned by tests.

Like Slices 4–6, the change is **additive and inert until used**: a
project-less launch is behavior-identical to today — same statuses, same
side effects, zero KV access, no project store base even created — because
every existing run (including this milestone's own) stays first-class. No
sealed behavior changes: the driver and existing store semantics are consumed
as-is; `kvstore.py` only gains the public empty-store initializer named below.

## Scope (observable contracts)

Six contracts. Each statement is falsifiable by a named test, not by
reading the diff. The route paths, verbs, request shapes, and response
envelopes below are public API contracts for the panel and later machine
consumers; handler names and file layouts remain the implementation's
choice. The pinned content is each surface's observable behavior, the
sealed vocabularies riding verbatim, the launch flow's ordering and
refusal semantics, the config precedence, the projection's
value/lifecycle, and project-less inertness.

**Route and envelope contract.** Every service response keeps the existing
top-level envelope: success is `{"ok": true, ...}`; refusal is
`{"ok": false, "error": reason}`. `ProjectEntry` is
`{slug, work_areas: [WorkAreaView], policy, defaults?}`; `ProjectError`
is `{slug, error: {reason}}`; `WorkAreaView` is `{record, meta}` where
`record` is the full public work-area domain and `meta` is null or the
sealed reuse-source value. Project slugs and work-area names ride as
URL-encoded path segments; every Slice 2-valid slug/name, including spaces,
round-trips on all routes below.

- `GET /api/projects` →
  `{"ok": true, "projects": [ProjectEntry | ProjectError]}`.
- `POST /api/projects` body `{"slug": string, "defaults"?: object}` →
  201 `{"ok": true, "project": ProjectEntry}`.
- `GET /api/projects/<slug>` → `{"ok": true, "project": ProjectEntry}`.
- `POST /api/projects/<slug>` body `{"defaults": object | null}` → 200
  `{"ok": true, "project": ProjectEntry}`; object replaces defaults, null
  clears them.
- `DELETE /api/projects/<slug>` → `{"ok": true, "deleted": slug}`.
- `POST /api/projects/<slug>/work-areas` body
  `{"name": string, "display_name"?: string, "primary_path": string,
  "additional_paths"?: [string]}` → `{"ok": true, "work_area": WorkAreaView}`;
  this declare route also handles descriptor re-declare/update.
- `GET /api/projects/<slug>/work-areas/<name>` →
  `{"ok": true, "work_area": WorkAreaView}`.
- `POST /api/projects/<slug>/work-areas/<name>` body
  `{"display_name": string}` → `{"ok": true, "work_area": WorkAreaView}`.
- `DELETE /api/projects/<slug>/work-areas/<name>` →
  `{"ok": true, "work_area": {"name": name, "deleted": true, "version": n}}`.
- `GET /api/projects/<slug>/work-areas/<name>/meta` →
  `{"ok": true, "meta": null | {reuse_sources: [...]}}`; the work area must
  read as a live record.
- `POST /api/projects/<slug>/work-areas/<name>/meta` body
  `{reuse_sources: [...]}` — the raw sealed meta value, not wrapped in
  `meta` — requires a live work area, replaces it, and returns
  `{"ok": true, "meta": {reuse_sources: [...]}}`.
- Any project-bound route with a syntactically invalid slug refuses
  400-class with `invalid_project`; any project-bound route with a valid but
  undeclared slug refuses 404-class with `unknown_project`.

### A. The project surface: declaration, enumeration, defaults

- **Declaration.** A project is declared through the service (the current
  panel is "the prototype of agent_99's human milestone surface", goal
  `:74`–`:75`): a Slice 2-valid slug (`validate_project_slug`,
  `workareas.py:101`) plus optional `defaults`. Declaring materializes the
  project's `<base>/<slug>` store under ONE service-level base directory
  the service owns (under its home; exact location the implementation's
  choice) and leaves the store READABLE — not a bare directory — by using a
  public empty-store initializer on the sealed KV format. This is a
  declaration/read contract: a declared zero-entry project survives restart
  and is distinguishable from a missing or corrupt store in `GET
  /api/projects` and single-project reads. This writes no key and changes no
  key family.
  An invalid slug refuses with `invalid_project`; re-declaring an existing
  slug refuses as a conflict (defaults change through the update surface,
  never by silent re-create).
- **Enumeration and read: `GET /api/projects`** (the frozen route, goal
  `:361`). The listing returns every declared project; each entry carries
  the slug and the assembled read model of sealed slice-03 §E: `policy`
  (live policies, READ-ONLY here), `defaults` when set, and `work_areas`
  from the sealed assembler (`ProjectStore.read`, `projects.py:267`). The
  service response wraps each live work-area record as `WorkAreaView`, with
  the untouched Slice 2 public record in `record` and the meta value beside
  it in `meta`, never inside it (the goal's "rides BESIDE the agent_99
  fields" doctrine, `:63`–`:65`). A single-project read exposes the same
  shape.
- **Per-project fail-closed.** A project whose store is missing, unreadable,
  or holds malformed data yields an ERROR ENTRY for that slug (reason
  included, no partial record — slice-03's fail-closed assembly), while
  healthy projects keep listing; a missing zero-entry KV file is an error, not
  an empty project, and nothing repairs or invents (greenfield, I12).
- **Defaults persist service-side, never in the KV.** `defaults` (the
  project record's optional standing conventions, goal `:70`) persists in
  an operator-owned service-home record written with the same locked
  temp-file-replace posture as `registry.json`/`recents.json`
  (`registry.py:65`–`:76`, `:79`–`:90`, `:214`–`:224`) — NOT in a new KV
  family: the key grammar is frozen and
  closed (I7; sealed slice-03 §E: "It has no KV family"). Defaults survive
  service restarts, are returned by the reads above, feed every bound
  launch (C/D), and are replaceable through `POST /api/projects/<slug>`:
  a JSON-plain object replaces the defaults, null clears them, and any
  other value refuses with `projects.INVALID_DEFAULTS`
  (`kvstore.canonical_json_value`, `kvstore.py:179`).
- **Guarded delete.** Deleting a project removes it from enumeration and
  removes its store, and REFUSES as a conflict while: any live
  (non-tombstoned) work area exists, any live policy exists, or any
  registered run's state binds the project, or any registered run's state
  is unreadable and therefore cannot be proven unbound. A plain-forgotten
  bound run is still a retained, attachable state for this guard: it blocks
  delete until the state is purge-deleted or reads back unbound. Deleting
  standing law under any such state would strand it in slice-06's
  fail-closed failure with nothing left to repair. Tombstone-only history
  never blocks deletion (descriptors are disposable by design, goal
  `:136`–`:141`).

### B. Work-area CRUD over the sealed store

Every agent_99-readable work-area mutation goes through Slice 2's sealed
`WorkAreaStore` — declare (`workareas.py:429`), relabel (`:528`), delete
(`:550`), never a parallel raw-record writer — so the compatibility
behaviors (full stored domain, whole-value CAS, per-operation version
semantics, positive-version tombstone — I3/I4/I5) hold through the API by
construction. Meta authoring uses the same store's sealed meta shape
(`:561`, `:565`); on delete, the service additionally tombstones the
sibling `work_area_meta:<name>` key through that enveloped family. That
touches only OUR meta family, never the agent_99 raw record.

- **Declare → pending** (the Body-declare role): the operator supplies the
  name, optional display name, and the roots as absolute canonical PATHS
  (primary + additional); the service supplies the device value and the
  executor identity (E). The created record reads back in the full public
  domain `{name, display_name, primary, additional, executor_id, version,
  status}` at `version` 1, `status` "pending". Re-declaring different
  content is the sealed content-update (version+1, back to `pending` — it
  must re-reconcile); re-declaring identical content is the sealed no-op.
- **Relabel** updates `display_name` and PRESERVES `version` (the sealed
  label-only edit, I3). **Delete** writes agent_99's positive-version
  tombstone through the sealed store; in the same successful API operation,
  the service tombstones sibling meta so the name reads and lists as unknown,
  and re-declaring the same name starts with no retained meta.
- **Reuse-source meta**: get/put of the enveloped `work_area_meta:<name>`
  value, validated by Slice 2's sealed shape (exactly
  `{reuse_sources: [{root, inventory, registry, consumption}]}`,
  `workareas.py:336`); a malformed value refuses; absent meta is not an
  error. Meta get/put are valid only for a live work-area record: unknown or
  tombstoned names refuse 404-class with `unknown_work_area`; malformed
  records refuse 5xx-class with `malformed_work_area`. This is the authoring
  surface slice-06's rendering and the reuse-audit slice's audits consume.
- **Refusal mapping.** Sealed reason tokens ride VERBATIM in error bodies
  (no string-matching — slice-05's doctrine): the validation reasons
  (`workareas.py:45`–`:55`) map to 400-class, `unknown_work_area` to
  404-class, CAS exhaustion (`conflict`) to 409-class, and
  `malformed_work_area` (store corruption) to a 5xx-class error. Names ride
  URL-encoded; every Slice 2-valid name (spaces included) round-trips.

### C. Launch binding: validation is the reconcile

The EXISTING launch surface (`POST /api/runs`, `create_run`,
`service.py:336`) gains the optional binding — no second launch endpoint: a
payload naming `{project, work_area}` (goal/goal_doc/name/config/autostart
as today) launches against the project instead of a bare path. Observable
flow, in order:

1. **Addressing.** The project must be declared (A) and the work area must
   read as a live record through the sealed store (`read`,
   `workareas.py:378`). An undeclared project, unknown/tombstoned work area,
   or malformed work-area record refuses 400-class with the sealed reason
   token through `ProjectResolutionError`; this is the sealed launch-init
   seam, distinct from the CRUD/read-route status mapping in B. Either
   refusal creates nothing.
2. **Validation (the executor-reconcile role, goal `:126`–`:129`).**
   Against the STORED descriptor's roots — never roots taken from the
   request: `primary.path` must be an existing directory; when git is
   enabled in the launch's effective config (D) it must be a git repository
   ROOT — the SAME predicate as today's gate (`gitops.is_repo_root`,
   `gitops.py:124`, used at `service.py:399`; no parallel git logic); and
   every `additional` root must be an existing directory (the
   launcher-validation duty sealed slice-05 §B explicitly deferred here; a
   root that vanishes later still surfaces through Slice 4's operational
   error at check time). A failed validation refuses 400-class with a
   machine-readable reason, leaves the record's status UNCHANGED, and
   creates nothing.
3. **Reconcile → ready.** On pass, the service confirms the stored
   descriptor through the sealed transition (`WorkAreaStore.confirm`,
   `workareas.py:497`): the first reconcile takes `pending` version 1 to
   `ready` version 2 (the sealed agent_99-pinned bump); re-reconciling an
   already-ready record with the same stable identity (E) preserves the
   version — repeat launches are version-silent. A failed confirm refuses
   with the sealed work-area reason token and B's status mapping (including
   `descriptor_mismatch` and `conflict`) and creates no state file, registry
   entry, or projection entry.
4. **Bound init through the sealed seam.** The run is created by Slice 5's
   `init_run(project=…, config_override=…)` (`driver.py:2204`) with the
   binding `{directory, project, work_area, defaults}`. The service supplies
   binding `defaults` as the launch-time standing defaults from D: service
   convention merged UNDER the persisted project defaults; the launch
   config alone rides `config_override`. Workspace derivation and the strict
   equality cross-check, read-only resolution, the state project block, and
   the single `project_resolved` event are the sealed contracts — this
   slice adds no resolution logic.
5. **Refusals ride verbatim.** A `ProjectResolutionError` response maps to
   400-class and carries its `cause` token verbatim (`driver.py:2082` built
   that seam naming this launcher as its consumer); no per-cause status
   remapping is introduced at this seam, so `malformed_work_area` is still
   400-class here. `FileExistsError` stays 409 with the attach hint
   (`service.py:416`–`:417`). Any refusal at or after step 4 creates no state
   file, no registry entry, and no projection entry; a refusal AFTER step 3
   may truthfully leave the work area `ready` — the reconcile validated real
   roots, and readiness describes the descriptor, not this launch.
6. **Attach is incompatible with a binding** (attach adopts an existing
   state as-is; combining refuses, exactly like goal/goal_doc/config today,
   `service.py:349`–`:358`). A supplied `workspace` alongside a binding
   passes through to init's sealed strict-equality check
   (`workspace_mismatch`, `driver.py:2076`); omitted, the workspace derives
   from `primary.path`.

### D. Effective config precedence at bound launches

One observable order, built from the single merge source
(`driver.merge_config`, `driver.py:143`) over sealed slice-05 §E's
launch > defaults > built-ins rule:

launch config > persisted project defaults > the service's git-enabled
convention > `DEFAULT_CONFIG`.

The service's existing full-flow convention (git enabled by default for
panel runs, `service.py:381`) drops BENEATH project defaults for bound
launches: a project whose defaults disable git launches pure-state runs
with no per-launch typing (standing operator law beats a service
convention), while an explicit launch config beats both — the milestone's
precedence doctrine at the config layer. Validation (C.2) follows the same
effective config: a git-disabled bound launch skips the repo-root check;
primary existence and additional-root existence are unconditional.

At the sealed init seam this order is represented as
`DEFAULT_CONFIG <- binding defaults <- config_override`: for bound service
launches only, binding defaults are the service git-enabled convention
merged beneath the persisted project defaults, and `config_override` is only
the explicit launch config.

### E. Run status carries the project; identity is stable

- **The handles, everywhere run status flows** (goal `:361`): for a bound
  run the state summary (`state.py:759`) exposes the two path-free handles
  `{project, work_area}` from the state project block, and both
  `GET /api/runs` entries (`run_status`, `service.py:297`) and the
  run-detail response carry them; a project-less run's summary stays
  KEY-IDENTICAL to today's (absence, not null — mirroring the state block,
  `state.py:151`–`:157`), and its API status is distinguishable as unbound.
  The path-shaped `workspace` field is untouched: the `primary_root` alias
  and public SCHEMAS doc stay queued to the machine-api milestone (skeleton
  Non-Goals, `skeleton.md:46`–`:49`).
- **Stable local identity.** The executor identity and device value the
  service writes through declare/confirm are non-blank,
  implementation-chosen, and STABLE across service restarts for the same
  home — so reconciles stay version-silent across restarts (I3's victim
  class is exactly version churn that makes no-op operations look like
  material changes). Provenance is non-authoritative (agent_99's design);
  nothing interprets these values locally.

### F. The `run:<run_id>/status` projection

The in-scope `run:*` family gets its writer (skeleton Non-Goals: "in scope
here and must not be left inert", `skeleton.md:50`–`:53`;
`run:<run_id>/digest` stays reserved and is never written):

- **Writer and authority.** The SERVICE is the projection's only writer
  (local-authoritative, goal `:130`–`:135`); the driver's run-critical path
  never writes it, and nothing ever reads it back to drive decisions —
  durable truth stays in `state.json` (skeleton Shared Invariants). Keys
  are written to the bound project's own KV store — the same declared
  service-owned `<base>/<project>` store used by `GET /api/projects` — and
  come from the sealed `KeyBuilder.run_status` (`kvstore.py:142`) in the
  default reserved namespace (`kvstore.py:24`, the single config point).
  Values go through the sealed envelope (`RevisionEnvelopeStore`,
  `kvstore.py:460`). No global, workspace-root, or foreign project store is
  a valid projection authority.
- **Value.** JSON-plain, string-keyed, PATH-FREE (the Brain-boundary
  vocabulary — "project + milestone + attention state … filesystem paths
  never cross", goal `:363`–`:366`): exactly `{run_id, name, project,
  work_area, milestone_status, current_unit, current_unit_status,
  failure_reason}`. Values mirror the run's current summary EXCEPT the
  operator-authored strings that can carry local paths: `name` is a
  path-sanitized display name derived from the summary name, and
  `failure_reason` is null while healthy; when failed, it stores a
  path-sanitized operator-readable reason derived from the summary reason.
  Sanitization replaces absolute path substrings with `<path>` and falls
  back to `run` for `name` or `failure_recorded` for `failure_reason` if the
  result is still not path-free. The raw run name and raw failure reason
  remain only in the service registry/durable state summary/run detail. The
  machine-api milestone may evolve the shape when it builds the digest
  sibling; nothing here pads for it (greenfield).
- **Lifecycle, bounded.** A successful bound launch writes the initial
  value (envelope revision 1). Updates ride the service's existing
  observation paths (the poll's summary refresh, `service.py:148`; the
  guard's periodic scan, `:1055`) and are CHANGE-DRIVEN: an observation
  whose projected value is unchanged writes nothing (the envelope revision
  does not move — I6's "bounded … projection writes"); one that differs
  writes once. Terminal states (failed, closed) reach the store through the
  same paths. Purge-deleting the run (`?purge=1`, `service.py:557`–`:563`)
  tombstones the projection through the sealed envelope delete
  (`kvstore.py:524`; readback `exists?: false`) in that same bound-project
  store; a plain forget leaves the last truthful snapshot and a retained
  delete-guard claim (the run itself still exists on disk).
- **Contained.** Projection writes are visibility, never load-bearing: a
  write failure, whether during the initial launch-time projection or a later
  observation, fails NO launch, poll, or run — the fault surfaces in the
  service log only, and the pump self-heals on the next observation once the
  bound-project store is writable again (the goal's re-pump doctrine,
  `:140`–`:141`). Project-less runs project NOTHING.

## Non-Goals

- **No panel UI.** `orchestrator/static/` is untouched; the standing
  project/work-area cards, the safeguard editor, and displaying the
  resolved project in the launch form are the panel slice's. This slice is
  the API those surfaces call.
- **No policy/safeguard authoring endpoints.** `GET /api/projects` exposes
  policies READ-ONLY through the sealed assembler; put/delete — the
  safeguard editor's API — lands with the editor in the panel slice.
  Policy semantics themselves are sealed (Slices 3/4/6).
- **No digest, no `primary_root` alias, no SCHEMAS doc** — the machine-api
  milestone's (skeleton Non-Goals). The reserved `run:<run_id>/digest` key
  is never written.
- **No CLI binding flags.** The service API is the launch surface binding
  `(project, work_area)`; the CLI keeps its path-based init unchanged.
- **No `unavailable` management, no health monitoring.** Nothing local
  marks work areas unavailable (Slice 2 accepts the status for agent_99
  compatibility); roots are validated at launch time, and Slice 4's
  operational error owns later vanishes.
- **No foreign-store adoption and no multi-base stores.** One
  service-owned base; declared projects are the enumeration source.
  Greenfield: there are no hand-made stores to import (I12).
- **No new KV family, no grammar or namespace change** (I7): defaults
  persist service-side; the projection uses the existing reserved `run:`
  family through the sealed key builder.
- **No semantic changes to sealed modules:** `driver.py`, `workareas.py`,
  `projects.py`, `verifiers.py`, `contracts.py`, `runners.py`,
  `prompts.py`, and `gitops.py` are consumed as-is. `kvstore.py` may gain
  only the public empty-store initializer needed by declaration; the point-KV
  primitives, envelope semantics, key grammar, and codec are unchanged.
- **No mid-run rebinding, no projection-as-truth, no trust-model change**
  (localhost-only, no auth — `service.py:36`–`:38` — unchanged).
- **No migrations, compat shims, or tolerant readers** (greenfield,
  **I12**). Project-less runs are a first-class mode, not legacy data;
  keeping them behavior-identical is scope, not a shim.

## Expected Files

- `orchestrator/service.py` (edit) — the project/work-area endpoints (A/B),
  the launch binding with validation/reconcile and refusal mapping (C/D),
  the run-status handles (E), the projection pump and purge tombstone (F).
- `orchestrator/kvstore.py` (edit, minimal) — a public empty-store
  initializer so project declaration can create a readable zero-entry
  `kv.json` without writing a sentinel key or changing KV semantics.
- `orchestrator/registry.py` (edit, minimal, optional) — the service-home
  projects-record and retained-state helpers, if the implementation keeps
  home-file bookkeeping beside `registry.json`/`recents.json`; keeping them
  in `service.py` is equally acceptable.
- `orchestrator/state.py` (edit, minimal) — `summary` exposes the project
  handles for bound runs (E); project-less summaries key-identical.
- `orchestrator/tests/test_service_projects.py` (new) — the pinning tests:
  the `make_server(home, 0)`-in-a-thread, isolated tempdir home,
  `autostart: false` conventions of `test_service_api.py`; stores seeded
  through the API itself; run states advanced via `MockRunner` through the
  sealed driver where lifecycle observation needs progress (the
  `test_run_init.py` convention).

## Dependencies

- **Slice 2** (`orchestrator/workareas.py`, sealed) — declare/confirm/
  relabel/delete/read/list_records/read_meta/put_meta (`:429`, `:497`,
  `:528`, `:550`, `:378`, `:406`, `:561`, `:565`), the validation
  vocabulary and reason constants (`:45`–`:55`, `:101`, `:111`), the
  `<base>/<slug>` binding (`:372`), the public record/root shapes (`:213`),
  and the sealed meta shape (`:336`).
- **Slice 3** (`orchestrator/projects.py`, sealed) — the assembled read
  model (`ProjectStore.read`, `:267`, fail-closed assembly), the read-only
  policy list (`:204`), and `INVALID_DEFAULTS` (`:32`).
- **Slice 5** (sealed) — `init_run(project=, config_override=)`
  (`driver.py:2204`), `ProjectResolutionError.cause` (`:2082`, built for
  this launcher), the init-specific causes (`:2076`–`:2077`), the state
  project block (`state.py:151`–`:157`), `project_resolved`
  (`driver.py:2285`–`:2296`), and the launch>defaults>built-ins precedence
  (§E) this slice extends with the service rung.
- **Slice 1** (`orchestrator/kvstore.py`, sealed) — the envelope store
  (`:460`) and `KeyBuilder.run_status` (`:142`), `canonical_json_value`
  (`:179`), the default namespace constant (`:24`), and the store-file format
  the empty-store initializer preserves.
- **Slices 4/6** (sealed, context) — slice-06's live standing-law reads fail
  closed if a bound store later loses its KV file (`driver.py:591`–`:595`)
  and make store deletion under a bound run a recorded failure (the delete
  guard's victim); Slice 4's operational error backstops reuse-source roots
  that vanish after validation.
- The existing service/registry machinery this slice extends:
  `create_run`/`ApiError` (`service.py:336`, `:68`), the git gate and
  convention (`:387`–`:406`, `:381`), the attach discipline
  (`:349`–`:358`), the summary cache (`:144`–`:158`) and guard scan
  (`:1033`, `:1055`) as the observation paths, purge (`:557`–`:566`),
  atomic service-home writes (`registry.py:65`–`:76`, `:214`–`:224`),
  the registry lock (`registry.py:79`–`:90`), `gitops.enabled`/`is_repo_root`
  (`gitops.py:58`, `:124`), `merge_config` (`driver.py:143`), `st.summary`
  (`state.py:759`).
- The sealed skeleton (rows 7–8 `skeleton.md:174`–`:175`; sequencing
  "Slices 7 and 8 underpin 9" `:186`–`:187`; the status-family non-goal
  `:50`–`:53`; Tests That Pin `:198`–`:199`) and the pricing-pilot fixture
  (`implementation/brainstorming/project-concept-pricing-pilot.json` —
  **I2** gap evidence `orchestrator/service.py:337`; **I1** launch-flow
  consumer; **I6** frequency/victim; **I3** version behavior; **I7**
  grammar; **I12** greenfield).
- The frozen goal re-read read-only as the contract source: `:43`–`:44`,
  `:61`–`:65`, `:70`, `:74`–`:75`, `:126`–`:141`, `:286`–`:288`,
  `:359`–`:366`.
- Consumers arriving later (not required to land this slice): the panel
  slice (UI over every surface here; the safeguard editor), the
  reuse-audit slice (meta-authored reuse sources feeding audits), the
  machine-api milestone (digest sibling; `primary_root` alias).

## Reuse Posture

- **Checked (this repo):** the whole existing service surface — the launch
  path that still takes `workspace` as a path (`service.py:337`, the I2
  gap), `ApiError` status mapping, the attach discipline, the git gate and
  git-enabled convention, the summary cache and auto-resume guard as the
  only periodic observation loops, purge semantics, the amendments/acts
  files as the operator-owned-document pattern, and registry/recents as the
  service-home persistence precedent; the sealed seams of Slices 1/2/3/5
  and slice-06's bound-store fail-closed behavior (all cited above); confirmed
  nothing anywhere writes `run:<run_id>/status` yet (the key builder from
  Slice 1 has no production caller).
- **Checked (contract source, read-only):** the frozen goal's
  declare/reconcile state machine, storage and authority doctrine,
  deliverable (5), and service-surface lines; fixture I1/I2/I3/I6/I7/I12.
- **Reused / extended:** every agent_99-readable work-area mutation goes
  through Slice 2's sealed store — no parallel raw-record writer, validator,
  or interpreter, so the compatibility surface stays single-source; sibling
  meta cleanup is only an enveloped `work_area_meta:<name>` tombstone in OUR
  family; the project read is Slice 3's assembler verbatim; launch resolution
  and refusal tokens are Slice 5's sealed init and cause vocabulary (no
  parallel resolution, no string-matching); repo-root validation reuses
  `gitops.is_repo_root` — the same predicate as today's launch gate; config
  precedence reuses `merge_config` as the single merge source; the projection
  uses Slice 1's envelope over the sealed key builder (no hand-assembled keys,
  mirroring slice-03's discipline); project declaration uses a public
  empty-store initializer rather than a sentinel key or a private store-file
  write; defaults persistence and the new endpoints reuse the service's
  existing atomic-file, lock, handler, and error patterns.
- **No new agent_99-readable shape:** the only agent_99-native records this
  slice touches (work areas) are written by sealed Slice 2 code; the
  projection is OUR enveloped family; stores open with the default reserved
  namespace (single config point, I7).
- **New machinery, and why (the priced gaps, not parallels):** the endpoint
  layer (I2's gap — no project addressing exists in the API); the
  service-home projects record (defaults need a persisted, grammar-legal
  home — sealed slice-03 §E and slice-05 §E both name this slice); the
  launch validation set (the reconcile's concrete checks); the projection
  pump (the I6 writer that does not exist); the summary handles (goal
  `:361`). None duplicates an existing facility.

## Proportionality (amendment A1)

The CRUD surface, `GET /api/projects`, declare → pending / reconcile →
ready, the launch binding, the status projection, and run status carrying
the project name are pinned by I1/I2/I6 and the frozen goal — not
re-derived. New mechanism beyond the pinned invariants, one line each:

- **Service-home projects record (A).** VICTIM: the operator and every
  bound launch — without it, defaults die with the service process (sealed
  slice-03/05 both name this slice as their persister) and
  `GET /api/projects` has no total enumeration source; a KV home is barred
  by the frozen grammar (I7). COST: one small operator-owned JSON document
  plus reuse of the existing atomic-write/lock helpers.
- **Empty-store initializer (A).** VICTIM: the operator managing a newly
  declared, policy-empty project — without a readable zero-entry KV file,
  the project surface cannot distinguish an intentionally empty project from
  a lost store after restart or during fail-closed reads. COST: one public
  helper over the existing store format plus a focused materialization test.
- **Launcher validation set (C.2).** VICTIM: the operator — a work area
  confirmed `ready` without real-filesystem validation runs milestones
  against nonexistent or misdeclared roots (the I2 victim: a repo path
  mistaken for the boundary; slice-05 §B explicitly left additional-root
  existence to this check). COST: existence checks plus the existing
  repo-root predicate, per launch.
- **Service git-enabled convention placement (D).** VICTIM: the operator
  using project defaults for standing pure-state launches, and the operator
  with no defaults who still expects panel launches to keep today's repo-root
  safety. COST: one existing config merge folded into binding defaults; no new
  config surface.
- **Stable executor/device identity (E).** VICTIM: fusion-facing consumers
  and the operator — an unstable identity would bump the domain version on
  every relaunch, making no-op reconciles look like material changes (I3's
  pinned victim class). COST: one derived constant.
- **Change-driven projection pump on existing observation paths (F).**
  VICTIM: the future Brain/other-device mirror (fixture I6 victim: "loses
  projected run visibility") and the skeleton's own non-goal line — without
  a writer the family ships inert. A driver-side writer was rejected: a
  projection-store hiccup must never fail a run. COST: one value builder,
  a change compare, and an envelope put; no new loop, thread, or cache.
- **Projection display-string sanitization (F).** VICTIM: the future
  Brain/other-device mirror — operator-supplied run names and durable failure
  reasons may include local filesystem paths, so raw mirroring would violate
  the path-free boundary. COST: one projection-only string sanitizer plus
  two tests.
- **Per-project error markers in the listing (A).** VICTIM: the operator
  with one corrupt store, who would otherwise lose the whole project
  surface — and not SEE the corruption; fail-closed stays per-project.
  COST: an error-entry shape in the listing.
- **Guarded project delete (A).** VICTIM: the operator — an unguarded
  delete destroys standing law and strands bound runs in slice-06's
  fail-closed failure with an unrepairable store; an unreadable registered
  or retained plain-forgotten state is the same harm because the service
  cannot prove it is unbound. COST: live descriptor/policy/run pre-checks
  plus one retained-state claim on plain forget.
- **Meta authoring endpoints (B).** VICTIM: slice-06's rendered roles and
  the reuse-audit slice — without an authoring surface `reuse_sources` is
  dead config no operator can create, and without a live-record guard/clear a
  deleted or re-declared name can carry stale roles into project context.
  COST: two thin endpoints over the sealed read/put, one live-record read
  before meta get/put, and a meta tombstone on work-area delete.
- **Summary project handles (E).** VICTIM: the panel slice and the pump
  (both read summaries), and the goal's pinned "run status carries the
  project name". COST: two additive keys for bound runs.

Nothing is SPECULATIVE and nothing requires operator approval. Deliberately
NOT built, with reasons: policy-authoring endpoints (the safeguard editor's
API ships with the editor — panel slice); `unavailable` transitions and
background revalidation (no local consumer; launch-time validation plus
Slice 4's operational error own the failure); a projection for project-less
runs (no store exists to hold one); a project rename/move surface (slugs
are identity; greenfield, nothing to migrate); multi-base stores and
foreign-store import (one base keeps `(project, work_area)` unambiguous;
no foreign data exists).

## Acceptance Criteria

1. **Project lifecycle + `GET /api/projects` (I2).** Creating a project
   with a valid slug, including a slug containing spaces addressed
   URL-encoded, makes `GET /api/projects` list it with the assembled
   record (`work_areas: []`, `policy: []`, plus `defaults` when supplied);
   the single-project read shows the same shape; an invalid slug refuses
   400-class with `invalid_project`; a duplicate create refuses as a
   conflict without changing defaults; updating defaults through
   `POST /api/projects/<slug>` replaces them, null clears them, invalid
   values refuse with `invalid_defaults`, and read/update/delete/nested routes
   against a valid undeclared slug refuse 404-class with `unknown_project`;
   declaration creates a readable zero-entry KV file for the project; after a
   service restart (a new server over the same home) the project and its
   defaults are intact.
2. **Per-project fail-closed listing.** With one project's KV file
   corrupted or missing/unreadable after declaration, `GET /api/projects`
   still lists the healthy projects and yields an error entry (no partial
   record) for the broken one; its single read fails closed with the reason.
3. **Work-area CRUD through the sealed store (I3/I5 at the surface).**
   Declare returns the full public domain at version 1 `pending`;
   re-declaring different roots yields version 2 `pending`; identical
   re-declare changes nothing; relabel changes `display_name` and
   PRESERVES the version; delete makes the name read/list as unknown and
   makes any sibling meta absent; re-declaring the same name does not
   resurrect old meta; invalid inputs (bad name, relative path, duplicate root)
   refuse 400-class with the sealed reason verbatim; a name with spaces
   round-trips URL-encoded.
4. **Meta beside the record.** Posting the raw sealed meta body
   `{reuse_sources: [{root, inventory, registry, consumption}]}` reads back
   as `{"meta": {reuse_sources: [...]}}` and beside the work-area record
   (never inside it) in project reads; a
   malformed meta value refuses 400-class; absent meta is not an error;
   get/put for unknown or tombstoned names refuses 404-class, and a malformed
   underlying work-area record refuses 5xx-class.
5. **Launch reconcile happy path (I1/I2/I3).** With a declared `pending`
   work area whose primary is a git repo root: `POST /api/runs
   {project, work_area, goal…}` succeeds; the record is now `ready` at
   exactly version 2; the run's workspace equals `primary.path`; the state
   carries Slice 5's project block and exactly one `project_resolved`; the
   response and `GET /api/runs` carry `{project, work_area}`; and the run
   is drivable (a `MockRunner` step executes — proving the work-area-backed
   store satisfies the driver's standing-law reads).
6. **Reconcile idempotency + stable identity (I3).** After purging the
   first run, relaunching the SAME ready work area — from a fresh service
   instance over the same home — succeeds with the work-area version
   UNCHANGED (same-identity re-confirm is version-silent).
7. **Validation refusals create nothing.** A missing primary directory, a
   non-repo primary (git enabled), and a missing additional root each
   refuse 400-class with a machine-readable reason, leave the record's
   status UNCHANGED, and leave NO state file, no registry entry, and no
   projection entry; an undeclared project, an unknown or tombstoned work
   area, and a corrupted work-area record all refuse 400-class through
   `ProjectResolutionError`, with the cause token (`unknown_work_area` or
   `malformed_work_area`) verbatim; attach combined with a binding refuses
   400-class; a supplied workspace ≠ `primary.path` refuses with
   `workspace_mismatch` verbatim; a state-exists launch stays 409 with the
   attach hint; confirm failures such as `descriptor_mismatch` and `conflict`
   return the sealed token with B's mapping and create no state file, registry
   entry, or projection entry (the prior truthful `ready` transition may
   persist).
8. **Config precedence (D).** A project default `{"git": {"enabled":
   false}}` launches a pure-state bound run whose validation skips the
   repo-root check (a non-repo primary launches); an explicit launch
   `{"git": {"enabled": true}}` restores the gate; a `docs_dir` default
   applies to the resolved docs dir and a launch-supplied `docs_dir` wins
   over it; with no defaults the service git-enabled convention still applies
   above `DEFAULT_CONFIG`, so a non-repo primary refuses unless launch config
   disables git.
9. **Projection lifecycle (I6).** After a bound launch, the bound project's
   KV store — and no other declared project or service-level KV — contains
   `run:<run_id>/status` at envelope revision 1 with EXACTLY
   `{run_id, name, project, work_area, milestone_status, current_unit,
   current_unit_status, failure_reason}`, JSON-plain and path-free, with all
   fields other than `name` and `failure_reason` matching the run's summary; a
   launch whose raw name contains an absolute path stores only the
   path-sanitized display `name`; advancing the run (`MockRunner`) then one
   service observation (a poll or a guard scan) updates the value at revision
   2; repeated observations without change do not move the revision; a
   recorded failure mirrors into the path-sanitized `failure_reason` and never
   leaks a raw absolute path; purge tombstones the projection in that same
   bound-project store (`exists?: false`) while a plain forget leaves the last
   snapshot; a failed initial projection write does not fail the bound launch;
   removing the bound-project store makes observations log-and-continue (the
   poll still answers) and the pump self-heals once the store is restored.
10. **Run status carries the project (goal `:361`).** `GET /api/runs`
    entries and the run-detail summary carry both handles for a bound run
    (including one adopted via attach); a project-less run is reported
    unbound and its summary document is key-identical to today's.
11. **Guarded delete.** Project delete refuses as a conflict with a live
    work area, with a live policy, while a registered run binds the
    project, while any registered run has an unreadable state that cannot
    be proven unbound, and while a plain-forgotten retained state still
    binds the project or is unreadable; once work areas are deleted
    (tombstones remain), policies are removed, and bound states are purged
    or readable unbound, delete succeeds, the project leaves
    `GET /api/projects`, and re-declaring the same slug starts empty (no old
    defaults, policies, or work areas resurrect).
12. **Additivity / project-less inertness.** Project-less
    create/start/stop/resume/delete behavior is unchanged; a project-less
    launch performs zero KV access and creates no project store base; the
    entire pre-existing test suite passes unmodified.
13. **Suite green.** `python3 -m unittest discover -s orchestrator/tests
    -t .` passes.

## Tests / Verification

In `orchestrator/tests/test_service_projects.py` (standard library only;
threaded `make_server(home, 0)` with an isolated tempdir home and
`autostart: false` throughout, per `test_service_api.py`; bound states
advanced via the sealed driver over `MockRunner` where lifecycle needs
progress, per `test_run_init.py`):

- **Project surface** — create/list/read/defaults round-trip, update and
  clear defaults, invalid defaults, invalid slug, valid URL-encoded slug with
  spaces, unknown-project 404s for project-bound routes, duplicate conflict
  without mutation, readable zero-entry KV materialization, restart
  persistence (AC1); the corrupt and missing/unreadable-store error marker
  beside healthy projects (AC2); the guarded-delete matrix, including unreadable
  registered run state, plain-forgotten retained state, and empty re-declare
  after delete (AC11).
- **Work areas** — the CRUD matrix at the surface: declare/re-declare/
  relabel/delete with version observations, sealed-reason mapping,
  URL-encoded names, meta absence on delete, and no stale-meta resurrection on
  re-declare (AC3); raw meta-body put/get beside the record, malformed
  refusal, and unknown/tombstoned/malformed-record meta refusals (AC4).
- **API contract** — every project/work-area route above is exercised with
  its pinned verb, request shape, top-level envelope, and URL-encoded
  project-slug/name handling (AC1-AC4, AC11).
- **Launch flow** — the happy path through ready-at-version-2, the state
  block, the single event, the handles, and MockRunner drivability (AC5);
  purge-then-relaunch version silence across a service restart (AC6); the
  full refusal matrix with nothing-created postconditions, the corrupt-record
  400-class `ProjectResolutionError` case, confirm
  `descriptor_mismatch`/`conflict`, and verbatim cause tokens (AC7).
- **Precedence** — the git-convention/default/launch matrix and the
  docs_dir default-vs-launch pair (AC8).
- **Projection** — initial write, exact key set and path-free values,
  bound-project store identity with non-bound stores empty, path-sanitized
  launch name, change-driven revision movement and no-change stability,
  sanitized failure mirroring including a raw path-containing failure, purge
  tombstone vs forget, contained initial-write and observation-write failures,
  and self-healing (AC9).
- **Status handles and inertness** — bound and attached runs carrying the
  handles; project-less summary key-identity and zero-KV launches (AC10,
  AC12); the pre-existing suite as the regression body (AC12, AC13).

Full slice verification: `python3 -m unittest discover -s orchestrator/tests
-t .` (AC13).

## Risks

- **Confirming without validating (or validating request-supplied roots
  instead of the stored descriptor)** would mark descriptors `ready` that
  no executor-equivalent ever checked — runs against misdeclared universes,
  the exact class of failure this milestone exists to prevent. The AC5/AC7
  gates are load-bearing.
- **Making the run or the launch depend on projection writes** would turn a
  visibility mirror load-bearing, inverting the durable-truth invariant;
  conversely a projection nobody writes ships the family inert against the
  skeleton's explicit non-goal. The AC9 containment and lifecycle tests are
  load-bearing.
- **Unstable executor/device identity** would bump work-area versions on
  every relaunch, corrupting the fusion-facing version semantics (I3) and
  flooding diffs with phantom changes. The AC6 restart test is
  load-bearing.
- **A parallel merge, resolution, or git predicate** (instead of
  `merge_config`, the sealed init seam, and `gitops.is_repo_root`) would
  fork sealed semantics — the duplication failure the milestone targets.
  Reuse Posture plus AC7/AC8 guard this.
- **Persisting defaults in a new KV family** would break the frozen closed
  key grammar (I7) and the fusion namespace pump. Non-Goals and AC1's
  restart persistence (service-side) guard this.
- **Failing the whole listing over one corrupt store** would take the
  operator's entire project surface hostage to one bad file; **repairing or
  partially rendering it** would violate fail-closed greenfield reads
  (I12). The AC2 marker test is load-bearing.
- **Unguarded project delete** destroys standing law under bound,
  plain-forgotten-but-attachable, or unreadable-possibly-bound runs
  (slice-06 turns missing law into an unrepairable recorded failure) and
  silently discards policies. The AC11 matrix is load-bearing.
- **Reading the projection back as truth** (any decision path consuming
  `run:*` values) would make a wipeable descriptor store load-bearing,
  contradicting the wipe-safety doctrine. Contract F's write-only posture
  and the AC9 tombstone/self-heal cases guard this.
- **Raw operator-authored strings in the projection** would leak local
  filesystem paths across the Brain boundary even though durable service
  state still keeps the full operator-facing name and failure reason.
  Contract F's sanitized `name`/`failure_reason` and AC9's path-containing
  launch-name and failure cases guard this.
- **Breaking project-less launches** (required binding keys, non-additive
  status shapes, KV access on unbound paths) would strand every existing
  run including this milestone's own. The AC12 inertness tests and the
  unmodified pre-existing suite are load-bearing.
- **String-matched refusals** (instead of the sealed cause/reason tokens
  riding verbatim) would leave the panel slice parsing prose — the exact
  failure slice-05's error seam was built to prevent. The AC3/AC7 token
  assertions are load-bearing.

## Line budget

Expected to EXCEED the ~500 changed-line target, for a recorded structural
reason: the run ledger binds skeleton rows 7 AND 8 into this single unit
(the title's "CRUD + launch binding"), so two priced gaps land together —
the I2 service addressing surface and the I1 launch half with its
I6-governed projection — and the skeleton's own non-goal forbids shipping
the status family inert (`skeleton.md:50`–`:53`) while the ledger has no
later pre-panel slice to host it. Production code stays thin over sealed
seams (endpoints, one validation set, one pump, two summary keys); as in
Slices 1–6 the pinning tests — the CRUD and refusal matrices, the
precedence matrix, the projection lifecycle, and the inertness sweeps that
the panel slice and the fusion story depend on — carry the bulk.
