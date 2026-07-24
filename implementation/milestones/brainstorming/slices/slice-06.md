# Slice 06 — Standalone lifecycle API

## Register 1 — Intent

### What this slice builds

This slice gives people and product adapters a direct way to start a bounded
brainstorming discussion, check its progress, and stop it without creating a
milestone. A successful launch returns one stable session identity. Repeated
reads show the same durable discussion moving toward its final result.

The service chooses the available agent assignments before work begins, keeps
the caller's participant order and agreement rule, and runs the discussion
independently. A caller may use an already declared work area or, when allowed
by the existing service, supply a standalone working directory.

### Ownership and boundary

This slice owns the public lifecycle surface, caller and work-area binding,
background execution of an accepted session, progress reads, and explicit
stop behavior. It joins the session, participant, round, transcript, and
closure capabilities delivered by the preceding slices; it does not redefine
them.

It does not add a screen, milestone transition, product adapter, event feed,
new permission system, or new target-version scheme. It does not interpret the
question or caller evidence. It never treats a working directory or target as
a repository.

### Guarantee posture

- **Strict:** accepted inputs, participant roles, caller visibility, durable
  state, terminal results, and successful stop responses are mutually
  consistent. One accepted session has one lifecycle worker, and the service
  never reports a stop complete while participant work can still change the
  target.
- **Optimistic:** competing creation, completion, and stop operations contend
  on durable revisions. One outcome wins; a stale operation cannot append a
  second turn, result, or closing.
- **Eventual:** following is polling. A caller learns about new durable state
  on its next read; this slice adds no push or exactly-once notification claim.
- **Best-effort:** provider delivery and frozen-process detection retain their
  inherited limits. An unclean host or service death can leave a nonterminal
  session inspectable; it is not falsely promoted to a result when worker
  quiescence or target recovery cannot be proved.

### Dependencies and consumers

This slice depends on the durable request, roster, lifecycle, and result
record; persistent participant conversations; ordered lead-owned target
revisions; the human transcript; and revision-bound closure.

Its direct consumers are standalone service callers and the later dedicated
view. The existing service identity and declared work-area facilities remain
the access and execution-context sources. Existing milestone runs, milestone
state, the current panel, Agent99, Life, LPC, and Tutor are not changed.

### Non-goals

- No list, search, delete, restart, event-cursor, streaming, webhook, digest,
  or Persona endpoint.
- No milestone creation, milestone registry entry, milestone chronology, or
  milestone result action.
- No caller-supplied identity, executor command, environment, root grant, or
  access rule.
- No Agent99 or target-specific adapter and no interpretation of opaque caller
  evidence.
- No new bearer token, remote-binding policy, sandbox, custody model,
  idempotency system, or exactly-once execution claim.
- No repository validation, version-control inspection, or recovery of any
  caller path other than the target.

### Acceptance

The slice is accepted when an authorized standalone caller can launch a valid
cross-family or same-family discussion and receive a stable session, then poll
that session through real ordered work to either coherent terminal outcome
without any milestone artifact or ledger mutation.

Invalid input, an unauthorized caller, an unresolved work area, an unavailable
participant assignment, or an already-active session for the same target
starts no agent and changes neither target nor durable session state.

Every progress read is authorized from durable caller or project binding
before session content is read. It returns one self-consistent durable snapshot
and current process observation. Opaque caller evidence and the resolved
execution context survive unchanged.

An explicit stop either returns the already-terminal session unchanged or
waits for local participant work to become unable to mutate, restores only the
target to its last accepted Brainstorming version, records the material
interruption, and returns a coherent failure. If those conditions cannot be
confirmed, the service reports a retryable conflict and does not claim that
the session stopped cleanly.

The production seam should remain compact, but this slice is expected to
exceed the roughly 500 changed-line target once the independent process
registry, lifecycle runner, HTTP and authorization matrix, fake-provider
end-to-end cases, and stop/completion races are counted. Those tests are the
executable evidence for exposing full-permission work safely; generated and
mechanical changes remain excluded.

### Risks

- Reusing the milestone registry could make an independent discussion appear
  in milestone chronology. The service metadata and tests remain separate.
- Authorizing from mutable session content could expose a discussion across
  projects. Visibility is decided from the durable service binding before
  content is read.
- Two sessions for one target could undo each other's accepted work. Admission
  permits only one nonterminal service-owned session for a resolved target.
- A stop can race with a completed participant response. Stop is reported
  complete only after the lifecycle worker and its participant work are quiet,
  target recovery is verified, and one terminal state wins.
- Push or delivery guarantees would exceed the neighbouring service contract.
  Polling returns current durable truth but does not promise notification
  timing.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Public routes and success schema | The only routes added here are `POST /api/brainstorming/sessions`, `GET /api/brainstorming/sessions/<session_id>`, and `POST /api/brainstorming/sessions/<session_id>/stop`. Create returns HTTP 201; inspect/follow and a completed or already-terminal stop return HTTP 200. Every success body is exactly `{"ok": true, "session": session}`. `session` has exactly `id`, `caller`, `project`, `work_area`, `process`, `revision`, and `state`; project/work-area are strings or both `null`, process is exactly `running` or `stopped`, revision is the positive durable session revision, and state is the complete validated Brainstorming state. The server generates an opaque path-safe id; clients do not parse it. | `implementation/milestones/brainstorming/skeleton.md:3-5,78,98,108`; `implementation/milestones/brainstorming/goal.md:300-334`; `orchestrator/service.py:2735-2818,2820-2891,2946-2953`; `orchestrator/brainstorming.py:87-90,1205-1291,1918-1974` | touch additive Brainstorming dispatch and one stable projection; do-not-change `/api/runs`, add a collection read, expose a pid, or add an event/stream route |
| Creation input and roster resolution | The create body has exactly required `request`, `participants`, and `closure_policy`, plus optional `project` and `work_area`, which are supplied together or not at all. `request` is Slice 1's exact request. `participants` is an ordered list of exact `{id, role}` objects with unique non-empty ids, exactly one `lead`, and at least one `interlocutor`; its order becomes turn order. Policy is exactly `unanimity` or `majority_with_lead_tiebreak`. Before any process starts, the service resolves immutable `executor_ref` and `model_family` values from its configured continuation-capable executors, uses more than one family when available, and otherwise records independent same-family fallback. Caller identity is derived, never accepted in the body. | `implementation/milestones/brainstorming/skeleton.md:25-28,73-74,78,99-102`; `implementation/milestones/brainstorming/goal.md:65-104,300-316`; `orchestrator/brainstorming.py:500-596,746-826`; `orchestrator/runners.py:751-900` | touch one API-input adapter into the existing `request` and `run_config`; do-not-add request fields, caller-selected commands, answer options, taxonomy, or re-resolve an accepted roster |
| Execution-context and access binding | With no project/work-area pair, creation and every later read/stop are administrative-only and `request.workspace_path` must be an existing directory. With a pair, the existing project membership check and READY work-area resolver apply; `request.workspace_path` must equal the resolved primary path, while the resolved additional roots and existing access rules pass through unchanged. The immutable service record stores caller plus optional project/work-area before launch and is the authorization source before any session state is read. Project members see their assigned project's sessions; administrators see all. No repository check applies. | `implementation/milestones/brainstorming/skeleton.md:42-43,65-67,78,88,101`; `implementation/milestones/brainstorming/goal.md:148-160,300-316`; `orchestrator/access.py:41-69`; `orchestrator/service.py:2641-2695,2702-2733`; `orchestrator/driver.py:4473-4504,4564-4604` | touch pass-through resolution and an independent durable access/process record; do-not-add roots, narrow inherited tools, trust request identity, inspect a foreign session before authorization, or require Git |
| Standalone lifecycle and follow | Accepted creation writes no milestone state, transitions the Brainstorming session to `running`, and starts at most one background lifecycle process. That process uses the existing ordered-turn and closure seams until durable state is exactly `success` or `failure`, then exits. Repeated detail GETs are the follow contract: each returns the latest complete CAS snapshot and reconciled transcript plus current process liveness; observed `revision` never decreases. There is no public event name, cursor, long poll, SSE, or WebSocket. A normal operational error becomes coherent `failure`; an unclean death that cannot be reconciled remains visibly nonterminal with process `stopped`, never a fabricated result. | `implementation/milestones/brainstorming/skeleton.md:23-34,38-47,65-67,77-79,98,105,108`; `orchestrator/brainstorming.py:30-42,1294-1357,1918-1974,2147-2219`; `orchestrator/brainstorming_coordination.py:774-796,944-1090,1116-1292`; `orchestrator/service.py:880-925,1815-1855` | touch one Brainstorming-only lifecycle runner and process record; do-not-use milestone units/driver state, add resume semantics, expose intermediate candidate state, or promise push/exactly-once delivery |
| Target admission and isolation | Creation rejects a target that overlaps Brainstorming state/transcript authority or resolves to or aliases the target of another nonterminal service-owned Brainstorming session, with `brainstorming_target_in_use`. During the accepted run, only completed lead work can advance `accepted_target_revision`; interlocutor or other-turn mutations are rejected and recover only `target_path` from the last accepted Brainstorming revision. External writes remain outside the run contract. No workspace path, sibling path, repository state, or VCS object is inspected or changed for recovery. | `implementation/milestones/brainstorming/skeleton.md:25-28,42-45,75,92,99,103`; Operator Amendment A1, **Target versioning clarification**; `orchestrator/brainstorming.py:139-309,2147-2181`; `orchestrator/brainstorming_coordination.py:54-168,387-490,944-1090` | touch pre-launch active-target admission and reuse target-exclusive coordination; do-not-create repository locks, attribute external writes, or roll back anything except `target_path` |
| Explicit stop | Stop accepts no body fields. On a nonterminal session it first stops the lifecycle process and forwards stop to every tracked participant process group. Only after worker quiescence and target-only reconciliation may it append the existing `material_interruption` at the current completed-turn boundary and atomically terminalize as `failure`; result and closing reason state that the caller stopped the discussion, `rounds_used` does not increase, and no attempted turn, target revision, vote, or success is accepted. A terminal session returns unchanged with no extra interruption. Concurrent stop/completion has one durable winner. If quiescence, process exit, or target recovery is unconfirmed, return `brainstorming_stop_incomplete` and preserve inspectable accepted state. | `implementation/milestones/brainstorming/skeleton.md:25-32,44-45,76-78,92,104-105,108`; `implementation/milestones/brainstorming/slices/slice-04.md:143,145-146`; `orchestrator/runners.py:31-59,1142-1174`; `orchestrator/service.py:1858-1895`; `orchestrator/brainstorming.py:911-926,1075-1102,1309-1357,2306-2315`; `orchestrator/brainstorming_coordination.py:716-749,808-845` | touch lifecycle stop/failure composition and focused races; do-not-add a `stopped` durable status, terminalize before safety evidence, count stop as a turn/round, or accept post-terminal work |
| Error vocabulary | Lifecycle errors retain the service envelope exactly `{"ok": false, "error": code}`. New codes are: HTTP 400 `invalid_brainstorming_request`; HTTP 404 `unknown_brainstorming_session`; HTTP 409 `brainstorming_target_in_use` or `brainstorming_stop_incomplete`; and HTTP 503 `brainstorming_unavailable`. Existing identity/project refusals pass through unchanged: HTTP 403 `forbidden`, HTTP 404 `unknown_project`, and HTTP 400 `invalid_project`, `invalid_name`, `unknown_work_area`, `malformed_work_area`, `work_area_not_ready`, `workspace_mismatch`, or `missing_primary_path`. Error responses expose no raw worker output, exception, command, environment, or provider-session reference. | `implementation/milestones/brainstorming/skeleton.md:3-5,42-45,78,98,101,108`; `orchestrator/service.py:185-205,220-227,2641-2651,2815-2818,2888-2891`; `orchestrator/workareas.py:45-55,378-404`; `orchestrator/driver.py:4473-4504`; `orchestrator/brainstorming.py:59-84` | touch one explicit exception-to-public-code mapping; do-not-return raw diagnostics, introduce a second error envelope, or adopt the non-canonical typed-error object |
| Slice boundary | Slice 6 exposes and drives the existing product-neutral state/result shapes. It adds no panel markup, dedicated visualization, milestone signal or return route, Agent99 code, target-specific schema, transcript vocabulary beyond stop's existing interruption, closure policy, storage engine, permission model, or public deletion/listing. Existing milestone routes and registry remain behaviorally unchanged. | `implementation/milestones/brainstorming/skeleton.md:36-47,73-80,94-108`; `orchestrator/service.py:2735-2916`; `implementation/milestones/brainstorming/goal.md:278-334,376-386` | touch standalone API/runtime and focused tests only; do-not-touch panel, milestone flow/registry, external repositories, or later adapters |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_api`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Standalone creation is real and independent | `test_create_runs_without_a_milestone_and_resolves_roster` | Administrative and authorized project-bound requests return the pinned 201 projection, preserve participant order, prefer configured cross-family assignments or record valid same-family fallback, start one lifecycle process, and leave milestone registry/state sentinels byte-identical. | strict |
| Refused creation has no effects | `test_create_refusals_are_typed_and_side_effect_free` | Invalid exact shapes, roster/policy errors, unavailable executors, missing/mismatched work areas, authority overlap, and an active equal or aliased target return the pinned code with no session/process/target/transcript or milestone write. | strict |
| Follow is stable, polling, and authorized | `test_detail_poll_is_authorized_before_state_read_and_revision_monotonic` | Create and every GET use the exact session projection; foreign/unbound remote access is refused before state read; repeated reads never regress revision, return valid state and repaired `chat.md`, and expose no event/stream route or raw diagnostic. | strict snapshot and access; eventual client observation |
| The background lifecycle reaches both results | `test_fake_provider_lifecycle_reaches_success_and_failure` | Real fake-CLI subprocess sessions run ordered turns and closure to one coherent success, while round exhaustion and an operational failure produce coherent failure; target/result/transcript references agree and no milestone artifact appears. | strict accepted state; best-effort provider delivery |
| Execution context is inherited | `test_bound_and_unbound_execution_context_passes_through_unchanged` | Every first call, continuation, repair, and closure call receives the same resolved tools/environment/root/access sentinel; workspace is orientation, source payload stays opaque, and no root or repository resolver is introduced after acceptance. | strict pass-through |
| Stop is target-safe and terminal | `test_stop_waits_for_quiescence_recovers_only_target_and_records_failure` | Stop during first or later work kills/reaps tracked descendants, accepts no attempted turn/revision/round/vote, restores the accepted target bytes/mode, leaves sibling sentinels unchanged, appends one human-safe interruption, publishes one failure/closing, and an identical repeat makes no write. | strict completion; best-effort signal delivery |
| Completion and stop cannot fork | `test_stop_completion_and_duplicate_launch_races_have_one_winner` | Concurrent launch admits one lifecycle process; concurrent stop and closure expose one terminal successor, one closing, no post-terminal participant call, and stale work returns neither a second result nor target revision. | optimistic contention; strict winner |
| Unclean process outcomes are honest | `test_unreconciled_process_exit_never_fabricates_terminal_state` | A normal process error becomes failure after safe recovery; injected unknown quiescence or recovery failure yields process stopped plus the last valid nonterminal state and `brainstorming_stop_incomplete`, never success or a false clean stop. | best-effort recovery; strict reporting |
| Existing service and core contracts remain compatible | `test_existing_routes_registry_and_slice_contracts_are_unchanged` | Existing `/api/runs`, project authorization, milestone registry, panel bytes, and Slice 1–5 focused suites retain their accepted behavior while no additional-root repository changes. | strict compatibility |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:309-319`). Later visualization and adapter work retain
the milestone-wide matrix in
`implementation/milestones/brainstorming/skeleton.md:124-137`.

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for every guarantee this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **verified current runtime:** the local service HTTP dispatcher, request identity/project authorization, project work-area resolver, process registry/stop convention, and the real Brainstorming session, participant-execution, coordination, transcript, and closure seams. **new direct consumer:** standalone callers and the focused API suite. **declared later consumer:** the dedicated view. **not touched:** current milestone routes/registry/panel and the read-only Agent99, Life, LPC, and Tutor roots. | `orchestrator/service.py:2641-2695,2702-2916`; `orchestrator/driver.py:4500-4604`; `orchestrator/brainstorming.py:1918-2333`; `orchestrator/brainstorming_execution.py:85-415`; `orchestrator/brainstorming_coordination.py:682-1315`; `implementation/milestones/brainstorming/skeleton.md:73-80` |
| pinned_facts | **closed facts:** the three routes and one success projection; exact creation input and roster resolution; durable caller/project access binding; polling lifecycle semantics; active-target isolation; stop's interruption and terminal failure; the exact public error vocabulary; and the no-UI/no-milestone/no-adapter boundary. | `implementation/milestones/brainstorming/slices/slice-06.md:123-132`; `implementation/milestones/brainstorming/skeleton.md:23-47,73-80,94-108`; Operator Amendment A1, **Target versioning clarification** |
| verification | **focused:** the nine named checks pin standalone creation, side-effect-free refusals, authorization and monotonic polling, both terminal outcomes, inherited context, target-safe stop, races, honest unclean exits, and compatibility. **full:** repository unittest discovery remains the milestone gate. | `implementation/milestones/brainstorming/slices/slice-06.md:134-156`; `implementation/milestones/brainstorming/skeleton.md:124-137`; `orchestrator/README.md:309-319` |
| reuse_posture | **checked:** existing HTTP/body/error envelopes, identity/project authorization, READY work-area resolution, atomic process registry, process-group spawn/stop/reap, Brainstorming CAS/state/transcript, persistent participant execution, ordered coordination, closure, and the older API planning note. **adopted:** those service and Brainstorming seams. **extended:** additive routes, an independent caller/process record, and one lifecycle loop. **new-with-why:** the independent process record/loop is necessary because no current process launches the coordinator and the milestone registry is forbidden as Brainstorming authority. | `orchestrator/service.py:866-925,1815-1895,2641-2953`; `orchestrator/registry.py:1-9,65-91,94-175`; `orchestrator/brainstorming.py:1918-2333`; `orchestrator/brainstorming_coordination.py:682-1315`; `implementation/milestones/brainstorming/skeleton.md:49-67,78,98`; `implementation/brainstorming/machine-api-and-persona-projection.md:31-55` |
| enforceability | **shape/vocabulary:** exact validators plus route tests. **authorization/context:** durable pre-read binding plus existing identity/project resolver and pass-through sentinels. **single process/target:** locked service metadata plus existing session-leader and target-exclusive locks. **lifecycle/follow:** SessionStore CAS/read reconciliation plus coordinator and closure successors. **stop:** process-group forwarding, quiescence evidence, target-only restore, interruption append, and terminal CAS. **limits:** polling/provider liveness and unclean-death recovery remain eventual/best-effort and are tested without promotion. | `implementation/milestones/brainstorming/slices/slice-06.md:200-211`; `orchestrator/access.py:41-69`; `orchestrator/service.py:866-925,1815-1895,2641-2695`; `orchestrator/brainstorming.py:1205-1357,1918-2333`; `orchestrator/brainstorming_coordination.py:142-168,387-490,682-1315`; `orchestrator/runners.py:31-59,642-736,1142-1174` |

### Reuse Posture

- **Checked:** the current service's JSON/body envelope, identity and
  project-membership gates, READY work-area resolution, atomic registry,
  session-leader process bookkeeping, stop forwarding, and polling model; all
  accepted Brainstorming contracts and focused tests; and the non-canonical
  machine-API/Persona note.
- **Adopted:** existing request/state/result validation, CAS and transcript
  reconciliation, persistent participant bindings, ordered coordinator,
  closure, service identity/project access, process-group supervision, and
  fake-CLI test style.
- **Extended:** the HTTP dispatcher gains only the three pinned routes. A
  separate Brainstorming service record binds caller, optional project/work
  area, target ownership, and lifecycle process without placing any of them in
  milestone state.
- **New-with-why:** one small standalone lifecycle loop and its independent
  service metadata are required because the coordinator currently exposes
  bounded turn/closure operations but nothing launches them as a complete
  service run, while the sealed boundary requires an independent API and
  forbids milestone-ledger authority. Authorities:
  `implementation/milestones/brainstorming/skeleton.md:58-67,78,98,108`;
  `orchestrator/brainstorming_coordination.py:682-1315`;
  `orchestrator/service.py:1298-1353,1815-1895`.
- **Compatibility:** existing service response framing, identity, project,
  process, and polling rigor are inherited rather than strengthened. Existing
  milestone routes, state, registry, panel, and external repositories remain
  untouched.

### Enforceability Gate

| invariant asserted here | mechanism that can enforce it | implementation gate |
|---|---|---|
| Exact create/inspect/stop schemas and codes | Existing bounded JSON-object reader and response envelope (`orchestrator/service.py:2924-2953`) plus the exact request/config validators (`orchestrator/brainstorming.py:500-596`) | Route matrix accepts only the pinned shapes/statuses and maps every lifecycle refusal to the pinned non-diagnostic code. |
| Authorized read and inherited execution context | Existing fail-closed identity and project membership (`orchestrator/access.py:41-69`; `orchestrator/service.py:2641-2695`) plus READY primary/additional resolution (`orchestrator/driver.py:4500-4604`) | Tests prove authorization uses immutable service binding before state access and the same resolved context object reaches every participant call. |
| One lifecycle process and one active service session per target | Existing locked atomic registry pattern and session-leader liveness/reaping (`orchestrator/registry.py:65-91,126-175`; `orchestrator/service.py:880-925,1815-1855`) extended to Brainstorming, plus the target-exclusive lock (`orchestrator/brainstorming_coordination.py:54-168`) | Double-launch and same-target races admit one process/session; the loser starts no worker and changes no target or state. |
| Current complete follow snapshots | SessionStore's validated CAS snapshot and read-time transcript reconciliation (`orchestrator/brainstorming.py:1918-1974,2118-2219`) | Polling tests observe nondecreasing revisions, one valid whole state, repaired transcript, and separately derived current process liveness. |
| Normal standalone completion | Existing ordered next-turn and closure operations (`orchestrator/brainstorming_coordination.py:944-1090,1116-1292`) over strict terminal result/closing validation (`orchestrator/brainstorming.py:1049-1126,1205-1291`) | Fake-CLI end-to-end tests reach coherent success and explicit failure without a milestone write. |
| Stop cannot accept post-terminal or unowned target work | Existing active-worker group stop (`orchestrator/runners.py:31-59`), session-group stop/wait (`orchestrator/service.py:1858-1895`), worker-quiescence evidence (`orchestrator/runners.py:1142-1174`), target-only reconciliation (`orchestrator/brainstorming_coordination.py:387-490,716-749`), and CAS interruption/terminal successors (`orchestrator/brainstorming.py:1309-1384,2306-2315`) | Stop/race tests require target-only restoration, no accepted attempted work, one interruption and failure, and a conflict rather than a clean-stop claim when any safety evidence is absent. |
| Best-effort limits stay honest | Existing fail-open liveness watchdog (`orchestrator/runners.py:642-736`) and the sealed posture (`implementation/milestones/brainstorming/skeleton.md:23-34`) | Blind liveness and unclean-exit fixtures may remain nonterminal/stopped, but never gain a fabricated result or notification guarantee. |
| No milestone or repository coupling | Independent-process and no-repository boundary (`implementation/milestones/brainstorming/skeleton.md:36-47,65-67,78,98`; Operator Amendment A1) | Sentinel tests keep milestone registry/state/panel and every path other than target plus Brainstorming-owned state/transcript byte-unchanged. |

If implementation authorizes from mutable session content, launches before the
durable binding wins, permits two live sessions for one target, reports stop
before quiescence and target recovery, or turns a dead nonterminal process into
success, the pinned guarantee is not delivered.

### Planning Material Disposition

- **Adopt:** the sealed skeleton as the operative boundary and the generated
  goal snapshot only for standalone caller intent and the required
  create/inspect/follow/stop capability it clarifies.
- **Revise:** the older machine-API note's additive-service and stable-schema
  direction into this independent Brainstorming lifecycle, using the accepted
  service identity, project, response, and polling conventions.
- **Reject:** that note's milestone event cursor, API-version field, typed error
  object, bearer token, external reference, attention state, push channel,
  Persona digest, and milestone-ledger projections; also reject every
  repository/VCS, new-permission, UI, and product-adapter expansion.

Authority:
`implementation/milestones/brainstorming/skeleton.md:3-5,36-67,78,94-122`;
`implementation/brainstorming/README.md:3-8,12-17`;
`implementation/brainstorming/machine-api-and-persona-projection.md:31-55,57-113`;
Operator Amendment A1, **Target versioning clarification**.
