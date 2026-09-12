# Slice 07 — Progress, rebaseline, stagnation, and expansion

## Register 1 — INTENT

This slice lets an operator's creativity search distinguish useful improvement
from repeatedly trying the same possibilities. Small gains can accumulate. A
disappointing round, or keeping a different but lower-scoring candidate, should
not make the search ask for new material prematurely.

When the evaluator changes, the search reassesses the candidates it is keeping.
A more generous evaluator is not evidence of better ideas. When exploration
really stalls, the search can ask for additional choices, keep its best eligible
candidates, and try again within the operator's limits. It reports why further
exploration stopped, including when it found nothing valid.

### Dependencies and non-goals

This work connects the existing population motor, comparable evaluation results,
expansion prompt and reply checks, and controlled model-call boundary. It owns
progress decisions and their handoff to the task owner. It does not own the
operator's objective or judge whether a proposal will work in the world.

Complete task recovery, public ordering and presentation remain outside this
slice. There is no new search framework, service, configuration channel or
product integration, and the search takes no action on proposals.

### Risks and acceptance

Repeated evaluator changes can spend the available evaluations on reassessment.
Newly named choices can still mean much the same thing, and model scores can be
noisy. Keeping the archive protects useful work; it cannot recover model spend
or guarantee useful ideas. An evaluation allowance is not a fixed monetary cap.

Acceptance uses small score histories and controlled local workers through the
existing call boundaries. It observes decisions, retained candidates, model
inputs, accepted additions and work counts. No live model spend or creative
quality claim is needed.

## Register 2 — PINNED-FACTS TABLE

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Slice boundary and handoff | Extend `orchestrator/creativity_search.py`, `orchestrator/creativity_evaluation.py` and their focused tests. The named cross-slice contract is the **search-progress handoff**: the task owner can observe best/reference scores, patience, required survivor reassessment, expansion usage/evidence, the eligible archive and the search stop decision. Consume the existing **evaluation-wave handoff** from `evaluate_wave`; reuse `select_survivors`, `make_population`, `reproduce` and genome identity/component helpers. Private state layout and helper names are not contracts. | `implementation/milestones/creativity/skeleton.md:125-130,145`; `orchestrator/creativity_evaluation.py:112-134,198-211`; `orchestrator/creativity_search.py:25-45,73-97,144-160` | touch these search/evaluation surfaces; do-not-publish an executor, change lifecycle/checkpoint recovery, catalogue, routes/events/errors, panel, shared routing/staffing/validation/control/accounting policy, skeleton, goal, or any additional root |
| F2 — Cumulative progress | Within one evaluator regime, progress means best valid score minus the window's best-valid reference reaches `minimum_improvement`. Smaller gains do not move the reference. Recovered progress establishes the new reference and resets patience and consecutive expansion usage. A full `patience_generations` without that gain permits expansion; batches and reassessment calls are not additional search generations. Population average and invalid candidates never establish progress. An empty valid set supplies no invented score; the first valid best establishes a reference. | `implementation/milestones/creativity/skeleton.md:33-54,128,145`; admitted controls `orchestrator/tasks.py:897-948`; valid score selection `orchestrator/creativity_search.py:90-119` | own progress decisions over accepted comparable results; do-not-change scoring, selection/diversity policy, or disable ordinary mutation during productive generations |
| F3 — Rebaseline | Use `evaluate_wave`'s `regime_revision`, `rebaseline_required`, `comparison_ready`, `unfinished` and comparable `evaluated` results. A change in actual `(material, agent, model, effort)` within or between waves makes earlier-regime scores ineligible. Current valid survivors require current-regime evaluation without old scores or prestige; their reassessed valid best becomes the reference and starts a new window without progress credit or resetting consecutive expansion usage. Any other candidate needs matching-regime evaluation before selection. Reassessment that reports a candidate invalid excludes it. An incomplete comparison supplies no selection or progress decision; reassessment consumes `max_evaluated_candidates` allowance. Prompt edits alone require no rebaseline. | `implementation/milestones/creativity/skeleton.md:49-54,91-96,145`; `orchestrator/creativity_evaluation.py:33-43,103-134,144-179,198-211`; `orchestrator/creativity_search.py:90-119` | own reassessment obligations and reference changes; trust the wave's eligibility/attribution contract rather than duplicating it or rescoring historical work outside its budget |
| F4 — Bounded variant expansion | After a full stagnant window, an available intervention under `max_stagnation_expansions` may add variants only to existing dimensions. Expansion retains the eligible best archive, existing choices and all fixed problem fields, and starts a new window from the current best without claiming progress or clearing consecutive expansion usage. Only recovered progress clears that usage; lifetime `expansion_interventions` does not reset. Incorporate accepted `{id,text}` choices and retain their returned `reason` as expansion evidence. Preserve dimension identities, meanings and order. A new ID is structural novelty, not proof of a new idea. | `implementation/milestones/creativity/skeleton.md:33-45,141-145`; `orchestrator/prompt_contracts.py:605-625`; `implementation/brainstorming/prompt-router/adapted-kinds/milestone/expand_genes.json:18-32,79-89`; `orchestrator/creativity_search.py:30-45,90-119` | own incorporation and intervention decisions; do-not-replace the archive, mutate constraints/criteria, evolve the dimension schema, add semantic deduplication or introduce another expansion limit/default |
| F5 — Routed expansion boundary | Use `expand_genes@creativity`, `executor="agent_call"`, kind `expand_genes`, and the served `expand_genes_result` validator with current `dimensions`. Inputs are `objective`, complete current `search_material`, `promising_candidates` without historical score/rank/prestige fields, and `explored_account`. Every physical attempt reads live material, Prompt Router and `creativity_job_staffing_request("expand_genes", configuration)` / Staffing Router (`role="brainstorm", index=1`; job > task default > session rigor). The closed reply is `{"additions":[{"dimension_id":…, "variants":[{"id":…, "text":…, "reason":…}]}]}`; `{"additions":[]}` is accepted, unknown dimensions/reused variant IDs are rejected by the existing validator. Use the host-owned `TaskCallGroup.call_worker`, existing one response correction and per-attempt job/generation/batch evidence. Correction belongs to the same intervention. Staffing conditions remain `staffing_unavailable` and `distinct_families_unsatisfiable`. Operational faults/interruption are not empty additions or normal search stops. | `orchestrator/prompt_router.py:44-46,467-503`; `orchestrator/tasks.py:904-907,965-972`; `orchestrator/staffing.py:1767-1779,2045-2072`; `orchestrator/prompt_contracts.py:605-625,891-914`; `implementation/brainstorming/prompt-router/adapted-kinds/milestone/expand_genes.json:38-66`; `orchestrator/runners.py:3013-3017,3035-3056`; `orchestrator/task_execution.py:294-325` | wire the established invocation seams, preserving fallback and control behavior; do-not-add prompts, parsers, retries, worker dispatch paths, error vocabulary or a second accounting ledger |
| F6 — Honest limits and stop reasons | Normal `stop_reason` is exactly `generation_limit` when the admitted generation count is completed; `evaluation_budget` when capacity prevents another required candidate evaluation, including rebaseline; `persistent_stagnation` for another full stagnant window after the allowed consecutive expansions; or `repertoire_exhausted` when no unseen genome remains and an allowed expansion returns no novel variant. An empty expansion while unseen genomes remain, absent valid parents, or random collisions alone do not prove repertoire exhaustion. Progress/expansion never bypass a completed generation cap or evaluation allowance. Expose truthful `generations_completed`, `evaluated_candidates` and `expansion_interventions` for later result composition; valid and invalid accepted evaluations both count, reassessment counts again, response correction does not double accepted evaluations. No valid candidates remains an explicit empty result possibility. | `implementation/milestones/creativity/skeleton.md:144-146`; `orchestrator/tasks.py:975-1005`; `orchestrator/creativity_evaluation.py:144-179,198-211`; finite repertoire supply `orchestrator/creativity_search.py:48-87,144-160` | own stop decisions and search counts; do-not-use the terminal shape validator as proof of truthful stopping, invent a score-target stop, pad candidates or emit task terminal envelopes here |
| F7 — Guarantee posture | **Strict:** F2–F4 arithmetic, eligibility, allowance and preservation; F5 served-input/structural acceptance and inherited dispatch fences; F6 truthful decisions/counts. **Optimistic:** live material/prompt/staffing reads, with no transaction across them and no rewrite of dispatched calls. **Best-effort:** semantic validity, score calibration, useful expansion, meaningful difference, worker exploration-only compliance, auxiliary evidence persistence and provider usage availability. Recorded calls retain existing accounting; this slice adds no provider exactly-once or recovery guarantee. **Eventual:** no new mechanism here; panel polling belongs to its existing owner. Operator, product code, admitted data, emitted handoffs/checkpoints and libraries are trusted. | `implementation/milestones/creativity/skeleton.md:78-116,149-160`; `orchestrator/creativity_search.py:1-6`; `orchestrator/prompt_contracts.py:891-896`; `orchestrator/task_execution.py:269-325`; `orchestrator/task_api.py:954-979` | test this slice's own decisions and call wiring; do-not-police trusted producers, add sandboxing, recovery infrastructure or stronger persistence/security claims |

### Acceptance criteria and tests

These are implementation obligations, not passing runtime evidence from this
draft. Add the decision cases to `orchestrator/tests/test_creativity_search.py`
and invocation/handoff cases to `orchestrator/tests/test_creativity_evaluation.py`.
Use accepted-material fixtures and the real wave, router, validator and call-group
seams with controlled workers. Tests observe F1's handoff and provider-facing
inputs rather than prescribing private state or call ordering.

1. **T1 — `test_cumulative_best_valid_progress` (F2):** reference `0.25`,
   improvement threshold `0.125`, then best scores `0.3125` and `0.375` retain
   the original reference until the exact cumulative threshold is reached.
   Observe the resets on that gain. A falling average, one poor generation
   within a longer patience window and a higher-scoring invalid candidate do
   not trigger expansion or fake progress. All-invalid observations invent no
   reference; a later valid candidate establishes one.
2. **T2 — `test_rebaseline_without_progress_credit` (F3):** extend the existing
   live regime-change fixtures across and within waves. Observe requests for
   current survivors, clean evaluation inputs and withheld selection until the
   comparison is ready. Higher reassessed scores reset the reference/window,
   consume evaluation allowance and preserve consecutive expansion usage.
   Include a survivor newly judged invalid, a late old-regime completion and
   prompt-only edits. The tests exercise the progress consumer, without adding
   another eligibility checker around the wave.
3. **T3 — `test_full_windows_bound_expansion` (F2, F4):** no intervention before
   a full stagnant window; one eligible intervention starts another full window.
   After the configured consecutive interventions, the next complete stagnant
   window stops. Genuine cumulative progress restores the allowance; expansion
   and rebaseline do not. Total interventions remain cumulative. Productive
   generations retain ordinary mutation through the existing motor.
4. **T4 — `test_expansion_uses_live_routed_contract` (F5):** inspect all four
   required inputs, including the complete expanded material on a later call,
   and absence of historical score/rank fields. Save live material, prompts and
   staffing before another attempt, including a correction; observe the served
   inputs and per-job rigor. Exercise accepted empty additions and producer-owned
   unknown-dimension/reused-ID rejection cases. Only a validated reply supplies
   additions; one correction does not create another intervention.
5. **T5 — `test_expansion_preserves_material_and_archive` (F4):** add variants
   within a subset of dimensions. Observe unchanged fixed problem fields,
   dimensions, existing variants and eligible retained genomes; new choices
   become available to the existing motor and their reasons remain observable.
   Equal text under a new valid ID is accepted without a semantic novelty claim.
6. **T6 — `test_exact_search_stop_reasons` (F6):** independently reach each
   stop trigger and observe its exact token, counts and absence of further
   disallowed work. Include budget exhaustion during reassessment, completion of
   the last admitted generation, and a fully exhausted tiny repertoire plus
   an empty allowed expansion. Empty expansion with unseen choices, no valid
   parents with unseen choices, and repeated random draws do not establish
   exhaustion. An all-invalid run retains an empty eligible archive; no proposal
   or score-target completion is fabricated.
7. **T7 — `test_expansion_faults_keep_shared_controls_and_evidence` (F5, F7):**
   an expansion uses the existing group's stop/interruption boundary and does
   not turn interruption, staffing failure or exhausted response correction
   into search exhaustion. Inspect ordinary per-attempt evidence, including a
   correction's separate physical charge, through the shared accounting seam.
   No new replay, dependency-fault matrix or full task Resume test is introduced.

Acceptance requires T1–T7 and the existing focused search/evaluation regressions
to pass. Reuse the producer contract tests rather than recreating their malformed
reply matrix. This draft runs no implementation tests and claims no completed
runtime integration.

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator can otherwise pay for repeated stagnant exploration, stop despite cumulative gains, or mistake evaluator generosity for better ideas. Exposure is a creativity search reaching a progress or evaluator-change boundary; choices are reversible, incurred model spend is not. The skeleton independently requires these decisions, and the existing wave explicitly leaves reassessment and progress-reference ownership to its caller. | `implementation/milestones/creativity/skeleton.md:39-54,128,145`; `orchestrator/creativity_evaluation.py:124-133,198-211` |
| machinery | New machinery is limited to progress/reference and intervention decisions in the existing search surface, the handoff that requests survivor reassessment through `evaluate_wave`, and a routed expansion caller using `TaskCallGroup`. Each closes a concrete missing outcome: cumulative progress, fair comparisons, bounded renewed exploration or honest stopping. Existing selection, repertoire supply, prompt validation, staffing and physical-call controls remain their owners. No new module, runtime dependency, store or public API is needed. | `orchestrator/creativity_search.py:1-6,73-97,144-160`; `orchestrator/creativity_evaluation.py:112-134`; `orchestrator/task_execution.py:294-325`; `orchestrator/prompt_contracts.py:605-625`; `implementation/milestones/creativity/skeleton.md:128` |
| consumers_touched | The concrete integration touched is the wave-to-search handoff: current tests already feed accepted wave results into the selector. Runtime evaluation currently uses the search component projection. There is no live creativity executor to claim as a consumer: admission remains preparatory and host dispatch has no creativity branch. Slice 8 is the authorized task-owner consumer of the new handoff. Searches of all four granted roots, their dependency manifests and available source found no alternate progress engine or client for these seams; no product root is touched. | `orchestrator/tests/test_creativity_evaluation.py:59-71,440-443`; `orchestrator/creativity_evaluation.py:33-43`; `orchestrator/tasks.py:911-915`; `orchestrator/task_api.py:1831-1838`; `implementation/milestones/creativity/skeleton.md:128-130,149` |
| cheaper_alternative | Extend the two existing modules. Configuration or documentation alone cannot make the wave's caller decide progress or reassessment, and the result validator expressly does not prove truthful counters/stops. The external reuse check found general evolution/archive support in [DEAP](https://deap.readthedocs.io/en/master/api/algo.html) and window/limit termination in [pymoo](https://pymoo.org/interface/termination.html). Those documented primitives would still need this task's regime and routed-expansion wiring. Extending the existing modules is the smaller integration and respects the no-new-dependency boundary. | `orchestrator/creativity_evaluation.py:124-133`; `orchestrator/tasks.py:975-982`; `orchestrator/README.md:46`; `implementation/milestones/creativity/skeleton.md:70-76,145,149`; linked primary library documentation |
| cost | Build/review cost is two small module extensions and seven focused behavioral cases. No deployed creativity state or external consumer needs migration. Operation adds reassessment charged to the evaluation allowance and bounded expansion calls; existing accounting exposes their spend. Maintenance stays with existing search and invocation seams. Omission leaves misleading progress and stop decisions. Code changes are reversible; completed provider work is not. | `orchestrator/tasks.py:911-915`; `orchestrator/creativity_evaluation.py:144-179`; `orchestrator/task_api.py:954-979`; `implementation/milestones/creativity/skeleton.md:128-129,145,147` |
| threat_model | Untrusted actors are model providers and authors of third-party text carried in admitted material; their expansion replies can name foreign dimensions, reuse IDs or contain misleading prose. The existing contextual validator rejects structural violations; semantic claims remain best-effort. The authorized operator, product code, prompt/staffing configuration, accepted material, wave handoffs, checkpoints and standard library are trusted. The new caller validates provider replies, not imagined malformation by those trusted producers. Full-access worker effects are not contained by JSON validation. | `orchestrator/prompt_contracts.py:605-625,891-896`; `implementation/brainstorming/prompt-router/adapted-kinds/milestone/expand_genes.json:18-32`; `implementation/milestones/creativity/skeleton.md:99-110,160`; `orchestrator/README.md:631-634` |
| pinned_facts | F1 pins ownership and the named cross-slice handoff; F2 cumulative comparison; F3 regime/reassessment semantics; F4 variant-only bounded expansion; F5 the existing routed job, inputs and reply admission; F6 exact stop vocabulary/counts; F7 the strength and trust boundary of those guarantees. Numeric examples in T1 are test data, not defaults. | `implementation/milestones/creativity/skeleton.md:128,140-147`; `orchestrator/creativity_evaluation.py:198-211`; `orchestrator/prompt_contracts.py:605-625`; `orchestrator/tasks.py:975-1005` |
| verification | T1–T7 pin the new producer's outputs and its use of real shared boundaries. Existing tests supply controlled score histories, exact repertoire shortages, live regime changes, contextual expansion rejection and task-owned call fixtures. Read-only source checks verify ownership and dependencies; this note does not claim those future tests already pass. No purchased model run, semantic-quality benchmark or hostile-library testing is required. | `orchestrator/tests/test_creativity_search.py:97-137,235-275`; `orchestrator/tests/test_creativity_evaluation.py:24-81,467-538`; `orchestrator/tests/test_prompt_contracts.py:154-187` |
| enforceability | F2 uses admitted numeric controls and the selector's valid scores for ordinary difference/counter predicates. F3 uses the wave's actual revision, readiness and unfinished-ID API; its existing allowance reservation/accepted count bounds reassessment. F4 uses the contextual additions validator, stable genome/component representation and existing valid-survivor selection; incorporation must preserve the observable old material. F5 uses the runner's per-attempt preparation/dispatch hooks, fresh resolvers, served validator and group dispatch/quiescence fence. F6 combines those authoritative counts and finite repertoire supply with the new stop decision; the terminal validator enforces vocabulary only. F1/F7 scope and posture are checked against these owners. These seams can express the promised guarantees; decision/invocation wiring is this slice's implementation obligation. No semantic truth, atomic cross-authority read or stronger recovery guarantee is asserted. | `orchestrator/tasks.py:911-948,975-996`; `orchestrator/creativity_search.py:25-45,48-119`; `orchestrator/creativity_evaluation.py:124-179,198-211`; `orchestrator/prompt_contracts.py:605-625,891-914`; `orchestrator/runners.py:3035-3056`; `orchestrator/prompt_router.py:467-503`; `orchestrator/staffing.py:1767-1779,2045-2072`; `orchestrator/task_execution.py:269-325` |
