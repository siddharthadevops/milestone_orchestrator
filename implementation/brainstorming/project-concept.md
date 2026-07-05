# Project concept: ecosystem-scoped standing safeguards and reuse gates

Status: non-canonical brainstorming — operator-driven need (2026-07-05).
Sequencing: this milestone PRECEDES "skeleton code-first discipline"
(skeleton-code-first-discipline.md) — the discipline's reuse audit consumes
the project machinery defined here.

## Need

Runs are workspace-scoped; real work is ecosystem-scoped. Amendments are
per-run and die with the run; repo docs are advisory prose. Nothing today
carries standing, operator-authored law that binds EVERY run across a family
of related repositories.

Motivating incident (agent_99 M26/M27, 2026-07-01): the implementation
rebuilt ~2,300 lines of chat surface (thread-list/timeline/composer state and
markup) that already existed SEALED in LPC (`life_product_chat` M7,
`life_product_chat_components` M8) — sitting inside agent_99's OWN vendored
submodule at the active pin. The planning docs even contained the verbatim
prohibition "Agent99 MUST NOT invent local chat mechanics or duplicate
LPC/Life behavior" — and it failed anyway, because the docs' LPC inventory
was incomplete: they named only `chat_runtime` and `client`, never the two
packages that got duplicated, so "mechanics" was read as transport-only and
the UI/state layer was rebuilt locally.

Lesson (load-bearing for this design): **shouted prohibitions do not prevent
duplication; mandatory enumerated verification does.** The safeguard is not a
louder warning — it is a procedure: enumerate what the ecosystem already
provides, cite it, and record an explicit adopt/gap/reject decision before
inventing anything.

## Concept

A **project** is a named ecosystem spanning multiple repositories/roots. The
concept is fully generic and operator-defined: nothing about any particular
ecosystem is built in. (`life_prod` = { life, life_product_components,
agent_99, tutor } is an ILLUSTRATION, not a schema — the same machinery must
serve a solo developer with one repo, or a writer whose "project" is a folder
of documents.)

Storage: a **local KV contract compatible with agent_99's workspace
datastore**, so the future fusion is a transport swap, not a data migration
(see "Local datastore contract" below). Operator-owned, service-level
(projects span repos), panel-editable. Workspaces resolve their project
membership at run init; the ledger records the project and each safeguard
the run's workers were shown (`project_safeguard_seen`, mirroring
`amendment_seen`), so every round can be judged against what its workers
knew.

The project record is **workspace-shaped: it adopts agent_99's configuration
architecture literally**, so the two are the same thing from day one rather
than converging later:

- **policy**: the safeguards, as versioned policy objects (id, version,
  enabled, scope, and the contract field each one adds — see gate machinery
  below). These are the future workspace capability policies, in miniature.
- **work_areas**: `[{name, primary_root, additional_roots, description}]` —
  named sets of filesystem roots, exactly agent_99's work-area shape. A run
  launches against `(project, work_area)`: the **primary_root** is the git
  repo the driver owns and executes in; **additional_roots** are read-only
  grants. Reuse sources are additional roots carrying role metadata:
  `{inventory, registry, consumption}` — the directory planners must
  enumerate, the milestone registry to read, and the sanctioned consumption
  model (submodule + path dep, hex, HTTP client...). The ledger records the
  work-area name on every run.
- **defaults** (optional): acts/model preferences, docs_dir convention.

Dual authorship, also adopted from agent_99's design: milestones may be
created by an orchestrating Brain OR by a human directly — both first-class
over the same work areas. The current panel is the prototype of agent_99's
human milestone surface, not a temporary operator hack.

## Convergence with agent_99's workspace architecture

The project concept does not map to agent_99's workspace — it IS agent_99's
workspace architecture, adopted now. agent_99's hierarchy (verified in its
canon): org → **workspace** (the tenancy/policy boundary — capabilities live
here as versioned policy objects) → **work area** (a named SET of filesystem
roots: primary root + additional roots — where execution happens, under
exclusive leases) → executor spawning CLIs at the primary root.

Correspondence (identical shapes, one instance today, shared later):

- orchestrator **project** = agent_99 **workspace** (the policy boundary);
- orchestrator **work_areas** = agent_99 **work areas** (same record shape);
- project **policy** (safeguards) = workspace **capability policy objects**
  (versioned: id + version + enabled + scope) — a safeguard later becomes a
  workspace policy with zero translation.

Design rules that follow: (1) safeguards are versioned policy objects from
day one; (2) the project slug + work-area name are the stable path-free
handles a future agent_99 adapter (or Brain) uses; (3) NAMING COLLISION,
resolve now: what the orchestrator's current API calls `workspace` is a
work-area **primary_root**, NOT a workspace — the machine API's schema doc
states this and grows a `primary_root` alias, so the future adapter is a
rename-free projection.

## Local datastore contract (fusion-ready storage)

agent_99's workspace is a KV datastore (LPC `LifeProductWorkspaces`):
`put/get/cas/list_entries` over binary keys, with a revision-envelope CAS
adapter (`%{revision, value, deleted?}`, monotonic +1, tombstone deletes,
`:absent` sentinel) and per-key-family state machines (work areas live at
`refs/work_area:<name>` as pending/ready/unavailable). The project store
adopts this contract LOCALLY:

- **Same primitives, local backing.** The service stores project data in a
  local KV (file-backed) implementing the same get/put/cas/list semantics,
  the same revision envelope, and JSON-plain, serialization-stable values.
  Fusion later = pumping entries into a reserved namespace of the workspace
  datastore (`milestone_orchestrator/…` — final name TBD, a single
  configurable constant) through the same Client behaviour, revisions intact.
- **Key families**: `refs/work_area:<name>` (identical shape to agent_99's,
  including the pending/ready/unavailable machine — locally, the panel plays
  the Body's declare role and the launcher's validation plays the executor's
  reconcile role, e.g. "primary_root is a git repo root" → ready);
  `policy:<id>` (versioned safeguards); `run:<id>/status` and
  `run:<id>/digest` (projections).
- **Authority is per-family, and OURS is bottom-up.** agent_99's work-area
  family reconciles top-down (server declares, executor confirms) — fine for
  descriptors, which are cheap declarations. The orchestrator's families are
  **local-authoritative**: this machine is the writer of record; after
  fusion the server copy is a visibility mirror (Brain, other devices), and
  server-side edits to our namespace are never auto-applied locally.
- **Durable truth never lives in the datastore at all** — wipe-safety by
  construction: run ledgers stay in `.orchestrator/state.json`, gate history
  and milestone records are committed in the repos (git is the durability).
  The datastore (local now, shared later) holds only descriptors and
  projections. If the server data is ever wiped during development, nothing
  is lost: re-declare work areas, re-pump projections.

## Prompt and gate machinery

1. **PROJECT CONTEXT block** in every worker prompt: ecosystem map +
   safeguards, with the same authority rendering as operator amendments.
2. **Mandatory REUSE AUDIT at planning altitude**: any skeleton/slice note
   scoping a surface for which a reuse source exists must include an audit
   table — per relevant package: enumerate the inventory, read the registry
   rows, and record adopt / gap / reject WITH file:line citations from the
   sibling repo. A missing or uncited audit is a P1 content gap. Recorded
   gaps go to the source's consumer-needs channel, never to local
   reimplementation. (agent_99's retroactive "LPC Coverage Audit" table in
   chat-surface-reuse is the proven prototype of exactly this artifact.)
3. **Review duties**: reviewers may read reuse sources (read-only) to verify
   audit claims; implementing locally what a reuse source already provides,
   without a recorded reject decision, is a P1 duplication finding.
4. **Safeguards compile to CONTRACT FIELDS, not prose.** Proven twice: prose
   prohibitions failed (M26/M27 duplicated despite a verbatim ban), while
   JSON contract obligations worked (suite_command reporting; the phantom-fix
   worktree-delta guard). An LLM fills a required slot far more reliably than
   it obeys a warning — so each project safeguard declares the contract field
   it adds to the relevant worker's REQUIRED output. Two hard rules:
   - **No bare booleans.** `check_lpc: true` is statistically free to fill;
     the slot must demand falsifiable content — enumerations and citations
     (e.g. `reuse_audit: [{source, package, decision: adopt|gap|reject,
     evidence: "file:line"}]`).
   - **Mechanical verification where possible.** The driver validates what it
     can without an LLM: cited paths exist; the enumerated inventory matches
     a real directory listing of the reuse source; missing/short audits are
     rejected at the contract layer (same posture as the no-op suite_command
     denylist). Reviewers verify semantics; the driver verifies existence.
5. **Project contract extensions are declarative JSON.** A policy object
   bundles, versioned together: the prompt block (the instruction the worker
   sees), the contract field it adds (name + per-entry schema + scope: which
   worker kinds / unit kinds it applies to), and its mechanical checks —
   parameters over a CLOSED verifier vocabulary implemented by the
   orchestrator (e.g. path_exists, citation_exists, dir_listing_matches,
   non_empty, enum). Projects compose these primitives; they can never
   inject code or shell. The driver merges the base kind contract with the
   in-scope extensions and validates both in the same repair-retry path as
   the core protocol; the ledger records the policy id+version each worker
   was bound by. A new verifier kind is an orchestrator milestone, not
   project config.

## Panel / service surface

- Project CRUD + safeguard editor (like the amendments card, but standing).
- Launch flow resolves and displays the project for the chosen workspace.
- `GET /api/projects`; run status carries the project name.

Integration dividend: "project" becomes the stable, path-free vocabulary a
future agent_99 capability uses to address this service (project + milestone
+ attention state), aligning with agent_99's Brain boundary where filesystem
paths never cross.

## Non-goals

- No cross-repo writes: reuse sources are read-only during runs; gaps flow
  through consumer-needs notes.
- No vendoring/pinning management: HOW a consumer depends on a source
  (submodule, path dep, hex) stays the consumer repo's decision; the project
  only records what that sanctioned model is.
- Not a monorepo tool and not a build system.

## Constraint

Canon changes run the canon's own full milestone cycle — uniform depth, no
fast paths.
