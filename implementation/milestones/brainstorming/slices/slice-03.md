# Slice 03 — Ordered rounds and lead-owned target

## Register 1 — Intent

### What this slice builds

This slice turns the saved participant list into an orderly discussion. Each
participant speaks once per round in the order fixed when the session was
accepted. Before speaking, each participant gets the current target and the
accepted discussion so far. A round counts only after everyone has completed
their turn.

The lead is the only participant whose completed turn may advance the accepted
target. Interlocutors are told to analyze without editing it. The service checks
what actually happened around every turn: an unauthorized or unfinished change
is rejected, the accepted discussion does not advance, and only the target is
returned to its last accepted Brainstorming revision. A valid envelope is not
enough: the worker's supervised local process set must first be quiescent, then
the target is checked before the turn can be accepted.

Brainstorming owns those target revisions. They work whether the target is new
or already exists and do not depend on the workspace or target being a
repository. The agents keep the caller's full tools and work area; ownership is
enforced at the accepted-turn boundary, not by adding a sandbox.

### Ownership and boundary

This slice owns the ordered-turn coordinator, the exclusive acceptance window
for each turn attempt, durable completed-turn and completed-round facts, the
current accepted target revision, and exact recovery of that target after an
invalid worker outcome. These facts are the input to the later transcript and
closure slices. This slice may tighten the existing execution seam to establish
worker quiescence; it does not reopen Slice 2 or change its logical-session or
discussion-envelope contracts.

It does not write `chat.md`, collect or count closure votes, decide success or
failure, expose a route or screen, or connect Milestone Orchestrator or Agent99.
It does not judge proposals, merge competing target edits, or change the
caller's tools, permissions, roots, or work-area rules.

### Guarantee posture

- **Strict:** accepted turns follow the persisted order; each accepted turn sees
  the latest accepted target and all earlier accepted discussion; only a
  completed lead turn may advance the accepted target revision; one exclusive
  turn-attempt window spans worker admission, quiescence, target disposition,
  and the accepted-state decision; rejected turns change no accepted
  discussion, revision, or round count; only complete passes increase
  `rounds_used`; and restart recovery re-establishes the accepted target before
  another turn.
- **Optimistic:** competing coordinators contend before worker admission. Only
  one may invoke the scheduled participant; a stale contender cannot overlap
  target work, duplicate, reorder, or overwrite accepted progress.
- **Eventual:** none. The later screen may lag, but ordering, round count, and
  accepted target revision are authoritative state.
- **Best-effort:** participant-call delivery and liveness retain Slice 2's
  posture. A provider conversation may have advanced even when its worker
  outcome is rejected; there is no exactly-once or perfect-liveness claim.

These guarantees assume the run contract: callers do not mutate the target
while the session is active. Such external writes are neither attributed nor
merged.

### Dependencies and consumers

The slice depends on Slice 1's immutable request, roster, lifecycle, and durable
state and Slice 2's validated continuing participant exchanges and inherited
process supervision. The corrective quiescence and exclusive-admission work is
assigned to this slice, including any narrow change needed in the shared
execution seam. Its direct consumer is the new coordinator test suite. Slice 4
consumes accepted turns in order; Slice 5 consumes `rounds_used` and the
accepted target revision.

Current service routes, the panel, milestone transitions, and all additional
root products remain outside this slice.

### Non-goals

- No transcript file, ballot, closure policy evaluation, terminal result, API,
  visualization, milestone signal, or Agent99 adapter.
- No new permission, sandbox, custody, root resolution, executor selection,
  liveness, retry-delivery, or idempotency system.
- No repository inspection, version-control revision, or repository-wide
  recovery model.
- No attribution or merge of concurrent external target writes.
- No restoration or rollback of any path outside `target_path`.
- No coordinator interpretation of the target's domain or of a participant's
  Markdown.

### Acceptance

The slice is accepted when cross-family and same-family sessions each follow
their persisted order across restarts; every turn receives the current accepted
target plus earlier accepted discussion; partial, repaired, interrupted, or
rejected work consumes no turn or round; and each complete pass increments
`rounds_used` exactly once without exceeding `max_rounds`.

A turn remains unaccepted after a valid envelope appears. Its exclusive
acceptance window closes only after every supervised local process from the
attempt is known quiescent, the final target observation is complete, and the
outcome is either durably accepted or rejected with the target reconciled.
Unknown process state does not satisfy quiescence, and no competing or later
participant attempt starts inside that window. A completed lead turn may then
establish a changed accepted target revision. An unchanged lead turn and every
valid interlocutor turn keep the same revision. If an interlocutor changes the
target, or a lead changes it without completing a valid turn, the outcome is
rejected and the exact last accepted target is restored before work continues.
The same rule covers a target that started absent. Recovery changes only
`target_path`; sibling sentinels remain byte-identical.

The production seam should remain small, but this slice is expected to exceed
the roughly 500 changed-line target once the fake-participant, restart,
content-revision, stale-writer, missing-target, invalid-writer, and
target-only-recovery tests are counted. Those tests are the executable evidence
for the strict guarantees; generated and mechanical changes remain excluded.

### Risks

- A prompt-only writer rule would accept unauthorized changes. Acceptance
  compares the target around every exchange and rejects the worker outcome.
- A content hash without retained revision content could detect drift but not
  recover it. Every accepted target revision must remain exactly restorable.
- A crash can occur after a worker changes the target but before its turn is
  accepted. Restart reconciliation restores the last accepted revision before
  another participant sees the target.
- A valid envelope can appear while supervised descendant work is still able to
  change the target. Envelope availability is not acceptance: the process set
  must be quiescent and the target checked before any completed turn is durable.
- Competing coordinators could otherwise run two writers from one accepted
  state. Exclusive worker admission prevents overlap; whole-state
  compare-and-set still admits only one ordered successor.
- Broad recovery could erase unrelated caller work. Recovery is confined to the
  target and tests keep neighbouring paths under sentinel observation.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Ordered discussion | The persisted `run_config.participants` list is the only turn order. Round numbers are one-based. Each scheduled participant has exactly one accepted `discussion_turn` per round; admission, repair, supervision, recovery, and later ballot activity are control work, not turns. | `implementation/milestones/brainstorming/skeleton.md:25-28,73-75,103`; `implementation/milestones/brainstorming/goal.md:162-179,230-241`; `orchestrator/brainstorming.py:159-204` | touch the coordinator and additive coordination state; do-not-re-resolve or reorder the roster |
| Cross-slice coordination projection | The accepted discussion projection adds exactly `completed_turns`, `rounds_used`, and `accepted_target_revision`. `rounds_used` starts at `0`. `completed_turns` is append-only; each item has exactly `round`, `participant_id`, `markdown`, and `target_revision`. The exclusive acceptance window is control state and never appears as completed progress. The next scheduled participant is determined from accepted progress and the immutable roster. Slice 4 consumes the ordered Markdown; Slice 5 consumes the round count and revision. | `implementation/milestones/brainstorming/skeleton.md:73-77,102-105`; `implementation/milestones/brainstorming/goal.md:203-211,230-248`; `orchestrator/brainstorming.py:398-425,464-483` | touch one validated additive accepted-state projection plus its control boundary; do-not-add transcript, ballot, result, route, or caller-action fields |
| Turn view | Every participant turn receives the session question and context, `target_path` with its current accepted Brainstorming revision, all earlier `completed_turns.markdown` entries in order, its persisted role, the round number, and the lead-only target rule. Interlocutors are explicitly instructed not to edit the target. Unaccepted output is never presented as prior discussion. | `implementation/milestones/brainstorming/skeleton.md:11-15,44-45,75,103`; `implementation/milestones/brainstorming/goal.md:137-146,162-175,224-235`; Operator Amendment A1, **Target versioning clarification** | touch the product-neutral discussion prompt; do-not-add domain taxonomy or interpret Markdown |
| Exclusive turn-acceptance window | At most one scheduled participant attempt is admitted per session. Its window starts before any worker invocation and remains exclusive through repair, worker quiescence, final target observation, and durable acceptance or rejection with target reconciliation. A valid envelope is only a candidate and never enters `completed_turns` while this window is open. Unknown worker state keeps the window open. After interruption or restart, no attempt is admitted until prior supervised work is quiescent and `target_path` matches the last accepted Brainstorming revision. | `implementation/milestones/brainstorming/skeleton.md:25-28,102-103`; `implementation/milestones/brainstorming/goal.md:166-183,224-241`; Operator Amendment A1, **Target versioning clarification** | touch Slice 3 admission, coordination, narrow execution completion evidence, and focused tests; do-not-add a new permission, sandbox, custody, or liveness system |
| Brainstorming target revisions | Before the first participant turn, `accepted_target_revision` identifies the exact starting state of `target_path`, including an absent target. The identifier is Brainstorming-owned and independent of the session-store CAS revision and of any VCS. Thereafter only a contract-valid completed lead turn may create or advance the accepted revision; an unchanged lead turn and every interlocutor turn retain it. Each accepted revision remains exactly recoverable. | `implementation/milestones/brainstorming/skeleton.md:25-28,44-45,58-60,75,103`; `implementation/milestones/brainstorming/goal.md:13-15,61-62,114-115,224-248,351-354`; Operator Amendment A1, **Target versioning clarification**; `orchestrator/brainstorming.py:52-63,521-578` | touch a Brainstorming-owned target-only revision seam; do-not-conflate target revision with state CAS or any repository revision |
| Invalid target mutation | Any target mutation during an interlocutor turn, during control work, or during a lead attempt that fails to yield one valid completed turn invalidates that whole worker outcome. It appends no completed turn, consumes no round, does not advance `accepted_target_revision`, and restores only `target_path` from the last accepted Brainstorming revision before the exclusive window closes. A valid lead change is accepted only with its completed turn and durable revision. | `implementation/milestones/brainstorming/skeleton.md:25-28,42-45,75,102-103`; `implementation/milestones/brainstorming/goal.md:166-175,226-241,351-354`; Operator Amendment A1, **Target versioning clarification** | touch target-only observation, acceptance, and recovery; do-not-inspect or restore commits, refs, branches, HEAD, repository history, merges, or any other path |
| Atomic accepted progress | No completed-turn record is durable until the exclusive window has reached worker quiescence and the final target-ownership check passes. The completed-turn append, its resulting accepted revision, and the possible complete-pass increment then form one validated state successor. A stale or failed state write exposes none of that progress; after interruption, the target is reconciled to the durable accepted revision before scheduling resumes. `rounds_used` increases exactly after the last participant in a pass and never exceeds request `max_rounds`. | `implementation/milestones/brainstorming/skeleton.md:23-28,75,102-103`; `implementation/milestones/brainstorming/goal.md:230-241,336-374`; `orchestrator/brainstorming.py:130-156,464-483,521-578`; `orchestrator/kvstore.py:343-359,391-457` | touch exact successor validation and target/state reconciliation; do-not-claim exactly-once provider execution |
| Public and slice boundary | This slice adds no public route, public error code, transcript event, ballot, closure decision, terminalization rule, UI surface, or product adapter. `ParticipantExecution.exchange` remains the participant-call seam; this slice may add only the internal completion evidence needed by its acceptance window, without changing the discussion envelope or existing service routes. | `implementation/milestones/brainstorming/skeleton.md:36-47,73-80`; `orchestrator/brainstorming_execution.py:177-255`; `orchestrator/service.py:2735-2887` | touch coordination, narrow execution completion evidence, and focused tests; do-not-touch later-slice or external-root consumers |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_coordination`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Persisted order and context survive restart | `test_persisted_order_and_turn_view_survive_restart` | Cross-family and same-family fixtures call participants only in roster order; after reopening state, the next participant receives the accepted target revision and every earlier accepted Markdown entry once and in order. | strict |
| Only complete passes count | `test_only_complete_passes_increment_rounds_used` | Partial, interrupted, repaired, and rejected exchanges do not increment `rounds_used`; the last accepted turn in each pass increments it once; no turn starts beyond `max_rounds`. | strict |
| Completed lead work owns accepted target advancement | `test_completed_lead_turn_advances_target_revision_atomically` | A valid lead change produces one new recoverable revision and one completed-turn record together; an unchanged lead keeps the revision; a forced durable-write failure accepts neither and restores the prior target. | strict accepted state; optimistic conflict detection |
| Worker quiescence precedes turn acceptance | `test_worker_quiescence_precedes_target_validation_and_turn_acceptance` | Producing a valid envelope while supervised participant work can still mutate the target creates no completed turn or round and admits no later attempt. After that work ends, its mutation is judged as part of the same outcome; interruption or restart retains the same gate, and an invalid writer is rejected with only the target restored. | strict accepted state; best-effort participant delivery |
| Interlocutor mutation is invalid | `test_interlocutor_target_mutation_is_rejected_and_restored` | Even with a valid envelope, an interlocutor target edit returns no accepted turn, revision, cursor movement, or round count; the target is restored exactly and neighbouring sentinel paths are unchanged. | strict |
| Incomplete lead mutation is invalid | `test_failed_lead_exchange_cannot_advance_target` | Provider failure, interruption, or two invalid envelopes after a lead edit leave no accepted progress and restore the last accepted target before retry. | strict accepted state; best-effort provider delivery |
| Initial absence and restart recovery are exact | `test_missing_target_and_restart_recover_last_accepted_revision` | An absent starting target is recoverable; create/revise/delete cases retain stable Brainstorming revision identities; reopening with divergent target bytes restores the durable accepted state before another executor call. | strict |
| Concurrent coordinators cannot overlap or fork order | `test_stale_coordinator_cannot_duplicate_or_reorder_turns` | Two coordinators from one accepted state never invoke overlapping workers: one owns the exclusive window and the other re-evaluates after it closes. Durable turns remain a valid roster prefix with one accepted successor and coherent round count. | strict worker admission and accepted state; optimistic conflict detection |
| Existing execution and service consumers do not change | `test_coordination_reuses_execution_without_public_surface_changes` | The Slice 2 execution suite remains green, no brainstorming route/error contract is introduced, and target recovery changes only the configured target. | strict compatibility |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:309-319`). Later slices add transcript and closure
checks; milestone closure retains the matrix in
`implementation/milestones/brainstorming/skeleton.md:124-137`.

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for this slice.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **verified current seams:** Slice 1's `SessionStore` and immutable roster/state plus Slice 2's `ParticipantExecution.exchange`; neither currently has a production coordinator consumer. **slice-local consumer:** the focused coordination tests and any narrow execution-completion evidence they require. **declared next consumers:** Slice 4 reads accepted ordered turns and Slice 5 reads `rounds_used` plus `accepted_target_revision`. **not touched:** service routes, panel, milestone transitions, Agent99, Life, LPC, and Tutor. | `orchestrator/brainstorming.py:159-204,398-425,521-645`; `orchestrator/brainstorming_execution.py:80-255`; `orchestrator/tests/test_brainstorming_execution.py:14-16`; `orchestrator/service.py:2735-2887`; `implementation/milestones/brainstorming/skeleton.md:73-80` |
| pinned_facts | **closed facts:** immutable roster order; accepted coordination projection; one exclusive turn-attempt window; worker quiescence and final target observation before append; accepted turn view; Brainstorming-owned target revisions; completed-lead-only revision advancement; invalid-mutation rejection and target-only recovery; atomic completed-turn/round progress; no public or later-slice surface. | `implementation/milestones/brainstorming/slices/slice-03.md:139-148`; `implementation/milestones/brainstorming/skeleton.md:23-47,73-80,102-103`; Operator Amendment A1, **Target versioning clarification** |
| verification | **focused:** nine named checks pin order/restart context, complete-pass counting, exclusive quiescent acceptance, valid lead advancement, interlocutor and incomplete-lead rejection, missing-target recovery, stale-coordinator exclusion, and current-consumer compatibility. **full:** repository unittest discovery remains the milestone gate. | `implementation/milestones/brainstorming/slices/slice-03.md:150-172`; `implementation/milestones/brainstorming/skeleton.md:124-137`; `orchestrator/README.md:309-319` |
| reuse_posture | **checked:** exact contract validation, immutable roster, append-only successor guards, state CAS, participant execution and process supervision, file hashing, atomic replacement, fake executors, and the dependency-free runtime. **adopted:** those validation/CAS/execution/supervision/hash/atomic-write primitives and test style. **extended:** Slice 3 adds the exclusive quiescent acceptance window, additive accepted coordination state, and prompt composition. **new-with-why:** one target-only retained revision seam, because A1 requires exact recovery while existing hashing detects content but retains no recoverable target revision. | `orchestrator/brainstorming.py:72-105,159-204,398-425,464-483,521-645`; `orchestrator/brainstorming_execution.py:177-255`; `orchestrator/runners.py:30-58,548-642,644-885,1269-1298,1367-1371`; `orchestrator/kvstore.py:343-359,391-457`; `orchestrator/tests/test_brainstorming_execution.py:746-915`; `orchestrator/README.md:45`; Operator Amendment A1, **Target versioning clarification** |
| enforceability | **order/context:** immutable roster plus validated append-only completed turns drive each call. **acceptance boundary:** exclusive worker admission, inherited process-set supervision, and a final target check prevent any candidate from becoming accepted while its attempt can still write. **accepted state:** exact successor validation and CAS reject stale/partial progress. **target ownership:** persisted role, retained accepted revision, and target-only restore mechanically reject non-lead or incomplete-lead mutation; prompt discipline alone is insufficient. **round count:** roster-prefix validation and the atomic last-turn successor. **delivery:** Slice 2 remains best-effort. **external writes:** excluded by A1's run contract, not silently attributed. | `implementation/milestones/brainstorming/slices/slice-03.md:139-172,219-230`; `orchestrator/brainstorming.py:159-204,398-425,464-483,521-645`; `orchestrator/brainstorming_execution.py:177-255`; `orchestrator/runners.py:30-58,548-642,644-885,1269-1298`; `orchestrator/kvstore.py:343-359,391-457`; Operator Amendment A1, **Target versioning clarification** |

### Reuse Posture

- **Checked:** Slice 1's exact validators, immutable roster, append-only
  successor guards, and CAS-backed store; Slice 2's explicit participant
  exchange; the existing content-hash/change primitives, atomic file
  replacement, fake executors, and standard-library-only runtime. Authorities:
  `orchestrator/brainstorming.py:72-105,159-204,398-425,464-483,521-645`;
  `orchestrator/brainstorming_execution.py:177-255`;
  `orchestrator/runners.py:1269-1298,1367-1371`;
  `orchestrator/kvstore.py:343-359,391-457`;
  `orchestrator/tests/test_brainstorming_execution.py:81-130,287-391`;
  `orchestrator/README.md:45`.
- **Adopted:** exact validation, immutable roster order, whole-state CAS,
  participant execution, content hashing, atomic persistence, and the existing
  stateful fake-executor style.
- **Extended:** Slice 3 adds an exclusive turn-attempt window around the existing
  execution seam, with worker quiescence and a final target observation before
  accepted progress. The Brainstorming accepted-state projection gains only the
  coordination facts; the coordinator composes the turn view from accepted
  state.
- **New-with-why:** one Brainstorming-owned, target-only retained revision seam
  is necessary. Detection alone cannot perform A1's exact recovery, and neither
  the goal nor existing code provides a recoverable target revision. This need
  is independently mandated by Operator Amendment A1 and
  `implementation/milestones/brainstorming/skeleton.md:25-28,75,102-103`.
- **Compatibility:** current one-shot and participant-execution callers keep
  their logical-session and envelope contracts. Slice 3 may add only internal
  completion evidence needed for its acceptance gate. The new coordinator
  consumes the already-resolved roster and caller context, changes no route, and
  never restores anything outside the target.

### Enforceability Gate

| invariant asserted here | mechanism that can enforce it | implementation gate |
|---|---|---|
| Persisted order and complete turn view | Immutable validated roster (`orchestrator/brainstorming.py:159-204`), exact discussion envelope (`orchestrator/brainstorming_execution.py:12-27`), and append-only `completed_turns` validated against the roster | Restart/order tests inspect every executor call and reject a skipped, repeated, out-of-order, stale-target, or missing-prior-discussion turn. |
| One exclusive turn-attempt window | Slice 3 extends the existing participant-execution and process-set supervision seams only enough to admit one worker, retain exclusivity until that worker is quiescent, and withhold later admission until target disposition is complete (`orchestrator/brainstorming_execution.py:177-255`; `orchestrator/runners.py:30-58,548-642,644-885`) | Concurrent-coordinator and late-mutation checks observe no overlapping participant calls, no accepted candidate while a supervised writer remains, and no next turn before rejection recovery completes. |
| One whole accepted coordination successor | The exclusive quiescent window plus the final target observation determine eligibility; existing complete-state validation, history-rewrite guards, and revisioned CAS (`orchestrator/brainstorming.py:398-425,464-483,521-578`; `orchestrator/kvstore.py:343-359,391-457`) protect the accepted successor | Late-within-exchange mutation, failure, and two-coordinator tests observe one valid successor or none, never an accepted outcome that must be retracted. |
| Brainstorming-owned recoverable target revision | Existing byte hashing and structural change comparison (`orchestrator/runners.py:1269-1298,1367-1371`) plus the atomic persistence pattern (`orchestrator/kvstore.py:391-457`) support the new target-only retained revision seam mandated by A1 | Create/revise/delete/restart fixtures prove stable identifiers and exact restoration. A hash without retained content fails this gate. |
| Completed-lead-only target advancement | Persisted role (`orchestrator/brainstorming.py:108-127,159-204`), Slice 3's exclusive quiescent acceptance window, final target observation, and the retained accepted revision | Lead/interlocutor/late-mutation/failure matrices prove that only one valid completed lead outcome can advance the revision; prompt compliance is never the enforcement mechanism. |
| Complete-pass-only `rounds_used` | Exact roster-prefix and completed-turn validators plus the same whole-state CAS; the bound is the validated positive `request.max_rounds` (`orchestrator/brainstorming.py:130-156`) | Partial/repair/failure/restart/max-bound fixtures observe an increment only with the last participant's accepted turn. |
| Target-only recovery and unchanged authority | A1 confines recovery to `target_path`; Slice 2 passes the caller context unchanged (`orchestrator/brainstorming_execution.py:177-220`) | Sentinel checks prove recovery changes the target and no sibling path, while execution-context identity remains unchanged. |
| Best-effort participant delivery | Existing explicit-session execution and inherited process supervision (`orchestrator/brainstorming_execution.py:177-255`; `implementation/milestones/brainstorming/skeleton.md:23-32,74,102`) | Rejected turns may leave provider conversation history, but never accepted target/turn/round state; no exactly-once assertion appears. |

If implementation relies on participant obedience, a target hash without
retained content, or broad workspace recovery for any strict row, that guarantee
is not delivered.

### Planning Material Disposition

- **Adopt:** the sealed skeleton, the generated goal only where the skeleton
  leaves intent open, and Operator Amendment A1 as the target-versioning
  clarification.
- **Revise:** existing hashing, change-detection, and atomic-persistence ideas
  are reused only as low-level primitives behind a Brainstorming-owned
  target-only revision contract.
- **Reject:** exploratory planning as independent authority; the older
  machine-API/Persona routes; any repository/VCS restoration design; and any
  permission, work-area, or product-specific expansion.

Authority: `implementation/milestones/brainstorming/skeleton.md:3-5,36-67,75,110-122`;
`implementation/brainstorming/README.md:3-8,12-17`;
`implementation/brainstorming/machine-api-and-persona-projection.md:31-55,81-113`;
Operator Amendment A1, **Target versioning clarification**.
