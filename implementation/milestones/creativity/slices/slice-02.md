# Slice 02 — Routed semantic jobs and contracts

## Register 1 — Intent

This slice gives the creativity task three model-facing jobs: turn an operator's
problem into meaningful parts, explain and assess combinations of those parts,
and suggest more variants when exploration stalls. It supplies the instructions
and checks the shape of the answers so the later search driver can use them.
It does not run a search or make the task publicly orderable.

Each job works without a specialist prompt. Literary refinements can attend to
imagery, voice, rhythm and tension; business refinements can attend to resources,
recipients, agreements and alternative uses. Both preserve the operator's
objective and distinguish supplied conditions from assumptions. Evaluators must
interpret the supplied combination faithfully; expansion offers alternatives
within the existing dimensions. All three jobs ask for exploration without
editing files or acting on proposals.

### Dependencies and non-goals

The slice extends the existing prompt store, router, renderer and registered
answer validators. The preceding slice supplies the job vocabulary and task
contracts; the new answers must remain compatible with that representation.
The owning session already supplies material selection. Connecting these jobs
to physical model calls belongs to the later driver work.

Population construction, selection, mutation, evaluation scheduling, staffing
changes, persistence, task controls, accounting and presentation are outside
this slice. It adds no library, prompt service, domain classifier or parallel
validation framework, and changes no product repository.

### Risks and guarantee limits

An older saved prompt set may lack the newly required documents and therefore
use the existing complete-set fallback. Its custom text can stop being served
until the operator completes that set; the saved files are preserved. The
shared prompt consumers need regression coverage for this consequence.

Answer structure is enforceable; understanding, feasibility and creative merit
remain model judgments. Prompt edits retain ordinary live-read behavior, without
a transaction across authorities. The instructions prohibit outside action, but
the existing worker access model does not provide containment or restoration of
effects from a disobedient worker.

## Register 2 — Pinned facts

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Delivery boundary | Preparatory routing, prompt content and contextual reply contracts only. Existing jobs retain their contracts; this slice does not admit or dispatch the `creativity` TaskExecutor. | `implementation/milestones/creativity/skeleton.md:122-130,149`; current preparatory boundary `orchestrator/tasks.py:911-915` | touch `orchestrator/prompt_router.py`, `orchestrator/prompt_sets.py`, `orchestrator/prompt_contracts.py`, `orchestrator/prompt_set_seed.py`, the canonical corpus under `implementation/brainstorming/prompt-router/adapted-kinds/`, and focused tests; do-not-change task catalogue, service routes/events/errors, staffing, runner policy, lifecycle, panel or any granted additional root |
| F2 — Direct jobs and supplied content | `executor="agent_call"`: `create_genes@creativity` → kind `create_genes`; `evaluate_candidates@creativity` → `evaluate_candidates`; `expand_genes@creativity` → `expand_genes`. Creation receives the admitted objective, context and ordered reference paths. Evaluation receives the immutable compact problem, criteria and an unlabeled candidate batch, without historical scores or prestige. Expansion receives the original objective, complete search material, promising valid candidates without historical scores or prestige, and a compact explored account. | `implementation/milestones/creativity/skeleton.md:47-54,140`; direct-route seam `orchestrator/prompt_router.py:28-44,97-118`; existing renderer `orchestrator/prompt_router.py:550-592` | extend the direct route/canonical kind inventory and declared prompt inputs; do-not-build caller prompt prose or define candidate-generation/dispatch behavior here |
| F3 — Complete prompts and material layers | All three jobs have complete generic instructions and their own F5–F7 output contract. The default corpus and seed supply additive `material_layers[job][material]` entries for `literature` and `business` for every job. Refinements retain the same objective and machine result schema; an absent layer, including an unknown material name, uses the generic base. Every served default variant instructs workers to read material and return search data/proposals without editing files or executing proposals. | `implementation/milestones/creativity/skeleton.md:104-110,140`; semantic content `implementation/milestones/creativity/goal.md:40-61,70-77,137-147`; additive assembly `orchestrator/prompt_router.py:336-338,388-415` | touch generic prompts and additive material instructions; do-not-add domain schemas, automatic classification, model names, prose-quality enforcement on operator edits or a second prompt assembly path |
| F4 — Whole-set and live resolution | **Strict per resolution:** canonical documents, seed and fresh default installation agree; selection serves one complete requested set, otherwise stored default, otherwise seed, never mixed members. Existing `prompt_set_fallback` stays `None`, `stored_default` or `in_code_seed` as applicable. Missing new members make an older set incomplete; no automatic repair of stored sets. **Optimistic freshness:** subsequent resolution reads completed edits afresh; existing answers stay unchanged. Material remains the live owning-session value, with `default` when absent; no new material channel. Per-physical-call placement is a later integration obligation, not delivery here. | `implementation/milestones/creativity/skeleton.md:91-96,123,127,140`; `orchestrator/prompt_sets.py:50-60,507-580`; `orchestrator/prompt_router.py:464-500`; `orchestrator/staffing.py:1767-1779` | extend required corpus membership; retain store/fallback and material authority; do-not-add migrations, transactions, cache, versions, snapshots or prompt-edit rebaseline tracking |
| F5 — Creation reply | Exactly `{search_material}`. That object has exactly `objective`, `context_summary`, `facts`, `constraints`, `assumptions`, `unknowns`, `dimensions`, `composition_guidance`, `criteria`. `objective`, `context_summary` and `composition_guidance` are non-empty strings; `objective` exactly echoes the admitted objective. Facts, assumptions and unknowns are possibly empty lists of non-empty strings. Constraints and criteria are lists of exactly `{id,text}` objects; dimensions is a list of exactly `{id,meaning,variants}` objects, each with a variants list of exactly `{id,text}` objects. Dimensions, criteria and each dimension's variants are non-empty; constraints may be empty. Throughout F5–F7, objects are closed; every ID and every `text`, `meaning`, `proposal` and `reason` value is a non-blank string. IDs are unique within each constraint/criterion/dimension list and each dimension's variant list. | `implementation/milestones/creativity/skeleton.md:80-83,141`; compact-content intent `implementation/milestones/creativity/goal.md:40-61`; exact-key/text seam `orchestrator/prompt_contracts.py:42-52,114-118` | add the creation reply validator and matching prompt contract; do-not-rewrite the objective, impose domain-specific dimensions or introduce a second search-material schema in later consumers |
| F6 — Evaluation reply | Exactly `{evaluations}`: a list containing exactly one `{candidate_id,proposal,constraint_valid,constraint_violations,reason,assumptions,score}` per supplied candidate ID, with no duplicates, omissions or extras; reply order is immaterial. `constraint_valid` is boolean; `constraint_violations` lists unique supplied constraint IDs and is empty exactly when valid. Assumptions are a possibly empty list of non-empty strings. Score is a finite number in `[0,1]`, excluding booleans. Both valid and invalid evaluations are legitimate replies; score never changes the reported validity. | `implementation/milestones/creativity/skeleton.md:141-142`; violation meaning `implementation/milestones/creativity/goal.md:70-77`; contextual coverage precedent `orchestrator/contracts.py:1014-1025`; existing score/assumption contract `orchestrator/tasks.py:1023-1040` | add the batch reply validator and matching prompt contract; do-not-select candidates, reject an honestly invalid evaluation as malformed, normalize scores or promise semantic validity |
| F7 — Expansion reply | Exactly `{additions}`: a possibly empty list of exactly `{dimension_id,variants}` entries, each naming an existing dimension once and containing a non-empty list of exactly `{id,text,reason}` variants. Variant IDs are new within that dimension and unique within the reply for it. Empty `additions` is accepted. Adding or renaming dimensions, changing existing variants and extra fields are outside the reply contract. Textual or semantic novelty is not proved by a new ID. | `implementation/milestones/creativity/skeleton.md:39-45,99-102,141`; contextual validation seam `orchestrator/prompt_contracts.py:790-807`; trusted dimension representation `orchestrator/tasks.py:975-982,1007-1013` | add the expansion reply validator and matching prompt contract; do-not-apply additions, choose exhaustion/stop reasons or add semantic deduplication here |
| F8 — Registered validation seam | New section IDs are `create_genes_result`, `evaluate_candidates_result`, `expand_genes_result`, each bound to its matching kind. Extend `prompt_contracts.validate` with optional keyword context `expected_objective`, `candidate_ids`, `constraint_ids`, `dimensions`: creation uses the objective; evaluation uses the two ID collections; expansion uses the existing search-material dimension list. Relevant context comes from the trusted caller. A valid reply is returned; violations raise existing `contracts.ContractError`. Bind obligations from the served prompt; unknown stored section IDs retain their existing data-only meaning. No `status`, `kind` or `questions` envelope is added to F5–F7. | slice assignment and closed replies `implementation/milestones/creativity/skeleton.md:123,141`; registry/binding/API `orchestrator/prompt_contracts.py:530-550,696-711,783-820`; contextual caller precedent `orchestrator/judgment_calls.py:527-540` | extend the existing registry/API; preserve other kinds and call signatures; do-not-revalidate driver-emitted requests/context, validate a reply with an unserved contract, or add a parallel error vocabulary/framework |
| F9 — Proof and trust limits | **Strict:** F2–F3 shipped route/content obligations, F4 whole-set behavior and F5–F8 structural/contextual checks. **Optimistic:** F4 live authority reads, without a cross-authority transaction. **Best-effort:** semantic faithfulness, feasibility, calibration, creative quality and meaningful novelty; scores are evaluations, not probabilities. Exploration-only worker compliance retains the existing full-access trust posture. No eventual delivery, provider exactly-once, sandboxing or rollback guarantee is introduced. | `implementation/milestones/creativity/skeleton.md:78-116`; trusted prompt authoring `orchestrator/prompt_sets.py:3-10`; worker access `orchestrator/README.md:631-634`; existing correction allowance `orchestrator/runners.py:2982-3019` | test structural contracts and rendered instructions; do-not-add worker-effect containment, automatic retry/recovery, semantic-quality gates or defenses around trusted operator/product/compile-time inputs |

### Acceptance criteria and tests

The following new tests are implementation obligations, not claimed passing
evidence from this draft. T1–T5 operate on the served corpus through the existing
router, renderer and bound-validator APIs; no provider call is required.

1. **T1 — `PromptRouterTest.test_creativity_jobs_and_materials`**, in
   `orchestrator/tests/test_prompt_router.py`: resolve/render every F2 job with
   generic, literary, business and unknown material. Check supplied content and
   reference order, additive refinements, the matching F8 section and the shared
   reply shape. Review rendered fixtures for the substantive F3 instructions;
   a string-presence assertion alone does not establish prompt completeness.
2. **T2 — `PromptRouterTest.test_creativity_live_whole_set_resolution`**, in the
   same module: exercise complete named/default/seed sets, an old set missing a
   new member, and completed edits between resolutions. Check F4 fallback
   evidence, unmixed answers, unchanged stored bytes and the next resolved text.
3. **T3 — `PromptContractsTest.test_create_genes_contextual_contract`**, in
   `orchestrator/tests/test_prompt_contracts.py`: accept a minimal valid F5 reply
   including empty descriptive lists/constraints; reject changed objectives,
   missing/extra keys, wrong types, blank text, duplicate IDs and empty required
   collections. Reusing a variant ID in different dimensions remains valid.
4. **T4 — `PromptContractsTest.test_evaluate_candidates_contextual_contract`**,
   in the same module: accept reordered exact coverage and honestly invalid
   candidates, including a high-scoring invalid candidate. Reject malformed
   records, duplicate/missing/extra candidates, unknown or duplicate violation
   IDs, inconsistent validity, and boolean/non-finite/out-of-range scores.
5. **T5 — `PromptContractsTest.test_expand_genes_contextual_contract`**, in the
   same module: accept empty additions and valid additions; reject unknown or
   duplicate dimensions, reused/duplicate variant IDs, empty variant groups,
   changed shapes and blank required text. F5–F7 use the same positive and
   negative reply fixtures under generic and both shipped material layers.
6. **T6 — Existing corpus/registry regressions:** retain
   `PromptSetStoreTest.test_shipped_corpus_and_seed_are_equivalent` and
   `PromptContractsTest.test_shipped_contract_section_registry_is_complete`,
   along with the existing whole-set, freshness and legacy-kind tests. The
   expanded corpus must preserve the contracts of existing shared consumers.

Acceptance requires T1–T6, review of the rendered generic and material prompts,
and a change scope matching F1. Run the focused modules after implementation:

```sh
python3 -m unittest orchestrator.tests.test_prompt_sets orchestrator.tests.test_prompt_router orchestrator.tests.test_prompt_contracts
```

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator and later search driver need usable, attributable semantic answers. Without these jobs, every creative run lacks a routed instruction/answer boundary; accepting changed objectives, missing evaluations or invalid references would waste model spend or make results unusable. Draft proposals and prompt edits are reversible; spent calls are not. The reviewed assignment establishes need, independently corroborated by the current route and section registries lacking these jobs. | `implementation/milestones/creativity/skeleton.md:12-29,123,140-141`; `orchestrator/prompt_router.py:28-44`; `orchestrator/prompt_contracts.py:530-550` |
| machinery | Extend direct routes/canonical membership, three generic prompt documents with six additive refinements, the seed and three registered contextual validators. The first supplies selectable instructions, the second domain-sensitive guidance without another engine, and the third machine-usable replies. Context keywords extend an existing API. No new module, dependency, dispatch adapter or store is required. | `implementation/milestones/creativity/skeleton.md:123,140-141,149`; `orchestrator/prompt_sets.py:50-54,358-395`; `orchestrator/prompt_contracts.py:790-807` |
| consumers_touched | Existing author, judgment and session call adapters consume the shared resolver/binder and are exposed to expanded-set fallback, although their code need not change. Creativity's driver is a later consumer, not runnable delivery here; the existing native-result contract already consumes the dimension/variant representation. Searches across all four granted roots found no creativity-job or task/staffing API consumer to migrate. | `orchestrator/author_calls.py:228-250,257-269`; `orchestrator/judgment_calls.py:499-539`; `orchestrator/session_calls.py:630-668`; `orchestrator/tasks.py:975-982,1007-1013`; `implementation/milestones/creativity/skeleton.md:127-130` |
| cheaper_alternative | Reuse the existing router, renderer and contextual validator registry. Documentation/configuration alone cannot register executable reply checks. External [jsonschema validation](https://python-jsonschema.readthedocs.io/en/stable/validate/) was checked: it would add a dependency while job/context binding remains local work. Granted-root searches found Life's planner contracts, Agent99's text/artifact envelope and LPC/Tutor's product adapters, not a reusable implementation of these Python jobs. | `orchestrator/README.md:46`; `orchestrator/prompt_router.py:464-500,550-592`; `orchestrator/prompt_contracts.py:783-807`; `/Users/siddhartha/Development/source/life/apps/life_brain/lib/life_brain/llm/structured_output/contracts.ex:29-38`; `/Users/siddhartha/Development/source/life_prod/agent_99/apps/agent_99/lib/agent_99/body/execution_contract.ex:64-80`; `/Users/siddhartha/Development/source/life_prod/life_product_components/elixir/apps/life_product_adapter_contracts/lib/life_product_adapter_contracts.ex:18-30`; `/Users/siddhartha/Development/source/life_prod/tutor/web/mix.exs:68-79` |
| cost | Build/review cost is three prompt/validator pairs, six short refinements and focused fixtures, aiming at the repository's roughly 500-line slice guidance excluding mechanical seed/render copies. No task-data migration or model spend is introduced. Operators may complete old prompt sets to restore their custom selection; no automatic migration is promised. Maintenance stays with existing prompt/contract owners. Omission blocks later jobs or pressures callers to duplicate them; this preparatory change is reversible before public activation. | `WORKSPACE.md:14-30`; `implementation/milestones/creativity/skeleton.md:123,130`; `orchestrator/prompt_sets.py:507-580` |
| threat_model | A third-party source author can control reference text, and a provider can return malformed or misleading replies. F5–F8 reject malformed structures and context mismatches; prompts ask that source material remain evidence under the operator's objective. This does not contain prompt injection or worker tool effects. The authorized operator, product code, prompt/staffing documents, compiled seed and driver-provided validation context are trusted. No new checks police their hypothetical self-malformation. | `implementation/milestones/creativity/skeleton.md:99-110,140-141,160`; `orchestrator/prompt_sets.py:8-10`; provider-validation boundary `orchestrator/runners.py:3438-3444` |
| pinned_facts | F1 pins scope; F2–F4 pin routing, served content and resolution semantics; F5–F7 complete the closed cross-slice replies; F8 names the registered sections and context API; F9 limits the guarantees. These facts and their tests stay in the hard register. | `implementation/milestones/creativity/skeleton.md:78-116,123,140-141,149`; existing API `orchestrator/prompt_contracts.py:790-820` |
| verification | T1–T2 observe actual assembled/rendered prompts and fallback; T3–T5 exercise provider reply fixtures against served contracts and valid caller context. T6 retains producer-owned corpus/registry coverage and existing consumers. Prompt-content review checks the three jobs' meaning without inventing a creativity benchmark. This draft verifies source authorities and specifies tests; implementation supplies the new passing evidence. | existing fixture seams `orchestrator/tests/test_prompt_router.py:56-78,878-909`; corpus proof `orchestrator/tests/test_prompt_sets.py:67-84,250-308`; registry/context proof `orchestrator/tests/test_prompt_contracts.py:76-97,506-521` |
| enforceability | F2–F3 use existing direct resolution, declared substitution, rendering and additive layers. F4 uses fresh whole-set loading/fallback and the existing session material API. F5–F8 add callbacks to the existing bound-section/context API: exact keys/types/text, numeric ranges and contextual ID comparison express every structural invariant. These callbacks are work to implement, not pre-existing validation. F1 is a scope check. F9's semantic judgments and worker effects have no mechanical proof and are not strict promises. No unexpressible guarantee is asserted. | `orchestrator/prompt_router.py:97-118,336-415,464-500,539-547`; `orchestrator/prompt_sets.py:507-580`; `orchestrator/staffing.py:1767-1779`; `orchestrator/prompt_contracts.py:42-52,114-118,783-820`; `orchestrator/contracts.py:115-124,1014-1025`; range precedent `orchestrator/tasks.py:1034-1040`; limits `implementation/milestones/creativity/skeleton.md:99-116` |
