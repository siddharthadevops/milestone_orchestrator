# Slice 08 — Milestone `need_rethink` adapter

## Register 1 — Intent

### What this slice builds

This slice lets a milestone worker pause on one focused design doubt and ask
the independent Brainstorming process to produce a small amendment or proposal.
The discussion keeps its own record and result; it is not disguised as another
milestone review.

A `need_rethink` request names the proposal target and a positive caller-chosen
round bound. Only then does the adapter create a Brainstorming session for that
target. Creation retains its exact existing-or-absent state as
`recovery_baseline_revision`, but that baseline is not accepted target state.
`accepted_target_revision` remains null until a completed lead turn creates it.

This slice also delivers that acceptance-provenance correction to the existing
Brainstorming state, coordination, lifecycle, stop, and dedicated-view
consumers. Target versions are Brainstorming revision identifiers or hashes,
independent of Git or any VCS. Only completed lead work may create or advance an
accepted revision. A mutation during any other turn is rejected without
accepted progress or round consumption, and only `target_path` is recovered
from the last accepted Brainstorming revision or the launch baseline. The same
pending worker action may then be attempted once more; a second invalid target
mutation before it completes restores the target again and ends the session as
coherent `failure`. This allowance and the one discussion-envelope repair are
independent and neither resets the other.

The adapter introduces no fixed maximum round count, artifact-size ceiling,
target-history allowance, or global active-session quota. Actual inability to
create a session may use the existing unavailable outcome without creating
state or starting participants; it remains an operational fault, not a
discussion result.

If Brainstorming succeeds, an implementer or fixer continues the exact
conversation that asked for help. A reviewer instead takes a fresh look. A
failed discussion returns through the already-declared caller-specific route.
Asking for help never counts as completed work, review evidence, or approval.

### Ownership and boundary

This slice owns the bridge: validation of the rethink signal, durable
association with the waiting milestone call, creation of the independent
session using the named target and inherited context, and deterministic
consumption of its result.

Brainstorming remains sole owner of its discussion, recovery baseline, accepted
target revisions, transcript, and result. The milestone remains sole owner of
unit progress, findings, review, sealing, and escalation. A successful proposal
cannot approve itself.

If adopting a proposal requires a fixer's own sealed slice note to change, the
milestone reuses its existing provisional correction and independent delta
ratification path. Brainstorming cannot edit sealed milestone documents or
generated records; its target is a separate proposal artifact.

### Guarantee posture

- **Strict signal boundary:** a valid `need_rethink` is help-seeking, not work
  completion. Without it, ordinary results, validation failures, provider
  failures, retry, and cleanup behavior remain unchanged and no target is
  observed or reserved by Brainstorming.
- **Strict target authority:** creation captures an unaccepted target baseline
  and leaves accepted state null. Only completed lead work creates or advances
  accepted target state. Interlocutor, control, and incomplete-lead mutations
  accept no turn, round, or revision and recover only the target. One corrected
  attempt of the same pending worker action is allowed; another invalid target
  mutation restores the target and returns coherent `failure`. The independent
  envelope-repair allowance cannot reset this bound. The handoff names a
  retained lead-accepted Brainstorming revision, never the baseline or live
  drift.
- **Strict caller bound:** `max_rounds` is any positive integer. No fixed
  numeric round, artifact, history, or global-session admission policy is added.
- **Optimistic:** durable state and existing locking decide which competing
  milestone action wins; stale work cannot apply a return twice.
- **Eventual:** the milestone may observe Brainstorming completion on its next
  check. Until then the same work item remains visibly paused.
- **Best-effort:** session creation, provider delivery, and liveness are not
  exactly-once across an unacknowledged crash. Uncertain work is never promoted
  to a result.

Callers that mutate `target_path` while a session is active are outside the run
contract. Brainstorming neither attributes nor merges those writes. The full
inherited tools and execution context remain unchanged: participants may
inspect and reason about supplied references and legitimate neighbouring
material. Target-version selection and recovery never derive authority from
repository or VCS state.

### Dependencies and consumers

This slice depends on Slices 1–7: generic state and roster, persistent
participant conversations, ordered target revisions, transcript, closure,
standalone lifecycle, and dedicated view.

It owns the corrective implementation that separates the recovery baseline
from accepted state and updates every affected current consumer. It also owns
focused regression coverage proving that the discarded 16-round, 8-MiB-target,
32-MiB-history, 17-revision, and eight-active-session values are not product
admission thresholds. No quota state, reservation, migration, legacy
stop-only branch, or quota-specific retry is implemented. The same corrective
coverage makes repository/VCS reads by target-version selection and recovery
observable and fail-fast.

The adapter reuses the milestone's existing result/finding/gap validation,
provider-session continuation, atomic transition, design-correction
ratification, and review/seal routes. Consumers are implementation, fixing,
full review, change review, final seal review, and the dedicated Brainstorming
view.

No Agent99, Life, LPC, Tutor, external repository, or milestone browser surface
is changed. The standalone view keeps its route, envelope, and page.

### Acceptance

- A valid signal pauses current work without recording completion, review
  judgment, fix, or seal.
- Without `need_rethink`, ordinary outcomes create no Brainstorming session,
  target baseline, reservation, mutation check, recovery step, or new rejection.
- A valid signal names a separate proposal target and any positive
  `max_rounds`, including values above 16.
- Session creation captures the target's exact existing-or-absent state as an
  unaccepted recovery baseline and initializes accepted target state to null.
- A valid target is not refused solely because it exceeds 8 MiB, retained
  revisions would exceed 17 or 32 MiB, or eight other distinct-target sessions
  are active.
- Interlocutor or incomplete-lead mutation rejects the worker outcome, advances
  no accepted state, consumes no round, and restores only the target.
- The same pending worker action receives one target-mutation correction after
  recovery. A second invalid mutation restores only the target and publishes
  one coherent failure; its independent envelope-repair allowance cannot reset
  that bound, including across restart.
- The first completed lead turn creates accepted target state even if bytes are
  unchanged; only later completed lead work may advance it.
- Target-version creation, acceptance, recovery, and restart reconciliation
  inspect no Git/VCS state or repository metadata. A focused fail-on-access
  check observes those reads separately from unchanged-path checks, while
  participant access to contextual references remains intact.
- Before lead acceptance, the dedicated view remains readable and identifies
  the target as not yet accepted without previewing the baseline as accepted.
- A recorded active discussion survives restart without changing the
  milestone's place. Unacknowledged creation advances nothing.
- Success returns the recorded lead-accepted proposal. Builders continue their
  exact origin conversation; reviewers start a fresh provider session.
- A fixer's own-note adoption reuses the existing provisional correction,
  integrity/rollback, independent delta verdict, and note gate.
- A genuine discussion failure uses the predeclared caller route. Access,
  lifecycle, provider, stop-incomplete, target-in-use, and actual resource
  unavailability remain operational faults and consume no domain fallback.
- The motivating fixer flow produces a small amendment, resumes the same fixer,
  receives normal delta review, and continues without reopening all milestone
  documentation.

This slice is expected to exceed the roughly 500 changed-line target. It joins
five worker-result paths with restart-safe suspension and return routing, while
also correcting acceptance provenance and its state, coordination, lifecycle,
stop, and view consumers. The focused restart, routing, correction, and
compatibility matrices are necessary to prove that those surfaces move as one
observable contract; splitting them would leave an intermediate state in which
the adapter and the accepted-target consumers disagree. Generated and
mechanical changes remain excluded.

### Non-goals

- No redesign of transcript, closure, result, standalone routes, or page.
- No fixed round maximum, target-size ceiling, retained-history limit,
  active-session quota, quota version, migration, retirement regime, or
  quota-specific correction loop.
- No new milestone phase or substitute for verification, review, sealing,
  correction, or escalation.
- No use by documentation drafters, classifiers, verification commands, or
  external products.
- No new route, launch form, notification, event feed, or push transport.
- No repository requirement, VCS meaning, or repository/VCS inspection by
  target-version selection or recovery.
- No new identity, permission, sandbox, work-area, custody, idempotency,
  provider, or threat model.
- No edit outside the requested target and no discussion edit to sealed or
  generated milestone artifacts.
- No workspace snapshot, sibling capture, repository rollback, or recovery
  outside `target_path`.
- No target monitoring around an ordinary milestone call before a valid rethink
  request creates a session.

### Risks

- Mistaking help-seeking for completed work could skip review.
- Treating the origin worker as a participant before session creation would add
  a custody model that the amendment rejects.
- Calling the launch baseline accepted would erase lead-turn provenance.
- Reading the live target instead of the retained accepted revision could hand
  off drift.
- Treating a proposal as self-approving could rewrite sealed design.
- Concurrent final reviewers may ask different questions; one deterministic
  request wins and the review attempt restarts fresh.
- A service outage can look like disagreement; operational and domain failure
  remain distinct.
- Fixed cross-project quotas would let callers deny valid sessions and add
  unsupported migration machinery. This slice explicitly excludes them.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority | touch / do-not-touch |
|---|---|---|---|
| Milestone worker signal | The exact status is `need_rethink`, eligible only for `implement`, `fix_findings`, `review_round`, `delta_review`, and `seal_half`. Its object has exactly non-empty `question`, one current `finding`, normalized workspace-relative non-empty `target_path`, and positive-integer `max_rounds`. `implement` and `fix_findings` also require exactly one current `failure_gap`; report kinds forbid it. A fixer finding equals one queued finding and siblings remain pending. No ordinary result, work claim, retry, finding list, disposition, verdict, or slice plan may be mixed in. | frozen mandate, Milestone integration; skeleton, Milestone adapter | touch common worker output validation, eligible prompts, and focused tests; do-not-enable other kinds, preassign targets, drop sibling findings, or treat signal as completion |
| Ordinary origin outcomes | Without a valid signal, all five eligible paths retain ordinary result, validation, provider-failure, retry, and cleanup behavior. No Brainstorming target reservation, baseline, mutation observation, recovery, or outcome rejection occurs. | skeleton, Milestone adapter; Amendment A1 | touch only the alternative signal branch; do-not-add pre-session custody |
| Session-creation target boundary | After signal and target validation, the adapter creates a session naming the target, captures its exact existing-or-absent state as `recovery_baseline_revision`, and initializes `accepted_target_revision` to null. Only a completed lead turn creates or advances accepted state. Any mutation during another turn rejects that outcome and recovers only `target_path` from the accepted revision or baseline. The same pending worker action has one target-mutation correction; repetition restores the target and returns coherent `failure`. Its independent envelope-repair allowance cannot reset that bound. Pre-session writes are not attributed or merged. | skeleton, Roles, rounds, revisions, and Invalid target mutation; Amendment A1 | touch create adapter, bounded correction/failure, and target-only revision/recovery seam; do-not-monitor origin calls, promote baseline, inspect VCS, or recover another path |
| Resource posture | `max_rounds` is any positive integer. No fixed target bytes, revision count, retained-history bytes, or global active-session count is an admission rule. Actual inability to create may return the existing unavailable outcome without effects. It is operational and consumes no finding/gap fallback. | skeleton, Resource posture; frozen mandate, Request contract | touch focused regression and existing unavailable route; do-not-add quota state, reservation, migration, legacy branch, or quota-triggered correction |
| Generic request and run policy | `workspace_path` is the milestone's resolved workspace; question, target, and positive `max_rounds` equal the signal. `context.source_payload` equals the finding; `brief` is non-empty; references are the stable unique current skeleton/governing/unit artifacts, omitting absent/placeholders and the target. The adapter supplies exactly lead then interlocutor and selects unanimity; existing resolution prefers cross-family and records same-family fallback. Current execution context passes unchanged, so participants may inspect and reason about references and legitimate neighbouring material. | frozen mandate, Request contract and Inherited execution context | touch translation into existing create contract; do-not-interpret finding, add taxonomy, narrow contextual access, or re-resolve work area |
| Durable suspension and attachment | The valid signal records origin unit/kind/family/model/effort, explicit origin provider reference where return needs it, and exact signal. After create returns, the session id is recorded before transition. While active, origin status and review/fix/seal counters do not move and no later worker runs. Recovery follows only the recorded session; stale/concurrent consumers cannot apply two returns. Unacknowledged creation has no exactly-once claim. | frozen mandate, Milestone integration | touch additive adapter state and deterministic step; do-not-store discussion in milestone rounds or advance while waiting |
| Successful return routes | Success is accepted only from the recorded session. Handoff contains its session id, exact result, and a non-null retained accepted target revision created by completed lead work. Implement/fix continue the exact origin provider session; report kinds start fresh. A seal request waits for sibling halves, selects deterministically, invalidates the attempt, re-verifies, and starts a fresh seal attempt. | frozen mandate, Milestone integration; Amendment A1 | touch session-aware calls and existing return gates; do-not-resume reviewers, count the request, hand off baseline/live drift, or bypass review |
| Amendment adoption | A Brainstorming target is a proposal. A fixer's own-note correction reuses the existing `design_correction` contract and adds `brainstorming_authority: {session_id, accepted_target_revision}` bound to the recorded handoff. Authority content comes from that retained revision. Existing single-note scope, provisional rollback, independent delta verdict, and note-gate update remain authoritative. | frozen mandate, Motivating case and Milestone integration | touch the correction authority variant; do-not-self-ratify, edit another sealed artifact, or add a parallel lane |
| Failure and operational split | A validated terminal failure to produce or agree on the target, including repetition after the one target-mutation correction, invokes the predeclared domain route. Implement/fix use their unchanged `failure_gap`. A report kind sends the unchanged source finding to its ordinary fixer checkpoint. No origin session resumes and no fresh review starts. Invalid request/access, target-in-use, unavailable lifecycle/resources, stop-incomplete, uncertain creation, and provider/continuation faults remain operational and consume neither fallback. | frozen mandate, Result contract and Milestone integration; skeleton, Invalid target mutation | touch deterministic result consumption and existing routes; do-not-invent adapter results, synthesize domain evidence, or erase terminal evidence |
| Target and compatibility boundary | The normalized proposal target resolves inside the current primary workspace and must not equal, overlap, or alias a context reference, sealed/generated milestone artifact, Brainstorming authority, or another nonterminal session target. From creation through handoff, only Brainstorming revisions version it and recovery is confined to that path. The dedicated view preserves its public shape for null pre-lead and accepted-revision states. No Git/VCS fact or repository metadata selects, validates, restores, or merges a target revision. | skeleton, Invalid target mutation and Standalone projection; Amendment A1 | touch adapter admission, revision correction, no-VCS verification, view projection, and tests; do-not-change ordinary behavior, public routes/page, generated artifacts, external roots, or another path |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_state orchestrator.tests.test_brainstorming_milestone_adapter orchestrator.tests.test_brainstorming_coordination orchestrator.tests.test_brainstorming_api orchestrator.tests.test_brainstorming_visualization`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Control result is exact and non-completing | `test_need_rethink_signal_is_closed_eligible_and_non_completing` | Five eligible kinds accept only the exact kind-specific object with valid target and positive round bound, including a value above 16; malformed or mixed work claims accept no progress. | strict |
| Ordinary paths do not enter Brainstorming | `test_ordinary_results_and_provider_failures_create_no_brainstorming_target_state` | Valid ordinary results, validation failures, and provider failures retain existing behavior with no target observation, reservation, baseline, recovery, or new rejection. | strict compatibility |
| No fixed numeric admission policy | `test_request_and_target_admission_has_no_fixed_global_quota` | A request above 16 rounds, a target above 8 MiB, a session whose retained revisions cross the discarded 17/32-MiB values, and a ninth concurrent distinct-target session are not refused solely by those numbers. Actual injected unavailability remains a side-effect-free 503. | strict |
| Creation captures an unaccepted baseline | `test_rethink_session_creation_captures_unaccepted_target_baseline` | Existing, absent, and pre-session-changed targets are captured exactly at creation; accepted revision stays null and non-lead/incomplete-lead mutation restores only the target. | strict |
| Completed lead work owns acceptance | `test_completed_lead_turn_creates_or_advances_target_revision_atomically` | Setup creates no accepted state. First completed lead work creates it even unchanged; later completed lead work alone advances it; failed durable acceptance records neither turn nor revision. | strict accepted state; optimistic conflict detection |
| Target versions never depend on a repository | `test_target_revision_and_recovery_never_probe_vcs_or_repository_metadata` | Creation, completed-lead acceptance, invalid-mutation recovery, and restart reconciliation run with fail-on-access observation of their process-launch and filesystem-read seams. Any Git/VCS command or repository-metadata read fails the check; unrelated repository-state changes leave revision identities and recovery outcomes unchanged. | strict |
| Invalid target mutation has one bounded disposition | `test_invalid_target_mutation_allows_one_correction_then_fails_coherently` | For a discussion or closure worker action, the first invalid target mutation restores only the target and accepts no turn, round, revision, vote, or result; a second before that action completes restores the target and publishes one failure, closing, and result. The one envelope repair and one target-mutation correction remain independent across restart and neither resets the other. | strict |
| Existing view accepts pre-lead state | `test_coordination_without_lead_acceptance_is_not_yet_accepted` | With accepted revision null, the authorized view returns target ref plus null revision/existence/content and `truncated: false`; after lead acceptance it reads only that revision. | strict |
| Translation preserves caller facts | `test_adapter_builds_exact_request_roster_and_execution_context` | Request copies question/target/positive round bound, preserves finding as source payload, builds exact references and two-person unanimity roster, and passes primary/additional roots and fallback fact unchanged. | strict |
| Protected targets are refused before create | `test_adapter_rejects_protected_and_aliased_targets_before_creation` | Direct/aliased context, sealed/generated, Brainstorming-authority, and active-session targets are refused without session, target, or milestone mutation; a separate proposal target is accepted. | strict |
| Recorded wait is restart-safe | `test_rethink_pause_recovery_uses_recorded_session_without_advancing` | Recovery, a second driver, and repeated terminal inspection cannot consume twice or advance while active; uncertain creation advances nothing. | strict state; optimistic contention; best-effort create |
| Builders return to exact conversation | `test_implementer_and_fixer_continue_exact_origin_session` | Handoff uses the recorded provider reference and non-null lead-accepted revision, never baseline/live drift; only the resumed ordinary envelope advances and fixer still enters delta review. | strict routing; best-effort delivery |
| Reviewers take a fresh look | `test_review_delta_and_concurrent_seal_restart_fresh` | Full/delta review creates no judgment from the request and reruns fresh. Concurrent seal halves quiesce, one request wins deterministically, verification precedes the fresh attempt. | strict routing; optimistic winner |
| Domain and operational failures stay distinct | `test_failure_reuses_builder_gap_or_reviewer_finding_without_false_result` | Genuine discussion failure uses the exact predeclared builder gap or report finding; lifecycle/access/provider/actual-unavailability faults consume neither. | strict |
| Motivating amendment reuses ratification | `test_fixer_amendment_reuses_brainstorming_revision_and_design_correction` | The focused proposal resumes the same fixer, binds own-note correction to its retained accepted revision, and exercises existing ratify/retry/remodel/operator outcomes without a documentation reset or parallel lane. | strict |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`.

### Question Battery

The skeleton's Question Battery is inherited. Slice-specific answers:

| question | answer | evidence |
|---|---|---|
| consumers_touched | Five eligible worker-result paths, atomic milestone state, provider continuation, standalone Brainstorming create/result/target revisions, dedicated view, and existing correction/review/seal routes. | Dependencies and consumers |
| pinned_facts | Exact signal and fallback schema; ordinary-path compatibility; unaccepted baseline and lead-only accepted revision; one bounded target-mutation correction independent of envelope repair; no fixed quota; suspension; builder/fresh-review returns; correction ratification; domain/operational split; no VCS or sealed target. | Pinned-Facts Table |
| verification | Focused modules pin signal, ordinary behavior, no fixed threshold, baseline/acceptance, fail-on-access detection of repository/VCS dependencies, bounded invalid-mutation failure, pre-lead view, translation, target protection, restart, exact continuation, fresh review, routing, and ratification. | Verification Contract |
| reuse_posture | Existing result/finding/gap validators, driver state/locks, explicit provider sessions, standalone Brainstorming lifecycle, target-only recovery, view, gap routing, and design-correction delta gate are adopted. New work is one alternative result, recorded association, acceptance-provenance correction, and correction authority variant. | Reuse Posture |
| enforceability | Closed validators isolate the signal; create captures baseline; role/quiescence/CAS enforce lead-only acceptance; fail-on-access observation detects repository/VCS probes; atomic milestone state serializes waiting/return; explicit provider references enforce routing; retained revision identity gates handoff and correction. | Enforceability Gate |

### Reuse Posture

- **Checked and adopted:** common worker output validation; all five origin
  consumers; atomic milestone state and lock; explicit provider start/continue;
  standalone Brainstorming create/inspect/stop; immutable target revisions and
  target-only recovery; dedicated view; gap/operator routing; and existing
  design-correction integrity, rollback, delta verdict, and note gate.
- **Extended:** one alternative `need_rethink` result, one recorded
  origin/session association, a distinct unaccepted recovery-baseline fact,
  nullable accepted target state, one bounded target-mutation correction
  composed with the existing envelope repair and failure result, and one
  Brainstorming revision authority variant for own-note correction.
- **Why new:** ordinary results cannot suspend on an independent session, setup
  cannot satisfy lead-only acceptance, and the correction gate needs immutable
  accepted proposal authority rather than a drifting live target.
- **Compatibility:** ordinary worker outputs, lifecycle transitions, public
  Brainstorming routes/view schema/page, milestone panel, and external projects
  retain behavior. No quota or migration contract is added.

### Enforceability Gate

| invariant | enforcing seam | implementation gate |
|---|---|---|
| Exact non-completion signal | Existing closed status/kind, finding, gap, and reserved-key validation | Contract matrices reject malformed, ineligible, or mixed claims before adapter progress. |
| Ordinary boundary unchanged | Alternative branch starts only after valid `need_rethink` | Five-kind compatibility matrix observes no Brainstorming state or target operation on ordinary paths. |
| Exact unaccepted baseline | Existing create plus target-only revision seam | Existing/absent/pre-session-change fixtures prove capture-at-create and null accepted state. |
| No fixed numeric quota | Positive-integer request validation and absence of artifact/history/global-count thresholds | Regression crosses every discarded value without threshold-only refusal and separately injects actual unavailability. |
| Lead-only accepted provenance | Persisted role, exclusive quiescent turn acceptance, final target observation, exact state validation, and CAS | Setup/interlocutor/failure/lead matrices prove only completed lead work creates or advances acceptance. |
| Bounded invalid target mutation | Exact target observation and recovery, one persisted correction allowance for the pending worker action, and existing failure/closing terminalization | Restart matrices prove the first invalid mutation accepts no progress and permits one corrected attempt; repetition restores only the target and publishes one coherent failure, while envelope repair neither resets nor is reset by this allowance. |
| Nullable view remains coherent | Exact not-yet-accepted projection and immutable accepted-revision read | Pre-lead and post-lead fixtures return the pinned public target shape without reading live unaccepted content. |
| One recorded wait/return | Atomic milestone state and step lock plus recorded Brainstorming session id | Recovery/concurrency tests produce one terminal consumer and unchanged origin counters while active. |
| Exact builder versus fresh reviewer | Explicit provider references with no recency fallback | Fake provider records prove builder continuation and new reviewer sessions. |
| Handoff uses accepted revision | Result validation and immutable retained revision lookup | Live-path drift cannot replace the recorded lead-accepted revision or baseline. |
| Proposal cannot self-ratify | Existing provisional correction, rollback, independent delta verdict, and note gate | Correction matrix proves single-note scope and all existing verdict routes. |
| Operational failure cannot consume domain fallback | Existing typed lifecycle/API errors versus recorded result | Result matrix keeps genuine failure and infrastructure faults mutually exclusive. |
| Target-only recovery writes | Amendment A1 target-only authority | Target identity and unchanged-path checks prove recovery changes only `target_path`; they make no claim about read-only dependencies. |
| No repository/VCS dependency | Amendment A1 plus `test_target_revision_and_recovery_never_probe_vcs_or_repository_metadata` | Fail-on-access observation of process-launch and filesystem-read seams detects every Git/VCS command or repository-metadata probe during target-version creation, acceptance, recovery, and restart; unrelated repository state cannot affect the result. |

No mechanism promises exactly-once provider delivery, perfect liveness, or
immediately current UI observation. Those remain best-effort or eventual.

### Planning Material Disposition

- **Adopt:** the skeleton, frozen mandate, and Operator Amendment A1.
- **Revise:** the motivating arrow into the exact signal, recorded suspension,
  Brainstorming-revision handoff, and existing-route returns pinned here.
- **Reject:** machine/Persona projection proposals, event cursors, replacement
  errors, bearer tokens, push transport, fixed quotas, quota migration, and all
  Git/VCS target-version or restoration designs.
