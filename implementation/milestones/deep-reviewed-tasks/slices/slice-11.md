# Slice 11 — Five-slice and final verification cadence

## Register 1 — INTENT (lay language)

### What this slice builds

For newly activated runs, complete repository verification becomes a milestone
step of its own. The milestone orders it after each five completed slices and
before final closure. It is separate from the slice that came before it, and it
does not make the next slice wait on hidden work inside that earlier slice.

The fifth slice must be fully delivered before verification is due. A slice
split into implementation parts still counts once. Once verification is due,
later slice work and milestone closure wait for its successful reviewed result.

At the end, the milestone needs proof for the repository content it is actually
closing. If the periodic verification already proves that same active content,
the milestone uses it instead of ordering a duplicate. Changed content or work
superseded by reconciliation cannot satisfy final closure.

### Ownership and scope

Milestone law owns when verification is due and whether later work may start.
The existing reviewed verification task owns the suite run, any repair, review,
evidence, accounting, seal, and gate. This slice joins those two existing
boundaries; it does not create another verifier or review cycle.

Runs that started under the earlier cadence finish under that law. Their
in-slice verification and history are not reclassified, rewritten, or copied
into sibling tasks. The granted product roots remain read-only.

### Guarantee posture

- **Strict:** prospective activation; five completed logical slices per periodic
  boundary; one active milestone verification attempt per due boundary; no
  later slice or closure past an open or failed due verification; current active
  content at final closure; no duplicate when periodic and final needs coincide;
  and unchanged pre-activation behavior.
- **Best-effort:** physical-call uniqueness, interrupt delivery, task grouping,
  and display freshness retain their existing posture.
- **Optimistic / eventual:** none. This slice adds no queue, redelivery,
  replication, or eventual-presentation promise.

### Dependencies

This slice depends on prospective milestone composition, successful deep-task
closure as the logical-slice boundary, the existing sibling reviewed
verification task, durable task history and results, current-content gate proof,
accepted-plan reconciliation, and the milestone's advancement and close gates.

### Non-goals

- No new task type, public route, order field, result status, error code, suite
  runner, prompt route, review path, fixer, seal rule, or Git operation.
- No verification child inside a deep task and no counting verification as a
  slice.
- No panel/card work, compatibility backfill, history rewrite, migration,
  scheduler service, queue, cache, notification, retry ledger, or dependency.
- No change to focused checks owned by ordinary reviewed work.
- No Brainstorming or implementation-size behavior and no edit in a granted
  product root.

### Acceptance criteria

On an activated run, completion of the fifth successful deep task admits one
sibling reviewed verification task before any work for slice six. Multiple
implementation parts count as their one enclosing logical slice. While that
verification is open or failed, neither the next deep task nor milestone close
may advance.

Successful verification permits advancement from its own terminal result and
gate. Recovery at admission, result, and gate boundaries observes the already
recorded attempt and does not place another active attempt for the same due
boundary.

A short milestone orders final verification after its last slice. A final slice
that also reaches a five-slice boundary produces one task, not two. An earlier
five-slice success is reused at final closure only while its certified content
and active ancestry are still current; later content changes or reconciliation
supersession make verification due again.

Activated runs perform no periodic or final complete-suite work inside a slice.
Pre-activation runs retain the four-slice and final in-slice chronology. Direct
reviewed verification orders, deep-task behavior, and existing task records stay
unchanged.

### Risks

The main risks are counting implementation parts as slices, scheduling from a
pre-gate slice-close event, opening the next slice before verification succeeds,
duplicating a task after a crash or coincident final boundary, reusing stale or
rollback-superseded proof, treating terminal failure as success, or changing an
already-started run. Pulling presentation or new suite machinery into this slice
would also violate its boundary.

## Register 2 — PINNED FACTS (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Prospective activation and legacy law | Only runs initialized with this cadence law use sibling verification. Runs without it retain `FULL_VERIFICATION_SLICE_INTERVAL = 4` and the in-slice `four_slice_checkpoint` / `milestone_final` chronology; their events and task history are neither rewritten nor backfilled. | compatibility mandate `implementation/milestones/deep-reviewed-tasks/goal.md:188-208`; prospective-init precedent `orchestrator/driver.py:14696-14705`; retained legacy assertion `orchestrator/tests/test_reviewed_complete_verification.py:409-430` | touch one prospective run binding and its branch; do-not-change the legacy constant/vocabulary, reinterpret old events, or migrate existing runs |
| Sibling five-slice boundary | After each five terminal-successful logical-slice `deep_task` results, admit one top-level `reviewed_task` with `configuration.task_kind: "complete_verification"`. It has no `parent`, does not count as a slice, and must succeed before the next deep task starts. Implementation parts count once through their enclosing deep task. Catalogue ids remain exactly `agent_call`, `brainstorming`, `reviewed_task`, and `deep_task`; no `verification_task` or route is added. | assigned slice `implementation/milestones/deep-reviewed-tasks/skeleton.md:138`; milestone contract `implementation/milestones/deep-reviewed-tasks/skeleton.md:157`; existing kind `orchestrator/tasks.py:23-38`; deep completion `orchestrator/driver.py:4591-4618`; generic routes `orchestrator/service.py:4649-4699,4906-4916` | touch milestone admission and advancement over the existing reviewed task; do-not-use a slice event before deep success, add parentage, change the public catalogue/routes, or call the standalone host |
| Due-task durability and blocking | A recorded open or terminal-failed due verification blocks later slice admission and milestone close. Recovery reuses the recorded open task for that boundary; task identity/order are immutable and its result moves only from `null` to one terminal value. Success requires the existing native reviewed result and its own `gate_commit`; physical calls remain at-least-once. | required refusal `implementation/milestones/deep-reviewed-tasks/goal.md:249-252`; task admission/result `orchestrator/tasks.py:1284-1327`; append-only task enforcement `orchestrator/state.py:385-433`; reviewed success result `orchestrator/driver.py:680-730` | touch durable due-boundary association plus advancement/closure predicates; do-not-reopen a terminal task, infer success from a call/event, add a queue, or promise physical exactly-once delivery |
| Final current-content reuse | Final closure requires one successful milestone-scheduled verification whose certified repository content and ancestry are current. Reuse an already-current five-slice task, including a coincident fifth/final boundary, without admitting another. A later candidate change or reconciliation supersession prevents reuse and leaves verification due. | final reuse contract `implementation/milestones/deep-reviewed-tasks/skeleton.md:138,157`; mandate `implementation/milestones/deep-reviewed-tasks/goal.md:156-169`; current-proof gate `orchestrator/driver.py:1829-1852,14177-14239`; reconciliation validity `orchestrator/state.py:1438-1493` | touch final-close certification lookup and active-history filtering; do-not-reuse a direct standalone task, a stale tree, or superseded history, and do-not duplicate a current periodic task |
| Verification | Focused command: `python3 -m unittest orchestrator.tests.test_milestone_verification_cadence orchestrator.tests.test_reviewed_complete_verification orchestrator.tests.test_milestone_deep_slice_composition orchestrator.tests.test_verification_chronology orchestrator.tests.test_plan_reconciliation orchestrator.tests.test_state orchestrator.tests.test_tasks`. New checks named `test_five_completed_deep_tasks_admit_one_sibling_before_slice_six`, `test_parts_count_once_and_open_or_failed_verification_blocks`, `test_final_reuses_only_current_active_five_slice_verification`, `test_crash_and_reconciliation_never_duplicate_or_reuse_superseded_verification`, and `test_activation_replaces_only_new_runs_in_slice_cadence` must pass. Checkpoint and extended suites remain separate and unclaimed until run. | existing cadence cases `orchestrator/tests/test_verification_chronology.py:323-509,561-620`; sibling task cases `orchestrator/tests/test_reviewed_complete_verification.py:175-213,275-407`; deep boundary cases `orchestrator/tests/test_milestone_deep_slice_composition.py:97-202`; suite authority `orchestrator/README.md:565-586` | touch one focused cadence module and the retained chronology expectations; do-not weaken existing task/deep/reconciliation tests or claim unrun repository suites |

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Operators and milestone consumers currently receive complete verification inside the fourth/final implementation unit, so there is no sibling task result at the mandated five-slice boundary and current closure can proceed without that sibling gate. The realistic harm is misowned evidence/repair/accounting or later work starting before the required proof. Git changes are reversible; spent calls and a falsely advanced run are not. | assigned need `implementation/milestones/deep-reviewed-tasks/skeleton.md:138,157`; current placement `orchestrator/state.py:19-25`; current cadence `orchestrator/driver.py:1916-1932`; current close predicate `orchestrator/state.py:1545-1580` |
| machinery | Add one prospective cadence binding and extend existing milestone admission, advancement, active-history lookup, and close predicates to order/observe the Slice 10 reviewed verification task. Add one focused test module. Existing task records, lifecycle, Prompt Router, suite/fix/review path, Git gate, reconciliation barriers, and accounting are reused; no new runtime module, API, process, store, or dependency is needed. | prospective pattern `orchestrator/driver.py:14696-14705`; current advancement gap `orchestrator/driver.py:14115-14129`; existing admission/result `orchestrator/tasks.py:1284-1327`; existing verification kind `orchestrator/tasks.py:23-38` |
| consumers_touched | Verified code consumers are the milestone driver that admits deep work and advances after gates, the state initializer/close predicate, and canonical task history. The existing reviewed verification lifecycle is consumed unchanged. Generic service routes and the catalogue remain unchanged. Exact searches across Life, Agent99, life_product_components, and Tutor found no cadence consumer or alternate reviewed-verification engine to wire. | deep admission consumer `orchestrator/driver.py:4476-4572`; step/advance consumer `orchestrator/driver.py:9090-9131,14115-14129`; close consumer `orchestrator/state.py:1545-1580`; whole-universe reuse finding `implementation/milestones/deep-reviewed-tasks/skeleton.md:110-116` |
| cheaper_alternative | Cheapest sufficient is to schedule the existing complete-verification reviewed task and gate advancement on its durable result. Changing `4` to `5` is insufficient because it leaves verification inside a slice and breaks pre-activation runs; documentation/configuration cannot create sibling identity, recovery, or closure blocking. A new scheduler or verifier would duplicate existing machinery. | current in-slice selector `orchestrator/driver.py:1916-1932,13088-13111`; reusable task contract `orchestrator/tasks.py:28-38,856-889`; independent-task requirement `implementation/milestones/deep-reviewed-tasks/goal.md:150-169` |
| cost | Build and review cost is a bounded state/driver scheduling change plus five focused behaviors. Runtime adds one existing task record and verification gate at each due boundary; suite, repair, and review calls are the work already required by that task. There is no migration, daemon, package, parallel store, or product-root change. Omission leaves the milestone boundary unmet; code/state changes before activation are Git-reversible, call spend is not. | standard-library architecture `orchestrator/README.md:3-9,33-46`; append-only record reuse `orchestrator/state.py:385-433`; cadence assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:138` |
| threat_model | This slice introduces no new externally controlled input. Cadence reads trusted product-emitted run binding, canonical plan/deep results, validated task records, and Git/current-content evidence. Caller orders, model JSON, suite commands/semantics, and worker mutations remain at the existing reviewed verification boundary; this slice adds no defense around trusted emitters and does not claim to judge whether trusted commands are semantically complete. | trust boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:118-123`; closed task order/result `orchestrator/tasks.py:1017-1048,1284-1327`; current proof `orchestrator/driver.py:680-730,14177-14239` |
| pinned_facts | The five hard rows are the complete bug-level set: prospective/legacy law, sibling identity and five-slice boundary, durable blocking, final current-content reuse, and executable verification. Internal helper names, traversal order, state layout, and polling/control flow are deliberately unpinned. | this note `implementation/milestones/deep-reviewed-tasks/slices/slice-11.md:98-104`; slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:138`; hard milestone boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:157-159` |
| verification | Five new observable checks inspect task count/type/parentage, deep-success ordering, part counting, next-slice and close blocking, terminal result/gate, crash adoption, current-content reuse, reconciliation invalidation, and prospective compatibility. Retained Slice 9/10, chronology, reconciliation, state, and task tests pin the reused seams. Repository checkpoint and extended suites may be claimed only when separately run. | retained sibling proof `orchestrator/tests/test_reviewed_complete_verification.py:175-213,275-407`; retained deep proof `orchestrator/tests/test_milestone_deep_slice_composition.py:97-202`; retained cadence/reconciliation proof `orchestrator/tests/test_verification_chronology.py:323-620`; suite commands `orchestrator/README.md:565-586` |
| enforceability | Existing mechanisms can enforce most claims: the run binding separates prospective law; deep-parent terminal success identifies a completed logical slice; the exclusive state mutation plus append-only task record supports one durable active attempt; reviewed success carries the verification gate; candidate and reconciliation checks decide current active proof. The missing enforceable seams are the five-slice due-boundary association, the interlock before next deep admission, and the final-close verification predicate; this slice must add them before those guarantees can be claimed. No mechanism can prove trusted third-party commands are the semantically complete suite, so no such promise is made. | deep completion `orchestrator/driver.py:4591-4618`; lock/history `orchestrator/state.py:385-455`; reviewed gate result `orchestrator/driver.py:680-730`; current-proof checks `orchestrator/driver.py:1829-1852,14177-14239`; current gaps `orchestrator/driver.py:14115-14129`; `orchestrator/state.py:1545-1580` |
