# Slice 02 — Persistent participant execution

## Register 1 — Intent

### What this slice builds

This slice gives every brainstorming participant a private, continuing agent
conversation. When that participant speaks again, the provider remembers its
earlier work; two participants using the same provider still have separate
conversations. The operating-system command may finish between turns—the
durable conversation identity is what persists.

The slice is for the coordinator built by later slices. It accepts a prompt for
one already-resolved participant, runs it with the caller's existing work-area
and access context, and returns only a valid Markdown discussion envelope.

### Ownership and boundary

This slice owns participant-to-executor binding, durable logical-session
identity, one validated discussion-turn envelope, and process supervision for
each in-flight participant exchange.

It does not choose participants, order turns, count rounds, compose the
discussion prompt, decide who may edit the target, write `chat.md`, conduct a
closure vote, expose routes or screens, or connect Milestone Orchestrator or
Agent99. Those remain with the sealed later slices.

### Guarantee posture

- **Strict:** only a durably `running` session accepts an exchange; a
  participant is always bound to its persisted `executor_ref` and
  `model_family`; an accepted exchange has one write-once explicit session
  reference; later exchanges continue that reference; same-family participants
  never share a logical session; caller execution context is passed through
  unchanged; and only an exact valid discussion envelope is returned.
- **Optimistic:** concurrent attempts to establish the first reference use the
  existing compare-and-set discipline. One durable binding wins; a stale
  attempt cannot replace it.
- **Eventual:** none. Execution identity and accepted envelopes are not a
  projection.
- **Best-effort:** provider-call delivery and frozen-process detection inherit
  the current posture. An unmeasurable liveness interval is treated as live;
  an interrupted call may be reissued; there is no exactly-once, perfect
  provider-liveness, or remote-effect-revocation claim.

### Dependencies and consumers

The sealed Slice 1 request, roster, lifecycle, and durable-state contracts are
the only slice prerequisite. This slice extends the shared CLI runner and
process supervision without changing their current one-shot Milestone consumer.
Slice 3 is the first runtime consumer of the new participant-execution seam.
The current service routes and all additional-root products remain untouched.

### Non-goals

- No turn ordering, round accounting, target snapshot/edit enforcement,
  transcript append, target revision, ballot, closure, or terminal decision.
- No implicit “latest conversation” continuation and no silent fresh-session
  fallback after an explicit continuation fails.
- No new executor selection, model-family policy, permission, sandbox, root,
  work-area, provider, idempotency, retry-delivery, or recovery system.
- No public API route, UI projection, milestone signal, or Agent99 adapter.
- No provider diagnostics or session references in the future human transcript.

### Acceptance

The slice is accepted when cross-family and same-family fixtures each preserve
private working context across repeated exchanges; every accepted continuation
uses the durable explicit reference; a missing, mismatched, or non-continuable
executor and a non-running lifecycle cannot produce an accepted turn; caller
context arrives unchanged on the first and later exchanges; malformed output
gets at most one repair in the same logical session and never becomes a
completed turn; stale binding writes cannot replace a winner; and frozen,
active, unmeasurable, stopped, and descendant-process cases retain the current
supervision behavior.

The production seam should stay narrow, but the slice is expected to exceed the
roughly 500 changed-line target once the two-provider fake-CLI, restart/CAS, and
process-group tests are counted. Those tests are the executable evidence for
the mandated continuity and inherited supervision; generated and mechanical
changes remain excluded.

### Risks

- An implicit “most recent” resume can cross-wire two same-family participants.
  Acceptance requires the exact durable reference on every continuation.
- A provider response can exist before its reference is durably accepted.
  Compare-and-set prevents state replacement, but a crash may leave an unused
  provider conversation; the goal explicitly forbids inventing idempotency.
- Shared-runner changes could alter ordinary milestone calls. The legacy call
  contract and its full existing tests remain compatibility gates.
- Re-resolving or narrowing roots on continuation would silently change the
  caller's authority. Sentinel-context checks cover every exchange.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Durable participant-session projection | The cross-slice projection is exactly `participant_sessions`: an object whose keys are only persisted participant ids and whose present values are non-empty opaque, executor-namespaced `session_ref` strings. A key is added at most once and is never changed or removed; no two participants share a reference. A first envelope is not accepted until its reference wins durable compare-and-set. | `implementation/milestones/brainstorming/skeleton.md:23-32,74,92,100,102`; `implementation/milestones/brainstorming/goal.md:91-104,177-183`; `orchestrator/brainstorming.py:393-478`; `orchestrator/kvstore.py:343-359,391-457` | touch additive execution state/projection; do-not-rewrite Slice 1 request, roster, lifecycle history, or terminal result |
| Lifecycle admission | Participant start, continuation, and repair are admitted only while the durable session `status` is exactly `running`. `created`, `success`, and `failure` reject before a provider call or binding write. | `implementation/milestones/brainstorming/skeleton.md:23-32,73-74`; `orchestrator/brainstorming.py:17-27,336-390`; `implementation/milestones/brainstorming/goal.md:50-63,266-279` | touch an execution admission guard; do-not-add lifecycle states or reopen terminal sessions |
| Executor binding and inherited context | Each call uses the participant's immutable `executor_ref` and `model_family`. The execution input named `execution_context` is the caller-resolved capability bundle; first and continued exchanges receive it unchanged, including tools, environment, primary/additional roots, sibling access, and access rules. `workspace_path` remains orientation. A missing executor, family mismatch, or executor without explicit continuation support is rejected before an envelope is accepted. | `implementation/milestones/brainstorming/skeleton.md:25-32,42-43,74,100-102`; `implementation/milestones/brainstorming/goal.md:148-183`; `orchestrator/driver.py:911-958`; `orchestrator/prompts.py:584-619`; `orchestrator/runners.py:748-759` | touch pass-through and binding validation; do-not-resolve roots again, add roster fields, or create access policy |
| Explicit logical continuation | A participant's first exchange establishes its `session_ref`; every later exchange addresses that exact reference. Selection by “latest”, process-global recency, or another participant's reference is forbidden. Continuation failure is surfaced and never replaced by a fresh logical session. The OS subprocess may exit between exchanges; the provider conversation identity must not. | `implementation/milestones/brainstorming/skeleton.md:58-64,74,92,102`; `implementation/milestones/brainstorming/goal.md:177-183`; `orchestrator/runners.py:465-476,519-528,644-850` | touch one provider-neutral start/continue seam and configured provider bindings; do-not-replace the one-shot Milestone call contract |
| Discussion-turn envelope | The only envelope this slice adds has exactly `kind` and `markdown`; `kind` is exactly `discussion_turn` and `markdown` is a non-empty string. Participant identity, role, round, target/revision facts, votes, results, and transport status are not model-supplied fields. The caller associates the validated envelope with the participant it invoked. | `implementation/milestones/brainstorming/skeleton.md:74-77,103-105`; `implementation/milestones/brainstorming/goal.md:174-187,230-248` | touch one exact validator; do-not-pull round, edit, transcript, or closure contracts forward |
| Validation and repair | Each requested discussion turn accepts exactly one contract-valid JSON object. An invalid first response permits one repair exchange in the same logical session; a second invalid response is a protocol failure. Invalid raw responses remain technical evidence and are never accepted as discussion. The repair exchange is control, not another completed discussion turn. | `orchestrator/runners.py:414-459,962-1053`; `implementation/milestones/brainstorming/skeleton.md:25-32,74,103-104`; `implementation/milestones/brainstorming/goal.md:174-187,230-241` | touch reusable validation/repair entry point; do-not-parse prose, accept multiple objects, or create a fresh repair session |
| Supervision and delivery | Every in-flight start, continuation, and repair uses the existing process-group watchdog: CPU progress, process-set change, or output growth means live; an unmeasurable interval fails open as live. Stop/timeout/stall cleanup targets and reaps the whole worker group. This is best-effort and at-least-once: no provider-internal or exactly-once guarantee is added. | `implementation/milestones/brainstorming/skeleton.md:23-34,74,102`; `orchestrator/runners.py:30-58,548-642,644-850,874-885`; `orchestrator/driver.py:1574-1579` | touch parameterization/wrapping of existing supervision; do-not-create a parallel watchdog or stronger delivery promise |
| Slice boundary | Slice 2 returns validated participant discussion and preserves logical-session identity. Slice 3 owns ordering/rounds/lead edits, Slice 4 `chat.md`, Slice 5 votes/results, Slice 6 lifecycle API, Slice 7 visualization, and Slice 8 `need_rethink`. Existing `SubprocessRunner.call`, service routes, panel, Milestone transitions, and additional roots remain behaviorally unchanged. | `implementation/milestones/brainstorming/skeleton.md:36-47,73-80`; `orchestrator/driver.py:357-361,988-1015`; `orchestrator/service.py:2735-2887` | touch participant execution plus focused tests; do-not-touch later consumers or external roots |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_execution`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Explicit references preserve private context | `test_explicit_session_refs_survive_reload_and_isolate_participants` | Two turns per participant observe their own earlier marker after the execution store is reopened; no participant sees another's marker or receives a rewritten reference. | strict |
| Same-family fallback remains independent | `test_same_family_participants_never_use_implicit_latest_session` | Two participants with one family and executor obtain separate references; recorded provider invocations always name the intended reference and never select by recency. | strict |
| Lifecycle, binding, and context are inherited | `test_execution_admission_binding_and_context_pass_through` | Created/terminal sessions and missing/mismatched/non-continuable bindings make no provider call and yield no reference; valid running-session start, continuation, and repair calls receive the same sentinel tools, environment, roots, rules, and workspace orientation. | strict |
| Envelope validation is closed | `test_discussion_turn_envelope_contract` | Only the exact two-field envelope with `discussion_turn` and non-empty Markdown passes; missing, extra, wrong-type, multiple-object, identity, round, target, vote, result, and transport fields fail. | strict |
| Repair stays in one logical session | `test_protocol_repair_continues_once_without_completing_an_extra_turn` | One malformed response is repaired through the same reference; two malformed responses fail; neither invalid response nor the repair exchange is returned as an additional discussion turn. | strict validation; best-effort delivery |
| Binding persistence is conflict-safe | `test_first_session_ref_compare_and_set_is_write_once` | Concurrent first exchanges expose one durable winner; a stale writer cannot replace/delete it, and a failed store write exposes no accepted envelope. | optimistic conflict detection; strict accepted state |
| Existing supervision is inherited | `test_participant_calls_reuse_liveness_and_stop_supervision` | Frozen work is killed; CPU, process-set, or output progress survives; unmeasurable windows survive; stop and setup/interruption paths leave no tracked descendant or temporary resource. | best-effort liveness |
| Existing one-shot consumers do not change | `test_legacy_runner_call_contract_is_unchanged` | Ordinary configured calls still receive the same argv/model/effort, workspace, environment, output, repair, timeout, and cleanup behavior without a session reference. | strict compatibility |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:309-319`). Later slices add their own focused checks;
milestone closure runs the matrix in
`implementation/milestones/brainstorming/skeleton.md:124-137`.

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for this slice.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **verified current runtime consumer:** every Milestone worker call through `Driver._call` and `SubprocessRunner.call`; shared-runner behavior must not change. **slice-local consumer:** the new focused execution tests. **state dependency:** Slice 1's real immutable roster/session store is read and additively projected. **declared next consumer:** Slice 3's coordinator. **not touched:** current service routes, panel, Agent99, Life, LPC, and Tutor. | `orchestrator/brainstorming.py:336-487`; `orchestrator/driver.py:357-361,988-1015`; `orchestrator/service.py:2735-2887`; `implementation/milestones/brainstorming/skeleton.md:73-80` |
| pinned_facts | **closed facts:** write-once `participant_sessions`; running-only admission; immutable executor/family binding; unchanged `execution_context`; explicit-reference continuation with no implicit/fresh fallback; exact `discussion_turn` envelope; one same-session repair; inherited supervision/delivery posture; later-slice and external-root exclusions. | `implementation/milestones/brainstorming/slices/slice-02.md:99-108`; `implementation/milestones/brainstorming/skeleton.md:23-34,73-80,100-103` |
| verification | **focused:** the eight named checks pin continuity across reload, same-family isolation, lifecycle/binding/context, envelope closure, same-session repair, CAS, liveness/stop, and legacy compatibility. **full:** repository unittest discovery remains the milestone gate. | `implementation/milestones/brainstorming/slices/slice-02.md:110-131`; `implementation/milestones/brainstorming/skeleton.md:124-137`; `orchestrator/README.md:309-319` |
| reuse_posture | **checked:** Slice 1 state/CAS, current JSON extraction/one-repair protocol, command templates, process-group liveness/stop, prompt/root pass-through, service consumers, and Agent99's deferred work-area boundary. **adopted:** exact validation, CAS, subprocess context, watchdog, stop, and mocks. **extended:** explicit logical-session start/continue and durable reference projection. **new-with-why:** only that continuation seam, because the accepted runner is one-shot and the skeleton explicitly requires the missing capability. | `orchestrator/brainstorming.py:393-487`; `orchestrator/runners.py:30-58,414-476,519-948,986-1053`; `orchestrator/driver.py:43-64,911-958`; `../life_prod/agent_99/apps/agent_99/lib/agent_99/body/work_area.ex:1-57`; `implementation/milestones/brainstorming/skeleton.md:49-67,74,92` |
| enforceability | **identity/binding:** lifecycle and projection validators plus locked CAS. **continuation:** an explicit-reference-only adapter exercised by stateful fake CLIs; implicit recency is outside its accepted input. **context:** identity/equality sentinels at every provider call. **envelope/repair:** exact-key validator, unambiguous JSON extraction, and one same-session retry. **liveness/stop:** existing measured process-group watchdog and reap path. **excluded:** no round, edit, transcript, closure, route, exactly-once, or perfect-liveness guarantee is asserted. | `implementation/milestones/brainstorming/slices/slice-02.md:99-131,169-180`; `orchestrator/brainstorming.py:336-390`; `orchestrator/kvstore.py:343-359,391-457`; `orchestrator/runners.py:30-58,414-459,548-642,644-885,986-1053` |

### Reuse Posture

- **Checked:** Slice 1's validated immutable roster and locked CAS; the current
  exact JSON extractor and one-repair path; configured Codex/Claude command
  templates; process-group liveness, stop, and cleanup; root/context rendering;
  service routes; and Agent99's real named work-area boundary.
- **Adopted:** the validator/CAS patterns, existing subprocess environment and
  workspace behavior, liveness signals, active-worker stop/reap, and mock/fake
  CLI test style.
- **Extended:** the runner gains a provider-neutral explicit-reference
  start/continue capability and brainstorming gains the write-once
  `participant_sessions` projection.
- **New-with-why:** no new supervisor, storage engine, or access layer. The only
  new machinery is logical-session continuation because the existing runner is
  expressly one-shot while the sealed skeleton requires persistent participant
  sessions. Authority: `implementation/milestones/brainstorming/skeleton.md:49-67,74,92`;
  `orchestrator/runners.py:1-14,465-476,644-850`.
- **Compatibility:** callers that do not request participant continuation keep
  the existing one-shot interface and behavior. The new path consumes the
  already-resolved roster and caller context without changing Milestone state,
  routes, or any additional-root repository.

### Enforceability Gate

| invariant asserted here | mechanism that can enforce it | implementation gate |
|---|---|---|
| One write-once explicit reference per participant | Exact `participant_sessions` projection plus existing locked whole-value CAS (`orchestrator/kvstore.py:343-359,391-457`) | Reload/concurrency/failure checks observe one winner, no rewrite/delete, and no accepted envelope before commit. |
| Running-only execution | Existing closed lifecycle validator and legal transitions (`orchestrator/brainstorming.py:17-27,336-390`) checked before any executor call | Created and terminal fixtures observe no provider call, binding write, or accepted envelope. |
| Correct participant and same-family isolation | Immutable roster validation (`orchestrator/brainstorming.py:158-203,393-400`) plus the explicit-reference-only seam pinned above | Stateful fake providers prove each participant sees only its own prior turns; missing/mismatched capability fails before acceptance. |
| Same logical conversation across exchanges | The new adapter requires the durable `session_ref` for every continuation and offers no “latest” input; the seam is mandated by `implementation/milestones/brainstorming/skeleton.md:74,92,102` | Provider-binding tests inspect every start/continue and fail on implicit selection, reference switching, or fresh fallback. |
| Exact discussion envelope and bounded repair | Exact-key/type helpers (`orchestrator/brainstorming.py:65-93`), unambiguous JSON extraction, and existing one-repair boundary (`orchestrator/runners.py:414-459,986-1053`) | Invalid/extra/multiple outputs are rejected; one repair uses the same reference; a second strike returns no turn. |
| Caller execution context is unchanged | Existing fixed-root input, prompt rendering, and subprocess cwd/environment seams (`orchestrator/driver.py:911-958`; `orchestrator/prompts.py:584-619`; `orchestrator/runners.py:748-759`) | Sentinel context is identical on start, continuation, and repair; no root resolver or policy layer is invoked. |
| Best-effort liveness and stop | Existing process tracking, three-signal fail-open watchdog, group kill, reap, and cleanup (`orchestrator/runners.py:30-58,548-642,644-885`) | Frozen/active/blind-window/stop/descendant tests retain the accepted neighboring behavior. |
| No exactly-once claim | Existing at-least-once worker boundary plus the sealed best-effort posture (`orchestrator/driver.py:1574-1579`; `implementation/milestones/brainstorming/skeleton.md:23-34`) | Crash/CAS tests permit an unused external conversation but never a second accepted binding or silent context replacement. |

If implementation relies on prompt discipline, provider recency, or convention
for any strict row instead of the named mechanical gate, that guarantee is not
delivered.

### Planning Material Disposition

- **Adopt:** no brainstorming or `_drafts` file as independent authority; only
  the sealed skeleton and, where it does not settle intent, its generated goal
  snapshot.
- **Revise:** older machine-API material is only a reminder to keep the seam
  product-neutral and inspectable. Its routes and projections are not Slice 2.
- **Reject:** bearer-token, event-cursor, Persona-digest, milestone-phase, and
  any new permission/work-area proposal as participant-execution scope.

Authority: `implementation/milestones/brainstorming/skeleton.md:110-122`;
`implementation/brainstorming/README.md:3-8,12-17`;
`implementation/brainstorming/machine-api-and-persona-projection.md:31-55,81-113`.
