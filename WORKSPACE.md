# Workspace layout — impl_roadmap

How any repository becomes a valid workspace for impl_roadmap milestones.
This is the document to hand to an agent with "prepare this repo" or
"read the milestone structure": everything below is the whole contract.

## What is a milestone

A milestone is **one coherent, bounded increment** of a project — a single
goal small enough to plan, build, and review as a unit — **not** the whole
project. A project is delivered as a **sequence of milestones**, each
opened, driven, and closed on its own.

A milestone runs as one **skeleton** unit, then per slice a **slice-doc**
unit and a **slice-impl** unit. The skeleton is a thin planning contract:
it restates the goal, sets the boundary and non-goals, and names a short
table of narrow slices — it does not specify or build them. Each slice is
then documented (its note fixes scope, files, tests, acceptance) and
implemented, and every unit is reviewed and **sealed independently** before
the next. A slice is *the smallest reviewable, approvable, and closeable
delivery unit — one clear intent, one reviewable surface, no unrelated
scope.*

**Sizing, so scope lands right.** A slice aims to stay **under about 500
changed lines** where practical (generated, lockfile, and mechanical
changes do not count; a slice that must exceed it records the reason in its
note) — this is the one size the worker prompts actually pin. As a rule of
thumb a whole milestone is **≤ ~5K lines of code with its docs (≈ up to
~10 slices)**; past that it is **several milestones**, not one giant one.
(The ~5K figure is planning guidance, not a mechanical gate.)

**The two mistakes to avoid — both seen in real reviews:**

- **Do not inflate a project into one milestone.** A skeleton is not a
  licence to specify an entire product and then drive one mega-slice
  through the pipeline. If the work does not decompose into a handful of
  ~500-line slices, it is too big — split it into milestones.
- **Do not fragment cohesive work.** Bundling several roadmap needs into
  one milestone is normal and correct when they form one coherent
  increment: a milestone named `N34+N35+N28+N36` is *one* 8-slice
  milestone, not four, and a milestone may even be a single slice when the
  increment is that small. *Do not split cohesive work artificially.*

Scope is decided by **coherence and reviewable size, not by need-count**:
group what belongs together, keep each slice small, and let the slice count
— not extra milestones — absorb the size.

### Importer repositories: copy this

The doctrine below keeps process text out of consumer repos, but this one
scope definition belongs where a repo's own reviewers can see it (they may
never open this file). Paste the block below into the top prose of your
`implementation/milestones/README.md`, above the machine-maintained marker,
so a reviewer reading only your repo knows what a milestone is:

> **Milestones (impl_roadmap).** A milestone is one coherent, bounded
> increment — planned by a thin *skeleton* into a short table of narrow
> *slices*, each slice documented, then implemented, then sealed on its
> own. A slice is the smallest reviewable, approvable, closeable unit (one
> clear intent, one reviewable surface), aiming under ~500 changed lines; a
> whole milestone is roughly ≤5K lines with its docs (≈ up to 10 slices).
> Bundling several needs into one milestone is normal — do not split
> cohesive work artificially — and a milestone may be a single slice; past
> ~5K lines it is several milestones, not one. Full contract: WORKSPACE.md
> in the milestone_orchestrator repo.

## Doctrine: nothing is vendored, nothing is pinned

The process lives in the orchestrator (this repository — the service and
driver that run milestones), never in the consumer repository. Consumer
repos carry **no vendored canon, no pinned process documents, no process
checklists**. Worker prompts explicitly void any repo-resident process
document, so a leftover vendored canon is at best dead weight (remove
it). Provenance replaces pinning: every run records the orchestrator
commit that executed it in its state (`orchestrator_rev`).

## Preparing a repository (once)

1. The workspace must be the **root of its own git repository** — created
   deliberately (`git init`); the orchestrator refuses non-roots and
   never auto-inits.
2. Nothing else is required. Optional niceties:
   - `implementation/milestones/` may exist already (the driver creates
     its milestone directory on demand);
   - `.gitignore` covering the project's build artifacts — the tamper
     check honors it, so reviewers running the project's own tests never
     invalidate a round with artifact churn.
3. The driver itself force-ignores `.orchestrator/` (runtime state) and
   maintains everything below.

## Per-milestone layout (created and maintained by the driver)

```
implementation/milestones/
  README.md                     # milestone index — machine-maintained
                                # marker block; hand-written prose
                                # around it is preserved
  <milestone-slug>/
    README.md                   # milestone record (status, slices,
                                # units, gates) — GENERATED
    skeleton.md                 # planning contract — worker-authored
    slices/slice-NN.md          # slice notes — worker-authored
    review-log.md               # every round/seal — GENERATED
    adjudications.md            # settled rejections — GENERATED
    closures/slice-NN.md        # per-slice closure — GENERATED
```

GENERATED files carry a marker comment and are compiled from
`.orchestrator/state.json` at every gate — no LLM ever writes them, so
they cannot disagree with the ledger. Worker-authored artifacts
(skeleton, slice notes, the code itself) are ordinary reviewable
content.

The milestone directory name is the slug of the run name given at
launch. The docs directory is configurable per run (`docs_dir` in the
launch config) for repos with a different convention (e.g. a nested
`elixir/implementation/milestones/{slug}`); `"docs"` selects the legacy
flat layout of pre-2026-07 runs.

## Runtime files (git-ignored, operator-owned where noted)

```
.orchestrator/
  state.json        # append-only run ledger — the single source of truth
  raw/              # every worker's raw output
  amendments.json   # operator: binding mid-run notes (panel-editable)
  acts.json         # operator: who drafts/implements/fixes, model/effort
  current.json      # cosmetic in-flight marker
```

## Running

Milestones launch from the panel (`orchestrator/panel.sh` in this repo →
http://127.0.0.1:8700) or the CLI (`python3 -m orchestrator.driver init
--goal ... --name ... --workspace ... && ... run`). Gate history lands
as one commit per sealed unit plus a final `Close milestone` commit; the
index row flips to `closed` in the same commit.
