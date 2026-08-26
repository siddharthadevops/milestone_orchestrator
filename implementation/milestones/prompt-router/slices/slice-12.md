# Slice 12 — Read-only suite checkpoint

## Outcome

Replace the driver's in-process full-suite execution at a due pre-seal
boundary with one fresh routed `suite_checkpoint@workspace` agent call. The
call is staffed by `implement` seat 1 with material `code`; it either runs the
ordered operator commands or judges the repository-owned evidence and selects
the complete suite itself.

This slice owns the physical call, its contextual reply contract, and the
read-only repository boundary. Slice 13 owns cadence and the failed-checkpoint
fix/rerun lifecycle. Slice 14 removes the now-unreachable legacy command and
shell-verification lanes and activates the new schema after the driver drain.

## Authority and scope

- The configured command source is only the current `verification` list.
  Historical discovered or fixer-corrected commands do not feed this route.
- An absent or empty configured list means discovery by the checkpoint LLM.
  A malformed configured value fails closed before dispatch; there is no
  repair or fallback for operator configuration.
- Configured commands are passed as one JSON array so command boundaries are
  not inferred from prose. The contextual validator requires exact equality.
- Suite completeness, command suitability, and repository evidence are LLM
  judgments. The driver does not classify command text, documentation prose,
  diagnostics, or evidence semantics.
- Structural validation remains mechanical: result shape, configured-list
  equality, attempted prefix, exit codes, authority source, existing evidence
  paths, and failure-account agreement.
- Current operator amendments, project context, safeguards, prompt-set
  selection, and contract correction are resolved afresh for every physical
  attempt. No command or prompt result is cached.

## Repository boundary

Immediately before every provider dispatch, reuse the canonical-plan call
boundary to checkpoint pending work and capture HEAD, index, governed work-tree
bytes, and the anchored canonical block.

After the provider returns and before validating its JSON:

1. If the repository is unchanged, the reply remains eligible.
2. If ordinary governed bytes changed, restore the snapshot and discard the
   returned status. The checkpoint remains due for a fresh call.
3. If the only preservable change is a valid canonical-plan block, restore all
   other mutation, commit that block alone, observe the accepted A..B range,
   discard the returned status, and require a fresh call on the new unchanged
   revision.
4. If that accepted range computes a wipe boundary, the existing Slice 10–11
   reconciliation freezes scheduling and runs before any checkpoint retry.
5. An invalid canonical block or failed restore is a terminal boundary error;
   this slice adds no recovery machinery.

Only an unchanged `passed` or `no_suite` result may satisfy the due pre-seal
checkpoint. `failed` evidence is recorded intact for Slice 13. `blocked` stops
for the operator.

## Runtime cut

| Surface | Slice 12 rule | Deferred owner |
|---|---|---|
| Route | `suite_checkpoint@workspace` × `agent_call` × `code` | — |
| Staffing | existing `implement` seat 1, freshly resolved | — |
| Prompt | current set, amendments, project law, checkpoint reason, optional configured command array | — |
| Reply | routed `suite_checkpoint_result` plus applicable project extensions | — |
| Execution | one LLM call; the driver never runs the suite command | legacy deletion: Slice 14 |
| Mutation | restore ordinary mutation; preserve valid block only; invalidate status | — |
| Success | stable `passed` or `no_suite` may seal | cadence completion: Slice 13 |
| Failure | preserve complete `failure_account` without sealing | synthetic P1/fixer/rerun: Slice 13 |
| History | no discovered/corrected command is reused | state-field retirement: Slice 14 |

## Verification

Focused tests must prove:

- configured and discovery prompts bind the same contextual validator;
- configured command arrays must echo exactly, while discovery authority cites
  existing repository-relative paths;
- no lexical/no-op command parser participates in validation;
- project safeguard fields can be mounted without colliding with checkpoint
  result fields;
- every physical attempt receives a fresh prompt and repository snapshot;
- unchanged `passed` and `no_suite` results are accepted;
- ordinary mutation is restored and its result is discarded;
- a valid block-only edit is preserved and its result is discarded, with the
  accepted A..B range routed through the shared reconciliation observer;
- neither historical `suite_command` state nor fixer certification supplies
  the command plan.

## Explicit non-goals

No parser for command meaning or LLM prose; no retry beyond the ordinary
single contract correction; no cache, command-discovery store, backup,
watchdog, compatibility lane, or recovery for malformed replies, provider
failure, arbitrary Git damage, missing files between runs, or model
misbehavior. Those cases fail at their existing boundary or stop for the
operator.
