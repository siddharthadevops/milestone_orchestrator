# Creativity: cross-domain evidence

## Current evidence boundary

Controlled checks T1 and T3 pass. The earlier language pilot below remains
incomplete, partial and unmatched. A replacement comparison now has a completed
language baseline under a new declaration made before dispatch. Its creativity
task and both business tasks remain unrun. M1 and the evidenced catalogue
defaults/admission/form checks (T2) remain incomplete. Controlled numbers remain
fixture limits and simulated accounting, separate from real evidence. No
catalogue defaults are published by this cut.

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
the complete common input appears in the `agent_call` request text itself;
its separate context field alone does not reach that worker.

## Replacement comparison: completed language baseline

The [replacement declaration](evidence/comparison/declaration.json) was written
at 2026-09-12T14:08:24.400825Z against revision
`6fe04a6a8350f5925cdaac23c645a6cce3b6dc0d`, before its first dispatch. It declares
USD 0.015 API-equivalent per task and the same 50% relative-difference tolerance,
requiring complete positive totals for both members of each pair. The proposed
search allowance is two generations and eight evaluations in batches of four;
the direct request asks it to consider eight alternatives and return three.
This reduces the third-generation overhead exposed by the pilot. These are
experimental work targets and explicit trial controls, not defaults or enforced
spend caps. The old pilot's missing charge and failed comparison are preserved.

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
the service is stopped and has no active task. No remaining pair member ran.

Human inspection: the three openings count holes in a net, pocket a thread
after a forgotten embrace, and cut a thread after a forgotten farewell. They
contain 22, 23 and 19 whitespace-delimited words; the third self-check incorrectly
says 20. All fit the length bound, give the daughter an action, avoid explaining
the cause and end without a question. Silence, returning boat noise and a
lighthouse sweep supply different sensory traces. Only the first explicitly
anchors net repair; the latter two add assumed intimate events. The first's
forgotten knot is less clearly an emotional cost. These observations assess the
supplied criteria without treating a model self-check as an independent judge.

This is one complete baseline, not a matched pair or M1 completion. The next
work is the declared language creativity order and both business orders, then
comparison/defaults review and T2. Provisional defaults and T2 edits were
withdrawn at the cutoff because neither pair yet supports publication.

Cut verification: all eight retained JSON files parse; common-input equality,
dispatch/session evidence, original store/worker bytes and one-charge result
handoff agree. Existing `test_agent_call_success_during_pause_is_retained_until_resume`
and `test_public_pause_waits_for_active_call_and_resume_reuses_its_result` passed
(two tests, 2.252 seconds). `git diff --check` passed. The complete suite remains
reserved for the scheduled checkpoint.

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
