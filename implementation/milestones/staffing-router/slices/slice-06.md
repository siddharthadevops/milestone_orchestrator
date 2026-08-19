# Slice 06 — Brainstorming cutover

## Register 1 — INTENT (lay language)

### What this slice builds

Brainstorming stops choosing the intelligence for its own automatic
participants. A new discussion inherits one staffing session from its owner,
and every agent call asks that live session immediately before the call. A
milestone discussion uses the milestone run's session. A standalone discussion
may name a session the caller can already access; if it does not, the normal
default staffing answers.

The discussion still owns its people, speaking order, rounds, agreement rules,
manual participation and recovery. The staffing router owns only which agent,
model and effort fill each automatic seat. The ordinary milestone discussion
therefore has three staffed seats in roster order: Initial Position, Contrary
Position and Dante. A failure-classification call uses the separate classifier
seat.

Changing the inherited staffing session's selection or its referenced document
affects the next agent call, including a later turn, closure call or agreed
production call. A prior provider conversation cannot freeze an older choice.
The activity shown for a call says what actually ran and whether default
staffing answered.

Explicit static Brainstorming pins admitted before this cutover keep their
binding. They are read, resumed and completed without rewriting their stored
records. Profile-backed attached work is not a pin: it follows the run's
already-bound staffing session.

### Ownership and boundary

Owned here: the Brainstorming creation, restart, participant-dispatch,
production-effect and failure-classification seams; inheritance of a run's or
standalone caller's staffing session; live participant projection; additive
staffing evidence on existing activity; compatibility for already-admitted
Brainstorming records; and focused tests.

Not owned here: the router or session-store contract; review rotation,
advancement or sealing; the general Agent-call host; work-area alignment;
planner material selection; the panel's document/session controls; a new
Brainstorming roster, lifecycle, permission rule, store, ledger or recovery
path. Manual external participants make no agent call and therefore ask no
staffing question.

The general standalone-task request acquires its owner-session field in the
standalone-task slice. This slice makes the Brainstorming adapter consume that
context when supplied and use default staffing when absent; it does not pull
the Agent-call or git-alignment cutovers forward.

### Guarantee posture

- **Strict — call selection.** Every automatic call of a new router-backed
  discussion uses the current router answer for its seat and round. A surfaced
  staffing condition prevents that provider call; it is not replaced by roster
  rotation, a participant pin, a model profile or a runtime default.
- **Strict — live change.** The last completed session or document write governs
  the next call. A call already made is unchanged, and a stopped discussion
  restarted later keeps the same live session reference.
- **Strict — compatibility.** A stored pre-cutover explicit static binding keeps
  that binding. A profile-backed attached record follows its run's session
  without rewriting either record. No stored record is migrated merely because
  this cutover ships.
- **Optimistic — concurrent configuration.** Session and document saves retain
  their existing atomic, last-completed-write behaviour; there is no version,
  acknowledgement or call barrier.
- **Best-effort — staffing evidence and projections.** Staffing fields on
  activity, fallback annotations, roster views and order-time staffing
  snapshots are bookkeeping; existing lifecycle uses of the activity itself do
  not change. When an activity entry is written it identifies that call
  accurately, but no new survival, notification or reconciliation guarantee is
  added.
- **Eventual — none.** Nothing is replicated, queued or reconciled.

### Dependencies and consumers

This slice depends on the document conversion, the session resolver, the run's
single session binding, and the existing staffing API/access checks. It also
depends on Brainstorming's present per-call resolver hook, durable round facts,
activity entries and restart path. It changes what those seams read, not the
discussion or router state machines.

Direct consumers are milestone-attached design discussions and guarantee
calibration, milestone and standalone Brainstorming production tasks,
standalone Brainstorming sessions, their explicit restart path, and their
read-only participant view.

### Acceptance

The slice is accepted when focused tests show that:

- each automatic seat and the optional classifier asks the router with its
  correct role, roster position and discussion round immediately before the
  corresponding physical call;
- a session or document edit between two calls changes the second call, while
  participant pins, profile edits, roster rotation and order-time snapshots do
  not;
- milestone-attached discussions and production tasks inherit the run's one
  session; standalone discussions honour an accessible supplied session and
  use visible default staffing when it is absent or later unreadable;
- same-family Brainstorming assignments are allowed unless the selected
  document itself declares a split, and when either surfaced condition is met
  at an automatic dispatch it stops that call before a provider or fabricated
  activity;
- activity for each physical discussion, closure, classifier and production
  call identifies the family, model and effort that ran, and records the
  default-document fallback when applicable;
- explicit restart keeps the same live staffing reference; and
- representative pre-cutover static sessions and tasks resume with their pins,
  while an attached profile-backed record follows its run's session; neither
  record is rewritten.

The implementation is expected to exceed the approximately 500 changed-line
aim because the same call contract must be pinned across discussion, automatic
narration, closure, classification and production; attached, standalone and
restart entry paths; the static-pin compatibility boundary; and activity-schema
fixtures. The runtime design remains one inherited reference and an extension
of existing resolver/view/evidence seams, not a new service or state machine;
most of the excess is the required integration matrix and its tests.

### Risks and non-goals

- Reusing a creation-time roster answer at later calls would silently restore a
  snapshot. Tests change both the session and document between calls.
- Treating a provider retry count as a discussion round would escalate the
  wrong seat. Tests cover retries, closure and production after a completed
  round.
- Resolving the optional classifier before its LLM stage is actually needed
  could fail a discussion for a call that never happens. Tests cover the
  deterministic no-classifier path.
- A new record accidentally classified as legacy could keep a static pin;
  treating an attached profile-backed record as a pin could bypass its run's
  session; rewriting either legacy shape could break a resumable discussion.
- No panel, generic task-order, Agent-call, git-sync, planner-material, review
  cycle or granted read-only-root work is included.

### Reuse Posture

The affected parties are operators, calling products and discussion
participants. Without the cutover, a Brainstorming turn can still run at a
family, model or effort chosen by a separate roster/profile rule; the quality
and cost harm is visible per call, reversible on the next call, and repeated
for every discussion action. The reviewed slice is the independent authority.

Checked and reused: the live staffing resolver and run binding; Brainstorming's
existing per-dispatch resolver and fresh-call behaviour; its durable roster
position and round; the Initial Position production seam; classifier callback;
activity/accounting record; service identity and staffing-session access; and
the existing distinction between static and attached profile-backed records.
The cheapest sufficient option is to carry one session reference through those
seams, add one presence marker so a new default-backed record cannot be mistaken
for an old field-absent static record, resolve at the existing call boundary,
and add one optional activity field. The marker is the only new machinery: the
existing create, restart, view and dispatch paths consume it. Documentation
alone cannot change the call; a second roster, snapshot, cache, store, retry,
ledger or migration would duplicate authority and cost more to build, operate
and review. Omission repeats misstaffing; the chosen change is locally
reversible and leaves old records intact.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Owner session | A new milestone-attached Brainstorming session uses the run's one `staffing_session`. `POST /api/brainstorming/sessions` accepts one optional top-level `staffing_session`; when supplied it must be a session the caller may already access, with existing `404 unknown_staffing_session` and `403 forbidden` classifications. When absent, calls resolve as the `default` document at `medium` with the consumer's configured families and expose the fallback on their activity. The durable Brainstorming record distinguishes that new absent-reference default from a pre-cutover field-absent record, so restart preserves both contracts. The reference is inherited context, never a copied document or a second staffing value. | `implementation/milestones/staffing-router/skeleton.md:225-230,294,321-322`; run binding `orchestrator/driver.py:628-665`; access `orchestrator/service.py:2140-2172,2190-2202`; record/restart seam `orchestrator/brainstorming_lifecycle.py:153-206,1622-1639,2293-2340`; create seam `orchestrator/service.py:4794-4835` | touch Brainstorming create/attach/restart and the existing service body/record compatibly; do-not copy a staffing document, create another session implicitly, add a permission rung, expose seats as staffing input, or let new-default and old-static records become indistinguishable |
| Role, seat and round | Every automatic discussion-turn, closure and production-effect provider call resolves `brainstorm` at the participant's 1-based position in the persisted roster and at that action's discussion round. The standard milestone roster is Initial Position = 1, Contrary Position = 2, Dante = 3. The optional LLM failure classifier resolves `classify`, index 1, round 1, only when its physical classifier call is made. A manual external participant resolves nothing. | `implementation/milestones/staffing-router/skeleton.md:215-224,294,310`; roster/round source `orchestrator/brainstorming_coordination.py:1809-1867`; production lead `orchestrator/brainstorming_execution.py:561-593`; classifier seam `orchestrator/brainstorming_lifecycle.py:2551-2583`; narrator/manual boundary `orchestrator/brainstorming_lifecycle.py:2693-2802` | touch the existing current-resolver inputs and classifier resolver; do-not add roles, renumber the roster, use provider-attempt as round, or resolve a call that is not dispatched |
| New authority and legacy boundary | For every new router-backed session, participant `model_family`/`model`/`effort` pins, family rotation, model profiles, runtime defaults and task `resolved_staffing` do not decide a call; legacy-shaped pin fields may remain transitionally accepted but are inert. A pre-cutover explicit `static` binding keeps its pins. A pre-cutover attached `current_profile` record is not a pin exception: its next call uses the owning run's bound session, without migrating or rewriting either record. A damaged model-profile catalogue cannot gate that call; profile and sidecar files remain untouched. | run amendment A2; `implementation/milestones/staffing-router/skeleton.md:118-136,234-242,294,317-318,324`; current selectors `orchestrator/brainstorming_lifecycle.py:497-744,1196-1206`; static task binding `orchestrator/brainstorming_tasks.py:160-192`; profile-backed seams being retired `orchestrator/driver.py:756-811,8807-8847` | touch the authority discriminator and new-session selection source; do-not derive an override, migrate records, delete legacy readers, reject the transitional panel solely for sending an inert pin, or leave a second selector for a new call |
| Live dispatch and conditions | Each physical automatic call resolves once at the existing pre-provider boundary. The last completed session/document edit governs it; restart and production resolve again. `staffing_unavailable` and `distinct_families_unsatisfiable` remain the only surfaced staffing conditions and prevent the affected provider call before activity is created. Unreadable session/document input instead answers through the mandatory default-document fallback. | `implementation/milestones/staffing-router/skeleton.md:33-40,100-117,294,314-316`; resolver `orchestrator/staffing.py:2001-2044`; pre-provider hook `orchestrator/brainstorming_execution.py:451-487`; live seam test `orchestrator/tests/test_brainstorming_execution.py:515-604` | touch what the existing hook reads and its typed refusal mapping; do-not cache across calls, retry a surfaced condition, manufacture activity without a provider call, or add a third condition |
| Call evidence | Every Brainstorming activity created from a physical `discussion_turn`, `closure`, `classifier` or `production_effect` call carries the actual `model_family`, `model` and `effort`; router fallback adds `staffing_fallback: "default_document"`. A synthetic recovery entry with no evidenced provider call keeps null staffing rather than inventing it. These fields and the participant view are best-effort bookkeeping and never dispatch input. Existing activity without the new optional field remains readable. | `implementation/milestones/staffing-router/skeleton.md:317`; fallback token `orchestrator/staffing.py:1587-1589`; participant activity `orchestrator/brainstorming_execution.py:380-448`; classifier activity `orchestrator/brainstorming_lifecycle.py:2353-2421`; synthetic no-call entry `orchestrator/brainstorming_tasks.py:973-1015`; activity validator `orchestrator/brainstorming.py:962-1124` | touch the activity schema additively and the live view source; do-not add a staffing ledger/event stream, require the optional field on old activity, invent staffing for a no-call entry, or make acceptance depend on the projection |
| Slice boundary | Review-cycle reads and sealing, the router/session stores and routes, the generic `agent_call` host, git-sync, planner material, panel controls and model-profile/acts retirement remain outside this slice. The accepted third non-dispatch review-family read is unchanged. | `implementation/milestones/staffing-router/skeleton.md:294-301,319,322-325`; third read `orchestrator/staffing.py:2048-2106`; prior boundary `implementation/milestones/staffing-router/slices/slice-04.md:257-260,280` | touch only Brainstorming consumers, their create/restart/view adapter, activity schema and focused tests; do-not alter review law, router answers, panel controls, generic task hosting, alignment or any read-only root |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_staffing_brainstorming_cutover orchestrator.tests.test_brainstorming_execution orchestrator.tests.test_brainstorming_tasks orchestrator.tests.test_brainstorming_milestone_adapter orchestrator.tests.test_brainstorming_api orchestrator.tests.test_staffing_sessions`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Every automatic Brainstorming call asks the pinned seat | new `test_every_brainstorming_call_asks_the_router` in `orchestrator/tests/test_staffing_brainstorming_cutover.py` | Captured requests for three discussion seats, closure proposal/votes, Initial Position production and an actual LLM classifier match the exact role/index/round table; a manual external response and a deterministic failure classification make no request. | strict |
| Staffing is live and exclusive | new `test_live_session_and_document_edits_replace_all_old_selectors` | Two calls around a session edit and two around a document save run the new answers; changing participant pins, profile selection, runtime defaults, rotation order and `resolved_staffing` changes none; each call starts fresh rather than continuing a provider binding that would freeze staffing. | strict |
| Owners are inherited on both entry paths | new `test_attached_and_standalone_sessions_inherit_one_staffing_session` | Attached design/calibration/production sessions use the run's exact id; standalone create accepts an accessible id, returns 404/403 for unknown/foreign ids, and omission uses `default@medium` without creating a second staffing session. Restart retains the same reference, and a new omitted reference remains distinguishable from an old field-absent static record. | strict |
| Router law replaces roster law | new `test_router_assignment_can_collapse_brainstorming_seats` | A new multi-family session whose router seats share one family dispatches when `brainstorm` declares no split, regardless of legacy pins/rotation; after creation, live edits that make its document declare an unsatisfied split or offer no available family surface the exact token at the affected call, with no provider invocation or activity. | strict |
| Activity records the call, not the creation roster | new `test_activity_records_resolved_staffing_and_fallback` | Physical participant, closure, classifier and production events carry the family/model/effort used; an absent or later unreadable staffing session/document dispatches on the default and adds the exact fallback field; old events without it still validate, and a synthetic no-call recovery entry retains null staffing. | best-effort evidence, strict when written |
| The pre-cutover boundary is exact | new `test_pre_cutover_brainstorming_bindings_resume_without_rewrite` | Representative stored `static` sessions and tasks restart and complete on their pins; an attached `current_profile` record instead resolves through its owning run's session; neither stored record changes, and a newly admitted task selects no legacy authority. | strict |
| No adjacent consumer moved | existing Brainstorming and staffing-session suites in the focused command | Existing discussion, recovery, production-effect, API access and session-resolution contracts pass; the accepted review-family reader and router answer shape are unchanged. | strict |

The repository closure gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-524`; `implementation/milestones/staffing-router/skeleton.md:325`).

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These are the slice-scoped remainder. Enforceability is answered again for the
facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | Verified direct consumers: the driver's attached design/calibration and production launch paths; the milestone adapter's fixed three-seat roster; the Brainstorming task adapter's admission, start, restart and agreed production effect; the lifecycle's standalone create, child restart, participant bindings, classifier, automatic narrator and live participant view; the execution seam immediately before a provider call; the service's standalone create/restart/view handlers; and the activity validator. The router, review cycle, generic Agent-call host, git-sync, planner and panel are not touched. | `orchestrator/driver.py:4921-4937,5207-5235,5433-5463,5501-5516,5565-5601`; `orchestrator/brainstorming_milestone.py:320-370`; `orchestrator/brainstorming_tasks.py:93-157,450-563,838-900,1207-1229`; `orchestrator/brainstorming_lifecycle.py:1402-1613,2293-2340,2443-2626,2693-2802`; `orchestrator/brainstorming_execution.py:35-101,451-487`; `orchestrator/service.py:4008-4140,4659-4730,4794-4835`; `orchestrator/brainstorming.py:962-1124` |
| pinned_facts | One inherited session reference and the optional standalone `staffing_session` field; exact `brainstorm`/roster-position/discussion-round and `classify 1`/round-1 requests; live resolution at every physical call; only the two surfaced conditions; default fallback and its exact activity field; retirement of new-session pins/rotation/profiles/snapshots; preservation only of explicit pre-cutover static pins; attached profile-backed work using its run session without rewrite; and the explicit adjacent-slice boundary. | run amendment A2; `implementation/milestones/staffing-router/skeleton.md:118-136,215-230,234-242,294-301,310,314-325`; `orchestrator/staffing.py:1582-1589,2001-2044`; `orchestrator/brainstorming_coordination.py:1809-1867` |
| verification | The seven-row Verification Contract pins every automatic call's captured router request, live edits and selector exclusion, attached/standalone inheritance and access, same-family collapse versus an explicit split, exact activity/fallback evidence, the static-pin versus attached-profile compatibility boundary, and unchanged adjacent suites. The existing fresh-dispatch and static-binding tests are reused as seam and compatibility evidence; closure keeps the official full suite. | this note, Verification Contract; `orchestrator/tests/test_brainstorming_execution.py:515-604`; `orchestrator/tests/test_brainstorming_tasks.py:201-267,310-418`; `orchestrator/tests/test_brainstorming_milestone_adapter.py:929-1005`; `orchestrator/README.md:522-524` |
| reuse_posture | Affected parties are the owner and participants of every new discussion; omission repeats visible, per-call and next-call-reversible quality/cost misstaffing. Reused: run/session authority, the existing current-resolver/fresh-call hook, durable roster position and round, production and classifier callbacks, activity/accounting, restart attachment, API identity/access and the static-versus-attached authority distinction. Cheapest sufficient is one inherited reference, one additive binding-presence marker consumed by existing create/restart/view/dispatch paths, one resolver adapter and one optional activity field. No new store, roster, cache, ACL, daemon, retry, ledger, migration or route family remains to operate; lifecycle cost is one live read per automatic call and one legacy-readable record field, weighed against repeated misstaffing and a locally reversible record addition. | `implementation/milestones/staffing-router/skeleton.md:258-283,294,316-318,321-324`; `orchestrator/brainstorming_execution.py:35-101,451-487`; `orchestrator/brainstorming_coordination.py:1809-1867`; `orchestrator/service.py:2140-2202`; `orchestrator/brainstorming_lifecycle.py:153-206,1196-1206,1622-1639,2293-2340` |
| enforceability | The run-state key, existing Brainstorming service record/restart path plus one additive binding-presence marker, and session-access reader enforce inheritance, retention, default-versus-legacy distinction and authorization; the coordinator's persisted roster/round plus the pre-provider current-resolver hook enforce request identity and timing; atomic document/session writes plus `staffing.resolve` enforce last-completed live answers, fallback and the two tokens; fresh-call execution prevents provider-session freeze; the existing activity append/validator can enforce actual call evidence with one optional fallback field; and the existing authority lookup can preserve static pins while routing attached profile-backed records through their run. Focused tests capture requests, provider invocations, record bytes and activity. No survival, notification, cache-coherence, eventual-delivery or projection-freshness guarantee is asserted. | `orchestrator/driver.py:628-665`; `orchestrator/service.py:2140-2202,3840-4005`; `orchestrator/brainstorming_lifecycle.py:153-206,1196-1206,1622-1639,2293-2340`; `orchestrator/brainstorming_coordination.py:1809-1867`; `orchestrator/brainstorming_execution.py:56-101,451-487,683-719`; `orchestrator/staffing.py:718-760,1512-1549,1975-2044`; `orchestrator/brainstorming.py:962-1124` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| An attached discussion uses the run's one session; a standalone supplied session is retained and accessible; a new omitted reference is not legacy | The existing Brainstorming service record and restart path in `orchestrator/brainstorming_lifecycle.py:153-206,1622-1639,2293-2340` can carry the one additive distinction beside the bound run key in `orchestrator/driver.py:628-665`; stored-session authorization is already `orchestrator/service.py:2140-2202`. | Capture the id at every attached create/restart; exercise allowed, unknown and foreign standalone ids; stop and restart explicit and omitted new bindings; load an old field-absent record as static. |
| Each automatic call uses the correct seat and round | The selected participant and computed round in `orchestrator/brainstorming_coordination.py:1809-1867`, production lead in `orchestrator/brainstorming_execution.py:561-593`, narrator/manual boundary in `orchestrator/brainstorming_lifecycle.py:2693-2802`, and the pre-provider resolver hook in `orchestrator/brainstorming_execution.py:451-487`. | Capture the router request beside each provider invocation across turns, closure, classifier and production. |
| A completed edit reaches the next call and an unreadable input falls back | Atomic document/session writes in `orchestrator/staffing.py:718-760,1512-1549`, one `_effective` read and answer per `orchestrator/staffing.py:1975-2044`, and fresh-call execution in `orchestrator/brainstorming_execution.py:683-719`. | Race complete writes, edit between calls, break each input after creation, and assert the next provider identity and fallback evidence. |
| A surfaced condition invokes no provider and creates no activity | Resolution runs before provider start in `orchestrator/brainstorming_execution.py:451-487`; the resolver's only condition tokens are in `orchestrator/staffing.py:1582-1613,2028-2033`. | Count provider calls and activity before and after each condition. |
| New selectors are exclusive, static pins survive, and attached profiles yield | Existing record/task authority discrimination in `orchestrator/brainstorming_lifecycle.py:1196-1206` and `orchestrator/brainstorming_tasks.py:160-192`, plus the run-attachment lookup in `orchestrator/service.py:3840-4005`. | Mutate every retired selector for a new session; restart a byte snapshot of a static binding; attach a profile-backed snapshot to a run and assert its session answer without rewriting it. |
| Physical-call activity names what ran and old activity remains readable | Existing call-time event construction and append in `orchestrator/brainstorming_execution.py:380-448`, the explicit no-call recovery shape in `orchestrator/brainstorming_tasks.py:973-1015`, and validation in `orchestrator/brainstorming.py:962-1124`. | Compare provider metadata to stored events; validate fixtures with and without `staffing_fallback`, plus a synthetic no-call entry with null staffing. |

There is deliberately no enforcement row for session survival, notification,
history, cache coherence, reconciliation, projection delivery or eventual
convergence: this slice asserts none of them.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's slice-6, live-resolution, marker,
  Brainstorming-session and compatibility boundaries. Accepted amendment B1 is
  inherited as a no-touch dependency: its third read remains review-cycle law.
- **Revise:** only the still-live Brainstorming selector identified by slice 4:
  new sessions use the router while the existing per-call, lifecycle, restart
  and evidence forms remain.
- **Reject:** `_drafts` and other Brainstorming planning material as authority;
  any new roster/lifecycle, session copy, snapshot, cache, permission, retry,
  ledger, migration or adjacent consumer cutover.

Authority: `implementation/milestones/staffing-router/skeleton.md:234-256,294-301,314-325`;
accepted amendment B1; current deferred boundary
`implementation/milestones/staffing-router/slices/slice-04.md:257-260,280`.
