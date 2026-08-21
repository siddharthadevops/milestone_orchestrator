# Slice 04 — Milestone driver cutover and run binding

## Register 1 — INTENT (lay language)

### What this slice builds

Slices 2 and 3 built the staffing document, the session and the resolver, and
deliberately left them inert: nothing dispatches through them. This slice is the
first cutover. After it, **every worker call the milestone driver makes takes its
agent family, its model and its effort from the run's staffing session** — the
skeleton draft, the slice-note draft, the implementation, the fixer, the failure
classifier and the debt rater, the fixer's consultation, every review round and
every delta review. The model profile, the per-run acts sidecar and the config's
own act table stop deciding any of them.

For that to work a run needs a session, so this slice also **binds one**. A run
opened from now on names a staffing document and a rigor at launch, and the
orchestrator opens exactly one session for it and remembers its id. A run that
was already running when this slice landed gets one the first time it resumes,
derived by the rule the operator fixed in amendment A2: the session points at
the document named by the profile the run had selected, at the rigor it had
selected, or at the default document when no document carries that name.
Nothing else is carried over — the old per-run act literals are not copied into
the session, the document's own numbers apply from the next call, the marker
shows what actually ran, and the operator edits the session to change it.
Resume is never failed or blocked for compatibility, and no profile file or act
sidecar is written, edited or deleted by any of this.

Two things about review change shape. Which families review a piece of work
stops coming from the run's configured family order and starts coming from the
**review seats the document assigns** — the cycle walks those seats in index
order, and a piece of work is clean when each assigned seat's family has given
it a clean look on the current bytes. And because the operator can declare that
review must be split across different families, the driver checks before each
review dispatch that the families available can still honour that split.

Almost nothing can stop a dispatch any more. A session or document that cannot
be read no longer fails the run: the call resolves on the default document and
the in-flight marker says it did. Exactly two situations still stop a call — no
agent family available at all, and a split-family review that cannot be split —
and each stops the run the ordinary visible way, carrying its own name.

What this slice does not do: it does not touch how the milestone's Brainstorming
discussions are staffed (slice 6), standalone tasks or work-area alignment
(slice 7), the panel's document editor and per-run session controls (slice 8),
or the planner's material proposal (slice 9). The old profile and acts screens
stay where they are; for a cut-over run they simply decide nothing.

### Ownership and boundary

Owned here: the run's session binding and the launch input that opens it; the
A2 resume derivation; the per-dispatch resolution of every driver-made worker
call with its role, seat and round; the review cycle keyed to the document's
review seats and the pre-dispatch split-family check; the fixer's consultation
command line; the retirement of the model profile, the acts sidecar, the config
act table and the loud dispatch failure as *dispatch inputs* for a run with a
catalogue home; the fallback note on the in-flight marker; the read-only
document list the launch form needs; and focused tests.

Not owned here: any Brainstorming seat, standalone order, git alignment, panel
document editor or session control, planner material, or `resolved_staffing`
change. No session lifecycle, expiry, ledger, snapshot or version. No new
permission system. No change to what a review round means, to convergence, to
the round cap, to the seal predicate's shape, or to any rule about which
findings are raised — only to where the reviewing seat's family comes from.

### Guarantee posture

- **Strict — one authority.** For a run with a catalogue home, every worker call
  the driver makes resolves through the run's session. No model profile, act
  sidecar, `families_order[0]` or config act entry decides any of them.
- **Strict — live per call.** Each physical dispatch resolves again, so an edit
  to the session or the document reaches the next call and rewrites no call
  already made.
- **Strict — one binding.** A run carries exactly one session id, written once
  at launch or at the first resume without one, and never rebound afterwards.
  Changing a run's staffing means editing its session, not rebinding it.
- **Strict — no dispatch fails for an unreadable input.** An unreadable session
  or document resolves on the default document; the dispatch is never failed,
  blocked or retried on that account.
- **Strict — exactly two conditions stop a call.** No family available, and a
  declared split-family role that cannot be split. Each stops the run through
  the ordinary failure path, naming its own token. There is no third.
- **Strict — resume is never blocked for compatibility.** A run without a
  session resumes; if the session cannot even be created, every call falls back
  visibly instead of failing.
- **Best-effort — bookkeeping.** The marker's fallback note and the rounds-time
  review projection in the run summary. A lost or stale one changes no
  acceptance, seal or result.
- **Optimistic — concurrent writes.** Inherited unchanged from slices 2 and 3:
  no compare-and-set, no version, last completed write wins.
- **Eventual — none.** Nothing here replicates, queues or converges.

### Dependencies and consumers

Depends on slice 2 (the document store, the conversion and the seeded
`default`) and slice 3 (the session store, the resolver, and the live
document reads over a session — a role's assigned seats and the split-family
projection, plus the seats' families this slice adds beside them, three in
all). It has no functional dependency on slice 1.

Its consumers are the operator launching a run, every milestone run already on
disk, and slices 5 through 10, which inherit a driver that already asks the
router. Slice 5 adds the session and resolve routes on the surface this slice
opens; slice 10 proves end to end that no other staffing path remains.

### Non-goals

- No Brainstorming cutover, standalone/`agent_call` cutover, git-sync cutover,
  panel document editor or per-run session control, planner material channel,
  or `resolved_staffing` change.
- No retirement of the model-profile or acts routes, dialogs and launch act
  grid: they stay, and for a cut-over run they decide nothing. Slice 8 removes
  them.
- No edit, migration or deletion of any stored profile, act sidecar, run record
  or document. No document is written or mutated at resume.
- No second rule type, expression language, rule engine, or new surfaced
  condition. No change to the resolver built in slice 3.
- No new permission system, session lifecycle, daemon, ledger or snapshot.
- No edit to the granted read-only roots.

### Acceptance

The slice is accepted when focused tests prove all of the following.

A run launched with `staffing` carries one session id in its run state, and that
session names the given document at the given rigor with the run's configured
families; a launch without `staffing` binds one on the `default` document at
`medium`; a launch that still sends `model_profile` is refused before any run
state is created; and an attach neither takes `staffing` nor is refused for the
lack of it. The launch form lists the documents the store holds.

Every driver-made worker call asks the router, once per physical dispatch, with
the role, seat and round this note pins — proven by capturing the requests a run
makes across a skeleton draft, a slice-note draft, an implementation, a fix with
its consultation, a failure classification, a debt rating, review rounds and a
delta review — and the family, model and effort each call runs on are exactly
the router's answer. Editing the session between two dispatches changes the
second; no value is carried from the first.

A run whose document assigns three review seats reviews with three seats in
index order; the cycle is clean when each assigned seat's family has one clean
look on the current bytes; the round cap and cycle restarts behave as before,
keyed to those families. A document that adds a family slot without assigning it
adds no review seat. A run standing on its third review seat whose assigned
review seats then drop to two — by a document edit, by a session repointed at a
smaller document, or by the fallback for an unreadable one — is not stopped: it
continues to the pre-seal path and there either seals, because every currently
assigned seat is clean on the current bytes, or restarts its cycle because one
is not. A review dispatch under a document whose `review` role
declares split families that the available families cannot honour stops the run
with `distinct_families_unsatisfiable`; a document assigning one review seat
runs normally. The converted `default` document assigns two review seats and
declares that split, so a run whose available families are one — every
single-family `families_order` among them — stops there at its first review
dispatch, and reviews only under a document whose `review` role declares no
split, or assigns it a single seat. A run with no available family at all
stops with `staffing_unavailable`. No other input stops a dispatch.

Describing the cycle is a read, so that condition reaches none of the three
non-dispatch readers. A run whose currently assigned `review` seats come to
share one family — by collapse, by reassignment, or by the fallback for an
absent, repointed or unreadable document — under a document declaring a split
those families cannot honour: with a clean round already recorded, the advance
behind it reads the cycle without failing, that round stands and the cycle moves
to the next seat or to pre-seal; at the seal read the split itself neither fails
the run nor dispatches a reviewer, and where the current families' clean rounds
are already in the ledger the unit seals with no `review_cycle_start` pushed and
no cycle restart recorded; the checkpoint's current-family field names the
family standing at the unit's cycle index rather than stopping the step that
pushes it; and the condition appears only if a later review dispatch is made.
The cycle read answers one family per assigned seat from one reading of one
document, so no reading mixes two; it still raises `staffing_unavailable`,
which leaves no cycle to describe, and that stops the run at the advance and at
the seal read with its token while the checkpoint field, being bookkeeping on a
step that has already run, is left empty instead. Nobody to call leaves no
family to NAME and nothing else, so the move a clean round has already earned
still happens before that stop — the cycle keeps one entry per assigned seat,
which the seat read answers on its own, and the advance's family label is left
empty like the checkpoint's. Such a run restarts no cycle and stands on no seat
it has already cleared, so the repaired document seals on the rounds already
earned and buys none of them twice.

An unreadable session, an unreadable referenced document and an unreadable
stored `default` each let every dispatch proceed on the default document, and
the in-flight marker carries the fallback note.

A run resumed without a session gets one that references the document named by
its selected profile at its selected rigor, or `default` when no document
carries that name, with the run's configured families; a run with no selection
sidecar gets `default` at `medium`; the run's act sidecar contributes nothing to
the session and no override is written from it; no profile file, act sidecar or
document is created, edited or deleted; and the derivation binds once, so a
second resume reuses the same id. A run whose session cannot be created resumes
anyway and every call falls back visibly.

The model profile, the acts sidecar and the config act table decide nothing:
editing any of them between two dispatches of a cut-over run changes neither
answer, and a deliberately invalid one no longer fails a dispatch. Every
candidate finding is rated at the `classify 1` seat the document assigns,
including one raised by that seat's own family — none is retained for want of an
independent rater — and its debt entry names the raising and the rating family;
the drift threshold and the deferred/retained split are unchanged. A run that
supplies one family is the one exception, on the machine fact today's rule
already reads: no second family can run the rating whatever the document
assigns, so no rating is taken and the finding goes to the fix path, exactly as
today — observable only where such a run reviews at all, which is under a
document whose `review` role declares no split, or assigns it a single seat.
A run that supplies two families is never that exception, not even where its
document offers it a single one — there the seat that runs rates, by the
collapse rule that answers every other seat.

The slice-2 conversion drift alarm still passes, still measuring the pre-cutover
profile resolution.

**Size.** This slice is expected to exceed the ~500 changed-line aim, as the
skeleton's slice table anticipates. The reason is not new contract surface — the
router already exists — but that the cutover retires behaviour an entire
existing suite pins: `orchestrator/tests/test_model_profile_runtime.py` asserts,
test by test, that driver dispatches read profiles and acts, that an invalid
profile or a dangling link fails a dispatch, and that the consultation derives
the caller's effort. Every one of those becomes a router assertion or a
Brainstorming-only assertion, and the migration dominates the diff. The review
seat change also reaches four rotation and seal predicates that today read the
run's family order. If the implementation is cut, the natural boundary is: first
the run binding, the launch input and the A2 derivation with the driver's
single-seat calls (plan, draft, implement, fix, classify, consult); second the
review-seat cycle, the delta review seat, the split-family pre-dispatch check
and the projection.

### Risks

- **A silently wrong seat.** Every fallback in the resolver answers rather than
  fails, so a wrong role, seat or round produces a plausible staffing instead of
  an error. The guard is the captured-request test: it asserts the request the
  driver *made*, not only the family that ran, for every call kind.
- **The review cycle stalling or double-reviewing.** Rotation, the round cap and
  the seal predicate are one interlocking set keyed by family; re-keying them to
  seats can leave a cycle that never completes or completes twice. The guard is
  a full cycle over a three-seat document, plus the existing seal-predicate
  suite passing unchanged.
- **A resumed run's seat index meaning something else.** A run interrupted
  mid-cycle carries a seat index chosen under its old family order. Under a
  converted document the review seats are those families in that order, so the
  index means the same thing; under a hand-written document it may not. This is
  A2's "default and move on": the marker shows who ran, and one session edit
  changes it. No machinery represents the old meaning.
- **The conversion alarm going circular.** Slice 2's drift alarm measures
  today's staffing through the very seams this slice cuts over; left alone, its
  end-to-end consultation assertion would compare the document with itself. It
  is re-pointed at the same profile-side reference its other seats already use,
  and nothing else in that test changes.
- **Retiring the loud failure too widely.** Unreadable inputs must stop failing
  dispatches while save-time validation and the two surfaced conditions stay
  loud. The guard is that both tokens are asserted to stop the run and every
  unreadable input is asserted not to.
- **Scope leaking into slices 6 to 8.** The driver also holds the Brainstorming
  seat resolvers, and the launch form also holds an act grid. Both stay exactly
  as they are; a test asserts the Brainstorming seats still resolve through
  profiles after this slice.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Run binding | A milestone run carries exactly ONE staffing session id in its run state. It is written once — at launch, or at the first resume that finds none — and never rebound; the key is ABSENT on a run that has none, never present-null, as `project` already is. Changing a run's staffing means editing that session, never binding a second one. | `implementation/milestones/staffing-router/skeleton.md:225-228`; absent-key precedent `orchestrator/state.py:171-176` | touch run state and the two writers; do-not rebind, copy a document into the run, migrate stored state, or add a per-unit or per-call binding |
| Launch input | `POST /api/runs` takes `staffing: {document, rigor, material?}` and opens the run's session from it: `document` and `rigor` as given, `material` as the session's default material, `families` the run's effective `families_order`, `work_area` the run's resolved project and work area and/or its workspace path. Absent `staffing` binds the `default` document at `medium`. `model_profile` is REFUSED (400) before any run state is created, because after this slice it decides no call. `attach` refuses `staffing` exactly as it refuses `model_profile` today. `GET /api/staffing/documents` lists the stored documents (read-only; admin like `/api/model-profiles`), and the launch form's model-profile selector becomes a document selector beside the existing rigor selector. | `implementation/milestones/staffing-router/skeleton.md:292,322`; today's launch validation `orchestrator/service.py:2016-2035,2145-2147`; list source `orchestrator/staffing.py:684-698`; catalogue route pattern `orchestrator/service.py:2656-2664,4294`; selector `orchestrator/static/panel.html:690-697,5470-5473` | touch the launch body, the launch form and the one read route; do-not add the document write, session or resolve routes (slice 5), expose seats, or keep `model_profile` as a live launch input |
| Role, seat and round | Each driver-made call resolves exactly one request: skeleton draft → `plan` 1; a fix on the skeleton unit → `plan` 1; slice-note draft → `draft` 1; implementation → `implement` 1; every other fix → `fix` 1; failure classifier and debt rater → `classify` 1; the fixer's consultation → `consult` 1; a review round and a delta review → `review` at their seat. Round is 1 except: a `review` request carries the count of review rounds already recorded for that seat's family in the current review cycle, plus one (the count the round cap already takes); a `fix` request carries the unit's active-episode fixer iteration count, plus one. No request carries a `material` in this slice; the session's default material applies through the resolver. `brief` is not sent. | `implementation/milestones/staffing-router/skeleton.md:215-224`; the seat map conversion already reproduces `orchestrator/staffing.py:866-980`; skeleton-fix act today `orchestrator/driver.py:8097-8113`; round-cap count `orchestrator/driver.py:10327-10338`; fix iterations `orchestrator/state.py:217`, `orchestrator/driver.py:9061` | touch each dispatch seam's request; do-not invent a role, send a seat the consumer does not count, read `brief`, or send a material before slice 9 |
| One resolution per physical dispatch | Every physical provider dispatch resolves once, through the existing per-dispatch resolver hook that returns `(family, model, effort)`, and the in-flight marker is retargeted to what it returned. Retries, infrastructure re-dispatches and cutoff stabilization resolve again. | `orchestrator/runners.py:2941-2962`; `implementation/milestones/staffing-router/skeleton.md:316`; resolver signature `orchestrator/staffing.py:2000-2047` | touch what the hook reads; do-not cache a resolution across calls, resolve at order time, or change the hook's shape |
| Review seats ARE the cycle | The review cycle iterates the `review` seats the run's session document assigns, in index order, read live over the session; the run's `families_order` no longer decides which families review. The cycle is clean when each assigned seat's family has one clean same-byte review, and the round cap, cycle restarts, amnesty and the seal predicate keep their present shape keyed to those families. A family slot the document adds but assigns to no seat adds no review seat. Seats read live can also SHRINK below the seat a cycle has already reached — by a document edit, by a session repointed at a document with fewer review seats, or by the default-document fallback for an unreadable one — and that is not a stopping condition: with no seat left at the unit's index the cycle is exhausted, and the run continues through the ordinary pre-seal path, where the seal predicate over the CURRENTLY assigned seats decides — sealing when each of them has a clean same-byte review and restarting the cycle when one does not. Delta review chooses only among assigned `review` seats: it resolves the lowest-index seat whose resolved family matches the latest fixer, and the lowest assigned seat when none matches; the marker records the family that ran. | `implementation/milestones/staffing-router/skeleton.md:319`; seat reader `orchestrator/staffing.py:2061-2077`; predicates re-keyed `orchestrator/state.py:887-892,1069-1081,1099-1110,1112-1116`; today's refusal of a rounds status with no seat left `orchestrator/driver.py:10320-10322` and the pre-seal seal-or-restart path it is routed into instead `orchestrator/state.py:1040-1057`, `orchestrator/driver.py:9752-9770`; today's fixed-family delta `orchestrator/driver.py:8256-8265,9427-9429` | touch the source of the seat's family and the rounds branch that today refuses a status with no seat left; do-not move convergence, sealing, the cap or rotation into the router, let a review seat be chosen by anything but the document, or let a shorter seat list stop a run |
| Split-family check before dispatch | Before each review dispatch the run checks that the `review` role's declared split can still be honoured with the families available; the resolver's own refusal is that check. A `review` role with one assigned seat is trivially honoured. The seats' families are READ, not judged, outside it: describing the cycle dispatches nothing, so the cycle reader below answers under a split it cannot honour and the condition stops only the dispatches it affects. | `implementation/milestones/staffing-router/skeleton.md:315,319`; the flag and its judgement `orchestrator/staffing.py:1122,1921-1946`; projection reader `orchestrator/staffing.py:2109-2122` | touch the review dispatch path; do-not validate any other family relationship, or surface the CONDITION anywhere else in this slice |
| The cycle is read, not dispatched | Where the run needs the family an assigned `review` seat runs on and is dispatching nothing — the cycle behind rotation and advance, the pre-seal seal predicate, and the checkpoint's current-family field — it uses a third live document read over a session, `session_seat_families(home, session, role, ...)`: the family each assigned seat of *role* runs on, in index order, collapse included, from ONE reading of one effective document, fallback included. It refuses nothing it can answer, so a declared split this session cannot honour comes back described. `staffing_unavailable` it still raises, because no family available leaves no answer to give and an empty list reads as a cycle with no seat left; its readers stop the run with that token, the advance only AFTER making the move a clean round has already earned, which needs no family name and takes its one-entry-per-seat length from the seat read. The read never keys the round cap, picks a callee or seals anything: both of the cap's takes stay on the family `resolve` returns for that dispatch. | run amendment A4; `implementation/milestones/staffing-router/skeleton.md:319`; the private composition it exposes `orchestrator/staffing.py:1911,1921-1946`; the reads it joins `orchestrator/staffing.py:2061-2077,2109-2122`; its consumers `orchestrator/driver.py:8463,8479,8503` | touch the seat→family source and the three non-dispatch readers; do-not derive the cycle driver-side, re-implement collapse, layering or the fallback, add a fourth reader, change `resolve`, or let a read refuse what it can answer |
| Only two conditions stop a call | `staffing_unavailable` and `distinct_families_unsatisfiable` stop the affected dispatch and fail the run through the ordinary recovery path, each naming its own token in the reason. Nothing else stops a dispatch: an unreadable session, an unreadable document, an unreadable stored `default`, an unbound family, an out-of-range rank, an unknown material and an unassigned seat all resolve. | `implementation/milestones/staffing-router/skeleton.md:314-315`; tokens `orchestrator/staffing.py:1584-1585`; existing recovery path `orchestrator/driver.py:8020-8030` | touch the dispatch seam's handling; do-not add a third condition, retry a surfaced condition, or fail a dispatch for an unreadable input |
| Retired as dispatch inputs | For a run with a catalogue home, no driver-made worker call reads a model profile, `acts.json`, the config `acts` table, `families_order[0]` or a structural family derivation — the retained debt gate below reads the run's own families to decide WHETHER a rating call is made, never which family, model or effort runs one. `model_profile.json` is read once at resume for a name and a rigor and for nothing else; `acts.json` is read only by the run summary and run detail so the acts dialog keeps showing it until slice 8. No profile file, act sidecar or record is edited or deleted. The consultation command line becomes the `consult 1` staffing resolved when the fixer runs it, so the "consulted family, caller's effort" derivation retires. The debt rater's independence gate loses the origin-relative derivation it reads and is re-keyed to the router: it withholds a rating today only where that derivation collapses onto the raising family AND no family was named explicitly, since the same rule already admits an explicitly named same-family rater as a second look. After the cutover the document's `classify 1` assignment is that explicit rater wherever the run SUPPLIES a second family, so such a run rates every candidate finding at the `classify` seat that runs — including where its own document offers it a single family and collapse answers that seat — and the debt entry goes on naming the raising and the rating family. A run that supplies ONE family keeps the gate, on the same machine fact the retired derivation reads and the only one the dispatch has: no second family can run the rating whatever the document assigns, so the rating is withheld and the finding takes the fix path, unchanged from today — a state such a run reaches only where its review dispatches run at all, which is under a document whose `review` role declares no split, or assigns it a single seat that the split-family check above honours trivially. Nothing else about debt moves: the drift threshold, the deferred/retained split and which findings are raised are untouched. | `implementation/milestones/staffing-router/skeleton.md:292,313-314,317`; retiring seams `orchestrator/driver.py:8020-8030,8052-8095,8097-8123,8241-8265,3736-3762,1364-1397,9986-9992,10011-10018,10060-10082`; consultation subprocess `orchestrator/current_model_call.py:15-64`; config act table `orchestrator/driver.py:168-205` | touch each named seam; do-not delete or rewrite a profile, sidecar or record, leave a second staffing channel for a driver call, or re-derive an origin-relative rater, resolve a second time to compare one, or key the retained gate on anything but the families the run supplies |
| Catalogue-home boundary | The cutover applies to a run whose driver has a catalogue home — which is every reachable run: the service and every CLI entry point supply it. A `Driver` constructed in-process without one has no document store to read and keeps today's configuration-act resolution unchanged; it is a library and test construction, not a channel an operator or a product can reach. | entry points `orchestrator/driver.py:11235-11236,11307-11309,11384-11385,11403-11404`; today's same gate `orchestrator/driver.py:741,8015,8081` | touch the homed path; do-not build a second resolver, inject a document into the router, or treat the home-less construction as an operator-facing path |
| Compatibility derivation (A2) | At resume a run with no bound session opens one that REFERENCES the document named by its `model_profile.json` selection at that selection's rigor (absent selection = `default` at `medium`), with the run's `families_order` as its available families, and the `default` document when no document carries that name. Nothing else is derived: `acts.json` literals are not carried and no override is written from them, the document's own numbers apply from the next call, and the operator edits the session to change it. No document is written or mutated, no profile file or act sidecar is edited or deleted, the derivation reads `model_profile.json` and no other file, and resume is never failed or blocked for compatibility — a session that cannot be created leaves every call to the visible default-document fallback. | run amendment A2; `implementation/milestones/staffing-router/skeleton.md:322`; `goal.md:259-270`; selection reader `orchestrator/driver.py:443-459`; converted names `orchestrator/staffing.py:1145-1163` | touch the resume path once; do-not migrate state, rewrite records, fail resume, carry an act literal into the session, write a document at resume, or add machinery to represent an old literal |
| Marker and projection are bookkeeping | The in-flight marker keeps `family`, `model` and `effort` retargeted per physical call and gains `staffing_fallback` when the resolution fell back to the default document. The run summary's rounds-time review projection names the family and model the next review round would run on, and is withheld when it cannot be read, exactly as today. Both are best-effort: a lost or stale one changes no acceptance, seal, result or price. | `implementation/milestones/staffing-router/skeleton.md:292,317`; marker `orchestrator/driver.py:3076-3108`; fallback note `orchestrator/staffing.py:2000-2047`; projection `orchestrator/driver.py:611-641`, `orchestrator/service.py:1077-1080`, `orchestrator/webapp.py:29` | touch marker fields additively and the projection's source; do-not add a staffing ledger, event stream or projection guarantee, or make a dispatch depend on either |
| Slice boundary | Untouched here and still staffed as today: the milestone's Brainstorming seats and their per-dispatch resolver, standalone `agent_call` orders and their host, git-sync, `resolved_staffing`, the planner's material, the panel's model-profile dialog, per-run model-profile route, acts dialog and launch act grid. For a cut-over run those surfaces decide nothing; they are transitional and slice 8 removes them. Slice 2's conversion drift alarm keeps measuring the pre-cutover profile resolution; its one end-to-end consultation assertion is re-pointed at the same profile-side reference its other seats use, and no converted document changes. | `implementation/milestones/staffing-router/skeleton.md:294-296,300-303`; still-live seams `orchestrator/driver.py:8176-8207,8209-8216`, `orchestrator/task_api.py:94-128`, `orchestrator/service.py:3470-3474`; the alarm `orchestrator/tests/test_staffing_documents.py:564-595` | touch the driver's own worker calls; do-not cut over another consumer, retire a panel surface or route, or weaken the conversion alarm |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_staffing_driver_cutover orchestrator.tests.test_model_profile_runtime orchestrator.tests.test_staffing_documents orchestrator.tests.test_staffing_sessions orchestrator.tests.test_p3_debt orchestrator.tests.test_seal_predicate orchestrator.tests.test_driver_mock orchestrator.tests.test_service_api`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Launch binds exactly one session from `staffing` | new `test_launch_binds_one_session` (`orchestrator/tests/test_staffing_driver_cutover.py`) | A launch with `staffing` stores one session id in run state whose document, rigor and material are the ones given and whose families are the run's; a launch without it binds `default` at `medium`; `model_profile` is refused with 400 and no state file is created; attach refuses `staffing`; a second step does not rebind. | strict |
| The launch form offers the documents the store holds | new `test_document_list_route_and_launch_selector` | `GET /api/staffing/documents` returns every stored document sorted, fails loudly on a damaged one, and the launch form's selector is populated from it. | strict |
| Every driver call asks the router with its pinned request | new `test_every_driver_call_asks_the_router` | Requests captured across a skeleton draft, a skeleton fix, a slice-note draft, an implementation, a fix, a consultation, a failure classification, a debt rating, two review rounds and a delta review match the pinned role, seat and round exactly, carry no material and no brief, and the family, model and effort each call ran on equal the router's answer. | strict |
| Nothing else decides a driver call | new `test_profiles_acts_and_config_decide_nothing` | Editing the run's profile selection, its `acts.json`, and the config act table between two dispatches changes neither answer; an invalid profile selection and a dangling profile link no longer fail a dispatch; the run's Brainstorming seats still resolve through profiles. | strict |
| Resolution is live per dispatch | new `test_session_and_document_edits_reach_the_next_call`, following `orchestrator/tests/test_model_profile_runtime.py:1190,1351` | Editing the session, and separately the document, between two physical dispatches of one run changes the second call's family, model or effort; a retry and a cutoff stabilization resolve again. | strict |
| The review cycle is the document's review seats | new `test_review_cycle_follows_assigned_seats` | A three-seat document reviews with three seats in index order and seals only when each seat's family is clean on current bytes; a one-seat document seals after one; a family slot assigned to no review seat adds no seat; the round cap, the cycle restart on changed bytes and resume amnesty behave as before. | strict |
| A shorter seat list stops no run | new `test_review_cycle_survives_a_shrinking_seat_list` | A run standing on review seat 3 whose document is edited to two review seats, and one whose referenced document becomes unreadable so the two-seat default answers, both continue: each seals on its currently assigned clean seats or restarts its cycle, neither fails the run nor raises, and no third token appears. | strict |
| Delta review chooses among the assigned review seats | new `test_delta_review_uses_the_fixers_review_seat` | The delta resolves the lowest-index review seat whose resolved family matches the latest fixer; with no matching seat it resolves the lowest assigned review seat, and the marker records the family that ran. | strict |
| Every candidate finding is rated at the `classify` seat that runs, unless the run supplies one family | new `test_debt_rating_uses_the_assigned_classify_seat` | A finding raised by the family the document assigns to `classify 1` is rated at that seat rather than retained for want of an independent rater; its debt entry names the raising and the rating family; the drift threshold and the deferred/retained split are unchanged. A homed run that supplies one family, reviewing under a one-review-seat document, takes no rating whatever that document assigns to `classify`: its debt list stays empty and the finding appears in the fix queue; the same run under the two-review-seat converted `default` stops at its first review dispatch instead and reaches no finding. A homed run that supplies two families whose document offers it one is rated at the seat that runs. | strict |
| The debt rater's existing tests are re-pointed off the retired derivation | existing `orchestrator/tests/test_p3_debt.py` | Its homed multi-family debt-rater tests assert the router's answer and the rating at the assigned `classify` seat instead of a profile-derived rater. `test_reclassifier_policy_change_before_dispatch_is_not_incident` is a homed run that supplies one family: reviewing under a one-review-seat document it keeps today's answer — no rating, its `no independent reclassifier (single family)` reason, its two-call runner list and no incident — and the profile edit it makes mid-flight is asserted to decide nothing. `test_single_family_config_never_defers` keeps today's answer unchanged, and its `a P3 must never self-defer` invariant is asserted for a homed single-family run under the same one-review-seat document, not only for the home-less `Driver` it builds. | strict |
| Only the two conditions stop a call | new `test_only_two_conditions_stop_a_dispatch` | A session with no available family stops the run naming `staffing_unavailable`; a `review` role declaring split families the machine cannot honour stops it naming `distinct_families_unsatisfiable` at the review dispatch and not before — including the converted `default`'s two review seats under a single available family; a one-seat `review` runs; no other input stops any dispatch. | strict |
| The cycle read answers what a dispatch refuses | new `TheCycleReadAnswersWithoutDispatching` | `session_seat_families` names the family each assigned seat runs on in index order, applies the same collapse a dispatch would, falls back to the default document for an unreadable one, and ANSWERS for a `review` role whose declared split the session cannot honour — while `resolve` on that same session refuses it. No family available raises `staffing_unavailable`; an unknown role is an input error and neither condition. | strict |
| A described cycle stops no run | new `ASurfacedConditionStopsOnlyADispatch` | Under a document declaring a split its available families cannot honour: a run at pre-seal whose currently assigned seats are clean seals, dispatching nobody, with no `review_cycle_start` pushed and no cycle restart recorded; a run whose document declares it while a reviewer runs advances on the round that landed, which stands; the condition then names its token at the next review dispatch. `staffing_unavailable` still stops the run at those reads, restarting no cycle, and the move a clean round has already earned is made before the stop — mid-cycle onto the next seat, and from the last seat into pre-seal — so the repaired document seals on the rounds already earned and re-buys none. | strict |
| One reading describes one cycle | new `test_the_cycle_is_read_from_one_document` | A save completing inside the cycle read still returns a cycle that document assigns — never a seat-1 family from one document beside a seat-2 family from another — and the completed write governs the next reading whole. | strict |
| Unreadable inputs never fail a dispatch | new `test_unreadable_inputs_dispatch_on_the_default_document` | An absent and a corrupt session, an absent and a corrupt referenced document and a corrupt stored `default` each let the run dispatch, on the default document, with `staffing_fallback` on the in-flight marker and no stored file written. | strict (dispatch) / best-effort (marker) |
| Resume derives once and carries nothing else | new `test_resume_derives_a_session_and_carries_nothing_else` | A run with a profile selection resumes with a session referencing that name at that rigor with its own families; an unknown name gives `default`; no selection gives `default` at `medium`; the run's `acts.json` contributes no override and no value; no document, profile file or act sidecar is created, edited or deleted; a second resume reuses the id; a run whose session cannot be created resumes and falls back visibly. | strict |
| Bookkeeping stays bookkeeping | new `test_marker_and_projection_are_best_effort` | The marker's family, model and effort equal the resolved answer on every physical call; the rounds-time projection names the staffing the next review round would run on and is withheld, without failing the summary, when it cannot be read. | best-effort |
| The conversion alarm still measures the profile side | existing `orchestrator/tests/test_staffing_documents.py` `test_conversion_matches_current_effective_staffing` | Passes with every converted document byte-identical; its consultation assertion measures the profile-side reference rather than the now-router-backed command builder. | strict |
| No unrelated behaviour moved | existing `orchestrator/tests/test_seal_predicate.py`, `test_driver_mock.py`, `test_staffing_sessions.py`, `test_service_api.py` | Pass with only the changes this note pins; review law, fix-loop law and run recovery are otherwise untouched. | strict |

The repository closure gate is unchanged:
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:524`; `implementation/milestones/staffing-router/skeleton.md:325`).

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These entries are the slice-scoped remainder. Enforceability is answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | Verified in code, all inside the driver, the service's launch, and one panel form. Driver dispatch seams: the act resolver and its dispatch factories, the worker-kind map, the skeletoner profile, the review and delta-review profiles, the failure classifier, the debt rater's live resolver, and the consultation command with its subprocess. Review law seams: the rotation, advance and seal predicates that read the run's family order, including the rounds branch that today refuses a status with no seat left. Service: run creation's `model_profile` validation and sidecar write, and the summary's rounds-time review projection (also read by the CLI status and the webapp). Panel: the launch form's model-profile selector. Explicitly NOT touched, verified still profile-backed after this slice: the Brainstorming seat resolvers and their runtime locator, the standalone task host, and git-sync. | `orchestrator/driver.py:8020-8030,8052-8095,8097-8123,8126-8146,8241-8265,3736-3762,1364-1397,9986-9992,10011-10018,10060-10082,9427-9429,10320-10353`; `orchestrator/current_model_call.py:15-64`; `orchestrator/state.py:887-892,1069-1081,1099-1110,1112-1116`; `orchestrator/service.py:2016-2035,2145-2147,1077-1080`; `orchestrator/driver.py:611-641`; `orchestrator/webapp.py:29`; `orchestrator/static/panel.html:690-697,5470-5473`; untouched `orchestrator/driver.py:8176-8207,8209-8216`, `orchestrator/task_api.py:94-128`, `orchestrator/service.py:3470-3474` |
| pinned_facts | The single run binding and its write-once rule; the launch body with `staffing`, the refusal of `model_profile`, and the one read-only document list route behind the launch selector; the role/seat/round map for every driver call, including which two roles count repeats; one resolution per physical dispatch through the existing hook; the review cycle as the document's assigned review seats, with the delta review on the fixer's seat and a shrunken seat list exhausting the cycle rather than stopping the run; the debt rating at the assigned `classify` seat, with its independence gate re-keyed to the router and kept where the run supplies one family; the split-family check before each review dispatch; exactly two stopping conditions and their tokens; the retirement of profiles, acts, the config act table and the structural derivations as dispatch inputs, with the files read-only; the catalogue-home boundary; the A2 derivation in full; the marker's fallback note and the projection as best-effort; and the slice boundary, including that the conversion alarm keeps measuring the profile side. | run amendments A1, A2, A3; `implementation/milestones/staffing-router/skeleton.md:215-224,292-296,300-303,313-322`; `goal.md:178-211,259-270`; `orchestrator/staffing.py:866-980,1584-1585,2000-2087`; `orchestrator/driver.py:168-205,443-459,9061,10327-10338`; `orchestrator/state.py:171-176,217` |
| verification | The nineteen-row Verification Contract above: launch binding and its refusals; the document list and selector; a captured-request test covering every driver call kind with its role, seat and round and the staffing each ran on; a negative test that profiles, acts and config acts decide nothing while Brainstorming still reads them; live change across two physical dispatches including a retry; the review cycle over one-, two- and three-seat documents with cap, restart and seal; a cycle whose seats shrink beneath it sealing or restarting rather than failing; the delta review's seat; the debt rating at the assigned `classify` seat, including a self-rating, and a single-family run still never self-deferring, with the existing debt-rater tests re-pointed off the retired derivation and their module in the focused command; both stopping conditions and no third; the cycle read answering the very declared split a dispatch refuses while `staffing_unavailable` still raises there; a described cycle advancing and sealing with nobody dispatched and the token named only at the next review dispatch; one reading of one document per described cycle; all five unreadable-input paths dispatching with the marker note; the A2 derivation with its nothing-else clause and its never-blocked clause; marker and projection as best-effort; the slice-2 drift alarm still green with its reference re-pointed; and the existing seal-predicate, driver, session and service-API suites passing. | this note, Verification Contract; `orchestrator/tests/test_model_profile_runtime.py:1190,1351,1407,1464`; `orchestrator/tests/test_staffing_documents.py:564-595,598-620`; `orchestrator/tests/test_seal_predicate.py`; `orchestrator/README.md:524` |
| reuse_posture | Affected party: the operator and every run on this machine, whose milestone calls are still staffed by seven rules the router was built to replace, and slices 5-10, which cannot proceed over an uncut driver. Realistic harm: work running at an unintended family, model or effort — visible in the marker and in cost, reversible per call, repeated on every dispatch until corrected. Authority: the skeleton's slice-4 row and its consumer, review-law, live-change, fallback, surfaced-condition and compatibility rows, plus amendment A2. Checked and reused rather than rebuilt: the per-dispatch resolver hook and marker retarget, which already carry a family/model/effort triple; the busy marker; the seal predicate's existing families parameter and the summary's existing projection parameter; the run-state absent-key convention; the launch body's validate-before-create ordering; the catalogue route pattern; slice 3's resolver, seat reader and split-family projection, used exactly as built. Cheapest sufficient option: change what the existing seams READ, re-route the one branch that today refuses a rounds status with no seat left into the existing pre-seal path, and add one run-state key, one launch field, one read route and one document read — no new resolver, no adapter, no per-call record. That last one is added rather than reused because no existing reader answers a seat's family: `resolve` is the only source and refuses the whole role before computing a slot, leaving the cycle, the rotation and the seal predicate — which dispatch nothing — unreadable in exactly the state where stopping is forbidden. It exposes the private composition the split judgement already calls, in the router module, because a driver-side derivation would re-implement collapse, layering and the fallback, which is the parallel staffing channel the skeleton forbids; it adds no surfaced condition and changes no resolver. Machinery that remains: the run binding, the A2 derivation, the one read route and the one document read — the re-routed branch leaves no durable surface behind, and the retired cycle-settle loop leaves less than it found, since one document read makes a torn cycle unconstructible — consumed by the operator, the panel launch form, this slice's own cycle readers and slices 5-10. Lifecycle cost: one key, one field, one route, one read, one derivation that runs at most once per run; omission blocks the milestone and keeps the misstaffing; reversible because no stored profile, sidecar or record is edited and a run without a session still dispatches. | `implementation/milestones/staffing-router/skeleton.md:292-296,313-322`; `orchestrator/runners.py:2941-2962`; `orchestrator/driver.py:3076-3108,611-639`; `orchestrator/state.py:171-176,1112-1116`; `orchestrator/service.py:2016-2035,2656-2664`; `orchestrator/staffing.py:2000-2087` |
| enforceability | Every guarantee asserted here has a mechanism that exists, row by row in the Enforceability Gate below: the run-state key for one binding; validate-before-create at launch for the refusals; the per-dispatch resolver hook for one-resolution-per-call and for live change; slice 3's resolver for never-failing on unreadable inputs and for the two tokens; the document's own assignment read live for the review seats; the seats' families over that same single reading — a read that answers where a dispatch refuses — for the described cycle that stops no run and never mixes two documents; the existing families parameter of the seal predicate for the clean-cycle claim; the in-flight marker for what ran. The two claims with NO stronger mechanism than best-effort are named as such: the marker's fallback note and the rounds-time projection can be lost or stale and nothing here promises otherwise. Nothing asserts freshness, survival or delivery of any record. | this note, Enforceability Gate; `orchestrator/runners.py:2941-2962`; `orchestrator/staffing.py:1975-1994,2001-2044,2061-2106`; `orchestrator/state.py:1112-1116`; `orchestrator/driver.py:3076-3108`; `orchestrator/service.py:2016-2035` |

### Reuse Posture

The affected parties are the operator and every run on this machine — milestone
staffing is still decided by the rules the router was built to replace, so a
call can run at a family, model or effort nobody chose — and slices 5 through
10, none of which can proceed over a driver that has not been cut over. The harm
is visible per call in the in-flight marker and in cost, reversible by one
session edit, and repeated on every dispatch until corrected. The independent
authority is the skeleton's slice-4 row together with its consumer-cutover,
review-law, live-change, fallback, surfaced-condition and compatibility rows, and
run amendment A2.

Checked and reused rather than rebuilt: the per-dispatch resolver hook, which
already returns exactly the triple the router answers with, and the marker
retarget beside it; the durable in-flight marker, extended by one additive
field; the seal predicate's existing families parameter and the summary's
existing review-projection parameter, both of which already accept a computed
value from the driver, so neither state nor the summary learns about the router;
the run-state convention of an absent key rather than a present-null one; the
launch route's validate-everything-before-creating-anything ordering; the
model-profile catalogue route as the shape of the one read route; and slice 3's
resolver, seat reader and split-family projection, used exactly as they were
built.

One reader is added beside them rather than reused, because none of the three
answers the fact the cycle needs. `resolve` is the only present source of a
seat's family and refuses the whole `review` role before computing a slot, so
the cycle, the rotation and the seal predicate — none of which dispatches
anything — were unreadable in exactly the state where stopping is forbidden.
The read is public and in the router module because the private composition it
exposes is already there (`_seat_families` over `_effective`/`_assigned_seats`,
what the split judgement itself calls) and a driver-side derivation would
re-implement collapse, layering and the fallback, which is the parallel staffing
channel the skeleton forbids. It adds no surfaced condition, changes no
resolver, and decides nothing: it describes.

The cheapest sufficient option is to change what those seams read and where the
one branch that today refuses a rounds status with no seat left sends the run,
plus one run state key, one launch field, one read-only list route and that one
document read.
Documentation alone is insufficient because the cutover is executable
behaviour. Two cheaper-looking options were rejected: translating a launch
`model_profile` into a document reference would keep a second live staffing
input at launch that slice 10 must then prove gone, while refusing it costs one
error and tells the caller the truth; and routing the home-less in-process
`Driver` through the router as well would require injecting a document into the
resolver — new public router machinery whose only consumer is a construction no
operator or product can reach — so that path keeps today's configuration-act
resolution untouched instead.

The machinery that remains is the run binding, the A2 derivation and the read
route, consumed by the operator, the panel's launch form and slices 5-10; the
re-routed refusal branch is a new destination inside an existing seam and
leaves no durable surface behind. No ledger, snapshot, version, lease, identity
scheme, notification or scheduler is justified, and none is added. Lifecycle
cost is one state key, one launch field, one route and a derivation that runs
at most once per run; omission blocks the milestone; the change is reversible
because no stored profile, act sidecar, document or record is edited or
deleted, and a run with no session still dispatches.

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| A run carries exactly one session id, written once | One run-state key written by the launch path and by the resume derivation, absent when there is none, like `orchestrator/state.py:171-176`. | A second step and a second resume are asserted to leave the id unchanged. |
| A launch that cannot be honoured creates nothing | Validate-before-create ordering already used for `model_profile` at `orchestrator/service.py:2016-2035`, which the existing suite pins by asserting no state file exists after a refusal. | `model_profile` at launch is asserted to give 400 with no state file created. |
| Every driver call takes its staffing from the router | The one per-dispatch resolver hook `orchestrator/runners.py:2941-2962`, which is the only place a family, model and effort enter a call. | Captured requests are asserted for every call kind, and the ran-on triple is asserted equal to the answer. |
| Resolution is live and cached nowhere | The hook resolves per physical dispatch; the resolver reads its stores per call `orchestrator/staffing.py:2000-2047`. | Two dispatches around a session edit and a document edit are asserted to differ. |
| No dispatch fails for an unreadable input | Slice 3's mandatory fallback, which answers unknown, unreadable, malformed and damaged alike `orchestrator/staffing.py:1697-1740`. | Five unreadable-input cases are asserted to dispatch, with the marker note. |
| Exactly two conditions stop a call | The resolver's two typed refusals carrying their tokens `orchestrator/staffing.py:1584-1585,2031-2033`, raised into the run's existing failure path. | Both are asserted by token; every other input is asserted not to stop a dispatch. |
| The review cycle is the document's seats | The seat readers, both read live per use: the assigned indices `orchestrator/staffing.py:2061-2077` for the seats the cycle walks, and the family each of them runs on `orchestrator/staffing.py:2079-2106`, which is what feeds the seal predicate's existing families parameter `orchestrator/state.py:1112-1116`. | A three-seat and a one-seat document are asserted to review and seal accordingly. |
| A seat list shorter than the cycle has walked stops no run | The existing pre-seal path, which seals over the currently assigned seats and restarts the cycle when that is unsatisfied `orchestrator/state.py:1040-1057`, `orchestrator/driver.py:9752-9770`. Its ENTRY is the one mechanism this row adds rather than reuses: a rounds status with no seat left is refused today `orchestrator/driver.py:10320-10322` and is routed to that path instead. | A run past its last remaining seat is asserted to seal or restart, never to fail or raise. |
| Describing the cycle stops no run, and describes one document's cycle | `staffing.session_seat_families` `orchestrator/staffing.py:2079-2106`, which answers a `review` role whose declared split this session cannot honour instead of refusing it — `_unsatisfiable` is raised only where a dispatch is made `orchestrator/staffing.py:1958-1969,2031-2033` — over the single `_effective` reading the resolver and all three readers share `orchestrator/staffing.py:1975-1994`. `staffing_unavailable` stays, since with no family available there is no answer to give. | The advance, the seal read and the checkpoint field are asserted to answer under an unhonourable split with nothing dispatched and the clean rounds standing, and the token is asserted at the next review dispatch; a save completing inside the read is asserted never to return one document's seat beside another's. |
| The split-family declaration is honoured before a review runs | The same judgement the resolver refuses with `orchestrator/staffing.py:1921-1946`, applied at the review dispatch. | An unsatisfiable `review` is asserted to stop the run at the review dispatch and not earlier. |
| Every candidate finding is rated at the `classify` seat that runs, unless the run supplies one family | The document's own `classify 1` assignment, which is the explicit same-family rater today's debt law already admits `orchestrator/driver.py:10011-10018`. The kept single-family gate is keyed on the only two facts the dispatch has — the resolved family and the families the run supplies to the resolver, which is also the fact the retired derivation reads `orchestrator/driver.py:1355-1359` — rather than on any origin-relative re-derivation or on a count of available families, which no router read answers. | A finding raised by that seat's family is asserted to be rated, with both families in the debt entry; a run that supplies one family, reviewing under a one-review-seat document, is asserted to withhold the rating and fix instead, and a two-family run whose document offers it one is asserted to rate. |
| Resume is never blocked for compatibility | The derivation writes only the session; every remaining failure path is the resolver's fallback, which cannot fail. | A run whose session cannot be created is asserted to resume and dispatch. |
| Nothing else decides a driver call | Removal of the profile, act-sidecar and config-act reads from the driver's dispatch seams, plus the captured-request test. | Edits to all three are asserted to change no answer; an invalid profile is asserted not to fail a dispatch. |
| The marker and the projection are best-effort ONLY | The existing marker write and the existing withhold-on-error projection `orchestrator/driver.py:3076-3108,611-639`. | Their loss is asserted to change no acceptance, seal or result. |

There is deliberately no enforcement row for delivery, freshness, survival of a
marker, session lifecycle, or any guarantee about a document's contents: this
slice asserts none of them.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's slice-4 row and its consumer-cutover,
  review-law, live-change, fallback, surfaced-condition, marker, launch-surface
  and compatibility rows; the goal's mandatory resolution paragraph; run
  amendments A1, A2 and A3.
- **Revise:** no baseline decision. This note settles eight points the skeleton
  leaves to the slice: the run's session id is one run-state key written once
  and never rebound; a launch that still sends `model_profile` is refused rather
  than silently ignored or translated; the read-only document list route lands
  here because this slice's own launch selector consumes it, while the document
  write, session and resolve routes stay in slice 5; `review` and `fix` are the
  two driver roles that count repeats, from the counters the unit already keeps,
  and every other role sends round 1; the delta review resolves the review seat
  whose family is the fixer's and the lowest assigned seat when none is; and a
  `Driver` built without a catalogue home keeps today's configuration-act
  resolution, since every reachable entry point supplies the home; a live seat
  list that shrinks beneath the seat a cycle stands on exhausts the cycle
  through the ordinary pre-seal path rather than stopping the run; and the debt
  rater's independence gate loses the origin-relative derivation it reads but
  not its invariant: the document's `classify` assignment is the explicit rater
  that same rule already admits, while a run that supplies one family — which no
  document can give a second rater — still never self-defers.
- **Reject:** brainstorming and `_drafts` material as authority; carrying any
  `acts.json` literal into a derived session, in any form; any edit or deletion
  of a profile file, act sidecar, document or stored record; any Brainstorming,
  standalone, git-sync, panel-editor, planner-material or `resolved_staffing`
  work, all of which belong to later slices; any third surfaced condition; and
  any change to the resolver, the document schema or the conversion.

Authority: `implementation/milestones/staffing-router/skeleton.md:215-224,292-296,300-303,309-325`;
`implementation/milestones/staffing-router/goal.md:55-83,178-211,259-270`; run amendments A1, A2 and A3.
