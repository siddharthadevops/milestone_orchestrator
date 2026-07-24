# Slice 05 — Revision-bound closure and results

## Register 1 — Intent

### What this slice builds

This slice lets a brainstorming group finish on a decision that still matches
the target they actually discussed. After a complete round, the lead may ask to
close against the accepted target version. The lead's proposal counts as its
acceptance; every interlocutor then accepts or objects to that same version.

The selected agreement rule decides the ballot. Agreement ends the session
successfully. A rejected ballot returns the group to discussion when another
round remains; otherwise the session ends with an explicit failure. If the
target changes while votes are being gathered, the ballot is discarded and
only the target is restored to its last accepted Brainstorming version.

### Ownership and boundary

This slice owns closure eligibility, vote counting, the accepted ballot,
round-limit failure, and the final consistency between target version, ballot,
session status, result, and closing account. It supplies the result later API,
view, and product-adapter slices consume.

It does not decide whether an idea is good, reinterpret an objection, schedule
ordinary discussion turns, create target versions, add routes or screens, or
choose what a caller does with the result. It adds no permission, repository,
work-area, or provider policy.

### Guarantee posture

- **Strict:** an accepted ballot is complete, ordered, policy-correct, and bound
  to the current accepted target version and completed round; a target mutation
  invalidates the ballot; success exists only with the current approving
  ballot; exhaustion is failure; every terminal `object` vote is recorded as an
  unresolved ballot objection under the participant's human label; and every
  durable terminal snapshot has one coherent result and closing account.
- **Optimistic:** competing closure attempts contend on accepted session state.
  A stale attempt loses without duplicating a ballot or replacing the winner.
- **Eventual:** none in this slice. The later visualization may lag, but durable
  closure state, the target reference, and `chat.md` are the authorities it
  projects.
- **Best-effort:** participant-call delivery, provider liveness, and the
  subjective quality of participant-authored closing prose beyond the derived
  ballot-objection records retain their existing posture. Rejected control work
  may remain in provider conversation history, but never becomes accepted
  closure state.

### Dependencies and consumers

This slice depends on the immutable request, roster, policy, lifecycle, and
result shape; persistent participant sessions; complete-pass round accounting
and the accepted Brainstorming target version; and the existing ballot,
interruption, closing-summary, and transcript-publication contracts.

Its direct consumers are the focused closure tests and the existing session,
participant-execution, coordination, and transcript seams they exercise. The
standalone lifecycle API, visualization, and Milestone adapter consume the
result later. Current HTTP routes, panel behavior, milestone transitions, and
the additional read-only product roots remain outside this slice.

### Non-goals

- No new discussion-turn shape, participant roster field, closure policy, result
  outcome, public route, or public error code.
- No API lifecycle, event stream, visualization, `need_rethink` routing, or
  Agent99 adapter.
- No domain judgment, automatic reconciliation of objections, or semantic
  scoring of participant prose.
- No new storage engine, permission boundary, sandbox, target-custody system,
  liveness detector, delivery guarantee, or idempotency system.
- No VCS revision, repository inspection, concurrent-external-write
  attribution, or modification or recovery of any path other than
  `target_path`.

### Acceptance

The slice is accepted when both configured policies produce the exact pinned
decision for complete roster ballots and the recorded `approved` value is always
derived from that decision rather than trusted as input.

Every accepted ballot follows a complete round, includes the lead's proposal and
every interlocutor vote once, and identifies the current accepted
Brainstorming target version. A target edit, stale session revision, missing or
duplicate participant, wrong vote, wrong round, or wrong target version accepts
no ballot or result. Target mutation during closure restores only the target and
invalidates all votes gathered by that attempt.

A failed ballot remains in the human history and another ballot cannot be
accepted until another complete discussion round finishes. An approving ballot
and `success` become visible together. A final non-approving ballot and
`failure` become visible together. Reaching the round bound without an
approving ballot also returns `failure`, including when the lead does not
propose closure. Explicit operational failure remains possible before the first
completed turn, with zero rounds and a non-empty plain reason.

Both outcomes retain the target, inspectable state, target and transcript
references, exact completed-round count, and one complete closing account.
Every terminal `object` vote contributes a human-labeled unresolved objection
to that account, in addition to any participant-authored objection text, so a
closing cannot claim that no objection was recorded while its accepted ballot
contains one. Success has no failure reason; failure has one. No partial target
is promoted to success, no terminal state can change, and a stale closure writer
can publish neither a losing ballot nor a losing closing.

The production seam should stay small, but the slice is expected to exceed the
roughly 500 changed-line target once the required policy, revision-invalidation,
target-recovery, atomic-terminal, exhaustion, zero-turn, and contention test
matrices are counted. Those tests are the executable evidence for the strict
guarantees; generated and mechanical changes remain excluded.

### Risks

- Trusting a supplied `approved` flag could record the opposite of the selected
  rule. The accepted flag is recalculated from the immutable roster and votes.
- Gathering votes while the target can move could approve a version nobody
  finally receives. Closure retains target exclusivity through vote acceptance
  and rejects the whole attempt on mutation.
- Appending a ballot and terminal result separately could expose an approving
  running session or a success with no ballot. Terminal closure is one durable
  accepted outcome.
- Repeating ballots at one round could bypass the discussion bound. A failed
  ballot requires another complete pass before another ballot.
- Treating participant prose as machine truth would overstate the guarantee.
  Result and ballot facts are strict, so terminal object votes are derived into
  the unresolved-objections account; other prose meaning and delivery remain
  best-effort.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Closure boundary | Closure is eligible only after a complete persisted roster pass. The lead may propose closure against the current `accepted_target_revision`; that proposal is the lead's `accept` vote. Without a lead proposal there is no accepted ballot. Ballot activity is control work, consumes no turn or round, and at most one ballot is accepted for a completed round. | `implementation/milestones/brainstorming/skeleton.md:25-28,75,77,103,105`; `implementation/milestones/brainstorming/goal.md:230-259`; `orchestrator/brainstorming.py:654-737,1299-1341` | touch closure eligibility over accepted progress; do-not-change discussion order, round accounting, or interpret Markdown |
| Accepted ballot | The cross-slice event remains exactly `closure_ballot` with `after_completed_rounds`, `target_revision`, `votes`, and `approved`. `votes` contains every persisted participant exactly once in roster order; every item has exactly `participant_id` and `vote`, whose value is exactly `accept` or `object`. The lead entry is `accept`. `approved` is derived by the closure rule and a mismatched supplied value is rejected. | `implementation/milestones/brainstorming/skeleton.md:77,92,105`; `implementation/milestones/brainstorming/goal.md:243-264`; `implementation/milestones/brainstorming/slices/slice-04.md:140,144`; `orchestrator/brainstorming.py:916-947` | touch the provisional ballot validator/producer and focused fixtures; do-not-add vote reasons, caller actions, identities outside the roster, or a second ballot record |
| Target-revision validity | Every vote in one accepted ballot refers to the same current Brainstorming revision. Any target mutation during proposal, vote collection, or ballot acceptance invalidates every vote from that attempt, accepts no ballot/result/round change, and recovers only `target_path` from the last accepted Brainstorming revision. A later completed lead edit makes an older ballot ineligible for success. External concurrent target writes are outside the run contract. | `implementation/milestones/brainstorming/skeleton.md:25-28,42-45,77,92,103,105`; Operator Amendment A1, **Target versioning clarification**; `orchestrator/brainstorming_coordination.py:137-153,583-690,731-877` | touch the existing target-exclusive acceptance and target-only recovery seam; do-not-inspect or act on Git, repository history, or any other path |
| Policy decisions | `unanimity` approves only when every vote is `accept`. `majority_with_lead_tiebreak` gives each participant one vote: more `accept` than `object` approves, more `object` rejects, and an exact tie has the lead's decision. The coordinator counts only; it never judges objection substance. | `implementation/milestones/brainstorming/skeleton.md:25-28,77,100,105`; `implementation/milestones/brainstorming/goal.md:250-264`; `orchestrator/brainstorming.py:545-590` | touch one deterministic evaluator used by ballot validation; do-not-add a default, threshold, veto, weight, abstention, or third policy |
| Failed ballot and exhaustion | A non-approving accepted ballot remains append-only. While `rounds_used < max_rounds`, status stays `running` and another ballot requires the next complete roster pass. When no complete round remains, absence of a current approving ballot terminalizes as `failure`; the final failed ballot, when present, and failure are one coherent durable outcome. Ballots do not change `rounds_used`. | `implementation/milestones/brainstorming/skeleton.md:25-28,77,103,105`; `implementation/milestones/brainstorming/goal.md:230-241,256-259,266-276`; `orchestrator/brainstorming.py:668-737,1359-1404` | touch explicit ballot/result successors; do-not-loop ballots at one boundary or leave an exhausted session running |
| Success eligibility | `success` is legal only with a current accepted `closure_ballot` whose `approved` is true and whose round and target revision equal durable `rounds_used` and `accepted_target_revision`. The ballot, terminal status, `result`, and `closing_summary` become one winning durable session outcome; no durable snapshot exposes success without its ballot or an approved ballot still running. | `implementation/milestones/brainstorming/skeleton.md:25-28,77,92,105`; `implementation/milestones/brainstorming/goal.md:243-276`; `orchestrator/brainstorming.py:992-1126,1144-1208,1838-1865` | touch terminal eligibility and a combined closure successor; do-not-trust caller-declared success or publish partial terminal state |
| Result and closing | Terminal outcomes remain exactly `success` or `failure`. `result` remains exactly `outcome`, `target_ref`, `transcript_ref`, `rounds_used`, plus failure-only non-empty `reason`; outcome equals status, references match session authority, and rounds equal durable completed rounds. Both outcomes retain target/state/references and use Slice 4's exact `closing_summary`; failure reason matches its closing reason, and each terminal `object` vote is derived into `unresolved_objections` under the persisted human label without removing authored objection text. Failure may occur before a completed turn without a ballot. A terminal operation is not reported complete until `chat.md` reflects its winning state. | `implementation/milestones/brainstorming/skeleton.md:25-28,77,104-105`; `implementation/milestones/brainstorming/goal.md:218-221,243-279,336-370`; `implementation/milestones/brainstorming/slices/slice-01.md:101-102`; `implementation/milestones/brainstorming/slices/slice-04.md:145-146`; `orchestrator/brainstorming.py:950-1019,1054-1126,1695-1719` | touch closure-owned terminalization and closing publication; do-not-add caller routing, result variants, public error codes, or semantic prose validation |
| Slice boundary | Slice 5 adds no public HTTP route or error vocabulary, visualization, milestone transition, product adapter, permission/access rule, target-version scheme, or independent transcript/state store. Existing `discussion_turn`, completed-turn, target-revision, `material_interruption`, `closing_summary`, and result shapes remain compatible. | `implementation/milestones/brainstorming/skeleton.md:36-47,73-80,98-108`; `orchestrator/brainstorming_execution.py:12-27`; `orchestrator/service.py:2735-2887` | touch closure/result enforcement plus focused tests; do-not-touch service routes, panel, milestone flow, external roots, or later-slice contracts |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_closure`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Ballot truth is derived | `test_ballot_is_complete_ordered_and_decision_is_derived` | Missing, duplicate, reordered, extra, malformed, non-roster, non-`accept`/`object`, lead-object, wrong-round, wrong-revision, and mismatched-`approved` ballots are rejected; one complete valid ballot records the calculated flag. | strict |
| Both policies are exact | `test_unanimity_majority_and_lead_tiebreak_matrix` | Unanimity approves only all-accept; majority approves a strict accept majority, rejects a strict object majority, and an exact tie follows the persisted lead vote, including the two-participant lead-authority case. | strict |
| Votes stay on one accepted target | `test_target_mutation_invalidates_ballot_and_restores_only_target` | Lead/interlocutor mutation, deletion, recreation, or late mutation during closure accepts no vote, ballot, result, turn, revision, or round change; the last accepted target is restored and sibling sentinels are byte-identical. | strict accepted state; best-effort participant delivery |
| A failed ballot resumes real discussion | `test_failed_ballot_requires_another_complete_round` | A failed ballot remains once in order; a second ballot at that boundary is rejected; the persisted next roster pass sees it, and only that complete pass permits another ballot. | strict |
| Exhaustion is explicit failure | `test_round_exhaustion_without_approval_is_failure` | At `max_rounds`, a failed ballot or no lead proposal yields terminal `failure`, the exact durable round count, non-empty reason, unfinished-target closing, and no later turn or ballot. | strict |
| Success is revision-bound and atomic | `test_success_requires_current_approved_ballot_and_is_atomic` | Success without a ballot, with a failed/stale ballot, wrong round/revision, incomplete summary, or mismatched references is rejected; a current approving ballot exposes ballot, success result, closing, and transcript together, with every terminal object vote present in unresolved objections. | strict |
| Non-closure failure remains coherent | `test_failure_before_first_turn_retains_complete_evidence` | A zero-turn operational failure has no ballot, reports zero rounds and a non-empty matching reason, keeps target/state/references inspectable, publishes one complete closing, and is immutable. | strict structure; best-effort authored prose |
| Competing attempts cannot fork closure | `test_stale_closure_attempt_cannot_publish_losing_state` | Two closure attempts from one session revision produce one accepted ballot/result path; stale or interrupted candidates publish no duplicate ballot, contradictory result, or losing closing and recover the accepted target. | strict accepted state; optimistic conflict detection |
| Existing consumers remain compatible | `test_closure_reuses_sessions_and_changes_no_public_surface` | Votes use the persisted participant sessions and unchanged execution context; Slice 1-4 focused suites stay green after their provisional ballot/result fixtures adopt enforced truth; no service route/error, panel behavior, milestone state, or external-root sentinel changes. | strict compatibility; best-effort provider delivery |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:309-319`). Later slices add API, visualization, and
adapter checks; milestone closure retains the matrix in
`implementation/milestones/brainstorming/skeleton.md:124-137`.

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **verified current seams:** `SessionStore` currently validates/persists provisional ballots, lifecycle results, closings, and transcript publication; `BrainstormingCoordinator` owns accepted round/revision and target recovery; `ParticipantExecution` owns the persisted-session exchange. **slice-local consumer:** the new focused closure suite and the Slice 1-4 fixtures whose permissive ballot/success setup must adopt enforced truth. **declared later consumers:** Slices 6-8 consume the coherent result; their routes, view, and adapter are not touched now. | `orchestrator/brainstorming.py:916-1019,1054-1208,1695-1719,1923-2043`; `orchestrator/brainstorming_coordination.py:566-690,731-900`; `orchestrator/brainstorming_execution.py:85-180,218-377`; `implementation/milestones/brainstorming/skeleton.md:73-80` |
| pinned_facts | **closed facts:** complete-round lead-proposed ballots; exact accepted-ballot shape; current-revision binding and target-only invalidation recovery; the two exact policy decisions; one ballot per round; discussion-after-failure and failure-at-exhaustion; ballot-gated atomic success; coherent explicit failure/result/closing; and no public or later-slice surface. | `implementation/milestones/brainstorming/slices/slice-05.md:127-136`; `implementation/milestones/brainstorming/skeleton.md:23-47,73-80,92,103-105`; Operator Amendment A1, **Target versioning clarification** |
| verification | **focused:** the nine named closure checks pin ballot shape/truth, both policies, target invalidation/recovery, real discussion between ballots, exhaustion, success eligibility/atomicity, zero-turn failure, contention, and compatibility. **full:** repository unittest discovery remains the milestone gate. | `implementation/milestones/brainstorming/slices/slice-05.md:138-160`; `implementation/milestones/brainstorming/skeleton.md:124-137`; `implementation/milestones/brainstorming/goal.md:336-374`; `orchestrator/README.md:309-319` |
| reuse_posture | **checked:** exact roster/policy/result/closing validators, provisional ballot event, append-only state successors, target-exclusive coordination/recovery, persistent participant exchanges, whole-state CAS, transcript publication, current service routes, and existing focused fakes. **adopted:** those contracts and enforcement primitives. **extended:** the provisional ballot and terminal seams gain policy-derived, revision-bound, atomic closure eligibility. **new-with-why:** only the explicit closure evaluator/successor assigned by the skeleton; current code accepts `approved` without evaluating it and success without requiring a ballot. | `orchestrator/brainstorming.py:545-590,916-1019,1054-1208,1359-1415,1695-1719,1838-2043`; `orchestrator/brainstorming_coordination.py:137-153,583-690,731-877`; `orchestrator/brainstorming_execution.py:85-180,218-377`; `orchestrator/kvstore.py:343-359,391-457`; `orchestrator/tests/test_brainstorming_transcript.py:452-468,594-605`; `implementation/milestones/brainstorming/skeleton.md:58-64,77,92,105` |
| enforceability | **ballot/policy:** extend the exact ballot validator so `approved` is recomputed from immutable roster/policy. **revision/ownership:** reuse accepted revision, target-exclusive quiescent control, final observation, and target-only recovery. **one ballot/round and exhaustion:** validate against append-only transcript events, complete-pass count, and `max_rounds`. **atomic terminal truth:** add the skeleton-required ballot/result successor over existing whole-state CAS and lifecycle/result/closing validators. **publication:** reuse deterministic transcript reconciliation. **delivery/prose:** remain best-effort; no stronger promise is asserted. | `implementation/milestones/brainstorming/slices/slice-05.md:210-222`; `orchestrator/brainstorming.py:654-737,916-1019,1054-1208,1359-1415,1695-1719,1838-2043`; `orchestrator/brainstorming_coordination.py:137-153,583-690,731-877`; `orchestrator/kvstore.py:343-359,391-457`; `implementation/milestones/brainstorming/skeleton.md:23-34,77,92,103-105` |

### Reuse Posture

- **Checked:** the immutable roster and closure-policy validator; provisional
  `closure_ballot` validator/event; lifecycle, result, closing, append-only, and
  transcript-publication seams; accepted round/revision projection;
  target-exclusive recovery; persistent participant exchanges; whole-state CAS;
  current service routes; and stateful fake-executor tests. Authorities:
  `orchestrator/brainstorming.py:545-590,654-737,916-1019,1054-1208,1359-1415,1695-1719,1838-2043`;
  `orchestrator/brainstorming_coordination.py:137-153,583-690,731-877`;
  `orchestrator/brainstorming_execution.py:85-180,218-377`;
  `orchestrator/kvstore.py:343-359,391-457`;
  `orchestrator/service.py:2735-2887`;
  `orchestrator/tests/test_brainstorming_coordination.py:52-180`.
- **Adopted:** immutable roster/policy, exact validation, accepted target
  revisions, target-only recovery, persistent logical sessions, append-only
  session facts, whole-state CAS, transcript projection/reconciliation, and the
  existing focused-fake style.
- **Extended:** the existing ballot shape becomes enforceable closure truth:
  `approved` is derived, one ballot is admitted per complete round/current
  target revision, and a terminal ballot/result/closing is one accepted state
  outcome. Existing result and closing shapes do not grow.
- **New-with-why:** one deterministic closure evaluator and combined closure
  successor. The current ballot validator checks types but trusts `approved`,
  while current terminal validation checks result shape but not an approving
  ballot. The sealed design explicitly assigns those missing revision/vote
  transitions to Slice 5. Authorities:
  `orchestrator/brainstorming.py:916-947,992-1019,1054-1126`;
  `implementation/milestones/brainstorming/skeleton.md:77,92,105`.
- **Compatibility:** `discussion_turn`, participant-session, completed-turn,
  target-revision, transcript-event, closing-summary, and result shapes remain
  stable. Slice 4's provisional fixtures adopt calculated decisions; no parallel
  vote log, storage engine, API, panel path, milestone field, or external-product
  integration is added.

### Enforceability Gate

| invariant asserted here | mechanism that can enforce it | implementation gate |
|---|---|---|
| Complete, ordered, policy-true ballots | Extend the existing exact `closure_ballot` validator (`orchestrator/brainstorming.py:916-947`) over the immutable validated roster/policy (`orchestrator/brainstorming.py:545-590`) so the decision is calculated, never trusted | Shape/order/lead-proposal/policy matrices reject every malformed or mismatched ballot and compare the accepted `approved` flag with the exact rule. |
| Current-revision votes and mutation invalidation | Reuse accepted target revisions plus the exclusive target window, final observation, and target-only restore (`orchestrator/brainstorming_coordination.py:137-153,583-690,731-877`) around closure control work | Mutation timing matrices accept no partial vote/ballot/result, restore the retained target exactly, and keep sibling sentinels unchanged. |
| One ballot per complete round | Existing roster-prefix/round validation (`orchestrator/brainstorming.py:654-737`) and ordered transcript-event successor (`orchestrator/brainstorming.py:830-885,1359-1415`) provide the extension seam for a per-round ballot guard | Repeat-at-boundary and failed-ballot fixtures require another full roster pass before another accepted ballot; ballots never change `rounds_used`. |
| Success and final exhaustion are one coherent durable outcome | Add the skeleton-required combined closure successor over current lifecycle/result/closing validation (`orchestrator/brainstorming.py:950-1019,1054-1208`) and the existing revisioned whole-state CAS (`orchestrator/brainstorming.py:1838-1865`; `orchestrator/kvstore.py:343-359,391-457`) | No intermediate durable snapshot has approved-running, success-without-ballot, or final-failed-running state; stale/failing CAS exposes the old whole state or one exact winner. |
| Explicit non-closure failure and retained evidence | Existing `created`/`running` to `failure` transitions, exact result/closing validators, immutable terminal history, and target/transcript references (`orchestrator/brainstorming.py:30-42,950-1208`) | Zero-turn and operational-failure matrices require matching non-empty reason, exact zero/current rounds, complete closing, retained references, and no post-terminal write. |
| Closing publication agrees with terminal state | Winning-state transcript rendering and read-time reconciliation (`orchestrator/brainstorming.py:1503-1638,1695-1719`) plus atomic replacement (`orchestrator/brainstorming.py:118-136`) | Success/failure/interruption tests inject publication failure and prove no partial file; every terminal object vote is derived into the closing's unresolved objections, and the next read repairs one ballot/closing from winning state before return. |
| Optimistic contention cannot fork closure | Existing session revision comparison and CAS (`orchestrator/brainstorming.py:1838-1865`) combined with target exclusivity | Two-attempt tests observe one ballot/result successor and no duplicate participant control overlap or losing target/transcript publication. |
| Best-effort delivery is not promoted | Existing explicit-session participant execution, single repair, and quiescence evidence (`orchestrator/brainstorming_execution.py:85-180,197-377`) retain provider delivery limits while accepted-state gates stay strict | Provider failure may advance opaque provider history but cannot create accepted votes or closure; tests claim neither exactly-once delivery nor semantic prose correctness. |
| No public or product expansion | Current HTTP dispatch contains no Brainstorming route (`orchestrator/service.py:2735-2887`); later Brainstorming surfaces remain assigned to Slices 6-8 (`implementation/milestones/brainstorming/skeleton.md:78-80`) | Compatibility check observes no new route/error, panel behavior, milestone state, or external-root write. |

If implementation trusts `approved`, permits direct success, accepts a ballot
after target drift, appends terminal pieces in separate observable states, or
relies on prompt obedience for target ownership, the strict guarantee is not
delivered.

### Planning Material Disposition

- **Adopt:** the sealed skeleton as the operative boundary and the generated goal
  snapshot only for the lead-proposal, vote-policy, exhaustion, and retained
  result intent the skeleton assigns to this slice.
- **Revise:** the current provisional ballot and generic terminal seams into the
  enforced Slice 5 contract without changing their cross-slice shapes.
- **Reject:** exploratory brainstorming material as independent authority, plus
  any VCS restoration, permission/custody expansion, event framework, caller
  routing, machine-API, Persona, or product-specific closure semantics.

Authority:
`implementation/milestones/brainstorming/skeleton.md:3-5,36-67,77,92,105,110-122`;
`implementation/brainstorming/README.md:3-8,12-17`;
Operator Amendment A1, **Target versioning clarification**.
