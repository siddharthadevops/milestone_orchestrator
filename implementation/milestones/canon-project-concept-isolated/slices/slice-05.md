# Slice 05 — Run-Init Project Resolution + `project_resolved`

Status: draft — pending review.

Milestone: canon-project-concept-isolated. This slice makes runs
**project-addressed**: a run can be initialized against a `(project, work_area)`
binding instead of a bare directory path, resolving its membership ONCE at init
through the sealed work-area store — `primary.path` becomes the repo the driver
owns and executes in, the additional roots become the run's recorded read-only
grants, and the ledger records `project_resolved {project, work_area}` exactly
once. It pins fixture invariant **I1**'s resolution half (today `state.py:125`
stores one workspace path — the I1 `ecosystem_equivalent: gap`) and supplies
exactly what slice-04.md scoped to it: "the resolved `(project, work_area)` and
roots that Slice 6 consumes." The other half of I1 — "show workers standing
safeguards" — is Slice 6's (PROJECT CONTEXT + `project_safeguard_seen`, fixture
I10); the service launch surface that binds `(project, work_area)` end-to-end
and projects `run:<run_id>/status` is Slice 8's.

This slice touches the run-init path of existing production code
(`driver.py:1849` `init_run`, `state.py:113` `new_state`) with the same posture
Slice 4 established for `call_worker`: **inert until bound**. Without a project
binding, init is byte-identical to today — same state document, no new events,
no store access — because every existing run (including this milestone's own
bootstrap runs) is project-less and must stay first-class.

The compatibility target is the frozen goal contract
(`implementation/brainstorming/project-concept.md`, frozen at `45f6968`), read
read-only: the launch shape ("A run launches against `(project, work_area)`:
**primary.path** is the git repo the driver owns and executes in; **additional**
roots are read-only grants", `:61`–`:63`), the resolve-at-init rule
("Workspaces resolve their project membership at run init", `:44`), and the
frozen ledger-event shape (`project_resolved {project, work_area}` once at run
init, `:254`). Those shapes are adopted verbatim, never re-derived. The refusal
semantics, the state seam, and the defaults precedence below are this slice's
design, consistent with I1 and pinned by tests.

## Scope (observable contracts)

Five contracts. Each statement is falsifiable by a named test, not by reading
the diff. Concrete identifiers are illustrative and the implementation's choice;
the pinned content is the init seam's observable behavior, the state block shape
(the cross-slice seam Slices 6 and 8 read), the frozen event payload, the
refusal semantics Slice 8 maps to launch errors, and the defaults precedence.
Where resolution code lives (in `driver`, `state`, or a helper beside
`projects`) is the implementation's choice.

### A. The project binding and read-only resolution at init

The init seam (`driver.init_run`, the entry point the CLI, the service, and
tests already share) gains an OPTIONAL project binding carrying:

- the **store directory** — the service-level backing directory under which
  each project opens its `<base>/<slug>` KV (Slice 2's binding,
  `workareas.py:372`), recorded as an absolute path;
- the **project** slug and **work-area** name — the stable path-free handles
  (goal §Convergence design rule 2), validated by Slice 2's vocabulary
  (`validate_project_slug`, `workareas.py:101`; `validate_name`, `:111`);
- optionally **defaults** (E).

When the binding is present, init resolves the named work area through
Slice 2's sealed READY-gated seam (`WorkAreaStore.resolve`, `workareas.py:393`):
the work area must exist, interpret as a live agent_99-domain record, and have
`status: "ready"` — the executor-confirmed signal the launcher's validation
reconciles to (goal `:127`–`:129`; that reconcile flow is Slice 7's, and
Slice 2's `confirm` already provides the transition for tests). A pending or
unavailable work area is refused (D), never silently accepted and never
reconciled by init itself.

**Resolution is read-only.** A successful project-bound init writes NO KV
entry (nothing created, changed, or tombstoned): the work-area record
(including its domain `version`), the meta family, and every other store
entry are byte-unchanged afterwards.
`project_resolved` is a run-ledger event in `state.json`, not a datastore
write (skeleton Shared Invariants: durable truth never lives in the datastore).

### B. `primary.path` is the executed repo; grants are recorded in state

- **Workspace derivation.** For a project-bound init the run's `workspace` IS
  the resolved work area's `primary.path`. A binding without a workspace
  argument derives it; a binding WITH a workspace argument is cross-checked by
  strict equality against `primary.path` (the record's path domain is already
  canonical-absolute — Slice 2) and refused on mismatch. No looser (symlink-
  resolving) comparison is attempted: ambiguity refuses, mirroring Slice 4's
  ambiguity posture. This is the guard against the I2 naming-collision harm —
  "a repo path mistaken for the workspace/policy boundary" — without building
  the `primary_root` alias (a non-goal queued to the machine-api milestone).
- **No invented directories.** Project-bound init requires `primary.path` to
  exist as a directory and refuses otherwise; it never fabricates the executed
  repo (the project-less path keeps today's `makedirs` behavior unchanged).
  Additional-root existence is deliberately NOT checked at init: validating
  roots is the launcher-validation duty (Slice 7), and a missing reuse-source
  directory already surfaces as Slice 4's distinct operational error at check
  time.
- **The state block (the seam Slices 6 and 8 consume).** A project-bound
  state document carries a project block with exactly
  `{directory, project, work_area, primary, additional}`: the absolute store
  directory, the two handles, and the resolved roots VERBATIM in Slice 2's
  public root shape (`{path, device}`, `workareas.py:213`). The block is
  ABSENT for a project-less run (not present-null), so a project-less state
  document gains no new key. `device` rides along verbatim; nothing
  interprets it locally (provenance is non-authoritative in agent_99 by
  design). Recording the store directory in state is what lets a later worker
  call reopen the project's stores (Slice 6 reads policies live per call,
  exactly as amendments are re-read, `driver.py:525`) from a driver that only
  has `state.json`; it is machine-local in the same way and trust domain as
  the existing absolute `workspace` field.
- **Resolution is once-per-run and stable.** Like `docs_dir` ("resolved once
  at init and stable for the run's life", `state.py:127`), the recorded
  binding and roots never change after init: editing, relabeling, declaring
  and confirming a replacement descriptor to READY, or deleting the work area
  in the store mid-run does not rebind a live run, change its workspace, or
  alter its recorded grants.
  Slice 6 must take the run's grant roots FROM this block (the fixed universe
  its verifier containment quantifies over, via `path_is_inside_roots`,
  `kvstore.py:596`), while the prompt's ecosystem map and policies may be read
  live from the stores.
- **Read-only grants bind at the contract layer, not the filesystem.** The
  additional roots are recorded so Slice 4's checks and Slice 6's context can
  grant and confine against them; the existing prompt ACCESS rule already
  scopes worker edits to the workspace (`prompts.py:58`), and no
  mount/permission enforcement is added (Non-Goals).

### C. The `project_resolved` ledger event (frozen shape)

- A project-bound init appends `project_resolved` with payload exactly
  `{project, work_area}` — the frozen contract (`project-concept.md:254`;
  fixture I10 frequency: "Once at run init for project resolution") — plus the
  `seq/at/type` envelope every event carries (`state.py:286`).
- **Exactly once per run, at init.** The event is present in the state as
  first persisted by init and is never appended again: driver construction,
  steps, failures, and a `resume_run` cycle add no second `project_resolved`.
  Exactly-once holds by the same construction that makes init itself
  exactly-once (`state.save_new`'s exclusive claim, `state.py:239`) plus the
  driver never re-resolving (B).
- A project-less run records ZERO `project_resolved` events.

### D. Refusals: init fails closed, creating nothing

A binding that cannot be resolved refuses the init: NO state file is created,
no KV entry is written, and there is nothing to resume — the operator gets
the reason at launch time (the same fail-loudly-to-the-operator posture as
Slice 4's config-error class). Refusal causes, each observably distinct:

- invalid project slug or work-area name (Slice 2's validation vocabulary,
  reused — `invalid_project`, `invalid_name`);
- unknown work area: never declared, tombstoned, or a store directory that
  does not exist or holds no such record (`unknown_work_area`);
- malformed stored record (`malformed_work_area` — fail-closed, no repair,
  greenfield I12);
- work area not ready — `pending` or `unavailable` (`work_area_not_ready`);
- `primary.path` not an existing directory;
- supplied workspace ≠ `primary.path`;
- invalid `defaults` (E).

Refusals raise ONE dedicated, catchable error type (illustratively
`ProjectResolutionError`) carrying the cause — distinct from `FileExistsError`
(state already exists, unchanged) — so Slice 8's launcher can map project
refusals to 400-class API errors without string-matching. Where the cause is a
Slice 2 validation or read failure, the refusal reuses Slice 2's reason
vocabulary verbatim rather than minting parallel names; the init-specific
causes (workspace mismatch, missing primary directory, invalid defaults) name
their cause distinctly. Exact message text is the implementation's choice;
distinctness of cause is the contract.

### E. Project defaults apply at init, beneath operator intent

The binding may carry `defaults` — the project record's optional
acts/model/docs_dir conventions (goal `:70`; stored shape and validation
pattern from Slice 3 §E, which named run-init as this field's consumer). Since
no persisted defaults surface exists until Slice 7, defaults arrive
CALLER-SUPPLIED through the binding (Slice 8's launcher will pass the persisted
ones), and this slice pins only their application:

- **Domain.** `defaults` must be a JSON-plain object in the config-override
  domain (validated like Slice 3's assembler input: an object accepted by
  `kvstore.canonical_json_value`, `kvstore.py:179`); anything else refuses
  (D). Inner keys are NOT allowlisted: defaults are operator-authored
  configuration in the same trust domain as the `--config` file.
- **Precedence, observable in the effective run config:** an option the
  launch sets explicitly wins over the project default; a project default
  wins over the built-in `DEFAULT_CONFIG`. Merge semantics are
  `driver.merge_config`'s (`driver.py:142`) — the single existing source
  (one level deep, dict values key-wise) — applied in that order; no second
  merge function is introduced. A project-default `docs_dir` therefore
  participates in init's docs-dir resolution and slug uniquification exactly
  as a config-file `docs_dir` does today.
- **Inert when absent:** no `defaults` ⇒ the effective config is exactly
  today's. To make the precedence orderable, the init seam takes the launch's
  own override distinguishably from the already-merged config (parameter
  shape is the implementation's choice; the pinned contract is the
  precedence, and it binds only the project-bound path — the CLI carries no
  binding).

This mirrors the milestone's precedence doctrine at the config layer:
run-scoped operator intent WINS over standing project law (skeleton Shared
Invariants — amendments over safeguards; here launch config over project
defaults).

## Non-Goals

- **No PROJECT CONTEXT block, no safeguard selection, no
  `project_safeguard_seen`.** Rendering the ecosystem map + in-scope safeguards
  at operator-amendment authority and recording what workers saw is Slice 6
  (I10). This slice records the binding those calls will consume.
- **No policy reads or validation at init.** Init resolves membership only; a
  malformed or vocabulary-illegal policy surfaces as Slice 4's config error at
  enforcement time. Failing init on a policy whose scope a run may never touch
  would block launches for nothing.
- **No service or panel surface.** Project/work-area CRUD endpoints and the
  reconcile-to-ready launcher validation are Slice 7; binding a LAUNCH to
  `(project, work_area)` (`service.py:336` still takes `workspace` as a path —
  the I2 gap), the `run:<run_id>/status` projection, and the project name in
  run status are Slice 8; the panel is Slice 9. This slice adds no endpoint,
  writes no KV entry, and leaves `state.summary` untouched.
- **No CLI binding flags.** The operator-facing launch surface that binds
  `(project, work_area)` is Slice 8's; a second, weaker CLI surface now would
  duplicate it. The init seam itself is callable (tests; Slice 8).
- **No work-area mutation at init.** Init never declares, confirms, relabels,
  or deletes; `pending → ready` reconciliation is the launcher validation
  (Slice 7) over Slice 2's sealed transitions.
- **No mid-run re-resolution or rebinding**, and **no device matching** (no
  local device-identity concept exists; agent_99 treats provenance as
  non-authoritative).
- **No filesystem read-only enforcement** of additional roots (no mounts,
  permissions, or sandboxing): grants bind through the contract layer
  (Slice 4 containment) and prompt ACCESS scope, per the goal's non-goals.
- **No `primary_root` API alias or SCHEMAS doc** — queued to the machine-api
  milestone (skeleton Non-Goals); B's strict workspace≡primary.path check is
  the in-scope guard.
- **No migrations, compat shims, or tolerant readers** (greenfield, **I12**).
  Project-less runs are not "legacy data" — they are a first-class mode this
  repo's own runs use; keeping them byte-identical is scope, not a shim. No
  state `schema_version` bump: the block is additive and absent when unbound,
  and existing states keep loading unchanged.

## Expected Files

- `orchestrator/driver.py` (edit) — `init_run` gains the optional project
  binding: resolution through Slice 2's store, the refusal error type and
  causes (D), workspace derivation/cross-check (B), defaults precedence (E),
  and the `project_resolved` append (C). `cmd_init` and all existing callers
  are unchanged.
- `orchestrator/state.py` (edit, minimal) — `new_state` carries the optional
  resolved project block (B); absent when unbound. `summary` untouched
  (Slice 8).
- `orchestrator/projects.py` or a sibling (optional edit) — a resolution
  helper beside the stores if the implementation prefers; a finer split is the
  implementation's choice.
- `orchestrator/tests/test_run_init.py` (new) — the pinning tests (standard
  library `unittest`; stores in `tempfile.TemporaryDirectory`, matching the
  repo convention), driving `init_run` and, for the exactly-once/stability
  contracts, the driver over `MockRunner`.

## Dependencies

- **Slice 2** (`orchestrator/workareas.py`, sealed) — the resolution seam this
  slice consumes verbatim: `WorkAreaStore.resolve` (`:393`, READY-gated at
  `:397`), the validation vocabulary (`validate_project_slug` `:101`,
  `validate_name` `:111`) and reason constants (`:45`–`:55`), the
  `<base>/<slug>` project binding (`:372`), the public root shape (`:213`),
  and `confirm` (`:497`) so tests can reach `ready` without Slice 7.
- **Slice 1** (`orchestrator/kvstore.py`, sealed) — the storage beneath
  Slice 2 (skeleton sequencing: "Slice 1 underpins all storage (2, 3, 5, 7,
  8)") and `canonical_json_value` (`:179`) for the defaults domain check.
- **Slice 3** (`orchestrator/projects.py`, sealed) — context, not a code
  dependency: its §E pinned the `defaults` field shape-free and named
  "run-init defaults in Slice 5" as the consumer; this slice honors that
  forecast through the binding (E). The whole-project assembler
  (`projects.py:267`) is deliberately NOT consumed here (see Reuse Posture).
- The existing init/state machinery this slice extends: `driver.init_run`
  (`driver.py:1849`), `st.new_state` (`state.py:113`), `append_event`
  (`:286`), `save_new`'s exclusive claim (`:239`), `merge_config`
  (`driver.py:142`), and the amendments precedent for ledgered worker
  knowledge (`driver.py:525`, `amendment_seen` at `:552`).
- The sealed skeleton (Slices row 5 at `skeleton.md:172`; Sequencing "Slice 5
  underpins 6 and 8" `:186`; Tests That Pin `:199`) and the pricing-pilot
  fixture (`implementation/brainstorming/project-concept-pricing-pilot.json`,
  **I1** `priced_ok`, gap evidence `orchestrator/state.py:125`; **I10**
  frequency for the event; **I2** victim for the workspace-naming guard).
- The frozen goal re-read read-only as the contract source:
  `project-concept.md:44`, `:61`–`:63`, `:70`, `:127`–`:129`, `:254`.
- Consumers arriving later (not required to land this slice): Slice 6 (grant
  roots + store handles from the state block; the event's sibling
  `project_safeguard_seen`), Slice 7 (the reconcile flow that produces
  `ready` in production), Slice 8 (launch binding calling this seam; status
  projection; refusal→400 mapping).

## Reuse Posture

- **Checked (this repo):** run identity today is one workspace path
  (`state.py:125`, the I1 gap; `service.py:336` launches by path — the I2
  gap); init flow and its exactly-once claim (`driver.py:1849`,
  `state.py:239`); the amendments pattern for standing-law plumbing
  (`driver.py:525`); config merge single source (`driver.py:142`); the
  docs_dir resolved-once precedent (`state.py:127`); Slice 2's
  `resolve`/`confirm`/validation seams and Slice 3's assembler + defaults
  validation as candidate reuse.
- **Checked (contract source, read-only):** the frozen goal's launch shape,
  resolve-at-init rule, ledger-event shape, and defaults field (`:44`,
  `:61`–`:63`, `:70`, `:254`); fixture I1/I10/I2.
- **Reused / extended:** resolution consumes Slice 2's sealed READY-gated
  `resolve` verbatim — no parallel work-area reader, interpreter, or status
  logic is written; slug/name validation and refusal reasons reuse Slice 2's
  vocabulary; the defaults domain check reuses `canonical_json_value`
  (mirroring Slice 3's assembler validation); precedence reuses
  `merge_config` as the single merge source; the event rides the existing
  append-only event ledger (`append_event`), mirroring `amendment_seen`'s
  worker-knowledge doctrine; exactly-once leans on `save_new`'s existing
  exclusive claim rather than any new guard.
- **Deliberately not consumed:** Slice 3's whole-project assembler
  (`projects.py:267`). Init needs ONE work area by name, READY-gated —
  exactly `resolve`'s contract; the assembler lists every work area and
  every policy and would drag policy reads into init (a non-goal). The
  assembler's consumers remain the display flows (Slices 7/9), and slice-03's
  defaults forecast is honored via the binding instead, consistent with its
  own "authored and persisted by the service/panel in Slices 7/9".
- **New machinery, and why (the I1 gap, not a parallel):** the binding
  parameter and refusal class on the init seam; the state project block; the
  event append; the ordered defaults merge. None of this exists today
  (`state.py:125` knows a single path; no caller can address a run by
  `(project, work_area)`).
- **Compatibility:** the handles recorded (project slug + work-area name) are
  the stable path-free vocabulary the future agent_99 adapter/Brain uses
  (goal §Convergence rule 2); the roots are recorded in Slice 2's public
  shape, so nothing re-derives the agent_99 domain; no KV write at init and
  no new key family means the frozen grammar (I7) and every store contract
  are untouched; project-less behavior is byte-identical, so every existing
  consumer of `state.json` is unaffected.

## Proportionality (amendment A1)

Resolution at init, the frozen event, `primary.path` as the executed repo, and
read-only additional grants are pinned by **I1**/I10 and not re-derived. New
mechanism beyond those invariants, with victims:

- **The state project block (B), beyond the bare event.** VICTIM: Slice 6
  (per-call safeguard selection and verifier containment need the store
  location and the run's FIXED grant roots — slice-04.md pins that Slice 5
  "supplies the resolved `(project, work_area)` and roots") and Slice 8 (the
  status projection needs the handles); without it a driver holding only
  `state.json` cannot reach the project's stores or know its grant universe.
  COST: one optional state field written once at init; no new subsystem, no
  schema bump.
- **The dedicated refusal error type (D).** VICTIM: Slice 8's launcher (maps
  project refusals to 400-class errors; without a type it string-matches or
  500s) and the operator (a precise launch-time reason instead of a
  half-created run). COST: one exception class and its raise sites.
- **Workspace derivation, strict mismatch refusal, and the
  primary-must-exist check (B).** VICTIM: the operator — the I2 victim
  ("harmed if a repo path is mistaken for the workspace/policy boundary");
  today's `makedirs` would otherwise fabricate a missing `primary.path` and
  run a milestone in an invented empty directory. COST: one equality check
  and one `isdir` check replacing `makedirs` on the bound path only.
- **Defaults application at init (E).** VICTIM: the operator (standing
  project conventions — acts/model/docs_dir — re-typed on every launch is
  exactly the per-run-vs-standing gap this milestone exists to close) and
  Slice 8 (which would otherwise have to invent the application point);
  sealed slice-03 §E names run-init as this field's consumer, so omitting it
  would leave the project record's `defaults` dead config with no owner in
  the milestone. COST: one ordered `merge_config` application plus a
  JSON-plain object check reusing Slice 1.

Nothing is SPECULATIVE and nothing requires operator approval. Deliberately
NOT built, with reasons: CLI binding flags (Slice 8 owns the launch surface);
work-area `version` snapshot in the state block (no consumer judges runs by
work-area version; safeguard versions — which ARE judged — ride
`project_safeguard_seen` in Slice 6); device matching (no local
device-identity concept; provenance non-authoritative); additional-root
existence checks at init (the launcher validation and Slice 4's operational
error already own that failure); mid-run rebinding (would silently change the
grant universe rounds were judged under).

## Acceptance Criteria

1. **Project-bound init happy path (I1).** Against a store holding a READY
   work area, init with `{directory, project, work_area}` creates a state
   whose `workspace` equals the work area's `primary.path`; the state carries
   the project block with exactly `{directory, project, work_area, primary,
   additional}`, the roots verbatim in Slice 2's public `{path, device}`
   shape; the run is drivable (a `MockRunner` step executes normally).
2. **`project_resolved` frozen payload, exactly once (I10).** The persisted
   init state contains exactly ONE `project_resolved` event with payload keys
   exactly `{project, work_area}` (plus the standard `seq/at/type` envelope);
   after driver construction, a step, a recorded failure, and a
   `resume_run` cycle, the count is still one.
3. **Project-less inertness.** Init without a binding produces a state with NO
   project key and ZERO `project_resolved` events, and works with no store
   directory existing anywhere; the entire pre-existing test suite passes
   unmodified.
4. **Resolution is read-only.** After a successful project-bound init, the
   work-area record (including its domain `version`), the meta family, and
   the store listing are byte-unchanged.
5. **Ready is required.** A `pending` and an `unavailable` work area each
   refuse with the not-ready cause; after Slice 2's `confirm` transitions the
   record to `ready`, the same binding succeeds.
6. **Unknown/malformed refusals.** A never-declared name, a tombstoned work
   area, and a nonexistent store directory each refuse as unknown; a stored
   record outside the agent_99 domain refuses as malformed with no repair
   write (I12); an invalid project slug and an invalid work-area name each
   refuse with Slice 2's validation reasons.
7. **Workspace ≡ primary.path.** A binding with no workspace argument derives
   it from `primary.path`; an equal supplied workspace succeeds; a differing
   supplied workspace refuses; a `primary.path` that is not an existing
   directory refuses (no directory is created).
8. **Refusals create nothing.** Every refusal in AC5–AC7 (and AC10's invalid
   defaults) raises the dedicated error type with a distinct cause, and
   afterwards NO state file exists at the target path, the workspace location
   is untouched, and the store holds no new or changed KV entry.
9. **Stability after init.** Relabeling, replacing the stored descriptor by
   declaring different roots and confirming that replacement to READY, and
   deleting the work area in the store after init leave the run's recorded
   block, workspace, and grants unchanged, and a subsequent driver step
   neither re-resolves nor appends any project event.
10. **Defaults precedence (E).** A project-default key the launch does not
    set applies (observable e.g. via the resolved `docs_dir` landing per the
    default, including `{slug}` handling); a launch-explicit value for the
    same key wins over the default; a dict-valued key (e.g. `acts`) merges
    key-wise per `merge_config`; with no defaults the effective config is
    exactly today's; a non-object or non-JSON-plain `defaults` refuses.
11. **Suite green.** `python3 -m unittest discover -s orchestrator/tests -t .`
    passes.

## Tests / Verification

In `orchestrator/tests/test_run_init.py` (standard library only; each store a
real `tempfile.TemporaryDirectory` seeded through Slice 2's `declare`/`confirm`
— the file-backed lesson from Slice 1's seal history):

- **Happy path + state seam** — bound init deriving the workspace, the exact
  project-block shape and verbatim roots, and a `MockRunner`-driven step
  (AC1).
- **Event** — payload key-set exactness and the exactly-once count across
  driver construction, a step, a failure, and resume (AC2).
- **Inertness** — no-binding init's state document equality with today's
  shape, zero events, no store required (AC3); the pre-existing suite is the
  regression body.
- **Read-only resolution** — store snapshot equality (record, version, meta,
  listing) across a successful init (AC4).
- **Refusal matrix** — pending/unavailable then confirm→ready success (AC5);
  unknown (undeclared, tombstoned, missing store dir), malformed record,
  invalid slug/name (AC6); workspace mismatch and missing primary directory
  (AC7); each refusal's distinct cause, the dedicated error type, and the
  nothing-created postcondition (AC8).
- **Stability** — post-init store mutations (relabel, declare+confirm a
  different READY descriptor, delete) with an unchanged run and no
  re-resolution on the next step (AC9).
- **Defaults** — default-applies / launch-wins / key-wise-merge / absent-inert
  / invalid-refuses matrix, including `docs_dir` with `{slug}` (AC10).

Full slice verification: `python3 -m unittest discover -s orchestrator/tests
-t .` (AC11).

## Risks

- **Accepting a not-ready work area at init** would bypass the
  launcher-validation contract (`ready` is the executor-confirmed signal,
  goal `:127`–`:129`) and execute against unvalidated roots. The AC5 gate is
  load-bearing.
- **Deriving the workspace from anything but `primary.path`, or fabricating a
  missing primary via `makedirs`,** would run a milestone outside the declared
  work area — the I2 collision harm and the wrong-universe failure mode. The
  AC7 derivation/mismatch/existence tests are load-bearing.
- **Re-recording `project_resolved` on restart or resume** would break the
  frozen once-at-init frequency (I10) and corrupt the worker-knowledge audit
  the event exists for. The AC2 exactly-once test is load-bearing.
- **Re-resolving mid-run** would silently change the grant universe rounds
  were judged under (and make Slice 6's containment unstable). The AC9
  stability tests are load-bearing.
- **Writing to the KV at init** (e.g. auto-confirming pending, bumping
  versions) would make init a store mutator and entangle run creation with
  Slice 7's reconcile role. The AC4 read-only test is load-bearing.
- **Inverting defaults precedence** (project defaults clobbering launch
  config) would make per-launch operator intent lose to standing config —
  contradicting the milestone's precedence doctrine (amendments win over
  safeguards; launches win over defaults). The AC10 matrix is load-bearing.
- **A parallel work-area reader or a second merge function** (instead of
  Slice 2's `resolve` and `merge_config`) would fork sealed semantics — the
  exact duplication failure this milestone exists to prevent. Reuse Posture +
  AC4/AC10 guard this.
- **Breaking project-less runs** (a required binding, a present-null block, a
  schema bump) would strand every existing run including this milestone's
  own. The AC3 inertness test and the unmodified pre-existing suite are
  load-bearing.

## Line budget

Production code is small: a resolution call over sealed seams, a refusal
class, one state field, one event append, and an ordered merge. As in
Slices 1–4, the pinning tests — the refusal matrix, the exactly-once and
stability contracts, read-only resolution, and the defaults precedence
matrix that Slices 6 and 8 depend on — carry the bulk. The slice is expected
near the ~500 changed-line target and may modestly exceed it for that test
surface; that surface is the deliverable's point (**I1**), not incidental.
