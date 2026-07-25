# Generic Brainstorming Orchestrator — Milestone Skeleton

Mandate: `implementation/milestones/brainstorming/goal.md`. This is a thin
planning contract. Slice notes pin their public seams and focused acceptance
checks just in time.

## Register 1 — Intent

### Goal Restatement

Build a standalone way for a lead agent and one or more interlocutors to work
through one caller-bounded question while the lead constructs the requested
result. The human record reads like a discussion, while the service keeps the
machine state needed to order turns, supervise participants, and decide whether
the group closed successfully.

The first user is the Milestone Orchestrator: a focused design doubt can pause
normal work, run this independent discussion, and return by the route
appropriate to the worker that asked. The core belongs to Brainstorming, not
milestones. It stays neutral enough for a later Agent99 adapter, but this
milestone does not build that adapter.

### Guarantee Posture

- **Strict:** accepted requests and rosters are validated; roles and turn order
  are fixed; and the caller supplies a positive `max_rounds`, which is the
  discussion's round bound. Session creation retains the target's exact
  existing-or-absent state as an unaccepted Brainstorming recovery baseline.
  `accepted_target_revision` remains null until a completed lead turn creates
  it, and only a later completed lead turn may advance it. Interlocutors are
  instructed not to edit the target. A mutation during an interlocutor turn,
  control work, or a lead attempt that does not complete is an invalid worker
  outcome: it accepts no turn, round, or target revision and recovers only
  `target_path` from the last accepted Brainstorming revision, or from the
  recovery baseline before one exists. Each pending worker action has one
  target-mutation correction allowance: after recovery, that same action may be
  attempted once more. A second invalid target mutation before it completes
  restores the target again and ends the session as coherent `failure`, without
  accepting the rejected work or consuming a round. This allowance and the
  discussion-envelope repair allowance are independent and neither resets the
  other. Target revision identifiers or hashes are owned by Brainstorming and
  have no VCS meaning. Rounds, revisions, votes, results, and the ordered human
  transcript agree with durable state.
- **Operational availability:** this milestone introduces no fixed
  process-global session quota, artifact-size ceiling, target-history byte
  allowance, revision-count allowance, or fixed upper bound on
  `max_rounds`. If the service cannot admit a session because required runtime
  resources are actually unavailable, creation may return the existing
  unavailable outcome without creating session state or starting participants.
  That is an operational refusal, not a caller-triggerable contractual quota or
  a discussion failure.
- **Best-effort:** frozen-process detection inherits the existing measurable
  CPU, process-set, and output-progress watchdog. An unmeasurable interval is
  treated as live; this milestone does not claim perfect provider liveness or
  exactly-once execution.
- **Eventual:** the visualization may lag durable state by its normal refresh
  interval. It is a projection, never process authority.

These guarantees assume callers do not mutate `target_path` while a
Brainstorming session is active. Concurrent external writes are outside the run
contract and are neither attributed nor merged. Participants retain the
caller's complete inherited tools and execution context; target ownership is a
turn-acceptance rule, not a new permission, sandbox, custody, or threat model.
They may inspect and reason about supplied references and legitimate
neighbouring material; only target mutation and recovery are narrowed.

### Boundary and Non-Goals

- No milestone units, slices, seals, review families, or milestone chronology
  inside the Brainstorming core; the milestone side is an adapter.
- No Agent99, Life Documents, cloud-drive, legal, or other target-specific
  adapter; no domain taxonomy or answer-options field.
- No new permission, sandbox, root, work-area, idempotency, or provider-policy
  system. The caller's resolved execution context remains authoritative.
- No coordinator judgment about the domain, no interlocutor target edits, and
  no raw diagnostics in the human transcript.
- No replacement or bypass of ordinary review, delta review, sealing,
  consultation, or gap/operator routing.
- Target-version selection and recovery have no repository requirement and
  inspect no Git/VCS state or repository metadata. Recovery mutates only
  `target_path`; this does not restrict participant inspection or reasoning
  through the inherited execution context.
- No milestone-invented resource policy. A caller chooses the positive round
  bound; deployment-level availability remains an operational concern.

### Reuse Posture

- **Checked:** current structured-output validation, append-only state,
  one-shot CLI calls, process-group supervision, resolved multi-root context,
  local API/access controls, panel projection, current fixer consultation, and
  the existing target-only revision seam.
- **Reused:** validation and atomic-history patterns; process tracking,
  liveness and stop propagation; inherited root context; target-only recovery;
  and the service's lifecycle, access, and projection conventions.
- **Extended:** a separate Brainstorming lifecycle, durable discussion state,
  persistent participant sessions, exclusive quiescent turn acceptance,
  Brainstorming-owned target revisions, revision-bound closure, transcript,
  standalone interface, and one adapter.
- **Why new machinery:** today's workers and fixer consultation are bounded
  one-shot calls. They neither maintain a multi-party discussion nor let one
  designated lead progressively revise a target, and milestone rounds cannot
  be repurposed without violating the independent-process boundary.
- **Compatibility:** Brainstorming state stays outside the milestone ledger;
  the adapter passes caller context through unchanged; existing milestone and
  Agent99 work-area ownership remain where they are.

### Planned Slices

| id | title | intent |
|---:|---|---|
| 1 | Session contract and durable state | Add the product-neutral request, resolved roster, closure-policy, lifecycle, and result contracts, with atomic auditable state and no milestone vocabulary. |
| 2 | Persistent participant execution | Keep one logical CLI session per participant across turns, validate each control envelope, inherit the caller's execution context, and reuse existing liveness and stop supervision. |
| 3 | Ordered rounds and lead-owned target | Run complete passes through the persisted order, expose prior discussion and the current target to each turn, count only completed passes, and enforce Brainstorming-owned, lead-only accepted target revisions. |
| 4 | Plain-language session transcript | Produce ordered Markdown opening, turn, material-interruption, and closing entries in `chat.md`, while keeping identifiers and diagnostics in structured state and technical logs. |
| 5 | Revision-bound closure and results | Record closure votes against one target revision, invalidate votes after edits, apply the selected policy deterministically, and return only coherent `success` or explicit `failure`. |
| 6 | Standalone lifecycle API | Let a caller create, inspect, follow, and stop Brainstorming without creating a milestone, using stable product-neutral request, state, and result shapes. |
| 7 | Dedicated brainstorming visualization | Show the required session, roster, policy, round, process, transcript, target, and result projection without embedding it in milestone chronology. |
| 8 | Milestone `need_rethink` adapter | Accept focused rethink requests from implementers, fixers, and reviewers; correct recovery-baseline versus lead-accepted target state; suspend the normal transition; invoke Brainstorming; and test same-session continuation, fresh-review return, failure routing, and the motivating amendment flow. |

### Question Battery

| question | answer | evidence |
|---|---|---|
| victim | The immediate victims are the milestone operator and active workers: a small resolvable contradiction currently forces a full documentation reset, review, and reseal instead of one bounded decision. | frozen mandate, Motivating case |
| machinery | The milestone adds an independent session lifecycle, persistent participant discussions, ordered coordination, lead-owned target revisions, transcript, closure, standalone interface, visualization, and a milestone adapter. | frozen mandate, Process boundary and Participants |
| consumers | Immediate consumers are Milestone implementer, fixer, and reviewer paths plus standalone operators. Agent99 is a future compatibility consumer, not part of this delivery. | frozen mandate, Milestone integration and Standalone use |
| cheaper_alternative | Doing nothing preserves the full-reset cost. Extending fixer consultation is insufficient because it decides only finding rejection and has no target-construction lifecycle. Reusing milestone review rounds violates the independent-process mandate. | frozen mandate, Goal and Process boundary |
| cost | Eight slices add contracts/state, participant execution, coordination, transcript, closure, standalone API/view, and the adapter. The target-version correction is confined to Brainstorming-owned revisions and existing consumers; no quota, VCS, milestone-ledger, or Agent99 migration is introduced. | this skeleton, Planned Slices |
| threat_model | No new remote attacker or permission model is introduced. Worker control envelopes are validated, supplied context is examined rather than obeyed, only completed lead work advances accepted target state, and recovery changes only the target. | frozen mandate, Contextual altitude and Inherited execution context; Amendment A1 |
| enforceability | Existing validation, atomic state, process-group supervision, stop propagation, and projection seams are reused. Slices 3 and 8 establish the unaccepted baseline, nullable accepted revision, exclusive quiescent acceptance, lead-only advancement, and target-only recovery; Slice 5 binds votes to that revision. Slice 8's fail-on-access regression separately detects repository/VCS probes without narrowing participant tools or context. | Planned Slices 3, 5, and 8; Amendment A1 |

## Register 2 — Pinned Facts

| fact | value | authority | touch / do-not-touch |
|---|---|---|---|
| Process ownership | Brainstorming owns its lifecycle, sessions, state, transcript, result, API, visualization, and target revision identifiers. It is product-neutral and independent of milestone phases or ledger chronology. | frozen mandate, Goal and Process boundary | touch Brainstorming surfaces and adapters; do-not-put milestone vocabulary in the core |
| Request and context | Required request names are `workspace_path`, `target_path`, `question`, `context`, and `max_rounds`. `max_rounds` is any positive integer supplied by the caller; this milestone adds no fixed upper bound. `context.brief` is non-empty; ordered `references` is optional; JSON-compatible `source_payload` is optional, preserved unchanged, and never drives core workflow. `target_path` is the output; consulted material stays context. | frozen mandate, Request contract | touch generic validation; do-not-add taxonomy, answer options, or a fixed global round policy |
| Resolved roster | Before execution, persist each participant's stable id, role, executor reference, model family, and turn order; require exactly one lead and at least one interlocutor. Prefer different families, but permit and record independent same-family fallback. | frozen mandate, Request contract | touch session resolution; do-not-leave roles as process-global defaults |
| Execution context | `workspace_path` is orientation, not confinement. Inherit the caller's tools, environment, primary/additional roots, sibling access, and access rules; define no new permission or work-area policy. Participants may inspect and reason about supplied references and legitimate neighbouring material. | frozen mandate, Request contract and Inherited execution context | touch pass-through only; do-not-resolve or narrow roots again |
| Participant supervision | Each participant retains one logical CLI session. A candidate turn is not accepted until its supervised local process set is quiescent and target ownership has been checked. Reuse current liveness and stop propagation without a new idempotency or provider-internal claim. | frozen mandate, Participants and discussion; this skeleton, Guarantee Posture | touch coordination and existing execution seam only as needed; do-not-create parallel supervision |
| Roles, rounds, and revisions | A round is one completed turn per persisted participant in order; only a complete pass increments `rounds_used`. Session creation records `recovery_baseline_revision` and leaves `accepted_target_revision` null. Only a completed lead turn may create or advance accepted target state. Both identifiers are Brainstorming revision identifiers or hashes, independent of Git or any VCS. | frozen mandate, Participants and Round definition; Amendment A1 | touch Brainstorming target-only revision state; do-not-promote setup state, count rejected work, or assign repository meaning |
| Invalid target mutation | A mutation during any non-lead turn, control activity, or incomplete lead attempt invalidates that worker outcome. It appends no completed turn, consumes no round, and advances no accepted revision. Recover only `target_path` from the last accepted Brainstorming revision, or from the launch baseline before one exists. The same pending worker action may then be attempted once more; a second invalid target mutation before it completes restores the target and terminalizes coherent `failure`. The target-mutation allowance and the one discussion-envelope repair are independent and neither resets the other. Interlocutors are explicitly told not to edit the target. | Amendment A1; frozen mandate, bounded lifecycle and result contract | touch target observation, bounded correction, failure, and exact target-only recovery; do-not-let target-version selection or recovery inspect commits, refs, branches, HEAD, history, merges, or repository metadata, and do-not-mutate another path |
| Resource posture | No fixed global active-session count, target byte ceiling, retained-history byte/count budget, or fixed `max_rounds` ceiling is part of the product contract. Actual inability to admit a new session may use the existing unavailable outcome and must be side-effect free. | frozen mandate, Request contract and Non-goals; queued findings resolved by this wave | touch focused regression coverage and ordinary operational refusal; do-not-add quota reservation, legacy migration, or quota-specific retry machinery |
| Human transcript | The append-only transcript is `chat.md`. Its opening names the question/reason, target, participants/lead, closure rule, and caller-supplied round cap. Every completed turn records the human-facing name and round; only material interruptions appear. Its closing always records agreement/result reason, produced or unfinished target, completed rounds, and unresolved objections. | frozen mandate, Target and transcript | touch transcript projection; do-not-turn it into a process log |
| Closure and result | Votes are exactly `accept` or `object` against one identifiable accepted target revision; edits invalidate prior votes. The selected unanimity or majority-with-lead-tiebreak policy decides closure. Terminal results are exactly `success` or `failure`; round exhaustion is failure and partial work is never promoted. | frozen mandate, Deterministic closure and Result contract | touch closure/result state; do-not-add core caller actions |
| Contextual closing record | Every participant receives the common contextualization check. The closing account records affected parties, damage altitude, proportionality, and concrete escalation evidence without inventing victims, guarantees, threats, or preferences. | frozen mandate, Contextual altitude | touch common prompts and closing projection; do-not-add domain taxonomy |
| Milestone adapter | `need_rethink` carries the question, existing finding, caller-selected target, and positive round bound. The adapter creates the independent session only after that signal. On success, implementer/fixer returns to the same provider session and reviewer starts fresh; on failure, the caller uses its existing route. Normal review remains mandatory. | frozen mandate, Milestone integration; Amendment A1 | touch Slice 8 adapter; do-not-monitor ordinary calls, promote the recovery baseline, or bypass review |
| Standalone projection | Standalone sessions are creatable, inspectable, followable, and stoppable. The view shows required session, roster, policy, round, process, transcript, accepted target, and result facts. Before completed lead work it identifies the target as not yet accepted and never presents the recovery baseline as accepted content. | frozen mandate, Separate visualization; Amendment A1 | touch standalone API/view; do-not-embed discussion in milestone chronology |

### Planning Material Disposition

- **Adopt:** the live goal only through the frozen mandate.
- **Revise:** older machine-API/persona notes only as reuse hints for service
  projections.
- **Reject:** all brainstorming material as independent authority, any future
  drift of the live goal, and the discarded Git-based restoration design.

### Verification Contract

Each slice adds focused behavioral checks for its surface. The milestone closes
only when the repository's full suite
(`python3 -m unittest discover -s orchestrator/tests -t .`) covers standalone
operation, participant/family resolution, persistent logical sessions,
worker-quiescent turn acceptance, complete-pass accounting, transcript
boundaries and order, lead-only target construction, both closure policies and
vote invalidation, unresolved closure at the caller's round limit, both terminal
results including failure before a completed turn, opaque context and
multi-root pass-through, liveness/stop behavior, the unaccepted recovery
baseline and first lead acceptance, exact target-only recovery,
repository-independent target versioning whose focused probe fails on any
Git/VCS command or repository-metadata read, one bounded target-mutation
correction followed by coherent failure on repetition, the independent
envelope-repair allowance, the pre-lead standalone view, ordinary-origin
compatibility, both milestone return routes, and the motivating amendment flow.

Focused regression coverage also proves that values above the discarded
16-round, 8-MiB-target, and eight-active-session thresholds are not refused
solely because of those numbers. Genuine runtime unavailability remains
side-effect free and operationally distinct from discussion failure.

Authority: frozen mandate, Acceptance; Operator Amendment A1.
