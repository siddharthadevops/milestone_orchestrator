# Creativity: cross-domain evidence

## Current evidence boundary

The replacement language and business pairs are complete and matched under their
predeclared accounting tolerance. M1 records their outputs, charges and limitations
below, and the twelve measured numeric controls are published as catalogue
defaults. T1, T2 and T3 pass; controlled checks establish mechanical contracts
separately from model quality. The earlier language pilot remains incomplete, partial and
unmatched; its unknown charge is not erased by the replacement comparison.

Initial controlled checks executed on 2026-09-12 against base revision
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
replies live only in the conformance test. In each direct comparison,
the complete common input appears in the `agent_call` request text itself;
its separate context field alone does not reach that worker.

## Replacement comparison

The [replacement declaration](evidence/comparison/declaration.json) was written
at 2026-09-12T14:08:24.400825Z against revision
`6fe04a6a8350f5925cdaac23c645a6cce3b6dc0d`, before its first dispatch. It declares
USD 0.015 API-equivalent per task and the same 50% relative-difference tolerance,
requiring complete positive totals for both members of each pair. The proposed
search allowance is two generations and eight evaluations in batches of four;
the direct request asks it to consider eight alternatives and return three.
This reduces the third-generation overhead exposed by the pilot. These are
experimental work targets and explicit trial controls at dispatch, not enforced
spend caps. The defaults review below adopts the measured numeric values.
The old pilot's missing charge and failed comparison are preserved.

The [submitted order](evidence/comparison/language-agent_call-order.json),
[session](evidence/comparison/language-agent_call-session.json),
[physical transcript](evidence/comparison/language-agent_call-call-01.json),
[worker receipt](evidence/comparison/language-agent_call-worker.json) and
[terminal task](evidence/comparison/language-agent_call-task.json) retain the
new baseline `00e02a9f-a717-4466-9835-066338109c08`. The existing
[staffing document](evidence/staffing.json) is reused unchanged. The worker
received the complete language fixture, including all context and reference
paths, three-proposal request and exploration-only instruction. It received no
search-produced material. Actual dispatch was Codex `gpt-5.6-luna` at max effort;
the retained admission projection says `gpt-5.6-sol`/xhigh and is not dispatch
evidence. Both the runner transcript and worker receipt record Luna/max.
The session selects `literature`; this ordinary agent call has no routed job,
generation, batch or prompt-fallback record.

| Physical call | Duration s | Input / cached / output / reasoning tokens | API USD | Partial tokens / cost |
| --- | ---: | --- | ---: | --- |
| `ecb39c28-14dc-4b14-bcc0-ad69a08651b3` | 206.48500728607178 | 18310 / 15104 / 11160 / 10876 | 0.01433528 | false / false |

The one recorded attempt used 95.6% of its target. Subscription real cost is
USD 0; cached input is included in input and reasoning output in output. The
controlled size cutoff requested Pause during this call. It nevertheless
completed and left a successful `completed_result` in the
[paused response](evidence/comparison/language-agent_call-paused-task.json).
After process quiescence, explicit Resume published that saved result without
another physical call; the terminal envelope contains its accounting once.
The [task store](evidence/comparison/task-store.json) preserves the final store
bytes. The temporary service home is
`/var/folders/_d/j9g16_hn2psglg_vgfl_8z680000gn/T/creativity-slice10-comparison-f92_3y8d`;
the service was reopened for the remaining declared tasks below and is now
stopped with all four replacement tasks terminal.

Human inspection: the three openings count holes in a net, pocket a thread
after a forgotten embrace, and cut a thread after a forgotten farewell. They
contain 22, 23 and 19 whitespace-delimited words; the third self-check incorrectly
says 20. All fit the length bound, give the daughter an action, avoid explaining
the cause and end without a question. Silence, returning boat noise and a
lighthouse sweep supply different sensory traces. Only the first explicitly
anchors net repair; the latter two add assumed intimate events. The first's
forgotten knot is less clearly an emotional cost. These observations assess the
supplied criteria without treating a model self-check as an independent judge.

Baseline-cut verification: all eight retained JSON files parse; common-input equality,
dispatch/session evidence, original store/worker bytes and one-charge result
handoff agree. Existing `test_agent_call_success_during_pause_is_retained_until_resume`
and `test_public_pause_waits_for_active_call_and_resume_reuses_its_result` passed
(two tests, 2.252 seconds). `git diff --check` passed. The complete suite remains
reserved for the scheduled checkpoint.

### Completed pairs and M1 review

The remaining three tasks ran on 2026-09-12 against
`2e143944e0514c60e5994ccc3201b598eb7e6c57`, before the default-admission edit,
using the same service home, staffing document, public routes and declaration.
No allowance, tolerance, problem input or trial control changed after dispatch.
The baseline always preceded its search and received the complete common problem
in its request text, with no search-produced genes, proposals or scores.

| Task and actual output | Task ID | Submitted order / session / checkpoint |
| --- | --- | --- |
| [Language creativity](evidence/comparison/language-creativity-task.json) | `c3c0c52a-d86a-4656-9fe4-ede209576707` | [Order](evidence/comparison/language-creativity-order.json), [session](evidence/comparison/language-creativity-session.json), [checkpoint](evidence/comparison/language-creativity-checkpoint.json) |
| [Business direct](evidence/comparison/business-agent_call-task.json) | `38b8bf77-df64-4a2e-b028-8b15e78b3c7a` | [Order](evidence/comparison/business-agent_call-order.json), [session](evidence/comparison/business-agent_call-session.json), [worker receipt](evidence/comparison/business-agent_call-worker.json) |
| [Business creativity](evidence/comparison/business-creativity-task.json) | `1a0c772a-1a35-421d-ab3e-c43435e5a6b6` | [Order](evidence/comparison/business-creativity-order.json), [session](evidence/comparison/business-creativity-session.json), [checkpoint](evidence/comparison/business-creativity-checkpoint.json) |

Every task succeeded. Both searches returned three unique, evaluator-reported
valid proposals after two generations and eight accepted candidate evaluations,
with zero expansions and stop reason `generation_limit`. Language dimensions are
daughter action, sensory trace, emotional stake and opening rhythm; business
dimensions are revenue offer, delivery arrangement, customer selection,
commitment model and pilot boundary. All final components name known variants.

Actual calls used Codex `gpt-5.6-luna`: creation at medium effort, evaluation at
low and direct ideation at max. The search configuration selects task-default
medium and evaluation-specific low; sessions retain high. Search calls record
`literature` or `business` material and null prompt-set fallback. Ordinary direct
calls supply no routed job, generation, batch or prompt-fallback record. Actual
call IDs and batch IDs are retained in the linked task histories and direct
worker receipts; resolved orders are in each task response.

| Physical transcript | Job / generation | Duration s, rounded | Input / cached / output / reasoning tokens | API USD |
| --- | --- | ---: | --- | ---: |
| [Language 02](evidence/comparison/language-creativity-call-02.json) | create_genes / 0 | 20.952918 | 18948 / 9984 / 972 / 73 | 0.00315888 |
| [Language 03](evidence/comparison/language-creativity-call-03.json) | evaluate_candidates / 1 | 28.380546 | 20748 / 5888 / 1379 / 707 | 0.00474456 |
| [Language 04](evidence/comparison/language-creativity-call-04.json) | evaluate_candidates / 2, malformed JSON | 19.497340 | 20761 / 15104 / 822 / 179 | 0.00241988 |
| [Language 05](evidence/comparison/language-creativity-call-05.json) | evaluate_candidates / 2, contract correction | 24.036040 | 20802 / 2816 / 1116 / 487 | 0.00499272 |
| [Business 06](evidence/comparison/business-agent_call-call-06.json) | direct ideation | 99.759118 | 18376 / 5888 / 5297 / 4660 | 0.00897176 |
| [Business 07](evidence/comparison/business-creativity-call-07.json) | create_genes / 0 | 39.475680 | 21403 / 19200 / 1422 / 345 | 0.00253100 |
| [Business 08](evidence/comparison/business-creativity-call-08.json) | evaluate_candidates / 1 | 43.876126 | 27838 / 26368 / 1599 / 402 | 0.00274016 |
| [Business 09](evidence/comparison/business-creativity-call-09.json) | evaluate_candidates / 2 | 29.888722 | 21116 / 9984 / 1460 / 431 | 0.00417808 |

All these attempts have token/cost partial flags false and subscription real cost
USD 0. Cached input is included in input, reasoning output in output. The failed
language reply contributes its charge once; only its corrected four-candidate
reply is accepted. Language search totals 92.866844 seconds and 85,548 tokens;
business direct totals 23,673 tokens; business search totals 113.240528 seconds
and 74,838 tokens. Each evaluation batch has four candidates, with exact accepted
ID coverage and one simultaneous call. T1 supplies the separate overlap and
expansion evidence; neither occurred in these modest real runs.

| Pair | Direct / creativity API USD | Direct / creativity share of USD 0.015 target | Relative difference | Declared result |
| --- | --- | --- | ---: | --- |
| Language | 0.01433528 / 0.01531604 | 95.6% / 102.1% | 6.4% | matched, below 50% |
| Business | 0.00897176 / 0.00944924 | 59.8% / 63.0% | 5.1% | matched, below 50% |

The common USD unit has complete positive totals for all four tasks, including
the unsuccessful language attempt. The language search slightly exceeded its
target; the target is not a cap. Different cache usage and variable reasoning
work affect these amounts. Matching spend does not establish equal useful work.

Language review: the search openings contain 23, 24 and 22 whitespace-delimited
words, each one Spanish sentence with concrete action and no explanatory cause,
new name or final question. All retain net-related action. Tying a net, marking
one after a tug and holding the father's hand offer different emotional stakes.
The wet thread requires an assumption to signal lost time; the second opening
does not itself make the missing minute clear; the third assumes a hidden truth.
The direct openings and their limitations are inspected above. Neither set
establishes superiority or eliminates the operator's editorial judgment.

Business review: direct ideation itemises three different offers: five EUR 35
tune-ups (EUR 0, four hours), a four-seat EUR 25 clinic (up to EUR 25, four hours),
and eight EUR 18 inspections (EUR 0, 4.84 hours). Each includes day-seven paid
demand thresholds and a continue/stop decision. Clinic space, zero consumable
costs and delivery timings remain assumptions, not verified shop feasibility.
The search instead returns a maintenance check and two repair bundles, varying
prepaid appointments, targeting and drop-off windows. Its reasons acknowledge
that price, slot counts, cash and complete labour itemisation are missing.
Those outputs do not demonstrate the requested feasibility criterion; their
continue/stop thresholds are also unspecified, and two offers sell the same
service value. Evaluator-reported validity and structural difference do not
prove feasibility or materially different offers. No semantic repair or judge
call was added to improve this recorded comparison.

### Evidenced catalogue defaults

The catalogue adopts exactly the twelve measured numeric controls. This is a
small initial exploration allowance, not a tuned optimum or a quality guarantee.
Both examples completed it and produced inspectable shortlists; the business
weakness above remains visible. The earlier third-generation pilot exposed
additional overhead, supporting a modest two-generation starting point.

| Control | Default | Workload rationale |
| --- | ---: | --- |
| population_size | 4 | Four alternatives per generation in both examples. |
| generation_limit | 2 | Initial exploration plus one evolved generation. |
| max_evaluated_candidates | 8 | Covers both four-candidate generations; rebaselining shares this allowance. |
| elite_count | 2 | Retains two strong valid combinations in the measured search. |
| diversity_count | 1 | Reserves one structurally different survivor alongside the elites. |
| mutation_rate | 0.35 | Measured nonzero ordinary mutation; this sample does not calibrate its optimum. |
| minimum_improvement | 0.05 | Measured cumulative-gain threshold; scores remain objective-relative. |
| patience_generations | 1 | One full stagnant window before an eligible expansion; larger limits are needed to explore beyond these completed runs. |
| max_stagnation_expansions | 1 | Bounds a consecutive intervention sequence; T1 verifies its mechanics, not an empirical optimum. |
| evaluation_batch_size | 4 | One bounded evaluation call per generation avoids additional prompt overhead. |
| evaluation_concurrency | 1 | Serial dispatch sufficed for these small examples; T1 separately proves configured overlap. |
| shortlist_size | 3 | Matches both common problems and both direct requests. |

Omitted rigor stays inherited; the measured session and job rigor choices are
not catalogue defaults. Model, effort, material, response length, corrections and
cache usage can change future cost. The service and form consume this one
catalogue through the existing resolver/schema path. Explicit complete orders
retain their values; partial orders fill only omitted numeric controls and still
must satisfy every existing bound and relationship. No stored order is migrated.

M1 verification checked retained JSON, complete common input at both worker
boundaries, unchanged live sessions/staffing, exact task-store/checkpoint copies,
accepted batch coverage, counters, terminal outputs, summed physical accounting
and the declared tolerance. Published defaults equal the measured numeric order.
The temporary service exited normally after all three remaining tasks completed.

## Earlier language pilot: incomplete and unmatched

[Declaration](evidence/declaration.json) was written at
2026-09-12T13:48:19.734271Z, before either measured task. Execution used revision
`2df9039a57f38718d949cc7ee43c88e888a90579` on 2026-09-12. The allowance is USD 0.03
API-equivalent per task, with complete positive totals required and
`abs(creativity - agent_call) / max(creativity, agent_call) <= 0.5` for a match.
It is an experimental target, not an enforced spending cap. The declaration
also retains all twelve explicit trial controls; those are not catalogue defaults.

The existing service and `DirectTaskHost` ran in a temporary service home, bound
to project `orchestrators`, work area `implementation`, the primary workspace
and all four read-only additional roots. Tasks used `POST /api/tasks` and
`GET /api/tasks/<id>`. The [staffing document](evidence/staffing.json) selected
Codex `gpt-5.6-luna`: direct ideation at max effort, gene creation/expansion at
medium and evaluation at low. The baseline's stronger effort was the planned
allowance counterweight to multiple search calls, not evidence of equal spend.
Both used the same common problem; the direct worker received its complete JSON,
empty reference list, three-proposal request and exploration-only instruction.
The baseline ran first and received no search-produced material.

| Task | ID | Retained result |
| --- | --- | --- |
| [Language direct](evidence/language-agent_call-task.json) | `be0c1d70-57fc-4278-b073-27c28dec14cc` | Success; three openings and their reasons/assumptions. |
| [Language creativity](evidence/language-creativity-task.json) | `fa06051c-3033-40e1-b2c8-ebdf336e0de5` | Paused at lifecycle revision 2; no terminal result, outcome or stop reason. |

The size cutoff interrupted generation three through ordinary `POST .../pause`.
The recorded lifecycle permits explicit Resume only after quiescence; the host
then shut down. Two generations and eight candidate evaluations were accepted,
with zero expansion interventions. The checkpoint's best/reference score is
0.88 and its current three candidates are provisional, not a final shortlist.
No business task, automatic rerun or judge call was launched.

| Actual call / transcript | Generation | Duration s | Input / cached / output / reasoning tokens | API USD | Partial tokens / cost |
| --- | ---: | ---: | --- | ---: | --- |
| [Direct ideation](evidence/language-agent_call-call-01.json) | not supplied | 64.900643 | 18305 / 9984 / 3340 / 3106 | 0.00587188 | false / false |
| [create_genes](evidence/language-creativity-call-02.json) | 0 | 21.537048 | 18948 / 5888 / 960 / 140 | 0.00388176 | false / false |
| [evaluate_candidates](evidence/language-creativity-call-03.json) | 1 | 37.109687 | 20618 / 9984 / 1875 / 1231 | 0.00457648 | false / false |
| [evaluate_candidates](evidence/language-creativity-call-04.json) | 2 | 31.545715 | 20618 / 9984 / 1558 / 851 | 0.00419608 | false / false |
| [Interrupted evaluation](evidence/language-creativity-call-05.json) | 3 | 33.364927 | unavailable | unavailable | true / true |

Cached input is included in input, and reasoning output in output. All four
search dispatches record material `literature` and null prompt-set fallback;
their actual call IDs and batch IDs are retained in the task lifecycle. The
baseline has no routed semantic job, generation, batch or prompt fallback record.
Its completed task envelope is its accounting authority. The interrupted call
has an empty reply and remains a charged physical attempt with unknown usage,
not an accepted evaluation or a zero-cost call.

The baseline used 19.6% of its target. Search accounting totals 123.557377 seconds,
64,577 known tokens and USD 0.01265432 known API-equivalent (42.2% of target),
with both partial flags true. Known charges already differ by 53.6% of the larger
total, exceeding the predeclared 50% tolerance before the missing charge. This
is unfinished, unmatched evidence; completing the search would not erase the
recorded cost gap. Both configured billing modes are subscription: the baseline
records real USD 0; the search's known real USD 0 remains partial.

Human observations against the language criteria: the baseline offers holding
the father's wrist, keeping a shell and marking a table, with different sensory
traces. Its openings contain 23, 24 and 23 whitespace-delimited words; its own
first label incorrectly says 24. All give concrete action without a question or
causal explanation. Only the first explicitly keeps the shared net-repair scene.
The provisional search candidates instead use a hidden thread, a held needle
and a tightened knot (24, 23 and 20 words). Two reuse cold saltwater; the
third's shared-memory fear needs the model's stated assumption to coexist with
the father's forgetting. These are specific strengths and limitations to inspect,
not a superiority judgment from either the scores or this interrupted sample.

Submitted orders and sessions are retained beside each `*-task.json` response.
The response files preserve HTTP response bytes; [task-store.json](evidence/task-store.json)
and [the checkpoint](evidence/language-creativity-checkpoint.json) preserve the
existing stores' bytes. Call transcripts capture the exact prompt and reply
strings at the real subprocess runner boundary; they add no accounting ledger.
The service home remains at
`/var/folders/_d/j9g16_hn2psglg_vgfl_8z680000gn/T/creativity-slice10-live-xlphlz8k`;
it is stopped, not a running background service. Its session and checkpoint
records preserve the explicit-continuation boundary. Unknown interrupted usage
must remain partial; these artifacts do not close M1 or justify defaults.

Cut verification: retained JSON, common-input equality at both worker boundaries,
admitted orders, session/staffing choices, original store copies, accounting sums
and paused/quiescent state were checked. T1 passed again (four domain/material
subtests, 2.778 seconds); `git diff --check` passed. The complete suite remains
reserved for the scheduled checkpoint. The existing standard-library HTTP and
[unittest](https://docs.python.org/3/library/unittest.html) fixtures were reused.

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

After the default-admission edit, T1 and T3 passed again: seven tests in 3.249
seconds. All four T2 checks pass, including the executable Node form check
(1.351 seconds on its final run). Omission, empty/partial configuration,
explicit complete values, rigor inheritance and invalid combinations are covered.
The form submits untouched defaults through HTTP, then explicit values through
the same schema-generated path; its fixture closes admitted tasks without model
work so another submission can use the same workspace.

```sh
python3 -m unittest \
  orchestrator.tests.test_tasks.TaskContractsTest.test_creativity_configuration_contract \
  orchestrator.tests.test_tasks.TaskContractsTest.test_creativity_public_catalogue_and_configuration \
  orchestrator.tests.test_task_api.TaskApiTest.test_creativity_public_order_and_controls \
  orchestrator.tests.test_task_panel.TaskPanelTests.test_creativity_schema_form_submits_public_order
```

Initial T1: one test with four domain/material subtests passed in 2.833 seconds.

```sh
python3 -m unittest orchestrator.tests.test_creativity_task.CreativityTaskTest.test_creativity_cross_domain_contracts
```

Initial T3: all six existing tests passed in 0.517 seconds; their matrices were reused.

```sh
python3 -m unittest \
  orchestrator.tests.test_prompt_router.PromptRouterTest.test_creativity_jobs_and_materials \
  orchestrator.tests.test_tasks.TaskContractsTest.test_creativity_job_staffing_contract \
  orchestrator.tests.test_creativity_evaluation.CreativityEvaluationTest.test_wave_bounds_and_candidate_allowance \
  orchestrator.tests.test_creativity_evaluation.CreativityEvaluationTest.test_each_attempt_reads_live_authorities \
  orchestrator.tests.test_creativity_evaluation.CreativityEvaluationTest.test_rebaseline_without_progress_credit \
  orchestrator.tests.test_creativity_task.CreativityTaskTest.test_creativity_composes_search_and_results
```

`git diff --check` passes. The complete suite remains for the driver's scheduled
checkpoint. Controlled checks establish mechanical behavior only: neither scripted
scores nor this small real-model sample establish creative superiority or
real-world feasibility.
