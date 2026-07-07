# Project Concept: Ecosystem-Scoped Standing Safeguards And Reuse Gates

Status: skeleton draft.

## Goal

Runs are workspace-scoped; real work is ecosystem-scoped. Amendments die
with the run and repo docs are advisory prose, so nothing carries standing,
operator-authored law that binds every run across a family of related
repositories. A **project** is a named, fully generic, operator-defined
ecosystem spanning multiple roots. This milestone gives the orchestrator
that project as first-class configuration and makes its safeguards bite.

Load-bearing lesson from the motivating incident (agent_99 M26/M27
rebuilt ~2,300 lines of chat surface already SEALED in LPC, despite a
verbatim in-doc prohibition): **shouted prohibitions do not prevent
duplication; mandatory enumerated verification does.** So every safeguard
compiles to a required, falsifiable CONTRACT FIELD — an enumeration with
`file:line` evidence the driver can check mechanically — never a warning.

The project record is **workspace-shaped**: it adopts agent_99's
configuration architecture literally (project = agent_99 *workspace*;
work_areas = agent_99 *work areas*; safeguards use agent_99's versioned
capability-policy concept), so future fusion with agent_99 is a transport
swap, not a migration. Storage is a local KV honoring LPC's
revision-envelope CAS contract.

## Boundary

In scope — the ten slices below deliver: a local KV store; an
agent_99-readable work-area store; the project + policy configuration
model; a closed verifier vocabulary with contract-extension enforcement;
run-init project resolution; the PROJECT CONTEXT prompt block and project
ledger events; the service and panel operator surfaces; and the built-in
reuse-audit safeguard.

## Non-Goals

- **No cross-repo writes.** Reuse sources are read-only during runs; a
  recorded gap flows to the source's consumer-needs channel, never to
  local reimplementation.
- **No vendoring/pinning management.** How a consumer depends on a source
  (submodule, path dep, hex) stays the consumer repo's decision; the
  project only records the sanctioned model.
- Not a monorepo tool and not a build system.
- **No `primary_root` API alias or public SCHEMAS doc** — queued to
  `machine-api-and-persona-projection.md`. This milestone binds launches
  to `(project, work_area)` with `primary.path` as the executed repo; the
  rename-free projection is that sibling milestone's job.
- **No digest implementation.** The key grammar RESERVES
  `run:<run_id>/digest`; the endpoint is built by the machine-api
  milestone. The sibling `run:<run_id>/status` projection is in scope
  here and must not be left inert.
- **No skeleton price-tag / verified-assumptions machinery.** That is
  `skeleton-code-first-discipline.md`, which sequences AFTER this and
  consumes this milestone's reuse-audit machinery.
- **No migrations, compat shims, tolerant readers, or deprecation
  cycles.** Greenfield (see Shared Invariants).

## Reuse Posture

- **Checked (this repo):** the existing contract validation + single
  repair-retry path (`orchestrator/contracts.py`, `orchestrator/runners.py`);
  the amendments mechanism, its authority rendering, and the
  `amendment_seen` ledger event (`orchestrator/driver.py`,
  `orchestrator/prompts.py`); the existing `Reuse Posture` prompt
  requirement (`orchestrator/prompts.py:254`); the worker-kind vocabulary
  (`contracts.py:40`) and unit-kind constants (`state.py:36`); the
  single-workspace-path run model (`state.py`, `service.py`); the
  generated-record + append-only-ledger doctrine (`WORKSPACE.md`).
- **Checked (reuse sources, read-only):** agent_99's `WorkAreaStore`
  (stored value, per-operation version semantics, tombstone); LPC
  `LifeProductWorkspaces` `Client` / `Cas` / `Datastore` (revision
  envelope, primitives, refs helpers); agent_99's versioned
  capability-policy concept.
- **Reused / extended:** safeguards enforce inside the EXISTING repair-retry
  path (one retry on contract violation), not a parallel validator;
  `project_safeguard_seen` mirrors `amendment_seen`; safeguards render with
  the same operator authority as amendments; policy scope uses the EXISTING
  kind/unit-kind vocabularies (no new names); durable truth stays in git +
  `state.json` (datastore holds only descriptors/projections).
- **Adopted verbatim from reuse sources** (the compatibility target):
  agent_99's full work-area stored domain and version/tombstone behavior;
  LPC's revision-envelope CAS contract.
- **New machinery, and why (each a fixture-priced gap, not a parallel):**
  a local file-backed project KV (none exists); the closed verifier
  vocabulary + policy contract-extension merge (no project-extension
  mechanism exists); the concrete safeguard policy JSON (`prompt`,
  `contract`, verifier checks) that instantiates the versioned-policy
  concept for this orchestrator; project/work-area addressing at run init
  (state knows one path); the PROJECT CONTEXT block + project ledger
  events.
- **Compatibility:** stored shapes match agent_99's CURRENT readers, so
  fusion is a namespace-pump transport swap; the raw `refs/work_area:`
  family is byte-compatible and NEVER namespaced; a new verifier kind is
  an orchestrator milestone, never project config, preserving the
  no-code-injection boundary.

## Non-Canonical Planning (Adopt / Revise / Reject)

- **Named material:** `implementation/brainstorming/project-concept.md`
  (the goal; normative contracts frozen at commit `45f6968` after ten
  advisory rounds), `project-concept-pricing-pilot.json` (the r10
  convergence fixture, 12 priced invariants), and the two sibling
  brainstorming notes.
- **Adopt:** the frozen normative contracts as pinned; the fixture's
  invariants as the priced work map — each `ecosystem_equivalent: gap` is
  a build unit, each `adopt` a compatibility target; the fixture as the
  validator's test fixture (its `file:line` citations anchored to the
  reviewed commit in its provenance, not to the moving goal note).
- **Revise:** none. The contracts are frozen; slices restate them as
  invariants without weakening (two advisory rounds killed weaker
  compatibility claims — not reopened).
- **Reject / defer:** the `primary_root` alias + SCHEMAS doc and the
  digest endpoint (→ machine-api milestone); the price-tag /
  verified-assumptions skeleton machinery (→ skeleton-code-first
  discipline, which sequences after and consumes this work).

## Shared Invariants (pinned — do not re-derive)

These are pinned by `project-concept.md` §Normative contracts (frozen at
`45f6968`) and the pricing-pilot fixture. Slice notes COPY the exact
field domains from those sources verbatim; nothing re-derives them.

- **Storage split.** OUR families (`work_area_meta:`, `policy:`,
  `run:<run_id>/status`; `run:<run_id>/digest` reserved) use LPC's
  revision envelope — stored `{revision, value, deleted?}`,
  public read `{exists?, revision, value}`, first write revision 1 then
  monotonic +1, tombstone deletes, listings INCLUDE tombstones, values
  JSON-plain / string-keyed / serialization-stable. The raw
  `refs/work_area:<name>` family is stored RAW (agent_99's top-level map),
  CAS on the WHOLE current value, deleted via agent_99's own
  `{name, deleted: true, version}` tombstone with positive version — never
  the envelope tombstone. Control revision is independent of any domain
  `version` inside a value. (Fixture I3–I7.)
- **Key grammar.** One reserved namespace constant (default
  `milestone_orchestrator`, single config point). `refs/work_area:<name>`
  is agent_99-native and never namespaced (so it pumps to the exact native
  key at fusion). The enveloped `work_area_meta:<name>` value is exactly
  `{reuse_sources: [{root, inventory, registry, consumption}]}`. Every
  cited/verifier path must resolve inside a work-area root.
- **Authority is local-authoritative.** This machine is the writer of
  record for our families; after fusion the server copy is a visibility
  mirror, and server-side edits to our namespace are never auto-applied.
- **Durable truth never lives in the datastore.** Run ledgers stay in
  `.orchestrator/state.json`; gate history and milestone records are
  committed in the repos. The datastore holds only descriptors and
  projections; a server wipe loses nothing (re-declare, re-pump).
- **Safeguards are versioned contract fields, not prose.** No bare
  booleans; each safeguard demands a falsifiable enumeration + citations.
  Projects compose a CLOSED verifier vocabulary; they can never inject
  code or shell. A new verifier kind is an orchestrator milestone.
- **Scope uses existing vocabularies.** `scope.kinds` are `contracts.py`
  `KIND_*` values; `scope.unit_kinds` are `state.py` unit constants
  (`skeleton`, `slice_doc`, `slice_impl`). No new scope names.
- **Precedence.** Run-scoped operator amendments WIN over project
  safeguards on conflict; both render with operator authority; reviewers
  treat safeguard violations exactly like amendment violations.
- **Greenfield.** Zero existing project records, work areas, policies, or
  KV entries. "Compatibility" means only: our shapes match agent_99's
  CURRENT readers for future fusion. No migration/shim/tolerant-reader
  scope is valid at this altitude. (Fixture I12.)

## Slices

| Slice | Title | Intent (one line) | Pins |
|---|---|---|---|
| 1 | Local KV store + key grammar | File-backed local KV honoring LPC's revision-envelope CAS for our families, with atomic write visibility, serialized concurrent writers, the reserved-namespace key grammar, and root-containment for verifier/citation paths; the storage foundation for every later slice. | I6, I7 |
| 2 | Agent99-compatible work-area store | The raw `refs/work_area:<name>` family carrying agent_99's full stored work-area domain: whole-value CAS, pending→ready version bump, display-name rename preserving version, and positive-version tombstone; plus the enveloped `work_area_meta:<name>` reuse-source family beside it. | I3, I4, I5 |
| 3 | Project record + policy config model | The workspace-shaped project record (`{work_areas, policy[], defaults}`) and the versioned policy object (`id, version, enabled, scope, prompt, contract`), with scope matching against the existing kind/unit-kind vocabularies. | I8 |
| 4 | Verifier vocabulary + contract-extension merge | The closed V1 verifier set (`path_exists`, `citation_exists`, `dir_listing_matches`, `non_empty`, `enum`) and the merge of in-scope policy contract fields into a worker's base kind contract, validated in the existing repair-retry path. | I9 |
| 5 | Run-init project resolution + `project_resolved` | A run resolves its `(project, work_area)` membership at init and records `project_resolved` once; `primary.path` is the executed repo, additional roots are read-only grants. | I1 |
| 6 | PROJECT CONTEXT block + `project_safeguard_seen` | Every worker prompt carries the ecosystem map + in-scope safeguards at operator-amendment authority; the ledger records `project_safeguard_seen {policy_id, version, text[:300]}` first-seen per `(id, version)`, re-recording on bump; amendments win on conflict. | I10 |
| 7 | Service API: project/work-area config | Additive endpoints for project and work-area CRUD (declare/create → pending for new work areas; launcher validation reconciles → ready) and `GET /api/projects`. | I2 |
| 8 | Launch binding + run status projection | Bind a launch to `(project, work_area)`, write/update the enveloped `run:<run_id>/status` projection, and carry the project name in run status. | I1 |
| 9 | Panel operator surface | Standing project and work-area CRUD surfaces, plus the safeguard editor (like the amendments card but standing); the launch flow displays the resolved project. | I8 |
| 10 | Built-in reuse-audit safeguard | Ship the reuse-audit policy as a built-in template any project can enable and parameterize: the planning-side `reuse_audit` contract field (enumerated adopt/gap/reject with `file:line` evidence) and the review-side contract field carrying one concur/dissent entry per audited package, with the reviewer's own `file:line` citation; every dissent backs a finding. | I11 |

Invariant ids reference the pricing-pilot fixture
(`implementation/brainstorming/project-concept-pricing-pilot.json`).

## Sequencing

Suggested order is Slice 1 → 10. Dependencies: Slice 1 underpins all
storage (2, 3, 5, 7, 8); Slice 3 underpins 4, 6, 7, 8, 9, 10; Slice 4
underpins 6 and 10; Slice 5 underpins 6 and 8; Slices 2 and 3 underpin 7,
8, and 9; Slices 7 and 8 underpin 9. Each slice is independently
reviewable; a safeguard is fully live only once its prompt half (Slice 6)
and contract half (Slice 4) both land. Each slice
aims under ~500 changed lines; the slice note sets final scope, files,
tests, risks, and acceptance.

## Tests That Pin The Milestone

Per the goal's deliverables, the milestone's tests pin: the KV envelope
semantics, atomic write visibility, and serialized concurrent writers
(Slice 1); root containment for verifier/citation paths (Slices 1 and 4);
each verifier (Slice 4); the contract merge (Slice 4); `run:<run_id>/status`
projection writes (Slice 8); run-init `(project, work_area)` resolution and
exactly-once `project_resolved` recording (Slice 5); PROJECT CONTEXT prompt
inclusion and `project_safeguard_seen` text payload + dedup/re-record
(Slice 6); the built-in reuse-audit planning and review contract fields
(Slice 10); and verbatim agent_99 work-area domain acceptance, whole-value
CAS, pending→ready version bump, display-name rename preserving version,
and positive-version tombstone (Slice 2). The pricing-pilot fixture is a
ready-made input for the validator's tests.
