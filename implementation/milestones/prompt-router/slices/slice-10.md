# Slice 10 — Plan identity and wipe boundary

## Register 1 — INTENT (lay language)

### What this slice builds

Every accepted plan-changing call already leaves a committed Git range `A..B`.
This slice gives that range one consequence boundary. It reads the canonical
plan directly from the skeleton committed at A and B; it never reconstructs
either side from the run projection, reply fields, markdown, or events.
The initial `draft_skeleton` is the sole exception because A has no canonical
plan: its first valid B only establishes the anchor/projection and continues
the ordinary lifecycle, without plan diff or reconciliation.

Slice id is identity and array order is delivery. Descriptive or producer
changes on a retained id, forward appends, and edits confined to work that has
not started require no unwind. Deleting a started id does. Inserting or
reordering at or before started history also does: the first old-plan position
whose id differs is a candidate even when no id was deleted. The earliest
candidate wins once.

When there is no candidate, the accepted anchor and projection at B remain in
force, the range is recorded as accepted with no wipe, and ordinary work
continues. When there is a candidate, the driver persists one open
`accepted_range_reconciliation` containing the original old plan and run
boundaries, A and B, the computed wipe boundary, the units/slices that will be
invalidated and requeued, and the affected checkpoint anchors. Scheduling then
freezes before the source result can advance its unit.

The accepted plan, anchor, projection, work tree, branch, and HEAD remain at B.
Slice 10 performs no reset, checkout, cherry-pick, merge, conflict resolution,
or state invalidation. Slice 11 alone dispatches `merge_repair`, validates its
result, applies the persisted account, and closes reconciliation.

Direct routed calls now expose the same real range as sessions. Before each
physical attempt the driver folds any ordinary pending delta into A. If the
canonical block changes validly, the surviving work tree is committed on the
current branch as B and the anchor moves to B. That physical attempt is
observed immediately, independently of reply validity. A no-wipe change may
continue to the existing single contract correction, whose own attempt starts
from the already accepted B. If that correction opens a wipe, its repair range
still begins at the earliest accepted A of the logical call so the first
attempt's committed delta is not discarded. A wipe freezes before any further
correction is dispatched. Repository sessions reuse their sealed
`pre_session_commit..accepted_revision` handoff unchanged.

### Ownership and boundary

Owned here are real direct-call range identities, canonical A/B comparison,
plan-identity diff, original run-boundary capture, opening wipe/requeue/checkpoint
account, and scheduling freeze. Slice 11 owns all repository surgery, the sole
repair call, final-account recomputation, invalidation, requeue, and atomic
close. Slices 12–13 own suite execution and cadence.

### Guarantee posture

- **Strict Git source.** Old and accepted plans are extracted and validated
  only from the canonical skeleton at committed A and B. HEAD and the plan
  anchor remain B. Initial establishment is explicitly marked and bypasses
  comparison because no old plan exists.
- **Strict identity and boundary.** A started deleted id and the first
  positional divergence within started history are candidates; the earliest
  old-plan position wins. Future-only changes do not wipe.
- **Strict original account.** Opening reconciliation stores immutable copies
  of the originating unit/job/executor/material/physical-attempt identity, old
  plan, original unit/gate boundaries, source range, wipe boundary, requeue
  set, and checkpoint invalidations before downstream mutation.
- **Strict freeze.** An open reconciliation preempts every ordinary milestone
  action. The result that opened it is not recorded as a draft, round, fix, or
  fresh re-entry before Slice 11 resolves the range.
- **No driver surgery.** This slice never moves HEAD away from B and never
  edits, restores, or applies repository bytes after accepting B.
- **Fail closed, no speculative recovery.** A missing declared revision or
  boundary stops. There is no fallback inference, parser, retry, backup,
  compatibility lane, semantic detector, or protection from arbitrary Git or
  LLM damage.

### Non-goals

- No `merge_repair` dispatch, Git rewind, deterministic restoration, apply,
  conflict handling, second repair, or manual-recovery machinery.
- No mutation of unit history, closure records, debt, checkpoints, or ledgers;
  Slice 11 consumes the persisted opening account.
- No parsing of worker prose, commit messages, findings, or reply fields to
  decide whether the plan changed.
- No suite checkpoint or activation behavior.

### Acceptance

The focused gate proves exact A/B extraction, id/order boundary selection,
future-only continuation, direct-call real ranges, per-physical observation and
correction preemption, session-range consumption, persisted original
accounting, and total scheduling freeze without any driver-side repository
surgery.

## Register 2 — PINNED FACTS (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Plan source | Compare the canonical blocks committed at A and B; state projection and replies are never before/after authority | `goal.md:224-243`; accepted amendments A3 and A8 | read Git objects and the existing validator; do not add a second plan parser |
| Identity and order | Slice id is identity; the earliest started deletion or positional divergence in old-plan order selects the boundary | `goal.md:256-283`; skeleton Plan recovery | compute one candidate minimum; do not infer intent from titles or prose |
| Direct range | A is the committed pre-attempt work tree; a valid changed block leaves the accepted whole result committed on the same branch at B | `goal.md:229-243`; skeleton Strict repository transitions | touch the existing call completion boundary; do not create a detached plan-only range |
| Session range | Repository sessions supply A=`pre_session_commit`, B=`accepted_revision` with HEAD=B | Slice 09 handoff | consume the existing handoff; do not copy or apply session output |
| Opening account | Persist originating unit/job/executor/material/attempt, original old plan/run boundaries, A/B, wipe, invalidated units/slices, requeue ids, and affected checkpoint anchors before later mutation | canonical Slice 10 intent; accepted amendments A3 and A8 | snapshot existing state facts once; do not mutate them in this slice |
| Freeze | Only a computed wipe boundary opens reconciliation; open reconciliation preempts all ordinary work | skeleton Guarantee posture and Plan recovery | add one driver action boundary; do not fail, loop, or dispatch repair in S10 |
| Repository ownership | Accepted plan/anchor/projection and HEAD remain B; S11 owns all surgery and final accounting | accepted amendment A3 | leave repository untouched after observation; do not reset, merge, or restore |
| Later ownership | Repair/invalidation/requeue are S11; suite/cadence are S12–13; retirement is S14 | canonical slice plan | persist inputs only; do not pull later behavior forward |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_plan_reconciliation orchestrator.tests.test_canonical_plan orchestrator.tests.test_author_call_cutover orchestrator.tests.test_judgment_call_cutover orchestrator.tests.test_session_repository_seal orchestrator.tests.test_session_call_cutover orchestrator.tests.test_verification_chronology`

| observable claim | named check | pass condition |
|---|---|---|
| Plan diff comes only from Git A/B | `test_range_ignores_projection_as_before_authority` | Deliberately stale run projection cannot change the old/new plans derived from the two commits. |
| Initial plan only establishes authority | `test_initial_plan_establishment_does_not_open_reconciliation` | The first valid skeleton B anchors/projects and opens due work without trying to parse a plan from pre-skeleton A. |
| Future-only edits continue | `test_forward_only_changes_do_not_open_reconciliation` | Retained-field edits, appends, and divergence strictly after the started frontier record no wipe and scheduling remains ordinary. |
| Earliest historical candidate wins | `test_started_delete_and_reorder_choose_earliest_boundary` | Mixed deletion and positional divergence produce one boundary at the earliest old-plan position. |
| Opening account is complete and immutable | `test_opening_account_captures_original_units_requeue_and_checkpoints` | The stored record contains A/B, raw old/accepted plans, original unit gates, exact invalidations/requeue, and only affected completed checkpoint anchors. |
| Direct calls expose a real range | `test_valid_physical_change_projects_a_ref_pinned_commit_anchor` and `test_invalid_change_restores_proportional_repository_boundary` | Pending pre-call bytes are checkpointed at A; the valid changed result commits B, HEAD and anchor equal B, and no detached plan commit decides the range. |
| Every physical attempt is observed immediately | `test_wipe_stops_before_contract_correction_dispatch` | A valid no-wipe change survives an invalid reply and the correction starts from B; a wipe opens and freezes before a correction call can start. |
| Session handoffs share the observer | `test_producer_session_freezes_before_recording_draft_or_wip` and `test_rethink_session_freezes_even_when_b_deletes_its_owner` | A wipe from either repository-session path opens the same record before draft recording, WIP creation, or fresh re-entry. |
| Freeze performs no surgery | `test_wipe_stops_before_contract_correction_dispatch` | The next decision is reconciliation-frozen, HEAD/branch/worktree stay B, and no unit or checkpoint record is rewritten. |

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Without this cut, a valid accepted plan can silently schedule against a refreshed projection while built commits and checkpoint anchors still describe the old plan. | canonical Slice 10 intent |
| machinery | One pure A/B comparer plus one persisted reconciliation record and one preempting action cover every direct or session source. | existing canonical-plan and session handoff seams |
| consumers_touched | Direct routed completion, runner boundary-result carry-through, producer/rethink handoff consumption, and pure driver decision. | Slices 05–09 cutover seams |
| cheaper_alternative | Using the same committed range for every source is smaller than role-specific plan handlers or deterministic restoration. | accepted amendments A3 and A8 |
| cost | The cut stores only facts Slice 11 must consume and performs no repair work itself. | Non-goals and Verification Contract |
| threat_model | Normal accepted calls may change the canonical block. Invalid configuration, repeated malformed replies, malicious workers, arbitrary repository loss, and crashes fail closed or remain operator problems. | amendments A4, A7, A8 and operator law |
| verification | Pure diff/account tests plus one direct and two session integration seams prove the boundary without broad recovery scenarios. | Verification Contract |
