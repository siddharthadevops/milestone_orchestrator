# Goal — Creativity: Fixed or Interchangeable Component Order

Status: **operator-directed draft, non-canonical implementation input**.
This goal refines the existing Creativity task. It does not launch a session,
authorize implementation, or allocate milestones, slices, or delivery stages.

## Outcome

Creativity makes component ordering an operator-selected mode. It can preserve
the inventor's proposed order or evolve the order alongside the selected
variant for each semantic dimension.

The existing gene-creation call remains responsible for understanding the
operator's problem and returning a problem-dependent number of dimensions and
their possible variants unless the operator supplies that contracted JSON
directly. The call and its result contract are identical in both order modes.
The inventor returns logical, position-independent units and arranges the
dimension list in the order it recommends for the problem.

With fixed ordering, code preserves that returned order. With interchangeable
ordering, code treats the returned order as the canonical permutation and adds
one synthetic order gene. The order gene is ordinary genetic material: it is
initialized, inherited, mutated, compared, selected, persisted, and exhausted
under the same evolutionary loop as the semantic genes.

The only special treatment occurs when an interchangeable candidate is composed
for evaluation. The driver consumes the order gene, deterministically converts
its integer value into a permutation, arranges the selected semantic components
in that order, and sends only those ordered components to the evaluator.

This lets the operator choose whether the inventor's recommended sequence is
binding or merely one arrangement in the search space, without asking the
inventor to formulate the problem differently.

## Search material and ownership

The contracted `create_genes` call continues to return the objective, context,
facts, constraints, assumptions, unknowns, dimensions, variants, composition
guidance, and evaluation criteria. The model still decides how many semantic
dimensions the problem needs. No fixed `gene_count` is introduced merely to
support ordering.

Search material additionally states what component order means for the problem.
The compact representation includes a non-blank `order_semantics` value:

```json
{
  "order_semantics": "sequence in which the selected components are applied"
}
```

For every newly created search material:

- dimensions describe movable semantic functions or components, not
  predetermined positions or numbered slots;
- variants remain alternatives within their own dimension;
- facts and hard constraints remain outside the mutable genome; and
- composition guidance explains how the ordered components should be
  interpreted for this objective.

## Generic gene-creation prompt

The generic base prompt for `create_genes@creativity` explicitly instructs the
inventor to derive **logical, position-independent composition units**. A unit
may represent an action, event, policy, resource use, commitment, meal,
operation, behavior, or any other component that serves the operator's
objective. It is not a domain-specific narrative beat and does not assume that
the task concerns literature.

Each ordered dimension expresses **what can vary**, never **where its selected
value must occur**. Its meaning and variants remain intelligible when the unit
is moved to another position on the declared order axis. The inventor must not
bake a preferred sequence into IDs, meanings, or variant text through ordinal
labels, predefined phases or slots, encoded predecessor/successor relationships,
or equivalent hidden position constraints.

The base prompt requires the inventor to:

- identify the relevant order semantics;
- derive a problem-dependent number of coherent units independently of their
  eventual positions;
- give each unit genuine alternatives that preserve its semantic function;
- arrange the returned dimension list in the sequence it recommends while
  keeping each unit's own meaning independent of that position;
- place real causal, temporal, resource, compatibility, or policy dependencies
  in constraints or composition guidance instead of fixing every unit's
  position in advance; and
- avoid manufacturing dependencies merely to preserve the order in which it
  happened to invent the units.

Position-independent does not promise that every permutation is valid. A
genuine dependency may make some orders incoherent or forbidden, and the
evaluator may reject them. The inventor recommends a sequence through list
order, but it does not encode that sequence into the units themselves.

This instruction belongs to the generic base prompt and its output contract.
Material-specific layers may contribute vocabulary and judgment for business,
literature, food planning, or any other material, but they must preserve the
same unit semantics and machine representation. No material layer owns or
redefines ordering.

The model does not enumerate orders and does not create the synthetic order
gene. Both are code-owned concerns.

The selected order mode is deliberately absent from the creation prompt and
its values. Given the same operator request, context, references, prompt set,
material, and model behavior, `create_genes` receives the same prompt and
returns the same contract whether the task uses fixed or interchangeable
ordering. The task interprets the returned list only after admission.

## Operator-selected order mode

Creativity configuration adds one required resolved choice, provisionally named
`order_mode`, with exactly these values:

- **`fixed`** — preserve the admitted dimension-list order. Do not create an
  order gene. Candidate repertoire and identity remain the Cartesian product of
  one selected variant per dimension.
- **`interchangeable`** — use the admitted dimension-list order as canonical
  permutation `0`, inject the synthetic integer order gene, and let evolution
  explore other permutations.

The default for every newly admitted order is `interchangeable`; `fixed` must be
selected explicitly. The mode belongs to task configuration, not to
`search_material`, prompt routing, staffing, or a material-specific layer. It
is resolved and frozen at task admission. Changing it after work begins would
change genome identity, repertoire size, and the meaning of existing
evaluations, so it is not a live control.

The public task API and panel expose the same choice. Selecting a mode does not
add a semantic call, alter the `create_genes` prompt, or change the JSON that an
operator may inject as initial search material.

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
    "order_semantics": "sequence in which the selected components are applied"
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
JSON, the operator takes authority for its semantic fitness to the request and,
for supplying the same position-independent units and recommended list order
required from the inventor.

The public task API accepts this JSON object directly. Stored orders and task
projections preserve whether initial material was supplied so the absence of a
creation call is inspectable without inventing one.

## Panel request and JSON input

The standalone task-ordering panel removes the shared **Context** input. This is
a panel simplification for every TaskExecutor, not a change to the public task
API. `request.context` remains part of the API contract and stored task order;
the panel submits the empty string for that field. Direct API clients remain
free to supply any currently valid context value. The backend validator,
transport, persistence, and execution use of API-supplied context do not change.

When the selected TaskExecutor is Creativity, the panel shows one optional,
monospaced **Initial genes JSON** editor. The operator can:

- paste JSON directly into the editor and modify it before submission; or
- press a visible **Load JSON file…** button, choose one local `.json` file,
  and load its UTF-8 text into the same editor.

The file chooser reads the selected file in the browser. It does not send a
filesystem path, upload the file to a separate store, or create a second API.
Loading a file replaces the editor text but does not submit the task. The
operator may continue editing the loaded JSON before submission.

On submission:

- an empty or whitespace-only editor omits `initial_genes`, preserving the
  ordinary `create_genes` call;
- non-empty text must parse as one JSON value before the request is sent;
- a syntax error remains in the dialog as a local validation error and no task
  is created; and
- the parsed value is sent unchanged as the order's `initial_genes` field, with
  the server's shared `create_genes` contract remaining authoritative for its
  structure.

The client does not reproduce the full search-material schema. It checks JSON
syntax only; structural errors use the ordinary server refusal. File selection
and paste/edit therefore converge on one editor, one parsed object, one task
field, and one backend validator.

## Synthetic integer order gene

In `interchangeable` mode, for `N` semantic dimensions, code injects a reserved
first gene, provisionally named `__order__`. Its value is an integer in the
closed range:

```text
0 .. N! - 1
```

Each integer identifies exactly one permutation of the canonical dimension
IDs. Permutation `0` is the recommended dimension-list order admitted from the
inventor or the operator-supplied JSON. Ranking and unranking are deterministic
and stable for the life of the task.

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

With one semantic dimension, the only interchangeable value is `0` and the
gene is immutable. In `fixed` mode, no order gene is created at any dimension
count.

## Ordinary evolution in interchangeable mode

When present, the order gene uses the existing categorical evolutionary
behavior:

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

For dimensions with variant counts `V1 .. VN`, the fixed repertoire is
`V1 * ... * VN`. The interchangeable repertoire includes the order gene and is:

```text
N! * V1 * ... * VN
```

Enumeration remains lazy and bounded by the task's existing population,
generation, and evaluation limits.

## Candidate identity and persistence

In `interchangeable` mode, the order integer is part of genome identity.
Candidates with the same selected semantic variants but different order values
are distinct because they can produce different proposals and scores. In
`fixed` mode, only the semantic selections form genome identity and the
admitted recommended dimension order is common to every candidate.

For example, these are different genomes:

```text
[order=0, A2, B1, C3]
[order=4, A2, B1, C3]
```

Explored identities, duplicate removal, survivor archives, pending generations,
checkpoints, expansion handoffs, exhaustion checks, and resumed execution must
all retain that distinction.

Existing stored work without `order_mode` is a legacy exception: it reads as
`fixed` and continues to use its admitted dimension order. This compatibility
rule does not change the `interchangeable` default for new orders. Historical
work is not silently expanded into newly unevaluated permutations, and old
scores are not reinterpreted as assessments of newly ordered candidates.
Historical search material that predates `order_semantics` remains readable
under that fixed mode; newly generated or operator-supplied material uses the
current contract.

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

Before an evaluation call, the driver resolves the effective component order:

1. in `fixed` mode, use the admitted dimension-list order;
2. in `interchangeable` mode, read and remove the synthetic order gene and
   convert its integer to a dimension-ID permutation;
3. resolve each dimension's selected variant;
4. emit the component records in the effective order; and
5. supply the admitted order semantics with the immutable search material.

The evaluator receives neither `order_mode` nor an `__order__` component and
does not need to know the integer. It sees the semantic effect: an intentionally
ordered component list. Its prompt is identical in both modes, requires it to
interpret the supplied order faithfully, and forbids silently reordering the
components, replacing selected variants, or repairing a weak candidate into a
different one.

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
- new `order_mode` values resolving to `interchangeable` by default, `fixed`
  requiring explicit selection, and the resolved mode remaining frozen after
  admission and exposed consistently by the API and panel;
- fixed and interchangeable runs using the same creation prompt and result
  contract for the same admitted inputs;
- fixed mode preserving the admitted recommended dimension order without an
  order gene or factorial repertoire growth;
- for the same admitted material and semantic selections, fixed mode and
  interchangeable mode with `__order__ = 0` emitting exactly the same component
  sequence as the admitted dimension list;
- the served generic `create_genes` prompt explicitly requiring logical,
  position-independent units and every material layer preserving that rule;
- materially different ordered examples—a strategic decision, a creative
  composition, and a practical schedule such as a weekly meal plan—using the
  same generic prompt contract, genome, operators, and evaluator contract;
- those examples deriving position-independent logical units rather than
  domain-specific slot schemas or position encoded into the units;
- a valid operator-supplied `create_genes` envelope starting directly at
  evolution with zero creation calls in either order mode and otherwise
  identical behavior;
- invalid supplied JSON being refused before execution without correction or
  fallback, while the same validator admits an equivalent model reply;
- the standalone task panel exposing no Context input for any TaskExecutor and
  submitting an empty context, while direct API orders still accept, preserve,
  and use non-empty context without contract changes;
- Creativity accepting the same `initial_genes` object through pasted/edited
  JSON or a locally selected `.json` file, with no server-side file upload;
- an empty JSON editor omitting `initial_genes`, malformed JSON preventing
  submission locally, and structurally invalid JSON receiving the ordinary
  server refusal;
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
generated genes, repair operator JSON, add a server-side filesystem loader or
upload store, or call `create_genes` as a fallback after supplied input is
refused. The panel's local file chooser only fills the same JSON editor.

It does not claim that changing order can discover a semantic component the
inventor never supplied, nor can ordering override a hard constraint that
excludes a desired solution. It makes order operator-selectable and, in
`interchangeable` mode, evolvable inside the admitted search space and nothing
more.

## Existing design references

- [Creativity goal](../creativity/goal.md).
- [Creativity search representation](../../../orchestrator/creativity_search.py).
- [Creativity evaluation composition](../../../orchestrator/creativity_evaluation.py).
- [Standalone task execution](../../../orchestrator/task_api.py).
- [Task contracts and catalogue](../../../orchestrator/tasks.py).
- [Registered prompt reply contracts](../../../orchestrator/prompt_contracts.py).
- [Prompt Router Creativity jobs](../prompt-router/adapted-kinds/milestone/).
