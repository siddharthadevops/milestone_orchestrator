# Slice 05 — Staffing API

## Register 1 — INTENT (lay language)

### What this slice builds

The staffing router already stores documents and sessions and can answer a
staffing question. This slice makes those capabilities available to the panel
and to calling products through the orchestrator's existing JSON service.

An authenticated caller can see the document catalogue. An administrator can
create or replace a document. A caller with access to a project's work can open
a session for it, inspect it, change its live choices and ask it who should run
a call. A session that cannot satisfy a requested split still opens and remains
readable; its response points out the affected roles, while only an actual
resolution request can refuse on that condition. Every authorized session
owner may write or clear session overrides.

The run detail also names the session a milestone run is bound to. It exposes
the id, not a copied session, so callers use the same live session surface as
everyone else.

### Ownership and boundary

Owned here: the thin HTTP surface over the existing document store, session
store and resolver; authorization through the service's existing identity and
project-membership checks; the live split-family projection on session
responses; the run-summary session id; and focused API tests.

Not owned here: a new document, session or resolver shape; any panel editor;
Brainstorming, standalone-task or work-area-alignment cutover; the planner's
material channel; retirement of model-profile or acts routes; or any new
identity, permission, session-listing or lifecycle machinery.

### Guarantee posture

- **Strict — admitted HTTP contracts.** Successful writes return the stored
  record, successful resolution returns the router's three-value answer, and
  the named admission and staffing failures keep their fixed status and token.
- **Strict — authorization.** Document writes require the existing service
  administrator. Session create, read, edit and resolve require the same live
  project access as the work they name; a session with no project handle stays
  on the existing local-administrator path.
- **Strict — live reads and atomic writes.** A completed document or session
  edit governs the next API resolution. Invalid writes change no stored byte.
- **Optimistic — concurrent edits.** There is no version or compare-and-set;
  complete atomic writes race by last completion, as the stores already do.
- **Best-effort — consequence and delivery.** The run-detail session id and the
  split-family projection decide no acceptance, seal or result. A successful
  response still carries the exact live fields pinned below; no survival,
  notification or reconciliation promise is added outside that response.
- **Eventual — none.** Nothing is replicated, queued or reconciled.

### Dependencies and consumers

This slice depends on slice 2's document store, slice 3's session store,
resolver and split-family projection, and slice 4's run binding and existing
read-only document list. It changes none of those contracts.

Its direct consumers are authenticated calling products, project members and
the local panel service. Slice 8 will build controls on this API. Milestone
dispatches continue to call the router in-process and do not route through
HTTP.

### Acceptance

The slice is accepted when focused tests show that:

- the catalogue remains readable to authenticated members, document writes are
  administrative, whole replacements, and invalid writes preserve prior bytes;
- a project member can create, read, edit and resolve a session for that
  project, including writing and clearing overrides, while a foreign member
  cannot and a workspace-only session remains administrative;
- an unsatisfiable split does not reject session create, read or edit, and the
  affected roles are recomputed after a live document or session change;
- resolution defaults the seat and round, returns exactly the router answer,
  distinguishes invalid input, an unknown session and the two staffing
  conditions, and still uses the default document when the referenced document
  is unreadable;
- editing a session and replacing its document change the next resolution with
  no cache or extra record; and
- a bound run's detail names its session id, while an unbound old run gains no
  invented session and no copied session record.

The implementation is expected to stay below the approximately 500 changed-line
aim: it is a route-and-test slice over existing stores, authorization and
projection seams.

### Risks and non-goals

- A session route authorized from caller-supplied data could cross a project
  boundary. Tests cover an allowed member, a foreign member and a member whose
  project access later changes.
- Treating the split projection as an admission gate would make a readable
  session unusable before any call. Tests keep projection and resolution
  refusal separate.
- Returning a copied session in run detail would create a stale second
  authority. The summary carries only the id.
- A friendly merge on document save would leave removed rules or seats alive.
  Replacement and byte-stable refusal are tested.
- No session list, delete, expiry, lease, owner field, cache, history, event,
  daemon or permission layer is added. No granted read-only root is edited.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Document routes | `GET /api/staffing/documents` returns `{"ok": true, "documents": [...]}` with every stored document in name order and fails loudly on catalogue damage. `POST /api/staffing/documents` is administrative, creates or WHOLLY replaces one document, and returns `200 {"ok": true, "document": <stored>}`. Validation refusal is `400 invalid_staffing_document` and leaves prior bytes unchanged. | `implementation/milestones/staffing-router/skeleton.md:293,322`; existing GET `orchestrator/service.py:4367-4379`; store `orchestrator/staffing.py:692-760`; access precedent `orchestrator/service.py:4691-4694` | touch the existing service route family and focused tests; do-not add patch/merge/delete/version semantics or hide a damaged catalogue |
| Session routes and projection | `POST /api/staffing/sessions` takes the slice-3 create body without `id`, assigns it and returns `201`; `GET /api/staffing/sessions/<id>` returns the stored record; `POST /api/staffing/sessions/<id>` applies a partial edit of exactly `document`, `rigor`, `material`, `overrides`, with explicit null clearing only the optional two. Every successful response is `{"ok": true, "session": <record>, "distinct_families_unsatisfiable": [<role>...]}` with the role list read live. Invalid create/edit is `400 invalid_staffing_session`; unknown id is `404 unknown_staffing_session`. | `implementation/milestones/staffing-router/skeleton.md:293,312,315,322`; store `orchestrator/staffing.py:1416-1549`; projection `orchestrator/staffing.py:2109-2122` | touch thin API adapters only; do-not accept a caller id, edit `id`/`work_area`/`families`, require the referenced document to exist, or fail create/read/edit for an unsatisfied split |
| Session access and authors | Identity is the service's existing request identity. If `work_area` carries a project, create requires live access to that project and later session operations authorize from the stored project handle; without a project handle they require the existing service administrator. Every caller who passes that check may write and clear session overrides; there is no creator check, owner field or new permission rung. Foreign access is `403 forbidden`. | run amendment A3; `goal.md:72-75,244-249`; session handle shape `orchestrator/staffing.py:1308-1343`; identity/access `orchestrator/access.py:42-70`; `orchestrator/service.py:3375-3386,4285-4294` | touch authorization around the routes; do-not add an ACL, persist caller identity, or restrict override authors beyond existing identity and project access |
| Resolve route | `POST /api/staffing/sessions/<id>/resolve` admits exactly `role`, optional `index` (default 1), optional `round` (default 1), optional `material`, optional `brief`; it returns `200 {"ok": true, "staffing": {"agent", "model", "effort"}}`. `brief` changes no answer and is not stored. Unknown session is `404 unknown_staffing_session`; malformed/unknown-key/invalid-value input is `400 invalid_staffing_request`; the router conditions are `503 staffing_unavailable` and `409 distinct_families_unsatisfiable`. These four are admission/condition responses, not new staffing conditions. A referenced document that cannot be read still resolves through the router's default-document fallback; no fallback note is added to the three-key answer. | `implementation/milestones/staffing-router/skeleton.md:100-117,310,314-315,322`; `goal.md:79-83,191-204`; resolver `orchestrator/staffing.py:1582-1622,2001-2044` | touch the HTTP adapter and token mapping; do-not add response keys to the staffing answer, expose `families` in the request, keep router history, or turn an unreadable document into an HTTP failure |
| Run summary | A produced run summary carries `staffing_session: <id>` when the run state is bound and omits the key when it is not. It never embeds a session or document. The existing run-detail access check remains its authorization. | `implementation/milestones/staffing-router/skeleton.md:293`; binding `orchestrator/state.py:467-488`; summary seam `orchestrator/state.py:2365-2372,2768-2829`; authorized detail `orchestrator/service.py:3294-3312,4508-4515` | touch only the summary projection; do-not read a session into it, invent one for an unbound run, or add it to a durable ledger/event |
| Slice boundary | This slice adds no session list/delete route and no panel, dispatch, Brainstorming, standalone-task, git-sync, planner-material or legacy-route work. In-process consumers keep calling the router directly. | `implementation/milestones/staffing-router/skeleton.md:293-301,322-324` | touch service adapters, the summary projection and focused tests; do-not change `orchestrator/staffing.py` contracts, driver call selection, model-profile/acts routes, or any read-only root |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_staffing_api orchestrator.tests.test_staffing_sessions orchestrator.tests.test_staffing_documents orchestrator.tests.test_staffing_driver_cutover`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Document API preserves the store contract | new `test_document_list_save_replace_validation_and_access` in `orchestrator/tests/test_staffing_api.py` | Member GET sees sorted source documents; administrator POST creates then wholly replaces; invalid save returns the fixed token and leaves prior bytes identical; member POST is forbidden; catalogue damage makes GET fail rather than shorten. | strict / optimistic for racing valid saves |
| Session responses are live and do not gate on a split | new `test_session_create_read_and_live_condition_projection` | Create assigns the id and returns the stored record; an unsatisfied split still returns success with the affected roles; a document edit changes the next GET projection; one-seat and restored-distinct cases clear it. | strict |
| Existing project access is the whole session policy | new `test_session_access_and_authorized_override_authors` | A project member creates, reads, writes and clears an override and resolves; a foreign member gets `403 forbidden`; a workspace-only create is forbidden to the member and succeeds for the local administrator; no caller identity is stored. | strict |
| Session edits are partial, atomic and closed | new `test_session_edit_shape_clear_and_byte_stable_refusal` | The four editable fields change without replacing omitted fields; null clears only material/overrides; `id`, `work_area`, `families`, unknown fields and invalid values return the fixed token and leave the record byte-identical. | strict / optimistic for racing valid edits |
| Resolve maps one router answer and its four refusals | new `test_resolve_answer_defaults_fallback_and_error_mapping` | Omitted index/round behave as 1; success contains only the three answer keys under `staffing`; brief changes nothing; malformed input, unknown session, no family and an unsatisfied split return their exact status/token; an unreadable referenced document answers from the default document. | strict |
| API reads are live and add no authority | new `test_session_and_document_edits_reach_the_next_resolution` | Two equal requests around a session edit differ, and two around a document replacement differ; resolution creates no record and returns no history, fallback or projection field inside the staffing answer. | strict |
| Run detail exposes only the binding | new `test_run_summary_exposes_only_the_staffing_session_id` | A newly bound run's authorized detail carries its exact id; an attached unbound run omits the key; neither summary embeds the session/document; existing unknown/foreign run responses stay 404/403. | best-effort projection, strict when produced |

The repository closure gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-524`; `implementation/milestones/staffing-router/skeleton.md:325`).

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These are the slice-scoped remainder. Enforceability is answered again for the
facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | Verified direct consumers: the service handler gains thin document/session/resolve routes; the run-detail consumer gains the bound session id through the existing state summary. The existing document GET from slice 4 is extended with its sibling write. The document/session stores, resolver and project-access policy are reused, not changed; driver, Brainstorming, direct-task, git-sync and panel consumers are not touched. | `orchestrator/service.py:4275-4294,4367-4379,4508-4515,4640-4776`; `orchestrator/state.py:2365-2372,2768-2829`; reused `orchestrator/staffing.py:692-760,1452-1549,2001-2044`; boundary `implementation/milestones/staffing-router/skeleton.md:293-301` |
| pinned_facts | The two document routes and administrative write; the three session routes, exact create/edit shapes and live split projection; A3's any-authorized-owner rule under existing identity/project access; the resolve body's defaults, three-key answer and four fixed status/token mappings; the run summary's id-only projection; and the explicit absence of list/delete, panel, lifecycle or consumer-cutover work. | `implementation/milestones/staffing-router/skeleton.md:293,310,312,314-315,322`; `goal.md:72-83,191-204,244-249`; run amendment A3 |
| verification | The seven-row Verification Contract above pins document replacement and access, session create/read/projection, project authorization and authorized override edits, closed atomic session edits, resolve success/fallback/status mapping, live changes across repeated requests, and id-only run summary exposure. Existing store, resolver and driver-cutover suites run beside the new API suite; closure retains the official full suite. | this note, Verification Contract; `orchestrator/tests/test_staffing_documents.py:229-297`; `orchestrator/tests/test_staffing_sessions.py:857-935`; `orchestrator/tests/test_staffing_driver_cutover.py:2113-2243`; `orchestrator/README.md:522-524` |
| reuse_posture | Affected parties are project members and calling products that cannot yet configure or query the existing router; omission leaves them dependent on in-process consumers, while a wrong access check exposes or changes another project's live staffing. The harm is immediate and reversible by restoring one record. Reused: store validation/atomic replacement, resolver and projection, common JSON envelopes, request identity, project access, administrator gate, existing document GET and run summary. Cheapest sufficient option is thin adapters plus one summary field and one focused test module. No new store, ACL, owner identity, cache, route family, lifecycle or event remains to maintain. | `implementation/milestones/staffing-router/skeleton.md:293,322`; `orchestrator/staffing.py:718-760,1452-1549,2001-2044,2109-2122`; `orchestrator/access.py:42-70`; `orchestrator/service.py:3375-3386,4275-4294,4886-4893` |
| enforceability | Document/session write guarantees are expressible by the existing validate-then-atomic-replace stores; live resolution and the two condition tokens by the existing resolver; the non-gating role projection by the existing projection reader; authorization by identity plus project/admin checks; and id-only run exposure by the existing state key and summary seam. The tests compare prior bytes, make repeated live requests, exercise member/foreign identities and assert exact envelopes. No delivery, survival, freshness-after-response, notification or reconciliation guarantee is asserted. | `orchestrator/staffing.py:718-760,1416-1549,1582-1622,2001-2044,2109-2122`; `orchestrator/access.py:42-70`; `orchestrator/service.py:3375-3386,4285-4294,4846-4893`; `orchestrator/state.py:467-488,2768-2829` |

### Reuse Posture

The affected parties are project members and calling products: the router now
exists, but without this slice only in-process milestone code can configure or
query it. Omission blocks those consumers. A faulty access adapter is the larger
local risk because it could expose or change another project's live staffing;
the effect is immediate, visible on the next request and reversible by restoring
one document or session. The independent authority is the reviewed API slice,
the public-surface row and amendment A3.

The existing document and session stores already validate before atomic whole
replacement; the resolver already owns defaults, fallback and the two condition
tokens; the projection already names affected roles without refusing; the
service already supplies identity, project membership, an administrator gate,
JSON envelopes, a document GET and authorized run detail. All are reused.

The cheapest sufficient option is thin service adapters, one id field in the
existing run summary, and one focused API test module. Documentation alone
cannot make the API callable; a second store, session ACL, owner identity, cache
or generic routing framework duplicates an existing authority and adds ongoing
migration, operation and review cost. None is justified. The remaining
machinery is consumed immediately by external callers and later by the panel;
its omission cost is the missing public contract, while every stored change is
locally replaceable and no legacy record is rewritten.

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Invalid document/session writes change no bytes | Existing validate-before-write and atomic same-directory replacement in `orchestrator/staffing.py:718-760,1452-1549`. | Snapshot bytes before each refused POST and compare after it. |
| Every authorized session owner may edit overrides, and foreign callers may not | Existing request identity plus project membership and administrator checks in `orchestrator/access.py:42-70` and `orchestrator/service.py:3375-3386,4285-4294`; authorization is derived from the stored work-area handle. | Exercise member, foreign member and local administrator against the same route; assert no caller field is stored. |
| Session create/read/edit never fails merely because a split is unsatisfied | The answering read `orchestrator/staffing.py:2109-2122`, separate from the resolver refusal. | Create and read an unsatisfiable session successfully and assert the role list; then resolve and assert 409. |
| A successful resolve is exactly the router's answer and is live | One call to `orchestrator/staffing.py:2001-2044`, whose store reads occur per call, wrapped under one `staffing` member. | Capture the direct resolver answer, compare the HTTP answer, edit between requests and compare again. |
| HTTP failures keep their public classifications | The typed condition codes at `orchestrator/staffing.py:1582-1613`, route admission before resolve, and the service's common error envelope `orchestrator/service.py:4546-4553,4769-4776`. | Assert all four status/token pairs and distinguish them from successful split projection. |
| Run detail exposes the binding without copying it | The one state key `orchestrator/state.py:467-488` projected by the existing summary `orchestrator/state.py:2768-2829` after run access is checked. | Compare the state id with detail, assert no nested session/document, and assert omission for an unbound run. |

There is deliberately no enforcement row for session survival, projection
delivery, notification, history, cache coherence, reconciliation or eventual
convergence: this slice asserts none of them.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's slice-5 and public-surface rows, its
  document/session/resolve, fallback, condition and summary boundaries; amendment
  A3; and the accepted distinction between a non-dispatch read that answers and
  a resolution that may refuse.
- **Revise:** no baseline decision. This note settles only the API envelopes,
  the direct live role-list projection, the authorization mapping from the
  session's existing work-area handle, and the id-only summary projection.
- **Reject:** brainstorming and `_drafts` material as authority; any new
  permission, identity, owner, session list/delete/lifecycle, cache, history,
  ledger or event; and all panel, consumer-cutover, planner-material and
  legacy-route work assigned to later slices.

Authority: `implementation/milestones/staffing-router/skeleton.md:293-301,310,312,314-315,322-325`;
`implementation/milestones/staffing-router/goal.md:72-83,191-204,244-249`; run amendment A3 and accepted amendment B1.
