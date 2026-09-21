# Creativity v2: literal and abstract vocabulary comparison

## Acceptance boundary

CV2-001 is valid against the current skeleton's slice 6 and its pinned
"Prompt authority and comparison" and "Assurance ceiling" rows. Inspection
found only slice 1–5 implementation evidence here. The earlier
`../creativity/evidence.md` measures direct ideation against legacy search on
two problems; it cannot supply this sparse, two-vocabulary, three-problem
comparison. No settled rejection exists in `adjudications.md`.

The affected party is the operator: without the retained comparison they
cannot inspect seed fidelity, vocabulary effects, usefulness and actual work
for the promised experiment. An unfinished comparison is ordinary during
implementation, but does not satisfy milestone completion. Weak proposals,
unequal measured costs and no useful surprise are permitted outcomes; missing
observations are the omission. This is a slice 6 evidence defect, not a claim
that the existing search changes behavior. Every milestone completion review
encounters it until the comparison and its assessment are retained.

All six measured tasks, mechanical checks and accounting reconciliation are
complete. Acceptance remains open for the required operator assessment. A
model's score or an assistant's inspection is not a human judgment.

## Method and retained authority

The [declaration](evidence/declaration.json) precedes the first measured call.
It records revision, sequence, RNG seed, controls, accounting basis and limits.
The [capture script](evidence/capture_comparison.py) uses the existing local
HTTP service, `DirectTaskHost`, prompt router, validators, checkpoint stores,
subprocess runner, staffing and physical-call accounting. It creates no search
engine, scheduler, retry policy, benchmark service or production control.
All four additional repositories remain read-only.

The [literary](examples/literature-problem.json),
[strategic](examples/strategy-problem.json) and
[ordinary planning](examples/planning-problem.json) inputs reuse the earlier
cross-domain fixtures. Requests now ask for one proposal per candidate;
difference criteria judge that proposal independently of the batch. Facts,
constraints, assumptions, unknowns, criteria and order semantics are identical
between the literal and abstract members of each pair.

Six `examples/<problem>-<formulation>.json` files enter through the existing
`initial_genes` contract. Each contains five independent foci and twelve shared
values. Those equal fixture sizes control this small comparison; they impose
no product count. Literature's literal material starts with the daughter,
father, fishing net and missing minute, plus an explicitly proposed shell.
The abstract member uses memory, routine, shared labour, absence and a proposed
memory token. Strategy contrasts concrete actors/resources with capacity,
relationships and exchange; planning contrasts ingredients/appliances with
meal functions, availability and preparation capacity. Neither contains
pre-composed solutions or per-focus subsets.

This is an authored supplied-material experiment, not a measurement of how
well a creator model invents either vocabulary. The skeleton permits this
authority. The served evaluator prompt set and its source/seed remain
unchanged. Literature uses the literature material layer, strategy business,
and planning default; each pair uses the same layer. Actual staffing is read
at dispatch from the retained [document](evidence/staffing.json).

Each task has two generations, population four, at most eight evaluations,
batch size four, concurrency one, mutation rate 0.35, two elite survivors,
one diversity survivor and shortlist size three. Ordering is interchangeable.
The isolated process resets the RNG to 20260921 per task. Equal-shaped pairs
therefore start with the same genetic draws; subsequent scored evolution may
diverge. Neither seed size nor model score is forced. Literal runs first in
each pair. One run per cell cannot isolate vocabulary effects from model
variation or order effects and supplies no statistical superiority claim.

Retained `*-call-*.json` files contain the exact prompts and replies at the
real runner boundary and provider usage payloads. `*-task.json` contains the
public terminal projection, `*-lifecycle.json` the authoritative physical-call
receipts, and `*-checkpoint*.json` the search state and original KV bytes.
Orders, sessions and original task-store bytes are retained alongside them.
Creation is skipped by supplied material; no expansion or judge call is part
of the experiment. Existing contract-correction attempts, if any, remain
physical work and must be counted.

`*-draws.json` observes returns from the existing `genome_key` only when
called by `_fill_population`. It records the actual genome, returned effective
identity and whether that identity was already in the supplier's `seen` set.
It changes no return value or search decision. "Repeated seeds avoided" means
those duplicate draws, not a fabricated estimate from terminal uniqueness;
empty draws are counted separately. Low score means strictly below 0.5.
Validity rates are evaluator-reported, not independently proven compliance.

## Results and assessment

All six tasks succeeded on 2026-09-21 against production revision
`1f62e32`: two generations and eight accepted evaluations each, stopping at
`generation_limit`. All twelve physical calls used Codex `gpt-5.6-luna`, low
effort, with no prompt-set fallback. There were no creation, expansion,
correction, failed or interrupted calls. The temporary service is stopped;
all six tasks are terminal. The only workspace additions are these fixtures,
the capture/inspection script and evidence; production behavior is unchanged.

The [machine-readable summary](evidence/summary.json) reconciles every
projection, exact sent seed, accepted reply and accounting receipt.

| Problem / formulation and retained outputs | Active pairs: count distribution | Mean active | Score < 0.5 | Model-valid | Repeated seeds avoided |
| --- | --- | ---: | ---: | ---: | ---: |
| [Literature literal](evidence/literature-literal-task.json) | 2:2, 3:2, 4:3, 5:1 | 3.375 | 2/8 (25%) | 8/8 (100%) | 0 |
| [Literature abstract](evidence/literature-abstract-task.json) | 1:1, 2:3, 3:3, 4:1 | 2.500 | 0/8 (0%) | 8/8 (100%) | 0 |
| [Strategy literal](evidence/strategy-literal-task.json) | 1:1, 2:3, 3:2, 4:2 | 2.625 | 6/8 (75%) | 5/8 (62.5%) | 0 |
| [Strategy abstract](evidence/strategy-abstract-task.json) | 1:1, 2:3, 3:2, 4:2 | 2.625 | 4/8 (50%) | 5/8 (62.5%) | 0 |
| [Planning literal](evidence/planning-literal-task.json) | 2:2, 3:3, 4:3 | 3.125 | 1/8 (12.5%) | 8/8 (100%) | 0 |
| [Planning abstract](evidence/planning-abstract-task.json) | 1:1, 2:3, 3:2, 4:2 | 2.625 | 0/8 (0%) | 8/8 (100%) | 0 |

`2:2` means two seeds had two active pairs. All 48 evaluator-visible seeds
were nonempty and distinct within their task; none contained raw genomes or
omission/order metadata. There were no duplicate or empty supplier draws in
this small sample, so no avoided calls are credited. The focused identity
test covers collisions separately; zero observed collisions is not a live
stress demonstration. Every accepted evaluation, including the zero-scored
and constraint-invalid strategy candidates, remains in the public projection.
The admitted repertoires stayed unchanged. First-generation genetic draws and
immutable problem fields matched exactly within each pair.

| Run | Physical calls | Model work s | Input / cached input / output / reasoning output tokens | API-equivalent USD |
| --- | ---: | ---: | --- | ---: |
| Literature literal | 2 | 56.702289 | 37768 / 19968 / 2692 / 1423 | 0.00718976 |
| Literature abstract | 2 | 88.554365 | 37425 / 19968 / 3224 / 1998 | 0.00775956 |
| Strategy literal | 2 | 75.788153 | 37382 / 19968 / 2444 / 834 | 0.00681496 |
| Strategy abstract | 2 | 77.249281 | 37464 / 19968 / 2496 / 374 | 0.00689376 |
| Planning literal | 2 | 71.069597 | 37398 / 19968 / 2437 / 421 | 0.00680976 |
| Planning abstract | 2 | 68.128261 | 37152 / 19968 / 2079 / 451 | 0.00633096 |

Totals are 437.491945 seconds of physical model work, 239,961 tokens and
USD 0.04179876 API-equivalent at the existing accounting owner's rates.
Cached input is included in input; reasoning output is included in output.
Every usage/cost partial flag is false. The configured subscription accounting
reports real USD 0 for each call; it does not allocate the fixed subscription
charge. No new price calculation or equal-spend claim is introduced.

### Assistant inspection, not operator judgment

These observations come from inspecting the retained seeds and outputs, not
from treating fitness or the evaluator's explanation as a quality verdict.
Candidate prefixes below identify full IDs in the linked task projections.

| Pair | Concrete observations and limitations |
| --- | --- |
| Literature | Literal `649f2fd5` receives shell→tie but writes "Ata la red", dropping the shell; `92e9a145` drops it again. `a112ba29` says the father remembers, and the evaluator itself notes conflict with the supplied asymmetry while still reporting validity. All sixteen sentences meet the 24-word bound by whitespace count. Abstract `116abc3b` offers a more fluent image of a suddenly silent sea, but shared labour→conceal becomes concealment of the missing minute, so its 0.92 score is not evidence of exact seed fidelity. Literal `a88d2d05` is concise and concrete, but exchanging the net supplies little emotional cost by itself. |
| Strategy | Both formulations retain a one-pair withdrawal/cancellation candidate with near-zero score and diagnostic validity true: respecting spending limits does not satisfy the objective. Literal `52a33d0f` supplies a six-hour split and three-booking threshold, but leaves service and price unspecified. Abstract `5fe14eae` suggests a paid assessment but leaves price, appointment cap, time itemization and continue/stop threshold to later decisions; capability→measure becomes measurement of bicycle condition. Its reason also calls it "the strongest complete proposal in the batch", contrary to the authored independent-scoring instruction. This is observed best-effort semantic noncompliance, not a mechanical guarantee of calibration. |
| Planning | Literal `9b532c44` gives a readable weekday allocation, but freezer→cook becomes ordinary cooking followed by freezing. `e9f9d364` similarly turns freezer→roast into roasting vegetables for storage, and `5c116e7d` redirects freezer→chop to chopping vegetables. Abstract `2ce5a655` retains energy→heat, protein→distribute and freshness→reuse more plausibly, but offers a generic early/late-week pattern rather than a concrete menu for each evening. Neither top proposal itemizes the ninety-minute workload. Fluency and model validity therefore overstate how complete or seed-faithful these plans are. |

The sample shows an evaluable vocabulary difference: abstract literature is
more fluent here, while literal planning is more concrete. It also shows
semantic substitutions in both formulations and broadly conventional proposed
pilots/menus. These are assistant observations from this sample, not proof of
creative superiority, operational feasibility or useful human surprise.
Poor materialization is a permitted best-effort outcome; the outputs have
been retained instead of repaired or silently replaced.

### Required human assessment: pending

The operator was asked for a useful-surprise judgment on each problem's two
highest-scoring proposals, with their material limitations shown. Selecting
"neither" is a complete judgment; a positive result is not required. This
small excerpt assessment does not ask the operator to review all 48 outputs.
The exact requests and response state are retained in
[operator-judgments.json](evidence/operator-judgments.json).

No operator response has been received. Useful operator-judged surprises are
therefore **unassessed**, not zero, and CV2-001 cannot yet be reported fixed.
The remaining blocker is human input, not model access, missing live runs,
accounting, or a contradiction in the skeleton. An assistant cannot supply
that judgment under a human label.

## Focused checks

The six supplied-material files pass the existing sparse admission validator.
The following three checks pass (0.325 seconds): source/seed equivalence,
sparse task integration with generated and supplied material in both order
modes, and effective identity/nonempty handoff.

```sh
python3 -m unittest \
  orchestrator.tests.test_prompt_sets.PromptSetStoreTest.test_shipped_corpus_and_seed_are_equivalent \
  orchestrator.tests.test_creativity_task.SparseCreativityTaskTest.test_sparse_task_composes_search \
  orchestrator.tests.test_creativity_search.CreativitySearchTest.test_sparse_effective_identity_and_nonempty_handoff
```

The full suite remains for its scheduled checkpoint. These focused mechanical
checks do not establish faithful materialization or creative usefulness.

Offline retained-evidence reconciliation also passes:

```sh
python3 implementation/milestones/creativity-v2/evidence/capture_comparison.py --summarize
git diff --check
```

It checks the six sparse admissions and immutable repertoires, exact effective
seeds against physical prompts and public projections, accepted replies
against checkpoint batches, both generation limits, skipped creation/expansion,
actual model/effort/fallback provenance, every token/cost/work sum, unique
nonempty identities, and pairwise immutable-input/initial-draw equivalence.
