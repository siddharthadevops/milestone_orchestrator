# Slice 08 — Repository-backed session turns

## Register 1 — INTENT (lay language)

### What this slice builds

Milestone Brainstorming now works directly in the project's Git repository.
Before a producer or rethink session opens, the driver commits the current
workspace and records that full revision as `pre_session_commit`. There is no
session copy, detached work area, proposal repository, or later landing step.

Every physical seat attempt starts from one proportional repository snapshot:
current branch identity and HEAD, index tree, Git-visible work-tree tree, and
the canonical-plan anchor. Initial Position is the editor. After its process is
quiescent, the driver validates the canonical block and commits the complete
delta on the current branch; an empty delta creates no commit. A contract
correction is another physical attempt and receives its own fresh snapshot.

Contrary Position and Dante are read-only. An unchanged attempt may be
accepted. An ordinary mutation is restored and the reply does not count. A
valid changed canonical block is the sole exception: all mutations are
restored, only that block is reinserted into the pre-call skeleton and committed,
the plan anchor/projection refreshes, and the reply still does not count. An
invalid block restores the snapshot and ends the session path with an error.

### Ownership and boundary

Owned here are the pre-session repository checkpoint, durable repository
context carried by the session, per-physical-attempt snapshot/completion,
driver-owned author commits, read-only restoration, block-only preservation,
and immediate canonical-plan anchor/projection refresh.

Slice 09 owns readiness at HEAD, invalidating readiness after commits, session
close, Git-derived delivery, and retirement of proposal/vote/application
mechanics. Slices 10–11 own the consequences of a changed projected plan and
accepted-range reconciliation. Slice 12 reuses the read-only boundary for suite
checkpoints. Slice 14 removes the remaining standalone/legacy target path.

### Guarantee posture

- **Strict one-repository boundary.** Every milestone session receives the
  project workspace, state path, canonical skeleton path, and one committed
  `pre_session_commit`. Missing repository context refuses the session.
- **Strict per physical attempt.** Snapshot occurs immediately before provider
  dispatch and completion immediately after quiescence, before reply parsing;
  the one contract correction crosses the same boundary afresh.
- **Strict editor ownership.** Initial Position may edit any governed repository
  path. The driver stages and commits its complete valid delta; the seat never
  supplies delivery metadata or performs bookkeeping. Empty delta means no
  commit.
- **Strict read-only seats.** Contrary and Dante must leave HEAD, index, and
  governed work-tree bytes unchanged. Mutation invalidates the reply. Only one
  valid changed canonical block survives restoration, as one driver commit.
- **Strict plan observation.** Every completed physical attempt compares the
  canonical block with the pre-call anchor. Invalid editing or read-only plan
  bytes restore and fail; valid changed bytes anchor and project before another
  seat can run.
- **Fail closed, no speculative recovery.** A materially incomplete boundary or
  interrupted repository operation stops for the operator. This slice adds no
  retry, cache, backup, alternate ref, last-known-good lane, or cross-run repair.

### Non-goals

- No readiness ledger, common-ready revision, session seal, close rule, ballot
  retirement, application retirement, or delivery derivation; Slice 09 owns it.
- No plan diff, wipe boundary, requeue account, scheduling freeze, or merge
  repair; Slices 10–11 own them.
- No suite checkpoint; Slice 12 reuses this boundary.
- No protection against malicious seats, arbitrary Git commands, unrelated
  refs/reflogs/stash/config, ignored-file damage, machine failure, or an LLM that
  disregards its role. A failed asserted boundary is an error, not a new system.
- No repository parser, prose detector, path allow-list, compatibility lane, or
  migration of pre-cutover sessions.

### Acceptance

The focused gate proves the real workspace is used, the pre-session commit is
persisted, editor deltas advance HEAD through driver commits, empty editor turns
do not, read-only ordinary mutations restore and rerun, a valid plan-only edit
survives alone and reruns, invalid plan bytes fail after restoration, and both
the initial call and contract correction receive independent snapshots.

## Register 2 — PINNED FACTS (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Session repository | Exactly the project repository; the driver commits it before opening and records full `pre_session_commit` | `skeleton.md`, Slice 08 intent; `goal.md:198-212` | touch milestone session creation/context; do not create a work area, copy, snapshot repository, or landing call |
| Physical-call boundary | Branch/HEAD, index, Git-visible work tree, and plan anchor are captured immediately before every seat attempt including correction | `skeleton.md`, Plan boundary and projection; `goal.md:203-212` | reuse proportional Git/canonical primitives; do not capture unrelated Git plumbing |
| Editor completion | Initial Position's valid complete delta is committed by the driver; empty delta creates no commit | `goal.md:195-206` | touch prepared-call completion; do not accept reply delivery fields or seat-authored bookkeeping |
| Read-only completion | Ordinary mutation restores and invalidates; one valid changed canonical block is reinserted alone, committed, projected, and also invalidates | `skeleton.md`, Read-only seat boundary; `goal.md:195-197` | touch Contrary/Dante completion and ordinary rerun; do not preserve any other mutation |
| Later ownership | Readiness/close are S09; plan consequences S10–11; suite S12; global retirement S14 | canonical slice plan | do not widen this cut to final session closure or recovery |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_session_repository_turns orchestrator.tests.test_session_call_cutover orchestrator.tests.test_brainstorming_execution orchestrator.tests.test_brainstorming_coordination orchestrator.tests.test_canonical_plan orchestrator.tests.test_gitops`

| observable claim | named check | pass condition |
|---|---|---|
| Session opens on a committed real-repo base | `test_driver_admits_the_planned_producer_charge` | Pending workspace bytes are committed once and the charge records the resulting full HEAD plus state/skeleton coordinates. |
| Editor physical calls advance the repository | `test_editor_turn_commits_and_empty_turn_does_not` | A changed call creates one driver commit; an empty call preserves HEAD; both refresh plan observation. |
| Correction is a fresh repository attempt | `test_contract_correction_has_a_fresh_repository_snapshot` | First and corrected provider attempts complete independently and the second begins at the first attempt's accepted HEAD. |
| Read-only mutation never rides with a reply | `test_read_only_turn_restores_and_reruns` | Ordinary changes are removed, HEAD/index/work tree match the snapshot, and no completed turn is recorded. |
| Only a valid plan block may survive | `test_read_only_plan_change_preserves_only_the_block` | Other changes disappear; the block alone is committed/projected; the same seat remains due. Invalid plan bytes restore and fail. |

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Without this cut, Brainstorming still edits a private target/copy and can report agreement over bytes that never became the milestone repository history. | `goal.md:187-226`; canonical Slice 08 intent |
| machinery | One repository context and one prepared-call completion boundary reuse existing Git snapshots, restoration, canonical extraction/validation, and commits. | `orchestrator/gitops.py`; `orchestrator/canonical_plan.py`; `orchestrator/session_calls.py` |
| consumers_touched | Producer and rethink creation, routed seat preparation, participant physical attempts, internal turns, and automatic Dante turns. | `orchestrator/driver.py`; `orchestrator/brainstorming_tasks.py`; `orchestrator/brainstorming_milestone.py`; `orchestrator/brainstorming_execution.py`; `orchestrator/brainstorming_coordination.py`; `orchestrator/brainstorming_lifecycle.py` |
| cheaper_alternative | Target-only snapshots cannot commit multi-file/code edits or preserve the one plan-block exception. The existing repository primitives are the smallest sufficient boundary. | canonical Slice 08 intent and pinned facts |
| cost | One bounded adapter plus consumer tests; no service, daemon, alternate repository, retry system, migration, or compatibility state. | Non-goals and Verification Contract |
| threat_model | Normal seats may edit repository bytes; read-only roles are structurally enforced after successful quiescent attempts. Arbitrary Git sabotage, bad models, malformed external state, and machine failure stop the path and are not repaired here. | accepted amendments A1, A7, A8; skeleton Guarantee posture |
| verification | Focused repository fixtures prove commits, restore, plan-only preservation, correction freshness, and rerun without Cartesian failure simulation. | Verification Contract |
