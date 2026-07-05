# Workspace layout — impl_roadmap

How any repository becomes a valid workspace for impl_roadmap milestones.
This is the document to hand to an agent with "prepare this repo" or
"read the milestone structure": everything below is the whole contract.

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
