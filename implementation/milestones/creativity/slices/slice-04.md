# Slice 04 — Selection, diversity, crossover, and mutation

## Register 1 — Intent

This slice builds the part of the creativity task that explores combinations
for an operator seeking a useful way forward. It keeps strong acceptable
possibilities, leaves room for different combinations, combines parts from
parents, and varies choices while the search is making progress.

It owns population construction and selection over the representation already
built. It does not judge whether a proposal works: it uses the evaluator's
accepted judgment. Changing candidates must preserve the operator's problem and
the candidates being kept. Repeated combinations must not consume more places.

### Dependencies and non-goals

The preceding slices supply admitted settings, accepted search material and
evaluation replies, and the representation of a combination. This slice extends
that representation module. The later caller supplies comparable evaluations
and the combinations already explored.

Model calls, evaluator changes, progress tracking, expansion, task stop reasons,
shortlist composition, checkpoints, task controls, accounting and presentation
remain outside this slice. It adds no framework or product integration.

### Risks and acceptance

A small repertoire may not supply enough different combinations; a poor one
may supply no acceptable parents. Neither case justifies filling places with
duplicates or invalid work. Diversity can also preserve a lower-scoring option
without making it meaningfully different to a human. Random variation offers
opportunities, not a promise that every generation improves.

Acceptance rests on small, repeatable examples of the population's behavior,
including these shortages. There is no model-quality benchmark or live model
spend in this slice.

## Register 2 — Pinned facts

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Delivery boundary | Extend `orchestrator/creativity_search.py` and `orchestrator/tests/test_creativity_search.py` for the Slice 4 population motor. Reuse `make_genome`, `genome_key` and `genome_components`; Python 3.9+ standard library only. | `implementation/milestones/creativity/skeleton.md:125,142,149`; `orchestrator/creativity_search.py:9-41`; `orchestrator/README.md:46` | touch those two implementation files; do-not-change shared schemas, prompts, routing, staffing, catalogue, routes/events/errors, runner, lifecycle, accounting, panel, skeleton or additional roots |
| F2 — Input and comparison seam | Consume already admitted configuration, accepted dimensions, and accepted evaluations associated with their genomes. Selection uses `constraint_valid` and `score`; the existing reply validator remains the admission authority. The caller supplies one comparable evaluator regime and already explored identities from `genome_key`; this slice does not establish or revalidate that regime. | `orchestrator/tasks.py:911-960`; `orchestrator/prompt_contracts.py:547-602,891-914`; `orchestrator/creativity_search.py:21-23`; `implementation/milestones/creativity/skeleton.md:50-54,127-129` | reuse trusted input seams; do-not-add a reply parser, internal-input validator, regime tracker, evaluation cache or durable explored-state store |
| F3 — Bounded, distinct populations | Initial and fresh-candidate construction yields complete genomes, unique by `genome_key`, within the requested count and `population_size`. A request for fresh combinations excludes supplied explored identities. It fills the request when enough unseen combinations exist; otherwise it returns the available smaller set and terminates. A repeated random choice is not proof of exhaustion. Retained survivors may recur across generations; explicit re-evaluation of the same genome is not forbidden. | `implementation/milestones/creativity/skeleton.md:80-88,125,142,144-145`; `orchestrator/creativity_search.py:9-23`; identity consumer `orchestrator/tasks.py:1061-1065` | own population output and truthful local shortage; do-not-pad with duplicates, invent variants, introduce a hidden population ceiling, or choose a task stop reason |
| F4 — Validity and elite selection | Parent/survivor selections contain only evaluated `constraint_valid=true` genomes and no repeated genome, including overlap between retained and newly evaluated candidates. No score offsets invalidity. Preserve the highest-scoring `elite_count` distinct valid candidates when available; fewer eligible candidates yield fewer survivors, and no valid candidate yields an empty selection. Returned populations never exceed `population_size`. New offspring have no inherited evaluation or validity. | `implementation/milestones/creativity/skeleton.md:33-37,125,142,144`; accepted high-scoring invalid reply `orchestrator/tests/test_prompt_contracts.py:108-149`; representation-only result boundary `orchestrator/tasks.py:975-982` | own filtering, score-based preservation and unique membership; do-not-fabricate parents, evaluate children in code, or add an archive/result store |
| F5 — Reserved structural diversity | Reserve `diversity_count` additional survivor places beyond elites when enough distinct valid candidates exist. Diversity depends on differing dimension/variant choices, not labels, prose or score alone. The distinguishing acceptance case retains a lower-scoring candidate differing from the elite in more dimensions over a nearer higher-scoring alternative. Equal text under distinct variant IDs remains structurally distinct; insertion order does not create diversity. Exact ties need no prescribed winner. | `implementation/milestones/creativity/skeleton.md:35-37,99-102,125,142,144`; `orchestrator/creativity_search.py:21-23`; `orchestrator/tests/test_creativity_search.py:66-80` | own an observable diversity preference and separate quota; do-not-add semantic deduplication, embeddings, a domain metric or an optimal-diversity claim |
| F6 — Crossover, ordinary mutation and preservation | Crossover combines same-dimension choices from selected valid parents. Ordinary mutation uses `mutation_rate` and can select a different existing variant, including one absent from the parents; it remains active for offspring during productive generations. With one mutable dimension, rate `1` changes its choice; a singleton dimension stays unchanged. Reserving all survivor places does not disable bounded offspring production. Offspring and retained candidates remain complete, independent genomes; source material, fixed problem fields, parents and retained elites remain unchanged by reproduction. | `implementation/milestones/creativity/skeleton.md:33-45,58-61,125,142,144`; intent clarification `implementation/milestones/creativity/goal.md:65-68,86-89`; admitted quota equality `orchestrator/tasks.py:937-943`; independent representation `orchestrator/creativity_search.py:1-18`; preservation fixture `orchestrator/tests/test_creativity_search.py:82-103` | own categorical offspring and configured mutation opportunity; do-not-change dimensions/variants, mutate the problem, gate ordinary mutation on stagnation, inherit scores, or prescribe crossover layout, random draw order or a public seed setting |
| F7 — Guarantee posture | **Strict:** F3–F6 structural outputs, count bounds, validity exclusion, elite/diversity places and preservation. **Best-effort:** useful proposals, semantic validity, meaningful difference and improvement; applying a mutation probability is not a guaranteed mutation count at fractional rates. **Optimistic / eventual:** no new delivery mechanism here; live authority resolution, checkpoints and panel freshness belong to their existing or assigned owners. Provider-originated IDs/text remain data. Operator, product code, admitted structures and the standard library are trusted. | `implementation/milestones/creativity/skeleton.md:78-116,160`; `orchestrator/creativity_search.py:1-5`; `orchestrator/prompt_contracts.py:891-896` | test this producer's behavior; do-not-add dependency fault injection, hostile-driver defenses, sandboxing, retry/recovery or semantic-quality guarantees |

### Acceptance criteria and tests

T1–T5 below are new obligations in `CreativitySearchTest`, not passing evidence
claimed by this draft. Use local accepted-material/evaluation fixtures and
controlled standard-library randomness; assert outputs, not random draw order,
statistical quality or a particular seed's sequence. Test cases refine F3–F6.

1. **T1 — `test_population_bounds_and_explored_identity`:** request populations
   below and above a tiny repertoire's capacity; verify complete unique outputs,
   requested bounds, exclusion of explored choices and finite empty output when
   all choices are explored. Leave exactly one unseen combination and obtain it.
   Include a singleton repertoire and repeated variant IDs across dimensions.
2. **T2 — `test_valid_elites_and_unique_survivors`:** include a higher-scoring
   invalid candidate, valid candidates with distinct scores, and overlapping
   retained/evaluated entries. Verify the valid top elites, unique selections and
   count bound. Cover fewer valid candidates than reserved places and all-invalid
   input. These are legitimate evaluator outcomes, not malformed internal data.
3. **T3 — `test_reserved_structural_diversity`:** with one elite and one diversity
   place, offer that elite, a near high scorer and a farther lower scorer. Keep
   the elite and farther candidate. In otherwise equivalent fixtures, reorder
   mappings and change labels/text; structural preference remains the same.
   Include enough candidates to exercise larger elite/diversity quotas.
4. **T4 — `test_crossover_and_mutation_preserve_candidates`:** observe a child
   combining choices from two parents; mutation can reach a known alternative
   absent from both. With one mutable dimension, exercise rate `1` and both
   change/no-change outcomes at a fractional rate. Keep singleton dimensions,
   parents, retained elites, other offspring and all material unchanged. Produced
   choices still project through the existing component helper.
5. **T5 — `test_productive_generation_variation`:** use the motor's population,
   selection and reproduction operations across successive improving evaluation
   fixtures. Ordinary mutation remains available; offspring carry no inherited
   score/validity and join selection after fixture evaluation. Retained strong
   valid candidates survive reproduction.
   Include the admitted `elite_count + diversity_count == population_size` case:
   reserving all survivor places does not disable bounded offspring production.

Acceptance requires T1–T5, existing representation/admission regressions, and
scope review against F1. After implementation run:

```sh
python3 -m unittest orchestrator.tests.test_creativity_search orchestrator.tests.test_prompt_contracts.PromptContractsTest.test_create_genes_contextual_contract orchestrator.tests.test_prompt_contracts.PromptContractsTest.test_evaluate_candidates_contextual_contract orchestrator.tests.test_tasks.TaskContractsTest.test_creativity_configuration_contract orchestrator.tests.test_tasks.TaskContractsTest.test_creativity_native_result_contract
```

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator's exploration can lose promising candidates, repeat the same choices or promote a high-scoring constraint violation without this motor. Exposure is every future population/selection; the data transformation is reversible, but wasted later evaluation spend is not. The reviewed Slice 4 assignment independently requires the motor; current code supplies representation only, and the existing evaluator fixture explicitly permits a high-scoring invalid result. | `implementation/milestones/creativity/skeleton.md:24-37,125`; `orchestrator/creativity_search.py:1-41`; `orchestrator/tests/test_prompt_contracts.py:108-149` |
| machinery | Extend the existing pure module with population construction, valid/elite/diverse selection and categorical reproduction. These supply F3–F6 to the assigned search caller. Reuse representation APIs, accepted reply/configuration contracts and standard-library collection/random facilities; no service, persistent schema, new dependency or general GA framework is introduced. | `orchestrator/creativity_search.py:9-41`; `orchestrator/tasks.py:911-960`; `orchestrator/prompt_contracts.py:579-602`; `implementation/milestones/creativity/skeleton.md:125,142,149` |
| consumers_touched | The current direct consumer of the search module is `CreativitySearchTest`; its component compatibility test feeds the existing native-result validator. Runtime host dispatch has no creativity branch yet. This slice creates the population seam for the assigned evaluation/progress/driver work, not a present product client. No existing task host, terminal validator or additional-root consumer is changed. | `orchestrator/tests/test_creativity_search.py:7-8,105-142`; `orchestrator/task_api.py:1723-1759`; `orchestrator/tasks.py:911-915`; `implementation/milestones/creativity/skeleton.md:127-130` |
| cheaper_alternative | Workspace and all four granted-root searches, including dependency sources/manifests, found no population motor to adopt. The reusable piece is the existing representation. [DEAP operators](https://deap.readthedocs.io/en/master/tutorials/basic/part2.html) and [PyGAD controls](https://pygad.readthedocs.io/en/stable/pygad.html) cover related evolution operations, but importing either violates the reviewed standard-library boundary. Extending this module is sufficient; documentation/configuration alone cannot select or reproduce populations, and score-only selection omits required diversity and validity exclusion. | `orchestrator/creativity_search.py:1-41`; `orchestrator/README.md:46`; `implementation/milestones/creativity/skeleton.md:125,142,149`; checked dependency boundaries `/Users/siddhartha/Development/source/life/mix.exs:14-21`, `/Users/siddhartha/Development/source/life_prod/agent_99/mix.exs:21-28`, `/Users/siddhartha/Development/source/life_prod/life_product_components/elixir/mix.exs:4-15`, `/Users/siddhartha/Development/source/life_prod/tutor/web/mix.exs:41-79` |
| cost | Build and maintenance cover one existing module and five focused behavioral tests. Review covers population bounds, selection tradeoffs and independent offspring. There is no migration, model dispatch or background operational cost here; local work grows with supplied candidates/dimensions and finite repertoire search. No latency guarantee is added. Omission transfers the same implementation work and avoidable evaluation waste to the driver; the addition remains easy to remove before public integration. | `implementation/milestones/creativity/skeleton.md:125,127-130,144,149`; `orchestrator/README.md:44-46`; `orchestrator/tasks.py:911-915` |
| threat_model | A provider or source author can influence returned material and evaluation text. This slice introduces no raw-input admission: model replies first pass existing structural validation. Their text/IDs are carried as categorical data, with no reference reading or expression execution here. Invalidity is a legitimate evaluator judgment that selection must honor, not an attack on trusted machinery. Operator settings, caller associations, comparable-regime preparation and Python are trusted. No new malformed-driver or dependency defenses are required. | `orchestrator/prompt_contracts.py:547-602,891-896`; `orchestrator/creativity_search.py:1-23`; `implementation/milestones/creativity/skeleton.md:99-110,160` |
| pinned_facts | F1 fixes scope; F2 fixes dependency and caller ownership; F3 fixes bounded unique construction; F4 fixes valid elites and unscored offspring; F5 fixes reserved structural diversity; F6 fixes categorical variation and preservation; F7 limits guarantees. No new public endpoint, error vocabulary, serialization format or internal algorithm is pinned. | `implementation/milestones/creativity/skeleton.md:125,142,144-145,149`; `orchestrator/creativity_search.py:9-41`; `orchestrator/prompt_contracts.py:579-602` |
| verification | T1–T5 observe outputs and ownership across ordinary small populations, shortages and improving generations. Existing tests pin admission and representation; their negative reply cases are not duplicated around the motor. The command above is implementation acceptance, not evidence that the new motor already exists. Scope review checks the two-file boundary and absence of downstream machinery. | `orchestrator/tests/test_creativity_search.py:56-142`; `orchestrator/tests/test_prompt_contracts.py:108-152,189-263`; `orchestrator/tests/test_tasks.py:105-158`; `implementation/milestones/creativity/skeleton.md:125` |
| enforceability | F2 already has structural admission and trusted-context APIs. F3 uses existing complete-genome construction and pair identity; Python's finite [Cartesian-product iterator](https://docs.python.org/3.9/library/itertools.html#itertools.product) can express complete shortage detection without materializing every combination. F4–F5 use admitted boolean/score fields, unique pair membership and dimension-choice comparisons for bounded selection. F6 uses independent mappings plus standard-library [random choices and probabilities](https://docs.python.org/3.9/library/random.html); T4–T5 verify this producer's use of them. These are available enforcement primitives, not claims that selection/reproduction is implemented. F1 is scope-reviewed; F7 makes no semantic, durable-delivery or fixed-latency promise. Regime comparability is explicitly caller-owned in F2. No asserted guarantee lacks an expressible mechanism. | `orchestrator/tasks.py:911-960`; `orchestrator/prompt_contracts.py:579-602,891-914`; `orchestrator/creativity_search.py:9-23`; identity enforcement precedent `orchestrator/tasks.py:1061-1065`; independent-value checks `orchestrator/tests/test_creativity_search.py:82-103`; `implementation/milestones/creativity/skeleton.md:50-54,99-116,125` |
