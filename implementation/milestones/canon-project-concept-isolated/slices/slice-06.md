# Slice 06 — PROJECT CONTEXT Block + `project_safeguard_seen`

Status: draft — pending review.

Milestone: canon-project-concept-isolated. This is the **activation** slice:
it makes a project-bound run SHOW its workers the standing law and makes what
they were shown auditable. Every worker prompt of a project-bound run gains a
PROJECT CONTEXT block — the ecosystem map plus the in-scope safeguards,
rendered with the same operator authority as amendments — and the ledger
records `project_safeguard_seen {policy_id, version, text[:300]}` the first
time each (id, version) pair enters a prompt, re-recording on a version bump,
mirroring `amendment_seen`. The SAME worker call that renders an in-scope
obligation also supplies the matching compiled extension and the run's grant
roots to Slice 4's sealed enforcement seam, honoring the skeleton's
sequencing rule that "a safeguard is fully live only once its prompt half
(Slice 6) and contract half (Slice 4) both land" (`skeleton.md:188`). It pins
fixture invariant **I10**'s `project_safeguard_seen` half (the sibling
`project_resolved` half sealed with Slice 5) and closes I1's remaining gap
("runs … show workers standing safeguards"). Slice 10's built-in reuse-audit
policy is the first real content to flow through this path.

Like Slices 4 and 5, the change to existing production code is **inert until
bound**: a project-less run builds byte-identical prompts, records zero
project events, and validates against the base kind contract exactly as
today — every existing run, including this milestone's own bootstrap runs,
stays first-class.

The compatibility target is the frozen goal contract
(`implementation/brainstorming/project-concept.md`, frozen at `45f6968`),
read read-only: the prompt-machinery rule ("PROJECT CONTEXT block in every
worker prompt: ecosystem map + safeguards, with the same authority rendering
as operator amendments", `:312`–`:313`), the policy `prompt` field's purpose
("the block the worker sees, amendment-authority rendering", `:225`), the
frozen ledger-event shape (`:254`–`:257`), the precedence rule (`:259`–`:262`),
and the audit purpose ("the ledger records the project and each safeguard the
run's workers were shown … so every round can be judged against what its
workers knew", `:44`–`:48`). Those shapes are adopted verbatim, never
re-derived. The block's composition, the live-read/fixed-roots split, and the
fail-closed selection surface below are this slice's design, consistent with
I10 and pinned by tests.

## Scope (observable contracts)

Five contracts. Each statement is falsifiable by a named test, not by reading
the diff. Concrete identifiers, block layout, and exact wording are
illustrative and the implementation's choice; the pinned content is the
block's presence and required content, the frozen event payload and its
dedup/re-record semantics, the ok-output rendered obligation ≡ enforced
obligation rule, the seal-attempt selection snapshot, and the fail-closed
selection surface.
Illustrative policies in tests follow
slice-03's rule: the concrete reuse-audit content ships in Slice 10, never
here.

### A. The PROJECT CONTEXT block in every project-bound worker prompt

- **Presence.** Every worker prompt the driver builds for a project-bound
  run — all seven worker kinds across the five handlers (draft, review
  round, fix, delta review, and both seal halves) — carries exactly one
  PROJECT CONTEXT block. A project-less run's prompts are BYTE-IDENTICAL to
  today's: the builders' new input defaults to absent and renders nothing.
- **Ecosystem map content.** The block names: the project slug and
  work-area name (the stable path-free handles, goal §Convergence rule 2);
  `primary.path` as the repo the worker executes in; and each additional
  root as an explicitly READ-ONLY grant. All roots come FROM the state
  project block Slice 5 recorded — the fixed universe the run was bound to —
  never from a live store read, so the map always describes exactly the
  universe containment enforces (D). Editing or replacing the work area in
  the store mid-run changes neither the map's roots nor the grant universe.
- **Reuse-source roles render live.** For the bound work area, the meta
  family's `{reuse_sources: [{root, inventory, registry, consumption}]}`
  value (Slice 2's sealed shape) renders into the map beside the roots it
  describes, read live per call through Slice 2's read seam. An absent meta
  record is not an error — the map renders without roles (the family is
  optional by Slice 2's design). A present meta record must match Slice 2's
  exact shape before any worker sees it; a malformed/corrupt value fails
  closed under E. Roles are operator-authored descriptors and render as
  recorded after that shape check; this slice adds no semantic validation of
  `root`/`inventory`/`registry`/`consumption`.

### B. Safeguard rendering: live selection at operator authority

- **Selection.** Before every project-bound worker call except a seal half,
  the enabled policies whose scope matches that call's (worker kind, unit
  kind) are re-read LIVE from the project's policy store via Slice 3's sealed
  predicate — mirroring the amendments hot-edit doctrine for ordinary calls
  while keeping exposure auditable. A seal attempt is one judgment
  surface: both halves use the same pre-attempt policy snapshot, even when
  the halves run sequentially, so an edit between halves binds the next
  worker call after that attempt, not the second half. Disabled and
  out-of-scope policies never render. A project-bound call with nothing in
  scope renders the ecosystem map alone.
- **Per-safeguard rendering.** Each in-scope safeguard renders: its id and
  version, visibly attached to its text; the operator's `prompt` text
  VERBATIM — operator text is trusted, length-clipped only to protect the
  context window, exactly the amendments posture (`prompts.py:366`, `:374`);
  and the machine-rendered obligation derived from the compiled extension:
  the REQUIRED output field's name, the declared entry fields with their
  type-specs (enum values listed), and the full mechanical check set with
  each check's kind and parameters. The operator's prompt text carries the
  procedure; the machine-rendered obligation carries everything the driver
  will mechanically enforce for an ok output — naming the slot is the prompt
  half of the no-bare-boolean doctrine (a worker not told the field name can
  only fail the merged contract and burn the single repair retry by design).
- **Authority and precedence text.** When at least one safeguard is in scope,
  the block states, at phrase level (asserted on whitespace-normalized text,
  the `test_prompts.py` convention): safeguards bind authors and fixers like
  the TASK itself; for report-only reviewers a safeguard violation in the
  reviewed artifact is a FINDING, exactly like an amendment violation; and
  run-scoped OPERATOR AMENDMENTS WIN over project safeguards on conflict (the
  more specific, later intent — the frozen precedence,
  `project-concept.md:259`–`:262`). When amendments are present the two
  blocks coexist in the same prompt; the amendments mechanism itself is
  untouched. With no in-scope safeguards, the block is only the ecosystem map.

### C. The `project_safeguard_seen` ledger event (frozen shape)

- **Payload.** `project_safeguard_seen` carries exactly
  `{policy_id, version, text}` plus the standard `seq/at/type` envelope
  (`state.py:294`), where `text` is the first 300 characters of the
  policy's `prompt` — the same clip `amendment_seen` applies to amendment
  text (`driver.py:557`).
- **First-seen per (id, version), re-record on bump.** The event is
  appended the first time each (policy id, version) pair enters a prompt
  of this run; later renders of the same pair append nothing; a version
  bump re-records under the new version (`project-concept.md:254`–`:257`,
  fixture I10 frequency). A policy that never renders — disabled,
  out-of-scope for every call made, or any policy in a project-less run —
  is never recorded.
- **Exposure is recorded even when the call fails.** A worker that was
  shown a safeguard and then produced twice-invalid output (or was
  otherwise failed) still leaves the seen event in the persisted state:
  the event exists so every round "can be judged against what its workers
  knew" (`:44`–`:48`), and a failed round was still shown the law. A seal
  attempt records at most one event per pair across both halves (the
  once-before-half-threads pattern already used for amendments,
  `driver.py:1527`).
- **A run-ledger event, not a datastore write.** Seen events live in
  `state.json`'s append-only event ledger only; this slice writes NO KV
  entry (skeleton Shared Invariants: durable truth never lives in the
  datastore; the frozen key grammar I7 gains nothing).

### D. Enforcement rides the same call (Slice 4 activated)

- **Rendered obligation ≡ enforced obligation for ok outputs.** The
  project-bound worker call whose prompt renders in-scope obligations
  supplies exactly those policies — compiled through Slice 4's sealed
  compiler — plus the run's grant roots to the existing enforcement seam
  (`runners.py:380` `call_worker(extensions=, roots=)`). Never one without
  the other: every rendered field, entry schema, and mechanical check is
  enforced against a `status: "ok"` output in that same call, and no call is
  held to any field, entry schema, or check its prompt did not carry (the I10
  victim: "a reviewer or fixer is harmed if a worker is blamed for a
  safeguard absent from its prompt").
- **Observable enforcement.** Through the driver's real call path, a first
  `status: "ok"` output that omits the extension field or fails a check
  triggers exactly ONE repair retry; a second failure raises the same
  protocol failure as a malformed base contract; a conforming output
  proceeds. A valid `status: "blocked"` output follows Slice 4's ok-only
  exemption and does not need extension fields. With nothing in scope,
  validation is byte-identical to the base kind contract.
- **The grant universe is the state block's.** The roots handed to
  enforcement are `primary.path` plus each additional root's path from the
  run's recorded project block — the fixed universe slice-05 §B pinned for
  this consumer. A citation into an additional root is inside the universe;
  one outside every recorded root is a worker contract violation; a mid-run
  store edit to the work-area record changes nothing (map and containment
  stay on the recorded roots).

### E. Standing law fails closed

- **Selection, meta, and compile faults fail the run, loudly.** An unreadable
  policy store, a malformed or vocabulary-illegal stored policy, a malformed
  present `work_area_meta:<name>` value, a compile collision (Slice 4's
  config-error class), or an operational check fault (its
  missing-reuse-source-directory class) surfaces as a RECORDED run failure:
  the run's status and failure reason are observable in state, the fault is
  never sent to a worker as a repair (config faults detected while preparing
  the call consume no worker call at all; operational faults burn no repair
  retry — Slice 4's error split, reused), and the operator reads the reason
  at the failure surface. After the operator repairs the store, the existing
  resume path re-executes the step and reads fresh.
- **The deliberate contrast with amendments.** The amendments reader
  tolerates a malformed file by returning nothing (`driver.py:542`) because
  amendments.json is a lock-free hot-edit file where a mid-write read must
  not kill a run. The policy store is a CAS-disciplined KV whose content is
  validated on write: malformed content there is corruption, and a run that
  silently proceeds WITHOUT standing law is exactly the M26/M27 incident
  this milestone exists to prevent. Silent skip is the one behavior this
  surface must never exhibit; the tolerant pattern is NOT copied.

## Non-Goals

- **No service or panel surface.** Project/work-area CRUD and launcher
  validation are Slice 7; binding a LAUNCH to `(project, work_area)`, the
  `run:<run_id>/status` projection, and the project name in run status are
  Slice 8; the panel safeguard editor is Slice 9. This slice adds no
  endpoint and leaves `state.summary` untouched.
- **No built-in safeguard content.** The reuse-audit policy — its real
  `prompt`, `entry`, `checks`, and the review-side concur/dissent field —
  is Slice 10. Policies appear here only as illustrative test content.
- **No contract-machinery changes.** Slice 4 is sealed: no new verifier
  kinds, no changes to the compile/merge/error classes or the repair-retry
  semantics. This slice only supplies that seam's inputs from the run's
  binding and records what was shown.
- **No amendments-machinery changes, and no conflict detection.** The
  precedence of amendments over safeguards is rendered law plus reviewer
  duty (the frozen rule's own enforcement model) — not a semantic
  diff/conflict engine.
- **No KV writes, no new key family, no state schema bump.** Seen events
  ride the existing event ledger; the frozen key grammar (I7) is untouched.
- **No policy validation at init.** Sealed slice-05 non-goal preserved: a
  bad policy surfaces at enforcement time through E, not at `init_run`
  (failing init on a policy a run may never touch would block launches for
  nothing).
- **No mid-run re-resolution.** Roots and binding stay as recorded at init
  (Slice 5's stability contract); only policies and meta roles are live.
- **No migrations, compat shims, or tolerant readers** (greenfield,
  **I12**): the fail-closed posture of E is the designed behavior for data
  that can only be malformed by corruption, not a compatibility layer.

## Expected Files

- `orchestrator/prompts.py` (edit) — the PROJECT CONTEXT block builder
  beside `_amendments_block`; each of the seven builders gains an optional
  project-context input rendered only when supplied (absent ⇒ byte-identical
  output).
- `orchestrator/driver.py` (edit) — selection/compile/seen-record for
  project-bound runs: per ordinary worker call, and once per seal attempt
  for the shared half snapshot; threading the compiled extensions and
  state-block roots through both worker-call paths (the shared `_call` and
  the seal halves' direct `runners.call_worker`); the fail-closed handling
  of Slice 4's non-repairable error family into a recorded run failure (E).
- `orchestrator/tests/test_project_context.py` (new) — the pinning tests
  (standard library `unittest`; stores in `tempfile.TemporaryDirectory`
  seeded through Slice 2's `declare`/`confirm` and Slice 3's `PolicyStore`,
  runs driven over `MockRunner` through Slice 5's project-bound `init_run`).
- No changes to `contracts.py`, `runners.py`, `verifiers.py`,
  `projects.py`, `workareas.py`, `kvstore.py`, or `state.py` — their sealed
  seams are consumed as-is.

## Dependencies

- **Slice 5** (sealed) — the state project block
  `{directory, project, work_area, primary, additional}` (`state.py:151`)
  this slice reads for store handles, map roots, and the grant universe;
  project-bound `init_run` as the test entry point; `project_resolved` as
  the event's sealed sibling.
- **Slice 4** (`orchestrator/verifiers.py`, sealed) — `compile_extensions`
  (`:211`) and the enforcement seam `call_worker(extensions=, roots=)`
  (`runners.py:380`); the non-repairable `VerifierError` family
  (`PolicyConfigError` `:55`, `OperationalError` `:60`) E routes to a
  recorded failure; `validate_merged_output` (`:482`) as the merged
  validation this slice's calls exercise.
- **Slice 3** (`orchestrator/projects.py`, sealed) — `PolicyStore` (`:176`)
  and the scope predicate `policy_matches` / `in_scope` (`:165`, `:244`)
  selection reuses verbatim; the policy value's `prompt` field as the
  rendered and ledgered text.
- **Slice 2** (`orchestrator/workareas.py`, sealed) — `read_meta` (`:561`)
  for the live reuse-source roles; `declare`/`confirm` for test seeding;
  the meta value shape `{reuse_sources: [{root, inventory, registry,
  consumption}]}` (`:336`).
- The existing machinery this slice extends: the seven prompt builders
  (`prompts.py:485`–`:656`) and `_amendments_block` + its clip
  (`:366`–`:388`) as the authority-rendering precedent; `_amendments` and
  `amendment_seen` (`driver.py:526`–`:559`, clip at `:557`) as the
  seen-ledger precedent; the once-before-half-threads pattern
  (`driver.py:1527`); `append_event` (`state.py:294`) and `fail_run`
  (`:541`); `MockRunner` (`runners.py:310`); the `build_all` /
  normalized-phrase conventions of `orchestrator/tests/test_prompts.py`.
- The sealed skeleton (Slices row 6 `skeleton.md:173`; Sequencing "Slice 3
  underpins … 6", "Slice 4 underpins 6", "Slice 5 underpins 6", and the
  fully-live rule `:185`–`:189`; Tests That Pin `:200`–`:202`) and the
  pricing-pilot fixture
  (`implementation/brainstorming/project-concept-pricing-pilot.json`,
  **I10** `priced_ok` — payload/frequency/victim; the `amendment_seen`
  adopt evidence `orchestrator/driver.py:523`).
- The frozen goal re-read read-only as the contract source:
  `project-concept.md:44`–`:48`, `:225`, `:254`–`:262`, `:312`–`:313`.
- Consumers arriving later (not required to land this slice): Slice 8 (the
  launch surface that produces project-bound runs in production), Slice 10
  (the built-in policy whose prompt and contract flow through this path).

## Reuse Posture

- **Checked (this repo):** the amendments pipeline end-to-end — block
  rendering with operator authority (`prompts.py:369`), live re-read per
  call, first-seen ledger with the 300-character clip
  (`driver.py:526`–`:559`), once-before-half-threads (`:1527`) — as the
  pattern this slice mirrors; the seven builders and their optional-input
  convention (`amendments=None`); Slice 3's selection, Slice 4's
  compile/enforce/error seams, Slice 5's state block and stability
  doctrine, Slice 2's meta read (all sealed, cited above); the driver's
  five prompt-building handlers as the complete set of worker-call sites
  (`prompts.build_` appears nowhere else outside tests).
- **Checked (contract source, read-only):** the frozen goal's prompt
  machinery, event shapes, precedence, and audit purpose (`:44`–`:48`,
  `:225`, `:254`–`:262`, `:312`–`:313`); fixture I10.
- **Reused / extended:** the block renders through the SAME builder
  pattern as amendments (an optional input, nothing global); the seen
  ledger mirrors `amendment_seen`'s doctrine — same event ledger, same
  clip, first-seen dedup extended by the version key the frozen contract
  adds; selection reuses Slice 3's predicate (no re-implemented matching);
  enforcement reuses Slice 4's seam (no parallel validator, no second
  retry path); roots and handles come from Slice 5's block (no
  re-resolution); meta comes through Slice 2's read seam (no parallel
  reader). Failure recording reuses `fail_run` and the existing resume
  path.
- **No reuse-source surface is scoped here.** The block and events are OUR
  prompt and ledger machinery; nothing in this slice is an
  agent_99-readable shape, and the only cross-repo-shaped content it
  touches (work-area roots, meta roles, policy records) is consumed
  through the sealed seams of Slices 2/3/5. Stores open with the default
  reserved namespace (the single config point, I7), unchanged.
- **New machinery, and why (the I10 gap, not a parallel):** the block
  builder + builder inputs; the selection/compile/record step (per ordinary
  call, shared once per seal attempt) and its threading into the two call
  paths; the fail-closed routing of Slice 4's error family into a recorded
  run failure. None of this exists today (fixture I10: "project events are
  new"; `amendment_seen` is the adopted precedent, not a substitute — it
  knows nothing of versions, scopes, or stores).

## Proportionality (amendment A1)

The block in every worker prompt, the amendment-authority rendering, the
frozen event name/payload/frequency/dedup/re-record, and the precedence rule
are pinned by **I10** (with I1's prompt half) and not re-derived. New
mechanism beyond those invariants, with victims:

- **The machine-rendered obligation in the block (B/D).** VICTIM: the
  operator and the worker — an in-scope worker not told the required field's
  name, entry shape, and mechanical checks can only fail the merged contract
  for any ok output, burning the single repair retry by design (two worker
  calls each; a second miss fails the run). The doctrine "an LLM fills a
  required slot far more reliably than it obeys a warning" requires the full
  mechanically enforced obligation to be visible. COST: rendering lines over
  the already-compiled extension; no new subsystem.
- **Live policy selection and compile (B/D).** VICTIM: the operator,
  reviewer, and next worker call — if hot-edited safeguards are not re-read,
  selected, and compiled before each ordinary call, workers can run under
  stale standing law or be enforced against yesterday's policy, breaking the
  amendments-like liveness AC7 pins. COST: one policy listing/selection and
  compile over Slice 3/4 sealed seams per project-bound ordinary call; no
  cross-call cache, index, background process, or new verifier.
- **Reuse-source roles rendered from live meta (A).** VICTIM: Slice 10's
  audit worker and the reuse sources themselves — the M26/M27 failure was
  an INCOMPLETE inventory map; a map of bare paths without the
  inventory/registry/consumption roles would recreate it at the prompt
  layer. COST: one enveloped read per bound work area per call plus the
  Slice 2 shape check and rendering.
- **Seal-attempt policy snapshot (B/C).** VICTIM: seal reviewers and the
  operator — one seal attempt judged under two different policy sets would
  make the verdict and `project_safeguard_seen` audit ambiguous, especially
  if a policy edit lands between sequential halves. COST: one shared
  in-memory policy selection for the attempt plus the seal cases in the
  dedup/liveness tests; no cross-call cache.
- **Fail-closed routing to a recorded run failure (E).** VICTIM: the
  operator — Slice 4's config/operational errors are deliberately outside
  the worker-repair family, and malformed live meta is corruption in
  prompt-visible standing context, so without this routing they would escape
  the driver as an unrecorded crash (no reason in state, log, or panel), or
  tempt a tolerant skip that runs without standing law. COST: one catch
  around selection/meta/validation routing into the existing `fail_run`.

Nothing is SPECULATIVE and nothing requires operator approval. Deliberately
NOT built, with reasons: policy caching across calls outside the explicit
seal-attempt snapshot (would break the mid-run-edit-binds-next-call doctrine
to optimize a handful of small local reads); rendering out-of-scope
safeguards "for context" (would either
corrupt the seen ledger into recording exposure to law that did not bind the
call, or split rendering from recording — both poison the audit); a
conflict-detection engine between amendments and safeguards (the frozen
precedence is rendered law judged by reviewers); a second seen event on the
repair retry (same call, same prompt block, dedup already covers it).

## Acceptance Criteria

1. **Block presence and map content (I1/I10).** For a project-bound run,
   prompts of all seven worker kinds carry exactly one PROJECT CONTEXT
   block naming the project slug, work-area name, `primary.path` as the
   executed repo, and each additional root as a read-only grant — the
   roots verbatim from the state project block; with a meta record
   present, its reuse-source roles render beside the roots; with no meta,
   the map renders without roles and without error.
2. **Safeguard rendering.** An enabled, in-scope policy renders its id,
   version, operator `prompt` text verbatim (long text clipped, mirroring
   the amendments clip), the required field name, and the entry fields
   with their type-specs including enum values, and every mechanical check
   with its kind and parameters. A disabled policy and an out-of-scope policy
   (wrong worker kind or wrong unit kind) do not render; with none in scope
   the map renders alone.
3. **Authority and precedence phrases.** For prompts with at least one
   in-scope safeguard, whitespace-normalized prompt text contains the
   binds-like-the-TASK statement, the reviewer duty (a safeguard violation in
   the reviewed artifact is a finding, like an amendment violation), and the
   amendments-win-on-conflict statement; with amendments also configured, both
   blocks appear in the same prompt. Prompts with no in-scope safeguards are
   governed by AC2/AC10's map-only contract.
4. **Event payload exactness (I10).** The first render of a safeguard
   appends exactly one `project_safeguard_seen` whose payload keys are
   exactly `{policy_id, version, text}` (plus the `seq/at/type` envelope),
   with `text` equal to the policy prompt's first 300 characters.
5. **Dedup / re-record matrix (I10).** Later calls rendering the same
   (id, version) append nothing; a version bump re-records under the new
   version (two events total for that id); disabled, out-of-scope, and
   project-less cases record zero; a seal attempt (both halves) records at
   most one event per pair; a call whose worker output fails twice (run
   fails) still leaves the seen event in the persisted state.
6. **Rendered obligation ≡ enforced obligation, over the recorded universe.**
   Driving a project-bound call with an in-scope policy through `MockRunner`:
   every rendered field, entry schema, and check is enforced against ok
   outputs; a first `status: "ok"` output missing the field or failing a
   check triggers exactly one repair retry and a second failure fails the
   call as a protocol violation; a conforming output proceeds; a valid
   `status: "blocked"` output is exempt from extension enforcement; a
   citation into an ADDITIONAL root passes containment while one outside
   every recorded root is a worker contract violation; a call whose prompt
   carries no obligation enforces none (base validation, byte-identical);
   replacing the stored work-area descriptor mid-run (declare + confirm
   different roots) changes neither the rendered map roots nor the
   containment universe of the next call.
7. **Live re-read of law.** A policy put into the store mid-run renders in
   the NEXT non-seal-half call's prompt (and records seen); a version bump
   mid-run renders and re-records; a policy disabled mid-run stops
   rendering and stops being enforced from the next non-seal-half call on.
   For seal attempts, the same put/bump/disable matrix binds the next seal
   attempt's shared half snapshot, while edits between the two halves of an
   attempt do not split their policy set.
8. **Fail-closed (E).** Against a project-bound run: a stored policy
   outside the vocabulary (Slice 4 config error), a malformed stored
   policy value, a malformed present `work_area_meta:<name>` value, an
   unreadable policy store (directory removed after init), and an operational
   check fault (missing `dir_listing_matches` directory) each fail the run
   with the reason recorded in state; the config/meta cases consume NO worker
   call (the runner is never invoked); the operational case burns no repair
   retry; after repairing the store, resume re-executes the step and
   proceeds.
9. **Project-less inertness.** A run initialized without a binding builds
   prompts byte-identical to today's for every kind, records zero
   `project_safeguard_seen` events, and validates against the base
   contract; the entire pre-existing test suite passes unmodified.
10. **No-policy project.** A project-bound run whose store holds no
    policies renders the map alone, records zero seen events, and
    validates against the base contract.
11. **Suite green.** `python3 -m unittest discover -s orchestrator/tests
    -t .` passes.

## Tests / Verification

In `orchestrator/tests/test_project_context.py` (standard library only;
stores in real `tempfile.TemporaryDirectory` seeded through Slice 2's
`declare`/`confirm` and Slice 3's `PolicyStore.put`; project-bound runs
created through Slice 5's `init_run` and driven over `MockRunner`):

- **Block content** — presence and map content across all seven kinds,
  meta roles present/absent, and project-less byte-identity, driving the
  prompt builders per `test_prompts.py`'s `build_all` convention and the
  driver for end-to-end presence (AC1, AC9).
- **Rendering** — id/version/verbatim-text/clip, field + entry schema with
  enum values, rendered check kind + parameters, disabled and out-of-scope
  exclusion, none-in-scope map-only (AC2); normalized authority/precedence
  phrases for in-scope safeguards and coexistence with amendments (AC3).
- **Events** — payload key-set and text-clip exactness (AC4); the full
  dedup/re-record matrix including the seal attempt and the
  failed-call-still-seen case (AC5).
- **Enforcement binding** — rendered field/schema/check identity with the
  enforced extension, the ok-output repair-retry/protocol-failure sequence
  through the driver's real path, blocked-output exemption, additional-root
  containment pass and out-of-universe violation, no-obligation byte-identity,
  and mid-run descriptor-replacement stability (AC6).
- **Liveness** — mid-run put / bump / disable binding the next ordinary call
  and the next seal attempt, while edits between seal halves do not split
  their shared policy snapshot (AC7).
- **Fail-closed** — the five failure cases with recorded reasons, the
  no-worker-call and no-retry assertions, and the repair-then-resume recovery
  (AC8).
- **No-policy project** (AC10); the pre-existing suite as the regression
  body (AC9, AC11).

Full slice verification: `python3 -m unittest discover -s orchestrator/tests
-t .` (AC11).

## Risks

- **Silently skipping unreadable law** (copying the amendments-tolerant
  read where it must not apply) would run workers WITHOUT the standing
  safeguards — the M26/M27 incident reborn at the exact layer built to
  prevent it. The AC8 fail-closed matrix is load-bearing.
- **Rendering without enforcing ok outputs** re-creates the
  prose-prohibition failure the goal's lesson names ("shouted prohibitions
  do not prevent duplication"); **enforcing without rendering** blames
  workers for fields, schema, or checks they were never shown and burns the
  repair retry by design. The AC6 set-identity tests are load-bearing.
- **Deduplicating seen by id alone** (dropping the version key) would make
  version bumps invisible to the audit, breaking the frozen re-record rule.
  The AC5 bump case is load-bearing.
- **Recording seen for unrendered law** (disabled/out-of-scope policies)
  would make the ledger claim exposure that never happened — the I10 victim
  verbatim ("a worker is blamed for a safeguard absent from its prompt").
  The AC5 zero-cases are load-bearing.
- **Reading roots live instead of from the state block** would let a
  mid-run store edit silently change the map and the containment universe
  rounds were judged under, breaking Slice 5's stability contract. The AC6
  descriptor-replacement test is load-bearing.
- **Omitting or inverting the precedence text when safeguards render** would
  leave reviewers judging amendments beneath safeguards, contradicting the
  frozen precedence. The AC3 phrase tests are load-bearing.
- **Splitting a seal attempt's policy set** (selection inside each half
  instead of once for the attempt) would corrupt the once-per-pair contract:
  concurrent halves could double-record, and sequential halves could judge
  one attempt under two different safeguard sets. The AC5 and AC7 seal
  cases are load-bearing; the amendments once-before-threads pattern is the
  reused shape.
- **Breaking project-less prompts** (a block or builder change leaking into
  unbound runs) would perturb every existing run including this
  milestone's own. The AC9 byte-identity test and the unmodified
  pre-existing suite are load-bearing.
- **A parallel rendering or selection path per kind** (instead of one block
  builder and one selection step feeding all seven kinds) would drift the
  law across worker kinds — the duplication failure this milestone exists
  to prevent. Reuse Posture and AC1's all-kinds sweep guard this.

## Line budget

Production code is small: one block builder beside `_amendments_block`, a
selection/record step (per ordinary call, once per seal attempt) threading
through the two existing call paths, and one failure-routing branch. As in
Slices 1–5, the pinning tests — the all-kinds prompt sweep, the dedup/
re-record matrix, the enforcement-binding integration, and the fail-closed
matrix — carry the bulk, so total changed lines may modestly exceed the
~500 target. That test surface is the deliverable's point (**I10**): the
audit ledger and the prompt law are only trustworthy to the exact extent
these tests pin them.
