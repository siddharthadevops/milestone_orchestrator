# Slice 10 — Compatibility and conformance

## Register 1 — INTENT (lay language)

### What this slice builds

This slice adds the final proof that the staffing router works as one system,
not merely as a collection of individually tested parts. It adds no new way to
choose an agent, model, or effort.

For an operator or calling product, the promise is simple: new work is staffed
from its live session and document at the moment each call is made. If work is
stuck, a document's `step_up` rule adds intelligence on the configured round —
first more effort, then a more capable model — and the normal call evidence
shows what actually ran. A completed edit governs the next call and never
changes a call already made.

Unreadable inputs do not strand work. The default document staffs the call and
normal evidence may say that fallback occurred. The two declared staffing
conditions remain the only refusals: creation and read surfaces can describe a
split that cannot currently be honoured, non-dispatch review reads can still
describe their cycle, and a Brainstorming discussion whose seats can be
described still opens. A non-dispatch family read with no available family
raises `staffing_unavailable`; an affected physical dispatch may be refused by
either condition.

Compatibility stays deliberately small. A resumable run without a session gets
the one reference required by amendment A2 and moves on. Already-admitted work
keeps its recorded authority, including old static Brainstorming seats and old
standalone staffing snapshots. Stored `worker` values read as `agent_call`
without rewriting history.

### Ownership and boundary

This slice owns one compact conformance matrix and any smallest correction that
the matrix proves necessary at an already-owned seam. Its runtime default is no
change. It does not own a new document, session, resolver, compatibility lane,
record, route, panel control, marker, cache, retry, migration, or lifecycle.

The matrix crosses the reachable staffing consumers: milestone calls and the
fixer's consultation, attached and standalone Brainstorming automatic calls,
direct Agent-call tasks, and work-area git alignment. It also crosses the
session surface and the stored compatibility shapes needed to prove condition
placement and old-record continuity. Earlier focused suites remain the detailed
authority for each individual seam.

### Dependencies and consumers

This slice follows all nine earlier slices. It depends on their validated
documents and sessions, live resolver, run binding, public API, consumer
cutovers, panel retirement, planner material channel, compatibility reads, and
existing focused tests.

Observable consumers are authorized session owners, milestone operators,
direct task callers, Brainstorming callers, git-alignment callers, and the
review/fix flow receiving staffed results. The repository test suite consumes
the new matrix. No granted read-only repository or external product contract is
changed.

### Guarantee posture

- **Strict — one live dispatch authority.** Every reachable new physical call
  takes `agent`, `model`, and `effort` from one live router resolution. Profile
  contents, post-binding profile selections, act literals, first-family
  defaults, admission snapshots, and projections decide no such call; A2's one
  name-and-rigor derivation remains the stated compatibility input.
- **Strict — configured escalation and live change.** `step_up` starts on its
  declared round and follows the document's capability-ordered ladders. The last
  completed session or document write governs the next call; an in-flight or
  completed call is not rewritten.
- **Strict — fallback and refusal placement.** An unreadable session or document
  never fails, blocks, or retries a dispatch. Exactly
  `staffing_unavailable` and `distinct_families_unsatisfiable` refuse affected
  calls. The non-dispatch family read raises `staffing_unavailable` when no
  family is available to describe; the split condition is descriptive on
  session and non-dispatch cycle reads. Building a Brainstorming roster is also
  not a dispatch: an answerable roster opens, and the split refuses only a later
  call it affects.
- **Strict — compatibility.** Amendment A2 is the entire old-run resume rule.
  Pre-cutover task and Brainstorming records keep their recorded authority, and
  retired `worker` values read as `agent_call`; no stored compatibility bytes
  are migrated or rewritten.
- **Optimistic — completed writes.** Session and document writes remain
  last-completed-write-wins. There is no version, compare-and-set, or mid-call
  arbitration.
- **Best-effort — evidence and projections.** Markers, fallback notes,
  Brainstorming activity, `resolved_staffing`, and read-only projections may be
  absent or stale. When present they identify the completed resolution or call;
  their survival, delivery, and freshness decide no acceptance, seal, or result.
- **Eventual — none.** Nothing here queues, replicates, retries, or converges.

### Acceptance criteria

- A physical milestone call below a `step_up` threshold runs at its tuned rung;
  the first call on the configured round runs at the next intelligence rung,
  and its in-flight evidence names the escalated family, model, and effort.
- Two physical calls around an authorized rigor edit, and separately a document
  replacement, show that only the later call takes the completed change. The
  same live-reference rule is proven across the milestone, Brainstorming,
  direct Agent-call, consultation, and git-alignment entry seams without
  copying a staffing answer between them.
- An absent or unreadable session, referenced document, or stored `default`
  still permits each affected consumer's next call on the fallback answer. A
  normal marker, activity entry, or sync outcome includes
  `staffing_fallback: "default_document"` where that surface records calls; the
  resolver answer itself remains exactly `agent`, `model`, and `effort`.
- Session create/read reports an unhonourable declared split without refusing
  the session. The review cycle's family read answers that same split without
  dispatching or failing the run. A router-backed Brainstorming create whose
  assigned seats share one family under that declaration also succeeds,
  records that roster, and makes no provider call; the split is refused only if
  a later Brainstorming dispatch is attempted. With no family available, the
  non-dispatch family read raises `staffing_unavailable` rather than supplying
  an empty cycle. Either token stops an affected physical dispatch before any
  provider call, and no third token appears.
- A run resumed without a bound session follows amendment A2 exactly: it binds
  once to the selected profile-named document and rigor, or to `default` when
  the name is absent or unknown; it derives no act override, edits no profile,
  act sidecar, or document, and never blocks resume if binding cannot be made.
- A pre-cutover standalone Agent-call/`worker` record runs its frozen staffing;
  a pre-cutover static Brainstorming record runs its stored seats; a
  pre-cutover attached current-profile record takes its owner's live session.
  Each stored record remains byte-unchanged except for its already-authorized
  terminal result.
- Stored task orders, producer selections, and agent-returned slice plans using
  `worker` project and route as `agent_call`; new writes continue to reject the
  retired id, and no migration rewrites the stored spelling.
- A closed consumer inventory proves that every reachable new physical agent
  call enters through the router-backed seams above. Retained profile/act
  helpers are limited to conversion, A2's name-and-rigor read, old-record
  compatibility, or a home-less in-process construction with no operator or
  product entry point; none staffs a reachable new call.
- The focused conformance module and the repository's complete suite pass at
  their respective gates.

### Non-goals

- No compatibility machinery beyond A2's one derivation; no migration or
  backfill.
- No change to document/session shape, capability order, role vocabulary,
  material validation, resolution precedence, review rotation, round caps,
  convergence, sealing, or the B1 non-dispatch family read.
- No restriction on which authorized session owner may write an override. No
  creator field, owner rung, new identity, or permission system.
- No stronger survival or freshness promise for markers, activity, projections,
  planner proposals, or `resolved_staffing`.
- No new error token, rule type, staffing answer member, route, panel surface,
  event, ledger, snapshot, cache, acknowledgement, notification, queue, or
  retry.
- No edits to generated milestone ledgers or any granted read-only root.

### Risks

- A resolver-only test could miss a consumer that still staffs a real call from
  profile contents, an act literal, a first family, or a stale snapshot.
- A broad new end-to-end harness could duplicate the large focused fixtures and
  become more expensive than the contract it protects.
- Testing fallback only at the resolver could miss a consumer that turns a valid
  fallback into a failed call or drops normal evidence.
- Treating a session's split projection, a review-cycle read, or Brainstorming
  roster construction as a dispatch would move
  `distinct_families_unsatisfiable` earlier than B1 permits. It could discard
  already-earned clean review evidence or refuse a discussion before any call.
- A compatibility test that synthesizes session overrides from old act literals
  would itself create the machinery A2 forbids.
- Requiring bookkeeping to survive injected storage loss would silently upgrade
  a best-effort surface into a delivery guarantee.

### Reuse Posture

The affected parties are operators and calling products. Without a closing
composition proof, individually correct seams can still disagree about the next
call, apply escalation one round late, block on a readable fallback, move a
split refusal to a non-dispatch read, or revive a retired staffing input. Those
faults are visible in the call that runs and reversible for later calls, but the
cost or quality of a completed call cannot be taken back. The reviewed
skeleton's Slice 10 row independently requires this conformance proof.

Checked and reused are the resolver matrix; physical dispatch hooks and marker
retargeting; the three live review reads; session create/read projection; run
binding and A2 tests; Brainstorming's roster-family read, seat resolver and
activity; direct-task dispatch and legacy snapshot boundary; git-sync's
eligible-call boundary; the read-time TaskExecutor alias; and every earlier
focused staffing suite. The cheapest sufficient option is one compact matrix
that composes those real seams and, for the proven Brainstorming creation
defect, reuses the answering family read for the roster while leaving the
existing resolver at the physical-call boundary. Documentation alone cannot
catch composition drift; a second runtime, store, compatibility adapter, or
runtime scanner would duplicate existing authority.

No new runtime machinery is justified. The remaining lifecycle cost is test
fixtures, assertions, and review, plus only a proportional correction if a
failing conformance case exposes a real seam defect. There is no migration,
deployment, service, retention, or operational cost. Omitting the matrix leaves
cross-surface drift undetected; stronger machinery would protect deliberately
best-effort evidence or preserve old literals the operator expressly chose not
to carry.

### Size posture

This slice is expected to remain under about 500 non-mechanical changed lines.
One compact conformance module should reuse existing fixture builders and
contracts. A production edit is justified only by a failing matrix case and is
limited to the smallest already-owned seam correction.

### Planning Material Disposition

- **Adopt:** the current reviewed skeleton, amendments A1–A3 and B1–B2, and the
  contracts already sealed by slices 1–9.
- **Revise:** no reviewed design decision. This note makes Slice 10's broad
  “end to end” row executable as a compact cross-surface matrix.
- **Reject:** `implementation/brainstorming`, `implementation/_drafts`, and any
  generated planning copy as authority; any parallel staffing or compatibility
  machinery proposed only to make the closing proof easier.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| One reachable dispatch authority | Every new reachable physical call made by the milestone driver or consultation subprocess, a router-backed Brainstorming seat/classifier/effect, a direct Agent-call task, or git alignment takes its final `agent`, `model`, and `effort` from `staffing.resolve` over the owner's session. A public resolve request exposes the same three-key answer. Apart from A2's one-time name-and-rigor derivation, no profile content or selection, act literal, first-family default, order snapshot, projection, or copied resolution staffs one of those calls. | `implementation/milestones/staffing-router/skeleton.md:11-20,118-136,298,310,316-318,321-325`; catalogue-home boundary `implementation/milestones/staffing-router/slices/slice-04.md:277`; driver dispatch `orchestrator/driver.py:814-869,8442-8455,8508-8519`; consultation `orchestrator/current_model_call.py:15-50`; Brainstorming `orchestrator/brainstorming_lifecycle.py:555-615,2964-3026,3028-3086,3099-3142`; direct task `orchestrator/task_api.py:176-226,331-387`; git alignment `orchestrator/service.py:3622-3713` | touch one compact conformance inventory and only a proven seam defect; do-not add a resolver, adapter, cache, copied answer, or alternate physical-call path |
| Escalation and live change | A `step_up` entry applies from `min_round`; each matching entry adds one step after rank saturation: effort first, then the next model at its first effort, saturating at the top. Model ladders are capability order, never price order. Each physical dispatch reads again, so the last completed document/session write governs the next call and the normal marker is retargeted to that answer. | amendment A1; `implementation/milestones/staffing-router/skeleton.md:95-111,196-207,298,313,316,325`; rule enforcement `orchestrator/staffing.py:1869-1904,2001-2044`; physical hook and marker `orchestrator/runners.py:2940-2962`, `orchestrator/driver.py:3307-3379,3586-3647`; lower-level proof `orchestrator/tests/test_staffing_sessions.py:606-647`, `orchestrator/tests/test_staffing_driver_cutover.py:780-835` | touch cross-boundary escalation/live-edit assertions; do-not reorder ladders, infer price, freeze a resolution, rewrite a completed call, or add write arbitration |
| Fallback and condition placement | An unreadable session, referenced document, or stored `default` resolves through the default-document floor and never fails, blocks, or retries a dispatch; call-recording surfaces may add `staffing_fallback: "default_document"` beside what ran, while the answer stays three keys. Only `staffing_unavailable` and `distinct_families_unsatisfiable` refuse calls. Session create/read projects an unhonourable split without refusal; `session_seat_families` describes it without dispatching. A router-backed Brainstorming create uses that descriptive answer to record its roster and is not an affected dispatch; the split token occurs only if a later physical call is made. With no available family, the family read still raises `staffing_unavailable`. | `implementation/milestones/staffing-router/skeleton.md:33-40,112-117,298,314-315,319,324-325`; fallback/conditions/read `orchestrator/staffing.py:1697-1739,1911-1968,2001-2106`; Brainstorming create seam `orchestrator/brainstorming_lifecycle.py:960-1051,1928-1962`; API projection/mapping `orchestrator/service.py:2106-2118,2204-2216,2267-2295`; lower-level proof `orchestrator/tests/test_staffing_api.py:281-360,536-660`, `orchestrator/tests/test_staffing_driver_cutover.py:1888-2060` | touch the conformance case and proven Brainstorming create seam only; do-not add a token or read, fail an answerable roster or unreadable input, expose fallback in the answer, refuse a descriptive read, or move review law into the router |
| Resume compatibility (A2) | A run resuming without a staffing session binds once to the document named by its `model_profile.json` selection at that rigor, or `default` when the name is absent or unknown, with its current configured families. Nothing else is derived: no `acts.json` literal is carried or turned into a session override; no document, profile, or act sidecar is written; inability to bind never blocks resume and later calls use visible fallback. | amendment A2; `implementation/milestones/staffing-router/skeleton.md:118-136,298,324-325`; selection/binding `orchestrator/driver.py:443-459,628-665,8365-8419`; existing proof `orchestrator/tests/test_staffing_driver_cutover.py:2129-2224` | touch the conformance fixture only unless it proves this seam wrong; do-not add compatibility levels, read an act literal, synthesize an override, migrate state, write a document, or fail resume |
| Pre-cutover records and rename | A standalone task order with no `staffing_session` retains its frozen Agent-call/`worker` snapshot; a stored explicit-static Brainstorming record retains its pins; a pre-cutover attached current-profile record resolves through its owner's supplied session. Stored orders, producer selections, and agent-returned plans saying `worker` read as `agent_call`; new writes accept only `agent_call`. Compatibility is read-time and does not rewrite the stored spelling or other record bytes. | `implementation/milestones/staffing-router/skeleton.md:47,135-136,298,320,324-325`; alias `orchestrator/tasks.py:97-130,296-310`; standalone boundary `orchestrator/task_api.py:176-226,331-341`; Brainstorming boundary `orchestrator/brainstorming_lifecycle.py:154-223,1140-1160,1552-1579`; existing proof `orchestrator/tests/test_task_conformance.py:99-180`, `orchestrator/tests/test_staffing_standalone_cutover.py:1116-1404`, `orchestrator/tests/test_staffing_brainstorming_cutover.py:1324-1381,1546-1574` | touch compatibility assertions and only a proven read seam; do-not migrate, backfill, re-resolve a frozen old task, turn a static record live, accept `worker` on a new write, or represent old literals in a session |
| Evidence posture | When present, milestone markers, direct-task markers, Brainstorming activity, and git-sync outcomes identify the family, model, and effort the physical call ran; fallback-recording surfaces add the fixed note. These records and all projections remain best-effort and never become dispatch input or acceptance/seal/result authority. | `implementation/milestones/staffing-router/skeleton.md:72-76,112-117,298,317,325`; milestone marker `orchestrator/driver.py:3307-3379`; direct marker `orchestrator/task_api.py:346-432`; Brainstorming activity `orchestrator/brainstorming_lifecycle.py:2826-2871`; sync outcome `orchestrator/service.py:3691-3713` | touch normal conformance observation only; do-not add lost-value fault injection, persistence, replay, freshness, acknowledgement, or a staffing ledger |
| Verification and slice boundary | `orchestrator/tests/test_staffing_conformance.py` is the compact cross-surface matrix; earlier staffing and rename suites remain lower-level authority. Final closure runs exactly `python3 -m unittest discover -s orchestrator/tests -t .`. Production changes are permitted only for an existing contract violation exposed by the matrix. Slices 1–9, amendments A1–A3/B1–B2, generated ledgers, and granted read-only roots otherwise remain untouched. | planned scope `implementation/milestones/staffing-router/skeleton.md:298-303,325`; official suite `orchestrator/README.md:535-545`; existing focused surfaces `orchestrator/tests/test_staffing_sessions.py:488-967`, `orchestrator/tests/test_staffing_api.py:276-762`, `orchestrator/tests/test_staffing_driver_cutover.py:261-2422`, `orchestrator/tests/test_staffing_brainstorming_cutover.py:506-2077`, `orchestrator/tests/test_staffing_standalone_cutover.py:301-1404` | touch one focused conformance module and the smallest proven seam correction; do-not duplicate every earlier matrix, narrow the full suite, reopen a sealed surface without evidence, or edit generated/read-only files |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_staffing_conformance`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Escalation and live edits reach physical calls | `test_step_up_marker_and_live_edits_cross_the_dispatch_boundary` | A physical call below `min_round` runs at base; the configured round runs one intelligence rung higher and its normal marker agrees. A completed rigor edit and document replacement each change only the following physical call, including an edit written by an authorized non-creator through the existing session surface. | strict call/answer; best-effort marker |
| Fallback and conditions keep their exact placement | `test_fallback_and_condition_placement_conforms_across_consumers` | Representative milestone, Brainstorming, direct-task, consultation, and sync calls use the fallback answer without dispatch failure; their normal evidence records the fixed note where supported. Session create/read and the B1 cycle read describe an unhonourable split. Under a valid document that assigns all Brainstorming seats to one family and declares `distinct_families`, Brainstorming creation succeeds with that roster and no provider call; its first affected dispatch then refuses with `distinct_families_unsatisfiable`. With no available family, the B1 cycle read raises `staffing_unavailable` rather than returning an empty cycle. Either token stops an affected physical call before the provider, and no third token appears. | strict dispatch/placement; best-effort evidence |
| A2 derives once and nothing else | `test_resume_derivation_defaults_and_moves_on` | Selected, unknown-name, absent-selection, and unbindable resumes match the A2 row; the session id is stable, no act literal becomes an override, source bytes are unchanged, and the unbindable run remains runnable through visible fallback. | strict |
| Old records keep their own authority and spelling | `test_pre_cutover_records_and_worker_alias_remain_read_only` | Frozen standalone Agent-call/`worker`, static Brainstorming, and attached current-profile fixtures each run under the pinned compatibility row; only the allowed terminal result changes. Stored task and plan `worker` values project/route as `agent_call`, while a new `worker` write is refused. | strict |
| Every reachable new call has one authority | `test_reachable_consumer_inventory_has_no_parallel_staffing_path` | The closed runtime consumer inventory reaches the router at each physical call with the correct session, role, seat, round, and admitted material/brief boundary. After A2 binding, poisoning profile contents/selection, acts, first-family defaults, `resolved_staffing`, and projections changes no new call. Retained legacy helpers have only the explicitly pinned conversion/A2/old-record/home-less uses. | strict |

The earlier `orchestrator.tests.test_staffing_sessions`,
`orchestrator.tests.test_staffing_api`,
`orchestrator.tests.test_staffing_driver_cutover`,
`orchestrator.tests.test_staffing_brainstorming_cutover`,
`orchestrator.tests.test_staffing_standalone_cutover`,
`orchestrator.tests.test_staffing_documents`,
`orchestrator.tests.test_staffing_panel`, and
`orchestrator.tests.test_task_conformance` suites remain the detailed branch
proof. Final closure runs exactly
`python3 -m unittest discover -s orchestrator/tests -t .`.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These five rows are the slice-scoped remainder; enforceability is answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | Verified observed consumers: the homed milestone driver's physical dispatch hook, review seats and consultation subprocess; Brainstorming automatic participant, classifier and production-effect calls for attached and standalone records; the direct Agent-call host; eligible git alignment; the session create/read/resolve surface; stored task/producer readers; and their focused tests. Verified untouched except for a matrix-proven defect: document/session schemas and stores, panel behavior, planner material, review convergence/sealing, profile conversion, generated ledgers, and all additional roots. | driver `orchestrator/driver.py:814-869,3586-3647,8365-8795,9005-9039`; consultation `orchestrator/current_model_call.py:15-50`; Brainstorming `orchestrator/brainstorming_lifecycle.py:555-615,1778-1860,1939-2054,2964-3142`; direct `orchestrator/task_api.py:176-226,331-432`; sync/API `orchestrator/service.py:2071-2295,3622-3713`; alias `orchestrator/tasks.py:97-130,296-310`; boundary `implementation/milestones/staffing-router/skeleton.md:298-303` |
| pinned_facts | The hard table pins one live authority for every reachable new physical call; capability-ordered `step_up` and next-call edits; the fallback floor, two-token vocabulary and B1 condition placement; A2 in full; frozen old standalone/static authorities and attached-session continuity; read-only `worker` aliasing; best-effort evidence; and the focused/full verification gates. | `implementation/milestones/staffing-router/skeleton.md:95-136,196-207,298,310,313-325`; enforcement `orchestrator/staffing.py:1869-2106`; compatibility `orchestrator/driver.py:8365-8419`, `orchestrator/tasks.py:97-130` |
| verification | One compact five-case conformance module crosses physical escalation plus marker evidence, authorized live edits, fallback and both condition placements across consumers (including the non-dispatch unavailable-family read and Brainstorming split creation versus dispatch), A2 derivation, all retained old-record authorities, read-only `worker` aliasing, and the closed reachable-consumer inventory. Existing focused suites remain the branch-level proof; repository discovery is the final gate. No check upgrades best-effort evidence into a survival or delivery promise. | planned scope `implementation/milestones/staffing-router/skeleton.md:298-303,325`; current lower-level matrices `orchestrator/tests/test_staffing_sessions.py:527-967`, `orchestrator/tests/test_staffing_api.py:281-690`, `orchestrator/tests/test_staffing_driver_cutover.py:261-2422`, `orchestrator/tests/test_staffing_brainstorming_cutover.py:506-2077`, `orchestrator/tests/test_staffing_standalone_cutover.py:301-1404`; suite `orchestrator/README.md:535-545` |
| reuse_posture | Affected parties are operators and calling products; omission can leave a real call misstaffed, wrongly refused, or governed by stale compatibility data, with the completed call's cost/quality irreversible though later calls are editable. Authority is the reviewed Slice 10 row. Checked/reused: resolver and condition matrices, dispatch hooks, marker/activity/outcome evidence, the public roster-family read, review reads, API projection, run binding, old-record fixtures, alias readers, and existing suites. Cheapest sufficient is one composition matrix plus the proven Brainstorming seam correction: describe the creation roster through the existing family read and retain `staffing.resolve` for the later physical call. A new runtime/store/adapter/scanner or router read duplicates authority. Remaining machinery is test fixtures/assertions and that bounded consumer correction; it carries no migration/operation/retention cost. Omission leaves every such valid discussion uncreatable until configuration changes. | authority `implementation/milestones/staffing-router/skeleton.md:258-283,298-303,319`; resolver/read `orchestrator/staffing.py:2001-2122`; defect seam `orchestrator/brainstorming_lifecycle.py:631-651,960-1051`; consumer tests `orchestrator/tests/test_staffing_driver_cutover.py:261-2422`, `orchestrator/tests/test_staffing_brainstorming_cutover.py:506-2077`, `orchestrator/tests/test_staffing_standalone_cutover.py:301-1404` |
| enforceability | One authority is enforceable at each physical dispatch hook and by a closed consumer inventory. Escalation/capability order is enforced by the stored ladder plus `_step_up_steps`/rung progression; liveness by per-call store reads. Fallback and two-token placement are enforced by the single resolver, three shared reads and API/consumer mappings. A2 is enforced by the one absent-session binding path; old records by field-presence discriminators and frozen authorities; `worker` by the read alias at every stored-value projection/routing seam. Marker/activity/projection survival and freshness have no strict mechanism, so this note promises none. No asserted guarantee needs a new runtime mechanism. | physical hooks `orchestrator/runners.py:2940-2962`, `orchestrator/driver.py:814-869`, `orchestrator/brainstorming_lifecycle.py:555-615`, `orchestrator/task_api.py:202-226`, `orchestrator/service.py:3674-3713`; resolver/reads `orchestrator/staffing.py:1697-1739,1869-1904,1975-2122`; A2 `orchestrator/driver.py:628-665,8365-8419`; old-record gates `orchestrator/tasks.py:724-747`, `orchestrator/task_api.py:176-226`, `orchestrator/brainstorming_lifecycle.py:1140-1160`; alias `orchestrator/tasks.py:97-130,296-310` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| A reachable new physical call gets one live router answer | The shared physical dispatch hook and each consumer's router-backed adapter at `orchestrator/runners.py:2940-2962`, `orchestrator/driver.py:814-869`, `orchestrator/brainstorming_lifecycle.py:555-615`, `orchestrator/task_api.py:202-226`, and `orchestrator/service.py:3674-3713`. | Exercise the closed consumer inventory while poisoning every retired input; assert each provider call and normal evidence match the captured router request. |
| `step_up` begins on the declared round and live edits govern only later calls | Whole-document validation supplies ordered ladders; `orchestrator/staffing.py:1869-1904,1975-2044` applies the rule from live reads; the dispatch hook runs again per physical call. | Make physical calls below/at the threshold and around completed session/document edits; compare provider identities and the normal marker. |
| Unreadable inputs dispatch, while only two conditions refuse at their pinned placement | The three-level floor and two typed conditions live in `orchestrator/staffing.py:1697-1739,1947-1968,2001-2044`; the family read's B1 placement is `orchestrator/staffing.py:2079-2106`; API projection/status mapping is `orchestrator/service.py:2106-2118,2204-2216,2267-2295`. Brainstorming creation already has the persisted roster and the later pre-provider resolver seam, so it needs no additional router answer. | Cross representative consumers; assert fallback reaches the provider, split projects/reads, an answerable Brainstorming roster is created without a provider call, the B1 family read raises `staffing_unavailable` instead of supplying an empty cycle when no family is available, and either token stops an affected dispatch before the provider. |
| A2 binds once, derives nothing else, and never blocks resume | The absent-session derivation and write-once binder at `orchestrator/driver.py:628-665,8365-8419`; the resolver floor answers an unbound run. | Compare session and source bytes for selected/default/unbindable resumes, then make the next call. |
| Pre-cutover authorities and `worker` spellings remain read-only | Field-presence gates at `orchestrator/tasks.py:724-747`, `orchestrator/task_api.py:176-226`, and `orchestrator/brainstorming_lifecycle.py:1140-1160`; read alias at `orchestrator/tasks.py:97-130,296-310`. | Run each stored shape, compare bytes except the legal terminal result, project/route old spellings, and refuse a new retired-id write. |

No contract-enforcement design gap remains. The matrix explicitly exposes the
known Brainstorming creation seam defect and pins its correction to the existing
family read plus physical-dispatch resolver; no new router contract is needed.
The other strict claims have a live dispatch hook, typed resolver condition,
write-once binding, field-presence discriminator, or read-time alias. Surfaces
without a strict persistence or freshness mechanism are explicitly best-effort.
