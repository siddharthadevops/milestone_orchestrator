# Creativity: cross-domain evidence

## Current evidence boundary

Controlled checks T1 and T3 pass. The real creativity/direct-ideation pairs
(M1), their retained call evidence and budget comparison, and the evidenced
catalogue defaults and admission/form checks (T2) remain incomplete. No real
model was called for this controlled exercise. Its numbers are fixture work
limits and simulated accounting, not measured provider spend or catalogue
defaults.

Executed on 2026-09-12 against base revision
`83823d73524dcb1ab22c5cf35367f17f1eb2fc2e` plus this implementation's examples
and `test_creativity_cross_domain_contracts` change.

## Common problem inputs

| Input | Objective and criteria |
| --- | --- |
| [Language](examples/language.json) | Three Spanish story openings: concrete action, emotional tension, economical language and different possibilities; each at most 24 words. |
| [Business](examples/business.json) | Three bicycle-shop revenue pilots: itemised feasibility, paid-demand signal and different offers; EUR 120, six staff hours, two weeks, existing tools and opted-in customers. |

Each file supplies the ordinary request text, context (including facts,
constraints, assumptions, unknowns and criteria), and an empty ordered reference
list. These fictional problems need no external source material. Neither file
contains genes, generated proposals or scores. Scripted dimensions and expansion
replies live only in the conformance test. In the eventual direct comparison,
the complete common input must appear in the `agent_call` request text itself;
its separate context field alone does not reach that worker.

## Controlled task evidence

The test submits each problem through `GET /api/task-executors` and
`POST /api/tasks`, then reads the completed task through `GET /api/tasks/<id>`.
It uses the existing HTTP/host fixture, real search motor, live routers,
registered reply validators, checkpoint store and physical-call accounting.
Only the worker replies and staffing document are controlled. Task IDs and
receipts exist in temporary fixture storage and are checked before cleanup;
they are not retained real-model evidence.

The submitted numeric configuration is:

| Control | Controlled value |
| --- | ---: |
| population_size | 4 |
| generation_limit | 4 |
| max_evaluated_candidates | 16 |
| elite_count | 2 |
| diversity_count | 1 |
| mutation_rate | 0.5 |
| minimum_improvement | 0.1 |
| patience_generations | 2 |
| max_stagnation_expansions | 1 |
| evaluation_batch_size | 2 |
| evaluation_concurrency | 2 |
| shortlist_size | 3 |

| Problem | Material | Scripted dimensions | Generations / evaluated / expansions | Physical attempts | Outcome / stop |
| --- | --- | --- | --- | ---: | --- |
| Language | default | action, trace | 4 / 16 / 1 | 10 | proposals / generation_limit |
| Language | literature | action, trace | 4 / 16 / 1 | 10 | proposals / generation_limit |
| Business | default | offer, delivery | 4 / 16 / 1 | 10 | proposals / generation_limit |
| Business | business | offer, delivery | 4 / 16 / 1 | 10 | proposals / generation_limit |

Each run retains the accepted fixed problem data across later calls, admits
only known variants, and returns at most three unique genomes with readable
components. A scripted invalid candidate scores 1.0; the best valid candidate
scores 0.6 and subsequent candidates score 0.4. The invalid candidate is absent
from expansion's promising set and the final shortlist. The best valid candidate
is present in both. Two complete stagnant generations lead to variant-only
expansion after generation three, preserving the original dimensions and variants.

A barrier holds the first two evaluation calls until both have entered; the
observed peak is two simultaneous calls. Every batch contains at most two
candidates and accepted replies cover exactly its candidate IDs. Each run has
one gene call, eight evaluation calls and one expansion call. Recorded call IDs,
batch/generation identities, material and dispatch staffing agree with the work;
the stored default prompt set serves every call without whole-set fallback.
Aggregate duration, input/output tokens and API/real cost equal the sums of
the ten recorded attempts. Token and cost partial flags are false for these
simulated complete receipts.

| Job / role | Selected rigor | Observed controlled family / model / effort |
| --- | --- | --- |
| create_genes / plan seat 1 | job high | claude / claude-fable-5 / max |
| evaluate_candidates / review seat 1, breadth 1 | job low | codex / gpt-5.6-luna / low |
| expand_genes / brainstorm seat 1 | task default medium | claude / claude-opus-5 / medium |

The session retains rigor high and is unchanged by all dispatches. Layered
calls carry the corresponding refinement; generic calls do not. T3 supplies
the existing full rigor-inheritance and prompt-contract matrices, serial and
concurrent bounds, live authority changes, rebaseline without progress credit,
and all four normal stops including empty success.

## Focused verification

T1: one test with four domain/material subtests passed in 2.833 seconds.

```sh
python3 -m unittest orchestrator.tests.test_creativity_task.CreativityTaskTest.test_creativity_cross_domain_contracts
```

T3: all six existing tests passed in 0.517 seconds; their matrices were reused.

```sh
python3 -m unittest \
  orchestrator.tests.test_prompt_router.PromptRouterTest.test_creativity_jobs_and_materials \
  orchestrator.tests.test_tasks.TaskContractsTest.test_creativity_job_staffing_contract \
  orchestrator.tests.test_creativity_evaluation.CreativityEvaluationTest.test_wave_bounds_and_candidate_allowance \
  orchestrator.tests.test_creativity_evaluation.CreativityEvaluationTest.test_each_attempt_reads_live_authorities \
  orchestrator.tests.test_creativity_evaluation.CreativityEvaluationTest.test_rebaseline_without_progress_credit \
  orchestrator.tests.test_creativity_task.CreativityTaskTest.test_creativity_composes_search_and_results
```

The complete suite remains for the driver's scheduled checkpoint. This exercise
establishes mechanical behavior only: neither scripted scores nor a future small
real-model sample establish creative superiority or real-world feasibility.
