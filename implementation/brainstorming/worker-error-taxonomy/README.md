# Worker Error Taxonomy, Raw-Output Links, and Scheduled Auto-Resume

Status: non-canonical brainstorming (evidence, not authority). To be
refined with the operator before any implementation; the implementing
change records Adopt / Revise / Reject against this note.

## Motivation (all from live incidents)

- A logged-out claude CLI returned `Not logged in · Please run /login`
  twice; the driver saw only "no valid JSON object found" and killed the
  run. Diagnosis required shelling into `.orchestrator/raw/*-protoerr*`.
- Quota windows are a known recurring pause (Codex r18 in Agent99 M28's
  manual era recorded "usage limit with concrete resume time 00:37").
- CLIs intermittently return service-busy/overloaded responses and plain
  network failures; today every one of them is an undifferentiated
  protocol failure that permanently fails the run (now resumable, but only
  by hand).

## Goals

1. The operator can see WHAT the LLM actually returned, from the panel.
2. Infra failures are classified into a closed taxonomy and the driver
   reacts deterministically per type — including scheduling its own
   resume when the error names a reset time.
3. The classifier can NEVER block or worsen an already-failing run.

## Non-goals

- No auto-retry of content-level failures (a worker that produced wrong
  JSON twice stays a failure; the repair-retry already covers the honest
  case).
- No classifier authority over content: it picks from an enum and
  extracts a timestamp, nothing else.

## Error taxonomy v1

| type | examples / detection seeds | driver action | operator surface |
|---|---|---|---|
| `login` | `Not logged in`, `Please run /login`, `401`, `authentication` | fail typed; NO repair-retry (pointless) | banner: "run `claude /login`" + Resume button |
| `quota` | `usage limit`, `quota`, `resets at HH:MM`, `try again at` | fail typed with `resume_at` when extractable; service auto-resumes at that time (cap + jitter) | badge "QUOTA — auto-resume 15:00"; cancelable |
| `network` | `ENOTFOUND`, `ECONNREFUSED`, `getaddrinfo`, `fetch failed`, `could not connect`, DNS errors | short in-place retries (N, backoff) BEFORE failing; then fail typed with near-term `resume_at` (e.g. +5–15 min, capped) | badge "NETWORK — retrying / auto-resume" |
| `busy` | `overloaded`, `529`, `503`, `Service Unavailable`, `server busy`, `capacity` | same shape as `network`: short backoff retries, then typed failure with near-term auto-resume | badge "SERVICE BUSY — auto-resume" |
| `timeout` | already a distinct RunnerError | keep current semantics; fold into the typed record | badge "TIMEOUT" |
| `unknown` | anything else | today's behavior: fail with explanation | banner + raw links |

Open sub-question: `rate_limited` as its own type vs a `busy` flavor with
short backoff vs a `quota` flavor without reset time. Lean: flavor of
`busy` (transient) unless a reset time is present (then `quota`).

## Classification chain (non-blocking by construction)

1. **Deterministic pattern table first** — regex/substring seeds above;
   offline, instant, free. Runs on the raw output (and stderr) of the
   FAILED attempt, before any repair-retry is issued: infra-class matches
   skip the repair-retry entirely (the model never saw the prompt; a
   retry cannot help).
2. **Opposite-family LLM classifier as fallback** for non-matching noise:
   closed-enum JSON contract
   `{"error_type": <enum>, "resume_at": iso8601|null, "evidence": "..."}`,
   validated like every worker contract; one attempt, short timeout,
   cheap model tier.
3. **Plain failure as final fallback** — classifier CLI dead/quota'd/
   garbage output → today's behavior, untouched. Correlated failures
   (both CLIs down, network out) land here by design.

Pattern graduation: `unknown`s and LLM-classified cases are recorded in
the ledger; recurring ones get promoted into the deterministic table.
The taxonomy grows from evidence, not from speculation.

## Scheduled auto-resume

- `state.failure` gains `type` and `resume_at` (extends the resume
  feature shipped after the login incident).
- The service (long-lived) scans the registry for failed runs with due
  `resume_at` and calls the existing resume path. Caps: max K auto-resumes
  per failure type per run, then operator. Jitter to avoid herds.
- Panel: typed badges with countdown; auto-resume cancelable; Resume
  button remains for manual cases (`login`, `unknown`).
- CLI-only runs (no service): `resume_at` is recorded; `driver resume`
  honors it or `--force` overrides.

## Raw-output links (observability)

- Every round/seal-half already records `raw_path`; protocol failures
  save both attempts (`-protoerr1/2`) but the failure record does not
  reference them → add the paths to the failure record.
- `GET /api/runs/<id>/raw/<round-id>` (localhost, read-only, path
  restricted to the run's `.orchestrator/raw/` dir — no traversal).
- Panel: round chips and seal halves link their raw; the failure banner
  links the protoerr raws directly. Truncated view with "open full".

## Content-discipline failures (added 2026-07-05, from the M164 incident)

A second family, DISTINCT from infra errors: the CLI worked and its
output is contract-valid, but a claim contradicts mechanical reality.
No classifier needed — the driver identifies these deterministically —
and blind auto-resume is WRONG for them (a plain resume can restore
into the state that re-fires the same check instantly).

| type | example | right reaction |
|---|---|---|
| `phantom_fix` | fixer disposes 'fixed' with an empty worktree delta (M164 fix19: supplied suite_command in JSON, edited nothing) | do not fail the run on the FIRST offense: discard the phantom round, re-run the fixer once (mirror of the JSON repair-retry); fail on the second. If failed anyway, typed resume restores to FIXING, never delta_review |
| (future) | tamper by report-only worker | already handled in-driver (restore + invalidated round) — listed as the family's precedent |

Design rule extracted: every failure type carries its own resume
target and retry budget; "resume" stops being one-size-fits-all.

## Open questions for the operator

1. Retry counts/backoff for `network`/`busy` before the typed failure
   (proposal: 3 tries, 10s/30s/60s), and the near-term `resume_at` window.
2. Auto-resume caps per type (proposal: quota unlimited-until-window-moves,
   network/busy 3, then operator).
3. Should consultations run BY workers (fixer-side dialogues) report infra
   errors through the same taxonomy? Today they surface as worker
   `blocked_reason` prose. Proposal: yes, same enum inside the consultation
   result contract.
4. Classifier model tier (cheap/fast vs default) and timeout.
5. Desktop notification on operator-action types (`login`, capped-out
   auto-resumes)?

## Evidence pointers

- LPC N30 run failure: `.orchestrator/raw/skeleton-claude-r1-protoerr{1,2}.txt`
  ("Not logged in · Please run /login").
- Agent99 M28 review-log skeleton section: Codex r18 quota pause with
  concrete resume time (the canon's quota rule precedent).
- Resume feature: orchestrator commits `e2e6187`, `fd70d0f`.
