# Generic Brainstorming Orchestrator — Milestone Skeleton

Mandate: `implementation/milestones/brainstorming/goal.md`. This is a thin
planning contract. Slice notes will pin their own public seams and focused
acceptance checks just in time.

## Register 1 — Intent

### Goal Restatement

Build a standalone way for a lead agent and one or more interlocutors to work
through one bounded question while the lead constructs the requested result.
The human record should read like a discussion, while the service keeps the
machine state needed to order turns, supervise participants, and decide whether
the group closed successfully.

The first user is the Milestone Orchestrator: a focused design doubt can pause
its normal work, run this independent discussion, and then return by the route
appropriate to the worker that asked. The core belongs to brainstorming, not
to milestones. It stays neutral enough for a later Agent99 adapter, but this
milestone does not build that adapter.

### Guarantee Posture

- **Strict:** accepted requests and participant rosters are validated; roles
  and turn order are fixed for the run; only the lead changes the target;
  complete rounds, target revisions, votes, terminal results, and the ordered
  human transcript agree with durable state.
- **Best-effort:** frozen-process detection inherits the existing measurable
  CPU, process-set, and output-progress watchdog. An unmeasurable interval is
  treated as live; this milestone does not claim perfect provider liveness or
  exactly-once execution.
- **Eventual:** the visualization may lag durable state by its normal refresh
  interval. It is a projection, never process authority.

### Boundary and Non-Goals

- No milestone units, slices, seals, review families, or milestone chronology
  inside the brainstorming core; the milestone side is an adapter.
- No Agent99, Life Documents, cloud-drive, legal, or other target-specific
  adapter; no domain taxonomy or answer-options field.
- No new permission, sandbox, root, work-area, idempotency, or provider-policy
  system. The caller's resolved execution context remains authoritative.
- No coordinator judgment about the domain, no interlocutor target edits, and
  no raw diagnostics in the human transcript.
- No replacement or bypass of ordinary review, delta review, sealing,
  consultation, or gap/operator routing.

### Reuse Posture

- **Checked:** current structured-output validation, append-only state,
  one-shot CLI calls, process-group supervision, edit detection, resolved
  multi-root context, local API/access controls, panel projection, current
  fixer consultation, and Agent99's named work-area admission seam.
- **Reused:** validation and atomic-history patterns; process tracking,
  liveness and stop propagation; workspace-change detection; inherited root
  context; and the service's lifecycle, access, and projection conventions.
- **Extended:** a separate brainstorming lifecycle, durable discussion state,
  persistent logical participant sessions, target-revision closure, human
  transcript, standalone interface, and one milestone adapter.
- **Why new machinery:** today's workers and fixer consultation are bounded
  one-shot calls. They neither maintain a multi-party discussion nor let one
  designated lead progressively revise a target, and milestone rounds cannot
  be repurposed without violating the independent-process boundary.
- **Compatibility:** brainstorming state stays outside the milestone ledger;
  the adapter passes caller context through unchanged; existing milestone and
  Agent99 work-area ownership remain where they are.

### Planned Slices

| id | title | intent |
|---:|---|---|
| 1 | Session contract and durable state | Add the product-neutral request, resolved roster, closure-policy, lifecycle, and result contracts, with atomic auditable state and no milestone vocabulary. |
| 2 | Persistent participant execution | Keep one logical CLI session per participant across turns, validate each control envelope, inherit the caller's execution context, and reuse existing liveness and stop supervision. |
| 3 | Ordered rounds and lead-owned target | Run complete passes through the persisted order, expose prior discussion and the current target to each turn, count only completed passes, and mechanically confine target changes to the lead. |
| 4 | Plain-language session transcript | Produce ordered Markdown opening, turn, material-interruption, and closing entries in `chat.md`, while keeping identifiers and diagnostics in structured state and technical logs. |
| 5 | Revision-bound closure and results | Record closure votes against one target revision, invalidate votes after edits, apply the selected policy deterministically, and return only coherent `success` or explicit `failure`. |
| 6 | Standalone lifecycle API | Let a caller create, inspect, follow, and stop brainstorming without creating a milestone, using stable product-neutral request, state, and result shapes. |
| 7 | Dedicated brainstorming visualization | Show the required session, roster, policy, round, process, transcript, target, and result projection without embedding it in milestone chronology. |
| 8 | Milestone `need_rethink` adapter | Accept focused rethink requests from implementers, fixers, and reviewers; suspend the normal transition; invoke brainstorming; and test same-session continuation, fresh-review return, failure routing, and the motivating amendment flow. |

### Question Battery

| question | answer | evidence |
|---|---|---|
| victim | The immediate victims are the milestone operator and the active implementation/review agents: a small resolvable contradiction currently forces a full documentation reset, review, and reseal instead of one bounded decision. | `implementation/milestones/brainstorming/goal.md:17-21,30-48` |
| machinery | The milestone adds an independent session lifecycle and state, persistent participant discussions, an ordered coordinator, lead-owned target revisions, transcript, closure, standalone interface, visualization, and a milestone adapter. It must exist because the mandate forbids synthetic milestone rounds and the current runner and consultation are explicitly one-shot. | `implementation/milestones/brainstorming/goal.md:50-63,177-183`; `orchestrator/runners.py:465-476,519-528`; `orchestrator/prompts.py:211-238` |
| consumers | The verified immediate consumers are the Milestone Orchestrator's implementer, fixer, and reviewer call paths plus standalone service operators. Agent99 is a future compatibility consumer, not part of this delivery; its real Body code already resolves a named primary-plus-additional-root work area before admitting a run. | `orchestrator/driver.py:1703-1817,2706-2833,3676-3835`; `orchestrator/service.py:2735-2885`; `../life_prod/agent_99/apps/agent_99/lib/agent_99/body/work_area.ex:1-57`; `../life_prod/agent_99/apps/agent_99/lib/agent_99/body/admission.ex:1-16,21-41,61-74` |
| cheaper_alternative | Doing nothing preserves the full-reset cost. Extending today's fixer consultation is cheaper but rejected: it exists only to decide a finding rejection, permits at most two dialogue rounds, and has no target-construction lifecycle. Reusing milestone review rounds is rejected by the independent-process mandate; the low-level validation, state, process, context, access, and projection machinery is reused instead. | `implementation/milestones/brainstorming/goal.md:30-54`; `orchestrator/prompts.py:211-238`; `orchestrator/runners.py:1-14` |
| cost | Build: eight narrow slices across contracts/state, participant execution, coordination, transcript, closure, standalone API/view, and the milestone adapter. Migration: additive brainstorming state plus an additive Milestone worker-result/transition path; no milestone-ledger, target-data, or Agent99 migration. Maintenance: provider continuation compatibility, lifecycle schemas, transcript/closure conformance, and one additional service projection. | this skeleton, Planned Slices; `implementation/milestones/brainstorming/goal.md:336-374`; `orchestrator/contracts.py:538-645` |
| threat_model | No new remote attacker or permission model is introduced. Trusted inputs are operator/product configuration and the caller-resolved execution context. Untrusted inputs are participant-produced control envelopes and claims or content found in supplied context/references; envelopes are validated, context is examined rather than obeyed as authority, and only the lead may change the target. Existing service identity and project/run access remain the external boundary. | `implementation/milestones/brainstorming/goal.md:85-89,137-160,164-183`; `orchestrator/runners.py:986-1053`; `orchestrator/access.py:41-58`; `orchestrator/service.py:2668-2695` |
| enforceability | Existing mechanisms can enforce structured envelopes, atomic append-only history, legal transitions, edit/no-edit boundaries, inherited roots, process-group supervision, stop propagation, and eventual UI projection. Two mechanisms do not exist yet: the current runner is one-shot, so Slice 2 must pin and test a provider-neutral logical-session continuation seam before persistent or same-session claims are valid; Slice 5 must add explicit revision/vote transitions before deterministic closure is valid. No dependent slice may claim either guarantee earlier. | `orchestrator/contracts.py:454-517,538-645`; `orchestrator/state.py:221-317,393-440`; `orchestrator/runners.py:30-58,548-642,739-783,1121-1191`; `orchestrator/driver.py:911-958,2662-2676`; `orchestrator/service.py:1815-1886`; `orchestrator/static/panel.html:1263-1270,1749-1759,3178-3193`; this skeleton, Planned Slices 2 and 5 |

## Register 2 — Pinned Facts

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Process ownership | Brainstorming owns its own lifecycle, sessions, state, transcript, result, API, and visualization. It is product-neutral and independent of milestone phases or ledger chronology. | `implementation/milestones/brainstorming/goal.md:17-26,50-63,278-279` | touch new brainstorming surfaces and adapters; do-not-touch core with milestone vocabulary |
| Request and context | Required request names are `workspace_path`, `target_path`, `question`, `context`, and `max_rounds`. `context.brief` is non-empty; ordered `references` is optional; JSON-compatible `source_payload` is optional, preserved unchanged, and never drives core workflow. `target_path` is always the output; consulted material stays context. Caller/session/timestamp metadata may not alter the request or resolved roster. There is no answer-options field or problem/domain type. | `implementation/milestones/brainstorming/goal.md:65-115` | touch generic contract; do-not-add taxonomy or interpret `source_payload` |
| Resolved roster | Before execution, persist each participant's stable id, role, executor reference, model family, and turn order; require exactly one lead and at least one interlocutor. Prefer different families, but permit and record independent same-family fallback. | `implementation/milestones/brainstorming/goal.md:91-104` | touch session resolution; do-not-leave roles as process-global defaults |
| Execution context | `workspace_path` is orientation, not confinement. Inherit the caller's tools, environment, primary/additional roots, sibling access, and access rules; define no new permission or work-area policy. | `implementation/milestones/brainstorming/goal.md:148-160`; `orchestrator/driver.py:911-958`; `orchestrator/prompts.py:584-619` | touch pass-through only; do-not-resolve or narrow roots again |
| Participant supervision | Each participant retains one logical CLI session across the discussion. Reuse current process-group CPU/process-set/output liveness and stop propagation. Liveness detection is best-effort; no new idempotency or provider-internal assumption. | `implementation/milestones/brainstorming/goal.md:177-183`; `orchestrator/runners.py:30-58,548-642,739-783` | touch participant-session adapter; do-not-create parallel supervision |
| Roles and rounds | Only the lead edits `target_path`; interlocutors analyze and the coordinator only orders/validates. A round is one completed turn per persisted participant in order; only a complete pass increments `rounds_used`; control and ballot events consume no round. | `implementation/milestones/brainstorming/goal.md:162-179,230-241` | touch coordinator and edit guard; do-not-allow other writers or partial-round counts |
| Human transcript | The append-only transcript is named `chat.md`. Before any turn, its plain opening names the question/reason, target, participants/lead, closure rule, and round cap. Every completed turn records the human-facing name and round; only material interruptions appear. Its closing always records agreement/result reason, produced or unfinished target, completed rounds, and unresolved objections, even when no turn completes. Machine identifiers, telemetry, and raw diagnostics stay elsewhere. | `implementation/milestones/brainstorming/goal.md:185-228`; `orchestrator/state.py:221-317` | touch transcript projection; do-not-turn it into a process log |
| Closure and result | Votes are exactly `accept` or `object` against one identifiable target revision; edits invalidate prior votes. `unanimity` requires every participant; `majority_with_lead_tiebreak` uses one vote each, strict majority, and the lead on an exact tie. A failed vote resumes discussion while rounds remain. Terminal results are exactly `success` or `failure`; round exhaustion is `failure`, partial work is never promoted, and the inspectable target/state plus target/transcript references, `rounds_used`, and failure reason remain available. | `implementation/milestones/brainstorming/goal.md:243-279` | touch closure/result state; do-not-add core caller actions |
| Contextual closing record | Every participant uses the same scope, real-affected-parties, damage-altitude, comparable-rigor, proportionality, and escalation-evidence check. The closing account records affected parties, damage altitude, proportionality, and concrete escalation evidence without inventing victims, guarantees, threats, or preferences. | `implementation/milestones/brainstorming/goal.md:117-146,351-357` | touch common participant prompt and closing projection; do-not-add domain taxonomy |
| Milestone adapter | The exact signal name is `need_rethink`. It carries the question, existing finding, target, and round bound; the finding reaches generic `source_payload` unchanged. On `success`, implementer/fixer returns through `continue` to the same provider session and reviewer starts a fresh review; on `failure`, use the existing gap/operator route. Normal delta review remains mandatory. | `implementation/milestones/brainstorming/goal.md:281-298`; `orchestrator/driver.py:1703-1817,2706-2833,3676-3835` | touch Milestone contract/adapter only; do-not-bypass existing review routes |
| Standalone projection | Standalone sessions are creatable, inspectable, followable, and stoppable. The dedicated eventual view shows session/caller/status/question/target, resolved roster and fallback, closure policy/votes, current/max round, process state, ordered transcript, final target, and result. A milestone UI may link, never embed the conversation as chronology. | `implementation/milestones/brainstorming/goal.md:300-334`; `orchestrator/static/panel.html:1263-1270,1749-1759,3178-3193` | touch standalone API/view and optional link; do-not-embed in milestone ledger/view |

### Planning Material Disposition

- **Adopt:** the live brainstorming goal only through the frozen mandate; its
  substantive text matched the snapshot when checked.
- **Revise:** the older machine-API/persona note only as a reuse hint for
  service projections. Its bearer-token, event-cursor, and Persona-digest
  proposals are not part of this goal.
- **Reject:** all brainstorming material as independent authority and any
  future drift of the live goal.

Authority: `implementation/brainstorming/README.md:3-8,12-17`;
`implementation/brainstorming/machine-api-and-persona-projection.md:31-55,81-113`;
`implementation/milestones/brainstorming/goal.md:1-9,150-160,300-316`.

### Verification Contract

Each slice adds focused contract and lifecycle checks for the surface it owns.
The milestone closes only when the repository's full suite
(`python3 -m unittest discover -s orchestrator/tests -t .`) covers standalone
operation, participant/family resolution, persistent logical sessions,
complete-pass accounting, transcript boundaries and order, lead-only target
construction, both closure policies and vote invalidation, both terminal
results including failure before a completed turn, opaque context and
multi-root pass-through, liveness/stop behavior, both milestone return routes,
and the motivating amendment flow.

Authority: `implementation/milestones/brainstorming/goal.md:336-374`;
`orchestrator/README.md:309-319`.
