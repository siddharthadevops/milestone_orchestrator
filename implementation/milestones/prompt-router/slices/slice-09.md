# Slice 09 — Anchored readiness and session seal

## Register 1 — INTENT (lay language)

### What this slice builds

Repository-backed Brainstorming closes on repository facts, not on a proposal
or a later application. Each accepted turn records the actual full Git revision
left by its Slice 08 completion boundary. A discussion seat may also return
`ready: true`; that readiness belongs only to that seat at that revision.

Initial Position, Contrary Position, and Dante still complete the ordered pass.
Dante asks but never readies. At the end of the pass, the session closes when
the latest readiness of every discussion seat is true at the same current
revision. If any accepted turn or preserved read-only plan change advances
HEAD, the session first advances to that revision and all readiness from the
older revision ceases to count. A read-only-invalidated attempt adds no turn,
and the same seat runs again against the new HEAD.

The terminal write appends the final turn and the success result atomically.
Exhausting the configured final pass without common readiness records failure
in the same way. Repository sessions never enter proposal, vote, closure-call,
or production-effect stages.

On success, delivery is exactly the Git range from the charge's committed
`pre_session_commit` to the sealed common-ready revision. HEAD must still equal
that accepted revision. Producer tasks consume the already-committed result
directly; slice-note production additionally requires its planned path to exist
at that revision. A successful rethink applies nothing and resumes the same
ordinary milestone stage with a fresh worker call against the resulting repo.

### Ownership and boundary

Owned here are repository coordination initialization, turn readiness, revision
advance without a turn after the Slice 08 read-only exception, atomic terminal
seal, repository lifecycle closure, Git-derived A..B handoff, direct producer
completion, and fresh post-rethink re-entry.

Slice 10 owns comparing the canonical blocks at A and B, computing any wipe
boundary, persisting its account, and freezing scheduling. Slice 11 owns the
single merge-repair handoff. Slice 14 physically removes the now-unreachable
standalone proposal/vote/application implementation.

### Guarantee posture

- **Strict readiness identity.** Only Initial and Contrary readiness counts;
  each seat's latest accepted boolean is bound to one full Git SHA. Dante has
  no readiness field.
- **Strict revision invalidation.** Advancing the accepted Git revision makes
  every readiness on a different revision ineffective, including a plan-only
  commit preserved from an invalidated read-only attempt.
- **Strict ordered seal.** The full roster pass, including Dante, finishes
  before readiness is evaluated. The final turn and terminal result are one
  CAS successor; there is no intermediate approved-but-running state.
- **Strict repository delivery.** Success exposes only
  `source_base_revision=pre_session_commit` and
  `accepted_revision=closed_ready_HEAD`, with current HEAD equal to B. No
  retained target bytes, proposal, vote, apply, or landing step exists.
- **Strict fresh re-entry.** A worker that requested rethink is spent. After a
  successful session the same ordinary stage admits a new task; implementation
  discards its pre-rethink attempt snapshot.
- **Fail closed, no speculative recovery.** Missing or inconsistent declared
  revisions stop at their consumption boundary. This slice adds no parser,
  retry engine, backup, compatibility lane, semantic detector, or protection
  against arbitrary Git/LLM damage.

### Non-goals

- No plan diff, wipe/requeue/checkpoint account, scheduling freeze, repository
  surgery, or merge repair; Slices 10–11 own those consequences.
- No suite checkpoint or cadence; Slices 12–13 own them.
- No migration of standalone or pre-activation sessions. Their existing
  retained-target lifecycle remains readable until Slice 14 retirement.
- No inference from markdown, readiness prose, commit messages, or target
  content. Only registered envelope fields and Git revisions decide the seal.

### Acceptance

The focused gate proves repository initialization stores A without capturing a
target copy; internal and automatic-Dante turns use the revision returned by
their actual completion boundary; a new revision invalidates old readiness;
Dante runs before closure; the final turn and result are atomic; producer
delivery bypasses production effects; and rethink returns to a fresh ordinary
call with no continuation or application.

## Register 2 — PINNED FACTS (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Repository readiness | Discussion `ready` is a boolean bound to the actual post-attempt full Git SHA; a later SHA invalidates earlier readiness | `goal.md:203-220`; accepted amendment A3 | touch repository coordination and turn acceptance; do not infer readiness from prose or events |
| Questioner ordering | Dante completes the ordered pass and never readies; seal evaluation follows that pass | `goal.md:214-220,285-286`; canonical Slice 09 intent | touch repository lifecycle only; do not add a vote or extra closure call |
| Seal | Common readiness at current HEAD atomically closes; final round without it atomically fails | canonical Slice 09 intent; existing bounded session rounds | touch one CAS successor; do not leave an approved running state |
| Delivery | `A=pre_session_commit`, `B=closed_ready_HEAD`; HEAD equals B and close applies nothing | `goal.md:224-243`; accepted amendment A3 | expose the committed range; do not retain target bytes, copy, apply, or land |
| Producer | A successful repository session is the completed producer task; draft-note path must exist at B | canonical Slices 08–09; `goal.md:224-227` | bypass production effect; do not create a second author call |
| Rethink | Session edits are already in Git; terminate the spent origin and re-enter its same ordinary stage fresh | accepted amendment B1 and operator rethink law | remove continuation/application on repository handoff; preserve stage queues and clear stale implementation snapshot |
| Later ownership | Plan consequences S10, repair S11, suite S12–13, physical legacy deletion S14 | canonical slice plan | do not implement downstream machinery early |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_session_repository_seal orchestrator.tests.test_session_repository_turns orchestrator.tests.test_session_call_cutover orchestrator.tests.test_brainstorming_state orchestrator.tests.test_brainstorming_coordination orchestrator.tests.test_brainstorming_closure orchestrator.tests.test_brainstorming_api orchestrator.tests.test_brainstorming_tasks`

| observable claim | named check | pass condition |
|---|---|---|
| Repository initialization has no retained target | `test_repository_initialization_writes_no_target_snapshot` | Coordination begins at A and no target-revision blob is written. |
| Readiness follows actual Git revision | `test_new_revision_invalidates_every_prior_readiness` | B readiness does not count after C; the seat due and ordered roster remain correct. |
| Read-only plan preservation advances without a turn | `test_plan_only_invalidation_advances_revision_without_a_turn` | The plan-only commit becomes current, prior readiness is void, and no completed turn is appended. |
| Dante precedes the seal | `test_repository_seal_waits_for_questioner_and_is_atomic` | Initial and Contrary readiness alone remain running; Dante's unchanged turn produces the sole terminal successor. |
| Delivery is Git-native | `test_terminal_handoff_is_exact_repository_range` | Handoff exposes A and B, HEAD equals B, and no retained target or apply payload exists. |
| Producer and rethink have no application call | `test_repository_producer_finishes_without_effect` and `test_repository_rethink_reenters_fresh_without_application` | Producer task succeeds directly; rethink removes its wait and stale implementation snapshot without continuing the origin session. |

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Without this cut, already-committed session work still enters the retired ballot/proposal/application route, and readiness can refer to copied target bytes rather than the repository revision under review. | `goal.md:203-227`; canonical Slice 09 intent |
| machinery | One repository variant of the existing coordination record, one atomic turn/seal successor, and one A..B handoff are sufficient. | `orchestrator/brainstorming.py`; `orchestrator/brainstorming_coordination.py`; `orchestrator/brainstorming_milestone.py` |
| consumers_touched | Repository session creation/lifecycle, internal and automatic external turns, task completion, producer wait, and rethink wait. | Slice 08 cutover seams |
| cheaper_alternative | Reusing the accepted turn CAS and Git SHAs is smaller than adapting retained proposals, ballots, and production effects to pretend they still own delivery. | canonical Slice 09 intent |
| cost | A bounded repository branch leaves standalone behavior in place until global retirement; no new service, parser, recovery subsystem, or compatibility migration. | Non-goals and Verification Contract |
| threat_model | Normal routed turns and the declared read-only block exception may advance HEAD. Invalid config, bad replies beyond the existing correction, arbitrary Git sabotage, and model misbehavior fail closed rather than expanding the design. | amendments A1, A3, A4, A7, A8 |
| verification | Focused state, coordinator, lifecycle, handoff, producer, and rethink tests prove the normal path and the one declared invalidation path. | Verification Contract |
