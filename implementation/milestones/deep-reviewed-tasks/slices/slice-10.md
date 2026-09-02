# Slice 10 — Sibling complete-verification task

## Register 1 — INTENT (lay language)

### What this slice builds

This slice lets an operator order complete repository verification as one
reviewed task. The task checks the repository's complete suite, owns any repair
work caused by a failure, and finishes only when the current repository state is
certified and has its own seal and Git gate.

An already-green repository still receives a visible task result and gate. If
verification exposes a real failure, the existing fixer gets the full failure
account and must make the complete suite green. Any repair is reviewed under the
task's selected review policy; later edits make the earlier proof stale.

This is an independently usable building block. A later slice will decide when
a milestone orders it. It is not part of a deep task, does not count as a
logical slice, and does not replace focused checks belonging to ordinary work.

### Ownership and scope

The reviewed task owns verification, repair, review of repair changes, evidence,
accounting, seal, and gate. The operator or bound project continues to own the
meaning of an explicitly configured suite, while the established discovery path
handles repositories without configured commands. Third-party tools and their
declared suite meaning remain trusted inputs to that existing boundary.

The slice extends the existing reviewed-task choice and lifecycle. It introduces
no runtime module, package, process, store, task type, prompt system, permission
model, or product adapter. The granted product roots remain read-only.

### Guarantee posture

- **Strict:** one admitted outer task; closed order validation; coherent suite
  evidence for current bytes and commands; repair before success after a failed
  suite; review convergence for changed bytes; one terminal result, seal, and
  gate; single-count accounting; no size control; and existing-task
  compatibility.
- **Best-effort:** physical-call uniqueness, process-interrupt delivery, and
  display freshness. A crash may repeat an unrecorded call, but cannot create a
  second logical result or reuse stale proof.
- **Optimistic / eventual:** none. No queue, redelivery, replication, or eventual
  presentation promise is added.

### Dependencies

This slice depends on the completed reviewed lifecycle, standalone reviewed-task
ordering, current-byte result and gate recovery, Prompt Router, the existing
complete-suite checkpoint and repair path, review/fix/delta convergence, Git
WIP/amend/finalize operations, task accounting, and service restart adoption.

The next slice consumes this task for milestone cadence. This slice deliberately
leaves the current milestone checkpoint placement and final scheduling law
unchanged.

### Non-goals

- No new verification-only executor, child of a deep task, or task relation.
- No five-slice or final scheduling, checkpoint reuse policy, milestone blocking,
  separate milestone card, or retirement of the current in-slice checkpoint.
- No new suite runner, shell executor, command discovery system, prompt route,
  repair loop, reviewer, seal rule, Git operation, or accounting ledger.
- No Brainstorming producer and no implementation-size threshold, intervention,
  interruption, stabilizer, cut, or overflow claim.
- No attempt to judge operator commands, third-party test semantics, or trusted
  product-emitted records. Untrusted order and model-result boundaries retain
  their existing validation.
- No migration or backfill, granted-root edit, push, deployment, notification,
  retry service, cache, or stronger delivery guarantee.

### Acceptance criteria

The focused contract must prove that the generic catalogue and task API admit
one complete-verification order and refuse ineligible producer or size choices
before admission. The order must create one outer reviewed task and no task for
its internal calls.

An unchanged configured pass and a valid no-suite discovery must each finish
with a successful native result, a deterministic seal, and a new gate commit
whose tree is the certified tree. Neither case needs a fixer or reviewer call.

A failed checkpoint must leave the task open, preserve the complete failure
account, and enter the existing repair path. A repair must certify the complete
suite on its final bytes. Changed bytes must pass the selected delta and whole
review discipline; any later change must force fresh verification before seal.

Blocked work, exhausted convergence, Stop, malformed output that exhausts its
existing correction allowance, or an unrecoverable gate must end honestly as
task failure without a success result. Restart must retain the same open task,
policy, evidence, and pending gate; every retained physical charge counts once.

Existing direct tasks, deep tasks, old task records, and the current milestone
verification chronology must pass unchanged. The focused tests must make no
claim that checkpoint commands are semantically adequate beyond the established
trusted suite contract.

### Risks

The main risks are accepting a stale or mutated checkpoint reply, treating the
first failure as terminal instead of repairable, sealing repaired bytes before
review, reusing a fixer proof after later edits or command changes, or collapsing
an unchanged verification into the preceding commit. Other risks are creating a
child call-task, enabling Brainstorming or size control, double-counting the
fixer, or pulling milestone cadence and presentation into this slice.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Public order contract | The public executor remains `reviewed_task`; add exactly `configuration.task_kind: "complete_verification"`. Its only producer is `agent_call`, resolved at the existing `implement` staffing role. Its optional policy keys are exactly `producer`, `review_breadth`, `same_family_second_look`, `impl_reclassify_from`, `p3_reclassify_debt`, `p3_defer_max_risk`, `max_rounds_per_family`, `max_fix_loops`, and `delta_full_review_after_fixes`; omission keeps the existing `agent_call` / `double` / `false` and project-effective defaults. `doc_reclassify_from`, `implementation_size_control`, Brainstorming, and a new suite-command order field are ineligible and return `invalid_task_request`; an unknown producer retains `unknown_task_executor`. Catalogue ids remain exactly `agent_call`, `brainstorming`, `reviewed_task`, `deep_task`, using `GET /api/task-executors`, `GET/POST /api/tasks`, `GET /api/tasks/<id>`, and `POST /api/tasks/<id>/stop`. | semantic-job assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:12-16,43-48,137`; public-policy mandate `implementation/milestones/deep-reviewed-tasks/goal.md:34-55`; current closed schema/errors `orchestrator/tasks.py:19-36,147-275,615-662,845-880`; generic routes `orchestrator/service.py:4649-4699,4906-4916` | touch the reviewed-task semantic choice, resolver, generated form, and shared lifecycle entry; do-not-add an executor/route/error, offer Brainstorming, expose size control, or change direct executors |
| Verification production contract | Production uses the existing direct Prompt Router job `suite_checkpoint@workspace` and result kind `suite_checkpoint`. Accepted statuses are exactly `passed`, `failed`, `no_suite`, or `blocked`. Configured `verification` commands must be returned in exact order; otherwise existing repository discovery may return `no_suite`, which requires empty commands/results and repository authority. `passed` requires one zero result per command; `failed` requires the matching final non-zero `failure_account`. | complete-verification behavior `implementation/milestones/deep-reviewed-tasks/goal.md:165-169`; route `orchestrator/prompt_router.py:28-49`; result contract `orchestrator/prompt_contracts.py:444-519`; command authority `orchestrator/driver.py:3301-3360` | touch the reviewed production adapter and retained result association; do-not-add a prompt route, execute a second driver-side suite, reinterpret command meaning, narrow discovery, or accept an incoherent trace |
| Current-byte success and result | The checkpoint call is read-only: a changed repository invalidates its reply, restores candidate bytes, and leaves verification due. Terminal task success accepts only a current `passed` or valid `no_suite` proof and returns the existing native keys `production_result`, `review_evidence`, and `gate_commit`. An unchanged success creates its own new allow-empty WIP/final gate commit with the same tree, not the preceding task's commit; its seal cites the accepted proof. Evidence uses the existing `verification`, `seal_satisfied`, and `gate_commit` events, with no new event name. | assigned unchanged gate `implementation/milestones/deep-reviewed-tasks/skeleton.md:97-103,137`; read-only boundary `orchestrator/driver.py:483-515,1661-1692`; result/events `orchestrator/driver.py:631-681,12835-12887,13108-13110,14053-14059`; allow-empty Git operations `orchestrator/gitops.py:638-644,741-749` | touch verification-specific lifecycle start, current-proof seal, and native production result; do-not-seal a mutated/stale reply, report success before the gate, omit the empty gate, or flatten/rename native fields |
| Failure, repair, and re-verification | `failed` is evidence, not task terminality: it queues the existing suite-repair fixer with the exact commands and failure account. The fixer must certify the complete suite on its final bytes. Repair changes take the established delta and selected whole-review path; a later edit or command change invalidates certification and requires fresh verification. `blocked`, exhausted caps, or unrecoverable execution cannot yield terminal success or a gate; a gate failure may retain the already-recorded seal but is still task failure. | failure discipline `implementation/milestones/deep-reviewed-tasks/skeleton.md:32-41,137`; existing failure queue `orchestrator/driver.py:13128-13186`; fixer certification and review edge `orchestrator/driver.py:12183-12245`; exact-proof reuse `orchestrator/driver.py:1729-1757` | touch only the existing checkpoint-to-fixer/review back-edge for this semantic job; do-not-create a repair task, truncate failure evidence, bypass selected review policy, reuse stale proof, or convert initial failure directly to task failure |
| Identity, compatibility, and slice boundary | One order has one top-level `reviewed_task`, one result that moves only from `null` to terminal `success` or `failure`, and no child `agent_call`; internal checkpoint/fix/review/delta/classification calls are evidence and are charged once. Restart adopts the same open task; unrecorded physical calls remain at-least-once. This task is not a `deep_task` child and does not count as a slice. Slice 10 leaves the existing four-slice/final in-slice milestone checkpoint and old history unchanged; Slice 11 owns replacement cadence and Slice 12 owns separate milestone presentation. No new dependency or granted-root edit is allowed. | call/task boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:50-58,106-123,137-139`; terminal record and statuses `orchestrator/tasks.py:92-105,1273-1316`; restart/delivery `orchestrator/task_api.py:781-838`; `orchestrator/state.py:1-17`; current cadence `orchestrator/driver.py:53,1759-1837` | touch standalone/reusable reviewed execution and focused tests; do-not-add parentage, count a logical slice, alter milestone scheduling/projection, backfill history, duplicate accounting, or edit another root |
| Verification | Focused command: `python3 -m unittest orchestrator.tests.test_reviewed_complete_verification orchestrator.tests.test_suite_checkpoint_call orchestrator.tests.test_reviewed_task_api orchestrator.tests.test_reviewed_result orchestrator.tests.test_reviewed_lifecycle orchestrator.tests.test_task_api orchestrator.tests.test_prompt_contracts orchestrator.tests.test_verification_chronology`. New checks named `test_contract_admits_only_agent_call_complete_verification`, `test_unchanged_pass_and_no_suite_each_own_seal_and_gate`, `test_failed_suite_repairs_reviews_changes_and_reverifies_current_bytes`, `test_blocked_stop_restart_and_gate_crashes_keep_one_honest_result`, and `test_slice_ten_leaves_milestone_cadence_and_old_records_unchanged` must pass. Repository checkpoint and extended suites remain separate and unclaimed until run. | existing suite boundary tests `orchestrator/tests/test_suite_checkpoint_call.py:194-318,423-494`; existing repair proof `orchestrator/tests/test_driver_mock.py:696-702,797-826`; result/recovery proof `orchestrator/tests/test_reviewed_result.py:115-325`; suite inventory authority `orchestrator/README.md:565-586` | touch one focused complete-verification module and retained contracts; do-not weaken existing tests, claim unrun suites, assert physical exactly-once delivery, or test trusted command semantics as hostile input |

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Operators and later milestone scheduling currently cannot order complete verification as one durable reviewed result: the public semantic-job list rejects it, while verification remains attached to the implementation unit that makes the cadence due. The realistic harm is missing public evidence/commit ownership or a false current-byte certification assembled outside the lifecycle. Repository changes are Git-reversible; paid calls and a consumed false gate are not. | assigned need `implementation/milestones/deep-reviewed-tasks/skeleton.md:12-16,137`; current rejection `orchestrator/tasks.py:23-36`; `orchestrator/tests/test_tasks.py:323-345`; current in-slice placement `orchestrator/driver.py:1821-1837,12944-12968` |
| machinery | Add one semantic-job choice and one verification entry/closure path inside the existing task contracts, standalone lifecycle state, and reusable reviewed lifecycle, plus one focused test module. These serve admission, suite-as-production, repair/review, and gate-backed result respectively. Existing Prompt Router, suite contract, fixer, reviews, Git, store, and accounting are reused; no new runtime module, API, dependency, process, or store is justified. | current missing job map `orchestrator/tasks.py:23-36,615-662`; lifecycle entry gap `orchestrator/driver.py:539-545`; standalone target mapping `orchestrator/task_api.py:569-650`; reusable suite path `orchestrator/driver.py:12889-13186` |
| consumers_touched | Verified consumers touched are the shared task catalogue/resolver, generic service admission and generated form, standalone reviewed host/state, and reusable reviewed lifecycle/result. The suite route, fixer/review machinery, Git, and accounting are reused dependencies. Exact-id searches across Life, Agent99, life_product_components, and Tutor found no code consumer or alternative reviewed-verification engine; no product adapter is created. | catalogue/API consumer `orchestrator/service.py:4193-4274,4649-4699`; host consumer `orchestrator/task_api.py:569-650,1128-1185`; generated form seam `orchestrator/static/panel.html:5674-5832`; whole-universe conclusion `implementation/milestones/deep-reviewed-tasks/skeleton.md:110-116` |
| cheaper_alternative | Cheapest sufficient is to expose the new semantic choice through `reviewed_task` and reuse the already-routed checkpoint, fixer, review, result, recovery, and gate machinery. Documentation or configuration alone cannot make the rejected job orderable or give it a task result/gate. Keeping verification inside a slice fails independent ordering; a new executor, wrapper engine, or shell runner duplicates solved machinery. | current refusal `orchestrator/tests/test_tasks.py:323-345`; existing suite path `orchestrator/driver.py:12889-13186`; reusable lifecycle/result `orchestrator/driver.py:518-681`; assigned independent ordering `implementation/milestones/deep-reviewed-tasks/goal.md:129-130,165-169` |
| cost | Build/review cost is a bounded schema/lifecycle extension and five focused behaviors. Runtime adds one task record and an allow-empty commit on unchanged success; provider, suite, fixer, and review calls are only those the outcome requires. There is no migration, daemon, package, or parallel storage. Omission blocks the next slice and leaves verification without independent result/commit ownership; implementation is Git-reversible, call spend is not. | standard-library environment `orchestrator/README.md:3-9,33-46`; task/store reuse `orchestrator/task_api.py:59-169`; allow-empty gate `orchestrator/gitops.py:638-644,741-749`; assigned next boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:137-138` |
| threat_model | Untrusted inputs newly reaching this path are the authenticated caller's task order, model-returned checkpoint/fix/review JSON, and worker workspace mutations. Existing closed order/result contracts and repository snapshot boundary guard them. Trusted inputs are operator/project verification commands, third-party suite semantics, admitted staffing/project authority, product-emitted task association, state/Git machinery, and the deterministic gate; this slice adds no defense around those emitters. | order validation `orchestrator/tasks.py:1008-1037`; suite-result validation `orchestrator/prompt_contracts.py:444-519`; repository boundary `orchestrator/driver.py:483-515`; trusted-command test `orchestrator/tests/test_prompt_contracts.py:417-475`; trust boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:118-123` |
| pinned_facts | The six hard rows contain every exact deviation treated as a bug: semantic job/producer/configuration/errors/routes, suite outcome vocabulary, current-byte result/gate, failure and re-verification discipline, task/slice/compatibility ownership, and executable checks. Internal unit names, helper decomposition, storage traversal, polling, and control-flow layout are deliberately unpinned. | slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:137`; public and verification facts `implementation/milestones/deep-reviewed-tasks/skeleton.md:143-159`; mechanism-altitude rule embodied by reusable boundary `orchestrator/driver.py:518-524` |
| verification | Five new observable checks plus retained checkpoint, repair, reviewed-result, API, protocol, chronology, Stop, and recovery tests inspect public orders, task counts/results, routed calls, preserved failure evidence, repository bytes, review history, charge totals, seal citations, Git trees/commits, and injected crash windows. The focused command pins this slice; repository suites stay independent and may be claimed only if implementation runs them. | retained checkpoint cases `orchestrator/tests/test_suite_checkpoint_call.py:194-318,423-494`; standalone recovery cases `orchestrator/tests/test_reviewed_task_api.py:523-555,696-921`; suite commands `orchestrator/README.md:565-586` |
| enforceability | Existing mechanisms enforce generic admission/error classes, structured checkpoint traces and exact configured commands, read-only/current-byte acceptance, failure-to-fixer evidence, selected review/fix caps, proof invalidation, allow-empty WIP/gate commits, null-to-terminal results, restart adoption, and at-least-once delivery. The bounded gaps this slice must close are the absent semantic kind, the three-kind production mapping, and a verification-specific start/final-proof association; until the named tests pass, independent ordering and unchanged gate ownership are not claimed. No mechanism can independently prove that trusted third-party commands are the semantically complete suite, so the note deliberately makes no such defensive promise. | existing enforcers `orchestrator/tasks.py:615-662,845-880,1273-1316`; `orchestrator/prompt_contracts.py:444-519`; `orchestrator/driver.py:483-515,12183-12245,12889-13186`; `orchestrator/gitops.py:638-644,741-749`; gaps `orchestrator/tasks.py:23-36`; `orchestrator/driver.py:539-545`; `orchestrator/task_api.py:581-620` |
