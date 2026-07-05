# Machine API v1 and the Persona projection: two consumers, one ledger

Status: non-canonical brainstorming — operator-driven need (2026-07-05).
Sequencing: after project-concept.md (its vocabulary — project, work area,
policy — is the addressing scheme this API exposes).

## Need

The orchestrator will be consumed by agent_99 in two radically different
ways, and neither is the current panel:

1. **Machines** (agent_99's local executor adapter): need stable schemas,
   event cursors, typed states — precise, complete, boring.
2. **The Persona** (agent_99's Brain): a small-model (codex-mini / sonnet
   class), human-voice companion. It is NOT an analysis agent. It must never
   process large JSON or reconstruct state from event streams. What it needs
   is a handful of short sentences it can relay in character:
   "The milestone you ordered is going well, roughly 90%. There were a couple
   of disputes between codex and claude; both resolved cleanly."
   "We're about to launch the next LPC milestone."

Division of labor doctrine (design anchor): the **orchestrator** produces
deterministic truth; the **Persona** provides voice and relationship on top
of pre-digested facts; **deep analysis on demand** is a big-model assistant
job, never the Persona's. Feeding the Persona anything heavier than a digest
is a design failure, not a tuning problem. Escalation path: the Persona may
COMMISSION a deep report by asking a governed big-model CLI agent (via the
executor) to read the machine API / ledger and write the analysis — the
Persona relays conclusions, it never does the digging.

## Machine projection (build-now checklist)

All additive to `service.py`; none touches driver.py's control loop or
state.py's ledger:

1. `GET /api/runs/<id>/events?since=<seq>` — cursor pagination (monotonic
   `seq` already exists in the ledger).
2. `api_version` in every response; typed error codes
   (`{"error": {"code": ..., "message": ...}}`) replacing prose-only errors.
3. `GET /api/health` → `{api_version, orchestrator_rev, home, detected CLIs}`.
4. File-based bearer token (`~/.impl_roadmap/token`) required on mutating
   routes — "localhost, no auth" stops being a boundary once another local
   app can drive full-permission CLI runs.
5. `external_ref` accepted on `POST /api/runs`, stored in the registry,
   filterable on `GET /api/runs` — deterministic find-or-attach for adapters.
6. Derived `attention` field in run status:
   `running | waiting_auto_resume | needs_operator | closed | failed`.
7. Per-run `autoresume: false` launch option honored by the guard (a
   lease-governed run must not be resurrected after its lease is released).
8. SCHEMAS doc freezing the public shapes (`run_status`, `summary`, `story`,
   `events`), including the naming note: API `workspace` = work-area
   `primary_root` (alias added), per project-concept.md.

Deferred deliberately: MCP wrapper, SSE/push, worker sandbox-rung matrix,
lease/audit wiring, any non-localhost binding.

## Persona projection

`GET /api/runs/<id>/digest` and `GET /api/projects/<slug>/digest` return a
few short sentences of plain language. Properties:

- **Deterministic, template-generated from the ledger** — same doctrine as
  the generated milestone records: no LLM in the loop, so the digest cannot
  hallucinate and cannot disagree with the state. A small Persona model can
  safely rephrase it in character because the facts arrive pre-verified.
- **Content**: current phase in human terms; rough progress (derived from
  sealed/total units and round counts, stated as approximate); notable
  events since the last digest — disputes (contested findings/adjudications)
  and how they ended, typed failures and their auto-resume plan; what is
  expected next. Nothing else.
- **Path-free and id-free** (unit names and family names are fine; absolute
  paths, seqs, raw JSON are not).
- **Bounded**: hard cap on length; the digest is a paragraph, not a report.
- Optional `since=<seq>` so the adapter can ask "what changed since I last
  told the human?" and get only the delta narrative.

Example target output (run digest):
"Slice 2 is in review after a fix round. Progress is roughly 80% — 1 of 2
slices sealed. Earlier today codex and claude disputed the relay design; the
operator adjudicated and the fix is being applied. Next: a delta review,
then the seal attempt."

## Non-goals

- No LLM summarization inside the service — templates only.
- No push channel to the Brain; the adapter polls digests and decides what
  to surface.
- The machine projection is not weakened or replaced by the digest — two
  projections, one ledger, different consumers.

## Constraint

Canon changes run the canon's own full milestone cycle — uniform depth, no
fast paths.
