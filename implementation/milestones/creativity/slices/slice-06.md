# Slice 06 — Bounded concurrent evaluation waves

## Register 1 — INTENT

This slice lets the creativity search assess several batches of proposals at
once, within the operator's chosen work limits. Every answer belongs to the
candidate that was sent, even when batches finish in a different order. A
completed batch is saved while other batches are still working, so a later
explicit continuation can use that work.

The operator can change the evaluation instructions or staffing during a search.
Each new call uses the live choices. The search must also know which evaluator
actually supplied each score: a change of evaluator cannot make old and new
scores look like one fair comparison. This slice supplies that distinction and
identifies when a comparison is incomplete.

### Dependencies and non-goals

The work connects the existing candidate representation, evaluation prompt and
reply checks to the task service's existing group of controlled model calls.
It supplies the evaluation part of the search checkpoint and a handoff for the
search driver. It owns neither the meaning of the proposals nor the operator's
objective, constraints, instructions or staffing choices.

Population evolution, deciding which survivors need reassessment, resetting the
progress reference, stagnation, expansion and choosing the search's stop reason
remain outside this slice. So do complete task recovery, public ordering and
presentation. There is no new scheduler, service, provider, retry policy or
product integration.

### Risks and acceptance

Concurrent completion can misassociate answers, overspend the remaining work
allowance or lose a completed batch. Live evaluator changes can leave no complete
comparison and require further paid assessment. A saved result avoids repeating
accepted work; it cannot undo money already spent on an interrupted call.
Concurrency permits overlap without promising a particular speedup.

Acceptance observes the real routing, validation, call-group and storage seams
with controlled local workers. It checks batching, freshness, attribution,
comparison eligibility and checkpoint reuse without buying model calls or
claiming that the proposals are good.

## Register 2 — PINNED-FACTS TABLE

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Delivery and ownership | Add one internal evaluation-wave caller in `orchestrator/creativity_evaluation.py`, including the evaluation portion of the sole task-owned search checkpoint, and focused tests. Its named cross-slice contracts are the **evaluation-wave handoff** (F2–F5) and **accepted-evaluation checkpoint** (F6). Consume the existing host-created `TaskCallGroup`; no `creativity` executor is admitted or dispatched here. | `implementation/milestones/creativity/skeleton.md:125-130,147,149`; `orchestrator/task_api.py:954-967,1831-1838`; `orchestrator/tasks.py:911-915` | touch the new caller/checkpoint and its tests; do-not-change shared routing, prompt corpus, validators, staffing, runner/lease/control policy, pricing, catalogue, routes/events/errors, panel, population/progress code, skeleton, goal, `.orchestrator/`, or any additional root |
| F2 — Batches and work allowance | `evaluation_batch_size` caps candidate IDs per call; `evaluation_concurrency` caps simultaneous physical calls, including correction. One works; larger bounds permit overlap when enough work exists. No hidden global ceiling. Accepted evaluations plus outstanding candidate work cannot exceed `max_evaluated_candidates`; capacity already occupied by an unfinished batch is unavailable to its siblings. Valid and honestly invalid evaluations consume the same allowance. Reassessment consumes allowance again; the existing correction of a malformed reply does not add a second accepted evaluation. A short final batch is allowed; no candidates or remaining capacity means no call. | `implementation/milestones/creativity/skeleton.md:47-48,127,144-147`; admitted controls `orchestrator/tasks.py:897-948`; group admission `orchestrator/task_execution.py:253-292`; per-attempt boundary `orchestrator/runners.py:3035-3056` | own candidate batching and allowance use through the shared group; do-not-add numeric defaults, waiting-work infrastructure, child tasks or a search stop decision |
| F3 — Live routed invocation | Every physical attempt, including correction, reads live `staffing.session_material`, resolves `evaluate_candidates@creativity` with `executor="agent_call"` and kind `evaluate_candidates`, and obtains staffing through `creativity_job_staffing_request("evaluate_candidates", configuration)` and `staffing.resolve`: `role="review"`, `index=1`, `review_breadth=1`; rigor precedence remains job > task default > live session. Render the served prompt with immutable `search_material` and candidate IDs/readable chosen components, without historical scores, rank or prestige. No earlier batch's resolution authorizes a later dispatch. Missing material layers and whole-set fallback retain current router behavior. | `implementation/milestones/creativity/skeleton.md:49-54,91-96,140,143`; `orchestrator/tasks.py:904-907,965-972`; `orchestrator/staffing.py:1767-1779,2045-2111`; `orchestrator/prompt_router.py:339-341,467-503,553-595`; `implementation/brainstorming/prompt-router/adapted-kinds/milestone/evaluate_candidates.json:18-52` | wire existing `prepare_call` / `resolve_dispatch` seams; do-not-assemble caller prompt prose, freeze a wave's authorities, mutate staffing sessions or add prompt versions/change tracking |
| F4 — Accepted reply and identity | Bind the served `evaluate_candidates_result` section and use `prompt_contracts.validate` with that batch's `candidate_ids` and the immutable `constraint_ids`. Accept exactly one closed `{candidate_id,proposal,constraint_valid,constraint_violations,reason,assumptions,score}` per requested ID, in any reply order. Existing validity/violation and finite `[0,1]` score rules remain authoritative. An honestly invalid candidate is accepted evidence; a malformed or incomplete batch is not partial success. Preserve candidate-to-genome association across batches. Only the runner's existing one correction is allowed; exhausted correction and operational faults remain failures to the owning caller, never empty evaluations or fabricated scores. | `implementation/milestones/creativity/skeleton.md:112-116,141-142`; `orchestrator/prompt_contracts.py:530-544,579-602,891-927`; `orchestrator/runners.py:3013-3017,3503-3552`; component representation `orchestrator/creativity_search.py:30-45` | use the producer-owned validator and existing runner errors; do-not-duplicate reply checks, reinterpret reported validity, validate trusted driver input as hostile, or retry a failed batch automatically |
| F5 — Comparable handoff | Accepted evaluations retain the actual `(material, agent, model, effort)` of the attempt that produced the accepted answer, including a changed correction attempt. The handoff identifies unfinished candidates and whether the requested comparison set is complete under one actual regime. A change within or between waves makes prior-regime scores ineligible for the next selection; a late old-regime completion cannot restore readiness. A smaller matching subset cannot stand in for the required comparison set, including current valid survivors. No mixed-regime list is offered to `select_survivors`. Report the need for rebaseline to its owner; Slice 7 owns survivor reassessment and reference/progress changes. Prompt edits alone are not regime changes. | `implementation/milestones/creativity/skeleton.md:49-54,127-128,145`; actual dispatch fields `orchestrator/runners.py:3301-3318,3411-3417`; selector's caller contract `orchestrator/creativity_search.py:1-6,90-99`; correction evidence `orchestrator/tests/test_task_call_group.py:611-655` | own attribution and comparison eligibility at this handoff; do-not-compare different regimes by score, use task defaults as actual staffing, add defensive checks to the trusted selector, or implement the progress/rebaseline loop |
| F6 — Accepted-evaluation checkpoint | After each accepted batch, a fresh read sees its ID/genome association, evaluations, actual regime and accepted-evaluation count together, even while a sibling is unfinished. Completed sibling updates are not lost. This is the evaluation portion of one task search checkpoint, using existing local whole-value persistence, not a per-wave store. Explicit re-entry after group quiescence uses the saved accepted work and schedules only unfinished evaluation obligations; a required new-regime reassessment is new work. A call without a committed accepted result remains unfinished. Checkpoint write failure is not reported as acceptance. No full Resume/lifecycle integration is delivered here. | `implementation/milestones/creativity/skeleton.md:112-116,127-129,147`; existing persistence `orchestrator/kvstore.py:331-376,408-430,509-523`; task ownership `orchestrator/task_execution.py:38-55,231-233,321-325` | own checkpoint content and reload behavior under the task owner; do-not-add a second search store, accounting ledger, checkpoint recovery daemon, automatic replay or a transaction with the provider/accounting store |
| F7 — Shared controls and physical evidence | All evaluation attempts use `TaskCallGroup.call_worker` from `DirectTaskHost.create_call_group`; Pause/Stop fences later work and reaches active members. No wave handoff permits reuse while group quiescence is unresolved. Retain distinct `call_id` and `call_context` with job `evaluate_candidates`, generation and batch association, plus the attempt's material, actual family/model/effort, `prompt_set_fallback`, duration, tokens and cost evidence. Corrections, failures and interruptions retain their physical charges. Existing task accounting sums each recorded attempt once with `token_usage_partial` / `cost_partial`; accepted-result checkpoints add no charge. Existing staffing conditions remain `staffing_unavailable` and `distinct_families_unsatisfiable`. | `implementation/milestones/creativity/skeleton.md:63-68,112-116,139,147`; `orchestrator/task_execution.py:294-325`; `orchestrator/task_api.py:191-247,954-979`; `orchestrator/runners.py:3052-3056,3344-3353,3371-3417`; `orchestrator/staffing.py:2062-2069` | supply evaluation context to the existing group/evidence owners; do-not-reimplement interruption, liveness, pricing, aggregation or task failure vocabulary |
| F8 — Guarantee posture and trust | **Strict:** F2 bounds/allowance, F3 served-input obligations, F4 contextual acceptance/association, F5 comparison eligibility, F6 completed-checkpoint visibility and F7 inherited control/recorded-call accounting. **Optimistic:** F3 live authority reads; no transaction across material, prompts and staffing and no rewrite of dispatched calls. **Best-effort:** semantic quality, worker exploration-only compliance, auxiliary evidence persistence and provider usage availability. **Eventual:** no new delivery mechanism; existing panel polling remains outside this slice. Operator, product code, admitted configuration/material, emitted context/checkpoints, libraries and OS APIs are trusted. No provider exactly-once, automatic recovery, fixed stopping time, sandbox or power-loss durability claim. | `implementation/milestones/creativity/skeleton.md:78-116,160`; trusted caller context `orchestrator/prompt_contracts.py:891-896`; auxiliary evidence `orchestrator/task_api.py:969-979`; local persistence boundary `orchestrator/kvstore.py:509-523`; worker access `orchestrator/README.md:631-634` | test the new caller's own obligations; do-not-add dependency policing, malformed-internal-data defenses or stronger delivery/security guarantees |

### Acceptance criteria and tests

T1–T7 are new implementation obligations in
`orchestrator/tests/test_creativity_evaluation.py`, not claims of passing tests
from this draft. Reuse accepted-material fixtures, temporary router/staffing
stores and the existing controlled-worker/group fixtures. Observe dispatched
inputs, returned handoffs, persisted checkpoints and common call evidence.

1. **T1 — `test_wave_bounds_and_candidate_allowance` (F2):** use more candidates
   than one wave can hold, with concurrency one and two and out-of-order
   completion. Observe actual overlap at two, both caps, a short final batch and
   no empty call. With three remaining places and batches of two, outstanding
   work cannot admit a fourth candidate. Reassessment consumes new places;
   correction does not double the accepted count.
2. **T2 — `test_each_attempt_reads_live_authorities` (F3):** complete real prompt,
   material and staffing saves between dispatched batches and before a correction.
   Later physical calls use the new inputs; already dispatched calls retain
   theirs. Exercise inherited and job-specific rigor, generic/material-layered
   prompts and existing fallback. Inspect rendered inputs for fixed problem data
   and absence of historical scores or prestige.
3. **T3 — `test_batch_reply_coverage_and_association` (F4):** return reordered
   evaluations, including a high-scoring invalid candidate. Keep exact genome
   association. Reuse producer fixtures for duplicate, missing and foreign IDs,
   bad violations and invalid scores through the served validator. A corrected
   batch is accepted once; exhausted correction admits none of that batch and
   does not erase an accepted sibling.
4. **T4 — `test_regime_changes_withhold_comparison` (F5):** change each regime
   component within and between waves, including during correction. Release an
   old call last. Retain actual attribution but no mixed or incomplete
   selection-ready handoff, including when a survivor still lacks the new
   assessment. A complete same-regime set becomes ready. A prompt-only edit does
   not request rebaseline. No test requires the Slice 7 progress loop.
5. **T5 — `test_checkpoint_reentry_keeps_accepted_work` (F6):** finish one batch
   while another remains active; a fresh checkpoint reader sees the accepted
   batch and count together. Complete siblings in reverse order and retain both.
   Interrupt with unfinished work, then explicitly re-enter after quiescence:
   accepted same-regime work is not dispatched or counted again; unfinished work
   remains identifiable. Re-entry without work starts no call.
6. **T6 — `test_wave_uses_task_controls_and_surfaces_faults` (F4, F7):** use the
   host-owned group with several evaluation batches; Pause and Stop reach active
   calls and fence later batches/correction. Preserve accepted checkpoints and
   wait for the existing group safety boundary. A staffing refusal or provider
   failure is surfaced without a synthetic evaluation or an automatic retry.
7. **T7 — `test_wave_evidence_uses_common_accounting` (F7):** combine successful,
   corrected, failed and interrupted calls with distinct batch context and
   staffing. Common records retain their physical identities and actual regime;
   rereading a checkpoint adds no cost. Known usage sums once; unknown usage
   stays partial. Check the successful correction's own attribution, not its
   first attempt's staffing or combined carrier totals.

Acceptance requires T1–T7, the existing producer/group regressions below, and a
diff restricted to F1. The new tests verify integration; they do not recreate
the producer's exhaustive transport, validator or storage tests. After
implementation run:

```sh
python3 -m unittest orchestrator.tests.test_creativity_evaluation orchestrator.tests.test_creativity_search orchestrator.tests.test_task_call_group orchestrator.tests.test_prompt_contracts orchestrator.tests.test_prompt_router orchestrator.tests.test_staffing_sessions orchestrator.tests.test_tasks
```

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator awaiting an evaluated population otherwise has prepared candidates and evaluation contracts without a caller that connects them. Concurrent mistakes can spend beyond the order, misassign scores or repeat paid accepted work; mixed regimes can choose the wrong survivors. Exposure is a creativity evaluation, not unrelated product activity. Search data can be replaced; incurred model spend cannot. The reviewed assignment establishes the need independently, and the existing selector explicitly requires comparable caller-supplied evaluations. | `implementation/milestones/creativity/skeleton.md:47-54,127,147`; `orchestrator/creativity_search.py:1-6,90-99`; `orchestrator/tasks.py:911-915` |
| machinery | One evaluation module adds batching/allowance use, routed-call wiring, attributed comparison handoff and accepted-checkpoint content. These respectively serve bounded work, live evaluation, fair selection input and reuse of completed work. It consumes `genome_components`, the registered evaluator validator, per-job staffing, `TaskCallGroup` and local KV persistence. No package, public API, shared scheduler or second accounting system is introduced. | `orchestrator/creativity_search.py:30-45`; `orchestrator/tasks.py:965-972`; `orchestrator/prompt_contracts.py:579-602`; `orchestrator/task_execution.py:253-325`; `orchestrator/kvstore.py:331-376`; `implementation/milestones/creativity/skeleton.md:127,147,149` |
| consumers_touched | The consumer created here is the evaluation caller and its integration harness. Verified existing seams are the host's group factory, the runner's per-attempt preparation/dispatch interface and the selector's comparable-input contract. Current host dispatch has no creativity branch; the future driver is an assigned consumer, not an existing runtime client claimed by this note. No current shared consumer or granted-root product is migrated. | `orchestrator/task_api.py:954-967,1831-1838`; `orchestrator/runners.py:3005-3056`; `orchestrator/creativity_search.py:90-99`; current group harness `orchestrator/tests/test_task_call_group.py:330-357`; composition assignment `implementation/milestones/creativity/skeleton.md:128-130` |
| cheaper_alternative | The sufficient option is wiring the existing group, routers, validator and store with standard-library concurrency. The group alone neither batches candidates nor supplies search acceptance/checkpoints; serial-only evaluation omits required overlap. Workspace and all four granted roots, including installed/vendored dependency sources, were searched: related Elixir streams perform database/directory probes, not this Python evaluation handoff. The established [standard-library thread pool](https://docs.python.org/3.9/library/concurrent.futures.html#concurrent.futures.ThreadPoolExecutor) supplies bounded execution; its [future cancellation](https://docs.python.org/3.9/library/concurrent.futures.html#concurrent.futures.Future.cancel) does not replace worker interruption. No new dependency is needed. | `orchestrator/task_execution.py:253-258,294-325`; `orchestrator/README.md:46`; `/Users/siddhartha/Development/source/life/apps/life_transport/lib/life_transport/storage/spanner/session_pool.ex:1334-1356`; `/Users/siddhartha/Development/source/life/deps/ecto/lib/ecto/repo/preloader.ex:136-158`; `/Users/siddhartha/Development/source/life_prod/agent_99/apps/agent_99/lib/agent_99/actor_directory/visible_set.ex:47-58`; `/Users/siddhartha/Development/source/life_prod/life_product_components/elixir/apps/life_product_workspaces/lib/life_product_workspaces.ex:577-589`; `/Users/siddhartha/Development/source/life_prod/tutor/web/vendor/life_product_components/elixir/apps/life_product_workspaces/lib/life_product_workspaces.ex:577-589` |
| cost | Build and maintenance cost is one caller/checkpoint surface plus focused integration tests; review concentrates on admission, attribution and completed-work reuse. No existing order/data migration or new operational service is required. Runtime cost is bounded model assessment plus local checkpoint writes; live regime churn can spend remaining allowance on reassessment. Reverting this preparatory integration is simple before activation, while paid calls remain irreversible. Omitting it leaves the already-built search and group disconnected. | `WORKSPACE.md:14-30`; `implementation/milestones/creativity/skeleton.md:125-130,145,147`; `orchestrator/task_api.py:954-979`; `orchestrator/kvstore.py:509-523` |
| threat_model | A provider controls evaluation replies; a third-party source author can influence text previously admitted into search material. This slice handles those replies with the existing contextual contract and carries text as data. It does not prove semantic truth or contain hostile worker tool use. The authorized operator, product code, staffing/prompt documents, accepted material, generated candidate batches/checkpoints and libraries are trusted. No new parser or defensive validation is added around their emitted structures. | `implementation/milestones/creativity/skeleton.md:99-110,160`; `orchestrator/prompt_contracts.py:579-602,891-896`; `implementation/brainstorming/prompt-router/adapted-kinds/milestone/evaluate_candidates.json:18-32,38-52`; `orchestrator/README.md:631-634` |
| pinned_facts | F1 fixes ownership; F2 fixes bounds and allowance; F3 fixes the routed job and live authorities; F4 fixes accepted coverage; F5 fixes attributable, comparable selection input; F6 fixes accepted-checkpoint visibility/re-entry; F7 inherits controls and recorded-call accounting; F8 limits every guarantee. No internal scheduling order, persistence layout, new task status or public error is pinned. | `implementation/milestones/creativity/skeleton.md:78-116,127-130,140-147`; existing contracts `orchestrator/tasks.py:897-972`; `orchestrator/prompt_contracts.py:579-602`; `orchestrator/task_execution.py:253-325` |
| verification | T1–T7 exercise this caller through real shared seams with controlled outcomes, live authority saves and fresh checkpoint reads. Existing tests already supply accepted search material, contextual malformed-provider cases, independent group completions and per-attempt correction accounting. The draft verifies those source authorities and defines new acceptance obligations; it claims no new passing runtime evidence. Tests target ordinary concurrency and untrusted replies, not fabricated malformation by trusted dependencies. | `orchestrator/tests/test_creativity_search.py:18-60`; `orchestrator/tests/test_prompt_contracts.py:122-152`; `orchestrator/tests/test_task_call_group.py:359-385,486-599,611-655`; `orchestrator/tests/test_prompt_router.py:1052-1122` |
| enforceability | F1 is checked by scope review. F2 uses admitted controls, bounded execution and the group's capacity fence; the runner's pre-dispatch seam can enforce remaining candidate allowance. F3 uses per-attempt preparation/dispatch callbacks and the live resolvers. F4 uses the served contextual validator. F5's new handoff compares actual dispatch attribution rather than cached staffing; the existing selector trusts that handoff. F6 uses one whole-value checkpoint write/read under task ownership, with serialized acceptance so sibling updates survive. F7 uses the existing interruption/quiescence and identity-keyed accounting paths. These APIs express the obligations; their evaluation wiring is the work of this slice. F8 explicitly limits auxiliary persistence, freshness and semantic claims. No unexpressible strict guarantee or governing-design contradiction was found. | `orchestrator/tasks.py:911-972`; `/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/concurrent/futures/thread.py:127-137,184-202`; `orchestrator/task_execution.py:261-325`; `orchestrator/runners.py:3035-3056,3301-3318,3411-3417`; `orchestrator/prompt_router.py:467-503`; `orchestrator/staffing.py:1767-1779,2045-2111`; `orchestrator/prompt_contracts.py:579-602`; `orchestrator/kvstore.py:340-376,408-430,509-523`; `orchestrator/task_api.py:219-247,954-979` |
