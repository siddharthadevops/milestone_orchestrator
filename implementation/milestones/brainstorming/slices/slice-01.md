# Slice 01 — Session contract and durable state

## Register 1 — Intent

### What this slice builds

This slice gives the brainstorming service one dependable record for a
discussion before any agent is started. A caller supplies the question, target,
background, round limit, chosen participants, and agreement rule. The service
accepts the session only when those facts form a usable whole, then preserves
them for the life of that session.

The durable record tells later parts of the service what was requested, who was
chosen, whether same-provider fallback was needed, what agreement rule applies,
what has happened, and whether the session ended successfully. A person can
close and reopen the record without losing or silently changing those facts.

### Ownership and boundary

This slice owns the product-neutral request, the resolved participant roster,
the selected closure rule, the durable session authority, and the terminal
result shape. It provides the foundation that later slices use to run
participants, order rounds, write the human transcript, decide closure, expose
the API, render the view, and connect Milestone Orchestrator.

It does not start or supervise agents, schedule turns, edit the target, write
the human transcript, count votes, decide closure, expose a route or screen, or
connect any product. It adds no permission system and changes no caller's work
area.

### Guarantee posture

- **Strict:** accepted requests and resolved rosters are valid and immutable;
  committed history is append-only; each state update is whole and durable; a
  terminal result's shape, outcome, and retained references agree with its
  terminal status.
- **Optimistic:** no public optimistic-consistency promise is introduced. A
  stale concurrent update must lose rather than overwrite a newer durable
  record.
- **Eventual:** none in this slice. The later visualization may be eventual,
  but this record is its authority.
- **Best-effort:** none in this slice. Process liveness and delivery are owned
  by later execution work.

### Dependencies and consumers

The slice has no later-slice prerequisite. Its only immediate consumer is its
focused contract/state test suite. Every runtime consumer is deliberately
later: participant execution, coordination, transcript, closure, standalone
API, visualization, and the milestone adapter.

### Non-goals

- No agent process, provider continuation, liveness watchdog, or stop
  propagation.
- No turn, round, target-revision, ballot, or transcript event vocabulary.
- No standalone HTTP route, service registry entry, panel projection, or
  milestone worker signal.
- No milestone unit, slice, review, seal, continuation, or operator-routing
  concept in the core-owned schema.
- No new storage engine, access policy, idempotency policy, or exactly-once
  provider claim.
- No Agent99 or other product adapter.

### Acceptance

The slice is accepted when valid sessions survive a close/reopen cycle without
drift; malformed requests and rosters create nothing; opaque caller evidence
round-trips without affecting lifecycle; concurrent or failed writes cannot
tear, erase, or silently replace committed state; past history and terminal
results cannot be rewritten; and the same core record works without any
milestone concept.

The expected implementation is comfortably below the roughly 500-line
changed-code target: one narrow contract/state seam and focused tests. If the
implementation needs a new storage subsystem or runtime wiring, it has left
this slice.

### Risks

- Treating caller evidence as instructions would make the generic core depend
  on a product. The acceptance checks compare sessions with different opaque
  evidence and require the same lifecycle behavior.
- Reusing the milestone state shape would leak milestone chronology into the
  core. Only its proven validation, transition, and atomic-persistence patterns
  are reusable.
- Writing related fields separately could expose a half-created session. The
  persisted request, roster, policy, lifecycle record, and result move as one
  durable state update.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Request and context | Required request names are `workspace_path`, `target_path`, `question`, `context`, and `max_rounds`. The three text fields are non-empty strings and `max_rounds` is a positive integer. `context` contains required non-empty string `brief`, optional ordered list of non-empty string `references`, and optional JSON-compatible `source_payload`. `source_payload` is preserved unchanged and never drives core state. `target_path` is the output; consulted material is context. | `implementation/milestones/brainstorming/skeleton.md:3-5,73,99`; `implementation/milestones/brainstorming/goal.md:65-115` | touch one product-neutral validator and durable copy; do-not-add answer options, a problem/domain type, or caller interpretation |
| Resolved roster | The cross-slice object is `run_config` with exactly `participants`, `closure_policy`, and boolean `same_family_fallback`. `participants` is the turn order; every item has exactly non-empty string `id`, `role` equal to `lead` or `interlocutor`, non-empty string `executor_ref`, and non-empty string `model_family`. Persist exactly one lead, at least one interlocutor, and stable unique ids. Eligible assignments from different families win; only the absence of an eligible second family permits separate same-family entries and sets `same_family_fallback` to true. Caller/session/timestamp metadata cannot change this object or the request. | `implementation/milestones/brainstorming/skeleton.md:3-5,73,100`; `implementation/milestones/brainstorming/goal.md:91-104,164-172` | touch one resolved cross-slice object; do-not-use process-global role defaults, add participant fields, or re-resolve after acceptance |
| Closure-policy vocabulary | The selected value is exactly `unanimity` or `majority_with_lead_tiebreak`; this slice persists the selection but does not count votes or decide closure. | `implementation/milestones/brainstorming/skeleton.md:100,105`; `implementation/milestones/brainstorming/goal.md:91-95,243-264` | touch validation and immutable configuration; do-not-add a default policy or a third policy |
| Durable session authority | Brainstorming state is independent of `.orchestrator/state.json`. The accepted request and resolved run configuration are immutable; completed audit records are append-only; persistence exposes only a complete old or complete new state; a stale writer cannot replace a newer state. No public route, event-name vocabulary, or API error code is added in this slice. | `implementation/milestones/brainstorming/skeleton.md:25-28,58-67,73,98`; `implementation/milestones/brainstorming/goal.md:17-21,50-63,336-361` | touch a separate product-neutral state/transition seam; do-not-embed brainstorming in the milestone ledger or invent API surface |
| Lifecycle vocabulary | Durable `status` is exactly `created`, `running`, `success`, or `failure`. Legal moves are `created` → `running` or `failure`, then `running` → `success` or `failure`; `result` is absent before a terminal move and terminal states have no outgoing transition. Rejected creation writes no session. | `implementation/milestones/brainstorming/skeleton.md:3-5,25-28,73`; `implementation/milestones/brainstorming/goal.md:50-63,266-279,336-358` | touch one explicit product-neutral transition contract; do-not-add milestone phases, resume, or caller routing |
| Result contract | `result` has exactly `outcome`, `target_ref`, `transcript_ref`, `rounds_used`, and failure-only `reason`. The two references are non-empty strings and `target_ref` equals the accepted `target_path`; `outcome` is exactly `success` or `failure` and equals terminal `status`; `rounds_used` is a non-negative integer; `reason` is non-empty on failure and absent on success. Target, transcript, and inspectable state remain available after either outcome. Slice 3 owns completed-round semantics, Slice 4 the transcript reference, and Slice 5 success eligibility. | `implementation/milestones/brainstorming/skeleton.md:3-5,73,75-77,92,99,105`; `implementation/milestones/brainstorming/goal.md:114-115,230-279` | touch one cross-slice result-shape validator and durable terminal representation; do-not-decide rounds, transcript production, closure, or caller actions |
| Slice boundary | Slice 1 defines and persists contracts only. Persistent participant execution is Slice 2; rounds/target ownership Slice 3; `chat.md` Slice 4; votes/closure Slice 5; API Slice 6; view Slice 7; `need_rethink` adapter Slice 8. | `implementation/milestones/brainstorming/skeleton.md:73-80` | touch contract/state plus focused tests; do-not-pull later behavior forward |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_state`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Request/context validation is closed and side-effect free | `test_request_and_context_contract` | Minimal and full valid requests are accepted; missing/wrong fields, empty required text, a non-positive/non-integer round bound, non-string-list `references`, non-JSON `source_payload`, or forbidden taxonomy/answer fields are rejected without creating state. | strict |
| Caller-native evidence is opaque | `test_source_payload_round_trips_opaque` | Nested JSON-compatible evidence reloads equal to the input; changing only that evidence cannot select a policy, role, lifecycle transition, or result. | strict |
| Roster and policy are fully resolved before acceptance | `test_roster_and_policy_contract` | Invalid roster/policy shapes are rejected; fixtures with two eligible families resolve across families, while a one-family fixture resolves separate same-family entries with fallback true; order, assignments, and fallback fact survive reload. | strict |
| Request and run configuration remain fixed | `test_session_contract_is_immutable` | Metadata or later updates cannot alter the accepted request, roster, order, assignments, fallback fact, or policy; a rejected rewrite leaves the prior durable bytes readable. | strict |
| Audit and terminal records cannot be rewritten | `test_history_and_terminal_result_are_append_only` | Shrinking or changing a completed record, changing a terminal result, or attempting another state transition after terminalization is rejected and leaves durable state unchanged. | strict |
| Persistence is whole under failures and contention | `test_atomic_persistence_and_stale_update_rejection` | A serialization/write failure leaves the previous valid state; two updates from the same prior revision yield one committed successor and one stale rejection, never a torn or lost update. | strict state; optimistic conflict detection |
| Lifecycle and retained terminal evidence are coherent | `test_lifecycle_and_result_contract` | Only the pinned legal transitions succeed; nonterminal state has no result; only `success`/`failure` terminalize; outcome matches terminal status, target reference matches the request, and both outcomes retain a transcript reference plus non-negative integer `rounds_used`; failure alone requires a reason; extra fields and caller actions are rejected. | strict |
| Core state is not milestone state | `test_brainstorming_state_is_independent` | Creating and updating a generic session leaves a neighbouring milestone ledger byte-unchanged, and the core-owned schema contains no milestone chronology or routing fields outside opaque `source_payload`. | strict |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:309-319`). Later slices add their own focused checks;
milestone closure runs the full matrix required by
`implementation/milestones/brainstorming/skeleton.md:124-137`.

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here.
These are the slice-scoped remainder; enforceability is intentionally answered
again for this slice.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **current runtime:** none; current worker kinds and service routes contain no brainstorming consumer. **slice-local direct consumer:** the new focused contract/state tests. **declared later consumers:** Slices 2-8, with the API and milestone adapter explicitly deferred to Slices 6 and 8. | `orchestrator/contracts.py:47-74`; `orchestrator/service.py:2735-2814,2820-2887`; `implementation/milestones/brainstorming/skeleton.md:73-80` |
| pinned_facts | **closed facts:** request/context names and opacity; resolved roster invariants and fallback record; two closure-policy values; lifecycle states `created`/`running`/`success`/`failure` and their legal transitions; independent atomic/auditable state; retained terminal evidence; no milestone vocabulary or later-slice behavior. | `implementation/milestones/brainstorming/slices/slice-01.md:95-103`; `implementation/milestones/brainstorming/skeleton.md:23-47,73,94-108`; `implementation/milestones/brainstorming/goal.md:50-115,266-279` |
| verification | **focused:** the eight named checks in this note cover validation, opacity, roster/policy resolution, immutability, append-only history, atomic/stale writes, result coherence, and ledger independence. **full:** the repository unittest discovery command remains the milestone gate. | `implementation/milestones/brainstorming/slices/slice-01.md:105-126`; `implementation/milestones/brainstorming/goal.md:336-374`; `implementation/milestones/brainstorming/skeleton.md:124-137`; `orchestrator/README.md:309-319` |
| reuse_posture | **checked:** existing structured validation, milestone append-only/transition enforcement, atomic state writes, serialized whole-value CAS, worker kinds, and service routes. **adopted:** JSON-compatible validation/copying plus atomic serialized persistence and stale-write rejection. **extended:** one product-neutral session transition validator because the existing state machine is milestone-specific and the mandate requires independent state. **new-with-why:** no new storage engine; only the missing generic schema/transition layer. | `implementation/milestones/brainstorming/slices/slice-01.md:142-164`; `orchestrator/contracts.py:92-113,454-517`; `orchestrator/state.py:1-17,221-317,393-440`; `orchestrator/kvstore.py:160-186,314-457`; `implementation/milestones/brainstorming/skeleton.md:49-67,73,98` |
| enforceability | **shape/closed vocabularies:** executable validators. **opaque JSON:** canonical JSON validation plus equality/metamorphic tests. **whole durable updates/concurrency:** existing locked atomic whole-value CAS. **immutability/history:** extend the existing prefix-rewrite guard to the product-neutral state. **lifecycle/result representation:** extend the existing explicit-transition guard; terminal fields are write-once. **excluded:** no semantic `success`, liveness, delivery, API, or view guarantee is asserted here; Slice 5 owns success eligibility. | `implementation/milestones/brainstorming/slices/slice-01.md:166-178`; `orchestrator/contracts.py:92-113,454-517`; `orchestrator/kvstore.py:160-186,343-359,391-457`; `orchestrator/state.py:221-317,393-440`; `implementation/milestones/brainstorming/skeleton.md:23-34,73,77,92` |

### Reuse Posture

- **Checked:** the worker-contract validators; milestone state's append-only,
  explicit-transition, exclusive-create, and atomic-save enforcement; the local
  JSON-safe, locked, whole-value CAS; current worker kinds and service routes.
  Authorities: `orchestrator/contracts.py:92-113,454-517`;
  `orchestrator/state.py:1-17,221-317,393-440`;
  `orchestrator/kvstore.py:160-186,314-457`;
  `orchestrator/contracts.py:47-74`;
  `orchestrator/service.py:2735-2814,2820-2887`.
- **Adopted:** the accepted JSON-compatible value discipline and the existing
  atomic, serialized, stale-write-rejecting persistence capability. The
  append-only-prefix and explicit-transition guards are extended as patterns,
  not by importing the milestone schema.
- **New-with-why:** one product-neutral request/state validator and its focused
  tests. Existing state enforcement is hard-coded to milestone units and
  history, while this mandate requires an independent lifecycle and forbids
  milestone vocabulary. Authority:
  `implementation/milestones/brainstorming/skeleton.md:38-43,58-67,73,98`.
- **Compatibility:** the new seam consumes JSON-compatible caller context,
  retains the caller-resolved roster without re-resolution, and exposes no
  runtime integration. Later slices can consume it without changing current
  milestone contracts or routes.

### Enforceability Gate

| invariant asserted here | mechanism that can enforce it | implementation gate |
|---|---|---|
| Required shapes and closed values | Existing required-key/type/closed-set validator pattern (`orchestrator/contracts.py:92-113,454-517`) | Every invalid matrix case is rejected before state creation. |
| JSON-compatible opaque evidence | Existing canonical JSON validator/copy (`orchestrator/kvstore.py:160-186`) | Round-trip equality and changing-only-payload metamorphic check pass. |
| Atomic durable state and stale-writer rejection | Existing locked whole-value CAS and same-directory atomic replacement (`orchestrator/kvstore.py:343-359,391-457`) | Failure/contention test observes one whole committed successor and no overwrite. |
| Immutable request/config and append-only completed records | Existing prefix comparison/rewrite rejection pattern (`orchestrator/state.py:221-263`) extended to the generic record | Mutation or shrink is rejected before persistence; prior durable state is unchanged. |
| Legal lifecycle and write-once terminal representation | Existing explicit adjacency guard plus appended transition record pattern (`orchestrator/state.py:313-317,393-440`) extended to the generic lifecycle | Illegal or post-terminal transitions fail; outcome matches terminal status; terminal evidence remains immutable. Semantic success remains Slice 5's gate. |
| Independent product-neutral authority | Separate-state mandate and no-milestone boundary (`implementation/milestones/brainstorming/skeleton.md:36-47,65-67,98`) | Independence test proves the milestone ledger is byte-unchanged and no core-owned milestone fields appear. |

If implementation relies on prompt discipline or convention for any row instead
of the named mechanical gate, that guarantee is not delivered.

### Planning Material Disposition

- **Adopt:** no brainstorming file as independent authority; only the sealed
  skeleton's frozen restatement and its cited generated goal snapshot.
- **Revise:** reuse hints from older planning material only where verified
  against current code above.
- **Reject:** bearer-token, event-cursor, Persona-digest, or any other
  machine-API proposal as Slice 1 scope.

Authority: `implementation/milestones/brainstorming/skeleton.md:110-122`;
`implementation/brainstorming/README.md:3-8,12-17`;
`implementation/brainstorming/machine-api-and-persona-projection.md:31-55,81-113`.
