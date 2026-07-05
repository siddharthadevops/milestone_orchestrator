# Codex Timeout And Agent Self-Review

Status: abandoned (2026-07-05) — superseded by the deterministic
orchestrator pivot (worker timeouts removed entirely; fresh-context review
is structural in the reviewer/fixer separation). Retained as a historical
record; the canonical-basis links below reference the removed manual canon.

Planned reviewed release: `v0.10.0`.

## Boundary

S9 hardens Codex review runtime and post-fix preflight discipline by giving
Codex reviews a longer watchdog and making pre-relaunch self-review a
fresh-agent loop.

## Canonical Basis

- Common process: [`../../../canon/process/README.md`](../../../canon/process/README.md)
- Review runner: [`../../../canon/process/codex-review.md`](../../../canon/process/codex-review.md)
- Local context: [`../../local-context.md`](../../local-context.md)
- Prior reviewed release: `v0.9.0`

## Reuse Posture

- Checked: Review/Seal Convergence, Finding Verification, Watchdog, Prompt
  Shape, and the S8 review-fix convergence rules.
- Reused or extended: existing Codex CLI watchdog, pre-relaunch self-review,
  local-inspection requirement, no-memory finding verification, and durable
  review-log evidence.
- New machinery, if any: a fresh agent for pre-relaunch self-review, necessary
  because same-thread checks can miss defects later found from fresh context;
  no new formal reviewer family, gate, script, or seal half.
- Compatibility: consumers keep the same `VERDICT: 0` gates, review order,
  seal independence, no-edit prompts, worktree checks, and closure rules.
- Local context: this product-neutral canon repo records no support order and
  no sensitive local exclusions.

## Shared Contract

Normal Codex review rounds and Codex seal halves have a 15-minute watchdog.
Codex disagreement dialogues remain separate evidence and follow their own
dialogue rules. After review findings are fixed, the orchestrator must run
pre-relaunch self-review through a fresh, report-only agent that checks the
pending diff against current code, docs, tests, commands, and local state; it
must not rely on thread memory, operator summaries, or intended behavior.
Corrections fold into the same fix pass and the loop repeats until the
preflight is clean. This remains orchestration only, not formal review
evidence.

## Non-Canonical Planning

- Named planning material: recent Codex review timeouts; operator-observed
  same-thread self-review false negatives; fresh-thread findings after manual
  review copy/paste; small P3 fixes introducing higher-severity regressions.
- Adopt / Revise / Reject: adopt 15-minute Codex watchdogs, fresh-agent
  pre-relaunch self-review, current-artifact verification, and loop-until-clean
  preflight. Reject same-thread memory checks, operator summary checks, and
  treating preflight as formal review evidence.
- Notes: planning material informs process discipline only; canon wording
  remains product-neutral.

## Slices

| Slice | Title | Status | Notes |
|---|---|---|---|
| 01 | Codex watchdog and fresh-agent preflight | planned | Raise Codex watchdog to 15 minutes and require looped fresh-agent self-review before amend/relaunch. |

## Work Log

| Unit | Phase | Status | Review | Commit | Notes |
|---|---|---|---|---|---|
| Skeleton | doc | under seal | Codex r1 clean; Claude r5 clean; seal a4 findings fixed | | Seal a5 due under current watchdog. |

## Current Slice

None until the skeleton is sealed `ready` and committed.

## Continuation

Continue by running the skeleton seal. Draft Slice 01 only after the skeleton
is sealed `ready` and committed.
