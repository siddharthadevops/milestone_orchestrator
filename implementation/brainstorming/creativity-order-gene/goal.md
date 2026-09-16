# Goal — Creativity: Evolve Component Order

Status: **operator-directed draft, non-canonical implementation input**.
This goal refines the existing Creativity task. It does not launch a session,
authorize implementation, or allocate milestones, slices, or delivery stages.

## Outcome

Creativity can evolve not only which variant it selects for each semantic
dimension, but also the order in which the selected components compose a
candidate.

The existing gene-creation call remains responsible for understanding the
operator's problem and returning a problem-dependent number of dimensions and
their possible variants unless the operator supplies that contracted JSON
directly. Code adds one synthetic order gene when component order is meaningful
for that material. The order gene is ordinary genetic material: it is
initialized, inherited, mutated, compared, selected, persisted, and exhausted
under the same evolutionary loop as the semantic genes.

The only special treatment occurs when a candidate is composed for evaluation.
The driver consumes the order gene, deterministically converts its integer
value into a permutation, arranges the selected semantic components in that
order, and sends only those ordered components to the evaluator.

This removes an accidental architectural commitment from gene creation. A
component such as a character's electrocution can be evaluated at the start,
middle, or end of an arc instead of remaining attached to the position in which
the inventor happened to return its dimension.

## Search material and ownership

The contracted `create_genes` call continues to return the objective, context,
facts, constraints, assumptions, unknowns, dimensions, variants, composition
guidance, and evaluation criteria. The model still decides how many semantic
dimensions the problem needs. No fixed `gene_count` is introduced merely to
support ordering.

Search material additionally states whether order changes the meaning of a
candidate and, when it does, what that order means. The compact representation
may express this as a nullable `order_semantics` value:

```json
{
  "order_semantics": "order of presentation to the reader"
}
```

`null` means that permutations are not part of the search. This preserves the
existing categorical behavior for objectives in which rearranging dimensions
would create duplicate candidates rather than different proposals.

When `order_semantics` is present:

- dimensions intended for ordering describe movable semantic functions or
  components, not positions named `beginning`, `middle`, or `ending`;
- variants remain alternatives within their own dimension;
- facts and hard constraints remain outside the mutable genome; and
- composition guidance explains how the ordered components should be
  interpreted for this objective.

The model does not enumerate orders and does not create the synthetic order
gene. Both are code-owned concerns. Material-specific prompt layers may help
the model identify useful components, but they do not introduce a different
order representation.

## Operator-supplied initial search material

A Creativity order may optionally carry the JSON that the initial
`create_genes` call would otherwise return. The optional order field,
provisionally named `initial_genes`, accepts exactly the current contracted
reply envelope:

```json
{
  "search_material": {
    "objective": "...",
    "context_summary": "...",
    "facts": [],
    "constraints": [],
    "assumptions": [],
    "unknowns": [],
    "dimensions": [
      {
        "id": "example_dimension",
        "meaning": "An aspect that may vary",
        "variants": [
          {"id": "example_variant", "text": "One possible value"}
        ]
      }
    ],
    "composition_guidance": "Combine the selected values faithfully.",
    "criteria": [
      {"id": "usefulness", "text": "How well the proposal serves the objective"}
    ],
    "order_semantics": null
  }
}
```

Supplied data must satisfy the full current `create_genes` result contract,
including non-empty dimensions, variants, criteria, closed objects, unique IDs,
and the ordering fields defined by this goal. The injected structure and a
model-produced reply have one machine contract and one validator. Implementation
should extract or reuse the existing search-material validation rather than
maintain a second hand-written schema for task admission.

When `initial_genes` is present and valid:

- task admission detaches and preserves the JSON as operator-supplied data;
- the first checkpoint starts with that `search_material` already admitted;
- the task starts evolution at generation one;
- no physical `create_genes` call, correction attempt, usage, cost, or call
  receipt exists; and
- evaluation, expansion, ordering, controls, accounting, pause/resume, and
  terminal behavior are otherwise identical to generated material.

When `initial_genes` is absent, the existing `create_genes` call remains the
source of initial search material. These are alternative entry paths, not two
materials to merge.

Malformed JSON or a structurally invalid supplied result is rejected as an
invalid task order before execution. The task does not repair operator-supplied
material, fall back to an agent call, partially accept it, or silently add
defaults that the model-produced reply could not use. The same reserved-ID
rules apply to both sources.

The original operator request remains required and durable in the task order.
Its wording need not equal `search_material.objective`: the latter may be the
same concise formulation that `create_genes` is already allowed to return.
Admission performs structural validation, not a new LLM judgment of semantic
equivalence between the request and the supplied objective. By injecting the
JSON, the operator takes authority for its semantic fitness to the request.

The public task API accepts this JSON object directly. The panel exposes one
optional Creativity-only JSON input that submits the same object; it does not
introduce a file-path loader, upload store, alternate envelope, or private
creation endpoint. Stored orders and task projections preserve whether initial
material was supplied so the absence of a creation call is inspectable without
inventing one.

## Synthetic integer order gene

For `N` ordered semantic dimensions, code injects a reserved first gene,
provisionally named `__order__`. Its value is an integer in the closed range:

```text
0 .. N! - 1
```

Each integer identifies exactly one permutation of the canonical dimension
IDs. The canonical base order is the admitted order of dimensions in the
search material. Ranking and unranking are deterministic and stable for the
life of the task.

`__order__` is reserved by the engine and cannot be used as a semantic
dimension ID in generated or operator-supplied material.

For example, with dimensions `A`, `B`, and `C`:

```text
0 -> [A, B, C]
1 -> [A, C, B]
2 -> [B, A, C]
3 -> [B, C, A]
4 -> [C, A, B]
5 -> [C, B, A]
```

A candidate may therefore be stored conceptually as:

```json
{
  "__order__": 4,
  "A": "A2",
  "B": "B1",
  "C": "C3"
}
```

and composed for evaluation as:

```text
[C3, A2, B1]
```

The implementation must not materialize or persist a matrix containing all
`N!` permutations. It calculates the permutation identified by the current
integer when needed. The integer is categorical: adjacent numbers do not imply
similar orders and no arithmetic distance, averaging, or numeric crossover is
assigned semantic meaning.

With one ordered dimension, the only value is `0` and the gene is immutable.
With no ordered dimensions or absent order semantics, no mutable order gene is
needed.

## Ordinary evolution

The order gene uses the existing categorical evolutionary behavior:

- population creation draws a valid order integer at random;
- crossover inherits the complete integer from one selected parent;
- ordinary mutation, at the configured mutation rate, selects a different
  valid integer uniformly when another value exists;
- selection judges the resulting candidate, not the integer in isolation; and
- diversity treats a different order value as one genetic difference.

No order-specific `swap`, `move`, inversion, random-key encoding, or permutation
crossover is required. Such operators may be considered later only if measured
behavior shows that ordinary categorical mutation is insufficient. They are
not prerequisites for this change.

The finite repertoire includes the order gene. For dimensions with variant
counts `V1 .. VN`, the maximum ordered repertoire is:

```text
N! * V1 * ... * VN
```

Enumeration remains lazy and bounded by the task's existing population,
generation, and evaluation limits.

## Candidate identity and persistence

The order integer is part of genome identity. Candidates with the same selected
semantic variants but different order values are distinct because they can
produce different proposals and scores.

For example, these are different genomes:

```text
[order=0, A2, B1, C3]
[order=4, A2, B1, C3]
```

Explored identities, duplicate removal, survivor archives, pending generations,
checkpoints, expansion handoffs, exhaustion checks, and resumed execution must
all retain that distinction.

Existing stored work without an order gene continues to read in canonical
dimension order. It is not silently expanded into newly unevaluated
permutations. Compatibility must not rewrite completed evidence or reinterpret
an old score as an assessment of a newly ordered candidate.

An admitted `initial_genes` value is retained in the immutable task order. Once
the checkpoint contains search material, that checkpoint remains the execution
authority on resume; re-entry neither calls `create_genes` nor recopies a
different value over evolved material.

Semantic expansion continues to add variants only within existing dimensions.
Because the dimension set and its canonical order remain fixed during a task,
adding a variant does not change the order gene's range. Adding, removing, or
replacing dimensions during stagnation is separate schema-evolution work and
is outside this goal.

## Evaluation contract

Before an evaluation call, the driver:

1. reads and removes the synthetic order gene from the semantic payload;
2. converts the integer to its dimension-ID permutation;
3. resolves each dimension's selected variant;
4. emits the component records in the resulting order; and
5. supplies the admitted order semantics with the immutable search material.

The evaluator receives no `__order__` component and does not need to know the
integer. It sees the semantic effect: an intentionally ordered component list.
Its prompt requires it to interpret that order faithfully and forbids silently
reordering the components, replacing selected variants, or repairing a weak
candidate into a different one.

The evaluator may explain that an order is incoherent or violates a supplied
constraint. Invalid orders are honest candidates and participate in the same
validity rules as every other combination; the evaluator must not rescue them
by choosing a better order.

## Results and operator visibility

Terminal proposals preserve the evaluated component order. Result validation
must therefore distinguish ordered component sequences rather than reducing
them to unordered dimension/variant sets.

The panel presents the components in their evaluated order and may state the
human-readable order semantics. The synthetic integer is implementation data;
showing `__order__ = 4` to the operator is unnecessary unless it aids existing
diagnostic inspection. No new ordering editor or permutation browser is
required.

Existing progress, controls, usage, cost, and stop reasons remain unchanged.
The change adds no new calls, retries, queues, caches, schedulers, or recovery
paths.

## Completion evidence

Completion demonstrates at least:

- deterministic one-to-one ranking and unranking for representative dimension
  counts, with valid bounds and no stored permutation matrix;
- random initialization, parent inheritance, and ordinary different-value
  mutation of the integer order gene;
- candidate identity, diversity, exploration accounting, checkpointing, and
  resumption retaining order;
- two candidates with identical semantic selections and different order values
  reaching evaluation as different ordered component lists;
- the evaluator receiving no synthetic component and being instructed to
  preserve the supplied order;
- result validation and the panel retaining the evaluated order;
- one ordered literary or planning example in which moving the same selected
  event changes the proposal materially;
- one unordered categorical example retaining the current behavior without
  factorial duplicate candidates;
- a valid operator-supplied `create_genes` envelope starting directly at
  evolution with zero creation calls and otherwise identical behavior;
- invalid supplied JSON being refused before execution without correction or
  fallback, while the same validator admits an equivalent model reply;
- the API, panel, stored order, projections, and resume path preserving the
  supplied-material entry path without duplicating the search-material schema;
- existing stored Creativity work continuing to read without rewriting its
  evidence.

## Boundaries

This goal does not add variable-length chromosomes, optional-gene insertion or
deletion, dynamic dimension creation, schema evolution after stagnation,
specialized permutation operators, precomputed permutation tables, a second
evaluator, semantic-equivalence judging, or a domain-specific Creativity
engine.

It also does not add a second initial-material schema, merge supplied and
generated genes, repair operator JSON, load initial material from a filesystem
path, or call `create_genes` as a fallback after supplied input is refused.

It does not claim that changing order can discover a semantic component the
inventor never supplied, nor can ordering override a hard constraint that
excludes a desired solution. It makes order evolvable inside the admitted
search space and nothing more.

## Existing design references

- [Creativity goal](../creativity/goal.md).
- [Creativity search representation](../../../orchestrator/creativity_search.py).
- [Creativity evaluation composition](../../../orchestrator/creativity_evaluation.py).
- [Standalone task execution](../../../orchestrator/task_api.py).
- [Task contracts and catalogue](../../../orchestrator/tasks.py).
- [Registered prompt reply contracts](../../../orchestrator/prompt_contracts.py).
- [Prompt Router Creativity jobs](../prompt-router/adapted-kinds/milestone/).
