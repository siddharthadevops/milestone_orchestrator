# Slice 08 — Durable creativity task lifecycle

## Register 1 — INTENT

This slice turns the existing creativity pieces into one task an operator can
pause, continue later, or cancel. It carries the operator's problem through
creating search material, exploring combinations, evaluating them, and asking
for additional choices when progress stalls. It finishes with understandable
proposals and the actual reason exploration stopped, including an honest empty
result when nothing valid was found.

The task keeps completed, saved work across a service interruption. Continuing
requires the operator's explicit action and waits until previous workers can no
longer write. Cancellation ends the task permanently. The task's existing
accounting carries recorded model work across those interruptions.

### Dependencies and non-goals

This work depends on the preceding slices' admitted configuration, semantic
prompts and reply checks, population motor, controlled evaluation waves, and
progress and expansion decisions. It owns their composition and saved
continuation. The existing task service retains identity, access, workspace
ownership, controls, deletion and accounting.

Public ordering, the order form and the creativity display belong to the next
slice. This slice introduces no new search rules, defaults, scheduler, storage
system, routing authority or product integration. It never acts on proposals.

### Risks and acceptance

A provider can finish work before its answer is saved; an explicit continuation
may then spend again on unfinished work. Previously saved evaluations may also
need reassessment when the evaluator changes. Neither checkpointing nor a work
allowance guarantees a fixed monetary cost or useful ideas. Stopping workers
cannot undo effects from a worker that disobeys its exploration instructions.

Acceptance uses small searches and controlled local workers to observe saved
work, continuation, controls, results and charges. It requires no purchased
model run or claim about creative quality.

## Register 2 — PINNED-FACTS TABLE

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Task owner and slice boundary | Compose one `creativity` task in `DirectTaskHost`, including eligibility in `RECOVERABLE_EXECUTORS` and the existing service control gate. Consume `make_population`, `reproduce`, the search-progress handoff, `evaluate_progress_wave` and `expand_progress`. The host remains the execution owner. | `implementation/milestones/creativity/skeleton.md:63-76,125-130`; `orchestrator/task_api.py:29,954-967,1597-1637,1831-1838`; `orchestrator/service.py:4978-4989`; `orchestrator/creativity_search.py:75-89,146-186`; `orchestrator/creativity_evaluation.py:117-126,275-289` | touch task composition/persistence in `task_api.py`, necessary creativity-module integration and service control eligibility; do-not-publish the catalogue, order schema, API projection or panel, change shared policy, edit skeleton/goal, or touch additional roots |
| F2 — Gene creation and shared semantic boundary | `create_genes@creativity` uses kind `create_genes` and served `create_genes_result`; supply admitted `objective`, `context`, ordered `references`, and validator context `expected_objective`. All three jobs use the host-created `TaskCallGroup`, the existing routed invocation boundary, live material/prompt/staffing reads and `creativity_job_staffing_request`. Preserve the existing single response-correction allowance and exploration-only context. | `implementation/milestones/creativity/skeleton.md:104-116,140-143`; `implementation/brainstorming/prompt-router/adapted-kinds/milestone/create_genes.json:10-14,34-57,66-80`; `orchestrator/prompt_contracts.py:547-574,891-914`; `orchestrator/tasks.py:965-972`; `orchestrator/creativity_evaluation.py:71-114`; `orchestrator/task_execution.py:294-311`; `orchestrator/runners.py:3013-3017,3035-3056` | add the missing gene-creation caller through existing seams; do-not-add prompts, parsers, staffing decisions, dispatch paths or defensive revalidation of trusted driver inputs |
| F3 — Creativity task checkpoint handoff | One task-owned checkpoint through `LocalKVClient` retains accepted material, stable candidate identities/genomes, explored identities, accepted wave evidence and eligibility, progress/archive, expansion evidence/counts, current job/generation and any completed search result. Saved accepted replies and generation transitions survive host-process restart. Explicit Resume reuses them and schedules only unfinished work; current-regime evaluations are not charged again, while required regime reassessment consumes the remaining allowance. Saved expansion and generation transitions are not applied twice. This is the named cross-slice handoff for the task owner and later projection; private layout is not a contract. | `implementation/milestones/creativity/skeleton.md:145,147-148`; `orchestrator/kvstore.py:331-358,408-430,509-523`; `orchestrator/creativity_evaluation.py:173-240,259-289`; `orchestrator/creativity_search.py:165-229,251-291,313-337` | own durable composition around the existing whole-checkpoint wave seam; do-not-overwrite accepted sibling results, reset budgets/explored history on Resume, revive obsolete scores, add a second store engine or derive authority from display state |
| F4 — Pause, Resume, faults and Cancel | Existing `pause`, `resume`, `stop` task controls apply. Pause and recoverable execution faults retain identity/checkpoint and `result: null`; `pausing` cannot become resumable while any recorded worker is unquiet. Resume requires the current paused `revision`; stale/repeated requests retain HTTP 409. Restart pauses interrupted work without new semantic calls. Accepted Cancel survives restart, fences further search and settles as task `failure` after quiescence; it cannot be replaced by a prepared search success. Existing terminal records are immutable. Preserve `staffing_unavailable` and `distinct_families_unsatisfiable`; faults are not normal search stops. | `implementation/milestones/creativity/skeleton.md:112-116,139,146-147`; `orchestrator/README.md:432-463`; `orchestrator/task_api.py:276-287,1032-1089,1092-1114,1358-1390,1392-1453,1639-1718`; `orchestrator/task_execution.py:269-325`; `orchestrator/tasks.py:1597-1611` | wire the existing lifecycle and Stop/result boundary; do-not-add automatic task retry, recovery service, control route, event, error vocabulary or terminal status |
| F5 — Terminal search result | Normal completion is task `success`. `native_result` has exactly `outcome`, `proposals`, `stop_reason`, `generations_completed`, `evaluated_candidates`, `expansion_interventions`. Outcomes are `proposals` for a nonempty shortlist and `no_valid_candidates` otherwise. Stop reasons remain `generation_limit`, `evaluation_budget`, `persistent_stagnation`, `repertoire_exhausted`. Compose truthful counts and at most `shortlist_size` unique valid proposals from the eligible archive, preserving score/diversity selection and self-contained ordered components through `validate_creativity_native_result`. Cancellation/operational failure is never represented as successful exhaustion. | `implementation/milestones/creativity/skeleton.md:145-146`; `orchestrator/tasks.py:975-1066,1597-1611`; `orchestrator/creativity_search.py:32-45,92-121,223-291,294-337` | own native-result composition and common-envelope publication; do-not-change the existing nested result shape, invent proposals, execute proposals or treat structural validation as proof of truthful stopping |
| F6 — Workspace, access and deletion | Open/paused creativity tasks retain the existing workspace reservation; unrelated ownership prevents Resume. Existing project access applies to controls and deletion. Only a terminal, quiescent task can be deleted; deletion forgets its canonical record and includes its private creativity checkpoint in ordinary evidence cleanup. Repository/reference files and other tasks remain untouched. | `implementation/milestones/creativity/skeleton.md:63-68,129,149`; `orchestrator/task_api.py:416-427,559-583,1756-1800`; `orchestrator/service.py:4978-4989,5025-5038,5085-5145` | reuse access, reservation and deletion guards; extend task-private cleanup only; do-not-create permissions or promise secure erasure/transactional cleanup |
| F7 — Accounting authority | Every **recorded** physical attempt, across all three jobs, corrections, failures and Resume, contributes once by `call_id` through `record_physical_attempt_locked` and `record_result_locked`. Preserve job/generation/batch, actual family/model/effort, prompt fallback and available duration/tokens/cost evidence. The terminal envelope aggregates receipts without another charge and retains `token_usage_partial` / `cost_partial`. Accepted-candidate counts remain distinct from physical-attempt counts. | `implementation/milestones/creativity/skeleton.md:89-90,115-116,145,147`; `orchestrator/task_api.py:191-247,471-487,954-979`; `orchestrator/tasks.py:1512-1544`; `orchestrator/creativity_evaluation.py:45-68,144-160,233-240`; `orchestrator/runners.py:2978-3002,3052-3056` | reuse host accounting and runner evidence; do-not-add a ledger, charge again for result publication or claim complete evidence for unrecorded calls |
| F8 — Guarantee posture and trust | **Strict:** F1 ownership, F2 served structural reply acceptance, F3 successfully saved continuation/counts, F4 controls and terminal precedence, F5 result composition, F6 access/reservation/deletion admission, F7 aggregation of recorded receipts. **Optimistic:** each physical call's live authorities, without a transaction across them. **Best-effort:** provider-to-checkpoint delivery, auxiliary call evidence, usage availability, private evidence cleanup, semantic quality and worker exploration-only compliance. **Eventual:** no new mechanism; later panel freshness retains ordinary polling. Durability covers successful local writes across host-process interruption, with no provider exactly-once, backup or hardware-loss guarantee. Operator, product code, admitted data, checkpoints and libraries are trusted. | `implementation/milestones/creativity/skeleton.md:78-116,149-160`; `orchestrator/kvstore.py:509-523`; `orchestrator/task_api.py:559-583,969-979`; `orchestrator/creativity_search.py:1-6`; `orchestrator/prompt_contracts.py:891-896` | retain the surrounding standard-library/full-access posture; do-not-add sandboxing, snapshotting, dependency hardening, checkpoint repair or stronger delivery promises |

### Acceptance criteria and tests

The following are implementation obligations, not evidence of tests already
passing. Add focused composition cases in
`orchestrator/tests/test_creativity_task.py`, reusing the existing controlled
worker, call-group and service fixtures. Exercise the host with admitted test
orders without publishing the production catalogue. Each case observes task
records, saved continuation or worker-facing calls rather than private helper
ordering.

1. **T1 — `test_creativity_composes_search_and_results` (F1–F3, F5):** a small
   controlled search reaches gene creation, ordinary evolution, evaluation and
   due expansion through the real existing seams. Observe the admitted objective,
   context/references and exploration context at gene creation, served reply
   validation, unchanged fixed problem data, bounded work and the terminal
   shortlist. Reuse established stop fixtures to observe all four reasons and
   all-invalid success at task level; nested result validation uses its existing
   tests rather than a copied rejection matrix.
2. **T2 — `test_creativity_resume_keeps_saved_work` (F3–F5):** reopen with a fresh
   store/host after accepted genes, one accepted sibling batch, a completed
   generation, accepted expansion, and completed search awaiting terminal
   publication. Adoption issues no semantic calls. Explicit Resume keeps task
   and candidate identities, current job/generation, saved work, counts and remaining obligations;
   accepted current-regime work is not repeated, transitions are not counted
   twice, and a saved completed search needs no new provider call.
3. **T3 — `test_creativity_resume_reads_live_authorities` (F2–F3, F8):** saved
   material, prompt and staffing changes govern subsequent physical calls,
   including gene-creation correction and calls following Resume. Observe
   per-job rigor through the existing resolver. A changed evaluator regime
   requires the existing survivor reassessment before comparison, consumes
   allowance and earns no progress credit; a prompt-only edit does not do so.
4. **T4 — `test_creativity_controls_wait_for_quiescence` (F4):** Pause during
   gene creation, overlapping evaluation calls and expansion reaches all owned
   calls. The task retains an empty terminal slot and no replacement dispatch
   while previous work is unquiet; Resume becomes available only at the safe
   paused revision. Reuse service fixtures for stale/repeated Resume rejection
   and verify unrelated task calls remain unaffected.
5. **T5 — `test_creativity_faults_and_cancel_keep_lifecycle` (F3–F5):** provider,
   exhausted reply-correction, staffing and checkpoint-write faults preserve
   saved work and pause without automatic continuation. A failed save leaves
   work unfinished, never falsely accepted. Cancel during running/paused work,
   after restart, or before publication of a saved success settles as failure
   without new semantic calls once accepted. Keep completed-call evidence;
   an already terminal result never changes. Reuse the surviving-worker fixture
   to pin settlement after host interruption.
6. **T6 — `test_creativity_accounting_spans_resume_and_finish` (F7–F8):** include
   all three jobs, one response correction, reassessment, a paid fault and
   explicit Resume. Compare recorded call identities and summed accounting with
   the common lifecycle and terminal envelope on success and Cancel. Publication
   adds no physical charge; known partial usage stays partial. Test ordinary
   receipt handling, without promising recovery of absent auxiliary evidence.
7. **T7 — `test_creativity_ownership_and_deletion` (F1, F6):** shared service
   controls retain project access and workspace-conflict behavior for creativity.
   Paused work still reserves its workspace. Active/paused or unquiet terminal
   tasks cannot be deleted. With ordinary successful cleanup, terminal deletion
   forgets the task and its private checkpoint while preserving workspace,
   reference files and another task. The production catalogue and panel remain
   unchanged in this slice.

Acceptance requires T1–T7 plus the existing focused search/evaluation,
call-group, task-control, cancellation and accounting regressions to pass.
Implementation review also checks the F1/F8 edit and dependency boundaries.
This documentation-only draft runs no implementation suite.

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator would otherwise lose useful completed exploration or pay to repeat it after a pause/restart; an unfinished composition also cannot deliver one honest task result. Exposure is an interrupted or completing creativity task, not a hypothetical malicious operator. Saved search choices are reusable; provider spend is irreversible. The independent need is the skeleton's lifecycle assignment, and current code explicitly leaves persistence and iteration to its task owner. | `implementation/milestones/creativity/skeleton.md:112-116,129`; `orchestrator/creativity_search.py:165-170`; `orchestrator/creativity_evaluation.py:122-126,275-280` |
| machinery | Introduce thin creativity coordination/checkpoint/result wiring in the task-host surface and the missing gene-creation invocation in the existing creativity semantic surface. Extend recoverable/control eligibility and private cleanup. These serve one resumable task; `creativity_search`, `creativity_evaluation`, `LocalKVClient`, Prompt/Staffing Router and `TaskCallGroup` already provide the required motor, waves, persistence primitives and physical calls. No new runtime dependency, storage engine or public API is required. | `orchestrator/task_api.py:29,84-88,954-967,1831-1838`; `orchestrator/service.py:4978-4989`; `orchestrator/creativity_evaluation.py:71-126,173-195,275-289`; `implementation/milestones/creativity/skeleton.md:129,147,149` |
| consumers_touched | Verified runtime owners are `DirectTaskHost` dispatch/controls and service control/deletion handlers. The wave already takes an owner-supplied whole checkpoint; expansion already returns material for its owner to persist. These become consumers of the completed task composition. There is currently no public creativity admission or host branch; public order/read presentation remains Slice 9. Searches of all four granted roots found no implemented client of these Python seams or generic task routes; the Agent99 route hit is exploratory adoption documentation, not a live consumer. | `orchestrator/task_api.py:1831-1838`; `orchestrator/service.py:4992-5039,5103-5145`; `orchestrator/tasks.py:911-915`; `orchestrator/creativity_evaluation.py:122-126,173-195`; `implementation/milestones/creativity/skeleton.md:129-130`; `/Users/siddhartha/Development/source/life_prod/agent_99/implementation/brainstorming/milestone-orchestrator-adoption/design.md:3-10,19-22` |
| cheaper_alternative | Wire existing owners. Documentation/configuration alone cannot preserve the state the current search leaves to its caller; reordering a one-call task repeats work. Root/dependency searches found Elixir chat supervision, product datastore helpers and product runtime adapters, not a replacement for this Python task host. External [Temporal documentation](https://docs.temporal.io/develop/python) describes an SDK, service and worker model; adopting it would duplicate the existing lifecycle and violate this milestone's dependency boundary. | `orchestrator/creativity_search.py:165-170`; `orchestrator/kvstore.py:331-358`; `orchestrator/README.md:46`; `implementation/milestones/creativity/skeleton.md:70-76,149`; `/Users/siddhartha/Development/source/life/apps/life_orchestration/lib/life_orchestration.ex:1-3`; `/Users/siddhartha/Development/source/life_prod/life_product_components/elixir/apps/life_product_live/lib/life_product_live/task_supervisor.ex:1-12`; `/Users/siddhartha/Development/source/life_prod/life_product_components/elixir/apps/life_product_workspaces/lib/life_product_workspaces/datastore.ex:1-21`; `/Users/siddhartha/Development/source/life_prod/tutor/web/lib/tutor_web/director/runtime.ex:1-12`; linked primary documentation |
| cost | Build/review cost is one composition layer and seven focused behavioral cases using existing fixtures. No publicly admitted creativity records need migration; existing executor records retain their contracts. Operation adds local checkpoint writes around already bounded model work. Maintenance is continuation/result wiring and private cleanup, with no new service. Omission loses continuity and can repeat paid work. The implementation is reversible; completed model spend and deletion of task evidence are not. | `orchestrator/tasks.py:911-915,1245-1264`; `orchestrator/kvstore.py:348-358,509-523`; `orchestrator/task_api.py:416-427,559-583`; `implementation/milestones/creativity/skeleton.md:129,144,147` |
| threat_model | Untrusted actors are providers and authors of third-party reference text; they control reply content and instructions embedded in source material. Gene creation newly exposes those inputs to the existing served reply validator and exploration instructions; evaluation/expansion keep their own boundaries. The operator, product code, prompt/staffing documents, admitted configuration, accepted handoffs/checkpoints and libraries are trusted. No checkpoint-malformation defense, hostile-library test or tool sandbox is added. Worker effects and semantic truth remain best-effort. | `implementation/brainstorming/prompt-router/adapted-kinds/milestone/create_genes.json:10-29,34-57`; `orchestrator/prompt_contracts.py:547-574,891-914`; `orchestrator/creativity_search.py:1-6`; `implementation/milestones/creativity/skeleton.md:99-110,160` |
| pinned_facts | F1 pins owner/scope; F2 the existing semantic entry; F3 saved continuation and the cross-slice handoff; F4 control/fault/terminal semantics; F5 the existing result; F6 shared ownership/access/deletion; F7 sole accounting; F8 the strength and trust boundary of each guarantee. The table is canonical; internal checkpoint layout and helper ordering are implementation choices. | `implementation/milestones/creativity/skeleton.md:129-130,139-149`; `orchestrator/tasks.py:975-1066`; `orchestrator/task_api.py:219-247,276-287,471-487` |
| verification | T1–T7 add task-level observations over existing producer and host tests: retained batches, failed-save behavior, multi-call controls, revision/access refusal, surviving-worker cancellation and publication without duplicate spend. Fresh host/store instances verify persistence, not an in-memory continuation alone. These are future implementation checks; this draft only verifies source authorities and scope. | `orchestrator/tests/test_creativity_evaluation.py:24-71,590-644,952-981`; `orchestrator/tests/test_task_call_group.py:658-714`; `orchestrator/tests/test_task_controls_api.py:115-172,199-223,398-412`; `orchestrator/tests/test_task_cancel_recovery.py:77-143`; `orchestrator/tests/test_task_resume_accounting.py:115-127` |
| enforceability | F1/F4 use host recoverable eligibility, the task lease/group dispatch fence, revision CAS and durable Stop under the existing registry lock; F4/F5 use the sole immutable terminal transition. F2 uses the served contextual validator and per-attempt live preparation. F3 uses `LocalKVClient.get/put` with locked atomic replacement and the wave's sole-write-owner contract, plus existing progress/expansion handoffs; composing and persisting them is this slice's obligation. F5 uses eligible selection, component projection and native-result validation. F6 uses service access/workspace/deletion guards; cleanup retains its weaker posture. F7 uses call-id receipt replacement and terminal receipt aggregation. F8 limits claims to what these mechanisms express; no new guarantee requires stronger storage, semantic proof or a distributed transaction. | `orchestrator/task_execution.py:38-55,269-325`; `orchestrator/task_api.py:213-247,276-287,471-520,531-556,1032-1057,1756-1800`; `orchestrator/tasks.py:975-1066,1597-1611`; `orchestrator/creativity_evaluation.py:71-114,173-240,275-289`; `orchestrator/creativity_search.py:32-45,92-121,165-229,313-337`; `orchestrator/kvstore.py:340-358,408-430,509-523`; `orchestrator/service.py:4978-4989,5025-5038,5085-5145` |
