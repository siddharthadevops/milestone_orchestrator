# Slice 01 — Continuable Brainstorming after round exhaustion

## Register 1 — INTENT (lay language)

### What this slice builds

This slice turns an unfinished Brainstorming round limit into a pause, not a
failure. When the allotted rounds end without agreement, the discussion stops
at a complete-round boundary and waits for an operator. The same discussion,
its work, and anything waiting on it remain open.

An operator can reserve more rounds without restarting the discussion, then
continue it. Continuing always leaves room for at least two complete new rounds
unless the operator already reserved more. Each Continue identifies the exact
waiting revision the operator chose: retrying that authorization cannot cross a
later exhaustion, whose new revision requires fresh operator action. Retrying
either control does not silently increase the allowance again. Later capacity
changes do not rewrite the admitted limit or the meaning of accepted history.

The public service shows that the discussion is waiting and shows rounds used,
the current maximum, and rounds remaining. The existing panel presents the same
facts and invokes the same public controls available to another authenticated
client. This applies both to directly created discussions and to discussions
owned by tasks or milestone work.

### Ownership and boundary

This slice owns round-exhaustion waiting, monotonic round extension, explicit
continuation, their public presentation, and preservation of every enclosing
owner while a discussion waits.

It extends the existing Brainstorming state, lifecycle, service, panel, task
adapter, and caller wait seams. It does not create another session engine,
scheduler, task type, store, process, or client-only source of truth.

The discussion still owns its target, roster, transcript, ballots,
interventions, context, and call accounting. Callers still own their task and
milestone lifecycles; they merely continue waiting until Brainstorming reaches a
real terminal outcome. An explicit Stop of a directly ordered task remains the
caller's existing abandonment action and leaves its owned discussion terminal
as well as the task.

### Guarantee posture

- **Strict:** a completed boundary without closure becomes non-terminal waiting;
  accepted discussion history, including its opening limit and ballot meaning,
  and identities are not replaced; round capacity never decreases; continuation
  uses the current durable counts and is scoped to one waiting revision; accepted
  turns and controls are not duplicated; a successful task Stop cannot leave its
  owned discussion actionable; terminal outcomes remain immutable; and an
  enclosing task or run cannot fail merely because the round allowance ended.
- **Optimistic:** concurrent extension, continuation, closure, and inspection
  contend on the session revision. An accepted winner is strict; a stale writer
  rereads or receives the public conflict rather than overwriting it.
- **Eventual:** the stopped/running process indicator and panel view converge by
  reaping and polling. They are not the durable session authority.
- **Best-effort:** provider liveness and physical exactly-once execution retain
  their existing posture. Recovery may repeat an unrecorded physical call, but
  it may not duplicate an accepted turn, ballot, intervention, or charge.

### Dependencies

The slice depends on the existing revisioned session store, complete-round and
closure contracts, lifecycle registry and gated launch, authenticated session
routes, session view and polling panel, Brainstorming task adapter, direct task
host, and reviewed/deep/milestone wait behavior.

No third-party package or external service is added. The granted Life, Agent99,
life_product_components, and Tutor roots remain read-only and gain no adapter.

### Non-goals

- No change to participant selection, prompt routing, closure policy, vote
  meaning, target custody, intervention semantics, or production effects.
- No new Brainstorming session or task identity, owner relation, task result,
  milestone event, accounting ledger, queue, retry daemon, or migration.
- No automatic continuation, automatic round purchase, background timeout, or
  reopening of a terminal session or task.
- No exactly-once provider-call claim and no attempt to deduplicate work that
  was never durably accepted.
- No panel-only continuation flag, inferred round count, hidden request retry,
  or alternate endpoint for task-owned discussions.
- No upper bound invented for an operator-selected positive ceiling, and no
  defensive validation layer around trusted orchestrator-emitted owner links.

### Acceptance criteria

At a complete round boundary without closure, both document-target and
repository-backed discussions preserve the completed round and any accepted
non-approving ballot, expose no terminal result, stop execution, and become an
actionable wait. A lead declining to propose closure reaches the same wait
without fabricating a ballot. Reaching the limit again after continuation
returns to the same kind of wait.

Adding rounds changes only a durable effective ceiling and its current-capacity
projections; the admitted request ceiling and accepted transcript history remain
unchanged, and it never starts work. Repeating the same requested ceiling is a
no-op, a smaller stale request cannot reduce a larger one, and a larger manual
ceiling wins over the automatic continuation minimum. If an extension wins
while an unresolved closure decision is in flight, that decision cannot use the
older ceiling to exhaust or terminalize the session: it rereads the accepted
capacity or conflicts without mutation.

Continuing uses the same session and the exact durable waiting revision exposed
by its authorized read. From zero, one, or at least two rounds remaining, it adds
two, one, or zero respectively and resumes at the next work not already durably
accepted. A duplicate or stale authorization, including a delayed retry after a
later exhaustion, conflicts without mutation; that later wait requires its
current revision. Continue does not repeat the exhausted round, closure proposal,
ballot votes, intervention, session, or task.

While waiting, a directly ordered Brainstorming task has no result. The same is
true of its reviewed-task child, deep-task parent, milestone unit, and run where
those owners exist. After continuation, their existing wait observes the same
session and closes only on later success or genuine failure.

An explicit Stop of a directly ordered task while its owned discussion is
waiting is an operator abandonment, not another pause. A successful Stop leaves
the task terminal as failure and its session terminal, preserves their accepted
history and accounting, and makes Add rounds and Continue conflict without
mutation. A session outcome that became terminal first remains immutable. Stop
racing Continue cannot start work under a terminal task: Continue may win only
while the task is open, and a later accepted Stop ends the resumed discussion if
it is still non-terminal. Later work requires the existing new-task operation
and a new session identity.

Authenticated API-only use and panel use both complete the wait, add, continue,
wait-again, and eventual terminal paths. Existing success, operator stop,
operational failure, protocol failure, access refusal, and unavailable-service
behavior remain independently covered.

Historical terminal failures are not converted to waits. Neither continuation
control mutates them; further work requires a newly admitted session or task
with a new identity.

### Risks

The main risks are recording failure before the wait, allowing a round extension
to wake the process, losing a larger extension to a concurrent Continue,
allowing stale closure to ignore an accepted extension, rewriting the historical
opening limit or ballot meaning, letting a delayed Continue retry cross a later
exhaustion, repeating the last closure attempt after restart, or letting an
enclosing task interpret waiting as failure. A further risk is splitting a task
Stop so the task is terminal while its owned discussion remains actionable.

Other risks are presenting stale counts as authority, accepting a negative or
non-integer ceiling, reopening historical terminal records, duplicating a
session/task on recovery, or promising physical exactly-once execution that the
provider boundary cannot enforce.

## Register 2 — PINNED-FACTS TABLE (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Exhaustion outcome | Brainstorming session statuses add exactly non-terminal `waiting`; terminal statuses remain exactly `success` and `failure`. At a complete round boundary with no valid closure, the completed turn/pass and any non-approving ballot are accepted with `status: "waiting"`, no `result`, no top-level `closing_summary`, and no failure origin. The lifecycle process then stops. A no-proposal boundary stores no invented ballot. Repeated exhaustion returns to `waiting`. | operative authority § Request, lines 5-12; current status/transition vocabulary `orchestrator/brainstorming.py:32-64,2437-2544`; current contrary terminalization `orchestrator/brainstorming.py:2280-2368,2889-2972,3062-3113`; `orchestrator/brainstorming_coordination.py:2550-2703` | touch the existing state/closure/repository-boundary/lifecycle contracts; do-not-add another terminal outcome, treat waiting as failure, fabricate a vote, or leave the exhausted process doing participant work |
| Round facts and Add rounds | The admitted `request.max_rounds` remains the immutable original limit. A separate durable effective ceiling supplies the current facts `used = rounds_used`, `maximum = effective ceiling`, and `remaining = maximum - used`, with `maximum >= used`; the existing public `max_rounds` field projects that effective maximum. Public `exhausted` is true exactly when status is `waiting` and remaining is `0`. `POST /api/brainstorming/sessions/<id>/rounds` accepts exactly `{"maximum": <positive integer>}` and returns `{"ok": true, "session": session}`. For every non-terminal session it raises the effective ceiling to `max(current maximum, requested maximum)` and starts no process. The panel's **Add rounds** quantity is positive and posts displayed maximum plus that quantity. Equal, stale, duplicate, or retried absolute ceilings are safe no-ops; a larger ceiling is never lost. An accepted extension and unresolved closure contend on the session revision; if the extension wins, stale closure rereads or conflicts and cannot exhaust or terminalize against the superseded ceiling. | operative authority § Request, lines 7-10; admitted positive ceiling `orchestrator/brainstorming.py:1378-1403`; transcript dependence on admitted/current ceiling `orchestrator/brainstorming.py:3262-3382`; revisioned session writes `orchestrator/brainstorming.py:4841-4923`; atomic compare-and-set `orchestrator/kvstore.py:581-613` | touch one effective-ceiling fact and its shared projections; do-not-mutate the admitted limit, decrease capacity, use an additive retry-sensitive API body, launch work, add an arbitrary cap, let stale closure ignore an accepted extension, or mutate a terminal session |
| Continue | `POST /api/brainstorming/sessions/<id>/continue` accepts exactly `{"waiting_revision": <positive integer>}` and returns `{"ok": true, "session": session}`. `waiting_revision` is the session revision from the authenticated waiting projection and authorizes only that wait. Only an exact current waiting revision can win one atomic update: it raises the effective ceiling to `max(current maximum, rounds_used + 2)` and makes the same session runnable, so remaining `0/1/2+` adds `2/1/0`. A duplicate or stale request, including one delayed until a later wait, returns the public conflict without changing capacity or creating a process, session, or task; fresh action on repeated exhaustion supplies the new waiting revision. The existing `/start` operation does not bypass `waiting`; it remains the control for an ordinarily stopped, non-waiting session. | operative authority § Request, lines 8-10; existing public session revision `orchestrator/brainstorming_lifecycle.py:1873-1882,2785-2810`; atomic compare-and-set `orchestrator/brainstorming.py:4841-4923`; existing same-id start contract `orchestrator/brainstorming_lifecycle.py:2985-3050`; task-aware restart `orchestrator/service.py:4058-4200`; gated launch seam `orchestrator/brainstorming_lifecycle.py:1452-1545` | touch one revision-scoped session continuation operation and the current task-aware start seam; do-not-create a successor identity or operation store, top up from stale client arithmetic, mutate the admitted limit, relaunch twice, or reinterpret ordinary Start as Continue |
| Preservation and next work | Add rounds and Continue may change only the effective round ceiling, the waiting/running lifecycle fact, the session revision, and process metadata. Session id, admitted request, target authority, participants and provider-session references, accepted turns, transcript events and ballots, floor/external interventions, context, staffing/prompt authority, task links, and accumulated activity/accounting remain unchanged. The opening transcript continues to report the admitted limit, and each accepted ballot retains the capacity meaning it had when accepted; increasing later capacity cannot change already-rendered transcript entries. Continuation resumes at the next not-yet-accepted roster turn; it does not repeat the exhausted boundary's discussion or closure control. Accepted records are unique and append-only; only an unrecorded physical provider call retains inherited at-least-once recovery. | operative authority § Request, lines 7-10; request/config/history successor guards `orchestrator/brainstorming.py:2630-2700`; transcript rendering `orchestrator/brainstorming.py:3262-3382`; ordered-turn acceptance `orchestrator/brainstorming.py:2782-2848,5399-5445`; ballot/event acceptance `orchestrator/brainstorming.py:3019-3059,5508-5527`; activity/accounting projection `orchestrator/brainstorming_lifecycle.py:1703-1862` | touch the minimum successor and historical-capacity facts needed for the two controls; do-not-reset or copy a session, mutate its admitted request, clear an intervention, rewrite accepted history, duplicate an accepted charge, or claim physical exactly-once delivery |
| Public read, access, and errors | Existing authenticated list, detail, and view reads expose `status` and durable session `revision`; list/detail session projections expose `rounds_used`, `max_rounds`, `rounds_remaining`, and `exhausted`; the view's existing `round` object retains `current`, `completed`, and `maximum` and adds `remaining`, where `completed` is rounds used. Both new POST routes use the same pre-read session/project authorization and JSON envelopes as existing controls. Malformed bodies, a non-positive/non-integer `maximum`, or a missing/non-positive/non-integer `waiting_revision` return `400 invalid_brainstorming_request`; unknown id returns `404 unknown_brainstorming_session`; forbidden remains `403 forbidden`; stale waiting revision, non-waiting or terminal state, or a lifecycle race returns `409 brainstorming_continuation_conflict` without mutation; store/launch failure returns `503 brainstorming_unavailable` without inventing terminality. | operative authority § Request, lines 10-12; existing typed errors `orchestrator/brainstorming_lifecycle.py:50-57`; pre-read authorization `orchestrator/service.py:3868-3875`; current reads/routes `orchestrator/service.py:5432-5507,5631-5699`; projections `orchestrator/brainstorming_lifecycle.py:1865-1883,2441-2508,2674-2825` | touch additive projection fields, two authenticated POST branches, and one conflict token; do-not-add a task-only route, expose content before authorization, replace existing envelopes, or derive authoritative counts in the panel |
| Open owners and terminal compatibility | Exhaustion alone keeps a `waiting` session and every owner open with task result `null`, retaining the same task/session relations. Existing milestone/reviewed/deep waits close only on a later terminal outcome. A successful Stop of a directly ordered task is instead an explicit operator failure: its task becomes terminal failure and its owned waiting or resumed session becomes terminal unless another immutable terminal session outcome won first. No paid continuation starts under that terminal task, and accepted history and accounting remain available. Existing terminal sessions and tasks are byte-immutable; Add rounds and Continue conflict without mutation. Further work uses the existing create/order operations and receives new session/task ids; no lineage member or migration is added. | operative authority § Request, lines 7, 9, 11-12; adapter waits on nonterminal state `orchestrator/brainstorming_tasks.py:1277-1321`; direct task Stop/result `orchestrator/task_api.py:684-731,1385-1401`; task restart terminal guard `orchestrator/service.py:4058-4200`; milestone producer wait `orchestrator/driver.py:8794-8831`; immutable task result `orchestrator/tasks.py:1425-1439`; existing atomic session interruption `orchestrator/brainstorming.py:3116-3177,5585-5626` | touch recognition of `waiting` through existing waits and couple the existing direct task Stop outcome to its owned session; do-not-terminalize from exhaustion, admit a replacement during Continue, reopen old failures, add lineage, or weaken real failure handling |
| Panel contract | A waiting discussion visibly says it is waiting, distinguishes exhausted from manually extended capacity, and shows used/maximum/remaining rounds. It offers **Add rounds** and **Continue** only from the session view, disables an in-flight click, refreshes from the returned/public view, and preserves last-good/out-of-order polling behavior. Add rounds calls only the rounds route; Continue calls only the continue route with the displayed waiting revision. That revision is only a server-checked authorization precondition; no browser value decides durable capacity, status, identity, or idempotency. Task pages continue to reach the same session through **Open discussion**; after a successful task Stop that view is terminal evidence and offers neither continuation control. | operative authority § Request, line 10; current session renderer/controls `orchestrator/static/panel.html:1311-1402,1740-1842,1969-1987`; task-to-session action `orchestrator/static/panel.html:5459-5517`; polling authority `orchestrator/static/panel.html:1440-1483` | touch the existing session renderer and focused panel checks; do-not-add panel storage, mint a client-only operation identity, call `/start` for continuation, hide API errors, or copy controls onto a separate task/milestone path |
| Verification | Focused command: `python3 -m unittest orchestrator.tests.test_brainstorming_state orchestrator.tests.test_brainstorming_closure orchestrator.tests.test_session_repository_seal orchestrator.tests.test_brainstorming_api orchestrator.tests.test_brainstorming_visualization orchestrator.tests.test_brainstorming_tasks orchestrator.tests.test_brainstorming_slice_production orchestrator.tests.test_reviewed_task_api orchestrator.tests.test_deep_task_documentation orchestrator.tests.test_deep_task_implementation orchestrator.tests.test_task_api`. Add or update checks named `test_round_exhaustion_without_approval_waits_open`, `test_final_unready_pass_waits_open`, `test_continue_top_up_matrix_is_atomic_and_idempotent`, `test_delayed_continue_retry_cannot_cross_wait_boundaries`, `test_add_rounds_raises_absolute_maximum_without_starting`, `test_add_rounds_winning_closure_race_prevents_stale_exhaustion`, `test_round_extensions_preserve_rendered_transcript_history`, `test_continuation_survives_restart_without_repeating_boundary_work`, `test_api_only_continuation_handles_direct_and_task_owned_sessions`, `test_panel_uses_public_round_and_continue_controls`, `test_waiting_session_keeps_milestone_reviewed_and_deep_owners_open`, and `test_task_stop_at_waiting_session_closes_both_and_requires_successor`. Retained success, operational/protocol failure, stop, access, recovery, task-result, and suite-inventory checks remain required. Repository gates remain `python3 -m unittest orchestrator.tests.suite_checkpoint`, `python3 -m unittest orchestrator.tests.suite_extended`, and `python3 -m unittest orchestrator.tests.test_suite_inventory`; do not claim them unless run. | operative authority § Request, line 12; transcript dependency `orchestrator/brainstorming.py:3262-3382`; closure revision seams `orchestrator/brainstorming_coordination.py:2550-2703`; opposite exhaustion fixtures `orchestrator/tests/test_brainstorming_closure.py:832-876`, `orchestrator/tests/test_session_repository_seal.py:296-315`; API restart/terminal compatibility `orchestrator/tests/test_brainstorming_api.py:2200-2424`; direct task Stop `orchestrator/tests/test_task_api.py:1607-1696`; panel contract `orchestrator/tests/test_brainstorming_visualization.py:469-492`; official suite contract `orchestrator/README.md:565-586` | touch the named existing suites and only add focused cases at their owning seams; do-not-create a second test runtime, remove/weaken retained failure tests, or represent unrun broad gates as evidence |

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The immediate victim is the operator whose unresolved but healthy discussion is currently recorded as failure. Task and milestone callers inherit that false terminal result, losing a resumable decision thread and potentially forcing duplicate sessions, tasks, calls, and review work. Conversely, after the operator explicitly stops an owning task, leaving its discussion actionable can spend more calls under a terminal owner or expose controls that cannot succeed. Accepted history is recoverable only by preserving it before terminalization; source changes are reversible, but spent calls and duplicated human/model work are not. | operative authority § Request, lines 7-12; current document-target failure `orchestrator/brainstorming_coordination.py:2550-2595,2672-2703`; current repository failure `orchestrator/brainstorming.py:2934-2972`; task propagation `orchestrator/brainstorming_tasks.py:1304-1321`; direct task Stop/session pause `orchestrator/task_api.py:684-731,1385-1401` |
| machinery | Extend the existing session status/successor validation, coordination boundary, lifecycle process/registry operations, shared projections, authenticated service dispatcher, panel session view, and existing caller adapters. Preserve the admitted ceiling and add one effective-ceiling fact within the existing session record. Add two session-scoped HTTP controls and one typed conflict token; add no runtime module, store, daemon, dependency, or product adapter. Each change serves the authorised wait, extension, continuation, visibility, history-preservation, or owner-preservation outcome. | existing owners `orchestrator/brainstorming.py:2437-2627,3262-3382,4841-4923`; `orchestrator/brainstorming_lifecycle.py:1865-1883,2985-3050,3650-3861`; `orchestrator/service.py:5432-5507,5631-5699`; `orchestrator/static/panel.html:1740-1842` |
| consumers_touched | Verified direct consumers are standalone session clients and the panel; direct Brainstorming tasks through `DirectTaskHost`; milestone-selected Brainstorming producers and rethink waits; reviewed tasks; and deep parents waiting on reviewed children. The four granted product roots expose no Brainstorming-continuation client or alternate session engine in their code search and remain untouched. | API/panel `orchestrator/service.py:5432-5507,5631-5699`; direct host `orchestrator/task_api.py:803-895,1349-1445`; milestone/reviewed wait `orchestrator/driver.py:330-364,519-535,8794-8831`; deep wait `orchestrator/task_api.py:1014-1084` |
| cheaper_alternative | Reusing Start alone is insufficient: it has no atomic top-up rule, cannot distinguish an exhausted boundary from an ordinary stop, and current closure turns exhaustion into immutable failure. Mutating the admitted ceiling is also insufficient because the transcript currently renders historical meaning from it. An empty Continue cannot distinguish a delayed retry from fresh action after repeated exhaustion. The cheapest sufficient option is one new nonterminal session status, one monotonic effective-ceiling fact, one same-id Continue guarded by the already-public session revision, additive projections, caller recognition through their existing nonterminal waits, and reuse of the existing task Stop plus atomic session-interruption seams to prevent a terminal-task/open-session split; no operation store, route, or key is needed. | current Start `orchestrator/brainstorming_lifecycle.py:2985-3050`; transcript dependency `orchestrator/brainstorming.py:3262-3382`; current public revision `orchestrator/brainstorming_lifecycle.py:1873-1882,2785-2810`; current terminal requirements `orchestrator/brainstorming.py:2317-2368,2934-2972,3062-3113`; existing caller nonterminal seam `orchestrator/brainstorming_tasks.py:1304-1309`; task Stop/session interruption `orchestrator/task_api.py:684-731`, `orchestrator/brainstorming.py:3116-3177` |
| cost | Build/review cost spans the central Brainstorming state, lifecycle, HTTP, panel, and caller integration plus focused restart/race matrices. Migration and deployment cost are zero: old terminal records stay valid and unchanged, and the project remains Python standard-library only. Operational cost is only operator-authorised extra rounds; maintenance stays within existing owners. Omission keeps false failures and makes later recovery duplicate paid work. | standard environment `orchestrator/README.md:3-9,33-46`; compatibility need `authority.md` § Request, lines 9-12; existing suite tiers `orchestrator/README.md:565-586` |
| threat_model | Untrusted inputs introduced here are an authenticated client's session id, JSON body, absolute requested maximum, waiting revision, and repeated/concurrent Add or Continue requests. The panel's body is untrusted at the same HTTP boundary as any external client's. Existing identity/project access must precede state reads; exact shape and positive-integer validation guard the body; the current durable revision guards races and prevents stale authorization from crossing wait boundaries. The service registry, task relations, run state, and persisted roster/context are trusted orchestrator data and receive no new defensive wrapper. Existing model output remains untrusted but enters through unchanged turn/closure validators. | body boundary `orchestrator/service.py:5890-5919`; access boundary `orchestrator/service.py:3868-3875`; positive-integer precedent `orchestrator/brainstorming.py:1378-1403`; CAS `orchestrator/kvstore.py:581-613`; model envelope boundary `orchestrator/brainstorming_execution.py:12-33,249-274` |
| pinned_facts | The eight hard rows pin the waiting outcome, exact round arithmetic and monotonic Add contract, same-id Continue contract, preservation/next-work boundary, public schemas/errors/access, owner and terminal compatibility, panel behavior, and executable verification. Any deviation in those values is a bug; all other internal names and call ordering remain implementation choices. | this note, Pinned-Facts Table; governing allocation `authority.md` § Request, lines 5-12 |
| verification | The focused command exercises state/closure and repository boundaries, public API and panel use, same-id restart, task/milestone/reviewed/deep ownership, Stop at the waiting boundary, and retained success/failure behavior. The twelve named checks pin the new outcomes, including transcript stability, the extension-versus-closure race, and consistent task/session terminality; existing opposite exhaustion tests must be rewritten rather than merely supplemented. Checkpoint, extended, and inventory remain separate repository evidence and must be reported honestly. | this note, Verification pinned fact; current opposite tests `orchestrator/tests/test_brainstorming_closure.py:832-876`, `orchestrator/tests/test_session_repository_seal.py:296-315`; suite partition `orchestrator/tests/suite_manifest.py:11-65,108-128` |
| enforceability | Existing CAS, exact successor assertions, atomic session interruption, process registry/gated launch, pre-read authorization, task-result immutability, caller waits, and panel polling can enforce the claimed levels. The confirmed design gaps are that current state permits no waiting status or round-limit successor and that direct task Stop can record task failure after only pausing its session. Implementation must close both before the waiting and continuation guarantees are claimed. The Enforceability Gate below maps each invariant to its enforcing seam and test. | current exhaustion gap `orchestrator/brainstorming.py:32-64,2317-2368,2630-2655,2934-2972`; task Stop/session pause gap `orchestrator/task_api.py:684-731,1385-1401`; available CAS/interruption `orchestrator/brainstorming.py:3116-3177,4841-4923,5585-5626`; owner enforcement `orchestrator/tasks.py:1425-1439`; process seam `orchestrator/brainstorming_lifecycle.py:1452-1545` |

### Enforceability Gate

| invariant | enforcing mechanism | implementation gate |
|---|---|---|
| Exhaustion is an atomic nonterminal boundary | Existing combined turn/ballot acceptance and revision CAS at `orchestrator/brainstorming.py:4841-4923,5399-5527,5560-5596`. **Design gap:** current validators/successors instead require terminal failure at `orchestrator/brainstorming.py:2317-2368,2934-2972,3062-3113`. | Both document and repository boundary tests must observe the accepted final pass and optional ballot together with `waiting`, no result, and no later provider work. |
| Add rounds is monotonic, non-starting, retry-safe, and ordered with closure | Exact request validation plus session compare-and-set at `orchestrator/brainstorming.py:1378-1403,4841-4923`; closure acceptance uses the same revisioned session at `orchestrator/brainstorming_coordination.py:2550-2703`; the registry/process authority is separate at `orchestrator/brainstorming_lifecycle.py:1538-1609`. **Design gap:** no accepted successor currently permits only an effective ceiling to increase. | Equal/smaller/repeated/racing absolute maxima produce one monotonic ceiling, preserve every other state field, and never create or signal a process. In the declared race, an accepted extension prevents a stale unresolved closure from exhausting or terminalizing against the old ceiling; the closure rereads or conflicts. |
| Continue applies the 0/1/2+ rule once and resumes the same identity | The already-public session revision identifies the operator-authorized wait; session CAS at `orchestrator/kvstore.py:581-613` admits only that current revision. Existing gated same-id start at `orchestrator/brainstorming_lifecycle.py:1452-1545,2985-3050` and task-aware recovery at `orchestrator/service.py:4058-4200` supply the launch path. **Design gap:** these seams are not yet one revision-scoped waiting-only public operation. | The matrix compares exact state before/after, races duplicate calls, injects restart/launch failure, and proves one session/task id and at least two remaining rounds at the accepted continuation revision. A retry of that request during running or after the next exhaustion conflicts without any state or process change; only the later wait's revision authorizes another continuation. |
| Accepted history, work, and accounting are never rewritten or duplicated by continuation | Ordered successor assertions at `orchestrator/brainstorming.py:2630-2700,2782-2848,3019-3059`; transcript rendering at `orchestrator/brainstorming.py:3262-3382`; activity projection at `orchestrator/brainstorming_lifecycle.py:1703-1862`; durable attempt recovery at `orchestrator/brainstorming.py:4458-4835`. | Capture the rendered transcript before Add rounds and Continue and prove its existing entries remain byte-stable, including the opening limit and an exhausted ballot's capacity meaning. Resume after both ballot and no-proposal exhaustion; compare transcript events, turn indices, interventions, provider-session refs, activity ids, usage, and cost before/after the first new accepted turn. Physical unrecorded-call replay is not asserted away. |
| Every caller stays open while the session waits unless explicitly stopped | Adapter completion only on terminal state at `orchestrator/brainstorming_tasks.py:1277-1321`; reviewed/milestone wait at `orchestrator/driver.py:330-364,519-535,8794-8831`; deep-child wait at `orchestrator/task_api.py:1014-1084`. Existing task Stop and atomic session interruption supply the explicit abandonment path at `orchestrator/task_api.py:684-731,1385-1401` and `orchestrator/brainstorming.py:3116-3177,5585-5626`. | Real direct, milestone, reviewed, and deep fixtures inspect `result: null`, unchanged ids/relations, and no failure event before continuing the same session to a genuine terminal result. A direct-task fixture stops at `waiting` and proves task failure, terminal session state, immutable old controls, and new ids on re-entry. |
| Public controls are authorized and the panel is a client | Pre-read authorization at `orchestrator/service.py:3868-3875`, shared route envelopes at `orchestrator/service.py:5432-5507,5631-5699`, and request-sequenced polling at `orchestrator/static/panel.html:1440-1483`. | API-only tests cover admin/project/forbidden/unknown/malformed/conflict/unavailable outcomes for direct and attached sessions; panel tests assert the two public requests and no local authoritative mutation. |
| Terminal history remains terminal | Session transitions have no terminal successor at `orchestrator/brainstorming.py:59-64`; task results mutate only null-to-terminal at `orchestrator/tasks.py:1425-1439`; create/admit allocates fresh ids at `orchestrator/brainstorming_lifecycle.py:335-346` and `orchestrator/tasks.py:1408-1422`. | Historical exhaustion failures, ordinary success/failure, and the terminal task/session outcomes produced by task Stop remain byte-identical after both controls; an explicitly new order receives distinct identities. |

No existing mechanism can promise provider-side exactly-once calls or perfectly
current browser display. Those remain best-effort and eventual respectively;
the strict contract stops at durable accepted session/task state.
