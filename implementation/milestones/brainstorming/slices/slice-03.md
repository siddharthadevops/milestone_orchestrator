# Slice 03 — Ordered rounds and lead-owned target

## Register 1 — Intent

### What this slice builds

This slice turns the saved participant list into an orderly discussion. Each
participant speaks once per round in the order fixed when the session was
accepted. Every turn receives the current recoverable target and all earlier
accepted discussion. A round counts only after every participant has completed
one turn.

Session creation records the target's exact existing-or-absent state as
`recovery_baseline_revision`; that state is recoverable but not accepted.
`accepted_target_revision` starts null. The first completed lead turn creates
accepted target state, even when the target bytes are unchanged. Only a later
completed lead turn may advance it.

Interlocutors are explicitly instructed not to edit `target_path`. A mutation
during an interlocutor turn, control work, or a lead attempt that does not
complete is an invalid worker outcome. It accepts no turn, consumes no round,
and creates or advances no accepted revision. Before another turn starts, only
`target_path` is recovered from the last accepted Brainstorming revision, or
from the launch baseline before one exists.

Brainstorming owns those revision identifiers or hashes. They work whether the
target is new or already exists and whether or not the workspace or target is
inside a repository. Participants keep the caller's complete inherited tools
and execution context, including the ability to inspect and reason about
supplied references and legitimate neighbouring material. Lead-only acceptance
is a role rule, not a new permission, sandbox, custody, or threat model.

### Ownership and boundary

This slice owns the persisted turn order, the exclusive acceptance window for
one scheduled attempt, durable completed-turn and completed-round facts, the
unaccepted recovery baseline, nullable accepted target revision, and exact
target-only recovery after an invalid worker outcome.

It may tighten the existing execution seam only enough to prove that supervised
local work is quiescent before a candidate turn is accepted. It does not change
the persistent logical-session or discussion-envelope contracts from Slice 2.

It does not write `chat.md`, collect closure votes, decide success, expose a
route or screen, or connect Milestone Orchestrator or Agent99. It does not judge
proposals, merge competing edits, alter the caller's tools, or establish an
artifact-size, retained-history, active-session, or process-global round quota.

### Guarantee posture

- **Strict:** accepted turns follow persisted roster order; each accepted turn
  sees the current recoverable target and all prior accepted discussion; only a
  completed lead turn creates or advances accepted target state; rejected work
  changes no accepted discussion, revision, turn cursor, or round count; only a
  complete roster pass increments `rounds_used`; and restart recovery restores
  the last accepted target, or the launch baseline before one exists, before
  another attempt starts.
- **Strict acceptance window:** one scheduled attempt is exclusive from worker
  admission through local-process quiescence, final target observation, and
  durable acceptance or rejection with target reconciliation. A valid control
  envelope alone is never accepted while supervised work can still mutate the
  target.
- **Optimistic:** competing coordinators contend before worker admission. A
  stale contender cannot overlap work, duplicate a turn, reorder the roster, or
  overwrite accepted progress.
- **Best-effort:** participant-call delivery and liveness retain Slice 2's
  posture. A provider conversation may have advanced even when its worker
  outcome is rejected; there is no exactly-once claim.

These guarantees assume the run contract: callers do not mutate `target_path`
while the session is active. Concurrent external writes are outside the run
contract and are neither attributed nor merged.

### Dependencies and consumers

The slice depends on Slice 1's immutable request, roster, lifecycle, and durable
state and Slice 2's validated continuing participant exchanges and inherited
process supervision. Slice 4 consumes accepted turns in order. Slice 5 consumes
`rounds_used` and the accepted target revision.

Slice 8 owns the corrective implementation that separates the already-built
recovery baseline from lead-accepted state. It updates affected state,
coordination, lifecycle, and visualization consumers so setup leaves
`accepted_target_revision` null, the first completed lead turn creates it, and
the dedicated view remains readable before that turn. It also composes the
bounded target-mutation correction with Slice 2's independent envelope repair
and Slice 5's coherent failure path. The historical Slice 3 unit is not rerun.

Current service routes, the panel, milestone transitions, and all additional
root products remain outside this slice.

### Non-goals

- No transcript file, ballot, closure evaluation, success decision, API,
  visualization, milestone signal, or Agent99 adapter.
- No new permission, sandbox, custody, root resolution, executor selection,
  liveness, retry-delivery, or idempotency system.
- No fixed artifact-size ceiling, retained revision-count/byte allowance,
  global active-session cap, or fixed upper limit on positive `max_rounds`.
- No repository or VCS dependency in target-version selection or recovery, and
  no Git-based or repository-wide rollback model.
- No attribution or merge of concurrent external target writes.
- No recovery or mutation of any path outside `target_path`; participant
  inspection and reasoning through the inherited context remain available.
- No coordinator interpretation of the target's domain or participant Markdown.

### Acceptance

Cross-family and same-family sessions follow their persisted order across
restarts. Every turn receives the current recoverable Brainstorming revision,
identified as the unaccepted launch baseline or the latest lead-accepted
revision, plus all earlier accepted discussion. Partial, repaired, interrupted,
or rejected work consumes no turn or round. Each complete pass increments
`rounds_used` exactly once, and no turn starts after the caller's positive
`max_rounds` is exhausted.

A candidate remains unaccepted until every supervised local process from the
attempt is known quiescent, the final target observation is complete, and the
outcome is either durably accepted or rejected with the target reconciled.
Unknown process state does not establish quiescence, and no competing or later
attempt starts inside that window.

Setup records an exact recovery baseline but no accepted revision. The first
completed lead turn creates accepted state even when bytes are unchanged. A
later completed lead change advances it; a later unchanged lead turn and every
valid interlocutor turn retain it. If an interlocutor changes the target, or a
lead changes it without completing a valid turn, the whole worker outcome is
rejected and the exact last accepted target is restored—or the launch baseline
if no lead turn has completed. The same rule covers a target that started
absent. Recovery changes only `target_path`; sibling sentinels remain
byte-identical. The same pending worker action may be attempted once after that
recovery. A second invalid target mutation before it completes restores the
target again and ends the session as coherent `failure`, with no rejected turn,
round, or revision accepted. This target-mutation allowance and Slice 2's
envelope-repair allowance are independent and neither resets the other.

Target-version selection and recovery inspect no Git/VCS state or repository
metadata. Supplied references and neighbouring material remain available to
participants as context; they never become revision or recovery authority.

An actual resource failure is not converted into a document-invented target
policy or domain judgment. It follows the existing operational/lifecycle
failure posture and cannot accept partial progress. This slice adds no special
quota reservation, quota migration, or quota-specific correction loop.

The production seam should remain narrow, but this slice is expected to exceed
the roughly 500 changed-line target once ordered coordination, quiescent
acceptance, exact target-revision recovery, restart and contention handling,
and their focused test matrix are counted. Those tests are the executable
evidence for the strict guarantees; generated and mechanical changes remain
excluded.

### Risks

- Prompt-only ownership would accept unauthorized changes. The acceptance
  boundary observes the target after supervised work is quiescent.
- A content hash without retained target content can detect drift but cannot
  perform exact recovery. The latest accepted target, or the baseline before
  acceptance, remains exactly recoverable.
- A crash can occur after a worker changes the target but before acceptance.
  Restart reconciliation restores the accepted Brainstorming revision before
  another participant sees the target.
- Two coordinators could otherwise run overlapping attempts. Exclusive
  admission prevents overlap; durable compare-and-set admits one successor.
- Broad recovery could erase unrelated caller work. Recovery is confined to
  the target; unchanged-path checks prove that write boundary, while a separate
  fail-on-access probe covers repository/VCS reads.
- Treating deployment sizing as product law would reject valid caller-bounded
  discussions. Resource policy is deliberately absent from this slice.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority | touch / do-not-touch |
|---|---|---|---|
| Ordered discussion | The persisted `run_config.participants` list is the only turn order. Round numbers are one-based. Each participant has exactly one accepted `discussion_turn` per round. Admission, repair, supervision, recovery, and later ballot activity are control work, not turns. | frozen mandate, Round definition | touch coordinator and additive coordination state; do-not-re-resolve or reorder the roster |
| Coordination projection | Accepted discussion state has `completed_turns`, `rounds_used`, `recovery_baseline_revision`, and nullable `accepted_target_revision`. `rounds_used` starts at 0; accepted revision starts null. Completed turns are append-only and determine the next scheduled participant. The exclusive attempt window is control state and never appears as completed progress. | skeleton, Roles, rounds, and revisions; Amendment A1 | touch one additive accepted-state projection; do-not-promote the baseline or add transcript, ballot, result, route, or caller-action fields |
| Turn view | Every participant receives the question and context, `target_path`, the current Brainstorming revision and its baseline-or-accepted provenance, all earlier accepted turn Markdown in order, its persisted role, the round number, and the lead-only target rule. Participants may inspect and reason about supplied references and legitimate neighbouring material through the inherited context; interlocutors are explicitly told not to edit the target. | frozen mandate, Request contract, Inherited execution context, and Participants and discussion; Amendment A1 | touch the product-neutral discussion prompt; do-not-present rejected output as prior discussion, narrow contextual access, or add domain taxonomy |
| Exclusive acceptance window | At most one scheduled attempt is admitted per session. Its window begins before invocation and stays exclusive through worker quiescence, final target observation, and durable acceptance or target-reconciled rejection. Restart admits nothing until prior supervised work is quiescent and the target matches the accepted revision or recovery baseline. | skeleton, Participant supervision; Amendment A1 | touch coordination and narrow execution completion evidence; do-not-add a new permission, sandbox, custody, or liveness system |
| Brainstorming target revisions | `recovery_baseline_revision` identifies the exact existing-or-absent launch state but grants no acceptance. `accepted_target_revision` is null until the first completed lead turn creates it. Only later completed lead turns may advance it. Identifiers or hashes are Brainstorming-owned, independent of state-store CAS and any VCS. Recorded identities remain auditable and the content needed for active recovery and final target inspection remains available. Storage organization is not a cross-slice contract. | skeleton, Roles, rounds, and revisions; Amendment A1 | touch a Brainstorming-owned target-only revision seam; do-not-conflate recovery with acceptance or assign repository meaning |
| Invalid target mutation | Any mutation during an interlocutor turn, control work, or a lead attempt that does not yield one valid completed turn invalidates that outcome. It appends no turn, consumes no round, advances no accepted revision, and restores only `target_path` from the last accepted Brainstorming revision or the baseline before one exists. Each pending worker action has one target-mutation correction allowance; a second invalid mutation before that action completes restores the target and terminalizes coherent `failure`. This allowance is independent of the one envelope repair and neither resets the other. | Amendment A1; skeleton, Invalid target mutation | touch target observation, bounded correction, rejection, coherent failure, and exact target-only recovery; do-not-let target-version selection or recovery inspect commits, refs, branches, HEAD, repository history, merges, or repository metadata, and do-not-recover another path |
| Resource posture | The caller's positive `max_rounds` is the only product round bound. No fixed target bytes, revision/history budget, or global active-session count is introduced here. | skeleton, Resource posture | touch regression coverage only; do-not-build quota reservation, migration, or quota-specific failure machinery |
| Slice boundary | Slice 3 adds ordered coordination and target-revision acceptance only. Slice 8 corrects baseline-versus-acceptance state and affected consumers. It adds no public route, transcript, ballot, result, UI, milestone transition, or external-root change. | skeleton, Planned Slices | touch coordination plus the declared Slice 8 correction; do-not-pull later surfaces forward |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_coordination`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Persisted order and context survive restart | `test_persisted_order_and_turn_view_survive_restart` | Cross-family and same-family fixtures call participants only in roster order; after reopen, the next participant receives the current recoverable revision, its provenance, and every earlier accepted Markdown entry once and in order. | strict |
| Only complete passes count | `test_only_complete_passes_increment_rounds_used` | Partial, interrupted, repaired, and rejected exchanges do not increment `rounds_used`; the last accepted turn in each pass increments it once; no turn starts beyond the caller's bound. | strict |
| Completed lead work owns acceptance | `test_completed_lead_turn_creates_or_advances_target_revision_atomically` | Setup leaves accepted revision null. The first valid completed lead turn creates it even with unchanged bytes; later valid lead changes may advance it; interlocutor/setup state never does. A failed durable write accepts neither turn nor revision and restores the prior recovery anchor. | strict accepted state; optimistic conflict detection |
| Worker quiescence precedes acceptance | `test_worker_quiescence_precedes_target_validation_and_turn_acceptance` | A valid envelope while supervised work can still mutate the target creates no completed turn or round and admits no later attempt. Its final mutation is judged only after quiescence. | strict accepted state; best-effort participant delivery |
| Interlocutor mutation is invalid | `test_interlocutor_target_mutation_is_rejected_and_restored` | Even with a valid envelope, an interlocutor edit accepts no turn, revision, cursor movement, or round and restores only the target; sibling paths are unchanged. | strict |
| Incomplete lead mutation is invalid | `test_failed_lead_exchange_cannot_advance_target` | Provider failure or interruption after a lead edit leaves no accepted progress and restores the last accepted target, or the baseline before one exists. | strict accepted state; best-effort provider delivery |
| Initial absence and restart recovery are exact | `test_missing_target_and_restart_recover_last_accepted_revision` | Existing, absent, revised, and deleted targets retain stable Brainstorming identities; reopen restores the accepted revision when present and otherwise the baseline before another call. | strict |
| Target versions are repository-independent | `test_target_revision_and_recovery_never_probe_vcs_or_repository_metadata` | Creation, completed-lead acceptance, invalid-mutation recovery, and restart reconciliation run with fail-on-access observation of their process-launch and filesystem-read seams. Any Git/VCS command or repository-metadata read fails the check; unrelated repository-state changes leave revision identities and recovery outcomes unchanged. | strict |
| Concurrent coordinators cannot overlap | `test_stale_coordinator_cannot_duplicate_or_reorder_turns` | Two coordinators from one state never invoke overlapping workers; durable turns remain a valid roster prefix with one accepted successor. | strict worker admission; optimistic conflict detection |
| Existing execution and service consumers do not change | `test_coordination_reuses_execution_without_public_surface_changes` | Slice 2 execution remains compatible, no route/error contract is introduced, and recovery changes only the configured target. | strict compatibility |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`.

### Question Battery

The skeleton's Question Battery is inherited. Slice-specific answers:

| question | answer | evidence |
|---|---|---|
| consumers_touched | Slice 1 state and roster, Slice 2 participant execution, Slice 4 accepted-turn reader, Slice 5 round/revision reader, and Slice 7's accepted-target view. Slice 8 owns the nullable-revision consumer correction. | Dependencies and consumers |
| pinned_facts | Persisted roster order; distinct unaccepted baseline and nullable lead-accepted revision; exclusive quiescent acceptance; completed-lead-only acceptance; target-only recovery; one bounded target-mutation correction and coherent failure independent of envelope repair; complete-pass accounting; no quota or public surface. | Pinned-Facts Table |
| verification | Focused checks pin order, complete-pass counting, quiescence, lead-only acceptance, invalid-mutation rejection and bounded failure, exact restart recovery, fail-on-access detection of repository/VCS dependencies, stale-coordinator exclusion, and compatibility. | Verification Contract |
| reuse_posture | Existing validation, CAS, participant execution, supervision, content hashing, exact target capture, and atomic replacement are reused. A Brainstorming-owned target-only revision seam is required because detection alone cannot recover the target and setup bytes cannot satisfy lead-only acceptance. | Reuse Posture |
| enforceability | Immutable roster plus append-only turns enforce order; supervised quiescence plus final target observation enforce acceptance; exact retained target state enforces target-only recovery; whole-state CAS rejects stale successors; Slice 8's fail-on-access regression detects repository/VCS probes separately from unchanged-path checks. | Enforceability Gate |

### Reuse Posture

- **Checked and adopted:** exact contract validation, immutable roster,
  append-only successor guards, whole-state CAS, participant execution,
  process supervision, content hashing, exact target observation, atomic
  replacement, and stateful fake executors.
- **Extended:** one exclusive turn-attempt window around the existing execution
  seam and one additive coordination projection.
- **New-with-why:** one Brainstorming-owned, target-only retained revision seam
  with distinct recovery and acceptance facts. Exact recovery requires content,
  and Amendment A1 forbids treating launch capture as lead-accepted state.
- **Compatibility:** participant logical sessions and envelopes remain
  unchanged. The coordinator consumes the resolved roster and caller context,
  changes no route, and never recovers another path. Slice 8 corrects existing
  consumers of the initial accepted revision.

### Enforceability Gate

| invariant | enforcing seam | implementation gate |
|---|---|---|
| Persisted order and complete turn view | Immutable roster plus validated append-only completed turns | Restart/order tests reject skipped, repeated, out-of-order, or stale-target turns. |
| Exclusive quiescent attempt | Existing participant execution and process-set supervision extended only around acceptance | Concurrent and late-mutation checks observe no overlapping call or accepted candidate while a supervised writer remains. |
| Whole accepted successor | Final target observation plus complete-state validation and CAS | Failure/contention tests observe one valid successor or none, never an accepted outcome that must be retracted. |
| Baseline and lead-accepted revision | Exact target capture, retained Brainstorming revision content, and atomic target-only replacement | Existing/absent/revise/delete/restart fixtures prove stable identifiers and exact restoration while setup leaves acceptance null. |
| Completed-lead-only acceptance | Persisted role plus the exclusive acceptance window | Lead/interlocutor/failure matrices prove only completed lead work creates or advances accepted state. |
| Complete-pass `rounds_used` | Roster-prefix validation and the last-turn successor | Partial/restart/max-bound fixtures increment only at the complete-pass boundary. |
| Bounded invalid target mutation | Exact target-only recovery plus one correction allowance for the pending worker action and Slice 5's existing failure terminalization | Slice 8 regression proves the first invalid mutation restores only the target and accepts no progress, while repetition restores it again and publishes one coherent failure; the independent envelope-repair allowance cannot reset it. |
| No invented quota | Positive-integer request contract and absence of quota state or threshold checks | Slice 8 regression accepts values above the discarded round, artifact, and active-session thresholds solely on their normal validity. |
| Target-only recovery | Amendment A1 plus exact configured target identity | Unchanged-path checks prove recovery writes only the target; they make no claim about reads. |
| Repository-independent target versions | Amendment A1 plus Slice 8's named fail-on-access regression | Instrumented process-launch and filesystem-read seams fail on every Git/VCS command or repository-metadata probe during creation, acceptance, recovery, and restart; unrelated repository-state changes cannot alter revision identity or recovery. |

If implementation relies on participant obedience, promotes the recovery
baseline without completed lead work, retains only an unrecoverable hash, uses
workspace-wide recovery, or consults VCS state, the guarantee is not delivered.

### Planning Material Disposition

- **Adopt:** the skeleton, frozen mandate, and Operator Amendment A1.
- **Revise:** existing hashing and atomic-persistence primitives only behind
  the Brainstorming-owned target revision contract.
- **Reject:** exploratory planning as authority; any repository/VCS restoration
  design; fixed global quotas; and any permission, work-area, or product-specific
  expansion.
