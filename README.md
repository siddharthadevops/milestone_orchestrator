# impl_roadmap

Deterministic orchestrator for AI-led implementation milestones: a
hardcoded driver runs the whole canon flow — skeleton → slice notes →
implementation, adversarial review rounds between CLI agent families,
review/fix separation, double seals, mechanical verification gates —
with JSON worker contracts and an append-only run ledger. Sequencing and
bookkeeping live in tested code; only content judgment is delegated to
the LLM workers.

- **[orchestrator/README.md](orchestrator/README.md)** — how the system
  works and how to run it (panel: `orchestrator/panel.sh` →
  http://127.0.0.1:8700).
- **[WORKSPACE.md](WORKSPACE.md)** — the workspace contract: how any
  repository becomes a milestone workspace, the per-milestone layout,
  and the no-vendoring doctrine.
- **implementation/** — this repository's own milestone bookkeeping.

## History

The manual textual canon (v0.x, `canon/` + `templates/`) that this
system replaces lived here until it was retired on 2026-07-05; git
history keeps it. Its refined content rules — altitude, reuse gate,
evidence discipline, consultation caps — were ported verbatim into the
worker prompts (`orchestrator/prompts.py`). Consumer repositories no
longer pin or vendor anything: the process travels in the orchestrator,
and every run records the orchestrator commit that executed it.
