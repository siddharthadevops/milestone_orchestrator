# Slice 06 — Standalone lifecycle API

## Register 1 — Intent

### What this slice builds

This slice gives people and product adapters a direct way to start a
caller-bounded Brainstorming discussion, inspect its progress, and stop it
without creating a milestone. A successful launch returns one stable session
identity. Repeated reads show the same durable discussion moving toward its
final result.

The service resolves available participant assignments before work begins,
keeps the caller's participant order and agreement rule, and runs the
discussion independently. A caller may use an existing declared work area or,
where the service already permits it, an administrative standalone working
directory.

### Ownership and boundary

This slice owns the public create, inspect/follow, and stop surface; durable
caller/work-area binding; background execution of an accepted session; and
explicit stop behavior. It joins the session, participant, round, transcript,
target-revision, and closure contracts from the preceding slices without
redefining them.

It does not add a screen, milestone transition, product adapter, event feed,
permission system, or target-version scheme. It does not interpret the question
or caller evidence. It never treats a working directory or target as a
repository.

### Guarantee posture

- **Strict:** accepted inputs, participant roles, caller visibility, durable
  state, terminal results, and successful stop responses are consistent. One
  accepted session has one lifecycle worker, and stop is not reported complete
  while participant work can still change the target.
- **Strict admission:** `max_rounds` is any positive caller-supplied integer.
  This API adds no fixed round maximum, artifact-size ceiling, retained-history
  allowance, or global active-session count. A target already owned by another
  nonterminal Brainstorming session remains unavailable.
- **Optimistic:** competing creation, completion, and stop operations contend
  on durable revisions. One outcome wins; stale work cannot append a second
  turn, result, or closing.
- **Eventual:** following is polling. A caller learns about new durable state on
  its next read; no push or exactly-once notification is promised.
- **Best-effort:** provider delivery and frozen-process detection retain their
  inherited limits. An unclean service death may leave a nonterminal session
  inspectable; it is not falsely promoted when quiescence or target recovery
  cannot be proved.

If required executors or runtime resources are actually unavailable, creation
may return the existing unavailable outcome without creating a session,
transcript, retained target revision, or participant process. That operational
outcome is not tied to a fixed cross-project quota and is not a Brainstorming
failure.

### Dependencies and consumers

This slice depends on the durable request, roster, lifecycle, and result record;
persistent participant conversations; ordered lead-owned target revisions; the
human transcript; and revision-bound closure.

Its direct consumers are standalone service callers and the dedicated view.
Existing service identity and declared work-area facilities remain the access
and execution-context sources. Existing milestone runs, milestone state, the
current panel, Agent99, Life, LPC, and Tutor are unchanged.

Slice 8 owns the corrective implementation that makes session creation retain
an unaccepted `recovery_baseline_revision` while leaving
`accepted_target_revision` null until completed lead work. It updates the
affected state, lifecycle, stop, and view checks without changing these public
routes or error vocabulary. The same correction carries one target-mutation
correction for the pending worker action and coherent failure on repetition
through the background lifecycle. It also adds regression coverage proving the
discarded numeric thresholds are not admission policy and that target-version
selection and recovery never probe repository/VCS state. The historical Slice
6 unit is not rerun.

### Non-goals

- No list, search, delete, restart, event cursor, streaming, webhook, digest, or
  Persona endpoint.
- No milestone creation, registry entry, chronology, or result action.
- No caller-supplied identity, executor command, environment, root grant, or
  access rule.
- No Agent99 or target-specific adapter and no interpretation of opaque caller
  evidence.
- No new bearer token, remote-binding policy, sandbox, custody, idempotency, or
  exactly-once claim.
- No fixed global quota, artifact-size limit, target-history allowance, or
  quota migration/retirement regime.
- No repository validation or repository/VCS inspection by target-version
  selection or recovery, and no recovery of any caller path other than
  `target_path`. Participant contextual inspection remains inherited.

### Acceptance

An authorized standalone caller can launch a valid cross-family or same-family
discussion and receive a stable session, then poll through ordered work to
either coherent terminal outcome without any milestone artifact or ledger
mutation.

Malformed input, a non-positive round bound, an unauthorized caller, an
unresolved work area, unavailable participant assignments or actual runtime
resources, an authority-overlapping target, or an already-active session for
the same target starts no participant and changes neither target nor durable
session state. A valid request is not refused solely because `max_rounds`
exceeds 16, the target exceeds 8 MiB, or eight other distinct-target sessions
are active.

Every progress read authorizes from the immutable caller/project binding before
session content is read. It returns one self-consistent durable snapshot and
current process observation. Opaque caller evidence and the resolved execution
context survive unchanged.

An explicit stop either returns an already-terminal session unchanged or waits
for local participant work to become unable to mutate, recovers only the target
to the last accepted Brainstorming revision—or to the unaccepted baseline
before any completed lead turn—records the material interruption, and returns a
coherent failure. If those conditions cannot be confirmed, the service reports
the existing retryable stop conflict and does not claim a clean stop.

The production seam should remain compact, but this slice is expected to exceed
the roughly 500 changed-line target once the standalone lifecycle, public API,
authorization and work-area integration, fake-provider end-to-end cases, and
stop/completion race matrix are counted. Those tests are the executable
evidence for the strict guarantees; generated and mechanical changes remain
excluded.

### Risks

- Reusing the milestone registry could place independent discussion in milestone
  chronology. Brainstorming service metadata remains separate.
- Authorizing from mutable session content could expose a discussion across
  projects. Visibility is decided before state access.
- Two sessions for one target could recover over each other. Admission permits
  only one nonterminal service-owned session for the resolved target.
- Stop can race a completed response. A clean stop requires quiet workers,
  verified target reconciliation, and one terminal winner.
- Push or delivery guarantees would exceed the neighbouring service contract.
- Turning deployment sizing into public policy would let arbitrary callers
  reject otherwise valid work. Only actual operational unavailability uses the
  unavailable outcome.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority | touch / do-not-touch |
|---|---|---|---|
| Public routes and success schema | The routes are `POST /api/brainstorming/sessions`, `GET /api/brainstorming/sessions/<session_id>`, and `POST /api/brainstorming/sessions/<session_id>/stop`. Create returns 201; inspect/follow and completed or already-terminal stop return 200. Success is exactly `{"ok": true, "session": session}`. `session` has `id`, `caller`, `project`, `work_area`, `process`, `revision`, and complete validated `state`; project/work-area are both strings or both null, process is `running` or `stopped`, and revision is the positive durable state revision. | frozen mandate, Standalone use and Separate visualization | touch additive Brainstorming dispatch and one stable projection; do-not-change `/api/runs`, add collection read, expose pid, or add stream route |
| Creation input and roster resolution | The body has required `request`, `participants`, and `closure_policy`, plus optional `project` and `work_area` supplied together. `request` is Slice 1's contract. Participant input is an ordered list of exact `{id, role}` objects with exactly one lead and at least one interlocutor. Before start, the service resolves immutable executor/model-family assignments, prefers multiple families, and otherwise records independent same-family fallback. Caller identity is derived. | skeleton, Request and context and Resolved roster | touch one API adapter into existing request/run config; do-not-add request fields, caller commands, taxonomy, or re-resolution |
| Execution context and access binding | With no project/work-area pair, create/read/stop are administrative-only and `workspace_path` is an existing directory. With a pair, existing project membership and READY work-area resolution apply; `workspace_path` equals the resolved primary path and additional roots/access rules pass through unchanged. Immutable service metadata authorizes before session state is read. No repository check applies. | skeleton, Execution context; frozen mandate, Inherited execution context | touch pass-through resolution and independent access/process record; do-not-add roots, narrow tools, trust request identity, or require Git |
| Standalone lifecycle and follow | Accepted creation writes no milestone state, transitions the Brainstorming session to running, and starts at most one lifecycle process. That process uses ordered turns and closure until durable success or failure. Repeated GETs return the latest complete state plus process observation; observed revision never decreases. A normal operational error becomes coherent failure only after safe reconciliation; an unclean death that cannot be reconciled stays visibly nonterminal/stopped. | skeleton, Process ownership and Closure/result | touch one Brainstorming lifecycle loop; do-not-use milestone units, add resume semantics, expose candidates, or promise push/exactly-once |
| Target admission and revision boundary | Creation rejects overlap with Brainstorming state/transcript authority and an equal or aliased target owned by another nonterminal session. It accepts every positive `max_rounds` and imposes no artifact/history/global-session threshold. Creation retains the exact target baseline but leaves accepted revision null. During the run, only completed lead work creates or advances accepted state; any other-turn mutation accepts no progress and recovers only the target. The same pending worker action may be corrected once; repetition restores the target and returns coherent `failure`, independently of the one envelope repair. External writes are outside contract. Target-version selection and recovery inspect no repository state or VCS object and change no other path; participant contextual access is unchanged. | skeleton, Roles, rounds, revisions, Invalid target mutation, and Execution context; Resource posture; Amendment A1 | touch Slice 8's baseline/null, bounded-failure, and no-VCS verification correction while reusing target-exclusive coordination; do-not-promote setup bytes, add quota policy, attribute external writes, or recover another path |
| Explicit stop | Stop accepts no body fields. On a nonterminal session it stops the lifecycle/participant processes, establishes quiescence, reconciles only the target to the accepted revision or baseline, appends the material interruption, and atomically terminalizes as failure. `rounds_used` does not increase and attempted work, votes, and target revisions are not accepted. Terminal stop is unchanged; concurrent stop/completion has one winner. Unconfirmed quiescence or recovery returns `brainstorming_stop_incomplete`. | skeleton, Guarantee Posture; Amendment A1 | touch lifecycle stop/failure composition; do-not-add a stopped durable result, terminalize before safety evidence, count stop as a turn, or promote the baseline |
| Error vocabulary | Errors retain `{"ok": false, "error": code}`. New codes are HTTP 400 `invalid_brainstorming_request`, HTTP 404 `unknown_brainstorming_session`, HTTP 409 `brainstorming_target_in_use` or `brainstorming_stop_incomplete`, and HTTP 503 `brainstorming_unavailable`. Non-positive/non-integer round bounds are invalid. Missing executors or actual admission unavailability may use unavailable. Existing identity/project refusals pass through unchanged. No error exposes raw output, command, environment, or provider reference. | existing service contract; skeleton, Resource posture | touch explicit public mapping; do-not-add a quota error, second envelope, or diagnostics |
| Slice boundary | Slice 6 exposes and drives product-neutral state/result shapes. Slice 8 corrects baseline-versus-acceptance facts and affected consumers without changing route envelopes or lifecycle result shapes. No panel markup, milestone signal, Agent99 code, target schema, permission model, or public deletion/listing is added here. | skeleton, Planned Slices | touch standalone API/runtime plus declared correction; do-not-touch milestone flow, external roots, or later adapters |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_api`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Standalone creation is independent | `test_create_runs_without_a_milestone_and_resolves_roster` | Authorized requests return the 201 projection, retain order, resolve cross-family or valid fallback assignments, start one lifecycle process, and leave milestone state unchanged. | strict |
| Refused creation has no effects | `test_create_refusals_are_typed_and_side_effect_free` | Invalid shapes, non-positive round bounds, roster/policy errors, unavailable executors/resources, work-area failures, authority overlap, and an active equal/aliased target return the pinned code with no session/process/target/revision/transcript write. | strict |
| No document-invented numeric admission policy | `test_request_and_target_admission_has_no_fixed_global_quota` | A request above 16 rounds, a regular target above 8 MiB, and a ninth concurrent distinct-target session are accepted when ordinary authorization and resources are available; none is refused solely by the discarded threshold. | strict |
| Follow is stable, polling, and authorized | `test_detail_poll_is_authorized_before_state_read_and_revision_monotonic` | Foreign/unknown reads are refused before content access; repeated reads never regress, return valid state and reconciled `chat.md`, and expose no stream or raw diagnostic. | strict snapshot/access; eventual observation |
| Background lifecycle reaches both results | `test_fake_provider_lifecycle_reaches_success_and_failure` | Real fake-CLI sessions run turns/closure to coherent success; round exhaustion and safe operational failure produce coherent failure; target/result/transcript references agree and no milestone artifact appears. | strict accepted state; best-effort delivery |
| Execution context is inherited | `test_bound_and_unbound_execution_context_passes_through_unchanged` | Every start, continuation, repair, and closure call receives the same resolved tools/environment/root/access sentinel; workspace is orientation and source payload stays opaque. | strict pass-through |
| Stop is target-safe and terminal | `test_stop_waits_for_quiescence_recovers_only_target_and_records_failure` | Stop during work reaps tracked descendants, accepts no attempted progress, restores baseline before lead acceptance and accepted target afterward, leaves siblings unchanged, appends one interruption/closing, and publishes one failure. | strict completion; best-effort signal delivery |
| Completion and stop cannot fork | `test_stop_completion_and_duplicate_launch_races_have_one_winner` | Duplicate launch admits one process; stop/closure exposes one terminal successor and no post-terminal participant call. | optimistic contention; strict winner |
| Unclean outcomes are honest | `test_unreconciled_process_exit_never_fabricates_terminal_state` | Unknown quiescence or recovery failure yields process stopped plus last valid nonterminal state and stop-incomplete, never success or false clean stop. | best-effort recovery; strict reporting |
| Existing consumers remain compatible | `test_existing_routes_registry_and_slice_contracts_are_unchanged` | Existing milestone routes, project authorization, registry, panel, and Slice 1–5 contracts retain behavior; external roots remain unchanged. | strict compatibility |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`.

### Question Battery

The skeleton's Question Battery is inherited. Slice-specific answers:

| question | answer | evidence |
|---|---|---|
| consumers_touched | Local service dispatch, identity/project authorization, work-area resolution, process registry/stop convention, Brainstorming lifecycle, dedicated view, and focused API tests. | Dependencies and consumers |
| pinned_facts | Three routes, one success envelope, exact creation input, durable access binding, polling lifecycle, active-target isolation, caller-selected positive rounds, one bounded target-mutation correction with coherent failure, side-effect-free actual unavailability, target-safe stop, and exact errors. | Pinned-Facts Table |
| verification | Focused checks plus Slice 8's corrective regression pin creation, refusals, absence of fixed numeric quotas, authorization/follow, both outcomes including repeated-mutation failure, inherited context, fail-on-access detection of repository/VCS dependencies, stop/races, honest failures, and compatibility. | Verification Contract |
| reuse_posture | Existing HTTP envelopes, authorization, work-area resolution, process bookkeeping, stop/reap, Brainstorming state/transcript/coordination/closure, and polling are adopted. A separate Brainstorming lifecycle record/loop is the only necessary extension. | Reuse Posture |
| enforceability | Exact validators and route tests enforce shape; immutable pre-read binding enforces access; process registry and target lock enforce one lifecycle/target; SessionStore snapshots enforce follow; quiescence plus target-only reconciliation enforce stop. | Enforceability Gate |

### Reuse Posture

- **Checked and adopted:** current JSON/error envelope, identity/project access,
  READY work-area resolution, atomic process registry, process-group stop/reap,
  Brainstorming CAS/state/transcript, participant execution, ordered
  coordination, closure, and polling conventions.
- **Extended:** three additive routes, an independent caller/process record,
  and one small lifecycle loop.
- **New-with-why:** the independent record/loop is required because no current
  process launches the coordinator as a standalone service run and milestone
  state cannot be Brainstorming authority.
- **Compatibility:** existing routes, milestone state/registry/panel, project
  contracts, and external repositories remain unchanged. Slice 8 changes only
  recovery-baseline versus accepted-revision state and its consumers.

### Enforceability Gate

| invariant | enforcing seam | implementation gate |
|---|---|---|
| Exact schemas and codes | Existing response envelope plus exact request/config validation | Route matrix accepts only pinned shapes/statuses and maps refusals without diagnostics. |
| No fixed numeric quota | Positive-integer request validation and no target-size/history/global-count threshold in admission | Regression accepts values above all discarded thresholds when ordinary resources are available. |
| Side-effect-free actual unavailability | Admission completes before session/process/transcript creation | Missing-executor and injected resource-unavailable fixtures return 503 with no target or durable effect. |
| Authorized inherited context | Existing identity/project membership and READY root resolution | Tests authorize before state access and pass the same resolved context to every participant call. |
| One lifecycle and one session per target | Atomic process registry plus target-exclusive coordination | Double-launch and same-target races admit one winner; loser changes nothing. |
| Complete follow snapshots | Validated SessionStore snapshot and transcript reconciliation | Polling sees nondecreasing revisions, one whole state, and current process liveness. |
| Target-safe stop | Process-group stop, quiescence evidence, target-only recovery, and terminal CAS | Stop/race tests require exact target restoration, no attempted progress, one interruption/failure, and conflict when safety evidence is absent. |
| No milestone or VCS coupling | Independent process boundary and Amendment A1 | Milestone and non-target sentinels prove write isolation only. Slice 8's named fail-on-access regression observes process and filesystem reads during target-version selection and recovery, failing on every repository/VCS probe. |

If implementation authorizes from mutable session content, launches before the
durable binding wins, permits two live sessions for one target, reports stop
before quiescence and recovery, or turns a dead nonterminal process into
success, the guarantee is not delivered.

### Planning Material Disposition

- **Adopt:** the skeleton and frozen mandate.
- **Revise:** older machine-API hints only into the independent, polling
  lifecycle pinned here.
- **Reject:** event cursors, replacement error envelopes, bearer tokens, push,
  Persona projections, fixed quotas, Git/VCS recovery, new permissions, UI, and
  product-adapter expansion.
