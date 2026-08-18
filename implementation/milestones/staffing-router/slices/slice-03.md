# Slice 03 — Sessions and resolution

## Register 1 — INTENT (lay language)

### What this slice builds

Slice 2 made staffing documents exist. They are inert: nothing asks one
anything. This slice builds the two things that ask — the **session** and the
**resolver** — and stops there.

A **session** is what an owner opens for a piece of work. It names the work
area, the agent families actually installed on this machine, the staffing
document to use — by name, never a copy — the rigor, and optionally a default
material. It may also carry its own overrides on top of that document, in the
document's own shape: that is where "for this run, the fixer runs on the other
family" lives. Sessions are edited while work runs; a change reaches the next
call and never rewrites a call already made.

The **resolver** is the one question and answer. A caller asks with a session, a
role (the process step), a seat index, a round number, and optionally a material
and a free-text brief. The answer is exactly three things: which agent family,
which model, which effort. Nothing else comes back, and nothing about the call is
remembered.

Almost nothing makes the resolver refuse. A family this machine does not have
collapses onto the lowest-numbered slot it does have; a rung past the end of a
ladder saturates at the top; an unknown material counts as no material; a seat
nobody assigned falls back to that role's first seat; a session or a document
that cannot be read at all resolves as the default document and reports that it
did. Only two situations are surfaced: there is no family on this machine at
all, or a role that milestone law requires to be split across different families
cannot be split with the families available.

One rule type exists: **step up**. From a configured round onward a stuck role
gets more effort, and when effort has nowhere left to go, the next model up its
ladder. It climbs by capability, never by price, and stops at the top.

What this slice deliberately does not do: none of it staffs a call. Sessions
exist, the resolver answers correctly, and every actual dispatch still reads the
model profile exactly as it does today. The cutover is slice 4 and after.

### Ownership and boundary

This slice owns the session record and its validation, the session store
(create, read, edit) in the same module that already owns documents, the
resolver with its layering, collapse, saturation, seat fallback, `step_up`
arithmetic, mandatory fallback and two surfaced conditions, and the two live
document reads the later slices need over a session: a role's assigned seat
indices, and the `distinct_families` projection.

It owns no consumer behaviour. There is no route, no panel surface, no marker
field, no run binding, no resume derivation, no planner material channel and no
change to how any call is staffed, dispatched, resumed or priced.

### Guarantee posture

- **Strict — save-time validation.** An invalid session write is refused before
  any byte changes and the previously stored session stays byte-identical.
- **Strict — resolution answers.** Every admitted request returns a staffing
  except the two surfaced conditions. Collapse, saturation, seat fallback and
  the material rules replace failure; none of them can refuse.
- **Strict — the floor never fails.** An unreadable session, an unreadable
  document and an unreadable stored `default` each still produce an answer, the
  last from the in-code seed.
- **Strict — live change.** Each resolution reads the current stored session and
  document. The last completed write governs the next call; no value is cached
  across calls, and no caller-held copy is authoritative.
- **Strict — pure read.** Resolving writes nothing. The router keeps no history
  of its own beyond the session record.
- **Optimistic — concurrent session writes.** No compare-and-set and no version:
  two saves of one session each land atomically and the last completed one wins,
  exactly as the document and profile stores behave.
- **Best-effort — the fallback note.** Resolution reports that it fell back to
  the default document; what a consumer does with that report, and whether the
  marker carrying it survives, is that consumer's slice and stays best-effort.
- **Eventual — none.** No replication, queue or convergence exists here.

### Dependencies and consumers

This slice depends on slice 2 and on nothing else that is new: the document
store's load and save, the document shape it validates, its base lookup, and the
in-code `default` seed. It has no functional dependency on slice 1.

It touches no consumer. The seams that will consume it are read-only evidence
here: the per-dispatch resolver hook that expects a family, model and effort
triple; the Brainstorming seat seam that already consumes an `{agent, model,
effort}` dict; the busy marker that records what ran. All of them keep reading
model profiles until slices 4, 6 and 7 cut them over.

Its consumers downstream are later slices only: slice 4 binds a run's session
and asks per dispatch, slice 5 exposes the session and resolve routes, slices 6
and 7 ask for their own seats, and slice 8 edits sessions from the panel.

### Non-goals

- No cutover of any dispatch path; no run binding, no resume derivation, no
  retirement of `model_profile.json` or `acts.json`.
- No route, no panel surface, no marker write, no `resolved_staffing` change,
  no accounting change.
- No session deletion, expiry, lease, liveness, recovery, daemon, ledger,
  snapshot, freeze or version; no permission system.
- No second rule type, expression language or rule engine; no domain role
  words and no material vocabulary invented for the operator.
- No document schema change, no conversion change, and no edit to any stored
  profile, act sidecar or record.
- No edit to the granted read-only roots.

### Acceptance

The slice is accepted when focused tests prove all of the following.

A session write is refused loudly for an unknown key, an unknown role or rigor,
a malformed index key, a non-positive slot or rank, a `work_area` that names a
project without its area, or an override that changes nothing — and a refused
edit leaves the stored session byte-identical. A session is created with an
assigned id, read back equal, and edited live in exactly its four editable
fields; two saves are last-write-wins.

The resolution matrix answers, seat by seat: a slot whose family the session does
not have collapses to the lowest-numbered available slot; a rank beyond a ladder
saturates at that ladder's top; a material named in the request beats the
session's default and both beat base assignment; an unknown material resolves as
if absent; an unassigned seat resolves as that role's index 1; session overrides
outrank material overrides, which outrank base; a session override naming a slot
the document does not carry collapses; `step_up` fires from its `min_round` and
not before, adds effort first, takes the next model when effort is at the top,
and stands still when both are; and two requests differing only in `brief` give
identical answers.

An unreadable or absent session resolves as `default` at `medium` with the
caller's configured families; an unreadable or absent document keeps the
session's rigor and families; an unreadable stored `default` resolves from the
in-code seed. Each reports the fallback, none fails, and none writes a document
or a session.

The two surfaced conditions are raised and no third one is: no available family
at all, and a `distinct_families` role whose assigned seats cannot resolve to
distinct families. A `distinct_families` role with one assigned seat resolves
normally. The same projection is readable over a session without dispatching.

Live change is proven by editing the session and the document between two
resolutions of the same request and seeing the second answer change, and by a
resolution leaving every stored file byte-identical.

That no call's staffing changed is proven by the existing model-profile,
runtime and staffing-document suites passing unmodified.

**Size.** This slice is expected to exceed the ~500 changed-line aim. The reason
is structural: the resolution matrix *is* this slice's strict guarantee, and its
rules are one function's behaviour that cannot be pinned by parts — a collapse
test without saturation, or `step_up` without the layering it applies to, proves
nothing about the answer a consumer gets. The session store's validation is
likewise inseparable from the shape it validates, and shipping the store without
the resolver would leave a record nothing can read. If the implementation is
cut, the natural boundary is the session store and its validation first, the
resolver and its matrix second.

### Risks

- **A silent wrong answer.** Every fallback in this slice is designed not to
  fail, so a mis-ordered rule produces a plausible staffing rather than an error.
  The guard is a matrix that pins the *answer* for each rule in isolation and for
  the combinations that interact — collapse then tuning, saturation then
  `step_up`, session override then collapse.
- **Fallback swallowing a real defect.** A resolver that falls back for any
  exception would hide a bug behind a valid-looking answer forever. The fallback
  is pinned to unreadable inputs only: an invalid request is refused, and the
  named fallback tests assert the reported note rather than only the triple.
- **The floor failing.** The mandatory fallback promises an answer even with a
  damaged `default`. It is met by the in-code seed, and the initialization-time
  loudness slice 2 pinned for a damaged stored `default` is a different moment
  and is left exactly as it is.
- **A cached session.** Any per-caller copy of the session or document would
  quietly make live change untrue for the consumers that come next. The guard is
  a test that edits between two calls through the same caller.
- **Over-strict distinct-families.** Surfacing the condition where milestone law
  is honourable would block review cycles in slice 4. The check is pinned to the
  role's own assigned seats and one assigned seat is trivially honoured.
- **Scope leaking into slice 4.** Sessions are useless until something binds
  one, which invites binding a run here. Nothing in this slice reads or writes
  run state.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Module, store and identity | `orchestrator/staffing.py` gains sessions; records live in the service home in their own directory beside `staffing_documents/` and never inside it. The store assigns each session an opaque path-safe id and never accepts a caller-supplied one; it offers exactly create, read and edit. | `implementation/milestones/staffing-router/skeleton.md:225-228,291`; directory pattern `orchestrator/staffing.py:99-107`; id pattern `orchestrator/brainstorming_lifecycle.py:273-274`; fragment rule `orchestrator/kvstore.py:113-114` | touch the new module surface and its directory; do-not accept caller-supplied ids, add delete/expiry/lease/lifecycle, or open a second store |
| Session record | Exactly `id`, `work_area`, `families`, `document`, `rigor`, optional `material`, optional `overrides`. `work_area` carries the owner's existing handles — `project` and `work_area` supplied together, and/or `workspace_path` — recorded verbatim and read by nothing here. `families` is the ordered list of family names available on this machine; `document` is a name reference, never a copy, and is not required to exist. `rigor` is one of `low`, `medium`, `high`. Editable live: exactly `document`, `rigor`, `material`, `overrides`. | `goal.md:57-64`; `implementation/milestones/staffing-router/skeleton.md:312`; handles `orchestrator/service.py:161-164`, `orchestrator/brainstorming_tasks.py:80-83`; rigors `orchestrator/staffing.py:73` | touch the session store and its validation; do-not copy the document into the session, make `work_area` or `families` editable, freeze at order time, or add session lifecycle/recovery |
| Session overrides | One unconditional delta in the document's inner shape: optional `assignment` (role → 1-based index → slot) and optional `tuning` (rigor → slot → role → `[model_rank, effort_rank]`), at least one of the two written. Validated for shape only — closed role and rigor vocabularies, decimal index keys, positive-integer slots and ranks — never against the referenced document, which is a live reference. Written by any authorized session owner (amendment A3). | `goal.md:62-64`; `implementation/milestones/staffing-router/skeleton.md:312`; inner shapes `orchestrator/staffing.py:310-341,343-375`; run amendment A3 | touch session validation; do-not key session overrides by material, validate them against a document, or write "operator only" anywhere |
| Request and answer | Request: `session`, `role`, `index` (default 1), `round` (default 1), optional `material`, optional `brief`; the call also carries the caller's own configured families, used only when the session cannot be read. Answer: exactly `agent` (the family name), `model`, `effort`. `brief` is accepted, read by no rule and never stored; resolution writes nothing at all. | `goal.md:79-83`; `implementation/milestones/staffing-router/skeleton.md:310`; consuming seam `orchestrator/brainstorming_execution.py:56-81`; family name `orchestrator/staffing.py:516-553` | touch the resolver signature and its answer; do-not return a fourth key, read `brief`, or keep router history |
| Resolution order | Material = the request's, else the session's default, else none; a material the document does not carry counts as absent. The slot comes from the layered assignment — base, then the material's override, then the session's override — for `(role, index)`; an index no layer assigns resolves as that role's index 1. A slot whose family the session does not list as available, including a slot the document does not carry, collapses to the lowest-numbered slot whose family is available. Ranks come from layered `tuning[rigor][slot][role]` for the resolved slot; a rank beyond its ladder saturates at that ladder's top. Then `step_up`. Nothing in this order can fail. | `goal.md:178-190`; `implementation/milestones/staffing-router/skeleton.md:313`; base lookup `orchestrator/staffing.py:516-553`; saturation is resolution's `orchestrator/staffing.py:497-514` | touch the resolver only; do-not fail, freeze or gate on any of these, or add a precedence layer |
| `step_up` | Each rule entry whose `role` matches the request and whose `min_round` is at most the request's `round` applies exactly one step, after saturation: effort rank + 1; when effort already stands at its ladder's top, the next model at its first effort; when both stand at the top, no change. N matching entries apply N steps, so progression is written as data, never as a second rule type. It climbs capability, never price. | `goal.md:121-127`; `implementation/milestones/staffing-router/skeleton.md:313`; rule shape `orchestrator/staffing.py:425-451`; run amendment A1 | touch the resolver's rule step; do-not add a second rule type, an expression language, or a cost criterion |
| Mandatory fallback | An input that cannot be read at dispatch — absent or unreadable alike — resolves as the default document with the available families: an unreadable document keeps the session's rigor and families; an unreadable session resolves as `default` at `medium` with the caller's configured families; an unreadable stored `default` resolves from the in-code seed. Resolution reports `staffing_fallback: "default_document"` beside the answer, which the consumer's marker carries in its own slice. The dispatch is never failed, blocked or retried on that account, and no document or session is written. Slice 2's loud initialization for a damaged stored `default` is a different moment and is untouched. | `goal.md:191-197`; `implementation/milestones/staffing-router/skeleton.md:314`; seed `orchestrator/staffing.py:1022-1031`; initialization loudness `orchestrator/staffing.py:1053-1060` and `orchestrator/tests/test_staffing_documents.py:915-944` | touch the resolver's fallback and its report; do-not reintroduce a failure, freeze or validation gate for unreadable inputs, or heal a damaged document |
| Surfaced conditions | Exactly two, raised as a typed refusal carrying its public token, in the established `(code, detail)` shape. `staffing_unavailable`: no slot of the effective document names a family the session lists as available — an empty `families` included, which is stored as the machine fact it is and never refused at save. `distinct_families_unsatisfiable`: a role whose document `roles` entry declares `distinct_families` has two or more assigned seats that do not resolve to pairwise-distinct families under the session's available families; one assigned seat is trivially honoured. HTTP statuses (503, 409), the resolve route's 404 and 400 admission errors, and what a consumer does with either belong to slice 5 and after. | `goal.md:199-204`; `implementation/milestones/staffing-router/skeleton.md:315,309`; token pattern `orchestrator/tasks.py:18-19,126-131`; flag shape `orchestrator/staffing.py:220-244` | touch the resolver's two refusals; do-not add a third surfaced condition or refuse an empty families list at save |
| Invalid request | A request naming an unknown role, a non-positive index or round, or a non-string material is refused as an input error before resolution. It is not a surfaced condition and never reaches the fallback. | `implementation/milestones/staffing-router/skeleton.md:315,322`; role and rigor refusals `orchestrator/staffing.py:534-541` | touch request validation; do-not absorb an unknown role into a fallback or a collapse |
| Live change and no cache | Each resolution reads the current stored session and its document; the last completed write governs the next call and no call already made is rewritten. No value is cached across calls and no caller-held copy is authoritative. Two saves of one session each land atomically and the last completed one wins: no compare-and-set, no version, no snapshot, no freeze. | `goal.md:206-211`; `implementation/milestones/staffing-router/skeleton.md:316,312`; per-call read pattern `orchestrator/driver.py:462-470`; store pattern `orchestrator/staffing.py:615-681` | touch the resolver's reads; do-not cache across calls or add generations, versions or acknowledgements |
| Seats and projection | Over a session the module exposes, as a live document read and never as part of the answer, a role's assigned seat indices in index order, and the `distinct_families` projection over them. Their consumers are slice 4's review cycle and slice 5's session create and read. | `implementation/milestones/staffing-router/skeleton.md:319,315` | touch these two readers; do-not move convergence, rotation or sealing into the router, or return seats in the resolve answer |
| Slice boundary | Nothing dispatches through any of this: no consumer edit, no route, no panel surface, no marker write, no run binding, no resume derivation, no planner material, no `resolved_staffing` change. `model_profile.json` and `acts.json` still decide every call, and every call is staffed exactly as today. | `implementation/milestones/staffing-router/skeleton.md:291,292,300-303`; still-live paths `orchestrator/driver.py:462-470,8010-8020`; `orchestrator/task_api.py:94-128` | touch sessions and the resolver; do-not cut over a consumer, bind a run, or leave a parallel staffing channel |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_staffing_sessions orchestrator.tests.test_staffing_documents orchestrator.tests.test_model_profiles orchestrator.tests.test_model_profile_runtime`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| The session shape is closed and its write is loud | new `test_session_shape_is_closed_and_write_is_loud` (`orchestrator/tests/test_staffing_sessions.py`) | An unknown key, an unknown role or rigor, a malformed index key, a non-positive slot or rank, a `project` without its `work_area`, and an empty override are each refused, and a refused edit leaves the stored session byte-identical. An empty `families` is accepted and stored. | strict |
| The store creates, reads and edits, last write wins | new `test_session_store_creates_reads_and_edits` | Create assigns an id and reads back equal; edit changes exactly `document`, `rigor`, `material`, `overrides` and refuses to change `work_area`, `families` or `id`; two saves land and the second wins; an unknown id raises. | optimistic (writes) / strict (shape) |
| The resolution matrix | new `test_resolution_matrix` | One document and one session per row: collapse to the lowest-numbered available slot; saturation at each ladder's top; request material over session material over base; unknown material as absent; unassigned index as index 1; session override over material override over base; a session override naming an uncarried slot collapsing; `brief` changing nothing. Each row asserts the whole `{agent, model, effort}`. | strict |
| `step_up` fires from its round and saturates | new `test_step_up_fires_from_its_round_and_saturates` | Below `min_round` the answer is the tuned one; at and above it the effort is one rung higher; with effort at the top the model is the next rung at its first effort; with both at the top the answer is unchanged; two matching entries apply two steps. | strict |
| Unreadable inputs resolve on the default document | new `test_unreadable_inputs_resolve_on_the_default_document` | Absent and corrupt session, absent and corrupt referenced document, and corrupt stored `default` each answer — the last from the in-code seed — each report `staffing_fallback: "default_document"`, and none writes or repairs a stored file. | strict |
| Only the two surfaced conditions are raised | new `test_the_two_surfaced_conditions` | No available family raises `staffing_unavailable`; a `distinct_families` role whose seats cannot be distinct raises `distinct_families_unsatisfiable`; the same role with one assigned seat resolves; an unknown role is an input refusal, not either token; no other input raises. | strict |
| Seats and the projection are readable without dispatch | new `test_seats_and_distinct_families_projection` | A role's assigned indices come back in index order under the session's layering; the projection names exactly the roles whose declared `distinct_families` cannot be honoured, and changes with the document between two reads. | strict |
| Resolution is live and writes nothing | new `test_resolution_is_live_and_writes_nothing`, following `orchestrator/tests/test_model_profile_runtime.py:186,1190,1351` | Editing the session, and separately the document, between two identical requests through one caller changes the second answer; every file under the service home is byte-identical before and after a resolution. | strict |
| No call's staffing changed | existing `orchestrator/tests/test_staffing_documents.py`, `test_model_profiles.py`, `test_model_profile_runtime.py`, unmodified | All three pass unmodified; no dispatch seam is edited. | strict |

The repository closure gate is unchanged:
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:524`; `implementation/milestones/staffing-router/skeleton.md:325`).

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These entries are the slice-scoped remainder. Enforceability is answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **None.** Verified in code: every path that staffs a call still reads model profiles and is untouched here — the driver's per-dispatch profile layers and act resolution, the direct task host's first-family snapshot, git-sync's first family, and the Brainstorming seat resolver. The seams that will consume this slice are read-only evidence: the dispatch hook that takes a family/model/effort triple and the Brainstorming seam that already takes an `{agent, model, effort}` dict. The only file this slice extends is the module slice 2 created; its downstream consumers are slices 4-8. | `orchestrator/driver.py:462-470,8010-8020`; `orchestrator/task_api.py:94-128`; `orchestrator/service.py:3470-3474`; `orchestrator/brainstorming_tasks.py:107-132`; `orchestrator/runners.py:2941-2962`; `orchestrator/brainstorming_execution.py:56-81`; `implementation/milestones/staffing-router/skeleton.md:291,300-303` |
| pinned_facts | The session record's closed shape, its four editable fields and its live document reference; session overrides as one unconditional delta in the document's inner shape, validated for shape only; the request fields and the three-key answer with `brief` read by nothing; the resolution order with its collapse, seat fallback, material precedence and saturation; `step_up` as one step per matching entry after saturation; the mandatory fallback's three levels and its reported note; exactly two surfaced conditions with their tokens; input refusal as separate from both; per-call reads with no cache and last-write-wins saves; the seat and projection readers; and the boundary that nothing dispatches through this slice. | `goal.md:57-64,79-83,178-197,199-204,206-211`; `implementation/milestones/staffing-router/skeleton.md:291,309,310,312,313,314,315,316,319`; run amendments A1 and A3 |
| verification | The nine-row Verification Contract above: closed session shape with byte-stable refusal; store create/read/edit and last-write-wins; the resolution matrix asserting the whole answer per rule; `step_up` from its round with both saturations; all five unreadable-input paths including the in-code seed floor, each asserting the reported fallback and that nothing was written; both surfaced conditions with the one-seat case and the input refusal beside them; seats and projection read without dispatch; live change through one caller plus byte-identical files after a resolution; and the three existing suites passing unmodified. | this note, Verification Contract; `orchestrator/tests/test_model_profile_runtime.py:186,1190,1351`; `orchestrator/tests/test_staffing_documents.py:301-337,915-944`; `orchestrator/README.md:524` |
| reuse_posture | Affected party: every later slice, which has no way to ask for a staffing, and the operator and calling products whose sessions cannot exist; the harm is the milestone's own blockage plus a wrong answer resolving silently, visible per call in the marker and reversible by one session edit. Authority: the skeleton's slice-3 row and its resolution, fallback, surfaced-condition, live-change and review-law rows. Checked and reused: the document store's validate-then-atomically-replace pattern, its loud load and its closed-vocabulary validators; the document's own inner assignment and tuning shapes for session overrides; the base lookup and the in-code seed; the established opaque-token id and path-fragment rules; the `(code, detail)` public-token error shape; the live-change test pattern. Cheapest sufficient option: one session record and one resolver inside the existing module — no new store, no new error family, no new id scheme. Machinery that remains: the session store and the resolver, consumed by slices 4-8; nothing else. Lifecycle cost: one directory of small records, no daemon, no migration; omission blocks every remaining slice; reversible because nothing dispatches through it and deleting the directory restores the prior state exactly. | `implementation/milestones/staffing-router/skeleton.md:291,312-319`; `orchestrator/staffing.py:310-341,343-375,497-514,516-553,615-681,1022-1031`; `orchestrator/brainstorming_lifecycle.py:273-274`; `orchestrator/kvstore.py:113-114`; `orchestrator/tasks.py:18-19,126-131` |
| enforceability | Every guarantee asserted here has a mechanism that exists, row by row in the Enforceability Gate below: validate-then-atomic-replace for the loud session write; one resolver function under the matrix for always-answers, collapse, saturation, precedence and `step_up`; the in-code seed for the floor; a per-call store read for live change, proven by editing between two calls as the runtime suite already does; the public-token error shape for the two surfaced conditions; and byte comparison of the service home for the pure-read claim. Nothing here promises freshness, survival or delivery of anything: the fallback note is reported to the caller and its persistence is the marker's posture in a later slice. | this note, Enforceability Gate; `orchestrator/staffing.py:615-681,1022-1031`; `orchestrator/driver.py:462-470`; `orchestrator/tests/test_model_profile_runtime.py:186,1190,1351`; `orchestrator/tasks.py:126-131` |

### Reuse Posture

The affected parties are every remaining slice of this milestone, which has no
way to ask for a staffing until this exists, and the operator and calling
products, whose sessions are the only channel the goal gives them. The realistic
harm is not the absence of a record but a resolver that answers plausibly and
wrongly: work then runs at an unintended family, model or effort, visible in the
marker and in cost, reversible by one session edit, and repeated on every call
until edited. The independent authority is the skeleton's slice-3 row together
with its resolution, fallback, surfaced-condition, live-change and review-law
rows.

Checked and reused rather than rebuilt: the staffing document store's whole
pattern — validation before any byte changes, atomic same-directory replacement
so a refused write leaves the prior record untouched, loud loading, closed
vocabularies and 1-based decimal index keys; the document's own `assignment` and
partial `tuning` shapes, taken verbatim as the session override's shape rather
than invented; the base lookup and the in-code `default` seed as the fallback
floor; the established opaque session-id token and the existing path-fragment
rule; the public-token error shape already used for task refusals; and the
existing live-change test pattern.

The cheapest sufficient option is one session record and one resolver added to
the module that already owns documents. Documentation alone is insufficient
because the resolver is executable behaviour four later slices call. A separate
sessions module would duplicate the store pattern and split one vocabulary
across two files. Deriving the session from the document — no record at all —
cannot hold the machine's available families or a per-run override, which the
goal places on the session.

The machinery that remains is the session store and the resolver, consumed by
slices 4 through 8, plus two small readers — a role's assigned seats and the
`distinct_families` projection — whose consumers the skeleton names. No ledger,
snapshot, version, identity scheme, lease, notification or scheduler is
justified, and none is added. Lifecycle cost is one directory of small records
and one module to maintain; omission blocks every remaining slice; the change is
reversible because no call is staffed through it in this slice.

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| An invalid session write is refused before any byte changes and the prior record survives | Validate-then-atomically-replace, exactly as `orchestrator/staffing.py:615-681` does for documents. | Each malformed shape is asserted to raise and to leave the stored session byte-identical. |
| Every admitted request answers | One resolver function whose only refusals are the two tokens and the input error, under the matrix rows above. | Collapse, saturation, unknown material, unassigned seat and uncarried slot are each asserted to answer. |
| The floor never fails | The in-code seed `orchestrator/staffing.py:1022-1031`, which is the conversion of the profile store's own seed. | A corrupt stored `default` is asserted to answer from the seed, with the fallback reported. |
| Resolution is live and cached nowhere | A store read per call, the pattern the driver already uses at `orchestrator/driver.py:462-470`, proven by editing between calls as `orchestrator/tests/test_model_profile_runtime.py:186,1190,1351` do. | Two identical requests through one caller are asserted to differ after an edit. |
| Resolution writes nothing | Byte comparison of the service home around a resolution; the resolver opens no file for writing. | Every stored file is asserted byte-identical after resolving. |
| Exactly two conditions are surfaced | The public-token error shape of `orchestrator/tasks.py:18-19,126-131`, carrying `staffing_unavailable` or `distinct_families_unsatisfiable`. | Both are asserted by token, and an unknown role is asserted to raise neither. |
| `distinct_families` is judged on the role's own seats | The document's `roles` flag `orchestrator/staffing.py:220-244` read live over the session's layered assignment. | One assigned seat is asserted to resolve; two unsatisfiable seats are asserted to raise; the projection is asserted to follow a document edit. |
| Session overrides need no document to validate | Shape-only validation over the document's own inner shapes `orchestrator/staffing.py:310-341,343-375`; an uncarried slot is answered by collapse, not by validation. | A session naming an uncarried slot is asserted to save and to collapse at resolution. |
| No call's staffing changes in this slice | No dispatch seam is edited; the existing profile and runtime suites already pin today's answers. | The three existing suites are asserted to pass unmodified. |

There is deliberately no enforcement row for markers, routes, run binding,
delivery or freshness: this slice asserts no guarantee about any of them.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's slice-3 row and its session, resolution,
  fallback, surfaced-condition, live-change, seat-reader and verification rows;
  the goal's mandatory resolution paragraph; run amendments A1 and A3.
- **Revise:** no baseline decision. This note settles seven points the skeleton
  leaves to the slice: session ids are assigned by the store and never supplied
  by a caller; sessions live in their own directory beside the documents; a
  session's `overrides` is one unconditional delta in the document's inner
  shape rather than a material-keyed map, applied above the material layer; a
  session validates its own shape only and does not require its referenced
  document to exist, the live reference and the mandatory fallback covering
  absence; an override naming a slot the document does not carry collapses like
  an unavailable family; each matching `step_up` entry applies exactly one step,
  after saturation, so progression is written as data; and an empty `families`
  list is stored as a machine fact and surfaces at resolution rather than being
  refused at save.
- **Reject:** brainstorming and `_drafts` material as authority; the goal
  illustration's literal numbers as a pin; any consumer cutover, run binding,
  resume derivation, route, panel surface, marker write or planner material
  work, all of which belong to later slices; any second rule type or rule
  engine; and any edit to profile files, act sidecars or stored records.

Authority: `implementation/milestones/staffing-router/skeleton.md:291,300-303,309-319,325`;
`implementation/milestones/staffing-router/goal.md:55-83,178-211`; run amendments A1 and A3.
