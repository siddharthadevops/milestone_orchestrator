# Slice 07 — Deep implementation-part delivery

## Register 1 — INTENT (lay language)

### What this slice builds

This slice completes the implementation half of a deep task. After the reviewed
slice note succeeds, the deep task orders implementation part `a` as an ordinary
public reviewed task. The reviewed slice note is part of that child's authority.
The child does the implementation, receives the full review discipline, and
owns its result and gate commit.

Most implementation ends in that first child. If an eligible child instead
finishes a coherent cut and identifies work that remains, the deep task orders
the remainder as part `b`; another cut can produce `c`, and so on. Parts never
run in parallel or appear in advance. Each one starts only from the approved
commit of its predecessor and is reviewed as complete work in its own right.

The parent succeeds only when documentation and every implementation part have
succeeded and the last part reports no remainder. It totals the children's time,
usage, and cost once. It does not replace their commits or copy their native
results into a second source of truth. Failure or operator Stop closes the active
child before the parent and prevents another part from starting.

### Ownership and consumers

The deep parent owns only the sequence: documentation before implementation,
one durable child per part, the hand-off of a recorded remainder, and the final
parent outcome. Every implementation child remains the same public reviewed
task available to a direct caller. Its producer, reviewers, evidence, seal, Git
gate, and accounting retain their existing owners.

The current consumers are the shared standalone task host and store and the
generic task read/Stop surfaces. Calling products can observe the same parent
and children without a product adapter. None of the granted product roots is
changed.

### Guarantee posture

- **Strict:** documentation succeeds before part `a`; one parent/phase/part has
  one durable child id; parts are admitted and gated sequentially; a recorded
  remainder is the next part's scope; every child keeps its native result and
  gate commit; parent terminality follows child terminality; parent accounting
  includes every admitted child exactly once; old records retain their meaning.
- **Best-effort:** physical-call uniqueness, delivery of an interrupt to an
  already-running process, grouping, links, chips, and display freshness. None
  of these can decide admission, success, recovery, or accounting.
- **Optimistic / eventual:** none. This slice adds no queue, redelivery,
  replication, exactly-once call, or eventual-display promise.

### Dependencies

This slice depends on Slices 1–6: the public reviewed-task lifecycle and frozen
policy, routed evidence, gate-backed native result, generic task API, deep
documentation child, durable parent relation, related-child admission, recovery,
retention, and parent Stop fence. It reuses the existing coherent-cut contract,
code-generated part labels, implementation-scope prompt boundary, task-result
vocabulary, and accounting arithmetic.

It adds no third-party dependency, module, service process, route, scheduler,
queue, relationship store, ledger, prompt path, or product integration.

### Non-goals

- No milestone skeleton or deep-slice composition, plan reconciliation, design
  repair, verification cadence, closure, deployment, or run accounting.
- No bare implementation leg, private child API, pre-planned part list,
  parallel part, automatic retry of a failed child, or reopening of a terminal
  child.
- No aggregate Git commit, copied child native result, verification child, or
  milestone-wide/full-suite slot inside `deep_task`.
- No size control owned by `deep_task`, direct `agent_call`, or Brainstorming.
  A Brainstorming-produced reviewed implementation gets no size monitor,
  intervention, grace timer, interruption, stabilizer, or size-driven cut.
- No new public status, error code, event vocabulary, permission rule,
  migration, history backfill, or required panel grouping.
- No defensive parser for child ids, relations, policies, or terminal results
  emitted by this product. Their outcomes are tested; imaginary self-corruption
  is not treated as an attacker.

### Acceptance criteria

After the documentation child has a successful gate-backed result, exactly one
implementation child must be admitted for part `a`. It must be a public
`reviewed_task` with semantic job `implement`, the parent's admitted request and
staffing session, its frozen implementation policy, and the canonical
implementation-part relationship. Its reference material must retain the
parent's ordered references and append the successful documentation artifact
once, inside the admitted workspace. No implementation child may exist before
the documentation gate. An artifact that cannot resolve to a readable path in
that workspace must fail the parent without admitting implementation.

The first child receives the whole admitted implementation request. If an
eligible successful child returns `implementation_cut`, its exact
`remaining_scope` must constrain the next lettered child's production, review,
fix, and delta-review work. The next child cannot be admitted before the
predecessor has its own seal and gate commit. Labels are generated in order and
cannot be supplied by a caller or worker. A successful child with no cut ends
the sequence; a Brainstorming-produced child cannot create a size-driven
continuation.

On normal completion, the parent must close once as `success` only after every
child is successful. On child failure or accepted parent Stop, no later part may
be admitted; any active child must settle before the parent closes once as
`failure`. The parent's duration is the sum of all admitted child results.
Known token and cost fields are summed, and their partial flags are true if any
child is partial or unknown. The canonical child records remain the authority
for native results, review evidence, and gate commits; the parent creates no
aggregate commit or second copy.

Restart and concurrent recovery at every implementation boundary must reuse the
one recorded child id. A crash before its record exists may admit it later; a
crash after the record exists must observe or resume it. A terminal child needed
by an open parent remains undeletable. Existing direct tasks, standalone
reviewed-task cuts, deep documentation behavior, generic routes, and old records
must remain unchanged.

### Risks

The main risks are starting implementation before reviewed documentation,
starting a remainder before its predecessor gate, losing or broadening the
recorded scope, duplicating a child after restart, activating size control for
Brainstorming, and reporting parent success too early. Other risks are replacing
child commits with an aggregate commit, copying charges or native results into a
second authority, accepting Stop while a later part can still start, and making
display grouping authoritative. The focused contracts below expose each fault.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Implementation child identity and authority | After the documentation child succeeds, the first implementation child has `order.task_executor: "reviewed_task"`, `order.configuration.task_kind: "implement"`, and `parent: {"task_id": <deep id>, "phase": "implementation", "part": "a"}`. All implementation children retain the parent's request, context, work area, output destination, staffing session, frozen implementation policy, and ordered references, with one appended reference to the successful reviewed documentation artifact; later children differ only by generated part and current scope. | slice assignment and composition `implementation/milestones/deep-reviewed-tasks/skeleton.md:60-68,115,135-136`; public request/reference contract `orchestrator/tasks.py:468-503`; bounded derived paths `orchestrator/tasks.py:1084-1108`; existing readable-design seam `orchestrator/driver.py:6570-6590`; relation admission `orchestrator/task_api.py:159-218` | touch deep composition and the existing reviewed-state scope seam; do-not-drop or reorder caller references, add a private executor/route/store, trust an out-of-root artifact path, or accept caller-authored `parent` |
| Cut and part vocabulary | An eligible child cut is exactly `implementation_cut: {"cut_scope": <non-empty text>, "remaining_scope": <non-empty text>}`. Product code derives `a`, `b`, `c`, …; a worker cannot name or skip a part. Only a successful, gated predecessor with a cut can cause the next part, whose current scope is that predecessor's exact `remaining_scope`. | cut contract `orchestrator/contracts.py:272-293,862-866`; generated labels and immutable predecessor derivation `orchestrator/state.py:589-659,662-747`; routed scope enforcement `orchestrator/prompts.py:1467-1501`; `orchestrator/author_calls.py:177-191` | touch the hand-off from a child's validated native result into the existing scope contract; do-not-add a plan list, accept model-supplied labels, parse prose for a cut, or admit a successor before the predecessor gate |
| Size-control ownership | `deep_task` owns no size control. Only an implementation `reviewed_task` whose selected producer is `agent_call` may expose and use the existing controller. Direct `agent_call`, direct Brainstorming, and Brainstorming-produced reviewed implementation remain unmonitored and cannot claim a size-driven cut or continuation. | operator amendment A1 as restated in `implementation/milestones/deep-reviewed-tasks/skeleton.md:41-46,132`; applicability `orchestrator/tasks.py:774-805`; runtime exclusion `orchestrator/driver.py:2620-2629` | touch only deep consumption of an eligible child's cut; do-not-monitor the parent, move the controller into an executor, or add Brainstorming size machinery |
| Sequential completion and failure | The deep parent succeeds only after documentation and all discovered implementation children succeed, and only when the last implementation child has no cut. Any child failure or accepted parent Stop prevents later admission and closes the parent as `failure` only after the active child is terminal. Public terminal statuses remain exactly `success` and `failure`. | completion law `implementation/milestones/deep-reviewed-tasks/goal.md:126-130`; Stop and child-first boundary `implementation/milestones/deep-reviewed-tasks/slices/slice-06.md:111-120,155`; result vocabulary `orchestrator/tasks.py:1378-1450` | touch the deep host's post-documentation sequence and terminal projection; do-not-run parts in parallel, auto-retry failure, reopen a terminal task, or report success from a cut |
| Results, accounting, and commits | Each child remains the sole authority for its native result, review evidence, accounting, seal, and gate commit. A terminal parent sums each admitted child's duration, known token usage, and known cost once and propagates partiality; recording the parent result creates no physical charge. There is no aggregate commit or copied/flattened child native result. | ownership `implementation/milestones/deep-reviewed-tasks/skeleton.md:64-68,80-84,115,136`; reviewed native result `orchestrator/driver.py:625-669`; accounting arithmetic `orchestrator/state.py:2270-2332`; null-to-terminal result `orchestrator/tasks.py:1182-1197` | touch one child-result aggregate at parent terminality; do-not-record charge events for the parent, replace child commits, copy child native results, or add a ledger |
| Identity, recovery, and retention | `(parent.task_id, parent.phase, parent.part)` admits at most one logical child. Recovery observes or resumes the exact recorded id, including a terminal child; an open parent's child cannot be deleted. Physical calls retain at-least-once semantics, so logical uniqueness is not a physical exactly-once claim. | composite authority `implementation/milestones/deep-reviewed-tasks/skeleton.md:61-68,80-89,136`; serialized relation `orchestrator/task_api.py:159-218`; retention `orchestrator/service.py:4304-4327`; delivery limit `orchestrator/state.py:1-17` | touch recovery for implementation relations; do-not-infer linkage, create retry ids for one part, reopen records, add a retry ledger, or promise exactly-once calls |
| Public and compatibility boundary | This slice adds no executor id, public route, status, error code, or public event. Parent and children remain visible through `GET /api/tasks` and `GET /api/tasks/<id>`; ordering remains `POST /api/tasks`; parent control remains `POST /api/tasks/<id>/stop`. Existing records are not rewritten or backfilled, and convenience presentation stays best-effort. | public/compatibility law `implementation/milestones/deep-reviewed-tasks/skeleton.md:128,139`; current generic reads `orchestrator/service.py:4649-4699`; current order/Stop routes `orchestrator/service.py:4901-4916` | touch the existing host/store and generic projections only as required; do-not-add deep-specific routes, errors, migrations, product adapters, or execution gates based on display state |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_deep_task_implementation orchestrator.tests.test_deep_task_documentation orchestrator.tests.test_reviewed_task_api orchestrator.tests.test_reviewed_result orchestrator.tests.test_reviewed_policy orchestrator.tests.test_brainstorming_slice_production orchestrator.tests.test_tasks orchestrator.tests.test_task_api`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Documentation gates part `a` and supplies its authority | new `DeepTaskImplementationTest.test_documentation_gate_admits_one_public_part_a_with_frozen_authority` | Before documentation success no implementation relation exists. After its gate, exactly one public implementation reviewed task carries the exact order/relation above and appends one readable in-root documentation reference without dropping or reordering the parent's references. An out-of-root or unreadable artifact admits no implementation child and fails the parent after preserving documentation accounting. | strict |
| Cuts create only the next constrained part | new `DeepTaskImplementationTest.test_cut_chain_gates_a_b_c_and_mounts_exact_remaining_scope` | A cut in `a` creates no `b` until `a` is gate-backed; then `b` receives exactly `a.remaining_scope`. Repeating once produces only `c`; production, review, fix, and delta prompts expose the current scope and no model-supplied label. | strict logical sequencing / best-effort physical-call uniqueness |
| Final success preserves child authority and counts once | new `DeepTaskImplementationTest.test_final_uncut_part_completes_parent_with_child_owned_results_and_single_count_totals` | The parent remains open after each cut, succeeds once after the first uncut part, equals the arithmetic aggregate of documentation plus all implementation children, has no aggregate commit or copied native results, and every child retains its distinct gate/native result. | strict |
| Failure and Stop are child-first | new `DeepTaskImplementationTest.test_failure_and_stop_prevent_successors_and_settle_all_child_accounting` | A failed child or accepted Stop starts no later part. An active child becomes terminal before the parent and work-area release; the parent fails once with every settled child counted once, and a late physical return cannot become success. | strict terminality/accounting / best-effort interrupt delivery |
| Crash and concurrent recovery reuse part identity | new `DeepTaskImplementationTest.test_part_admission_crash_windows_and_races_reuse_exact_child` | Before-write failure leaves no child and permits one later admission; after-write failure and concurrent adopters converge on one id and at most one logical lifecycle for each part. A terminal child retained by an open parent remains recovery authority. | strict logical identity / best-effort physical-call uniqueness |
| Size ownership and compatibility do not move | new `DeepTaskImplementationTest.test_brainstorming_implementation_finishes_without_size_continuation`; retained `ReviewedTaskOrderingTest.test_agent_call_implementation_cut_returns_without_successor`, `ReviewedTaskOrderingTest.test_brainstorming_jobs_reach_the_same_result_without_size_control`, and `ReviewedProducerPolicyTest.test_brainstorming_implementation_refuses_size_control_before_freeze` | Deep sequencing consumes only an eligible agent-call child's cut. Brainstorming emits no size events/cut; a directly ordered reviewed task still creates no successor; direct executors, documentation behavior, routes, and old records do not change. | strict compatibility / best-effort presentation |

Repository-level commands remain:

`python3 -m unittest orchestrator.tests.suite_checkpoint`

`python3 -m unittest orchestrator.tests.suite_extended`

They remain separate checkpoint and architectural gates and must not be claimed
as run unless implementation executes them (`orchestrator/README.md:565-586`).

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | A valid deep order currently completes its reviewed documentation child and then remains open forever; no implementation child can deliver the requested slice. Operators and future generic callers must otherwise place parts manually, risking implementation before the note's gate, lost remainder scope, duplicate paid calls after restart, false parent success, and double-counted spend. Code and records are repairable; spent calls, consumed wrong-order results, and published commits are not cheaply reversible. | assigned need `implementation/milestones/deep-reviewed-tasks/skeleton.md:18-22,60-68,115`; current documentation-only host `orchestrator/task_api.py:847-890` |
| machinery | No new runtime module, public API, or dependency is introduced. This slice extends the existing deep host from documentation settlement through sequential related admission, carries the gated note through the common reference contract, reuses the public reviewed-state lifecycle for every child, passes a validated predecessor remainder through the existing implementation-scope seam, and projects one terminal parent result from child results. Each extension directly serves reviewed authority, ordered delivery, scope hand-off, recovery, or single-count closure. One focused test module is the only new test machinery. | current host/store seams `orchestrator/task_api.py:159-218,691-720,777-890`; request/path seams `orchestrator/tasks.py:468-503,1084-1108`; reviewed-state and routed-scope seams `orchestrator/task_api.py:534-609`; `orchestrator/prompts.py:1467-1501` |
| consumers_touched | Verified runtime consumers touched are the standalone task host and canonical store. The existing service read, Stop, delete-retention, and work-area ownership paths observe their results without a new adapter; each created consumer is the already-public `reviewed_task` lifecycle. Exact-id searches found no runtime consumer in Life, Agent99, life_product_components, or Tutor, so those granted roots remain read-only and no speculative product integration is created. | host/store `orchestrator/task_api.py:59-218,614-890`; service consumers `orchestrator/service.py:4277-4327,4348-4390,4649-4699`; public child lifecycle `orchestrator/driver.py:512-669` |
| cheaper_alternative | Cheapest sufficient is to extend the current deep host, reuse related admission and the public reviewed child, and feed the already-validated remainder into the existing scope contract. Documentation or configuration alone cannot advance a durable parent or close crash windows. Doing nothing leaves every successful deep order open after documentation. A private child, embedded lifecycle, precomputed plan, queue, relationship store, or second accounting ledger duplicates existing solved machinery. | reusable relation/host `orchestrator/task_api.py:159-218,777-890`; existing cut/part machinery `orchestrator/contracts.py:272-293`; `orchestrator/state.py:589-747`; reuse boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:91-104,135-136` |
| cost | Build and review cost is one composition extension plus focused sequential, crash, Stop, and aggregate tests. There is no migration, dependency, daemon, new store, or product rollout. Runtime adds one canonical record and the already-selected reviewed calls/Git gate per discovered part; an uncut implementation adds only one child. Maintenance adds one bounded composite path. Omission costs the entire implementation outcome and invites manual, non-recoverable orchestration. Source changes are Git-reversible; call spend and externally consumed outcomes are not. | dependency posture `orchestrator/README.md:33-46`; current record cost `orchestrator/task_api.py:132-218`; mandated part boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:115,135-136` |
| threat_model | This slice adds no caller-supplied field. New untrusted values consumed are the documentation producer's artifact path and an implementation producer's `implementation_cut` text. The artifact must resolve inside the admitted workspace before becoming reference material; the emitting reviewed lifecycle validates the cut's exact shape and non-empty bounded strings before `remaining_scope` becomes quoted prompt scope. Model edits remain under the existing reviewed/Git boundary. Child ids, parent relations, frozen policies, validated terminal envelopes, and generated labels are trusted product emissions; the note adds no malformed-self-record guards or tests. | path containment `orchestrator/tasks.py:1084-1108`; cut validation `orchestrator/contracts.py:272-293,862-866`; quoted scope `orchestrator/prompts.py:1467-1501`; edit boundary `orchestrator/README.md:551-554`; trusted-emission law `implementation/milestones/deep-reviewed-tasks/skeleton.md:99-104` |
| pinned_facts | The seven hard rows pin only deviations that would break public or cross-slice behavior: child identity, cut/part vocabulary, size ownership, sequential terminality, result/accounting/commit ownership, recovery identity, and the unchanged public/compatibility boundary. Internal helper names, storage traversal, polling, and control flow remain implementation choices. | slice boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:115,132,135-139`; exact cut vocabulary `orchestrator/contracts.py:272-293` |
| verification | Six executable rows add one implementation-composition test module and retain the established deep-documentation, reviewed-result, policy, Brainstorming-size, record, and API proofs. They observe records, routed scope, terminal results, Git commits, provider-call counts, and crash/Stop races. The named focused command pins this slice; repository suites remain separate and unclaimed until run. | current deep proof `orchestrator/tests/test_deep_task_documentation.py:178-268,400-549`; cut/native-result proof `orchestrator/tests/test_reviewed_task_api.py:502-521`; size proof `orchestrator/tests/test_reviewed_policy.py:210-255`; suite authority `orchestrator/README.md:565-586` |
| enforceability | Existing mechanisms enforce bounded readable design paths, validated cuts, generated labels, exact scope mounting, one related child per relation, immutable child terminality, reviewed gate-backed results, Stop fencing, and canonical accounting arithmetic. Three mechanisms are currently absent and are explicit implementation gates: the deep host does not advance after documentation, standalone reviewed state cannot yet receive predecessor-derived part scope, and no terminal projector aggregates multiple child results. Until those gaps are implemented and the named tests pass, Slice 7 cannot claim sequential delivery or deep success. No strict mechanism exists for physical exactly-once calls, interrupt delivery, or display freshness, so those remain best-effort. | existing enforcement `orchestrator/tasks.py:1084-1108`; `orchestrator/driver.py:625-669,6570-6590`; `orchestrator/contracts.py:272-293`; `orchestrator/state.py:589-747,2270-2332`; `orchestrator/task_api.py:159-218,832-890`; scope gap `orchestrator/task_api.py:534-609`; delivery limit `orchestrator/state.py:1-17` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Documentation gates one authoritative implementation child per part | Serialized relation lookup/admission at `orchestrator/task_api.py:159-218`; gate-backed child result at `orchestrator/driver.py:625-669`; derived-path containment at `orchestrator/tasks.py:1084-1108`; existing readable-design check at `orchestrator/driver.py:6570-6590`. | **Current gap:** `_run_deep` stops after documentation at `orchestrator/task_api.py:847-890`. Acceptance requires it to admit/reuse part `a` only from documentation success, carry that child's readable in-root artifact as reviewed authority, and admit each later part only from its predecessor's gated cut. |
| Every later child receives only the predecessor's exact remainder | Cut validation at `orchestrator/contracts.py:272-293`; code-derived labels and predecessor scope at `orchestrator/state.py:589-747`; routed prompt enforcement at `orchestrator/author_calls.py:177-191`. | **Current gap:** standalone reviewed-state creation at `orchestrator/task_api.py:534-609` has no predecessor-derived scope input. Acceptance requires the recorded remainder to reach the existing scope boundary before any production/review call, without changing the public request schema. |
| Size control stays inside eligible agent-call implementation children | Policy applicability at `orchestrator/tasks.py:774-805`; Brainstorming runtime exclusion at `orchestrator/driver.py:2620-2629`; retained focused proofs at `orchestrator/tests/test_reviewed_policy.py:210-255`. | No new controller is needed. Deep composition may inspect only the validated terminal child result; it must not observe repository size, steer, interrupt, or stabilize work itself. |
| Every implementation part is a complete reviewed result with its own gate | Reviewed lifecycle success projection at `orchestrator/driver.py:625-669`; terminal null-to-result mutation at `orchestrator/tasks.py:1182-1197`; existing standalone host at `orchestrator/task_api.py:919-999`. | Acceptance requires each related implementation child to traverse this unchanged public lifecycle. A production result, cut, review, or seal without its gate cannot advance the parent. |
| Parent success/failure is child-first and accounting is single-count | Result contract at `orchestrator/tasks.py:1378-1450`; token/cost arithmetic at `orchestrator/state.py:2270-2332`; terminal/Stop fence at `orchestrator/task_api.py:632-661,813-845`. | **Current gap:** the deep terminal projector accepts only one child result. Acceptance requires one arithmetic projection over all admitted children, with no parent charge event, and an atomic choice between success/failure and an accepted Stop. |
| Restart preserves logical identity without stronger delivery claims | Open-task adoption at `orchestrator/task_api.py:722-769`; related CAS/lock authority at `orchestrator/task_api.py:132-218`; open-parent deletion refusal at `orchestrator/service.py:4304-4327`; at-least-once limit at `orchestrator/state.py:1-17`. | Extend the same recovery path across implementation relations and boundaries. Tests must prove one logical child id and child-first settlement; they must not assert exactly-once physical calls, interrupt delivery, or UI freshness. |
