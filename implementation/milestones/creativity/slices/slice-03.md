# Slice 03 — Search material and categorical genomes

## Register 1 — Intent

This slice gives the later search motor a simple way to describe a possibility:
choose one alternative for each part of the operator's problem. Those parts come
from the problem itself, so the same representation can serve a literary or a
business objective. A combination can also be read back as the selected parts
and their descriptions.

The operator's objective and the accepted account of the problem stay separate
from those choices. Changing a combination must not change the facts, limits,
assumptions, unanswered questions, guidance or judging criteria, or another
combination. Two combinations are the same when they make the same choices;
different wording alone is not a new combination.

### Dependencies and non-goals

The preceding slices already supply the model-answer validator and the final
result's component format. This slice reuses both and supplies their missing
representation seam. It does not introduce another material schema or validator.

It does not build populations, select winners, measure diversity, cross or
mutate candidates, add variants, schedule model calls, or decide when to stop.
Persistence, task controls, public ordering and presentation are also outside
this slice. No product repository or runtime dependency changes.

### Risks and acceptance

The main risks are losing a condition while forming candidates, confusing
alternatives with the same identifier in different parts, and presenting text
that does not match the selected alternative. Small fixtures must demonstrate
complete combinations, unchanged problem data and faithful readable components.

These checks establish structure and preservation of accepted data. The model
can still misunderstand the original material, offer weak alternatives or give
two different alternatives the same meaning. This slice cannot prove semantic
faithfulness, feasibility or creativity, and it does not execute proposals.

## Register 2 — Pinned facts

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Delivery boundary | Add only the representation portion of one small standard-library search module, `orchestrator/creativity_search.py`, and focused tests in `orchestrator/tests/test_creativity_search.py`. Existing reply and native-result contracts are dependencies. | `implementation/milestones/creativity/skeleton.md:123-130,142,149`; `orchestrator/README.md:46`; existing preparatory boundary `orchestrator/tasks.py:911-915` | touch the new representation module and focused tests; do-not-change the skeleton, shared schemas, prompts, routing, staffing, catalogue, service routes/events/errors, runner, lifecycle, accounting, panel or granted additional roots; no population/evolution/expansion implementation |
| F2 — Accepted search material | Reuse served section `create_genes_result` through `prompt_contracts.validate(bound, reply, expected_objective=...)`; malformed model replies raise existing `contracts.ContractError`. Reply is exactly `{search_material}`; material has exactly `objective`, `context_summary`, `facts`, `constraints`, `assumptions`, `unknowns`, `dimensions`, `composition_guidance`, `criteria`. Objective exactly echoes the admitted request. Objective, summary and guidance are non-blank strings; facts/assumptions/unknowns are lists of non-blank strings; constraints/criteria contain `{id,text}`; dimensions contain `{id,meaning,variants}` with variants `{id,text}`. All objects are closed. Dimensions, criteria and each variants list are non-empty; the other lists may be empty. IDs and record text/meaning are non-blank; IDs are unique within their respective lists, with variant IDs scoped to their dimension. | `implementation/milestones/creativity/skeleton.md:124,141`; implemented validation `orchestrator/prompt_contracts.py:530-576,648,891-914,926-927` | reuse existing admission; representation consumes accepted material as trusted input; do-not-add a second validator, domain fields, ID normalization, textual-uniqueness rule or additional size ceiling |
| F3 — Genome cross-slice contract | A genome is exactly a `dimension_id -> variant_id` mapping, with one known variant for every material dimension and no other entries. Within that material, identity depends only on those pairs, independent of mapping insertion order, candidate label or descriptive text. Repeated variant IDs across dimensions remain distinct choices in their own dimensions; different IDs may carry equal text. | `implementation/milestones/creativity/skeleton.md:80-83,124,142`; existing consumer's lookup and identity `orchestrator/tasks.py:1007-1013,1042-1065` | supply complete categorical combinations and structural identity for later search consumers; do-not-introduce a candidate-ID format, domain schema, expression evaluator, semantic deduplication or population selection |
| F4 — Fixed problem and independent choices | `objective`, `context_summary`, `facts`, `constraints`, `assumptions`, `unknowns`, `composition_guidance` and `criteria` remain unchanged by representation operations and never enter the genome. Creating/projecting combinations leaves source dimensions and variants unchanged. Changing one candidate's choices or returned component records does not change accepted material or another candidate. | `implementation/milestones/creativity/skeleton.md:33-45,80-83,124,142`; existing separation of trusted dimensions from result data `orchestrator/tasks.py:975-982,1007-1013,1066`; detached-result precedent `orchestrator/tests/test_tasks.py:250-256` | own producer-side preservation and independent candidate values; do-not-police trusted callers, mutate the problem or apply expansion additions |
| F5 — Readable components cross-slice contract | A genome projects to the existing ordered `components` list: exactly `{dimension_id,dimension,variant_id,variant}` per dimension, covering every dimension once. `dimension` is that dimension's `meaning`; `variant` is the selected variant's exact `text`. The projection must fit `validate_creativity_native_result(result, *, dimensions, shortlist_size)` without changing its contract. | `implementation/milestones/creativity/skeleton.md:146`; `orchestrator/tasks.py:975-982,1042-1066` | supply readable components from the accepted material; do-not-compose terminal outcomes, invent proposal/reason/score values, impose a new component-sort requirement or change result validation |
| F6 — Guarantee and trust posture | **Strict:** F2 structural admission and F3–F5 representation/preservation, observable in T1–T4. **Best-effort:** semantic faithfulness of accepted material, feasibility and meaningful novelty. **Optimistic / eventual:** no new mechanism or delivery promise here; live routing and later checkpoint/panel delivery remain outside this slice. Provider-originated text and IDs remain data, never executable expressions. Operator, product code, standard library, admitted material structure and driver choices are trusted. | `implementation/milestones/creativity/skeleton.md:78-116,141-142,160`; trusted context `orchestrator/prompt_contracts.py:891-896`; trusted dimensions `orchestrator/tasks.py:975-982`; worker posture `orchestrator/README.md:631-634` | test this slice's own outputs; do-not-add hostile-input wrappers around driver requests/checkpoints, dependency fault injection, semantic-quality gates, sandboxing, retry, rollback or recovery |

### Acceptance criteria and tests

T1 and the existing native-result test are already implemented prerequisites.
T2–T4 are implementation obligations, not passing evidence claimed by this note.
All tests use local fixtures; no physical model call is needed.

1. **T1 — Existing `PromptContractsTest.test_create_genes_contextual_contract`**
   in `orchestrator/tests/test_prompt_contracts.py`: retain its valid minimal and
   populated material, exact-objective, closed-shape, non-empty collection and
   scoped-ID checks under generic, literature and business prompts. New search
   fixtures enter through this existing served-contract boundary; do not copy
   its negative-case matrix into a second validator's tests.
2. **T2 — `CreativitySearchTest.test_genome_representation`**: exercise the new
   producer with a singleton repertoire and a small multi-dimension repertoire.
   Its outputs satisfy F3 for every fixture choice, including a variant ID reused
   in two dimensions and equal text under different IDs. Equivalent produced
   choices retain their identity after mapping reordering; a changed selected ID
   changes identity. Tiny fixtures establish representation, not an exhaustive
   search requirement or a random-sampling policy.
3. **T3 — `CreativitySearchTest.test_problem_is_not_candidate_state`**: populate
   every fixed field, construct and project several choices, then change one
   returned candidate/component value. Verify F4 against the original accepted
   material and the other candidate. This tests ownership of produced values,
   not defenses against a hostile internal caller.
4. **T4 — `CreativitySearchTest.test_components_match_native_result_contract`**:
   observe F5's exact selected meanings/text and complete dimension coverage,
   including shared variant IDs across dimensions. Place the produced components
   in the existing valid native-result fixture and pass the existing validator.
   Retain `TaskContractsTest.test_creativity_native_result_contract`, including
   its rejection of duplicate genomes despite reversed component order.

Acceptance requires T1–T4, the existing native-result regression, and a reviewed
change scope matching F1. Run after implementation:

```sh
python3 -m unittest orchestrator.tests.test_creativity_search orchestrator.tests.test_prompt_contracts.PromptContractsTest.test_create_genes_contextual_contract orchestrator.tests.test_tasks.TaskContractsTest.test_creativity_native_result_contract
```

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator and the forthcoming population consumer need choices that retain the same problem and can be read back correctly. Without this seam, incompatible or misidentified choices can waste later evaluations or misrepresent proposals; exposure is each creativity search. Representation errors are reversible before dispatch, but later model spend is not. The reviewed slice assignment independently establishes the need; existing producer validation and terminal consumption corroborate the gap between the two. | `implementation/milestones/creativity/skeleton.md:12-29,124-125,142`; `orchestrator/prompt_contracts.py:547-576`; `orchestrator/tasks.py:1042-1065` |
| machinery | One small representation module supplies F3 combinations/identity and F5 readable components while preserving F4. These are data seams for the assigned search motor. F2 reuses the existing bound-reply API; no new parser, validation framework, service, store or dependency is needed. | `implementation/milestones/creativity/skeleton.md:124-125,142,149`; existing APIs `orchestrator/prompt_contracts.py:891-927`; `orchestrator/tasks.py:975-982` |
| consumers_touched | The new module consumes the already validated creation material. The existing native-result validator consumes dimensions and readable components and remains unchanged; T4 proves compatibility with it. The population motor is the next assigned consumer, not existing runtime code. Current code contains creation/evaluation/expansion validators and a preparatory task contract, but no running creativity driver to wire or product client to migrate in this slice. | `orchestrator/prompt_contracts.py:547-576,579-625`; `orchestrator/tasks.py:911-915,975-982,1007-1013,1042-1065`; `implementation/milestones/creativity/skeleton.md:125,129-130` |
| cheaper_alternative | Reuse the current validator and Python mappings/sets. Documentation alone cannot produce faithful components or pin producer-side preservation. Workspace and all four granted-root searches, including dependency manifests, found no reusable categorical engine: Life has planner reply contracts, Agent99 an execution envelope, and LPC/Tutor product adapters. External [DEAP's individual/toolbox model](https://deap.readthedocs.io/en/master/tutorials/basic/part1.html) was checked; adopting it adds machinery and a forbidden dependency for this small representation seam. | `orchestrator/README.md:46`; `orchestrator/tasks.py:1007-1013,1061-1065`; `/Users/siddhartha/Development/source/life/apps/life_brain/lib/life_brain/llm/structured_output/contracts.ex:29-38`; `/Users/siddhartha/Development/source/life_prod/agent_99/apps/agent_99/lib/agent_99/body/execution_contract.ex:64-80`; `/Users/siddhartha/Development/source/life_prod/life_product_components/elixir/apps/life_product_adapter_contracts/lib/life_product_adapter_contracts.ex:18-40`; `/Users/siddhartha/Development/source/life_prod/tutor/web/mix.exs:68-79` |
| cost | Build/maintenance cost is a small pure module and three focused tests; review covers two existing contracts and their connecting representation, fitting the roughly 500-line slice guidance. There is no data migration, model spend, background operation or new dependency. Omitting it shifts the same work and drift risk into population/result consumers. Before public integration the addition is readily reversible. | `WORKSPACE.md:14-30`; `implementation/milestones/creativity/skeleton.md:124-125,129-130,149`; `orchestrator/tasks.py:975-982` |
| threat_model | A provider can return malformed material; a source author can influence its text. F2's existing validator rejects bad structure and a changed objective. The new representation helpers add no raw-input boundary: F3–F5 receive accepted material and carry its text/IDs only as data, without reading references or executing text. Structural acceptance proves neither truth nor prompt-injection containment. The operator, product code, standard library and internal choices/context are trusted; no new defense checks their hypothetical self-malformation. | `orchestrator/prompt_contracts.py:547-576,891-896`; `implementation/milestones/creativity/skeleton.md:99-110,140-142,160` |
| pinned_facts | F1 fixes scope; F2 preserves the existing material schema/admission; F3 fixes genome coverage and structural identity; F4 fixes problem preservation; F5 fixes readable component compatibility; F6 limits guarantees and defenses. No internal helper signature, serialized identity format or future state machine is prescribed. | `implementation/milestones/creativity/skeleton.md:80-102,124,141-142,146,149`; `orchestrator/prompt_contracts.py:547-576`; `orchestrator/tasks.py:1042-1065` |
| verification | T1 retains actual served-contract checks. T2–T3 exercise the new producer's outputs and unchanged input data; T4 feeds produced components to the real existing consumer. Fixtures establish structural correctness without evaluating creative quality or testing Python itself. This note verifies source authorities and defines the new tests; implementation must provide their passing evidence. | existing fixtures `orchestrator/tests/test_prompt_contracts.py:189-263`; `orchestrator/tests/test_tasks.py:158-205,250-256,296-312`; assignment `implementation/milestones/creativity/skeleton.md:124,142` |
| enforceability | F2 is already enforced by exact-key, text, scoped-ID and objective comparisons in the registered validator. F3/F5 use dictionary membership/lookup and pair equality already exercised by the terminal consumer. For F4, independent returned containers holding selected IDs/text, with standard-library copying where needed, can preserve source material without caller-policing; [Python copying](https://docs.python.org/3.9/library/copy.html) and [mapping equality](https://docs.python.org/3.9/library/stdtypes.html#mapping-types-dict) provide the required primitives. The new producer still has to implement these contracts and pass T2–T4. F1 is enforced by scope review; F6 makes no mechanically unprovable semantic or delivery promise. No unexpressible guarantee was found. | `orchestrator/prompt_contracts.py:530-576,911-914`; `orchestrator/tasks.py:1007-1013,1042-1066`; existing detached-value API `orchestrator/tasks.py:471-475` and `orchestrator/kvstore.py:196-203`; its observable test `orchestrator/tests/test_tasks.py:250-256`; limits `implementation/milestones/creativity/skeleton.md:99-116` |
